"""모듈 A 앞단 (A1 질문 설계 · A2 3색 후보) 회귀.

후보 엔진은 두 방향을 다 본다: 맞는 검정이 뜨는지 **그리고** 안 맞는 검정이
목록에서 빠지거나 red 로 표시되는지. 한쪽만 보면 "전부 후보"가 통과한다.
"""

import os
import pathlib

import numpy as np
import pandas as pd
import pytest

from statop.analyze.candidates import shortlist
from statop.analyze.spec import Spec, build, current, question_ids, record, validate


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(7)
    n = 400
    df = pd.DataFrame({
        "arm": rng.choice(["control", "case"], n),
        "site": rng.choice(["A", "B", "C"], n),
        "vaf": np.clip(rng.beta(2, 8, n), 0, 1),
        "age": rng.normal(60, 12, n),
        "stage": rng.integers(1, 5, n),
    })
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    return str(sc.session_file)


def _confirm(session, **types):
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session)
    src = main_source(doc)
    for col, typ in types.items():
        append_op(doc, "semantic_confirm", source=src["id"], column=col, type=typ)
    save_session(doc)


# ── A1 스펙 검증 ─────────────────────────────────────────────
def test_spec_validates_before_touching_data():
    errs = validate(Spec(question="Q-99", y="y", group="y", direction="up",
                         contrast="vs-control", n_tests=0), ["y"])
    text = " ".join(errs)
    assert "Q-99" in text and "같은 컬럼" in text and "two-sided" in text
    assert "기준 수준" in text and "1 이상" in text
    assert len(question_ids()) == 12   # Q-12 표본 크기·대표성 추가


def test_build_defers_until_types_confirmed(session):
    res = build(session, Spec(question="Q-01", y="vaf", group="arm"))
    assert any("미확정" in p for p in res.problems)


def test_build_uses_label_mapping_for_groups(session):
    """3수준을 2군으로 묶었으면 군 구성도 2군으로 보여야 한다 ()."""
    from statop.session.core import append_op, load_session, main_source, save_session

    _confirm(session, vaf="proportion", site="label")
    doc = load_session(session)
    src = main_source(doc)
    append_op(doc, "label_map", source=src["id"], column="site",
              mapping={"A": 0, "B": 1, "C": 1})
    save_session(doc)

    res = build(session, Spec(question="Q-01", y="vaf", group="site"))
    assert set(res.group_levels) == {"0", "1"}


def test_build_runs_compat_automatically(session):
    """S141 — 대상 컬럼 지정 = 적합성 자동 판정. id 를 group 에 넣으면 gate."""
    _confirm(session, vaf="proportion", arm="id")
    res = build(session, Spec(question="Q-01", y="vaf", group="arm"))
    assert res.compat["verdict"] == "gate"
    assert any("차단" in p for p in res.problems)


def test_build_warns_on_continuous_group(session):
    _confirm(session, vaf="proportion", age="label")   # 연속인데 label 로 확정한 상황
    res = build(session, Spec(question="Q-01", y="vaf", group="age"))
    assert any("수준이" in p and "Q-03" in p for p in res.problems)


def test_record_and_current_roundtrip(session):
    _confirm(session, vaf="proportion", arm="label")
    spec = Spec(question="Q-01", y="vaf", group="arm", n_tests=3)
    record(session, spec)
    got = current(session)
    assert got == spec

    record(session, Spec(question="Q-03", y="vaf", group="arm"))
    assert current(session).question == "Q-03"       # 마지막 것이 이긴다


# ── A2 후보 엔진 ─────────────────────────────────────────────
def test_two_group_difference_candidates(session):
    _confirm(session, vaf="proportion", arm="label")
    res = build(session, Spec(question="Q-01", y="vaf", group="arm"))
    cands = shortlist(res)
    ids = {c.id for c in cands}
    assert {"T-101", "T-103"} <= ids                  # Welch t, MWU 는 반드시 후보
    # ≥3군 전용(ANOVA 계열)은 2군 질문에 나오면 안 된다
    assert not any(c.design.startswith("≥3") for c in cands)
    # 짝지음 전용도 빠진다
    assert not any("대응" in c.design for c in cands)


def test_paired_flag_switches_the_design(session):
    _confirm(session, vaf="proportion", arm="label")
    res = build(session, Spec(question="Q-01", y="vaf", group="arm", paired=True))
    cands = shortlist(res)
    assert cands and all("대응" in c.design or "반복" in c.design for c in cands)


def test_assumption_bearing_tests_are_yellow_until_a3(session):
    """가정(C-xx)이 필요한 검정은 A3 전에는 초록이라 말하지 않는다."""
    _confirm(session, vaf="proportion", arm="label")
    res = build(session, Spec(question="Q-01", y="vaf", group="arm"))
    by = {c.id: c for c in shortlist(res)}
    assert by["T-101"].color == "yellow"
    assert any("C-01" in r for r in by["T-101"].reasons)
    # 가정 없는 검정(Brunner–Munzel)은 초록
    assert by["T-104"].color == "green"


def test_rank_outcome_blocks_continuous_tests(session):
    """순위 y 에 t-test — red 로 보여주고 이유와 대안을 단다."""
    _confirm(session, stage="ordinal code", arm="label")
    res = build(session, Spec(question="Q-01", y="stage", group="arm"))
    by = {c.id: c for c in shortlist(res)}
    assert by["T-101"].color == "red"
    assert any("ordinal" in r or "순위" in r for r in by["T-101"].reasons)
    assert by["T-103"].color != "red"                 # MWU 는 순위에 쓸 수 있다


def test_small_groups_turn_candidates_yellow(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "h2"))
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"arm": ["a"] * 8 + ["b"] * 8,
                       "y": rng.normal(0, 1, 16)})
    p = tmp_path / "s.csv"
    df.to_csv(p, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    _confirm(str(sc.session_file), y="continuous", arm="label")
    res = build(str(sc.session_file), Spec(question="Q-01", y="y", group="arm"))
    by = {c.id: c for c in shortlist(res)}
    # Welch t 의 caution: 소표본(n<15) — n=8 이므로 노랑 + 수치가 사유에
    assert by["T-101"].color == "yellow"
    assert any("n=8" in r for r in by["T-101"].reasons)


def test_association_question_uses_correlation_tests(session):
    _confirm(session, vaf="proportion", age="continuous")
    res = build(session, Spec(question="Q-03", y="age", group="vaf"))
    ids = {c.id for c in shortlist(res)}
    assert "T-302" in ids                              # Spearman
    assert not any(i.startswith("T-1") for i in ids)   # 차이 검정은 안 나온다
    assert res.group_levels == {}                      # 연속 x 를 군으로 세지 않는다


def test_candidates_sorted_green_first(session):
    _confirm(session, vaf="proportion", arm="label")
    res = build(session, Spec(question="Q-01", y="vaf", group="arm"))
    colors = [c.color for c in shortlist(res)]
    order = {"green": 0, "yellow": 1, "red": 2}
    assert colors == sorted(colors, key=lambda c: order[c])


# ── A3 가정 검사 (~) ─────────────────────────────────
from statop.analyze.checks import (collinearity, equal_variance, independence,
                                 multiplicity, normality, power_check, run_checks)


def test_normality_ok_on_normal_data():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"g": ["a"] * 40 + ["b"] * 40, "y": rng.normal(0, 1, 80)})
    r = normality(df, "y", "g")
    assert r.verdict == "ok" and all(g["method"] == "shapiro" for g in r.per_group)
    assert r.plot["a"]["theoretical"]                  # QQ 재료가 있다


def test_normality_blames_outliers_when_they_are_the_cause():
    rng = np.random.default_rng(2)
    y = rng.normal(0, 1, 45)
    y[:2] = [9.0, -8.5]                                # 소수 outlier
    df = pd.DataFrame({"g": ["a"] * 45, "y": y})
    r = normality(df, "y", "g")
    assert r.verdict == "violated" and r.cause == "outliers"
    assert "outlier" in r.summary


def test_normality_blames_skew():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"g": ["a"] * 60, "y": rng.lognormal(0, 1, 60)})
    r = normality(df, "y", "g")
    assert r.verdict == "violated" and r.cause == "skew"


def test_normality_large_n_uses_skew_not_p():
    """n>300 에서 p 는 무의미 (C-01) — 검정 대신 왜도로 본다."""
    rng = np.random.default_rng(4)
    df = pd.DataFrame({"g": ["a"] * 500, "y": rng.normal(0, 1, 500)})
    r = normality(df, "y", "g")
    assert r.per_group[0]["method"] == "large_n" and r.per_group[0]["p"] is None
    assert r.verdict == "ok"


def test_equal_variance_brown_forsythe():
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"g": ["a"] * 80 + ["b"] * 80,
                       "y": np.r_[rng.normal(0, 1, 80), rng.normal(0, 4, 80)]})
    r = equal_variance(df, "y", "g")
    assert r.verdict == "violated" and "Welch" in r.summary
    assert r.numbers["method"] == "brown-forsythe"

    same = pd.DataFrame({"g": ["a"] * 80 + ["b"] * 80, "y": rng.normal(0, 1, 160)})
    assert equal_variance(same, "y", "g").verdict == "ok"


def test_collinearity_vif():
    rng = np.random.default_rng(6)
    x = rng.normal(0, 1, 200)
    df = pd.DataFrame({"x1": x, "x2": x * 2 + rng.normal(0, 0.05, 200),
                       "x3": rng.normal(0, 1, 200)})
    r = collinearity(df, ["x1", "x2", "x3"])
    assert r.verdict == "violated"
    vifs = {g["column"]: g["vif"] for g in r.per_group}
    assert vifs["x1"] > 5 and vifs["x3"] < 5


def test_independence_reads_confirmed_structure(session):
    r = independence(session)
    assert r.verdict == "caution"                      # 구조 미확정이면 모른다고 말한다

    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session)
    append_op(doc, "group_confirm", column="site", kind="cluster")
    save_session(doc)
    r2 = independence(session)
    assert r2.verdict == "violated" and "site" in r2.summary


def test_multiplicity_bonferroni():
    r = multiplicity(5)
    assert r.numbers["alpha_adjusted"] == pytest.approx(0.01)
    assert multiplicity(1).verdict == "ok"


