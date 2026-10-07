"""A3 가정 검사 (~) — 규칙 DB(assumptions.yaml C-01~)의 방법을 그대로 따른다.

각 검사는 판정만 주지 않는다:
  정규성 — 위배면 **원인**(소수 outlier / 왜도 / 군간 형태 상이)까지 분기
  검정력 — 부족하면 **어느 방향(어느 군) 샘플이 부족한지**까지
p<0.05 = 위배 같은 기계적 판정으로 끝내지 않고, 규칙의 on_violation 문구로 잇는다.
"""

from dataclasses import dataclass, field

import re

import numpy as np
import pandas as pd

from statop.messages import msg


@dataclass
class CheckResult:
    id: str                        # C-01 …
    name: str
    verdict: str                   # ok | violated | caution | skipped
    summary: str
    per_group: list = field(default_factory=list)
    cause: str | None = None       # 위배 원인 분기 (언어 독립 코드)
    numbers: dict = field(default_factory=dict)
    plot: dict = field(default_factory=dict)      # 껍데기가 그릴 재료 (QQ 점 등)


# ── C-01 정규성  ───────────────────────────────────────
def _normality_p(x: np.ndarray) -> tuple[float | None, str]:
    """n에 맞는 방법 (규칙 C-01): n<50 Shapiro / 50~300 D'Agostino / >300 검정 무의미."""
    from scipy import stats

    n = x.size
    if n < 8:
        return None, "too_few"
    if n < 50:
        return float(stats.shapiro(x).pvalue), "shapiro"
    if n <= 300:
        return float(stats.normaltest(x).pvalue), "dagostino"
    return None, "large_n"        # 대표본은 p가 무의미 — 왜도·QQ로만 본다


def _violation_cause(x: np.ndarray) -> str:
    """위배 원인 분기 : outlier 소수 / 왜도(틸팅) / 그 외 형태."""
    from scipy import stats

    q1, q3 = np.percentile(x, [25, 75])
    iqr = q3 - q1
    if iqr > 0:
        mask = (x >= q1 - 1.5 * iqr) & (x <= q3 + 1.5 * iqr)
        n_out = int((~mask).sum())
        if 0 < n_out <= max(2, 0.02 * x.size):
            # outlier 몇 개를 빼면 정규로 돌아오는가 — 돌아오면 원인은 outlier 다
            p2, _ = _normality_p(x[mask])
            if p2 is not None and p2 >= 0.05:
                return "outliers"
    skew = float(stats.skew(x))
    if abs(skew) >= 1:
        return "skew"
    return "shape"


def qq_points(x: np.ndarray, k: int = 40) -> dict:
    """QQ 그림 재료 — 이론 분위수 vs 표본 분위수. 껍데기가 점만 찍으면 된다."""
    from scipy import stats

    x = np.sort(x)
    probs = (np.arange(1, k + 1) - 0.5) / k
    sample = np.quantile(x, probs)
    theo = stats.norm.ppf(probs, loc=float(x.mean()), scale=float(x.std(ddof=1)) or 1.0)
    return {"theoretical": [float(v) for v in theo],
            "sample": [float(v) for v in sample]}


def normality(df: pd.DataFrame, y: str, group: str | None = None,
              alpha: float = 0.05) -> CheckResult:
    """C-01 — 군별로 본다. 전체를 합쳐 보면 군 차이가 '비정규'로 둔갑한다."""
    from scipy import stats

    groups = ([(str(g), sub[y].dropna().to_numpy(dtype="float64"))
               for g, sub in df.groupby(group, observed=True)] if group
              else [("all", df[y].dropna().to_numpy(dtype="float64"))])
    per, worst = [], "ok"
    causes = set()
    plot = {}
    for name, x in groups:
        p, method = _normality_p(x)
        skew = float(stats.skew(x)) if x.size > 2 else 0.0
        if method == "too_few":
            verdict = "caution"
        elif method == "large_n":
            verdict = "caution" if abs(skew) >= 1 else "ok"
        else:
            verdict = "violated" if p < alpha else "ok"
        cause = _violation_cause(x) if verdict == "violated" else None
        if cause:
            causes.add(cause)
        per.append({"group": name, "n": int(x.size), "p": p, "method": method,
                    "skew": skew, "verdict": verdict, "cause": cause})
        plot[name] = qq_points(x) if x.size >= 8 else {}
        if verdict == "violated":
            worst = "violated"
        elif verdict == "caution" and worst == "ok":
            worst = "caution"

    # 군마다 위배 원인이 다르면 그 자체가 세 번째 분기(형태 상이)다
    cause = ("mixed_shapes" if len(causes) > 1
             else next(iter(causes)) if causes else None)
    bad = [g["group"] for g in per if g["verdict"] == "violated"]
    summary = (msg("a3_norm_ok") if worst == "ok"
               else msg("a3_norm_violated", groups=", ".join(bad),
                        cause=msg(f"a3_cause_{cause}")) if worst == "violated"
               else msg("a3_norm_caution"))
    return CheckResult(id="C-01", name=msg("a3_name_normality"), verdict=worst,
                       summary=summary, per_group=per, cause=cause, plot=plot)


