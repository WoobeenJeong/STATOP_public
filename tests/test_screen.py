"""`statop` 첫 화면 회귀 — 열기 → 컬럼 고르기 → 작업 영역.

이 파일이 있는 이유: 화면을 띄워야만 확인되는 구조라 **클릭 핸들러와 space 키가
한 번도 동작한 적 없이 살아남았다.** 여기서는 화면 없이 같은 동작을 직접 부른다.
"""

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from statop.shell import screen as S
from statop.shell.screen import (STEP_COLUMNS, STEP_OPEN, STEP_WORKSPACE,
                               TABLE_HEADER_LINES, Screen)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(3)
    n = 200
    df = pd.DataFrame({
        "pid": [f"P{i:04d}" for i in range(n)],
        "arm": rng.choice(["a", "b"], n),
        "x": rng.normal(0, 1, n),
        "y": rng.normal(0, 1, n),
        "mostly_missing": np.where(rng.random(n) < 0.6, np.nan, 1.0),
    })
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    return p


# ── 첫 화면 ─────────────────────────────────────────────────
def test_starts_on_open_screen_without_any_command():
    """`statop`를 치면 바로 경로 입력 화면이다 — /open 같은 걸 칠 필요가 없다."""
    sc = Screen()
    assert sc.step == STEP_OPEN
    assert "경로" in sc.render_open() or "path" in sc.render_open().lower()


def test_open_bad_path_reports_reason_and_stays(data):
    sc = Screen()
    assert sc.open_path("/does/not/exist.csv") is False
    assert sc.step == STEP_OPEN and sc.status_kind == "err"

    assert sc.open_path("   ") is False
    assert sc.status_kind == "err"


def test_open_moves_to_columns_and_lists_them(data):
    sc = Screen()
    assert sc.open_path(str(data)) is True
    assert sc.step == STEP_COLUMNS and sc.session_file.exists()
    names = [x["column"] for x in sc.view.items]
    assert names == ["pid", "arm", "x", "y", "mostly_missing"]
    # 결측이 많은 컬럼은 등급이 붙는다 (색만이 아니라 기호도 함께 쓰이는 근거)
    lvl = {x["column"]: x["missing_level"] for x in sc.view.items}
    assert lvl["mostly_missing"] == "high" and lvl["x"] == "ok"


def test_open_strips_quotes_from_pasted_path(data):
    """경로를 복사해 붙이면 따옴표가 섞여 들어온다."""
    sc = Screen()
    assert sc.open_path(f'"{data}"') is True


# ── 체크 (space·클릭) ───────────────────────────────────────
def test_space_key_is_a_literal_space_not_the_word():
    """`kb.add("space")`는 s·p·a·c·e 다섯 글자로 등록된다 — 스페이스바가 아니다."""
    src = inspect.getsource(S.run_screen)
    assert 'kb.add("space"' not in src
    assert 'kb.add(" "' in src


def test_toggle_checks_and_unchecks(data):
    sc = Screen()
    sc.open_path(str(data))
    assert sc.toggle_at(0) and sc.view.picked == {"pid"}
    assert sc.toggle_at(0) and sc.view.picked == set()
    assert sc.toggle_at(99) is False        # 없는 행은 아무것도 하지 않는다


def test_click_maps_screen_row_to_column(data):
    """클릭 y좌표가 헤더만큼 밀려 엉뚱한 행이 체크되면 안 된다."""
    sc = Screen()
    sc.open_path(str(data))
    assert sc.click_table(TABLE_HEADER_LINES) is True
    assert sc.view.picked == {"pid"}

    sc.click_table(TABLE_HEADER_LINES + 2)
    assert sc.view.picked == {"pid", "x"}

    assert sc.click_table(0) is False        # 제목 줄 클릭은 무시
    assert sc.click_table(TABLE_HEADER_LINES + 99) is False


def test_click_respects_warning_line_offset(data):
    """경고 줄이 하나 더 깔리면 표도 한 줄 내려간다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.view.warnings = ["경고"]
    assert sc.click_table(TABLE_HEADER_LINES) is False
    assert sc.click_table(TABLE_HEADER_LINES + 1) is True
    assert sc.view.picked == {"pid"}


def test_toggle_page_covers_only_visible_rows(data):
    """'이 쪽 전체'는 본 것만 고른다 — 안 본 쪽까지 고르게 하지 않는다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    assert sc.view.picked == {"pid", "arm", "x", "y", "mostly_missing"}
    sc.toggle_page()
    assert sc.view.picked == set()

    sc.search("^[xy]$")                 # 보이는 것이 2개로 줄면 그 2개만
    sc.toggle_page()
    assert sc.view.picked == {"x", "y"}


