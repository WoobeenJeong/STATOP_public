from pathlib import Path

from statop.io.transpose import estimate_cost

DATA = Path(__file__).parent / "data"


def test_estimate_cost_long_parquet():
    c = estimate_cost(DATA / "synth_long.parquet")
    assert (c.n_rows, c.n_cols, c.estimated) == (10_000, 2_000, False)
    assert 1200 < c.mem_mb < 1400  # 10k×2k×8×8 = 1,280MB (실측 보정 계수)
    assert not c.warn


def test_estimate_cost_warns_on_huge(tmp_path):
    import pandas as pd

    p = tmp_path / "t.csv"
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(p, index=False)
    c = estimate_cost(p, warn_mb=0.00001)  # 임계 강제로 경고 경로 확인
    assert c.warn and c.estimated


def test_transpose_roundtrip_small(tmp_path):
    import pandas as pd

    from statop.io.transpose import transpose_table

    p = tmp_path / "t.csv"
    pd.DataFrame({"id": ["a", "b"], "x": [1, 2], "y": [3, 4]}).to_csv(p, index=False)
    t = transpose_table(p)
    assert list(t.columns) == ["column", "a", "b"]  # 첫 컬럼 값이 새 컬럼명
    assert t["column"].tolist() == ["x", "y"]       # 원래 컬럼명이 첫 컬럼으로
    assert t["a"].tolist() == [1, 3] and t["b"].tolist() == [2, 4]


def test_transpose_rejects_duplicate_ids(tmp_path):
    import pandas as pd
    import pytest as pt

    from statop.io.transpose import transpose_table

    p = tmp_path / "d.csv"
    pd.DataFrame({"id": ["a", "a"], "x": [1, 2]}).to_csv(p, index=False)
    with pt.raises(ValueError, match="중복"):
        transpose_table(p)


def test_transpose_wide_real():
    import time

    from statop.io.transpose import transpose_table

    t0 = time.time()
    t = transpose_table(DATA / "synth_wide.parquet")  # 2,000행 × 10,000컬럼
    dt = time.time() - t0
    assert t.shape == (9_999, 2_001)  # 10,000-1 피처행 × (column + 2,000 샘플)
    assert t.columns[0] == "column" and t.columns[1] == "PT000000"
    assert dt < 120


def test_transpose_cli_records_and_toggles(tmp_path, monkeypatch, tmp_path_factory):
    import json

    import pandas as pd
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.session.core import load_session, replay

    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("statop_home")))
    from statop.store import tmp_dir

    data = tmp_path / "t.csv"
    pd.DataFrame({"id": ["a", "b"], "x": [1, 2]}).to_csv(data, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(data)])
    sess = str(next(tmp_dir().glob("session_*.json")))

    r = runner.invoke(app, ["transpose", str(data), "--session", sess])
    assert r.exit_code == 0
    assert "전치 예상" in r.output and "전치됨" in r.output
    assert replay(load_session(sess))["transposed"]["d1"] is True

    r = runner.invoke(app, ["transpose", str(data), "--session", sess])  # 2번 = 원상복귀
    assert "원상복귀" in r.output
    assert replay(load_session(sess))["transposed"]["d1"] is False
    assert [o["op"] for o in load_session(sess)["ops"]] == ["open", "transpose", "transpose"]


def test_columns_reflects_transposed_view(tmp_path, monkeypatch, tmp_path_factory):
    import pandas as pd
    from typer.testing import CliRunner

    from statop.cli import app

    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("statop_home")))
    from statop.store import tmp_dir

    data = tmp_path / "t.csv"
    pd.DataFrame({"id": ["a", "b"], "x": [1, 2], "y": [3, 4]}).to_csv(data, index=False)
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(data)])
    sess = str(next(tmp_dir().glob("session_*.json")))

    # 전치 전: 원래 컬럼
    r = runner.invoke(app, ["columns", str(data), "--session", sess])
    assert "id" in r.output and "전치" not in r.output

    runner.invoke(app, ["transpose", str(data), "--session", sess])
    r = runner.invoke(app, ["columns", str(data), "--session", sess])
    assert r.exit_code == 0
    assert "전치(Transpose)된 뷰" in r.output
    assert "a" in r.output.split("컬럼명")[1]  # 첫 컬럼 값이 컬럼명으로

    # 세션 없이 보면 여전히 원본 기준 (원본 불변)
    r = runner.invoke(app, ["columns", str(data)])
    assert "전치" not in r.output