# ── C-02 등분산  ───────────────────────────────────────
def equal_variance(df: pd.DataFrame, y: str, group: str,
                   alpha: float = 0.05) -> CheckResult:
    """C-02 — Brown–Forsythe(중앙값 중심 Levene). 평균 중심보다 비정규에 강하다."""
    from scipy import stats

    parts = [(str(g), sub[y].dropna().to_numpy(dtype="float64"))
             for g, sub in df.groupby(group, observed=True)]
    arrays = [x for _, x in parts if x.size >= 2]
    if len(arrays) < 2:
        return CheckResult(id="C-02", name=msg("a3_name_variance"), verdict="skipped",
                           summary=msg("a3_skip_groups"))
    stat, p = stats.levene(*arrays, center="median")
    sds = {name: float(x.std(ddof=1)) for name, x in parts if x.size >= 2}
    hi, lo = max(sds.values()), min(sds.values())
    verdict = "violated" if p < alpha else "ok"
    summary = (msg("a3_var_violated", ratio=hi / lo if lo else float("inf"), p=p)
               if verdict == "violated" else msg("a3_var_ok", p=p))
    return CheckResult(id="C-02", name=msg("a3_name_variance"), verdict=verdict,
                       summary=summary,
                       per_group=[{"group": k, "sd": v} for k, v in sds.items()],
                       numbers={"stat": float(stat), "p": float(p), "method": "brown-forsythe"})


# ── C-07 다중공선성  ───────────────────────────────────
def collinearity(df: pd.DataFrame, columns: list[str],
                 vif_threshold: float = 5.0) -> CheckResult:
    """C-07 — VIF 와 상관 행렬. VIF = 1/(1-R²), 다른 변수들로 자신을 회귀한 R²."""
    X = df[columns].dropna().to_numpy(dtype="float64")
    if X.shape[0] < len(columns) + 2 or len(columns) < 2:
        return CheckResult(id="C-07", name=msg("a3_name_collinearity"),
                           verdict="skipped", summary=msg("a3_skip_columns"))
    vifs = {}
    for i, c in enumerate(columns):
        others = np.delete(X, i, axis=1)
        A = np.column_stack([np.ones(len(others)), others])
        coef, *_ = np.linalg.lstsq(A, X[:, i], rcond=None)
        resid = X[:, i] - A @ coef
        ss_res = float((resid ** 2).sum())
        ss_tot = float(((X[:, i] - X[:, i].mean()) ** 2).sum())
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        vifs[c] = float(1 / max(1e-12, 1 - r2))
    corr = pd.DataFrame(X, columns=columns).corr().round(3)
    bad = {c: v for c, v in vifs.items() if v >= vif_threshold}
    verdict = "violated" if bad else "ok"
    summary = (msg("a3_vif_violated", cols=", ".join(f"{c} (VIF {v:.1f})"
                                                     for c, v in bad.items()))
               if bad else msg("a3_vif_ok", vmax=max(vifs.values())))
    return CheckResult(id="C-07", name=msg("a3_name_collinearity"), verdict=verdict,
                       summary=summary,
                       per_group=[{"column": c, "vif": v} for c, v in vifs.items()],
                       numbers={"corr": corr.to_dict()})