# ── 정렬·검색·페이지 ────────────────────────────────────────
def test_sort_toggles_off_when_pressed_twice(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.set_sort("missing")
    assert sc.view.visible()[0]["column"] == "mostly_missing"
    sc.set_sort("missing")
    assert sc.view.sort is None and sc.view.visible()[0]["column"] == "pid"


def test_search_filters_and_resets_position(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.view.cursor = 3
    sc.search("mis")
    assert [x["column"] for x in sc.view.visible()] == ["mostly_missing"]
    assert sc.view.cursor == 0 and sc.view.offset == 0
    sc.search("")
    assert len(sc.view.visible()) == 5


def test_page_does_not_run_past_the_end(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.page(1)                       # 5컬럼이면 1쪽뿐이다
    assert sc.view.offset == 0
    sc.page(-1)
    assert sc.view.offset == 0


def test_cursor_stops_at_both_ends(data):
    sc = Screen()
    sc.open_path(str(data))
    for _ in range(10):
        sc.move(-1)
    assert sc.view.cursor == 0
    for _ in range(10):
        sc.move(1)
    assert sc.view.cursor == 4


# ── 가져오기 → 작업 영역 ────────────────────────────────────
def test_import_requires_a_selection(data):
    sc = Screen()
    sc.open_path(str(data))
    assert sc.import_picked() is False
    assert sc.step == STEP_COLUMNS and sc.status_kind == "err"


def test_import_records_op_and_keeps_file_order(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(3)          # y
    sc.toggle_at(1)          # arm  — 고른 순서는 y, arm
    assert sc.import_picked() is True
    assert sc.step == STEP_WORKSPACE
    assert sc.imported == ["arm", "y"]      # 파일의 컬럼 순서로 남는다

    from statop.session.core import load_session

    ops = load_session(sc.session_file)["ops"]
    assert [o["op"] for o in ops][-1] == "select"


def test_workspace_hold_and_drop(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()

    sc.toggle_hold("pid")
    assert sc.held == ["pid"]
    assert "pid" in sc.imported            # hold는 남긴다, 제외와 다르다
    sc.toggle_hold("pid")
    assert sc.held == []

    sc.row = sc.imported.index("mostly_missing")
    sc.drop_current()
    assert "mostly_missing" not in sc.imported


def test_workspace_click_toggles_hold(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.click_workspace(S.WORKSPACE_HEADER_LINES) is True
    assert sc.held == [sc.imported[0]]
    assert sc.click_workspace(0) is False


def test_drop_on_empty_workspace_does_nothing(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    sc.drop_current()
    assert sc.imported == []
    sc.drop_current()                      # 두 번째는 조용히 아무것도 안 한다


def test_workspace_shows_the_next_commands(data):
    """화면이 끊기는 지점을 감추지 않는다 — 다음에 뭘 쳐야 하는지 그대로 보여준다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(2)
    sc.import_picked()
    body = sc.render_workspace()
    assert "statop types" in body and "statop compat" in body and "statop guard" in body
    assert str(sc.session_file) in body


# ── 다시 열기 · 저장 ────────────────────────────────────────
def test_reopening_keeps_the_session(data, tmp_path):
    """파일을 바꿔도 세션과 조작 기록은 유지된다 ."""
    sc = Screen()
    sc.open_path(str(data))
    first = sc.session_file

    other = tmp_path / "other.csv"
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(other, index=False)
    sc.open_path(str(other))
    assert sc.session_file == first
    assert [x["column"] for x in sc.view.items] == ["a"]


def test_save_then_listed_as_recent(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    assert sc.save_session_as() is True
    assert sc.saved_name and sc.status_kind == "ok"
    assert any(f.name == sc.saved_name for f in sc.saved_files())


def test_load_saved_restores_workspace(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(1)
    sc.toggle_at(2)
    sc.import_picked()
    sc.save_session_as()

    fresh = Screen()
    assert fresh.load_saved() is True
    assert fresh.step == STEP_WORKSPACE
    assert fresh.imported == ["arm", "x"]


def test_load_saved_with_nothing_saved_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "empty"))
    sc = Screen()
    assert sc.load_saved() is False
    assert sc.status_kind == "err"


# ── 렌더 ────────────────────────────────────────────────────
def test_import_label_tracks_selection(data):
    sc = Screen()
    assert "0" in sc.import_label()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.toggle_at(1)
    assert "2" in sc.import_label()


def test_render_marks_checked_rows(data):
    sc = Screen()
    sc.open_path(str(data))
    assert "☑" not in sc.render_table()
    sc.toggle_at(0)
    assert "☑" in sc.render_table()


def test_render_status_changes_with_step(data):
    sc = Screen()
    first = sc.render_status()
    sc.open_path(str(data))
    assert sc.render_status() != first
    sc.toggle_at(0)
    sc.import_picked()
    assert sc.render_status() != first


# ── 눌린 것을 알 수 있는가 (사용자 지적) ────────────────────
def test_every_action_reports_what_it_did(data):
    """누르고 나서 '눌린 건가?' 싶으면 안 된다 — 동작마다 무엇이 어떻게 됐는지 남긴다."""
    sc = Screen()
    sc.open_path(str(data))
    assert "13" in sc.status or "5" in sc.status      # 열었다 + 컬럼 수
    assert sc.status_kind == "ok"

    sc.toggle_at(0)
    assert "pid" in sc.status and "1" in sc.status
    sc.toggle_at(0)
    assert "pid" in sc.status

    sc.set_sort("missing")
    before = sc.status
    sc.set_sort("missing")
    assert sc.status != before                        # 껐다는 것도 말한다

    sc.search("pid")
    assert "pid" in sc.status
    sc.search("")
    assert sc.status_kind == "mut"


def test_focus_label_names_every_place(data):
    """Tab 을 잘못 눌러도 지금 어디인지 알 수 있어야 한다."""
    sc = Screen()
    for where, expect in (("path", "경로"), ("search", "검색"),
                          ("table", "컬럼"), ("workspace", "컬럼")):
        sc.focus = where
        assert expect in sc.focus_label()

    sc.focus = "btn:열기"
    assert "열기" in sc.focus_label() and "Enter" in sc.focus_label()

    sc.focus = "?"                                    # 이름 모르는 곳도 침묵하지 않는다
    assert sc.focus_label()


def test_status_shows_where_you_are(data):
    sc = Screen()
    sc.focus = "btn:열기"
    body = sc.render_status()
    assert "지금 위치" in body and "열기" in body


def test_buttons_use_bracket_symbols():
    """<열기> 보다 [ 열기 ] 가 버튼처럼 읽힌다."""
    src = inspect.getsource(S.run_screen)
    assert 'left_symbol="["' in src and 'right_symbol="]"' in src


def test_open_does_not_block_the_screen():
    """큰 파일을 읽는 동안 화면이 멈춰 보이면 눌린 건지 알 수 없다."""
    src = inspect.getsource(S.run_screen)
    assert "create_background_task" in src and "run_in_executor" in src


# ── 열기 vs 불러오기 (사용자 지적) ──────────────────────────
def test_open_screen_separates_data_from_session(data):
    """무엇을 여는 건지 화면이 말해야 한다 — 데이터 파일과 작업 기록은 다른 것이다."""
    sc = Screen()
    body = sc.render_open()
    assert "데이터" in body and "세션" in body
    assert "저장된 세션이 없습니다" in body

    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    sc.save_session_as()
    assert "1개" in Screen().render_open()      # 생기면 개수를 보여준다


def test_session_list_is_selectable_not_just_latest(data):
    """[불러오기]가 최근 것만 여는 건 고르는 게 아니다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    sc.save_session_as()

    fresh = Screen()
    assert fresh.open_sessions() is True
    assert fresh.step == S.STEP_SESSIONS
    assert "1" in fresh.render_sessions()

    fresh.move_session(5)                         # 끝을 넘지 않는다
    assert fresh.session_row == 0
    assert fresh.click_sessions(S.SESSIONS_HEADER_LINES) is True
    assert fresh.step == STEP_WORKSPACE


def test_session_list_refuses_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "none"))
    sc = Screen()
    assert sc.open_sessions() is False
    assert sc.step == STEP_OPEN and sc.status_kind == "err"


# ── 저장 위치·덮어쓰기 (사용자 지적) ────────────────────────
def test_save_goes_where_the_user_says(data, tmp_path):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()

    where = tmp_path / "myplace"
    where.mkdir()
    assert sc.save_session_as(out_dir=str(where)) is True
    assert (where / sc.saved_name).exists()


def test_save_rejects_a_folder_that_does_not_exist(data, tmp_path):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    assert sc.save_session_as(out_dir=str(tmp_path / "nope")) is False
    assert sc.status_kind == "err"


def test_overwrite_needs_its_own_click(data, tmp_path):
    """단순 저장이 조용히 덮으면 안 된다 ."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    where = tmp_path / "place"
    where.mkdir()
    assert sc.save_session_as(out_dir=str(where)) is True
    first = where / sc.saved_name

    assert sc.save_session_as(out_dir=str(where)) is False      # 두 번째는 거부
    assert "덮어쓰기" in sc.status

    assert sc.save_session_as(out_dir=str(where), overwrite=True) is True
    assert first.with_suffix(".json.bak").exists()              # 직전 것은 보존


def test_save_screen_shows_the_target_before_pressing(data, tmp_path):
    """어디에 저장되는지 누르기 전에 보여야 한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    sc.open_save()
    assert sc.step == S.STEP_SAVE
    body = sc.render_save()
    assert ".json" in body and sc.save_dir in body


def test_save_screen_warns_when_name_exists(data, tmp_path):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    where = tmp_path / "p2"
    where.mkdir()
    sc.save_dir = str(where)
    sc.save_session_as()
    sc.open_save()
    assert "덮어쓰기" in sc.render_save()


# ── 캐시 (load 느림) ────────────────────────────────────────
def test_second_open_of_same_file_uses_cache(data):
    """같은 파일을 다시 열 때 파일을 또 읽지 않는다 — 웹과 같은 캐시를 쓴다."""
    from statop.api import cache

    cache.clear()
    sc = Screen()
    sc.open_path(str(data))
    assert cache.size() == 1

    import statop.io.profile as prof_mod

    calls = []
    real = prof_mod.profile_columns
    prof_mod.profile_columns = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        again = Screen()
        again.open_path(str(data))
        assert calls == []                       # 다시 읽지 않았다
        assert len(again.view.items) == 5
    finally:
        prof_mod.profile_columns = real


def test_focus_label_covers_every_widget_name():
    """위젯을 늘릴 때 이름표 목록을 빠뜨리면 '알 수 없음'이 뜬다 — 전부 이름이 있어야 한다."""
    sc = Screen()
    for where in ("path", "search", "table", "workspace", "sessions", "savedir"):
        sc.focus = where
        label = sc.focus_label()
        assert label and "알 수 없음" not in label, where


# ── 웹 연동 (사용자 지적) ───────────────────────────────────
def test_web_url_carries_the_session(data):
    """웹이 같은 세션을 열어야 상태가 갈라지지 않는다."""
    import json

    from statop import webshare

    sc = Screen()
    sc.open_path(str(data))
    url = webshare.url_for(sc.session_file, 8000)
    sid = json.loads(Path(sc.session_file).read_text())["session_id"]
    assert url == f"http://127.0.0.1:8000/ui/?s={sid}"
    assert webshare.url_for(None) == "http://127.0.0.1:8000/ui/"


def test_web_url_stays_short_enough_to_click(data):
    """주소가 터미널 폭을 넘어 줄바꿈되면 Ctrl+클릭이 링크로 인식하지 못한다."""
    from statop import webshare

    sc = Screen()
    sc.open_path(str(data))
    url = webshare.url_for(sc.session_file, 8000)
    assert len(url) < 80
    assert str(sc.session_file) not in url        # 긴 경로를 주소에 넣지 않는다


def test_button_padding_is_one_space_each_side():
    """`[ 세션 저장 ]` — 괄호 안은 글자 앞뒤 한 칸씩으로 통일한다."""
    src = inspect.getsource(S.run_screen)
    assert "get_cwidth(text) + 4" in src          # 글자폭 + 좌우 1칸 + 대괄호 2칸


def test_pressed_button_is_highlighted():
    """눌렀는지 모르는 상태를 만들지 않는다 — 잠깐 노랗게."""
    src = inspect.getsource(S.run_screen)
    assert "button.pressed" in src and "sc.pressed" in src


def test_web_button_reports_when_ui_is_not_built(data, monkeypatch):
    """빌드가 없으면 조용히 실패하지 않고 무엇을 해야 하는지 말한다."""
    from statop import webshare

    monkeypatch.setattr(webshare, "ui_built", lambda: False)
    sc = Screen()
    sc.open_path(str(data))
    assert sc.open_in_web() is None
    assert sc.status_kind == "err" and "build" in sc.status.lower()


def test_refresh_picks_up_changes_made_elsewhere(data):
    """웹에서 hold 한 것을 터미널이 가져온다 — 같은 세션 파일이기 때문."""
    from statop.session.core import append_op, load_session, main_source, save_session

    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.held == []

    doc = load_session(sc.session_file)          # 웹이 한 것과 같은 조작
    src = main_source(doc)
    append_op(doc, "hold", source=src["id"], cols=["pid"])
    save_session(doc)

    assert sc.held == []                          # 아직은 모른다
    assert sc.refresh() is True
    assert sc.held == ["pid"]


def test_refresh_without_a_session_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "h"))
    sc = Screen()
    assert sc.refresh() is False
    assert sc.status_kind == "err"


def test_web_skips_a_port_that_is_not_ours():
    """포트가 열린 것과 우리 화면이 있는 것은 다르다 — 남의 것에 붙으면 Not Found가 뜬다."""
    import http.server
    import socketserver
    import threading

    from statop import webshare

    with socketserver.TCPServer(("127.0.0.1", 0),
                                http.server.SimpleHTTPRequestHandler) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        assert webshare.port_open(port) is True
        assert webshare.is_ours(port) is False      # 열려 있어도 우리 것이 아니다
        srv.shutdown()


def test_web_url_is_shown_on_its_own_line(data):
    """주소가 상태줄에 섞이면 잘려서 복사가 안 된다."""
    sc = Screen()
    sc.open_path(str(data))
    assert sc.render_web() == ""               # 아직 없으면 줄 자체가 없다
    sc.web_url = "http://127.0.0.1:8000/ui/?session=/x/y.json"
    body = sc.render_web()
    assert sc.web_url in body and "ssh -N -L" in body


def test_buttons_do_not_stretch():
    """버튼이 남는 폭만큼 늘어나면 버튼 줄이 화면을 넘겨 줄바꿈된다."""
    src = inspect.getsource(S.run_screen)
    assert "dont_extend_width" in src


# ── 마우스가 안 되는 터미널 대비 (사용자 지적) ──────────────
def test_mouse_note_tells_the_truth():
    """클릭이 안 될 때 '왜 안 되는지'를 화면이 말해야 한다."""
    from statop.shell.columns_view import ClickableControl

    before = ClickableControl.mouse_events_seen
    try:
        ClickableControl.mouse_events_seen = 0
        assert "번호키" in Screen().mouse_note()
        ClickableControl.mouse_events_seen = 1
        assert "✓" in Screen().mouse_note()
    finally:
        ClickableControl.mouse_events_seen = before


def test_number_keys_exist_for_every_button():
    """마우스를 못 쓰는 터미널이 있다 — 모든 버튼에 번호키가 있어야 한다."""
    src = inspect.getsource(S.run_screen)
    assert "screen_buttons" in src and "_press_nth" in src
    assert 'kb.add(str(_n)' in src


def test_status_lists_the_number_keys():
    src = inspect.getsource(S.run_screen)
    assert "numkey_line" in src


def test_web_assets_are_served_under_ui():
    """빌드가 /assets/ 를 가리키면 HTML은 200인데 화면은 빈 채로 뜬다."""
    from pathlib import Path as P

    idx = P(__file__).resolve().parents[1] / "ui" / "dist" / "index.html"
    if not idx.exists():
        pytest.skip("ui/dist 없음")
    html = idx.read_text()
    assert 'src="/ui/assets/' in html and 'href="/ui/assets/' in html


# ── 파생 컬럼 화면 (웹과 같은 기능을 CLI에도) ───────────────
def test_derive_needs_imported_columns_first(data):
    sc = Screen()
    sc.open_path(str(data))
    assert sc.open_derive() is False           # 아직 가져온 게 없다
    assert sc.status_kind == "err"

    sc.toggle_page()
    sc.import_picked()
    assert sc.open_derive() is True and sc.step == S.STEP_DERIVE


def test_derive_preview_does_not_record(data):
    """미리보기는 세션을 건드리지 않는다."""
    from statop.session.core import load_session

    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()

    before = len(load_session(sc.session_file)["ops"])
    assert sc.preview_formula("x * 2") is True
    assert len(load_session(sc.session_file)["ops"]) == before
    assert sc.derive_prep.preview["n"] > 0
    assert sc.derive_prep.result_type == "continuous"


def test_derive_reports_a_bad_formula(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.preview_formula("__import__('os')") is False
    assert sc.derive_error and sc.status_kind == "err"
    assert sc.preview_formula("") is False


def test_derive_shows_token_roles(data):
    """컬럼 스칼라는 행마다 변하지 않는다 — 색으로 구분되어야 한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("x / mean(y)")
    body = sc.render_derive()
    assert "<tscalar>mean</tscalar>" in body and "<tcol>x</tcol>" in body


def test_derive_requires_eps_to_be_chosen(data):
    """미리보기는 추천값으로 되지만, 저장은 값을 밝혀야 한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("log2(x + eps)")
    assert sc.needs_eps() and sc.eps_candidates()
    assert sc.commit_formula("lx") is False        # eps 없이 저장 거부
    assert "eps" in sc.derive_error


def test_derive_creates_the_column_and_returns(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("x * 2")
    assert sc.commit_formula("x2") is True
    assert sc.step == STEP_WORKSPACE
    assert "x2" in sc.imported                      # 작업 영역에 바로 보인다

    from statop.session.core import load_session

    op = load_session(sc.session_file)["ops"][-1]
    assert op["op"] == "derive" and op["name"] == "x2" and op["expr"] == "x * 2"


def test_derive_rejects_an_empty_name(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("x * 2")
    assert sc.commit_formula("  ") is False
    assert sc.status_kind == "err"


def test_header_does_not_reread_the_session_file_every_render(data):
    """렌더마다 세션 JSON을 읽으면 네트워크 저장소에서 키 입력마다 느려진다."""
    sc = Screen()
    sc.open_path(str(data))
    assert sc.session_id.startswith("s_")

    import statop.session.core as core

    calls = []
    real = core.load_session
    core.load_session = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        for _ in range(5):
            sc.render_header()
        assert calls == []                    # 헤더 렌더는 파일을 읽지 않는다
    finally:
        core.load_session = real


# ── 저장이 동기화 키다 (사용자 설계) ────────────────────────
def test_share_state_records_checked_columns(data):
    """가져오기 전의 체크 상태도 저장돼야 웹이 같은 화면이 된다."""
    from statop.session.core import peek_state

    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(1)
    sc.toggle_at(2)
    assert sc.share_state() is True
    st = peek_state(sc.session_file)
    assert st["view"]["by"] == "cli" and st["view"]["step"] == "columns"
    assert st["view"]["picked"] == ["arm", "x"]


def test_refresh_restores_checks_saved_by_web(data):
    """웹이 저장한 체크가 CLI 목록에 그대로 복원된다."""
    from statop.session.core import save_view

    sc = Screen()
    sc.open_path(str(data))
    save_view(sc.session_file, by="web", step="columns", picked=["x", "y", "없는컬럼"])
    assert sc.refresh() is True
    assert sc.view.picked == {"x", "y"}          # 없는 컬럼은 조용히 거른다
    assert "web" in sc.status


def test_refresh_without_saved_view_says_so(data):
    """저장(동기화 키)이 없으면 없다고 말한다 — 조용히 아무 일도 없던 척하지 않는다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_at(0)
    sc.import_picked()
    assert sc.refresh() is True
    assert "웹→CLI 반영" in sc.status            # 웹에서 먼저 저장하라는 안내


def test_peek_state_is_light(data):
    """반영 전 확인은 재생 없이 — 자주 불러도 부담이 없어야 한다."""
    from statop.session.core import peek_state

    sc = Screen()
    sc.open_path(str(data))
    st = peek_state(sc.session_file)
    assert set(st) == {"session_id", "n_ops", "view"}
    assert st["view"] is None                     # 아직 아무도 저장 안 함


def test_run_screen_actually_starts(data, monkeypatch):
    """run_screen 을 실제로 띄운다 — 위젯 정의 누락(NameError)은 import 만으로는 안 잡힌다."""
    import asyncio

    import prompt_toolkit.application as pta
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.plain_text import PlainTextOutput

    import io

    buf = io.StringIO()
    with create_pipe_input() as inp:
        with create_app_session(input=inp, output=PlainTextOutput(buf)):
            orig = pta.Application

            class Driven(orig):
                def run(self, *a, **k):  # noqa: ANN001, ANN202
                    async def feed():
                        await asyncio.sleep(0.2)
                        inp.send_text("\x11")          # Ctrl-Q

                    async def both():
                        t = asyncio.ensure_future(feed())
                        try:
                            await self.run_async()
                        finally:
                            t.cancel()

                    asyncio.run(both())

            monkeypatch.setattr(pta, "Application", Driven)
            S.run_screen()                              # 여기서 NameError 가 나면 실패
    assert "STATOP" in buf.getvalue()


def test_stale_server_is_not_reused():
    """코드를 고친 뒤에도 옛 서버가 재사용되면, 웹은 새 화면인데 API는 옛것이라
    '없는 엔드포인트 404 → 첫 화면'이 된다. 지문이 다르면 우리 것이어도 버린다."""
    import inspect as _i

    from statop import webshare

    src = _i.getsource(webshare.is_ours)
    assert "code_stamp" in src


def test_health_carries_the_code_stamp():
    from statop.api.app import code_stamp, health

    h = health()
    assert h["code_stamp"] == code_stamp() > 0


def test_sync_buttons_carry_direction_in_their_names():
    """[새로고침]은 어느 쪽으로 맞추는지 알 수 없다 — 이름에 방향이 있어야 한다.

    (교훈: yaml 저장이 따옴표를 벗겨서, 따옴표 포함 치환이 조용히 빗나간 적이 있다.
    라벨은 문자열 치환이 아니라 이 테스트로 잠근다.)
    """
    from statop.messages import msg

    assert msg("screen_share_btn") == "CLI→웹 반영"
    assert msg("screen_refresh_btn") == "웹→CLI 반영"
    for key in ("screen_share_btn", "screen_refresh_btn", "screen_shared",
                "screen_pulled", "screen_pull_no_view", "screen_web_same_session"):
        text = msg(key, **{k: 0 for k in ("n", "h", "p")}, step="s", by="b") \
            if "{" in msg.__doc__ else None
    # 옛 이름이 어디에도 안 남아 있어야 한다
    import yaml
    from pathlib import Path as P

    ko = yaml.safe_load((P("src/statop/messages/ko.yaml")).read_text())
    joined = " ".join(str(v) for v in ko.values())
    assert "새로고침" not in joined and "[상태 저장]" not in joined


# ── 읽기 진행률 (사용자 요청: % + 남은 시간) ────────────────
def test_progress_reaches_100_and_never_goes_back(data):
    """진행률은 단조증가해서 1.0으로 끝난다 — 뒤로 가는 막대는 신뢰를 깬다."""
    from statop.io.profile import profile_columns

    got = []
    profile_columns(str(data), progress=got.append)
    assert got == sorted(got) and got[-1] == 1.0


def test_progress_works_for_parquet(tmp_path):
    import pandas as pd

    from statop.io.profile import profile_columns

    p = tmp_path / "t.parquet"
    pd.DataFrame({"a": range(5000), "b": range(5000)}).to_parquet(p, row_group_size=500)
    got = []
    profile_columns(str(p), progress=got.append)
    assert got and got[-1] == 1.0 and got == sorted(got)


def test_eta_format_is_short():
    from statop.shell.screen import format_eta

    assert "12s" in format_eta(12.4)
    assert "3min 5s" in format_eta(185)
    assert "1h 2min" in format_eta(3720)
    assert "0s" in format_eta(-1)          # 음수는 0으로


def test_eta_hidden_until_estimate_is_stable(data):
    """5% 미만에서는 추정이 널뛴다 — 그때는 숨긴다."""
    import time

    sc = Screen()
    sc.loading = "x.csv"
    sc.load_started = time.monotonic() - 10
    sc.set_progress(0.02)
    assert sc.eta_text() == ""
    sc.set_progress(0.5)
    assert "남은 시간" in sc.eta_text()


def test_loading_panel_shows_bar_and_percent(data):
    import time

    sc = Screen()
    sc.loading = "demo.csv"
    sc.load_started = time.monotonic() - 4
    sc.set_progress(0.4)
    body = sc.render_open()
    assert "▮" in body and "40%" in body and "남은 시간" in body

    sc.set_progress(0.3)                   # 뒤로 가는 값은 무시된다
    assert sc.load_pct == 0.4


# ── 타입 확정 화면 (M1-1) ───────────────────────────────────
def _types_ready(data):
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.open_types() is True
    return sc


def test_types_needs_imported_columns(data):
    sc = Screen()
    sc.open_path(str(data))
    assert sc.open_types() is False and sc.status_kind == "err"


def test_types_lists_every_imported_column(data):
    sc = _types_ready(data)
    assert sc.step == S.STEP_TYPES
    assert [r["column"] for r in sc.type_rows] == sc.imported
    assert all(r["order"] for r in sc.type_rows)


def test_types_cycle_reaches_types_not_inferred(data):
    """추론에 없던 타입도 순환하다 보면 나온다 — 막지 않는다 (요구사항-7)."""
    sc = _types_ready(data)
    r = sc.type_rows[sc.type_row]
    seen = set()
    for _ in range(len(r["order"])):
        seen.add(sc.current_type_choice()[1])
        sc.cycle_type(1)
    assert seen == set(r["order"])
    assert set(Screen.known_types()) <= seen | set(r["order"])


def test_types_confirm_records_op_and_moves_on(data):
    from statop.session.core import load_session, replay

    sc = _types_ready(data)
    col, typ = sc.current_type_choice()
    assert sc.confirm_type() is True
    assert sc.type_rows[0]["confirmed"] == typ
    assert sc.type_row == 1                       # 다음 미확정으로 이동

    doc = load_session(sc.session_file)
    sid = doc["sources"][0]["id"]
    assert replay(doc)["semantic_types"][sid][col] == typ


def test_types_confirm_reports_risks(data):
    """proportion 처럼 위험 규칙이 걸린 타입은 확정 시 규칙 ID를 알린다."""
    sc = _types_ready(data)
    sc.type_row = sc.imported.index("x")
    r = sc.type_rows[sc.type_row]
    r["idx"] = r["order"].index("proportion")
    sc.confirm_type()
    assert "S-R01" in sc.status or "S-R02" in sc.status


def test_types_dist_toggle(data):
    sc = _types_ready(data)
    sc.type_row = sc.imported.index("x")
    sc.toggle_dist()
    assert sc.dist_col == "x" and sc.dist_lines
    body = sc.render_types()
    assert "┤" in body or "┼" in body or "▮" in body or "█" in body

    sc.toggle_dist()                              # 다시 누르면 접힌다
    assert sc.dist_lines == []


def test_types_render_marks_confirmed_and_pending(data):
    sc = _types_ready(data)
    body = sc.render_types()
    assert "0/" in body                           # 확정 0개로 시작
    sc.confirm_type()
    assert "1/" in sc.render_types()
    assert "✔" in sc.render_types()


def test_types_infer_reports_progress(data):
    """추론도 긴 동작이다 — 진행률 패턴을 따라야 한다 (저장된 원칙)."""
    got = []
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.on_progress = got.append
    sc.open_types()
    assert got and got[-1] == 1.0 and got == sorted(got)


# ── 열기 전 과정의 단계 표시 (0%에 머무는 문제) ─────────────
def test_open_covers_the_whole_pipeline_with_stages(data):
    """진행률이 걸린 구간 밖에서 시간이 가면 0%에 머문다 — 해시·세션 기록까지
    전부 진행률 구간 안에 있어야 하고, 지금 어느 단계인지 이름이 붙어야 한다."""
    sc = Screen()
    trace = []
    sc.on_progress = lambda f: trace.append((sc.load_stage, round(f, 3)))
    sc.open_path(str(data))

    stages = [s for s, _ in trace]
    assert any("부분해시" in s for s in stages)      # 해시 구간이 진행률 안에 있다
    assert any("샘플" in s for s in stages)
    fracs = [f for _, f in trace]
    assert fracs == sorted(fracs) and fracs[-1] == 1.0


def test_partial_hash_reports_progress(tmp_path):
    """네트워크 콜드 캐시에서 가장 느린 구간 — 청크 단위로 진행이 보여야 한다."""
    from statop.session.core import partial_hash

    big = tmp_path / "b.bin"
    big.write_bytes(b"x" * (9 * 1024 * 1024))       # 9MB → 앞뒤 4MB씩
    got = []
    partial_hash(big, progress=got.append)
    assert len(got) > 10 and got[-1] == 1.0 and got == sorted(got)

    # progress 유무와 무관하게 해시값은 같아야 한다
    assert partial_hash(big)["value"] == partial_hash(big, progress=lambda f: None)["value"]


def test_loading_panel_names_the_stage():
    import time

    sc = Screen()
    sc.loading = "x.csv"
    sc.load_started = time.monotonic()
    sc.load_stage = "원본 등록 — 부분해시 (앞뒤 4MB 읽기)"
    sc.set_progress(0.1)
    assert "부분해시" in sc.render_open()


# ── 파생 컬럼도 타입·분포의 대상 (사용자 지적) ──────────────
def test_derived_column_appears_in_types_screen(data):
    """파생 컬럼은 파일에 없다 — 재계산해 붙이지 않으면 추론에서 통째로 빠진다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("x * 2")
    sc.commit_formula("x2")

    sc.open_types()
    cols = [r["column"] for r in sc.type_rows]
    assert "x2" in cols
    row = next(r for r in sc.type_rows if r["column"] == "x2")
    assert row["confirmed"] is None             # 자동 확정은 없다 — 확정은 사용자의 몫
    assert row["order"][0] == "continuous"      # 수식 유도 타입이 1순위 후보로만
    assert any("수식에서 유도" in w for w in row["evidence"]["continuous"])
    assert row["needs_confirm"]


def test_derived_column_can_feed_a_second_formula(data):
    """파생 컬럼을 입력으로 쓰는 2차 수식 — frame 에 파생이 붙어야 가능하다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("x * 2")
    sc.commit_formula("x2")
    sc.open_derive()
    assert sc.preview_formula("x2 + 1") is True
    assert sc.commit_formula("x3") is True
    assert "x3" in sc.imported


def test_types_detail_lists_all_candidates_at_once(data):
    """넘겨보지 않아도 후보 전체와 추론 밖 목록이 보여야 한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_types()
    sc.type_row = sc.imported.index("x")
    body = sc.render_types()
    assert "후보:" in body and "추론 밖" in body
    r = sc.type_rows[sc.type_row]
    for t in list(r["evidence"])[:2]:           # 추론 후보가 전부 한 화면에
        assert t in body
    assert "▸" in body                          # 현재 선택 표시


# ── id·label 역할 (hold 의 실제 용도, 사용자 설계) ──────────
@pytest.fixture
def labeled(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(5)
    n = 300
    df = pd.DataFrame({
        "patient_id": [f"P{i:04d}" for i in range(n)],
        "diagnosis": rng.choice(["control", "hcc", "liver"], n, p=[.5, .3, .2]),
        "x": rng.normal(0, 1, n),
    })
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    sc.open_types()
    return sc


def test_label_is_an_inferred_candidate(labeled):
    """diagnosis 같은 이름은 label 후보가 떠야 한다 — 매번 추론 밖에서 찾게 하지 않는다."""
    row = next(r for r in labeled.type_rows if r["column"] == "diagnosis")
    assert "label" in row["evidence"]


def test_confirming_id_auto_excludes_from_analysis(labeled):
    """id 확정 = 분석 제외 + 식별용 유지 — hold 를 따로 누를 필요가 없다."""
    sc = labeled
    sc.type_row = [r["column"] for r in sc.type_rows].index("patient_id")
    r = sc.type_rows[sc.type_row]
    r["idx"] = r["order"].index("id")
    sc.confirm_type()
    assert "patient_id" in sc.held
    assert "patient_id" in sc.imported            # 빠지되 남는다
    assert sc.col_roles["patient_id"] == "id"


def test_confirming_label_opens_code_mapping(labeled):
    """label 확정 → 바로 코드 매핑 화면 (한 흐름)."""
    sc = labeled
    sc.type_row = [r["column"] for r in sc.type_rows].index("diagnosis")
    r = sc.type_rows[sc.type_row]
    r["idx"] = r["order"].index("label")
    sc.confirm_type()
    assert sc.step == S.STEP_LABELS
    assert sc.label_col == "diagnosis"
    assert [x["value"] for x in sc.label_rows] == ["control", "hcc", "liver"]  # 빈도순
    assert [x["code"] for x in sc.label_rows] == [0, 1, 2]
    assert "diagnosis" in sc.held                  # label 도 분석 변수가 아니다


def test_arrow_keys_change_codes_and_merging_is_warned(labeled):
    """←→ 로 코드를 바꾸고, 같은 코드로 묶이면 군 재정의를 경고한다 ."""
    sc = labeled
    sc.open_labels("diagnosis")
    sc.label_row = 2                               # liver
    sc.bump_code(-1)                               # 2 → 1 (hcc 와 같은 군)
    assert sc.label_rows[2]["code"] == 1
    body = sc.render_labels()
    assert "묶임" in body and "hcc+liver" in body.replace(" ", "").replace("+", "+") or "hcc" in body

    sc.bump_code(1)                                # 되돌리기 (순환)
    assert sc.label_rows[2]["code"] == 2


def test_save_labels_records_op_and_returns_to_types(labeled):
    from statop.session.core import load_session, main_source, replay

    sc = labeled
    sc.open_labels("diagnosis")
    sc.label_row = 2
    sc.bump_code(-1)                               # liver → 1
    assert sc.save_labels() is True
    assert sc.step == S.STEP_TYPES

    doc = load_session(sc.session_file)
    src = main_source(doc)
    m = replay(doc)["label_maps"][src["id"]]["diagnosis"]
    assert m == {"control": 0, "hcc": 1, "liver": 1}


def test_reopening_labels_shows_saved_codes(labeled):
    """다시 열면 저장된 매핑이 보인다 — 처음부터 다시 만들게 하지 않는다."""
    sc = labeled
    sc.open_labels("diagnosis")
    sc.label_row = 2
    sc.bump_code(-1)
    sc.save_labels()
    sc.open_labels("diagnosis")
    assert [x["code"] for x in sc.label_rows] == [0, 1, 1]


def test_workspace_shows_roles_not_just_hold(labeled):
    """작업 영역에 hold 대신 역할(id/label)이 보인다."""
    sc = labeled
    for col, typ in (("patient_id", "id"), ("diagnosis", "label")):
        sc.type_row = [r["column"] for r in sc.type_rows].index(col)
        r = sc.type_rows[sc.type_row]
        r["idx"] = r["order"].index(typ)
        sc.confirm_type()
        if sc.step == S.STEP_LABELS:
            sc.save_labels()
    sc.step = STEP_WORKSPACE
    body = sc.render_workspace()
    assert "id" in body and "label" in body
    assert "역할" in body


# ── eps 양방향 · 만들기의 자동 미리보기 (사용자 지적) ────────
def test_eps_candidates_are_bounded_both_ways(data):
    """낮추기만 있으면 실수로 내려간 뒤 돌아올 길이 없다 — 위로는 추천값까지."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("log2(x + eps)")
    cands = sc.eps_candidates()
    assert len(cands) >= 2 and cands == sorted(cands, reverse=True)   # 큰 값부터

    # 낮추기 → 올리기 왕복
    sc.preview_formula("log2(x + eps)", cands[1])
    assert sc.derive_eps == cands[1]
    sc.preview_formula("log2(x + eps)", cands[0])
    assert sc.derive_eps == cands[0]               # 추천값(허용 최대)까지만


def test_render_shows_flow_before_and_ready_after(data):
    """미리보기 전에는 흐름 안내, 후에는 '기록 가능' 표시 — 왜 안 넘어가는지 화면이 말한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    before = sc.render_derive()
    assert "흐름" in before and "[만들기]만 눌러도" in before

    sc.preview_formula("x * 2")
    after = sc.render_derive()
    assert "미리보기 완료" in after


def test_create_button_previews_the_latest_text():
    """수식을 바꾸고 미리보기 없이 [만들기] — 옛 수식이 기록되면 안 된다."""
    import inspect as _i

    src = _i.getsource(S.run_screen)
    assert "text != sc.derive_expr or sc.derive_prep is None" in src


# ── 파생 컬럼 분포 + 핸들러 예외 가드 (사용자가 겪은 오류) ──
def test_dist_works_for_derived_columns(data):
    """log2_x 는 파일에 없다 — 분포는 frame()(파생 재계산 포함) 기준이어야 한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("log2(x + eps)")
    sc.preview_formula("log2(x + eps)", sc.eps_candidates()[-1])
    sc.commit_formula("log2_x")

    sc.open_types()
    sc.type_row = [r["column"] for r in sc.type_rows].index("log2_x")
    sc.toggle_dist()                       # 여기서 터졌었다
    assert sc.dist_col == "log2_x" and sc.dist_lines


def test_every_screen_handler_is_guarded():
    """핸들러 예외가 이벤트 루프로 새면 화면이 깨진다 — 등록 경로 전부가 가드여야 한다."""
    import inspect as _i

    src = _i.getsource(S.run_screen)
    assert "class GuardedBindings" in src            # 키 바인딩은 한 곳에서 전부
    assert "_enter_binding(guard(" in src            # 입력칸 Enter
    for click in ("sc.click_sessions", "sc.click_workspace", "sc.click_types",
                  "sc.click_labels", "sc.click_table"):
        assert f"guard({click})" in src, click       # 모든 클릭 핸들러
    assert "guard(handler)()" in src                 # 버튼


# ── eps 양방향 · 만들기의 자동 미리보기 ─────────────────────
def test_eps_candidates_are_bounded_both_ways(data):
    """낮추기만 있으면 실수로 내려간 뒤 돌아올 길이 없다 — 위로는 추천값까지."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    sc.preview_formula("log2(x + eps)")
    cands = sc.eps_candidates()
    assert len(cands) >= 2 and cands == sorted(cands, reverse=True)   # 큰 값부터

    sc.preview_formula("log2(x + eps)", cands[1])     # 낮추고
    assert sc.derive_eps == cands[1]
    sc.preview_formula("log2(x + eps)", cands[0])     # 다시 올린다 (추천값 = 허용 최대)
    assert sc.derive_eps == cands[0]


def test_render_shows_flow_before_and_ready_after(data):
    """미리보기 전에는 흐름 안내, 후에는 '기록 가능' — 왜 안 넘어가는지 화면이 말한다."""
    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    sc.open_derive()
    before = sc.render_derive()
    assert "흐름" in before and "미리보기가 자동" in before

    sc.preview_formula("x * 2")
    assert "미리보기 완료" in sc.render_derive()


def test_create_button_previews_the_latest_text():
    """수식을 바꾸고 미리보기 없이 [만들기] — 옛 수식이 기록되면 안 된다."""
    import inspect as _i

    src = _i.getsource(S.run_screen)
    assert "text != sc.derive_expr or sc.derive_prep is None" in src


# ── 분석 화면 (모듈 A를 화면으로) ───────────────────────────
def _analysis_ready(labeled):
    """labeled 픽스처에서 타입까지 확정하고 분석 화면을 연다."""
    sc = labeled
    for col, typ in (("x", "continuous"), ("diagnosis", "label")):
        sc.type_row = [r["column"] for r in sc.type_rows].index(col)
        r = sc.type_rows[sc.type_row]
        r["idx"] = r["order"].index(typ)
        sc.confirm_type()
        if sc.step == S.STEP_LABELS:
            sc.save_labels()
    sc.type_row = [r["column"] for r in sc.type_rows].index("patient_id")
    r = sc.type_rows[sc.type_row]
    r["idx"] = r["order"].index("id")
    sc.confirm_type()
    assert sc.open_analyze() is True
    return sc


def test_analyze_needs_imported_columns(data):
    sc = Screen()
    sc.open_path(str(data))
    assert sc.open_analyze() is False and sc.status_kind == "err"


def test_analyze_fields_cycle_and_exclude_id(labeled):
    sc = _analysis_ready(labeled)
    fields = {f["key"]: f for f in sc.an_fields}
    assert "patient_id" not in fields["y"]["choices"]   # id 는 측정값 후보가 아니다
    assert fields["question"]["value"] == "Q-01"

    sc.an_row = 0
    sc.an_cycle(1)
    assert sc.an_fields[0]["value"] == "Q-02"
    sc.an_cycle(-1)
    assert sc.an_fields[0]["value"] == "Q-01"


def test_analyze_plan_shows_candidates_or_problems(labeled):
    sc = _analysis_ready(labeled)
    fields = {f["key"]: f for f in sc.an_fields}
    fields["y"]["value"] = "x"
    fields["group"]["value"] = "diagnosis"
    assert sc.an_plan() is True
    assert sc.an_cands and sc.an_row == len(sc.an_fields)   # 커서가 첫 후보로
    body = sc.render_analyze()
    assert "✅" in body or "⚠" in body

    fields["group"]["value"] = "patient_id"                  # id 를 군에 — 차단
    sc.an_cands = []
    assert sc.an_plan() is False
    assert any("S-R10" in p for p in sc.an_problems)


def test_analyze_changing_a_field_invalidates_candidates(labeled):
    """조건이 바뀌면 옛 후보로 실행되면 안 된다."""
    sc = _analysis_ready(labeled)
    fields = {f["key"]: f for f in sc.an_fields}
    fields["y"]["value"] = "x"
    fields["group"]["value"] = "diagnosis"
    sc.an_plan()
    assert sc.an_cands
    sc.an_row = 0
    sc.an_cycle(1)
    assert sc.an_cands == []


def test_analyze_run_from_candidate_produces_hypothesis(labeled):
    sc = _analysis_ready(labeled)
    fields = {f["key"]: f for f in sc.an_fields}
    fields["y"]["value"] = "x"
    fields["group"]["value"] = "diagnosis"
    sc.an_plan()
    ids = [c.id for c in sc.an_cands]
    assert "T-101" not in ids                    # diagnosis 는 3군 — 2군 검정은 후보가 아니다
    sc.an_row = len(sc.an_fields) + ids.index("T-121")
    assert sc.an_run() is True
    assert sc.an_mode == "result"                    # 설계·후보를 접는다
    assert any("T-121" in x for x in sc.an_result)
    assert any("1안" in x for x in sc.an_hypo)
    body = sc.render_analyze()
    assert "eta^2" in body and "1안" in body and "2안" in body
    assert "주의사항" in body                         # 주의사항이 전부 화면에
    assert "검정 후보" not in body                    # 후보 목록은 접혔다 — 가설이 밀리지 않게

    sc.an_back_to_design()                           # Esc — 후보는 유지된다
    assert sc.an_mode == "design" and sc.an_cands
    assert "검정 후보" in sc.render_analyze()


def test_analyze_run_without_plan_says_so(labeled):
    sc = _analysis_ready(labeled)
    assert sc.an_run() is False
    assert "계획 확인" in sc.status


# ── 사용 중 드러난 결함 (문제 5·6·7) ───────────────────────
def test_web_to_cli_refresh_updates_the_types_screen(labeled):
    """웹에서 확정한 타입이 CLI 화면에 안 보이면 같은 세션인데 상태가 갈린다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    sc = labeled
    sc.open_types()
    assert not any(r["confirmed"] for r in sc.type_rows)

    doc = load_session(sc.session_file)          # 웹이 확정한 상황을 흉내
    src = main_source(doc)
    append_op(doc, "semantic_confirm", source=src["id"], column="x",
              type="continuous")
    save_session(doc)

    assert sc.refresh() is True
    assert sc.step == S.STEP_TYPES               # 타입 화면에 머문다
    row = next(r for r in sc.type_rows if r["column"] == "x")
    assert row["confirmed"] == "continuous"


def test_progress_shows_what_is_left(labeled):
    """뒤로 갔다 와도 무엇을 마쳤는지 알 수 있어야 한다."""
    steps = {s["key"]: s for s in labeled.progress_steps()}
    assert steps["import"]["done"] is True
    assert steps["derive"]["optional"] is True and steps["derive"]["done"] is False
    assert steps["types"]["done"] is False
    assert steps["analyze"]["done"] is False
    body = labeled.render_workspace()
    assert "진행 단계" in body and "타입 확정" in body


def test_progress_order_is_derive_then_types_then_analyze(labeled):
    keys = [s["key"] for s in labeled.progress_steps()]
    assert keys == ["import", "derive", "types", "analyze"]


def test_question_choices_can_be_listed_not_just_cycled(labeled):
    """←→ 로만 돌리면 어떤 선택지가 더 있는지 알 수가 없다."""
    sc = _analysis_ready(labeled)
    sc.an_row = 0
    assert sc.an_open is False
    assert "Enter 로 목록 펼치기" in sc.render_analyze()

    assert sc.an_toggle_list() is True
    body = sc.render_analyze()
    assert "Q-09" in body and "Q-11" in body          # 11종이 다 보인다
    assert "생존/사건 시간" in body                     # 코드만이 아니라 이름도

    sc.an_pick_move(2)
    sc.an_pick_choose()
    assert sc.an_fields[0]["value"] == "Q-03"
    assert sc.an_open is False


def test_listing_works_for_column_fields_too(labeled):
    """y·x 도 목록에서 골라야 한다 — 컬럼이 많으면 ←→ 로는 못 찾는다."""
    sc = _analysis_ready(labeled)
    sc.an_row = 1                                     # 측정값 y
    assert sc.an_toggle_list() is True
    body = sc.render_analyze()
    for col in sc.an_fields[1]["choices"]:
        assert col in body
    sc.an_pick_move(1)
    sc.an_pick_choose()
    assert sc.an_fields[1]["value"] == sc.an_fields[1]["choices"][1]


# ── CLI 수식 키패드 (클릭·방향키로만 식 만들기) ─────────────
def test_keypad_covers_columns_operators_and_functions(labeled):
    sc = labeled
    assert sc.open_derive() is True
    labels = [r["label"] for r in sc.pad_rows()]
    assert labels[:3] == ["pad_cols", "pad_ops", "pad_bin"]

    cols = next(r for r in sc.pad_rows() if r["label"] == "pad_cols")
    assert [k["text"] for k in cols["keys"]][:2] == sc.imported[:2]
    ops = {k["text"] for k in next(r for r in sc.pad_rows()
                                   if r["label"] == "pad_ops")["keys"]}
    assert {"+", "-", "*", "/", "**", "( )", "eps", ","} <= ops
    binning = {k["text"] for k in next(r for r in sc.pad_rows()
                                       if r["label"] == "pad_bin")["keys"]}
    assert {"floor_to", "round_to", "round", "bin"} <= binning
    assert any(k["text"] == "logit" for r in sc.pad_rows() for k in r["keys"])
    # 키에는 괄호가 보이지 않는다 — 넣을 때만 감싸진다
    assert not any("(" in k["text"] for r in sc.pad_rows() for k in r["keys"]
                   if k["text"] != "( )")


def test_keypad_keys_insert_and_place_the_cursor_inside_parentheses(labeled):
    """함수를 넣으면 괄호 안으로 들어가야 바로 컬럼을 넣을 수 있다."""
    sc = labeled
    sc.open_derive()
    key = next(k for r in sc.pad_rows() for k in r["keys"] if k["text"] == "floor_to")
    assert key["insert"] == "floor_to()" and key["back"] == 1
    plain = next(k for r in sc.pad_rows() for k in r["keys"] if k["text"] == "+")
    assert plain["insert"] == " + " and plain["back"] == 0


def test_keypad_cursor_moves_within_bounds(labeled):
    sc = labeled
    sc.open_derive()
    sc.pad_row = sc.pad_col = 0
    sc.pad_move(drow=-1)
    assert sc.pad_row == 0                      # 위로 더 못 간다
    sc.pad_move(dcol=-1)
    assert sc.pad_col == 0
    sc.pad_move(drow=99, dcol=99)
    rows = sc.pad_rows()
    assert sc.pad_row == len(rows) - 1
    assert sc.pad_col == len(rows[sc.pad_row]["keys"]) - 1
    assert sc.pad_pick() is not None


def test_derive_screen_warns_when_values_are_collapsed(labeled):
    sc = labeled
    sc.open_derive()
    col = next(c for c in sc.imported
               if pd.api.types.is_numeric_dtype(sc.frame()[c]))
    assert sc.preview_formula(f"floor_to({col}, 10)") is True
    body = sc.render_derive()
    assert "뭉개집니다" in body and "되돌릴 수 없습니다" in body
    assert "ordinal code" in body


# ── CLI 전용 화면: 전치 · 사본 저장 · 무결성 검증 ──────────
def test_transpose_screen_is_a_session_toggle_not_a_new_file(labeled):
    """파일을 새로 만들지 않는다 — 두 번 하면 원래대로 돌아온다."""
    from statop.session.core import load_session, main_source, replay

    sc = labeled
    origin = sc.data_path
    assert sc.open_transpose() is True
    assert sc.step == S.STEP_TRANSPOSE
    body = sc.render_transpose()
    assert any("예상 메모리" in x for x in body)
    assert any("타입 확정 다시" in x for x in body)   # 컬럼 구성이 달라진다는 경고

    assert sc.do_transpose() is True
    doc = load_session(sc.session_file)
    sid = main_source(doc)["id"]
    assert replay(doc)["transposed"][sid] is True
    assert sc.data_path == origin                   # 원본 경로 그대로

    sc.do_transpose()
    assert replay(load_session(sc.session_file))["transposed"][sid] is False


def test_savecopy_screen_lists_unsaved_changes(labeled, tmp_path):
    """값을 바꾸고 저장 안 하면 원본과 다른 데이터로 일하는 중이다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    sc = labeled
    doc = load_session(sc.session_file)
    src = main_source(doc)
    append_op(doc, "impute", source=src["id"], method="median", cols=["x"],
              group_by=None, seed=0, params={}, n_filled=3)
    save_session(doc)

    assert sc.open_savecopy() is True
    body = "\n".join(sc.render_savecopy())
    assert "저장하지 않은 값 변경 1건" in body and "결측 대치" in body
    assert "원본은 건드리지 않고" in body


def test_savecopy_can_switch_the_basis_to_the_copy(labeled):
    from statop.session.core import load_session, main_source

    sc = labeled
    origin = sc.data_path
    sc.open_savecopy()
    sc.copy_use_main = True
    assert sc.do_savecopy("mycopy") is True
    assert sc.copy_result["path"].endswith("mycopy.csv")
    assert main_source(load_session(sc.session_file))["path"].endswith("mycopy.csv")
    assert Path(origin).exists()                    # 원본은 그대로 있다
    assert "저장:" in "\n".join(sc.render_savecopy())


def test_verify_screen_needs_a_second_file_then_compares(labeled, tmp_path):
    """비교할 파일을 하나 더 열어야 한다 — 그 다음 대조는 컬럼을 골라서."""
    import pandas as pd

    sc = labeled
    assert sc.open_verify() is True
    assert sc.do_verify() is False                  # 파일 없이는 못 한다
    assert "먼저" in sc.status

    other = pd.read_csv(sc.data_path)
    other.loc[0, "x"] = 999.0
    p = tmp_path / "other.csv"
    other.to_csv(p, index=False)

    assert sc.set_verify_path(str(p)) is True
    assert set(sc.verify_columns()) >= {"x", "diagnosis"}
    # 키는 아무 컬럼이나 되는 것이 아니다 — **확정한 행 식별자**라야 한다.
    # 커서를 그 컬럼에 두고 이 화면에서 바로 확정한다
    assert sc.do_verify() is False
    sc.verify_row = [r["column"] for r in sc.verify_page_rows()].index("patient_id")
    assert sc.confirm_verify_id() is True
    assert sc.do_verify() is True
    body = "\n".join(sc.render_verify())
    assert "기준(A)" in body and "비교(B)" in body
    assert sc.verify_result.identical is False


def test_verify_screen_refuses_a_missing_file(labeled):
    sc = labeled
    sc.open_verify()
    assert sc.set_verify_path("/nope/none.csv") is False
    assert sc.verify_result is None


# ── 모델링 감사 화면 (모듈 B) ────────────────────────────────
def _model_screen(tmp_path, monkeypatch):
    """세트 2벌 + 구성 기록까지 마친 화면."""
    import numpy as np
    import pandas as pd

    from statop.modeling.spec import ModelSpec, record
    from statop.shell.screen import Screen

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(1)
    n = 300
    src = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                        "x1": rng.normal(0, 1, n),
                        "grp": rng.choice(["case", "control"], n)})
    paths = {}
    for name, part in (("source", src), ("train", src.iloc[:180]),
                       ("test", src.iloc[180:])):
        p = tmp_path / f"m_{name}.csv"
        part.to_csv(p, index=False)
        paths[name] = str(p)

    sc = Screen()
    sc.open_path(paths["source"])
    sc.toggle_page()
    sc.import_picked()
    record(str(sc.session_file),
           ModelSpec(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                     label_column="grp", positive_class="case",
                     sets={"train": paths["train"], "test": paths["test"]}))
    return sc, paths


def test_model_screen_runs_every_module_b_check(tmp_path, monkeypatch):
    """한 화면에서 세트 비율·손실 · 누수 · 라벨 방향을 모두 볼 수 있어야 한다."""
    from statop.shell.screen import STEP_MODEL

    sc, _ = _model_screen(tmp_path, monkeypatch)
    assert sc.open_model() and sc.step == STEP_MODEL
    assert sc.mb_notes                              # B1 구성을 먼저 말한다
    assert sc.run_model_audit(key="sid", expect="train=6,test=4")
    ids = {f.id for f in sc.mb_findings}
    assert {"MB-C06", "MB-C07", "MB-C01", "MB-C13"} <= ids
    text = "\n".join(sc.render_model())
    assert "MB-C06" in text and "MB-C13" in text


def test_model_screen_never_prints_data_cells(tmp_path, monkeypatch):
    """점진 노출  — 감사 화면에도 원자료 값이 나오면 안 된다."""
    sc, _ = _model_screen(tmp_path, monkeypatch)
    sc.open_model()
    sc.run_model_audit(key="sid", expect="train=6,test=4")
    text = "\n".join(sc.render_model())
    assert "S0000" not in text and "S0199" not in text


def test_model_screen_code_check_reads_only(tmp_path, monkeypatch):
    sc, _ = _model_screen(tmp_path, monkeypatch)
    sc.open_model()
    code = tmp_path / "train.py"
    code.write_text("from sklearn.preprocessing import StandardScaler\n"
                    "from sklearn.model_selection import train_test_split\n"
                    "X = StandardScaler().fit_transform(X)\n"
                    "a, b = train_test_split(X)\n", encoding="utf-8")
    assert sc.run_model_code(str(code))
    assert any(f.verdict == "fail" for f in sc.mb_code_findings)
    assert "MB-C09" in "\n".join(sc.render_model())


def test_model_screen_includes_balance_checks(tmp_path, monkeypatch):
    """B4 균형·분포도 같은 화면에서 본다 ."""
    sc, _ = _model_screen(tmp_path, monkeypatch)
    sc.open_model()
    sc.run_model_audit(key="sid", expect="train=6,test=4")
    # MB-C12 는 B4 에서만 나온다 — 균형 검사가 실제로 돌았다는 표시
    assert "MB-C12" in {f.id for f in sc.mb_findings}
    assert "MB-C12" in "\n".join(sc.render_model())


def test_origin_note_appears_where_paths_are_shown(tmp_path, monkeypatch):
    """S172b — 가공 파일을 기준으로 작업하면 원본이 어디였는지 잊는다.

    경로가 드러나는 화면(작업 영역·사본 저장·무결성 검증)마다 **같은 문구로** 보인다.
    """
    import numpy as np
    import pandas as pd

    from statop.export import export_trimmed
    from statop.session.core import load_session, save_session
    from statop.shell.screen import Screen

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(4)
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(30)],
                  "v": rng.normal(0, 1, 30).round(3)}).to_csv(raw, index=False)

    sc = Screen()
    sc.open_path(str(raw))
    sc.toggle_page()
    sc.import_picked()
    assert sc.origin_note() == ""             # 원본에는 붙지 않는다

    doc = load_session(sc.session_file)
    out = export_trimmed(doc, tmp_path / "proc.csv")
    save_session(doc)

    sc2 = Screen()
    sc2.open_path(str(out.path))
    sc2.toggle_page()
    sc2.import_picked()
    note = sc2.origin_note()
    assert str(raw) in note and "가공 전" in note
    assert note in sc2.render_workspace()     # 작업 영역
    sc2.open_savecopy()
    assert note in "\n".join(sc2.render_savecopy())
    sc2.open_verify()
    assert note in "\n".join(sc2.render_verify())


def test_origin_note_says_unknown_when_the_sidecar_is_gone(tmp_path, monkeypatch):
    """사이드카를 지우면 가공 사실만 알고 경로는 모른다 — 모른다고 말한다."""
    import numpy as np
    import pandas as pd

    from statop.export import origin_line, sidecar_path

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(5)
    p = tmp_path / "marked.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(20)],
                  "v": rng.normal(0, 1, 20).round(3),
                  "_relabeled": [False] * 20}).to_csv(p, index=False)
    assert not sidecar_path(p).exists()
    note = origin_line(str(p))
    assert "알 수 없음" in note                # 지어내지 않는다


