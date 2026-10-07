"""M1-1 의미 타입 판별 (S-T01~15, DECISIONS).

저장 타입(float64)이 아니라 **값이 실제로 무엇인가**(count·비율·확률·정규화 점수…)를 본다.
여기가 틀리면 이후 검정 선택이 전부 틀린다.

원칙:
- **순위만 제시하고 점수는 보이지 않는다** — 유사확률 표기는 의존 편향을 만든다
- 동점은 공동 순위. 근거는 분포 형태를 말로 (단봉형/쌍봉형/평탄)
- 신호가 상충하면 순위를 낮추지 말고 **"상충"으로 표시하고 확정을 요구**
- 확정 요구는 순위 차이뿐 아니라 **오분류 비용**도 본다 (probability ↔ proportion 등)
- 사용자는 언제든 다른 타입으로 확정할 수 있다 — **막지 않되 결과의 위험을 고지한다** (요구사항-7)
"""

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# 오분류 비용이 큰 조합 — 순위가 벌어져도 확정을 요구한다
COSTLY_PAIRS = {
    frozenset({"probability", "proportion"}),
    frozenset({"proportion", "normalized score"}),
    frozenset({"count", "proportion"}),
    frozenset({"log-scale", "continuous"}),
    frozenset({"ordinal code", "nominal code"}),
}


@dataclass
class Candidate:
    type: str
    rank: int          # 공동 순위 (1,1,3 …)
    evidence: list[str]  # 왜 이 타입인가 — 사용자가 판단할 근거
    _score: float = field(default=0.0, repr=False)  # 내부 정렬용. 절대 노출하지 않는다


@dataclass
class TypeInference:
    column: str
    candidates: list[Candidate]
    shape: str                 # 언어 독립 코드 (unimodal/bimodal/…) — 표시는 shape_label
    conflicts: list[str]       # 상충 신호
    needs_confirm: bool        # 확정을 요구해야 하는가
    confirm_reason: str | None


SHAPE_KEYS = ("unimodal", "bimodal", "bimodal_ends", "skewed", "flat",
              "categorical", "too_few")


def shape_label(code: str) -> str:
    """형태 코드를 표시 문장으로 — 로직은 코드로 비교하고 화면만 번역한다."""
    from statop.messages import msg

    return msg(f"shape_{code}")


def _shape(x: np.ndarray) -> str:
    """분포 형태를 **언어 독립 코드**로 반환한다 (표시는 shape_label이 한다)."""
    if x.size < 10:
        return "too_few"
    uniq = np.unique(x)
    if uniq.size <= 20 and np.all(np.equal(np.mod(x, 1), 0)):
        # 정수·소수 수준: 히스토그램 구간이 값 사이에 걸치면 가짜 봉우리가 생긴다
        hist = np.array([int((x == u).sum()) for u in uniq])
    else:
        hist, _ = np.histogram(x, bins=min(20, max(5, int(np.sqrt(x.size)))))
    if hist.max() == 0:
        return "flat"

    # 평탄부터 판정한다 — 균등분포를 봉우리 여러 개로 오해하지 않기 위해
    if hist.std() / max(1e-9, hist.mean()) < 0.35:
        return "flat"

    # 양끝 집중은 **양쪽 모두** 두꺼울 때만 — 한쪽만 몰린 건 치우침이지 쌍봉이 아니다
    lo, hi = hist[0] / max(1, hist.sum()), hist[-1] / max(1, hist.sum())
    if lo > 0.15 and hi > 0.15:
        return "bimodal_ends"     # 0/1 근처 집중 — 확률의 전형

    # 봉우리: 이웃보다 **엄격히** 크고, 전체 최대의 40% 이상이며, 서로 떨어져 있어야 한다
    peaks = []
    for i in range(1, len(hist) - 1):
        if hist[i] > hist[i - 1] and hist[i] > hist[i + 1] and hist[i] > hist.max() * 0.4:
            if not peaks or i - peaks[-1] >= 2:
                peaks.append(i)
    if len(peaks) >= 2:
        return "bimodal"

    skew = float(pd.Series(x).skew()) if x.size > 2 else 0.0
    if abs(skew) >= 1:
        return "skewed"
    return "unimodal"


COMP_CACHE = "statop_composition_sets"   # 같은 프레임에 같은 질문을 두 번 하지 않게


