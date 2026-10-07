"""B1 데이터 구성 확인 — 세트 역할·검증 방식·MB-Q/MB-M 선택 (, MB-C14).

모델링 감사는 "무엇을 학습했는가"를 알아야 시작된다. 어떤 세트가 train/test/external 인지,
어떤 검증 방식을 썼는지, 어떤 질문(MB-Q)과 어떤 티어(MB-M)인지 — 이걸 **사용자가 확정**해야
뒤따르는 누수·불균형·평가 감사가 무엇을 볼지 정해진다.

모듈 A 의 `analyze/spec.py` 와 같은 자리에 있지만 **다른 질문**을 다룬다 (: 모드는 2개).
"""

from dataclasses import asdict, dataclass, field
from functools import lru_cache

from statop.messages import msg

# 세트 역할 — 감사의 뼈대. 무엇이 test 인지 모르면 누수를 볼 수 없다
ROLES = ("train", "valid", "test", "external")

# 검증 방식과 그 조건 (MB-C14). 소표본 LOOCV 처럼 **분산이 커지는** 조합을 잡는다
VALIDATIONS = {
    "holdout": {"needs_valid": True},
    "kfold": {"needs_k": True},
    "stratified_kfold": {"needs_k": True},
    "group_kfold": {"needs_k": True, "needs_group": True},
    "time_split": {"needs_time": True},
    "loocv": {},
    "nested_cv": {"needs_k": True},
}


@dataclass
class ModelSpec:
    question: str                      # MB-Q01 …
    tier: str                          # MB-M0 …
    validation: str = "kfold"
    k: int | None = None
    group_column: str | None = None    # GroupKFold 의 그룹 (환자·배치)
    time_column: str | None = None     # 시간 split 의 기준
    sets: dict = field(default_factory=dict)     # 역할 → 파일 경로
    label_column: str | None = None
    score_column: str | None = None    # 확률·점수 (MB-Q01/03)
    positive_class: str | None = None  # 어느 수준이 양성인가 (MB-C13 방향)
    class_weight: str | None = None    # 가중·샘플링을 썼다면 무엇으로 (MB-C12)
    model_family: str | None = None    # 모델 계열 (MB-C10) — distance·penalized·tree …
    scaling: str | None = None         # 표준화를 썼다면 무엇으로 (MB-C10/C11)
    reduction: str | None = None       # 차원축소를 썼다면 무엇으로 (MB-C11) — PCA 등
    threshold: float | None = None     # 민감도·특이도를 보고한 임계값 (MB-C20)
    averaging: str | None = None       # 다중분류 평균 방식 (MB-C17) — macro|micro|weighted
    fold_scores: list = field(default_factory=list)   # fold 별 성능 (MB-C22)
    metric: str | None = None          # 무엇을 보고했는가 (MB-C21) — ROC-AUC·mean prob …
    metric_change_reason: str | None = None           # 지표를 바꿨다면 왜 (MB-C21)
    environment: str | None = None     # 라이브러리·하드웨어 (MB-C26/C27)
    nondeterminism: str | None = None  # 비결정 연산 고지 (MB-C27)
    importance: str | None = None      # 특성중요도를 보고했다면 무엇으로 (MB-C31)
    seed: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpecCheck:
    spec: ModelSpec
    problems: list = field(default_factory=list)   # 진행 전에 풀 것
    notes: list = field(default_factory=list)      # 확인 요약
    v1_supported: bool = True
    n_rows: dict = field(default_factory=dict)     # 역할 → 행 수


@lru_cache(maxsize=1)
def _db() -> dict:
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "models.yaml").read_text(encoding="utf-8"))


def questions() -> list[dict]:
    return _db()["questions"]


def tiers() -> list[dict]:
    return _db()["tiers"]


def checks(group: str | None = None) -> list[dict]:
    items = _db()["checks"]
    return [c for c in items if group is None or c["group"] == group]


