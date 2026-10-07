"""M0-1 축약 인입 1단계: 데이터를 읽지 않고 메타(컬럼 목록)만 연다."""

import csv
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

_DELIMS = {".csv": ",", ".tsv": "\t"}


@dataclass
class TableMeta:
    path: str
    fmt: str  # csv | tsv | parquet
    columns: list[str]
    dtypes: dict[str, str] | None  # parquet=스키마 기반. csv/tsv=None (샘플에서 추정, )
    n_rows: int | None  # parquet=정확(메타). csv/tsv=None (추정은 )


def open_meta(path: str | Path) -> TableMeta:
    """컬럼명·저장 타입·행수를 데이터 본문 없이 반환한다.

    parquet은 푸터 메타데이터만, csv/tsv는 헤더 한 줄만 읽는다.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".parquet":
        pf = pq.ParquetFile(p)
        schema = pf.schema_arrow
        return TableMeta(
            path=str(p),
            fmt="parquet",
            columns=list(schema.names),
            dtypes={name: str(schema.field(name).type) for name in schema.names},
            n_rows=pf.metadata.num_rows,
        )

    if suffix in _DELIMS:
        with open(p, newline="") as f:
            header = next(csv.reader(f, delimiter=_DELIMS[suffix]))
        return TableMeta(
            path=str(p),
            fmt=suffix[1:],
            columns=header,
            dtypes=None,
            n_rows=None,
        )

    raise ValueError(f"unsupported format: {suffix} ({p})")


def estimate_rows(path: str | Path, sample_lines: int = 200) -> int:
    """csv/tsv 총 행수를 추정한다 (헤더 제외).

    파일 크기 ÷ 샘플 줄 평균 바이트. 본문을 다 읽지 않으므로 결과는 추정치다.
    """
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as f:
        header_len = len(f.readline())
        lens = [len(line) for line in (f.readline() for _ in range(sample_lines)) if line]
    if not lens:
        return 0
    return round((size - header_len) / (sum(lens) / len(lens)))
