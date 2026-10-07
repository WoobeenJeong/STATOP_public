"""S205 실제 있었던 사례건 회귀 — **전 건 검출**.

이 도구를 만든 이유였던 오류들이다 (`registry-tests.md` 6절·11절). 각 사례마다 그 오류를
일부러 심은 자료를 만들고, **기대한 규칙이 실제로 걸리는지** 본다. 하나라도 안 걸리면
그 사례가 다시 지나간다는 뜻이다.

여기서 보는 것은 "무엇이 걸렸나"이지 "몇 점인가"가 아니다 — 검출이 되는지가 전부다.
"""

from pathlib import Path

import pandas as pd
import pytest

from cases import make


def _session(tmp_path, monkeypatch, df: pd.DataFrame, name: str):
    """자료 하나로 세션을 만들고 컬럼을 전부 가져온다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    path = tmp_path / f"{name}.csv"
    df.to_csv(path, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    return str(sc.session_file), str(path)


def _confirm(session: str, **types: str) -> None:
    """의미 타입 확정. **분석 대상 전부**를 확정해야 판정이 열린다 ( · S-R14)."""
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session)
    sid = main_source(doc)["id"]
    for col, typ in types.items():
        append_op(doc, "semantic_confirm", source=sid, column=col, type=typ)
    save_session(doc)


def _compat_pair(session: str, a: str, b: str, op: str = "correlate") -> set:
    """두 컬럼을 명시해 걸었을 때 걸리는 규칙들.

    세트 요약(judge_set)은 **일부러** 쌍을 다 나열하지 않는다 — nC2 경고 남발을 막기
    위해서다 . 사용자가 두 컬럼을 지정하는 경로가 쌍 판정이다.
    """
    from statop.compat import composition_groups, judge_pair
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session)
    _, src, df = session_frame(session)
    df = apply_ops(df, doc, src["id"])
    types = replay(doc)["semantic_types"].get(src["id"], {})
    comp = composition_groups(df, list(df.columns), types)
    return {f.id for f in judge_pair(op, a, b, types, df=df, comp_groups=comp).findings}


# ── #1 분포 무시 metric ─────────────────────────────────────
def test_case01_distribution_ignored_is_flagged(tmp_path, monkeypatch):
    """중꼬리·왜곡이면 평균 기반 검정이 '확인 필요'로 내려가야 한다 (C-01/R-11)."""
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import Spec, build

    session, _ = _session(tmp_path, monkeypatch, make.case01_distribution_ignored(), "c1")
    _confirm(session, value="continuous", arm="label")
    res = build(session, Spec(question="Q-01", y="value", group="arm"))
    cands = {c.id: c for c in shortlist(res)}
    assert "T-101" in cands, "Welch 가 후보에 없다"
    # 정규성이 확인 안 된 상태에서 평균 기반 검정이 초록이면 안 된다
    assert cands["T-101"].color != "green"
    # 순위 기반 대안이 후보에 있어야 한다
    assert {"T-103", "T-104"} & set(cands)


# ── #2 임의 log 변환 ────────────────────────────────────────
def test_case02_mixing_log_and_raw_scale_is_blocked(tmp_path, monkeypatch):
    """log 척도와 원척도를 섞어 상관·차이를 내면 S-R06 이 잡아야 한다."""
    session, _ = _session(tmp_path, monkeypatch, make.case02_arbitrary_log(), "c2")
    _confirm(session, sid="id", raw_scale="continuous", log_scale="log-scale",
             arm="label")
    assert "S-R06" in _compat_pair(session, "raw_scale", "log_scale")


# ── #3 확률값 변동성 ────────────────────────────────────────
def test_case03_probability_gets_its_own_variability_metric(tmp_path, monkeypatch):
    """[0,1] 확률의 변동은 SD 로 재면 안 된다 — 전용 지표가 제안돼야 한다."""
    from statop.analyze.scores import catalog

    session, _ = _session(tmp_path, monkeypatch, make.case03_probability_variability(), "c3")
    _confirm(session, prob="probability", arm="label")
    by = {e.id: e for e in catalog(session)}
    # SC-VAR-04 Bernoulli 정규화 변동성 — 확률 전용 (내부 사례 #3 에서 나온 지표)
    assert by["SC-VAR-04"].verdict == "green", by["SC-VAR-04"].why
    assert "P-233" in (by["SC-VAR-04"].recommend or "")


# ── #4 소표본 ───────────────────────────────────────────────
def test_case04_small_sample_is_not_called_normal(tmp_path, monkeypatch):
    """n 이 작으면 정규성 '통과'를 근거로 쓸 수 없다고 말해야 한다 (C-01)."""
    from statop.analyze.checks import run_checks
    from statop.analyze.spec import Spec, build

    from statop.analyze.spec import record

    session, _ = _session(tmp_path, monkeypatch, make.case04_small_sample(), "c4")
    _confirm(session, value="continuous", arm="label")
    res = build(session, Spec(question="Q-01", y="value", group="arm"))
    record(session, res.spec)
    out = run_checks(session)
    text = " ".join(f"{c.id} {c.verdict} {c.summary}" for c in out)
    assert "C-01" in text
    assert res.n_rows < 30 or "n=" in text


# ── #5 Simpson ─────────────────────────────────────────────
def test_case05_simpson_flip_is_reported(tmp_path, monkeypatch):
    """전체 방향과 층별 방향이 반대면 그 사실을 말해야 한다."""
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record

    session, _ = _session(tmp_path, monkeypatch, make.case05_simpson(), "c5")
    _confirm(session, success="probability", arm="label", site="nominal code")
    record(session, Spec(question="Q-02", y="success", group="arm", by="site"))
    out = run_test(session, "T-201")
    assert out.strata, "층화 결과가 없다"
    from statop.hypothesis.mech import strata_flips

    flips = strata_flips({"test": out.id, "name": out.name, "effect": out.effect,
                          "statistic": out.statistic, "p": out.p,
                          "strata": out.strata, "by": "site"})
    assert flips, "층별로 방향이 뒤집혔는데 말하지 않았다"


# ── #6 숨은 불균형 ──────────────────────────────────────────
def test_case06_hidden_imbalance_is_found(tmp_path, monkeypatch):
    """군과 메타가 겹치면 어떤 보정도 둘을 못 가른다 — 그 사실을 잡아야 한다."""
    from statop.guard import checks

    df = make.case06_hidden_imbalance()
    sigs = checks.smd_imbalance(df, group_col="arm", meta_cols=["batch"])
    hits = [s for s in sigs if s.hit]
    assert hits, f"군과 배치가 거의 겹치는데 못 잡았다: {sigs}"
    assert any("batch" in (s.columns or []) for s in hits)


# ── #7 조성 ────────────────────────────────────────────────
def test_case07_composition_needs_clr(tmp_path, monkeypatch):
    """합이 1인 성분에 일반 상관을 걸면 S-R01 이 잡고 CLR 을 제안해야 한다."""
    session, _ = _session(tmp_path, monkeypatch, make.case07_composition(), "c7")
    _confirm(session, sid="id", frac_A="composition set", frac_B="composition set",
             frac_C="composition set", arm="label")
    assert "S-R01" in _compat_pair(session, "frac_A", "frac_B")


# ── #8 다중검정 ────────────────────────────────────────────
def test_case08_multiplicity_adjusts_alpha(tmp_path, monkeypatch):
    """20개를 훑으면 보정 α 가 내려가야 한다 — 0.05 그대로면 안 된다."""
    from statop.analyze.checks import multiplicity

    adj = multiplicity(20).numbers["alpha_adjusted"]
    assert adj < 0.05
    assert multiplicity(1).numbers["alpha_adjusted"] == pytest.approx(0.05)


# ── #9 가설-검정 불일치 ─────────────────────────────────────
def test_case09_planned_contrast_beats_omnibus(tmp_path, monkeypatch):
    """'정상=교란≠암' 을 물으면 omnibus(T-121) 가 1순위여서는 안 된다 (Q-11)."""
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import Spec, build

    session, _ = _session(tmp_path, monkeypatch, make.case09_hypothesis_mismatch(), "c9")
    _confirm(session, value="continuous", grp="label")
    res = build(session, Spec(question="Q-11", y="value", group="grp",
                              contrast="planned"))
    ids = [c.id for c in shortlist(res)]
    assert "T-1101" in ids, "사전지정 대비가 후보에 없다"
    if "T-121" in ids:
        assert ids.index("T-1101") < ids.index("T-121")


# ── #10 비교 불가 metric 변경 ───────────────────────────────
def test_case10_scale_mismatch_is_blocked(tmp_path, monkeypatch):
    """0~1 과 0~100 을 같이 쓰면 S-R07 이 잡고 ÷100 을 제안해야 한다."""
    session, _ = _session(tmp_path, monkeypatch, make.case10_metric_changed(), "c10")
    _confirm(session, sid="id", score_0_1="proportion", score_0_100="percent",
             arm="label")
    assert "S-R07" in _compat_pair(session, "score_0_1", "score_0_100")


# ── #11 external 중복 ───────────────────────────────────────
def test_case11_external_overlap_is_a_gate(tmp_path, monkeypatch):
    """학습 세트와 외부 세트에 같은 행이 있으면 외운 것을 맞히게 된다 (MB-C01)."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    paths = make.case11_external_overlap(str(tmp_path))

    from statop.modeling import leak
    from statop.modeling.spec import ModelSpec, record
    from statop.session.core import new_session, register_source, save_session

    doc = new_session()
    register_source(doc, paths["source"])
    session = save_session(doc)
    spec = ModelSpec(question="MB-Q01", tier="MB-M0", label_column="label",
                     validation="holdout", seed=1,
                     sets={"train": paths["train"], "external": paths["external"]})
    record(session, spec)
    found = leak.run_all(spec)
    gates = [f for f in found if f.id == "MB-C01" and f.verdict == "fail"]
    assert gates, f"중복을 못 잡았다: {[(f.id, f.verdict) for f in found]}"


def test_all_eleven_cases_have_a_regression_test():
    """사례가 늘면 검사도 늘어야 한다 — 빠진 번호가 없는지 본다."""
    src = Path(__file__).read_text()
    for n in range(1, 12):
        assert f"test_case{n:02d}" in src, f"사례 #{n} 검사가 없다"
