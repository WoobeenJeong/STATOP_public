"""M1-3 원클릭 수정 (~) — 판정에서 제시한 조치를 실제 파생 컬럼으로 만든다.

고친 뒤에는 **지정을 교체한다** : 원본 컬럼은 남지만 분석 대상에서 빠지고,
새로 만든 컬럼이 그 자리에 들어간다. 그래야 다시 판정했을 때 같은 경고가 또 뜨지 않는다.

조치는 전부 파생 컬럼 수식으로 표현된다 — 즉 수식과 eps가 세션 기록에 남아
나중에 "무엇을 어떻게 고쳤는지"를 되짚을 수 있다.
"""

from dataclasses import dataclass

from statop.compat import (FIX_ALR, FIX_CLR, FIX_DIV100, FIX_LOGIT, FIX_UNIFY_SCALE,
                         Finding)

SUFFIX = {FIX_CLR: "_clr", FIX_ALR: "_alr", FIX_LOGIT: "_logit",
          FIX_DIV100: "_frac", FIX_UNIFY_SCALE: "_log"}


@dataclass
class Plan:
    """무엇을 만들고 무엇을 뺄지 — 적용 전에 그대로 보여준다."""

    action: str
    derives: list[dict]          # {name, expr, eps, composition, result_type}
    replaces: list[tuple[str, str]]   # (원본, 대체)
    needs_eps: bool = False
    needs_composition: bool = False
    note: str = ""


def plan(finding: Finding, df=None, composition: list[str] | None = None,
         reference: str | None = None) -> Plan:
    """판정 1건에서 수정 계획을 만든다. 계산은 하지 않는다 (미리 보여주기 위함).

    composition: CLR/ALR용 조성 세트. 미지정이면 needs_composition으로 되돌려
    사용자에게 묻는다  — 세트를 임의로 정하면 값이 통째로 달라진다.
    """
    from statop.messages import msg

    act = finding.fix_action
    if act is None:
        raise ValueError(msg("compat_no_auto_fix", id=finding.id))

    targets = finding.targets or finding.columns

    if act in (FIX_CLR, FIX_ALR):
        # 사용자 지정 > 판정이 확인한 세트 > (없으면 묻는다). 추측하지 않는다
        comp = composition or finding.composition or None
        if not comp or len(comp) < 2:
            return Plan(act, [], [], needs_composition=True,
                        note=msg("compat_need_composition"))
        if act == FIX_ALR:
            ref = reference or comp[-1]      # 기준 성분 — 나머지를 이것으로 나눈다
            if ref not in comp:
                raise ValueError(msg("compat_alr_reference_unknown", col=ref))
            others = [c for c in comp if c != ref]
            derives = [{"name": c + SUFFIX[act], "expr": f"alr({c}, {ref})",
                        "eps": None, "composition": None, "result_type": "log-scale"}
                       for c in others]
            return Plan(act, derives, [(c, c + SUFFIX[act]) for c in others],
                        needs_eps=True, note=msg("compat_alr_note", ref=ref))
        derives = [{"name": c + SUFFIX[act], "expr": f"clr({c})", "eps": None,
                    "composition": list(comp), "result_type": "clr"} for c in comp]
        return Plan(act, derives, [(c, c + SUFFIX[act]) for c in comp],
                    needs_eps=True, note=msg("compat_clr_note", n=len(comp)))

    if act == FIX_LOGIT:
        derives = [{"name": c + SUFFIX[act], "expr": f"logit({c})", "eps": None,
                    "composition": None, "result_type": "log-scale"} for c in targets]
        return Plan(act, derives, [(c, c + SUFFIX[act]) for c in targets], needs_eps=True)

    if act == FIX_DIV100:
        derives = [{"name": c + SUFFIX[act], "expr": f"{c} / 100", "eps": None,
                    "composition": None, "result_type": "proportion"} for c in targets]
        return Plan(act, derives, [(c, c + SUFFIX[act]) for c in targets],
                    note=msg("compat_div100_note"))

    if act == FIX_UNIFY_SCALE:
        # 원척도 쪽을 log로 올린다 — 이미 log인 쪽을 되돌리면 정보가 사라진다
        derives = [{"name": c + SUFFIX[act], "expr": f"log2({c} + eps)", "eps": None,
                    "composition": None, "result_type": "log-scale"} for c in targets]
        return Plan(act, derives, [(c, c + SUFFIX[act]) for c in targets],
                    needs_eps=True, note=msg("compat_unify_note"))

    raise ValueError(msg("compat_no_auto_fix", id=finding.id))


def apply(doc: dict, source_id: str, df, p: Plan, eps: float | None = None) -> list[dict]:
    """계획을 세션에 기록한다 — 파생 op들과 지정 교체 op 1건.

    eps가 필요한 조치인데 값이 없으면 거부한다. 미리보기는 추천값으로 되지만
    기록에는 실제로 쓴 값이 남아야 한다 (derive와 같은 규칙).
    """
    from statop.derive.service import prepare
    from statop.messages import msg
    from statop.session.core import append_op, save_session

    if p.needs_composition:
        raise ValueError(msg("compat_need_composition"))
    if p.needs_eps and eps is None:
        raise ValueError(msg("eps_explicit_required"))

    entries = []
    for d in p.derives:
        if d["name"] in df.columns:
            raise ValueError(msg("derive_name_exists", name=d["name"]))
        # 커밋 전에 실제로 계산해 본다 — 여기서 터지면 기록을 남기지 않는다
        prep = prepare(df, d["expr"], eps=eps if d["expr"].find("eps") >= 0 or p.needs_eps
                       else None, composition=d["composition"])
        entries.append(append_op(doc, "derive", source=source_id, name=d["name"],
                                 expr=prep.parsed.expr, eps=eps,
                                 composition=d["composition"],
                                 result_type=d["result_type"], from_fix=p.action))
    entries.append(append_op(doc, "replace", source=source_id, action=p.action,
                             pairs=[list(x) for x in p.replaces]))
    save_session(doc)
    return entries
