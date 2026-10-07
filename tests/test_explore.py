"""S175 지표 찾기 — 질문 → 컬럼 → 무엇을 쓸까.

이 화면이 없어서 "frac_a 와 age 가 관계있나"를 볼 방도가 없었다. 지표 목록은 세션
전체 기준으로만 깔렸고, 검색은 이름을 알아야만 들었다.
"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def session(tmp_path, monkeypatch):
    """조성 3성분 + 연속값 + 라벨을 **확정까지** 해 둔 세션."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(0)
    n = 300
    comp = rng.dirichlet([5, 3, 2], size=n)
    path = tmp_path / "d.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                  "frac_a": comp[:, 0].round(4), "frac_b": comp[:, 1].round(4),
                  "frac_c": comp[:, 2].round(4),
                  "age": rng.normal(60, 11, n).round(1),
                  "arm": rng.choice(["a", "b"], n)}).to_csv(path, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    doc = load_session(sc.session_file)
    sid = main_source(doc)["id"]
    for c, t in (("sid", "id"), ("frac_a", "composition set"),
                 ("frac_b", "composition set"), ("frac_c", "composition set"),
                 ("age", "continuous"), ("arm", "label")):
        append_op(doc, "semantic_confirm", source=sid, column=c, type=t)
    save_session(doc)
    return str(sc.session_file)


def test_two_columns_and_a_question_give_a_candidate_list(session):
    """컬럼 두 개를 정해 놓고 "무엇을 쓸까"를 물을 수 있어야 한다."""
    from statop.analyze.explore import find

    f = find(session, "Q-03", ["frac_a", "age"])
    assert f.question_name and not f.problems
    ids = [c["id"] for c in f.candidates]
    assert "T-301" in ids and "T-302" in ids, ids
    for c in f.candidates:
        assert c["verdict"] in ("green", "yellow", "red")
    assert "기록되지 않습니다" in f.note


def test_the_value_comes_only_when_you_ask_for_it(session):
    """목록에 뜬 것을 전부 미리 돌리면 화면이 멈춘다 — 누를 때만 돈다."""
    from statop.analyze.explore import find, run

    f = find(session, "Q-03", ["frac_a", "age"])
    assert all("p" not in c for c in f.candidates), "목록 단계에서 이미 계산했다"

    r = run(session, "Q-03", ["frac_a", "age"], "T-302")
    assert r["test"] == "T-302" and r["p"] is not None
    assert r["effect_name"] and r["effect"] is not None
    assert r["recorded"] is False


def test_a_refused_combination_still_computes(session):
    """쓸 수 없다고 판정돼도 값은 나와야 한다 — 숨기면 "왜 안 되는데"로 끝난다."""
    from statop.analyze.explore import run
    from statop.compat import composition_groups, judge_pair

    import pandas as pd

    from statop.derive.service import session_frame

    _, _, df = session_frame(session, 10_000)
    types = {"frac_a": "composition set", "frac_b": "composition set",
             "frac_c": "composition set"}
    g = composition_groups(df, list(types), types)
    rep = judge_pair("correlate", "frac_a", "frac_b", types, df, comp_groups=g)
    assert rep.verdict == "red"                  # 같은 조성 세트끼리 상관 (S-R01)

    r = run(session, "Q-03", ["frac_a", "frac_b"], "T-301")
    assert r["p"] is not None and r["effect"] is not None
    assert r["effect"] < 0, "조성 성분끼리는 음의 편향이 나온다"
    assert pd is not None


def test_an_unknown_question_says_so(session):
    from statop.analyze.explore import find

    with pytest.raises(ValueError, match="Q-99"):
        find(session, "Q-99", ["age"])


# ── 다중검정 보정 (C-15) ────────────────────────────────────
def test_adjustment_matches_the_standard_definitions():
    """값은 표준 정의 그대로여야 한다 — R 의 p.adjust 와 같은 수."""
    from statop.analyze.padjust import adjust

    ps = [0.001, 0.008, 0.039, 0.041, 0.9]
    assert adjust(ps, "none") == ps
    assert adjust(ps, "bonferroni") == pytest.approx([0.005, 0.04, 0.195, 0.205, 1.0])
    assert adjust(ps, "holm") == pytest.approx([0.005, 0.032, 0.117, 0.117, 0.9])
    assert adjust(ps, "bh") == pytest.approx([0.005, 0.02, 0.05125, 0.05125, 0.9])


def test_adjusted_values_never_go_backwards():
    """작은 p 가 큰 p 보다 커지면 순서가 뒤집힌다 — 단조성은 정의의 일부다."""
    from statop.analyze.padjust import adjust

    rng = np.random.default_rng(3)
    ps = sorted(rng.random(40).tolist())
    for m in ("bonferroni", "holm", "bh"):
        out = adjust(ps, m)
        assert out == sorted(out), m
        assert max(out) <= 1.0


def test_the_report_says_which_survive():
    from statop.analyze.padjust import report

    r = report([{"name": "A", "p": 0.001}, {"name": "B", "p": 0.04},
                {"name": "C", "p": 0.9}], "bonferroni")
    assert [x["significant"] for x in r["rows"]] == [True, False, False]
    assert "Bonferroni" in r["head"]
    assert any("여러 번 재면" in ln for ln in r["lines"])


def test_an_unknown_method_is_refused():
    from statop.analyze.padjust import report

    with pytest.raises(ValueError):
        report([{"name": "A", "p": 0.1}], "made-up")


# ── 내가 더하는 추천  ────────────────────────────────
def test_you_can_add_your_own_recommendation(session, tmp_path):
    """규칙표에 없어도 넣을 수 있어야 한다 — 다만 **출처가 갈려** 있다.

    base 관계(무엇으로 재는가)는 그대로다 (). 내가 더한 것은 `custom` 에 따로
    쌓이고 화면에서 "사용자 지정"으로 보인다.
    """
    from statop.analyze.explore import run
    from statop.analyze.metrics import (add_custom, apply_choices, custom_for, goal_key,
                                      remove_custom, save_choice, set_goal, suggest,
                                      with_custom)

    r = run(session, "Q-03", ["frac_a", "age"], "T-302")
    set_goal(session, test="T-302", name="Spearman ρ", effect_key=r["effect_name"])
    key = goal_key(suggest(session))
    path = tmp_path / "roles.json"

    base = suggest(session)
    n_base = len(base.support) + len(base.guardrail)

    mine = add_custom(key, "guardrail", "표본 수 27명", "작은 n 에서는 흔들린다", path)
    assert mine["id"].startswith("U-")
    panel = with_custom(suggest(session), path)
    assert len(panel.support) + len(panel.guardrail) == n_base + 1
    added = next(x for x in panel.guardrail if x.id == mine["id"])
    assert added.source == "user" and added.name == "표본 수 27명"
    assert all(x.source == "base" for x in base.support + base.guardrail)

    # 고를 수도 있다 — base 에 없는 id 라고 거절하면 안 된다
    save_choice(key, [], [mine["id"]], path=path)
    chosen = apply_choices(with_custom(suggest(session), path), path)
    assert next(x for x in chosen.guardrail if x.id == mine["id"]).chosen

    # 다음에도 뜬다 (파일에 남는다)
    assert custom_for(key, path)["guardrail"][0]["name"] == "표본 수 27명"
    assert remove_custom(key, mine["id"], path)
    assert not custom_for(key, path)["guardrail"]


def test_a_nameless_recommendation_is_refused(session, tmp_path):
    """이름이 없으면 나중에 무엇인지 알 수 없다."""
    from statop.analyze.metrics import add_custom

    with pytest.raises(ValueError):
        add_custom("T-302", "guardrail", "   ", path=tmp_path / "r.json")
    with pytest.raises(ValueError):
        add_custom("T-302", "참고", "뭔가", path=tmp_path / "r.json")


# ── 그림과 검정력  ───────────────────────────────────
def test_the_shape_comes_with_the_numbers(session):
    """값과 p 만 보면 V 자인지 직선인지 알 수 없다 — 그림 재료가 함께 나와야 한다."""
    from statop.analyze.explore import points

    sc = points(session, "Q-03", ["frac_a", "age"])
    assert sc["kind"] == "scatter" and len(sc["series"]) == 1
    assert len(sc["series"][0]["pts"]) == sc["n"] > 100

    # 군으로 색을 나누면 계열이 갈린다 — 섞여서 생긴 관계가 그 자리에서 보인다
    col = points(session, "Q-03", ["frac_a", "age"], color_by="arm")
    assert {s["name"] for s in col["series"]} == {"a", "b"}
    assert sum(len(s["pts"]) for s in col["series"]) == col["n"]

    # 차이면 군별 분포를 같은 축에 겹친다
    gr = points(session, "Q-01", ["age", "arm"])
    assert gr["kind"] == "groups" and len(gr["edges"]) == 21
    for s in gr["series"]:
        assert len(s["bins"]) == 20 and s["n"] > 0
        assert s["min"] <= s["med"] <= s["max"]


def test_a_small_sample_says_what_it_can_catch(session, tmp_path, monkeypatch):
    """작은 n 에서 "유의하지 않다"가 "관계가 없다"로 읽히면 안 된다."""
    import numpy as np
    import pandas as pd

    from statop.analyze.explore import power

    big = power(session, "Q-03", ["frac_a", "age"])
    assert big["n"] == 300
    assert 0 < big["cut"] < 0.2, "큰 표본은 작은 관계도 잡는다"

    # 27명이면 |r| ≥ 0.52 만 잡힌다 — 001 발표 자료가 그 경계에 선다
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home2"))
    rng = np.random.default_rng(0)
    p = tmp_path / "small.csv"
    pd.DataFrame({"sid": [f"S{i}" for i in range(27)],
                  "x": rng.normal(0, 1, 27), "y": rng.normal(0, 1, 27)}).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    doc = load_session(sc.session_file)
    sid = main_source(doc)["id"]
    for c, t in (("sid", "id"), ("x", "continuous"), ("y", "continuous")):
        append_op(doc, "semantic_confirm", source=sid, column=c, type=t)
    save_session(doc)

    small = power(str(sc.session_file), "Q-03", ["x", "y"])
    assert small["n"] == 27
    assert round(small["cut"], 2) == 0.52
    assert "0.52" in small["head"] and "27" in small["head"]


def test_power_judges_each_measured_value(session):
    """잰 값이 **그 선의 어느 쪽인지**까지 말해야 쓸모가 있다."""
    from statop.analyze.explore import n_for_r, power, run

    eff = []
    for tid in ("T-302", "T-301"):
        r = run(session, "Q-03", ["frac_a", "age"], tid)
        eff.append({"id": tid, "name": r["name"], "value": r["effect"],
                    "effect_name": r["effect_name"]})
    p = power(session, "Q-03", ["frac_a", "age"], eff)
    assert p["kind"] == "corr" and p["cut"] > 0
    assert len(p["rows"]) == 2
    for r in p["rows"]:
        assert r["comparable"] is True and r["line"]
        assert r["catchable"] == (abs(r["value"]) >= p["cut"])
        if not r["catchable"]:
            assert r["needed_n"] > p["n"], "못 잡으면 몇 개가 더 필요한지 말해야 한다"

    # 더 모으면 선이 내려간다
    ns = [x["n"] for x in p["ladder"]]
    cuts = [x["cut"] for x in p["ladder"]]
    assert ns == sorted(ns) and cuts == sorted(cuts, reverse=True)
    # 역산이 맞물린다 — n_for_r(cut(n)) ≈ n
    assert abs(n_for_r(p["cut"]) - p["n"]) <= 1


def test_a_different_scale_is_not_put_on_the_line(session):
    """τ·dCor 은 상관계수와 다른 자다 — 같은 선에 얹으면 틀린 말을 하게 된다."""
    from statop.analyze.explore import power, run

    eff = []
    for tid in ("T-304", "T-303", "T-302"):
        r = run(session, "Q-03", ["frac_a", "age"], tid)
        eff.append({"id": tid, "name": r["name"], "value": r["effect"],
                    "effect_name": r["effect_name"]})
    rows = {r["id"]: r for r in power(session, "Q-03", ["frac_a", "age"], eff)["rows"]}
    assert rows["T-304"]["comparable"] is False      # dCor
    assert rows["T-303"]["comparable"] is False      # tau
    assert rows["T-302"]["comparable"] is True       # rho 는 같은 척도
    for k in ("T-304", "T-303"):
        assert "다른 척도" in rows[k]["line"]
        assert "needed_n" not in rows[k], "비교하지 않기로 해 놓고 수를 들이대면 안 된다"


def test_moving_the_target_moves_the_line(session):
    """목표 검정력은 **옮길 수 있다** — 80% 는 관습일 뿐이다.

    더 확실히 잡으려 하면 잡히는 가장 작은 크기가 커지고, 같은 크기를 잡는 데
    필요한 표본도 늘어난다. 화면의 끌기가 바꾸는 것이 이것 하나다.
    """
    from statop.analyze.explore import n_for_r, power

    cols = ["frac_a", "age"]
    cuts = {t: power(session, "Q-03", cols, target=t)["cut"] for t in (0.5, 0.8, 0.95, 0.99)}
    assert list(cuts.values()) == sorted(cuts.values()), "목표가 높을수록 선이 올라간다"
    assert n_for_r(0.2, 0.95) > n_for_r(0.2, 0.80) > n_for_r(0.2, 0.50)

    # 머리글·note 가 그 숫자를 말한다 — 80 이 박혀 있으면 안 된다
    p95 = power(session, "Q-03", cols, target=0.95)
    assert "95%" in p95["head"] and "95%" in p95["note"] and p95["target"] == 0.95
    assert "80" not in p95["head"]
    # 범위 밖은 끌어당긴다 — 100% 는 어떤 n 으로도 닿지 않는다
    assert power(session, "Q-03", cols, target=1.5)["target"] == 0.99
    assert power(session, "Q-03", cols, target=0.0)["target"] == 0.50


def test_only_group_columns_can_colour_the_plot(session):
    """색에 넣을 수 있는 것은 **군 컬럼**뿐 — 연속값·식별자를 넣으면 그림이 죽는다."""
    from statop.analyze.explore import find

    f = find(session, "Q-03", ["frac_a", "age"])
    assert "frac_a" not in f.color_columns and "age" not in f.color_columns
    assert "arm" in f.color_columns, f.color_columns
    assert all(c not in f.color_columns for c in ("sample_id", "subject_id"))


def test_one_column_cannot_be_measured_and_says_what_is_missing(session):
    """컬럼 하나로는 **어느 질문도 못 돌린다** — 그런데 목록을 내밀고 있었다.

    누르면 검정 함수가 군을 못 찾아 TypeError 로 터졌다 (12종 전부 같은 증상).
    막는 것으로는 모자라고, 무엇을 더 골라야 하는지를 **고를 목록으로** 내야 한다.
    """
    from statop.analyze.explore import find

    f = find(session, "Q-01", ["frac_a"])
    assert not f.candidates, "돌릴 수 없는 것을 쓸 수 있다고 내밀면 안 된다"
    assert f.problems and f.second_role == "group"
    assert "arm" in f.second_columns

    # 연관은 둘째가 **값** 자리다 — 군을 고르라고 하면 틀린 안내다
    v = find(session, "Q-03", ["frac_a"])
    assert v.second_role == "value" and "age" in v.second_columns
    assert "arm" not in v.second_columns


def test_the_group_you_picked_can_still_colour_the_plot(session):
    """차이를 볼 때 군은 분석 컬럼이면서 **색으로도 보고 싶은 것**이다."""
    from statop.analyze.explore import find

    f = find(session, "Q-01", ["frac_a", "arm"])
    assert "arm" in f.color_columns, "고른 군을 색 목록에서 빼면 나눌 길이 없다"
    assert "frac_a" not in f.color_columns, "보려는 값 자체를 색으로 나누지는 않는다"


def test_a_measured_result_says_what_to_look_at_next(session):
    """재고 나면 **다음에 무엇을 볼까**까지 내야 한다 — 값과 p 만 두면 거기서 멈춘다."""
    from statop.analyze.explore import run

    r = run(session, "Q-01", ["frac_a", "arm"], "T-101")
    nx = r.get("next") or {}
    assert nx.get("head") and nx.get("lines"), "결론 한 줄이 없다"
    # 둘러본 것은 **기록하지 않는다**는 사실을 같이 말해야 한다
    assert any("기록하지 않" in x for x in nx["lines"]) or not nx["scan"]
    for s in nx["steps"]:
        assert s["text"] and s["kind"]


def test_next_steps_do_not_fire_on_a_group_too_small(session):
    """군이 작으면 그 군의 상관은 말하지 않는다 — 셋이 몰려 있으면 뭐든 나온다."""
    from statop.analyze.explore import GROUP_MIN, next_steps, run

    r = run(session, "Q-03", ["frac_a", "age"], "T-301")
    nx = next_steps(session, "Q-03", ["frac_a", "age"], "T-301", r)
    for s in nx["scan"]:
        for g in s.get("groups", []):
            assert g["n"] >= GROUP_MIN
