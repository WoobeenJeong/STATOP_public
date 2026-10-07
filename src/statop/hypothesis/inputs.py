"""프롬프트 입력 채우기  — 세션에서 **요약치만** 모은다.

유형(analysis | modeling)만 정해져 있으면 [ask] 클릭 하나로 돌아야 한다. 사용자가
무엇을 적어 넣을 일이 없어야 하므로, 여기서 세션 기록을 전부 훑어 자리를 채운다.

**원자료(셀 값)는 한 칸도 넣지 않는다** — 넣는 값은 판정·개수·요약뿐이다 (요구사항3절).
채우지 못한 자리는 지어내지 않고 `not recorded` 로 둔다.

값은 전부 영문이다 (registry-prompts 0절) — 한영 변환에서 통계 용어의 뜻이 흔들린다.
판정 문구도 마찬가지라, 입력을 모으는 동안만 **메시지 언어를 영어로 바꾼다**. 화면에
보이는 한국어와 모델에게 보내는 영어가 같은 메시지 카탈로그에서 나오므로, 문구를
두 벌 쓸 필요가 없다.
"""

import os
from contextlib import contextmanager

NONE = "not recorded"
NOTHING = "none"


@contextmanager
def english():
    """이 블록 안에서 만들어지는 판정 문구는 영어로 나온다 (STATOP_LANG)."""
    before = os.environ.get("STATOP_LANG")
    os.environ["STATOP_LANG"] = "en"
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("STATOP_LANG", None)
        else:
            os.environ["STATOP_LANG"] = before


def _join(items, sep: str = "; ") -> str:
    items = [str(x) for x in items if x]
    return sep.join(items) if items else NOTHING


def _num(v, fmt: str = ".3g") -> str:
    return format(v, fmt) if isinstance(v, (int, float)) else NONE


def family_for(session_file: str) -> str:
    """무엇을 물을 자리인가 — 모델 구성이 있으면 modeling, 검정이 있으면 analysis.

    **둘 다 없으면 물을 것이 없다.** 지어내지 않고 실패한다.
    """
    from statop.analyze.spec import current as a_current
    from statop.modeling.spec import current as b_current
    from statop.session.core import load_session, replay

    st = replay(load_session(session_file))
    if b_current(session_file) is not None:
        return "modeling"
    if st["test_results"] or a_current(session_file) is not None:
        return "analysis"
    from statop.messages import msg

    raise ValueError(msg("qwen_nothing_to_ask"))


# ── analysis (모듈 A) ───────────────────────────────────────
def analysis_values(session_file: str, opinion: str = "") -> dict:
    from statop.analyze.spec import current, questions
    from statop.hypothesis.mech import build_report
    from statop.session.core import load_session, main_source, replay

    rep = build_report(session_file)
    b = rep.basis
    spec = current(session_file)
    doc = load_session(session_file)
    st, src = replay(doc), main_source(doc)
    sid = src["id"] if src else ""
    types = st["semantic_types"].get(sid, {})
    eff = b.get("effect") or {}

    derived = [d for d in st["derived"] if d.get("source") == sid]
    excl = st["excluded"]
    miss = st["missing_ops"]
    groups = [g for g in st.get("group_confirms", [])] if st.get("group_confirms") else []

    # 무엇을 **보지 않았는지**도 넣는다 — 못 본 것을 근거로 읽으면 안 된다
    unchecked = []
    if not st["test_results"]:
        unchecked.append("no test has been run")
    missing_types = [c for c in (st["selected"].get(sid) or []) if c not in types]
    if missing_types:
        unchecked.append(f"semantic type not confirmed for {len(missing_types)} columns")
    if not groups:
        unchecked.append("group structure not confirmed")

    return {
        "question": spec.question if spec else NONE,
        "question_text": next((q["question"] for q in questions()
                               if spec and q["id"] == spec.question), NONE),
        "y": spec.y if spec else NONE,
        "y_type": types.get(spec.y, NONE) if spec else NONE,
        "x": (f"{spec.group} (semantic type: {types.get(spec.group, NONE)})"
              if spec and spec.group else NOTHING),
        "transforms": _join(f"{d['name']} = {d['expr']}" for d in derived),
        "groups": _join(f"{g.get('column')} ({g.get('kind')})" for g in groups),
        "n_tests": spec.n_tests if spec else NONE,
        "alpha": _num(b.get("alpha_adjusted", 0.05)),
        "test": f"{b.get('test', NONE)} {b.get('name', '')}".strip(),
        "statistic": _num(b.get("statistic"), ".4g"),
        "p": _num(b.get("p")),
        "effect_name": eff.get("name", NONE),
        "effect_value": _num(eff.get("value")),
        "ci": (f"(95% CI {_num(eff.get('ci_low'))} to {_num(eff.get('ci_high'))})"
               if eff.get("ci_low") is not None else ""),
        "n_detail": _join((f"{k}={v}" for k, v in (b.get("n") or {}).items()), " "),
        "assumptions": _join(rep.assumptions if hasattr(rep, "assumptions") else [], "\n- "),
        "guardrail": _join(rep.guardrail, "\n- "),
        "excluded": (f"{len(excl)} rows excluded, each with a recorded reason"
                     if excl else NOTHING),
        "missing": _join(f"{m['op']}: {m.get('method', '')}".strip() for m in miss),
        "not_checked": _join(unchecked, "\n- "),
        "opinion": opinion or NOTHING,
    }


