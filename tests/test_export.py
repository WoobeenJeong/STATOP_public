"""행 필터 + 가공 파일 저장 (M0-6 · DECISIONS ).

가공된 파일은 자기가 가공되었음을 스스로 알린다 — 파일이 손을 떠나도 사실이 따라가도록.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.export import inspect_file, sidecar_path
from statop.rowfilter import apply_filter, preview

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))


@pytest.fixture()
def demo(tmp_path):
    p = tmp_path / "demo.csv"
    pd.read_csv(DATA / "labels_demo.csv").to_csv(p, index=False)
    return p


def _session(runner, demo) -> str:
    from statop.store import tmp_dir

    runner.invoke(app, ["session", "new", "--data", str(demo)])
    return str(next(tmp_dir().glob("session_*.json")))


# ── 행 필터 ─────────────────────────────────────────────────
def test_filter_keeps_and_excludes():
    df = pd.DataFrame({"age": [10, 20, 30], "dx": ["a", "b", "a"]})
    assert len(apply_filter(df, "age > 15")) == 2
    assert len(apply_filter(df, "dx == 'a'", keep=False)) == 1
    r = preview(df, "age > 15")
    assert (r.kept, r.removed, round(r.ratio_removed, 3)) == (2, 1, 0.333)


@pytest.mark.parametrize("expr", ["__import__('os')", "df.to_csv('x')", "age", "",
                                  "eval('1')", "lambda x: x"])
def test_filter_rejects_unsafe_or_nonboolean(expr):
    df = pd.DataFrame({"age": [1, 2]})
    with pytest.raises(ValueError):
        apply_filter(df, expr)


def test_filter_cli_preview_then_apply(demo):
    runner = CliRunner()
    sess = _session(runner, demo)
    pre = runner.invoke(app, ["filter", "--session", sess, "--expr", "value > 2"])
    assert pre.exit_code == 0 and "남김" in pre.output
    assert not any(o["op"] == "filter_rows"
                   for o in json.loads(Path(sess).read_text())["ops"])   # 미리보기는 기록 안 함

    ap = runner.invoke(app, ["filter", "--session", sess, "--expr", "value > 2",
                             "--apply", "--reason", "검출 한계 미만"])
    assert ap.exit_code == 0 and "사유: 검출 한계 미만" in ap.output
    op = next(o for o in json.loads(Path(sess).read_text())["ops"] if o["op"] == "filter_rows")
    assert op["expr"] == "value > 2" and op["reason"] == "검출 한계 미만"


# ── 가공 파일 저장 ───────────────────────────────────────────
def test_export_marks_file_and_writes_sidecar(demo):
    runner = CliRunner()
    sess = _session(runner, demo)
    runner.invoke(app, ["select", str(demo), "--cols", "patient_id,diagnosis,value",
                        "--session", sess])
    runner.invoke(app, ["filter", "--session", sess, "--expr", "value > 2", "--apply",
                        "--reason", "검출 한계 미만"])
    runner.invoke(app, ["relabel", "--session", sess, "--key-column", "patient_id",
                        "--key", "PT00417", "--column", "diagnosis", "--to", "liver",
                        "--note", "등록 오류"])

    r = runner.invoke(app, ["export", "--session", sess])
    assert r.exit_code == 0 and "인위적 라벨 수정 1건" in r.output

    out = demo.with_name("demo_trimmed.csv")
    assert out.exists() and demo.exists()          # 원본은 그대로
    df = pd.read_csv(out)
    assert "_relabeled" in df.columns               # 표식이 파일에 남는다
    edited = df[df["_relabeled"]]
    assert len(edited) == 1
    assert edited.iloc[0]["_relabel_from"] == "hct" and edited.iloc[0]["diagnosis"] == "liver"
    assert edited.iloc[0]["_relabel_note"] == "등록 오류"

    meta = json.loads(sidecar_path(out).read_text())
    assert meta["statop_sidecar"] == 1
    assert meta["n_relabels"] == 1 and meta["source"]["path"] == str(demo)
    assert meta["filters"][0]["reason"] == "검출 한계 미만"


def test_reopening_trimmed_file_warns(demo):
    runner = CliRunner()
    sess = _session(runner, demo)
    runner.invoke(app, ["relabel", "--session", sess, "--key-column", "patient_id",
                        "--key", "PT00417", "--column", "diagnosis", "--to", "liver",
                        "--note", "등록 오류"])
    runner.invoke(app, ["export", "--session", sess])
    out = demo.with_name("demo_trimmed.csv")

    r = runner.invoke(app, ["columns", str(out)])
    assert "STATOP로 가공된 파일입니다 — 인위적 변경 1건" in r.output
    assert str(demo) in r.output                    # 원본 경로를 알려준다


def test_marker_detected_without_sidecar(demo):
    """사이드카를 지워도 표식 컬럼만으로 감지한다."""
    runner = CliRunner()
    sess = _session(runner, demo)
    runner.invoke(app, ["relabel", "--session", sess, "--key-column", "patient_id",
                        "--key", "PT00417", "--column", "diagnosis", "--to", "liver",
                        "--note", "등록 오류"])
    runner.invoke(app, ["export", "--session", sess])
    out = demo.with_name("demo_trimmed.csv")
    sidecar_path(out).unlink()

    info = inspect_file(out)
    assert info["trimmed"] is True and info["via"] == "marker_column"
    r = runner.invoke(app, ["columns", str(out)])
    assert "_relabeled 표식이 있습니다" in r.output


def test_plain_file_has_no_banner(demo):
    assert inspect_file(demo) is None
    r = CliRunner().invoke(app, ["columns", str(demo)])
    assert "가공된 파일" not in r.output


def test_export_refuses_overwrite_and_source(demo):
    runner = CliRunner()
    sess = _session(runner, demo)
    assert runner.invoke(app, ["export", "--session", sess]).exit_code == 0
    again = runner.invoke(app, ["export", "--session", sess])
    assert again.exit_code == 1 and "이미 존재" in again.output
    assert runner.invoke(app, ["export", "--session", sess, "--overwrite"]).exit_code == 0
    same = runner.invoke(app, ["export", "--session", sess, "--out", str(demo)])
    assert same.exit_code != 0        # 원본 덮어쓰기는 불가
