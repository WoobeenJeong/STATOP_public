"""M0-6b 결측 처리 — 현황·패턴 표시 / NA 제거 / 경량 대치 (registry-errors 1.1).

원칙:
- **실행하는 기능은 두 가지뿐** — NA 제거와 허용 목록(1.1a) 안의 경량 대치.
- 그 밖의 방법(MLP·앙상블·딥러닝 대치, Rubin 풀링 등)은 **안내만** 하고 실행하지 않는다(1.1b).
- 제거·대치는 항상 전/후 n을 함께 남기고, 대치된 셀 수·방법·비율이 출력에 남는다.
- **0 ≠ NaN.** 0으로 채워진 결측이 의심되면 알린다.
"""

from dataclasses import dataclass, field

# 1.1a 허용 목록 — 여기 없는 방법은 실행하지 않는다
ALLOWED_METHODS = ("zero", "mean", "median", "mode", "group_mean", "group_median",
                   "knn", "mice")
HIGH_MISSING = 0.30   # 이 비율을 넘으면 컬럼 제거를 제안(노랑)
MEAN_LIMIT = 0.10     # 평균 대치는 결측 <10%에서만 권장 (분산 축소)
KNN_MAX_ROWS, KNN_MAX_COLS = 50_000, 200
MICE_MAX_COLS, MICE_MAX_ITER = 100, 10


@dataclass
class ColumnMissing:
    column: str
    n_missing: int
    ratio: float
    high: bool                  # 임계 초과 → 제거 제안
    zero_ratio: float | None    # 0 비율 — 0으로 채워진 결측 의심 신호
    suspect_zero_filled: bool


@dataclass
class MissingReport:
    n_rows: int
    columns: list[ColumnMissing]
    patterns: list[dict] = field(default_factory=list)  # 함께 비는 컬럼 조합
    complete_rows: int = 0


def report(df, top_patterns: int = 5) -> MissingReport:
    """결측 현황 + 패턴(어떤 컬럼 조합이 함께 비는지)."""
    n = len(df)
    cols = []
    for c in df.columns:
        miss = int(df[c].isna().sum())
        ratio = miss / n if n else 0.0
        zero_ratio = None
        suspect = False
        if df[c].dtype.kind in "if":
            nonnull = df[c].dropna()
            zero_ratio = float((nonnull == 0).mean()) if len(nonnull) else 0.0
            # 0이 과반인데 결측도 있으면 "0으로 채워진 결측" 의심 (1.1 마지막 항목)
            suspect = zero_ratio > 0.5 and 0 < ratio < 0.5
        cols.append(ColumnMissing(column=c, n_missing=miss, ratio=ratio,
                                  high=ratio > HIGH_MISSING, zero_ratio=zero_ratio,
                                  suspect_zero_filled=suspect))

    mask = df.isna()
    complete = int((~mask.any(axis=1)).sum())
    patterns = []
    if mask.any().any():
        combos = mask.apply(lambda r: tuple(df.columns[r]), axis=1)
        vc = combos[combos.map(len) > 0].value_counts().head(top_patterns)
        patterns = [{"columns": list(k), "n": int(v), "ratio": v / n} for k, v in vc.items()]
    return MissingReport(n_rows=n, columns=cols, patterns=patterns, complete_rows=complete)


def drop_na(df, columns: list[str] | None = None, how: str = "row"):
    """NA 제거 — 지정 컬럼 기준 행 제거(row) 또는 컬럼 제거(column)."""
    from statop.messages import msg

    if how == "column":
        targets = columns or [c for c in df.columns if df[c].isna().any()]
        return df.drop(columns=[c for c in targets if c in df.columns])
    if how != "row":
        raise ValueError(msg("missing_bad_how", how=how))
    return df.dropna(subset=columns) if columns else df.dropna()


