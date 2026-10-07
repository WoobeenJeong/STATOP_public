"""B5 모델특유 검사  — MB-C28 · C29 · C30 · C31 (T0 만).

같은 자료라도 **어떤 모델을 쓰느냐에 따라 다른 것이 터진다.** 여기 넷은 CPU 에서 도는
고전 모델(T0)에서 실제로 나는 것들이다:

- MB-C28 완전분리 — 한 변수가 라벨을 완벽히 가른다. **계열에 따라 결과가 다르다** —
  정규화가 없으면 계수가 발산하고, 벌점이 있으면 억제되지만 기여도를 따로 재야 한다
- MB-C29 다중공선성 — 변수끼리 겹치면 효과가 분리되지 않는다. C-07(VIF)을 그대로 부른다
- MB-C31 특성중요도 — 상관이 높을 때 **impurity 와 permutation 은 어긋나는 방향이 반대다**
  (나뉘어 실리는 것과 둘 다 낮게 나오는 것). 방식을 갈라 말한다 (Judg)

**학습 루프 안에서 일어나는 일은 여기서 보지 않는다** — 조기중단(옛 MB-C30)이나
학습곡선(C32·C33)은 학습하는 쪽에서 판단할 일이다. `debris/` 참조 .

**감사 전용이다.** 학습을 돌리지 않고 세트 파일과 설정만 본다.
"""

import numpy as np
import pandas as pd

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, skip
from statop.modeling.prep import _dev_frame, _feature_cols, family_of

# 계수를 적합하는 계열 — 완전분리·다중공선성은 여기서만 뜻이 있다
COEFFICIENT_FAMILIES = ("linear", "penalized")
# VIF 가 이보다 크면 지목한다. C-07 이 쓰는 값과 같게 둔다 (규칙 하나, 임계 하나)
VIF_LIMIT = 5.0
# 중요도가 갈라 실릴 만한 상관. 이보다 높은 쌍이 있으면 중요도를 그대로 읽기 어렵다
IMPORTANCE_CORR = 0.7
# 중요도 방식 — **상관이 높을 때 어긋나는 방향이 서로 반대다.**
# impurity: 먼저 뽑힌 쪽에 기여가 몰려 **나뉘어 실린다**
# permutation: 한쪽을 섞어도 다른 쪽에 정보가 남아 **둘 다 낮게 나온다**
IMPURITY_WORDS = ("gini", "gain", "impurity", "mdi", "split", "weight", "cover")
PERMUTATION_WORDS = ("permutation", "perm", "mda", "shuffle")


def importance_kind(how: str) -> str:
    """impurity | permutation | unknown — 모르는 이름은 지어내지 않는다."""
    low = (how or "").lower()
    if any(w in low for w in PERMUTATION_WORDS):
        return "permutation"
    if any(w in low for w in IMPURITY_WORDS):
        return "impurity"
    return "unknown"


def _binary_label(df: pd.DataFrame, spec):  # noqa: ANN001
    """이진 라벨을 0/1 로. 이진이 아니면 None."""
    if not spec.label_column or spec.label_column not in df.columns:
        return None
    y = df[spec.label_column].dropna()
    levels = sorted(str(v) for v in y.unique())
    if len(levels) != 2:
        return None
    pos = spec.positive_class if spec.positive_class in levels else levels[-1]
    return (df[spec.label_column].astype(str) == pos).to_numpy()


