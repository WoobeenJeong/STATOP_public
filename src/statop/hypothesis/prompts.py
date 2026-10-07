"""프롬프트를 `내부 규칙 명세` 에서 읽어 온다 (, ).

**문구는 코드가 아니라 md 가 갖는다.** 사용자가 읽고 고칠 수 있어야 하고, 고친 것이
바로 걸려야 한다 — 규칙 yaml 과 같은 원칙이다. 여기서는 읽어 채우기만 한다.

프롬프트·입력·출력은 전부 영문이다: 통계 용어는 한영 변환에서 뜻이 흔들린다.
사용자에게 보이는 화면만 번역한다.
"""

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_MD = Path(__file__).resolve().parents[3] / "schema" / "registry-prompts.md"

# 절 제목 → 이 프롬프트가 쓰는 블록. 제목을 바꾸면 여기서 시끄럽게 실패한다
SECTIONS = {                                              # rule-vocab
    "system": "4. 공통 시스템 프롬프트",                    # rule-vocab
    "analysis_input": "5.1 입력 형식",                      # rule-vocab
    "analysis_task": "5.2 지시문",                          # rule-vocab
    "modeling_input": "6.1 입력 형식",                      # rule-vocab
    "modeling_task": "6.2 지시문",                          # rule-vocab
}
STANCES = ("optimal", "conservative", "broad")


def _sections(text: str) -> dict[str, str]:
    """제목 → 그 절의 첫 코드블록 내용.

    **코드블록 안은 절 제목으로 보지 않는다** — 프롬프트 본문에도 `## Study setup`
    같은 줄이 있어서, 정규식으로 자르면 프롬프트가 두 동강 난다 (실제로 났다).
    """
    out, title, fence, buf = {}, None, False, []
    for line in text.splitlines():
        if line.startswith("```"):
            if fence and title and title not in out:
                out[title] = "\n".join(buf).rstrip()
            fence, buf = not fence, []
            continue
        if fence:
            buf.append(line)
        elif line.startswith(("## ", "### ")):
            title = line.lstrip("# ").strip()
    return out


@lru_cache(maxsize=1)
def _blocks() -> dict[str, str]:
    """절마다 첫 번째 코드블록을 꺼낸다."""
    found = _sections(PROMPTS_MD.read_text(encoding="utf-8"))
    out = {}
    for key, title in SECTIONS.items():
        hit = next((v for k, v in found.items() if k.startswith(title)), None)
        if hit is None:
            from statop.messages import msg

            raise ValueError(msg("prompt_block_missing", file=PROMPTS_MD.name,
                                 section=title))
        out[key] = hit
    return out


def system() -> str:
    return _blocks()["system"]


def template(family: str) -> tuple[str, str]:
    """(입력 템플릿, 지시문). family 는 analysis | modeling."""
    if family not in ("analysis", "modeling"):
        raise ValueError(f"unknown prompt family: {family}")
    b = _blocks()
    return b[f"{family}_input"], b[f"{family}_task"]


def fields(family: str) -> set[str]:
    """입력 템플릿이 요구하는 치환 자리 — 빠뜨리면 채우는 쪽에서 바로 드러난다."""
    body, _ = template(family)
    return set(re.findall(r"\{(\w+)\}", body))


def fill(family: str, values: dict) -> str:
    """입력 템플릿 + 지시문. 자리를 빠뜨리면 KeyError 로 시끄럽게 실패한다."""
    body, task = template(family)
    need = fields(family)
    missing = need - set(values)
    if missing:
        from statop.messages import msg

        raise KeyError(msg("prompt_missing_fields", family=family,
                           fields=", ".join(sorted(missing))))
    return body.format(**{k: values[k] for k in need}) + "\n\n" + task
