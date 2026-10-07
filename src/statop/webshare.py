"""터미널 화면에서 웹으로 넘기기 — 같은 세션을 그대로 연다.

웹과 터미널이 **같은 session_*.json 파일**을 읽고 쓴다. 그래서 한쪽에서 컬럼을
가져오면 다른 쪽도 같은 상태가 된다 — 상태를 서버 메모리에 두지 않는 이유가 이것이다.

여기서는 서버가 떠 있는지 보고, 없으면 띄우고, 그 세션을 여는 주소를 만든다.
"""

import atexit
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

DEFAULT_PORT = 8000
_started: subprocess.Popen | None = None


@atexit.register
def _stop_spawned() -> None:
    """정상 종료 경로 — 서버가 자기 워커를 정리하고 죽게 한다.

    커널 장치(PDEATHSIG)는 강제 종료까지 막아 주지만, 그때는 서버가 정리할 틈이 없다.
    둘 다 둔다.
    """
    if _started is not None and _started.poll() is None:
        _started.terminate()


def port_open(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def is_ours(port: int = DEFAULT_PORT, host: str = "127.0.0.1",
            require_stamp: bool = True) -> bool:
    """포트가 열린 것과 **지금 코드의 우리 서버**인 것은 다르다.

    남의 서버면 Not Found가 뜨고, 옛날에 띄운 우리 서버면 새 화면이 부르는
    엔드포인트가 없어 첫 화면으로 떨어진다. 코드 지문까지 맞아야 재사용한다.
    """
    import json
    import urllib.error
    import urllib.request

    base = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(base + "/health", timeout=1.5) as r:
            h = json.loads(r.read().decode())
        # 이름을 바꾸기 전에 내보낸 파일은 evid_version 으로 적혀 있다
        if not {"statop_version", "evid_version"} & set(h):
            return False
        from statop.api.app import code_stamp

        if require_stamp and h.get("code_stamp") != code_stamp():
            return False        # 우리 것이지만 낡았다 — 재사용하면 조용히 어긋난다
        with urllib.request.urlopen(base + "/ui/", timeout=1.5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return False


def url_for(session_file: str | Path | None, port: int = DEFAULT_PORT,
            host: str = "127.0.0.1") -> str:
    """이 세션을 여는 웹 주소.

    전체 경로 대신 **세션 ID**를 붙인다 — 경로를 넣으면 주소가 터미널 폭을 넘어
    줄바꿈되고, 그러면 Ctrl+클릭이 링크로 인식하지 못한다.
    """
    import json

    base = f"http://{host}:{port}/ui/"
    if not session_file:
        return base
    try:
        sid = json.loads(Path(session_file).read_text())["session_id"]
        return f"{base}?s={quote(sid)}"
    except (OSError, ValueError, KeyError):
        return f"{base}?session={quote(str(session_file))}"


def ensure_server(port: int = DEFAULT_PORT, wait: float = 12.0,
                  tries: int = 5) -> tuple[int | None, str]:
    """(우리 화면이 뜬 포트, 못 띄웠으면 그 이유). 남이 쓰는 포트는 건너뛴다.

    **포트마다 무엇이 막았는지 따로 적는다.** 예전에는 하나로 뭉쳐 "모두 남의
    것"이라고만 했는데, 비어 있는 포트에 서버를 띄웠다가 응답을 못 받은 경우까지
    그렇게 말해서 **사실과 다른 안내**가 나갔다 (실제로 났다).
    """
    global _started

    from statop.messages import msg

    if not ui_built():
        return None, msg("screen_web_no_build")

    why: list[str] = []
    for p in range(port, port + tries):
        if is_ours(p):
            return p, ""     # 이미 우리 것이 떠 있다 — 포트를 또 잡지 않는다
        if port_open(p):
            # 열려 있는데 우리 것이 아니다. 우리 서버인데 낡은 것이면 그렇게 말한다 —
            # "남의 것"과 달리 사용자가 끄면 되는 문제다
            why.append(msg("web_port_stale" if _is_evid(p) else "web_port_foreign",
                           port=p))
            continue
        log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        # statop.api.child 를 거쳐 띄운다 — 그 안에서 "부모가 죽으면 나도 죽는다"를 건다.
        # 화면을 닫았는데 서버만 남으면 포트를 물고 쌓인다
        _started = subprocess.Popen(
            [sys.executable, "-m", "statop.api.child", "--port", str(p)],
            stdout=log, stderr=subprocess.STDOUT, env={**os.environ},
        )
        deadline = time.time() + wait
        died = False
        while time.time() < deadline:
            # **방금 우리가 띄운 자식이다** — 지문까지 다시 맞춰 보면, 그 사이 소스가
            # 한 글자만 바뀌어도 영원히 "낡았다"가 되어 못 쓴다 (개발 중 실제로 났다).
            # 낡음 검사는 '이미 떠 있던 남의 서버'를 거를 때만 의미가 있다
            if is_ours(p, require_stamp=False):
                return p, ""
            if _started.poll() is not None:
                died = True
                break
            time.sleep(0.3)
        tail = _tail(log.name)
        if died:
            why.append(msg("web_port_died", port=p, tail=tail or "-"))
        else:
            # 살아는 있는데 우리 것으로 안 보인다 — 띄우고도 못 쓰는 상태다
            _started.terminate()
            why.append(msg("web_port_no_answer", port=p, wait=wait))
    return None, msg("web_why_head", detail=" · ".join(why))


def _is_evid(port: int, host: str = "127.0.0.1") -> bool:
    """이 포트의 서버가 (낡았더라도) STATOP 인가 — 남의 것과 구별해 말하기 위해."""
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1.5) as r:
            got = json.loads(r.read().decode())
            return bool({"statop_version", "evid_version"} & set(got))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _tail(path: str, n: int = 2) -> str:
    """서버가 남긴 마지막 줄 — 사용자에게 보일 한 줄짜리 단서."""
    try:
        lines = [x.strip() for x in Path(path).read_text().splitlines() if x.strip()]
    except OSError:
        return ""
    return " / ".join(lines[-n:])[:300]


def ui_built() -> bool:
    return (Path(__file__).resolve().parents[2] / "ui" / "dist" / "index.html").exists()
