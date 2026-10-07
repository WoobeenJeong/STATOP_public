"""B5 전처리·모델 적합 권고  — MB-C10 · MB-C11 · MB-C15.

성능이 나오든 안 나오든, **모델이 값을 쓰는 방식과 전처리가 어긋나 있으면** 그 숫자는
모델의 실력이 아니다. 여기서 보는 셋이 그 자리다:

- MB-C10 표준화 필요 모델인데 안 했나 — 거리·벌점·경사는 척도에 직접 의존한다
- MB-C11 차원축소(PCA 등) 전에 표준화했나 — 분산 최대 방향이 척도 큰 변수로 끌린다
- MB-C15 EPV(변수당 사건 수)가 10 미만인가 — 로지스틱 계수가 불안정해진다

**어느 컬럼이 문제인지 지목한다** . "표준화하세요"만 말하면 무엇을 표준화할지
사용자가 다시 찾아야 한다 — 척도가 몇 배 벌어져 있는지까지 같이 낸다.

**감사 전용이다.** 학습을 돌리지 않고 세트 파일과 설정만 본다.
"""

from functools import lru_cache

import numpy as np
import pandas as pd

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, load_set, skip
from statop.modeling.split_audit import DEV_ROLES

# 척도 차이가 이 배수를 넘는 컬럼을 지목한다. 표준편차 비로 본다 — 평균이 0 근처면
# 최대/최소 비가 발산하고, 분산이 곧 거리·벌점·경사에 실리는 양이기 때문이다
SCALE_RATIO = 10.0
# 로지스틱 계수가 안정적이려면 변수당 사건이 이만큼은 필요하다 (MB-C15, C-09)
EPV_MIN = 10


@lru_cache(maxsize=1)
def _rules() -> dict:
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "models.yaml").read_text(encoding="utf-8"))


def families() -> list[dict]:
    """모델 계열과 표준화 필요 여부 (registry-models 3.6)."""
    return _rules()["preprocessing"]


def family_of(name: str) -> dict | None:
    """계열 코드로 찾는다. 모르는 이름은 지어내지 않고 None."""
    return next((f for f in families() if f["family"] == (name or "").lower()), None)


def _dev_frame(spec, sample_n: int) -> pd.DataFrame:  # noqa: ANN001
    """개발 세트를 합친 표 — 전처리는 개발 자료 기준으로 정한다."""
    parts = [load_set(p).head(sample_n) for r, p in spec.sets.items()
             if r in DEV_ROLES]
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _feature_cols(df: pd.DataFrame, spec) -> list[str]:  # noqa: ANN001
    drop = {spec.label_column, spec.group_column, spec.time_column, spec.score_column}
    return [c for c in df.columns
            if c not in drop and pd.api.types.is_numeric_dtype(df[c])]


