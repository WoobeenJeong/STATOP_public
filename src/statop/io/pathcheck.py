"""저장·불러오기 경로 검사 (요구사항): 초록/노랑/빨강 판정. 웹 UI 아이콘의 원천."""

import os
from dataclasses import dataclass
from pathlib import Path

from statop.messages import msg


@dataclass
class PathStatus:
    color: str  # green | yellow | red
    exists: bool
    readable: bool
    writable: bool
    can_create: bool  # 없을 때 부모 폴더에 만들 수 있는지
    reason: str  # 사유 1줄


def check_path(path: str | Path, need: str = "write") -> PathStatus:
    """경로를 검사한다. need: 'write'(저장용) 또는 'read'(불러오기용).

    초록 = 바로 사용 가능 / 노랑 = 없지만 생성 가능 / 빨강 = 사용 불가.
    """
    p = Path(path).expanduser()

    try:
        exists = p.exists()
    except OSError as e:  # 상위 폴더 접근 자체가 차단된 경우
        return PathStatus("red", False, False, False, False, msg("path_no_access", err=e.strerror))

    if exists:
        readable = os.access(p, os.R_OK)
        writable = os.access(p, os.W_OK)
        if need == "read":
            if readable:
                return PathStatus("green", True, readable, writable, False, msg("path_ok_read"))
            return PathStatus("red", True, False, writable, False, msg("path_no_read"))
        if writable:
            return PathStatus("green", True, readable, True, False, msg("path_ok_write"))
        return PathStatus("red", True, readable, False, False, msg("path_no_write"))

    if need == "read":
        return PathStatus("red", False, False, False, False, msg("path_not_exist"))

    # 저장용: 가장 가까운 존재하는 부모를 찾아 생성 가능 여부 판단
    parent = p.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if parent.exists() and os.access(parent, os.W_OK):
        return PathStatus("yellow", False, False, False, True, msg("path_can_create"))
    return PathStatus("red", False, False, False, False, msg("path_cannot_create", parent=parent))
