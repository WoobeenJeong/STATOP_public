"""라벨 매핑 (DECISIONS ) — 표시는 문자열, 계산은 코드.

`control`, `hct`, `liver` 같은 문자열 카테고리를 화면에는 그대로 보이고, 계산에는 지정한
코드(0/0/1)를 쓴다. 여러 수준을 같은 코드로 묶는 것은 **그룹 정의**이므로(3수준 → 2군),
묶기 전후의 군 크기를 항상 함께 보여준다.

색은 design-tokens 7절 앵커 사전에서 부분일치로 배정하고, 무매칭은 회색 미분류로 둔다.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

UNMATCHED_COLOR = "#8A9096"  # design-tokens --text-faint. 무매칭은 회색 미분류 (7.2-5)

# 7.2-1 정규화: 소문자화 · 구분자 제거 · 흔한 접미 제거
_SEPARATORS = re.compile(r"[-_./ ]+")
_SUFFIXES = ("cancer", "carcinoma", "adeno", "tumor", "tissue", "cells", "ca", "ep")


@dataclass
class Level:
    value: str  # 원래 문자열 (화면 표시용)
    n: int
    ratio: float
    code: int | None  # 계산에 쓰는 코드
    color: str
    category: str | None  # 라벨 사전에서 매칭된 카테고리
    ambiguous: bool = False  # 여러 카테고리에 걸린 경우 (7.2-4 → 사용자 확인)


def normalize(value: str) -> str:
    v = _SEPARATORS.sub("", str(value).lower())
    for suf in _SUFFIXES:  # 긴 접미부터 제거 (carcinoma가 ca보다 먼저)
        if v.endswith(suf) and len(v) > len(suf):
            v = v[: -len(suf)]
            break
    return v


@lru_cache(maxsize=1)
def _palette() -> tuple[list[dict], dict[str, list[str]]]:
    """rules/label_palette.yaml — 앵커 사전과 키워드 충돌 목록."""
    import yaml

    path = Path(__file__).resolve().parents[2] / "rules" / "label_palette.yaml"
    data = yaml.safe_load(path.read_text())
    conflicts = {c["keyword"]: c["categories"] for c in data.get("keyword_conflicts", [])}
    return data["anchors"], conflicts


def match_label(value: str) -> tuple[str | None, str, bool]:
    """문자열 → (카테고리, 색, 모호 여부). 우선순위는 7.2: TCGA 정확일치 → 최장 부분일치."""
    anchors, conflicts = _palette()
    norm = normalize(value)
    raw = str(value).strip().upper()

    for a in anchors:  # 1) TCGA 코드 정확일치
        if raw in a["tcga"]:
            return a["category"], a["color"], False

    hits: list[tuple[int, dict, str]] = []  # (일치 길이, 앵커, 키워드)
    for a in anchors:
        for kw in a["keywords"]:
            k = normalize(kw)
            if k and k in norm:
                hits.append((len(k), a, kw))
    if not hits:
        return None, UNMATCHED_COLOR, False

    hits.sort(key=lambda h: -h[0])  # 2) 가장 긴 일치 우선
    best_len, best, kw = hits[0]
    # 같은 길이로 여러 카테고리에 걸리거나, 사전 자체에 충돌 키워드면 모호로 표시 (7.2-4)
    tied = {h[1]["category"] for h in hits if h[0] == best_len}
    ambiguous = len(tied) > 1 or kw in conflicts
    return best["category"], best["color"], ambiguous


def levels_of(path: str | Path, column: str, sample_n: int = 10_000,
              mapping: dict[str, int] | None = None) -> list[Level]:
    """컬럼의 수준 목록 — 값·n·비율·코드·색. 코드 미지정이면 등장 순서대로 0,1,2…"""
    from statop.io.sample import sample_rows

    df = sample_rows(path, n=sample_n)
    if column not in df.columns:
        from statop.messages import msg

        raise ValueError(msg("select_err_missing", cols=column))

    vc = df[column].dropna().astype(str).value_counts()
    total = int(vc.sum())
    auto = {v: i for i, v in enumerate(vc.index)}  # 기본 코드: 빈도 높은 순
    out = []
    for value, n in vc.items():
        category, color, ambiguous = match_label(value)
        out.append(Level(value=str(value), n=int(n), ratio=n / total,
                         code=(mapping or {}).get(str(value), auto[value]),
                         color=color, category=category, ambiguous=ambiguous))
    return out


def groups_after(levels: list[Level]) -> dict[int, dict]:
    """매핑 적용 후의 군 구성 — 묶기가 무엇을 만드는지 보여준다 (그룹 정의)."""
    groups: dict[int, dict] = {}
    for lv in levels:
        g = groups.setdefault(lv.code, {"code": lv.code, "values": [], "n": 0})
        g["values"].append(lv.value)
        g["n"] += lv.n
    return dict(sorted(groups.items()))