def composition_set(df: pd.DataFrame, name: str) -> set[str]:
    """name이 속한 조성 세트를 찾는다 — 행 합이 1(또는 100)에 가까운 컬럼 묶음 (C-12).

    후보 묶음: ① 같은 이름 접두(comp00_frac01 → comp00_) ② 전체 수치 컬럼.

    타입 추론은 이걸 컬럼마다 두 번(후보 점수 + 세트 일부 경고) 묻는다. 프레임이
    같으면 답도 같으므로 그 프레임에 적어 둔다 — 안 그러면 25컬럼 추론이 19초였다.
    """
    if df is None or name not in df.columns:
        return set()
    # 잘라낸 프레임은 attrs 를 물려받는다 — 컬럼 구성이 다르면 답도 다르므로
    # 그때는 캐시를 버린다 (물려받은 답을 그대로 쓰면 없는 세트를 찾아낸다)
    cols = tuple(df.columns)
    cache = df.attrs.get(COMP_CACHE)
    if cache is None or cache["cols"] != cols:
        cache = df.attrs[COMP_CACHE] = {"cols": cols, "sets": {}}
    if name in cache["sets"]:
        return cache["sets"][name]
    out = cache["sets"][name] = _composition_set(df, name)
    return out


def _composition_set(df: pd.DataFrame, name: str) -> set[str]:

    def sums_to_one(cols: list[str]) -> bool:
        if len(cols) < 2:
            return False
        # 결측이 있으면 행 합이 1이 될 수 없다 — **완전한 행만** 보고 판단한다
        block = df[cols].dropna()
        if len(block) < max(10, 0.05 * len(df)):
            return False
        rs = block.sum(axis=1, numeric_only=True)
        return bool(np.isclose(rs, 1.0, atol=0.01).mean() > 0.9
                    or np.isclose(rs, 100.0, atol=1.0).mean() > 0.9)

    # ① 같은 이름 접두 묶음 (comp00_frac01 … 처럼 번호가 붙는 흔한 형태)
    prefix = re.sub(r"[_\-]?\w?\d*$", "", name)
    if prefix and len(prefix) >= 2:
        group = [c for c in df.columns if c.startswith(prefix)]
        if sums_to_one(group):
            return set(group)

    # ② 이름에 의존하지 않는 탐색.
    #    핵심 성질: 조성 성분을 빼면 잔차(1 - 누적합)가 **음수가 되지 않는다**.
    #    무관한 컬럼은 잔차를 음수로 만들므로 이걸로 걸러낸다.
    # 수치가 아닌 컬럼은 아예 후보가 아니다 — 문자열·날짜와 크기를 비교하면 터진다
    numeric = df.select_dtypes(include="number")
    if name not in numeric.columns:
        return set()
    pool = [c for c in numeric.columns
            if c != name and numeric[c].dropna().between(-0.01, 1.01).all()]
    if not pool:
        return set()

    # 후보마다 `df[[*chosen, c]].dropna()` 를 새로 만들면 컬럼 하나에 0.5초가 든다
    # (실측). 값은 한 번만 꺼내 두고 **누적합과 결측 마스크를 굴린다** — 보는 식은
    # 위와 같다: 고른 컬럼들이 모두 있는 행에서 잔차 1 - 합
    vals = {c: numeric[c].to_numpy(dtype="float64") for c in (name, *pool)}
    nan = {c: np.isnan(v) for c, v in vals.items()}
    chosen = [name]
    total = vals[name].copy()
    ok = ~nan[name]
    for _ in range(len(pool)):
        if not ok.any():
            return set()
        residual = 1.0 - total[ok]
        if float(np.abs(residual).mean()) < 0.01 and sums_to_one(chosen):
            return set(chosen)

        best, best_gap = None, float("inf")
        for c in pool:
            if c in chosen:
                continue
            m = ok & ~nan[c]
            if int(m.sum()) < 10:
                continue
            res = 1.0 - (total[m] + vals[c][m])
            if (res < -0.01).mean() > 0.01:   # 음수 잔차가 생기면 조성 성분이 아니다
                continue
            gap = float(res.mean())
            if gap < best_gap:
                best, best_gap = c, gap
        if best is None:
            return set()
        chosen.append(best)
        total = total + vals[best]
        ok = ok & ~nan[best]
    return set(chosen) if sums_to_one(chosen) else set()


