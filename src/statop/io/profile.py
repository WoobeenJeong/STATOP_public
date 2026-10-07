"""M0-2 컬럼 목록의 재료: 샘플에서 컬럼별 결측률·고유값수를 계산한다."""

from pathlib import Path

import pandas as pd

from statop.io.meta import open_meta
from statop.io.sample import sample_rows


def profile_frame(df: pd.DataFrame, estimated: bool = False) -> pd.DataFrame:
    """메모리 안 DataFrame(예: 전치 뷰)에서 같은 형태의 컬럼 프로파일을 만든다."""
    return pd.DataFrame(
        {
            "column": df.columns,
            "dtype": [str(t) for t in df.dtypes],
            "missing_rate": df.isna().mean().to_numpy(),
            "n_unique": df.nunique(dropna=True).to_numpy(),
            "estimated": estimated,
            "sample_rows": len(df),
        }
    )


def profile_columns(path: str | Path, sample_n: int = 10_000,
                    progress=None) -> pd.DataFrame:
    """컬럼별 (저장 타입, 결측률, 고유값수) 표를 반환한다.

    값은 앞/중/뒤 샘플 기준이며, 샘플이 전체를 덮지 못하면 estimated=True.
    데이터 셀 자체는 반환하지 않는다 — 통계만.

    progress(0~1): 읽기가 앞 60%, 컬럼별 통계가 뒤 40%를 차지한다 —
    컬럼이 수천 개면 통계 쪽이 오래 걸리므로 거기도 진행이 보여야 한다.
    """
    meta = open_meta(path)
    df = sample_rows(path, n=sample_n,
                     progress=(lambda f: progress(f * 0.6)) if progress else None)

    if meta.dtypes is not None:  # parquet: 스키마가 진실
        dtypes = [meta.dtypes[c] for c in df.columns]
    else:  # csv/tsv: 샘플에서 추정
        dtypes = [str(t) for t in df.dtypes]

    if progress:
        # 컬럼 단위로 계산하며 진행을 알린다 (전체 벡터화와 총비용은 같다)
        miss, uniq = [], []
        n_cols = max(1, len(df.columns))
        for i, c in enumerate(df.columns):
            miss.append(float(df[c].isna().mean()))
            uniq.append(int(df[c].nunique(dropna=True)))
            if i % 20 == 0 or i == n_cols - 1:
                progress(0.6 + 0.4 * (i + 1) / n_cols)
    else:
        miss = df.isna().mean().to_numpy()
        uniq = df.nunique(dropna=True).to_numpy()

    covered = meta.n_rows is not None and len(df) >= meta.n_rows
    return pd.DataFrame(
        {
            "column": df.columns,
            "dtype": dtypes,
            "missing_rate": miss,
            "n_unique": uniq,
            "estimated": not covered,
            "sample_rows": len(df),
        }
    )
