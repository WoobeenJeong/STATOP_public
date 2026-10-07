"""M0 축약 인입 2단계: 본문 전체를 읽지 않고 앞/중/뒤 구간에서 행을 뽑는다.

정렬된 파일(예: site 순 정렬)에서 앞N행만 읽으면 한 그룹만 보게 되므로,
파일을 k개 구간으로 나눠 각 구간에서 같은 수의 행을 읽는다. 무작위 없음 — 결정론적.
"""

import io
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

_DELIMS = {".csv": ",", ".tsv": "\t"}

# 진행률 콜백: 0.0~1.0 한 개 인자. 없으면 아무 비용도 들지 않는다
Progress = Callable[[float], None] | None


def sample_rows(path: str | Path, n: int = 10_000, k_blocks: int = 3,
                progress: Progress = None) -> pd.DataFrame:
    """앞/중/뒤 k개 구간으로 나눠 총 n행을 읽는다. csv/tsv/parquet 동일 API.

    csv/tsv: 바이트 오프셋 seek 후 다음 줄 경계부터. parquet: 행 위치를 row group에
    매핑해 필요한 group만 읽는다. progress는 읽은 분량을 0~1로 알린다.
    """
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return _sample_parquet(p, n, k_blocks, progress)
    delim = _DELIMS[p.suffix.lower()]
    size = p.stat().st_size
    per_block = n // k_blocks

    with open(p, "rb") as f:
        header = f.readline()
        body_start = f.tell()
        chunks: list[bytes] = []
        covered = body_start          # 이미 읽은 바이트의 끝 — 여기부터 겹침을 막는다
        for b in range(k_blocks):
            start = max(body_start + (size - body_start) * b // k_blocks, covered)
            f.seek(start)
            if start > covered:
                f.readline()          # 줄 중간으로 건너뛰었으니 잘린 줄을 버린다
            # start == covered 면 이미 줄 경계다 — 여기서 버리면 멀쩡한 행이 사라진다
            lines = []
            for i in range(per_block):
                line = f.readline()
                if not line:
                    break
                lines.append(line)
                if progress and i % 500 == 0:      # 줄마다 부르면 콜백이 더 비싸진다
                    progress((b * per_block + i) / (k_blocks * per_block))
            covered = f.tell()
            chunks.append(b"".join(lines))
            if progress:
                progress((b + 1) / k_blocks)

    raw = header + b"".join(chunks)
    # 내용으로 중복을 지우면 안 된다 — 값이 같은 서로 다른 샘플이 통째로 사라진다.
    # 겹침은 위에서 바이트 범위로 막았으므로 여기서 지울 것이 없다.
    return pd.read_csv(io.BytesIO(raw), sep=delim)


def _sample_parquet(p: Path, n: int, k_blocks: int,
                    progress: Progress = None) -> pd.DataFrame:
    """전체 행 위치 기준으로 앞/중/뒤 구간을 정하고, 겹치는 row group을 한 번씩만 읽는다."""
    pf = pq.ParquetFile(p)
    total = pf.metadata.num_rows
    per_block = n // k_blocks
    # 원하는 전역 행 구간 [start, stop) — 다음 구간 시작 전에서 잘라 겹침을 원천 차단.
    # 행 수가 적으면 구간이 비는데(total < k_blocks 등), 빈 구간은 버린다.
    wanted = []
    for b in range(k_blocks):
        start = total * b // k_blocks
        next_start = total * (b + 1) // k_blocks if b + 1 < k_blocks else total
        stop = min(start + per_block, next_start, total)
        if stop > start:
            wanted.append((start, stop))
    if not wanted:  # 요청 n이 0이거나 파일이 비었을 때
        return pf.read_row_groups([]).to_pandas() if pf.metadata.num_row_groups else pd.DataFrame()

    # row group 경계 (누적 행수)
    bounds = [0]
    for g in range(pf.metadata.num_row_groups):
        bounds.append(bounds[-1] + pf.metadata.row_group(g).num_rows)

    # 구간별 필요 group 목록 → 전체 합집합을 한 번만 읽고 캐시
    needed: dict[int, list[int]] = {}
    for i, (start, stop) in enumerate(wanted):
        needed[i] = [g for g in range(pf.metadata.num_row_groups)
                     if bounds[g] < stop and bounds[g + 1] > start]
    unique_groups = sorted({g for gs in needed.values() for g in gs})
    cache = {}
    for gi, g in enumerate(unique_groups):         # group 하나가 진행 단위다
        cache[g] = pf.read_row_groups([g]).to_pandas()
        if progress:
            progress((gi + 1) / len(unique_groups))

    parts = []
    for i, (start, stop) in enumerate(wanted):
        tbl = pd.concat([cache[g] for g in needed[i]]) if len(needed[i]) > 1 else cache[needed[i][0]]
        offset = bounds[needed[i][0]]
        parts.append(tbl.iloc[start - offset : stop - offset])
    return pd.concat(parts, ignore_index=True)  # 구간이 겹치지 않으므로 중복 제거 불필요
