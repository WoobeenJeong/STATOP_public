import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.integrity import compare_files

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("statop_home")))


def test_identical_and_tampered(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_bytes(b"x,y\n1,2\n" * 100_000)
    shutil.copy(a, b)
    assert compare_files(a, b).identical

    b.write_bytes(b.read_bytes() + b"z")  # 말미 1바이트 추가
    d = compare_files(a, b)
    assert not d.identical
    assert d.size_b - d.size_a == 1
    assert d.first_diff_offset == a.stat().st_size  # 첫 차이 = 원래 파일 끝


def test_table_diff_reports_columns(tmp_path):
    import pandas as pd

    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_csv(a, index=False)
    pd.DataFrame({"x": [1, 2], "z": [5, 6]}).to_csv(b, index=False)
    d = compare_files(a, b)
    assert d.table_diff["cols_only_a"] == ["y"]
    assert d.table_diff["cols_only_b"] == ["z"]


def test_cli_exit_codes(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("x\n1\n")
    shutil.copy(a, b)
    runner = CliRunner()
    assert runner.invoke(app, ["integrity", str(a), str(b)]).exit_code == 0
    b.write_text("x\n2\n")
    r = runner.invoke(app, ["integrity", str(a), str(b)])
    assert r.exit_code == 1 and "다름" in r.output


def test_against_session_log(tmp_path):
    runner = CliRunner()
    data = tmp_path / "d.csv"
    data.write_text("x\n1\n2\n")
    runner.invoke(app, ["session", "new", "--data", str(data)])
    import os
    from statop.store import tmp_dir
    sess = str(next(tmp_dir().glob("session_*.json")))

    r = runner.invoke(app, ["integrity", str(data), "--log", sess])
    assert r.exit_code == 0 and "일치" in r.output
    data.write_text("x\n1\n2\n3\n")
    r = runner.invoke(app, ["integrity", str(data), "--log", sess])
    assert r.exit_code == 1 and "불일치" in r.output


def test_corrupted_parquet_reported_not_crash(tmp_path):
    """손상된 parquet: 죽지 않고 '표로 읽을 수 없음'으로 보고 (사용자 발견 버그)."""
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    shutil.copy(DATA / "synth_long.parquet", a)
    shutil.copy(a, b)
    b.write_bytes(b.read_bytes() + b"x")  # footer 손상
    r = CliRunner().invoke(app, ["integrity", str(a), str(b)])
    assert r.exit_code == 1
    assert "표로 읽을 수 없습니다" in r.output


# ──  표 상세 대조 (두 파일을 키 기준으로) ───────────────
@pytest.fixture
def two_tables(tmp_path):
    """b 는 a 에서 셀 2개 변경 · 행 1개 빠짐 · 행 1개 추가 · 컬럼 1개씩 +/−."""
    a = pd.DataFrame({"sid": [f"S{i:03d}" for i in range(6)],
                      "age": [20, 30, 40, 50, 60, 70],
                      "vaf": [0.1, 0.2, 0.3, 0.4, 0.5, np.nan],
                      "note": list("abcdef")})
    b = a.copy()
    b.loc[1, "age"] = 31
    b.loc[2, "vaf"] = 0.35
    b = b[b.sid != "S004"]
    b = pd.concat([b, pd.DataFrame([{"sid": "S009", "age": 90, "vaf": 0.9,
                                     "note": "z"}])])
    b = b.drop(columns=["note"]).assign(batch="B1")
    pa, pb = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(pa, index=False)
    b.to_csv(pb, index=False)
    return str(pa), str(pb)


def test_table_diff_finds_rows_columns_and_cells(two_tables):
    from statop.integrity import compare_tables

    a, b = two_tables
    r = compare_tables(a, b, key="sid")
    assert r.identical is False and r.key == "sid"
    assert r.rows_added == ["S009"] and r.rows_removed == ["S004"]
    assert r.cols_added == ["batch"] and r.cols_removed == ["note"]
    assert r.cells_changed == 2
    assert r.changed_by_column == {"age": 1, "vaf": 1}


def test_missing_on_both_sides_is_not_a_difference(two_tables):
    """NaN == NaN 을 다름으로 세면 결측 많은 표가 전부 다르다고 나온다."""
    from statop.integrity import compare_tables

    a, _ = two_tables
    r = compare_tables(a, a, key="sid")
    assert r.identical is True and r.cells_changed == 0


def test_only_the_named_columns_are_compared(two_tables):
    """'이 컬럼들만 같으면 된다' — 나머지 차이는 세지 않는다."""
    from statop.integrity import compare_tables

    a, b = two_tables
    r = compare_tables(a, b, key="sid", columns=["vaf"])
    assert r.cells_changed == 1 and r.changed_by_column == {"vaf": 1}
    assert r.cols_added == [] and r.cols_removed == []   # note/batch 는 안 읽었다


def test_values_are_shown_only_when_asked(two_tables):
    """점진 노출 — 실제 값은 명시할 때만 나온다."""
    from statop.integrity import compare_tables

    a, b = two_tables
    assert compare_tables(a, b, key="sid").examples == []
    got = compare_tables(a, b, key="sid", show_values=True).examples
    assert {"key": "S001", "column": "age", "from": "30", "to": "31"} in got


def test_duplicate_keys_stop_cell_comparison(tmp_path):
    """키가 중복이면 행을 1:1로 맞출 수 없다 — 억지로 맞추면 없는 차이를 만든다."""
    from statop.integrity import compare_tables

    a = pd.DataFrame({"sid": ["S1", "S2", "S1"], "v": [1, 2, 3]})
    b = pd.DataFrame({"sid": ["S1", "S2"], "v": [1, 2]})
    pa, pb = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(pa, index=False)
    b.to_csv(pb, index=False)
    r = compare_tables(str(pa), str(pb), key="sid")
    assert r.duplicate_keys and r.cells_changed == 0
    assert "중복" in r.note and r.identical is False


def test_missing_key_column_is_refused(two_tables):
    from statop.integrity import compare_tables

    a, b = two_tables
    with pytest.raises(ValueError):
        compare_tables(a, b, key="nope")


def test_tablediff_cli_exit_code_signals_difference(two_tables):
    from typer.testing import CliRunner

    from statop.cli import app

    a, b = two_tables
    runner = CliRunner()
    r = runner.invoke(app, ["tablediff", a, b, "--key", "sid"])
    assert r.exit_code == 1                       # 다르면 1
    assert "+ S009" in r.output and "− S004" in r.output
    assert "batch" in r.output and "note" in r.output
    # 컬럼마다 한 건은 기본으로 보인다 — 더 보려면 --show-values
    assert "값을 더 보려면" in r.output

    same = runner.invoke(app, ["tablediff", a, a, "--key", "sid"])
    assert same.exit_code == 0 and "같습니다" in same.output


# ── 데모 무결성 한 쌍 (16/17) ───────────────────────────────
def test_the_demo_pair_is_what_the_docstring_says(tmp_path):
    """데모로 무결성을 눌러 볼 때, 심어 둔 것과 나오는 것이 달라지면 안 된다.

    `demo/make_validation.py` 의 build_integrity_changed 가 적어 둔 내용이 곧
    사용자가 화면에서 읽을 숫자다.
    """
    import importlib.util
    from pathlib import Path

    from statop.integrity import compare_tables

    # **생성기에서 새로 만들어** 본다. `demo/data` 의 파일은 사용자가 직접 손대며
    # 실험하는 자리다 — 거기에 대고 검사하면 남의 실험이 테스트를 깨뜨린다
    gen = Path(__file__).resolve().parents[1] / "demo" / "make_validation.py"
    if not gen.exists():
        pytest.skip("데모 생성기가 없음")
    spec = importlib.util.spec_from_file_location("make_validation", gen)
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)

    d = Path(tmp_path)
    types = mk.build_types(np.random.default_rng(mk.SEED))
    a, same, changed = d / "a.csv", d / "same.csv", d / "changed.csv"
    types.to_csv(a, index=False)
    mk.build_integrity_same(types).to_csv(same, index=False)
    mk.build_integrity_changed(types).to_csv(changed, index=False)

    assert compare_tables(str(a), str(same), key="sample_id").identical

    r = compare_tables(str(a), str(changed), key="sample_id")
    assert not r.identical
    assert r.rows_removed == ["S0010", "S0011", "S0012"]
    assert r.rows_added == ["S9001", "S9002"]
    assert r.cols_removed == ["odds_ratio"] and not r.cols_added
    assert r.cells_changed == 4
    assert r.changed_by_column == {"pct_purity": 2, "prob_score": 1, "tumor_type": 1}


# ── 한 컬럼을 A/B 로 겹쳐 보기  ──────────────────────
def test_a_column_can_be_overlaid_a_against_b(tmp_path):
    """"바뀐 셀 2개"로는 **어디가 어떻게** 옮겼는지 알 수 없다."""
    from statop.integrity import column_view

    rng = np.random.default_rng(4)
    n = 120
    a = pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                      "v": rng.normal(10, 2, n).round(3),
                      "g": rng.choice(["x", "y"], n)})
    b = a.copy()
    b.loc[0, "v"] = 99.0
    b.loc[1, "v"] = 0.0
    b.loc[2, "g"] = "z"
    pa, pb = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(pa, index=False)
    b.to_csv(pb, index=False)

    v = column_view(str(pa), str(pb), "sid", "v")
    body = "\n".join(v["lines"])
    assert v["kind"] == "numeric" and v["n_diff"] == 2
    assert "평균" in body and "중앙" in body and "IQR" in body
    assert "B−A" in body, "차이가 안 보인다"
    assert "값이 다른 2행만" in body, "문제가 되는 행만 따로 보여야 한다"
    assert "KS 거리" in body and "Wasserstein" in body

    g = column_view(str(pa), str(pb), "sid", "g")
    assert g["kind"] == "categorical" and g["n_diff"] == 1
    assert "총변동거리" in "\n".join(g["lines"])