# ── modeling (모듈 B) ───────────────────────────────────────
def modeling_values(session_file: str, opinion: str = "",
                    sample_n: int = 50_000) -> dict:
    from statop.modeling.report import collect
    from statop.modeling.spec import current, questions

    spec = current(session_file)
    rep = collect(session_file, sample_n=sample_n)
    t = rep.triad or {}

    def line(f) -> str:  # noqa: ANN001
        return f"{f.id}: {f.summary}"

    return {
        "question": spec.question,
        "question_text": next((q["question"] for q in questions()
                               if q["id"] == spec.question), NONE),
        "tier": spec.tier,
        "family": spec.model_family or NONE,
        "validation": f"{spec.validation}" + (f" (k={spec.k})" if spec.k else ""),
        "sets": _join(f"{r}={_rows(p, sample_n):,} rows"
                      for r, p in spec.sets.items()),
        "label": spec.label_column or NONE,
        "positive": spec.positive_class or NONE,
        "balance": _balance_text(rep),
        "scaling": spec.scaling or NONE,
        "reduction": spec.reduction or NONE,
        "class_weight": spec.class_weight or NONE,
        "seed": spec.seed if spec.seed is not None else NONE,
        "gates": _join((line(f) for f in rep.gates), "\n- "),
        "diagnostics": _join((line(f) for f in rep.diagnostics), "\n- "),
        "goal": t.get("goal", NONE),
        "support": t.get("support", NONE),
        "guardrail": t.get("guardrail", NONE),
        "reported_metric": spec.metric or NONE,
        "not_checked": _join((line(f) for f in rep.skipped), "\n- "),
        "opinion": opinion or NOTHING,
    }


def _rows(path: str, sample_n: int) -> int:
    """행 수만 — 셀 값은 읽어도 밖으로 내보내지 않는다."""
    from statop.modeling.leak import load_set

    try:
        return int(len(load_set(path).head(sample_n)))
    except (ValueError, OSError, KeyError):
        return 0


def _balance_text(rep) -> str:  # noqa: ANN001
    """클래스 비 — 트리아드 판정이 이미 계산해 둔 값을 그대로 쓴다."""
    f = next((x for x in rep.findings if x.id == "MB-C24"), None)
    if f is None or f.numbers.get("class_ratio") is None:
        return NONE
    return (f"max:min class ratio {f.numbers['class_ratio']:.1f}x"
            + (" (imbalanced)" if f.numbers.get("imbalanced") else " (balanced)"))


def build(session_file: str, opinion: str = "", family: str | None = None,
          sample_n: int = 50_000) -> tuple[str, str]:
    """(family, 채워진 프롬프트). 유형이 정해져 있으면 클릭 하나로 여기까지 온다."""
    from statop.hypothesis import prompts

    family = family or family_for(session_file)
    # 판정 문구까지 영어로 — 모델에게 보내는 것과 화면에 보이는 것은 언어만 다르다
    with english():
        values = (modeling_values(session_file, opinion, sample_n)
                  if family == "modeling" else analysis_values(session_file, opinion))
    return family, prompts.fill(family, values)
