"""A1 구조화 입력 (~) — "무엇을 물을 것인가"를 자유문이 아니라 항목으로 받는다.

질문유형(Q-01~11)·대상 컬럼·짝지음·방향·대비·계획 검정 수를 세션 op(analysis_spec)로
남긴다. 이게 있어야 A2(후보)·A3(가정 검사)·다중검정 보정이 전부 같은 전제를 쓴다.

대상 컬럼을 지정하는 순간 M1-3(연산 적합성)을 자동으로 돌린다  —
질문을 세워놓고 보니 y가 조성 성분이었다는 것을 검정 직전이 아니라 여기서 안다.
"""

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from statop.messages import msg

DIRECTIONS = ("two-sided", "greater", "less")
CONTRASTS = ("all-pairs", "vs-control")


@lru_cache(maxsize=1)
def _rules() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[3] / "rules" / "tests.yaml"
    return yaml.safe_load(path.read_text())


def questions() -> list[dict]:
    """질문 유형 11종 — 사용자 말(user_words)이 붙어 있어 고르는 기준이 된다."""
    return _rules()["questions"]


def question_ids() -> list[str]:
    return [q["id"] for q in questions()]


@dataclass
class Spec:
    question: str                     # Q-01 …
    y: str                            # 측정(결과) 컬럼
    group: str | None = None          # 그룹/두 번째 변수 (Q-03 연관이면 x)
    event: str | None = None          # 생존 분석의 사건 여부 (1=발생, 0=중도절단)
    by: str | None = None             # 층화 라벨 — 전체와 **수준별**을 함께 본다
    subject: str | None = None        # 대상 ID — 같은 대상을 여러 번 쟀을 때 (반복측정)
    paired: bool = False              # 같은 대상 반복 측정인가
    direction: str = "two-sided"
    contrast: str = "all-pairs"       # ≥3군일 때 무엇끼리 비교하나
    control: str | None = None        # vs-control 의 기준 수준
    weights: str | None = None        # 사전지정 대비의 가중치 (군 순서대로, 합 0)
    n_tests: int = 1                  # 계획한 검정 수 — 다중검정 보정의 분모

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpecResult:
    spec: Spec
    y_type: str | None                # 확정된 의미 타입 (없으면 None — 보류 사유)
    group_type: str | None
    n_rows: int
    group_levels: dict = field(default_factory=dict)   # 수준 → n
    compat: dict = field(default_factory=dict)         # M1-3 자동 판정
    problems: list[str] = field(default_factory=list)  # 진행 전에 풀어야 할 것
    # 이 설계에 실제로 쓰이는 컬럼의 결측 — 검정마다 조용히 다른 행이 빠지는 것을 막는다
    missing: dict = field(default_factory=dict)        # 컬럼 → {n, ratio}
    n_complete: int = 0                                # y·x 가 모두 있는 행 수
    # id 로 확정된 컬럼에 같은 값이 여러 번 나오면 같은 대상을 여러 번 잰 것이다
    repeat_candidates: list = field(default_factory=list)   # [{column, subjects, rows}]
    # A3 가정 검사 결과 — 후보 색이 이것을 본다. 안 돌렸으면 빈 목록이고, 그때는
    # 가정이 필요한 검정이 초록으로 올라가지 않는다 (확인 못 한 것은 통과가 아니다)
    checks: list = field(default_factory=list)


def validate(spec: Spec, columns: list[str]) -> list[str]:
    """스펙 자체의 오류 — 데이터를 보기 전에 잡을 수 있는 것."""
    errs = []
    if spec.question not in question_ids():
        errs.append(msg("spec_bad_question", q=spec.question,
                        allowed=", ".join(question_ids())))
    if spec.y not in columns:
        errs.append(msg("select_err_missing", cols=spec.y))
    if spec.group is not None and spec.group not in columns:
        errs.append(msg("select_err_missing", cols=spec.group))
    if spec.group == spec.y:
        errs.append(msg("spec_same_column"))
    if spec.subject is not None and spec.subject not in columns:
        errs.append(msg("select_err_missing", cols=spec.subject))
    if spec.by is not None:
        if spec.by not in columns:
            errs.append(msg("select_err_missing", cols=spec.by))
        elif spec.by == spec.y:
            errs.append(msg("spec_by_same_column", col=spec.by))
    if spec.event is not None:
        if spec.event not in columns:
            errs.append(msg("select_err_missing", cols=spec.event))
        elif spec.event in (spec.y, spec.group):
            errs.append(msg("spec_event_same_column", col=spec.event))
    if spec.direction not in DIRECTIONS:
        errs.append(msg("spec_bad_direction", allowed="|".join(DIRECTIONS)))
    if spec.contrast not in CONTRASTS:
        errs.append(msg("spec_bad_contrast", allowed="|".join(CONTRASTS)))
    if spec.contrast == "vs-control" and not spec.control:
        errs.append(msg("spec_need_control"))
    if spec.n_tests < 1:
        errs.append(msg("spec_bad_ntests"))
    return errs


