"""S170 M3 보조 지표 자동 병기 제안 — Goal 옆에 Support·Guardrail 을 붙인다.

목표 지표(Goal) 하나만 보면 "얼마나"를 모르거나(Support 부재), 한쪽을 올리느라 다른 쪽이
무너지는 것을 놓친다(Guardrail 부재). 무엇을 병기할지는 `rules/metric_roles.yaml`
(MR-S/MR-G/MR-T)과 `rules/post.yaml`이 정한다 — 여기서 지어내지 않는다 (: base 고정).

**Support/Guardrail 이 없는 Goal 도 정상이다.** 짝을 강제하지 않고 "추천 없음"으로 둔다.
"""

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from statop.messages import msg

ROLE_SUPPORT = "support"
ROLE_GUARDRAIL = "guardrail"


@dataclass
class Suggestion:
    """병기 제안 1건. 계산까지 되는 것과 '확인만' 하는 것을 구분한다."""

    id: str                               # MR-S14 / P-203 / U-xxxx …
    role: str                             # support | guardrail
    name: str
    why: str = ""
    computable: bool = False              # 여기서 값을 낼 수 있는가
    chosen: bool = False                  #  사용자가 보고서에 넣기로 고른 항목
    source: str = "base"                  # base(규칙표) | user(직접 더한 것)
    value: dict | None = None             # {lines: [...]} — 계산 결과
    error: str = ""


@dataclass
class Panel:
    goal: dict = field(default_factory=dict)          # 지금 본 지표 (검정 결과)
    support: list = field(default_factory=list)
    guardrail: list = field(default_factory=list)
    triad: dict | None = None                         # 상황이 맞는 3종 세트 (MR-T)


@lru_cache(maxsize=1)
def _roles() -> dict:
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "metric_roles.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _post() -> list[dict]:
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "post.yaml").read_text(encoding="utf-8"))


def _post_by_id(pid: str) -> dict:
    return next((p for p in _post() if p["id"] == pid), {})


# 어떤 상황에 어떤 관계를 거는가. 판단 재료는 세션에 기록된 사실뿐이다 —
# 검정 ID·효과크기 이름·질문 유형·의미 타입·제외 여부.
def _situation(session_file: str) -> dict:
    from statop.analyze.points import status as exclude_status
    from statop.analyze.spec import current
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    st = replay(doc)
    results = [r for r in st["test_results"] if r.get("source") in (None, src["id"])]
    spec = current(session_file)
    types = st["semantic_types"].get(src["id"], {})
    last = results[-1] if results else None
    eff = (last or {}).get("effect") or {}
    # : 사용자가 Goal 을 직접 지정했으면 그것이 기준이다. 안 했으면 마지막 검정
    goal = st.get("metric_goal")
    return {
        "spec": spec, "result": last, "types": types, "goal": goal,
        "effect_key": (goal or {}).get("effect_key")
        or str(eff.get("name", "")).split(" (")[0].strip(),
        "test": (goal or {}).get("test") or (last or {}).get("test", ""),
        "n_groups": len((last or {}).get("n") or {}),
        "excluded": exclude_status(session_file).n_excluded,
        "session": session_file,
    }


# 관계 → 언제 거는가. 각 조건은 "세션이 말해주는 사실"만 본다.
_SUPPORT_WHEN = {
    "MR-S15": lambda s: s["effect_key"] in ("Hedges g", "dz", "mean diff"),
    "MR-S14": lambda s: s["effect_key"] in ("eta^2", "epsilon^2", "partial eta^2",
                                            "partial eta^2 (rank)"),
    "MR-S05": lambda s: _has_type(s, ("clr", "log-scale")),
    "MR-S10": lambda s: s["effect_key"] in ("dCor", "energy distance"),
    "MR-S08": lambda s: s["test"] in ("T-901", "T-902", "T-904", "T-807"),
    "MR-S18": lambda s: s["test"] == "T-805",
    "MR-S11": lambda s: _has_type(s, ("proportion",)) and s["test"].startswith("T-100"),
    # 비율끼리 상관(S-R01)은 조성 제약 때문에 음의 편향이 낀다. 원값 상관을 그대로
    # 쓰지 말고 **CLR·ALR 로 옮긴 뒤 구한 상관**을 보조로 함께 본다
    "MR-S01c": lambda s: _is_ratio_correlation(s),
}