def scale_spread(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    """컬럼별 표준편차와, 가장 작은 컬럼 대비 몇 배인지. 큰 순으로.

    "척도가 다르다"는 말만으로는 무엇을 볼지 알 수 없다 — **몇 배인지와 어느 컬럼인지**를
    같이 줘야 사용자가 판단한다 .
    """
    sds = {c: float(np.nanstd(pd.to_numeric(df[c], errors="coerce"))) for c in cols}
    sds = {c: v for c, v in sds.items() if np.isfinite(v) and v > 0}
    if not sds:
        return []
    lo = min(sds.values())
    return sorted(({"column": c, "sd": v, "ratio": v / lo} for c, v in sds.items()),
                  key=lambda x: -x["ratio"])


# ── MB-C10 표준화 필요 모델인데 누락 ────────────────────────
def scaling_needed(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """이 모델 계열이 표준화를 요구하는가, 했다고 기록돼 있는가.

    **했는지가 아니라 적혀 있는지**를 본다 — 학습 코드를 읽지 않는다 (MB-C12 와 같은 태도).
    """
    fam = family_of(spec.model_family)
    if fam is None:
        return skip("MB-C10", msg("mb_c10_no_family",
                                  allowed=", ".join(f["family"] for f in families())))
    if fam["scaling"] == "optional":
        return LeakFinding(id="MB-C10", grade=grade_of("MB-C10"), verdict="pass",
                           summary=msg("mb_c10_not_needed", family=spec.model_family,
                                       examples=fam["examples"]),
                           detail=[fam["why"]], numbers={"family": fam["family"]})
    if fam["scaling"] == "depends" and not spec.scaling:
        # 어느 쪽이 옳다고 말하지 않는다 — 목적·구조에 따라 갈리므로 **기록만 청한다**.
        # 안 해도 되는데 해버리거나 그 반대여서 성적이 달라지는 일을 막는 것이 목적이다
        df = _dev_frame(spec, sample_n)
        spread = scale_spread(df, _feature_cols(df, spec)) if len(df) else []
        detail = [fam["why"]]
        if spread:
            detail.append(msg("mb_c10_spread", body=" · ".join(
                msg("mb_c10_cell", col=s["column"], sd=s["sd"], ratio=s["ratio"])
                for s in spread[:5])))
        return LeakFinding(
            id="MB-C10", grade=grade_of("MB-C10"), verdict="fail",
            summary=msg("mb_c10_depends", family=spec.model_family,
                        examples=fam["examples"]),
            detail=detail, action=msg("mb_c10_depends_action"),
            numbers={"family": fam["family"], "scaling_rule": "depends",
                     "columns": {s["column"]: s["ratio"] for s in spread}})
    if spec.scaling:
        return LeakFinding(id="MB-C10", grade=grade_of("MB-C10"), verdict="pass",
                           summary=msg("mb_c10_recorded", how=spec.scaling,
                                       family=spec.model_family),
                           numbers={"family": fam["family"], "scaling": spec.scaling})

    df = _dev_frame(spec, sample_n)
    spread = scale_spread(df, _feature_cols(df, spec)) if len(df) else []
    detail = [fam["why"]]
    worst = spread[0]["ratio"] if spread else 0.0
    if spread:
        detail.append(msg("mb_c10_spread", body=" · ".join(
            msg("mb_c10_cell", col=s["column"], sd=s["sd"], ratio=s["ratio"])
            for s in spread[:5])))
    return LeakFinding(
        id="MB-C10", grade=grade_of("MB-C10"), verdict="fail",
        summary=msg("mb_c10_missing", family=spec.model_family,
                    examples=fam["examples"], ratio=worst),
        detail=detail, action=msg("mb_c10_action"),
        numbers={"family": fam["family"], "max_ratio": worst,
                 "columns": {s["column"]: s["ratio"] for s in spread}})


# ── MB-C11 /  차원축소 전 표준화 ───────────────────────
def projection_scaling(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """PCA 등 차원축소 전에 표준화가 필요한가 — **끌고 갈 컬럼을 지목한다** .

    분산 최대 방향을 찾는 것이므로, 분산이 큰 컬럼이 첫 주성분을 그대로 가져간다.
    "표준화하세요"가 아니라 "이 컬럼이 끌고 갑니다"라고 말해야 판단할 수 있다.
    """
    if not spec.reduction:
        return skip("MB-C11", msg("mb_c11_no_reduction"))
    df = _dev_frame(spec, sample_n)
    cols = _feature_cols(df, spec)
    if len(cols) < 2:
        return skip("MB-C11", msg("mb_c11_need_features"))
    spread = scale_spread(df, cols)
    if not spread:
        return skip("MB-C11", msg("mb_c11_need_features"))

    # 표준화하지 않았을 때 첫 주성분이 어디서 오는지 — 분산 몫으로 보여준다
    total = sum(s["sd"] ** 2 for s in spread)
    share = {s["column"]: (s["sd"] ** 2) / total for s in spread} if total else {}
    top = spread[0]
    numbers = {"reduction": spec.reduction, "scaling": spec.scaling,
               "max_ratio": top["ratio"], "variance_share": share}
    if spec.scaling:
        return LeakFinding(id="MB-C11", grade=grade_of("MB-C11"), verdict="pass",
                           summary=msg("mb_c11_recorded", how=spec.scaling,
                                       reduction=spec.reduction),
                           numbers=numbers)
    detail = [msg("mb_c10_spread", body=" · ".join(
        msg("mb_c10_cell", col=s_["column"], sd=s_["sd"], ratio=s_["ratio"])
        for s_ in spread[:5]))]
    return LeakFinding(
        id="MB-C11", grade=grade_of("MB-C11"), verdict="fail",
        summary=msg("mb_c11_missing", reduction=spec.reduction, col=top["column"],
                    share=share.get(top["column"], 0.0), ratio=top["ratio"]),
        detail=detail, numbers=numbers, action=msg("mb_c11_action"))


# ── MB-C15 EPV (변수당 사건 수) ─────────────────────────────
def events_per_variable(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """로지스틱에서 변수당 사건이 몇 개인가 — 적으면 계수가 불안정해진다 (C-09)."""
    fam = family_of(spec.model_family)
    if fam is None or fam["family"] not in ("linear", "penalized"):
        return skip("MB-C15", msg("mb_c15_not_applicable",
                                  family=spec.model_family or "-"))
    if not spec.label_column:
        return skip("MB-C15", msg("mb_need_label"))
    df = _dev_frame(spec, sample_n)
    if not len(df) or spec.label_column not in df.columns:
        return skip("MB-C15", msg("mb_c08_no_dev"))

    y = df[spec.label_column].dropna()
    counts = y.value_counts()
    if len(counts) != 2:
        return skip("MB-C15", msg("mb_c15_binary_only", n=int(len(counts))))
    n_events = int(counts.min())          # 드문 쪽이 사건 — 많은 쪽으로 세면 낙관적이 된다
    n_vars = len(_feature_cols(df, spec))
    if not n_vars:
        return skip("MB-C15", msg("mb_c11_need_features"))
    epv = n_events / n_vars
    numbers = {"events": n_events, "variables": n_vars, "epv": epv, "limit": EPV_MIN}
    if epv >= EPV_MIN:
        return LeakFinding(id="MB-C15", grade=grade_of("MB-C15"), verdict="pass",
                           summary=msg("mb_c15_pass", epv=epv, events=n_events,
                                       variables=n_vars),
                           numbers=numbers)
    return LeakFinding(
        id="MB-C15", grade=grade_of("MB-C15"), verdict="fail",
        summary=msg("mb_c15_low", epv=epv, events=n_events, variables=n_vars,
                    limit=EPV_MIN),
        detail=[msg("mb_c15_why"),
                msg("mb_c15_room", n=int(n_events // EPV_MIN))],
        numbers=numbers, action=msg("mb_c15_action"))


def run_all(spec, sample_n: int = 50_000) -> list[LeakFinding]:  # noqa: ANN001
    """B5 전처리 검사 전부 — 하나가 실패해도 나머지는 돈다."""
    out = []
    for fn in (scaling_needed, projection_scaling, events_per_variable):
        try:
            out.append(fn(spec, sample_n))
        except (ValueError, OSError, KeyError) as e:
            out.append(skip("MB-C10", str(e)))
    return out
