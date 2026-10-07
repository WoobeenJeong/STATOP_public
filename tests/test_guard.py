"""M4 가드레일 회귀 — 잠금과 GR-01~04 검사.

검사마다 **걸리는 경우와 안 걸리는 경우**를 함께 본다. 한쪽만 보면
"전부 경고"로 통과하는 엔진이 만들어진다.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.guard import checks, locks
from statop.guard.pipeline import headline, run
from statop.guard.report import to_dict, to_markdown


@pytest.fixture
def lock_file(tmp_path):
    return tmp_path / "overrides.json"


# ── · 값 잠금 ────────────────────────────────────────
def test_base_values_are_read_only(lock_file):
    """조정해도 기준값은 그대로다 — 무엇이 바뀌었는지 항상 되짚을 수 있어야 한다."""
    before = dict(locks.BASE_THRESHOLDS["GR-02"])
    locks.set_threshold("GR-02", "p_threshold", 0.01, lock_file)
    assert locks.BASE_THRESHOLDS["GR-02"] == before
    lim = locks.limits("GR-02", lock_file)["p_threshold"]
    assert lim.value == 0.01 and lim.base == 0.0005 and lim.overridden


def test_gate_floor_cannot_be_relaxed(lock_file):
    """GR-03은 floor가 gate — 낮추는 경로가 아예 없다 ."""
    assert locks.floor("GR-03") == "gate"
    for tier in ("diagnostic", "info", "off"):
        with pytest.raises(locks.LockError, match="아래로 낮출 수 없습니다"):
            locks.set_tier("GR-03", tier, lock_file)
    assert locks.tier_of("GR-03", lock_file) == "gate"


def test_relaxation_allowed_down_to_floor(lock_file):
    locks.set_tier("GR-02", "diagnostic", lock_file)     # floor가 diagnostic
    assert locks.tier_of("GR-02", lock_file) == "diagnostic"
    with pytest.raises(locks.LockError):
        locks.set_tier("GR-02", "off", lock_file)


def test_hand_edited_file_cannot_sneak_below_floor(lock_file):
    """파일을 직접 고쳐도 floor 아래로는 적용되지 않는다 — 우회로를 막는다."""
    import json

    lock_file.write_text(json.dumps({"GR-03": {"tier": "off"}}))
    assert locks.tier_of("GR-03", lock_file) == "gate"


def test_clip_cannot_become_a_default(lock_file):
    """clip은 분포를 왜곡한다 — 기본값으로 굳어지면 안 된다."""
    with pytest.raises(locks.LockError, match="기본값으로 둘 수 없습니다"):
        locks.set_threshold("GR-01", "action", "clip", lock_file)
    locks.set_threshold("GR-01", "action", "drop", lock_file)   # 나머지는 허용


def test_unknown_rule_and_threshold_rejected(lock_file):
    with pytest.raises(locks.LockError):
        locks.set_tier("GR-99", "gate", lock_file)
    with pytest.raises(locks.LockError):
        locks.set_threshold("GR-02", "nope", 1, lock_file)


def test_active_overrides_are_reported(lock_file):
    assert locks.active_overrides(lock_file) == []
    locks.set_threshold("GR-04", "min_group_n", 3, lock_file)
    keys = {(x.rule, x.key) for x in locks.active_overrides(lock_file)}
    assert ("GR-04", "min_group_n") in keys
    locks.clear(path=lock_file)
    assert locks.active_overrides(lock_file) == []


# ── GR-01 정의역  ──────────────────────────────────────
def test_gr01_separates_impossible_from_unusual():
    df = pd.DataFrame({"p": [0.1, 0.5, 1.3, -0.2], "c": [1, 2, 3, -4]})
    sigs = checks.out_of_range(df, {"p": "probability", "c": "count"})
    by = {(s.check, s.columns[0]) for s in sigs}
    assert ("impossible", "p") in by and ("impossible", "c") in by
    assert all(s.tier_hint == "gate" for s in sigs if s.check == "impossible")

    clean = pd.DataFrame({"p": [0.1, 0.5, 0.9] * 5})
    assert not [s for s in checks.out_of_range(clean, {"p": "probability"})
                if s.check == "impossible"]


def test_gr01_boundary_is_diagnostic_not_gate():
    """0과 1은 틀린 값이 아니다 — 다만 log·logit이 정의되지 않는다."""
    df = pd.DataFrame({"p": [0.0, 1.0, 0.5, 0.3]})
    sigs = [s for s in checks.out_of_range(df, {"p": "probability"})
            if s.check == "boundary"]
    assert len(sigs) == 1 and sigs[0].tier_hint == "diagnostic"
    assert sigs[0].numbers["n"] == 2


def test_gr01_actions_change_data_only_when_asked():
    df = pd.DataFrame({"p": [0.5, 1.3, -0.2]})
    kept, n = checks.apply_action(df, "p", "probability", "flag")
    assert len(kept) == 3 and n == 0            # flag는 아무것도 바꾸지 않는다

    dropped, n = checks.apply_action(df, "p", "probability", "drop")
    assert len(dropped) == 1 and n == 2

    clipped, n = checks.apply_action(df, "p", "probability", "clip")
    assert list(clipped["p"]) == [0.5, 1.0, 0.0] and n == 2


# ── GR-02 SRM  ─────────────────────────────────────────
def test_gr02_srm_fires_only_on_real_skew():
    assert checks.srm({"a": 500, "b": 500}).hit is False
    assert checks.srm({"a": 600, "b": 400}).hit is True
    # 기대 비율이 2:1이면 600:300은 정상이다 — 균등으로 검정하면 틀린 경고가 된다
    assert checks.srm({"a": 600, "b": 300}, {"a": 2, "b": 1}).hit is False
    assert checks.srm({"a": 600, "b": 300}).hit is True


def test_gr02_dimensional_uses_bonferroni():
    rng = np.random.default_rng(1)
    n = 600
    site = rng.choice(["A", "B"], n)
    arm = np.where((site == "A") & (rng.random(n) < 0.8), "case", "control")
    df = pd.DataFrame({"arm": arm, "site": site})
    sigs = checks.srm_by_dimension(df, "arm", ["site"], None, 0.0005)
    assert sigs and all(s.numbers["p_threshold_adjusted"] < 0.0005 for s in sigs)


def test_gr02_counterfactual_distinguishes_loss_from_design():
    """손실을 되돌려 SRM이 풀리면 손실이 후보, 안 풀리면 다른 원인이다 ()."""
    kept = pd.DataFrame({"g": ["a"] * 600 + ["b"] * 400})
    lost = pd.DataFrame({"g": ["b"] * 200})
    assert checks.srm_counterfactual(kept, lost, "g")["resolved"] is True

    # 손실이 균형적이면 되돌려도 안 풀린다 — 손실 탓이 아니다
    lost_even = pd.DataFrame({"g": ["a"] * 50 + ["b"] * 50})
    assert checks.srm_counterfactual(kept, lost_even, "g")["resolved"] is False
    assert checks.srm_counterfactual(kept, None, "g")["available"] is False


# ── GR-03 손실  ────────────────────────────────────────
def test_gr03_detects_biased_loss_but_not_random_loss():
    rng = np.random.default_rng(3)
    n = 800
    df = pd.DataFrame({"arm": rng.choice(["a", "b"], n),
                       "age": rng.normal(60, 10, n)})
    biased = df.index[(df["arm"] == "a") | (rng.random(n) < 0.5)]
    assert [s for s in checks.biased_loss(df, biased, ["arm"]) if s.check == "biased_loss"]

    random_keep = df.index[rng.random(n) < 0.6]
    assert checks.biased_loss(df, random_keep, ["arm", "age"]) == []


def test_gr03_loss_by_group_reports_spread():
    df = pd.DataFrame({"g": ["a"] * 100 + ["b"] * 100})
    kept = list(range(100)) + list(range(100, 150))      # b만 절반 손실
    sig = checks.loss_by_group(df, kept, "g")
    assert sig.hit and sig.numbers["by_group"]["a"] == 0.0
    assert sig.numbers["by_group"]["b"] == pytest.approx(0.5)


def test_gr03_retention_funnel_counts_each_step():
    steps = [{"label": "filter", "n_before": 1000, "n_after": 800},
             {"label": "dropna", "n_before": 800, "n_after": 790}]
    sigs = checks.retention_funnel(steps)
    assert [s.numbers["lost"] for s in sigs] == [200, 10]


def test_gr03_join_rate_gate_vs_warn():
    assert checks.join_rate(1000, 850).tier_hint == "gate"
    assert checks.join_rate(1000, 950).tier_hint == "diagnostic"
    assert checks.join_rate(1000, 1000).hit is False


# ── GR-04 불균형  ──────────────────────────────────────
def test_gr04_small_group_grades():
    tiny = pd.DataFrame({"g": ["a"] * 50 + ["b"] * 3})
    assert any(s.check == "tiny_group" and s.tier_hint == "gate"
               for s in checks.group_balance(tiny, "g"))

    small = pd.DataFrame({"g": ["a"] * 50 + ["b"] * 7})
    assert any(s.check == "small_group" for s in checks.group_balance(small, "g"))

    fine = pd.DataFrame({"g": ["a"] * 50 + ["b"] * 45})
    assert checks.group_balance(fine, "g") == []


def test_gr04_coverage_flags_partial_metrics():
    df = pd.DataFrame({"m": [1.0] * 50 + [np.nan] * 50})
    assert checks.coverage(df, ["m"], 0.80)
    assert checks.coverage(df, ["m"], 0.40) == []


def test_gr04_smd_catches_balance_that_only_looks_balanced():
    """라벨은 50:50인데 메타가 편중된 경우 — 겉보기 균형."""
    rng = np.random.default_rng(7)
    n = 4000                      # SMD 0.1 임계는 표본이 작으면 우연만으로도 걸린다
    arm = np.array(["a", "b"] * (n // 2))
    age = np.where(arm == "a", rng.normal(50, 8, n), rng.normal(65, 8, n))
    df = pd.DataFrame({"arm": arm, "age": age})
    assert dict(df["arm"].value_counts()) == {"a": n // 2, "b": n // 2}
    assert [s for s in checks.smd_imbalance(df, "arm", ["age"]) if s.numbers["smd"] > 1]

    same = pd.DataFrame({"arm": arm, "age": rng.normal(60, 8, n)})
    assert checks.smd_imbalance(same, "arm", ["age"]) == []


def test_gr04_metric_stability_only_for_small_groups():
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"g": ["big"] * 60 + ["small"] * 6,
                       "v": rng.normal(10, 3, 66)})
    sigs = checks.metric_stability(df, "g", "v", min_n=10)
    assert len(sigs) == 1 and sigs[0].numbers["n"] == 6


# ──  파이프라인 ──────────────────────────────────────────
@pytest.fixture
def loss_case():
    rng = np.random.default_rng(9)
    n = 1000
    arm = rng.choice(["control", "case"], n)
    qc = np.where(arm == "case", rng.random(n) * 0.5, rng.random(n))
    before = pd.DataFrame({"arm": arm, "site": rng.choice(["A", "B"], n),
                           "vaf": np.clip(rng.beta(2, 8, n), 0, 1)})
    kept = before[qc >= 0.3]
    steps = [{"label": "qc", "n_before": len(before), "n_after": len(kept)}]
    return before, kept, steps


def test_pipeline_runs_in_diagnostic_order(loss_case, lock_file):
    before, kept, steps = loss_case
    rep = run(kept, {"vaf": "proportion"}, group_col="arm", meta_cols=["site"],
              metric_cols=["vaf"], df_before=before, kept_index=kept.index,
              retention_steps=steps, lock_path=lock_file)
    seen = [f.rule for f in rep.findings]
    assert seen == sorted(seen, key=lambda r: rep.order.index(r))
    assert rep.tier == "gate" and headline(rep)


def test_pipeline_links_srm_to_loss(loss_case, lock_file):
    """앞 검사 결과가 뒤 검사의 입력이다 — 연결을 표시하되 인과는 단정하지 않는다."""
    before, kept, steps = loss_case
    rep = run(kept, {}, group_col="arm", meta_cols=["site"], df_before=before,
              kept_index=kept.index, retention_steps=steps, lock_path=lock_file)
    srm = next(f for f in rep.findings if f.check == "srm")
    assert "GR-03:loss_by_group" in srm.links
    assert rep.cause_trace["candidate"] == "loss"
    assert rep.cause_trace["counterfactual"]["resolved"] is True


def test_pipeline_says_what_it_did_not_check(lock_file):
    """검사하지 않은 것과 통과한 것은 다르다."""
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    rep = run(df, {}, lock_path=lock_file)
    skipped = {s["rule"] for s in rep.skipped}
    assert {"GR-01", "GR-02", "GR-03", "GR-04"} <= skipped
    assert rep.tier == "ok" and headline(rep) is None


def test_pipeline_respects_relaxed_tier(loss_case, lock_file):
    """등급을 낮추면 차단이 진단으로 내려간다 — 단, floor까지만."""
    before, kept, steps = loss_case
    locks.set_tier("GR-02", "diagnostic", lock_file)
    rep = run(kept, {}, group_col="arm", df_before=before, kept_index=kept.index,
              retention_steps=steps, lock_path=lock_file)
    assert next(f for f in rep.findings if f.check == "srm").tier == "diagnostic"
    # GR-03은 floor가 gate라 그대로다
    assert any(f.rule == "GR-03" and f.tier == "gate" for f in rep.findings)
    assert any(o["key"] == "tier" for o in rep.overrides)


# ──  출력 ────────────────────────────────────────────────
def test_markdown_puts_gate_first(loss_case, lock_file):
    """스크롤해야 보이는 경고는 없는 것과 같다."""
    before, kept, steps = loss_case
    rep = run(kept, {"vaf": "proportion"}, group_col="arm", df_before=before,
              kept_index=kept.index, retention_steps=steps, lock_path=lock_file)
    md = to_markdown(rep)
    assert md.splitlines()[0].startswith("> **")
    assert md.index("차단") < md.index("# ")


def test_json_carries_numbers_not_just_text(loss_case, lock_file):
    before, kept, steps = loss_case
    rep = run(kept, {}, group_col="arm", df_before=before, kept_index=kept.index,
              retention_steps=steps, lock_path=lock_file)
    d = to_dict(rep)
    srm = next(f for f in d["findings"] if f["check"] == "srm")
    assert "p" in srm["numbers"] and "observed" in srm["numbers"]
    assert d["cause_trace"]["counterfactual"]["available"] is True


# ── CLI ──────────────────────────────────────────────────────
def test_cli_guard_floor_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    r = runner.invoke(app, ["guard", "set", "--rule", "GR-03", "--tier", "off"])
    assert r.exit_code != 0 and "gate" in r.output

    ok = runner.invoke(app, ["guard", "set", "--rule", "GR-04",
                             "--key", "min_group_n", "--value", "3"])
    assert ok.exit_code == 0
    lim = runner.invoke(app, ["guard", "limits", "--rule", "GR-04"])
    assert "조정됨" in lim.output
    runner.invoke(app, ["guard", "reset"])


def test_cli_guard_run_writes_report(tmp_path, monkeypatch, loss_case):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    before, _, _ = loss_case
    p = tmp_path / "d.csv"
    before.to_csv(p, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(p)])
    sess = next((tmp_path / "home").glob("*/tmp/session_*.json")).as_posix()
    runner.invoke(app, ["select", str(p), "--cols", "arm,site,vaf", "--session", sess])
    runner.invoke(app, ["types", "--session", sess, "--confirm", "vaf",
                        "--as", "proportion"])

    out = tmp_path / "r.json"
    r = runner.invoke(app, ["guard", "run", "--session", sess, "--group", "arm",
                            "--meta", "site", "--out", out.as_posix()])
    assert r.exit_code == 0 and out.exists()
    import json

    d = json.loads(out.read_text())
    assert d["order"] == ["GR-03", "GR-02", "GR-04", "GR-01"]
    # 손실 기록이 없으므로 GR-03은 검사하지 않았다고 말해야 한다
    assert any(s["rule"] == "GR-03" for s in d["skipped"])