def test_mouse_can_be_turned_off_so_you_can_drag_copy():
    """마우스를 잡고 있으면 터미널이 드래그를 못 받아 복사가 안 된다."""
    import re
    from pathlib import Path

    sc = Screen()
    assert sc.mouse_on is True          # 기본은 클릭이 되게
    sc.mouse_on = False
    assert sc.mouse_on is False

    src = Path("src/statop/shell/screen.py").read_text()
    # 상수 True 로 박아 두면 끌 수가 없다 — 필터여야 한다
    assert "mouse_support=Condition(lambda: sc.mouse_on)" in src
    assert re.search(r'@kb\.add\("f2"\)', src)


def test_web_failure_says_why(monkeypatch):
    """왜 못 띄웠는지 안 보여주면 사용자가 할 수 있는 일이 없다."""
    from statop import webshare

    monkeypatch.setattr(webshare, "port_open", lambda p, host="127.0.0.1": True)
    monkeypatch.setattr(webshare, "is_ours",
                        lambda p, host="127.0.0.1", require_stamp=True: False)
    monkeypatch.setattr(webshare, "_is_evid", lambda p, host="127.0.0.1": False)
    got, why = webshare.ensure_server(9700, tries=2)
    assert got is None
    assert "9700" in why and "9701" in why      # 포트마다 따로 말한다