def test_power_names_the_short_group():
    rng = np.random.default_rng(8)
    df = pd.DataFrame({"g": ["big"] * 200 + ["small"] * 9,
                       "y": rng.normal(0, 1, 209)})
    r = power_check(df, "y", "g")
    assert r.verdict == "caution"
    assert "small" in r.summary and r.numbers["smallest_group"] == "small"
    assert r.numbers["min_detectable_d"] > 0.5


def test_run_checks_needs_a_spec(session):
    with pytest.raises(ValueError, match="analyze plan"):
        run_checks(session)


def test_run_checks_picks_checks_for_the_question(session):
    _confirm(session, vaf="proportion", arm="label")
    record(session, Spec(question="Q-01", y="vaf", group="arm", n_tests=2))
    results = {r.id for r in run_checks(session)}
    assert {"C-01", "C-02", "C-05", "C-09", "C-15"} <= results


# ──  검정 실행 — 효과크기·CI 동반 ────────────────────────
from statop.analyze.run import RUNNERS, run_test


def _planned(session, question="Q-01", y="vaf", group="arm", **kw):
    _confirm(session, vaf="proportion", arm="label", age="continuous")
    record(session, Spec(question=question, y=y, group=group, **kw))
    return session


def test_run_welch_carries_effect_and_adjusted_alpha(session):
    _planned(session, n_tests=3)
    r = run_test(session, "T-101")
    assert r.p is not None and r.effect["name"] == "Hedges g"
    assert r.effect["ci_low"] < r.effect["value"] < r.effect["ci_high"]
    assert any("0.01667" in n for n in r.notes)        # α/3 비교가 붙는다


def test_run_mwu_rank_biserial_with_ci(session):
    _planned(session)
    r = run_test(session, "T-103")
    assert r.effect["name"] == "rank-biserial"
    assert r.effect["ci_low"] is not None


def test_run_detects_a_real_difference(tmp_path, monkeypatch):
    """알려진 차이를 넣으면 잡아야 한다 — 방향·크기까지."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "h3"))
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"arm": ["a"] * 100 + ["b"] * 100,
                       "y": np.r_[rng.normal(0, 1, 100), rng.normal(1, 1, 100)]})
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    _confirm(s, y="continuous", arm="label")
    record(s, Spec(question="Q-01", y="y", group="arm"))
    r = run_test(s, "T-101")
    assert r.p < 0.001
    assert abs(r.effect["value"]) > 0.7                # g ≈ 1


def test_run_respects_direction(session):
    _planned(session, direction="greater")
    r = run_test(session, "T-101")
    assert r.p is not None                             # 단측도 돈다


def test_run_correlation_with_fisher_ci(session):
    _planned(session, question="Q-03", y="age", group="vaf")
    r = run_test(session, "T-302")
    assert r.effect["name"] == "rho"
    assert -1 <= r.effect["ci_low"] <= r.effect["ci_high"] <= 1


def test_run_unimplemented_says_so(session):
    _planned(session)
    with pytest.raises(ValueError, match="T-999"):
        run_test(session, "T-999")
    assert len(RUNNERS) >= 14


def test_run_uses_label_mapping(session):
    """3수준을 2군으로 묶었으면 검정도 묶인 군으로 돌아야 한다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    _confirm(session, vaf="proportion", site="label")
    doc = load_session(session)
    src = main_source(doc)
    append_op(doc, "label_map", source=src["id"], column="site",
              mapping={"A": 0, "B": 1, "C": 1})
    save_session(doc)
    record(session, Spec(question="Q-01", y="vaf", group="site"))
    r = run_test(session, "T-101")                     # 3수준이지만 2군으로 돈다
    assert set(r.n) == {"0", "1"}


