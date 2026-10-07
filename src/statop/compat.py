"""M1-3 연산 적합성 판정 (S-R 14종) — 막지 않고 무엇이 어떻게 틀어지는지 말한다.

**판정 범위를 둘로 나눈다 .**
  쌍(pair): 사용자가 두 컬럼을 **명시 지정했을 때만** 본다.
  전체(set): 선택 집합 전체를 보는 요약을 **연산 종류당 1건**만 낸다.
컬럼 n개에서 nC2 쌍마다 경고를 쏟으면 도구 자신이 다중비교 오류를 범하는 셈이 된다.

**타이밍 .** 컬럼을 고르는 순간에는 아무 말도 하지 않는다. 계산하려는 시점에
의미 타입 확정을 먼저 요구하고(미확정이면 S-R14로 보류), 확정된 뒤에만 판정을 전한다.

출력 순서는 registry-tests 9.3을 따른다: 미확정 → Gate → 빨강 → 노랑.
"""

from dataclasses import dataclass, field

from statop.messages import msg

# 연산 종류 — 어떤 규칙이 걸리는지는 "무엇을 하려는가"에 달려 있다
OP_CORRELATE = "correlate"     # 상관
OP_COMPARE = "compare"         # 군 간 차이·평균 비교
OP_REGRESS = "regress"         # 회귀·모델 입력
OP_SPREAD = "spread"           # 변동성(분산·SD) 질문
OP_AGGREGATE = "aggregate"     # 집계값 사용
OPERATIONS = (OP_CORRELATE, OP_COMPARE, OP_REGRESS, OP_SPREAD, OP_AGGREGATE)

# 판정 우선순위 (9.3) — 숫자가 작을수록 먼저
VERDICT_ORDER = {"unconfirmed": 0, "gate": 1, "red": 2, "yellow": 3}

# 원클릭 수정 가능한 조치 . 여기 없는 규칙은 사람이 판단해야 한다 —
# "수정 버튼이 없다"는 것 자체가 정보다.
FIX_CLR = "clr"
FIX_ALR = "alr"
FIX_LOGIT = "logit"
FIX_DIV100 = "div100"
FIX_UNIFY_SCALE = "unify_scale"
FIX_ACTIONS = (FIX_CLR, FIX_ALR, FIX_LOGIT, FIX_DIV100, FIX_UNIFY_SCALE)

# 척도가 서로 다른 타입 묶음 — 섞이면 차이·상관이 척도에 끌려간다
_LOG_TYPES = {"log-scale", "clr", "expression index"}
_RAW_UNIT = {"proportion", "probability"}


@dataclass
class Finding:
    """판정 1건. 근거 ID를 항상 달고 다닌다 — 왜 그런지 되짚을 수 있어야 한다."""

    id: str
    verdict: str
    scope: str                       # pair | set | column
    columns: list[str]
    why: str = ""
    fix: str = ""
    fix_action: str | None = None    # 원클릭으로 고칠 수 있으면 그 조치
    detail: str = ""                 # 이 데이터에서 실제로 관측된 근거
    targets: list[str] = field(default_factory=list)   # 조치가 바꿀 컬럼
    # 확인된 조성 세트. CLR/ALR은 세트 전체가 있어야 한다 — 일부만 변환하면 값이 틀린다
    composition: list[str] = field(default_factory=list)


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    blocked: bool = False            # 미확정이라 판정을 미룬 상태인가

    @property
    def verdict(self) -> str:
        if self.blocked:
            return "unconfirmed"
        for v in ("gate", "red", "yellow"):
            if any(f.verdict == v for f in self.findings):
                return v
        return "green"


def _rule(rid: str) -> dict:
    from statop.semantic_risk import _compat_rules

    return _compat_rules().get(rid, {})


