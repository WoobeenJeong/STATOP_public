"""기계적 가설 생성 (A7 기본 경로, ) — LLM 없이 템플릿으로 만든다.

세션에 기록된 것(질문 설계·실행한 검정·타입·파생 이력·라벨 매핑)만 근거로
**1안/2안** 가설과 해석·방향·주의사항을 만든다. 기록에 없는 것은 말하지 않는다.

LLM(Qwen)은 이 결과가 마음에 안 들 때만 버튼으로 부른다 — 기본 경로가 아니다.
"""

from dataclasses import dataclass, field

from statop.messages import msg

# 효과크기 → 강도 표현 경계 (통용 기준: Cohen 1988 / rank-biserial·상관은 관례 경계)
_BANDS = {
    "Hedges g": [(0.2, "small"), (0.5, "medium"), (0.8, "large")],
    "dz": [(0.2, "small"), (0.5, "medium"), (0.8, "large")],
    "mean diff": None,                # 원단위 — 강도 표현 없이 수치로만
    "rank-biserial": [(0.1, "small"), (0.3, "medium"), (0.5, "large")],
    "P(X>Y)": None,
    "r": [(0.1, "small"), (0.3, "medium"), (0.5, "large")],
    "rho": [(0.1, "small"), (0.3, "medium"), (0.5, "large")],
    "tau": [(0.07, "small"), (0.21, "medium"), (0.35, "large")],
    "eta^2": [(0.01, "small"), (0.06, "medium"), (0.14, "large")],
    "epsilon^2": [(0.01, "small"), (0.06, "medium"), (0.14, "large")],
    "Cramér V": [(0.1, "small"), (0.3, "medium"), (0.5, "large")],
    "OR": None,
    # 일치도 계열은 Landis–Koch 관례 경계 — 상관 경계와 섞어 쓰면 안 된다
    "ICC(2,1)": [(0.4, "small"), (0.6, "medium"), (0.8, "large")],
    "CCC": [(0.4, "small"), (0.6, "medium"), (0.8, "large")],
    "kappa": [(0.2, "small"), (0.4, "medium"), (0.6, "large")],
    "Fleiss kappa": [(0.2, "small"), (0.4, "medium"), (0.6, "large")],
    "tau-b": [(0.07, "small"), (0.21, "medium"), (0.35, "large")],
    "rho_p": [(0.5, "small"), (0.8, "medium"), (0.95, "large")],
    # 원단위·비(ratio)는 경계가 없다 — 숫자로만 읽어야 한다
    "Sen slope": None, "slope": None, "bias": None, "IRR": None, "HR": None,
    "D": None, "energy distance": None, "proportion/score": None,
}

# 질문 유형 → 문장 틀. 회귀·추세를 "군 간 차이"로 쓰면 틀린 말이 된다
_FAMILY = {"Q-03": "assoc", "Q-05": "slope", "Q-08": "slope",
           "Q-06": "agree", "Q-07": "shape"}

# 1을 기준으로 읽는 비(ratio) 효과크기 — 0이 아니라 1이 "차이 없음"이다
_RATIO = {"OR", "IRR", "HR"}


@dataclass
class Hypothesis:
    title: str                        # 1안 / 2안 라벨
    statement: str                    # 가설 문장
    interpretation: str               # 해석 (효과 크기·방향)
    direction: str | None = None      # 어느 쪽이 큰가/양·음


@dataclass
class HypothesisReport:
    proposals: list[Hypothesis] = field(default_factory=list)   # 1안, 2안
    cautions: list[str] = field(default_factory=list)           # 주의사항
    companions: list[str] = field(default_factory=list)         # 보조지표 해석법
    guardrail: list[str] = field(default_factory=list)          # 가드레일 지표 해석
    basis: dict = field(default_factory=dict)                   # 근거 (검정 결과 요약)
    source: str = "mechanical"                                  # mechanical | qwen


def _effect_key(name: str | None) -> str:
    """'slope (age)' 처럼 컬럼 이름이 붙은 효과크기에서 종류만 떼어낸다."""
    return (name or "").split(" (")[0].strip()


def _magnitude(effect: dict) -> str | None:
    bands = _BANDS.get(_effect_key(effect.get("name")))
    if not bands or effect.get("value") is None:
        return None
    v = abs(float(effect["value"]))
    label = "negligible"
    for cut, name in bands:
        if v >= cut:
            label = name
    return label


def _context(session_file: str) -> dict:
    """가설의 재료 — 전부 세션 기록에서. 기록에 없는 것은 없는 것이다."""
    from statop.analyze.spec import current
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    st = replay(doc)
    sid = src["id"] if src else None
    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    results = [r for r in st["test_results"] if r.get("question") == spec.question
               and r.get("y") == spec.y and r.get("group") == spec.group]
    if not results:
        raise ValueError(msg("hypo_need_result"))
    return {
        "spec": spec,
        "result": results[-1],                     # 같은 설계의 마지막 실행
        "all_results": results,
        "types": st["semantic_types"].get(sid, {}),
        "derived": {d["name"]: d for d in st["derived"] if d.get("source") == sid},
        "label_map": st["label_maps"].get(sid, {}).get(spec.group)
        if spec.group else None,
    }


