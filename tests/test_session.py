import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.session.core import new_session, partial_hash, register_source, save_session

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    """기본 저장소를 테스트 전용 폴더로 격리."""
    home = tmp_path_factory.mktemp("statop_home")
    monkeypatch.setenv("STATOP_HOME", str(home))
    return home


def _uid():
    from statop.store import user_id
    return user_id()


def _make(tmp_path, name, body: bytes):
    p = tmp_path / name
    p.write_bytes(body)
    return p


def test_partial_hash_detects_head_tail_and_size_change(tmp_path):
    base = b"A" * 10_000_000  # 10MB — 선두/말미 4MB 창보다 큼
    h0 = partial_hash(_make(tmp_path, "f0", base))["value"]
    assert h0 == partial_hash(_make(tmp_path, "same", base))["value"]  # 동일 내용 = 동일 지문
    assert h0 != partial_hash(_make(tmp_path, "head", b"B" + base[1:]))["value"]  # 선두 변경
    assert h0 != partial_hash(_make(tmp_path, "tail", base[:-1] + b"B"))["value"]  # 말미 변경
    assert h0 != partial_hash(_make(tmp_path, "size", base + b"A"))["value"]  # 크기 변경


def test_partial_hash_documented_blind_spot(tmp_path):
    """한계 문서화: 정중앙만 바뀌면 못 잡는다 — 그래서 주의 문구·statop verify가 존재."""
    base = b"A" * 20_000_000
    mid = bytearray(base)
    mid[10_000_000] = ord(b"B")
    h0 = partial_hash(_make(tmp_path, "f0", base))["value"]
    assert h0 == partial_hash(_make(tmp_path, "mid", bytes(mid)))["value"]


def test_partial_hash_fast_on_large_file():
    t0 = time.time()
    partial_hash(DATA / "synth_long.csv")  # 242MB
    assert time.time() - t0 < 2.0


def test_session_new_writes_schema(tmp_path, statop_home):
    result = CliRunner().invoke(app, [
        "session", "new", "--project", str(tmp_path), "--data", str(DATA / "synth_long.parquet"),
    ])
    assert result.exit_code == 0
    assert "부분 해시" in result.output  # 주의 문구 자동 표기
    files = list((statop_home / _uid() / "tmp").glob("session_*.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text())
    assert doc["schema_version"] == 1
    assert doc["sources"][0]["format"] == "parquet"
    assert doc["sources"][0]["hash"]["mode"] == "partial"
    assert doc["ops"] == []


def test_register_source_no_data_copy(tmp_path, statop_home):
    doc = new_session(tmp_path)
    register_source(doc, DATA / "synth_long.parquet")
    path = save_session(doc)
    text = path.read_text()
    assert "PT000001" not in text and "siteA" not in text  # 로그에 데이터 값 없음


def test_open_op_recorded_and_source_reused(tmp_path, statop_home):
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--project", str(tmp_path),
                        "--data", str(DATA / "synth_long.parquet")])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    r1 = runner.invoke(app, ["open", str(DATA / "synth_long.parquet"), "--session", sess])
    r2 = runner.invoke(app, ["open", str(DATA / "synth_wide.parquet"), "--session", sess])
    assert r1.exit_code == 0 and r2.exit_code == 0
    doc = json.loads(Path(sess).read_text())
    assert [s["id"] for s in doc["sources"]] == ["d1", "d2"]  # 같은 경로는 재등록 안 됨
    assert [(o["seq"], o["op"], o["source"]) for o in doc["ops"]] == [
        (1, "open", "d1"), (2, "open", "d2")]


def test_notice_is_interface_neutral():
    """코어 문구에 CLI 명령어가 박혀 있으면 안 된다 — 웹 UI에서도 같은 문구를 쓴다."""
    from statop.messages import msg
    assert "statop " not in msg("notice_partial_hash")
    assert "statop " not in msg("notice_partial_hash", lang="en")


def test_select_auto_opens_and_validates(tmp_path, statop_home):
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--project", str(tmp_path)])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    data = str(DATA / "synth_long.parquet")

    bad = runner.invoke(app, ["select", data, "--cols", "site,no_such_col", "--session", sess])
    assert bad.exit_code != 0  # 없는 컬럼은 시끄럽게 실패

    ok = runner.invoke(app, ["select", data, "--cols", "site,label", "--session", sess])
    assert ok.exit_code == 0
    doc = json.loads(Path(sess).read_text())
    ops = [(o["op"], o.get("cols")) for o in doc["ops"]]
    assert ops == [("open", None), ("select", ["site", "label"])]  # open 자동 선행

    # 두 번째 select는 open을 다시 기록하지 않음
    runner.invoke(app, ["select", data, "--cols", "cont000", "--session", sess])
    doc = json.loads(Path(sess).read_text())
    assert [o["op"] for o in doc["ops"]] == ["open", "select", "select"]


