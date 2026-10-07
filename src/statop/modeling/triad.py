"""S194b MB-Q별 3-metric 트리아드 추천 (MB-C24).

지표 하나만 보면 놓치는 것이 있다. **Goal 옆에 Support 와 Guardrail 을 세운다** —
Support 는 Goal 과 비슷한 것, Guardrail 은 **Goal 의 반례가 될 수 있는 것**이다 .
불균형 이진에서 AUC(Goal) 옆에 PR-AUC(Guardrail)를 세우는 것이 그 예다.

무엇을 세울지는 `registry-models.md` 5절 트리아드 표가 정한다 — **여기서 지어내지 않는다.**
같은 MB-Q01 이라도 균형이냐 불균형이냐에 따라 표의 다른 줄이 걸린다.

**감사 전용이다.** 학습을 돌리지 않고 구성과 라벨 분포만 본다.
"""

from functools import lru_cache

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, skip


@lru_cache(maxsize=1)
def _triads() -> list[dict]:
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "models.yaml").read_text(encoding="utf-8"))["triads"]


def triads() -> list[dict]:
    return _triads()


def pick(question: str, imbalanced: bool) -> dict | None:
    """질문 유형(+불균형 여부)에 걸리는 트리아드 한 줄.

    표의 `question` 열은 "MB-Q01 불균형 이진" 처럼 사람이 읽는 문구다 — ID 로 맞추되
    **불균형 줄이 있으면 그것을 먼저** 본다. 없는 조합은 지어내지 않고 None.
    """
    rows = [t for t in _triads() if question in t["question"]]
    if not rows:
        return None
    special = [t for t in rows if "불균형" in t["question"]]   # rule-vocab
    if imbalanced and special:
        return special[0]
    plain = [t for t in rows if "불균형" not in t["question"]]   # rule-vocab
    return plain[0] if plain else rows[0]


def class_ratio(spec, sample_n: int = 50_000) -> float | None:  # noqa: ANN001
    """개발 세트의 최다:최소 클래스 비. 볼 수 없으면 None — 0 으로 두지 않는다."""
    import pandas as pd

    from statop.modeling.leak import load_set
    from statop.modeling.split_audit import DEV_ROLES

    if not spec.label_column:
        return None
    parts = [load_set(p, [spec.label_column]).head(sample_n)
             for r, p in spec.sets.items() if r in DEV_ROLES]
    parts = [p for p in parts if spec.label_column in p.columns]
    if not parts:
        return None
    counts = pd.concat(parts)[spec.label_column].value_counts()
    if len(counts) < 2 or counts.min() == 0:
        return None
    return float(counts.max() / counts.min())


def recommend(spec, sample_n: int = 50_000, lock_path=None) -> LeakFinding:  # noqa: ANN001
    """MB-C24 — Goal·Support·Guardrail 이 구성돼 있는가, 아니면 무엇을 세울 것인가."""
    from statop.guard import locks

    ratio = class_ratio(spec, sample_n)
    limit = locks.limits("GR-04", lock_path)["imbalance_ratio"].value
    imbalanced = bool(ratio and ratio > limit)
    row = pick(spec.question, imbalanced)
    if row is None:
        return skip("MB-C24", msg("mb_c24_no_triad", q=spec.question))

    numbers = {"question": row["question"], "goal": row["goal"],
               "support": row["support"], "guardrail": row["guardrail"],
               "class_ratio": ratio, "imbalanced": imbalanced,
               "reported": spec.metric}
    detail = [msg("mb_c24_row", role=msg("mb_c24_goal"), what=row["goal"]),
              msg("mb_c24_row", role=msg("mb_c24_support"), what=row["support"]),
              msg("mb_c24_row", role=msg("mb_c24_guardrail"), what=row["guardrail"])]
    if ratio is not None:
        detail.append(msg("mb_c24_basis", ratio=ratio, limit=limit,
                          which=row["question"]))

    if not spec.metric:
        # 무엇을 보고했는지 모르면 구성됐는지도 알 수 없다 — 없다고 단정하지 않는다
        return LeakFinding(
            id="MB-C24", grade=grade_of("MB-C24"), verdict="fail",
            summary=msg("mb_c24_not_recorded", q=row["question"]),
            detail=detail, numbers=numbers, action=msg("mb_c24_action"))
    # 보고한 지표가 Goal 과 같은 이름인지만 본다. 다르다고 틀린 것은 아니다
    aligned = spec.metric.lower().replace(" ", "") in row["goal"].lower().replace(" ", "")
    if aligned:
        return LeakFinding(id="MB-C24", grade=grade_of("MB-C24"), verdict="pass",
                           summary=msg("mb_c24_aligned", metric=spec.metric,
                                       q=row["question"]),
                           detail=detail, numbers=numbers)
    return LeakFinding(
        id="MB-C24", grade=grade_of("MB-C24"), verdict="fail",
        summary=msg("mb_c24_differs", metric=spec.metric, goal=row["goal"],
                    q=row["question"]),
        detail=[*detail, msg("mb_c24_differs_why")], numbers=numbers,
        action=msg("mb_c24_differs_action"))