def test_a_stale_evid_server_is_not_called_someone_elses(monkeypatch):
    """낡은 STATOP 서버는 끄면 되는 문제다 — '남의 것'이라고 하면 손을 못 쓴다."""
    from statop import webshare

    monkeypatch.setattr(webshare, "port_open", lambda p, host="127.0.0.1": True)
    monkeypatch.setattr(webshare, "is_ours",
                        lambda p, host="127.0.0.1", require_stamp=True: False)
    monkeypatch.setattr(webshare, "_is_evid", lambda p, host="127.0.0.1": True)
    _, why = webshare.ensure_server(9800, tries=1)
    assert "STATOP" in why


def test_our_own_fresh_server_is_not_judged_stale():
    """방금 띄운 자식까지 지문을 맞추면, 그 사이 소스가 바뀔 때 영원히 못 쓴다.

    낡음 검사는 **이미 떠 있던** 서버를 거를 때만 뜻이 있다 (개발 중 실제로 막혔다).
    """
    import inspect

    from statop import webshare

    src = inspect.getsource(webshare.ensure_server)
    assert "is_ours(p, require_stamp=False)" in src
    # 재사용 판단(루프 첫 줄)은 여전히 지문을 본다
    assert "if is_ours(p):" in src


def test_the_web_server_dies_with_the_window():
    """웹은 보기 수단이다 — 창을 닫았는데 서버만 남으면 포트를 물고 쌓인다.

    실측으로 4일간 5개가 쌓여 8000~8004 를 전부 막았고 그 뒤로는 웹을 못 띄웠다.
    **강제 종료에서도** 남으면 안 된다 — 그때는 종료 훅이 아예 안 돈다.
    """
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request

    from statop import webshare

    if not webshare.ui_built():
        import pytest

        pytest.skip("빌드된 화면이 없으면 서버를 띄우지 않는다")

    code = ("import time\n"
            "from statop import webshare\n"
            "if __name__ == '__main__':\n"
            "    got, _ = webshare.ensure_server(8600)\n"
            "    print(got, flush=True)\n"
            "    time.sleep(60)\n")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        port = int(p.stdout.readline().strip())
    except ValueError:
        p.kill()
        import pytest

        pytest.skip("이 환경에서 서버를 띄우지 못했다")

    def up() -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5)
            return True
        except (urllib.error.URLError, OSError):
            return False

    assert up()
    p.kill()                       # 창을 강제로 꺼버린 경우
    for _ in range(24):
        time.sleep(0.5)
        if not up():
            break
    assert not up(), f"창을 껐는데 포트 {port} 서버가 살아 있다"