def _is_ratio_correlation(s: dict) -> bool:
    spec = s["spec"]
    if spec is None or not spec.group:
        return False
    if s["effect_key"] not in ("r", "rho", "tau", "tau-b", "bicor", "dCor"):
        return False
    both = [s["types"].get(c) for c in (spec.y, spec.group)]
    return all(t in ("proportion", "percent", "probability") for t in both)
_GUARDRAIL_WHEN = {
    "MR-G14": lambda s: s["excluded"] > 0,
    "MR-G06": lambda s: bool(s["spec"]) and s["spec"].n_tests > 1,
    "MR-G16": lambda s: _has_type(s, ("proportion", "clr")),
    "MR-G17": lambda s: s["test"] in ("T-901", "T-902", "T-903", "T-904", "T-807"),
    "MR-G01": lambda s: s["effect_key"] in ("OR", "Cramér V"),
    "MR-G11": lambda s: s["test"] in ("T-802", "T-806", "T-803", "T-801", "T-804"),
}
_TRIAD_WHEN = {
    "MR-T11": lambda s: s["test"].startswith("T-11"),
    "MR-T12": lambda s: s["test"] in ("T-601", "T-602", "T-603"),
    "MR-T03": lambda s: s["test"] in ("T-901", "T-902", "T-903", "T-904"),
    "MR-T06": lambda s: s["test"] in ("T-1001", "T-1002", "T-1003", "T-1004"),
}


def _has_type(s: dict, kinds: tuple[str, ...]) -> bool:
    spec = s["spec"]
    if spec is None:
        return False
    return any(s["types"].get(c) in kinds for c in (spec.y, spec.group) if c)


def suggest(session_file: str, sample_n: int = 10_000) -> Panel:
    """지금 본 지표 옆에 병기할 것을 고른다. 없으면 없다고 둔다 — 짝을 강제하지 않는다."""
    s = _situation(session_file)
    if s["result"] is None and s["goal"] is None:
        raise ValueError(msg("metrics_need_result"))

    r = s["result"] or {}
    eff = r.get("effect") or {}
    g = s["goal"] or {}
    # 점수를 Goal 로 지정했는데 마지막 검정의 효과크기를 그 값인 양 붙이면 거짓말이 된다.
    # 지정한 지표로 아직 계산한 값이 없으면 값 자리를 비운다
    own_value = not g.get("score")
    panel = Panel(goal={"test": s["test"], "name": g.get("name") or r.get("name"),
                        "effect": g.get("effect_key")
                        or (eff.get("name") if own_value else None),
                        "value": eff.get("value") if own_value else None,
                        "p": r.get("p") if own_value else None,
                        "score": g.get("score"), "chosen": bool(g),
                        "measured_by": r.get("name") if g.get("score") else None})

    rel = _roles()
    # 규칙표에 없는 조합은 만들지 않는다 — 다만 S-R01(조성 상관)이 걸리는 자리는
    # 이미 규칙이 "CLR/ALR 로 옮겨서 보라"고 말하고 있으므로, 그 변환 상관을 보조로 올린다
    rel = {**rel, "support_relations": [
        *rel["support_relations"],
        {"id": "MR-S01c", "goal": msg("metrics_ratio_corr_goal"),
         "support": msg("metrics_ratio_corr_support"),
         "why": msg("metrics_ratio_corr_why")},
    ]}
    for src_list, when, role, key in (
            (rel["support_relations"], _SUPPORT_WHEN, ROLE_SUPPORT, "support"),
            (rel["guardrail_relations"], _GUARDRAIL_WHEN, ROLE_GUARDRAIL, "guardrail")):
        for item in src_list:
            cond = when.get(item["id"])
            if cond is None or not cond(s):
                continue
            sug = Suggestion(id=item["id"], role=role, name=str(item[key]),
                             why=str(item.get("why") or item.get("tradeoff") or ""))
            sug.computable = item["id"] in COMPUTE
            getattr(panel, role).append(sug)

    # P-203 은 registry 가 "Support metric 기본값"이라고 못박은 항목이다 — 항상 올린다.
    # 다만 **차이를 재는 자리에서만** 뜻이 있다. 상관 질문에 "원척도 차이"를 올리면
    # 무엇을 빼라는 말인지 알 수 없다
    is_difference = s["spec"] is not None and s["spec"].question not in ("Q-03",)
    if is_difference and not any("P-203" in x.name or x.id == "P-203"
                                 for x in panel.support):
        p203 = _post_by_id("P-203")
        panel.support.insert(0, Suggestion(
            id="P-203", role=ROLE_SUPPORT, name=p203.get("name", ""),
            why=msg("metrics_p203_why"), computable=True))

    # 모듈 B 가 지름길 학습 위험을 찾았으면 **여기 Guardrail 로 올린다** (MB-C08).
    # 감사 화면에만 두면 지표를 고르는 자리에서는 보이지 않는다 — 정작 그때 필요한 정보다.
    # 지어낸 id 가 아니라 규칙표에 있는 MB-C08 을 그대로 쓴다
    cols = _shortcut_columns(session_file, sample_n)
    if cols:
        panel.guardrail.insert(0, Suggestion(
            id="MB-C08", role=ROLE_GUARDRAIL,
            name=msg("metrics_shortcut_guard", cols=", ".join(cols)),
            why=msg("metrics_shortcut_why")))

    for t in rel["triads"]:
        if _TRIAD_WHEN.get(t["id"], lambda _s: False)(s):
            panel.triad = dict(t)
            break
    return panel


