"""세션 격리  — 무거운 연산을 별도 프로세스 풀에서 실행한다.

목적은 상태 격리가 아니라 **성능 격리**다. 세션 상태는 파일이 진실이라 이미 섞이지 않지만,
한 사용자의 대용량 연산(10GB 전치 등)이 이벤트 루프를 점유하면 다른 사용자의 가벼운 요청까지
멈춘다. 그래서 무거운 작업은 풀로 보내고, **세션당 동시 1개**로 제한해 독점을 막는다.
"""

import asyncio
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

_pool: ProcessPoolExecutor | None = None
_locks: dict[str, asyncio.Lock] = {}


def pool_size() -> int:
    return int(os.environ.get("STATOP_WORKERS", "4"))


def die_with_parent() -> None:
    """부모가 죽으면 커널이 이 프로세스도 죽이게 한다 (Linux PR_SET_PDEATHSIG).

    이게 없으면 서버가 갑자기 끝났을 때 워커가 **고아로 남아 영원히 산다.** 워커
    하나가 pandas·scipy를 들고 있어 수백 MB다 — 실측으로 6일 만에 326개·106GB가
    쌓여 있었고, 포트까지 물고 있어 다음 실행이 막혔다. 종료 훅만으로는 못 막는다:
    SIGKILL 이나 비정상 종료에서는 훅이 아예 안 돈다.
    """
    import signal
    import sys

    if not sys.platform.startswith("linux"):
        return
    import ctypes

    PR_SET_PDEATHSIG = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM,
                                                   0, 0, 0)


def get_pool() -> ProcessPoolExecutor:
    """프로세스 풀. **spawn**으로 띄운다 — 부모에 스레드(이벤트 루프·pyarrow)가 있는 상태에서
    fork하면 자식이 불안정해진다(실제로 segfault 재현). spawn은 기동이 조금 느린 대신 안전하다."""
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(
            max_workers=pool_size(), mp_context=multiprocessing.get_context("spawn"),
            initializer=die_with_parent,
        )
    return _pool


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
    _locks.clear()


def _session_lock(key: str) -> asyncio.Lock:
    """세션(또는 익명 요청군)별 잠금 — 한 세션이 풀을 독점하지 못하게 한다."""
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def run_isolated(key: str, fn, /, *args, **kwargs):
    """fn을 프로세스 풀에서 실행한다. 같은 key의 작업은 동시에 하나만 돈다.

    fn과 인자는 프로세스 간 전달을 위해 picklable이어야 한다 — 최상위 함수와 기본 타입만 쓴다.
    """
    async with _session_lock(key):
        loop = asyncio.get_running_loop()
        from functools import partial

        return await loop.run_in_executor(get_pool(), partial(fn, *args, **kwargs))
