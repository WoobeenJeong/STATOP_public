"""A2 3색 후보 엔진 (~) — 규칙 DB(tests.yaml 66종)에서 검정 후보를 고른다.

판정은 세 단계다:
  ① 설계 불일치(군 수·짝지음·변수 형태가 스펙과 다름) → 목록에서 **제외**
  ② 기계로 판정 가능한 차단·주의(blocked_when/caution 의 타입·n 조건) → red/yellow
  ③ 가정(C-xx)이 필요한데 아직 안 봤으면 → yellow (A3 를 돌리면 갱신된다)

사유 문장은 규칙 DB의 필드를 그대로 쓰고 데이터 수치만 끼운다 ( — LLM 불필요).
규칙에 없는 말을 지어내지 않는다.
"""

import re
from dataclasses import dataclass, field

from statop.analyze.spec import Spec, SpecResult, _rules
from statop.messages import msg

# y 의 의미 타입 → 검정이 보는 변수 형태
_CONTINUOUS = {"continuous", "log-scale", "clr", "z-score", "normalized score",
               "expression index", "percent", "proportion", "probability", "count"}
_RANK = {"ordinal code"}
_BINARY_CODE = {"nominal code", "label"}


@dataclass
class Candidate:
    id: str
    name: str
    color: str                        # green | yellow | red
    reasons: list[str] = field(default_factory=list)
    assumptions: str = ""             # 아직 확인 안 된 가정 (C-xx)
    effect_size: str = ""
    alternatives: str = ""
    design: str = ""
    runnable: bool = True             # 실행 함수가 있는가 (없으면 값을 구할 수 없다)


def _design_terms(design: str) -> dict:
    """design 문자열("2군 독립, 연속")을 조건으로 — 규칙 필드가 원본이다."""
    d = design or ""
    out = {
        "k2": bool(re.search(r"(^|[^≥\d])2\s*군|2×2|2군", d)),  # rule-vocab
        "k3": "≥3" in d or "r×c" in d,
        "paired": ("대응" in d) or ("반복" in d),  # rule-vocab
        "independent": "독립" in d,  # rule-vocab
        "continuous": "연속" in d,  # rule-vocab
        "rank": "순위" in d,  # rule-vocab
        "binary": ("이진" in d) or ("비율" in d and "군" in d) or ("2×2" in d),  # rule-vocab
        "two_vars": d.startswith("두 "),  # rule-vocab
        "survival": ("생존" in d) or ("사건" in d),  # rule-vocab
        "composition": "조성" in d,  # rule-vocab
    }
    return out


def _n_condition(text: str) -> tuple[str, int] | None:
    """"n<15", "n≥15/군" 같은 숫자 조건을 찾는다 — 이것만 기계로 판정한다."""
    m = re.search(r"n\s*([<≥>=≤]+)\s*(\d+)", text or "")
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _min_group_n(res: SpecResult) -> int | None:
    if res.group_levels:
        return min(res.group_levels.values())
    return res.n_rows or None


def _stays_same_test(t: dict) -> bool:
    """가정이 깨져도 **그 검정 안에서** 해결되는가.

    규칙표의 `caution` 이 다른 검정(T-xxx)을 가리키면 그쪽으로 가라는 뜻이고,
    아무 T-id 도 없으면 "이 검정의 다른 변형을 쓰라"는 뜻이다
    (T-803: 과산포 → NB, 영과잉 → ZIP/ZINB). 뒤쪽을 탈락으로 세면
    **맞는 검정이 영영 초록이 못 된다** — 실측으로 그랬다.
    """
    how = t.get("caution") or ""
    return bool(how) and not re.search(r"T-\d+", how)


def _assumption_state(res: SpecResult) -> tuple[set, set]:
    """(본 가정, 위배된 가정). A3 를 아직 안 돌렸으면 둘 다 빈 집합이다."""
    checked: set = set()
    violated: set = set()
    for c in getattr(res, "checks", None) or []:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        verdict = c.get("verdict") if isinstance(c, dict) else getattr(c, "verdict", "")
        if not cid or verdict == "skipped":
            continue
        checked.add(cid)
        if verdict in ("violated", "caution"):
            violated.add(cid)
    return checked, violated


