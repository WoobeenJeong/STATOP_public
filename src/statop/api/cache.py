"""프로파일 캐시 — 페이지를 넘길 때마다 파일을 다시 읽지 않기 위한 층.

키는 (경로, 수정시각, 크기, 샘플 크기, 전치 여부). 파일이 바뀌면 키가 달라져 **자동으로
무효화**된다 — 낡은 프로파일로 판정하는 사고를 막는다.
정렬·페이지 자르기는 캐시된 결과 위에서 하므로 전체 기준 정렬이 유지된다.
"""

from collections import OrderedDict
from pathlib import Path

MAX_ENTRIES = 8  # 세션 몇 개 분량. 항목당 수 MB (2,000컬럼 기준 ~0.5MB)

_cache: "OrderedDict[tuple, dict]" = OrderedDict()


def cache_key(path: str | Path, sample_n: int, transposed: bool) -> tuple:
    st = Path(path).stat()
    return (str(Path(path).resolve()), st.st_mtime_ns, st.st_size, sample_n, transposed)


def get(key: tuple) -> dict | None:
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)  # 최근 사용을 뒤로 — 오래된 것부터 버린다
    return hit


def put(key: tuple, value: dict) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def clear() -> None:
    _cache.clear()


def size() -> int:
    return len(_cache)
