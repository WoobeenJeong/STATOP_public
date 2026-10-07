"""B2 누수·중복 검사 (~) — 전부 Gate.

모델 성능이 좋아 보이는 가장 흔한 이유는 모델이 좋아서가 아니라 **답을 미리 봤기**
때문이다. 여기서 보는 네 가지가 그 통로다:

- MB-C01 세트 간 중복 — 같은 행이 train 과 test 에 함께 있으면 외운 것을 맞힌다
- MB-C02 그룹 교차 — 같은 환자의 다른 샘플이 양쪽에 있으면 사실상 같은 행이다
- MB-C03 시간 누수 — test 가 train 보다 과거면 미래를 보고 과거를 맞히는 셈이다
- MB-C05 라벨 대리변수 — 라벨을 거의 그대로 담은 피처가 있으면 모델이 할 일이 없다

**감사 전용이다.** 학습을 돌리지 않고 세트 파일과 설정만 본다.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statop.messages import msg

# 근사 중복 판정 — **모든 수치 피처가 각각** SD 의 이 비율 안에서 일치하면 같은 행으로 본다.
# 유클리드 총거리를 쓰면 피처가 적을 때 우연히 가까운 점이 잡힌다 (차원이 낮을수록 심하다).
# "각 피처가 SD의 0.1% 이내"는 차원 수와 무관하게 같은 뜻을 유지한다.
# 0.1% 로 잡은 이유: 무작위 자료에서는 우연히 걸리지 않고(실측), 복사본에 미세한
# 반올림·잡음이 얹힌 진짜 근사중복은 그대로 걸린다
# 피처가 이보다 적으면 "가까움"과 "같음"을 구별할 수 없다 — 그 사실을 함께 알린다
NEAR_DUP_MIN_FEATURES = 3
NEAR_DUP_PER_FEATURE = 0.001
# 근사 중복 비교는 n×m 이라 양쪽을 이만큼만 본다 — 잘랐으면 그 사실을 결과에 적는다
NEAR_DUP_PROBE = 2000
# 라벨 대리변수 — 이 이상 맞히는 단일 피처는 라벨을 담고 있다고 본다
PROXY_AUC = 0.98
PROXY_CORR = 0.95


@dataclass
class LeakFinding:
    id: str                       # MB-C01 …
    grade: str                    # Gate | Diag
    verdict: str                  # pass | fail | skipped
    summary: str
    detail: list = field(default_factory=list)
    numbers: dict = field(default_factory=dict)
    action: str = ""


def load_set(path: str, columns: list[str] | None = None) -> pd.DataFrame:
    from pathlib import Path

    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p, columns=columns)
    sep = "\t" if p.suffix.lower() in (".tsv", ".tab") else ","
    return pd.read_csv(p, sep=sep, usecols=columns)


def row_keys(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """행 식별 문자열 — 두 표에서 같은 행인지 볼 때 쓴다.

    구분자는 값에 나올 일이 없는 제어문자라 "a,b" 와 "a" + ",b" 가 섞이지 않는다.
    """
    return df[cols].astype(str).agg("\x1f".join, axis=1)


def grade_of(check_id: str) -> str:
    from statop.modeling.spec import checks

    return next((c["grade"] for c in checks() if c["id"] == check_id), "Gate")


def skip(check_id: str, why: str) -> LeakFinding:
    return LeakFinding(id=check_id, grade=grade_of(check_id), verdict="skipped",
                       summary=why)


def _feature_cols(df: pd.DataFrame, spec) -> list[str]:  # noqa: ANN001
    """피처 후보 — 라벨·그룹·시간 컬럼은 뺀다."""
    drop = {spec.label_column, spec.group_column, spec.time_column,
            spec.score_column}
    return [c for c in df.columns if c not in drop]


# ── MB-C01 세트 간 중복·근사중복 ────────────────────────────
def duplicate_rows(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """train 과 test/external 에 같은 행이 있는가 — 정확 중복과 근사 중복 둘 다."""
    if "train" not in spec.sets:
        return skip("MB-C01", msg("mb_leak_need_train"))
    others = [r for r in ("test", "external") if r in spec.sets]
    if not others:
        return skip("MB-C01", msg("mb_leak_need_other"))

    tr = load_set(spec.sets["train"]).head(sample_n)
    feats = _feature_cols(tr, spec)
    detail, worst = [], 0
    numbers: dict = {}
    for role in others:
        te = load_set(spec.sets[role]).head(sample_n)
        shared = [c for c in feats if c in te.columns]
        if not shared:
            continue
        # 정확 중복 — 피처가 모두 같은 행
        exact = int(row_keys(te, shared).isin(set(row_keys(tr, shared))).sum())

        # 근사 중복 — 수치 피처를 표준화해 가장 가까운 train 행과의 거리를 본다
        num = [c for c in shared if pd.api.types.is_numeric_dtype(tr[c])
               and pd.api.types.is_numeric_dtype(te[c])]
        near = 0
        if num and len(tr) and len(te):
            a = tr[num].astype("float64").to_numpy()
            b = te[num].astype("float64").to_numpy()
            sd = np.nanstd(a, axis=0)
            sd[sd == 0] = 1.0
            a, b = (a - np.nanmean(a, axis=0)) / sd, (b - np.nanmean(a, axis=0)) / sd
            a, b = np.nan_to_num(a), np.nan_to_num(b)
            probe, ref = b[:NEAR_DUP_PROBE], a[:NEAR_DUP_PROBE]
            # 각 피처의 차이 중 **최댓값**이 기준 아래여야 한다 (모든 피처가 일치)
            gap = np.abs(probe[:, None, :] - ref[None, :, :]).max(axis=-1)
            near = int((gap.min(axis=1) <= NEAR_DUP_PER_FEATURE).sum())
            if len(b) > NEAR_DUP_PROBE or len(a) > NEAR_DUP_PROBE:
                detail.append(msg("mb_c01_truncated", n=NEAR_DUP_PROBE))
            if near and len(num) < NEAR_DUP_MIN_FEATURES:
                detail.append(msg("mb_c01_low_dim", n=len(num)))
        numbers[role] = {"rows": int(len(te)), "exact": exact, "near": near,
                         "features": len(num)}
        worst = max(worst, exact + max(0, near - exact))
        if exact or near:
            detail.append(msg("mb_c01_row", role=role, n=len(te), exact=exact,
                              near=near, ratio=(exact / len(te)) if len(te) else 0))

    if not numbers:
        return skip("MB-C01", msg("mb_leak_no_shared_cols"))
    grade = grade_of("MB-C01")
    if worst:
        return LeakFinding(id="MB-C01", grade=grade, verdict="fail",
                           summary=msg("mb_c01_fail", n=worst), detail=detail,
                           numbers=numbers, action=msg("mb_c01_action"))
    return LeakFinding(id="MB-C01", grade=grade, verdict="pass",
                       summary=msg("mb_c01_pass"), numbers=numbers)


# ── MB-C02 그룹 구조가 split 을 가로지름 ────────────────────
def group_crossing(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """같은 환자·배치가 train 과 test 양쪽에 있으면 사실상 같은 행이 섞인 것이다."""
    if not spec.group_column:
        return skip("MB-C02", msg("mb_c02_no_group"))
    if "train" not in spec.sets:
        return skip("MB-C02", msg("mb_leak_need_train"))
    others = [r for r in ("test", "external", "valid") if r in spec.sets]
    if not others:
        return skip("MB-C02", msg("mb_leak_need_other"))

    col = spec.group_column
    tr = load_set(spec.sets["train"], [col]).head(sample_n)
    a = set(tr[col].astype(str))
    detail, crossed_total, numbers = [], 0, {}
    for role in others:
        te = load_set(spec.sets[role], [col]).head(sample_n)
        b = te[col].astype(str)
        crossed = sorted(set(b) & a)
        rows = int(b.isin(crossed).sum())
        numbers[role] = {"groups": len(set(b)), "crossed": len(crossed),
                         "rows": rows}
        crossed_total += len(crossed)
        if crossed:
            detail.append(msg("mb_c02_row", role=role, n=len(crossed),
                              rows=rows, sample=", ".join(crossed[:5])))
    grade = grade_of("MB-C02")
    if crossed_total:
        return LeakFinding(id="MB-C02", grade=grade, verdict="fail",
                           summary=msg("mb_c02_fail", col=col, n=crossed_total),
                           detail=detail, numbers=numbers,
                           action=msg("mb_c02_action"))
    return LeakFinding(id="MB-C02", grade=grade, verdict="pass",
                       summary=msg("mb_c02_pass", col=col), numbers=numbers)


# ── MB-C03 시간 누수 ────────────────────────────────────────
def time_leak(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """test 가 train 보다 과거면 미래를 보고 과거를 맞히는 셈이다."""
    if not spec.time_column:
        return skip("MB-C03", msg("mb_c03_no_time"))
    if "train" not in spec.sets or not any(r in spec.sets
                                           for r in ("test", "external")):
        return skip("MB-C03", msg("mb_leak_need_other"))

    col = spec.time_column

    def span(path: str):  # noqa: ANN202
        t = pd.to_datetime(load_set(path, [col]).head(sample_n)[col],
                           errors="coerce", format="mixed").dropna()
        return (t.min(), t.max(), len(t)) if len(t) else (None, None, 0)

    lo_a, hi_a, n_a = span(spec.sets["train"])
    if not n_a:
        return skip("MB-C03", msg("mb_c03_unparsable", col=col))

    detail, overlap_total, numbers = [], 0, {"train": {"from": str(lo_a),
                                                       "to": str(hi_a)}}
    for role in ("test", "external"):
        if role not in spec.sets:
            continue
        lo_b, hi_b, n_b = span(spec.sets[role])
        if not n_b:
            continue
        overlap = lo_b <= hi_a
        numbers[role] = {"from": str(lo_b), "to": str(hi_b), "overlaps": bool(overlap)}
        if overlap:
            overlap_total += 1
            detail.append(msg("mb_c03_row", role=role, tlo=str(lo_b), tro=str(hi_b),
                              alo=str(lo_a), ahi=str(hi_a)))
    grade = grade_of("MB-C03")
    if overlap_total:
        return LeakFinding(id="MB-C03", grade=grade, verdict="fail",
                           summary=msg("mb_c03_fail", col=col), detail=detail,
                           numbers=numbers, action=msg("mb_c03_action"))
    return LeakFinding(id="MB-C03", grade=grade, verdict="pass",
                       summary=msg("mb_c03_pass", col=col), numbers=numbers)


# ── MB-C05 라벨 대리변수 ────────────────────────────────────
def label_proxy(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """라벨을 거의 그대로 담은 피처 — 있으면 모델이 할 일이 없다."""
    if not spec.label_column or "train" not in spec.sets:
        return skip("MB-C05", msg("mb_leak_need_train"))
    df = load_set(spec.sets["train"]).head(sample_n)
    if spec.label_column not in df.columns:
        return skip("MB-C05", msg("select_err_missing", cols=spec.label_column))

    y = df[spec.label_column]
    binary = y.dropna().nunique() == 2
    hits, numbers = [], {}
    for col in _feature_cols(df, spec):
        v = pd.to_numeric(df[col], errors="coerce")
        sub = pd.concat([v, y], axis=1).dropna()
        if len(sub) < 10:
            continue
        x, yy = sub.iloc[:, 0], sub.iloc[:, 1]
        if binary:
            # AUC — 이 피처 하나로 라벨을 얼마나 가려내는가
            pos = yy == sorted(yy.unique())[-1]
            if pos.sum() == 0 or (~pos).sum() == 0:
                continue
            from scipy.stats import rankdata

            r = rankdata(x)
            auc = ((r[pos.to_numpy()].sum() - pos.sum() * (pos.sum() + 1) / 2)
                   / (pos.sum() * (~pos).sum()))
            score = max(auc, 1 - auc)
            if score >= PROXY_AUC:
                hits.append((col, float(score), "AUC"))
            numbers[col] = round(float(score), 4)
        else:
            ynum = pd.to_numeric(yy, errors="coerce")
            if ynum.isna().any():
                continue
            r = abs(float(np.corrcoef(x, ynum)[0, 1]))
            if r >= PROXY_CORR:
                hits.append((col, r, "r"))
            numbers[col] = round(r, 4)

    grade = grade_of("MB-C05")
    if hits:
        detail = [msg("mb_c05_row", col=c, kind=k, value=v) for c, v, k in hits]
        return LeakFinding(id="MB-C05", grade=grade, verdict="fail",
                           summary=msg("mb_c05_fail", n=len(hits)), detail=detail,
                           numbers=numbers, action=msg("mb_c05_action"))
    return LeakFinding(id="MB-C05", grade=grade, verdict="pass",
                       summary=msg("mb_c05_pass", n=len(numbers)), numbers=numbers)


def run_all(spec, sample_n: int = 50_000) -> list[LeakFinding]:  # noqa: ANN001
    """B2 누수 검사 전부 — 하나가 실패해도 나머지는 돈다."""
    out = []
    for fn in (duplicate_rows, group_crossing, time_leak, label_proxy):
        try:
            out.append(fn(spec, sample_n))
        except (ValueError, OSError, KeyError) as e:
            out.append(LeakFinding(id="?", grade="Gate", verdict="skipped",
                                   summary=str(e)))
    return out