def check_method(method: str, df, columns: list[str],
                 group_by: str | None = None) -> list[str]:
    """이 방법을 이 데이터에 써도 되는지 — 경고 목록을 돌려준다 (빈 목록이면 문제 없음).

    허용 목록 밖이면 아예 예외. 조건 위반(컬럼 수·행 수 초과)도 예외.
    """
    from statop.messages import msg

    if method not in ALLOWED_METHODS:
        raise ValueError(msg("missing_method_not_allowed", method=method,
                             allowed=", ".join(ALLOWED_METHODS)))
    warns: list[str] = []
    n = len(df)
    if method in ("group_mean", "group_median") and not group_by:
        raise ValueError(msg("missing_group_required"))
    if method == "knn":
        if n > KNN_MAX_ROWS or len(df.columns) > KNN_MAX_COLS:
            raise ValueError(msg("missing_knn_limit", rows=KNN_MAX_ROWS, cols=KNN_MAX_COLS))
    if method == "mice" and len(df.columns) > MICE_MAX_COLS:
        raise ValueError(msg("missing_mice_limit", cols=MICE_MAX_COLS))

    for c in columns:
        ratio = df[c].isna().mean() if c in df.columns else 0.0
        if method == "mean" and ratio > MEAN_LIMIT:
            warns.append(msg("missing_warn_mean", col=c, ratio=ratio))
        if method == "zero" and df[c].dtype.kind == "f" and df[c].dropna().between(0, 1).all():
            warns.append(msg("missing_warn_zero_fraction", col=c))
    return warns


def impute(df, method: str, columns: list[str], group_by: str | None = None,
           seed: int = 0) -> tuple:
    """경량 대치 실행 → (결과 DataFrame, 정보). 대치된 셀 수를 항상 함께 돌려준다."""
    import numpy as np
    import pandas as pd

    from statop.messages import msg

    warns = check_method(method, df, columns, group_by)
    out = df.copy()
    before = out[columns].isna().sum().sum()
    info = {"method": method, "columns": columns, "warnings": warns, "seed": None,
            "params": {}}

    if method == "zero":
        out[columns] = out[columns].fillna(0)
    elif method in ("mean", "median"):
        for c in columns:
            out[c] = out[c].fillna(out[c].mean() if method == "mean" else out[c].median())
    elif method == "mode":
        for c in columns:
            m = out[c].mode()
            if len(m):
                out[c] = out[c].fillna(m.iloc[0])
    elif method in ("group_mean", "group_median"):
        agg = "mean" if method == "group_mean" else "median"
        for c in columns:
            filled = out.groupby(group_by)[c].transform(agg)
            out[c] = out[c].fillna(filled)
        info["params"]["group_by"] = group_by
    elif method == "knn":
        from sklearn.impute import KNNImputer

        k = min(5, max(1, len(out) - 1))
        imp = KNNImputer(n_neighbors=k)
        out[columns] = imp.fit_transform(out[columns])
        info["params"]["k"] = k
    elif method == "mice":
        from sklearn.experimental import enable_iterative_imputer  # noqa: F401
        from sklearn.impute import IterativeImputer
        from sklearn.linear_model import BayesianRidge

        # 추정기는 BayesianRidge 고정 (1.1a 원칙 — 무거운 추정기 금지)
        imp = IterativeImputer(estimator=BayesianRidge(), max_iter=MICE_MAX_ITER,
                               random_state=seed)
        out[columns] = imp.fit_transform(out[columns])
        info["seed"] = seed
        info["params"] = {"max_iter": MICE_MAX_ITER, "estimator": "BayesianRidge"}

    after = out[columns].isna().sum().sum()
    info["n_filled"] = int(before - after)
    info["n_remaining"] = int(after)
    info["ratio_filled"] = float((before - after) / (len(df) * len(columns))) if columns else 0.0
    if info["n_remaining"]:
        info["warnings"] = [*warns, msg("missing_not_all_filled", n=info["n_remaining"])]
    return out, info