def _shortcut_columns(session_file: str, sample_n: int) -> list[str]:
    """라벨과 분포가 다른 메타 컬럼 (MB-C08). 모델 구성이 없으면 볼 것이 없다.

    메타는 hold 한 컬럼이다 (요구사항) — 분석에서 뺐지만 라벨을 예측하면 문제가 된다.
    라벨 컬럼만 읽으므로 가볍다.
    """
    from statop.modeling.spec import current as model_current
    from statop.session.core import load_session, main_source, replay

    spec = model_current(session_file)
    if spec is None or not spec.sets:
        return []
    doc = load_session(session_file)
    src = main_source(doc)
    held = replay(doc)["held"].get(src["id"] if src else "", [])
    if not held:
        return []
    from statop.modeling.balance import hidden_imbalance

    try:
        f = hidden_imbalance(spec, held, sample_n)
    except (ValueError, OSError, KeyError):
        return []
    return list(f.numbers) if f.verdict == "fail" else []


def compute(session_file: str, suggestion_id: str, sample_n: int = 10_000) -> dict:
    """제안 하나를 실제로 계산한다 — '아래에 이어서 확인'하는 부분 (사용자 요청)."""
    fn = COMPUTE.get(suggestion_id)
    if fn is None:
        raise ValueError(msg("metrics_not_computable", id=suggestion_id))
    return fn(_frame(session_file, sample_n))


@dataclass
class Ctx:
    session: str
    spec: object
    df: pd.DataFrame
    types: dict
    result: dict


def _frame(session_file: str, sample_n: int) -> Ctx:
    from statop.analyze.spec import current
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import load_session, main_source, replay

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    doc, src, df = session_frame(session_file, sample_n)
    st = replay(doc)
    results = [r for r in st["test_results"] if r.get("source") in (None, src["id"])]
    return Ctx(session=session_file, spec=spec,
               df=apply_ops(df, doc, src["id"]),
               types=st["semantic_types"].get(src["id"], {}),
               result=results[-1] if results else {})


def _groups(c: Ctx) -> list[tuple[str, np.ndarray]]:
    if not c.spec.group:
        return []
    sub = c.df[[c.spec.y, c.spec.group]].dropna()
    y = pd.to_numeric(sub[c.spec.y], errors="coerce")
    sub = sub[y.notna()]
    return [(str(g), pd.to_numeric(d[c.spec.y], errors="coerce").dropna()
             .to_numpy("float64"))
            for g, d in sub.groupby(c.spec.group, observed=True)]