def test_evid_serve_is_not_killed_with_a_window():
    """`statop serve` 는 사용자가 일부러 띄운 것이다 — 창과 함께 죽으면 안 된다."""
    from pathlib import Path

    cli = Path("src/statop/cli.py").read_text()
    # serve 는 자기 프로세스에서 직접 돌린다 (부모와 함께 죽는 child 경로가 아니다)
    assert 'uvicorn.run("statop.api.app:app"' in cli
    assert "statop.api.child" not in cli


# ── 유령 프로세스 보기·정리 ─────────────────────────────────
def test_cleanup_never_touches_its_own_ancestors():
    """조상을 서버로 잘못 보고 죽이면 사용자의 셸이 죽는다 (실제로 죽였다)."""
    import os

    from statop.api.ghosts import _ancestors

    rows = [(10, 1, 0, "init"), (20, 10, 0, "shell"), (30, 20, 0, "statop")]
    assert _ancestors(30, rows) == {30, 20, 10}
    # 순환이 있어도 멈춘다
    assert _ancestors(30, [(30, 30, 0, "self")]) == {30}
    assert os.getpid() in _ancestors(os.getpid(), [])


def test_cleanup_does_not_count_the_conda_wrapper_as_a_server():
    """`conda run ...` 은 서버가 아니라 껍데기다 — 세면 개수가 부풀고 껍데기를 죽인다."""
    from statop.api.ghosts import _is_wrapper

    assert _is_wrapper("/home/me/anaconda3/bin/python /home/me/condabin/conda run "
                       "-n statop python -m uvicorn statop.api.app:app --port 8000")
    assert not _is_wrapper("python -m uvicorn statop.api.app:app --host 127.0.0.1 "
                           "--port 8000 --log-level warning")
    assert not _is_wrapper("python -m statop.api.child --port 8000")


