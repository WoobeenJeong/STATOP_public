"""개별 샘플 라벨 수정 (DECISIONS) — 허용하되 흔적을 지울 수 없게."""

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.relabel import WARN_RATIO, apply_relabels, check_ratio, find_row
from statop.session.core import load_session, replay

DATA = Path(__file__).parent / "data"
DEMO = DATA / "labels_demo.csv"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("h")
    monkeypatch.setenv("STATOP_HOME", str(home))
    return home


def _session(runner) -> str:
    from statop.store import tmp_dir

    runner.invoke(app, ["session", "new", "--data", str(DEMO)])
    return str(next(tmp_dir().glob("session_*.json")))


def test_apply_marks_edited_rows():
    """사본에 표식 컬럼이 붙는다 — 파일로 저장되면 표식이 따라간다."""
    df = pd.DataFrame({"pid": ["A", "B"], "dx": ["control", "hct"]})
    out = apply_relabels(df, [{"key": "B", "column": "dx", "from": "hct", "to": "liver",
                               "note": "입력 오류", "seq": 1, "ts": "t"}], "pid")
    assert out.loc[1, "dx"] == "liver"
    assert out.loc[1, "_relabeled"] and out.loc[1, "_relabel_from"] == "hct"
    assert out.loc[1, "_relabel_note"] == "입력 오류"
    assert not out.loc[0, "_relabeled"]
    assert df.loc[1, "dx"] == "hct"        # 원본 프레임은 그대로


def test_no_marker_columns_when_no_edits():
    df = pd.DataFrame({"pid": ["A"], "dx": ["control"]})
    assert "_relabeled" not in apply_relabels(df, [], "pid").columns


def test_ratio_threshold():
    assert check_ratio(1, 50).over_threshold is True       # 2% > 1%
    assert check_ratio(1, 1000).over_threshold is False
    assert check_ratio(0, 1000).ratio == 0.0
    assert WARN_RATIO == 0.01


def test_find_row_and_missing_column():
    assert find_row(DEMO, "patient_id", "PT00417", "diagnosis", sample_n=2000) == "hct"
    assert find_row(DEMO, "patient_id", "PT99999", "diagnosis", sample_n=2000) is None
    with pytest.raises(ValueError, match="없는 컬럼"):
        find_row(DEMO, "nope", "x", "diagnosis", sample_n=500)


def test_cli_requires_note_and_records_op():
    runner = CliRunner()
    sess = _session(runner)
    common = ["relabel", "--session", sess, "--key-column", "patient_id",
              "--key", "PT00417", "--column", "diagnosis", "--to", "liver"]

    assert runner.invoke(app, [*common, "--note", "   "]).exit_code != 0   # 사유 필수

    r = runner.invoke(app, [*common, "--note", "등록 시 입력 오류 — 병리 재확인"])
    assert r.exit_code == 0
    assert "hct → liver" in r.output
    assert "개별 라벨 수정 1건" in r.output          # 출력에 강제 표시
    assert "원본 파일은 변경되지 않음" in r.output

    doc = json.loads(Path(sess).read_text())
    op = next(o for o in doc["ops"] if o["op"] == "relabel")
    assert op["from"] == "hct" and op["to"] == "liver" and op["note"]

    st = replay(load_session(sess))
    assert len(st["relabels"]) == 1 and st["relabels"][0]["key"] == "PT00417"


def test_cli_rejects_bad_targets():
    runner = CliRunner()
    sess = _session(runner)
    base = ["relabel", "--session", sess, "--key-column", "patient_id",
            "--column", "diagnosis", "--note", "사유"]
    assert runner.invoke(app, [*base, "--key", "PT99999", "--to", "liver"]).exit_code != 0
    assert runner.invoke(app, [*base, "--key", "PT00001", "--to", "control"]).exit_code != 0


def test_repeated_edit_keeps_history_but_last_wins():
    runner = CliRunner()
    sess = _session(runner)
    base = ["relabel", "--session", sess, "--key-column", "patient_id",
            "--key", "PT00417", "--column", "diagnosis", "--note", "사유"]
    runner.invoke(app, [*base, "--to", "liver"])
    runner.invoke(app, [*base, "--to", "control"])

    doc = load_session(sess)
    assert sum(1 for o in doc["ops"] if o["op"] == "relabel") == 2   # 이력은 둘 다 남고
    rl = replay(doc)["relabels"]
    assert len(rl) == 1 and rl[0]["to"] == "control"                 # 상태는 마지막이 이긴다