def _raw_difference(c: Ctx) -> dict:
    """P-203 / MR-S15 — 원척도 차이 + CI. 표준화 값은 '몇 배'인지 알려주지 않는다."""
    from scipy import stats

    parts = _groups(c)
    if len(parts) < 2:
        raise ValueError(msg("run_need_two_groups", n=len(parts)))
    lines = [msg("metrics_group_mean", level=g, mean=float(a.mean()),
                 sd=float(a.std(ddof=1)), n=int(a.size)) for g, a in parts]
    if len(parts) == 2:
        (ga, a), (gb, b) = parts
        diff = float(a.mean() - b.mean())
        se = float(np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size))
        dof = (a.var(ddof=1) / a.size + b.var(ddof=1) / b.size) ** 2 / (
            (a.var(ddof=1) / a.size) ** 2 / (a.size - 1)
            + (b.var(ddof=1) / b.size) ** 2 / (b.size - 1))
        t = float(stats.t.ppf(0.975, dof))
        lines.append(msg("metrics_raw_diff", a=ga, b=gb, diff=diff,
                         lo=diff - t * se, hi=diff + t * se, unit=c.spec.y))
    return {"lines": lines}


def _group_means(c: Ctx) -> dict:
    """MR-S14 — η² 는 '전체의 몇 %'만 말한다. 어느 군이 어디 있는지는 원값이 말한다."""
    from scipy import stats

    parts = _groups(c)
    if not parts:
        raise ValueError(msg("run_need_two_groups", n=0))
    lines = []
    for g, a in parts:
        se = float(a.std(ddof=1) / np.sqrt(a.size)) if a.size > 1 else 0.0
        t = float(stats.t.ppf(0.975, max(1, a.size - 1)))
        lines.append(msg("metrics_group_ci", level=g, mean=float(a.mean()),
                         lo=float(a.mean() - t * se), hi=float(a.mean() + t * se),
                         n=int(a.size)))
    return {"lines": lines}


def _multiplicity(c: Ctx) -> dict:
    """MR-G06 — 검정을 늘리면 1종 오류가 늘어난다. 보정 전/후를 함께 본다 (P-225)."""
    from statop.analyze.checks import multiplicity

    m = multiplicity(c.spec.n_tests)
    adj, alpha = m.numbers["alpha_adjusted"], m.numbers["alpha"]
    # 보정을 안 하면 검정 n개 중 최소 하나가 우연히 유의할 확률 — 1-(1-α)^n
    family = 1 - (1 - alpha) ** c.spec.n_tests
    lines = [msg("metrics_alpha", n=c.spec.n_tests, adj=adj, any_err=family)]

    p = c.result.get("p")
    if p is None:
        return {"lines": lines}
    before, after = p < alpha, p < adj
    lines.append(msg("metrics_alpha_verdict", p=p,
                     before=msg("metrics_sig") if before else msg("metrics_ns"),
                     after=msg("metrics_sig") if after else msg("metrics_ns")))
    if before != after:
        lines.append(msg("metrics_alpha_flipped"))
    return {"lines": lines}


def _exclusion_cost(c: Ctx) -> dict:
    """MR-G14 — 이상치를 뺄수록 결과는 깨끗해진다. 얼마나 뺐는지가 가드레일이다."""
    from statop.analyze.points import status

    st = status(c.session)
    lines = [msg("metrics_excluded", n=st.n_excluded, total=st.n_total,
                 ratio=st.ratio, left=st.n_total - st.n_excluded)]
    if st.verdict == "red":
        lines.append(msg("points_excl_red", n=st.n_excluded, total=st.n_total,
                         ratio=st.ratio))
    return {"lines": lines}