def test_select_cols_file_roundtrip(tmp_path, statop_home):
    """columns --out 으로 뽑은 tsv를 그대로 select 입력으로 쓰는 왕복."""
    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--project", str(tmp_path)])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    data = str(DATA / "synth_long.parquet")
    tsv = tmp_path / "picked.tsv"

    runner.invoke(app, ["columns", data, "--sample-n", "3000", "--grep", "^comp00", "--out", str(tsv)])
    r = runner.invoke(app, ["select", data, "--cols-file", str(tsv), "--session", sess])
    assert r.exit_code == 0
    doc = json.loads(Path(sess).read_text())
    sel = next(o for o in doc["ops"] if o["op"] == "select")
    assert len(sel["cols"]) == 20 and sel["cols"][0] == "comp00_frac00"

    # 한 줄에 하나짜리 평문 목록도 동작
    plain = tmp_path / "plain.txt"
    plain.write_text("site\nlabel\n")
    r = runner.invoke(app, ["select", data, "--cols-file", str(plain), "--session", sess])
    assert r.exit_code == 0

    # --cols와 --cols-file 동시 지정(또는 둘 다 없음)은 에러
    both = runner.invoke(app, ["select", data, "--cols", "site", "--cols-file", str(plain), "--session", sess])
    neither = runner.invoke(app, ["select", data, "--session", sess])
    assert both.exit_code != 0 and neither.exit_code != 0


def test_session_save_autoname_and_overwrite(tmp_path, statop_home):
    import re

    runner = CliRunner()
    runner.invoke(app, ["session", "new", "--project", str(tmp_path),
                        "--data", str(DATA / "synth_long.parquet")])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))

    r1 = runner.invoke(app, ["session", "save", "--session", sess])
    assert r1.exit_code == 0
    saved = [p for p in tmp_path.glob("*.json") if not p.name.startswith("session_")]
    assert len(saved) == 1
    # : 날짜_프로젝트_모드_태그_n행수_시각
    assert re.fullmatch(r"\d{6}_.+_hypo_clean_n10000_(am|pm)\d{2}\.json", saved[0].name)

    # 같은 시간대 재저장: 단순 저장은 실패, --overwrite면 성공 + .bak
    r2 = runner.invoke(app, ["session", "save", "--session", sess])
    assert r2.exit_code != 0
    r3 = runner.invoke(app, ["session", "save", "--session", sess, "--overwrite"])
    assert r3.exit_code == 0
    # 반복 덮어쓰기해도 .bak은 항상 1개 (원본-bak 쌍 유지, )
    runner.invoke(app, ["session", "save", "--session", sess, "--overwrite"])
    runner.invoke(app, ["session", "save", "--session", sess, "--overwrite"])
    assert len(list(tmp_path.glob("*.json.bak"))) == 1

    # 사용자 추가 이름
    r4 = runner.invoke(app, ["session", "save", "--session", sess, "--suffix", "cohortB"])
    assert r4.exit_code == 0
    assert any("__cohortB.json" in p.name for p in tmp_path.glob("*.json"))


def test_default_store_and_close(statop_home):
    """--project 없이 생성 → 기본 저장소 구조. close는 저장 전 거부, 저장 후 임시본 삭제."""
    runner = CliRunner()
    r = runner.invoke(app, ["session", "new", "--data", str(DATA / "synth_long.parquet")])
    assert r.exit_code == 0
    tmp = statop_home / _uid() / "tmp"
    sess = str(next(tmp.glob("session_*.json")))

    # 저장 전 close → 거부
    r = runner.invoke(app, ["session", "close", "--session", sess])
    assert r.exit_code != 0 and "저장된 적이 없습니다" in r.output

    # 저장 → sessions/ 폴더에 자동 이름으로
    r = runner.invoke(app, ["session", "save", "--session", sess])
    assert r.exit_code == 0
    assert len(list((statop_home / _uid() / "sessions").glob("*.json"))) == 1

    # 저장 후 close → 임시본 삭제
    r = runner.invoke(app, ["session", "close", "--session", sess])
    assert r.exit_code == 0
    assert not list(tmp.glob("session_*.json"))


def test_close_force_discards_unsaved(statop_home):
    runner = CliRunner()
    runner.invoke(app, ["session", "new"])
    tmp = statop_home / _uid() / "tmp"
    sess = str(next(tmp.glob("session_*.json")))
    r = runner.invoke(app, ["session", "close", "--session", sess, "--force"])
    assert r.exit_code == 0
    assert not list(tmp.glob("session_*.json"))


