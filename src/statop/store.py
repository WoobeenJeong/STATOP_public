"""기본 저장소 : {STATOP_HOME}/{사용자id}/ 아래에 tmp·sessions·라이브러리를 관리.

STATOP_HOME 미설정 시 ~/.statop. 배포 시 공용 경로로 설정하면 팀원 폴더가 한곳에 모여
남의 저장물을 경로로 탐색할 수 있다.
"""

import getpass
import os
from pathlib import Path


def base_dir() -> Path:
    return Path(os.environ.get("STATOP_HOME", Path.home() / ".statop"))


def user_id() -> str:
    return os.environ.get("STATOP_USER", getpass.getuser())


def user_dir() -> Path:
    return base_dir() / user_id()


def tmp_dir() -> Path:
    """작업 중 임시본(session_*.json) 위치 — 저장 없이 닫으면 삭제되는 영역."""
    d = user_dir() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    """정식 저장본 기본 위치."""
    d = user_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d