# ── C-05 독립성  ───────────────────────────────────────
def independence(session_file: str, group: str | None = None) -> CheckResult:
    """C-05 — 데이터만으로는 판정할 수 없다. 확정된 그룹 구조(M0-7)를 근거로 말한다."""
    from statop.session.core import load_session, replay

    st = replay(load_session(session_file))
    structure = st["group_structure"]
    if not structure:
        return CheckResult(id="C-05", name=msg("a3_name_independence"),
                           verdict="caution", summary=msg("a3_indep_unknown"))
    clustered = {c: k for c, k in structure.items() if k in ("cluster", "repeated")}
    if clustered:
        return CheckResult(id="C-05", name=msg("a3_name_independence"),
                           verdict="violated",
                           summary=msg("a3_indep_clustered",
                                       detail=", ".join(f"{c}({k})" for c, k in clustered.items())),
                           numbers={"structure": structure})
    return CheckResult(id="C-05", name=msg("a3_name_independence"), verdict="ok",
                       summary=msg("a3_indep_ok"), numbers={"structure": structure})


# ── 다중검정  ──────────────────────────────────────────
def multiplicity(n_tests: int, alpha: float = 0.05) -> CheckResult:
    """계획 검정 수 → Bonferroni 보정 α. 검정을 늘릴수록 문턱이 낮아진다는 것을 숫자로."""
    adj = alpha / max(1, n_tests)
    verdict = "ok" if n_tests == 1 else "caution"
    return CheckResult(id="C-15", name=msg("a3_name_multiplicity"), verdict=verdict,
                       summary=msg("a3_multi", n=n_tests, alpha=alpha, adj=adj),
                       numbers={"n_tests": n_tests, "alpha": alpha,
                                "alpha_adjusted": adj, "method": "bonferroni"})


# ── 소표본 검정력  ─────────────────────────────────────
def power_check(df: pd.DataFrame, y: str, group: str, alpha: float = 0.05,
                target_power: float = 0.8) -> CheckResult:
    """지금 n으로 80% 검정력이 되는 **최소 효과크기(d)** — 사후검정력 대신 이걸 쓴다.

    관측 효과로 계산한 사후검정력은 p값의 재표현일 뿐이다. 대신
    "이 표본으로는 d≥X 만 잡을 수 있다"와 **어느 군이 부족한지**를 말한다.
    """
    from statsmodels.stats.power import TTestIndPower

    counts = df.groupby(group, observed=True)[y].count()
    if len(counts) != 2:
        return CheckResult(id="C-09", name=msg("a3_name_power"), verdict="skipped",
                           summary=msg("a3_skip_two_groups"))
    n1, n2 = int(counts.iloc[0]), int(counts.iloc[1])
    ratio = n2 / n1 if n1 else 1.0
    solver = TTestIndPower()
    d_min = float(solver.solve_power(effect_size=None, nobs1=n1, ratio=ratio,
                                     alpha=alpha, power=target_power))
    # 어느 방향이 부족한가 — 작은 군을 늘렸을 때가 큰 군을 늘렸을 때보다 이득이 크다
    small = str(counts.idxmin())
    need = float(solver.solve_power(effect_size=0.5, nobs1=None, ratio=1.0,
                                    alpha=alpha, power=target_power))
    verdict = "caution" if d_min > 0.5 else "ok"
    summary = msg("a3_power", d=d_min, n1=n1, n2=n2)
    if verdict == "caution":
        summary += " " + msg("a3_power_short", group=small,
                             need=int(np.ceil(need)))
    return CheckResult(id="C-09", name=msg("a3_name_power"), verdict=verdict,
                       summary=summary,
                       numbers={"min_detectable_d": d_min, "n": dict(counts.astype(int)),
                                "smallest_group": small,
                                "n_per_group_for_d05": int(np.ceil(need))})


# ── 묶음 실행 ────────────────────────────────────────────────
# ── 빠져 있던 가정 검사 6종 ( 에서 드러났다) ──────────────
# 검정이 요구하는 가정인데 검사가 없으면 그 검정은 **영영 초록이 될 수 없다** —
# "가정 검사를 돌리면 갱신됩니다"라고 말해 놓고 갱신할 방법을 안 준 상태였다.

def outliers(df: pd.DataFrame, y: str, limit: float = 0.05) -> CheckResult:
    """C-03 — MAD 3 기준 이상치 비율. 5% 를 넘으면 평균 기반을 먼저 권하지 않는다."""
    x = pd.to_numeric(df[y], errors="coerce").dropna().to_numpy(dtype="float64")
    if x.size < 5:
        return CheckResult("C-03", msg("check_c03_name"), "skipped",
                           msg("check_need_numeric", col=y))
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) * 1.4826
    n_out = int(np.sum(np.abs(x - med) > 3 * mad)) if mad > 0 else 0
    pct = 100 * n_out / x.size
    ok = pct <= limit * 100
    return CheckResult("C-03", msg("check_c03_name"), "ok" if ok else "violated",
                       msg("check_c03_ok" if ok else "check_c03_bad",
                           pct=pct, n=n_out),
                       numbers={"ratio": pct / 100, "n": n_out, "mad": mad})