def test_load_replays_state(statop_home):
    """저장 → 불러오기: 새 세션 id, 같은 기록, 재생 상태(선택 컬럼 합집합) 복원."""
    from statop.session.core import load_saved, replay

    runner = CliRunner()
    data = str(DATA / "synth_long.parquet")
    runner.invoke(app, ["session", "new", "--data", data])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    runner.invoke(app, ["select", data, "--cols", "site,label", "--session", sess])
    runner.invoke(app, ["select", data, "--cols", "label,cont000", "--session", sess])
    runner.invoke(app, ["session", "save", "--session", sess])
    saved = next((statop_home / _uid() / "sessions").glob("*.json"))

    orig = json.loads(Path(sess).read_text())
    doc, state = load_saved(saved)
    assert doc["session_id"] != orig["session_id"]  # 새 세션
    assert doc["ops"] == orig["ops"]                # 기록은 동일
    # 재생: 중복 없이 선택 순서 유지 (label은 한 번만)
    assert state["selected"]["d1"] == ["site", "label", "cont000"]
    # 같은 로그 2회 재생 → 동일 상태 (S030의 씨앗)
    assert replay(doc) == replay(orig)


def test_replay_rejects_unknown_op():
    from statop.session.core import new_session, replay

    doc = new_session()
    doc["ops"] = [{"seq": 1, "ts": "t", "op": "mystery"}]
    with pytest.raises(ValueError, match="재생 규칙이 없는 op"):
        replay(doc)  # 모르는 op를 조용히 건너뛰지 않는다


def test_load_cli_shows_summary_not_full_ops(statop_home):
    runner = CliRunner()
    data = str(DATA / "synth_long.parquet")
    runner.invoke(app, ["session", "new", "--data", data])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    for i in range(8):
        runner.invoke(app, ["select", data, "--cols", f"cont{i:03d}", "--session", sess])
    runner.invoke(app, ["session", "save", "--session", sess])
    saved = next((statop_home / _uid() / "sessions").glob("*.json"))

    r = runner.invoke(app, ["session", "load", str(saved)])
    assert r.exit_code == 0
    assert "조작 9개" in r.output           # 요약은 보임
    assert r.output.count("#") <= 4          # 마지막 3개만 — 전체 나열 금지


def test_deselect_op_and_replay(statop_home):
    """select 후 deselect(체크 해제) → 재생 상태에서 그 컬럼이 빠진다."""
    runner = CliRunner()
    data = str(DATA / "synth_long.parquet")
    runner.invoke(app, ["session", "new", "--data", data])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    runner.invoke(app, ["select", data, "--cols", "site,label,cont000", "--session", sess])

    r = runner.invoke(app, ["deselect", data, "--cols", "label", "--session", sess])
    assert r.exit_code == 0 and "남은 선택 2개" in r.output

    from statop.session.core import load_session, replay
    doc = load_session(sess)
    assert replay(doc)["selected"]["d1"] == ["site", "cont000"]
    assert [o["op"] for o in doc["ops"]] == ["open", "select", "deselect"]  # 해제도 기록

    # 가져온 적 없는 컬럼 해제는 에러
    bad = runner.invoke(app, ["deselect", data, "--cols", "cont999", "--session", sess])
    assert bad.exit_code != 0

    # 해제했던 컬럼 재선택도 정상 (체크 → 해제 → 재체크)
    runner.invoke(app, ["select", data, "--cols", "label", "--session", sess])
    doc = load_session(sess)
    assert replay(doc)["selected"]["d1"] == ["site", "cont000", "label"]


def _saved_session(runner, statop_home, tmp_path):
    """저장본 1개를 만들되 원본은 tmp_path 사본이라 조작 가능."""
    import shutil
    data = tmp_path / "data.parquet"
    shutil.copy(DATA / "synth_long.parquet", data)
    runner.invoke(app, ["session", "new", "--data", str(data)])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    runner.invoke(app, ["select", str(data), "--cols", "site", "--session", sess])
    runner.invoke(app, ["session", "save", "--session", sess])
    runner.invoke(app, ["session", "close", "--session", sess])
    return data, next((statop_home / _uid() / "sessions").glob("*.json"))


def test_load_hash_ok_shows_notice(statop_home, tmp_path):
    runner = CliRunner()
    _, saved = _saved_session(runner, statop_home, tmp_path)
    r = runner.invoke(app, ["session", "load", str(saved)])
    assert r.exit_code == 0
    assert "부분 해시 일치" in r.output and "무결성 검증" in r.output


def test_load_changed_source_asks_user(statop_home, tmp_path):
    runner = CliRunner()
    data, saved = _saved_session(runner, statop_home, tmp_path)
    data.write_bytes(data.read_bytes() + b"tampered")  # 원본 변조

    r = runner.invoke(app, ["session", "load", str(saved)], input="n\n")
    assert r.exit_code != 0 and "해시가 다릅니다" in r.output  # 거절 → 중단
    assert not list((statop_home / _uid() / "tmp").glob("session_*.json"))  # 임시본 안 생김

    r = runner.invoke(app, ["session", "load", str(saved)], input="y\n")
    assert r.exit_code == 0 and "복원된 선택" in r.output  # 사용자 결정으로 진행


