"""S152 검정 실행 — 후보(A2)에서 고른 T-xxx 를 실제로 돌리고 **효과크기·CI를 항상 동반**한다.

p값만 주지 않는다 (P-20x): 효과의 크기와 불확실성이 없으면 "유의하다"는 말은
아무것도 알려주지 않는다. 구현되지 않은 검정은 그렇다고 말한다 — 비슷한 걸로
조용히 대체하지 않는다.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statop.messages import msg


@dataclass
class TestOutcome:
    id: str
    name: str
    statistic: float | None
    p: float | None
    effect: dict = field(default_factory=dict)   # {name, value, ci_low, ci_high}
    n: dict = field(default_factory=dict)
    direction: str = "two-sided"
    notes: list[str] = field(default_factory=list)
    # 층화(by) 결과 — 전체 하나로 뭉뚱그리면 군마다 방향이 뒤집히는 것을 놓친다
    strata: list[dict] = field(default_factory=list)


def _two_groups(df: pd.DataFrame, y: str, group: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    parts = [(str(g), sub[y].dropna().to_numpy(dtype="float64"))
             for g, sub in df.groupby(group, observed=True)]
    if len(parts) != 2:
        raise ValueError(msg("run_need_two_groups", n=len(parts)))
    (na, a), (nb, b) = parts
    return a, b, [na, nb]


def _hedges_g(a: np.ndarray, b: np.ndarray) -> dict:
    n1, n2 = a.size, b.size
    sp = np.sqrt(((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2))
    d = (a.mean() - b.mean()) / sp if sp > 0 else 0.0
    j = 1 - 3 / (4 * (n1 + n2) - 9)                  # 소표본 보정
    g = d * j
    se = np.sqrt((n1 + n2) / (n1 * n2) + g ** 2 / (2 * (n1 + n2)))
    return {"name": "Hedges g", "value": float(g),
            "ci_low": float(g - 1.96 * se), "ci_high": float(g + 1.96 * se)}


def _mean_diff_ci(a: np.ndarray, b: np.ndarray) -> dict:
    from scipy import stats

    diff = float(a.mean() - b.mean())
    se = float(np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size))
    dof = (a.var(ddof=1) / a.size + b.var(ddof=1) / b.size) ** 2 / (
        (a.var(ddof=1) / a.size) ** 2 / (a.size - 1)
        + (b.var(ddof=1) / b.size) ** 2 / (b.size - 1))
    t = float(stats.t.ppf(0.975, dof))
    return {"name": "mean diff", "value": diff,
            "ci_low": diff - t * se, "ci_high": diff + t * se}


def _rank_biserial(a: np.ndarray, b: np.ndarray, u: float) -> dict:
    """r = 2U/(nm) − 1 — **첫 군이 크면 양수**.

    부호를 뒤집어 쓰면 (1 − 2U/(nm)) 다른 효과크기와 방향이 반대로 나가고, 가설 문장의
    "어느 군이 크다"가 뒤집힌다. 실측으로 A 가 명백히 큰 자료에서 P(X>Y)=+0.9997,
    Hedges g=+5.11 인데 rank-biserial 만 −0.9994 였다.
    """
    nm = a.size * b.size
    rb = 2 * u / nm - 1
    # CI 는 부트스트랩 — 정확식이 없다. 500회면 화면용으로 충분하고 1초 안이다
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(500):
        aa = rng.choice(a, a.size, replace=True)
        bb = rng.choice(b, b.size, replace=True)
        from scipy.stats import mannwhitneyu

        uu = mannwhitneyu(aa, bb, alternative="two-sided").statistic
        boots.append(2 * uu / nm - 1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"name": "rank-biserial", "value": float(rb),
            "ci_low": float(lo), "ci_high": float(hi)}


def _fisher_z_ci(r: float, n: int) -> tuple[float, float]:
    z = np.arctanh(max(-0.999999, min(0.999999, r)))
    se = 1 / np.sqrt(max(4, n) - 3)
    return float(np.tanh(z - 1.96 * se)), float(np.tanh(z + 1.96 * se))


# ── 검정별 실행 함수 ─────────────────────────────────────────
def _welch(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.ttest_ind(a, b, equal_var=False, alternative=alternative)
    out = TestOutcome("T-101", "Welch t-test", float(r.statistic), float(r.pvalue),
                      effect=_hedges_g(a, b),
                      n={names[0]: int(a.size), names[1]: int(b.size)})
    out.notes.append(msg("run_note_meandiff", **{k: round(v, 6) for k, v in
                                                 _mean_diff_ci(a, b).items()
                                                 if k != "name"}))
    return out


def _student(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.ttest_ind(a, b, equal_var=True, alternative=alternative)
    return TestOutcome("T-102", "Student t-test", float(r.statistic), float(r.pvalue),
                       effect=_hedges_g(a, b),
                       n={names[0]: int(a.size), names[1]: int(b.size)})


def _mwu(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.mannwhitneyu(a, b, alternative=alternative)
    return TestOutcome("T-103", "Mann–Whitney U", float(r.statistic), float(r.pvalue),
                       effect=_rank_biserial(a, b, float(r.statistic)),
                       n={names[0]: int(a.size), names[1]: int(b.size)})


def _brunner_munzel(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.brunnermunzel(a, b, alternative=alternative)
    # 확률적 우위 P(X>Y) + 0.5 P(X=Y)
    gt = float((a[:, None] > b[None, :]).mean())
    eq = float((a[:, None] == b[None, :]).mean())
    return TestOutcome("T-104", "Brunner–Munzel", float(r.statistic), float(r.pvalue),
                       effect={"name": "P(X>Y)", "value": gt + 0.5 * eq,
                               "ci_low": None, "ci_high": None},
                       n={names[0]: int(a.size), names[1]: int(b.size)})


def _perm_t(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)

    def statistic(x, z):
        return np.mean(x) - np.mean(z)

    r = stats.permutation_test((a, b), statistic, alternative=alternative,
                               n_resamples=2000, random_state=0)
    return TestOutcome("T-105", "Permutation t", float(r.statistic), float(r.pvalue),
                       effect=_mean_diff_ci(a, b),
                       n={names[0]: int(a.size), names[1]: int(b.size)})


def _paired_t(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    if a.size != b.size:
        raise ValueError(msg("run_paired_unequal", a=a.size, b=b.size))
    r = stats.ttest_rel(a, b, alternative=alternative)
    dz = float((a - b).mean() / ((a - b).std(ddof=1) or 1))
    return TestOutcome("T-111", "Paired t-test", float(r.statistic), float(r.pvalue),
                       effect={"name": "dz", "value": dz, "ci_low": None, "ci_high": None},
                       n={"pairs": int(a.size)})


def _wilcoxon(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    if a.size != b.size:
        raise ValueError(msg("run_paired_unequal", a=a.size, b=b.size))
    r = stats.wilcoxon(a, b, alternative=alternative)
    return TestOutcome("T-112", "Wilcoxon signed-rank", float(r.statistic),
                       float(r.pvalue), n={"pairs": int(a.size)})


def _anova(df, y, group, alternative):
    from scipy import stats

    parts = [sub[y].dropna().to_numpy(dtype="float64")
             for _, sub in df.groupby(group, observed=True)]
    r = stats.f_oneway(*parts)
    grand = np.concatenate(parts)
    ss_b = sum(p.size * (p.mean() - grand.mean()) ** 2 for p in parts)
    ss_t = float(((grand - grand.mean()) ** 2).sum())
    eta2 = ss_b / ss_t if ss_t > 0 else 0.0
    return TestOutcome("T-121", "One-way ANOVA", float(r.statistic), float(r.pvalue),
                       effect={"name": "eta^2", "value": float(eta2),
                               "ci_low": None, "ci_high": None},
                       n={"groups": len(parts), "total": int(grand.size)})


def _kruskal(df, y, group, alternative):
    from scipy import stats

    parts = [sub[y].dropna().to_numpy(dtype="float64")
             for _, sub in df.groupby(group, observed=True)]
    r = stats.kruskal(*parts)
    n = sum(p.size for p in parts)
    eps2 = (float(r.statistic) - len(parts) + 1) / (n - len(parts)) if n > len(parts) else 0.0
    return TestOutcome("T-123", "Kruskal–Wallis", float(r.statistic), float(r.pvalue),
                       effect={"name": "epsilon^2", "value": max(0.0, eps2),
                               "ci_low": None, "ci_high": None},
                       n={"groups": len(parts), "total": int(n)})


def _chi2(df, y, group, alternative):
    from scipy import stats

    tab = pd.crosstab(df[y], df[group])
    chi2, p, dof, _ = stats.chi2_contingency(tab)
    n = int(tab.to_numpy().sum())
    k = min(tab.shape) - 1
    v = float(np.sqrt(chi2 / (n * k))) if n * k > 0 else 0.0
    # **2×2 면 방향 있는 효과크기(OR)를 쓴다.** Cramér V 는 항상 양수라 방향이 없고,
    # 그러면 층별로 방향이 뒤집히는 것(심슨 역설)을 **원리적으로 못 잡는다** —
    # 내부 사례 #5 가 그대로 지나갔다
    if tab.shape == (2, 2):
        a, b, c, d = (float(x) + 0.5 for x in tab.to_numpy().ravel())  # Haldane 보정
        odds = (a * d) / (b * c)
        return TestOutcome("T-201", "Chi-square", float(chi2), float(p),
                           effect={"name": "OR", "value": float(odds),
                                   "ci_low": None, "ci_high": None},
                           n={"table": "2x2", "total": n},
                           notes=[msg("run_note_or_for_2x2", v=v)])
    return TestOutcome("T-201", "Chi-square", float(chi2), float(p),
                       effect={"name": "Cramér V", "value": v,
                               "ci_low": None, "ci_high": None},
                       n={"table": f"{tab.shape[0]}x{tab.shape[1]}", "total": n})


def _fisher(df, y, group, alternative):
    from scipy import stats

    tab = pd.crosstab(df[y], df[group])
    if tab.shape != (2, 2):
        raise ValueError(msg("run_fisher_needs_2x2", shape=f"{tab.shape[0]}x{tab.shape[1]}"))
    odds, p = stats.fisher_exact(tab, alternative=alternative)
    a, b, c, d = tab.to_numpy().ravel().astype(float)
    if min(a, b, c, d) > 0:
        se = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        lo, hi = np.exp(np.log(odds) - 1.96 * se), np.exp(np.log(odds) + 1.96 * se)
    else:
        lo = hi = None
    return TestOutcome("T-202", "Fisher exact", float(odds), float(p),
                       effect={"name": "OR", "value": float(odds),
                               "ci_low": lo, "ci_high": hi},
                       n={"total": int(tab.to_numpy().sum())})


def _pearson(df, y, group, alternative):
    from scipy import stats

    sub = df[[y, group]].dropna()
    r = stats.pearsonr(sub[y], sub[group], alternative=alternative)
    lo, hi = _fisher_z_ci(float(r.statistic), len(sub))
    return TestOutcome("T-301", "Pearson r", float(r.statistic), float(r.pvalue),
                       effect={"name": "r", "value": float(r.statistic),
                               "ci_low": lo, "ci_high": hi}, n={"pairs": len(sub)})


def _spearman(df, y, group, alternative):
    from scipy import stats

    sub = df[[y, group]].dropna()
    r = stats.spearmanr(sub[y], sub[group], alternative=alternative)
    lo, hi = _fisher_z_ci(float(r.statistic), len(sub))
    return TestOutcome("T-302", "Spearman ρ", float(r.statistic), float(r.pvalue),
                       effect={"name": "rho", "value": float(r.statistic),
                               "ci_low": lo, "ci_high": hi}, n={"pairs": len(sub)})


def _kendall(df, y, group, alternative):
    from scipy import stats

    sub = df[[y, group]].dropna()
    r = stats.kendalltau(sub[y], sub[group], alternative=alternative)
    return TestOutcome("T-303", "Kendall τ", float(r.statistic), float(r.pvalue),
                       effect={"name": "tau", "value": float(r.statistic),
                               "ci_low": None, "ci_high": None}, n={"pairs": len(sub)})



def _ordered_groups(df: pd.DataFrame, y: str, group: str) -> tuple[list, list[np.ndarray]]:
    """군을 **순서대로** 돌려준다 — 추세 검정은 군 순서가 곧 가설이다.

    숫자로 읽히면 숫자 순, 아니면 문자열 순. 라벨을 0/1/2로 매핑해 뒀다면
    그 코드 순서가 그대로 추세의 방향이 된다.
    """
    from statop.semantic import order_key

    parts = {str(g): sub[y].dropna().to_numpy(dtype="float64")
             for g, sub in df.groupby(group, observed=True)}
    levels = sorted(parts, key=order_key)
    if len(levels) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(levels)))
    return levels, [parts[k] for k in levels]


def _scores(levels: list[str]) -> np.ndarray:
    """군 점수 — 숫자면 그 값, 아니면 0,1,2… 등간격으로 둔다."""
    try:
        return np.array([float(x) for x in levels])
    except ValueError:
        return np.arange(len(levels), dtype="float64")


def _paired_numeric(df: pd.DataFrame, a: str, b: str) -> tuple[np.ndarray, np.ndarray, int]:
    """두 수치 컬럼을 행 단위로 맞춘다 (결측 행 제거). 일치도·비례성·회귀의 공통 입구."""
    if b is None:
        raise ValueError(msg("run_need_second_column"))
    sub = df[[a, b]].apply(pd.to_numeric, errors="coerce").dropna()
    if sub.empty:
        raise ValueError(msg("run_need_numeric", cols=f"{a}, {b}"))
    return (sub[a].to_numpy(dtype="float64"), sub[b].to_numpy(dtype="float64"), len(sub))


def _positive_pairs(x: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """로그를 씌우기 전에 0·음수 행을 뺀다 — eps를 몰래 더하면 값이 조용히 달라진다."""
    keep = (x > 0) & (z > 0)
    return x[keep], z[keep], int((~keep).sum())


# ── Q-05 경향/추세 ───────────────────────────────────────────
def _jonckheere(df, y, group, alternative):
    from scipy import stats

    levels, parts = _ordered_groups(df, y, group)
    jt = 0.0
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i], parts[j]
            jt += float((a[:, None] < b[None, :]).sum()) + 0.5 * float(
                (a[:, None] == b[None, :]).sum())
    sizes = np.array([p.size for p in parts], dtype="float64")
    n = sizes.sum()
    mean = (n ** 2 - (sizes ** 2).sum()) / 4
    var = (n ** 2 * (2 * n + 3) - (sizes ** 2 * (2 * sizes + 3)).sum()) / 72
    z = (jt - mean) / np.sqrt(var) if var > 0 else 0.0
    p = (stats.norm.sf(abs(z)) * 2 if alternative == "two-sided"
         else stats.norm.sf(z) if alternative == "greater" else stats.norm.cdf(z))
    # 효과크기는 군 점수와 y 사이의 tau — JT 통계량 자체는 크기를 읽을 수 없다
    codes = np.concatenate([np.full(p_.size, s) for p_, s in zip(parts, _scores(levels))])
    tau = stats.kendalltau(codes, np.concatenate(parts))
    out = TestOutcome("T-501", "Jonckheere–Terpstra", float(z), float(p),
                      effect={"name": "tau-b", "value": float(tau.statistic),
                              "ci_low": None, "ci_high": None},
                      n={"groups": len(parts), "total": int(n)})
    out.notes.append(msg("run_note_order", order=" < ".join(levels)))
    return out


def _cochran_armitage(df, y, group, alternative):
    from scipy import stats

    levels, parts = _ordered_groups(df, y, group)
    vals = np.unique(np.concatenate(parts))
    if vals.size != 2:
        raise ValueError(msg("run_need_binary_y", col=y, n=int(vals.size)))
    hi = vals.max()
    t = _scores(levels)
    ni = np.array([p.size for p in parts], dtype="float64")
    xi = np.array([float((p == hi).sum()) for p in parts])
    n, r = ni.sum(), xi.sum()
    pbar = r / n
    stat = float((t * (xi - ni * pbar)).sum())
    var = pbar * (1 - pbar) * float((ni * t ** 2).sum() - (ni * t).sum() ** 2 / n)
    z = stat / np.sqrt(var) if var > 0 else 0.0
    p = (stats.norm.sf(abs(z)) * 2 if alternative == "two-sided"
         else stats.norm.sf(z) if alternative == "greater" else stats.norm.cdf(z))
    # 군당 비율을 군 크기로 가중해 직선을 맞춘다 — z 만으로는 추세의 크기를 못 읽는다
    slope = float(np.polyfit(t, xi / ni, 1, w=np.sqrt(ni))[0])
    out = TestOutcome("T-502", "Cochran–Armitage", float(z), float(p),
                      effect={"name": "proportion/score", "value": slope,
                              "ci_low": None, "ci_high": None},
                      n={"groups": len(parts), "total": int(n)})
    out.notes.append(msg("run_note_order", order=" < ".join(levels)))
    out.notes.append(msg("run_note_ca_rates", rates=", ".join(
        f"{lv}={x / m:.3f}" for lv, x, m in zip(levels, xi, ni))))
    return out


def _mann_kendall(df, y, group, alternative):
    from scipy import stats

    sub = df[[y, group]].apply(pd.to_numeric, errors="coerce").dropna()
    if sub.empty:
        raise ValueError(msg("run_need_numeric", cols=f"{y}, {group}"))
    x, yy = sub[group].to_numpy("float64"), sub[y].to_numpy("float64")
    order = np.argsort(x, kind="stable")
    x, yy = x[order], yy[order]
    s = float(np.sign(yy[None, :] - yy[:, None])[np.triu_indices(yy.size, 1)].sum())
    r = stats.kendalltau(x, yy, alternative=alternative)
    sen = stats.theilslopes(yy, x, 0.95)
    out = TestOutcome("T-503", "Mann–Kendall", s, float(r.pvalue),
                      effect={"name": "Sen slope", "value": float(sen.slope),
                              "ci_low": float(sen.low_slope),
                              "ci_high": float(sen.high_slope)},
                      n={"points": int(yy.size)})
    out.notes.append(msg("run_note_mk_tau", tau=float(r.statistic), s=s))
    return out


def _trend_ols(df, y, group, alternative):
    from scipy import stats

    yy, x, n = _paired_numeric(df, y, group)
    r = stats.linregress(x, yy, alternative=alternative)
    t = float(stats.t.ppf(0.975, n - 2))
    out = TestOutcome("T-504", "Linear regression slope", float(r.slope / r.stderr)
                      if r.stderr else None, float(r.pvalue),
                      effect={"name": f"slope ({y}/{group})", "value": float(r.slope),
                              "ci_low": float(r.slope - t * r.stderr),
                              "ci_high": float(r.slope + t * r.stderr)},
                      n={"points": n})
    out.notes.append(msg("run_note_r2", r2=float(r.rvalue ** 2),
                         intercept=float(r.intercept)))
    return out


# ── Q-07 분포 비교 (형태 자체) ───────────────────────────────
def _ks2(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.ks_2samp(a, b, alternative=alternative)
    out = TestOutcome("T-701", "Kolmogorov–Smirnov 2-sample", float(r.statistic),
                      float(r.pvalue),
                      effect={"name": msg("run_eff_ks_d"), "value": float(r.statistic),
                              "ci_low": None, "ci_high": None},
                      n={names[0]: int(a.size), names[1]: int(b.size)})
    out.notes.append(msg("run_note_shape_only"))
    return out


def _anderson_k(df, y, group, alternative):
    from scipy import stats

    parts = [sub[y].dropna().to_numpy(dtype="float64")
             for _, sub in df.groupby(group, observed=True)]
    r = stats.anderson_ksamp(parts, variant="midrank",
                             method=stats.PermutationMethod(n_resamples=999,
                                                            random_state=0))
    out = TestOutcome("T-702", "Anderson–Darling k-sample", float(r.statistic),
                      float(r.pvalue), n={"groups": len(parts),
                                          "total": int(sum(p.size for p in parts))})
    out.notes.append(msg("run_note_shape_only"))
    out.notes.append(msg("run_note_perm_p", n=999))
    return out


def _energy(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.permutation_test((a, b), lambda x, z: stats.energy_distance(x, z),
                               alternative="greater", n_resamples=999, random_state=0)
    out = TestOutcome("T-703", "Energy distance permutation", float(r.statistic),
                      float(r.pvalue),
                      effect={"name": "energy distance", "value": float(r.statistic),
                              "ci_low": None, "ci_high": None},
                      n={names[0]: int(a.size), names[1]: int(b.size)})
    out.notes.append(msg("run_note_shape_only"))
    out.notes.append(msg("run_note_perm_p", n=999))
    return out


def _cvm(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    r = stats.cramervonmises_2samp(a, b)
    out = TestOutcome("T-704", "Cramér–von Mises", float(r.statistic), float(r.pvalue),
                      n={names[0]: int(a.size), names[1]: int(b.size)})
    out.notes.append(msg("run_note_shape_only"))
    return out


# ── Q-03 / Q-10 비례성 ──────────────────────────────────────
def _proportionality(df, y, group, alternative):
    """조성 두 성분의 비례성 (Lovell φ, Erb ρ_p) — 상관이 아니라 로그비의 변동을 본다."""
    x, z, n = _paired_numeric(df, y, group)
    x, z, dropped = _positive_pairs(x, z)
    if x.size < 3:
        raise ValueError(msg("run_need_positive", n=int(x.size)))
    lx, lz = np.log(x), np.log(z)
    vr = float(np.var(lx - lz, ddof=1))
    vx, vz = float(np.var(lx, ddof=1)), float(np.var(lz, ddof=1))
    phi = vr / vx if vx > 0 else float("inf")
    rho = 1 - vr / (vx + vz) if (vx + vz) > 0 else 0.0
    out = TestOutcome("T-321", "Proportionality (ρ_p, φ)", float(phi), None,
                      effect={"name": "rho_p", "value": float(rho),
                              "ci_low": None, "ci_high": None},
                      n={"pairs": int(x.size)})
    out.notes.append(msg("run_note_prop", phi=float(phi), vr=vr))
    out.notes.append(msg("run_note_no_p"))
    if dropped:
        out.notes.append(msg("run_note_dropped_nonpositive", n=dropped))
    return out


# ── Q-06 일치도/재현성 ──────────────────────────────────────
def _boot_ci(fn, x: np.ndarray, z: np.ndarray, n: int = 500) -> tuple[float, float]:
    """짝을 통째로 다시 뽑는 부트스트랩 — 일치도 지표에는 닫힌 형태의 CI가 없다."""
    rng = np.random.default_rng(0)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, x.size, x.size)
        try:
            vals.append(fn(x[idx], z[idx]))
        except (ValueError, ZeroDivisionError):
            continue
    if not vals:
        return None, None
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def _icc21(x: np.ndarray, z: np.ndarray) -> float:
    """ICC(2,1) 이원 랜덤·절대일치 — 두 번 잰 값이 얼마나 같은 값인가."""
    m = np.column_stack([x, z])
    n, k = m.shape
    gm = m.mean()
    ms_r = k * float(((m.mean(axis=1) - gm) ** 2).sum()) / (n - 1)
    ms_c = n * float(((m.mean(axis=0) - gm) ** 2).sum()) / (k - 1)
    ss_e = float(((m - m.mean(axis=1, keepdims=True) - m.mean(axis=0, keepdims=True)
                   + gm) ** 2).sum())
    ms_e = ss_e / ((n - 1) * (k - 1))
    den = ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n
    return float((ms_r - ms_e) / den) if den != 0 else 0.0


def _icc(df, y, group, alternative):
    from scipy import stats

    x, z, n = _paired_numeric(df, y, group)
    val = _icc21(x, z)
    lo, hi = _boot_ci(_icc21, x, z)
    # F 검정: 피험자 간 분산이 잔차보다 큰가 (ICC=0 이라는 귀무가설)
    m = np.column_stack([x, z])
    ms_r = 2 * float(((m.mean(axis=1) - m.mean()) ** 2).sum()) / (n - 1)
    ss_e = float(((m - m.mean(axis=1, keepdims=True) - m.mean(axis=0, keepdims=True)
                   + m.mean()) ** 2).sum())
    ms_e = ss_e / (n - 1)
    f = ms_r / ms_e if ms_e > 0 else float("inf")
    out = TestOutcome("T-601", msg("run_name_icc"), float(f),
                      float(stats.f.sf(f, n - 1, n - 1)),
                      effect={"name": "ICC(2,1)", "value": val, "ci_low": lo,
                              "ci_high": hi}, n={"subjects": n, "raters": 2})
    out.notes.append(msg("run_note_icc_model"))
    return out


def _bland_altman(df, y, group, alternative):
    from scipy import stats

    x, z, n = _paired_numeric(df, y, group)
    d = x - z
    bias, sd = float(d.mean()), float(d.std(ddof=1))
    se = sd / np.sqrt(n)
    t = float(stats.t.ppf(0.975, n - 1))
    r = stats.ttest_1samp(d, 0.0, alternative=alternative)
    out = TestOutcome("T-602", "Bland–Altman", float(r.statistic), float(r.pvalue),
                      effect={"name": f"bias ({y}-{group})", "value": bias,
                              "ci_low": bias - t * se, "ci_high": bias + t * se},
                      n={"pairs": n})
    out.notes.append(msg("run_note_loa", lo=bias - 1.96 * sd, hi=bias + 1.96 * sd))
    # 차이가 크기에 따라 커지면 고정 LoA 는 못 쓴다 — 비례오차를 함께 본다
    prop = stats.pearsonr((x + z) / 2, d)
    out.notes.append(msg("run_note_ba_proportional", r=float(prop.statistic),
                         p=float(prop.pvalue)))
    return out


def _ccc(x: np.ndarray, z: np.ndarray) -> float:
    vx, vz = float(x.var(ddof=0)), float(z.var(ddof=0))
    cov = float(((x - x.mean()) * (z - z.mean())).mean())
    den = vx + vz + (x.mean() - z.mean()) ** 2
    return float(2 * cov / den) if den > 0 else 0.0


def _lins_ccc(df, y, group, alternative):
    x, z, n = _paired_numeric(df, y, group)
    val = _ccc(x, z)
    lo, hi = _boot_ci(_ccc, x, z)
    from scipy import stats

    r = stats.pearsonr(x, z)
    out = TestOutcome("T-603", "Lin's CCC", None, None,
                      effect={"name": "CCC", "value": val, "ci_low": lo, "ci_high": hi},
                      n={"pairs": n})
    # CCC = 상관(정밀도) x 보정계수(정확도). 둘을 나눠 봐야 무엇이 문제인지 안다
    cb = val / float(r.statistic) if r.statistic else 0.0
    out.notes.append(msg("run_note_ccc_parts", r=float(r.statistic), cb=cb))
    out.notes.append(msg("run_note_no_p"))
    return out


def _kappa_tab(df, a: str, b: str):
    if b is None:
        raise ValueError(msg("run_need_second_column"))
    sub = df[[a, b]].dropna().astype(str)
    cats = sorted(set(sub[a]) | set(sub[b]))
    if len(cats) < 2:
        raise ValueError(msg("run_need_two_categories", n=len(cats)))
    tab = pd.crosstab(sub[a], sub[b]).reindex(index=cats, columns=cats, fill_value=0)
    return tab.to_numpy(dtype="float64"), cats


def _kappa(m: np.ndarray, weights: np.ndarray | None = None) -> tuple[float, float, float]:
    n = m.sum()
    obs, exp = m / n, np.outer(m.sum(1), m.sum(0)) / n ** 2
    if weights is None:
        po, pe = float(np.trace(obs)), float(np.trace(exp))
    else:
        po, pe = 1 - float((weights * obs).sum()), 1 - float((weights * exp).sum())
    k = (po - pe) / (1 - pe) if pe != 1 else 0.0
    se = np.sqrt(po * (1 - po) / (n * (1 - pe) ** 2)) if pe != 1 else 0.0
    return float(k), float(se), float(n)


def _cohen_kappa(df, y, group, alternative):
    from scipy import stats

    m, cats = _kappa_tab(df, y, group)
    k, se, n = _kappa(m)
    # 선형 가중 κ — 범주에 순서가 있으면 "한 칸 차이"와 "세 칸 차이"는 같지 않다
    idx = np.arange(len(cats))
    w = np.abs(idx[:, None] - idx[None, :]) / max(1, len(cats) - 1)
    kw, _, _ = _kappa(m, w)
    z = k / se if se > 0 else 0.0
    out = TestOutcome("T-604", "Cohen's κ", float(z), float(stats.norm.sf(abs(z)) * 2),
                      effect={"name": "kappa", "value": k, "ci_low": k - 1.96 * se,
                              "ci_high": k + 1.96 * se},
                      n={"pairs": int(n), "categories": len(cats)})
    out.notes.append(msg("run_note_kappa_weighted", kw=kw))
    out.notes.append(msg("run_note_kappa_prevalence", po=float(np.trace(m / n))))
    return out


def _fleiss(df, y, group, alternative):
    from statsmodels.stats.inter_rater import aggregate_raters, fleiss_kappa

    if group is None:
        raise ValueError(msg("run_need_second_column"))
    sub = df[[y, group]].dropna().astype(str)
    table, cats = aggregate_raters(sub.to_numpy())
    k = float(fleiss_kappa(table))
    out = TestOutcome("T-605", "Fleiss' κ", None, None,
                      effect={"name": "Fleiss kappa", "value": k,
                              "ci_low": None, "ci_high": None},
                      n={"subjects": int(table.shape[0]), "raters": 2,
                         "categories": int(len(cats))})
    out.notes.append(msg("run_note_fleiss_two"))
    out.notes.append(msg("run_note_no_p"))
    return out


# ── Q-08 예측/설명 (회귀) ───────────────────────────────────
def _design(df: pd.DataFrame, y: str, group: str, numeric_y: bool = True):
    """회귀의 입구 — (y, 상수항 붙은 설계행렬, 설명변수 이름들).

    설명변수가 문자·라벨이면 더미로 편다. 기준 범주는 첫 수준이고, 계수는 모두
    "기준 대비"로 읽어야 한다 — 이름에 그대로 드러나게 둔다.
    """
    import statsmodels.api as sm

    if group is None:
        raise ValueError(msg("run_need_second_column"))
    sub = df[[y, group]].dropna()
    yy = pd.to_numeric(sub[y], errors="coerce") if numeric_y else sub[y]
    x = pd.to_numeric(sub[group], errors="coerce")
    if x.isna().all():
        x = pd.get_dummies(sub[group].astype(str), prefix=group, drop_first=True,
                           dtype="float64")
    else:
        x = x.to_frame(group)
    keep = ~(yy.isna() | x.isna().any(axis=1)) if numeric_y else ~x.isna().any(axis=1)
    yy, x = yy[keep], x[keep]
    if len(yy) < 3:
        raise ValueError(msg("run_need_numeric", cols=f"{y}, {group}"))
    return yy, sm.add_constant(x, has_constant="add"), list(x.columns)


def _coef_effect(res, name: str, label: str, exp: bool = False) -> dict:
    """첫 설명변수의 계수와 95% CI. exp=True 면 비(OR·IRR·HR)로 바꾼다."""
    ci = res.conf_int()
    lo, hi = float(ci.loc[name][0]), float(ci.loc[name][1])
    v = float(res.params[name])
    f = np.exp if exp else (lambda q: q)
    return {"name": label, "value": float(f(v)), "ci_low": float(f(lo)),
            "ci_high": float(f(hi))}


def _extra_coefs(res, names: list[str], exp: bool = False) -> list[str]:
    """설명변수가 더미로 여러 개면 나머지도 한 줄씩 — 첫 계수만 보면 오독한다."""
    out = []
    for nm in names[1:]:
        ci = res.conf_int()
        v = float(res.params[nm])
        lo, hi = float(ci.loc[nm][0]), float(ci.loc[nm][1])
        if exp:
            v, lo, hi = np.exp(v), np.exp(lo), np.exp(hi)
        out.append(msg("run_note_coef", name=nm, value=v, lo=lo, hi=hi))
    return out


def _logistic(df, y, group, alternative):
    import statsmodels.api as sm

    yy, x, names = _design(df, y, group)
    vals = np.unique(yy)
    if vals.size != 2:
        raise ValueError(msg("run_need_binary_y", col=y, n=int(vals.size)))
    yb = (yy == vals.max()).astype(float)
    res = sm.Logit(yb, x).fit(disp=0)
    out = TestOutcome("T-801", "Logistic regression",
                      float(res.tvalues[names[0]]), float(res.pvalues[names[0]]),
                      effect=_coef_effect(res, names[0], f"OR ({names[0]})", exp=True),
                      n={"rows": int(len(yy)), "events": int(yb.sum())})
    out.notes.append(msg("run_note_logit_ref", pos=str(vals.max()), neg=str(vals.min())))
    out.notes.append(msg("run_note_pseudo_r2", r2=float(res.prsquared)))
    out.notes += _extra_coefs(res, names, exp=True)
    epv = float(min(yb.sum(), (1 - yb).sum())) / max(1, len(names))
    if epv < 10:
        out.notes.append(msg("run_note_epv", epv=epv))
    return out


def _ols(df, y, group, alternative):
    import statsmodels.api as sm

    yy, x, names = _design(df, y, group)
    res = sm.OLS(yy, x).fit()
    out = TestOutcome("T-802", "Linear regression (OLS)",
                      float(res.tvalues[names[0]]), float(res.pvalues[names[0]]),
                      effect=_coef_effect(res, names[0], f"slope ({names[0]})"),
                      n={"rows": int(len(yy))})
    out.notes.append(msg("run_note_r2_adj", r2=float(res.rsquared),
                         adj=float(res.rsquared_adj)))
    out.notes += _extra_coefs(res, names)
    # 등분산이 깨지면 표준오차가 틀린다 → CI 도 틀린다. 강건 표준오차를 함께 준다
    rob = res.get_robustcov_results(cov_type="HC3")
    i = list(res.params.index).index(names[0])
    out.notes.append(msg("run_note_hc3", se=float(rob.bse[i]), p=float(rob.pvalues[i])))
    return out


def _poisson(df, y, group, alternative):
    import statsmodels.api as sm

    yy, x, names = _design(df, y, group)
    if (yy < 0).any() or not np.allclose(yy, np.round(yy)):
        raise ValueError(msg("run_need_counts", col=y))
    res = sm.GLM(yy, x, family=sm.families.Poisson()).fit()
    disp = float(res.pearson_chi2 / res.df_resid) if res.df_resid else float("nan")
    name, model = "T-803", "Poisson regression"
    if disp > 1.5:
        # 과산포면 Poisson 의 CI 가 좁게 나온다 — 음이항으로 바꿔 다시 맞춘다
        try:
            res = sm.NegativeBinomial(yy, x).fit(disp=0)
            model = "Negative binomial regression"
        except Exception:
            model = msg("run_name_poisson_over")
    out = TestOutcome(name, model, float(res.tvalues[names[0]]),
                      float(res.pvalues[names[0]]),
                      effect=_coef_effect(res, names[0], f"IRR ({names[0]})", exp=True),
                      n={"rows": int(len(yy)), "total_count": int(yy.sum())})
    out.notes.append(msg("run_note_dispersion", disp=disp, model=model))
    out.notes += _extra_coefs(res, names, exp=True)
    return out


def _ordinal(df, y, group, alternative):
    from statsmodels.miscmodels.ordinal_model import OrderedModel

    yy, x, names = _design(df, y, group, numeric_y=False)
    # 순서는 값 자체가 정한다. 숫자(라벨→코드 매핑 결과)면 숫자 순, 아니면 사전 순 —
    # 사전 순은 L<M<H 같은 의도를 맞힐 수 없으므로 아래에서 그 사실을 알린다
    cats = list(pd.unique(yy.astype(str)))
    try:
        cats = sorted(cats, key=float)
        lexical = False
    except ValueError:
        cats, lexical = sorted(cats), True
    if len(cats) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(cats)))
    # 수준이 수십 개면 순서형이 아니라 연속이다. 그대로 맞추면 절편이 수백 개라
    # 몇 분씩 걸리고 결과도 못 읽는다 — 여기서 끊고 무엇을 하라고 말한다
    if len(cats) > 20:
        raise ValueError(msg("run_too_many_levels", col=y, n=len(cats)))
    ycat = pd.Series(pd.Categorical(yy.astype(str), categories=cats, ordered=True),
                     index=yy.index)
    res = OrderedModel(ycat, x.drop(columns="const").astype("float64"),
                       distr="logit").fit(method="bfgs", disp=0)
    out = TestOutcome("T-804", "Ordinal logistic",
                      float(res.tvalues[names[0]]), float(res.pvalues[names[0]]),
                      effect=_coef_effect(res, names[0], f"OR ({names[0]})", exp=True),
                      n={"rows": int(len(yy)), "categories": len(cats)})
    out.notes.append(msg("run_note_ordinal_order", order=" < ".join(cats)))
    if lexical:
        out.notes.append(msg("run_note_ordinal_lexical"))
    out.notes.append(msg("run_note_proportional_odds"))
    out.notes += _extra_coefs(res, names, exp=True)
    return out


def _beta_reg(df, y, group, alternative):
    from statsmodels.othermod.betareg import BetaModel

    yy, x, names = _design(df, y, group)
    if yy.min() < 0 or yy.max() > 1:
        raise ValueError(msg("run_need_unit_interval", col=y, lo=float(yy.min()),
                             cols=f"{yy.min():.4g}~{yy.max():.4g}"))
    n = len(yy)
    squeezed = int(((yy <= 0) | (yy >= 1)).sum())
    z = yy
    if squeezed:
        # 베타 분포는 0·1 을 못 받는다. 표준 축소(Smithson–Verkuilen)로 안쪽으로 민다
        z = (yy * (n - 1) + 0.5) / n
    res = BetaModel(z, x).fit(disp=0)
    out = TestOutcome("T-805", "Beta regression",
                      float(res.tvalues[names[0]]), float(res.pvalues[names[0]]),
                      effect=_coef_effect(res, names[0], f"OR ({names[0]})", exp=True),
                      n={"rows": n})
    out.notes.append(msg("run_note_beta_link"))
    if squeezed:
        out.notes.append(msg("run_note_beta_squeeze", n=squeezed))
    out.notes += _extra_coefs(res, names, exp=True)
    return out


def _robust_reg(df, y, group, alternative):
    import statsmodels.api as sm

    yy, x, names = _design(df, y, group)
    res = sm.RLM(yy, x, M=sm.robust.norms.HuberT()).fit()
    ols = sm.OLS(yy, x).fit()
    out = TestOutcome("T-806", "Robust regression (Huber)",
                      float(res.tvalues[names[0]]), float(res.pvalues[names[0]]),
                      effect=_coef_effect(res, names[0], f"slope ({names[0]})"),
                      n={"rows": int(len(yy))})
    # OLS 와 크게 다르면 몇몇 점이 직선을 끌고 있었다는 뜻이다
    out.notes.append(msg("run_note_robust_vs_ols", ols=float(ols.params[names[0]]),
                         rob=float(res.params[names[0]])))
    w = np.asarray(res.weights)
    out.notes.append(msg("run_note_downweighted", n=int((w < 0.9).sum()),
                         total=int(w.size)))
    out.notes += _extra_coefs(res, names)
    return out


# ── Q-10 조성 데이터 (bio 특화) ─────────────────────────────
def _comp_members(df: pd.DataFrame, y: str) -> list[str]:
    """y가 속한 조성 세트. 세트 전체가 있어야 기하평균이 맞는다 (S-R01/02와 같은 근거)."""
    from statop.semantic import composition_set

    members = sorted(composition_set(df, y) & set(df.columns))
    if len(members) < 2 or y not in members:
        raise ValueError(msg("run_need_composition", col=y))
    return members


def _count_members(df: pd.DataFrame, y: str) -> list[str]:
    """개수로 된 조성 세트 — 행 합이 1로 닫히지 않으므로 composition_set 으로는 못 찾는다.

    개수 조성은 표본마다 총량(library size)이 달라서, 닫힌 값 대신 **같은 이름 접두**나
    전체 음이 아닌 정수 컬럼을 묶음으로 본다.
    """
    import re

    num = df.select_dtypes(include="number")
    ints = [c for c in num.columns
            if (num[c].dropna() >= 0).all()
            and np.allclose(num[c].dropna(), np.round(num[c].dropna()))]
    prefix = re.sub(r"[_\-]?\w?\d*$", "", y)
    if prefix and len(prefix) >= 2:
        grp = [c for c in ints if c.startswith(prefix)]
        if len(grp) >= 2 and y in grp:
            return sorted(grp)
    if len(ints) >= 2 and y in ints:
        return sorted(ints)
    raise ValueError(msg("run_need_count_composition", cols=y))


def _clr_frame(df: pd.DataFrame, members: list[str]) -> tuple[pd.DataFrame, int]:
    """세트 전체를 CLR 변환한다 — 양수 행만 남긴다 (0은 로그를 못 씌운다)."""
    m = df[members].apply(pd.to_numeric, errors="coerce")
    keep = m.notna().all(axis=1) & (m > 0).all(axis=1)
    dropped = int((~keep).sum())
    lg = np.log(m[keep])
    return lg.sub(lg.mean(axis=1), axis=0), dropped


def _comp_compare(df, y, group, alternative, values: pd.Series, keep_idx,
                  tid: str, name: str, extra: list[str]) -> TestOutcome:
    """변환된 값을 군 간에 비교한다 — 2군이면 Welch, 3군 이상이면 ANOVA."""
    from scipy import stats

    sub = pd.DataFrame({y: values, group: df.loc[keep_idx, group]}).dropna()
    parts = [(str(g), g_[y].to_numpy("float64"))
             for g, g_ in sub.groupby(group, observed=True)]
    if len(parts) < 2:
        raise ValueError(msg("run_need_two_groups", n=len(parts)))
    if len(parts) == 2:
        (n1, a), (n2, b) = parts
        r = stats.ttest_ind(a, b, equal_var=False, alternative=alternative)
        out = TestOutcome(tid, name, float(r.statistic), float(r.pvalue),
                          effect=_hedges_g(a, b),
                          n={n1: int(a.size), n2: int(b.size)})
        out.notes.append(msg("run_note_logratio_diff",
                             d=float(a.mean() - b.mean()), a=n1, b=n2))
    else:
        arrs = [p for _, p in parts]
        r = stats.f_oneway(*arrs)
        grand = np.concatenate(arrs)
        ss_b = sum(p.size * (p.mean() - grand.mean()) ** 2 for p in arrs)
        ss_t = float(((grand - grand.mean()) ** 2).sum())
        out = TestOutcome(tid, name, float(r.statistic), float(r.pvalue),
                          effect={"name": "eta^2",
                                  "value": float(ss_b / ss_t) if ss_t > 0 else 0.0,
                                  "ci_low": None, "ci_high": None},
                          n={"groups": len(arrs), "total": int(grand.size)})
    out.notes += extra
    return out


def _clr_compare(df, y, group, alternative):
    members = _comp_members(df, y)
    clr, dropped = _clr_frame(df, members)
    notes = [msg("run_note_comp_set", n=len(members), cols=", ".join(members)),
             msg("run_note_clr_read")]
    if dropped:
        notes.append(msg("run_note_dropped_nonpositive", n=dropped))
    return _comp_compare(df, y, group, alternative, clr[y], clr.index,
                         "T-1001", msg("run_name_clr_compare"), notes)


def _alr_compare(df, y, group, alternative):
    members = _comp_members(df, y)
    m = df[members].apply(pd.to_numeric, errors="coerce")
    keep = m.notna().all(axis=1) & (m > 0).all(axis=1)
    m = m[keep]
    # 기준 성분은 가장 안정한 것(로그 분산 최소)으로 — 기준이 흔들리면 전부 흔들린다
    others = [c for c in members if c != y]
    ref = min(others, key=lambda c: float(np.log(m[c]).var(ddof=1)))
    alr = np.log(m[y] / m[ref])
    notes = [msg("run_note_comp_set", n=len(members), cols=", ".join(members)),
             msg("run_note_alr_ref", ref=ref, y=y)]
    if int((~keep).sum()):
        notes.append(msg("run_note_dropped_nonpositive", n=int((~keep).sum())))
    return _comp_compare(df, y, group, alternative, alr, m.index,
                         "T-1002", msg("run_name_alr_compare"), notes)


def _aldex(df, y, group, alternative):
    """ALDEx2-형 — 개수의 불확실성을 Dirichlet 로 뽑아 CLR 한 뒤, 그 분포로 판단한다."""
    from scipy import stats

    members = _count_members(df, y)
    m = df[members].apply(pd.to_numeric, errors="coerce").dropna()
    g = df.loc[m.index, group]
    keep = g.notna()
    m, g = m[keep], g[keep]
    levels = sorted(set(g.astype(str)))
    if len(levels) != 2:
        raise ValueError(msg("run_need_two_groups", n=len(levels)))
    rng = np.random.default_rng(0)
    counts = m.to_numpy(dtype="float64") + 0.5      # Bayes 사전분포 (Jeffreys)
    ia = (g.astype(str) == levels[0]).to_numpy()
    j = members.index(y)
    ps, es = [], []
    for _ in range(128):                             # MC 인스턴스
        draw = np.array([rng.dirichlet(row) for row in counts])
        clr = np.log(draw) - np.log(draw).mean(axis=1, keepdims=True)
        a, b = clr[ia, j], clr[~ia, j]
        ps.append(float(stats.ttest_ind(a, b, equal_var=False,
                                        alternative=alternative).pvalue))
        es.append(float(a.mean() - b.mean()))
    lo, hi = np.percentile(es, [2.5, 97.5])
    out = TestOutcome("T-1003", msg("run_name_aldex"), None,
                      float(np.median(ps)),
                      effect={"name": msg("run_eff_clr_diff", a=levels[0], b=levels[1]),
                              "value": float(np.median(es)), "ci_low": float(lo),
                              "ci_high": float(hi)},
                      n={levels[0]: int(ia.sum()), levels[1]: int((~ia).sum())})
    out.notes.append(msg("run_note_comp_set", n=len(members), cols=", ".join(members)))
    out.notes.append(msg("run_note_aldex_mc", k=128, pmax=float(np.max(ps))))
    out.notes.append(msg("run_note_clr_read"))
    return out


def _ancombc(df, y, group, alternative):
    """ANCOM-BC-형 (간이) — 표본별 채취량 치우침을 빼고 군 간 로그 차이를 본다."""
    from scipy import stats

    members = _comp_members(df, y)
    clr, dropped = _clr_frame(df, members)
    sub = pd.DataFrame({y: clr[y], group: df.loc[clr.index, group]}).dropna()
    levels = sorted(set(sub[group].astype(str)))
    if len(levels) != 2:
        raise ValueError(msg("run_need_two_groups", n=len(levels)))
    a = sub.loc[sub[group].astype(str) == levels[0], y].to_numpy("float64")
    b = sub.loc[sub[group].astype(str) == levels[1], y].to_numpy("float64")
    # 군마다 치우침이 다를 수 있다 — 세트 전체 CLR 평균의 군 차이를 보정량으로 뺀다
    base = clr[[c for c in members if c != y]].mean(axis=1)
    ga = base[sub.index[sub[group].astype(str) == levels[0]]].mean()
    gb = base[sub.index[sub[group].astype(str) == levels[1]]].mean()
    corr = float(ga - gb)
    r = stats.ttest_ind(a - corr / 2, b + corr / 2, equal_var=False,
                        alternative=alternative)
    d = float(a.mean() - b.mean() - corr)
    se = float(np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size))
    out = TestOutcome("T-1004", msg("run_name_ancombc"), float(r.statistic),
                      float(r.pvalue),
                      effect={"name": msg("run_eff_ancombc_diff", a=levels[0], b=levels[1]),
                              "value": d, "ci_low": d - 1.96 * se,
                              "ci_high": d + 1.96 * se},
                      n={levels[0]: int(a.size), levels[1]: int(b.size)})
    out.notes.append(msg("run_note_comp_set", n=len(members), cols=", ".join(members)))
    out.notes.append(msg("run_note_ancombc_simple", corr=corr))
    if dropped:
        out.notes.append(msg("run_note_dropped_nonpositive", n=dropped))
    return out


def _proportionality_comp(df, y, group, alternative):
    out = _proportionality(df, y, group, alternative)
    out.id, out.name = "T-1005", msg("run_name_prop_comp")
    return out


def _marginal_vs_conditional(df, y, group, alternative):
    """P(Y) 와 P(Y|Z) 를 나란히 — 전체 비율만 보면 군마다 뒤집히는 것을 놓친다 (심슨)."""
    from scipy import stats

    if group is None:
        raise ValueError(msg("run_need_second_column"))
    sub = df[[y, group]].dropna().astype(str)
    tab = pd.crosstab(sub[y], sub[group])
    marg = (tab.sum(axis=1) / tab.to_numpy().sum())
    cond = tab / tab.sum(axis=0)
    chi2, p, dof, _ = stats.chi2_contingency(tab)
    gap = float((cond.sub(marg, axis=0)).abs().to_numpy().max())
    out = TestOutcome("T-1006", msg("run_name_marginal"), float(chi2), float(p),
                      effect={"name": msg("run_eff_marginal_gap"), "value": gap,
                              "ci_low": None, "ci_high": None},
                      n={"table": f"{tab.shape[0]}x{tab.shape[1]}",
                         "total": int(tab.to_numpy().sum())})
    out.notes.append(msg("run_note_marginal", dist=", ".join(
        f"{k}={v:.3f}" for k, v in marg.items())))
    for col in cond.columns:
        out.notes.append(msg("run_note_conditional", z=str(col), dist=", ".join(
            f"{k}={v:.3f}" for k, v in cond[col].items())))
    out.notes.append(msg("run_note_simpson"))
    return out


# ── Q-09 생존/사건 시간 ─────────────────────────────────────
def _survival_input(df: pd.DataFrame, y: str, group: str, spec):  # noqa: ANN001
    """(시간, 사건여부, 군, 중도절단 컬럼이 없다는 경고) — 생존 4종의 공통 입구.

    사건 컬럼이 설계에 없으면 **모두 사건 발생**으로 본다. 추적이 끊긴 대상이 있으면
    그 결과는 쓸 수 없으므로, 가정했다는 사실이 결과에 반드시 남아야 한다.
    """
    cols = [c for c in (y, group, getattr(spec, "event", None)) if c]
    sub = df[cols].dropna()
    t = pd.to_numeric(sub[y], errors="coerce")
    sub = sub[t.notna() & (t > 0)]
    if len(sub) < 4:
        raise ValueError(msg("run_need_positive_time", col=y))
    t = pd.to_numeric(sub[y], errors="coerce").to_numpy("float64")
    ev = getattr(spec, "event", None)
    if ev:
        raw = pd.to_numeric(sub[ev], errors="coerce")
        if raw.isna().all():
            raw = (sub[ev].astype(str) != sorted(set(sub[ev].astype(str)))[0]).astype(float)
        status = (raw > 0).to_numpy(dtype="float64")
        note = msg("run_note_censor_col", col=ev, events=int(status.sum()),
                   censored=int((status == 0).sum()))
    else:
        status = np.ones(len(sub), dtype="float64")
        note = msg("run_note_cox_no_censor")
    return t, status, sub[group].astype(str).to_numpy() if group else None, sub, note


def _hr_from_cox(t, status, g: np.ndarray) -> tuple[dict, list[str]]:
    """로그순위 검정에는 크기가 없다 — 같은 자료의 Cox 위험비를 효과크기로 붙인다."""
    from statsmodels.duration.hazard_regression import PHReg

    levels = sorted(set(g))
    x = pd.get_dummies(pd.Series(g, name="g"), drop_first=True, dtype="float64")
    res = PHReg(t, x, status=status).fit()
    ci = res.conf_int()
    name = list(x.columns)[0]
    eff = {"name": msg("run_eff_hr_vs", name=name, ref=levels[0]),
           "value": float(np.exp(res.params[0])),
           "ci_low": float(np.exp(ci[0][0])), "ci_high": float(np.exp(ci[0][1]))}
    extra = [msg("run_note_coef", name=nm, value=float(np.exp(res.params[i + 1])),
                 lo=float(np.exp(ci[i + 1][0])), hi=float(np.exp(ci[i + 1][1])))
             for i, nm in enumerate(list(x.columns)[1:])]
    return eff, extra


def _median_survival(t, status, g: np.ndarray) -> list[str]:
    from statsmodels.duration.survfunc import SurvfuncRight

    out = []
    for lv in sorted(set(g)):
        m = g == lv
        sf = SurvfuncRight(t[m], status[m])
        below = np.where(sf.surv_prob <= 0.5)[0]
        # 절반이 아직 사건을 겪지 않았으면 중앙생존은 관측되지 않은 것이다.
        # nan 을 숫자인 척 찍으면 "0쯤"으로 읽힌다
        if below.size:
            out.append(msg("run_note_median_surv", level=lv, n=int(m.sum()),
                           events=int(status[m].sum()),
                           median=float(sf.surv_times[below[0]])))
        else:
            out.append(msg("run_note_median_unreached", level=lv, n=int(m.sum()),
                           events=int(status[m].sum()),
                           low=float(sf.surv_prob[-1])))
    return out


def _logrank_like(df, y, group, alternative, spec, weight_type, tid, name):  # noqa: ANN001
    from statsmodels.duration.survfunc import survdiff

    t, status, g, _, censor_note = _survival_input(df, y, group, spec)
    if g is None or len(set(g)) < 2:
        raise ValueError(msg("run_need_two_groups", n=0 if g is None else len(set(g))))
    chisq, p = survdiff(t, status, g, weight_type=weight_type)
    eff, extra = _hr_from_cox(t, status, g)
    out = TestOutcome(tid, name, float(chisq), float(p), effect=eff,
                      n={"total": int(len(t)), "events": int(status.sum())})
    out.notes.append(censor_note)
    out.notes += _median_survival(t, status, g)
    out.notes.append(msg("run_note_hr_companion"))
    out.notes += extra
    return out


def _logrank(df, y, group, alternative, spec=None):  # noqa: ANN001
    out = _logrank_like(df, y, group, alternative, spec, None, "T-901",
                        msg("run_name_logrank"))
    out.notes.append(msg("run_note_logrank_crossing"))
    return out


def _gehan(df, y, group, alternative, spec=None):  # noqa: ANN001
    out = _logrank_like(df, y, group, alternative, spec, "gb", "T-902",
                        msg("run_name_gehan"))
    out.notes.append(msg("run_note_gehan_early"))
    return out


def _rmst_one(t, status, tau: float) -> tuple[float, float]:
    """tau 까지의 제한평균생존시간과 그 분산 (KM 곡선 아래 넓이)."""
    from statsmodels.duration.survfunc import SurvfuncRight

    sf = SurvfuncRight(t, status)
    times = np.concatenate([[0.0], sf.surv_times])
    probs = np.concatenate([[1.0], sf.surv_prob])
    keep = times <= tau
    times, probs = times[keep], probs[keep]
    edges = np.concatenate([times, [tau]])
    area = float((probs * np.diff(edges)).sum())
    # Greenwood 형 분산: 각 사건시점 이후 남은 넓이의 제곱에 가중
    var = 0.0
    n_risk = np.concatenate([[len(t)], sf.n_risk])[keep]
    n_ev = np.concatenate([[0.0], sf.n_events])[keep]
    for i in range(len(times)):
        if n_ev[i] <= 0 or n_risk[i] <= n_ev[i]:
            continue
        rest = float((probs[i:] * np.diff(edges[i:])).sum())
        var += rest ** 2 * n_ev[i] / (n_risk[i] * (n_risk[i] - n_ev[i]))
    return area, var


def _rmst(df, y, group, alternative, spec=None):  # noqa: ANN001
    from scipy import stats

    t, status, g, _, censor_note = _survival_input(df, y, group, spec)
    levels = sorted(set(g)) if g is not None else []
    if len(levels) != 2:
        raise ValueError(msg("run_need_two_groups", n=len(levels)))
    a, b = g == levels[0], g == levels[1]
    # tau 는 두 군 모두 관측이 남아 있는 구간까지만 — 넘어가면 넓이가 추정이 아니라 추측이다
    tau = float(min(t[a].max(), t[b].max()))
    ra, va = _rmst_one(t[a], status[a], tau)
    rb, vb = _rmst_one(t[b], status[b], tau)
    d, se = ra - rb, float(np.sqrt(va + vb))
    z = d / se if se > 0 else 0.0
    p = (stats.norm.sf(abs(z)) * 2 if alternative == "two-sided"
         else stats.norm.sf(z) if alternative == "greater" else stats.norm.cdf(z))
    out = TestOutcome("T-903", msg("run_name_rmst"), float(z), float(p),
                      effect={"name": msg("run_eff_rmst", a=levels[0], b=levels[1]),
                              "value": d, "ci_low": d - 1.96 * se,
                              "ci_high": d + 1.96 * se},
                      n={levels[0]: int(a.sum()), levels[1]: int(b.sum())})
    out.notes.append(censor_note)
    out.notes.append(msg("run_note_rmst_tau", tau=tau, a=ra, b=rb))
    out.notes.append(msg("run_note_rmst_why"))
    return out


def _cox_ph(df, y, group, alternative, spec=None):  # noqa: ANN001
    """Cox 비례위험 — 중도절단 컬럼이 설계에 있으면 그것을 쓴다."""
    from statsmodels.duration.hazard_regression import PHReg

    t, status, g, sub, censor_note = _survival_input(df, y, group, spec)
    x = pd.to_numeric(sub[group], errors="coerce")
    x = (x.to_frame(group) if not x.isna().all()
         else pd.get_dummies(sub[group].astype(str), prefix=group, drop_first=True,
                             dtype="float64"))
    res = PHReg(t, x.astype("float64"), status=status).fit()
    ci = res.conf_int()
    names = list(x.columns)
    out = TestOutcome("T-807", "Cox PH", float(res.tvalues[0]), float(res.pvalues[0]),
                      effect={"name": msg("run_eff_hr", name=names[0]),
                              "value": float(np.exp(res.params[0])),
                              "ci_low": float(np.exp(ci[0][0])),
                              "ci_high": float(np.exp(ci[0][1]))},
                      n={"rows": int(len(t)), "events": int(status.sum())})
    out.notes.append(censor_note)
    out.notes.append(msg("run_note_ph_assumption"))
    out.notes += [msg("run_note_coef", name=nm, value=float(np.exp(res.params[i + 1])),
                      lo=float(np.exp(ci[i + 1][0])), hi=float(np.exp(ci[i + 1][1])))
                  for i, nm in enumerate(names[1:])]
    return out


def _cox_adjusted(df, y, group, alternative, spec=None):  # noqa: ANN001
    out = _cox_ph(df, y, group, alternative, spec)
    out.id, out.name = "T-904", msg("run_name_cox_adj")
    return out


# ── Q-04 상호작용/조절 (group × by) ─────────────────────────
def _two_factor(df: pd.DataFrame, y: str, group: str, spec):  # noqa: ANN001
    """두 요인을 꺼낸다. 두 번째 요인은 층화 컬럼(by)이다 — label 을 지정하는 이유다."""
    by = getattr(spec, "by", None)
    if not group or not by:
        raise ValueError(msg("run_need_two_factors"))
    sub = df[[y, group, by]].dropna().rename(columns={y: "_y", group: "_a", by: "_b"})
    sub["_y"] = pd.to_numeric(sub["_y"], errors="coerce")
    sub = sub.dropna(subset=["_y"])
    if len(sub) < 8:
        raise ValueError(msg("run_need_numeric", cols=f"{y}, {group}, {by}"))
    return sub, by


def _interaction_anova(df, y, group, alternative, spec=None):  # noqa: ANN001
    from statsmodels.formula.api import ols
    from statsmodels.stats.anova import anova_lm

    sub, by = _two_factor(df, y, group, spec)
    res = ols("_y ~ C(_a) * C(_b)", data=sub).fit()
    tab = anova_lm(res, typ=2)
    row = "C(_a):C(_b)"
    ss_resid = float(tab.loc["Residual", "sum_sq"])
    ss_int = float(tab.loc[row, "sum_sq"])
    out = TestOutcome("T-401", msg("run_name_two_way_anova"),
                      float(tab.loc[row, "F"]), float(tab.loc[row, "PR(>F)"]),
                      effect={"name": "partial eta^2",
                              "value": ss_int / (ss_int + ss_resid) if ss_int + ss_resid else 0.0,
                              "ci_low": None, "ci_high": None},
                      n={"rows": int(len(sub)),
                         "cells": int(sub.groupby(["_a", "_b"], observed=True).ngroups)})
    out.notes.append(msg("run_note_factors", a=group, b=by))
    out.notes += _cell_means(sub)
    for nm, label in ((("C(_a)"), group), (("C(_b)"), by)):
        out.notes.append(msg("run_note_main_effect", name=label,
                             f=float(tab.loc[nm, "F"]), p=float(tab.loc[nm, "PR(>F)"])))
    if out.p is not None and out.p < 0.05:
        out.notes.append(msg("run_note_interaction_first"))
    out.notes += _cell_balance(sub)
    return out


def _cell_means(sub: pd.DataFrame) -> list[str]:
    """칸별 평균 — 상호작용은 숫자 하나로 못 읽는다. 어디서 갈리는지 보여야 한다."""
    g = sub.groupby(["_a", "_b"], observed=True)["_y"].agg(["mean", "size"])
    return [msg("run_note_cell", a=str(a), b=str(b), mean=float(r["mean"]),
                n=int(r["size"])) for (a, b), r in g.iterrows()]


def _cell_balance(sub: pd.DataFrame) -> list[str]:
    n = sub.groupby(["_a", "_b"], observed=True)["_y"].size()
    if n.min() < 2:
        return [msg("run_note_cell_empty", n=int(n.min()))]
    if n.max() / n.min() > 3:
        return [msg("run_note_unbalanced", lo=int(n.min()), hi=int(n.max()))]
    return []


def _art_anova(df, y, group, alternative, spec=None):  # noqa: ANN001
    """정렬 순위 변환 ANOVA — 상호작용만 남기고 주효과를 뺀 뒤 순위로 본다."""
    from statsmodels.formula.api import ols
    from statsmodels.stats.anova import anova_lm

    sub, by = _two_factor(df, y, group, spec)
    grand = sub["_y"].mean()
    ma = sub.groupby("_a", observed=True)["_y"].transform("mean")
    mb = sub.groupby("_b", observed=True)["_y"].transform("mean")
    cell = sub.groupby(["_a", "_b"], observed=True)["_y"].transform("mean")
    # 정렬: 칸 평균에서 두 주효과를 빼면 상호작용 성분만 남는다
    aligned = sub["_y"] - cell + (cell - ma - mb + grand)
    sub = sub.assign(_r=aligned.rank())
    res = ols("_r ~ C(_a) * C(_b)", data=sub).fit()
    tab = anova_lm(res, typ=2)
    row = "C(_a):C(_b)"
    ss_int = float(tab.loc[row, "sum_sq"])
    ss_resid = float(tab.loc["Residual", "sum_sq"])
    out = TestOutcome("T-402", msg("run_name_art_anova"),
                      float(tab.loc[row, "F"]), float(tab.loc[row, "PR(>F)"]),
                      effect={"name": "partial eta^2 (rank)",
                              "value": ss_int / (ss_int + ss_resid) if ss_int + ss_resid else 0.0,
                              "ci_low": None, "ci_high": None},
                      n={"rows": int(len(sub))})
    out.notes.append(msg("run_note_factors", a=group, b=by))
    out.notes.append(msg("run_note_art"))
    out.notes += _cell_balance(sub)
    return out


def _interaction_glm(df, y, group, alternative, spec=None):  # noqa: ANN001
    """회귀 + 교호작용 항 — 조절변수가 연속이어도 된다. 중심화해 주효과를 읽을 수 있게 한다."""
    import statsmodels.api as sm

    sub, by = _two_factor(df, y, group, spec)
    a_num = pd.to_numeric(sub["_a"], errors="coerce")
    b_num = pd.to_numeric(sub["_b"], errors="coerce")
    parts, notes = [], []
    for name, raw, col in ((group, a_num, "_a"), (by, b_num, "_b")):
        if raw.isna().all():
            d = pd.get_dummies(sub[col].astype(str), prefix=name, drop_first=True,
                               dtype="float64")
            parts.append(d)
        else:
            # C-07: 중심화하지 않으면 주효과 계수가 "상대가 0일 때"라는 무의미한 값이 된다
            parts.append((raw - raw.mean()).to_frame(name).astype("float64"))
            notes.append(msg("run_note_centered", col=name, mean=float(raw.mean())))
    a_x, b_x = parts
    inter = pd.DataFrame(
        {f"{ca}:{cb}": a_x[ca].to_numpy() * b_x[cb].to_numpy()
         for ca in a_x.columns for cb in b_x.columns}, index=sub.index)
    x = sm.add_constant(pd.concat([a_x, b_x, inter], axis=1).astype("float64"),
                        has_constant="add")
    res = sm.OLS(sub["_y"].astype("float64"), x).fit()
    first = list(inter.columns)[0]
    ci = res.conf_int()
    out = TestOutcome("T-403", msg("run_name_interaction_glm"),
                      float(res.tvalues[first]), float(res.pvalues[first]),
                      effect={"name": msg("run_eff_interaction", term=first),
                              "value": float(res.params[first]),
                              "ci_low": float(ci.loc[first][0]),
                              "ci_high": float(ci.loc[first][1])},
                      n={"rows": int(len(sub))})
    out.notes.append(msg("run_note_factors", a=group, b=by))
    out.notes += notes
    out.notes.append(msg("run_note_r2_adj", r2=float(res.rsquared),
                         adj=float(res.rsquared_adj)))
    for c in list(inter.columns)[1:]:
        out.notes.append(msg("run_note_coef", name=c, value=float(res.params[c]),
                             lo=float(ci.loc[c][0]), hi=float(ci.loc[c][1])))
    return out


# ── Q-11 사전지정 대비 (Planned contrast) ───────────────────
def _groups_in_order(df: pd.DataFrame, y: str, group: str):
    levels, parts = [], []
    for g, sub in df.groupby(group, observed=True):
        arr = pd.to_numeric(sub[y], errors="coerce").dropna().to_numpy("float64")
        if arr.size:
            levels.append(str(g))
            parts.append(arr)
    from statop.semantic import order_key

    order = sorted(range(len(levels)), key=lambda i: order_key(levels[i]))
    return [levels[i] for i in order], [parts[i] for i in order]


def _parse_weights(spec, levels: list[str]) -> np.ndarray:  # noqa: ANN001
    """가중치는 군 순서대로 주어진다. 합이 0이 아니면 대비가 아니라 그냥 평균 조합이다."""
    raw = getattr(spec, "weights", None)
    if not raw:
        raise ValueError(msg("run_need_weights", k=len(levels),
                             levels=" < ".join(levels)))
    try:
        w = np.array([float(x) for x in str(raw).replace(" ", "").split(",")])
    except ValueError:
        raise ValueError(msg("run_bad_weights", raw=raw)) from None
    if w.size != len(levels):
        raise ValueError(msg("run_weights_count", got=int(w.size), k=len(levels),
                             levels=" < ".join(levels)))
    if abs(float(w.sum())) > 1e-9:
        raise ValueError(msg("run_weights_sum", total=float(w.sum())))
    return w


def _mse(parts: list[np.ndarray]) -> tuple[float, int]:
    ss = sum(float(((p - p.mean()) ** 2).sum()) for p in parts)
    dof = sum(p.size for p in parts) - len(parts)
    return (ss / dof if dof > 0 else float("nan")), dof


def _contrast_value(parts, w, alternative):  # noqa: ANN001
    from scipy import stats

    means = np.array([p.mean() for p in parts])
    sizes = np.array([p.size for p in parts], dtype="float64")
    mse, dof = _mse(parts)
    value = float((w * means).sum())
    se = float(np.sqrt(mse * (w ** 2 / sizes).sum()))
    t = value / se if se > 0 else 0.0
    p = (stats.t.sf(abs(t), dof) * 2 if alternative == "two-sided"
         else stats.t.sf(t, dof) if alternative == "greater" else stats.t.cdf(t, dof))
    crit = float(stats.t.ppf(0.975, dof))
    return value, se, t, float(p), crit, means, sizes


def _planned_contrast(df, y, group, alternative, spec=None):  # noqa: ANN001
    levels, parts = _groups_in_order(df, y, group)
    if len(levels) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(levels)))
    w = _parse_weights(spec, levels)
    value, se, t, p, crit, means, sizes = _contrast_value(parts, w, alternative)
    out = TestOutcome("T-1101", msg("run_name_planned_contrast"), t, p,
                      effect={"name": msg("run_eff_contrast"), "value": value,
                              "ci_low": value - crit * se, "ci_high": value + crit * se},
                      n={lv: int(s) for lv, s in zip(levels, sizes)})
    out.notes.append(msg("run_note_contrast_spec", spec=" , ".join(
        f"{lv}×{wi:g}" for lv, wi in zip(levels, w))))
    out.notes.append(msg("run_note_group_means", means=", ".join(
        f"{lv}={m:.4g}" for lv, m in zip(levels, means))))
    out.notes.append(msg("run_note_contrast_single"))
    return out


def _dunnett(df, y, group, alternative, spec=None):  # noqa: ANN001
    from scipy import stats

    levels, parts = _groups_in_order(df, y, group)
    if len(levels) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(levels)))
    control = getattr(spec, "control", None)
    if control is None or str(control) not in levels:
        raise ValueError(msg("run_need_control_level", levels=", ".join(levels)))
    ci_idx = levels.index(str(control))
    others = [i for i in range(len(levels)) if i != ci_idx]
    res = stats.dunnett(*[parts[i] for i in others], control=parts[ci_idx],
                        alternative=alternative)
    ci = res.confidence_interval()
    worst = int(np.argmin(res.pvalue))
    out = TestOutcome("T-1102", msg("run_name_dunnett"),
                      float(res.statistic[worst]), float(res.pvalue.min()),
                      effect={"name": msg("run_eff_vs_control",
                                          level=levels[others[worst]], ctrl=str(control)),
                              "value": float(parts[others[worst]].mean() - parts[ci_idx].mean()),
                              "ci_low": float(ci.low[worst]), "ci_high": float(ci.high[worst])},
                      n={lv: int(parts[i].size) for i, lv in enumerate(levels)})
    out.notes.append(msg("run_note_dunnett_ctrl", ctrl=str(control)))
    for j, i in enumerate(others):
        out.notes.append(msg("run_note_dunnett_row", level=levels[i],
                             diff=float(parts[i].mean() - parts[ci_idx].mean()),
                             lo=float(ci.low[j]), hi=float(ci.high[j]),
                             p=float(res.pvalue[j])))
    out.notes.append(msg("run_note_dunnett_adjusted"))
    return out


def _orthogonal_contrasts(df, y, group, alternative, spec=None):  # noqa: ANN001
    """직교 대비 집합 (Helmert) — k−1개가 서로 겹치지 않게 전체 차이를 쪼갠다."""
    levels, parts = _groups_in_order(df, y, group)
    k = len(levels)
    if k < 3:
        raise ValueError(msg("run_need_three_levels", n=k))
    rows, best = [], None
    for j in range(k - 1):
        w = np.zeros(k)
        w[j] = k - j - 1
        w[j + 1:] = -1.0
        value, se, t, p, crit, means, sizes = _contrast_value(parts, w, alternative)
        rows.append((levels[j], value, se, t, p, crit))
        if best is None or p < best[4]:
            best = rows[-1]
    lv, value, se, t, p, crit = best
    out = TestOutcome("T-1103", msg("run_name_orthogonal"), t, p,
                      effect={"name": msg("run_eff_helmert", level=lv), "value": value,
                              "ci_low": value - crit * se, "ci_high": value + crit * se},
                      n={l_: int(p_.size) for l_, p_ in zip(levels, parts)})
    out.notes.append(msg("run_note_helmert_set", k=k - 1))
    for lv_, v, se_, t_, p_, crit_ in rows:
        out.notes.append(msg("run_note_helmert_row", level=lv_, value=v,
                             lo=v - crit_ * se_, hi=v + crit_ * se_, p=p_))
    out.notes.append(msg("run_note_orthogonal_why"))
    return out


def _nonparam_contrast(df, y, group, alternative, spec=None):  # noqa: ANN001
    """비모수 대비 — 가중치의 부호로 군을 두 덩어리로 묶어 Mann–Whitney 로 본다."""
    from scipy import stats

    levels, parts = _groups_in_order(df, y, group)
    if len(levels) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(levels)))
    w = _parse_weights(spec, levels)
    pos = np.concatenate([p for p, wi in zip(parts, w) if wi > 0])
    neg = np.concatenate([p for p, wi in zip(parts, w) if wi < 0])
    if not pos.size or not neg.size:
        raise ValueError(msg("run_weights_need_both_signs"))
    r = stats.mannwhitneyu(pos, neg, alternative=alternative)
    out = TestOutcome("T-1104", msg("run_name_nonparam_contrast"),
                      float(r.statistic), float(r.pvalue),
                      effect=_rank_biserial(pos, neg, float(r.statistic)),
                      n={"pooled+": int(pos.size), "pooled-": int(neg.size)})
    out.notes.append(msg("run_note_pooled", plus=", ".join(
        lv for lv, wi in zip(levels, w) if wi > 0), minus=", ".join(
        lv for lv, wi in zip(levels, w) if wi < 0)))
    out.notes.append(msg("run_note_pooled_caveat"))
    return out


# ── 남은 검정들 (Q-01 / Q-02 / Q-03) ────────────────────────
def _sign_test(df, y, group, alternative):
    from scipy import stats

    a, b, names = _two_groups(df, y, group)
    if a.size != b.size:
        raise ValueError(msg("run_paired_unequal", a=a.size, b=b.size))
    d = a - b
    pos, neg = int((d > 0).sum()), int((d < 0).sum())
    ties = int((d == 0).sum())
    r = stats.binomtest(pos, pos + neg, 0.5, alternative=alternative)
    ci = r.proportion_ci()
    out = TestOutcome("T-113", "Sign test", float(pos), float(r.pvalue),
                      effect={"name": msg("run_eff_prop_positive"),
                              "value": pos / (pos + neg) if pos + neg else 0.0,
                              "ci_low": float(ci.low), "ci_high": float(ci.high)},
                      n={"pairs": int(a.size), "+": pos, "-": neg, "tie": ties})
    out.notes.append(msg("run_note_sign_only_direction"))
    return out


def _welch_anova(df, y, group, alternative):
    from scipy import stats

    parts = [sub[y].dropna().to_numpy("float64")
             for _, sub in df.groupby(group, observed=True)]
    if len(parts) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(parts)))
    r = stats.alexandergovern(*parts)
    grand = np.concatenate(parts)
    ss_b = sum(p.size * (p.mean() - grand.mean()) ** 2 for p in parts)
    ss_t = float(((grand - grand.mean()) ** 2).sum())
    out = TestOutcome("T-122", "Welch ANOVA", float(r.statistic), float(r.pvalue),
                      effect={"name": "eta^2",
                              "value": float(ss_b / ss_t) if ss_t else 0.0,
                              "ci_low": None, "ci_high": None},
                      n={"groups": len(parts), "total": int(grand.size)})
    out.notes.append(msg("run_note_welch_anova"))
    return out


def _perm_anova(df, y, group, alternative):
    from scipy import stats

    parts = [sub[y].dropna().to_numpy("float64")
             for _, sub in df.groupby(group, observed=True)]
    if len(parts) < 3:
        raise ValueError(msg("run_need_three_levels", n=len(parts)))
    r = stats.permutation_test(tuple(parts), lambda *a: stats.f_oneway(*a).statistic,
                               permutation_type="independent", alternative="greater",
                               n_resamples=999, random_state=0)
    grand = np.concatenate(parts)
    ss_b = sum(p.size * (p.mean() - grand.mean()) ** 2 for p in parts)
    ss_t = float(((grand - grand.mean()) ** 2).sum())
    out = TestOutcome("T-124", "Permutation ANOVA", float(r.statistic), float(r.pvalue),
                      effect={"name": "eta^2",
                              "value": float(ss_b / ss_t) if ss_t else 0.0,
                              "ci_low": None, "ci_high": None},
                      n={"groups": len(parts), "total": int(grand.size)})
    out.notes.append(msg("run_note_perm_p", n=999))
    return out


def _gtest(df, y, group, alternative):
    from scipy import stats

    tab = pd.crosstab(df[y], df[group])
    obs = tab.to_numpy(dtype="float64")
    chi2, _, dof, exp = stats.chi2_contingency(obs)
    mask = obs > 0
    g = 2 * float((obs[mask] * np.log(obs[mask] / exp[mask])).sum())
    p = float(stats.chi2.sf(g, dof))
    n = float(obs.sum())
    k = min(tab.shape) - 1
    out = TestOutcome("T-203", msg("run_name_gtest"), g, p,
                      effect={"name": "Cramér V",
                              "value": float(np.sqrt(chi2 / (n * k))) if n * k else 0.0,
                              "ci_low": None, "ci_high": None},
                      n={"table": f"{tab.shape[0]}x{tab.shape[1]}", "total": int(n)})
    if (exp < 5).any():
        out.notes.append(msg("run_note_small_expected", n=int((exp < 5).sum())))
    return out


def _mcnemar(df, y, group, alternative):
    from statsmodels.stats.contingency_tables import mcnemar

    sub = df[[y, group]].dropna().astype(str)
    cats = sorted(set(sub[y]) | set(sub[group]))
    if len(cats) != 2:
        raise ValueError(msg("run_need_binary_y", col=f"{y}/{group}", n=len(cats)))
    tab = pd.crosstab(sub[y], sub[group]).reindex(index=cats, columns=cats,
                                                  fill_value=0).to_numpy()
    r = mcnemar(tab, exact=bool(tab[0, 1] + tab[1, 0] < 25))
    b, c = int(tab[0, 1]), int(tab[1, 0])
    out = TestOutcome("T-211", "McNemar", float(r.statistic), float(r.pvalue),
                      effect={"name": msg("run_eff_discordant"),
                              "value": (b - c) / len(sub) if len(sub) else 0.0,
                              "ci_low": None, "ci_high": None},
                      n={"pairs": int(len(sub)), "b": b, "c": c})
    out.notes.append(msg("run_note_mcnemar_discordant", b=b, c=c))
    return out


def _prop_diff(df, y, group, alternative):
    """두 비율의 차이와 신뢰구간 (Newcombe) — p만으로는 얼마나 다른지 알 수 없다."""
    from scipy import stats

    sub = df[[y, group]].dropna().astype(str)
    yv, gv = sorted(set(sub[y])), sorted(set(sub[group]))
    if len(yv) != 2 or len(gv) != 2:
        raise ValueError(msg("run_need_2x2", y=len(yv), g=len(gv)))
    hit = yv[-1]
    n1 = int((sub[group] == gv[0]).sum())
    n2 = int((sub[group] == gv[1]).sum())
    x1 = int(((sub[group] == gv[0]) & (sub[y] == hit)).sum())
    x2 = int(((sub[group] == gv[1]) & (sub[y] == hit)).sum())
    p1, p2 = x1 / n1, x2 / n2

    def wilson(x: int, n: int) -> tuple[float, float]:
        z = 1.959963985
        ph = x / n
        d = 1 + z ** 2 / n
        c = ph + z ** 2 / (2 * n)
        h = z * np.sqrt(ph * (1 - ph) / n + z ** 2 / (4 * n ** 2))
        return float((c - h) / d), float((c + h) / d)

    l1, u1 = wilson(x1, n1)
    l2, u2 = wilson(x2, n2)
    lo = (p1 - p2) - np.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = (p1 - p2) + np.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    se = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = (p1 - p2) / se if se > 0 else 0.0
    p = (stats.norm.sf(abs(z)) * 2 if alternative == "two-sided"
         else stats.norm.sf(z) if alternative == "greater" else stats.norm.cdf(z))
    out = TestOutcome("T-221", msg("run_name_prop_diff"), float(z), float(p),
                      effect={"name": msg("run_eff_prop_diff", a=gv[0], b=gv[1]),
                              "value": float(p1 - p2), "ci_low": float(lo),
                              "ci_high": float(hi)},
                      n={gv[0]: n1, gv[1]: n2})
    out.notes.append(msg("run_note_prop_rates", hit=hit, a=gv[0], pa=p1, b=gv[1], pb=p2))
    out.notes.append(msg("run_note_newcombe"))
    return out


def _distance_corr(df, y, group, alternative):
    """거리상관 — 직선이 아니어도 잡는다. 0이면 독립, 부호는 없다."""
    from scipy import stats

    sub = df[[y, group]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) > 2000:      # n² 행렬이라 그대로 두면 메모리가 터진다
        sub = sub.sample(2000, random_state=0)
    a = np.abs(sub[y].to_numpy()[:, None] - sub[y].to_numpy()[None, :])
    b = np.abs(sub[group].to_numpy()[:, None] - sub[group].to_numpy()[None, :])

    def center(m):  # noqa: ANN001, ANN202
        return m - m.mean(0) - m.mean(1)[:, None] + m.mean()

    ca, cb = center(a), center(b)
    dcov = float(np.sqrt(max(0.0, (ca * cb).mean())))
    da = float(np.sqrt(max(0.0, (ca * ca).mean())))
    db = float(np.sqrt(max(0.0, (cb * cb).mean())))
    dcor = dcov / np.sqrt(da * db) if da * db > 0 else 0.0
    n = len(sub)
    r = stats.permutation_test(
        (sub[y].to_numpy(),), lambda v: _dcor_stat(v, sub[group].to_numpy()),
        permutation_type="pairings", alternative="greater", n_resamples=299,
        random_state=0)
    out = TestOutcome("T-304", "Distance correlation", dcor, float(r.pvalue),
                      effect={"name": "dCor", "value": float(dcor),
                              "ci_low": None, "ci_high": None}, n={"pairs": n})
    out.notes.append(msg("run_note_dcor"))
    out.notes.append(msg("run_note_perm_p", n=299))
    return out


def _dcor_stat(x: np.ndarray, z: np.ndarray) -> float:
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(z[:, None] - z[None, :])
    ca = a - a.mean(0) - a.mean(1)[:, None] + a.mean()
    cb = b - b.mean(0) - b.mean(1)[:, None] + b.mean()
    da, db = (ca * ca).mean(), (cb * cb).mean()
    return float(np.sqrt(max(0.0, (ca * cb).mean())) / np.sqrt(np.sqrt(da * db))
                 if da * db > 0 else 0.0)


def _bicor(df, y, group, alternative):
    """Biweight midcorrelation — 이상점에 둔한 상관. Pearson 과 크게 다르면 몇 점이 끌고 있다."""
    from scipy import stats

    sub = df[[y, group]].apply(pd.to_numeric, errors="coerce").dropna()
    n = len(sub)
    if n < 5:
        raise ValueError(msg("run_need_numeric", cols=f"{y}, {group}"))

    def weights(v: np.ndarray) -> np.ndarray:
        med = np.median(v)
        mad = np.median(np.abs(v - med)) or 1e-12
        u = (v - med) / (9 * mad)
        w = (1 - u ** 2) ** 2 * (np.abs(u) < 1)
        d = v - med
        num = d * w
        denom = np.sqrt((num ** 2).sum()) or 1e-12
        return num / denom

    wa, wb = weights(sub[y].to_numpy("float64")), weights(sub[group].to_numpy("float64"))
    r = float((wa * wb).sum())
    lo, hi = _fisher_z_ci(r, n)
    t = r * np.sqrt((n - 2) / max(1e-12, 1 - r ** 2))
    p = float(stats.t.sf(abs(t), n - 2) * 2)
    pear = float(stats.pearsonr(sub[y], sub[group]).statistic)
    out = TestOutcome("T-305", "Biweight midcorrelation", float(t), p,
                      effect={"name": "bicor", "value": r, "ci_low": lo, "ci_high": hi},
                      n={"pairs": n})
    out.notes.append(msg("run_note_bicor_vs_pearson", pearson=pear, bicor=r))
    return out


def _partial_corr(df, y, group, alternative, spec=None):  # noqa: ANN001
    """편상관 — 층화 라벨(by)을 통제한 뒤 남는 상관. 무엇을 뺐는지가 결과의 전부다."""
    from scipy import stats

    ctrl = getattr(spec, "by", None)
    if not ctrl:
        raise ValueError(msg("run_need_control_var"))
    sub = df[[y, group, ctrl]].dropna()
    z = pd.to_numeric(sub[ctrl], errors="coerce")
    zx = (z.to_frame(ctrl) if not z.isna().all()
          else pd.get_dummies(sub[ctrl].astype(str), drop_first=True, dtype="float64"))
    import statsmodels.api as sm

    design = sm.add_constant(zx.astype("float64"), has_constant="add")
    ry = sm.OLS(pd.to_numeric(sub[y], errors="coerce").astype("float64"), design).fit().resid
    rx = sm.OLS(pd.to_numeric(sub[group], errors="coerce").astype("float64"), design).fit().resid
    r = stats.pearsonr(ry, rx, alternative=alternative)
    n, k = len(sub), design.shape[1] - 1
    lo, hi = _fisher_z_ci(float(r.statistic), n - k)
    raw = float(stats.pearsonr(pd.to_numeric(sub[y], errors="coerce"),
                               pd.to_numeric(sub[group], errors="coerce")).statistic)
    out = TestOutcome("T-311", "Partial correlation", float(r.statistic),
                      float(r.pvalue),
                      effect={"name": msg("run_eff_partial_r", ctrl=ctrl),
                              "value": float(r.statistic), "ci_low": lo, "ci_high": hi},
                      n={"pairs": n})
    out.notes.append(msg("run_note_partial_vs_raw", raw=raw, partial=float(r.statistic),
                         ctrl=ctrl))
    return out


# ── 반복측정 (같은 대상을 여러 번) ──────────────────────────
def _repeated_wide(df: pd.DataFrame, y: str, group: str, spec,  # noqa: ANN001
                   numeric: bool = True) -> tuple[pd.DataFrame, list[str], int]:
    """대상 × 회차 표로 편다. 회차 순서는 값 자체에서 읽는다 (T1<T2<T10, 25AIC…<26AIC…).

    회차가 하나라도 빠진 대상은 뺀다 — 반복측정 검정은 모든 회차가 있어야 하고,
    몰래 빼면 "왜 n이 줄었나"를 알 수 없으므로 몇 명이 빠졌는지 함께 돌려준다.
    """
    from statop.semantic import ordered_levels

    subj = getattr(spec, "subject", None)
    if not subj:
        raise ValueError(msg("run_need_subject"))
    if not group:
        raise ValueError(msg("run_need_occasion"))
    sub = df[[subj, group, y]].dropna()
    if numeric:
        sub = sub.assign(**{y: pd.to_numeric(sub[y], errors="coerce")}).dropna()
    levels = [str(v) for v in ordered_levels(sub[group])]
    if len(levels) < 2:
        raise ValueError(msg("run_need_two_occasions", n=len(levels)))
    wide = sub.assign(**{group: sub[group].astype(str)}).pivot_table(
        index=subj, columns=group, values=y,
        aggfunc="mean" if numeric else "first")
    wide = wide.reindex(columns=levels)
    complete = wide.dropna()
    return complete, levels, int(len(wide) - len(complete))


def _repeat_notes(spec, levels: list[str], dropped: int, n: int) -> list[str]:  # noqa: ANN001
    out = [msg("run_note_occasions", col=spec.subject, n=n,
               order=" < ".join(levels))]
    if dropped:
        out.append(msg("run_note_incomplete_subjects", n=dropped))
    return out


def _rm_anova(df, y, group, alternative, spec=None):  # noqa: ANN001
    from statsmodels.stats.anova import AnovaRM

    wide, levels, dropped = _repeated_wide(df, y, group, spec)
    if len(wide) < 3:
        raise ValueError(msg("run_need_subjects", n=len(wide)))
    long = wide.reset_index().melt(id_vars=wide.index.name, var_name="_t",
                                   value_name="_y")
    res = AnovaRM(long, "_y", wide.index.name, within=["_t"]).fit()
    row = res.anova_table.loc["_t"]
    f, p = float(row["F Value"]), float(row["Pr > F"])
    df1, df2 = float(row["Num DF"]), float(row["Den DF"])
    out = TestOutcome("T-131", "Repeated-measures ANOVA", f, p,
                      effect={"name": "partial eta^2",
                              "value": float(f * df1 / (f * df1 + df2)),
                              "ci_low": None, "ci_high": None},
                      n={"subjects": int(len(wide)), "occasions": len(levels)})
    out.notes += _repeat_notes(spec, levels, dropped, len(wide))
    out.notes.append(msg("run_note_means_by_occasion", means=", ".join(
        f"{lv}={wide[lv].mean():.4g}" for lv in levels)))
    out.notes.append(msg("run_note_sphericity"))
    return out


def _friedman(df, y, group, alternative, spec=None):  # noqa: ANN001
    from scipy import stats

    wide, levels, dropped = _repeated_wide(df, y, group, spec)
    if len(levels) < 3:
        raise ValueError(msg("run_need_three_occasions", n=len(levels)))
    if len(wide) < 3:
        raise ValueError(msg("run_need_subjects", n=len(wide)))
    r = stats.friedmanchisquare(*[wide[lv].to_numpy("float64") for lv in levels])
    n, k = len(wide), len(levels)
    w = float(r.statistic) / (n * (k - 1)) if n and k > 1 else 0.0   # Kendall W
    out = TestOutcome("T-132", "Friedman", float(r.statistic), float(r.pvalue),
                      effect={"name": "Kendall W", "value": w,
                              "ci_low": None, "ci_high": None},
                      n={"subjects": n, "occasions": k})
    out.notes += _repeat_notes(spec, levels, dropped, n)
    out.notes.append(msg("run_note_mean_ranks", ranks=", ".join(
        f"{lv}={v:.3f}" for lv, v in
        wide[levels].rank(axis=1).mean().items())))
    out.notes.append(msg("run_note_friedman_ranks"))
    return out


def _cochran_q(df, y, group, alternative, spec=None):  # noqa: ANN001
    from statsmodels.stats.contingency_tables import cochrans_q

    wide, levels, dropped = _repeated_wide(df, y, group, spec, numeric=False)
    if len(levels) < 3:
        raise ValueError(msg("run_need_three_occasions", n=len(levels)))
    vals = pd.unique(wide.to_numpy().ravel())
    if len(vals) != 2:
        raise ValueError(msg("run_need_binary_y", col=y, n=len(vals)))
    hit = sorted(map(str, vals))[-1]
    mat = (wide.astype(str) == hit).astype(int).to_numpy()
    r = cochrans_q(mat)
    rates = mat.mean(axis=0)
    out = TestOutcome("T-212", "Cochran Q", float(r.statistic), float(r.pvalue),
                      effect={"name": msg("run_eff_rate_range"),
                              "value": float(rates.max() - rates.min()),
                              "ci_low": None, "ci_high": None},
                      n={"subjects": int(len(wide)), "occasions": len(levels)})
    out.notes += _repeat_notes(spec, levels, dropped, len(wide))
    out.notes.append(msg("run_note_prop_by_occasion", hit=hit, rates=", ".join(
        f"{lv}={v:.4f}" for lv, v in zip(levels, rates))))
    return out


def _mixed_repeated(df, y, group, alternative, spec=None):  # noqa: ANN001
    """선형혼합모형 — 회차가 빠진 대상도 버리지 않고 쓸 수 있는 것이 장점이다."""
    import statsmodels.formula.api as smf
    from statop.semantic import ordered_levels

    subj = getattr(spec, "subject", None)
    if not subj:
        raise ValueError(msg("run_need_subject"))
    sub = df[[subj, group, y]].dropna()
    sub = sub.assign(_y=pd.to_numeric(sub[y], errors="coerce")).dropna(subset=["_y"])
    levels = [str(v) for v in ordered_levels(sub[group])]
    if len(levels) < 2:
        raise ValueError(msg("run_need_two_occasions", n=len(levels)))
    sub = sub.assign(_t=pd.Categorical(sub[group].astype(str), categories=levels,
                                       ordered=True), _s=sub[subj].astype(str))
    res = smf.mixedlm("_y ~ C(_t)", sub, groups=sub["_s"]).fit(reml=True)
    terms = [t for t in res.params.index if t.startswith("C(_t)")]
    wald = res.wald_test(np.eye(len(res.params))[[list(res.params.index).index(t)
                                                  for t in terms]], scalar=True)
    ci = res.conf_int()
    first = terms[0]
    out = TestOutcome("T-133", "Linear mixed model", float(wald.statistic),
                      float(wald.pvalue),
                      effect={"name": msg("run_eff_vs_first", term=first,
                                          base=levels[0]),
                              "value": float(res.params[first]),
                              "ci_low": float(ci.loc[first][0]),
                              "ci_high": float(ci.loc[first][1])},
                      n={"subjects": int(sub["_s"].nunique()), "rows": int(len(sub))})
    out.notes.append(msg("run_note_occasions", col=subj,
                         n=int(sub["_s"].nunique()), order=" < ".join(levels)))
    out.notes.append(msg("run_note_lmm_unbalanced"))
    for t in terms[1:]:
        out.notes.append(msg("run_note_coef", name=t, value=float(res.params[t]),
                             lo=float(ci.loc[t][0]), hi=float(ci.loc[t][1])))
    icc = float(res.cov_re.iloc[0, 0]) / (float(res.cov_re.iloc[0, 0]) + float(res.scale))
    out.notes.append(msg("run_note_icc_subject", icc=icc))
    return out


def _mixed_interaction(df, y, group, alternative, spec=None):  # noqa: ANN001
    """반복측정 안에서의 교호작용 — 대상별 개인차를 빼고 두 요인이 엇갈리는지 본다."""
    import statsmodels.formula.api as smf

    subj = getattr(spec, "subject", None)
    if not subj:
        raise ValueError(msg("run_need_subject"))
    sub, by = _two_factor(df, y, group, spec)
    sub = sub.assign(_s=df.loc[sub.index, subj].astype(str)).dropna(subset=["_s"])
    res = smf.mixedlm("_y ~ C(_a) * C(_b)", sub, groups=sub["_s"]).fit(reml=False)
    terms = [t for t in res.params.index if ":" in t]
    if not terms:
        raise ValueError(msg("run_need_two_factors"))
    wald = res.wald_test(np.eye(len(res.params))[[list(res.params.index).index(t)
                                                  for t in terms]], scalar=True)
    ci = res.conf_int()
    first = terms[0]
    out = TestOutcome("T-404", msg("run_name_mixed_interaction"),
                      float(wald.statistic), float(wald.pvalue),
                      effect={"name": msg("run_eff_interaction", term=first),
                              "value": float(res.params[first]),
                              "ci_low": float(ci.loc[first][0]),
                              "ci_high": float(ci.loc[first][1])},
                      n={"subjects": int(sub["_s"].nunique()), "rows": int(len(sub))})
    out.notes.append(msg("run_note_factors", a=group, b=by))
    out.notes.append(msg("run_note_random_subject", col=subj,
                         n=int(sub["_s"].nunique())))
    out.notes += _cell_balance(sub)
    return out


RUNNERS = {
    "T-101": _welch, "T-102": _student, "T-103": _mwu, "T-104": _brunner_munzel,
    "T-105": _perm_t, "T-111": _paired_t, "T-112": _wilcoxon,
    "T-121": _anova, "T-123": _kruskal,
    "T-201": _chi2, "T-202": _fisher,
    "T-301": _pearson, "T-302": _spearman, "T-303": _kendall, "T-321": _proportionality,
    "T-131": _rm_anova, "T-132": _friedman, "T-133": _mixed_repeated,
    "T-212": _cochran_q, "T-404": _mixed_interaction,
    "T-113": _sign_test, "T-122": _welch_anova, "T-124": _perm_anova,
    "T-203": _gtest, "T-211": _mcnemar, "T-221": _prop_diff,
    "T-304": _distance_corr, "T-305": _bicor, "T-311": _partial_corr,
    "T-1101": _planned_contrast, "T-1102": _dunnett,
    "T-1103": _orthogonal_contrasts, "T-1104": _nonparam_contrast,
    "T-401": _interaction_anova, "T-402": _art_anova, "T-403": _interaction_glm,
    "T-501": _jonckheere, "T-502": _cochran_armitage, "T-503": _mann_kendall,
    "T-504": _trend_ols,
    "T-601": _icc, "T-602": _bland_altman, "T-603": _lins_ccc,
    "T-604": _cohen_kappa, "T-605": _fleiss,
    "T-1001": _clr_compare, "T-1002": _alr_compare, "T-1003": _aldex,
    "T-1004": _ancombc, "T-1005": _proportionality_comp,
    "T-1006": _marginal_vs_conditional,
    "T-801": _logistic, "T-802": _ols, "T-803": _poisson, "T-804": _ordinal,
    "T-805": _beta_reg, "T-806": _robust_reg, "T-807": _cox_ph,
    "T-901": _logrank, "T-902": _gehan, "T-903": _rmst, "T-904": _cox_adjusted,
    "T-701": _ks2, "T-702": _anderson_k, "T-703": _energy, "T-704": _cvm,
}

_ALT = {"two-sided": "two-sided", "greater": "greater", "less": "less"}


def _pyfloat(x):  # noqa: ANN001, ANN202
    """numpy 스칼라를 파이썬 값으로 — 세션 JSON 에 numpy 가 들어가면 저장이 터진다."""
    if isinstance(x, dict):
        return {str(k): _pyfloat(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_pyfloat(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    return x


def _by_strata(fn, df: pd.DataFrame, spec, extra: dict) -> list[dict]:  # noqa: ANN001
    """같은 검정을 층화 수준마다 다시 돌린다.

    한 수준이 실패해도(표본이 적거나 한 군만 남거나) 나머지는 살린다 — 실패 사유를
    그 자리에 남겨야 "왜 이 군만 비었나"를 묻지 않는다.
    """
    out = []
    for level, sub in df.groupby(spec.by, observed=True):
        row = {"level": str(level), "n": int(len(sub))}
        try:
            r = fn(sub, spec.y, spec.group, _ALT[spec.direction], **extra)
            row.update(statistic=r.statistic, p=r.p, effect=dict(r.effect),
                       n_detail={str(k): v for k, v in r.n.items()})
        except Exception as e:      # noqa: BLE001 - 한 수준의 실패로 전체를 버리지 않는다
            row["error"] = str(e) or type(e).__name__
        out.append(row)
    return out


def _direction_flips(overall: TestOutcome, strata: list[dict]) -> list[str]:
    """전체와 방향이 반대인 수준 — 심슨의 역설이 일어난 자리다."""
    base = (overall.effect or {}).get("value")
    name = (overall.effect or {}).get("name", "")
    if base is None:
        return []
    ref = null_ref(name)
    if abs(base - ref) < 1e-12:
        return []
    return [s["level"] for s in strata
            if s.get("effect", {}).get("value") is not None
            and (s["effect"]["value"] - ref) * (base - ref) < 0]


def apply_label_maps(df, spec, maps: dict):  # noqa: ANN001, ANN201
    """표시용 라벨을 계산용 코드로 — 검정 전에 한 번 한다."""
    for col in (spec.group, spec.y):
        mapping = maps.get(col) if col else None
        if mapping:
            df = df.assign(**{col: df[col].astype(str).map(
                lambda v, m=mapping: str(m.get(v, v)))})
    return df


def run_on(df, spec, test_id: str) -> TestOutcome:  # noqa: ANN001
    """**준비된 프레임 하나로** 검정을 돌린다 — 세션을 다시 읽지 않는다.

    강건성(흔들어 보기)은 같은 검정을 수백 번 다시 돌려야 한다. 그때마다 파일을 읽고
    조작을 재생하면 못 쓴다. 그래서 프레임 준비와 검정 실행을 갈라 둔다.

    대부분의 검정은 y·군·방향이면 충분하다. 생존처럼 설계를 더 봐야 하는 검정만 spec 을
    받는다 — 각 함수의 시그니처가 그 자체로 무엇이 필요한지 말하게 둔다.
    """
    import inspect

    if test_id not in RUNNERS:
        raise ValueError(msg("run_not_implemented", id=test_id,
                             available=", ".join(sorted(RUNNERS))))
    fn = RUNNERS[test_id]
    extra = {"spec": spec} if "spec" in inspect.signature(fn).parameters else {}
    return fn(df, spec.y, spec.group, _ALT[spec.direction], **extra)


def null_ref(effect_name: str) -> float:
    """효과가 '차이 없음'이 되는 값 — 비는 1, 확률적 우위는 0.5, 나머지는 0."""
    key = (effect_name or "").split(" (")[0].strip()
    return 1.0 if key in ("OR", "IRR", "HR") else 0.5 if key == "P(X>Y)" else 0.0


def run_test(session_file: str, test_id: str, sample_n: int = 10_000,
             use_exclusions: bool = True, record: bool = True) -> TestOutcome:
    """현재 질문 설계(A1)의 y·group·방향으로 검정 하나를 실행한다.

    보정 α(계획 검정 수 기준)를 결과에 함께 싣는다 — p 를 원래 α와 비교하는
    실수를 화면 단계에서 막기 위함.
    """
    from statop.analyze.checks import multiplicity
    from statop.analyze.spec import current
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    if test_id not in RUNNERS:
        raise ValueError(msg("run_not_implemented", id=test_id,
                             available=", ".join(sorted(RUNNERS))))

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"], use_exclusions=use_exclusions)
    st = replay(doc)
    df = apply_label_maps(df, spec, st["label_maps"].get(src["id"], {}))

    out = run_on(df, spec, test_id)
    if spec.by:
        import inspect

        fn = RUNNERS[test_id]
        extra = {"spec": spec} if "spec" in inspect.signature(fn).parameters else {}
        out.strata = _by_strata(fn, df, spec, extra)
        out.notes.append(msg("run_note_strata", col=spec.by, n=len(out.strata)))
        flips = _direction_flips(out, out.strata)
        if flips:
            out.notes.append(msg("run_note_strata_flip", levels=", ".join(flips)))

    # 검정은 결측 행을 조용히 빼고 계산한다. 몇 행으로 나온 값인지 말하지 않으면
    # 대치한 경우와 무시한 경우를 결과만 보고 구별할 수 없다
    used = [c for c in (spec.y, spec.group, spec.event, spec.by) if c and c in df.columns]
    complete = int(df[used].notna().all(axis=1).sum()) if used else len(df)
    if complete < len(df):
        out.notes.append(msg("run_note_rows_used", used=complete, total=len(df),
                             dropped=len(df) - complete))
    adj = multiplicity(spec.n_tests).numbers["alpha_adjusted"]
    # 결과를 세션에 남긴다 — 가설 생성(A7)이 "실제로 본 것"을 근거로 쓰게.
    # 제외 전 값( 병기용)은 기록하지 않는다 — 기록하면 가설이 그쪽을 근거로 삼는다
    from statop.session.core import append_op, save_session

    if not record:
        out.notes.append(msg("run_note_alpha", n=spec.n_tests, adj=adj))
        return out
    append_op(doc, "test_result", source=src["id"], test=out.id, name=out.name,
              y=spec.y, group=spec.group, question=spec.question,
              statistic=out.statistic, p=out.p,
              effect=dict(out.effect), n={str(k): int(v) if isinstance(v, (int, float)) else v
                                          for k, v in out.n.items()},
              direction=spec.direction, alpha_adjusted=adj,
              by=spec.by, strata=_pyfloat(out.strata))
    save_session(doc)
    out.notes.append(msg("run_note_alpha", n=spec.n_tests, adj=adj))
    if out.p is not None:
        out.notes.append(msg("run_note_verdict_sig" if out.p < adj
                             else "run_note_verdict_ns", p=out.p, adj=adj))
    return out