def shape_similarity(df: pd.DataFrame, y: str, group: str) -> CheckResult:
    """C-04 — 군별 분포 **형태**가 비슷한가.

    형태가 다르면 순위합 비교(MWU·KW)의 결과를 '위치 차이'로 읽을 수 없다.
    """
    from scipy import stats

    parts = [sub[y].dropna().to_numpy(dtype="float64")
             for _, sub in df.groupby(group, observed=True)]
    parts = [x for x in parts if x.size >= 8]
    if len(parts) < 2:
        return CheckResult("C-04", msg("check_c04_name"), "skipped",
                           msg("check_need_two_groups"))
    sk = [float(stats.skew(x)) for x in parts]
    ku = [float(stats.kurtosis(x)) for x in parts]
    dskew, dkurt = max(sk) - min(sk), max(ku) - min(ku)
    ok = dskew < 1.0 and dkurt < 2.0
    return CheckResult("C-04", msg("check_c04_name"), "ok" if ok else "violated",
                       msg("check_c04_ok" if ok else "check_c04_bad",
                           dskew=dskew, dkurt=dkurt),
                       numbers={"d_skew": dskew, "d_kurt": dkurt})


def sphericity(df: pd.DataFrame, y: str, group: str, subject: str) -> CheckResult:
    """C-06 — 시점 **쌍마다** 차이의 분산이 비슷한가 (구형성의 실질).

    Mauchly 대신 쌍별 차이 분산비를 쓴다 — 읽는 사람이 무엇을 본 것인지 알 수 있다.
    """
    wide = df.pivot_table(index=subject, columns=group, values=y, aggfunc="mean")
    wide = wide.dropna()
    if wide.shape[1] < 3 or wide.shape[0] < 5:
        return CheckResult("C-06", msg("check_c06_name"), "skipped",
                           msg("check_need_repeats"))
    cols = list(wide.columns)
    vs = [float(np.var(wide[a] - wide[b], ddof=1))
          for i, a in enumerate(cols) for b in cols[i + 1:]]
    vs = [v for v in vs if v > 0]
    if len(vs) < 2:
        return CheckResult("C-06", msg("check_c06_name"), "skipped",
                           msg("check_need_repeats"))
    ratio = max(vs) / min(vs)
    ok = ratio < 3.0
    return CheckResult("C-06", msg("check_c06_name"), "ok" if ok else "violated",
                       msg("check_c06_ok" if ok else "check_c06_bad", ratio=ratio),
                       numbers={"var_ratio": ratio})


def linearity(df: pd.DataFrame, y: str, x: str) -> CheckResult:
    """C-08 — 직선으로 본 설명력과 순위로 본 설명력을 견준다.

    순위 쪽이 훨씬 크면 관계가 곡선이라는 뜻이고, 그때 Pearson 은 관계를 과소평가한다.
    """
    from scipy import stats

    a = pd.to_numeric(df[y], errors="coerce")
    b = pd.to_numeric(df[x], errors="coerce")
    ok_rows = a.notna() & b.notna()
    a, b = a[ok_rows].to_numpy(), b[ok_rows].to_numpy()
    if a.size < 8:
        return CheckResult("C-08", msg("check_c08_name"), "skipped",
                           msg("check_need_numeric", col=x))
    r2 = float(stats.pearsonr(a, b)[0]) ** 2
    s2 = float(stats.spearmanr(a, b)[0]) ** 2
    ok = s2 - r2 < 0.10
    return CheckResult("C-08", msg("check_c08_name"), "ok" if ok else "violated",
                       msg("check_c08_ok" if ok else "check_c08_bad", r2=r2, s2=s2),
                       numbers={"r2": r2, "rho2": s2})


def dispersion(df: pd.DataFrame, y: str) -> CheckResult:
    """C-10 — 카운트의 분산/평균 비와 0 비율. 1 보다 크게 넘으면 과산포다."""
    x = pd.to_numeric(df[y], errors="coerce").dropna().to_numpy(dtype="float64")
    if x.size < 5 or x.mean() <= 0:
        return CheckResult("C-10", msg("check_c10_name"), "skipped",
                           msg("check_need_numeric", col=y))
    ratio = float(x.var(ddof=1) / x.mean())
    zero = float(np.mean(x == 0))
    ok = ratio <= 1.5 and zero < 0.5
    return CheckResult("C-10", msg("check_c10_name"), "ok" if ok else "violated",
                       msg("check_c10_ok" if ok else "check_c10_bad",
                           ratio=ratio, zero=zero),
                       numbers={"var_mean_ratio": ratio, "zero_ratio": zero})