def _composition_tradeoff(c: Ctx) -> dict:
    """MR-G16 — 조성은 합이 1이다. 한 성분이 오르면 다른 성분은 **반드시** 내린다."""
    from statop.semantic import composition_set

    members = sorted(composition_set(c.df, c.spec.y) & set(c.df.columns))
    if len(members) < 2:
        raise ValueError(msg("run_need_composition", col=c.spec.y))
    parts = _groups(c)
    if len(parts) != 2:
        raise ValueError(msg("run_need_two_groups", n=len(parts)))
    ga, gb = parts[0][0], parts[1][0]
    sub = c.df[[*members, c.spec.group]].dropna()
    a = sub[sub[c.spec.group].astype(str) == ga][members].mean()
    b = sub[sub[c.spec.group].astype(str) == gb][members].mean()
    lines = [msg("metrics_comp_head", n=len(members), a=ga, b=gb)]
    lines += [msg("metrics_comp_row", col=col, a=float(a[col]), b=float(b[col]),
                  d=float(a[col] - b[col])) for col in members]
    lines.append(msg("metrics_comp_sum", total=float((a - b).sum())))
    return {"lines": lines}


def _followup_loss(c: Ctx) -> dict:
    """MR-G17 — 생존에서 HR 이 좋아 보여도 추적이 끊긴 비율이 크면 못 믿는다."""
    ev = getattr(c.spec, "event", None)
    if not ev or ev not in c.df.columns:
        return {"lines": [msg("metrics_no_event_col")]}
    raw = pd.to_numeric(c.df[ev], errors="coerce").dropna()
    events = float((raw > 0).sum())
    lines = [msg("metrics_censor", events=int(events),
                 censored=int(len(raw) - events), ratio=1 - events / max(1, len(raw)))]
    if c.spec.group:
        sub = c.df[[ev, c.spec.group]].dropna()
        val = pd.to_numeric(sub[ev], errors="coerce")
        for g, d in sub.assign(_e=val).groupby(c.spec.group, observed=True):
            lines.append(msg("metrics_censor_group", level=str(g),
                             ratio=float((d["_e"] <= 0).mean()), n=int(len(d))))
    return {"lines": lines}


def _omnibus(c: Ctx) -> dict:
    """MR-T11 — 사전지정 대비가 유의해도, 전체차(omnibus)가 없으면 해석이 달라진다."""
    from statop.analyze.run import run_test

    out = run_test(c.session, "T-121", use_exclusions=True, record=False)
    return {"lines": [msg("metrics_omnibus", name=out.name, stat=out.statistic or 0.0,
                          p=out.p if out.p is not None else float("nan"),
                          eff=(out.effect or {}).get("name", "?"),
                          val=(out.effect or {}).get("value", 0.0))]}


def _raw_scale(c: Ctx) -> dict:
    """MR-S05 — CLR·log 값의 차이는 배수가 아니다. 원척도 값을 함께 본다."""
    parts = _groups(c)
    src = c.spec.y
    lines = [msg("metrics_transformed_note", col=src)]
    for g, a in parts:
        lines.append(msg("metrics_group_mean", level=g, mean=float(a.mean()),
                         sd=float(a.std(ddof=1)), n=int(a.size)))
    return {"lines": lines}


def set_goal(session_file: str, score: str | None = None, test: str | None = None,
             effect_key: str | None = None, name: str | None = None) -> dict:
    """S171 Goal 지정 — 무엇을 주 지표로 볼지는 사용자가 정한다 (사용자③ 우선).

    지정하지 않으면 마지막에 실행한 검정이 Goal 이다. base 관계표는 건드리지 않는다.
    """
    from statop.session.core import append_op, load_session, main_source, save_session

    if not any((score, test, effect_key)):
        raise ValueError(msg("metrics_goal_need_one"))
    if score:
        from statop.analyze.scores import _db

        known = {x["id"] for x in _db()["scores"]}
        if score not in known:
            raise ValueError(msg("metrics_goal_unknown_score", id=score))
        name = name or next(x["name"] for x in _db()["scores"] if x["id"] == score)
    doc = load_session(session_file)
    src = main_source(doc)
    entry = append_op(doc, "metric_goal", source=src["id"], score=score, test=test,
                      effect_key=effect_key, name=name)
    save_session(doc)
    return entry


