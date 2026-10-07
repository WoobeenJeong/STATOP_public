from typer.testing import CliRunner

import statop
from statop.cli import app


def test_version_command():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert statop.__version__ in result.output


def test_columns_command_shows_summary_not_data():
    result = CliRunner().invoke(
        app, ["columns", "tests/data/synth_long.parquet", "--sample-n", "3000"]
    )
    assert result.exit_code == 0
    assert "컬럼 2,000개" in result.output
    assert "추정치" in result.output
    assert "patient_id" in result.output       # 컬럼명은 보임
    assert "PT00" not in result.output          # 데이터 셀 값은 절대 안 보임
    assert "siteA" not in result.output


def test_columns_page_mode():
    """--page N: 웹과 같은 25개 단위. 쪽마다 서로 다른 컬럼이 나온다."""
    runner = CliRunner()
    args = ["columns", "tests/data/synth_long.parquet", "--sample-n", "3000",
            "--sort", "missing", "--page-size", "5"]
    p1 = runner.invoke(app, [*args, "--page", "1"])
    p2 = runner.invoke(app, [*args, "--page", "2"])
    assert p1.exit_code == 0 and p2.exit_code == 0
    assert "1/400 쪽" in p1.output and "2/400 쪽" in p2.output
    # 표 본문만 비교 (요약줄 "결측 상위:"에도 컬럼명이 등장하므로)
    def body(out: str) -> str:
        lines = out.splitlines()
        head = next(i for i, ln in enumerate(lines) if "고유값수" in ln and "컬럼명" in ln)
        return "\n".join(lines[head + 1:])

    assert "count055" in body(p1.output) and "count055" not in body(p2.output)


def test_columns_grep_and_sort(tmp_path):
    out = tmp_path / "cols.tsv"
    result = CliRunner().invoke(app, [
        "columns", "tests/data/synth_long.parquet", "--sample-n", "3000",
        "--grep", "^trap_", "--sort", "missing", "--limit", "2", "--out", str(out),
    ])
    assert result.exit_code == 0
    assert "해당 4개" in result.output          # trap_* 4개만 필터됨
    assert out.read_text().count("\n") == 5     # 헤더 + 4행


def test_columns_warning_and_missing_markers(tmp_path):
    result = CliRunner().invoke(app, [
        "columns", "tests/data/synth_long.parquet", "--sample-n", "3000",
        "--sort", "missing", "--limit", "3",
    ])
    assert "200개를 넘습니다" in result.output
    assert "!!" in result.output               # 결측 ≥30% 기호 (색과 병행)

    import pandas as pd
    small = tmp_path / "small.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(small, index=False)
    result = CliRunner().invoke(app, ["columns", str(small)])
    assert result.exit_code == 0
    assert "200개를 넘습니다" not in result.output