def _mk(rid: str, scope: str, columns: list[str], detail: str = "",
        fix_action: str | None = None, targets: list[str] | None = None,
        composition: list[str] | None = None) -> Finding:
    r = _rule(rid)
    return Finding(id=rid, verdict=r.get("verdict", "yellow"), scope=scope,
                   columns=list(columns), why=r.get("why", ""), fix=r.get("fix", ""),
                   fix_action=fix_action, detail=detail,
                   targets=list(targets if targets is not None else columns),
                   composition=list(composition or []))


# ── 데이터에서 읽어야 판단되는 것들 ──────────────────────────
# 조성 성분이 받을 수 있는 의미 타입 — **둘 다 받는다.**
# 타입 추론은 `proportion` 을 1순위로 내놓지만, 사용자가 더 정확한 `조성 세트`(S-T13)로
# 확정하는 것도 자연스럽다(매뉴얼도 그렇게 안내한다). 한쪽만 보면 더 정확하게 고른
# 사용자에게서 조성 검사가 통째로 꺼진다 — 내부 사례 #7 이 그대로 지나갔다
COMPOSITION_TYPES = ("proportion", "composition set", "조성 세트")  # rule-vocab


def composition_groups(df, columns: list[str], types: dict[str, str]) -> list[list[str]]:
    """조성 세트를 찾는다 — 조성 타입으로 확정된 컬럼들 중 합이 1로 닫히는 묶음."""
    from statop.semantic import composition_set

    fracs = [c for c in columns
             if types.get(c) in COMPOSITION_TYPES and c in df.columns]
    groups: list[list[str]] = []
    seen: set[str] = set()
    for c in fracs:
        if c in seen:
            continue
        members = sorted(composition_set(df, c) & set(fracs))
        if len(members) >= 2:
            groups.append(members)
            seen |= set(members)
    return groups


def depth_differs(df, a: str, b: str, tol: float = 0.05) -> tuple[bool, str]:
    """count 두 컬럼의 총합(depth)이 다른가 — 다르면 값 차이가 총합 차이에 끌려간다."""
    sa, sb = float(df[a].sum()), float(df[b].sum())
    if min(sa, sb) <= 0:
        return False, ""
    ratio = max(sa, sb) / min(sa, sb)
    if ratio - 1 <= tol:
        return False, ""
    return True, msg("compat_detail_depth", a=a, b=b, sa=sa, sb=sb, ratio=ratio)