# ── MB-C28 완전분리 (E-801-2) ───────────────────────────────
def separation(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """한 변수가 라벨을 완벽히 가르는가 — 그러면 로지스틱 계수가 무한으로 간다.

    적합하지 않고 **값의 범위만 본다**: 두 군의 값 구간이 겹치지 않으면 완전분리,
    한쪽 끝만 겹치면 준완전분리다. 적합해서 계수가 발산하는 것을 보는 것보다
    빠르고, 어느 변수 때문인지 바로 지목할 수 있다.
    """
    fam = family_of(spec.model_family)
    if fam is None or fam["family"] not in COEFFICIENT_FAMILIES:
        return skip("MB-C28", msg("mb_c28_not_applicable",
                                  family=spec.model_family or "-"))
    df = _dev_frame(spec, sample_n)
    if not len(df):
        return skip("MB-C28", msg("mb_c08_no_dev"))
    y = _binary_label(df, spec)
    if y is None:
        return skip("MB-C28", msg("mb_c28_binary_only"))

    hits = []
    for c in _feature_cols(df, spec):
        v = pd.to_numeric(df[c], errors="coerce")
        a, b = v[y].dropna(), v[~y].dropna()
        if len(a) < 2 or len(b) < 2:
            continue
        # 겹치는 구간의 폭 — 0 이하면 완전히 갈린다
        overlap = min(a.max(), b.max()) - max(a.min(), b.min())
        span = max(v.max() - v.min(), 1e-12)
        if overlap <= 0:
            hits.append({"column": c, "kind": "complete", "overlap": 0.0})
        elif overlap / span < 0.02:
            # 거의 갈린다 — 준완전분리. 계수가 아주 커지고 표준오차가 폭발한다
            hits.append({"column": c, "kind": "quasi",
                         "overlap": float(overlap / span)})
    numbers = {"columns": hits, "family": fam["family"]}
    if not hits:
        return LeakFinding(id="MB-C28", grade=grade_of("MB-C28"), verdict="pass",
                           summary=msg("mb_c28_pass"), numbers=numbers)
    detail = [msg("mb_c28_row", col=h["column"],
                  kind=msg("mb_c28_complete" if h["kind"] == "complete"
                           else "mb_c28_quasi"), overlap=h["overlap"])
              for h in hits]
    # 벌점이 있으면 계수가 발산하지 않는다 — **계열에 따라 다른 문장을 쓴다.**
    # 한 문장으로 뭉뚱그리면 벌점 계열에서 틀린 말이 된다
    penalized = fam["family"] == "penalized"
    return LeakFinding(
        id="MB-C28", grade=grade_of("MB-C28"), verdict="fail",
        summary=msg("mb_c28_found", n=len(hits),
                    cols=", ".join(h["column"] for h in hits)),
        detail=[*detail, msg("mb_c28_why_penalized" if penalized
                             else "mb_c28_why_unpenalized")],
        numbers={**numbers, "penalized": penalized},
        action=msg("mb_c28_action_penalized" if penalized
                   else "mb_c28_action_unpenalized"))


# ── MB-C29 다중공선성 (C-07 재사용) ─────────────────────────
def collinearity(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """변수끼리 겹치는가 — **판정은 C-07 을 그대로 부른다** (규칙 하나, 임계 하나)."""
    fam = family_of(spec.model_family)
    if fam is None or fam["family"] not in COEFFICIENT_FAMILIES:
        return skip("MB-C29", msg("mb_c29_not_applicable",
                                  family=spec.model_family or "-"))
    df = _dev_frame(spec, sample_n)
    cols = _feature_cols(df, spec) if len(df) else []
    if len(cols) < 2:
        return skip("MB-C29", msg("mb_c11_need_features"))

    from statop.analyze.checks import collinearity as c07

    r = c07(df, cols, VIF_LIMIT)
    if r.verdict == "skipped":
        return skip("MB-C29", r.summary)
    vifs = sorted(r.per_group, key=lambda x: -x["vif"])
    numbers = {"vif": {x["column"]: x["vif"] for x in vifs}, "limit": VIF_LIMIT}
    detail = [msg("mb_c29_row", col=x["column"], vif=x["vif"]) for x in vifs[:5]]
    if r.verdict == "ok":
        return LeakFinding(id="MB-C29", grade=grade_of("MB-C29"), verdict="pass",
                           summary=msg("mb_c29_pass", vmax=vifs[0]["vif"],
                                       limit=VIF_LIMIT),
                           detail=detail, numbers=numbers)
    bad = [x["column"] for x in vifs if x["vif"] >= VIF_LIMIT]
    return LeakFinding(
        id="MB-C29", grade=grade_of("MB-C29"), verdict="fail",
        summary=msg("mb_c29_found", cols=", ".join(bad), limit=VIF_LIMIT),
        detail=[*detail, msg("mb_c29_why"),
                msg("mb_c29_rule_of_thumb", limit=VIF_LIMIT)],
        numbers=numbers, action=msg("mb_c29_action"))


# ── MB-C31 특성중요도 과신 (Judg) ───────────────────────────
def importance_stability(spec, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """중요도를 보고했는가 — 그렇다면 상관이 높은 변수쌍이 있는지 함께 본다.

    상관이 높으면 같은 정보가 여러 변수에 나뉘어 실려, **중요도가 갈라진다.**
    어느 변수가 중요한지가 아니라 **어느 쌍이 서로를 가리는지**를 지목한다 .
    """
    if not spec.importance:
        return skip("MB-C31", msg("mb_c31_not_reported"))
    df = _dev_frame(spec, sample_n)
    cols = _feature_cols(df, spec) if len(df) else []
    if len(cols) < 2:
        return skip("MB-C31", msg("mb_c11_need_features"))

    corr = df[cols].corr().abs()
    pairs = [{"a": a, "b": b, "r": float(corr.loc[a, b])}
             for i, a in enumerate(cols) for b in cols[i + 1:]
             if np.isfinite(corr.loc[a, b]) and corr.loc[a, b] >= IMPORTANCE_CORR]
    pairs.sort(key=lambda p: -p["r"])
    kind = importance_kind(spec.importance)
    numbers = {"importance": spec.importance, "kind": kind, "pairs": pairs,
               "limit": IMPORTANCE_CORR}
    if not pairs:
        return LeakFinding(id="MB-C31", grade=grade_of("MB-C31"), verdict="pass",
                           summary=msg("mb_c31_pass", how=spec.importance,
                                       limit=IMPORTANCE_CORR), numbers=numbers)
    return LeakFinding(
        id="MB-C31", grade=grade_of("MB-C31"), verdict="fail",
        summary=msg("mb_c31_correlated", how=spec.importance, n=len(pairs)),
        detail=[msg("mb_c31_row", a=p["a"], b=p["b"], r=p["r"])
                for p in pairs[:5]] + [msg(f"mb_c31_why_{kind}")],
        numbers=numbers, action=msg(f"mb_c31_action_{kind}"))


def run_all(spec, sample_n: int = 50_000) -> list[LeakFinding]:  # noqa: ANN001
    """모델특유 검사 전부 — 하나가 실패해도 나머지는 돈다."""
    out = []
    for fn in (lambda: separation(spec, sample_n),
               lambda: collinearity(spec, sample_n),
               lambda: importance_stability(spec, sample_n)):
        try:
            out.append(fn())
        except (ValueError, OSError, KeyError) as e:
            out.append(skip("MB-C28", str(e)))
    return out