def validate(spec: ModelSpec) -> list[str]:
    """스펙 자체의 오류 — 데이터를 읽기 전에 잡을 수 있는 것."""
    errs = []
    qs = {q["id"]: q for q in questions()}
    ts = {t["id"]: t for t in tiers()}
    if spec.question not in qs:
        errs.append(msg("mb_bad_question", q=spec.question,
                        allowed=", ".join(qs)))
    if spec.tier not in ts:
        errs.append(msg("mb_bad_tier", t=spec.tier, allowed=", ".join(ts)))
    if spec.validation not in VALIDATIONS:
        errs.append(msg("mb_bad_validation", v=spec.validation,
                        allowed=", ".join(VALIDATIONS)))
    else:
        rule = VALIDATIONS[spec.validation]
        if rule.get("needs_k") and not (spec.k and spec.k >= 2):
            errs.append(msg("mb_need_k", v=spec.validation))
        if rule.get("needs_group") and not spec.group_column:
            errs.append(msg("mb_need_group", v=spec.validation))
        if rule.get("needs_time") and not spec.time_column:
            errs.append(msg("mb_need_time", v=spec.validation))
    bad = [r for r in spec.sets if r not in ROLES]
    if bad:
        errs.append(msg("mb_bad_role", roles=", ".join(bad),
                        allowed=", ".join(ROLES)))
    if not spec.label_column:
        errs.append(msg("mb_need_label"))
    return errs


def build(spec: ModelSpec, sample_n: int = 10_000) -> SpecCheck:
    """스펙을 실제 세트에 대본다 — 확인 요약 (MB-C14).

    여기서는 **판정하지 않고 구성만 확인한다.** 누수·불균형·평가는 B2 이후의 몫이다.
    """
    from pathlib import Path

    from statop.io.sample import sample_rows

    out = SpecCheck(spec=spec, problems=validate(spec))
    qs = {q["id"]: q for q in questions()}
    ts = {t["id"]: t for t in tiers()}

    q, t = qs.get(spec.question), ts.get(spec.tier)
    if q and t:
        # v1 에서 판정하지 않는 조합은 **먼저** 말한다. 돌려놓고 빈 결과를 주면 안 된다
        out.v1_supported = q["v1"] != "later" and t["v1"] != "later"
        if not out.v1_supported:
            out.problems.append(msg("mb_not_v1", q=spec.question, qv=q["v1"],
                                    t=spec.tier, tv=t["v1"]))
        out.notes.append(msg("mb_note_question", id=q["id"], text=q["question"],
                             output=q["output"]))
        out.notes.append(msg("mb_note_tier", id=t["id"], tier=t["tier"],
                             need=t["audit_input"]))

    for role, path in spec.sets.items():
        if not Path(path).exists():
            out.problems.append(msg("mb_set_missing", role=role, path=path))
            continue
        try:
            out.n_rows[role] = int(len(sample_rows(path, n=sample_n)))
        except (ValueError, OSError) as e:
            out.problems.append(msg("mb_set_unreadable", role=role, detail=str(e)))

    if "test" not in spec.sets and spec.validation == "holdout":
        out.problems.append(msg("mb_holdout_needs_test"))
    if spec.validation == "loocv" and sum(out.n_rows.values()) > 500:
        # LOOCV 는 n 만큼 학습한다 — 크면 비현실적이고 분산도 크다
        out.notes.append(msg("mb_loocv_large", n=sum(out.n_rows.values())))
    if spec.validation in ("kfold", "stratified_kfold") and spec.group_column:
        # 그룹이 있는데 일반 KFold 면 MB-C02 가 걸릴 자리다
        out.notes.append(msg("mb_group_hint", col=spec.group_column))
    if spec.seed is None:
        out.notes.append(msg("mb_seed_missing"))       # MB-C25 는 B5 에서 Gate
    return out


def record(session_file: str, spec: ModelSpec) -> dict:
    """확정한 구성을 세션에 남긴다 — 이후 감사가 이 전제 위에서 돈다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    errs = validate(spec)
    if errs:
        raise ValueError("\n".join(errs))
    doc = load_session(session_file)
    src = main_source(doc)
    entry = append_op(doc, "model_spec", source=src["id"] if src else None,
                      **spec.as_dict())
    save_session(doc)
    return entry


def current(session_file: str) -> ModelSpec | None:
    from statop.session.core import load_session, replay

    specs = replay(load_session(session_file))["model_specs"]
    if not specs:
        return None
    last = {k: v for k, v in specs[-1].items()
            if k in ModelSpec.__dataclass_fields__}
    return ModelSpec(**last)