def proportional_hazards(df: pd.DataFrame, y: str, group: str,
                         event: str | None) -> CheckResult:
    """C-11 — 비례위험. 시간·사건이 있어야 볼 수 있다."""
    if not event or event not in df.columns:
        return CheckResult("C-11", msg("check_c11_name"), "skipped",
                           msg("check_c11_skip"))
    try:
        from lifelines.statistics import proportional_hazard_test  # noqa: F401
    except ImportError:
        return CheckResult("C-11", msg("check_c11_name"), "skipped",
                           msg("check_c11_skip"))
    return CheckResult("C-11", msg("check_c11_name"), "skipped",
                       msg("check_c11_skip"))


def run_checks(session_file: str, sample_n: int = 10_000) -> list[CheckResult]:
    """현재 질문 설계(A1)에 맞는 가정 검사만 돌린다 — 전부가 아니라 관련된 것만."""
    from statop.analyze.spec import current
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])

    st = replay(doc)
    mapping = st["label_maps"].get(src["id"], {}).get(spec.group) if spec.group else None
    if mapping:  # 라벨 매핑을 반영한 군으로 검사한다 — 묶은 대로 비교되므로
        df = df.assign(**{spec.group: df[spec.group].astype(str).map(
            lambda v: str(mapping.get(v, v)))})

    # 상관(Q-03)·회귀(Q-08)에서 group 은 **군이 아니라 두 번째 연속 변수**다.
    # 그걸로 군을 나누면 값마다 n=1 짜리 군이 수백 개 생기고, 정규성이 늘 '표본 부족'이
    # 되어 Pearson 이 영영 초록으로 못 올라간다 (실측으로 그랬다)
    pairwise = spec.question in ("Q-03", "Q-08")
    if pairwise:
        out = [normality(df, spec.y, None)]
        if spec.group and spec.group in df.columns and df[spec.group].dtype.kind in "if":
            out.append(normality(df, spec.group, None))
    else:
        out = [normality(df, spec.y, spec.group)]
    if spec.group and spec.question != "Q-03":
        out.append(equal_variance(df, spec.y, spec.group))
        out.append(power_check(df, spec.y, spec.group))
    if spec.question in ("Q-03", "Q-08"):
        numeric = [c for c in df.columns
                   if df[c].dtype.kind in "if" and c != spec.y][:8]
        if spec.group and spec.group in numeric:
            out.append(collinearity(df, [spec.y, *numeric][:6]))
    # 빠져 있던 가정들 — 그 검정이 초록이 되려면 이것들이 돌아야 한다
    if spec.y in df.columns and df[spec.y].dtype.kind in "if":
        out.append(outliers(df, spec.y))
        if pairwise and spec.group in df.columns and df[spec.group].dtype.kind in "if":
            out.append(linearity(df, spec.y, spec.group))
        if getattr(spec, "y_kind", None) == "count" or _looks_count(df[spec.y]):
            out.append(dispersion(df, spec.y))
    if spec.group and not pairwise and spec.group in df.columns:
        out.append(shape_similarity(df, spec.y, spec.group))
        if spec.paired and spec.subject and spec.subject in df.columns:
            out.append(sphericity(df, spec.y, spec.group, spec.subject))
    if spec.question == "Q-09":
        out.append(proportional_hazards(df, spec.y, spec.group, spec.event))
    out.append(independence(session_file, spec.group))
    out.append(multiplicity(spec.n_tests))
    return out


def _looks_count(sr) -> bool:  # noqa: ANN001
    """비음 정수만 있으면 카운트로 본다 — 과산포 검사를 걸지 말지 정하는 데만 쓴다."""
    x = pd.to_numeric(sr, errors="coerce").dropna()
    return bool(len(x)) and bool((x >= 0).all()) and bool((x % 1 == 0).all())