def infer(s: pd.Series, name: str, siblings: pd.DataFrame | None = None) -> TypeInference:
    """한 컬럼의 의미 타입 후보를 순위로. siblings가 있으면 행 합(조성)을 함께 본다."""
    from statop.messages import msg

    v = s.dropna()
    ev: dict[str, list[str]] = {}
    score: dict[str, float] = {}
    conflicts: list[str] = []

    def add(t: str, pts: float, why: str) -> None:
        score[t] = score.get(t, 0) + pts
        ev.setdefault(t, []).append(why)

    # ── 비수치: id / 범주 ──────────────────────────────────
    if v.dtype.kind not in "ifb":
        uniq = v.nunique() / max(1, len(v))
        if uniq > 0.9:
            add("id", 3, msg("ev_unique_ratio", ratio=uniq))
        else:
            add("nominal code", 3, msg("ev_few_levels", n=v.nunique()))
            # 그룹 변수(label) 후보 — 이름 힌트가 있으면 우선, 없어도 수준이 적으면 제시
            hint = bool(re.search(r"label|group|arm|class|cohort|dx|diagnos|status|grade",
                                  name, re.I))
            if hint:
                add("label", 3.5, msg("ev_label_name_hint", name=name))
            elif v.nunique() <= 6:
                add("label", 2, msg("ev_label_few_levels", n=v.nunique()))
            if v.nunique() <= 10:
                add("ordinal code", 1, msg("ev_few_levels_ordered", n=v.nunique()))
                conflicts.append(msg("conflict_nominal_ordinal"))
        try:
            pd.to_datetime(v.head(50), format="mixed")
            add("datetime", 2, msg("ev_parses_as_date"))
        except (ValueError, TypeError):
            pass
        return _finish(name, score, ev, "categorical", conflicts)

    x = v.to_numpy(dtype="float64")
    if x.size == 0:
        return _finish(name, {"continuous": 1}, {"continuous": [msg("ev_empty")]},
                       "too_few", [])

    mn, mx = float(x.min()), float(x.max())
    is_int = bool(np.all(np.equal(np.mod(x, 1), 0)))
    uniq = v.nunique() / max(1, len(v))
    shape = _shape(x)

    # 행 합 ≈ 1 (조성) — 가장 강한 신호 ( 신호 우선순위 1).
    # 조성은 전체 수치 컬럼이 아니라 **부분집합**이므로 이름 접두로 묶어서 본다 (C-12)
    row_sum_one = bool(siblings is not None and name in composition_set(siblings, name))

    if 0 <= mn and mx <= 1:
        if row_sum_one:
            add("proportion", 4, msg("ev_row_sum_one"))
        # min·max가 정확히 0·1 → min-max 정규화 흔적 (신호 2)
        if mn == 0.0 and mx == 1.0 and not is_int:
            add("normalized score", 3, msg("ev_minmax_exact"))
        if not is_int:
            add("probability", 2, msg("ev_range_01"))
            add("proportion", 1.5, msg("ev_range_01"))
            if shape in ("bimodal", "bimodal_ends"):
                add("probability", 1.5, msg("ev_bimodal_ends"))
        if is_int and v.nunique() <= 2:
            add("nominal code", 2.5, msg("ev_binary_int"))
            add("count", 1, msg("ev_binary_int_count"))
            conflicts.append(msg("conflict_binary_count"))

    if is_int and mn >= 0 and mx > 1:
        add("count", 3, msg("ev_nonneg_int"))
        if v.nunique() <= 10:
            add("ordinal code", 2, msg("ev_few_int_levels", n=v.nunique()))
            add("nominal code", 1.5, msg("ev_few_int_levels", n=v.nunique()))
            conflicts.append(msg("conflict_nominal_ordinal"))
    if 0 <= mn and mx <= 100 and mx > 1 and not is_int:
        add("percent", 2, msg("ev_range_0_100"))
    if mn < 0:
        add("continuous", 2, msg("ev_has_negative"))
        add("expression index", 1.5, msg("ev_negative_log"))
        if abs(float(x.mean())) < 0.3 and 0.7 < float(x.std()) < 1.4:
            add("z-score", 3, msg("ev_mean0_sd1"))
        conflicts.append(msg("conflict_negative_scale"))
    if mx > 1 and not is_int:
        add("continuous", 1.5, msg("ev_real_positive"))
        add("expression index", 1, msg("ev_gt1_reference"))
    if uniq > 0.9 and is_int:
        add("id", 1.5, msg("ev_unique_ratio", ratio=uniq))

    if not score:
        add("continuous", 1, msg("ev_fallback"))

    # 컬럼명은 낮은 가중치 보조 신호
    low = name.lower()
    for pat, t in ((r"\b(prob|p_|pred|score)\b|prob", "probability"),
                   (r"(frac|ratio|prop|pct_)", "proportion"),
                   (r"(count|_n$|^n_|num)", "count"),
                   (r"(log2?|ln_|_log)", "log-scale"),
                   (r"(id$|_id$|^id)", "id"),
                   (r"(zscore|_z$)", "z-score")):
        if re.search(pat, low):
            add(t, 0.5, msg("ev_name_hint", name=name))
    return _finish(name, score, ev, shape, conflicts)


