"""A5 —  가설 재작성 ·  3-metric 구성 + 에이전트 스니펫.

기계 가설(A7)은 **검정 하나**를 말한다. A5 는 거기에 Goal/Support/Guardrail 을 엮어
"무엇으로 재고, 무엇으로 보조 확인하고, 무엇이 무너지면 안 되는가"를 한 문단으로 만든다.

템플릿 우선이다 — LLM 은 이 결과가 마음에 안 들 때만 부른다 .
"""

from dataclasses import dataclass, field

from statop.messages import msg


@dataclass
class Rewritten:
    statement: str = ""                       # 재작성된 가설 한 문단
    goal: str = ""
    support: list = field(default_factory=list)
    guardrail: list = field(default_factory=list)
    cautions: list = field(default_factory=list)
    triad: dict | None = None
    snippet: str = ""                         #  에이전트 스니펫


def _label(sug) -> str:  # noqa: ANN001
    return f"{sug.id} {sug.name}"


def build(session_file: str, sample_n: int = 10_000) -> Rewritten:
    """S173 — 검정 결과 + 병기 지표를 한 문단으로 다시 쓴다."""
    from statop.analyze.metrics import apply_choices, suggest
    from statop.hypothesis.mech import build_report

    panel = apply_choices(suggest(session_file, sample_n))
    rep = build_report(session_file)
    g = panel.goal

    # 사용자가 고른 것이 있으면 그것만, 없으면 추천 전부를 엮는다
    def pick(items):  # noqa: ANN001, ANN202
        chosen = [s for s in items if s.chosen]
        return chosen or items

    sup, gr = pick(panel.support), pick(panel.guardrail)
    out = Rewritten(
        goal=msg("a5_goal", name=g.get("name") or g.get("test"),
                 eff=g.get("effect") or "?",
                 val=g.get("value") if g.get("value") is not None else float("nan")),
        support=[_label(s) for s in sup], guardrail=[_label(s) for s in gr],
        cautions=list(rep.cautions), triad=panel.triad)

    base = rep.proposals[0].statement if rep.proposals else ""
    parts = [base]
    if sup:
        parts.append(msg("a5_with_support", items=" · ".join(out.support)))
    if gr:
        parts.append(msg("a5_with_guardrail", items=" · ".join(out.guardrail)))
    if rep.cautions:
        parts.append(msg("a5_with_caution", n=len(rep.cautions), first=rep.cautions[0]))
    out.statement = " ".join(p for p in parts if p)
    out.snippet = snippet(session_file, out, sample_n)
    return out


def snippet(session_file: str, r: Rewritten, sample_n: int = 10_000) -> str:
    """S174 — 이 분석을 **그대로 재현**하는 명령 묶음.

    사람이 읽고 붙여 쓸 수 있어야 하고, 무엇을 뺐는지·무엇을 채웠는지가 빠지면 안 된다.
    재현되지 않는 스니펫은 안 주느니만 못하다.
    """
    from statop.analyze.spec import current
    from statop.session.core import load_session, main_source, replay

    spec = current(session_file)
    if spec is None:
        return ""
    doc = load_session(session_file)
    st = replay(doc)
    src = main_source(doc)

    # 세션부터 만들어야 나머지 명령이 걸린다. open 은 진단용이라 세션을 만들지 않는다
    lines = [msg("a5_snippet_head"), f"statop session new --data {src['path']}"]
    sel = st["selected"].get(src["id"], [])
    if sel:
        lines.append(f"statop select {src['path']} --cols {','.join(sel)}")
    for col, t in (st["semantic_types"].get(src["id"], {}) or {}).items():
        lines.append(f"statop types --confirm {col} --as '{t}'")
    for d in st["derived"]:
        eps = f" --eps {d['eps']:g}" if d.get("eps") is not None else ""
        lines.append(f"statop derive --name {d['name']} --expr '{d['expr']}'{eps} --apply")
    for m in st["missing_ops"]:
        if m["op"] == "impute":
            lines.append(f"statop missing impute --method {m['method']} "
                         f"--cols {','.join(m.get('cols') or [])} --apply")
    for e in st["excluded"]:
        # 주석으로만 적으면 이 스니펫을 돌린 사람은 다른 행 수로 다른 값을 얻는다
        note = (e.get("note") or "-").replace("'", "’")
        lines.append(f"statop exclude --key-column {e['key_column']} --key {e['key']} "
                     f"--note '{note}'")

    plan = [f"statop analyze plan --question {spec.question} --y {spec.y}"]
    for flag, val in (("--group", spec.group), ("--by", spec.by),
                      ("--event", spec.event), ("--subject", spec.subject),
                      ("--weights", spec.weights), ("--control", spec.control)):
        if val:
            plan.append(f"{flag} {val}")
    plan.append(f"--n-tests {spec.n_tests} --apply")
    lines.append(" ".join(plan))

    results = st["test_results"]
    if results:
        lines.append(f"statop analyze run --test {results[-1]['test']}")
    lines.append("statop metrics")
    if r.guardrail:
        lines.append(f"# {msg('a5_snippet_guardrail', items=' · '.join(r.guardrail))}")
    return "\n".join(lines)
