"""확정한 의미 타입으로 계산할 때 생길 수 있는 문제 (요구사항-7: 막지 않고 설명한다).

사용자는 추론 1위가 아닌 타입으로도 확정할 수 있다. 막지 않는다 — 대신 **그 타입으로
계산하면 무엇이 어떻게 틀어지는지**를 규칙 DB(S-R)에서 가져와 고지한다.
"""

from functools import lru_cache
from pathlib import Path

# 의미 타입 → 이 타입을 쓸 때 걸리는 S-R 규칙 (registry-tests 9.2)
TYPE_RULES = {
    "proportion": ["S-R01", "S-R02"],      # 조성 성분끼리 상관·차이
    "probability": ["S-R05"],              # 확률의 변동성(SD) 왜곡
    "count": ["S-R03", "S-R04"],           # 깊이 상이·log 변환
    "percent": ["S-R07"],                  # fraction과 척도 불일치
    "log-scale": ["S-R06"],                # 원척도와 혼합
    "expression index": ["S-R06"],
    "ordinal code": ["S-R08"],             # 평균·t-test
    "nominal code": ["S-R09"],             # 연속처럼 회귀
    "label": ["S-R09"],                    # 그룹 변수 — 연속처럼 쓰면 nominal 과 같은 사고
    "id": ["S-R10"],                       # 변수로 사용
    "z-score": ["S-R12"],                  # 기준 집단 상이
    "normalized score": ["S-R12"],
}


@lru_cache(maxsize=1)
def _compat_rules() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[2] / "rules" / "compat_rules.yaml"
    return {r["id"]: r for r in yaml.safe_load(path.read_text())}


def risks_for(semantic_type: str) -> list[dict]:
    """이 타입으로 계산할 때의 위험 목록 — 규칙 ID·판정·이유·해결책."""
    rules = _compat_rules()
    out = []
    for rid in TYPE_RULES.get(semantic_type, []):
        r = rules.get(rid)
        if r:
            out.append({"id": rid, "verdict": r["verdict"], "combination": r["combination"],
                        "why": r["why"], "fix": r["fix"]})
    return out


def risks_for_pair(type_a: str, type_b: str) -> list[dict]:
    """두 타입을 함께 쓸 때의 위험 — 같은 타입끼리(ratio×ratio)도 포함."""
    seen, out = set(), []
    for t in (type_a, type_b):
        for r in risks_for(t):
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out