def _transformed_correlation(c: Ctx) -> dict:
    """MR-S01c — 조성 제약을 푼 뒤의 상관. 원값 상관과 나란히 보여야 편향이 보인다.

    CLR(세트 전체 기하평균 기준)과 ALR(기준 성분 대비) 둘 다 낸다 — 기준을 바꾸면
    값이 달라지므로 한쪽만 보면 그 값이 유일한 답인 줄 안다.
    """
    import numpy as np
    from scipy import stats

    from statop.semantic import composition_set

    y, x = c.spec.y, c.spec.group
    sub = c.df[[y, x]].apply(pd.to_numeric, errors="coerce").dropna()
    raw = float(stats.pearsonr(sub[y], sub[x]).statistic)
    lines = [msg("metrics_corr_raw", a=y, b=x, r=raw)]

    members = sorted(composition_set(c.df, y) & set(c.df.columns))
    if len(members) < 2 or x not in members:
        lines.append(msg("metrics_corr_no_set", col=y))
        return {"lines": lines}

    m = c.df[members].apply(pd.to_numeric, errors="coerce")
    keep = m.notna().all(axis=1) & (m > 0).all(axis=1)
    dropped = int((~keep).sum())
    m = m[keep]
    if len(m) < 3:
        lines.append(msg("run_need_positive", n=len(m)))
        return {"lines": lines}

    lg = np.log(m)
    clr = lg.sub(lg.mean(axis=1), axis=0)
    r_clr = float(stats.pearsonr(clr[y], clr[x]).statistic)
    lines.append(msg("metrics_corr_clr", r=r_clr, n=len(members),
                     cols=", ".join(members)))

    others = [col for col in members if col not in (y, x)]
    if others:
        ref = min(others, key=lambda col: float(np.log(m[col]).var(ddof=1)))
        alr_y, alr_x = np.log(m[y] / m[ref]), np.log(m[x] / m[ref])
        lines.append(msg("metrics_corr_alr",
                         r=float(stats.pearsonr(alr_y, alr_x).statistic), ref=ref))
    else:
        lines.append(msg("metrics_corr_alr_need_third"))
    # 조성에서 "같이 움직이는가"의 표준 답은 비례성(T-321)이다 — 상관 셋과 나란히 둔다
    lr = np.log(m[y] / m[x])
    vr = float(lr.var(ddof=1))
    vy = float(np.log(m[y]).var(ddof=1))
    vx = float(np.log(m[x]).var(ddof=1))
    rho_p = 1 - vr / (vy + vx) if (vy + vx) > 0 else 0.0
    lines.append(msg("metrics_corr_prop", rho=rho_p,
                     phi=vr / vy if vy > 0 else 0.0))
    if dropped:
        lines.append(msg("run_note_dropped_nonpositive", n=dropped))
    lines.append(msg("metrics_corr_read"))
    return {"lines": lines}


COMPUTE = {
    "MR-S01c": _transformed_correlation,
    "P-203": _raw_difference,
    "MR-S15": _raw_difference,
    "MR-S14": _group_means,
    "MR-S05": _raw_scale,
    "MR-G06": _multiplicity,
    "MR-G14": _exclusion_cost,
    "MR-G16": _composition_tradeoff,
    "MR-G17": _followup_loss,
    "MR-T11": _omnibus,
}


# ──  사용자 선택 저장 (metric_roles.json) ───────────────
# ** 경계**: 점수 정의와 Goal↔Support/Guardrail **관계 자체는 base 고정**이다.
# 여기 저장하는 것은 "base 가 제안한 것 중 무엇을 내 보고서에 넣기로 했는가"라는 **선택**뿐이다.
# 새 관계를 만들지 않는다 — 무엇으로 재는지가 흔들리면 검증이 성립하지 않는다.
ROLES_FILE = "metric_roles.json"


def roles_path(path=None):  # noqa: ANN001, ANN201
    from pathlib import Path

    from statop.store import user_dir

    return Path(path) if path else user_dir() / ROLES_FILE


def goal_key(panel: Panel) -> str:
    """선택을 어느 Goal 에 매달 것인가 — 점수 ID 가 있으면 그것, 없으면 검정 ID."""
    g = panel.goal
    return str(g.get("score") or g.get("test") or g.get("effect") or "?")