# ── +: 구현 확대 (Q-05·06·07·08·10) ─────────────────────
def _frame():
    """참값을 알고 만든 표 — 추정값이 그 값 근처로 나오는지까지 본다."""
    rng = np.random.default_rng(7)
    n = 240
    x = rng.normal(0.0, 1.0, n)
    arm = np.array(["ctrl"] * (n // 2) + ["treat"] * (n // 2))
    lat = np.column_stack([rng.normal(1.0 + (arm == "treat") * 1.0, 0.4, n),
                           rng.normal(1.0, 0.4, n), rng.normal(1.0, 0.4, n)])
    cnt = np.array([rng.multinomial(3000, np.exp(r) / np.exp(r).sum()) for r in lat])
    df = pd.DataFrame(cnt, columns=["comp_A", "comp_B", "comp_C"]).astype(float)
    comp = df[["comp_A", "comp_B", "comp_C"]]
    frac = comp.div(comp.sum(axis=1), axis=0)
    return df.assign(
        x=x, arm=arm,
        dose=np.repeat([0.0, 1.0, 2.0], n // 3),
        yc=2.0 + 1.5 * x + rng.normal(0, 1, n),                       # 기울기 1.5
        ycnt=rng.poisson(np.exp(1.0 + 0.4 * x)).astype(float),        # log IRR 0.4
        t=rng.exponential(np.exp(-0.5 * x)),                          # log HR 0.5
        m1=x + rng.normal(0, 0.3, n), m2=x + 0.5 + rng.normal(0, 0.3, n),  # 치우침 0.5
        fa=frac["comp_A"], fb=frac["comp_B"], fc=frac["comp_C"])


def test_every_runner_id_matches_its_outcome_id():
    """RUNNERS 의 키와 결과의 id 가 다르면 세션 기록이 엉뚱한 검정으로 남는다."""
    import yaml

    known = {t["id"] for t in yaml.safe_load(
        open("rules/tests.yaml", encoding="utf-8"))["tests"]}
    assert set(RUNNERS) <= known, set(RUNNERS) - known


def test_trend_runners_recover_the_planted_slope():
    df = _frame()
    o = RUNNERS["T-504"](df, "yc", "x", "two-sided")
    assert o.effect["ci_low"] < 1.5 < o.effect["ci_high"]       # 참값 1.5 가 CI 안
    mk = RUNNERS["T-503"](df, "yc", "x", "two-sided")
    assert mk.effect["name"] == "Sen slope" and mk.p < 0.001
    jt = RUNNERS["T-501"](df.assign(dose=np.repeat([0.0, 1.0, 2.0], len(df) // 3)),
                          "yc", "dose", "two-sided")
    assert jt.n["groups"] == 3
    with pytest.raises(ValueError):                              # 2군이면 추세가 아니다
        RUNNERS["T-501"](df, "yc", "arm", "two-sided")


def test_regression_runners_recover_planted_effects():
    df = _frame()
    ols = RUNNERS["T-802"](df, "yc", "x", "two-sided")
    assert ols.effect["ci_low"] < 1.5 < ols.effect["ci_high"]
    pois = RUNNERS["T-803"](df, "ycnt", "x", "two-sided")
    assert pois.effect["name"].startswith("IRR")
    # CI 포함으로 걸면 20번에 한 번은 그냥 빗나간다 — 점추정이 참값 근처인지로 본다
    assert abs(np.log(pois.effect["value"]) - 0.4) < 0.15
    cox = RUNNERS["T-807"](df, "t", "x", "two-sided")
    assert cox.effect["ci_low"] < np.exp(0.5) < cox.effect["ci_high"]
    # 중도절단이 설계에 없다는 사실은 반드시 결과에 남아야 한다
    assert any("절단" in n or "censor" in n for n in cox.notes)


# ── Q-09 생존/사건 시간 ─────────────────────────────────────
def _survival_frame(seed: int = 9, n: int = 400, hr: float = 0.5):
    """참값 HR을 심은 생존 자료 — 중도절단이 절반쯤 섞인다."""
    rng = np.random.default_rng(seed)
    arm = np.array(["ctrl"] * (n // 2) + ["treat"] * (n // 2))
    t_event = rng.exponential(1 / np.where(arm == "treat", hr, 1.0))
    t_censor = rng.exponential(2.0)
    return pd.DataFrame({"t": np.minimum(t_event, t_censor),
                         "ev": (t_event <= t_censor).astype(float),
                         "arm": arm, "age": rng.normal(60, 10, n)})


def test_survival_runners_recover_the_planted_hazard_ratio():
    df = _survival_frame()
    spec = Spec(question="Q-09", y="t", group="arm", event="ev")
    for tid in ("T-901", "T-902", "T-904"):
        o = RUNNERS[tid](df, "t", "arm", "two-sided", spec)
        assert o.effect["ci_low"] < 0.5 < o.effect["ci_high"], (tid, o.effect)
        assert o.p < 0.01
        assert any("중도절단" in n or "censored" in n for n in o.notes)


def test_ignoring_censoring_biases_the_hazard_ratio():
    """사건 컬럼을 안 주면 모두 사건으로 보게 되어 값이 참값에서 멀어진다 — 말해줘야 한다."""
    df = _survival_frame()
    with_ev = RUNNERS["T-901"](df, "t", "arm", "two-sided",
                               Spec(question="Q-09", y="t", group="arm", event="ev"))
    without = RUNNERS["T-901"](df, "t", "arm", "two-sided",
                               Spec(question="Q-09", y="t", group="arm"))
    assert abs(with_ev.effect["value"] - 0.5) < abs(without.effect["value"] - 0.5)
    assert any("모든 행을 사건" in n or "every row" in n for n in without.notes)


def test_rmst_stops_where_observation_stops():
    """tau 를 관측 밖으로 밀면 넓이가 추정이 아니라 추측이 된다."""
    df = _survival_frame()
    o = RUNNERS["T-903"](df, "t", "arm", "two-sided",
                         Spec(question="Q-09", y="t", group="arm", event="ev"))
    tau_note = next(n for n in o.notes if "까지" in n or "up to" in n)
    tau = float(tau_note.split("까지")[0].rsplit(" ", 1)[-1].replace(",", "")) \
        if "까지" in tau_note else None
    if tau is not None:
        by_arm = df.groupby("arm")["t"].max()
        assert tau <= by_arm.min() + 1e-9
    assert o.effect["ci_low"] < o.effect["value"] < o.effect["ci_high"]
    assert o.p < 0.01


def test_median_survival_not_reached_is_not_printed_as_a_number():
    """절반이 사건을 안 겪었으면 nan 을 숫자인 척 찍으면 안 된다."""
    df = _survival_frame(hr=0.05)              # 처치군은 거의 사건이 없다
    o = RUNNERS["T-901"](df, "t", "arm", "two-sided",
                         Spec(question="Q-09", y="t", group="arm", event="ev"))
    assert any("도달 안 함" in n or "not reached" in n for n in o.notes)
    assert not any("nan" in n for n in o.notes)


def test_event_column_must_not_collide_with_outcome_or_group():
    from statop.analyze.spec import validate

    errs = validate(Spec(question="Q-09", y="t", group="arm", event="t"),
                    ["t", "arm", "ev"])
    assert errs


def test_ordinal_text_outcome_is_flagged_as_lexical():
    """L<M<H 를 사전 순으로 늘어놓으면 값이 무의미해진다 — 조용히 넘어가면 안 된다."""
    df = _frame()
    lat = 0.7 * df["x"] + np.random.default_rng(0).normal(0, 1, len(df))
    txt = df.assign(o=pd.cut(lat, 3, labels=["L", "M", "H"]).astype(str))
    code = df.assign(o=pd.cut(lat, 3, labels=[0, 1, 2]).astype(str))
    a = RUNNERS["T-804"](txt, "o", "x", "two-sided")
    b = RUNNERS["T-804"](code, "o", "x", "two-sided")
    assert any("사전 순" in n or "alphabetically" in n for n in a.notes)
    assert not any("사전 순" in n or "alphabetically" in n for n in b.notes)
    assert b.effect["value"] > 1.0 and b.p < 0.01        # 코드를 붙이면 방향이 산다


def test_agreement_runners_find_the_planted_bias():
    df = _frame()
    ba = RUNNERS["T-602"](df, "m1", "m2", "two-sided")
    assert ba.effect["ci_low"] < -0.5 < ba.effect["ci_high"]   # m1-m2 = -0.5
    icc = RUNNERS["T-601"](df, "m1", "m2", "two-sided")
    ccc = RUNNERS["T-603"](df, "m1", "m2", "two-sided")
    # 치우침이 있으므로 절대일치(ICC·CCC)는 상관보다 낮아야 한다
    r = abs(np.corrcoef(df["m1"], df["m2"])[0, 1])
    assert icc.effect["value"] < r and ccc.effect["value"] < r


def test_distribution_runners_agree_on_a_real_difference():
    df = _frame()
    two = df.assign(g=np.where(df["x"] > 0, "hi", "lo"))
    for tid in ("T-701", "T-702", "T-703", "T-704"):
        o = RUNNERS[tid](two, "yc", "g", "two-sided")
        assert o.p < 0.01, (tid, o.p)
        assert any("퍼짐" in n or "spread" in n for n in o.notes)


def test_compositional_runners_use_the_whole_set():
    """세트 일부만 변환하면 기하평균이 틀린다 — 쓴 컬럼을 결과에 남긴다."""
    df = _frame()
    clr = RUNNERS["T-1001"](df, "fa", "arm", "two-sided")
    assert any("comp_A" in n or "fa" in n for n in clr.notes)
    alr = RUNNERS["T-1002"](df, "fa", "arm", "two-sided")
    assert any("fa" in n for n in alr.notes)
    ald = RUNNERS["T-1003"](df, "comp_A", "arm", "two-sided")   # 개수로만 돌아간다
    assert ald.effect["ci_low"] < ald.effect["value"] < ald.effect["ci_high"]
    with pytest.raises(ValueError):
        RUNNERS["T-1003"](df, "fa", "arm", "two-sided")         # 비율이면 거부
    # CLR(T-1001)과 ALDEx2(T-1003)는 같은 양을 추정한다 — 크게 어긋나면 하나가 틀린 것이다
    logdiff = next(n for n in clr.notes if "=" in n and ("로그비" in n or "log-ratio" in n))
    assert abs(float(logdiff.rsplit("=", 1)[1]) - ald.effect["value"]) < 0.1
    for o in (clr, ald):
        assert any("배" in n or "fold" in n for n in o.notes)   # CLR 오독 경고


def test_marginal_vs_conditional_reports_both_distributions():
    df = _frame()
    d = df.assign(cat=np.where(df["x"] > 0, "yes", "no"))
    o = RUNNERS["T-1006"](d, "cat", "arm", "two-sided")
    assert any("P(Y |" in n for n in o.notes)
    assert any("심슨" in n or "Simpson" in n for n in o.notes)


def test_unimplemented_candidates_are_marked_not_runnable(session):
    """계산기가 없는 후보는 초록이어도 실행할 수 없다고 먼저 말해야 한다."""
    _confirm(session, vaf="proportion", arm="label")
    res = build(session, Spec(question="Q-01", y="vaf", group="arm"))
    cands = shortlist(res)
    assert cands
    for c in cands:
        assert c.runnable == (c.id in RUNNERS)
        if not c.runnable:
            assert any("계산기" in r or "calculator" in r for r in c.reasons)


def _open_analyze(session_file: str, **values):
    """분석 화면을 실제 진입점으로 연 뒤 필드 값만 바꾼다.

    필드 목록을 테스트가 베껴 쓰면 화면에 필드가 하나 늘 때마다 테스트가 깨진다.
    """
    from statop.shell.screen import Screen

    sc = Screen()
    sc.session_file = pathlib.Path(session_file)
    sc.imported = ["age", "vaf", "arm"]
    assert sc.open_analyze() is True
    for f in sc.an_fields:
        if f["key"] in values:
            f["value"] = values[f["key"]]
    return sc


# ── 결측 대치가 분석 경로에 반영되는가 ──────────────────────
@pytest.fixture
def session_gaps(tmp_path, monkeypatch):
    """y 와 x 양쪽에 결측이 있는 표 — 대치 전에는 쓸 수 있는 행이 줄어든다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(3)
    n = 200
    age = rng.normal(60, 10, n)
    vaf = np.clip(0.2 + 0.01 * (age - 60) + rng.normal(0, 0.05, n), 0.001, 0.999)
    age[rng.choice(n, 30, replace=False)] = np.nan
    vaf[rng.choice(n, 20, replace=False)] = np.nan
    p = tmp_path / "g.csv"
    pd.DataFrame({"age": age, "vaf": vaf,
                  "arm": rng.choice(["a", "b"], n)}).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for col, t in (("age", "continuous"), ("vaf", "proportion"), ("arm", "label")):
        append_op(doc, "semantic_confirm", source=src["id"], column=col, type=t)
    save_session(doc)
    return s


def test_plan_reports_how_many_rows_survive_the_missing(session_gaps):
    from statop.analyze.spec import Spec, build

    res = build(session_gaps, Spec(question="Q-08", y="vaf", group="age"))
    assert res.missing["vaf"]["n"] == 20
    assert res.missing["age"]["n"] == 30
    assert res.n_complete < res.n_rows          # 실제로 쓰이는 행이 줄었다


def test_recorded_imputation_is_reflected_in_analysis(session_gaps):
    """CLI/웹에서 대치해 둔 것이 분석에서 없던 일이 되면 안 된다."""
    from statop.analyze.spec import Spec, build
    from statop.session.core import append_op, load_session, main_source, save_session

    before = build(session_gaps, Spec(question="Q-08", y="vaf", group="age"))
    doc = load_session(session_gaps)
    append_op(doc, "impute", source=main_source(doc)["id"], method="median",
              cols=["vaf", "age"], group_by=None, seed=0, params={}, n_filled=50)
    save_session(doc)

    after = build(session_gaps, Spec(question="Q-08", y="vaf", group="age"))
    assert after.missing["vaf"]["n"] == 0 and after.missing["age"]["n"] == 0
    assert after.n_complete == after.n_rows > before.n_complete


def test_imputation_changes_the_number_of_rows_a_test_uses(session_gaps):
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.session.core import append_op, load_session, main_source, save_session

    record(session_gaps, Spec(question="Q-08", y="vaf", group="age"))
    n_before = run_test(session_gaps, "T-802").n["rows"]

    doc = load_session(session_gaps)
    append_op(doc, "impute", source=main_source(doc)["id"], method="median",
              cols=["vaf", "age"], group_by=None, seed=0, params={}, n_filled=50)
    save_session(doc)
    assert run_test(session_gaps, "T-802").n["rows"] > n_before


def test_screen_impute_only_touches_the_designed_columns(session_gaps):
    """화면에서 대치할 때 설계와 무관한 컬럼까지 채우면 안 된다."""
    from statop.session.core import load_session, replay
    from statop.shell.screen import Screen

    sc = _open_analyze(session_gaps, y="vaf", group="age")
    assert sc.an_plan() is True
    assert sc.an_missing["vaf"]["n"] > 0
    sc.an_impute = "median"
    assert sc.an_do_impute() is True

    ops = replay(load_session(session_gaps))["missing_ops"]
    assert ops and sorted(ops[-1]["cols"]) == ["age", "vaf"]   # arm 은 건드리지 않았다
    assert all(m["n"] == 0 for m in sc.an_missing.values())


def test_ignore_missing_lets_the_metric_through_without_touching_the_session(session_gaps):
    """채우기 싫을 때도 값은 봐야 한다 — 다만 몇 행으로 나온 값인지는 남아야 한다."""
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.session.core import load_session, replay

    record(session_gaps, Spec(question="Q-08", y="vaf", group="age"))
    out = run_test(session_gaps, "T-802")
    assert any("결측" in n and "제외" in n for n in out.notes)
    # 무시는 기록을 남기지 않는다 — 대치와 구별되어야 한다
    assert not replay(load_session(session_gaps))["missing_ops"]


def test_screen_ignore_missing_hides_the_impute_prompt(session_gaps):
    from statop.shell.screen import Screen

    sc = _open_analyze(session_gaps, y="vaf", group="age")
    sc.an_plan()
    assert "결측 대치" in sc.render_analyze()
    assert sc.an_ignore_missing_rows() is True
    body = sc.render_analyze()
    assert "결측 행 제외" in body and "결측 대치" not in body


# ── 층화(by)와 그것이 여는 검정들 ───────────────────────────
def _simpson_frame():
    """각 site 안에서는 A가 높지만, A가 낮은 site에 몰려 전체로는 B가 높은 자료."""
    rng = np.random.default_rng(4)
    rows = []
    for site, (na, nb, ma, mb) in {"S1": (220, 30, 5.6, 5.0),
                                   "S2": (30, 220, 8.6, 8.0)}.items():
        rows += [{"site": site, "arm": "A", "y": v} for v in rng.normal(ma, 1, na)]
        rows += [{"site": site, "arm": "B", "y": v} for v in rng.normal(mb, 1, nb)]
    return pd.DataFrame(rows)


def test_strata_expose_a_direction_flip():
    """전체 하나로 뭉치면 군마다 방향이 뒤집힌 것을 놓친다 — label을 지정하는 이유다."""
    from statop.analyze.run import _by_strata, _direction_flips

    df = _simpson_frame()
    fn = RUNNERS["T-101"]
    overall = fn(df, "y", "arm", "two-sided")
    spec = Spec(question="Q-01", y="y", group="arm", by="site")
    strata = _by_strata(fn, df, spec, {})
    assert {s["level"] for s in strata} == {"S1", "S2"}
    assert overall.effect["value"] < 0                  # 전체로는 B가 큼
    assert all(s["effect"]["value"] > 0 for s in strata)  # 수준별로는 A가 큼
    assert sorted(_direction_flips(overall, strata)) == ["S1", "S2"]


def test_one_bad_stratum_does_not_kill_the_rest():
    from statop.analyze.run import _by_strata

    df = pd.concat([_simpson_frame(),
                    pd.DataFrame([{"site": "S3", "arm": "A", "y": 1.0}])])
    strata = _by_strata(RUNNERS["T-101"], df, Spec(question="Q-01", y="y",
                                                   group="arm", by="site"), {})
    bad = next(s for s in strata if s["level"] == "S3")
    assert "error" in bad and bad["n"] == 1
    assert sum("error" not in s for s in strata) == 2    # 나머지는 살아 있다


def test_ratio_effects_use_one_as_the_flip_reference():
    """HR·OR 은 1이 기준이다 — 0과 비교하면 모든 수준이 뒤집힌 것처럼 보인다."""
    from statop.analyze.run import TestOutcome, _direction_flips

    overall = TestOutcome("T-901", "x", 1.0, 0.01,
                          effect={"name": "HR (treat vs ctrl)", "value": 0.5})
    strata = [{"level": "a", "effect": {"value": 0.6}},     # 같은 방향 (1 미만)
              {"level": "b", "effect": {"value": 1.4}}]     # 반대 방향
    assert _direction_flips(overall, strata) == ["b"]


def test_interaction_recovers_the_planted_moderation():
    rng = np.random.default_rng(6)
    n = 400
    arm = rng.choice(["ctrl", "treat"], n)
    sex = rng.choice(["M", "F"], n)
    df = pd.DataFrame({"arm": arm, "sex": sex,
                       "y": 5 + (arm == "treat") * np.where(sex == "M", 1.0, 0.0)
                       + rng.normal(0, 1, n)})
    spec = Spec(question="Q-04", y="y", group="arm", by="sex")
    glm = RUNNERS["T-403"](df, "y", "arm", "two-sided", spec)
    assert glm.effect["ci_low"] < 1.0 < glm.effect["ci_high"]   # 참값 1.0
    aov = RUNNERS["T-401"](df, "y", "arm", "two-sided", spec)
    assert aov.p < 0.01
    assert any("칸별 평균" in n or "main effects" in n for n in aov.notes)
    # 층화 컬럼이 없으면 상호작용은 성립하지 않는다
    with pytest.raises(ValueError):
        RUNNERS["T-401"](df, "y", "arm", "two-sided",
                         Spec(question="Q-04", y="y", group="arm"))


def test_planned_contrast_matches_the_hand_computed_value():
    rng = np.random.default_rng(8)
    n = 90
    grp = np.repeat(["normal", "confound", "cancer"], n)
    mean = {"normal": 5.0, "confound": 5.0, "cancer": 7.0}
    df = pd.DataFrame({"g": grp, "y": [rng.normal(mean[g], 1) for g in grp]})
    spec = Spec(question="Q-11", y="y", group="g", weights="1,1,-2")
    out = RUNNERS["T-1101"](df, "y", "g", "two-sided", spec)
    # 군은 사전순(cancer < confound < normal)으로 놓인다
    m = df.groupby("g")["y"].mean()
    expect = m["cancer"] + m["confound"] - 2 * m["normal"]
    assert abs(out.effect["value"] - expect) < 1e-9
    assert out.effect["ci_low"] < expect < out.effect["ci_high"]


@pytest.mark.parametrize(("weights", "needle"), [
    (None, "가중치"), ("1,1,1", "합"), ("1,-1", "3개"), ("a,b,c", "숫자")])
def test_bad_contrast_weights_are_refused_with_the_group_order(weights, needle):
    rng = np.random.default_rng(8)
    df = pd.DataFrame({"g": np.repeat(["a", "b", "c"], 30),
                       "y": rng.normal(0, 1, 90)})
    spec = Spec(question="Q-11", y="y", group="g", weights=weights)
    with pytest.raises(ValueError) as e:
        RUNNERS["T-1101"](df, "y", "g", "two-sided", spec)
    assert needle in str(e.value)


def test_dunnett_reports_every_group_against_the_control():
    rng = np.random.default_rng(8)
    n = 90
    grp = np.repeat(["normal", "confound", "cancer"], n)
    mean = {"normal": 5.0, "confound": 5.0, "cancer": 7.0}
    df = pd.DataFrame({"g": grp, "y": [rng.normal(mean[g], 1) for g in grp]})
    out = RUNNERS["T-1102"](df, "y", "g", "two-sided",
                            Spec(question="Q-11", y="y", group="g", control="normal"))
    rows = [n_ for n_ in out.notes if "대조군 =" in n_]
    assert len(rows) == 2                     # 대조군을 뺀 나머지 전부
    assert any("이미 보정" in n_ for n_ in out.notes)
    with pytest.raises(ValueError):           # 대조군을 안 주면 진행하지 않는다
        RUNNERS["T-1102"](df, "y", "g", "two-sided", Spec(question="Q-11", y="y", group="g"))


def test_partial_correlation_removes_the_confounder():
    """z가 x와 y를 함께 끌어올린 부분을 빼고 남는 상관만 본다."""
    rng = np.random.default_rng(12)
    n = 300
    z = rng.normal(0, 1, n)
    x = z + rng.normal(0, 1, n)
    df = pd.DataFrame({"z": z, "x": x, "y": 1.0 * z + 0.3 * x + rng.normal(0, 1, n)})
    out = RUNNERS["T-311"](df, "y", "x", "two-sided",
                           Spec(question="Q-03", y="y", group="x", by="z"))
    raw = float(np.corrcoef(df["y"], df["x"])[0, 1])
    assert out.effect["value"] < raw          # 교란을 빼면 상관이 줄어든다
    assert any("통제" in n_ or "controlling" in n_ for n_ in out.notes)
    with pytest.raises(ValueError):           # 무엇을 통제할지 없으면 못 한다
        RUNNERS["T-311"](df, "y", "x", "two-sided", Spec(question="Q-03", y="y", group="x"))


def test_distance_correlation_sees_a_curve_that_pearson_misses():
    rng = np.random.default_rng(12)
    n = 300
    x = rng.normal(0, 1, n)
    df = pd.DataFrame({"x": x, "curve": x ** 2 + rng.normal(0, 0.3, n)})
    pearson = abs(float(np.corrcoef(df["x"], df["curve"])[0, 1]))
    out = RUNNERS["T-304"](df, "curve", "x", "two-sided")
    assert pearson < 0.15 and out.effect["value"] > 0.4
    assert out.p < 0.05


# ── 반복측정: 순서를 값에서 읽는다 ──────────────────────────
@pytest.mark.parametrize(("raw", "want"), [
    (["T2", "T10", "T1", "T3"], ["T1", "T2", "T3", "T10"]),
    (["26AIC088", "25AIC032", "25AIC300", "26AIC007"],
     ["25AIC032", "25AIC300", "26AIC007", "26AIC088"]),   # 앞=연도, 뒤=생산번호
    (["2024-03-01", "2023-12-31", "2024-01-15"],
     ["2023-12-31", "2024-01-15", "2024-03-01"]),
    (["03/01/2024", "12/31/2023", "01/15/2024"],
     ["12/31/2023", "01/15/2024", "03/01/2024"]),
    (["3.5", "10.2", "3.45", "1"], ["1", "3.45", "3.5", "10.2"]),
    (["lib_b2", "lib_b10", "lib_b1"], ["lib_b1", "lib_b2", "lib_b10"]),
])
def test_occasion_order_is_read_from_the_values(raw, want):
    from statop.semantic import ordered_levels

    assert [str(v) for v in ordered_levels(pd.Series(raw))] == want


def test_plain_numbers_sort_numerically_not_chunk_by_chunk():
    """3.5 를 글자로 쪼개면 3.45 보다 작아진다."""
    from statop.semantic import ordered_levels

    assert list(ordered_levels(pd.Series([3.5, 10.2, 3.45, 1.0]))) == [1.0, 3.45, 3.5, 10.2]


def _repeated_frame(ns: int = 60, step: float = 0.8):
    """대상 ns명 × 회차 3번. 회차 라벨은 생산번호 규칙, 개인차가 회차 효과보다 크다."""
    rng = np.random.default_rng(21)
    occ = ["26AIC088", "25AIC032", "25AIC300"]      # 일부러 뒤섞어 둔다
    base = rng.normal(10, 3, ns)
    rows = []
    for i in range(ns):
        for o in occ:
            k = ["25AIC032", "25AIC300", "26AIC088"].index(o)
            rows.append({"pid": f"P{i:03d}", "batch": o,
                         "y": base[i] + step * k + rng.normal(0, 1),
                         "hit": "yes" if rng.random() < 0.3 + 0.15 * k else "no",
                         "arm": "treat" if i % 2 else "ctrl"})
    return pd.DataFrame(rows)


def test_repeated_measures_use_the_value_order_not_the_row_order():
    df = _repeated_frame()
    spec = Spec(question="Q-01", y="y", group="batch", subject="pid")
    out = RUNNERS["T-131"](df, "y", "batch", "two-sided", spec)
    order = next(n for n in out.notes if "회차 순서" in n)
    assert "25AIC032 < 25AIC300 < 26AIC088" in order     # 행 순서가 아니라 값 순서
    means = next(n for n in out.notes if "회차별 평균" in n)
    v = [float(x.split("=")[1]) for x in means.split(": ")[1].split(", ")]
    assert v[0] < v[1] < v[2]                            # 심은 +0.8/회차가 보인다


def test_mixed_model_keeps_subjects_that_repeated_anova_drops():
    """회차가 빠진 대상을 T-131은 버리고 T-133은 쓴다 — 버린 사실을 말해야 한다."""
    df = _repeated_frame()
    holed = df.drop(df.index[(df.pid == "P000") & (df.batch == "25AIC300")])
    spec = Spec(question="Q-01", y="y", group="batch", subject="pid")
    rm = RUNNERS["T-131"](holed, "y", "batch", "two-sided", spec)
    assert rm.n["subjects"] == 59
    assert any("빠진 대상 1명" in n for n in rm.notes)
    lmm = RUNNERS["T-133"](holed, "y", "batch", "two-sided", spec)
    assert lmm.n["subjects"] == 60


def test_repeated_tests_refuse_without_a_subject_column():
    df = _repeated_frame()
    for tid in ("T-131", "T-132", "T-133", "T-212", "T-404"):
        with pytest.raises(ValueError) as e:
            RUNNERS[tid](df, "y", "batch", "two-sided",
                         Spec(question="Q-01", y="y", group="batch"))
        assert "대상 ID" in str(e.value) or "요인" in str(e.value)


def test_mixed_model_reports_how_much_is_between_subject():
    """개인차가 크면 대상별 변량효과 없이 본 결과는 믿을 수 없다."""
    df = _repeated_frame()
    out = RUNNERS["T-133"](df, "y", "batch", "two-sided",
                           Spec(question="Q-01", y="y", group="batch", subject="pid"))
    icc = next(n for n in out.notes if "대상 간 분산" in n)
    pct = float(icc.split("전체의 ")[1].split("%")[0])
    assert pct > 80                    # 개인차 sd=3, 잔차 sd=1 → 9/(9+1)


def test_cochran_q_tracks_the_rate_per_occasion():
    df = _repeated_frame()
    out = RUNNERS["T-212"](df, "hit", "batch", "two-sided",
                           Spec(question="Q-02", y="hit", group="batch", subject="pid"))
    rates = next(n for n in out.notes if "비율:" in n)
    v = [float(x.split("=")[1]) for x in rates.split(": ")[1].split(", ")]
    assert v[0] < v[2]                 # 심은 0.30 → 0.60
    assert out.n["subjects"] == 60


def test_duplicate_id_values_are_surfaced_as_a_repeat_candidate(tmp_path, monkeypatch):
    """id 컬럼에 같은 값이 여러 번이면 반복측정을 할 수 있다고 먼저 알려준다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    df = _repeated_frame(ns=20)
    p = tmp_path / "r.csv"
    df.to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    doc = load_session(str(sc.session_file))
    src = main_source(doc)
    for col, t in (("pid", "id"), ("batch", "label"), ("y", "continuous")):
        append_op(doc, "semantic_confirm", source=src["id"], column=col, type=t)
    save_session(doc)

    res = build(str(sc.session_file), Spec(question="Q-01", y="y", group="batch"))
    assert res.repeat_candidates == [{"column": "pid", "subjects": 20, "rows": 60}]


# ── 개별 점 보기 / 샘플 제외  ─────────────────────────
@pytest.fixture
def session_points(tmp_path, monkeypatch):
    """이상점을 일부러 심은 자료 — 찍어서 뺄 수 있어야 한다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(31)
    n = 120
    y = rng.normal(10, 2, n)
    y[[3, 17]] = [28.0, -6.0]
    p = tmp_path / "p.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                  "arm": rng.choice(["ctrl", "treat"], n),
                  "site": rng.choice(["A", "B"], n), "y": y}).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c, t in (("sid", "id"), ("arm", "label"), ("site", "label"),
                 ("y", "continuous")):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type=t)
    save_session(doc)
    record(s, Spec(question="Q-01", y="y", group="arm", by="site"))
    return s


def test_points_are_the_rows_the_test_actually_used(session_points):
    from statop.analyze.points import collect
    from statop.analyze.run import run_test

    pts = collect(session_points)
    used = run_test(session_points, "T-101").n
    assert len(pts.y) == sum(v for v in used.values() if isinstance(v, int))
    assert pts.key_column == "sid"          # id 로 확정한 컬럼으로 지목한다
    assert pts.by == "site" and len(pts.group) == len(pts.y)   # 색 구분용 라벨


def test_planted_outliers_are_surfaced_with_a_reason(session_points):
    from statop.analyze.points import collect

    pts = collect(session_points)
    keys = {o["key"] for o in pts.outliers}
    assert {"S003", "S017"} <= keys
    assert all(o["why"] for o in pts.outliers)


def test_excluding_a_point_changes_the_test_and_is_recorded(session_points):
    from statop.analyze.points import exclude
    from statop.analyze.run import run_test
    from statop.session.core import load_session, replay

    before = run_test(session_points, "T-101")
    exclude(session_points, "sid", "S003", "장비 오류 — 재측정 불가")
    after = run_test(session_points, "T-101")

    assert sum(v for v in after.n.values() if isinstance(v, int)) == \
        sum(v for v in before.n.values() if isinstance(v, int)) - 1
    assert after.statistic != before.statistic
    rec = replay(load_session(session_points))["excluded"]
    assert rec == [{"op": "exclude_row", "seq": rec[0]["seq"], "source": rec[0]["source"],
                    "key_column": "sid", "key": "S003",
                    "note": "장비 오류 — 재측정 불가"}]


def test_excluding_without_a_reason_is_refused(session_points):
    from statop.analyze.points import exclude

    with pytest.raises(ValueError):
        exclude(session_points, "sid", "S003", "   ")


def test_restoring_a_point_brings_the_row_back(session_points):
    from statop.analyze.points import collect, exclude, include

    n0 = len(collect(session_points).y)
    exclude(session_points, "sid", "S003", "장비 오류")
    assert len(collect(session_points).y) == n0 - 1
    include(session_points, "sid", "S003")
    assert len(collect(session_points).y) == n0


def test_excluded_rows_are_gone_from_every_view(session_points):
    """그림에서 뺀 점이 분포·가정검사에도 빠져야 한다 — 화면마다 다르면 안 된다."""
    from statop.analyze.points import exclude
    from statop.derive.service import apply_ops, session_frame

    exclude(session_points, "sid", "S003", "장비 오류")
    doc, src, df = session_frame(session_points, 10_000)
    frame = apply_ops(df, doc, src["id"])
    assert "S003" not in set(frame["sid"].astype(str))
    assert frame["y"].max() < 28.0                    # 심은 이상점이 사라졌다


def test_screen_plot_mode_needs_a_reason_then_excludes(session_points):
    from statop.shell.screen import Screen

    sc = Screen()
    sc.session_file = pathlib.Path(session_points)
    sc.imported = ["sid", "arm", "site", "y"]
    assert sc.an_open_plot() is True
    body = sc.render_analyze()
    assert "개별 점" in body and "S003" in body

    assert sc.an_toggle_point() is False              # 사유 없이는 못 뺀다
    assert "사유" in sc.status
    sc.an_reason = "장비 오류"
    assert sc.an_toggle_point() is True
    assert any(e["key"] == sc.an_points.excluded[0]["key"]
               for e in sc.an_points.excluded)


def test_excluded_samples_appear_in_the_report(session_points):
    """무엇을 왜 뺐는지는 보고서에서 숨길 수 없어야 한다."""
    from statop.analyze.points import exclude
    from statop.report import collect as report_collect
    from statop.report import to_markdown

    exclude(session_points, "sid", "S003", "장비 오류 — 재측정 불가")
    md = to_markdown(report_collect(session_points))
    assert "S003" in md and "장비 오류 — 재측정 불가" in md


# ──  A4 제약: 제외 전/후 병기 · 대안 우선 · 10% 초과 red ──
def test_exclusion_over_ten_percent_is_red(session_points):
    from statop.analyze.points import EXCLUDE_RED, exclude, status

    assert status(session_points).verdict == "green"
    exclude(session_points, "sid", "S003", "장비 오류")
    assert status(session_points).verdict == "yellow"
    for i in range(4, 20):                       # 120행 중 17건 → 14%
        exclude(session_points, "sid", f"S{i:03d}", "테스트")
    st = status(session_points)
    assert st.ratio > EXCLUDE_RED and st.verdict == "red"


def test_robust_alternatives_are_offered_before_excluding(session_points):
    """빼기 전에 이상점에 둔한 검정을 먼저 권해야 한다."""
    from statop.analyze.points import status

    alts = {a["id"] for a in status(session_points).alternatives}
    assert {"T-103", "T-104"} <= alts           # Q-01 의 비모수·강건 대안
    assert all(a["why"] for a in status(session_points).alternatives)


def test_both_ways_returns_before_and_after(session_points):
    from statop.analyze.points import both_ways, exclude

    plain = both_ways(session_points, "T-101")
    assert plain["before"] is None              # 제외가 없으면 병기할 것도 없다

    exclude(session_points, "sid", "S003", "장비 오류")
    both = both_ways(session_points, "T-101")
    assert both["before"] is not None and both["after"] is not None
    assert both["before"].statistic != both["after"].statistic
    assert both["status"].n_excluded == 1


def test_the_pre_exclusion_run_is_not_recorded_in_the_session(session_points):
    """제외 전 값이 기록되면 가설이 그쪽을 근거로 삼는다 — 결론이 뒤집힌다."""
    from statop.analyze.points import both_ways, exclude
    from statop.session.core import load_session, replay

    exclude(session_points, "sid", "S003", "장비 오류")
    both_ways(session_points, "T-101")
    saved = replay(load_session(session_points))["test_results"]
    assert len(saved) == 1
    assert saved[-1]["statistic"] == both_ways(session_points, "T-101")["after"].statistic


def test_flipped_conclusion_is_flagged():
    """제외 때문에 유의성이 바뀌면 그 사실 자체가 결과다."""
    from statop.analyze.points import both_ways

    # 한 점이 결론을 좌우하도록 만든 자료
    import tempfile

    tmp = pathlib.Path(tempfile.mkdtemp())
    os.environ["STATOP_HOME"] = str(tmp / "home")
    rng = np.random.default_rng(2)
    a = rng.normal(10.0, 1.0, 20)
    b = rng.normal(11.2, 1.0, 20)
    b[0] = 4.0                                   # 이 점만 빼면 유의해진다
    p = tmp / "f.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(40)],
                  "arm": ["a"] * 20 + ["b"] * 20,
                  "y": np.concatenate([a, b])}).to_csv(p, index=False)

    from statop.analyze.points import exclude
    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c, t in (("sid", "id"), ("arm", "label"), ("y", "continuous")):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type=t)
    save_session(doc)
    record(s, Spec(question="Q-01", y="y", group="arm"))

    exclude(s, "sid", "S020", "이상치")
    both = both_ways(s, "T-101")
    assert both["flipped"] is ((both["before"].p < both["alpha"])
                               != (both["after"].p < both["alpha"]))


def test_report_flags_excessive_exclusion(session_points):
    from statop.analyze.points import exclude
    from statop.report import collect as report_collect
    from statop.report import to_markdown

    for i in range(20):
        exclude(session_points, "sid", f"S{i:03d}", "테스트")
    md = to_markdown(report_collect(session_points))
    assert "10%" in md or "분석이 아니라 표본" in md


# ──  보조·가드레일 지표 병기 제안 ───────────────────────
@pytest.fixture
def session_metrics(tmp_path, monkeypatch):
    """조성 3성분 + 2군. 조성이라 심플렉스 가드레일이 걸린다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(7)
    n = 150
    comp = rng.dirichlet([4, 3, 2], size=n)
    arm = np.array(["ctrl"] * 75 + ["treat"] * 75)
    comp[arm == "treat", 0] += 0.06
    comp = comp / comp.sum(axis=1, keepdims=True)
    p = tmp_path / "m.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)], "arm": arm,
                  "frac_A": comp[:, 0], "frac_B": comp[:, 1],
                  "frac_C": comp[:, 2]}).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c, t in (("sid", "id"), ("arm", "label"), ("frac_A", "proportion"),
                 ("frac_B", "proportion"), ("frac_C", "proportion")):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type=t)
    save_session(doc)
    return s


def test_metrics_need_a_result_first(session_metrics):
    from statop.analyze.metrics import suggest

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm"))
    with pytest.raises(ValueError):
        suggest(session_metrics)


def test_raw_scale_support_is_always_offered(session_metrics):
    """표준화 효과크기는 '몇 단위'인지 말하지 않는다 — 원척도 차이가 기본 Support."""
    from statop.analyze.metrics import compute, suggest
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session_metrics, "T-101")
    panel = suggest(session_metrics)
    assert panel.goal["test"] == "T-101"
    ids = [s.id for s in panel.support]
    assert any(i in ("P-203", "MR-S15") for i in ids)
    assert ids.count("P-203") + sum("P-203" in s.name for s in panel.support) <= 2

    got = compute(session_metrics, ids[0])["lines"]
    assert any("원단위" in line for line in got)


def test_composition_guardrail_shows_the_forced_tradeoff(session_metrics):
    """조성은 합이 1이다 — 한 성분이 오르면 다른 성분은 반드시 내린다."""
    from statop.analyze.metrics import compute, suggest
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session_metrics, "T-101")
    panel = suggest(session_metrics)
    assert "MR-G16" in {s.id for s in panel.guardrail}
    lines = compute(session_metrics, "MR-G16")["lines"]
    assert any("frac_B" in line for line in lines)
    total = next(line for line in lines if "차의 합" in line)
    assert abs(float(total.split("= ")[1].split(" ")[0])) < 1e-6


def test_multiplicity_guardrail_catches_a_conclusion_that_flips(session_metrics):
    from statop.analyze.metrics import compute, suggest
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm", n_tests=3))
    run_test(session_metrics, "T-101")
    assert "MR-G06" in {s.id for s in suggest(session_metrics).guardrail}
    lines = compute(session_metrics, "MR-G06")["lines"]
    assert any("보정 α" in line for line in lines)
    assert any("보정 전" in line for line in lines)
    # 이 자료는 p=0.035 — 3검정 보정이면 유의성이 뒤집힌다
    assert any("결론이 바뀝니다" in line for line in lines)


def test_exclusion_guardrail_only_fires_after_an_exclusion(session_metrics):
    from statop.analyze.metrics import suggest
    from statop.analyze.points import exclude
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session_metrics, "T-101")
    assert "MR-G14" not in {s.id for s in suggest(session_metrics).guardrail}

    exclude(session_metrics, "sid", "S001", "장비 오류")
    run_test(session_metrics, "T-101")
    assert "MR-G14" in {s.id for s in suggest(session_metrics).guardrail}


def test_survival_gets_followup_loss_as_a_guardrail(session_points):
    """HR 이 좋아 보여도 추적이 끊긴 비율이 크면 못 믿는다 (MR-G17)."""
    from statop.analyze.metrics import compute, suggest
    from statop.analyze.run import run_test

    record(session_points, Spec(question="Q-09", y="y", group="arm"))
    run_test(session_points, "T-901")
    panel = suggest(session_points)
    assert "MR-G17" in {s.id for s in panel.guardrail}
    lines = compute(session_points, "MR-G17")["lines"]
    assert any("사건 컬럼" in line or "절단" in line for line in lines)


def test_suggestions_come_only_from_the_rule_db(session_metrics):
    """지어내지 않는다 — 모든 제안 id 는 metric_roles.yaml 또는 post.yaml 에 있어야 한다."""
    import yaml

    from statop.analyze.metrics import suggest
    from statop.analyze.run import run_test
    from statop.rules.build import RULES_DIR

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm", n_tests=3))
    run_test(session_metrics, "T-101")
    mr = yaml.safe_load((RULES_DIR / "metric_roles.yaml").read_text(encoding="utf-8"))
    known = {r["id"] for r in mr["support_relations"] + mr["guardrail_relations"]}
    known |= {p["id"] for p in
              yaml.safe_load((RULES_DIR / "post.yaml").read_text(encoding="utf-8"))}
    panel = suggest(session_metrics)
    for s in panel.support + panel.guardrail:
        assert s.id in known, s.id


def test_no_suggestion_is_a_valid_outcome():
    """Support/Guardrail 이 없는 Goal 도 정상이다 — 짝을 강제하지 않는다."""
    from statop.analyze.metrics import _GUARDRAIL_WHEN, _SUPPORT_WHEN

    empty = {"spec": None, "result": None, "types": {}, "effect_key": "",
             "test": "", "n_groups": 0, "excluded": 0, "session": ""}
    assert not any(fn(empty) for fn in _SUPPORT_WHEN.values())
    assert not any(fn(empty) for fn in _GUARDRAIL_WHEN.values())


# ── // 점수 목록·수식·분포 분기 ─────────────────
@pytest.fixture
def session_scores(tmp_path, monkeypatch):
    """분포가 서로 다른 컬럼들 — 어느 엔트로피 공식이 맞는지 갈린다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(7)
    n = 300
    comp = rng.dirichlet([4, 3, 2], size=n)
    p = tmp_path / "s.csv"
    pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(n)], "arm": rng.choice(["a", "b"], n),
        "frac_A": comp[:, 0], "frac_B": comp[:, 1], "frac_C": comp[:, 2],
        "age": rng.normal(60, 10, n), "reads": rng.poisson(500, n).astype(float),
        "wait": rng.exponential(3.0, n), "conc": rng.lognormal(0, 1, n),
        "cau": rng.standard_cauchy(n),
    }).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c, t in (("sid", "id"), ("arm", "label"), ("frac_A", "proportion"),
                 ("frac_B", "proportion"), ("frac_C", "proportion"),
                 ("age", "continuous"), ("reads", "count"), ("wait", "continuous"),
                 ("conc", "continuous"), ("cau", "continuous")):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type=t)
    save_session(doc)
    return s


def test_catalog_covers_every_score_and_never_guesses_green(session_scores):
    """규칙표가 요구 조건을 안 적어 뒀으면 초록이 아니라 회색이다."""
    import yaml

    from statop.analyze.scores import UNSET, catalog
    from statop.rules.build import RULES_DIR

    db = yaml.safe_load((RULES_DIR / "scores.yaml").read_text(encoding="utf-8"))
    rows = catalog(session_scores)
    assert len(rows) == len(db["scores"])
    by_id = {r.id: r for r in rows}
    for s in db["scores"]:
        if not (s.get("input") or "").strip():
            assert by_id[s["id"]].verdict == UNSET, s["id"]


def test_scores_needing_two_columns_are_not_satisfied_by_one(session_scores):
    """'두 연속 컬럼'·'점수 + 이진'은 컬럼 하나로 만족되지 않는다."""
    from statop.analyze.scores import catalog

    by_id = {r.id: r for r in catalog(session_scores)}
    assert len(by_id["SC-ERR-01"].columns) == 2        # MAE: 두 연속
    auc = by_id["SC-CLS-06"]                           # ROC-AUC: 점수 + 이진
    assert len(auc.columns) == 2
    assert any(c == "arm" for c in auc.columns)        # 라벨 자리에 label 컬럼


def test_substituted_formula_is_valid_latex(session_scores):
    """컬럼 이름의 _ 를 그대로 두면 아래첨자가 되어 수식이 깨진다."""
    from statop.analyze.scores import catalog

    mae = next(r for r in catalog(session_scores) if r.id == "SC-ERR-01")
    assert mae.substituted
    assert r"\_" in mae.substituted or "_" not in "".join(mae.columns)
    assert r"\mathrm{" in mae.substituted
    assert "y_i" not in mae.substituted                # 원래 변수는 남지 않는다


@pytest.mark.parametrize(("column", "want"), [
    ("age", "SC-ENT-01"),      # 정규
    ("wait", "SC-ENT-05"),     # 지수
    ("conc", "SC-ENT-06"),     # 로그정규
    ("cau", "SC-ENT-08"),      # Cauchy (분산 정의 안 됨)
    ("frac_A", "SC-ENT-07"),   # 조성 → 디리클레
])
def test_entropy_branches_to_the_right_formula(session_scores, column, want):
    from statop.analyze.scores import entropy_branch

    assert entropy_branch(session_scores, column).picked == want


def test_entropy_refuses_discrete_columns(session_scores):
    """연속 분포의 미분 엔트로피를 카운트에 쓰면 값이 뜻을 잃는다."""
    from statop.analyze.scores import entropy_branch

    with pytest.raises(ValueError) as e:
        entropy_branch(session_scores, "reads")
    assert "Shannon" in str(e.value)


def test_entropy_says_what_it_rejected(session_scores):
    """왜 정규 공식을 못 쓰는지가 결론의 절반이다."""
    from statop.analyze.scores import entropy_branch

    b = entropy_branch(session_scores, "conc")
    assert b.picked == "SC-ENT-06"
    assert {r["id"] for r in b.rejected} >= {"SC-ENT-01"}
    assert all(r["why"] for r in b.rejected)


# ──  Goal 지정 ──────────────────────────────────────────
def test_goal_defaults_to_the_last_test_then_follows_the_user(session_scores):
    from statop.analyze.metrics import set_goal, suggest
    from statop.analyze.run import run_test

    record(session_scores, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session_scores, "T-101")
    auto = suggest(session_scores)
    assert auto.goal["test"] == "T-101" and auto.goal["chosen"] is False

    set_goal(session_scores, score="SC-ERR-02")
    chosen = suggest(session_scores)
    assert chosen.goal["chosen"] is True
    assert chosen.goal["score"] == "SC-ERR-02" and chosen.goal["name"] == "RMSE"


def test_goal_rejects_an_unknown_score(session_scores):
    from statop.analyze.metrics import set_goal

    with pytest.raises(ValueError):
        set_goal(session_scores, score="SC-NOPE-99")
    with pytest.raises(ValueError):
        set_goal(session_scores)          # 아무것도 안 주면 거부


def test_goal_survives_the_session_roundtrip(session_scores):
    from statop.analyze.metrics import set_goal
    from statop.session.core import load_session, replay

    set_goal(session_scores, score="SC-ERR-02")
    set_goal(session_scores, test="T-104")
    st = replay(load_session(session_scores))
    assert st["metric_goal"]["test"] == "T-104"      # 마지막 지정이 이긴다


def test_designated_goal_does_not_borrow_another_metrics_value(session_scores):
    """RMSE 를 Goal 로 정했는데 Hedges g 값을 그 값인 양 붙이면 거짓말이다."""
    from statop.analyze.metrics import set_goal, suggest
    from statop.analyze.run import run_test

    record(session_scores, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session_scores, "T-101")
    set_goal(session_scores, score="SC-ERR-02")

    g = suggest(session_scores).goal
    assert g["name"] == "RMSE" and g["score"] == "SC-ERR-02"
    assert g["value"] is None and g["p"] is None       # 아직 안 잰 값이다
    assert g["measured_by"] == "Welch t-test"          # 무엇을 쟀는지는 말해 준다


def test_search_finds_correlation_where_it_actually_lives():
    """상관계수는 점수 목록이 아니라 Q-03 연관 검정에 있다 — 어디 있는지를 알려줘야 한다."""
    from statop.analyze.find import search

    for q in ("상관", "correlation", "상관계수"):
        hits = {h.id for h in search(q, limit=40).hits}
        assert {"T-301", "T-302", "T-303"} <= hits, (q, hits)
    first = next(h for h in search("상관계수").hits if h.id == "T-301")
    assert "Q-03" in first.where and "연관" in first.where
    assert "Q-03" in first.how


def test_search_does_not_match_inside_other_words():
    """'cox' 가 'Wilcoxon' 안에 걸리면 생존 검색이 망가진다."""
    from statop.analyze.find import search

    ids = {h.id for h in search("생존", limit=40).hits}
    assert {"T-901", "T-903"} <= ids
    assert "T-112" not in ids                 # Wilcoxon signed-rank


def test_search_spans_every_catalogue():
    from statop.analyze.find import search

    kinds = {h.kind for h in search("생존", limit=40).hits}
    assert "test" in kinds and "relation" in kinds
    assert {h.kind for h in search("보정", limit=40).hits} & {"post"}


def test_search_needs_a_query():
    from statop.analyze.find import search

    with pytest.raises(ValueError):
        search("   ")


def test_search_narrows_as_you_type():
    """진짜 검색창이어야 한다 — 다 치고 버튼을 눌러야 나오면 못 찾는다."""
    from statop.analyze.find import search

    counts = [len(search(q, limit=60).hits) for q in ("c", "co", "cor", "correl")]
    assert all(c > 0 for c in counts), counts          # 중간에 0이 되면 안 된다
    assert counts[0] >= counts[-1]                      # 칠수록 좁아진다
    ids = {h.id for h in search("cor", limit=60).hits}
    assert {"T-301", "T-302", "T-303"} <= ids           # 접두만 쳐도 Pearson·Spearman


def test_question_tree_lists_tests_only_under_their_question():
    """이름을 몰라도 갈래로 찾아 들어갈 수 있어야 한다."""
    import yaml

    from statop.analyze.find import by_question
    from statop.rules.build import RULES_DIR

    db = yaml.safe_load((RULES_DIR / "tests.yaml").read_text(encoding="utf-8"))
    tree = by_question()
    assert len(tree) == len(db["questions"]) == 12   # +Q-12
    assert sum(len(q["tests"]) for q in tree) == len(db["tests"])
    q03 = next(q for q in tree if q["id"] == "Q-03")
    assert {t["id"] for t in q03["tests"]} >= {"T-301", "T-302", "T-303"}
    assert all(q["question"] for q in tree)             # 코드만이 아니라 이름도


# ── 검정이 요구하는 가정만 자동으로 (값 아래 병기) ─────────
@pytest.mark.parametrize(("test_id", "want", "unwanted"), [
    ("T-101", {"C-01"}, {"C-02", "C-04"}),      # Welch: 정규성, 등분산은 아님
    ("T-102", {"C-01", "C-02"}, {"C-04"}),      # Student: 등분산도
    ("T-103", {"C-04"}, {"C-01"}),              # 비모수에 정규성을 붙이면 틀린 경고다
    ("T-123", {"C-04"}, {"C-01", "C-02"}),
    ("T-302", set(), {"C-01"}),                 # Spearman 도 정규성 아님
    ("T-802", {"C-01", "C-07", "C-08"}, set()),
])
def test_assumptions_follow_the_test_not_the_family(test_id, want, unwanted):
    """규칙표의 'T-1xx' 묶음 표기가 개별 검정의 진술을 덮으면 안 된다."""
    from statop.analyze.checks import assumptions_of

    got = set(assumptions_of(test_id))
    assert want <= got, (test_id, got)
    assert not (unwanted & got), (test_id, got)
    assert {"C-05", "C-09", "C-13", "C-15"} <= got     # 모든 검정에 걸리는 것


def test_checks_for_test_runs_only_what_is_required(session_metrics):
    from statop.analyze.checks import checks_for_test
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm", n_tests=3))
    run_test(session_metrics, "T-101")
    ids = [c.id for c in checks_for_test(session_metrics, "T-101")]
    assert "C-01" in ids and "C-02" not in ids
    assert "C-15" in ids                              # 다중검정은 늘 본다


def test_checks_without_an_automatic_test_say_so(session_metrics):
    """자동 검사가 없는 가정이 조용히 빠지면 확인된 줄 안다."""
    from statop.analyze.checks import checks_for_test
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session_metrics, "T-101")
    manual = [c for c in checks_for_test(session_metrics, "T-101")
              if c.verdict == "skipped"]
    assert manual and all("사람이 확인" in c.summary for c in manual)
    assert all(c.numbers.get("action") for c in manual)


def test_screen_shows_assumptions_and_compat_under_the_result(session_metrics):
    """값과 p 아래에 바로 붙어야 한다 — 따로 눌러야 보이면 안 본다."""
    from statop.shell.screen import Screen

    sc = Screen()
    sc.session_file = pathlib.Path(session_metrics)
    sc.imported = ["sid", "arm", "frac_A", "frac_B", "frac_C"]
    assert sc.open_analyze() is True
    for f in sc.an_fields:
        f["value"] = {"y": "frac_A", "group": "arm"}.get(f["key"], f["value"])
    sc.an_plan()
    sc.an_row = len(sc.an_fields) + [c.id for c in sc.an_cands].index("T-101")
    assert sc.an_run() is True

    body = sc.render_analyze()
    assert "이 검정이 요구하는 가정" in body
    assert "C-01" in body and "C-15" in body
    # 비율 vs 라벨은 조성 규칙 대상이 아니다 — 걸린 게 없다는 것도 말해준다
    assert "걸리는 적합성 규칙 없음" in body


def test_compat_findings_appear_under_the_result_when_they_apply(session_metrics):
    """비율끼리 상관이면 S-R01 이 값 바로 아래에 붙어야 한다."""
    from statop.shell.screen import Screen

    sc = Screen()
    sc.session_file = pathlib.Path(session_metrics)
    sc.imported = ["sid", "arm", "frac_A", "frac_B", "frac_C"]
    sc.open_analyze()
    for f in sc.an_fields:
        f["value"] = {"question": "Q-03", "y": "frac_A",
                      "group": "frac_B"}.get(f["key"], f["value"])
    sc.an_plan()
    ids = [c.id for c in sc.an_cands]
    sc.an_row = len(sc.an_fields) + ids.index("T-301")
    assert sc.an_run() is True
    body = sc.render_analyze()
    assert "적합성 판정" in body and "S-R01" in body


# ── 조성 상관: 세 값은 서로 다른 질문 () ──────────────
def test_ratio_correlation_offers_transformed_views(session_metrics):
    from statop.analyze.metrics import compute, suggest
    from statop.analyze.run import run_test

    record(session_metrics, Spec(question="Q-03", y="frac_A", group="frac_B"))
    run_test(session_metrics, "T-301")
    panel = suggest(session_metrics)
    assert "MR-S01c" in {s.id for s in panel.support}
    # 상관 질문에 '원척도 차이'는 뜻이 없다
    assert "P-203" not in {s.id for s in panel.support}

    lines = compute(session_metrics, "MR-S01c")["lines"]
    joined = "\n".join(lines)
    assert "인위적인 상관(Closure effect)" in joined
    assert "전체(세트" in joined and "기하평균" in joined
    assert "기준 성분" in joined and "부호가 역전" in joined
    assert "같은 방향으로 증감" in joined               # 비례성 설명
    assert "묻는 질문이 다른 것" in joined
    assert sum(1 for x in lines if "비례성" in x) == 1  # 중복 없이 한 줄


# ──  대안 묶음 축 ──────────────────────────────────────
def test_every_score_belongs_to_a_purpose_group(session_scores):
    """122종 중 묶음 없는 것이 있으면 '대안이 무엇인가'에 답할 수 없다."""
    from statop.analyze.scores import catalog

    rows = catalog(session_scores)
    orphan = [r.id for r in rows if not r.purpose]
    assert not orphan, orphan
    assert all(r.purpose_name for r in rows)
    # 등급(A/B/C)은 두지 않는다 — 무엇에 흔들리는지만 적는다
    assert all(r.shaken_by for r in rows)


def test_groups_hold_exactly_the_same_scores_as_the_flat_list(session_scores):
    """묶어 보기와 펼쳐 보기가 다른 집합을 보이면 하나는 거짓말이다."""
    from statop.analyze.scores import catalog, groups

    flat = {r.id for r in catalog(session_scores)}
    grouped = {e.id for g in groups(session_scores) for e in g.entries}
    assert flat == grouped
    assert all(len(g.entries) >= 1 for g in groups(session_scores))


def test_a_group_really_offers_alternatives_for_the_same_job(session_scores):
    """MAE 를 고를 때 RMSE 가 같은 묶음에 있어야 '대안'이 보인다."""
    from statop.analyze.scores import groups

    by_id = {e.id: g for g in groups(session_scores) for e in g.entries}
    assert by_id["SC-ERR-01"].id == by_id["SC-ERR-02"].id
    members = {e.id for e in by_id["SC-ERR-01"].entries}
    assert {"SC-ERR-01", "SC-ERR-02", "SC-ERR-09"} <= members
    # 상대오차 계열은 다른 묶음이다 — 단위가 달라 나란히 고를 것이 아니다
    assert by_id["SC-ERR-03"].id != by_id["SC-ERR-01"].id


def test_no_robustness_grade_is_stored():
    """"강건하다"는 **무엇에 대해·얼마나 벗어났을 때**를 말하지 않으면 성립하지 않는다.

    같은 `불균형`이라도 양성 1,000:1,000 과 양성 8:1,000 은 전혀 다른 상황인데 한 글자는
    둘을 구분하지 못한다 (작성자 지적). 그래서 등급을 버리고 `statop robust` 가 그 자료에서
    직접 잰다.
    """
    import yaml

    from statop.analyze.scores import ScoreEntry
    from statop.rules.build import RULES_DIR

    db = yaml.safe_load((RULES_DIR / "scores.yaml").read_text(encoding="utf-8"))
    for s in db["scores"]:
        assert "robustness" not in s, s["id"]
        assert s["shaken_by"]
    assert not hasattr(ScoreEntry("x", "x", "x", "x"), "robustness")


# ──  Q-12 표본 크기·대표성 ─────────────────────────────
@pytest.fixture
def session_represent(tmp_path, monkeypatch):
    """범주 수가 다른 두 컬럼 — 어느 쪽이 n 을 정하는지 갈리게 만든다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(5)
    n = 20_000
    path = tmp_path / "rep.csv"
    pd.DataFrame({
        "v": rng.normal(0, 1, n),
        "few": rng.choice(["a", "b"], n),
        "many": rng.choice([f"k{i}" for i in range(60)], n),
    }).to_csv(path, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    return str(sc.session_file)


def test_the_curve_falls_and_names_the_column_that_sets_n(session_represent):
    """범주가 많은 컬럼이 더 큰 n 을 요구한다 — 그 컬럼 이름을 대야 한다 ."""
    from statop.analyze.represent import build

    rep = build(session_represent, repeats=5, seed=3, steps=6)
    by = {c.column: c for c in rep.curves}
    assert by["v"].metric_name == "KS distance"
    assert by["many"].metric_name == "total variation distance"
    # 거리는 n 이 커지면 줄어든다
    assert by["v"].points[0].mean > by["v"].points[-1].mean
    assert by["many"].enough_n > by["few"].enough_n
    assert rep.enough_n == by["many"].enough_n
    assert rep.limiting == ["many"]


def test_enough_n_does_not_stop_at_a_lucky_dip(session_represent):
    """한 번 내려간 것만 보면 우연히 낮게 나온 n 을 답으로 내놓는다."""
    from statop.analyze.represent import Point, _enough

    dipped = [Point(100, 0.09, 0, 0), Point(200, 0.04, 0, 0),
              Point(400, 0.07, 0, 0), Point(800, 0.02, 0, 0)]
    assert _enough(dipped, 0.05, total=10_000) == 800      # 200 이 아니다
    assert _enough(dipped, 0.01, total=10_000) is None


def test_the_same_seed_gives_the_same_curve(session_represent):
    """seed 와 반복 횟수가 기록되므로 같은 곡선이 다시 나와야 한다."""
    from statop.analyze.represent import build

    a = build(session_represent, repeats=5, seed=7, steps=5)
    b = build(session_represent, repeats=5, seed=7, steps=5)
    assert [p.mean for p in a.curves[0].points] == [p.mean for p in b.curves[0].points]
    c = build(session_represent, repeats=5, seed=8, steps=5)
    assert [p.mean for p in a.curves[0].points] != [p.mean for p in c.curves[0].points]


def test_check_compares_against_the_rest_not_the_whole(session_represent):
    """뽑은 행이 전체에 들어 있으면 독립 비교가 아니다 — 남은 행과 대조한다."""
    from statop.analyze.represent import verify

    rows = verify(session_represent, 2_000, seed=3)
    assert rows and all(h.n_picked + h.n_rest == 20_000 for h in rows)
    assert all(h.n_rest == 18_000 for h in rows)
    # 무작위로 갈랐으니 거리가 작아야 한다
    assert all(h.distance < 0.1 for h in rows)


def test_the_chosen_n_comes_back_as_a_falsifiable_sentence(session_represent):
    """'n 이면 충분하다'는 확인할 수 없다. '남은 행과 구별되지 않는다'는 확인된다."""
    from statop.analyze.represent import build, statement

    rep = build(session_represent, repeats=5, seed=3, steps=6)
    head, how = statement(rep)
    assert str(f"{rep.enough_n:,}") in head
    assert str(f"{rep.total_rows - rep.enough_n:,}") in head
    assert how


def test_spread_shows_what_chance_alone_produces(session_represent):
    """'0.05 는 관행'으로 끝내면 어디에 선을 그을지 알 수 없다 — 실측 분포를 낸다."""
    from statop.analyze.represent import spread

    sps = spread(session_represent, 2_000, draws=120, seed=4)
    assert sps and all(s.draws == 120 for s in sps)
    for s in sps:
        assert len(s.values) == 120
        assert s.q["p0"] <= s.q["p25"] <= s.q["p50"] <= s.q["p75"] <= s.q["p100"]
        assert sum(c for _, _, c in s.bins) == 120

    # 범주가 많을수록 우연만으로 나오는 거리가 크다 — 기본 임계 0.05 를 넘기도 한다.
    # 이것이 "0.05 는 관행일 뿐"이라는 말을 숫자로 보여 주는 자리다
    by = {s.column: s for s in sps}
    assert by["many"].q["p50"] > by["few"].q["p50"]
    assert by["many"].q["p95"] > 0.05 > by["few"].q["p95"]


def test_spread_skips_an_n_the_column_cannot_support(session_represent):
    """전체 행 수보다 큰 n 은 뽑을 수 없다 — 지어내지 않고 빼놓는다."""
    from statop.analyze.represent import spread

    assert spread(session_represent, 999_999, draws=5, seed=4) == []


def test_identifier_column_does_not_hijack_the_answer(session_represent, tmp_path,
                                                      monkeypatch):
    """행마다 값이 다른 컬럼은 어떤 n 으로도 전체를 닮을 수 없다.

    빼지 않으면 그 한 컬럼이 '충분한 n = 전체 행 수'라는 답을 만들고,
    가설 문구가 "남은 0행과 구별되지 않는다"가 된다 (실제로 났다).
    """
    from statop.analyze.represent import build

    rng = np.random.default_rng(9)
    n = 6_000
    path = tmp_path / "withid.csv"
    pd.DataFrame({"sid": [f"S{i:06d}" for i in range(n)],
                  "v": rng.normal(0, 1, n)}).to_csv(path, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()

    rep = build(str(sc.session_file), repeats=5, seed=2, steps=6)
    assert rep.skipped_ids == ["sid"]
    assert [c.column for c in rep.curves] == ["v"]
    assert rep.enough_n is not None and rep.enough_n < rep.total_rows


def test_seeing_every_row_is_not_an_answer(session_represent):
    """n = 전체에서 거리 0 은 재서 나온 값이 아니라 자기 자신과의 거리다."""
    from statop.analyze.represent import Point, _enough

    pts = [Point(100, 0.9, 0, 0), Point(1_000, 0.8, 0, 0), Point(5_000, 0.0, 0, 0)]
    assert _enough(pts, 0.05, total=5_000) is None       # 동어반복을 답으로 내지 않는다
    assert _enough(pts, 0.95, total=5_000) == 100


def test_effect_sizes_agree_on_which_group_is_larger():
    """A 군이 크면 세 효과크기가 **전부** 그 방향을 가리켜야 한다.

    rank-biserial 이 1−2U/(nm) 로 되어 있어 혼자 부호가 반대였다 — 가설 문장의
    "어느 군이 크다"가 T-103 에서만 뒤집혀 나갔다 (강건성 기능을 만들다 드러났다).
    """
    from statop.analyze.run import RUNNERS, null_ref

    rng = np.random.default_rng(0)
    df = pd.DataFrame({"y": np.r_[rng.normal(10, 1, 200), rng.normal(5, 1, 200)],
                       "g": ["A"] * 200 + ["B"] * 200})
    for tid in ("T-101", "T-103", "T-104"):
        out = RUNNERS[tid](df, "y", "g", "two-sided")
        eff = out.effect
        ref = null_ref(eff["name"])
        assert eff["value"] - ref > 0, f"{tid} {eff['name']}={eff['value']}"


def test_rank_biserial_matches_the_standard_formula():
    """r = 2U/(nm) − 1. 부호를 뒤집으면 다른 효과크기와 방향이 어긋난다."""
    from scipy.stats import mannwhitneyu

    from statop.analyze.run import RUNNERS

    rng = np.random.default_rng(3)
    a, b = rng.normal(2, 1, 80), rng.normal(0, 1, 90)
    df = pd.DataFrame({"y": np.r_[a, b], "g": ["A"] * 80 + ["B"] * 90})
    u = mannwhitneyu(a, b, alternative="two-sided").statistic
    got = RUNNERS["T-103"](df, "y", "g", "two-sided").effect["value"]
    assert abs(got - (2 * u / (80 * 90) - 1)) < 1e-9
