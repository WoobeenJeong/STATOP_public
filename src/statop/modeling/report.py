"""S194c B6 출력 + 에이전트 스니펫 — 모듈 B 감사를 한 장으로.

감사를 여러 명령으로 나눠 돌고 나면 **무엇이 걸렸는지 한눈에 볼 자리**가 없다. 여기서
전부 모아 한 장으로 낸다: 구성(B1) → 누수 → 비율·손실 → 균형·분포 → 전처리 →
평가 → 모델특유 → 지표 변경·재현성 → 3-metric 트리아드.

**스니펫은 이 감사를 그대로 재현하는 명령 묶음이다** ( 와 같은 규칙). 사람이 읽고
붙여 쓸 수 있어야 하고, 무엇을 전제로 봤는지가 빠지면 안 된다 — 재현되지 않는 스니펫은
안 주느니만 못하다.

**감사 전용이다.** 학습을 돌리지 않는다.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from statop.messages import msg


@dataclass
class ModelReport:
    session_id: str
    spec: dict | None = None
    notes: list = field(default_factory=list)      # B1 구성 확인 요약
    problems: list = field(default_factory=list)
    findings: list = field(default_factory=list)   # 모든 감사 결과 (LeakFinding)
    triad: dict | None = None
    snippet: str = ""

    @property
    def gates(self) -> list:
        return [f for f in self.findings
                if f.verdict == "fail" and f.grade.split("/")[0] == "Gate"]

    @property
    def diagnostics(self) -> list:
        return [f for f in self.findings
                if f.verdict == "fail" and f.grade.split("/")[0] != "Gate"]

    @property
    def skipped(self) -> list:
        return [f for f in self.findings if f.verdict == "skipped"]


def collect(session_file: str, source_path: str | None = None,
            key: str | None = None, expected_ratio: dict | None = None,
            meta_cols: list[str] | None = None,
            sample_n: int = 50_000) -> ModelReport:
    """감사를 전부 돌려 한 자리에 모은다 — 하나가 실패해도 나머지는 돈다."""
    from statop.modeling import balance, evaluate, leak, prep, repro, specific, triad
    from statop.modeling.spec import build, current
    from statop.modeling.split_audit import run_all as split_all
    from statop.session.core import load_session, main_source

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("mb_need_spec"))
    doc = load_session(session_file)
    src = main_source(doc)
    if not source_path:
        source_path = src["path"] if src else None

    checked = build(spec)
    rep = ModelReport(session_id=doc["session_id"], spec=spec.as_dict(),
                      notes=list(checked.notes), problems=list(checked.problems))

    held = []
    if src:
        from statop.session.core import replay

        held = replay(doc)["held"].get(src["id"], [])

    for fn in (lambda: leak.run_all(spec, sample_n),
               lambda: split_all(spec, source_path, key, expected_ratio,
                                 meta_cols, sample_n),
               lambda: balance.run_all(spec, meta_cols or held, sample_n),
               lambda: prep.run_all(spec, sample_n),
               lambda: evaluate.run_all(spec, session_file, sample_n),
               lambda: specific.run_all(spec, sample_n),
               lambda: repro.run_all(spec, session_file),
               lambda: [triad.recommend(spec, sample_n)]):
        try:
            rep.findings += fn()
        except (ValueError, OSError, KeyError) as e:
            rep.findings.append(leak.skip("MB-C14", str(e)))

    t = next((f for f in rep.findings if f.id == "MB-C24"), None)
    if t is not None and t.numbers.get("goal"):
        rep.triad = {k: t.numbers[k] for k in ("question", "goal", "support",
                                               "guardrail")}
    rep.snippet = snippet(session_file, spec, source_path, key, expected_ratio,
                          meta_cols or held)
    return rep


def snippet(session_file: str, spec, source_path: str | None,  # noqa: ANN001
            key: str | None, expected_ratio: dict | None,
            meta_cols: list[str] | None) -> str:
    """이 감사를 **그대로 다시 돌리는** 명령 묶음 ( 와 같은 규칙).

    구성(`model plan`)에 무엇을 적었는지가 판정의 전제다 — 그것이 빠지면 같은 명령을
    돌려도 다른 결과가 나온다. 그래서 **적어 둔 필드를 전부 되살린다.**
    """
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    lines = [msg("mb_snippet_head")]
    if source_path:
        lines.append(f"statop session new --data {source_path}")

    # 확률 컬럼은 **확정돼 있어야** 평가 감사가 열린다
    if src:
        for col, t in (replay(doc)["semantic_types"].get(src["id"], {}) or {}).items():
            if t == "probability":
                lines.append(f"statop types --confirm {col} --as probability")

    plan = ["statop model plan", f"--question {spec.question}", f"--tier {spec.tier}",
            f"--label {spec.label_column}"]
    for flag, val in (("--positive", spec.positive_class), ("--score", spec.score_column),
                      ("--validation", spec.validation), ("--k", spec.k),
                      ("--group-col", spec.group_column), ("--time-col", spec.time_column),
                      ("--family", spec.model_family), ("--scaling", spec.scaling),
                      ("--reduction", spec.reduction), ("--class-weight", spec.class_weight),
                      ("--threshold", spec.threshold), ("--averaging", spec.averaging),
                      ("--metric", spec.metric), ("--importance", spec.importance),
                      ("--environment", spec.environment), ("--seed", spec.seed)):
        if val not in (None, ""):
            plan.append(f"{flag} {val}" if " " not in str(val)
                        else f"{flag} '{val}'")
    for role, path in spec.sets.items():
        plan.append(f"--{role} {path}")
    if spec.fold_scores:
        plan.append("--fold-scores " + ",".join(f"{x:g}" for x in spec.fold_scores))
    plan.append("--apply")
    lines.append(" ".join(plan))

    split = "statop model split"
    if key:
        split += f" --key {key}"
    if expected_ratio:
        split += " --expect " + ",".join(f"{k}={v:g}" for k, v in expected_ratio.items())
    lines += ["statop model leak", split]
    bal = "statop model balance"
    if meta_cols:
        bal += " --meta " + ",".join(meta_cols)
    lines += [bal, "statop model prep", "statop model eval", "statop model specific",
              "statop model repro", "statop model labels"]
    lines.append(msg("mb_snippet_tail"))
    return "\n".join(lines) + "\n"


def to_markdown(rep: ModelReport) -> str:
    out = [f"# {msg('mb_report_title')}", "",
           f"- {msg('mb_report_session', id=rep.session_id)}"]
    if rep.spec:
        out.append(f"- {msg('mb_report_spec', q=rep.spec['question'], t=rep.spec['tier'], v=rep.spec['validation'])}")
    out += ["", f"## {msg('mb_report_summary')}", "",
            f"- {msg('mb_report_counts', gate=len(rep.gates), diag=len(rep.diagnostics), skip=len(rep.skipped))}"]
    if rep.gates:
        out.append(f"- **{msg('mb_leak_blocked', n=len(rep.gates))}**")
    out += ["", f"> {msg('mb_scope_note')}", f"> {msg('mb_scope_why')}"]

    if rep.triad:
        out += ["", f"## {msg('mb_report_triad')}", "",
                f"| | {msg('mb_report_what')} |", "|---|---|",
                f"| Goal | {rep.triad['goal']} |",
                f"| Support | {rep.triad['support']} |",
                f"| Guardrail | {rep.triad['guardrail']} |", "",
                f"*{msg('mb_report_triad_basis', q=rep.triad['question'])}*"]

    out += ["", f"## {msg('mb_report_findings')}", ""]
    mark = {"fail": "⛔", "pass": "✅", "skipped": "○"}
    for f in rep.findings:
        icon = ("⚠" if f.verdict == "fail" and f.grade.split("/")[0] != "Gate"
                else mark[f.verdict])
        out.append(f"### {icon} {f.id} — {f.summary}")
        out += [f"- {d}" for d in f.detail]
        if f.action:
            out.append(f"- → *{f.action}*")
        out.append("")

    out += [f"## {msg('mb_report_snippet')}", "",
            f"*{msg('mb_report_snippet_note')}*", "", "```bash", rep.snippet.rstrip(),
            "```", ""]
    return "\n".join(out)


def to_json(rep: ModelReport) -> str:
    from dataclasses import asdict

    body = {"session_id": rep.session_id, "spec": rep.spec, "notes": rep.notes,
            "problems": rep.problems, "triad": rep.triad, "snippet": rep.snippet,
            "counts": {"gate": len(rep.gates), "diagnostic": len(rep.diagnostics),
                       "skipped": len(rep.skipped)},
            "scope_note": msg("mb_scope_note"), "scope_why": msg("mb_scope_why"),
            "findings": [asdict(f) for f in rep.findings]}
    return json.dumps(body, ensure_ascii=False, indent=1, default=str)


FORMATS = {"md": to_markdown, "json": to_json}


def write(session_file: str, out_path: str, fmt: str | None = None, **kw) -> Path:
    p = Path(out_path)
    fmt = fmt or p.suffix.lstrip(".").lower() or "md"
    if fmt not in FORMATS:
        raise ValueError(msg("report_bad_format", allowed="|".join(FORMATS), fmt=fmt))
    p.write_text(FORMATS[fmt](collect(session_file, **kw)), encoding="utf-8")
    return p