def load_choices(path=None) -> dict:  # noqa: ANN001
    import json

    p = roles_path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ── 사용자가 직접 더하는 추천  ───────────────────────
# **base 관계는 그대로 둔다** . 사용자가 더한 것은 `custom` 에 따로 쌓고
# 화면에서 "사용자 지정"으로 표시한다 — 규칙표에서 온 것과 섞이지 않는다.
CUSTOM = "custom"
USER_PREFIX = "U-"


def add_custom(key: str, role: str, name: str, why: str = "",
               path=None) -> dict:  # noqa: ANN001
    """이 Goal 에서 함께 볼 것을 **직접** 더한다 — 다음에도 추천으로 뜬다."""
    import json
    import uuid

    if role not in ("support", "guardrail"):
        raise ValueError(msg("metrics_custom_bad_role"))
    if not (name or "").strip():
        raise ValueError(msg("metrics_custom_need_name"))
    items = load_choices(path)
    box = items.setdefault(CUSTOM, {}).setdefault(key, {"support": [], "guardrail": []})
    entry = {"id": f"{USER_PREFIX}{uuid.uuid4().hex[:6]}", "name": name.strip(),
             "why": (why or "").strip()}
    box[role].append(entry)
    _write(items, path)
    return entry


def remove_custom(key: str, item_id: str, path=None) -> bool:  # noqa: ANN001
    items = load_choices(path)
    box = items.get(CUSTOM, {}).get(key)
    if not box:
        return False
    hit = False
    for role in ("support", "guardrail"):
        before = len(box[role])
        box[role] = [x for x in box[role] if x["id"] != item_id]
        hit = hit or len(box[role]) != before
    if hit:
        _write(items, path)
    return hit


def custom_for(key: str, path=None) -> dict:  # noqa: ANN001
    box = load_choices(path).get(CUSTOM, {}).get(key)
    return box or {"support": [], "guardrail": []}


def _write(items: dict, path=None) -> None:  # noqa: ANN001
    import json

    p = roles_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def save_choice(key: str, support: list[str], guardrail: list[str],
                note: str = "", path=None) -> dict:  # noqa: ANN001
    """이 Goal 에 대해 **base 관계 중** 어떤 것을 함께 보고할지 저장한다.

    base 에 없는 id 는 받지 않는다 — 여기서 새 관계를 만들 수 있으면 이 깨진다.
    """
    import json

    rel = _roles()
    known = {r["id"] for r in rel["support_relations"] + rel["guardrail_relations"]}
    known.add("P-203")
    # 내가 더한 것도 고를 수 있다 — 다만 base 관계는 그대로다 (출처가 갈려 있다)
    mine = custom_for(key, path)
    known |= {x["id"] for x in mine["support"] + mine["guardrail"]}
    bad = [i for i in (*support, *guardrail) if i not in known]
    if bad:
        raise ValueError(msg("metrics_roles_unknown", ids=", ".join(bad)))

    items = load_choices(path)
    items[key] = {"support": list(support), "guardrail": list(guardrail),
                  "note": note.strip()}
    _write(items, path)
    return items[key]


def with_custom(panel: Panel, path=None) -> Panel:  # noqa: ANN001
    """내가 더한 추천을 뒤에 붙인다 — **출처가 보이게** (base 와 섞지 않는다)."""
    mine = custom_for(goal_key(panel), path)
    for role in ("support", "guardrail"):
        for x in mine[role]:
            getattr(panel, role).append(
                Suggestion(id=x["id"], role=role, name=x["name"], why=x.get("why", ""),
                           source="user"))
    return panel


def apply_choices(panel: Panel, path=None) -> Panel:  # noqa: ANN001
    """저장해 둔 선택을 표시에 반영 — 고른 것을 위로 올린다. 없앤 것은 없앤 채 두지 않는다."""
    chosen = load_choices(path).get(goal_key(panel))
    if not chosen:
        return panel
    for role in ("support", "guardrail"):
        picked = set(chosen.get(role, []))
        items = getattr(panel, role)
        for s in items:
            s.chosen = s.id in picked
        items.sort(key=lambda s: (not s.chosen, s.id))
    return panel
