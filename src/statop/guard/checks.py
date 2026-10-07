"""M4 가드레일 검사 GR-01~04 (~).

각 검사는 **무엇을 봤고 무엇이 나왔는지**를 숫자로 돌려준다. 등급은 여기서 정하지 않고
잠금(locks)이 정한 등급을 파이프라인이 붙인다 — 그래야 사용자가 등급을 조정해도
검사 코드가 흔들리지 않는다.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statop.messages import msg


@dataclass
class Signal:
    """검사 1건의 결과. 등급은 파이프라인이 붙인다."""

    rule: str
    check: str                  # 하위 검사 이름 (언어 독립 코드)
    hit: bool                   # 걸렸는가
    tier_hint: str              # 규칙 DB가 이 검사에 매긴 등급
    detail: str = ""
    numbers: dict = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)


# ── GR-01 정의역 검사  ─────────────────────────────────
# 의미 타입별 수학적 정의역. 이 밖은 "이례적"이 아니라 **불가능**이다.
DOMAIN = {
    "probability": (0.0, 1.0),
    "proportion": (0.0, 1.0),
    "percent": (0.0, 100.0),
    "count": (0.0, None),
}


def out_of_range(df: pd.DataFrame, types: dict[str, str],
                 tail_quantile: float = 0.999) -> list[Signal]:
    """GR-01 — 불가능한 값(gate)과 경계·꼬리 값(diagnostic)을 나눠서 본다."""
    out: list[Signal] = []
    for col, t in types.items():
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue

        lo, hi = DOMAIN.get(t, (None, None))
        n_bad = 0
        if lo is not None:
            n_bad += int((s < lo).sum())
        if hi is not None:
            n_bad += int((s > hi).sum())
        if n_bad:
            out.append(Signal("GR-01", "impossible", True, "gate",
                              detail=msg("guard_gr01_impossible", col=col, n=n_bad,
                                         lo=lo, hi=hi if hi is not None else "∞"),
                              numbers={"n": n_bad, "ratio": n_bad / len(s),
                                       "min": float(s.min()), "max": float(s.max())},
                              columns=[col]))

        # 경계 특수값 — 값 자체는 맞지만 log·logit이 불가능해진다
        if t in ("probability", "proportion"):
            n_edge = int(((s == 0) | (s == 1)).sum())
            if n_edge:
                out.append(Signal("GR-01", "boundary", True, "diagnostic",
                                  detail=msg("guard_gr01_boundary", col=col, n=n_edge),
                                  numbers={"n": n_edge, "ratio": n_edge / len(s)},
                                  columns=[col]))

        # 분포 꼬리 밖 — 불가능하진 않지만 확인이 필요하다
        if len(s) >= 50 and s.nunique() > 5:
            cut = float(s.quantile(tail_quantile))
            n_tail = int((s > cut).sum())
            if n_tail and cut > float(s.median()):
                out.append(Signal("GR-01", "tail", True, "diagnostic",
                                  detail=msg("guard_gr01_tail", col=col, n=n_tail,
                                             q=tail_quantile, cut=cut),
                                  numbers={"n": n_tail, "cut": cut,
                                           "max": float(s.max())},
                                  columns=[col]))
    return out


def apply_action(df: pd.DataFrame, col: str, t: str, action: str):
    """GR-01 조치 — flag는 아무것도 바꾸지 않는다(기본), drop/clip만 데이터를 바꾼다."""
    lo, hi = DOMAIN.get(t, (None, None))
    if action in ("flag", "keep") or (lo is None and hi is None):
        return df, 0
    s = pd.to_numeric(df[col], errors="coerce")
    bad = pd.Series(False, index=df.index)
    if lo is not None:
        bad |= s < lo
    if hi is not None:
        bad |= s > hi
    n = int(bad.sum())
    if action == "drop":
        return df[~bad], n
    if action == "clip":
        return df.assign(**{col: s.clip(lower=lo, upper=hi)}), n
    raise ValueError(msg("guard_unknown_action", action=action))


# ── GR-02 SRM  ─────────────────────────────────────────
def srm(counts: dict[str, int], expected_ratio: dict[str, float] | None = None,
        p_threshold: float = 0.0005) -> Signal:
    """GR-02 — 군 배정 비율이 기대와 다른가 (χ²).

    기대 비율을 주지 않으면 균등으로 본다. 균등이 아닌데 균등으로 검정하면
    "SRM"이 아니라 설계를 잘못 읽은 것이므로, 기대 비율은 출력에 항상 적는다.
    """
    from scipy import stats

    labels = list(counts)
    obs = np.array([counts[k] for k in labels], dtype="float64")
    if expected_ratio:
        w = np.array([expected_ratio.get(k, 0.0) for k in labels], dtype="float64")
    else:
        w = np.ones(len(labels))
    if w.sum() <= 0 or len(labels) < 2 or obs.sum() == 0:
        return Signal("GR-02", "srm", False, "gate",
                      detail=msg("guard_gr02_not_applicable"),
                      numbers={"n": int(obs.sum())})
    exp = w / w.sum() * obs.sum()
    chi2, p = stats.chisquare(obs, exp)
    ratio = {k: float(o / obs.sum()) for k, o in zip(labels, obs)}
    return Signal("GR-02", "srm", bool(p < p_threshold), "gate",
                  detail=msg("guard_gr02_result", p=p, ratio=" : ".join(
                      f"{k} {v:.1%}" for k, v in ratio.items())),
                  numbers={"chi2": float(chi2), "p": float(p), "n": int(obs.sum()),
                           "observed": {k: int(v) for k, v in zip(labels, obs)},
                           "expected": {k: float(v) for k, v in zip(labels, exp)},
                           "observed_ratio": ratio},
                  columns=labels)


def srm_by_dimension(df: pd.DataFrame, group_col: str, meta_cols: list[str],
                     expected_ratio: dict[str, float] | None = None,
                     p_threshold: float = 0.0005) -> list[Signal]:
    """메타 컬럼별 SRM — 여러 번 보므로 Bonferroni로 임계를 나눈다.

    차원마다 따로 검정하면 우연히 걸리는 것이 생긴다. 나누지 않으면 도구가
    스스로 다중비교 오류를 범한다.
    """
    tests = [(m, v) for m in meta_cols if m in df.columns
             for v in df[m].dropna().unique()]
    if not tests:
        return []
    adj = p_threshold / len(tests)
    out = []
    for m, v in tests:
        sub = df[df[m] == v]
        counts = sub[group_col].value_counts().to_dict()
        if len(counts) < 2:
            continue
        sig = srm(counts, expected_ratio, adj)
        sig.check = "srm_dimension"
        sig.columns = [m]
        sig.numbers["level"] = str(v)
        sig.numbers["p_threshold_adjusted"] = adj
        sig.detail = msg("guard_gr02_dimension", col=m, level=v,
                         p=sig.numbers.get("p", 1.0), adj=adj)
        out.append(sig)
    return [s for s in out if s.hit]


def srm_counterfactual(kept: pd.DataFrame, lost: pd.DataFrame, group_col: str,
                       expected_ratio: dict[str, float] | None = None,
                       p_threshold: float = 0.0005) -> dict:
    """반사실 확인  — **손실이 없었다면** SRM이 해소되는가.

    인과를 단정하지 않는다. "손실을 되돌리면 비율이 기대에 맞는다"는 사실만 보고하고,
    그래도 안 맞으면 기대 비율 설정이나 모집단 쪽을 보라고 분기한다.
    """
    if lost is None or lost.empty:
        return {"available": False}
    restored = pd.concat([kept[[group_col]], lost[[group_col]]])
    before = srm(restored[group_col].value_counts().to_dict(), expected_ratio, p_threshold)
    return {"available": True, "resolved": not before.hit,
            "p_restored": before.numbers.get("p"),
            "counts_restored": before.numbers.get("observed", {})}


# ── GR-03 손실·조인  ───────────────────────────────────
def retention_funnel(steps: list[dict]) -> list[Signal]:
    """단계별 잔존율 — 어디서 얼마나 빠졌는지 표로 보여준다."""
    out = []
    for st in steps:
        before, after = st["n_before"], st["n_after"]
        if before <= 0:
            continue
        rate = after / before
        out.append(Signal("GR-03", "retention", rate < 1.0, "diagnostic",
                          detail=msg("guard_gr03_retention", step=st["label"],
                                     before=before, after=after, rate=rate),
                          numbers={"n_before": before, "n_after": after,
                                   "rate": rate, "lost": before - after}))
    return out


def loss_by_group(df_before: pd.DataFrame, kept_index, group_col: str) -> Signal:
    """군별 손실률 ( 원인 추적 입력) — 전체 손실률과의 편차를 함께 낸다."""
    lost_mask = ~df_before.index.isin(kept_index)
    overall = float(lost_mask.mean())
    rates = {}
    for level, idx in df_before.groupby(group_col, observed=True).groups.items():
        sub = lost_mask[df_before.index.get_indexer(idx)]
        rates[str(level)] = float(np.mean(sub))
    spread = (max(rates.values()) - min(rates.values())) if rates else 0.0
    return Signal("GR-03", "loss_by_group", spread > 0.05, "diagnostic",
                  detail=msg("guard_gr03_loss_by_group", overall=overall, spread=spread),
                  numbers={"overall": overall, "by_group": rates, "spread": spread},
                  columns=[group_col])


def biased_loss(df_before: pd.DataFrame, kept_index, cols: list[str],
                p_threshold: float = 0.01) -> list[Signal]:
    """손실이 라벨·군·메타와 연관되는가 — 연관되면 무작위 손실이 아니다 (gate)."""
    from scipy import stats

    lost = ~df_before.index.isin(kept_index)
    if lost.sum() == 0 or lost.all():
        return []
    out = []
    for c in cols:
        if c not in df_before.columns:
            continue
        s = df_before[c]
        if s.dropna().nunique() < 2:
            continue
        if pd.api.types.is_numeric_dtype(s) and s.nunique() > 10:
            a, b = s[lost].dropna(), s[~lost].dropna()
            if len(a) < 2 or len(b) < 2:
                continue
            sd = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
            d = float(abs(a.mean() - b.mean()) / sd) if sd > 0 else 0.0
            _, p = stats.ttest_ind(a, b, equal_var=False)
            hit = bool(p < p_threshold and d >= 0.1)
            out.append(Signal("GR-03", "biased_loss", hit, "gate",
                              detail=msg("guard_gr03_bias_numeric", col=c, smd=d, p=p),
                              numbers={"smd": d, "p": float(p)}, columns=[c]))
        else:
            tab = pd.crosstab(s, lost)
            if tab.shape[0] < 2 or tab.shape[1] < 2:
                continue
            chi2, p, _, _ = stats.chi2_contingency(tab)
            out.append(Signal("GR-03", "biased_loss", bool(p < p_threshold), "gate",
                              detail=msg("guard_gr03_bias_categorical", col=c, p=p),
                              numbers={"chi2": float(chi2), "p": float(p)}, columns=[c]))
    return [s for s in out if s.hit]


def join_rate(n_left: int, n_matched: int, gate: float = 0.90,
              warn: float = 0.98) -> Signal:
    """조인 매칭률 — 낮으면 차단. 조인 기능이 없으면 호출되지 않는다."""
    rate = n_matched / n_left if n_left else 1.0
    return Signal("GR-03", "join_rate", rate < warn,
                  "gate" if rate < gate else "diagnostic",
                  detail=msg("guard_gr03_join", matched=n_matched, left=n_left, rate=rate),
                  numbers={"rate": rate, "n_left": n_left, "n_matched": n_matched})


# ── GR-04 관측 불균형  ─────────────────────────────────
def group_balance(df: pd.DataFrame, group_col: str, min_n: int = 10,
                  severe_n: int = 5, imbalance_ratio: float = 1.5) -> list[Signal]:
    """그룹별 n 편차와 소표본."""
    counts = df[group_col].value_counts().to_dict()
    if not counts:
        return []
    lo, hi = min(counts.values()), max(counts.values())
    out = []
    if lo < severe_n:
        out.append(Signal("GR-04", "tiny_group", True, "gate",
                          detail=msg("guard_gr04_tiny", n=lo, limit=severe_n),
                          numbers={"min_n": lo, "counts": counts}, columns=[group_col]))
    elif lo < min_n:
        out.append(Signal("GR-04", "small_group", True, "diagnostic",
                          detail=msg("guard_gr04_small", n=lo, limit=min_n),
                          numbers={"min_n": lo, "counts": counts}, columns=[group_col]))
    if lo > 0 and hi / lo > imbalance_ratio:
        out.append(Signal("GR-04", "imbalance", True, "diagnostic",
                          detail=msg("guard_gr04_imbalance", ratio=hi / lo, hi=hi, lo=lo),
                          numbers={"ratio": hi / lo, "counts": counts}, columns=[group_col]))
    return out


def coverage(df: pd.DataFrame, cols: list[str], threshold: float = 0.80) -> list[Signal]:
    """지표 커버리지 — 지표가 정의된 행 비율. 낮으면 '부분 지표'다."""
    out = []
    for c in cols:
        if c not in df.columns:
            continue
        cov = float(df[c].notna().mean())
        if cov < threshold:
            out.append(Signal("GR-04", "coverage", True, "diagnostic",
                              detail=msg("guard_gr04_coverage", col=c, cov=cov,
                                         limit=threshold),
                              numbers={"coverage": cov}, columns=[c]))
    return out


def smd_imbalance(df: pd.DataFrame, group_col: str, meta_cols: list[str],
                  threshold: float = 0.10) -> list[Signal]:
    """균형처럼 보이는 불균형 — 라벨은 50:50인데 메타가 편중된 경우 (SC-BE-09)."""
    levels = df[group_col].dropna().unique()
    if len(levels) != 2:
        return []      # 3군 이상의 SMD는 정의가 갈린다 — v1은 2군만 본다
    a_mask, b_mask = df[group_col] == levels[0], df[group_col] == levels[1]
    out = []
    for c in meta_cols:
        if c not in df.columns or c == group_col:
            continue
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            a, b = s[a_mask].dropna(), s[b_mask].dropna()
            if len(a) < 2 or len(b) < 2:
                continue
            sd = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
            d = float(abs(a.mean() - b.mean()) / sd) if sd > 0 else 0.0
        else:
            pa = pd.crosstab(s, df[group_col], normalize="columns")
            if pa.shape[1] < 2:
                continue
            p1, p2 = pa.iloc[:, 0], pa.iloc[:, 1]
            pooled = ((p1 + p2) / 2 * (1 - (p1 + p2) / 2)).sum()
            d = float(abs(p1 - p2).sum() / np.sqrt(pooled)) if pooled > 0 else 0.0
        if d >= threshold:
            # 군당 n을 함께 싣는다 — SMD 0.1은 표본이 작으면 우연만으로도 나온다.
            # 임계는 규칙 DB의 것이므로 바꾸지 않고, 판단 재료를 같이 준다
            n_a, n_b = int(a_mask.sum()), int(b_mask.sum())
            noise = float(np.sqrt(1 / n_a + 1 / n_b)) if n_a and n_b else float("nan")
            out.append(Signal("GR-04", "meta_imbalance", True, "diagnostic",
                              detail=msg("guard_gr04_smd", col=c, smd=d, limit=threshold)
                              + msg("guard_gr04_smd_noise", noise=noise),
                              numbers={"smd": d, "n_a": n_a, "n_b": n_b,
                                       "chance_level": noise}, columns=[c]))
    return out


def metric_stability(df: pd.DataFrame, group_col: str, value_col: str,
                     min_n: int = 10, n_boot: int = 200, seed: int = 0) -> list[Signal]:
    """소표본 그룹의 지표 부트스트랩 CI 폭 (P-231) — 넓으면 그 수치를 믿기 어렵다."""
    rng = np.random.default_rng(seed)
    out = []
    for level, sub in df.groupby(group_col, observed=True):
        s = pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy()
        if len(s) < 2 or len(s) >= min_n:
            continue
        boots = [rng.choice(s, len(s), replace=True).mean() for _ in range(n_boot)]
        lo, hi = np.percentile(boots, [2.5, 97.5])
        spread = float(hi - lo)
        rel = spread / abs(float(np.mean(s))) if np.mean(s) else float("inf")
        out.append(Signal("GR-04", "metric_stability", True, "diagnostic",
                          detail=msg("guard_gr04_stability", level=level, col=value_col,
                                     n=len(s), lo=lo, hi=hi),
                          numbers={"n": len(s), "ci_low": float(lo), "ci_high": float(hi),
                                   "width": spread, "relative_width": rel},
                          columns=[value_col]))
    return out