def _finish(name: str, score: dict, ev: dict, shape: str,
            conflicts: list[str]) -> TypeInference:
    """점수를 순위로 바꾸고(점수는 버린다) 확정 필요 여부를 판단한다."""
    from statop.messages import msg

    ordered = sorted(score.items(), key=lambda kv: -kv[1])
    cands: list[Candidate] = []
    rank = 0
    prev: float | None = None
    for i, (t, sc) in enumerate(ordered, start=1):
        if prev is None or not np.isclose(sc, prev):
            rank = i          # 동점이면 공동 순위, 다음은 건너뛴 번호 (1,1,3)
        prev = sc
        cands.append(Candidate(type=t, rank=rank, evidence=ev[t], _score=sc))

    reason = None
    if conflicts:
        reason = msg("confirm_conflict")
    elif len(cands) >= 2:
        top = {c.type for c in cands if c.rank == 1}
        second = {c.type for c in cands if c.rank == cands[1].rank}
        if len(top) > 1:
            reason = msg("confirm_tie")
        else:
            for a in top:
                for b in second:
                    if frozenset({a, b}) in COSTLY_PAIRS:
                        reason = msg("confirm_costly", a=a, b=b)
                        break
    return TypeInference(column=name, candidates=cands, shape=shape,
                         conflicts=conflicts, needs_confirm=reason is not None,
                         confirm_reason=reason)


def infer_columns(df: pd.DataFrame, columns: list[str],
                  progress=None) -> list[TypeInference]:
    """가져온 컬럼들의 타입 추론.

    조성 감지는 **파일 전체의 수치 컬럼**을 후보로 본다 — 세트의 일부만 가져왔어도
    "조성의 일부로 보인다"를 알려줄 수 있어야 하기 때문 (M1-3의 CLR은 세트 전체가 필요).
    progress(0~1): 컬럼 하나가 진행 단위다 (조성 탐색 때문에 컬럼당 비용이 크다).
    """
    pool = df[[c for c in df.columns if df[c].dtype.kind in "if"]]
    out = []
    for idx, c in enumerate(columns):
        if progress:
            progress((idx + 1) / max(1, len(columns)))
        if c not in df.columns:
            continue
        t = infer(df[c], c, siblings=pool if c in pool.columns else None)
        # 세트에 속하는데 일부만 가져왔으면 알린다
        if c in pool.columns:
            members = composition_set(pool, c)
            if members and not members <= set(columns):
                from statop.messages import msg

                t.conflicts.append(msg("conflict_partial_composition",
                                       n=len(members), missing=len(members - set(columns))))
                t.needs_confirm = True
                t.confirm_reason = t.confirm_reason or msg("confirm_conflict")
        out.append(t)
    return out


# ── 값 자체에서 순서를 읽는다 (반복측정의 회차 정렬) ─────────
_CHUNKS = re.compile(r"(\d+)")


def order_key(value) -> tuple:  # noqa: ANN001
    """한 값의 정렬 키. T1 < T2 < T10, 25AIC032 < 26AIC088 처럼 읽는다.

    숫자로만 된 값은 숫자로 본다 — 글자 단위로 쪼개면 3.5 가 3.45 보다 작아진다.
    그 밖에는 숫자 덩어리와 글자 덩어리를 번갈아 비교한다: 앞자리 연도가 먼저,
    같은 연도면 뒷자리 생산번호가 다음이다.
    """
    s = str(value).strip()
    try:
        return ((0, float(s), ""),)
    except ValueError:
        pass
    parts = []
    for tok in _CHUNKS.split(s):
        if not tok:
            continue
        if tok.isdigit():
            parts.append((0, float(tok), ""))
        else:
            parts.append((1, 0.0, tok.casefold()))
    return tuple(parts) or ((1, 0.0, s.casefold()),)


def ordered_levels(series) -> list:  # noqa: ANN001
    """컬럼의 수준을 순서대로. 날짜면 날짜 순, 숫자면 숫자 순, 아니면 order_key 순.

    회차(T1·T2·lib_batch·채취일)의 순서를 틀리면 추세도 반복측정도 전부 틀린다.
    """
    vals = pd.Series(series).dropna().unique()
    num = pd.to_numeric(pd.Series(vals), errors="coerce")
    if not num.isna().any():
        return [v for _, v in sorted(zip(num, vals), key=lambda t: t[0])]
    dt = pd.to_datetime(pd.Series(vals), errors="coerce", format="mixed")
    if not dt.isna().any():
        return [v for _, v in sorted(zip(dt, vals), key=lambda t: t[0])]
    return sorted(vals, key=order_key)