# ── 실행한 검정이 요구하는 가정만 (자동 병기) ────────────────
# 질문 유형이 아니라 **실제로 돌린 검정**이 기준이다. T-101(Welch)은 정규성을 묻고
# T-103(MWU)은 분포 형태를 묻는다 — 같은 질문이어도 필요한 가정이 다르다.
_C_PATTERN = re.compile(r"C-\d{2}")


def assumptions_of(test_id: str) -> list[str]:
    """이 검정이 요구하는 가정(C-xx) — 규칙표의 assumptions 칸이 원본이다.

    `linked_tests` 가 'T-1xx' 처럼 묶음으로 적힌 가정도 있으므로 양쪽을 다 본다.
    """
    from statop.analyze.candidates import _rules

    own: list[str] = []
    declared = False
    for t in _rules()["tests"]:
        if t["id"] == test_id:
            own = _C_PATTERN.findall(t.get("assumptions") or "")
            # 'C-01' 처럼 **ID로** 적어 뒀을 때만 구체적 진술로 본다. T-802 의
            # "잔차 정규·등분산·독립·선형" 처럼 산문뿐이면 묶음 표기를 살려야 한다
            declared = bool(own)
            break

    import yaml

    from statop.rules.build import RULES_DIR

    ids = list(own)
    for c in yaml.safe_load((RULES_DIR / "assumptions.yaml").read_text(encoding="utf-8")):
        linked = str(c.get("linked_tests") or "")
        if c["id"] in ids:
            continue
        # 모든 검정에 걸리는 것(독립성·표본크기·결측·다중검정)은 언제나 붙는다
        if "전부" in linked or "모든" in linked:  # rule-vocab
            ids.append(c["id"])
            continue
        if re.search(rf"\b{re.escape(test_id)}\b", linked):
            ids.append(c["id"])
            continue
        # 'T-1xx' 같은 **묶음** 표기는 그 검정이 자기 가정을 직접 적어 두지 않았을 때만
        # 편다. T-103(비모수)에 C-01 정규성을 붙이면 틀린 경고가 된다 —
        # 구체적인 진술이 일반적인 진술을 이긴다
        if declared:
            continue
        for fam in re.findall(r"T-(\d)xx", linked):
            if test_id.startswith(f"T-{fam}"):
                ids.append(c["id"])
                break
    return sorted(dict.fromkeys(ids))


def checks_for_test(session_file: str, test_id: str,
                    sample_n: int = 10_000) -> list[CheckResult]:
    """그 검정이 요구하는 가정만 돌린다 — 값과 p 아래에 바로 붙이기 위한 것."""
    from statop.analyze.spec import current
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    wanted = set(assumptions_of(test_id))
    if not wanted:
        return []

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    mapping = st["label_maps"].get(src["id"], {}).get(spec.group) if spec.group else None
    if mapping:
        df = df.assign(**{spec.group: df[spec.group].astype(str).map(
            lambda v: str(mapping.get(v, v)))})

    out: list[CheckResult] = []
    if "C-01" in wanted:
        out.append(normality(df, spec.y, spec.group))
    if "C-02" in wanted and spec.group:
        out.append(equal_variance(df, spec.y, spec.group))
    if "C-07" in wanted:
        numeric = [c for c in df.columns
                   if df[c].dtype.kind in "if" and c != spec.y][:5]
        if numeric:
            out.append(collinearity(df, [spec.y, *numeric][:6]))
    if "C-05" in wanted:
        out.append(independence(session_file, spec.group))
    if "C-09" in wanted and spec.group:
        out.append(power_check(df, spec.y, spec.group))
    if "C-15" in wanted:
        out.append(multiplicity(spec.n_tests))
    # 아직 검사 함수가 없는 가정은 **말은 해준다** — 조용히 빠지면 확인된 줄 안다
    covered = {"C-01", "C-02", "C-05", "C-07", "C-09", "C-15"}
    for cid in sorted(wanted - covered):
        out.append(_unchecked(cid))
    return out


def _unchecked(cid: str) -> CheckResult:
    """자동 검사가 없는 가정 — 무엇을 사람이 봐야 하는지 규칙표 그대로 전한다."""
    import yaml

    from statop.rules.build import RULES_DIR

    row = next((c for c in yaml.safe_load(
        (RULES_DIR / "assumptions.yaml").read_text(encoding="utf-8"))
        if c["id"] == cid), {})
    return CheckResult(
        id=cid, name=row.get("check") or cid, verdict="skipped",
        summary=msg("a3_manual_check", method=row.get("method") or "-"),
        numbers={"action": row.get("on_violation") or "-"})