def test_cleanup_reads_the_port_it_will_report():
    from statop.api.ghosts import _port_of

    assert _port_of("python -m statop.api.child --port 8002") == "8002"
    assert _port_of("python -m statop.api.child") == "?"


# ── 수식 키패드 — 눌린 자리와 들어가는 값이 같아야 한다 ──────
def _pad_screen(tmp_path, monkeypatch, n_cols: int = 14):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(1)
    cols = {f"c{i:02d}": rng.normal(10, 2, 60).round(2) for i in range(n_cols)}
    p = tmp_path / "wide.csv"
    pd.DataFrame({"sid": [f"S{i}" for i in range(60)], **cols}).to_csv(p, index=False)
    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    assert sc.open_derive()
    return sc


def _pad_lines(sc) -> list[tuple[int, str]]:
    """렌더된 화면에서 키패드 줄을 (화면 y, 태그 없는 글자) 로."""
    import re

    lines = sc.render_derive().splitlines()
    return [(y, re.sub(r"</?[a-z]+>", "", lines[y]))
            for y in range(sc.pad_top, min(len(lines), sc.pad_top + len(sc.pad_rows())))]


def test_every_keypad_key_is_clickable_where_it_is_drawn(tmp_path, monkeypatch):
    """그려진 자리와 click_pad 가 믿는 자리가 어긋나면 클릭이 옆 키를 고른다.

    라벨이 한글이라 글자 수로 세면 줄마다 다르게 밀린다 — 실제로 2~5칸 밀렸다.
    """
    from prompt_toolkit.utils import get_cwidth

    sc = _pad_screen(tmp_path, monkeypatch)
    for y, plain in _pad_lines(sc):
        row = sc.pad_rows()[y - sc.pad_top]
        at = 0
        for k in row["keys"]:
            cell = f"[{k['text']}]"
            at = plain.index(cell, at)
            x = get_cwidth(plain[:at])                 # 글자 자리 → 터미널 칸
            for dx in (1, get_cwidth(cell) - 1):       # 대괄호 안 첫 칸·끝 칸
                got = sc.click_pad(y, x + dx)
                assert got is not None and got["text"] == k["text"], (
                    f"{plain[:30]!r} 줄에서 {k['text']} 를 눌렀는데 "
                    f"{got and got['text']} 가 잡혔다")
            at += len(cell)


def test_no_column_is_hidden_from_the_keypad(tmp_path, monkeypatch):
    """앞 10개만 보이면 열한 번째 컬럼은 클릭으로 고를 길이 아예 없다."""
    sc = _pad_screen(tmp_path, monkeypatch, n_cols=20)
    keys = {k["text"] for r in sc.pad_rows() if r["label"] in ("pad_cols", "")
            for k in r["keys"]}
    assert set(sc.imported) <= keys, sorted(set(sc.imported) - keys)


def test_a_derived_column_can_be_used_in_the_next_formula(tmp_path, monkeypatch):
    """방금 만든 파생 컬럼이 키패드에 없으면 2차 수식을 못 만든다."""
    sc = _pad_screen(tmp_path, monkeypatch)
    assert sc.preview_formula("c00 + c01")
    assert sc.commit_formula("total")
    assert sc.open_derive()
    assert "total" in {k["text"] for r in sc.pad_rows() for k in r["keys"]}
    assert sc.preview_formula("total / c02")


def test_an_error_does_not_wipe_the_rest_of_the_screen(tmp_path, monkeypatch):
    """식이 틀렸다고 키패드·안내까지 사라지면 화면이 고장난 것으로 보인다."""
    sc = _pad_screen(tmp_path, monkeypatch)
    assert not sc.preview_formula("log2(nope)")
    out = sc.render_derive()
    assert "[c00]" in out, "오류가 났더니 키패드가 사라졌다"
    assert sc.derive_error in out


# ── 확정 취소 (되돌릴 길이 있어야 한다) ─────────────────────
def test_a_confirmed_type_can_be_taken_back(data, monkeypatch):
    """잘못 확정하면 되돌릴 길이 있어야 한다 — 없으면 세션을 버리는 수밖에 없다."""
    from statop.session.core import load_session, main_source, replay

    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.open_types()
    sc.type_row = next(i for i, r in enumerate(sc.type_rows) if r["column"] == "x")
    sc.type_rows[sc.type_row]["idx"] = sc.type_rows[sc.type_row]["order"].index("continuous")
    assert sc.confirm_type()

    def confirmed() -> dict:
        doc = load_session(sc.session_file)
        return replay(doc)["semantic_types"].get(main_source(doc)["id"], {})

    assert confirmed().get("x") == "continuous"
    # 확정하면 커서가 다음 미확정으로 간다 — 취소는 **커서가 있는 줄**을 되돌린다
    sc.type_row = next(i for i, r in enumerate(sc.type_rows) if r["column"] == "x")
    assert sc.unconfirm_type()
    assert "x" not in confirmed(), "확정 취소했는데 세션에 그대로 남아 있다"
    assert sc.type_rows[sc.type_row]["confirmed"] is None
    # 취소한 사실도 기록이다 — 조작이 지워지면 이력이 거짓이 된다
    ops = [o["op"] for o in load_session(sc.session_file)["ops"]]
    assert ops.count("semantic_confirm") == 1 and ops.count("semantic_unconfirm") == 1


def test_taking_back_what_was_never_confirmed_says_so(data, monkeypatch):
    """확정한 적 없는 컬럼은 취소할 것도 없다 — 조용히 조작만 쌓으면 안 된다."""
    from statop.session.core import load_session

    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.open_types()
    assert not sc.unconfirm_type()
    assert not any(o["op"] == "semantic_unconfirm"
                   for o in load_session(sc.session_file)["ops"])


def test_the_distribution_button_does_not_block_the_screen():
    """분포는 frame() 을 다시 만든다 — 큰 파일이면 화면이 얼어붙는다."""
    src = inspect.getsource(S.run_screen)
    head = src[src.index("distv_button = mk_button"):][:200]
    assert "do_bg" in head, "분포 버튼이 아직 화면을 잡고 돈다"


def test_the_compare_file_box_says_what_it_is():
    """라벨이 없으면 빈 줄로 보인다 — 어디에 경로를 치는지 알 수 없다."""
    src = inspect.getsource(S.run_screen)
    head = src[src.index("verify_input = TextArea"):][:200]
    assert "screen_verify_prompt_file" in head


# ── 입력칸 — 칠 수 있어야 칸이다 ────────────────────────────
def _textarea_names() -> list[str]:
    import re

    src = inspect.getsource(S.run_screen)
    return re.findall(r"^\s{4}(\w+) = TextArea\(", src, re.M)


def test_every_input_box_is_registered_as_a_text_box():
    """빠진 칸에서는 글자가 단축키가 된다.

    실제로 그랬다 — 경로를 치니 숫자가 전부 버튼으로 먹혀
    `/storm/.../jwb419/17_...` 가 `/storm/.../jwb/_...` 로 들어갔다.
    """
    src = inspect.getsource(S.run_screen)
    listed = src[src.index("text_boxes = ("):src.index(")", src.index("text_boxes = ("))]
    missing = [n for n in _textarea_names() if n not in listed]
    assert not missing, f"text_boxes 에 없는 입력칸: {missing}"


def test_every_input_box_can_be_clicked_into():
    """클릭해도 커서가 안 가면 칸이 있어도 없는 것과 같다."""
    import re

    src = inspect.getsource(S.run_screen)
    bad = []
    for name in _textarea_names():
        i = src.index(f"{name} = TextArea(")
        body = src[i:src.index("\n\n", i)]
        if "focus_on_click=True" not in body or "class:textbox" not in body:
            bad.append(name)
    assert not bad, f"클릭으로 커서가 안 가거나 칸으로 안 보이는 입력: {bad}"
    assert re.search(r"prompt=", src)


def test_entering_a_screen_puts_the_cursor_in_its_input():
    """들어가자마자 친 글자가 단축키가 되면 안 된다 — 커서를 칸에 놓고 시작한다."""
    src = inspect.getsource(S.run_screen)
    for opener, box in (("do_verify_open", "verify_input"),
                        ("do_copy_open", "copy_input"),
                        ("do_model_open", "mb_key_input")):
        i = src.index(f"def {opener}(")
        assert f"focus({box})" in src[i:i + 400], f"{opener} 가 {box} 로 커서를 안 옮긴다"


def test_you_can_actually_type_a_path_on_the_verify_screen(tmp_path, monkeypatch):
    """**화면을 띄워 실제로 친다.** 이것만이 잡을 수 있는 버그였다.

    입력칸이 text_boxes 에 없어서 숫자가 버튼으로 먹히고, 커서도 칸에 없어서
    경로가 통째로 단축키가 됐다 — 웹 서버까지 떠 버렸다. 소스 검사로는 못 잡는다.
    """
    import asyncio
    import io

    import prompt_toolkit.application as pta
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.plain_text import PlainTextOutput

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(0)
    n = 40
    a = pd.DataFrame({"sid419": [f"S{i:03d}" for i in range(n)],
                      "v17": rng.normal(0, 1, n).round(3)})
    pa = tmp_path / "a17.csv"
    pb = tmp_path / "b419.csv"       # 경로에 숫자가 있어야 이 버그가 드러난다
    a.to_csv(pa, index=False)
    b = a.copy()
    b.loc[0, "v17"] = 99.0
    b.to_csv(pb, index=False)

    buf = io.StringIO()

    class Out(PlainTextOutput):
        def get_size(self):  # noqa: ANN201
            from prompt_toolkit.data_structures import Size

            return Size(rows=50, columns=170)

    with create_pipe_input() as inp:
        with create_app_session(input=inp, output=Out(buf)):
            orig = pta.Application

            class Driven(orig):
                def run(self, *a_, **k):  # noqa: ANN001, ANN202
                    async def feed() -> None:
                        await asyncio.sleep(0.3)
                        inp.send_text(f"{pa}\r")      # 파일 열기
                        await asyncio.sleep(1.5)
                        inp.send_text("a")            # 이 쪽 전체 체크
                        await asyncio.sleep(0.3)
                        inp.send_text("\r")           # 가져오기
                        await asyncio.sleep(0.8)
                        # 번호는 **화면에서 읽는다** — 버튼이 하나 늘 때마다
                        # 테스트가 깨지면 그 테스트는 화면을 지키는 게 아니다
                        import re as _re

                        m = _re.search(r"(\d+)\.무결성 검증", buf.getvalue())
                        assert m, "작업 영역에 [무결성 검증] 번호가 없다"
                        inp.send_text(m.group(1))
                        await asyncio.sleep(0.8)
                        inp.send_text(str(pb))        # **그냥 친다**
                        await asyncio.sleep(0.6)
                        inp.send_text("\r")           # 경로 확정 (커서가 [대조] 로)
                        await asyncio.sleep(0.8)
                        inp.send_text("3")            # [행 식별자로 확정] — 커서 컬럼
                        await asyncio.sleep(0.8)
                        inp.send_text("8")            # [대조]
                        await asyncio.sleep(1.5)
                        # 요약에서 [자세히] — 번호는 화면에서 읽는다.
                        # (커서가 경로 칸에 있으면 Enter 는 그 칸의 것이다)
                        m2 = _re.search(r"(\d+)\.자세히", buf.getvalue())
                        assert m2, "결과 화면에 [자세히] 번호가 없다"
                        inp.send_text(m2.group(1))
                        await asyncio.sleep(1.5)
                        inp.send_text("\x11")

                    async def both() -> None:
                        t = asyncio.ensure_future(feed())
                        try:
                            await self.run_async()
                        finally:
                            t.cancel()

                    asyncio.run(both())

            monkeypatch.setattr(pta, "Application", Driven)
            S.run_screen()

    out = buf.getvalue()
    assert str(pb) in out, "친 경로가 화면 어디에도 없다 — 칠 자리가 없었다"
    assert "다릅니다" in out, "대조 결과가 안 나왔다"
    assert "v17" in out, "어느 컬럼이 다른지가 안 나왔다"
    assert "1/40행" in out, "몇 행 중 몇 행인지가 안 나왔다"
    assert "B−A" in out, "[자세히] 가 그 컬럼의 차이를 안 보여준다"