def test_an_identical_column_says_so_without_a_chart(tmp_path):
    """같은 컬럼에 개형을 두 번 그려 봐야 읽을 것이 없다."""
    from statop.integrity import column_view

    a = pd.DataFrame({"sid": ["A", "B", "C"], "v": [1.0, 2.0, 3.0]})
    pa, pb = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(pa, index=False)
    a.to_csv(pb, index=False)
    v = column_view(str(pa), str(pb), "sid", "v")
    assert v["n_diff"] == 0 and v["kind"] == "same"
    assert len(v["lines"]) == 2


def test_the_overlay_follows_a_pairing(tmp_path):
    """이름이 다른 짝도 겹쳐 볼 수 있어야 한다 — B 는 B 의 이름으로 읽는다."""
    from statop.integrity import column_view

    a = pd.DataFrame({"sid": ["A", "B", "C"], "log2_frac_v1": [1.0, 2.0, 3.0]})
    b = pd.DataFrame({"sid": ["A", "B", "C"], "log2_frac_v2": [1.0, 2.5, 3.0]})
    pa, pb = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(pa, index=False)
    b.to_csv(pb, index=False)
    v = column_view(str(pa), str(pb), "sid", "log2_frac_v1",
                    pairs={"log2_frac_v1": "log2_frac_v2"})
    assert v["n_diff"] == 1
    assert "log2_frac_v1 ↔ log2_frac_v2" in v["lines"][0]