def shortlist(res: SpecResult) -> list[Candidate]:
    """스펙+데이터에 맞는 후보를 3색으로 — 제외된 것은 목록에 없다 (66개를 다 보이지 않는다)."""
    checked, violated = _assumption_state(res)
    spec = res.spec
    k = len(res.group_levels) if res.group_levels else 0
    y_cont = res.y_type in _CONTINUOUS
    y_rank = res.y_type in _RANK
    y_code = res.y_type in _BINARY_CODE
    min_n = _min_group_n(res)

    out: list[Candidate] = []
    for t in _rules()["tests"]:
        if t.get("question") != spec.question:
            continue
        terms = _design_terms(t.get("design", ""))

        # ① 설계 불일치 → 제외
        if spec.group and k:
            if terms["k2"] and not terms["k3"] and k != 2:
                continue
            if terms["k3"] and not terms["k2"] and k < 3:
                continue
        if terms["paired"] != spec.paired and (terms["paired"] or terms["independent"]):
            continue
        if terms["continuous"] and not (terms["rank"] or y_cont):
            if y_rank or y_code:
                # 연속 전용 검정에 순위·코드 y — 차단으로 보여준다 (왜 안 되는지 알게)
                out.append(_make(t, "red",
                                 [msg("cand_reason_scale", y=spec.y,
                                      y_type=res.y_type or "?")]))
                continue
        if terms["binary"] and y_cont and not y_code:
            continue
        if terms["survival"] or terms["composition"]:
            if not (terms["composition"] and res.y_type in ("proportion", "clr")):
                continue

        # ② 기계 판정 가능한 차단·주의
        color, reasons = "green", []
        blocked = t.get("blocked_when") or ""
        caution = t.get("caution") or ""

        if ("순위" in blocked or "범주" in blocked) and (y_rank or y_code):  # rule-vocab
            color = "red"
            reasons.append(msg("cand_reason_blocked", text=blocked))
        nc = _n_condition(caution)
        if color != "red" and nc and min_n is not None:
            op, lim = nc
            hit = min_n < lim if "<" in op else min_n >= lim
            if hit:
                color = "yellow"
                reasons.append(msg("cand_reason_caution", text=caution, n=min_n))
        nc = _n_condition(t.get("best_when") or "")
        if color == "green" and nc and min_n is not None:
            op, lim = nc
            ok = min_n >= lim if "≥" in op or ">" in op else min_n < lim
            if not ok:
                color = "yellow"
                reasons.append(msg("cand_reason_best_unmet",
                                   text=t["best_when"], n=min_n))

        # ③ 가정 — **A3 결과가 있으면 그걸 쓴다.** 없으면 초록이라 말하지 않는다.
        #    예전에는 결과가 있어도 무조건 노랑으로 내렸다. 화면은 "가정 검사를 돌리면
        #    판정이 갱신됩니다"라고 말하는데 갱신하는 코드가 없었다 — 말과 동작이 달랐다
        assumptions = t.get("assumptions") or ""
        needed = set(re.findall(r"C-\d+", assumptions))
        if color == "green" and needed:
            bad = sorted(needed & violated)
            unseen = sorted(needed - checked)
            if bad and _stays_same_test(t):
                # 규칙표가 "이 검정 **안에서** 바꿔라"라고 말하는 경우다
                # (예: T-803 과산포 → NB). 그건 탈락이 아니라 변형 선택이다
                reasons.append(msg("cand_reason_assump_variant",
                                   c=", ".join(bad), how=t.get("caution") or ""))
            elif bad:
                color = "yellow"
                reasons.append(msg("cand_reason_assump_violated", c=", ".join(bad)))
            elif unseen:
                color = "yellow"
                reasons.append(msg("cand_reason_assumptions", c=", ".join(unseen)))
            else:
                reasons.append(msg("cand_reason_assump_ok", c=", ".join(sorted(needed))))

        if color == "green" and t.get("best_when"):
            reasons.append(msg("cand_reason_best", text=t["best_when"]))
        out.append(_make(t, color, reasons))

    order = {"green": 0, "yellow": 1, "red": 2}
    out.sort(key=lambda c: (order[c.color], c.id))
    return out


def _make(t: dict, color: str, reasons: list[str]) -> Candidate:
    # 표에는 있지만 아직 계산기가 없는 검정이 있다. 색과 별개로 표시해야
    # "초록인데 눌러도 값이 안 나오는" 일이 없다
    from statop.analyze.run import RUNNERS

    if t["id"] not in RUNNERS:
        reasons = [*reasons, msg("cand_reason_not_implemented")]
    return Candidate(id=t["id"], name=t["name"], color=color, reasons=reasons,
                     runnable=t["id"] in RUNNERS,
                     assumptions=t.get("assumptions") or "",
                     effect_size=t.get("effect_size") or "",
                     alternatives=t.get("alternatives") or "",
                     design=t.get("design") or "")
