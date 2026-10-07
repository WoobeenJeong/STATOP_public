"""M0-3 분포 미리보기 — 가져온 컬럼의 분포를 요약한다 (클릭할 때만 계산, 요구사항).

숫자는 코드가 만든다. 그림은 껍데기가 이 숫자로 그린다 — 웹은 막대, 셸·CLI는 블록 문자.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Distribution:
    column: str
    kind: str  # numeric | categorical
    n: int  # 관측 수 (결측 제외)
    n_missing: int
    # 숫자형
    bins: list[float] | None = None  # 히스토그램 도수
    edges: list[float] | None = None
    quartiles: list[float] | None = None  # 박스플롯용 [min, q1, median, q3, max]
    mean: float | None = None
    sd: float | None = None
    skewness: float | None = None
    iqr: float | None = None               # Q3 − Q1
    # 울타리(fence) — Q1−1.5×IQR · Q3+1.5×IQR. 보여 주지 않으면 "이 값이 바깥인가"를
    # 사용자가 손으로 계산해야 한다
    fence_lo: float | None = None
    fence_hi: float | None = None
    outlier_rate_iqr: float | None = None  # IQR 1.5 기준
    outlier_rate_mad: float | None = None  # MAD 3 기준
    zeros_rate: float | None = None  # 0 비율 (영과잉 신호, C-10)
    negative: bool | None = None
    # 범주형
    levels: list[dict] | None = None  # [{value, n, ratio}]
    n_levels: int | None = None
    truncated: bool = False  # 수준이 너무 많아 상위만 보였는지

    def as_dict(self) -> dict:
        return asdict(self)


MAX_LEVELS = 12  # 범주형에서 화면에 보일 수준 수 — 그 이상은 "기타"로 묶는다


def describe_series(s: pd.Series, name: str, bins: int = 20) -> Distribution:
    """한 컬럼의 분포 요약. 숫자형/범주형을 나눠 처리한다."""
    n_missing = int(s.isna().sum())
    v = s.dropna()

    if pd.api.types.is_numeric_dtype(v) and not pd.api.types.is_bool_dtype(v):
        x = v.to_numpy(dtype="float64")
        if x.size == 0:
            return Distribution(column=name, kind="numeric", n=0, n_missing=n_missing)
        counts, edges = np.histogram(x, bins=min(bins, max(5, int(np.sqrt(x.size)))))
        q1, med, q3 = np.percentile(x, [25, 50, 75])
        iqr = q3 - q1
        # IQR 1.5 / MAD 3 — 두 기준을 함께 준다 (C-03). 분포에 따라 답이 다르므로 사용자가 본다
        iqr_out = float(np.mean((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr))) if iqr > 0 else 0.0
        mad = float(np.median(np.abs(x - med)))
        mad_out = float(np.mean(np.abs(x - med) > 3 * mad)) if mad > 0 else 0.0
        sd = float(np.std(x, ddof=1)) if x.size > 1 else 0.0
        skew = float(pd.Series(x).skew()) if x.size > 2 else 0.0
        return Distribution(
            column=name, kind="numeric", n=int(x.size), n_missing=n_missing,
            bins=[int(c) for c in counts], edges=[float(e) for e in edges],
            quartiles=[float(x.min()), float(q1), float(med), float(q3), float(x.max())],
            iqr=float(iqr), fence_lo=float(q1 - 1.5 * iqr),
            fence_hi=float(q3 + 1.5 * iqr),
            mean=float(x.mean()), sd=sd, skewness=skew,
            outlier_rate_iqr=iqr_out, outlier_rate_mad=mad_out,
            zeros_rate=float(np.mean(x == 0)), negative=bool((x < 0).any()),
        )

    vc = v.astype(str).value_counts()
    total = int(vc.sum())
    head = vc.head(MAX_LEVELS)
    levels = [{"value": str(k), "n": int(c), "ratio": c / total} for k, c in head.items()]
    if len(vc) > MAX_LEVELS:
        from statop.messages import msg

        rest = int(vc.iloc[MAX_LEVELS:].sum())
        levels.append({"value": msg("dist_levels_rest", n=len(vc) - MAX_LEVELS),
                       "n": rest, "ratio": rest / total})
    return Distribution(column=name, kind="categorical", n=total, n_missing=n_missing,
                        levels=levels, n_levels=int(len(vc)),
                        truncated=len(vc) > MAX_LEVELS)


def distributions_of(df, columns: list[str]) -> list[dict]:
    """메모리 안 DataFrame의 분포 — 파생 컬럼처럼 **파일에 없는 컬럼**도 여기로 온다."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        from statop.messages import msg

        raise ValueError(msg("select_err_missing", cols=", ".join(missing)))
    return [describe_series(df[c], c).as_dict() for c in columns]


def distributions(path: str | Path, columns: list[str], sample_n: int = 10_000) -> list[dict]:
    """선택한 컬럼들의 분포를 계산한다 — 가져온 컬럼에만 쓴다 (M0-4)."""
    from statop.io.sample import sample_rows

    return distributions_of(sample_rows(path, n=sample_n), columns)