def _direction_text(spec, r: dict) -> tuple[str | None, str]:
    """방향 — 통계량 부호에서. 군 이름은 n dict 의 키 순서(= groupby 순서)를 쓴다."""
    eff = r.get("effect") or {}
    v = eff.get("value")
    if v is None:
        return None, ""
    groups = [k for k in (r.get("n") or {}) if k not in ("pairs", "groups", "total",
                                                        "table", "rows", "points",
                                                        "subjects", "raters",
                                                        "categories", "events",
                                                        "total_count")]
    key = _effect_key(eff.get("name"))
    if key in _RATIO:
        # 비는 1이 기준이다. 0과 비교하면 항상 "양의 방향"이 되어 늘 틀린다
        d = "positive" if v > 1 else "negative" if v < 1 else "none"
        return d, msg(f"hypo_dir_{d}", x=spec.group, y=spec.y)
    if spec.question in ("Q-03", "Q-05", "Q-08"):
        d = "positive" if v > 0 else "negative" if v < 0 else "none"
        return d, msg(f"hypo_dir_{d}", x=spec.group, y=spec.y)
    if len(groups) == 2 and eff.get("name") in ("Hedges g", "mean diff", "dz",
                                                "rank-biserial", "P(X>Y)"):
        base = 0.5 if eff.get("name") == "P(X>Y)" else 0.0
        hi, lo = (groups[0], groups[1]) if v > base else (groups[1], groups[0])
        if abs(v - base) < 1e-12:
            return "none", ""
        return "group", msg("hypo_dir_group", hi=hi, lo=lo, y=spec.y)
    return None, ""


def build_report(session_file: str) -> HypothesisReport:
    ctx = _context(session_file)
    spec, r = ctx["spec"], ctx["result"]
    eff = r.get("effect") or {}
    mag = _magnitude(eff)
    mag_txt = msg(f"hypo_mag_{mag}") if mag else ""
    sig = r.get("p") is not None and r["p"] < r.get("alpha_adjusted", 0.05)
    dir_code, dir_txt = _direction_text(spec, r)

    ci = ""
    if eff.get("ci_low") is not None:
        ci = msg("hypo_ci", lo=eff["ci_low"], hi=eff["ci_high"])
    common = dict(y=spec.y, x=spec.group, test=r["name"],
                  effect=eff.get("name", "?"), value=eff.get("value"),
                  p=r.get("p"), mag=mag_txt, ci=ci,
                  alpha=r.get("alpha_adjusted", 0.05))

    rep = HypothesisReport(basis={
        "test": r["test"], "name": r["name"], "p": r.get("p"),
        "statistic": r.get("statistic"),
        "effect": eff, "n": r.get("n"), "alpha_adjusted": r.get("alpha_adjusted"),
        "question": spec.question,
    })

    # ── 1안: 효과 중심(크기·CI), 2안: 방향·관측 중심 — 같은 결과의 두 서술이다
    key = _FAMILY.get(spec.question, "diff")
    sig_key = "sig" if sig else "ns"
    # 원단위·비는 통용 경계가 없다. 등급이 없으면 등급을 말하는 문장을 쓰면 안 된다
    interp_key = (f"hypo_p1_interp_{sig_key}" if mag or not sig
                  else "hypo_p1_interp_sig_nomag")
    # 문장에도 같은 규칙 — 등급 자리가 비면 "qc_score의  차이가 있다" 처럼 구멍이 남는다
    stmt_key = f"hypo_p1_{key}_{sig_key}"
    if not mag and sig and key in ("diff", "assoc", "agree"):
        stmt_key += "_nomag"
    rep.proposals.append(Hypothesis(
        title=msg("hypo_p1_title"),
        statement=msg(stmt_key, **common),
        interpretation=msg(interp_key, **common),
        direction=dir_txt or None))
    flips = strata_flips(r)
    if flips and dir_txt:
        # 전체 방향만 단언하면 보고서에 그대로 옮겨 적힌다. 문장 안에서 뒤집어 준다
        dir_txt = msg("hypo_dir_overall_only", dir=dir_txt,
                      by=r.get("by") or "?", levels=", ".join(flips))
    rep.proposals.append(Hypothesis(
        title=msg("hypo_p2_title"),
        statement=msg(f"hypo_p2_{key}_{sig_key}", **common,
                      dir=dir_txt or msg("hypo_dir_unknown")),
        interpretation=msg("hypo_p2_interp_simpson") if flips
        else msg(f"hypo_p2_interp_{key}", **common),
        direction=dir_txt or None))

    _add_cautions(rep, ctx)
    _add_companions(rep, ctx)
    _add_guardrail(rep, session_file)
    return rep