def build(session_file: str, spec: Spec, sample_n: int = 10_000) -> SpecResult:
    """스펙을 데이터에 대본다 — 타입·군 구성·적합성(M1-3)까지 한 번에 .

    기록은 하지 않는다. 기록(record)은 문제를 보고 사용자가 결정한 뒤다.
    """
    from statop.compat import composition_groups, judge_pair, judge_set
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    errs = validate(spec, list(df.columns))
    if errs:
        return SpecResult(spec=spec, y_type=None, group_type=None,
                          n_rows=len(df), problems=errs)

    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})
    y_type = types.get(spec.y)
    group_type = types.get(spec.group) if spec.group else None
    out = SpecResult(spec=spec, y_type=y_type, group_type=group_type, n_rows=len(df))

    used = [c for c in (spec.y, spec.group, spec.event, spec.by, spec.subject) if c]
    for c in used:
        n = int(df[c].isna().sum())
        out.missing[c] = {"n": n, "ratio": n / len(df) if len(df) else 0.0}
    out.n_complete = int(df[used].notna().all(axis=1).sum()) if used else len(df)

    for col, t in types.items():
        if t != "id" or col not in df.columns:
            continue
        vals = df[col].dropna()
        if len(vals) > vals.nunique():
            out.repeat_candidates.append({"column": col, "subjects": int(vals.nunique()),
                                          "rows": int(len(vals))})

    GROUPING = {"label", "nominal code", "ordinal code", "id"}
    group_is_grouping = group_type in GROUPING or (
        group_type is None and spec.group and df[spec.group].dtype.kind not in "if")
    if spec.group and group_is_grouping:
        vc = df[spec.group].dropna().astype(str).value_counts()
        # 라벨 매핑이 있으면 코드 기준 군 구성으로 — 묶은 대로 비교된다 ()
        mapping = st["label_maps"].get(src["id"], {}).get(spec.group)
        if mapping:
            merged: dict[str, int] = {}
            for value, n in vc.items():
                code = str(mapping.get(str(value), value))
                merged[code] = merged.get(code, 0) + int(n)
            out.group_levels = merged
        else:
            out.group_levels = {str(k): int(v) for k, v in vc.items()}
        if spec.control is not None and spec.contrast == "vs-control" \
                and spec.control not in out.group_levels:
            out.problems.append(msg("spec_control_unknown", control=spec.control,
                                    levels=", ".join(list(out.group_levels)[:8])))
        if len(out.group_levels) > 20 and spec.question != "Q-03":
            # 군 변수라기엔 수준이 너무 많다 — 연속 변수를 group 에 넣은 실수의 전형
            out.problems.append(msg("spec_group_too_many_levels",
                                    col=spec.group, n=len(out.group_levels)))

    # 타입 미확정은 보류 사유다 — 추론값으로 검정을 고르면 틀린 검정이 나온다
    if y_type is None:
        out.problems.append(msg("spec_y_unconfirmed", col=spec.y))
    if spec.group and group_type is None:
        out.problems.append(msg("spec_group_unconfirmed", col=spec.group))

    #  — 대상 컬럼을 지정하는 순간 적합성 판정을 자동으로 돌린다
    comp = composition_groups(df, [c for c in df.columns], types)
    op_kind = "correlate" if spec.question == "Q-03" else "compare"
    if spec.group:
        rep = judge_pair(op_kind, spec.y, spec.group, types, df=df, comp_groups=comp)
    else:
        rep = judge_set(op_kind, [spec.y], types, df=df, comp_groups=comp)
    out.compat = {
        "verdict": rep.verdict, "blocked": rep.blocked,
        "findings": [{"id": f.id, "verdict": f.verdict, "detail": f.detail,
                      "why": f.why, "fix": f.fix, "fix_action": f.fix_action}
                     for f in rep.findings],
    }
    if rep.verdict == "gate":
        out.problems.append(msg("spec_compat_gate",
                                ids=", ".join(sorted({f.id for f in rep.findings
                                                      if f.verdict == "gate"}))))

    # 이미 돌려 둔 가정 검사가 있으면 함께 싣는다 — 후보 색(A2)이 이걸 본다.
    # 없으면 빈 목록이고, 그때는 가정이 필요한 검정이 초록으로 올라가지 않는다
    try:
        from statop.analyze.checks import run_checks

        out.checks = run_checks(session_file, sample_n=sample_n)
    except (ValueError, KeyError):
        out.checks = []
    return out


def record(session_file: str, spec: Spec) -> dict:
    """스펙을 세션에 기록한다 (op: analysis_spec) — 이후 A2·A3·보정이 이 전제를 쓴다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session_file)
    src = main_source(doc)
    entry = append_op(doc, "analysis_spec", source=src["id"], **spec.as_dict())
    save_session(doc)
    return entry


def current(session_file: str) -> Spec | None:
    """세션의 마지막 analysis_spec — 같은 세션에서 다시 세우면 마지막이 이긴다."""
    from statop.session.core import load_session

    doc = load_session(session_file)
    for op in reversed(doc["ops"]):
        if op["op"] == "analysis_spec":
            keys = {f.name for f in Spec.__dataclass_fields__.values()} \
                if hasattr(Spec, "__dataclass_fields__") else set()
            return Spec(**{k: v for k, v in op.items()
                           if k in Spec.__dataclass_fields__})
    return None
