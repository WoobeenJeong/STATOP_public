"""M1-3 연산 적합성 회귀  — S-R 14종이 **걸릴 때 걸리고 안 걸릴 때 안 걸리는지**.

규칙마다 두 방향을 본다: 조건이 맞으면 잡히고, 조건이 어긋나면 조용해야 한다.
한쪽만 보면 "전부 경고"로 통과하는 엔진이 만들어진다.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.compat import (OP_AGGREGATE, OP_COMPARE, OP_CORRELATE, OP_REGRESS, OP_SPREAD,
                         composition_groups, judge_pair, judge_set)


@pytest.fixture
def df():
    rng = np.random.default_rng(11)
    n = 300
    comp = rng.dirichlet([4, 3, 2], size=n)
    return pd.DataFrame({
        "pid": [f"P{i:04d}" for i in range(n)],
        "fA": comp[:, 0], "fB": comp[:, 1], "fC": comp[:, 2],
        "lone_frac": rng.uniform(0, 1, n),      # 어떤 세트에도 속하지 않는 비율
        "prob": rng.beta(2, 5, n),
        "cnt_x": rng.poisson(1e5, n), "cnt_y": rng.poisson(9e5, n),
        "cnt_same": rng.poisson(1e5, n),
        "pct": rng.uniform(0, 100, n),
        "logv": rng.normal(0, 1, n),
        "ord_stage": rng.integers(1, 5, n),
        "nom_site": rng.integers(0, 4, n),
        "z1": rng.normal(0, 1, n), "z2": rng.normal(0, 1, n),
        "when": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 400, n), "D"),
    })


TYPES = {
    "pid": "id", "fA": "proportion", "fB": "proportion", "fC": "proportion",
    "lone_frac": "proportion", "prob": "probability",
    "cnt_x": "count", "cnt_y": "count", "cnt_same": "count",
    "pct": "percent", "logv": "log-scale", "ord_stage": "ordinal code",
    "nom_site": "nominal code", "z1": "z-score", "z2": "z-score",
    "when": "datetime",
}


@pytest.fixture
def groups(df):
    return composition_groups(df, list(TYPES), TYPES)


def ids(rep):
    return {f.id for f in rep.findings}


# ── S-R01 ~ S-R14, 각각 걸리는 경우와 안 걸리는 경우 ──────────
def test_sr01_composition_correlation(df, groups):
    assert "S-R01" in ids(judge_pair(OP_CORRELATE, "fA", "fB", TYPES, df, groups))
    # 같은 조성이 아니면 상관 자체는 문제가 아니다
    assert "S-R01" not in ids(judge_pair(OP_CORRELATE, "fA", "lone_frac", TYPES, df, groups))
    # 비교(compare)는 S-R01이 아니라 S-R02의 몫이다
    assert "S-R01" not in ids(judge_pair(OP_COMPARE, "fA", "fB", TYPES, df, groups))


def test_sr02_proportion_comparison(df, groups):
    rep = judge_pair(OP_COMPARE, "fA", "fB", TYPES, df, groups)
    assert "S-R02" in ids(rep)
    f = next(x for x in rep.findings if x.id == "S-R02")
    # 같은 조성이면 세트 전체를 CLR해야 한다 — 2개만 고치면 기하평균이 달라진다
    assert f.composition == ["fA", "fB", "fC"] and f.fix_action == "clr"

    lone = judge_pair(OP_COMPARE, "fA", "lone_frac", TYPES, df, groups)
    assert next(x for x in lone.findings if x.id == "S-R02").fix_action == "logit"


def test_sr03_count_depth(df, groups):
    assert "S-R03" in ids(judge_pair(OP_CORRELATE, "cnt_x", "cnt_y", TYPES, df, groups))
    # 총합이 같으면 깊이 문제가 아니다
    assert "S-R03" not in ids(judge_pair(OP_CORRELATE, "cnt_x", "cnt_same", TYPES, df, groups))


def test_sr04_count_log_is_handled_by_derive():
    """S-R04(count에 log)는 수식 경로에서 eps로 막는다 — 쌍 판정의 일이 아니다."""
    from statop.semantic_risk import risks_for

    assert "S-R04" in {r["id"] for r in risks_for("count")}


def test_sr05_probability_spread(df, groups):
    assert "S-R05" in ids(judge_pair(OP_SPREAD, "prob", "z1", TYPES, df, groups))
    assert "S-R05" not in ids(judge_pair(OP_CORRELATE, "prob", "z1", TYPES, df, groups))


def test_sr06_scale_mixture(df, groups):
    rep = judge_pair(OP_CORRELATE, "logv", "cnt_x", TYPES, df, groups)
    assert "S-R06" in ids(rep)
    f = next(x for x in rep.findings if x.id == "S-R06")
    assert f.fix_action == "unify_scale" and f.targets == ["cnt_x"]   # 원척도 쪽을 올린다
    # 둘 다 log면 섞인 게 아니다
    both = {**TYPES, "cnt_x": "log-scale"}
    assert "S-R06" not in ids(judge_pair(OP_CORRELATE, "logv", "cnt_x", both, df, groups))


def test_sr07_percent_vs_fraction(df, groups):
    rep = judge_pair(OP_CORRELATE, "pct", "fA", TYPES, df, groups)
    assert "S-R07" in ids(rep)
    assert next(x for x in rep.findings if x.id == "S-R07").targets == ["pct"]
    assert "S-R07" not in ids(judge_pair(OP_CORRELATE, "pct", "cnt_x", TYPES, df, groups))


def test_sr08_ordinal_mean(df, groups):
    assert "S-R08" in ids(judge_pair(OP_COMPARE, "ord_stage", "cnt_x", TYPES, df, groups))
    assert "S-R08" not in ids(judge_pair(OP_CORRELATE, "ord_stage", "cnt_x", TYPES, df, groups))


def test_sr09_nominal_as_continuous_is_gate(df, groups):
    rep = judge_pair(OP_REGRESS, "nom_site", "cnt_x", TYPES, df, groups)
    assert "S-R09" in ids(rep) and rep.verdict == "gate"
    # 군으로 비교하는 것은 이름뿐인 코드의 정상 용법이다
    assert "S-R09" not in ids(judge_pair(OP_COMPARE, "nom_site", "cnt_x", TYPES, df, groups))


def test_sr10_id_as_variable_is_gate(df, groups):
    rep = judge_pair(OP_CORRELATE, "pid", "cnt_x", TYPES, df, groups)
    assert "S-R10" in ids(rep) and rep.verdict == "gate"
    assert "S-R10" not in ids(judge_pair(OP_CORRELATE, "cnt_x", "cnt_same", TYPES, df, groups))


def test_sr11_aggregate_with_stratifier(df, groups):
    rep = judge_set(OP_AGGREGATE, ["nom_site", "cnt_x"], TYPES, df, groups)
    assert "S-R11" in ids(rep)
    assert "S-R11" not in ids(judge_set(OP_AGGREGATE, ["cnt_x", "cnt_same"], TYPES, df, groups))


def test_sr12_zscore_reference(df, groups):
    assert "S-R12" in ids(judge_pair(OP_CORRELATE, "z1", "z2", TYPES, df, groups))
    assert "S-R12" not in ids(judge_pair(OP_CORRELATE, "z1", "cnt_x", TYPES, df, groups))


def test_sr13_datetime_leakage(df, groups):
    assert "S-R13" in ids(judge_pair(OP_REGRESS, "when", "cnt_x", TYPES, df, groups))
    assert "S-R13" not in ids(judge_pair(OP_COMPARE, "when", "cnt_x", TYPES, df, groups))


def test_sr14_unconfirmed_defers_everything(df, groups):
    """미확정이면 다른 규칙을 보지 않는다 — 추론값으로 경고하면 틀린 경고가 쌓인다."""
    partial = {k: v for k, v in TYPES.items() if k != "fB"}
    rep = judge_pair(OP_CORRELATE, "fA", "fB", partial, df, groups)
    assert rep.blocked and ids(rep) == {"S-R14"} and rep.verdict == "unconfirmed"
    assert rep.unconfirmed == ["fB"]


# ── 판정 범위·순서 (, 9.3) ───────────────────────────────
def test_set_summary_does_not_explode_per_pair(df, groups):
    """컬럼 n개에서 nC2 경고를 쏟지 않는다 — 규칙당 1건이어야 한다."""
    rep = judge_set(OP_CORRELATE, list(TYPES), TYPES, df, groups)
    counts = {}
    for f in rep.findings:
        counts[f.id] = counts.get(f.id, 0) + 1
    assert all(v == 1 for v in counts.values()), counts
    assert len(rep.findings) < 10        # 16컬럼이면 쌍은 120개다


def test_findings_are_ordered_gate_red_yellow(df, groups):
    rep = judge_set(OP_CORRELATE, list(TYPES), TYPES, df, groups)
    order = [f.verdict for f in rep.findings]
    rank = {"gate": 0, "red": 1, "yellow": 2}
    assert order == sorted(order, key=lambda v: rank[v])
    assert rep.verdict == "gate"          # 가장 센 것이 전체 판정


def test_composition_groups_found(df):
    assert composition_groups(df, list(TYPES), TYPES) == [["fA", "fB", "fC"]]


# ── 수정 계획 (~) ────────────────────────────────────
def test_plan_clr_covers_whole_set(df, groups):
    from statop.compat_fix import plan

    f = next(x for x in judge_pair(OP_CORRELATE, "fA", "fB", TYPES, df, groups).findings
             if x.id == "S-R01")
    p = plan(f)
    assert [d["name"] for d in p.derives] == ["fA_clr", "fB_clr", "fC_clr"]
    assert p.needs_eps and all(d["composition"] == ["fA", "fB", "fC"] for d in p.derives)


def test_plan_alr_for_two_part_set(df):
    from statop.compat_fix import plan

    a = np.random.default_rng(2).uniform(0.1, 0.9, 60)
    two = pd.DataFrame({"a": a, "b": 1 - a})
    t = {"a": "proportion", "b": "proportion"}
    g = composition_groups(two, ["a", "b"], t)
    f = next(x for x in judge_pair(OP_CORRELATE, "a", "b", t, two, g).findings
             if x.id == "S-R01")
    assert f.fix_action == "alr"
    p = plan(f, reference="b")
    assert [d["expr"] for d in p.derives] == ["alr(a, b)"]
    assert p.replaces == [("a", "a_alr")]


def test_plan_asks_for_composition_when_unknown(df, groups):
    """세트를 모르면 추측하지 않는다  — 세트가 달라지면 값이 통째로 달라진다."""
    from statop.compat import Finding
    from statop.compat_fix import plan

    f = Finding(id="S-R02", verdict="red", scope="pair", columns=["x"],
                fix_action="clr", targets=["x"])
    assert plan(f).needs_composition


def test_plan_rejects_rule_without_auto_fix(df, groups):
    from statop.compat_fix import plan

    f = next(x for x in judge_pair(OP_COMPARE, "ord_stage", "cnt_x", TYPES, df, groups).findings
             if x.id == "S-R08")
    assert f.fix_action is None
    with pytest.raises(ValueError, match="자동 수정이 없습니다"):
        plan(f)


# ── CLI 왕복  ─────────────────────────────────────
def _session(runner, path, tmp_home):
    import os

    os.environ["STATOP_HOME"] = str(tmp_home)
    r = runner.invoke(app, ["session", "new", "--data", str(path)])
    assert r.exit_code == 0
    return next(Path(tmp_home).glob("*/tmp/session_*.json")).as_posix()


def test_cli_defers_until_types_confirmed(tmp_path, df):
    """선택 직후에는 경고를 쏟지 않는다 — 확정을 먼저 요구한다 ( 타이밍)."""
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p, tmp_path / "home")
    runner.invoke(app, ["select", str(p), "--cols", "fA,fB,fC", "--session", sess])

    r = runner.invoke(app, ["compat", "check", "--session", sess, "--op", "correlate",
                            "--cols", "fA,fB"])
    assert r.exit_code == 0 and "보류" in r.output and "S-R01" not in r.output

    for c in ("fA", "fB", "fC"):
        runner.invoke(app, ["types", "--session", sess, "--confirm", c, "--as", "proportion"])
    r2 = runner.invoke(app, ["compat", "check", "--session", sess, "--op", "correlate",
                             "--cols", "fA,fB"])
    assert "S-R01" in r2.output and "clr" in r2.output


def test_cli_fix_replaces_designation_and_rejudges(tmp_path, df):
    """고친 뒤 원본은 분석에서 빠지고 새 컬럼이 자리를 받는다 ."""
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p, tmp_path / "home")
    runner.invoke(app, ["select", str(p), "--cols", "fA,fB,fC", "--session", sess])
    for c in ("fA", "fB", "fC"):
        runner.invoke(app, ["types", "--session", sess, "--confirm", c, "--as", "proportion"])

    dry = runner.invoke(app, ["compat", "fix", "--session", sess, "--op", "correlate",
                              "--cols", "fA,fB", "--rule", "S-R01"])
    assert "fA_clr" in dry.output and "계획만" in dry.output
    assert not json.loads(Path(sess).read_text())["ops"][-1]["op"] == "replace"

    noeps = runner.invoke(app, ["compat", "fix", "--session", sess, "--op", "correlate",
                                "--cols", "fA,fB", "--rule", "S-R01", "--apply"])
    assert noeps.exit_code != 0          # eps 없이는 기록하지 않는다

    ok = runner.invoke(app, ["compat", "fix", "--session", sess, "--op", "correlate",
                             "--cols", "fA,fB", "--rule", "S-R01",
                             "--eps", "1e-8", "--apply"])
    assert ok.exit_code == 0 and "재판정: green" in ok.output

    from statop.session.core import load_session, replay

    st = replay(load_session(sess))
    sid = next(iter(st["selected"]))
    assert st["replaced"][sid] == {"fA": "fA_clr", "fB": "fB_clr", "fC": "fC_clr"}
    assert "fA" in st["selected"][sid] and "fA" not in st["analysis"][sid]
    assert st["semantic_types"][sid]["fA_clr"] == "clr"   # 수식이 정한 타입은 확정이다


def test_cli_rejects_unknown_operation(tmp_path, df):
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p, tmp_path / "home")
    runner.invoke(app, ["select", str(p), "--cols", "fA,fB", "--session", sess])
    r = runner.invoke(app, ["compat", "check", "--session", sess, "--op", "cluster"])
    assert r.exit_code != 0 and "correlate" in r.output
