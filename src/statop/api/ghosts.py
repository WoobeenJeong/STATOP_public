"""이 장비에 남아 있는 STATOP 프로세스를 세고, 원하면 정리한다.

왜 필요한가: 웹 서버와 계산 일꾼은 **부모가 죽으면 같이 죽게** 되어 있지만, 그 장치가
없던 때 띄운 것들은 그대로 남는다. 실제로 한 장비에서 326개(106GB)가 6일간 살아 있었고,
포트를 물고 있어 그 뒤로는 웹을 아예 못 띄웠다.

여기서는 **보기와 정리만** 한다. 무엇을 끄는지 먼저 보여 주고, `--stop` 을 줄 때만 끈다.
"""

import os
import subprocess
from dataclasses import dataclass, field

SERVER_MARK = "statop.api.child"          # [웹에서 보기] 가 띄우는 서버
SERVE_MARK = "uvicorn statop.api.app"     # statop serve 로 직접 띄운 서버
WORKER_MARK = "multiprocessing"


@dataclass
class Found:
    servers: list = field(default_factory=list)      # (pid, ppid, port)
    workers: list = field(default_factory=list)      # (pid, ppid)
    worker_gb: float = 0.0

    @property
    def orphans(self) -> list:
        return [p for p, ppid, *_ in self.servers + self.workers if ppid == 1]

    def __bool__(self) -> bool:
        return bool(self.servers or self.workers)


def _ps() -> list:
    out = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid=,ppid=,rss=,args="],
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
    return rows


def _port_of(args: str) -> str:
    bits = args.split()
    return bits[bits.index("--port") + 1] if "--port" in bits else "?"


def _ancestors(pid: int, rows: list) -> set:
    """나를 낳은 프로세스들 — **여기에 든 것은 절대 죽이지 않는다.**

    없으면 conda·셸 래퍼를 서버로 잘못 보고 내 셸을 죽인다 (실제로 죽였다).
    """
    parent = {p: pp for p, pp, *_ in rows}
    out, cur = set(), pid
    while cur and cur != 1 and cur not in out:
        out.add(cur)
        cur = parent.get(cur, 0)
    return out


def _is_wrapper(args: str) -> bool:
    """`conda run ...` 은 서버가 아니라 서버를 띄운 껍데기다."""
    return "conda run" in args or "condabin/conda" in args


def scan() -> Found:
    """이 장비에서 이 사용자가 띄운 것만 본다 — 남의 프로세스는 건드리지 않는다."""
    rows = _ps()
    safe = _ancestors(os.getpid(), rows)
    f = Found()
    for pid, ppid, rss, args in rows:
        if pid in safe or "statop/api/ghosts" in args or _is_wrapper(args):
            continue
        if SERVER_MARK in args or SERVE_MARK in args:
            f.servers.append((pid, ppid, _port_of(args)))
        elif "envs/statop" in args and WORKER_MARK in args:
            f.workers.append((pid, ppid))
            f.worker_gb += rss / 1048576
    return f


def stop(found: Found) -> int:
    """서버를 먼저 끈다 — 서버가 죽으면 그 일꾼도 따라 죽는다."""
    import signal
    import time

    pids = [p for p, *_ in found.servers] + [p for p, *_ in found.workers]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(3)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return len(pids)
