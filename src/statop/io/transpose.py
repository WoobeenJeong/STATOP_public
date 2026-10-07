"""전치(Transpose) — 행/열 뒤집기 . 원본 불변, 세션 뷰 차원의 조작."""

from dataclasses import dataclass
from pathlib import Path

from statop.io.meta import estimate_rows, open_meta


def transpose_table(path: str | Path):
    """파일을 전부 읽어 전치한 DataFrame을 반환한다. 원본 파일은 읽기만 한다.

    첫 컬럼 값이 새 컬럼명이 되고(중복이면 에러), 원래 컬럼명들은 첫 컬럼("column")이 된다.
    """
    import pandas as pd

    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(p)
    elif suffix in (".csv", ".tsv"):
        df = pd.read_csv(p, sep="," if suffix == ".csv" else "\t")
    else:
        from statop.messages import msg

        raise ValueError(msg("unsupported_format", suffix=suffix, path=p))

    first = df.columns[0]
    ids = df[first].astype(str)
    dup = ids.duplicated()
    if dup.any():
        from statop.messages import msg

        raise ValueError(msg("transpose_dup_ids", col=first, n=int(dup.sum())))

    out = df.drop(columns=[first]).T
    out.columns = ids.tolist()
    out.insert(0, "column", df.columns[1:])
    return out.reset_index(drop=True)


@dataclass
class TransposeCost:
    n_rows: int  # 현재 행수 (csv는 추정)
    n_cols: int
    estimated: bool
    mem_mb: float  # 예상 메모리 (전체 로드 + 전치 사본)
    warn: bool  # 메모리 경고 (기본 4GB 초과)


def estimate_cost(path: str | Path, warn_mb: float = 4096) -> TransposeCost:
    """전치는 전체 로드가 필요하므로 실행 전에 비용을 보인다 .

    메모리 ≈ 셀수 × 8byte × 8 — 실측 기준. pandas 전치가 혼합 dtype에서 object
    사본을 만들어 이론값(×2)의 약 4배가 든다. 문자열 컬럼이 많으면 이보다 커질 수 있다.
    """
    meta = open_meta(path)
    n_cols = len(meta.columns)
    if meta.n_rows is not None:
        n_rows, estimated = meta.n_rows, False
    else:
        n_rows, estimated = estimate_rows(path), True
    mem_mb = n_rows * n_cols * 8 * 8 / 1e6
    return TransposeCost(n_rows, n_cols, estimated, mem_mb, mem_mb > warn_mb)