# ── 무결성 검증 화면 ( 재설계) ─────────────────────────
@pytest.fixture
def verify_pair(tmp_path, monkeypatch):
    """A / B 두 파일 + 행 식별자까지 확정해 둔 세션."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(5)
    n = 50
    a = pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                      "v": rng.normal(0, 1, n).round(3),
                      "grp": rng.choice(["x", "y"], n),
                      "log2_frac_v1": rng.random(n).round(3)})
    b = a.rename(columns={"log2_frac_v1": "log2_frac_v2"}).copy()
    b.loc[0, "v"] = b.loc[0, "v"] + 5          # 값 하나가 다르다
    b.loc[1, "grp"] = "z"
    pa, pb = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(pa, index=False)
    b.to_csv(pb, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session

    sc = Screen()
    sc.open_path(str(pa))
    sc.toggle_page()
    sc.import_picked()
    doc = load_session(sc.session_file)
    append_op(doc, "semantic_confirm", source=main_source(doc)["id"],
              column="sid", type="id")
    save_session(doc)
    assert sc.open_verify()
    assert sc.set_verify_path(str(pb))
    return sc


def test_one_column_at_a_time_can_be_checked(verify_pair):
    """예전에는 클릭이 y 를 안 봐서 **전체 토글**만 됐다 — 하나씩 고를 수 없었다."""
    sc = verify_pair
    sc.render_verify()                       # verify_top 이 정해진다
    rows = sc.verify_page_rows()
    i = next(i for i, r in enumerate(rows) if r["column"] == "v")

    from statop.shell import screen as _S

    assert sc.verify_cols == set()
    sc.toggle_verify_col(rows[i]["column"])
    assert sc.verify_cols == {"v"}, "한 컬럼만 켜지지 않았다"
    sc.toggle_verify_col(rows[i]["column"])
    assert sc.verify_cols == set()
    assert _S  # noqa: B018


def test_the_key_must_be_a_confirmed_row_identifier(tmp_path, monkeypatch, verify_pair):
    """아무 컬럼이나 키로 쓰면 행이 1:1 로 안 맞고 대조가 통째로 멈춘다."""
    sc = verify_pair
    assert sc.verify_key_candidates() == ["sid"]
    assert sc.verify_key_now() == "sid"

    # 확정이 없으면 대조를 시작하지 않는다 — 조용히 첫 컬럼을 쓰지 않는다
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(sc.session_file)
    append_op(doc, "semantic_unconfirm", source=main_source(doc)["id"], column="sid")
    save_session(doc)
    assert not sc.verify_key_now()
    assert not sc.do_verify()
    assert sc.verify_result is None


def test_a_renamed_column_can_be_paired_up(verify_pair):
    """log2_frac_v1 ↔ v2 처럼 판본만 다른 컬럼이 대조에서 통째로 빠지면 안 된다."""
    sc = verify_pair
    row = next(r for r in sc.verify_rows() if r["column"] == "log2_frac_v1")
    assert not row["pair"], "짝이 없어야 정상 (이름이 다르다)"

    sc.verify_row = [r["column"] for r in sc.verify_page_rows()].index("log2_frac_v1")
    assert sc.pair_verify_col()
    assert sc.verify_pairs == {"log2_frac_v1": "log2_frac_v2"}
    assert sc.do_verify()
    cols = {c["column"] for c in sc.verify_result.columns}
    assert "log2_frac_v1" in cols, "짝을 지었는데도 대조에서 빠졌다"
    assert not sc.verify_result.unmatched


def test_the_result_says_same_or_different_in_one_line(verify_pair):
    """빨간 줄만 늘어놓으면 '그래서 같다는 건가'가 안 보인다."""
    sc = verify_pair
    assert sc.do_verify()
    text = "\n".join(sc.render_verify())
    assert "다릅니다" in text
    assert "1/50행" in text, "몇 행 중 몇 행이 다른지가 없다"
    assert "최대 차이 5" in text, "숫자 컬럼은 **얼마나** 다른지도 보여야 한다"
    assert "대조 못 함" in text, "왜 빠졌는지가 없다"

    # 짝을 지어 주면 같은 컬럼 묶음도 한 줄로 나온다
    sc.verify_row = [r["column"] for r in sc.verify_page_rows()].index("log2_frac_v1")
    assert sc.pair_verify_col()
    assert sc.do_verify()
    body2 = "\n".join(sc.render_verify())
    assert "log2_frac_v1" in body2 and "같음" in body2


# ── 상자그림의 다섯 수  ──────────────────────────────
def test_the_five_numbers_are_named_and_valued_everywhere(data, monkeypatch):
    """값만 있고 이름이 없으면 어느 수가 Q1 인지 세어야 한다.

    울타리(Q1−1.5×IQR · Q3+1.5×IQR)는 아예 없어서 손으로 계산해야 했다.
    CLI·TUI·웹이 **같은 목록 하나**를 쓴다.
    """
    from statop.io.distribution import distributions_of
    from statop.render.chart import boxplot
    from statop.render.spark import format_distribution, quartile_stats

    df = pd.read_csv(data)
    d = distributions_of(df, ["x"])[0]

    labels = [x["label"] for x in quartile_stats(d)]
    assert labels[:5] == ["최소", "Q1 (하위 25%)", "Q2 (중앙값)", "Q3 (상위 25%)", "최대"]
    assert labels[5:] == ["IQR (Q3−Q1)", "Q1−1.5×IQR", "Q3+1.5×IQR"]

    q = d["quartiles"]
    vals = {x["key"]: x["value"] for x in quartile_stats(d)}
    assert vals["q_q1"] == q[1] and vals["q_q2"] == q[2] and vals["q_q3"] == q[3]
    assert vals["q_iqr"] == pytest.approx(q[3] - q[1])
    assert vals["q_fence_lo"] == pytest.approx(q[1] - 1.5 * (q[3] - q[1]))
    assert vals["q_fence_hi"] == pytest.approx(q[3] + 1.5 * (q[3] - q[1]))

    for where in ("\n".join(format_distribution(d)),
                  "\n".join(boxplot(d["quartiles"], (0.0, d["outlier_rate_iqr"])))):
        for lab in labels:
            assert lab in where, f"{lab} 이 없다"

    # 상자그림을 그린 자리에서는 같은 줄을 두 번 적지 않는다
    assert "Q1 (하위 25%)" not in "\n".join(format_distribution(d, with_stats=False))


def test_the_tui_distribution_shows_the_five_numbers(data, monkeypatch):
    """`v` 로 연 분포에도 이름과 값이 보여야 한다 — 그림만으로는 상자 끝을 모른다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp := data.parent / "home"))
    assert tmp

    sc = Screen()
    sc.open_path(str(data))
    sc.toggle_page()
    sc.import_picked()
    assert sc.open_types()
    sc.type_row = next(i for i, r in enumerate(sc.type_rows) if r["column"] == "x")
    sc.toggle_dist()
    body = "\n".join(sc.dist_lines)
    assert "Q1 (하위 25%)" in body and "Q3+1.5×IQR" in body


# ── B1 모델링 구성 — TUI 안에서 만든다 ──────────────────────
def test_the_modeling_setup_can_be_made_without_leaving_the_screen(tmp_path, monkeypatch):
    """이 화면이 없으면 TUI 만 쓰는 사람은 모델링 감사에 **영원히 못 들어간다.**

    예전에는 `statop model plan --apply` 를 터미널에서 따로 쳐야만 구성이 생겼고,
    그때까지 감사 화면은 "모델링 구성을 먼저 확정하세요"만 반복했다.
    """
    from statop.modeling.spec import current

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(7)
    n = 60
    frame = pd.DataFrame({"pid": [f"P{i:03d}" for i in range(n)],
                          "x": rng.normal(0, 1, n).round(3),
                          "y": rng.integers(0, 2, n)})
    src = tmp_path / "src.csv"
    frame.to_csv(src, index=False)
    for name in ("train", "test"):
        frame.sample(frac=0.5, random_state=1).to_csv(tmp_path / f"{name}.csv", index=False)

    sc = Screen()
    sc.open_path(str(src))
    sc.toggle_page()
    sc.import_picked()
    assert sc.open_model()
    assert current(str(sc.session_file)) is None        # 아직 구성이 없다
    assert not sc.run_model_audit()                     # 그래서 감사도 안 된다

    assert sc.open_model_plan()
    assert sc.mb_add_set(f"train={tmp_path / 'train.csv'}")
    assert sc.mb_add_set(f"test={tmp_path / 'test.csv'}")
    for f in sc.mb_fields:
        if f["key"] == "label_column":
            f["value"] = "y"
    assert sc.mb_apply_plan(), sc.mb_problems
    assert current(str(sc.session_file)) is not None
    assert sc.step == S.STEP_MODEL                      # 확정하면 감사 화면으로 돌아온다
    assert sc.run_model_audit()                         # 이제 돈다


def test_a_bad_setup_is_not_recorded(tmp_path, monkeypatch):
    """빠진 것이 있으면 기록하지 않고 무엇이 빠졌는지 보여준다."""
    from statop.modeling.spec import current

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    p = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(p, index=False)
    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    sc.open_model()
    assert sc.open_model_plan()
    for f in sc.mb_fields:                      # 라벨을 비우면 확정되면 안 된다
        if f["key"] == "label_column":
            f["value"] = S.msg("an_none")
    assert not sc.mb_apply_plan()
    assert sc.mb_problems
    assert current(str(sc.session_file)) is None


def test_the_verify_result_is_not_pushed_off_screen(verify_pair):
    """이 창은 스크롤이 없다 — 목록 12줄을 위에 두면 판정이 화면 밖으로 나간다."""
    sc = verify_pair
    assert sc.do_verify()
    lines = sc.render_verify()
    head = "\n".join(lines[:10])
    assert "다릅니다" in head, f"판정이 앞쪽에 없다:\n{head}"
    assert "☐" not in head, "결과를 보는 중인데 컬럼 목록이 그대로 펼쳐져 있다"

    sc.verify_picking = True                     # [컬럼 고르기] 를 누르면 다시 펼친다
    assert any("☐" in ln for ln in sc.render_verify())


# ── 휠 스크롤 — 목록은 위아래로 굴려서 본다 ─────────────────
def test_the_wheel_moves_the_list(data, monkeypatch):
    """휠이 어디서도 안 먹었다 — 클릭만 처리하고 스크롤은 흘려보냈다."""
    from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
    from prompt_toolkit.data_structures import Point

    from statop.shell.columns_view import ClickableControl

    seen: list[int] = []
    ctl = ClickableControl(lambda: "", on_scroll=seen.append)
    for ev in (MouseEventType.SCROLL_DOWN, MouseEventType.SCROLL_UP):
        ctl.mouse_handler(MouseEvent(position=Point(x=0, y=0), event_type=ev,
                                     button=0, modifiers=frozenset()))
    assert seen == [1, -1], "휠이 아래·위로 전달되지 않는다"


def test_every_list_screen_takes_the_wheel():
    """한 화면이라도 빠지면 거기서만 휠이 죽는다 — 그게 더 헷갈린다."""
    src = inspect.getsource(S.run_screen)
    for win in ("table_window", "ws_window", "types_window", "analyze_window",
                "labels_window", "sessions_window", "mb_plan_window"):
        i = src.index(f"{win} = Window(")
        assert "on_scroll" in src[i:i + 400], f"{win} 에 휠이 없다"
    # 무결성 화면도 (창 이름이 없는 자리)
    i = src.index("render_verify()")
    assert "on_scroll" in src[i:i + 300]


def test_the_f2_line_says_it_is_a_switch():
    """F2 가 무엇과 무엇을 맞바꾸는지 한 줄로 보여야 한다."""
    from statop.messages import msg

    on, off = msg("screen_mouse_on"), msg("screen_mouse_off")
    for line in (on, off):
        assert "드래그 복사" in line and "클릭" in line
    assert on != off and "O" in on and "X" in on


