"""S190a 모델 비교 규칙 — 무엇으로 견줄 수 있는가 (MB-C34).

두 모델의 성능 숫자를 나란히 놓으면 우열이 있어 보인다. 그런데 **견줄 수 없는 쌍**이
있다 — 결측 처리로 행 수가 달라졌거나, 결과변수가 다르거나, 포함관계가 아닌데 LRT 를
쓰려는 경우다. 비교가 불가능한데 숫자를 나란히 놓으면 **없는 우열이 생긴다.**

판정은 **모델쌍마다** 낸다. "비교할 수 없습니다"만으로는 무엇을 고칠지 모르므로
어느 쌍이 왜 안 되는지 지목한다 .

규칙표는 `registry-models.md` 3.7 이고 `rules/models.yaml` 의 `comparison` 으로 들어온다 —
여기서 지어내지 않는다.

**감사 전용이다.** 학습을 돌리지 않고 사용자가 적어 준 모델 구성만 본다.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, skip


@dataclass
class Model:
    """감사 입력 — 학습을 돌리지 않으므로 사용자가 적어 준다."""

    name: str
    terms: list[str] = field(default_factory=list)   # 설명변수 항
    n: int | None = None                             # 실제로 적합한 행 수
    outcome: str | None = None                       # 결과변수
    family: str | None = None                        # 분포족 (binomial·gaussian …)

    @classmethod
    def parse(cls, text: str) -> "Model":
        """`m1: age+sex [n=480] [y=death] [family=binomial]` 형태를 읽는다."""
        import re

        name, _, rest = text.partition(":")
        opts = dict(re.findall(r"(\w+)\s*=\s*([^\s\]]+)", rest))
        terms = re.sub(r"\[[^\]]*\]", "", rest).strip()
        return cls(name=name.strip(),
                   terms=[t.strip() for t in terms.split("+") if t.strip()],
                   n=int(opts["n"]) if "n" in opts else None,
                   outcome=opts.get("y"), family=opts.get("family"))


@lru_cache(maxsize=1)
def _conditions() -> dict:
    import yaml

    from statop.rules.build import RULES_DIR

    db = yaml.safe_load((RULES_DIR / "models.yaml").read_text(encoding="utf-8"))
    return {c["condition"]: c for c in db["comparison"]}


def conditions() -> list[dict]:
    return list(_conditions().values())


def classify(a: Model, b: Model) -> str:
    """이 모델쌍이 규칙표의 어느 조건에 해당하는가.

    순서가 곧 우선순위다 — 결과변수가 다르면 n 이 같든 말든 견줄 수 없다.
    """
    if a.outcome and b.outcome and a.outcome != b.outcome:
        return "different_outcome"
    if a.n is not None and b.n is not None and a.n != b.n:
        return "different_n"
    if a.family and b.family and a.family != b.family:
        return "different_family"
    sa, sb = set(a.terms), set(b.terms)
    return "same_n_nested" if (sa <= sb or sb <= sa) else "same_n_non_nested"


def compare_pair(a: Model, b: Model) -> dict:
    """한 쌍의 판정 — 조건·가능 여부·쓸 수 있는 것·왜."""
    cond = classify(a, b)
    rule = _conditions()[cond]
    sa, sb = set(a.terms), set(b.terms)
    extra = sorted(sb - sa) if sa <= sb else sorted(sa - sb)
    # 행 수가 다르면 **얼마나 다른지**를 같이 낸다 — "다르다"만으로는 크기를 알 수 없다
    gap = None
    if a.n is not None and b.n is not None and a.n != b.n:
        gap = {"diff": abs(a.n - b.n),
               "ratio": abs(a.n - b.n) / max(a.n, b.n)}
    return {"pair": f"{a.name} vs {b.name}", "condition": cond,
            "comparable": rule["comparable"], "allowed": list(rule["allowed"]),
            "why": rule["why"], "nested": bool(sa <= sb or sb <= sa),
            "added_terms": extra if (sa <= sb or sb <= sa) else [],
            "n": {a.name: a.n, b.name: b.n}, "n_gap": gap}


def audit(models: list[Model]) -> LeakFinding:
    """모델 목록 전체 — 견줄 수 없는 쌍이 하나라도 있으면 그 쌍을 지목한다."""
    if len(models) < 2:
        return skip("MB-C34", msg("mb_c34_need_two"))
    pairs = [compare_pair(a, b) for a, b in combinations(models, 2)]
    blocked = [p for p in pairs if p["comparable"] == "불가"]   # rule-vocab
    limited = [p for p in pairs if p["comparable"] == "부분"]   # rule-vocab
    caution = [p for p in pairs if p["comparable"] == "주의"]   # rule-vocab
    flagged = blocked + caution + limited

    def line(p: dict) -> str:
        # 쓸 수 있는 것이 없으면 그 칸을 아예 뺀다 — "쓸 수 있는 것 —" 은 읽히지 않는다
        allowed = (msg("mb_c34_allowed", allowed=", ".join(p["allowed"]))
                   if p["allowed"] else "")
        # 행 수가 다르면 몇 행 차이인지 — 480 vs 412 와 480 vs 478 은 다른 이야기다
        gap = (msg("mb_c34_gap", body=" vs ".join(
            msg("mb_c34_gap_cell", name=k, n=v)
            for k, v in p["n"].items() if v is not None),
            diff=p["n_gap"]["diff"], ratio=p["n_gap"]["ratio"])
            if p["n_gap"] else "")
        return msg("mb_c34_row", pair=p["pair"], comparable=p["comparable"],
                   allowed=allowed, why=p["why"]) + gap

    numbers = {"pairs": pairs}
    if flagged:
        # 막지 않는다 (Diag). 어느 쌍이 어떤 상태인지 이름으로 부르고, 되는 쌍은 건드리지 않는다
        return LeakFinding(
            id="MB-C34", grade=grade_of("MB-C34"), verdict="fail",
            summary=msg("mb_c34_flagged", n=len(flagged), pairs=" · ".join(
                f"{p['pair']}({p['comparable']})" for p in flagged)),
            detail=[line(p) for p in pairs], numbers=numbers,
            action=msg("mb_c34_action" if blocked else "mb_c34_limited_action"))
    return LeakFinding(id="MB-C34", grade=grade_of("MB-C34"), verdict="pass",
                       summary=msg("mb_c34_pass", n=len(pairs)),
                       detail=[line(p) for p in pairs], numbers=numbers)
