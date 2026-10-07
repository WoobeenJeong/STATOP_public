"""M0-7 그룹 구조 감지 · M0-2b 구성 요약."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.groups import _kind_from_name, compose, detect

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))


@pytest.fixture()
def clustered():
    rng = np.random.default_rng(0)
    n = 300
    return pd.DataFrame({
        "patient_id": [f"PT{i // 3:03d}" for i in range(n)],   # 환자당 3회 반복
        "sample_id": [f"S{i:04d}" for i in range(n)],           # 식별자 (반복 없음)
        "batch": [f"B{i % 5}" for i in range(n)],
        "visit": [i % 3 for i in range(n)],
        "value": rng.normal(0, 1, n),                           # 연속형 — 그룹 아님
    })


def test_detects_repeats_and_identifiers(clustered):
    by = {g.column: g for g in detect(clustered)}
    assert "value" not in by                       # 연속형은 후보가 아니다

    pid = by["patient_id"]
    assert pid.is_identifier is False and pid.mean_per_group == 3.0
    assert pid.n_levels == 100 and "독립 가정" in pid.reason

    sid = by["sample_id"]
    assert sid.is_identifier is True and "식별자" in sid.reason   # 반복이 없으면 식별자

    assert by["batch"].n_levels == 5 and by["batch"].balanced is True


def test_name_hints_use_word_boundaries():
    """이름은 보조 신호일 뿐 — 부분 문자열 오탐이 없어야 한다."""
    assert _kind_from_name("label") == ("unknown", False)     # "lab"에 걸리면 안 됨
    assert _kind_from_name("site") == ("site", True)
    assert _kind_from_name("batch") == ("batch", True)
    assert _kind_from_name("daytime") == ("unknown", False)
    assert _kind_from_name("sample_id") == ("subject", True)


def test_imbalanced_groups_flagged():
    df = pd.DataFrame({"g": ["a"] * 90 + ["b"] * 8 + ["c"] * 2})
    g = detect(df)[0]
    assert g.balanced is False and g.max_per_group == 90


def test_compose_counts_types_and_hold():
    df = pd.DataFrame({"a": [1.0, np.nan], "b": ["x", "y"], "pid": ["P1", "P2"]})
    c = compose(df, ["a", "b", "pid"], held=["pid"])
    assert c["n_selected"] == 3 and c["n_analysis"] == 2 and c["n_held"] == 1
    assert c["kinds"]["numeric"] == 1 and c["kinds"]["categorical"] == 1
    assert c["complete_rows"] == 1 and c["any_missing"] == 1


def test_cli_groups_detect_and_confirm(tmp_path, clustered):
    from statop.store import tmp_dir

    p = tmp_path / "c.csv"
    clustered.to_csv(p, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(p)])
    sess = str(next(tmp_dir().glob("session_*.json")))
    runner.invoke(app, ["select", str(p), "--cols", "patient_id,batch,value",
                        "--session", sess])

    r = runner.invoke(app, ["groups", "--session", sess])
    assert r.exit_code == 0
    assert "그룹 구조 후보" in r.output and "patient_id" in r.output

    ok = runner.invoke(app, ["groups", "--session", sess,
                             "--confirm", "patient_id", "--kind", "subject"])
    assert ok.exit_code == 0 and "그룹 구조 확정" in ok.output

    from statop.session.core import load_session, replay
    assert replay(load_session(sess))["group_structure"] == {"patient_id": "subject"}

    bad = runner.invoke(app, ["groups", "--session", sess,
                              "--confirm", "patient_id", "--kind", "nope"])
    assert bad.exit_code != 0


def test_cli_compose_shows_state(tmp_path, clustered):
    from statop.store import tmp_dir

    p = tmp_path / "c.csv"
    clustered.to_csv(p, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(p)])
    sess = str(next(tmp_dir().glob("session_*.json")))
    runner.invoke(app, ["select", str(p), "--cols", "patient_id,batch,value",
                        "--session", sess])
    runner.invoke(app, ["hold", "--cols", "patient_id", "--session", sess])

    r = runner.invoke(app, ["compose", "--session", sess])
    assert r.exit_code == 0
    assert "가져온 3개 (분석 2 · hold 1)" in r.output
    assert "타입:" in r.output and "완전한 행" in r.output
