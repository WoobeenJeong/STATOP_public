"""사용자 문장 템플릿 로더 : 코어·CLI·웹이 같은 키로 한/영 문장을 얻는다."""

import os
from pathlib import Path

import yaml

_cache: dict[str, dict] = {}


def current_lang() -> str:
    return os.environ.get("STATOP_LANG", "ko")


def msg(_key: str, /, *, lang: str | None = None, **kw) -> str:
    """템플릿 문장을 얻는다.

    첫 인자는 위치 전용(`/`)이고 lang은 키워드 전용이다 — 템플릿이 `{key}`·`{lang}` 같은
    이름을 쓰더라도 인자 이름과 충돌하지 않게 하기 위함.
    """
    lang = lang or current_lang()
    if lang not in _cache:
        _cache[lang] = yaml.safe_load((Path(__file__).parent / f"{lang}.yaml").read_text())
    return _cache[lang][_key].format(**kw)
