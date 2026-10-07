"""M1-1 의미 타입 판별 (DECISIONS) — 순위만, 점수는 감춘다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.semantic import (SHAPE_KEYS, Candidate, composition_set, infer, infer_columns,
                           shape_label)
from statop.semantic_risk import risks_for, risks_for_pair

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))


@pytest.fixture()
def frame():
    rng = np.random.default_rng(0)
    n = 2000
    comp = rng.dirichlet([2, 3, 5], n)
    return pd.DataFrame({
        "comp_a": comp[:, 0], "comp_b": comp[:, 1], "comp_c": comp[:, 2],
        "prob_pred": rng.beta(0.3, 0.3, n),         # 0/1 근처 집중 — 확률의 전형
        "norm": np.linspace(0, 1, n),               # min·max 정확히 0·1
        "counts": rng.poisson(4, n).astype(float),
        "log2fc": rng.normal(0, 1.5, n),
        "binary": rng.integers(0, 2, n).astype(float),
        "pid": [f"PT{i}" for i in range(n)],
    })


def test_composition_ranks_proportion_first(frame):
    by = {t.column: t for t in infer_columns(frame, ["comp_a", "comp_b", "comp_c"])}
    assert by["comp_a"].candidates[0].type == "proportion"    # 행 합 ≈ 1이 가장 강한 신호
    assert "행 합" in by["comp_a"].candidates[0].evidence[0]


def test_composition_set_found_with_missing_values():
    """결측이 있으면 행 합이 1이 안 된다 — 완전한 행만 보고 판단해야 한다."""
    rng = np.random.default_rng(1)
    comp = rng.dirichlet([1, 1, 1], 500)
    df = pd.DataFrame({"a": comp[:, 0], "b": comp[:, 1], "c": comp[:, 2],
                       "noise": rng.uniform(0, 1, 500)})
    df.loc[:100, "b"] = np.nan
    assert composition_set(df, "a") == {"a", "b", "c"}
    assert composition_set(df, "noise") == set()


def test_partial_composition_warns(frame):
    """세트 일부만 가져오면 CLR을 쓸 수 없다는 사실을 알린다."""
    t = infer_columns(frame, ["comp_a", "counts"])[0]
    assert any("일부만" in c for c in t.conflicts) and t.needs_confirm


def test_shape_words(frame):
    by = {t.column: t for t in infer_columns(frame, list(frame.columns))}
    assert by["prob_pred"].shape == "bimodal_ends"     # U자 → 양끝 집중
    assert by["norm"].shape == "flat"
    assert by["counts"].shape == "unimodal"


def test_shape_codes_are_language_independent():
    """형태 비교는 코드로 — 한국어 문자열로 비교하면 --lang en에서 깨진다."""
    rng = np.random.default_rng(4)
    t = infer(pd.Series(rng.normal(0, 1, 500)), "x")
    assert t.shape in SHAPE_KEYS
    assert shape_label(t.shape) and shape_label("flat")


def test_one_sided_skew_is_not_bimodal():
    rng = np.random.default_rng(2)
    t = infer(pd.Series(rng.lognormal(1, 1, 2000)), "sk")
    assert t.shape == "skewed"                         # 한쪽만 몰린 건 쌍봉이 아니다


def test_scores_never_exposed(frame):
    """점수는 의존 편향을 만든다 — 순위만 노출 ."""
    t = infer_columns(frame, ["prob_pred"])[0]
    assert all(hasattr(c, "rank") for c in t.candidates)
    assert "_score" not in repr(t.candidates[0])       # repr=False


def test_tied_candidates_share_rank():
    c = infer(pd.Series([0.1, 0.5, 0.9] * 100), "x").candidates
    ranks = [x.rank for x in c]
    assert ranks == sorted(ranks)
    if ranks.count(1) > 1:                             # 공동 1위면 다음은 건너뛴 번호
        assert 2 not in ranks


def test_binary_int_trap_flagged(frame):
    """0/1 정수 — 이진 코드인지 카운트인지 값만으로는 모른다 (S-T01 함정)."""
    t = infer_columns(frame, ["binary"])[0]
    types = {c.type for c in t.candidates}
    assert {"nominal code", "count"} <= types
    assert t.needs_confirm and any("이진" in c for c in t.conflicts)


def test_costly_pair_requires_confirm():
    """probability ↔ proportion은 순위가 갈려도 확정을 요구한다 (오분류 비용)."""
    rng = np.random.default_rng(3)
    t = infer(pd.Series(rng.uniform(0.05, 0.95, 1000)), "v")
    assert t.needs_confirm


def test_identifier_detected(frame):
    t = infer_columns(frame, ["pid"])[0]
    assert t.candidates[0].type == "id"


# ── 위험 고지 (요구사항-7: 막지 않고 설명한다) ──────────────
def test_risks_come_from_rule_db():
    r = risks_for("proportion")
    assert {x["id"] for x in r} == {"S-R01", "S-R02"}
    assert all(x["why"] and x["fix"] for x in r)
    assert risks_for("continuous") == []               # 등록된 규칙이 없으면 빈 목록


def test_ratio_by_ratio_pair_warns():
    """ratio끼리 비교하면 안 되는 이유를 규칙에서 가져온다."""
    r = risks_for_pair("proportion", "proportion")
    assert any("spurious correlation" in x["why"] for x in r)
    assert any("CLR" in x["fix"] for x in r)


def test_cli_lists_and_confirms(tmp_path, frame):
    from statop.session.core import load_session, replay
    from statop.store import tmp_dir

    p = tmp_path / "f.csv"
    frame.to_csv(p, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(p)])
    sess = str(next(tmp_dir().glob("session_*.json")))
    runner.invoke(app, ["select", str(p), "--cols", "comp_a,counts", "--session", sess])

    r = runner.invoke(app, ["types", "--session", sess, "--sample-n", "2000"])
    assert r.exit_code == 0
    assert "1. proportion" in r.output or "1. probability" in r.output
    assert "확정 0개" in r.output

    ok = runner.invoke(app, ["types", "--session", sess, "--confirm", "counts",
                             "--as", "count", "--sample-n", "2000"])
    assert ok.exit_code == 0 and "의미 타입 확정: counts = count" in ok.output
    assert "S-R03" in ok.output          # 이 타입으로 계산할 때의 위험을 고지

    st = replay(load_session(sess))
    src = next(iter(st["semantic_types"]))
    assert st["semantic_types"][src]["counts"] == "count"


def test_cli_allows_unusual_type_but_warns(tmp_path, frame):
    from statop.store import tmp_dir

    p = tmp_path / "f.csv"
    frame.to_csv(p, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(p)])
    sess = str(next(tmp_dir().glob("session_*.json")))
    runner.invoke(app, ["select", str(p), "--cols", "counts", "--session", sess])

    # 추론에 없던 타입도 확정할 수 있다 — 막지 않고 고지한다
    r = runner.invoke(app, ["types", "--session", sess, "--confirm", "counts",
                            "--as", "proportion", "--sample-n", "2000"])
    assert r.exit_code == 0
    assert "추론 후보에 없는 타입" in r.output
    assert "S-R01" in r.output and "CLR" in r.output

    bad = runner.invoke(app, ["types", "--session", sess, "--confirm", "counts",
                              "--as", "완전히모르는타입"])
    assert bad.exit_code != 0


# ── 조성 탐색 비용 (실제로 TUI 가 19초 멈췄다) ───────────────
def test_the_composition_search_runs_once_per_column():
    """타입 추론은 컬럼마다 이걸 두 번 묻는다 — 프레임이 같으면 답도 같다.

    두 번씩 돌면 25컬럼 추론이 19초였다. 화면은 '추론 중'에서 멈춰 있고 아무것도
    눌리지 않는다.
    """
    import statop.semantic as sem

    rng = np.random.default_rng(0)
    n, m = 300, 12
    raw = rng.random((n, m))
    df = pd.DataFrame({f"f{i}": raw[:, i] / raw.sum(axis=1) for i in range(m)})
    df["noise"] = rng.normal(0, 1, n)

    calls = []
    real = sem._composition_set
    sem._composition_set = lambda d, name: (calls.append(name), real(d, name))[1]
    try:
        infer_columns(df, list(df.columns))
    finally:
        sem._composition_set = real
    assert len(calls) == len(set(calls)) == len(df.columns), calls


def test_the_faster_search_finds_the_same_set():
    """빠르게 고쳤다고 판정이 달라지면 안 된다 — 결측이 섞인 세트로 확인한다."""
    rng = np.random.default_rng(1)
    n = 200
    raw = rng.random((n, 4))
    parts = raw / raw.sum(axis=1, keepdims=True)
    df = pd.DataFrame({f"p{i}": parts[:, i] for i in range(4)})
    df.loc[df.index[:5], "p2"] = np.nan          # 완전한 행만 보고 판단한다
    df["unrelated"] = rng.normal(0, 1, n)
    df["also_small"] = rng.random(n) * 0.2       # 0~1 이지만 조성 성분이 아니다

    for c in ("p0", "p1", "p2", "p3"):
        assert composition_set(df, c) == {"p0", "p1", "p2", "p3"}, c
    assert composition_set(df, "unrelated") == set()
    assert composition_set(df, "also_small") == set()


def test_a_sliced_frame_does_not_inherit_the_wrong_answer():
    """pandas 는 잘라낸 프레임에 attrs 를 물려준다 — 컬럼이 다르면 답도 다르다."""
    rng = np.random.default_rng(2)
    n = 120
    raw = rng.random((n, 3))
    parts = raw / raw.sum(axis=1, keepdims=True)
    df = pd.DataFrame({f"p{i}": parts[:, i] for i in range(3)})
    assert composition_set(df, "p0") == {"p0", "p1", "p2"}
    half = df[["p0", "p1"]]            # 세트의 일부만 — 더 이상 합이 1 이 아니다
    assert composition_set(half, "p0") == set()


def test_cli_can_take_a_confirmation_back(tmp_path, frame):
    """CLI 에서도 되돌릴 수 있어야 한다 — 세 껍데기가 같은 조작을 남긴다."""
    from statop.session.core import load_session, main_source, replay
    from statop.store import tmp_dir

    p = tmp_path / "f.csv"
    frame.to_csv(p, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(p)])
    sess = str(next(tmp_dir().glob("session_*.json")))
    runner.invoke(app, ["select", str(p), "--cols", "comp_a,counts", "--session", sess])
    runner.invoke(app, ["types", "--session", sess, "--confirm", "counts", "--as", "count"])

    def confirmed() -> dict:
        doc = load_session(sess)
        return replay(doc)["semantic_types"].get(main_source(doc)["id"], {})

    assert confirmed().get("counts") == "count"
    r = runner.invoke(app, ["types", "--session", sess, "--unconfirm", "counts"])
    assert r.exit_code == 0, r.output
    assert "counts" not in confirmed()

    again = runner.invoke(app, ["types", "--session", sess, "--unconfirm", "counts"])
    assert again.exit_code != 0        # 취소할 것이 없으면 그렇다고 말한다