def test_load_missing_source_asks_user(statop_home, tmp_path):
    runner = CliRunner()
    data, saved = _saved_session(runner, statop_home, tmp_path)
    data.unlink()
    r = runner.invoke(app, ["session", "load", str(saved)], input="n\n")
    assert r.exit_code != 0 and "파일이 없습니다" in r.output


def test_replay_reproducible_cli_output(statop_home, tmp_path):
    """S030: 같은 저장본을 두 번 불러도 복원 결과가 동일 (세션 id·경로만 다름)."""
    import re

    runner = CliRunner()
    _, saved = _saved_session(runner, statop_home, tmp_path)

    def stable(output: str) -> str:
        out = re.sub(r"s_\d{8}-\d{4}_[0-9a-f]{4}", "SID", output)  # 세션 id 제거
        return "\n".join(ln for ln in out.splitlines()
                         if not ln.startswith("작업 파일:"))       # 경로 줄 제거

    r1 = runner.invoke(app, ["session", "load", str(saved)])
    r2 = runner.invoke(app, ["session", "load", str(saved)])
    assert r1.exit_code == 0 and r2.exit_code == 0
    assert stable(r1.output) == stable(r2.output)  # 출력 diff 0


def test_source_roles_and_set_main(statop_home):
    """: 메인 파일이 바뀌어도 세션·기록은 유지되고, 교체는 op로 남는다."""
    from statop.session.core import (append_op, main_source, new_session, register_source,
                                   replay, set_main)

    doc = new_session()
    a = register_source(doc, DATA / "synth_long.parquet")                 # 기본 main
    append_op(doc, "select", source=a, cols=["site"])
    b = register_source(doc, DATA / "synth_wide.parquet", role="compare")
    assert [s["role"] for s in doc["sources"]] == ["main", "compare"]
    assert main_source(doc)["id"] == a

    entry = set_main(doc, b)
    assert entry["op"] == "set_main" and entry["previous"] == a
    assert [s["role"] for s in doc["sources"]] == ["aux", "main"]
    st = replay(doc)
    assert st["main"] == b
    assert st["selected"][a] == ["site"]          # 이전 선택 기록은 그대로 유지

    # main으로 새로 등록하면 기존 main이 aux로 내려간다
    c = register_source(doc, DATA / "synth_long.csv", role="main")
    roles = {s["id"]: s["role"] for s in doc["sources"]}
    assert roles[c] == "main" and roles[b] == "aux"


def test_hold_excludes_from_analysis_but_keeps_selection(statop_home):
    """M0-5: hold는 제외(deselect)와 다르다 — 분석에서만 빠지고 작업 영역엔 남는다."""
    from statop.session.core import append_op, new_session, register_source, replay

    doc = new_session()
    a = register_source(doc, DATA / "synth_long.parquet")
    append_op(doc, "select", source=a, cols=["patient_id", "site", "label"])
    append_op(doc, "hold", source=a, cols=["patient_id"])

    st = replay(doc)
    assert st["selected"][a] == ["patient_id", "site", "label"]   # 선택엔 남아 있고
    assert st["held"][a] == ["patient_id"]
    assert st["analysis"][a] == ["site", "label"]                  # 분석에서만 빠진다

    append_op(doc, "unhold", source=a, cols=["patient_id"])
    assert replay(doc)["analysis"][a] == ["patient_id", "site", "label"]

    # 제외(deselect)는 아예 사라진다 — hold와 구분
    append_op(doc, "deselect", source=a, cols=["patient_id"])
    st = replay(doc)
    assert "patient_id" not in st["selected"][a] and "patient_id" not in st["analysis"][a]


def test_hold_cli(statop_home):
    runner = CliRunner()
    data = str(DATA / "synth_long.parquet")
    runner.invoke(app, ["session", "new", "--data", data])
    sess = str(next((statop_home / _uid() / "tmp").glob("session_*.json")))
    runner.invoke(app, ["select", data, "--cols", "patient_id,site,label", "--session", sess])

    r = runner.invoke(app, ["hold", "--cols", "patient_id", "--session", sess])
    assert r.exit_code == 0 and "분석 대상 2개 · hold 1개" in r.output

    off = runner.invoke(app, ["hold", "--cols", "patient_id", "--session", sess, "--off"])
    assert "분석 대상 3개 · hold 0개" in off.output

    bad = runner.invoke(app, ["hold", "--cols", "nope", "--session", sess])
    assert bad.exit_code != 0     # 가져온 적 없는 컬럼은 hold 불가