def strata_flips(r: dict) -> list[str]:
    """전체와 방향이 반대인 층. 검정 실행 때와 같은 기준(비는 1, 우위는 0.5)을 쓴다."""
    from statop.analyze.run import TestOutcome, _direction_flips

    strata = r.get("strata") or []
    if not strata:
        return []
    fake = TestOutcome(r.get("test", ""), r.get("name", ""), r.get("statistic"),
                       r.get("p"), effect=r.get("effect") or {})
    return _direction_flips(fake, strata)


def _add_cautions(rep: HypothesisReport, ctx: dict) -> None:
    """주의사항 — 변환 이력·타입·표본에서 기계적으로. 지어내지 않는다."""
    spec, r = ctx["spec"], ctx["result"]
    types, derived = ctx["types"], ctx["derived"]

    # 층마다 방향이 뒤집혔으면 전체값 문장 자체가 틀린 말이다 — 맨 앞에 둔다
    flips = strata_flips(r)
    if flips:
        rep.cautions.insert(0, msg("hypo_caution_simpson", by=r.get("by") or "?",
                                   levels=", ".join(flips)))

    for col in filter(None, (spec.y, spec.group)):
        t = types.get(col)
        d = derived.get(col)
        if t == "clr" or (d and d.get("result_type") == "clr"):
            # CLR 값의 상관·차이는 원척도 배수로 읽으면 안 된다
            rep.cautions.append(msg("hypo_caution_clr", col=col))
        elif t == "log-scale" or (d and d.get("result_type") == "log-scale"):
            rep.cautions.append(msg("hypo_caution_log", col=col,
                                    expr=(d or {}).get("expr", "log")))
        if d and d.get("eps") is not None:
            rep.cautions.append(msg("hypo_caution_eps", col=col, eps=d["eps"]))

    if ctx.get("label_map"):
        groups: dict[int, list[str]] = {}
        for v, c in ctx["label_map"].items():
            groups.setdefault(c, []).append(v)
        merged = {c: vs for c, vs in groups.items() if len(vs) > 1}
        if merged:
            detail = " · ".join(f"{c}={'+'.join(vs)}" for c, vs in merged.items())
            rep.cautions.append(msg("hypo_caution_merged", detail=detail))

    n = r.get("n") or {}
    sizes = [v for v in n.values() if isinstance(v, int)]
    if sizes and min(sizes) < 15:
        rep.cautions.append(msg("hypo_caution_small_n", n=min(sizes)))
    if r.get("alpha_adjusted", 0.05) < 0.05:
        rep.cautions.append(msg("hypo_caution_alpha",
                                adj=r["alpha_adjusted"], k=spec.n_tests))
    if spec.question == "Q-03":
        rep.cautions.append(msg("hypo_caution_causal"))


def _add_companions(rep: HypothesisReport, ctx: dict) -> None:
    """보조지표 해석법 — 주지표와 **무엇이 다르게 읽히는지**만 말한다."""
    r = ctx["result"]
    eff_name = (r.get("effect") or {}).get("name")
    if ctx["spec"].question == "Q-03":
        if eff_name == "r":
            rep.companions.append(msg("hypo_comp_r_vs_rho"))
        elif eff_name in ("rho", "tau"):
            rep.companions.append(msg("hypo_comp_rho_vs_r"))
        rep.companions.append(msg("hypo_comp_cosine"))
    else:
        if eff_name in ("Hedges g", "mean diff", "dz"):
            rep.companions.append(msg("hypo_comp_g_vs_rb"))
        elif eff_name in ("rank-biserial", "P(X>Y)"):
            rep.companions.append(msg("hypo_comp_rb_vs_g"))
    # 같은 설계로 함께 실행한 다른 검정 — 방향 일치 확인용 보조 (질문 유형 무관)
    others = [x for x in ctx["all_results"] if x["test"] != r["test"]]
    for o in others[-2:]:
        rep.companions.append(msg("hypo_comp_other_result", name=o["name"],
                                  effect=(o.get("effect") or {}).get("name", "?"),
                                  value=(o.get("effect") or {}).get("value")))


def _add_guardrail(rep: HypothesisReport, session_file: str) -> None:
    """가드레일 지표가 있으면 해석에 어떻게 얹어 읽을지 — 최근 리포트가 있을 때만."""
    try:
        from statop.analyze.spec import current
        from statop.derive.service import session_frame
        from statop.guard.pipeline import run
        from statop.session.core import replay

        spec = current(session_file)
        doc, src, df = session_frame(session_file, 10_000)
        st = replay(doc)
        types = st["semantic_types"].get(src["id"], {})
        grouping = {"label", "nominal code", "ordinal code"}
        gcol = spec.group if types.get(spec.group) in grouping else None
        g = run(df, types, group_col=gcol)
    except Exception:
        return
    for f in g.findings:
        if f.tier == "gate":
            rep.guardrail.append(msg("hypo_guard_gate", rule=f.rule, detail=f.detail))
        elif f.tier == "diagnostic" and f.rule in ("GR-02", "GR-04"):
            rep.guardrail.append(msg("hypo_guard_diag", rule=f.rule, detail=f.detail))
