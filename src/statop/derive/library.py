"""커스텀 수식 라이브러리 (M1-2, 요구사항.6b ②) — `formulas.json`.

세션이 아니라 **사용자 라이브러리**에 저장한다. 이름으로 저장·검색하고(Lorentzian_Entropy 등),
입력 슬롯으로 일반화해 다른 컬럼에 재사용한다.

base(내장 점수·관계표)는 건드리지 않는다 — 사용자가 만드는 건 **입력 층**이다 ().
"""

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FILENAME = "formulas.json"


@dataclass
class Formula:
    name: str
    expr: str                       # 정규화된 일반 표기 (계산용)
    latex: str | None = None        # 사용자가 입력한 LaTeX (표시용)
    slots: list[str] = field(default_factory=list)   # 입력 슬롯 이름 ({x}, {y} 대신 원 컬럼명)
    params: dict = field(default_factory=dict)       # eps·k 등 기본값
    result_type: str = "continuous"
    note: str | None = None
    created: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def library_path(path: str | Path | None = None) -> Path:
    from statop.store import user_dir

    return Path(path) if path else user_dir() / FILENAME


def load(path: str | Path | None = None) -> dict[str, Formula]:
    p = library_path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    return {k: Formula(**v) for k, v in raw.items()}


def save_all(items: dict[str, Formula], path: str | Path | None = None) -> Path:
    p = library_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({k: v.as_dict() for k, v in items.items()},
                            ensure_ascii=False, indent=1))
    return p


def save(formula: Formula, path: str | Path | None = None,
         overwrite: bool = False) -> Path:
    """이름으로 저장. 같은 이름이 있으면 overwrite 없이는 거부한다 (D-23과 같은 정신)."""
    from statop.messages import msg

    items = load(path)
    if formula.name in items and not overwrite:
        raise FileExistsError(msg("formula_name_exists", name=formula.name))
    formula.created = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    items[formula.name] = formula
    return save_all(items, path)


def remove(name: str, path: str | Path | None = None) -> Path:
    from statop.messages import msg

    items = load(path)
    if name not in items:
        raise KeyError(msg("formula_not_found", name=name))
    del items[name]
    return save_all(items, path)


def bind(formula: Formula, mapping: dict[str, str]) -> str:
    """슬롯에 실제 컬럼을 끼워 수식을 만든다 — 저장된 수식을 다른 데이터에 재사용."""
    import re

    from statop.messages import msg

    missing = [s for s in formula.slots if s not in mapping]
    if missing:
        raise KeyError(msg("formula_slot_missing", slots=", ".join(missing)))
    expr = formula.expr
    # 긴 이름부터 치환 — 짧은 이름이 긴 이름의 일부일 때 깨지지 않게
    for slot in sorted(formula.slots, key=len, reverse=True):
        expr = re.sub(rf"\b{re.escape(slot)}\b", mapping[slot], expr)
    return expr


# 규칙의 "원클릭 수정"에 등장하는 변환 ↔ 수식 함수. 수식이 이미 그 변환을 하고 있으면
# 그 규칙은 해소된 것으로 본다 (log2(frac+eps)는 S-R02가 권하는 방향이다).
# 변환 이름만 본다 — 한국어/영어 규칙문 양쪽에 그대로 나오는 유일한 부분이라서.
MITIGATIONS = {
    "clr": ("clr",), "ilr": ("ilr",), "alr": ("alr",),
    "logit": ("logit",), "log": ("log", "log2", "log10", "ln"),
}


def mitigated_by(fix_text: str, functions: set[str]) -> bool:
    """수식의 함수들이 이 규칙의 권고 변환을 이미 수행하는가."""
    low = (fix_text or "").lower()
    for key, funcs in MITIGATIONS.items():
        if key.lower() in low and functions & set(funcs):
            return True
    return False


def applicability(formula: Formula, types: dict[str, str], mapping: dict[str, str],
                  functions: set[str] | None = None) -> dict:
    """3색 판정 (M1-2) — 슬롯에 끼운 컬럼의 의미 타입으로 위험을 본다.

    사용자 수식에는 전용 규칙이 없으므로 **슬롯 공간(의미 타입)만** 검사한다.
    다만 수식이 이미 권고 변환(CLR·logit·log)을 적용했으면 그 규칙은 해소로 본다 —
    아니면 "고치라고 한 것을 고쳤는데도 빨간불"이 된다.
    판정: red(미해소 위험) / yellow(해소됨·타입 미확정) / green(문제 없음).
    """
    from statop.semantic_risk import risks_for

    functions = functions or set()
    risks, unknown = [], []
    for slot in formula.slots:
        col = mapping.get(slot)
        t = types.get(col)
        if t is None:
            unknown.append(col or slot)
            continue
        for r in risks_for(t):
            if r["id"] in {x["id"] for x in risks}:
                continue
            risks.append({**r, "column": col, "type": t,
                          "mitigated": mitigated_by(r["fix"], functions)})

    blocking = [r for r in risks if not r["mitigated"]]
    if any(r["verdict"] in ("red", "gate") for r in blocking):
        verdict = "red"
    elif blocking or unknown or risks:
        verdict = "yellow"
    else:
        verdict = "green"
    return {"verdict": verdict, "risks": risks, "unconfirmed": unknown,
            "n_mitigated": sum(1 for r in risks if r["mitigated"])}