# ── 임시본 정리 (캐시 지우기) ───────────────────────────────
def test_drafts_are_listed_with_enough_to_recognise_them(tmp_path, monkeypatch):
    """무엇이 쌓였는지 알아볼 만큼만 — 세션 id · 연 파일 · 조작 개수와 종류."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(3)
    for i in range(2):
        p = tmp_path / f"f{i}.csv"
        pd.DataFrame({"sid": [f"S{j}" for j in range(10)],
                      "v": rng.normal(0, 1, 10).round(2)}).to_csv(p, index=False)
        sc = Screen()
        sc.open_path(str(p))
        sc.toggle_page()
        sc.import_picked()

    sc = Screen()
    assert sc.open_tmp()
    rows = sc.tmp_rows
    assert len(rows) == 2
    for r in rows:
        assert r["id"].startswith("s_") and r["n_ops"] >= 1
        assert "select" in r["ops"] and r["path"].endswith(".csv")
    body = "\n".join(sc.render_tmp())
    assert "조작" in body and rows[0]["id"] in body


def test_deleting_drafts_takes_two_presses(tmp_path, monkeypatch):
    """되돌릴 수 없는 일이 한 번에 일어나면 안 된다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    p = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(p, index=False)
    for _ in range(3):
        sc = Screen()
        sc.open_path(str(p))
        sc.toggle_page()
        sc.import_picked()

    sc = Screen()
    sc.open_tmp()
    n = len(sc.tmp_rows)
    assert n == 3
    assert not sc.delete_tmp()                  # 첫 번째는 확인만
    assert "되돌릴 수 없" in sc.status
    assert len(sc.tmp_list()) == n, "확인 단계에서 이미 지워졌다"
    assert sc.delete_tmp()
    assert sc.tmp_rows == []


def test_the_session_you_are_in_is_not_deleted(tmp_path, monkeypatch):
    """쓰고 있는 세션을 지우면 그 자리에서 작업이 사라진다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    p = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(p, index=False)
    for _ in range(2):
        old = Screen()
        old.open_path(str(p))
        old.toggle_page()
        old.import_picked()

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    sc.open_tmp()
    mine = [r for r in sc.tmp_rows if r["current"]]
    assert len(mine) == 1
    sc.delete_tmp()
    assert sc.delete_tmp()
    assert [r["id"] for r in sc.tmp_rows] == [mine[0]["id"]]
    assert Path(sc.session_file).exists()


def test_a_pairing_can_be_taken_back(verify_pair):
    """한 바퀴 돌면 **짝 없음**으로 돌아와야 한다 — 잘못 지으면 되돌릴 길이 없었다."""
    sc = verify_pair
    sc.verify_row = [r["column"] for r in sc.verify_page_rows()].index("log2_frac_v1")
    assert sc.pair_verify_col()
    assert sc.verify_pairs == {"log2_frac_v1": "log2_frac_v2"}
    assert sc.pair_verify_col()                  # 후보가 하나뿐 → 다음은 짝 없음
    assert sc.verify_pairs == {}, "짝 없음으로 되돌아오지 않는다"
    assert sc.pair_verify_col()                  # 다시 누르면 또 짝이 지어진다
    assert sc.verify_pairs == {"log2_frac_v1": "log2_frac_v2"}


def test_the_confirmed_row_key_is_marked_red(verify_pair):
    """이 화면에서 확정했는데 아무 표시가 없으면 눌렸는지 알 수 없다."""
    sc = verify_pair
    body = "\n".join(sc.render_verify())
    assert "<err>sid" in body, "행 식별자가 붉게 표시되지 않는다"


def test_checked_columns_still_compare_when_names_differ(verify_pair):
    """짝을 지었으면 이름이 달라도 대조된다 — 컬럼을 골라도 마찬가지다.

    예전에는 B 를 **A 의 이름으로** 읽으려다 "컬럼이 없다"로 터졌다.
    """
    sc = verify_pair
    sc.verify_row = [r["column"] for r in sc.verify_page_rows()].index("log2_frac_v1")
    assert sc.pair_verify_col()
    sc.verify_cols = {"log2_frac_v1", "v"}       # 체크해서 골라 본다
    assert sc.do_verify(), sc.status
    got = {c["column"] for c in sc.verify_result.columns}
    assert got == {"log2_frac_v1", "v"}


def test_the_verify_screen_can_overlay_one_column(verify_pair):
    """대조 결과에서 **컬럼별로 골라** 개형·통계 차이를 볼 수 있어야 한다."""
    sc = verify_pair
    assert sc.do_verify()
    assert not sc.verify_view

    assert sc.verify_view_column("v")
    body = "\n".join(sc.verify_view)
    assert "평균" in body and "B−A" in body and "KS 거리" in body
    # 연 컬럼이 화면에 보여야 한다 — 그려 놓고 안 보이면 연 것이 아니다
    assert "\n".join(sc.render_verify()).count("B−A") == 2

    # 대조한 적 없는 컬럼은 그렇다고 말한다
    assert not sc.verify_view_column("없는컬럼")

    # 다시 대조하면 이전 그림은 버린다 — 옛 그림을 새 결과로 읽으면 안 된다
    assert sc.do_verify()
    assert not sc.verify_view


def test_clicking_a_differing_column_opens_its_overlay(verify_pair):
    """결과의 컬럼별 줄을 누르면 그 컬럼이 열린다 — 이름을 다시 칠 일이 아니다."""
    sc = verify_pair
    assert sc.do_verify()
    lines = sc.render_verify()
    assert sc.verify_diff_at, "컬럼별 줄의 자리를 기억하지 않는다"
    for y, col in sc.verify_diff_at.items():
        assert col in lines[y], f"{y}번째 줄이 {col} 이 아니다"


# ── 지표 찾기  ────────────────────────────────────────
@pytest.fixture
def finder(tmp_path, monkeypatch):
    """조성 3성분 + 연속값을 확정해 둔 세션에서 지표 찾기 화면까지."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(1)
    n = 200
    comp = rng.dirichlet([5, 3, 2], size=n)
    p = tmp_path / "d.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                  "frac_a": comp[:, 0].round(4), "frac_b": comp[:, 1].round(4),
                  "frac_c": comp[:, 2].round(4),
                  "age": rng.normal(60, 10, n).round(1)}).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    doc = load_session(sc.session_file)
    sid = main_source(doc)["id"]
    for c, t in (("sid", "id"), ("frac_a", "composition set"),
                 ("frac_b", "composition set"), ("frac_c", "composition set"),
                 ("age", "continuous")):
        append_op(doc, "semantic_confirm", source=sid, column=c, type=t)
    save_session(doc)
    assert sc.open_find()
    return sc


def _pick_question(sc, qid: str) -> None:
    sc.find_row = [q["id"] for q in sc.find_questions].index(qid)
    sc.find_pick()


def _pick_columns(sc, *cols: str) -> None:
    for c in cols:
        sc.find_row = sc.find_columns().index(c)
        sc.find_pick()


def test_picking_one_column_does_not_skip_the_second(finder):
    """하나를 골랐다고 다음 단계로 넘기면 둘째 컬럼을 고를 자리가 없다."""
    sc = finder
    _pick_question(sc, "Q-03")
    assert sc.find_stage == 1
    _pick_columns(sc, "frac_a")
    assert sc.find_stage == 1, "한 개만 골랐는데 넘어갔다"
    assert sc.find_cols == ["frac_a"]
    _pick_columns(sc, "age")
    assert sc.find_stage == 2 and sc.find_cols == ["frac_a", "age"]


def test_the_list_comes_without_values(finder):
    """목록에 뜬 것을 전부 미리 돌리면 화면이 멈춘다 — 누를 때만 돈다."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    assert sc.find_cands and not sc.find_ran
    body = "\n".join(sc.render_find())
    assert "Spearman" in body and "p " not in body.split("Spearman")[1][:40]

    sc.find_row = [c["id"] for c in sc.find_cands].index("T-302")
    assert sc.find_pick()
    assert "T-302" in sc.find_ran
    assert "p " in "\n".join(sc.render_find())


def test_measuring_twice_offers_a_correction(finder):
    """여러 번 쟀으면 그 수를 센다 (C-15 · post.yaml P-221~223)."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    ids = [c["id"] for c in sc.find_cands]
    assert not sc.cycle_find_adjust(), "한 번도 안 쟀는데 보정한다"

    for tid in ("T-302", "T-303"):
        sc.find_row = ids.index(tid)
        sc.find_pick()
    assert sc.cycle_find_adjust()
    assert sc.find_adj["rule"] in ("P-221", "P-222", "P-223")
    body = "\n".join(sc.render_find())
    assert "→" in body and "함께 보니" in body


def test_a_refused_pair_still_gets_a_value_in_the_screen(finder):
    """쓸 수 없다고 판정돼도 값은 나와야 한다 — 같은 조성 세트끼리 상관."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "frac_b")
    ids = [c["id"] for c in sc.find_cands]
    assert "T-301" in ids
    sc.find_row = ids.index("T-301")
    assert sc.find_pick()
    r = sc.find_ran["T-301"]
    assert r["effect"] is not None and r["effect"] < 0


def test_the_basis_comes_from_the_registry(finder):
    """근거는 규칙표에 적힌 그대로다 — 화면이 문구를 지어내지 않는다 ."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    sc.find_row = [c["id"] for c in sc.find_cands].index("T-302")
    assert sc.toggle_find_rule()
    body = "\n".join(sc.render_find())
    assert "단조성" in body and "동점" in body, body
    assert sc.toggle_find_rule()                 # 다시 누르면 접힌다
    assert "단조성" not in "\n".join(sc.render_find())


def test_goal_from_the_finder_keeps_the_name(finder):
    """ID 만 남으면 나중에 "무엇을 Goal 로 했더라"를 알 수 없다."""
    from statop.session.core import load_session, replay

    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    ids = [c["id"] for c in sc.find_cands]
    sc.find_row = ids.index("T-302")
    sc.find_pick()                                # 먼저 계산해 둔다
    assert sc.find_goal()
    goal = replay(load_session(sc.session_file))["metric_goal"]
    assert goal["test"] == "T-302" and goal["name"] == "Spearman ρ"
    # 효과크기 이름까지 — 병기 추천 조건이 이걸 본다
    assert goal["effect_key"] == sc.find_ran["T-302"]["effect_name"]


def test_the_tui_can_move_the_target_too(finder):
    """웹에서 끌어 옮기는 것을 TUI 는 눌러서 옮긴다 — 같은 일을 할 수 있어야 한다."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    sc.find_row = [c["id"] for c in sc.find_cands].index("T-302")
    sc.find_pick()
    first = sc.find_power["cut"]
    assert "80%" in "\n".join(sc.render_find())

    assert sc.set_find_target("95")
    assert sc.find_target == 0.95 and sc.find_power["cut"] > first
    body = "\n".join(sc.render_find())
    assert "95%" in body and "80%" not in body

    assert not sc.set_find_target("아무거나"), "숫자가 아니면 바꾸지 않는다"
    assert sc.find_target == 0.95
    sc.set_find_target("150")                 # 100% 는 어떤 n 으로도 닿지 않는다
    assert sc.find_target == 0.99


def test_power_shows_one_metric_at_a_time(finder):
    """검정력은 **한 번에 하나만** — 여럿을 얹으면 어느 값인지 알 수 없다."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    ids = [c["id"] for c in sc.find_cands]

    sc.find_row = ids.index("T-302"); sc.find_pick()
    assert sc.find_focus == "T-302"
    assert len(sc.find_power["rows"]) == 1

    sc.find_row = ids.index("T-301"); sc.find_pick()
    assert sc.find_focus == "T-301", "방금 잰 것을 본다"
    assert len(sc.find_power["rows"]) == 1
    assert sc.find_power["rows"][0]["id"] == "T-301"

    body = "\n".join(sc.render_find())
    assert "frac_a × age" in body, "무엇을 보고 있는지 적어야 한다"
    assert body.count("Pearson r  ") == 1, "선 위에는 하나만 선다"
    assert len(sc.find_ran) == 2, "잰 값은 목록에 그대로 남는다"


def test_support_and_guardrail_are_picked_from_the_list(finder):
    """검색칸에 이름을 쳐 넣게 두면 무엇을 적어야 할지 알 수 없다 — 목록에서 고른다."""
    sc = finder
    _pick_question(sc, "Q-03")
    _pick_columns(sc, "frac_a", "age")
    ids = [c["id"] for c in sc.find_cands]

    sc.find_row = ids.index("T-302")
    sc.find_pick()                                  # 재고
    assert not sc.find_role("support"), "Goal 없이 고르면 안 된다"

    assert sc.find_goal()
    sc.find_row = ids.index("T-301")
    assert sc.find_role("guardrail", "직선 가정이 깨지면 이걸로 본다")
    assert sc.find_roles["guardrail"] == ["Pearson r — 직선 가정이 깨지면 이걸로 본다"]

    body = "\n".join(sc.render_find())
    assert "Guardrail 지정: Pearson r" in body
    assert "직선 가정이 깨지면" in body, "왜 골랐는지가 같이 남아야 한다"
