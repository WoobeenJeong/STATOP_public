from pathlib import Path

import pytest

from statop.rules.mdparse import find_table, parse_file, parse_tables

SCHEMA = Path(__file__).parent.parent / "schema"


def test_registry_tests_key_tables():
    ts = parse_file(SCHEMA / "registry-tests.md")
    assert len(find_table(ts, "9.1 의미 타입").rows) == 15   # S-T01~15 (로 14·15 추가)
    assert len(find_table(ts, "9.2 연산 적합성").rows) == 14  # S-R01~14
    assert len(find_table(ts, "10. 파생 함수").rows) == 15    # F-01~15 (F-15 arcsinh)


def test_escaped_pipe_restored():
    ts = parse_file(SCHEMA / "registry-tests.md")
    sr = find_table(ts, "9.2 연산 적합성")
    r11 = next(r for r in sr.rows if r["ID"] == "S-R11")
    assert "P(Y|Z)" in r11["원클릭 수정"]  # md의 \| 가 | 로 복원


def test_short_row_padded():
    t = parse_tables("## t\n| a | b | c |\n|---|---|---|\n| 1 | 2 |\n")[0]
    assert t.rows[0] == {"a": "1", "b": "2", "c": ""}


def test_find_table_fails_loudly():
    ts = parse_file(SCHEMA / "registry-tests.md")
    with pytest.raises(ValueError, match="expected exactly 1"):
        find_table(ts, "없는 섹션 이름")