# ── 쌍 판정 ( (a)) ───────────────────────────────────────
def judge_pair(op: str, a: str, b: str, types: dict[str, str], df=None,
               comp_groups: list[list[str]] | None = None) -> Report:
    """사용자가 **명시 지정한 두 컬럼**에 대해서만 판정한다."""
    rep = Report()
    ta, tb = types.get(a), types.get(b)
    rep.unconfirmed = [c for c, t in ((a, ta), (b, tb)) if t is None]
    if rep.unconfirmed:
        # 확정 전에는 판정하지 않는다 — 추론값으로 경고하면 틀린 경고가 쌓인다
        rep.blocked = True
        rep.findings.append(_mk("S-R14", "pair", rep.unconfirmed))
        return rep

    pair = {ta, tb}
    same_comp = False
    if comp_groups:
        same_comp = any(a in g and b in g for g in comp_groups)

    # S-R10 id가 분석 변수로 (gate) — 무엇을 하든 걸린다
    for c, t in ((a, ta), (b, tb)):
        if t == "id":
            rep.findings.append(_mk("S-R10", "pair", [c], detail=msg("compat_detail_id", col=c)))

    # S-R09 nominal code를 연속처럼 (gate)
    if op in (OP_CORRELATE, OP_REGRESS):
        for c, t in ((a, ta), (b, tb)):
            if t in ("nominal code", "label"):
                rep.findings.append(_mk("S-R09", "pair", [c],
                                        detail=msg("compat_detail_nominal", col=c)))

    # S-R01 같은 조성 세트끼리 상관.
    # 타입은 두 이름 다 받는다 — `조성 세트`(S-T13)로 확정한 사용자에게서 꺼지면 안 된다
    comp_pair = pair <= set(COMPOSITION_TYPES)
    if op == OP_CORRELATE and comp_pair and same_comp:
        g = next(g for g in comp_groups if a in g and b in g)
        rep.findings.append(_mk("S-R01", "pair", [a, b],
                                detail=msg("compat_detail_comp_pair", n=len(g), cols=", ".join(g)),
                                fix_action=FIX_ALR if len(g) == 2 else FIX_CLR,
                                targets=g, composition=g))

    # S-R02 비율끼리 원척도 차이 비교. 같은 조성이면 세트 전체를 CLR해야 한다 —
    # 3성분 중 2개만 변환하면 기하평균이 달라져 값이 틀린다
    if op == OP_COMPARE and comp_pair:
        g = next((g for g in (comp_groups or []) if a in g and b in g), None)
        if g:
            rep.findings.append(_mk("S-R02", "pair", [a, b], targets=g, composition=g,
                                    fix_action=FIX_ALR if len(g) == 2 else FIX_CLR))
        else:
            rep.findings.append(_mk("S-R02", "pair", [a, b], fix_action=FIX_LOGIT))

    # S-R03 depth가 다른 count끼리
    if op in (OP_CORRELATE, OP_COMPARE) and pair == {"count"} and df is not None:
        differs, detail = depth_differs(df, a, b)
        if differs:
            rep.findings.append(_mk("S-R03", "pair", [a, b], detail=detail))

    # S-R05 확률의 변동성
    if op == OP_SPREAD and "probability" in pair:
        cols = [c for c, t in ((a, ta), (b, tb)) if t == "probability"]
        rep.findings.append(_mk("S-R05", "pair", cols))

    # S-R06 log 척도와 원척도를 섞음
    if op in (OP_CORRELATE, OP_COMPARE):
        logs = [c for c, t in ((a, ta), (b, tb)) if t in _LOG_TYPES]
        raws = [c for c, t in ((a, ta), (b, tb)) if t not in _LOG_TYPES and t is not None]
        if logs and raws:
            rep.findings.append(_mk("S-R06", "pair", [a, b],
                                    detail=msg("compat_detail_scale_mix", log=logs[0], raw=raws[0]),
                                    fix_action=FIX_UNIFY_SCALE, targets=raws))

    # S-R07 percent와 fraction을 함께
    if "percent" in pair and pair & _RAW_UNIT:
        pcts = [c for c, t in ((a, ta), (b, tb)) if t == "percent"]
        rep.findings.append(_mk("S-R07", "pair", [a, b],
                                detail=msg("compat_detail_percent", col=pcts[0]),
                                fix_action=FIX_DIV100, targets=pcts))

    # S-R08 순서 코드에 평균·t-test
    if op == OP_COMPARE:
        ords = [c for c, t in ((a, ta), (b, tb)) if t == "ordinal code"]
        if ords:
            rep.findings.append(_mk("S-R08", "pair", ords))

    # S-R12 기준 집단이 다른 z-score끼리
    if pair == {"z-score"} or pair == {"normalized score"}:
        rep.findings.append(_mk("S-R12", "pair", [a, b]))

    # S-R13 시간 파생 피처와 라벨
    if op in (OP_CORRELATE, OP_REGRESS):
        dts = [c for c, t in ((a, ta), (b, tb)) if t == "datetime"]
        if dts:
            rep.findings.append(_mk("S-R13", "pair", [a, b],
                                    detail=msg("compat_detail_datetime", col=dts[0])))

    _sort(rep)
    return rep


