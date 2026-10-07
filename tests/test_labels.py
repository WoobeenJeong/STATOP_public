"""라벨 매핑 (DECISIONS ) — 표시는 문자열, 계산은 코드."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.labels import UNMATCHED_COLOR, groups_after, levels_of, match_label, normalize

DATA = Path(__file__).parent / "data"
DEMO = DATA / "labels_demo.csv"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("h")
    monkeypatch.setenv("STATOP_HOME", str(home))
    return home


def test_normalize_strips_separators_and_suffixes():
    assert normalize("HCC_tumor") == "hcc"
    assert normalize("Liver-Cancer") == "liver"
    assert normalize("breast carcinoma") == "breast"


def test_match_label_priority_and_unmatched():
    assert match_label("LUAD")[0] == "lung"          # TCGA 정확일치
    assert match_label("HCC")[0] == "liver"          # 키워드 부분일치
    assert match_label("brca_basal")[0] == "breast"
    cat, color, amb = match_label("완전히모르는값")
    assert cat is None and color == UNMATCHED_COLOR and amb is False


def test_ambiguous_keyword_flagged():
    """사전에 충돌이 있으면 조용히 하나를 고르지 않고 모호로 표시한다 (7.2-4)."""
    assert match_label("germ-cell")[2] is True


def test_levels_default_codes_by_frequency():
    lv = levels_of(DEMO, "diagnosis", sample_n=2000)
    assert [l.value for l in lv] == ["control", "hct", "liver"]
    assert [l.code for l in lv] == [0, 1, 2]
    assert [l.n for l in lv] == [412, 388, 200]
    assert lv[2].category == "liver" and lv[2].color.startswith("#")


def test_grouping_changes_number_of_groups():
    """여러 수준을 같은 코드로 묶는 것은 그룹 정의다 — 3수준 → 2군."""
    lv = levels_of(DEMO, "diagnosis", sample_n=2000,
                   mapping={"control": 0, "hct": 0, "liver": 1})
    g = groups_after(lv)
    assert len(g) == 2
    assert g[0]["values"] == ["control", "hct"] and g[0]["n"] == 800
    assert g[1]["values"] == ["liver"] and g[1]["n"] == 200


def test_unknown_column_fails_loudly():
    with pytest.raises(ValueError, match="없는 컬럼"):
        levels_of(DEMO, "no_such_column", sample_n=500)


def test_cli_shows_regroup_warning():
    r = CliRunner().invoke(app, ["labels", str(DEMO), "--column", "diagnosis",
                                 "--sample-n", "2000",
                                 "--map", "control=0,hct=0,liver=1"])
    assert r.exit_code == 0
    assert "3수준 → 2군으로 묶임" in r.output
    assert "코드 0: control, hct (n=800)" in r.output


def test_cli_records_mapping_in_session(statop_home):
    import json

    from statop.store import tmp_dir

    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--data", str(DEMO)])
    sess = str(next(tmp_dir().glob("session_*.json")))
    r = runner.invoke(app, ["labels", str(DEMO), "--column", "diagnosis",
                            "--session", sess, "--map", "control=0,hct=0,liver=1"])
    assert r.exit_code == 0 and "label_map" in r.output

    doc = json.loads(Path(sess).read_text())
    op = next(o for o in doc["ops"] if o["op"] == "label_map")
    assert op["column"] == "diagnosis" and op["mapping"]["hct"] == 0

    # 재생하면 매핑이 복원된다
    from statop.session.core import load_session, replay
    st = replay(load_session(sess))
    assert st["label_maps"][op["source"]]["diagnosis"]["liver"] == 1


def test_cli_bad_mapping_format():
    r = CliRunner().invoke(app, ["labels", str(DEMO), "--column", "diagnosis",
                                 "--map", "control:0"])
    assert r.exit_code != 0
