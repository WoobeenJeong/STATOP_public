"""registry-*.md 표 파서 : md가 단일 진실, yaml은 여기서 자동 생성된다.

markdown 표를 섹션 제목과 함께 추출한다. 셀 안의 이스케이프된 파이프(\\|)를 처리한다
(예: registry-tests 9.2의 "P(Y\\|Z)").
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")  # |---|:---:| 형태
_SPLIT_RE = re.compile(r"(?<!\\)\|")  # 이스케이프 안 된 파이프로만 분할


@dataclass
class Table:
    section: str  # 직전 헤딩 (예: "9.2 연산 적합성 규칙 (S-R) — ...")
    headers: list[str]
    rows: list[dict] = field(default_factory=list)  # header → cell


def _cells(line: str) -> list[str]:
    parts = _SPLIT_RE.split(line.strip())
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [p.replace("\\|", "|").strip() for p in parts]


def parse_tables(text: str) -> list[Table]:
    tables: list[Table] = []
    section = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _SEP_RE.match(lines[i + 1]):
            headers = _cells(line)
            t = Table(section=section, headers=headers)
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = _cells(lines[i])
                cells += [""] * (len(headers) - len(cells))  # 짧은 행 보정
                t.rows.append(dict(zip(headers, cells[: len(headers)])))
                i += 1
            tables.append(t)
            continue
        i += 1
    return tables


def parse_file(path: str | Path) -> list[Table]:
    return parse_tables(Path(path).read_text())


def find_table(tables: list[Table], section_contains: str) -> Table:
    """섹션 제목 부분일치로 표 하나를 찾는다. 없거나 여러 개면 시끄럽게 실패."""
    hits = [t for t in tables if section_contains in t.section]
    if len(hits) != 1:
        raise ValueError(
            f"section {section_contains!r}: expected exactly 1 table, found {len(hits)}"
        )
    return hits[0]