# ── 전체 판정 ( (b)) — 연산 종류당 요약 1건 ─────────────
def judge_set(op: str, columns: list[str], types: dict[str, str], df=None,
              comp_groups: list[list[str]] | None = None) -> Report:
    """선택 집합 전체를 한 번에 본다. 쌍마다 경고하지 않는다."""
    rep = Report()
    rep.unconfirmed = [c for c in columns if types.get(c) is None]
    if rep.unconfirmed:
        rep.blocked = True
        rep.findings.append(_mk("S-R14", "set", rep.unconfirmed))
        return rep

    present = {c: types[c] for c in columns}
    by_type: dict[str, list[str]] = {}
    for c, t in present.items():
        by_type.setdefault(t, []).append(c)

    ids = by_type.get("id", [])
    if ids:
        rep.findings.append(_mk("S-R10", "set", ids,
                                detail=msg("compat_detail_ids_set", n=len(ids))))

    if op in (OP_CORRELATE, OP_REGRESS) and (by_type.get("nominal code")
                                              or by_type.get("label")):
        cols = by_type.get("nominal code", []) + by_type.get("label", [])
        rep.findings.append(_mk("S-R09", "set", cols,
                                detail=msg("compat_detail_nominal_set", n=len(cols), cols=", ".join(cols[:4]))))

    for g in (comp_groups or []):
        members = [c for c in g if c in present]
        if len(members) >= 2 and op in (OP_CORRELATE, OP_COMPARE):
            rid = "S-R01" if op == OP_CORRELATE else "S-R02"
            rep.findings.append(_mk(rid, "set", members,
                                    detail=msg("compat_detail_comp_set", n=len(g)),
                                    fix_action=FIX_ALR if len(g) == 2 else FIX_CLR,
                                    targets=g, composition=g))

    logs = [c for c, t in present.items() if t in _LOG_TYPES]
    raws = [c for c, t in present.items() if t in _RAW_UNIT or t in ("count", "percent")]
    if logs and raws and op in (OP_CORRELATE, OP_COMPARE):
        rep.findings.append(_mk("S-R06", "set", logs + raws,
                                detail=msg("compat_detail_scale_mix_set", n_log=len(logs), n_raw=len(raws)),
                                fix_action=FIX_UNIFY_SCALE, targets=raws))

    pcts, fracs = by_type.get("percent", []), by_type.get("proportion", [])
    if pcts and fracs:
        rep.findings.append(_mk("S-R07", "set", pcts + fracs,
                                detail=msg("compat_detail_percent_set", n_pct=len(pcts), n_frac=len(fracs)),
                                fix_action=FIX_DIV100, targets=pcts))

    counts = by_type.get("count", [])
    if len(counts) >= 2 and df is not None and op in (OP_CORRELATE, OP_COMPARE):
        sums = {c: float(df[c].sum()) for c in counts if c in df.columns}
        if sums and min(sums.values()) > 0:
            lo, hi = min(sums.values()), max(sums.values())
            if hi / lo - 1 > 0.05:
                rep.findings.append(_mk("S-R03", "set", counts,
                                        detail=msg("compat_detail_depth_set", ratio=hi / lo)))

    if op == OP_COMPARE and by_type.get("ordinal code"):
        rep.findings.append(_mk("S-R08", "set", by_type["ordinal code"]))

    if op == OP_SPREAD and by_type.get("probability"):
        rep.findings.append(_mk("S-R05", "set", by_type["probability"]))

    zs = by_type.get("z-score", []) + by_type.get("normalized score", [])
    if len(zs) >= 2:
        rep.findings.append(_mk("S-R12", "set", zs,
                                detail=msg("compat_detail_zscore_set", n=len(zs))))

    if op == OP_AGGREGATE and by_type.get("nominal code"):
        rep.findings.append(_mk("S-R11", "set", columns,
                                detail=msg("compat_detail_aggregate")))

    if op in (OP_CORRELATE, OP_REGRESS) and by_type.get("datetime"):
        rep.findings.append(_mk("S-R13", "set", by_type["datetime"]))

    _sort(rep)
    return rep


def _sort(rep: Report) -> None:
    """9.3 순서 — 미확정 → Gate → 빨강 → 노랑. 같은 등급이면 규칙 번호 순."""
    rep.findings.sort(key=lambda f: (VERDICT_ORDER.get(f.verdict, 9), f.id))
