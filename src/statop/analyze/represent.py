"""Q-12 표본 크기·대표성  — "몇 행만 봐도 전체를 닮는가".

Q-01~11 은 "내 가설이 맞나"를 묻고 답이 p 값이다. Q-12 는 그 앞의 질문 —
**"분석을 어떻게 설계하나"** 를 묻고 답이 **n** 이다.

전체 N 행에서 n 행을 뽑아 **뽑은 것의 분포와 전체 분포의 거리**를 재고, n 을 키우며
그 거리가 어디서 더 안 줄어드는지 본다. 거리는 규칙표에서 고른다 (T-1201~1203):

- `SC-DIST-18` **KS distance** — 두 누적분포의 최대 세로 간격. 0~1 무단위라
  단위가 다른 컬럼을 한 축에 놓을 수 있다. 연속 컬럼의 기본값
- `SC-DIST-19` **총변동거리(TV)** — 범주별 비율 차이 절댓값의 합의 절반. 범주 컬럼
- `SC-DIST-13` **1-Wasserstein 거리** — 차이의 크기를 **원 단위**로. 컬럼끼리 못 더한다

**n 마다 여러 번 다시 뽑아 평균낸다.** 한 번만 뽑으면 그 한 번의 운을 곡선으로
착각한다. 반복 횟수와 seed 는 기록되어 재현된다.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statop.messages import msg

KS, TV, W1 = "SC-DIST-18", "SC-DIST-19", "SC-DIST-13"

# 관행일 뿐이다 — 무엇이 충분한지는 쓰임새가 정한다. 화면에도 그렇게 적는다
DEFAULT_THRESHOLD = 0.05
DEFAULT_REPEATS = 20


@dataclass
class Point:
    n: int
    mean: float
    lo: float          # 반복 중 최솟값·최댓값 — 평균만 보면 그 n 의 운을 못 본다
    hi: float
    values: list = field(default_factory=list)   # 매 반복의 거리 — 분포를 보려면 원값이 필요하다


@dataclass
class ColumnCurve:
    column: str
    kind: str                       # continuous | categorical
    metric: str                     # SC-DIST-*
    metric_name: str
    unit_free: bool                 # 0~1 무단위라 다른 컬럼과 한 축에 놓을 수 있는가
    points: list = field(default_factory=list)
    enough_n: int | None = None
    n_used: int = 0                 # 결측을 뺀 뒤 실제로 쓴 행 수


@dataclass
class Report:
    total_rows: int
    repeats: int
    seed: int
    threshold: float
    ladder: list = field(default_factory=list)
    curves: list = field(default_factory=list)
    enough_n: int | None = None     # 모든 컬럼이 임계 아래로 내려오는 n
    limiting: list = field(default_factory=list)   # 가장 늦게 내려온 컬럼
    skipped_ids: list = field(default_factory=list)  # 식별자로 보아 뺀 컬럼


def _ks(sub: np.ndarray, full_sorted: np.ndarray) -> float:
    """두 누적분포의 최대 세로 간격 (SC-DIST-18).

    뽑은 표본은 전체의 부분집합이므로 전체의 관측점에서만 보면 충분하다 —
    두 계단함수의 차이가 최대가 되는 곳은 반드시 관측점이다.
    """
    sub_sorted = np.sort(sub)
    f_sub = np.searchsorted(sub_sorted, full_sorted, side="right") / sub_sorted.size
    f_all = np.searchsorted(full_sorted, full_sorted, side="right") / full_sorted.size
    return float(np.max(np.abs(f_sub - f_all)))


def _tv(sub: pd.Series, full_p: pd.Series) -> float:
    """범주별 비율 차이 절댓값의 합의 절반 (SC-DIST-19)."""
    p = sub.value_counts(normalize=True)
    q = full_p
    keys = p.index.union(q.index)
    return float(0.5 * np.abs(p.reindex(keys, fill_value=0.0).to_numpy()
                              - q.reindex(keys, fill_value=0.0).to_numpy()).sum())


def _w1(sub: np.ndarray, full: np.ndarray) -> float:
    """한 분포를 다른 분포로 옮기는 최소 운송 비용 — **단위가 원변수다** (SC-DIST-13)."""
    from scipy.stats import wasserstein_distance

    return float(wasserstein_distance(sub, full))


def ladder(total: int, steps: int = 10, start: int = 100) -> list[int]:
    """n 후보 — 로그 간격. 선형 간격이면 작은 n 쪽 변화가 다 뭉개진다."""
    if total <= start:
        return [total]
    xs = np.unique(np.geomspace(start, total, num=steps).astype(int))
    return [int(x) for x in xs if x >= 2]


def _identifiers(df: pd.DataFrame, cols: list, types: dict) -> list:
    """행마다 값이 다른 컬럼 — **어떤 n 으로도 전체를 닮을 수 없다.**

    표본을 아무리 키워도 남은 값이 빠져 있으므로 거리가 안 내려가고, 그 한 컬럼이
    "충분한 n = 전체" 라는 답을 만들어 버린다. 수치형은 빼지 않는다 —
    나이·발현량은 원래 고유값이 거의 전부다 (balance.py MB-C08 과 같은 판단).
    """
    from statop.groups import ID_UNIQUE_RATIO

    n = len(df)
    return [c for c in cols
            if types.get(c) == "id"
            or (n and not pd.api.types.is_numeric_dtype(df[c])
                and df[c].nunique(dropna=True) / n >= ID_UNIQUE_RATIO)]


def _kind_of(sr: pd.Series, semantic: str | None) -> str:
    if semantic in ("category", "nominal", "ordinal", "id"):
        return "categorical"
    return "continuous" if sr.dtype.kind in "if" else "categorical"


def curve(values: pd.Series, kind: str, metric: str, ns: list[int],
          repeats: int, rng: np.random.Generator) -> list[Point]:
    """n 마다 repeats 번 다시 뽑아 거리의 평균·최소·최대를 낸다."""
    v = values.dropna()
    total = v.size
    if kind == "continuous":
        arr = v.to_numpy(dtype="float64")
        full_sorted = np.sort(arr)
        full_p = None
    else:
        arr = v
        full_sorted = None
        full_p = v.value_counts(normalize=True)

    out = []
    for n in ns:
        if n >= total:
            out.append(Point(n=total, mean=0.0, lo=0.0, hi=0.0, values=[0.0]))
            continue
        ds = []
        for _ in range(repeats):
            idx = rng.choice(total, size=n, replace=False)
            if kind == "continuous":
                s = arr[idx]
                ds.append(_ks(s, full_sorted) if metric == KS else _w1(s, arr))
            else:
                ds.append(_tv(arr.iloc[idx], full_p))
        out.append(Point(n=n, mean=float(np.mean(ds)), lo=float(np.min(ds)),
                         hi=float(np.max(ds)), values=[float(x) for x in ds]))
    return out


def _enough(points: list[Point], threshold: float, total: int) -> int | None:
    """임계 아래로 내려온 뒤 **다시 올라오지 않는** 첫 n.

    한 번 내려간 것만 보면 우연히 낮게 나온 n 을 답으로 내놓게 된다.
    **n = 전체는 답이 될 수 없다** — 그 점의 거리 0 은 재서 나온 값이 아니라
    자기 자신과의 거리라는 정의다. 그걸 답으로 내면 "전부 다 보면 전부를 닮는다"는
    동어반복이 된다.
    """
    for i, p in enumerate(points):
        if p.n >= total:
            break
        if all(q.mean <= threshold for q in points[i:]):
            return p.n
    return None


def build(session_file: str, columns: list[str] | None = None,
          metric: str = KS, threshold: float = DEFAULT_THRESHOLD,
          repeats: int = DEFAULT_REPEATS, seed: int = 0, steps: int = 10,
          sample_n: int = 1_000_000, progress=None) -> Report:
    """부분표집 곡선 (T-1201~1203).

    `sample_n` 기본값이 크다 — 대표성을 물으려면 **전체를 봐야** 한다. 다른 기능처럼
    1만 행만 읽으면 "1만 행을 닮는 n"을 답하게 된다.
    """
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})
    cols = columns or [c for c in st["selected"].get(src["id"], list(df.columns))
                       if c in df.columns]
    cols = [c for c in cols if c in df.columns]
    ids = _identifiers(df, cols, types)
    cols = [c for c in cols if c not in ids]
    if not cols:
        raise ValueError(msg("represent_no_columns"))

    rep = Report(total_rows=int(len(df)), repeats=repeats, seed=seed,
                 threshold=threshold, ladder=ladder(int(len(df)), steps),
                 skipped_ids=ids)
    names = {KS: "KS distance", TV: "total variation distance",
             W1: "1-Wasserstein distance"}
    for i, c in enumerate(cols):
        if progress:
            progress(i / len(cols))
        kind = _kind_of(df[c], types.get(c))
        # 범주 컬럼에 KS 를 걸 수 없다 — 규칙표가 그렇게 적혀 있다 (T-1202)
        m = metric if kind == "continuous" else TV
        v = df[c].dropna()
        cc = ColumnCurve(column=c, kind=kind, metric=m, metric_name=names[m],
                         unit_free=m in (KS, TV), n_used=int(v.size))
        ns = ladder(int(v.size), steps)
        # 고른 seed 로 컬럼마다 다시 뽑는다 — 같은 인덱스를 돌려 쓰면 한 번의 운이
        # 모든 컬럼에 똑같이 실린다
        cc.points = curve(v, kind, m, ns, repeats,
                          np.random.default_rng([seed, i]))
        cc.enough_n = _enough(cc.points, threshold, int(v.size))
        rep.curves.append(cc)
    if progress:
        progress(1.0)

    unit_free = [c for c in rep.curves if c.unit_free]
    if unit_free and all(c.enough_n is not None for c in unit_free):
        rep.enough_n = max(c.enough_n for c in unit_free)
        # 어느 컬럼이 끝까지 안 내려왔는지 이름을 댄다
        rep.limiting = [c.column for c in unit_free if c.enough_n == rep.enough_n]
    else:
        rep.limiting = [c.column for c in unit_free if c.enough_n is None]
    return rep


# ── 거리 분포 (임계를 감으로 잡지 않게) ─────────────────────
@dataclass
class Spread:
    """한 n 에서 **다시 뽑을 때마다 나온 거리들**의 분포.

    "0.05 는 관행"이라고만 하면 어디에 선을 그을지 알 수 없다. 같은 자료를 같은 n 으로
    여러 번 뽑았을 때 거리가 실제로 어느 구간에 떨어지는지 보면, **우연만으로 나오는
    크기**가 얼마인지 알 수 있고 그것보다 위에 선을 그으면 된다.
    """

    column: str
    kind: str
    metric: str
    metric_name: str
    n: int
    draws: int
    values: list = field(default_factory=list)
    q: dict = field(default_factory=dict)        # p0 p5 p25 p50 p75 p95 p100
    bins: list = field(default_factory=list)     # (left, right, count)


def _hist(vals: np.ndarray, k: int = 12) -> list:
    lo, hi = float(vals.min()), float(vals.max())
    if hi <= lo:
        return [(lo, hi, int(vals.size))]
    edges = np.linspace(lo, hi, k + 1)
    cnt, _ = np.histogram(vals, bins=edges)
    return [(float(edges[i]), float(edges[i + 1]), int(cnt[i])) for i in range(k)]


def spread(session_file: str, n: int, columns: list[str] | None = None,
           metric: str = KS, draws: int = 200, seed: int = 0,
           sample_n: int = 1_000_000, progress=None) -> list[Spread]:
    """n 을 고정하고 여러 번 다시 뽑아 **거리 자체의 분포**를 낸다.

    곡선은 n 에 따라 평균이 어떻게 줄어드는지 보여 주고, 이것은 **한 n 안에서 거리가
    얼마나 흩어지는지** 보여 준다. 임계를 정할 때 보는 것은 뒤쪽이다.
    """
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})
    cols = columns or [c for c in st["selected"].get(src["id"], list(df.columns))
                       if c in df.columns]
    cols = [c for c in cols if c in df.columns]
    cols = [c for c in cols if c not in _identifiers(df, cols, types)]
    if not cols:
        raise ValueError(msg("represent_no_columns"))

    names = {KS: "KS distance", TV: "total variation distance",
             W1: "1-Wasserstein distance"}
    out = []
    for i, c in enumerate(cols):
        if progress:
            progress(i / len(cols))
        kind = _kind_of(df[c], types.get(c))
        m = metric if kind == "continuous" else TV
        v = df[c].dropna()
        if not 1 < n < v.size:
            continue
        pts = curve(v, kind, m, [n], draws, np.random.default_rng([seed, i]))
        vals = np.asarray(pts[0].values, dtype="float64")
        out.append(Spread(
            column=c, kind=kind, metric=m, metric_name=names[m], n=n,
            draws=int(vals.size), values=[float(x) for x in vals],
            q={f"p{p}": float(np.percentile(vals, p))
               for p in (0, 5, 25, 50, 75, 95, 100)},
            bins=_hist(vals)))
    if progress:
        progress(1.0)
    return out


def statement(rep: Report) -> tuple[str, str]:
    """고른 n 을 **반증 가능한 한 문장**으로 (PLAN  ④ → A5 경로).

    "n≈3,494 면 충분하다"는 확인할 수 없는 말이다. 확인할 수 있는 형태는
    "이 n 행은 남은 행과 구별되지 않는다" 이고, 그것이 T-1204 가 보는 것이다.
    """
    if rep.enough_n is None:
        return "", ""
    rest = rep.total_rows - rep.enough_n
    return (msg("represent_hypothesis", n=rep.enough_n, rest=rest),
            msg("represent_hypothesis_how"))


# ── T-1204 고른 n 의 검증 ───────────────────────────────────
@dataclass
class Holdout:
    column: str
    kind: str
    n_picked: int
    n_rest: int
    distance: float
    metric: str
    p: float | None
    test: str


def verify(session_file: str, n: int, columns: list[str] | None = None,
           seed: int = 0, sample_n: int = 1_000_000) -> list[Holdout]:
    """뽑은 n 행 vs **남은 N−n 행** (T-1204).

    전체와 대조하지 않는다 — 뽑은 것이 전체에 들어 있어 독립적인 비교가 아니다.
    무작위로 갈랐다면 두 쪽은 서로 바꿔도 되는 관계이므로 두 표본 비교가 성립한다.
    """
    from scipy.stats import chi2_contingency, ks_2samp

    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})
    cols = columns or [c for c in st["selected"].get(src["id"], list(df.columns))
                       if c in df.columns]
    total = len(df)
    if not 1 < n < total:
        raise ValueError(msg("represent_bad_n", n=n, total=total))

    rng = np.random.default_rng(seed)
    idx = rng.permutation(total)
    pick, rest = df.iloc[idx[:n]], df.iloc[idx[n:]]

    out = []
    for c in cols:
        a, b = pick[c].dropna(), rest[c].dropna()
        if a.empty or b.empty:
            continue
        kind = _kind_of(df[c], types.get(c))
        if kind == "continuous":
            av, bv = a.to_numpy(dtype="float64"), b.to_numpy(dtype="float64")
            r = ks_2samp(av, bv)
            out.append(Holdout(column=c, kind=kind, n_picked=int(a.size),
                               n_rest=int(b.size), distance=float(r.statistic),
                               metric=KS, p=float(r.pvalue), test="T-701"))
        else:
            tab = pd.crosstab(pd.concat([a, b]),
                              np.r_[np.zeros(a.size), np.ones(b.size)])
            d = _tv(a, b.value_counts(normalize=True))
            p = None
            if tab.shape[0] > 1 and (tab.to_numpy() >= 5).all():
                p = float(chi2_contingency(tab).pvalue)
            out.append(Holdout(column=c, kind=kind, n_picked=int(a.size),
                               n_rest=int(b.size), distance=d, metric=TV,
                               p=p, test="T-201"))
    return out
