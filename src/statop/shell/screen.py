"""`statop` 첫 화면  — 터미널에서 바로 뜨는 전체화면.

명령을 외워서 치는 곳이 아니다. **열자마자 경로 입력칸과 버튼이 있고**, 클릭·Tab·Enter로
끝까지 간다. 웹과 같은 코어·같은 판정을 쓰고 표현만 터미널이다.

화면은 셋뿐이다: 열기 → 컬럼 고르기 → 작업 영역.
그 다음(타입 확정·수식·적합성·가드레일)은 아직 `statop <명령>`이므로 마지막 화면에서
무엇을 치면 되는지 그대로 보여준다 — 화면이 끊기는 지점을 감추지 않는다.

**상태와 동작은 Screen에 있고 prompt_toolkit은 껍데기다.** 화면을 띄워야만 확인되는
구조였다면 클릭 핸들러나 키 이름이 틀려도 아무도 모른다 — 실제로 그렇게 두 개가 살아남았다
(mouse_handler 생성자 인자, "space" 키 이름).
"""

from dataclasses import dataclass, field
from pathlib import Path

from statop.messages import msg
from statop.shell.columns_view import FLAG, PAGE, ColumnsView, _cwidth, _esc, _pad_cells

def format_eta(seconds: float) -> str:
    """남은 시간을 h/min/s 로 — 두 단위까지만, 소수점 없이."""
    sec = max(0, int(round(seconds)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return msg("screen_eta", t=f"{h}h {m}min")
    if m:
        return msg("screen_eta", t=f"{m}min {s}s")
    return msg("screen_eta", t=f"{s}s")


STEP_OPEN, STEP_COLUMNS, STEP_WORKSPACE = "open", "columns", "workspace"
STEP_SESSIONS, STEP_SAVE = "sessions", "save"
STEP_DERIVE = "derive"
STEP_TYPES = "types"
STEP_LABELS = "labels"
STEP_ANALYZE = "analyze"
STEP_TRANSPOSE = "transpose"      # 전치 — 행/열 뒤집기
STEP_SAVECOPY = "savecopy"        # 사본 저장 (가공 파일) + 이후 기준 교체
STEP_VERIFY = "verify"            # 무결성 검증 — 비교 파일을 하나 더 연다
STEP_MODEL = "model"              # 모델링 감사 (모듈 B) — 학습은 실행하지 않는다
STEP_MODEL_PLAN = "model_plan"    # B1 구성 — 감사의 전제다
STEP_TMP = "tmp"                  # 임시본 정리 — 쌓인 작업 기록을 보고 지운다
STEP_FIND = "find"                # 지표 찾기 — 질문 → 컬럼 → 무엇을 쓸까


def _g(v) -> str:  # noqa: ANN001
    """값 한 칸 — 없으면 대시. 아주 작은 값은 지수로."""
    if v is None:
        return "-"
    return f"{v:.3e}" if v and abs(v) < 1e-4 else f"{v:,.4g}"

# 표 첫 행 위에 깔리는 줄 수 — 클릭 y좌표를 행 번호로 바꿀 때 쓴다
TABLE_HEADER_LINES = 2
WORKSPACE_HEADER_LINES = 2
SESSIONS_HEADER_LINES = 2
TYPES_HEADER_LINES = 2
LABELS_HEADER_LINES = 2
ANALYZE_HEADER_LINES = 2


@dataclass
class Screen:
    """화면 상태와 동작. prompt_toolkit 없이도 전부 실행된다."""

    step: str = STEP_OPEN
    session_file: Path | None = None
    data_path: str | None = None
    view: ColumnsView | None = None
    imported: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    row: int = 0
    session_row: int = 0              # 세션 목록 커서
    save_dir: str = ""                # 저장 위치 (빈 값이면 기본 저장소)
    loading: str = ""                 # 읽는 중인 파일 — 본문에 크게 보여준다
    load_pct: float = 0.0             # 진행률 0~1
    load_started: float = 0.0         # 시작 시각 — 남은 시간 추정용
    load_stage: str = ""              # 지금 무엇을 하는 중인지 — 0%에 머물면 이걸 본다
    session_id: str = ""              # 헤더 표시용 — 렌더마다 파일을 읽지 않게 캐시
    flash_row: int = -1               # 방금 클릭한 행 — 잠깐 반전시킨다
    web_url: str = ""                 # 웹 주소 — 상태줄이 아니라 제 줄에 크게 보인다
    pressed: str = ""                 # 방금 누른 버튼 (잠깐 반전)
    # 파생 컬럼 (M1-2) — 웹에만 있던 것을 터미널에도
    derive_expr: str = ""
    pad_row: int = 0                                 # 수식 키패드 커서 (행)
    pad_col: int = 0                                 # 〃 (열)
    derive_eps: float | None = None
    derive_prep: object | None = None
    derive_error: str = ""
    # 의미 타입 확정 + 분포 (M1-1 / M0-3)
    type_rows: list = field(default_factory=list)
    type_row: int = 0
    dist_lines: list = field(default_factory=list)
    dist_col: str = ""
    # 라벨 매핑  — label 확정 직후 진입
    label_col: str = ""
    label_rows: list = field(default_factory=list)   # {value, n, ratio, code}
    label_row: int = 0
    col_roles: dict = field(default_factory=dict)    # 작업 영역의 역할 표시용
    # 분석 화면 (모듈 A) — 필드와 후보가 한 커서 목록에 이어진다
    an_fields: list = field(default_factory=list)    # [{key, label, value, choices}]
    an_row: int = 0
    an_cands: list = field(default_factory=list)     # A2 후보
    an_problems: list = field(default_factory=list)
    an_result: list = field(default_factory=list)    # 실행 결과 표시 줄
    an_hypo: list = field(default_factory=list)      # 가설 표시 줄
    an_strata: list = field(default_factory=list)    # 층화 수준별 결과
    an_strata_col: str = ""
    an_metrics: list = field(default_factory=list)   #  병기 제안 표시 줄
    an_assump: list = field(default_factory=list)    # 실행한 검정이 요구하는 가정 (자동)
    an_compat: list = field(default_factory=list)    # 이 조합의 적합성 판정 (자동)
    # 전치 · 사본 저장 · 무결성 검증 (CLI 전용 — 파일 자체를 다루는 일)
    tp_info: dict = field(default_factory=dict)
    copy_name: str = ""
    copy_use_main: bool = True
    copy_result: dict = field(default_factory=dict)
    verify_path: str = ""                            # 비교할 두 번째 파일
    verify_key: str = ""
    verify_cols: set = field(default_factory=set)
    verify_pairs: dict = field(default_factory=dict)   # 이름이 다른 같은 컬럼 (A→B)
    verify_page: int = 0
    verify_row: int = 0
    verify_picking: bool = False                       # 결과를 덮고 컬럼 목록을 볼까
    verify_detail: int = -1                            # 상세로 보는 컬럼 (-1 이면 요약)
    verify_sum_row: int = 0                            # 요약에서 고른 줄
    verify_view: list = field(default_factory=list)    # 한 컬럼을 A/B 로 겹쳐 본 그림
    verify_diff_at: dict = field(default_factory=dict)  # 결과 줄 번호 → 컬럼
    mb_fields: list = field(default_factory=list)      # B1 구성 입력칸
    mb_sets: dict = field(default_factory=dict)        # 역할 → 세트 파일
    mb_row: int = 0
    mb_pick: int = 0
    mb_open: bool = False
    mb_top: int = 0
    mb_problems: list = field(default_factory=list)
    tmp_rows: list = field(default_factory=list)       # 임시본 목록
    tmp_row: int = 0
    tmp_top: int = 0
    tmp_confirm: bool = False                          # 한 번 더 눌러야 지운다
    find_questions: list = field(default_factory=list)  # 질문 유형 12종
    find_q: str = ""
    find_cols: list = field(default_factory=list)      # 고른 컬럼 (최대 2)
    find_cands: list = field(default_factory=list)
    find_ran: dict = field(default_factory=dict)       # 검정 id → 결과
    find_adj: object = None                            # 보정 결과
    find_method: str = "holm"                          # post.yaml P-221 기본값
    find_problems: list = field(default_factory=list)
    find_stage: int = 0                                # 0 질문 · 1 컬럼 · 2 무엇을 쓸까
    find_row: int = 0
    find_top: int = 0
    find_rule: str = ""                                # 근거를 편 검정 id
    find_plot: list = field(default_factory=list)      # 고른 컬럼의 모양
    find_color: object = None                          # 색으로 나눌 군
    find_power: dict = field(default_factory=dict)     # 이 표본으로 잡히는 크기
    find_target: float = 0.80                         # 목표 검정력 — 옮길 수 있다
    find_focus: str = ""                              # 검정력에서 보는 지표 하나
    find_roles: dict = field(default_factory=dict)    # 함께 볼 것으로 고른 지표
    verify_top: int = 0                                # 컬럼 목록 첫 줄의 화면 y
    verify_result: object = None
    # 모델링 감사 (모듈 B) — 검사 결과를 한 화면에 쌓아 보여준다
    mb_findings: list = field(default_factory=list)
    mb_code_findings: list = field(default_factory=list)
    mb_notes: list = field(default_factory=list)       # B1 구성 요약
    mb_shift: list = field(default_factory=list)       # 결측정리 전/후 분포 (눌렀을 때만)
    score_lines: list = field(default_factory=list)  #  점수 목록 (타입 화면 토글)
    represent_lines: list = field(default_factory=list)  # Q-12 부분표집 곡선
    score_page: int = 0                             # 점수 목록 쪽 (0부터)
    robust_lines: list = field(default_factory=list)  # 강건성 (작업 영역 토글)
    mouse_on: bool = True                           # 끄면 터미널 드래그 복사가 된다
    score_grade: str = "green"
    an_flips: list = field(default_factory=list)     # 전체와 방향이 반대인 수준
    an_repeats: list = field(default_factory=list)   # 반복측정이 가능한 id 컬럼
    # 개별 점 보기 — 어느 샘플이 결과를 끌고 있는지 눈으로 찾고 뺄 수 있게
    an_points: object = None
    an_plot_row: int = 0
    an_reason: str = ""                              # 제외 사유 (비면 뺄 수 없다)
    an_excl: dict = field(default_factory=dict)      #  제외 전/후 병기
    an_mode: str = "design"                          # design | result — 실행 후엔 결과·가설만
    an_missing: dict = field(default_factory=dict)   # 이 설계에 쓰이는 컬럼의 결측
    an_n_complete: int = 0
    an_n_rows: int = 0
    an_impute: str = "median"                        # 결측 대치 방법 (←→로 바꾼다)
    an_open: bool = False                            # 지금 필드의 선택지를 펼쳤는가
    an_pick: int = 0                                 # 펼친 목록의 커서
    an_ignore_missing: bool = False                  # 채우지 않고 그 행을 빼고 본다
    an_weights: str = ""                             # 사전지정 대비 가중치 (Q-11)
    an_control: str = ""                             # 대조군 수준 (Dunnett)
    web_port: int = 8000
    status: str = ""
    status_kind: str = "mut"          # mut | ok | err
    saved_name: str = ""
    sample_n: int = 3000
    focus: str = "path"               # 지금 어디에 있는지 (Tab 을 잘못 눌러도 알 수 있게)

    def say(self, text: str, kind: str = "mut") -> None:
        self.status, self.status_kind = text, kind

    def set_progress(self, frac: float) -> None:
        self.load_pct = max(self.load_pct, min(1.0, frac))   # 뒤로 가는 표시는 없다

    def set_stage(self, key: str, lo: float, hi: float):
        """단계 이름을 붙이고, 그 단계의 0~1 진행을 전체 [lo, hi] 구간으로 사상한다.

        어느 단계가 느린지 화면만 보고 알 수 있어야 한다 — "0%에 오래 머무는" 문제의
        원인 추적은 사용자가 아니라 화면의 몫이다.
        """
        self.load_stage = msg(key)
        if self.on_progress:
            self.on_progress(lo)

        def sub(frac: float) -> None:
            if self.on_progress:
                self.on_progress(lo + (hi - lo) * min(1.0, frac))

        return sub

    def eta_text(self) -> str:
        """남은 시간 — h/min/s 로 간단히. 초반(5% 미만)엔 추정이 널뛰므로 숨긴다."""
        import time

        if self.load_pct < 0.05 or not self.load_started:
            return ""
        elapsed = time.monotonic() - self.load_started
        remain = elapsed * (1 - self.load_pct) / self.load_pct
        return format_eta(remain)

    # ── 열기 ─────────────────────────────────────────────────
    def saved_files(self) -> list[Path]:
        from statop.store import sessions_dir

        try:
            return sorted(sessions_dir().glob("*.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        except OSError:
            return []

    on_progress = None                # 껍데기가 화면 갱신 함수를 꽂는다

    def open_path(self, raw: str) -> bool:
        """경로를 열고 컬럼 목록까지 간다. 실패하면 status에 이유를 남기고 False."""
        from statop.io.meta import open_meta
        from statop.session.core import (append_op, ensure_source, load_session,
                                       new_session, save_session)

        raw = (raw or "").strip().strip('"').strip("'")
        if not raw:
            self.say(msg("shell_need_path"), "err")
            return False
        p = Path(raw).expanduser()
        if not p.exists():
            self.say(f"{msg('path_not_exist')}: {p}", "err")
            return False
        hash_progress = self.set_stage("stage_check", 0.0, 0.05)
        try:
            open_meta(str(p))
        except ValueError as e:
            self.say(str(e), "err")
            return False

        # 네트워크 저장소의 콜드 캐시에서는 부분해시(8MB 읽기)가 가장 느릴 수 있다
        hash_progress = self.set_stage("stage_hash", 0.05, 0.30)
        if self.session_file is None:
            doc = new_session()
            ensure_source(doc, str(p), role="main", progress=hash_progress)
            self.set_stage("stage_session", 0.30, 0.35)
            self.session_file = save_session(doc)
            self.session_id = doc["session_id"]
        else:      # 세션은 유지하고 메인 파일만 교체
            doc = load_session(self.session_file)
            sid = ensure_source(doc, str(p), role="main", progress=hash_progress)
            if not any(o["op"] == "open" and o.get("source") == sid for o in doc["ops"]):
                append_op(doc, "open", source=sid)
            self.set_stage("stage_session", 0.30, 0.35)
            save_session(doc)
        self.data_path = str(p)
        self.load_columns()
        return True

    def load_columns(self) -> None:
        """컬럼 요약을 만든다. **웹과 같은 캐시**를 쓰므로 같은 파일을 다시 열면 즉시 뜬다."""
        from statop.api import cache
        from statop.io.profile import profile_columns

        key = cache.cache_key(self.data_path, self.sample_n, False)
        hit = cache.get(key)
        if hit is not None:
            items = hit["items"]
        else:
            sub = self.set_stage("stage_profile", 0.35, 1.0)
            prof = profile_columns(self.data_path, sample_n=self.sample_n,
                                   progress=sub)
            items = [{"column": r.column, "dtype": r.dtype,
                      "missing_rate": float(r.missing_rate), "n_unique": int(r.n_unique),
                      "missing_level": "high" if r.missing_rate >= 0.30 else
                                       ("mid" if r.missing_rate >= 0.10 else "ok")}
                     for r in prof.itertuples()]
            cache.put(key, {"items": items})
        warns = [msg("columns_warn_many", n=len(items))] if len(items) > 200 else []
        self.view = ColumnsView(items=items, title=Path(self.data_path).name,
                                warnings=warns)
        self.step = STEP_COLUMNS
        self.say(msg("screen_opened_ok", name=Path(self.data_path).name, n=len(items)), "ok")

    def open_sessions(self) -> bool:
        """저장된 세션 목록 화면으로. **고를 수 있어야** 한다 — 최근 것만 여는 건 선택이 아니다."""
        from statop.store import sessions_dir

        if not self.saved_files():
            self.say(msg("shell_no_saved", dir=sessions_dir()), "err")
            return False
        self.step = STEP_SESSIONS
        self.session_row = 0
        self.say(msg("screen_sessions_hint"), "mut")
        return True

    def click_sessions(self, y: int) -> bool:
        idx = y - SESSIONS_HEADER_LINES
        files = self.saved_files()
        if not (0 <= idx < len(files)):
            return False
        self.session_row = idx
        return self.load_saved(idx)

    def load_saved(self, index: int = 0) -> bool:
        from statop.session.core import load_saved, main_source, save_session
        from statop.store import sessions_dir

        files = self.saved_files()
        if not files:
            self.say(msg("shell_no_saved", dir=sessions_dir()), "err")
            return False
        index = max(0, min(len(files) - 1, index))
        doc, state = load_saved(files[index])
        self.session_file = save_session(doc)
        self.session_id = doc["session_id"]
        src = main_source(doc)
        self.data_path = src["path"] if src else None
        sel = list(state["selected"].values())
        self.imported = sel[0] if sel else []
        self.held = list(state["held"].values())[0] if state["held"] else []
        self.step = STEP_WORKSPACE if self.imported else STEP_OPEN
        self.say(msg("shell_loaded", name=doc["loaded_from"], n=len(self.imported)), "ok")
        return True

    # ── 컬럼 고르기 ──────────────────────────────────────────
    def toggle_at(self, index: int) -> bool:
        """지금 쪽의 index번째 행을 체크/해제. 범위를 벗어나면 아무것도 하지 않는다."""
        rows = self.view.page_items()
        if not (0 <= index < len(rows)):
            return False
        self.view.cursor = index
        name = rows[index]["column"]
        if name in self.view.picked:
            self.view.picked.discard(name)
            key = "screen_unchecked"
        else:
            self.view.picked.add(name)
            key = "screen_checked"
        # 누를 때마다 무엇이 어떻게 됐는지 말한다 — 눌렸는지 모르는 상태를 만들지 않는다
        self.say(msg(key, name=name, n=len(self.view.picked)), "ok")
        return True

    def click_table(self, y: int) -> bool:
        top = TABLE_HEADER_LINES + (1 if self.view and self.view.warnings else 0)
        return self.toggle_at(y - top)

    def toggle_page(self) -> None:
        """보이는 쪽 전체 토글 — 전체가 아니라 **본 것**만. 안 본 것을 고르게 하지 않는다."""
        names = {r["column"] for r in self.view.page_items()}
        if names and names <= self.view.picked:
            self.view.picked -= names
        else:
            self.view.picked |= names

    def move(self, delta: int) -> None:
        v = self.view
        rows = v.page_items()
        if delta < 0 and v.cursor == 0 and v.offset > 0:
            v.offset -= PAGE
            v.cursor = PAGE - 1
        elif delta > 0 and v.cursor == len(rows) - 1 and v.offset + PAGE < len(v.visible()):
            v.offset += PAGE
            v.cursor = 0
        else:
            v.cursor = max(0, min(max(0, len(rows) - 1), v.cursor + delta))

    def page(self, delta: int) -> None:
        v = self.view
        nxt = v.offset + delta * PAGE
        if 0 <= nxt < max(1, len(v.visible())):
            v.offset, v.cursor = nxt, 0
        self.say(msg("screen_paged", page=v.offset // PAGE + 1, pages=v.n_pages()), "mut")

    def set_sort(self, kind: str | None) -> None:
        v = self.view
        v.sort = None if v.sort == kind else kind
        v.offset = v.cursor = 0
        if v.sort is None:
            self.say(msg("screen_sort_off"), "ok")
        else:
            self.say(msg("screen_sorted", how=msg("screen_sort_" + v.sort)), "ok")

    def search(self, text: str) -> None:
        v = self.view
        v.grep = (text or "").strip()
        v.offset = v.cursor = 0
        n = len(v.visible())
        if v.grep:
            self.say(msg("screen_searched", q=v.grep, n=n), "ok")
        else:
            self.say(msg("screen_search_cleared", n=n), "mut")

    def import_picked(self) -> bool:
        from statop.session.core import (append_op, ensure_source, load_session, replay,
                                       save_session)

        v = self.view
        if not v.picked:
            self.say(msg("screen_none_picked"), "err")
            return False
        # 고른 순서가 아니라 파일의 컬럼 순서를 기준으로 남긴다
        cols = [x["column"] for x in v.items if x["column"] in v.picked]
        doc = load_session(self.session_file)
        sid = ensure_source(doc, self.data_path, role="main")
        entry = append_op(doc, "select", source=sid, cols=cols)
        save_session(doc)
        rs = replay(doc)
        self.imported = rs["selected"].get(sid, [])
        self.held = rs["held"].get(sid, [])
        self.step = STEP_WORKSPACE
        self.row = 0
        self.say(msg("select_recorded", seq=entry["seq"], n=len(doc["ops"])), "ok")
        return True

    # ── 작업 영역 ────────────────────────────────────────────
    def toggle_hold(self, name: str) -> None:
        from statop.session.core import (append_op, load_session, main_source, replay,
                                       save_session)

        doc = load_session(self.session_file)
        src = main_source(doc)
        off = name in self.held
        append_op(doc, "unhold" if off else "hold", source=src["id"], cols=[name])
        save_session(doc)
        rs = replay(doc)
        self.held = rs["held"].get(src["id"], [])
        self.say(msg("hold_state", n_analysis=len(rs["analysis"].get(src["id"], [])),
                     n_held=len(self.held)), "ok")

    def click_workspace(self, y: int) -> bool:
        idx = y - WORKSPACE_HEADER_LINES
        if not (0 <= idx < len(self.imported)):
            return False
        self.row = idx
        self.toggle_hold(self.imported[idx])
        return True

    def drop_current(self) -> None:
        """커서 컬럼을 작업 영역에서 뺀다 — 원본이면 선택 해제, **파생이면 파생 취소**."""
        from statop.session.core import (load_session, main_source, remove_columns,
                                       replay, save_session)

        if not self.imported:
            return
        name = self.imported[self.row]
        doc = load_session(self.session_file)
        src = main_source(doc)
        off, gone, unknown = remove_columns(doc, src["id"], [name])
        if unknown:
            self.say(msg("drop_err_unknown", cols=", ".join(unknown)), "err")
            return
        save_session(doc)
        self.refresh()
        self.row = min(self.row, max(0, len(self.imported) - 1))
        self.say(msg("derive_dropped", name=name) if gone
                 else msg("deselect_removed", n=1, cols=name), "ok")

    def move_session(self, delta: int) -> None:
        n = len(self.saved_files())
        if n:
            self.session_row = max(0, min(n - 1, self.session_row + delta))

    def open_in_web(self, port: int = 8000) -> str | None:
        """웹으로 넘긴다 — **같은 세션 파일**을 열게 해서 상태가 갈라지지 않게 한다."""
        from statop import webshare

        if not webshare.ui_built():
            self.say(msg("screen_web_no_build"), "err")
            self.web_url = ""
            return None
        got, why = webshare.ensure_server(port)
        if got is None:
            # 왜 실패했는지 안 보여주면 사용자가 할 수 있는 일이 없다
            self.say(msg("screen_web_failed_why", port=port, why=why), "err")
            self.web_url = ""
            return None
        self.web_url = webshare.url_for(self.session_file, got)
        self.web_port = got
        self.say(msg("screen_web_same_session"), "ok")
        return self.web_url

    def share_state(self) -> bool:
        """지금 화면 상태를 세션에 저장한다 — **저장해야 상대가 반영할 것이 생긴다.**

        가져오기 전의 체크 상태(picked)까지 남긴다. 조작(ops)이 아니라 화면 상태라
        view 블록에 마지막 것 하나만 둔다.
        """
        from statop.session.core import save_view

        if self.session_file is None:
            self.say(msg("screen_refresh_none"), "err")
            return False
        picked = sorted(self.view.picked) if self.view else []
        save_view(self.session_file, by="cli", step=self.step, picked=picked)
        self.say(msg("screen_shared", step=self.step, n=len(picked)), "ok")
        return True

    def refresh(self) -> bool:
        """웹이 저장한 상태를 CLI에 반영한다 — 저장(동기화 키)이 없으면 그렇다고 말한다."""
        from statop.session.core import load_session, main_source, peek_state, replay

        if self.session_file is None or not Path(self.session_file).exists():
            self.say(msg("screen_refresh_none"), "err")
            return False
        doc = load_session(self.session_file)
        src = main_source(doc)
        if src is None:
            self.say(msg("screen_refresh_none"), "err")
            return False
        rs = replay(doc)
        self.data_path = src["path"]
        # 파생 컬럼은 replay 가 선택 목록에 합쳐 준다 — 여기서 또 합치지 않는다
        self.imported = rs["selected"].get(src["id"], [])
        self.held = rs["held"].get(src["id"], [])
        self.row = min(self.row, max(0, len(self.imported) - 1))

        view = doc.get("view")
        if view:
            # 저장된 화면 상태 — 체크·단계까지 그대로 따라간다
            if view.get("step") == STEP_COLUMNS or (not self.imported and self.data_path):
                if self.view is None or view.get("step") == STEP_COLUMNS:
                    self.load_columns()
                if self.view is not None and view.get("picked"):
                    self.view.picked = set(view["picked"]) & {
                        x["column"] for x in self.view.items}
            elif view.get("step") == STEP_TYPES or self.step == STEP_TYPES:
                # 웹에서 확정한 타입이 CLI 화면에 안 보이면 같은 세션인데 상태가 갈린다
                self.open_types()
            elif self.imported:
                self.step = STEP_WORKSPACE
            self.say(msg("screen_pulled", by=view.get("by", "?"),
                         n=len(self.imported), p=len(view.get("picked", []))), "ok")
        elif self.step == STEP_TYPES:
            self.open_types()
            self.say(msg("screen_pull_no_view", n=len(self.imported)), "ok")
        else:
            if self.imported:
                self.step = STEP_WORKSPACE
            self.say(msg("screen_pull_no_view", n=len(self.imported)), "ok")
        return True

    # ── 의미 타입 확정 (M1-1) ────────────────────────────────
    @staticmethod
    def known_types() -> list[str]:
        from statop.semantic_risk import TYPE_RULES

        return sorted(set(TYPE_RULES) | {"continuous", "datetime", "composition set"})

    def open_types(self) -> bool:
        """타입 화면 — 추론은 컬럼당 비용이 커서 진행률을 보여준다."""
        import time

        from statop.semantic import infer_columns
        from statop.session.core import load_session, main_source, replay

        if not self.imported:
            self.say(msg("screen_types_need_columns"), "err")
            return False
        self.loading = msg("screen_types_inferring")
        self.load_pct = 0.0
        self.load_started = time.monotonic()
        df = self.frame()
        doc = load_session(self.session_file)
        src = main_source(doc)
        rs = replay(doc)
        confirmed = rs["semantic_types"].get(src["id"], {})
        # 파생 컬럼의 수식 유도 타입 — 확정이 아니라 **1순위 후보**로만 쓴다
        derived_hint = {d["name"]: (d.get("result_type"), d["expr"])
                        for d in rs["derived"] if d.get("source") == src["id"]}
        # 가져온 컬럼 + **파생 컬럼**. imported 에는 파생이 없어서, 이걸 빼면
        # 만들어 놓은 파생 컬럼이 타입 화면에 아예 안 나온다
        cols = [c for c in self.imported if c in df.columns]
        cols += [n for n in derived_hint if n in df.columns and n not in cols]
        sub = self.set_stage("stage_infer", 0.0, 1.0)
        infs = infer_columns(df, cols, progress=sub)
        self.loading = ""

        known = self.known_types()
        self.type_rows = []
        for t in infs:
            cands = [c.type for c in t.candidates]
            ev = {c.type: c.evidence for c in t.candidates}
            hint = derived_hint.get(t.column)
            if hint and hint[0]:
                # 수식이 유도한 타입을 맨 앞에 — 그래도 확정은 사용자가 누른다
                cands = [hint[0]] + [c for c in cands if c != hint[0]]
                ev.setdefault(hint[0], []).insert(
                    0, msg("ev_from_formula", expr=hint[1]))
            # 추론 후보 먼저, 그 뒤 나머지 전부 — 추론에 없는 타입도 확정할 수 있어야 한다
            order = cands + [k for k in known if k not in cands]
            cur = confirmed.get(t.column)
            self.type_rows.append({
                "column": t.column, "shape": t.shape, "order": order,
                "idx": order.index(cur) if cur in order else 0,
                "evidence": ev, "confirmed": cur,
                "needs_confirm": (t.needs_confirm or bool(hint)) and cur is None,
                "reason": t.confirm_reason, "conflicts": t.conflicts,
            })
        self.type_row = 0
        self.dist_lines, self.dist_col = [], ""
        self.step = STEP_TYPES
        n_pending = sum(1 for r in self.type_rows if not r["confirmed"])
        self.say(msg("screen_types_hint", pending=n_pending), "mut")
        return True

    def cycle_type(self, delta: int = 1) -> None:
        """커서 행의 후보 순환 — 추론에 없는 타입도 돌다 보면 나온다 (막지 않는다)."""
        if not self.type_rows:
            return
        r = self.type_rows[self.type_row]
        r["idx"] = (r["idx"] + delta) % len(r["order"])
        self.say(msg("screen_types_cycled", column=r["column"],
                     type=r["order"][r["idx"]]), "mut")

    def current_type_choice(self) -> tuple[str, str] | None:
        if not self.type_rows:
            return None
        r = self.type_rows[self.type_row]
        return r["column"], r["order"][r["idx"]]

    def confirm_type(self) -> bool:
        """확정 — 그 타입으로 계산할 때의 위험을 함께 알린다 (요구사항-7)."""
        from statop.semantic_risk import risks_for
        from statop.session.core import append_op, load_session, main_source, save_session

        choice = self.current_type_choice()
        if choice is None:
            return False
        col, typ = choice
        doc = load_session(self.session_file)
        src = main_source(doc)
        append_op(doc, "semantic_confirm", source=src["id"], column=col, type=typ)
        save_session(doc)
        r = self.type_rows[self.type_row]
        r["confirmed"] = typ
        r["needs_confirm"] = False
        risks = risks_for(typ)
        if risks:
            ids = ", ".join(x["id"] for x in risks)
            self.say(msg("screen_types_confirmed_risky", column=col, type=typ, ids=ids),
                     "err" if any(x["verdict"] in ("red", "gate") for x in risks) else "ok")
        else:
            self.say(msg("screen_types_confirmed", column=col, type=typ), "ok")

        # id·label 은 분석 변수가 아니다 — 자동으로 분석에서 빼고(식별·그룹용 유지),
        # hold 라는 이름 대신 역할로 보이게 한다
        if typ in ("id", "label"):
            self._auto_hold(col)
            self.say(msg("screen_role_auto_held", column=col, type=typ), "ok")
        self.col_roles[col] = typ if typ in ("id", "label") else ""
        if typ == "label":
            self.open_labels(col)         # 확정 직후 코드 매핑까지 한 흐름으로
            return True
        if self.type_row < len(self.type_rows) - 1:
            self.type_row += 1            # 다음 미확정으로 손이 가게
        return True

    def unconfirm_type(self) -> bool:
        """확정 취소 — 잘못 확정하면 되돌릴 길이 있어야 한다.

        기록을 지우지 않고 **취소했다는 조작을 남긴다** (replay 의 semantic_unconfirm).
        확정을 전제로 하던 판정은 다시 미확정 상태로 돌아간다.
        """
        from statop.session.core import append_op, load_session, main_source, replay, save_session

        if not self.type_rows:
            return False
        r = self.type_rows[self.type_row]
        col = r["column"]
        doc = load_session(self.session_file)
        src = main_source(doc)
        if col not in replay(doc)["semantic_types"].get(src["id"], {}):
            self.say(msg("semantic_not_confirmed", column=col), "err")
            return False
        append_op(doc, "semantic_unconfirm", source=src["id"], column=col)
        save_session(doc)
        r["confirmed"] = None
        r["needs_confirm"] = True
        self.col_roles.pop(col, None)
        self.say(msg("semantic_unconfirmed", column=col), "ok")
        return True

    def _auto_hold(self, col: str) -> None:
        from statop.session.core import append_op, load_session, main_source, replay, save_session

        doc = load_session(self.session_file)
        src = main_source(doc)
        if col in replay(doc)["held"].get(src["id"], []):
            return
        append_op(doc, "hold", source=src["id"], cols=[col])
        save_session(doc)
        self.held = replay(doc)["held"].get(src["id"], [])

    # ── 분석 (모듈 A): 질문 → 후보 → 실행 → 가설 ─────────────
    def open_analyze(self) -> bool:
        from statop.analyze.spec import current, question_ids
        from statop.session.core import load_session, main_source, replay

        if not self.imported:
            self.say(msg("screen_an_need_columns"), "err")
            return False
        # 행 식별자는 분석 변수가 아니다 (S-R10). 화면 상태가 아니라 **세션에 확정된**
        # 의미 타입을 본다 — 웹에서 확정했거나 다시 연 세션에서도 같아야 한다
        doc = load_session(self.session_file)
        types = replay(doc)["semantic_types"].get(main_source(doc)["id"], {})
        cols = [c for c in self.imported
                if types.get(c) != "id" and self.col_roles.get(c) != "id"]
        if not cols:
            self.say(msg("screen_an_need_columns"), "err")
            return False
        prev = current(str(self.session_file))
        qids = question_ids()
        self.an_fields = [
            {"key": "question", "label": msg("an_f_question"),
             "value": prev.question if prev else "Q-01", "choices": qids},
            {"key": "y", "label": msg("an_f_y"),
             "value": prev.y if prev and prev.y in cols else cols[0], "choices": cols},
            {"key": "group", "label": msg("an_f_group"),
             "value": (prev.group if prev else None) or msg("an_none"),
             "choices": [msg("an_none"), *cols]},
            {"key": "subject", "label": msg("an_f_subject"),
             "value": (prev.subject if prev else None) or msg("an_none"),
             "choices": [msg("an_none"), *self.imported]},
            {"key": "by", "label": msg("an_f_by"),
             "value": (prev.by if prev else None) or msg("an_none"),
             "choices": [msg("an_none"), *cols]},
            {"key": "event", "label": msg("an_f_event"),
             "value": (prev.event if prev else None) or msg("an_none"),
             "choices": [msg("an_none"), *cols]},
            {"key": "paired", "label": msg("an_f_paired"),
             "value": bool(prev.paired) if prev else False, "choices": [False, True]},
            {"key": "n_tests", "label": msg("an_f_ntests"),
             "value": prev.n_tests if prev else 1, "choices": [1, 2, 3, 4, 5, 10]},
        ]
        self.an_row = 0
        self.an_cands, self.an_problems = [], []
        self.an_result, self.an_hypo = [], []
        self.step = STEP_ANALYZE
        self.say(msg("screen_an_hint"), "mut")
        return True

    def _an_spec(self):
        from statop.analyze.spec import Spec

        v = {f["key"]: f["value"] for f in self.an_fields}
        none = msg("an_none")
        return Spec(question=v["question"], y=v["y"],
                    group=None if v["group"] == none else v["group"],
                    event=None if v["event"] == none else v["event"],
                    by=None if v["by"] == none else v["by"],
                    subject=None if v["subject"] == none else v["subject"],
                    weights=self.an_weights or None,
                    control=self.an_control or None,
                    paired=bool(v["paired"]), n_tests=int(v["n_tests"]))

    def an_toggle_list(self) -> bool:
        """필드의 선택지를 펼친다 — ←→ 로만 돌리면 어떤 값이 더 있는지 알 수가 없다."""
        if self.an_row >= len(self.an_fields):
            return False
        self.an_open = not self.an_open
        if self.an_open:
            f = self.an_fields[self.an_row]
            self.an_pick = (f["choices"].index(f["value"])
                            if f["value"] in f["choices"] else 0)
            self.say(msg("screen_an_list_open", label=f["label"],
                         n=len(f["choices"])), "mut")
        return True

    def an_pick_move(self, delta: int) -> None:
        f = self.an_fields[self.an_row]
        self.an_pick = max(0, min(len(f["choices"]) - 1, self.an_pick + delta))

    def an_pick_choose(self) -> None:
        """펼친 목록에서 고른 값을 확정하고 접는다."""
        f = self.an_fields[self.an_row]
        f["value"] = f["choices"][self.an_pick]
        self.an_open = False
        self.an_cands, self.an_problems = [], []
        self.an_result, self.an_hypo = [], []
        self.say(msg("screen_an_changed", label=f["label"], value=f["value"]), "mut")

    def an_cycle(self, delta: int) -> None:
        """커서가 필드 위면 값 순환, 후보 위면 아무것도 안 한다."""
        if self.an_row < len(self.an_fields):
            f = self.an_fields[self.an_row]
            i = f["choices"].index(f["value"]) if f["value"] in f["choices"] else 0
            f["value"] = f["choices"][(i + delta) % len(f["choices"])]
            self.an_cands, self.an_problems = [], []   # 조건이 바뀌면 후보는 무효다
            self.an_result, self.an_hypo = [], []
            self.say(msg("screen_an_changed", label=f["label"], value=f["value"]), "mut")

    def an_move(self, delta: int) -> None:
        total = len(self.an_fields) + len(self.an_cands)
        if total:
            self.an_row = max(0, min(total - 1, self.an_row + delta))

    def an_plan(self) -> bool:
        """계획 확인 — 문제가 있으면 후보 대신 문제를 보여준다 (여기서 멈춘다)."""
        from statop.analyze.candidates import shortlist
        from statop.analyze.spec import build

        res = build(str(self.session_file), self._an_spec(), sample_n=self.sample_n)
        self.an_missing = dict(res.missing)
        self.an_n_complete, self.an_n_rows = res.n_complete, res.n_rows
        self.an_repeats = list(res.repeat_candidates)
        if not any(m["n"] for m in self.an_missing.values()):
            self.an_ignore_missing = False          # 결측이 없어지면 안내도 사라진다
        self.an_problems = list(res.problems)
        for f in res.compat.get("findings", []):
            if f["verdict"] in ("red", "gate"):
                self.an_problems.append(f"[{f['id']}] {f['detail'] or f['why']}")
        if res.problems:
            self.an_cands = []
            self.say(msg("screen_an_blocked", n=len(res.problems)), "err")
            return False
        self.an_cands = shortlist(res)
        self.an_row = len(self.an_fields)          # 첫 후보로 커서 이동
        self.say(msg("screen_an_planned", n=len(self.an_cands)), "ok")
        return True

    IMPUTE_METHODS = ("median", "mean", "group_median", "group_mean", "mode",
                      "knn", "mice", "zero")

    def an_cycle_impute(self, delta: int) -> None:
        i = self.IMPUTE_METHODS.index(self.an_impute)
        self.an_impute = self.IMPUTE_METHODS[(i + delta) % len(self.IMPUTE_METHODS)]
        self.say(msg("screen_an_impute_method", method=self.an_impute), "mut")

    def an_ignore_missing_rows(self) -> bool:
        """채우지 않고 그대로 본다 — 결측 행은 검정에서 빠진다. 세션은 건드리지 않는다."""
        self.an_ignore_missing = True
        self.say(msg("screen_an_ignoring_missing", used=self.an_n_complete,
                     total=self.an_n_rows), "warn")
        return True

    def an_do_impute(self) -> bool:
        """이 설계에 쓰이는 컬럼만 대치한다 — 상관없는 컬럼까지 손대지 않는다."""
        from statop.derive.service import apply_ops, session_frame
        from statop.missing import impute
        from statop.session.core import append_op, save_session

        cols = [c for c, m in self.an_missing.items() if m["n"] > 0]
        if not cols:
            self.say(msg("screen_an_no_missing"), "mut")
            return False
        spec = self._an_spec()
        # 그룹별 대치는 군 컬럼이 있어야 한다. 군 자체가 결측이면 그룹별은 쓸 수 없다
        group_by = spec.group if self.an_impute.startswith("group_") else None
        if group_by and (group_by in cols or group_by is None):
            self.say(msg("screen_an_impute_group_missing", col=group_by), "err")
            return False
        doc, src, df = session_frame(str(self.session_file), self.sample_n)
        df = apply_ops(df, doc, src["id"])
        try:
            _, info = impute(df, self.an_impute, cols, group_by=group_by)
        except (ValueError, ImportError) as e:
            self.say(str(e), "err")
            return False
        append_op(doc, "impute", source=src["id"], method=self.an_impute, cols=cols,
                  group_by=group_by, seed=info["seed"], params=info["params"],
                  n_filled=info["n_filled"])
        save_session(doc)
        self.an_cands, self.an_problems = [], []      # 값이 바뀌었으니 후보는 다시
        self.say(msg("screen_an_imputed", method=self.an_impute,
                     n=info["n_filled"], cols=", ".join(cols)), "ok")
        for w in info["warnings"]:
            self.say(w, "warn")
        return self.an_plan()

    def an_selected_test(self):
        idx = self.an_row - len(self.an_fields)
        if 0 <= idx < len(self.an_cands):
            return self.an_cands[idx]
        return None

    def an_run(self) -> bool:
        """커서의 후보를 실행 — 스펙 기록 → 검정 → 가설까지 한 번에."""
        from statop.analyze.points import both_ways
        from statop.analyze.spec import record
        from statop.hypothesis.mech import build_report

        cand = self.an_selected_test()
        if cand is None:
            self.say(msg("screen_an_pick_candidate"), "err")
            return False
        if not cand.runnable:
            self.say(msg("screen_an_not_runnable", id=cand.id), "err")
            return False
        record(str(self.session_file), self._an_spec())
        try:
            both = both_ways(str(self.session_file), cand.id, self.sample_n)
        except ValueError as e:
            self.say(str(e), "err")
            return False
        r = both["after"]
        self.an_excl = both
        from statop.analyze.run import _direction_flips

        self.an_strata = list(r.strata)
        self.an_strata_col = self._an_spec().by or ""
        self.an_flips = _direction_flips(r, r.strata) if r.strata else []
        eff = r.effect or {}
        ci = (msg("run_line_ci", lo=eff["ci_low"], hi=eff["ci_high"])
              if eff.get("ci_low") is not None else "")
        self.an_result = [
            msg("run_head", id=r.id, name=r.name),
            "  " + msg("run_line_stat", stat=r.statistic, p=r.p),
            "  " + msg("run_line_effect", name=eff.get("name", "?"),
                       value=eff.get("value", 0.0), ci=ci),
            *[f"  {n}" for n in r.notes],
        ]
        self.an_assump = self._collect_assumptions(cand.id)
        self.an_compat = self._collect_compat()
        self.an_metrics = self._collect_metrics()
        try:
            rep = build_report(str(self.session_file))
        except ValueError as e:
            # 결과는 살리고 가설만 비운다 — 왜 없는지는 상태줄에
            self.an_hypo = []
            self.an_mode = "result"
            self.say(str(e), "err")
            return True
        self.an_hypo = []
        for h in rep.proposals:
            self.an_hypo.append(f"<okb>{_esc(h.title)}</okb>")
            self.an_hypo.append(f"  {_esc(h.statement)}")
            self.an_hypo.append(f"  <mut>{_esc(h.interpretation)}</mut>")
        if rep.cautions:
            self.an_hypo.append(f"<warn>{_esc(msg('hypo_cautions_head'))}</warn>")
            for c in rep.cautions:
                self.an_hypo.append(f"<warn>· {_esc(c)}</warn>")
        for c in rep.companions[:2]:
            self.an_hypo.append(f"<mut>· {_esc(c)}</mut>")
        self.an_mode = "result"          # 설계·후보를 접는다 — 가설이 화면에 밀려나지 않게
        self.say(msg("screen_an_ran", id=r.id), "ok")
        return True

    def _render_flip_banner(self) -> list[str]:
        """심슨의 역설 경고 — 결론이 뒤집히는 사안이라 목록에 섞지 않고 위에 크게 띄운다."""
        if not self.an_flips:
            return []
        bar = "━" * 74
        return [f"  <alarm>{bar}</alarm>",
                f"  <alarm>  ⛔ {_esc(msg('screen_an_flip_warn', levels=', '.join(self.an_flips)))}</alarm>",
                f"  <alarm>     {_esc(msg('screen_an_flip_why'))}</alarm>",
                f"  <alarm>{bar}</alarm>", ""]

    def _collect_assumptions(self, test_id: str) -> list[str]:
        """실행한 검정이 요구하는 가정 — 값과 p 바로 아래에 붙인다.

        따로 눌러야 보이면 안 본다. 값만 보고 넘어가는 것이 가장 흔한 사고다.
        """
        from statop.analyze.checks import checks_for_test

        try:
            results = checks_for_test(str(self.session_file), test_id, self.sample_n)
        except ValueError:
            return []
        if not results:
            return []
        icon = {"ok": "✅", "caution": "⚠ ", "violated": "⛔", "skipped": "○ "}
        tag = {"ok": "ok", "caution": "warn", "violated": "err", "skipped": "mut"}
        out = [f"<head>{_esc(msg('a3_auto_head', n=len(results)))}</head>"]
        for r in results:
            v = r.verdict if r.verdict in icon else "skipped"
            out.append(f"<{tag[v]}>  {icon[v]} {r.id} {_esc(r.name)} — {_esc(r.summary)}</{tag[v]}>")
            act = (r.numbers or {}).get("action")
            if act:
                out.append(f"<mut>       {_esc(msg('a3_manual_action', action=act))}</mut>")
        return out

    def _collect_compat(self) -> list[str]:
        """이 조합의 적합성 판정 — 비율끼리 상관 같은 것을 값 옆에서 바로 알린다."""
        from statop.analyze.spec import build

        try:
            res = build(str(self.session_file), self._an_spec(), sample_n=self.sample_n)
        except ValueError:
            return []
        findings = (res.compat or {}).get("findings", [])
        if not findings:
            # 아무 말이 없으면 검사가 돌았는지 안 돌았는지 알 수 없다
            return [f"<mut>{_esc(msg('compat_auto_none'))}</mut>"]
        tag = {"gate": "err", "red": "err", "yellow": "warn", "unconfirmed": "mut"}
        out = [f"<head>{_esc(msg('compat_auto_head'))}</head>"]
        for f in findings:
            t = tag.get(f["verdict"], "mut")
            out.append(f"<{t}>  [{f['id']}] {_esc(f['detail'] or f['why'])}</{t}>")
            if f.get("fix"):
                out.append(f"<mut>       → {_esc(f['fix'])}</mut>")
        return out

    def _collect_metrics(self) -> list[str]:
        """S170 — Goal 옆에 병기할 Support·Guardrail. 없으면 없다고 둔다."""
        from statop.analyze.metrics import compute, suggest

        try:
            panel = suggest(str(self.session_file), self.sample_n)
        except ValueError:
            return []
        out: list[str] = []
        for items, head in ((panel.support, "metrics_head_support"),
                            (panel.guardrail, "metrics_head_guardrail")):
            out.append(f"<head>{_esc(msg(head))}</head>")
            if not items:
                out.append(f"<mut>  {_esc(msg('metrics_none'))}</mut>")
            for sug in items:
                tail = "" if sug.computable else f"  ({msg('metrics_check_only')})"
                out.append(f"<okb>  [{sug.id}] {_esc(sug.name)}{_esc(tail)}</okb>")
                if sug.why:
                    out.append(f"<mut>        {_esc(sug.why)}</mut>")
                if not sug.computable:
                    continue
                try:
                    for line in compute(str(self.session_file), sug.id,
                                        self.sample_n)["lines"]:
                        out.append(f"        · {_esc(line)}")
                except (ValueError, KeyError) as e:
                    out.append(f"<err>        · {_esc(str(e))}</err>")
        if panel.triad:
            t = panel.triad
            out.append(f"<head>{_esc(msg('metrics_head_triad'))}</head>")
            out.append("  " + _esc(msg("metrics_triad_row", id=t["id"],
                                       situation=t["situation"], goal=t["goal"],
                                       support=t["support"],
                                       guardrail=t["guardrail"])))
        return out

    def _render_exclusion_block(self) -> list[str]:
        """제외 전/후 병기  — 제외 후 값만 보이면 '빼면 유의해진다'를 숨길 수 있다."""
        b = self.an_excl
        st = b.get("status")
        if not st or not st.n_excluded:
            return []
        key = "points_excl_red" if st.verdict == "red" else "points_excl_yellow"
        tag = "alarm" if st.verdict == "red" else "warn"
        out = [f"  <{tag}>{_esc(msg(key, n=st.n_excluded, total=st.n_total, ratio=st.ratio))}</{tag}>"]
        if b.get("flipped"):
            out.append(f"  <alarm>{_esc(msg('points_flipped'))}</alarm>")
        out.append(f"  <head>{_esc(msg('points_both_head'))}</head>")
        for when, r in (("points_when_before", b.get("before")),
                        ("points_when_after", b.get("after"))):
            if r is None:
                continue
            e = r.effect or {}
            out.append("  " + _esc(msg("points_both_row", when=msg(when), name=r.name,
                                       stat=r.statistic or 0.0, p=r.p or float("nan"),
                                       eff=e.get("name", "?"), val=e.get("value", 0.0))))
        out.append("")
        return out

    def _render_strata(self) -> list[str]:
        """층화 결과 — 전체 아래에 수준별로. 방향이 뒤집힌 수준은 빨갛게."""
        if not self.an_strata:
            return []
        out = ["", f"  <head>{_esc(msg('screen_an_strata_head', col=self.an_strata_col, n=len(self.an_strata)))}</head>"]
        for s_ in self.an_strata:
            if "error" in s_:
                out.append(f"  <mut>· {_esc(s_['level'])} (n={s_['n']}) — {_esc(s_['error'])}</mut>")
                continue
            e = s_.get("effect") or {}
            line = msg("screen_an_strata_row", level=s_["level"], n=s_["n"],
                       name=e.get("name", "?"), value=e.get("value", 0.0),
                       p=s_.get("p") if s_.get("p") is not None else float("nan"))
            tag = "err" if s_["level"] in self.an_flips else "ok"
            out.append(f"  <{tag}>· {_esc(line)}</{tag}>")
        return out

    # ── 전치 (행/열 뒤집기) ─────────────────────────────────
    def open_transpose(self) -> bool:
        from dataclasses import asdict

        from statop.io.transpose import estimate_cost
        from statop.session.core import load_session, main_source, replay

        if not self.data_path:
            self.say(msg("screen_open_first"), "err")
            return False
        try:
            self.tp_info = asdict(estimate_cost(self.data_path))
        except (ValueError, OSError) as e:
            self.say(str(e), "err")
            return False
        if self.session_file:
            doc = load_session(self.session_file)
            src = main_source(doc)
            self.tp_info["on"] = bool(replay(doc)["transposed"].get(
                src["id"] if src else "", False))
        self.step = STEP_TRANSPOSE
        self.say(msg("screen_tp_hint"), "mut")
        return True

    def do_transpose(self) -> bool:
        """전치는 **세션 조작**이다 — 파일을 새로 만들지 않고 보는 방향만 뒤집는다.

        같은 동작을 두 번 하면 원래대로 돌아온다. 원본은 어느 쪽이든 그대로다.
        """
        from statop.io.transpose import transpose_table
        from statop.session.core import (append_op, ensure_source, load_session,
                                       replay, save_session)

        try:
            transpose_table(self.data_path)   # 중복 컬럼명 등은 여기서 바로 걸린다
        except (ValueError, OSError) as e:
            self.say(str(e), "err")
            return False
        doc = load_session(self.session_file)
        src_id = ensure_source(doc, self.data_path)
        append_op(doc, "transpose", source=src_id)
        save_session(doc)
        on = bool(replay(doc)["transposed"].get(src_id, False))
        self.tp_info["on"] = on
        self.imported, self.held = [], []
        self.load_columns()
        self.say(msg("screen_tp_done_on" if on else "screen_tp_done_off"), "ok")
        return True

    def render_transpose(self) -> list[str]:
        i = self.tp_info
        out = [f"  <brand>{_esc(msg('screen_tp_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_tp_flow'))}</mut>", ""]
        if i:
            est = msg("estimated_suffix") if i.get("estimated") else ""
            out.append("  " + _esc(msg("screen_tp_shape", rows=i.get("n_rows", 0),
                                       cols=i.get("n_cols", 0), est=est)))
            tag = "err" if i.get("warn") else "mut"
            out.append(f"  <{tag}>{_esc(msg('screen_tp_cost', mb=i.get('mem_mb', 0)))}</{tag}>")
            if i.get("warn"):
                out.append(f"  <err>{_esc(msg('transpose_confirm_mem'))}</err>")
            state = msg("transpose_state_on" if i.get("on") else "transpose_state_off")
            out.append("  " + _esc(msg("screen_tp_state", state=state)))
        out.append("")
        out.append(f"  <warn>{_esc(msg('screen_tp_warn'))}</warn>")
        return out

    # ── 사본 저장 (가공 파일) ───────────────────────────────
    def pending(self) -> dict:
        from statop.export import pending_changes
        from statop.session.core import load_session

        if self.session_file is None:
            return {"counts": {}, "total": 0, "needs_export": False}
        return pending_changes(load_session(self.session_file))

    def open_savecopy(self) -> bool:
        if self.session_file is None or not self.data_path:
            self.say(msg("screen_open_first"), "err")
            return False
        self.copy_result = {}
        self.step = STEP_SAVECOPY
        self.say(msg("screen_copy_hint"), "mut")
        return True

    def do_savecopy(self, name: str = "", overwrite: bool = False) -> bool:
        """사본 저장 — 원본은 절대 건드리지 않는다."""
        from statop.export import export_trimmed
        from statop.session.core import load_session, main_source, save_session

        doc = load_session(self.session_file)
        try:
            res = export_trimmed(doc, name=(name or self.copy_name).strip() or None,
                                 overwrite=overwrite,
                                 use_as_main=self.copy_use_main)
        except FileExistsError as e:
            self.say(str(e), "err")
            return False
        except ValueError as e:
            self.say(str(e), "err")
            return False
        save_session(doc)
        self.copy_result = {"path": str(res.path), "sidecar": str(res.sidecar),
                            "rows": res.n_rows, "cols": res.n_cols,
                            "relabels": res.n_relabels}
        if self.copy_use_main:
            self.data_path = main_source(load_session(self.session_file))["path"]
        self.say(msg("screen_copy_done", path=res.path, rows=res.n_rows), "ok")
        return True

    def render_savecopy(self) -> list[str]:
        p = self.pending()
        out = [f"  <brand>{_esc(msg('screen_copy_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_copy_flow'))}</mut>", ""]
        if p["total"]:
            detail = " · ".join(f"{msg('op_' + k)} {v}" for k, v in p["counts"].items())
            out.append(f"  <warn>{_esc(msg('screen_copy_pending', n=p['total'], detail=detail))}</warn>")
        else:
            out.append(f"  <mut>{_esc(msg('screen_copy_nothing'))}</mut>")
        out.append("")
        mark = "✔" if self.copy_use_main else " "
        out.append(f"  [{mark}] {_esc(msg('screen_copy_use_main'))}")
        out.append(f"  <mut>{_esc(msg('screen_copy_origin', path=self.data_path or '-'))}</mut>")
        if (note := self.origin_note()):
            out.append(f"  <mut>{_esc(note)}</mut>")
        if self.copy_result:
            r = self.copy_result
            out += ["", f"  <ok>{_esc(msg('screen_copy_saved', path=r['path'], rows=r['rows'], cols=r['cols']))}</ok>",
                    f"  <mut>{_esc(msg('screen_copy_sidecar', path=r['sidecar']))}</mut>"]
            if r["relabels"]:
                out.append(f"  <warn>{_esc(msg('export_relabel_note', n=r['relabels']))}</warn>")
        return out

    # ── 지표 찾기  ────────────────────────────────────
    # 질문 → 컬럼 → 무엇을 쓸까. 값은 **누를 때만** 낸다.
    def open_find(self) -> bool:
        from statop.analyze.spec import questions

        if not self.imported:
            self.say(msg("screen_an_need_columns"), "err")
            return False
        self.find_questions = [{"id": q["id"], "name": q.get("question", q["id"]),
                                "words": q.get("user_words", "")}
                               for q in questions()]
        self.find_stage = 0
        self.find_row = 0
        self.find_cands = []
        self.find_ran = {}
        self.find_adj = None
        self.step = STEP_FIND
        self.say(msg("screen_find_pick_q"), "mut")
        return True

    def find_columns(self) -> list[str]:
        """고를 수 있는 컬럼 — 분석에서 뺀 것(hold)은 빼고, 파생도 넣는다."""
        return [c for c in self.formula_columns() if c not in self.held]

    def find_rows(self) -> list:
        """지금 단계에서 ↑↓ 로 오르내리는 목록."""
        if self.find_stage == 0:
            return self.find_questions
        if self.find_stage == 1:
            return self.find_columns()
        return self.find_cands

    def move_find(self, delta: int) -> None:
        n = len(self.find_rows())
        if n:
            self.find_row = max(0, min(n - 1, self.find_row + delta))

    def find_stage_move(self, delta: int) -> None:
        self.find_stage = max(0, min(2, self.find_stage + delta))
        self.find_row = 0

    def find_pick(self) -> bool:
        """지금 줄을 고른다 — 단계마다 뜻이 다르다 (질문 / 컬럼 / 계산)."""
        rows = self.find_rows()
        if not rows or self.find_row >= len(rows):
            return False
        if self.find_stage == 0:
            self.find_q = rows[self.find_row]["id"]
            self.find_stage = 1
            self.find_row = 0
            self.find_cands, self.find_ran, self.find_adj = [], {}, None
            self.say(msg("screen_find_pick_col"), "mut")
            return True
        if self.find_stage == 1:
            return self.toggle_find_col(rows[self.find_row])
        return self.run_find(rows[self.find_row]["id"])

    def toggle_find_col(self, col: str) -> bool:
        """두 개까지 — 세 번째를 켜면 가장 오래된 것이 빠진다.

        **하나를 골랐다고 다음 단계로 넘기지 않는다.** 넘겨 버리면 둘째 컬럼을 고를
        자리가 없어진다 (실제로 그랬다). 두 개가 차면 그때 넘어간다.
        """
        if col in self.find_cols:
            self.find_cols.remove(col)
        else:
            self.find_cols = [*self.find_cols, col][-2:]
        self.find_cands, self.find_ran, self.find_adj = [], {}, None
        self.find_plot = []
        ok = self.load_find()
        if len(self.find_cols) >= 2 and self.find_cands:
            self.find_stage = 2
            self.find_row = 0
            self.say(msg("screen_find_run_hint"), "mut")
        return ok

    def load_find(self) -> bool:
        """후보만 받아 온다 — **값은 아직 내지 않는다.**"""
        from statop.analyze.explore import find

        if not (self.find_q and self.find_cols):
            return False
        try:
            f = find(str(self.session_file), self.find_q, list(self.find_cols),
                     self.sample_n)
        except (ValueError, KeyError) as e:
            self.say(str(e), "err")
            return False
        self.find_cands = f.candidates
        self.find_problems = list(f.problems)
        self.refresh_power()
        return True

    def refresh_power(self) -> None:
        """이 표본으로 무엇이 잡히나 — **방금 잰 것 하나만** 선 위에 올린다 .

        여럿을 한꺼번에 얹으면 어느 값이 어느 지표인지 알 수 없고, 새로 재면 앞의
        것 위에 덧씌워진다. 잰 값은 목록에 그대로 남는다.
        """
        from statop.analyze.explore import power

        r = self.find_ran.get(self.find_focus or "")
        if r is None and self.find_ran:
            self.find_focus = list(self.find_ran)[-1]
            r = self.find_ran[self.find_focus]
        eff = [{"id": self.find_focus, "name": r["name"], "value": r["effect"],
                "effect_name": r["effect_name"]}] if r else []
        try:
            self.find_power = power(str(self.session_file), self.find_q,
                                    list(self.find_cols), eff, self.sample_n,
                                    self.find_target) or {}
        except (ValueError, KeyError):
            self.find_power = {}

    def run_find(self, test_id: str) -> bool:
        """**누른 검정 하나만** 돌린다 — 기록하지 않는다."""
        from statop.analyze.explore import run

        cand = next((c for c in self.find_cands if c["id"] == test_id), None)
        if cand and not cand.get("runnable", True):
            self.say(msg("screen_find_not_runnable"), "err")
            return False
        try:
            r = run(str(self.session_file), self.find_q, list(self.find_cols),
                    test_id, self.sample_n)
        except (ValueError, KeyError, TypeError) as e:
            self.say(msg("explore_run_failed", name=test_id, why=str(e)[:80]), "err")
            return False
        self.find_ran[test_id] = r
        self.find_focus = test_id         # **방금 잰 것**을 검정력에서 본다
        self.find_adj = None              # 검정이 늘면 보정도 다시 해야 한다
        self.refresh_power()
        self.say(msg("screen_find_ran", name=r["name"], eff_name=r["effect_name"],
                     eff=_g(r["effect"]), p=_g(r["p"])), "ok")
        return True

    def toggle_find_rule(self) -> bool:
        """그 검정의 **근거**를 편다 — 규칙표에 적힌 그대로 (설계·가정·주의·대안)."""
        rows = self.find_rows()
        if self.find_stage != 2 or not rows or self.find_row >= len(rows):
            return False
        cid = rows[self.find_row]["id"]
        self.find_rule = "" if self.find_rule == cid else cid
        return True

    def find_color_cycle(self) -> bool:
        """색으로 나눌 군을 돌린다 — 섞여서 생긴 관계는 색을 나눠야 보인다."""
        from statop.session.core import load_session, main_source, replay

        doc = load_session(self.session_file)
        src = main_source(doc)
        types = replay(doc)["semantic_types"].get(src["id"], {}) if src else {}
        cands = [c for c in self.find_columns()
                 if types.get(c) in ("label", "nominal code")
                 and c not in self.find_cols]
        if not cands:
            self.say(msg("screen_find_color_none"), "err")
            return False
        ring = [None, *cands]
        i = ring.index(self.find_color) if self.find_color in ring else 0
        self.find_color = ring[(i + 1) % len(ring)]
        self.find_plot = []
        self.say(msg("screen_find_color_set", col=self.find_color)
                 if self.find_color else msg("screen_find_color_off"), "ok")
        return True

    def toggle_find_plot(self) -> bool:
        """고른 컬럼의 **모양** — 값과 p 만 보면 V 자인지 직선인지 알 수 없다."""
        from statop.analyze.explore import points
        from statop.render.chart import scatter, strip_plot

        if self.find_plot:
            self.find_plot = []
            return True
        if not (self.find_q and len(self.find_cols) >= 1):
            self.say(msg("screen_find_plot_none"), "err")
            return False
        try:
            d = points(str(self.session_file), self.find_q, list(self.find_cols),
                       self.find_color, self.sample_n)
        except (ValueError, KeyError) as e:
            self.say(str(e), "err")
            return False
        if d["kind"] == "scatter":
            out = [msg("screen_find_plot_head", x=d["x_label"], y=d["y_label"],
                       n=f"{d['n']:,}")]
            for ser in d["series"]:
                xs = [q[0] for q in ser["pts"]]
                ys = [q[1] for q in ser["pts"]]
                if ser["name"]:
                    out.append(f"[{ser['name']}]")
                out += scatter(xs, ys, width=52, height=12,
                               xlab=d["x_label"], ylab=d["y_label"])
        else:
            out = [msg("screen_find_plot_groups", x=d["x_label"],
                       by=d["y_label"] or "-")]
            lo, hi = d["edges"][0], d["edges"][-1]
            groups = {}
            for ser in d["series"]:
                # 막대 높이를 그대로 점으로 펴지 않고, 구간 중앙값으로 되살린다
                mids = []
                for i, c in enumerate(ser["bins"]):
                    mid = (d["edges"][i] + d["edges"][i + 1]) / 2
                    mids += [mid] * c
                groups[ser["name"] or "-"] = mids
            out += strip_plot(groups, width=52)
            assert lo <= hi
        self.find_plot = out
        return True

    FIND_METHODS = ("holm", "bh", "bonferroni", "none")

    def set_find_target(self, text: str) -> bool:
        """목표 검정력을 **쳐서** 옮긴다 — 웹의 입력칸과 같은 일 (50~99%)."""
        from statop.analyze.explore import clamp_target

        s = (text or "").strip().rstrip("%").strip()
        if not s:
            return False
        try:
            v = float(s)
        except ValueError:
            self.say(msg("screen_find_aim_bad"), "err")
            return False
        self.find_target = clamp_target(v / 100 if v > 1 else v)
        self.refresh_power()
        head = (self.find_power or {}).get("head")
        self.say(head or msg("power_note_alpha", pw=f"{self.find_target * 100:g}"), "ok")
        return True

    def cycle_find_adjust(self) -> bool:
        """여러 번 쟀으면 그 수를 센다 (C-15 · post.yaml P-221~223)."""
        from statop.analyze.padjust import report

        rows = [{"name": r["name"], "p": r["p"]} for r in self.find_ran.values()
                if r.get("p") is not None]
        if len(rows) < 2:
            self.say(msg("a3_name_multiplicity") + " — " + msg("padj_why"), "mut")
            return False
        i = self.FIND_METHODS.index(self.find_method)
        self.find_method = self.FIND_METHODS[(i + 1) % len(self.FIND_METHODS)]
        self.find_adj = report(rows, self.find_method)
        self.say(self.find_adj["head"], "ok")
        return True

    def find_goal(self) -> bool:
        """지금 줄의 검정을 Goal 로 — 이건 기록된다."""
        from statop.analyze.metrics import set_goal

        rows = self.find_rows()
        if self.find_stage != 2 or not rows or self.find_row >= len(rows):
            return False
        ran = self.find_ran.get(rows[self.find_row]["id"]) or {}
        try:
            set_goal(str(self.session_file), test=rows[self.find_row]["id"],
                     name=rows[self.find_row]["name"],
                     effect_key=ran.get("effect_name") or None)
        except ValueError as e:
            self.say(str(e), "err")
            return False
        self.say(msg("metrics_goal_set", name=rows[self.find_row]["name"]), "ok")
        return True

    def find_role(self, role: str) -> bool:
        """지금 줄의 검정을 **함께 볼 것**으로 — Goal 을 정한 뒤에만.

        목록이 이미 화면에 있으므로 따로 검색칸을 두지 않는다. 고른 것은
        규칙표(base)를 건드리지 않고 '사용자 지정'으로 남는다.
        """
        from statop.analyze.metrics import add_custom, goal_key, suggest

        rows = self.find_rows()
        if self.find_stage != 2 or not rows or self.find_row >= len(rows):
            return False
        try:
            key = goal_key(suggest(str(self.session_file)))
        except (ValueError, KeyError) as e:
            self.say(str(e), "err")
            return False
        if not key:
            self.say(msg("screen_find_goal_first"), "err")
            return False
        name = rows[self.find_row]["name"]
        add_custom(key, role, name, "")
        self.find_roles.setdefault(role, []).append(name)
        self.say(msg("metrics_custom_added", name=name, role=role), "ok")
        return True

    def click_find(self, y: int) -> bool:
        i = y - self.find_top
        rows = self.find_rows()
        if not (0 <= i < len(rows)):
            return False
        self.find_row = i
        return self.find_pick()

    def render_find(self) -> list[str]:
        out = [f"  <brand>{_esc(msg('screen_find_title'))}</brand>", ""]
        qname = next((q["name"] for q in self.find_questions
                      if q["id"] == self.find_q), "-")
        cols = " × ".join(self.find_cols) or "-"
        for i, (key, val) in enumerate(((msg("screen_find_step1"), qname),
                                        (msg("screen_find_step2"), cols))):
            mark = "▸" if self.find_stage == i else " "
            style = "sel" if self.find_stage == i else "mut"
            out.append(f"  {mark} <{style}>{_esc(key)}</{style}>  {_esc(val)}")
        out.append("")
        self.find_top = len(out)

        if self.find_stage == 0:
            for i, q in enumerate(self.find_questions):
                cur = "▸" if i == self.find_row else " "
                body = f"{cur} {_pad_cells(q['name'], 30)} {q['words'][:44]}"
                out.append(f"  <sel>{_esc(body)}</sel>" if i == self.find_row
                           else f"  {_esc(body)}")
            return out

        if self.find_stage == 1:
            for i, c in enumerate(self.find_columns()):
                cur = "▸" if i == self.find_row else " "
                mark = f"{self.find_cols.index(c) + 1}." if c in self.find_cols else "☐"
                body = f"{cur} {mark} {c}"
                out.append(f"  <sel>{_esc(body)}</sel>" if i == self.find_row
                           else f"  {_esc(body)}")
            out.append(f"  <mut>{_esc(msg('screen_find_pick_col'))}</mut>")
            # 하나만 골랐으면 **둘째가 무엇의 자리인지** 말해 준다 — 그걸 모르면
            # 아무거나 골라 놓고 왜 안 되는지 묻게 된다
            if len(self.find_cols) == 1 and self.find_q:
                from statop.analyze.explore import second_columns, second_role

                role = second_role(self.find_q)
                out.append(f"  <warn>{_esc(msg('explore_need_second_' + role))}</warn>")
                try:
                    cands = second_columns(str(self.session_file), self.find_q,
                                           list(self.find_cols), self.sample_n)
                except (ValueError, KeyError):
                    cands = []
                out.append("  <mut>" + _esc(
                    msg("explore_second_pick") + ": " + ", ".join(cands) if cands
                    else msg("explore_second_none")) + "</mut>")
            return out

        if not self.find_cands:
            out.append(f"  <err>{_esc(msg('screen_find_none'))}</err>")
            for pr in self.find_problems:
                out.append(f"  <warn>{_esc(pr)}</warn>")
            return out

        if self.find_plot:
            out += ["", *[f"  <mut>{_esc(x)}</mut>" for x in self.find_plot], ""]
        flag = {"green": "✅", "yellow": "⚠ ", "red": "⛔"}
        style_of = {"green": "ok", "yellow": "warn", "red": "err"}
        for i, c in enumerate(self.find_cands):
            cur = "▸" if i == self.find_row else " "
            body = cur + " " + msg("screen_find_row", flag=flag.get(c["verdict"], "○"),
                                   id=c["id"], name=c["name"])
            st = style_of.get(c["verdict"], "mut")
            out.append(f"  <sel>{_esc(body)}</sel>" if i == self.find_row
                       else f"  <{st}>{_esc(body)}</{st}>")
            r = self.find_ran.get(c["id"])
            if r:
                adj = None
                if self.find_adj:
                    adj = next((x["p_adjusted"] for x in self.find_adj["rows"]
                                if x["name"] == r["name"]), None)
                n = " · ".join(f"{k} {v:,}" for k, v in (r["n"] or {}).items())
                if adj is None:
                    out.append("  " + _esc(msg("screen_find_value",
                                               eff_name=r["effect_name"],
                                               eff=_g(r["effect"]), p=_g(r["p"]), n=n)))
                else:
                    sig = adj <= 0.05
                    out.append("  " + _esc(msg("screen_find_value_adj",
                                               eff_name=r["effect_name"],
                                               eff=_g(r["effect"]), p=_g(r["p"]),
                                               adj=_g(adj),
                                               mark=msg("padj_sig" if sig else "padj_ns"),
                                               n=n)))
            elif c["reasons"]:
                out.append(f"       <mut>{_esc(c['reasons'][0][:70])}</mut>")
            if self.find_rule == c["id"]:
                from statop.analyze.explore import rule_labels

                for key, label in rule_labels():
                    val = (c.get("rule") or {}).get(key)
                    if val:
                        out.append(f"       <mut>{_esc(label)}  {_esc(str(val))}</mut>")
        # ── 결론: 재고 나면 여기부터 읽는다  ──────────────
        seen_now = self.find_ran.get(self.find_focus or "")
        nxt = (seen_now or {}).get("next") or {}
        if nxt.get("head"):
            out += ["", f"  <head>{_esc(nxt['head'])}</head>"]
            for line in nxt.get("lines", []):
                out.append(f"  {_esc(line)}")
            steps = nxt.get("steps", [])
            if steps:
                out.append(f"  <brand>{_esc(msg('screen_find_next'))}</brand>")
                for s in steps:
                    out.append(f"  <warn>· {_esc(s['text'])}</warn>")

        pw = self.find_power or {}
        if pw.get("head"):
            seen = self.find_ran.get(self.find_focus or "")
            out += ["", f"  <head>{_esc(pw['head'])}</head>",
                    f"  <mut>{_esc(pw['note'])}</mut>"]
            # 무엇을 보고 있는지 — 적지 않으면 값만 떠 있게 된다
            where = msg("screen_find_power_what", cols=" × ".join(self.find_cols),
                        name=seen["name"]) if seen else ""
            if where:
                out.append(f"  <mut>{_esc(where)}</mut>")
            if len(self.find_ran) > 1:
                out.append("  <mut>" + _esc(msg(
                    "screen_find_power_one",
                    others=", ".join(v["name"] for k, v in self.find_ran.items()
                                     if k != self.find_focus))) + "</mut>")
            for r in pw.get("rows", []):
                st = "err" if r.get("comparable") is False else (
                    "ok" if r.get("catchable") else "warn")
                out.append(f"  <{st}>{_esc(r['name'])}  {_g(r['value'])}"
                           f"  — {_esc(r['line'])}</{st}>")
            out.append(f"  <mut>{_esc(pw['why'])}</mut>")
        if self.find_roles:
            out.append("")
            for role, names in self.find_roles.items():
                out.append("  <mut>" + _esc(msg(
                    "screen_find_roles_now",
                    role=msg("screen_find_support_btn" if role == "support"
                             else "screen_find_guard_btn"),
                    names=", ".join(names))) + "</mut>")
        if self.find_adj:
            out += ["", f"  <head>{_esc(self.find_adj['head'])}</head>",
                    f"  <mut>{_esc(self.find_adj['why'])}</mut>"]
        return out

    # ── 임시본 정리 (캐시 지우기) ───────────────────────────
    # 저장하지 않은 작업은 자동으로 지우지 않는다 — 그러면 쌓인다.
    # 무엇이 쌓였는지 **보고 나서** 지울 자리가 있어야 한다.
    def open_tmp(self) -> bool:
        self.tmp_rows = self.tmp_list()
        self.tmp_row = 0
        self.tmp_confirm = False
        self.step = STEP_TMP
        self.say(msg("screen_tmp_keep_note"), "mut")
        return True

    def tmp_list(self) -> list[dict]:
        """임시본 한 줄 요약 — **파일을 열지 않고** 기록에서 읽을 수 있는 것만.

        무엇이었는지 알아볼 만큼만 보인다: 세션 id · 연 파일 · 조작 개수와 종류.
        값은 애초에 임시본에 없다.
        """
        import json
        from datetime import datetime

        from statop.store import tmp_dir

        cur = str(Path(self.session_file).resolve()) if self.session_file else ""
        rows = []
        try:
            files = sorted(tmp_dir().glob("session_*.json"),
                           key=lambda q: q.stat().st_mtime, reverse=True)
        except OSError:
            return []
        for f in files:
            try:
                doc = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            ops = [o.get("op", "?") for o in doc.get("ops", [])]
            src = next((x.get("path", "") for x in doc.get("sources", [])), "")
            kinds = list(dict.fromkeys(ops))
            rows.append({
                "file": f, "id": doc.get("session_id", f.stem),
                "path": src, "n_ops": len(ops),
                "ops": " · ".join(kinds[:5]) + (" …" if len(kinds) > 5 else ""),
                "when": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M"),
                "kb": f.stat().st_size / 1024,
                "current": str(f.resolve()) == cur,
            })
        return rows

    def move_tmp(self, delta: int) -> None:
        if self.tmp_rows:
            self.tmp_row = max(0, min(len(self.tmp_rows) - 1, self.tmp_row + delta))

    def delete_tmp(self) -> bool:
        """두 번 눌러야 지운다 — 되돌릴 수 없는 일은 한 번에 일어나면 안 된다."""
        targets = [r for r in self.tmp_rows if not r["current"]]
        if not targets:
            self.say(msg("screen_tmp_none"), "err")
            return False
        if not self.tmp_confirm:
            self.tmp_confirm = True
            self.say(msg("screen_tmp_confirm", n=len(targets)), "err")
            return False
        gone, failed = 0, []
        for r in targets:
            try:
                r["file"].unlink()
                gone += 1
            except OSError as e:
                failed.append(str(e))
        self.tmp_rows = self.tmp_list()
        self.tmp_row = 0
        self.tmp_confirm = False
        if failed:
            self.say(msg("screen_tmp_failed", n=len(failed), why=failed[0]), "err")
        else:
            self.say(msg("screen_tmp_done", n=gone), "ok")
        return True

    def click_tmp(self, y: int) -> bool:
        i = (y - self.tmp_top) // 2          # 한 항목이 두 줄이다
        if not (0 <= i < len(self.tmp_rows)):
            return False
        self.tmp_row = i
        return True

    def render_tmp(self) -> list[str]:
        rows = self.tmp_rows
        total = sum(r["kb"] for r in rows)
        out = [f"  <brand>{_esc(msg('screen_tmp_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_tmp_what'))}</mut>",
               f"  <mut>{_esc(msg('screen_tmp_keep_note'))}</mut>", ""]
        if not rows:
            out.append(f"  <mut>{_esc(msg('screen_tmp_none'))}</mut>")
            return out
        out.append(f"  <head>{_esc(msg('screen_tmp_count', n=len(rows), kb=f'{total:.0f}'))}</head>")
        self.tmp_top = len(out)
        for i, r in enumerate(rows):
            cur = "▸" if i == self.tmp_row else " "
            body = f"{cur} " + msg("screen_tmp_row", id=r["id"], when=r["when"],
                                   n=r["n_ops"], ops=r["ops"] or "-")
            out.append(f"  <sel>{_esc(body)}</sel>" if i == self.tmp_row
                       else f"  {_esc(body)}")
            out.append(f"  <mut>{_esc(msg('screen_tmp_current') if r['current'] else msg('screen_tmp_source', path=r['path'] or '-'))}</mut>")
        return out

    # ── 무결성 검증 (비교 파일을 하나 더 연다) ──────────────
    def open_verify(self) -> bool:
        if not self.data_path:
            self.say(msg("screen_open_first"), "err")
            return False
        self.verify_result = None
        self.step = STEP_VERIFY
        self.say(msg("screen_verify_hint"), "mut")
        return True

    def set_verify_path(self, path: str) -> bool:
        from pathlib import Path as _P

        p = (path or "").strip()
        if not p or not _P(p).exists():
            self.say(msg("path_not_exist"), "err")
            return False
        self.verify_path = str(_P(p).resolve())
        self.verify_result = None
        self.verify_cols = set()
        self.say(msg("screen_verify_loaded", path=self.verify_path), "ok")
        return True

    def verify_summary(self) -> list[dict]:
        """대조한 컬럼마다 같음/다름 한 줄 — **첫 장은 이것만** 본다."""
        r = self.verify_result
        if r is None:
            return []
        rows = []
        for c in r.columns:
            rows.append({"column": c["column"], "same": c["n_diff"] == 0, "info": c})
        for u in r.unmatched:
            rows.append({"column": u["column"], "same": None, "why": u["why"]})
        return rows

    def move_verify_sum(self, delta: int) -> None:
        rows = self.verify_summary()
        if rows:
            self.verify_sum_row = max(0, min(len(rows) - 1, self.verify_sum_row + delta))

    def step_verify_detail(self, delta: int) -> bool:
        """상세를 보는 중이면 **컬럼을 넘긴다** — 요약이면 줄만 옮긴다."""
        rows = [r for r in self.verify_summary() if r["same"] is not None]
        if not rows:
            return False
        if self.verify_detail < 0:
            self.move_verify_sum(delta)
            return True
        self.verify_detail = (self.verify_detail + delta) % len(rows)
        return self.verify_view_column(rows[self.verify_detail]["column"])

    def open_verify_detail(self) -> bool:
        """요약에서 고른 컬럼을 자세히 — 개형·통계 차이·분포 거리."""
        rows = self.verify_summary()
        if not rows or self.verify_sum_row >= len(rows):
            return False
        row = rows[self.verify_sum_row]
        if row["same"] is None:
            self.say(row["why"], "warn")
            return False
        done = [r["column"] for r in rows if r["same"] is not None]
        self.verify_detail = done.index(row["column"])
        return self.verify_view_column(row["column"])

    def back_to_summary(self) -> None:
        self.verify_detail = -1
        self.verify_view = []

    def verify_view_column(self, column: str = "") -> bool:
        """한 컬럼을 A/B 로 겹쳐 본다 — "바뀐 셀 2개"로는 어디가 어떻게 옮겼는지 모른다."""
        from statop.integrity import column_view

        col = column or (self.current_verify_row() or {}).get("column", "")
        if not col:
            return False
        done = {c["column"] for c in (self.verify_result.columns
                                      if self.verify_result else [])}
        if self.verify_result is not None and col not in done:
            self.say(msg("colview_no_column", col=col), "err")
            return False
        try:
            view = column_view(self.data_path, self.verify_path,
                               self.verify_key_now(), col, dict(self.verify_pairs))
        except (ValueError, OSError, KeyError) as e:
            self.say(str(e), "err")
            return False
        self.verify_view = view["lines"]
        done = [x["column"] for x in self.verify_summary() if x["same"] is not None]
        if col in done:
            self.verify_detail = done.index(col)
        self.say(msg("colview_head", col=col, n=f"{view['n']:,}"), "ok")
        return True

    def _verify_sides(self) -> tuple[list, list]:
        """양쪽 파일의 컬럼 이름 — 헤더만 읽는다 (값은 안 읽는다)."""
        from statop.io.meta import open_meta

        if not (self.data_path and self.verify_path):
            return [], []
        try:
            return (list(open_meta(self.data_path).columns),
                    list(open_meta(self.verify_path).columns))
        except (ValueError, OSError):
            return [], []

    def verify_rows(self) -> list[dict]:
        """컬럼 한 줄에 하나 — 짝이 있는지, 없으면 왜 없는지까지 한 줄에.

        한 줄에 전부 붙여 놓으면 어느 컬럼을 클릭했는지 알 수 없다 — 실제로
        클릭이 전체 토글로 동작해 **하나씩 고를 수가 없었다.**
        """
        a, b = self._verify_sides()
        bset = set(b)
        used = set(self.verify_pairs.values())
        rows = []
        for c in a:
            other = self.verify_pairs.get(c) or (c if c in bset else "")
            rows.append({"column": c, "side": "a", "pair": other,
                         "renamed": bool(other and other != c)})
        for c in b:
            if c not in set(a) and c not in used:
                rows.append({"column": c, "side": "b", "pair": "", "renamed": False})
        return rows

    def verify_columns(self) -> list[str]:
        """짝이 있어 대조할 수 있는 컬럼 (A 쪽 이름)."""
        return [r["column"] for r in self.verify_rows() if r["pair"]]

    VERIFY_PAGE = 12

    def verify_pages(self) -> int:
        return max(1, -(-len(self.verify_rows()) // self.VERIFY_PAGE))

    def verify_page_rows(self) -> list[dict]:
        self.verify_page = max(0, min(self.verify_page, self.verify_pages() - 1))
        i = self.verify_page * self.VERIFY_PAGE
        return self.verify_rows()[i:i + self.VERIFY_PAGE]

    def move_verify_page(self, delta: int) -> None:
        self.verify_page = (self.verify_page + delta) % self.verify_pages()
        self.verify_row = 0

    def move_verify_row(self, delta: int) -> None:
        n = len(self.verify_page_rows())
        if n:
            self.verify_row = max(0, min(n - 1, self.verify_row + delta))

    def current_verify_row(self) -> dict | None:
        rows = self.verify_page_rows()
        return rows[self.verify_row] if self.verify_row < len(rows) else None

    def toggle_verify_col(self, name: str) -> None:
        self.verify_cols ^= {name}

    def toggle_verify_all(self) -> None:
        cols = set(self.verify_columns())
        self.verify_cols = set() if self.verify_cols else cols

    # ── 맞추는 키 ───────────────────────────────────────────
    def verify_key_candidates(self) -> list[str]:
        """키 후보는 **행 식별자로 확정한 컬럼**이다 (양쪽에 다 있어야 한다).

        아무 컬럼이나 키로 쓰면 값이 겹쳐 행이 1:1 로 안 맞고, 그러면 대조가
        통째로 멈춘다. 무엇이 행을 가리키는지는 이미 의미 타입에서 정했다.
        """
        from statop.session.core import load_session, main_source, replay

        if self.session_file is None:
            return []
        a, b = self._verify_sides()
        both = set(a) & set(b)
        doc = load_session(self.session_file)
        src = main_source(doc)
        if src is None:
            return []
        types = replay(doc)["semantic_types"].get(src["id"], {})
        return [c for c, t in types.items() if t == "id" and c in both]

    def verify_key_now(self) -> str:
        cands = self.verify_key_candidates()
        if self.verify_key in cands:
            return self.verify_key
        return cands[0] if cands else ""

    def cycle_verify_key(self) -> bool:
        cands = self.verify_key_candidates()
        if len(cands) < 2:
            self.say(msg("screen_verify_key_only_one" if cands
                         else "screen_verify_key_none"), "err")
            return False
        i = cands.index(self.verify_key_now())
        self.verify_key = cands[(i + 1) % len(cands)]
        self.verify_result = None
        self.say(msg("screen_verify_key_changed", key=self.verify_key), "ok")
        return True

    def confirm_verify_id(self) -> bool:
        """커서 컬럼을 **행 식별자로 확정**한다 — 이 화면을 떠나지 않고.

        키가 없어서 대조를 못 하는데 타입 화면으로 보내 버리면, 돌아왔을 때
        무엇을 하려 했는지 잊는다.
        """
        from statop.session.core import append_op, load_session, main_source, save_session

        r = self.current_verify_row()
        if r is None:
            return False
        col = r["column"]
        a, b = self._verify_sides()
        if not (col in set(a) and col in set(b)):
            self.say(msg("screen_verify_key_not_both", col=col), "err")
            return False
        dup = self._verify_key_dups(col)
        if dup:
            self.say(msg("screen_verify_key_dup", col=col, n=dup), "err")
            return False
        doc = load_session(self.session_file)
        src = main_source(doc)
        append_op(doc, "semantic_confirm", source=src["id"], column=col, type="id")
        save_session(doc)
        self.verify_key = col
        self.verify_result = None
        self.say(msg("screen_verify_key_confirmed", col=col), "ok")
        return True

    def _verify_key_dups(self, col: str) -> int:
        """키 후보의 값이 겹치는지 — 겹치면 행을 1:1 로 못 맞춘다."""
        from statop.io.sample import sample_rows

        try:
            v = sample_rows(self.data_path, n=self.sample_n)[col]
        except (ValueError, OSError, KeyError):
            return 0
        return int(v.astype(str).duplicated().sum())

    # ── 이름이 다른 같은 컬럼 짝 짓기 ───────────────────────
    def pair_verify_col(self) -> bool:
        """커서 컬럼에 **짝 없는 상대**를 하나씩 대 본다 — 누를 때마다 다음 후보로.

        `log2_frac_v1` ↔ `log2_frac_v2` 처럼 판본만 다른 컬럼이 서로 "한쪽에만
        있는 컬럼"으로 갈려 대조에서 통째로 빠지는 것을 막는다.
        """
        r = self.current_verify_row()
        if r is None:
            return False
        col = r["column"]
        if r["side"] == "b":
            self.say(msg("screen_verify_pair_only_unmatched"), "err")
            return False
        a, b = self._verify_sides()
        if col in set(b):
            self.say(msg("screen_verify_pair_only_unmatched"), "err")
            return False
        used = set(self.verify_pairs.values())
        free = [c for c in b if c not in set(a)
                and (c not in used or self.verify_pairs.get(col) == c)]
        if not free:
            self.say(msg("screen_verify_pair_none"), "err")
            return False
        # 후보를 한 바퀴 돌면 **짝 없음**으로 돌아온다 — 잘못 지었을 때 되돌릴 길이
        # 없으면 화면을 나갔다 들어와야 했다
        ring = [*free, None]
        cur = self.verify_pairs.get(col)
        i = ring.index(cur) if cur in ring else len(ring) - 1
        nxt = ring[(i + 1) % len(ring)]
        if nxt is None:
            self.verify_pairs.pop(col, None)
            self.say(msg("screen_verify_pair_cleared", a=col), "ok")
        else:
            self.verify_pairs[col] = nxt
            self.say(msg("screen_verify_pair_set", a=col, b=nxt), "ok")
        self.verify_result = None
        return True

    def do_verify(self) -> bool:
        from statop.integrity import compare_tables

        if not self.verify_path:
            self.say(msg("screen_verify_need_file"), "err")
            return False
        key = self.verify_key_now()
        if not key:
            self.say(msg("screen_verify_key_none"), "err")
            return False
        cols = sorted(self.verify_cols) or None
        self.verify_view = []
        self.verify_detail = -1
        self.verify_sum_row = 0
        self.verify_picking = False       # 대조하면 **결과를 본다** — 고르기는 끝났다
        try:
            self.verify_result = compare_tables(
                self.data_path, self.verify_path, key=key, columns=cols,
                show_values=True, pairs=dict(self.verify_pairs))
        except (ValueError, OSError) as e:
            self.say(str(e), "err")
            return False
        r = self.verify_result
        self.say(msg("screen_verify_same" if r.identical else "screen_verify_diff"),
                 "ok" if r.identical else "err")
        return True

    def render_verify(self) -> list[str]:
        """세 토막으로 읽힌다 — 무엇을 무엇과 맞추는가 · 어느 컬럼을 볼까 · 결과.

        결과는 **한 줄 판정부터** 낸다. 빨간 줄을 여러 개 늘어놓으면 결국
        "그래서 같다는 거야 다르다는 거야"가 안 보인다.
        """
        from statop.io.meta import open_meta

        out = [f"  <brand>{_esc(msg('screen_verify_title2'))}</brand>", ""]

        def side(tag: str, path: str) -> str:
            """행 수는 **아는 경우에만** 적는다 — csv 는 헤더만 읽으므로 모른다.
            세어서 채우려면 파일을 통째로 읽어야 한다. 대조한 뒤에는 결과가 알려 준다."""
            try:
                m = open_meta(path)
                n_rows = getattr(m, "n_rows", None)
                cols = len(list(m.columns))
            except (ValueError, OSError):
                return f"  {_esc(tag)}  {_esc(path)}"
            if n_rows is None:
                return "  " + _esc(msg("screen_verify_side_cols", tag=tag,
                                       name=Path(path).name, cols=cols))
            return "  " + _esc(msg("screen_verify_side", tag=tag,
                                   name=Path(path).name, rows=f"{n_rows:,}",
                                   cols=cols))

        out.append(side(msg("screen_verify_a", path="").rstrip(": "), self.data_path or "-"))
        if self.origin_note():
            out.append(f"  <mut>{_esc(self.origin_note())}</mut>")
        if self.verify_path:
            out.append(side(msg("screen_verify_b", path="").rstrip(": "), self.verify_path))
        else:
            out.append(f"  <mut>{_esc(msg('screen_verify_side_b_none'))}</mut>")
            return out

        key = self.verify_key_now()
        if key:
            out.append("  " + _esc(msg("screen_verify_key_line", key=key)))
        else:
            out.append(f"  <err>{_esc(msg('screen_verify_key_none'))}</err>")
            out.append(f"  <mut>{_esc(msg('screen_verify_key_howto'))}</mut>")

        # ── 컬럼 고르기 — 한 줄에 하나 ──────────────────────
        # **결과가 있으면 접는다.** 이 창은 스크롤이 없다. 목록 12줄을 위에 두면
        # 판정이 22번째 줄로 밀려 화면 밖으로 나간다 — 상태줄만 "아래를 보세요"라고
        # 하고 정작 볼 아래가 없었다
        rows = self.verify_rows()
        if self.verify_result is not None and not self.verify_picking:
            n = len(self.verify_cols)
            out.append("  <mut>" + _esc(msg("screen_verify_picked_fold", n=n)
                                        if n else msg("screen_verify_all_fold"))
                       + "</mut>")
            self.verify_top = -1          # 접혀 있으면 클릭 좌표가 없다
            return out + self._verify_result_lines(len(out))
        out += ["", f"  <head>{_esc(msg('screen_verify_pick_head'))}</head>",
                f"  <mut>{_esc(msg('screen_verify_page', page=self.verify_page + 1, pages=self.verify_pages(), n=len(rows)))}</mut>"]
        self.verify_top = len(out)
        for i, r in enumerate(self.verify_page_rows()):
            cur = "▸" if i == self.verify_row else " "
            mark = "☑" if r["column"] in self.verify_cols else "☐"
            if not r["pair"]:
                pair, style = msg("screen_verify_no_pair"), "warn"
                mark = " "
            elif r["renamed"]:
                pair, style = msg("screen_verify_paired", other=r["pair"]), "tcol"
            else:
                pair, style = msg("screen_verify_same_name"), "mut"
            name = _pad_cells(r["column"], 26)
            # 행 식별자로 확정한 컬럼은 **붉게** — 이 화면에서 확정했는데 아무 표시가
            # 없으면 눌렸는지 알 수 없다
            cell = (f"<err>{_esc(name)}</err>" if r["column"] == key
                    else _esc(name))
            out.append(f"  {cur} {mark} {cell} <{style}>{_esc(pair)}</{style}>")

        return out + self._verify_result_lines(len(out))

    def _verify_result_lines(self, base: int = 0) -> list[str]:
        """대조 결과 — **첫 장은 컬럼마다 같음/다름**, 고르면 그 컬럼만 자세히.

        예전에는 전부 한 덩어리로 쏟아 놓아 "그래서 어느 컬럼이 어떻게 다른가"를
        넘겨 가며 볼 수가 없었다.
        """
        out: list[str] = []
        self.verify_diff_at = {}
        r = self.verify_result
        if r is None:
            return out

        out.append("")
        if r.note:                     # 키가 겹쳐 대조를 못 한 경우 등
            out.append(f"  <warn>{_esc(r.note)}</warn>")
        n_rows_diff = len(r.rows_added) + len(r.rows_removed)
        n_cols_diff = len(r.cols_added) + len(r.cols_removed)
        if r.identical:
            out.append(f"  <okb>{_esc(msg('screen_verify_verdict_same', rows=f'{r.rows_a:,}', cols=len(r.columns)))}</okb>")
        else:
            out.append(f"  <err>{_esc(msg('screen_verify_verdict_diff', rows=n_rows_diff, cells=r.cells_changed, cols=n_cols_diff))}</err>")
        out.append("  " + _esc(msg("screen_verify_rows_line",
                                   common=f"{r.rows_a - len(r.rows_removed):,}",
                                   added=len(r.rows_added), removed=len(r.rows_removed))))
        if n_cols_diff:
            out.append("  " + _esc(msg("screen_verify_cols_line",
                                       only_a=", ".join(r.cols_removed) or "-",
                                       only_b=", ".join(r.cols_added) or "-")))

        summary = self.verify_summary()
        done = [x for x in summary if x["same"] is not None]

        # ── 한 컬럼을 자세히 보는 중 ───────────────────────
        if self.verify_detail >= 0 and self.verify_view:
            col = (done[self.verify_detail]["column"]
                   if self.verify_detail < len(done) else "")
            out += ["", f"  <head>{_esc(msg('screen_verify_detail_of', col=col, i=self.verify_detail + 1, n=len(done)))}</head>"]
            out += [f"  {_esc(x)}" for x in self.verify_view]
            return out

        # ── 첫 장 — 고른 컬럼마다 같음/다름 ────────────────
        n_diff = sum(1 for x in done if not x["same"])
        out += ["", f"  <head>{_esc(msg('screen_verify_sum_head', n=len(done), n_diff=n_diff))}</head>"]
        for i, x in enumerate(summary):
            cur = "▸" if i == self.verify_sum_row else " "
            if x["same"] is None:
                mark, state, style = "○ ", msg("screen_verify_sum_skip"), "warn"
                detail = x["why"][:40]
            elif x["same"]:
                mark, state, style, detail = "✅", msg("screen_verify_sum_same"), "ok", ""
            else:
                c = x["info"]
                mark, state, style = "⛔", msg("screen_verify_sum_diff"), "err"
                detail = msg("screen_verify_bycol_short", n_diff=c["n_diff"],
                             n=f"{c['n']:,}", ratio=f"{c['ratio']:.1%}")
                if c["kind"] == "numeric" and c["max_abs"] is not None:
                    detail += msg("screen_verify_bycol_max", max=f"{c['max_abs']:,.4g}")
            self.verify_diff_at[base + len(out)] = x["column"]
            body = cur + " " + msg("screen_verify_sum_row", mark=mark,
                                   col=_pad_cells(x["column"], 24),
                                   state=state, detail=detail)
            out.append(f"  <sel>{_esc(body)}</sel>" if i == self.verify_sum_row
                       else f"  <{style}>{_esc(body)}</{style}>")
        out.append(f"  <mut>{_esc(msg('screen_verify_sum_hint'))}</mut>")
        return out

    def open_model(self) -> bool:
        """학습한 결과를 믿어도 되는지 — 세트가 만들어진 과정과 라벨 방향을 본다.

        모듈 A(가설검정)와 별개다. 여기서 학습을 돌리지는 않는다.
        """
        if self.session_file is None:
            self.say(msg("screen_open_first"), "err")
            return False
        self.mb_findings, self.mb_code_findings, self.mb_shift = [], [], []
        self.step = STEP_MODEL
        self.mb_notes = self._model_notes()
        return True

    def model_key(self, typed: str = "") -> str:
        """행 키 — 칸이 비어 있으면 확정한 행 식별자를 쓴다 ."""
        from statop.modeling.split_audit import key_from_session

        return (typed or "").strip() or key_from_session(str(self.session_file))

    # ── B1 모델링 구성 — 이 화면에서 만든다 ─────────────────
    # 여기가 없으면 TUI 만 쓰는 사람은 모델링 감사에 **영원히 못 들어간다**:
    # `statop model plan --apply` 를 터미널에서 따로 쳐야만 구성이 생겼다.
    def open_model_plan(self) -> bool:
        from statop.modeling.spec import ROLES, VALIDATIONS, current, questions, tiers
        from statop.session.core import load_session, main_source, replay

        prev = current(str(self.session_file))
        doc = load_session(self.session_file)
        src = main_source(doc)
        types = replay(doc)["semantic_types"].get(src["id"], {}) if src else {}
        cols = [c for c in self.imported]
        none = msg("an_none")
        # 라벨·그룹·시간 후보는 **이미 확정한 의미 타입**에서 먼저 올린다 —
        # 같은 것을 두 번 말하게 하지 않는다
        def first(kind: str) -> list:
            head = [c for c in cols if types.get(c) == kind]
            return head + [c for c in cols if c not in head]

        self.mb_fields = [
            {"key": "question", "label": msg("screen_mb_f_question"),
             "value": prev.question if prev else questions()[0]["id"],
             "choices": [q["id"] for q in questions()],
             "names": {q["id"]: q.get("question") or q.get("name", "") for q in questions()}},
            {"key": "tier", "label": msg("screen_mb_f_tier"),
             "value": prev.tier if prev else tiers()[0]["id"],
             "choices": [t["id"] for t in tiers()],
             "names": {t["id"]: t.get("name", "") for t in tiers()}},
            {"key": "validation", "label": msg("screen_mb_f_validation"),
             "value": prev.validation if prev else "kfold",
             "choices": list(VALIDATIONS)},
            {"key": "k", "label": msg("screen_mb_f_k"),
             "value": (prev.k if prev and prev.k else 5),
             "choices": [2, 3, 4, 5, 10, 20]},
            {"key": "label_column", "label": msg("screen_mb_f_label"),
             "value": (prev.label_column if prev and prev.label_column
                       else (first("label")[0] if cols else none)),
             "choices": first("label") or [none]},
            {"key": "positive_class", "label": msg("screen_mb_f_positive"),
             "value": (prev.positive_class if prev and prev.positive_class else none),
             "choices": [none, *self._mb_label_levels(prev)]},
            {"key": "score_column", "label": msg("screen_mb_f_score"),
             "value": (prev.score_column if prev and prev.score_column else none),
             "choices": [none, *cols]},
            {"key": "group_column", "label": msg("screen_mb_f_group"),
             "value": (prev.group_column if prev and prev.group_column else none),
             "choices": [none, *first("id")]},
            {"key": "time_column", "label": msg("screen_mb_f_time"),
             "value": (prev.time_column if prev and prev.time_column else none),
             "choices": [none, *first("datetime")]},
            {"key": "seed", "label": msg("screen_mb_f_seed"),
             "value": (prev.seed if prev and prev.seed is not None else 42),
             "choices": [0, 1, 42, 2024, 20260929]},
        ]
        self.mb_sets = dict(prev.sets) if prev else {}
        self.mb_row = 0
        self.mb_open = False
        self.mb_problems = []
        self.step = STEP_MODEL_PLAN
        self.say(msg("screen_mb_plan_hint"), "mut")
        assert ROLES
        return True

    def _mb_label_levels(self, prev) -> list:  # noqa: ANN001
        """양성 클래스 후보 — 라벨 컬럼의 실제 수준. 없으면 빈 목록."""
        col = getattr(prev, "label_column", None)
        if not col:
            return []
        try:
            from statop.labels import levels_of

            return [str(x["value"]) for x in levels_of(self.data_path, col)["levels"][:12]]
        except Exception:
            return []

    def mb_plan_spec(self):  # noqa: ANN201
        from statop.modeling.spec import ModelSpec

        v = {f["key"]: f["value"] for f in self.mb_fields}
        none = msg("an_none")
        opt = lambda x: None if x in (none, "", None) else x  # noqa: E731
        return ModelSpec(
            question=v["question"], tier=v["tier"], validation=v["validation"],
            k=int(v["k"]), sets=dict(self.mb_sets),
            label_column=opt(v["label_column"]),
            positive_class=opt(v["positive_class"]),
            score_column=opt(v["score_column"]),
            group_column=opt(v["group_column"]),
            time_column=opt(v["time_column"]),
            seed=int(v["seed"]))

    def mb_add_set(self, text: str) -> bool:
        """`train=/경로/train.csv` — 역할과 경로를 한 번에. 경로 확인은 여기서 한다."""
        from pathlib import Path as _P

        from statop.modeling.spec import ROLES

        t = (text or "").strip()
        if "=" not in t:
            self.say(msg("screen_mb_set_format"), "err")
            return False
        role, path = (x.strip() for x in t.split("=", 1))
        if role not in ROLES:
            self.say(msg("screen_mb_set_format"), "err")
            return False
        if not path:                       # 경로를 비우면 그 역할을 뺀다
            self.mb_sets.pop(role, None)
            self.say(msg("screen_mb_set_removed", role=role), "ok")
            return True
        if not _P(path).exists():
            self.say(msg("screen_mb_set_missing", path=path), "err")
            return False
        self.mb_sets[role] = str(_P(path).resolve())
        self.say(msg("screen_mb_set_added", role=role, path=self.mb_sets[role]), "ok")
        return True

    def mb_apply_plan(self) -> bool:
        """구성 확정 — 문제가 있으면 기록하지 않고 무엇이 빠졌는지 보여준다."""
        from statop.modeling.spec import build, record

        res = build(self.mb_plan_spec())
        self.mb_problems = list(res.problems)
        if res.problems:
            self.say(msg("screen_mb_plan_bad", n=len(res.problems)), "err")
            return False
        record(str(self.session_file), res.spec)
        self.mb_notes = self._model_notes()
        self.step = STEP_MODEL
        self.say(msg("screen_mb_plan_ok"), "ok")
        return True

    def mb_move(self, delta: int) -> None:
        if self.mb_open:
            f = self.mb_fields[self.mb_row]
            self.mb_pick = max(0, min(len(f["choices"]) - 1, self.mb_pick + delta))
        else:
            self.mb_row = max(0, min(len(self.mb_fields) - 1, self.mb_row + delta))

    def mb_toggle_list(self) -> None:
        f = self.mb_fields[self.mb_row]
        self.mb_open = not self.mb_open
        if self.mb_open:
            self.mb_pick = (f["choices"].index(f["value"])
                            if f["value"] in f["choices"] else 0)

    def mb_choose(self) -> None:
        f = self.mb_fields[self.mb_row]
        f["value"] = f["choices"][self.mb_pick]
        self.mb_open = False
        self.mb_problems = []

    def mb_cycle(self, delta: int) -> None:
        f = self.mb_fields[self.mb_row]
        i = f["choices"].index(f["value"]) if f["value"] in f["choices"] else 0
        f["value"] = f["choices"][(i + delta) % len(f["choices"])]
        self.mb_problems = []

    def click_model_plan(self, y: int) -> bool:
        i = y - self.mb_top
        if not (0 <= i < len(self.mb_fields)):
            return False
        self.mb_row = i
        self.mb_toggle_list()
        return True

    def render_model_plan(self) -> list[str]:
        out = [f"  <brand>{_esc(msg('screen_mb_plan_head'))}</brand>", ""]
        self.mb_top = len(out)
        for i, f in enumerate(self.mb_fields):
            cur = "▸" if i == self.mb_row else " "
            shown = f["value"]
            name = (f.get("names") or {}).get(shown, "")
            body = f"{cur} {_esc(_pad_cells(f['label'], 22))} {_esc(str(shown))}"
            if name:
                body += f"  <mut>{_esc(name)}</mut>"
            out.append(f"  <sel>{body}</sel>" if i == self.mb_row else f"  {body}")
            if self.mb_open and i == self.mb_row:
                for j, c in enumerate(f["choices"]):
                    mark = "▸" if j == self.mb_pick else " "
                    extra = (f.get("names") or {}).get(c, "")
                    line = f"      {mark} {_esc(str(c))}"
                    if extra:
                        line += f"  <mut>{_esc(extra)}</mut>"
                    out.append(f"<sel>{line}</sel>" if j == self.mb_pick else line)
        out += ["", f"  <head>{_esc(msg('screen_mb_sets_head', n=len(self.mb_sets)))}</head>"]
        if self.mb_sets:
            for role, path in self.mb_sets.items():
                out.append(f"  {_esc(_pad_cells(role, 10))} {_esc(path)}")
        else:
            out.append(f"  <mut>{_esc(msg('screen_mb_sets_none'))}</mut>")
        for pr in self.mb_problems:
            out.append(f"  <err>{_esc(pr)}</err>")
        return out

    def _model_notes(self) -> list[str]:
        """B1 구성 요약 — 무엇을 전제로 감사하는지 먼저 말한다."""
        from statop.modeling.spec import build, current

        spec = current(str(self.session_file))
        if spec is None:
            self.say(msg("mb_need_spec"), "err")
            return []
        res = build(spec)
        notes = list(res.notes)
        auto = self.model_key()
        notes.append(msg("mb_key_auto", col=auto) if auto else msg("mb_key_none"))
        if res.n_rows:
            notes.append(msg("mb_sets_line", sets=" · ".join(
                msg("mb_rows_cell", role=r, n=n) for r, n in res.n_rows.items())))
        return notes + res.problems

    def run_model_audit(self, key: str = "", expect: str = "") -> bool:
        """세트 비율·손실 → 누수 4종(~) → 라벨 방향 한 번에."""
        from statop.modeling.balance import run_all as balance_all
        from statop.modeling.evaluate import run_all as eval_all
        from statop.modeling.prep import run_all as prep_all
        from statop.modeling.repro import run_all as repro_all
        from statop.modeling.specific import run_all as specific_all
        from statop.modeling.triad import recommend as triad_of
        from statop.modeling.label_audit import label_audit
        from statop.modeling.leak import run_all as leak_all
        from statop.modeling.spec import current
        from statop.modeling.split_audit import run_all as split_all
        from statop.session.core import load_session, main_source

        session = str(self.session_file)
        spec = current(session)
        if spec is None:
            self.say(msg("mb_need_spec"), "err")
            return False
        src = main_source(load_session(session))
        try:
            ratio = ({k.strip(): float(v) for k, v in
                      (x.split("=") for x in expect.split(",") if x.strip())}
                     if expect.strip() else None)
        except ValueError:
            self.say(msg("labels_map_format"), "err")
            return False

        self.mb_shift = []
        key = self.model_key(key)
        self.mb_findings = (
            split_all(spec, src["path"] if src else None, key or None, ratio)
            + leak_all(spec) + label_audit(spec, session)
            # 숨은 불균형의 메타는 **hold 한 컬럼**이다 (요구사항) — 분석에서 뺐지만
            # 라벨을 예측하면 모델이 그쪽을 외운다
            + balance_all(spec, list(self.held)) + prep_all(spec)
            + eval_all(spec, session) + repro_all(spec, session)
            + specific_all(spec) + [triad_of(spec)])
        n = sum(1 for f in self.mb_findings if f.verdict == "fail")
        self.say(msg("mb_screen_done", n=n), "err" if n else "ok")
        return True

    def show_model_shift(self, key: str = "") -> bool:
        """판정이 지목한 컬럼의 정리 전/후 분포를 겹쳐 본다 (MB-C07).

        어느 컬럼인지는 이미 판정이 알고 있다 — 사용자가 다시 칠 일이 아니다.
        """
        from statop.modeling.spec import current
        from statop.modeling.split_audit import shift_view
        from statop.session.core import load_session, main_source

        cols = [c for f in self.mb_findings if f.id == "MB-C07"
                for c in f.numbers.get("kinds", {})]
        if not cols:
            self.say(msg("mb_screen_no_shift"), "err")
            return False
        session = str(self.session_file)
        src = main_source(load_session(session))
        spec = current(session)
        self.mb_shift = []
        for c in cols:
            self.mb_shift += shift_view(spec, src["path"], self.model_key(key), c)["lines"]
        self.say(msg("mb_screen_shift_done", n=len(cols)), "ok")
        return True

    def run_model_code(self, path: str) -> bool:
        """학습 코드를 읽기만 한다 — 실행하지 않는다 ."""
        from statop.modeling.code_audit import audit_code

        if not (path or "").strip():
            self.say(msg("mb_screen_need_code"), "err")
            return False
        self.mb_code_findings = audit_code(path.strip())
        n = sum(1 for f in self.mb_code_findings if f.verdict == "fail")
        self.say(msg("mb_screen_done", n=n), "err" if n else "ok")
        return True

    @staticmethod
    def _finding_lines(findings: list) -> list[str]:
        """판정 줄 — CLI·웹과 같은 기호, 같은 색. Gate 만 빨강, Diag 는 노랑."""
        tag = {"pass": ("ok", "✅"), "skipped": ("mut", "○ ")}
        out = []
        for f in findings:
            gate = f.grade.split("/")[0] == "Gate"
            style, icon = tag.get(f.verdict, ("err" if gate else "warn",
                                              "⛔" if gate else "⚠ "))
            out.append(f"  <{style}>{icon} {_esc(f.id)} {_esc(f.summary)}</{style}>")
            for d in f.detail:
                out.append(f"       <mut>{_esc(d)}</mut>")
            if f.action:
                out.append(f"       <mut>→ {_esc(f.action)}</mut>")
        return out

    def render_model(self) -> list[str]:
        out = [f"  <brand>{_esc(msg('screen_model_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_model_flow'))}</mut>",
               f"  <mut>{_esc(msg('mb_scope_note'))}</mut>", ""]
        for n in self.mb_notes:
            out.append(f"  <mut>· {_esc(n)}</mut>")
        if self.mb_findings:
            out += ["", f"  <head>{_esc(msg('screen_model_audit_head'))}</head>",
                    *self._finding_lines(self.mb_findings)]
        if self.mb_shift:
            out += ["", f"  <head>{_esc(msg('mb_shift_head'))}</head>",
                    *[f"  <mut>{_esc(x)}</mut>" for x in self.mb_shift]]
        if self.mb_code_findings:
            out += ["", f"  <head>{_esc(msg('mb_code_head'))}</head>",
                    *self._finding_lines(self.mb_code_findings)]
        if not self.mb_findings and not self.mb_code_findings:
            out += ["", f"  <mut>{_esc(msg('screen_model_hint'))}</mut>"]
        return out

    # ── 개별 점 보기 / 샘플 제외 ────────────────────────────
    def an_open_plot(self) -> bool:
        from statop.analyze.points import collect

        try:
            self.an_points = collect(str(self.session_file), self.sample_n)
        except ValueError as e:
            self.say(str(e), "err")
            return False
        self.an_plot_row = 0
        self.an_mode = "plot"
        self.say(msg("screen_an_plot_hint", n=len(self.an_points.y)), "mut")
        return True

    def an_plot_rows(self) -> list[dict]:
        """커서가 오르내리는 목록 — 뺄 후보(이상점)가 먼저, 이미 뺀 것이 뒤."""
        p = self.an_points
        if p is None:
            return []
        return ([{"kind": "out", **o} for o in p.outliers]
                + [{"kind": "back", **e} for e in p.excluded])

    def an_plot_move(self, delta: int) -> None:
        rows = self.an_plot_rows()
        if rows:
            self.an_plot_row = max(0, min(len(rows) - 1, self.an_plot_row + delta))

    def an_toggle_point(self) -> bool:
        """커서의 점을 빼거나 되돌린다. 빼려면 사유가 있어야 한다."""
        from statop.analyze.points import exclude, include

        rows = self.an_plot_rows()
        if not rows:
            self.say(msg("screen_an_no_candidates"), "mut")
            return False
        row = rows[self.an_plot_row]
        kc = self.an_points.key_column
        if row["kind"] == "back":
            include(str(self.session_file), kc, row["key"])
            self.say(msg("screen_an_included", key=row["key"]), "ok")
        else:
            if not self.an_reason.strip():
                self.say(msg("screen_an_need_reason"), "err")
                return False
            exclude(str(self.session_file), kc, row["key"], self.an_reason)
            self.say(msg("screen_an_excluded", key=row["key"],
                         reason=self.an_reason.strip()), "ok")
            self.an_reason = ""
        self.an_cands, self.an_result, self.an_hypo = [], [], []   # 값이 바뀌었다
        self.an_strata, self.an_flips = [], []
        return self.an_open_plot()

    def render_plot(self) -> list[str]:
        from statop.render.chart import strip_plot

        p = self.an_points
        if p is None:
            return []
        out = [f"  <brand>{_esc(msg('screen_an_plot_title', y=p.y_label, x=p.x_label))}</brand>",
               f"  <mut>{_esc(msg('screen_an_plot_flow'))}</mut>", ""]
        groups: dict = {}
        if p.x_kind == "category":
            for xv, yv in zip(p.x, p.y):
                groups.setdefault(str(xv), []).append(yv)
        else:
            groups[p.y_label] = list(p.y)
        out += ["  " + _esc(line) for line in strip_plot(groups)]
        out.append("")
        rows = self.an_plot_rows()
        if not rows:
            out.append(f"  <mut>{_esc(msg('screen_an_no_candidates'))}</mut>")
        for i, r in enumerate(rows):
            cur = "▸" if i == self.an_plot_row else " "
            if r["kind"] == "out":
                line = msg("screen_an_point_row", key=r["key"], x=str(r["x"]),
                           y=r["y"], why=r["why"])
                tag = "warn"
            else:
                line = msg("screen_an_excluded_row", key=r["key"],
                           reason=r["reason"] or "-")
                tag = "mut"
            text = f"{cur} {_esc(line)}"
            out.append(f"<sel>{text}</sel>" if i == self.an_plot_row
                       else f"<{tag}>{text}</{tag}>")
        from statop.analyze.points import status

        st = status(str(self.session_file), self.sample_n)
        if st.alternatives:
            out.append("")
            out.append(f"  <head>{_esc(msg('points_alt_head'))}</head>")
            for a in st.alternatives:
                out.append(f"  <ok>· {a['id']} {_esc(a['name'])} — {_esc(a['why'])}</ok>")
        if st.n_excluded:
            key = "points_excl_red" if st.verdict == "red" else "points_excl_yellow"
            tag = "alarm" if st.verdict == "red" else "warn"
            out.append("")
            out.append(f"  <{tag}>{_esc(msg(key, n=st.n_excluded, total=st.n_total, ratio=st.ratio))}</{tag}>")
        out.append("")
        out.append(f"  <mut>{_esc(msg('screen_an_reason_label'))}</mut>")
        return out

    def an_back_to_design(self) -> None:
        """결과 화면 → 설계로. 후보는 그대로라 바로 다른 검정을 돌릴 수 있다."""
        self.an_mode = "design"
        self.an_result, self.an_hypo = [], []
        self.an_points = None
        self.say(msg("screen_an_hint"), "mut")

    def click_analyze(self, y: int) -> bool:
        idx = y - ANALYZE_HEADER_LINES
        total = len(self.an_fields) + len(self.an_cands)
        if not (0 <= idx < total):
            return False
        self.an_row = idx
        return True

    def render_analyze(self) -> str:
        from statop.analyze.spec import questions

        if self.an_mode == "plot":
            return "\n".join(self.render_plot())
        if self.an_mode == "result":
            v = {f["key"]: f["value"] for f in self.an_fields}
            out = [f"  <brand>{_esc(msg('screen_an_result_title'))}</brand>",
                   f"  <mut>{_esc(msg('screen_an_result_spec', q=v.get('question'), y=v.get('y'), x=v.get('group')))}</mut>",
                   ""]
            out += self._render_flip_banner()
            out += self._render_exclusion_block()
            out += ["  " + _esc(x) for x in self.an_result]
            out += self._render_strata()
            for block in (self.an_compat, self.an_assump, self.an_metrics):
                if block:
                    out.append("")
                    out += ["  " + x for x in block]
            out.append("")
            out += ["  " + x for x in self.an_hypo]
            out.append("")
            out.append(f"  <mut>{_esc(msg('screen_an_result_keys'))}</mut>")
            return "\n".join(out)

        out = [f"  <brand>{_esc(msg('screen_an_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_an_flow'))}</mut>"]
        qmap = {q["id"]: q["question"] for q in questions()}
        for i, f in enumerate(self.an_fields):
            cur = "▸" if i == self.an_row else " "
            val = f["value"]
            shown = f"{val} {qmap.get(val, '')}" if f["key"] == "question" else str(val)
            arrows = f"◂ {_esc(shown)} ▸" if i == self.an_row else f"  {_esc(shown)}"
            hint = f"  <mut>({len(f['choices'])}{_esc(msg('screen_an_choices_n'))})</mut>" \
                if i == self.an_row and not self.an_open else ""
            line = f"{cur} {_esc(f['label']):<14.14s} {arrows}"
            out.append((f"<sel>{line}</sel>" if i == self.an_row
                        else f"<mut>{line}</mut>") + hint)
            if i == self.an_row and self.an_open:
                for j, ch in enumerate(f["choices"]):
                    label = f"{ch} {qmap.get(ch, '')}" if f["key"] == "question" else str(ch)
                    row = f"      {'▸' if j == self.an_pick else ' '} {_esc(label)}"
                    out.append(f"<sel>{row}</sel>" if j == self.an_pick
                               else f"<mut>{row}</mut>")
        for r in self.an_repeats:
            out.append(f"  <mut>{_esc(msg('screen_an_repeat_hint', col=r['column'], subjects=r['subjects'], rows=r['rows']))}</mut>")
        gone = [(c, m) for c, m in self.an_missing.items() if m["n"] > 0]
        if gone and self.an_ignore_missing:
            out.append(f"  <warn>{_esc(msg('screen_an_ignoring_missing', used=self.an_n_complete, total=self.an_n_rows))}</warn>")
        elif gone:
            out.append(f"  <warn>{_esc(msg('screen_an_missing_head', kept=self.an_n_complete, total=self.an_n_rows))}</warn>")
            for c, m in gone:
                out.append(f"  <warn>· {_esc(msg('screen_an_missing_col', col=c, n=m['n'], ratio=m['ratio']))}</warn>")
            out.append(f"  <mut>{_esc(msg('screen_an_impute_hint', method=self.an_impute))}</mut>")
        out.append("")
        for pr in self.an_problems:
            out.append(f"  <err>· {_esc(pr)}</err>")
        if self.an_cands:
            out.append(f"  <head>{_esc(msg('screen_an_cands_head', n=len(self.an_cands)))}</head>")
            icon = {"green": "✅", "yellow": "⚠ ", "red": "⛔"}
            tag = {"green": "ok", "yellow": "warn", "red": "err"}
            for j, c in enumerate(self.an_cands):
                i = len(self.an_fields) + j
                cur = "▸" if i == self.an_row else " "
                # 계산기가 없으면 색과 무관하게 회색 ○ — 눌러도 값이 안 나오는 걸 먼저 알린다
                mark = icon[c.color] if c.runnable else "○ "
                style = tag[c.color] if c.runnable else "mut"
                line = f"{cur} {mark} {c.id}  {_esc(c.name):<24.24s} {_esc((c.reasons or [''])[0]):<50.50s}"
                out.append(f"<sel>{line}</sel>" if i == self.an_row
                           else f"<{style}>{line}</{style}>")
        if self.an_result:
            out.append("")
            out += ["  " + _esc(x) for x in self.an_result]
        if self.an_hypo:
            out.append("")
            out.append(f"  <head>{_esc(msg('report_hypo_head'))}</head>")
            out += ["  " + x for x in self.an_hypo]
        return "\n".join(out)

    # ── 라벨 매핑  — ←→ 로 수준별 코드 ────────────────
    def open_labels(self, column: str) -> bool:
        from statop.labels import levels_of
        from statop.session.core import load_session, main_source, replay

        doc = load_session(self.session_file)
        src = main_source(doc)
        current = replay(doc)["label_maps"].get(src["id"], {}).get(column)
        lv = levels_of(self.data_path, column, sample_n=self.sample_n, mapping=current)
        self.label_col = column
        self.label_rows = [{"value": x.value, "n": x.n, "ratio": x.ratio, "code": x.code}
                           for x in lv]
        self.label_row = 0
        self.step = STEP_LABELS
        self.say(msg("screen_labels_hint"), "mut")
        return True

    def move_label(self, delta: int) -> None:
        if self.label_rows:
            self.label_row = max(0, min(len(self.label_rows) - 1,
                                        self.label_row + delta))

    def bump_code(self, delta: int) -> None:
        """←→ 로 커서 수준의 코드를 바꾼다 — 0..수준수-1 범위에서 순환."""
        if not self.label_rows:
            return
        n = len(self.label_rows)
        r = self.label_rows[self.label_row]
        r["code"] = (r["code"] + delta) % n

    def _label_groups(self) -> dict:
        groups: dict[int, list[str]] = {}
        for r in self.label_rows:
            groups.setdefault(r["code"], []).append(r["value"])
        return dict(sorted(groups.items()))

    def save_labels(self) -> bool:
        from statop.session.core import append_op, load_session, main_source, save_session

        if not self.label_rows:
            return False
        mapping = {r["value"]: r["code"] for r in self.label_rows}
        doc = load_session(self.session_file)
        src = main_source(doc)
        append_op(doc, "label_map", source=src["id"], column=self.label_col,
                  mapping=mapping)
        save_session(doc)
        groups = self._label_groups()
        detail = " · ".join(f"{code}={'+'.join(vals)}" for code, vals in groups.items())
        self.say(msg("screen_labels_saved", column=self.label_col, detail=detail), "ok")
        self.step = STEP_TYPES
        if self.type_row < len(self.type_rows) - 1:
            self.type_row += 1
        return True

    def click_labels(self, y: int) -> bool:
        idx = y - LABELS_HEADER_LINES
        if not (0 <= idx < len(self.label_rows)):
            return False
        self.label_row = idx
        return True

    def render_labels(self) -> str:
        out = [f"  <brand>{_esc(msg('screen_labels_title', column=self.label_col, n=len(self.label_rows)))}</brand>",
               f"     <head>{_esc(msg('screen_labels_header'))}</head>"]
        for i, r in enumerate(self.label_rows):
            cur = "▸" if i == self.label_row else " "
            arrows = f"◂ {r['code']} ▸" if i == self.label_row else f"  {r['code']}  "
            body = (f"{cur} {_esc(r['value']):<18.18s} {arrows}  "
                    f"{r['ratio']:>5.1%} ({r['n']:,})")
            out.append(f"<sel>{body}</sel>" if i == self.label_row else f"<mut>{body}</mut>")
        out += [""] * max(0, 3 - len(self.label_rows))
        groups = self._label_groups()
        if len(groups) < len(self.label_rows):
            detail = " · ".join(f"{c}: {'+'.join(v)} (n={sum(x['n'] for x in self.label_rows if x['code'] == c):,})"
                                for c, v in groups.items())
            out += ["", f"  <warn>{_esc(msg('screen_labels_grouped', before=len(self.label_rows), after=len(groups), detail=detail))}</warn>"]
        return "\n".join(out)

    def toggle_dist(self) -> None:
        """커서 컬럼의 분포 축약 그림 (: y눈금 ≤5) — 다시 누르면 접는다."""
        from statop.io.distribution import distributions_of
        from statop.render.chart import boxplot, histogram
        from statop.render.spark import bar as spark_bar

        if not self.type_rows:
            return
        col = self.type_rows[self.type_row]["column"]
        if self.dist_col == col and self.dist_lines:
            self.dist_lines, self.dist_col = [], ""
            return
        # 파일이 아니라 frame() 기준 — 파생 컬럼은 파일에 없다
        d = distributions_of(self.frame(), [col])[0]
        lines = []
        if d["kind"] == "numeric":
            lines += histogram(d["bins"], d["edges"], width=40)
            lines += boxplot(d["quartiles"], (0.0, d["outlier_rate_iqr"]), width=40)
        else:
            for lv in d["levels"][:8]:
                lines.append(f"  {lv['value'][:18]:<18s} {spark_bar(lv['ratio'], 20)} "
                             f"{lv['ratio']:>5.1%} ({lv['n']:,})")
        self.dist_lines, self.dist_col = lines, col
        self.say(msg("screen_types_dist_shown", column=col), "mut")

    SCORE_GRADES = ("green", "yellow", "red", "unset")

    def cycle_score_grade(self, delta: int = 1) -> None:
        i = self.SCORE_GRADES.index(self.score_grade)
        self.score_grade = self.SCORE_GRADES[(i + delta) % len(self.SCORE_GRADES)]
        if self.score_lines:
            self.toggle_scores(force=True)

    def toggle_robust(self, force: bool = False) -> None:
        """강건성 — 지금 낸 결론을 표본·이상치·다른 검정으로 흔들어 본다.

        등급을 적어 두지 않는 이유: 같은 '불균형'이라도 극단이냐 경계선이냐에 따라
        전혀 다른 상황인데 한 글자로는 구분되지 않는다 (작성자 지적). 그래서 이 자료에서
        직접 잰다.
        """
        from statop.analyze.robust import build, verdict

        if self.robust_lines and not force:
            self.robust_lines = []
            return
        self.say(msg("screen_robust_running"), "busy")
        try:
            rep = build(str(self.session_file), draws=200, progress=self.set_progress)
        except ValueError as e:
            self.say(str(e), "err")
            return

        def row(sh) -> str:  # noqa: ANN001
            if sh.failed:
                return f"  <warn>{_esc(msg('robust_line_failed', label=sh.label, why=sh.failed))}</warn>"
            t = msg("robust_line", label=sh.label,
                    eff=sh.effect_name or rep.effect_name, value=sh.effect, p=sh.p)
            if sh.flipped:
                return f"  <err>{_esc(t)}  ← {_esc(msg('robust_flipped_mark'))}</err>"
            return f"  <mut>{_esc(t)}</mut>"

        out = [f"<head>{_esc(msg('robust_head'))}</head>",
               f"<mut>{_esc(msg('robust_base', test=rep.test, name=rep.name, eff=rep.effect_name, value=rep.effect, p=rep.p, n=rep.n_rows))}</mut>",
               "",
               f"<brand>{_esc(msg('robust_boot_head', draws=rep.draws, seed=rep.seed))}</brand>"]
        band = ""
        if rep.boot_q:
            band = msg("robust_band", lo=rep.boot_q["p5"], hi=rep.boot_q["p95"],
                       q25=rep.boot_q["p25"], q75=rep.boot_q["p75"], n=len(rep.boot))
            out.append(f"  <mut>{_esc(band)}</mut>")
        out += ["", f"<brand>{_esc(msg('robust_outlier_head'))}</brand>"]
        out += [row(x) for x in rep.outliers]
        out.append(f"  <mut>{_esc(msg('robust_caveat'))}</mut>")
        out += ["", f"<brand>{_esc(msg('robust_choice_head'))}</brand>"]
        out += [row(x) for x in rep.choices]
        out += ["", f"<head>{_esc(msg('robust_read_head'))}</head>"]
        # ①의 폭은 위에서 이미 보였다 — 두 번 적지 않는다
        out += [f"  <tcol>{_esc(l)}</tcol>" for l in verdict(rep) if l != band]
        self.robust_lines = out
        self.say(msg("screen_robust_shown", n=len(rep.boot), o=len(rep.outliers),
                     c=len(rep.choices)), "ok")

    def move_score_page(self, delta: int) -> None:
        """점수 목록 쪽 넘기기. 목록이 접혀 있으면 할 일이 없다."""
        if not self.score_lines:
            return
        self.score_page += delta
        self.toggle_scores(force=True)

    def toggle_scores(self, force: bool = False) -> None:
        """S167 점수 목록 — 지금 데이터에 대본 4등급. 다시 누르면 접는다."""
        from statop.analyze.scores import catalog

        if self.score_lines and not force:
            self.score_lines = []
            return
        rows = [r for r in catalog(str(self.session_file), self.sample_n)
                if r.verdict == self.score_grade]
        # 112줄이 한 번에 쏟아지면 위쪽이 스크롤 밖으로 사라진다 — 10개씩 넘긴다
        per = 10
        pages = max(1, -(-len(rows) // per))
        self.score_page = min(max(0, self.score_page), pages - 1)
        shown = rows[self.score_page * per:(self.score_page + 1) * per]
        icon = {"green": "✅", "yellow": "⚠ ", "red": "⛔", "unset": "○ "}
        tag = {"green": "ok", "yellow": "warn", "red": "err", "unset": "mut"}
        out = [f"<head>{_esc(msg('scores_head', n=len(rows)))}</head>",
               f"<mut>{_esc(msg('scores_grade_' + self.score_grade))} "
               f"— {_esc(msg('screen_scores_cycle'))}</mut>"]
        for r in shown:
            t = tag[r.verdict]
            # 한 줄에 판정·이름·무엇을 재는 묶음까지 — 축을 다 펴면 10개도 안 들어간다
            out.append(f"<{t}>{icon[r.verdict]} {r.id:<11s} {_esc(r.name)}</{t}>"
                       f"  <mut>{_esc(r.purpose_name)}</mut>")
        foot = msg("list_page", page=self.score_page + 1, pages=pages, n=len(rows))
        out.append(f"<head>{_esc(foot)} — {_esc(msg('screen_scores_page_keys'))}</head>")
        out.append(f"<mut>{_esc(msg('scores_shaken_note'))}</mut>")
        out.append(f"<mut>{_esc(msg('scores_unset_meaning'))}</mut>")
        self.score_lines = out
        self.say(msg("screen_scores_shown", n=len(rows)), "mut")

    def toggle_represent(self, force: bool = False) -> None:
        """Q-12 부분표집 곡선  — 몇 행이면 전체를 닮는가. 다시 누르면 접는다.

        답이 p 값이 아니라 n 이라, 검정 화면이 아니라 컬럼 화면에 붙는다.
        """
        from statop.analyze.represent import build, statement

        if self.represent_lines and not force:
            self.represent_lines = []
            return
        self.say(msg("screen_represent_running"), "busy")
        rep = build(str(self.session_file), progress=self.set_progress)
        out = [f"<head>{_esc(msg('represent_head', total=rep.total_rows))}</head>",
               f"<mut>{_esc(msg('represent_repeats', r=rep.repeats, seed=rep.seed))}</mut>"]
        if rep.skipped_ids:
            skipped = msg("represent_skipped_ids", cols=", ".join(rep.skipped_ids))
            out.append(f"<mut>{_esc(skipped)}</mut>")
        for c in rep.curves:
            head_line = msg("represent_col_head", col=c.column, kind=c.kind,
                            metric=c.metric_name)
            out.append(f"<brand>{_esc(head_line)}</brand>")
            out.append("  " + " ".join(f"{p.n}:{p.mean:.3f}" for p in c.points))
            if c.enough_n is None:
                line = msg("represent_col_never", th=rep.threshold)
                out.append(f"  <err>{_esc(line)}</err>")
            else:
                line = msg("represent_col_enough", n=c.enough_n, th=rep.threshold)
                out.append(f"  <ok>{_esc(line)}</ok>")
        if rep.enough_n is not None:
            pct = round(100 * rep.enough_n / rep.total_rows, 1)
            out.append(f"<okb>{_esc(msg('represent_enough', n=rep.enough_n, th=rep.threshold, pct=pct))}</okb>")
            out.append(f"<mut>{_esc(msg('represent_limiting', cols=', '.join(rep.limiting)))}</mut>")
            head, how = statement(rep)
            out.append(f"<head>{_esc(head)}</head>")
            out.append(f"<mut>{_esc(how)}</mut>")
            out += self._render_spread(rep.enough_n, rep.threshold)
        elif rep.limiting:
            out.append(f"<err>{_esc(msg('represent_never', cols=', '.join(rep.limiting), th=rep.threshold))}</err>")
        out.append(f"<tcol>{_esc(msg('represent_threshold_convention', th=rep.threshold))}</tcol>")
        self.represent_lines = out
        self.say(msg("screen_represent_shown", n=len(rep.curves)), "mut")

    def _render_spread(self, n: int, threshold: float) -> list:
        """고른 n 에서 다시 뽑을 때마다 나온 거리들 .

        "0.05 는 관행"이라고만 하면 어디에 선을 그을지 알 수 없다. 우연만으로
        얼마가 나오는지 보여야 그보다 위에 선을 그을 수 있다.
        """
        from statop.analyze.represent import spread

        sps = spread(str(self.session_file), n, draws=200)
        if not sps:
            return []
        out = ["", f"<head>{_esc(msg('represent_spread_head', n=n, draws=sps[0].draws))}</head>",
               f"<mut>{_esc(msg('represent_spread_why'))}</mut>"]
        top = max(1, max(c for sp in sps for _, _, c in sp.bins))
        for sp in sps:
            line = msg("represent_spread_q", col=sp.column, metric=sp.metric_name,
                       **sp.q)
            out.append(f"<brand>{_esc(line)}</brand>")
            for lo, hi, c in sp.bins:
                bar = "█" * round(24 * c / top)
                out.append(f"  <mut>{lo:.4f}~{hi:.4f} {bar} {c}</mut>")
            sug = msg("represent_spread_suggest", col=sp.column, p95=sp.q["p95"],
                      th=threshold)
            out.append(f"<tcol>{_esc(sug)}</tcol>")
        return out

    def move_type(self, delta: int) -> None:
        if self.type_rows:
            self.type_row = max(0, min(len(self.type_rows) - 1, self.type_row + delta))

    def click_types(self, y: int) -> bool:
        idx = y - TYPES_HEADER_LINES
        if not (0 <= idx < len(self.type_rows)):
            return False
        self.type_row = idx
        return True

    def render_types(self) -> str:
        from statop.semantic import shape_label

        n_ok = sum(1 for r in self.type_rows if r["confirmed"])
        out = [f"  <brand>{_esc(msg('screen_types_title', ok=n_ok, total=len(self.type_rows)))}</brand>",
               f"     <head>{_esc(msg('screen_types_header'))}</head>"]
        for i, r in enumerate(self.type_rows):
            cur = "▸" if i == self.type_row else " "
            typ = r["order"][r["idx"]]
            if r["confirmed"]:
                state, tag = "✔", "ok"
                shown = r["confirmed"]
            else:
                state = "→" if r["needs_confirm"] else " "
                tag = "warn" if r["needs_confirm"] else "mut"
                shown = typ
            inferred = "" if typ in r["evidence"] or r["confirmed"] else _esc(msg("screen_types_not_inferred"))
            body = (f"{cur} {state} {_esc(r['column']):<22.22s} {_esc(shown):<18.18s} "
                    f"{_esc(shape_label(r['shape'])):<10.10s} {inferred}")
            out.append(f"<sel>{body}</sel>" if i == self.type_row else f"<{tag}>{body}</{tag}>")
        out += [""] * max(0, 4 - len(self.type_rows))

        # 커서 행의 상세 — 후보 전체를 한눈에 (넘겨보지 않아도 보이게)
        if self.type_rows:
            r = self.type_rows[self.type_row]
            typ = r["order"][r["idx"]]
            out.append("")
            inferred = [t for t in r["order"] if t in r["evidence"]]
            outside = [t for t in r["order"] if t not in r["evidence"]]
            cand_line = "  ".join(
                (f"<sel>▸{_esc(t)}</sel>" if t == typ else f"<ok>{_esc(t)}</ok>")
                for t in inferred)
            out.append("  " + msg("screen_types_cands") + " " + cand_line)
            if outside:
                shown = "  ".join(
                    (f"<sel>▸{_esc(t)}</sel>" if t == typ else _esc(t))
                    for t in outside)
                out.append(f"  <mut>{_esc(msg('screen_types_outside'))} {shown}</mut>")
            for why in r["evidence"].get(typ, [])[:3]:
                out.append(f"  <mut>· {_esc(why)}</mut>")
            if r["reason"] and not r["confirmed"]:
                out.append(f"  <warn>→ {_esc(r['reason'])}</warn>")
            for cf in r["conflicts"][:2]:
                out.append(f"  <warn>⚠ {_esc(cf)}</warn>")
        if self.score_lines:
            out += ["", *[f"  {x}" for x in self.score_lines]]
        if self.represent_lines:
            out += ["", *[f"  {x}" for x in self.represent_lines]]
        if self.dist_lines:
            out.append("")
            out.append(f"  <head>{_esc(self.dist_col)}</head>")
            out += ["  " + _esc(x) for x in self.dist_lines]
        return "\n".join(out)

    # ── 파생 컬럼 ────────────────────────────────────────────
    def open_derive(self) -> bool:
        """수식 화면 — 가져온 컬럼이 있어야 수식이 의미가 있다."""
        if not self.imported:
            self.say(msg("screen_derive_need_columns"), "err")
            return False
        self.step = STEP_DERIVE
        self.say(msg("screen_derive_hint"), "mut")
        return True

    def frame(self):  # noqa: ANN201
        """세션 샘플 + **파생 컬럼 재계산** — 파생도 추론·분포·2차 수식의 대상이다."""
        from statop.derive.service import apply_ops, session_frame

        doc, src, df = session_frame(str(self.session_file), self.sample_n)
        return apply_ops(df, doc, src["id"])

    def preview_formula(self, expr: str, eps: float | None = None) -> bool:
        """미리보기만 — 기록하지 않는다. 실패 이유는 화면에 그대로 남긴다."""
        from statop.derive.parser import FormulaError
        from statop.derive.service import prepare

        self.derive_expr = (expr or "").strip()
        self.derive_eps = eps
        self.derive_prep = None
        self.derive_error = ""
        if not self.derive_expr:
            self.derive_error = msg("screen_derive_empty")
            return False
        try:
            self.derive_prep = prepare(self.frame(), self.derive_expr, eps=eps)
        except (FormulaError, ValueError, KeyError) as e:
            self.derive_error = str(e)
            self.say(str(e), "err")
            return False
        self.say(msg("screen_derive_previewed"), "ok")
        return True

    def eps_candidates(self) -> list[float]:
        adv = getattr(self.derive_prep, "eps_advice", None)
        return list(getattr(adv, "candidates", []) or [])

    def needs_eps(self) -> bool:
        return bool(getattr(getattr(self.derive_prep, "parsed", None), "uses_eps", False))

    def commit_formula(self, name: str) -> bool:
        """파생 컬럼 기록 — 수식과 eps가 세션에 남아야 재현이 된다."""
        from statop.derive.service import commit, session_frame

        name = (name or "").strip()
        if not name:
            self.derive_error = msg("screen_derive_need_name")
            self.say(self.derive_error, "err")
            return False
        if self.derive_prep is None and not self.preview_formula(self.derive_expr,
                                                                 self.derive_eps):
            return False
        doc, src, df = session_frame(str(self.session_file), self.sample_n)
        try:
            commit(doc, src["id"], df, self.derive_prep, name, self.derive_eps)
        except ValueError as e:
            self.derive_error = str(e)
            self.say(str(e), "err")
            return False
        self.refresh()
        self.step = STEP_WORKSPACE
        self.say(msg("derive_committed", name=name,
                     type=self.derive_prep.result_type), "ok")
        return True

    def formula_columns(self) -> list[str]:
        """수식에 쓸 수 있는 컬럼 — 가져온 컬럼 **과 이미 만든 파생 컬럼**.

        파생을 빼면 방금 만든 컬럼으로 다음 식을 못 만든다. 식 자체는 되는데 키패드에만
        안 보이는 상태라, 쓸 수 있는 줄 모른 채 지나간다.
        """
        from statop.session.core import load_session, main_source, replay

        cols = list(self.imported)
        if self.session_file is None:
            return cols
        doc = load_session(self.session_file)
        src = main_source(doc)
        if src is None:
            return cols
        cols += [d["name"] for d in replay(doc)["derived"]
                 if d.get("source") == src["id"] and d["name"] not in cols]
        return cols

    def _pad_col_rows(self) -> list[dict]:
        """컬럼 키는 **하나도 빼지 않는다** — 줄이 넘치면 다음 줄로 접는다.

        앞의 10개만 보이면 열한 번째 컬럼은 클릭으로 고를 길이 아예 없다 (실제로 났다).
        """
        cols = self.formula_columns()
        rows, cur, used = [], [], 0
        for c in cols:
            w = _cwidth(c) + 2                      # 대괄호 2칸
            if cur and used + w > self.pad_wrap_at:
                rows.append(cur)
                cur, used = [], 0
            cur.append({"text": c, "insert": c, "back": 0})
            used += w
        if cur:
            rows.append(cur)
        # 접힌 줄은 라벨을 비운다 — 같은 이름이 여러 줄에 반복되면 다른 묶음처럼 보인다
        return [{"label": "pad_cols" if i == 0 else "", "keys": ks}
                for i, ks in enumerate(rows)]

    pad_wrap_at: int = 64            # 컬럼 키 한 줄의 칸 수

    # 클릭·방향키만으로 식을 만든다 — 함수 이름을 외워 타자칠 필요가 없게.
    # 목록은 parser 의 화이트리스트에서 온다 (웹 키패드와 같은 원본)
    def pad_rows(self) -> list[dict]:
        from statop.derive.parser import COLUMN_FUNCS, PAIR_FUNCS, ROW_FUNCS, SET_FUNCS

        def fn(names) -> list[dict]:  # noqa: ANN001
            # 키에는 이름만 보인다 — 괄호는 넣을 때 알아서 감싸진다
            return [{"text": n, "insert": f"{n}()", "back": 1} for n in names]

        binning = ["floor_to", "round_to", "ceil_to", "bin", "round", "trunc"]
        rows = [
            *self._pad_col_rows(),
            {"label": "pad_ops",
             "keys": [{"text": o, "insert": f" {o} ", "back": 0}
                      for o in ("+", "-", "*", "/", "**")]
                     + [{"text": "( )", "insert": "()", "back": 1},
                        {"text": "eps", "insert": "eps", "back": 0},
                        {"text": ",", "insert": ", ", "back": 0}]},
            {"label": "pad_bin", "keys": fn(binning)},
            {"label": "pad_row_func",
             "keys": fn(sorted(ROW_FUNCS - set(binning)))},
            {"label": "pad_scalar_func", "keys": fn(sorted(COLUMN_FUNCS))},
            {"label": "pad_set_func",
             "keys": fn(sorted(SET_FUNCS | PAIR_FUNCS))},
        ]
        return [r for r in rows if r["keys"]]

    def pad_move(self, drow: int = 0, dcol: int = 0) -> None:
        rows = self.pad_rows()
        if not rows:
            return
        self.pad_row = max(0, min(len(rows) - 1, self.pad_row + drow))
        n = len(rows[self.pad_row]["keys"])
        self.pad_col = max(0, min(n - 1, self.pad_col + dcol))

    def pad_pick(self) -> dict | None:
        rows = self.pad_rows()
        if not rows:
            return None
        row = rows[min(self.pad_row, len(rows) - 1)]
        return row["keys"][min(self.pad_col, len(row["keys"]) - 1)]

    def click_pad(self, y: int, x: int) -> dict | None:
        """키패드 줄을 클릭하면 그 자리의 키를 고른다."""
        rows = self.pad_rows()
        idx = y - self.pad_top
        if not (0 <= idx < len(rows)):
            return None
        self.pad_row = idx
        # **글자 수가 아니라 터미널 칸 수로 센다.** 라벨이 한글이면 한 글자가 두 칸이라
        # 글자 수로 재면 줄마다 다르게 어긋나고, 클릭이 옆 키를 고르거나 빗나간다
        cursor = self.pad_label_width + 2      # 들여쓰기 2칸 + 라벨 폭
        for j, k in enumerate(rows[idx]["keys"]):
            width = _cwidth(k["text"]) + 2     # 대괄호 2칸
            if cursor <= x < cursor + width:
                self.pad_col = j
                return k
            cursor += width
        return None

    pad_top: int = 0                 # 키패드 첫 줄의 화면 y — 클릭 좌표 변환용
    pad_label_width: int = 12

    def render_pad(self) -> list[str]:
        out = [f"  <head>{_esc(msg('pad_head'))}</head>"]
        for i, row in enumerate(self.pad_rows()):
            cells = []
            for j, k in enumerate(row["keys"]):
                on = i == self.pad_row and j == self.pad_col
                t = _esc(k["text"])
                cells.append(f"<sel>[{t}]</sel>" if on else f"<mut>[{t}]</mut>")
            label = msg(row["label"]) if row["label"] else ""
            out.append(f"  {_esc(_pad_cells(label, self.pad_label_width))}"
                       + "".join(cells))
        out.append(f"  <mut>{_esc(msg('pad_hint'))}</mut>")
        return out

    def render_derive(self) -> str:
        # 한 줄에 다 못 적으므로 앞쪽만 적되 **몇 개 중 몇 개인지**를 밝힌다.
        # 그냥 8개만 적으면 나머지는 못 쓰는 줄 안다 (아래 키패드에는 전부 있다)
        cols = self.formula_columns()
        shown = ", ".join(cols[:8]) + (f" … ({len(cols)})" if len(cols) > 8 else "")
        out = ["", f"  <brand>{_esc(msg('screen_derive_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_derive_cols', cols=shown))}</mut>",
               ""]
        self.pad_top = len(out) + 1
        out += self.render_pad()
        out.append("")
        if self.derive_error:
            out.append(f"  <err>{_esc(self.derive_error)}</err>")
            out.append("")
        # 오류가 났다고 **다음에 뭘 누르는지**까지 지우지 않는다. 미리보기가 없을 뿐,
        # 키패드도 안내도 그대로 있어야 한다 (사라지면 화면이 고장난 것처럼 보인다)
        p = self.derive_prep
        if p is None:
            out.append(f"  <mut>{_esc(msg('screen_derive_examples'))}</mut>")
            out.append("")
            out.append(f"  <mut>{_esc(msg('screen_derive_flow'))}</mut>")
            return "\n".join(out)

        # 토큰 색 — 웹과 같은 역할 구분 (F-04). 보라는 컬럼 전체를 한 수로 줄인다
        tag = {"column": "tcol", "row_func": "trow", "column_scalar_func": "tscalar",
               "set_func": "tset", "pair_func": "tset", "eps": "teps"}
        body = "".join(f"<{tag[t['role']]}>{_esc(t['text'])}</{tag[t['role']]}>"
                       if t["role"] in tag else _esc(t["text"]) for t in p.tokens)
        out.append(f"  {body}")
        out.append(f"  <mut>{_esc(msg('screen_derive_legend'))}</mut>")
        pv = p.preview
        out.append("  " + msg("derive_preview_stats", n=pv["n"], n_finite=pv["n_finite"],
                              n_nan=pv["n_nan"], n_inf=pv["n_inf"]))
        if pv["n_finite"]:
            out.append("  " + msg("derive_preview_range", min=pv["min"], mean=pv["mean"],
                                  max=pv["max"]))
        if pv.get("distinct_before") is not None:
            out.append("  <warn>" + _esc(msg("derive_lossy", before=pv["distinct_before"],
                                             after=pv["distinct_after"])) + "</warn>")
            out.append("  <mut>" + _esc(msg("derive_levels", levels=", ".join(
                f"{v:g}" for v in pv["levels"]))) + "</mut>")
        out.append(f"  <mut>{_esc(msg('screen_derive_result_type', type=p.result_type))}</mut>")
        if self.needs_eps():
            cands = " · ".join(f"{c:g}" for c in self.eps_candidates())
            chosen = f"{self.derive_eps:g}" if self.derive_eps else "-"
            out.append(f"  <warn>{_esc(msg('screen_derive_eps', chosen=chosen, cands=cands))}</warn>")
        if getattr(p, "alternative", ""):
            out.append(f"  <tcol>{_esc(p.alternative)}</tcol>")
        out.append(f"  <ok>{_esc(msg('screen_derive_ready'))}</ok>")
        return "\n".join(out)

    def back_to_columns(self) -> None:
        if self.view is None:
            self.load_columns()
        else:
            self.step = STEP_COLUMNS

    def open_save(self) -> None:
        """저장 화면 — 어디에 저장할지 사용자가 정한다. 기본 저장소로 조용히 넣지 않는다."""
        from statop.store import sessions_dir

        self.step = STEP_SAVE
        if not self.save_dir:
            self.save_dir = str(sessions_dir())
        self.say(msg("screen_save_hint"), "mut")

    def save_target(self) -> Path:
        """저장될 파일의 전체 경로 — 누르기 전에 그대로 보여준다."""
        from statop.session.core import auto_name, load_session
        from statop.store import sessions_dir

        doc = load_session(self.session_file)
        return Path(self.save_dir or sessions_dir()) / auto_name(doc)

    def save_session_as(self, out_dir: str | None = None,
                        overwrite: bool = False) -> bool:
        from statop.session.core import load_session, save_as, save_session

        where = (out_dir if out_dir is not None else self.save_dir) or None
        if where and not Path(where).is_dir():
            self.say(msg("screen_save_no_dir", path=where), "err")
            return False
        doc = load_session(self.session_file)
        try:
            target = save_as(doc, out_dir=where, overwrite=overwrite)
        except FileExistsError as e:
            # 덮어쓰기는 별도 클릭이어야 한다  — 단순 저장이 조용히 덮지 않게
            self.say(f"{e} — {msg('screen_save_overwrite_hint')}", "err")
            return False
        doc["saved_at"] = target.name
        save_session(doc)
        self.saved_name = target.name
        self.step = STEP_WORKSPACE
        self.say(msg("session_saved", path=target), "ok")
        return True

    # ── 렌더 (문자열만 만든다) ───────────────────────────────
    def render_header(self) -> str:
        line = f"  <title>STATOP</title>  <mut>{_esc(msg('screen_subtitle'))}</mut>"
        if self.session_id:
            line += f"  <mut>· {_esc(self.session_id)}</mut>"
        return line

    def render_open(self) -> str:
        """두 갈래를 뚜렷이 나눈다 — 처음이면 위쪽, 이어서 하려면 아래쪽."""
        if self.loading:
            # 눌린 뒤 화면이 그대로면 눌렸는지 알 수 없다. 본문을 통째로 바꾼다
            filled = int(self.load_pct * 30)
            bar = "▮" * filled + "▯" * (30 - filled)
            eta = self.eta_text()
            stage = f"  <mut>[{_esc(self.load_stage)}]</mut>" if self.load_stage else ""
            line = f"{bar}  {self.load_pct:4.0%}" + (f"  ·  {eta}" if eta else "") + stage
            return ("\n\n  <busy>" + _esc(msg("screen_reading_big", name=self.loading))
                    + "</busy>\n\n  " + line
                    + "\n\n  <mut>" + _esc(msg("screen_reading_note")) + "</mut>")
        files = self.saved_files()
        out = ["",
               f"  <brand>{_esc(msg('screen_open_data_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_open_data_desc'))}</mut>", ""]
        out += [f"  <brand>{_esc(msg('screen_open_session_title'))}</brand>",
                f"  <mut>{_esc(msg('screen_open_session_desc'))}</mut>"]
        if files:
            out.append(f"  <mut>{_esc(msg('screen_open_session_count', n=len(files), name=files[0].name))}</mut>")
        else:
            out.append(f"  <mut>{_esc(msg('screen_open_session_none'))}</mut>")
        return "\n".join(out)

    def render_sessions(self) -> str:
        files = self.saved_files()
        out = [f"  <brand>{_esc(msg('screen_sessions_title', n=len(files)))}</brand>",
               f"     <head>{_esc(msg('screen_sessions_header'))}</head>"]
        import datetime

        for i, f in enumerate(files):
            cur = "▸" if i == self.session_row else " "
            when = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")
            body = f"{cur} {_esc(f.name):<52.52s} {when}"
            out.append(f"<sel>{body}</sel>" if i == self.session_row else f"<mut>{body}</mut>")
        out += ["", f"  <mut>{_esc(msg('screen_sessions_dir', path=self.sessions_dir_text()))}</mut>"]
        return "\n".join(out)

    def sessions_dir_text(self) -> str:
        from statop.store import sessions_dir

        return str(sessions_dir())

    def render_save(self) -> str:
        out = ["", f"  <brand>{_esc(msg('screen_save_title'))}</brand>",
               f"  <mut>{_esc(msg('screen_save_dir_label'))}</mut>", ""]
        try:
            target = self.save_target()
            exists = target.exists()
            out.append(f"  <head>{_esc(msg('screen_save_target', path=target))}</head>")
            if exists:
                out.append(f"  <warn>{_esc(msg('screen_save_exists_warn'))}</warn>")
        except Exception:
            pass
        return "\n".join(out)

    def render_table(self) -> str:
        v = self.view
        if v is None:
            return ""
        rows = v.page_items()
        out = [f"  <brand>{_esc(v.title)}</brand>  "
               f"<mut>{msg('view_col_count', n=len(v.visible()))} · "
               f"{msg('view_page', page=v.offset // PAGE + 1, pages=v.n_pages())}</mut>"]
        if v.warnings:
            out.append(f"  <warn>{_esc(v.warnings[0])}</warn>")
        out.append(f"     <head>{_esc(msg('view_header'))}</head>")
        for i, r in enumerate(rows):
            mark = "☑" if r["column"] in v.picked else "☐"
            cur = "▸" if i == v.cursor else " "
            line = (f"{r['column']:<24.24s} {r['dtype']:<12.12s} "
                    f"{r['missing_rate'] * 100:>6.1f}% {r['n_unique']:>9,d}")
            tag = r["missing_level"] if r["missing_level"] != "ok" else "mut"
            body = f"{cur} {mark} {FLAG[r['missing_level']]}{_esc(line)}"
            if i == self.flash_row:
                out.append(f"<flash>{body}</flash>")       # 방금 누른 행
            elif i == v.cursor:
                out.append(f"<sel>{body}</sel>")
            else:
                out.append(f"<{tag}>{body}</{tag}>")
        if not rows:
            out.append(f"  <mut>{_esc(msg('view_empty'))}</mut>")
        # 빈 줄로 한 쪽 크기를 채운다. 이게 없으면 표 아래 빈 공간을 클릭했을 때
        # 마지막 행이 눌린다 (빈 곳에는 '내용'이 없어 클릭이 접힌다)
        out += [""] * max(0, PAGE - len(rows))
        return "\n".join(out)

    def origin_note(self) -> str:
        """가공 전 파일 위치 — 경로가 드러나는 화면마다 같은 문구로 ."""
        if not self.data_path:
            return ""
        from statop.export import origin_line

        return origin_line(self.data_path)

    def render_workspace(self) -> str:
        n_analysis = len(self.imported) - len(self.held)
        out = [f"  <brand>{_esc(msg('screen_ws_title', n=len(self.imported)))}</brand>"
               f"  <mut>{msg('hold_state', n_analysis=n_analysis, n_held=len(self.held))}</mut>",
               *([f"  <mut>{_esc(self.origin_note())}</mut>"] if self.origin_note()
                 else []),
               f"     <head>{_esc(msg('screen_role_header'))}</head>"]
        for i, c in enumerate(self.imported):
            cur = "▸" if i == self.row else " "
            role = self.col_roles.get(c) or ("hold" if c in self.held else "")
            held = f"{role:<5.5s}" if role else "     "
            body = f"{cur} {held} {_esc(c):<30.30s}"
            if i == self.flash_row:
                out.append(f"<flash>{body}</flash>")
            elif i == self.row:
                out.append(f"<sel>{body}</sel>")
            else:
                out.append(f"<mut>{body}</mut>")
        out += [""] * max(0, 6 - len(self.imported))   # 빈 곳 클릭이 접히지 않게
        if self.robust_lines:
            out += ["", *[f"  {x}" for x in self.robust_lines]]
        out += ["", *self.render_progress()]
        out += ["", f"  <head>{_esc(msg('screen_next_head'))}</head>"]
        sess = self.session_file or ""
        for key in ("types", "compat", "guard", "model"):
            out.append(f"    <mut>{_esc(msg('screen_next_' + key, session=sess))}</mut>")
        return "\n".join(out)

    def progress_steps(self) -> list[dict]:
        """지금 어디까지 왔는지 — 뒤로 갔다 와도 무엇을 마쳤는지 알 수 있어야 한다.

        순서는 **파생 컬럼 → 타입 확정 → 분석**이다. 타입이 확정돼야 적합성 판정이
        걸리고, 그래야 분석 후보가 제대로 나온다.
        """
        from statop.session.core import load_session, main_source, replay

        steps = [{"key": "import", "done": bool(self.imported),
                  "detail": msg("prog_import_detail", n=len(self.imported))}]
        if self.session_file is None or not Path(self.session_file).exists():
            return steps
        doc = load_session(self.session_file)
        src = main_source(doc)
        st = replay(doc)
        sid = src["id"] if src else ""
        derived = [d for d in st["derived"] if d.get("source") == sid]
        types = st["semantic_types"].get(sid, {})
        cols = [c for c in self.imported if c not in self.held]
        need = [*cols, *[d["name"] for d in derived]]
        done_types = [c for c in need if c in types]
        steps.append({"key": "derive", "done": bool(derived), "optional": True,
                      "detail": msg("prog_derive_detail", n=len(derived))})
        steps.append({"key": "types", "done": bool(need) and len(done_types) == len(need),
                      "detail": msg("prog_types_detail", done=len(done_types),
                                    total=len(need),
                                    left=", ".join(c for c in need
                                                   if c not in types)[:60] or "-")})
        steps.append({"key": "analyze", "done": bool(st["test_results"]),
                      "detail": msg("prog_analyze_detail", n=len(st["test_results"]))})
        return steps

    def render_progress(self) -> list[str]:
        out = [f"  <head>{_esc(msg('prog_head'))}</head>"]
        for i, s_ in enumerate(self.progress_steps(), 1):
            mark = "✔" if s_["done"] else ("·" if s_.get("optional") else "□")
            tag = "ok" if s_["done"] else ("mut" if s_.get("optional") else "warn")
            line = f"  {mark} {i}. {msg('prog_' + s_['key'])} — {s_['detail']}"
            out.append(f"<{tag}>{_esc(line)}</{tag}>")
        return out

    def mouse_note(self) -> str:
        """마우스가 이 터미널에서 동작하는지 — 안 되면 키보드로 안내한다."""
        from statop.shell.columns_view import ClickableControl

        return msg("screen_mouse_ok" if ClickableControl.mouse_events_seen
                   else "screen_mouse_none")

    def focus_label(self) -> str:
        """지금 초점이 어디 있는지 사람 말로. Tab 을 잘못 눌러도 길을 잃지 않게."""
        if self.focus.startswith("btn:"):
            return msg("screen_focus_button", name=self.focus[4:])
        try:
            # 이름을 목록으로 관리하면 위젯을 늘릴 때마다 목록을 같이 고쳐야 한다 —
            # 실제로 그걸 빠뜨려 "알 수 없음"이 떴다
            return msg("screen_focus_" + self.focus)
        except KeyError:
            return msg("screen_focus_unknown")

    def render_web(self) -> str:
        """웹 주소는 제 줄에 통째로 — 상태줄에 섞이면 잘려서 복사가 안 된다."""
        if not self.web_url:
            return ""
        import getpass

        return (f"  <urlhead>{_esc(msg('screen_web_url_head'))}</urlhead>\n"
                f"  <url>{_esc(self.web_url)}</url>\n"
                f"  <mut>{_esc(msg('screen_web_tunnel', port=self.web_port, user=getpass.getuser()))}</mut>")

    def render_status(self) -> str:
        keys = {STEP_OPEN: "screen_keys_open", STEP_COLUMNS: "screen_keys_columns",
                STEP_WORKSPACE: "screen_keys_workspace",
                STEP_SESSIONS: "screen_keys_sessions",
                STEP_SAVE: "screen_keys_save",
                STEP_DERIVE: "screen_keys_derive",
                STEP_TYPES: "screen_keys_types",
                STEP_LABELS: "screen_keys_labels",
                STEP_ANALYZE: ("screen_keys_plot" if self.an_mode == "plot"
                               else "screen_keys_analyze"),
                STEP_TRANSPOSE: "screen_keys_simple",
                STEP_SAVECOPY: "screen_keys_simple",
                STEP_VERIFY: "screen_keys_simple",
                STEP_MODEL: "screen_keys_simple",
                STEP_MODEL_PLAN: "screen_mb_plan_hint",
                STEP_TMP: "screen_keys_simple",
                STEP_FIND: "screen_keys_find"}[self.step]
        return (f"  <focus>{_esc(msg('screen_focus_here', where=self.focus_label()))}</focus>"
                f"   <mut>{_esc(self.mouse_note())}</mut>\n"
                f"  <{self.status_kind}>{_esc(self.status)}</{self.status_kind}>\n"
                f"  <mut>{_esc(msg(keys))}</mut>")

    def import_label(self) -> str:
        n = len(self.view.picked) if self.view else 0
        return msg("screen_import_btn", n=n)


# ── prompt_toolkit 껍데기 ────────────────────────────────────
def run_screen() -> None:
    """전체화면을 띄운다. 판단은 전부 Screen에 있고 여기서는 그리기와 키만 연결한다."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.filters import Condition, to_filter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import (ConditionalContainer, HSplit, Layout, VSplit,
                                       Window)
    from prompt_toolkit.layout.dimension import D
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Button, TextArea

    from statop.shell.columns_view import ClickableControl

    style = Style.from_dict({
        "head": "#5b6166", "sel": "reverse", "high": "#b23a17 bold", "mid": "#7a4a12",
        "mut": "#8a9096", "brand": "#35566b bold", "warn": "#7a4a12", "ok": "#0b6e6e",
        "err": "#b23a17 bold", "title": "#35566b bold", "focus": "#35566b bold",
        # 누른 버튼 — 터미널 테마와 무관하게 확실히 보이게 흰 바탕·검은 글씨로 못박는다
        "button.pressed": "bg:#ffffff #000000 bold",
        "button.pressed button.arrow": "bg:#ffffff #000000 bold",
        "button.pressed button.text": "bg:#ffffff #000000 bold",
        "rule": "#3a4046", "urlhead": "#5b6166", "url": "#35566b bold underline",
        "busy": "bg:#ffffff #000000 bold",
        "flash": "bg:#ffffff #000000 bold",
        "okb": "#0b6e6e bold", "err": "#b23a17",
        # 결론이 뒤집히는 경고는 반전으로 — 빨간 글씨만으로는 지나친다
        "alarm": "bg:#b23a17 #ffffff bold",
        "tcol": "#35566b bold", "trow": "#0b6e6e", "tscalar": "#7a3d8f underline",
        "tset": "#1f5fa8", "teps": "#7a4a12 bold",
        # 터미널 배경색을 모르므로 흰 배경을 깔지 않는다 — 테두리와 반전으로만 구분한다
        "button": "noinherit #9aa3aa",
        "button.arrow": "noinherit #9aa3aa",
        "button.text": "noinherit",
        "button.focused": "reverse bold",
        "button.focused button.arrow": "reverse bold",
        "button.focused button.text": "reverse bold",
        "textbox": "noinherit",
        "textbox.focused": "underline",
    })

    def mk_button(text: str, handler, width: int = 0, tag: str = ""):  # noqa: ANN001, ANN202
        """`[ 열기 ]` 모양 — 괄호 안은 글자 앞뒤 **한 칸씩**으로 통일한다.

        width는 무시하고 글자에서 계산한다. 숫자를 손으로 넣으면 글자가 바뀔 때
        여백이 들쭉날쭉해진다 (한글은 한 글자가 두 칸이라 더 그렇다).
        """
        from prompt_toolkit.utils import get_cwidth

        tag = tag or text
        b = Button(text, handler=press(tag, handler),
                   width=get_cwidth(text) + 4,          # 글자 + 좌우 1칸 + 대괄호 2칸
                   left_symbol="[", right_symbol="]")
        # 기본은 남는 폭만큼 늘어난다 — 그러면 버튼 줄이 화면을 넘겨 줄바꿈된다
        b.window.dont_extend_width = to_filter(True)
        b.window.style = _button_style(b)
        b.statop_tag = tag
        return b

    def press(tag: str, handler):  # noqa: ANN001, ANN202
        """누른 버튼을 잠깐 노랗게 — 눌렸는지 모르는 상태를 만들지 않는다."""
        import asyncio

        def wrapped() -> None:
            sc.pressed = tag
            app.invalidate()

            async def fade() -> None:
                await asyncio.sleep(0.6)     # 눈에 보일 만큼은 남아 있어야 한다
                if sc.pressed == tag:
                    sc.pressed = ""
                    app.invalidate()

            app.create_background_task(fade())
            guard(handler)()

        return wrapped

    def guard(fn):  # noqa: ANN001, ANN202
        """화면 핸들러의 예외는 상태줄로 — 이벤트 루프로 새면 화면이 깨지고
        'Press ENTER' 지옥이 된다. 삼키지 않는다: 이유가 그대로 붉게 남는다."""
        import functools

        @functools.wraps(fn)
        def safe(*a, **k):  # noqa: ANN002, ANN003, ANN202
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001 — 화면은 어떤 예외에도 살아남아야 한다
                sc.say(f"{type(e).__name__}: {e}", "err")
                app.invalidate()
                return None

        return safe

    def _button_style(btn):  # noqa: ANN001, ANN202
        def style() -> str:
            if sc.pressed and sc.pressed == getattr(btn, "statop_tag", None):
                return "class:button.pressed"
            if app.layout.has_focus(btn):
                return "class:button.focused"
            return "class:button"

        return style

    sc = Screen()
    path_input = TextArea(height=1, multiline=False, wrap_lines=False, prompt="▏ ",
                          focus_on_click=True, style="class:textbox")
    search_input = TextArea(height=1, multiline=False, wrap_lines=False, prompt="▏ ",
                            focus_on_click=True, style="class:textbox")
    savedir_input = TextArea(height=1, multiline=False, wrap_lines=False, prompt="▏ ",
                             focus_on_click=True, style="class:textbox")
    expr_input = TextArea(height=1, multiline=False, wrap_lines=False, prompt=msg("screen_prompt_expr"),
                          focus_on_click=True, style="class:textbox")
    newname_input = TextArea(height=1, multiline=False, wrap_lines=False, prompt=msg("screen_prompt_name"),
                             focus_on_click=True, style="class:textbox")

    def refresh_label() -> None:
        """글자가 바뀌면 폭도 같이 — 안 그러면 '선택 10개'에서 글자가 잘린다."""
        from prompt_toolkit.utils import get_cwidth

        import_button.text = sc.import_label()
        import_button.window.width = get_cwidth(import_button.text) + 4

    def do_open() -> None:
        """누르면 **즉시** 반응을 보여주고, 파일 읽기는 뒤에서 돈다.

        큰 파일은 프로파일링에 몇 초가 걸린다. 그동안 화면이 그대로면 눌린 건지
        멈춘 건지 알 수 없다.
        """
        import asyncio

        import time
        from pathlib import Path as _P

        raw = path_input.text.strip().strip('"').strip("'")
        sc.loading = _P(raw).name if raw else "?"
        sc.load_pct = 0.0
        sc.load_started = time.monotonic()
        sc.say(msg("screen_reading"), "mut")
        app.invalidate()

        last = [0.0]

        def on_progress(frac: float) -> None:
            """읽기 스레드에서 온다 — 0.1초에 한 번만 다시 그린다 (그리기가 더 비싸지지 않게)."""
            sc.set_progress(frac)
            now = time.monotonic()
            if now - last[0] >= 0.1 or frac >= 1.0:
                last[0] = now
                app.invalidate()          # prompt_toolkit 의 invalidate 는 스레드 안전

        sc.on_progress = on_progress

        async def work() -> None:
            loop = asyncio.get_running_loop()
            try:
                ok = await loop.run_in_executor(None, sc.open_path, path_input.text)
            finally:
                sc.loading = ""
                sc.on_progress = None
            if ok:
                refresh_label()
                app.layout.focus(table_window)
            app.invalidate()

        app.create_background_task(work())

    def do_import() -> None:
        if sc.import_picked():
            app.layout.focus(ws_window)

    def do_more() -> None:
        sc.back_to_columns()
        app.layout.focus(table_window)

    def do_sessions() -> None:
        if sc.open_sessions():
            app.layout.focus(sessions_window)

    def do_pick_session() -> None:
        if sc.load_saved(sc.session_row):
            app.layout.focus(ws_window)

    def do_open_save() -> None:
        sc.open_save()
        savedir_input.text = sc.save_dir
        app.layout.focus(savedir_input)

    def do_save(overwrite: bool = False) -> None:
        sc.save_dir = savedir_input.text.strip()
        if sc.save_session_as(overwrite=overwrite):
            app.layout.focus(ws_window)

    def do_analyze() -> None:
        if sc.open_analyze():
            app.layout.focus(analyze_window)

    def do_bg(fn) -> None:   # noqa: ANN001
        """계획 확인·실행·대치는 수 초 걸릴 수 있다 — 화면을 막지 않는다."""
        import asyncio

        sc.say(msg("screen_reading"), "mut")
        app.invalidate()

        async def work() -> None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, guard(fn))
            app.invalidate()

        app.create_background_task(work())

    def do_an_plan() -> None:
        do_bg(sc.an_plan)

    def do_an_run() -> None:
        do_bg(sc.an_run)

    def do_types() -> None:
        """추론은 오래 걸릴 수 있다 — 즉시 반응 + 진행률 (기본 패턴)."""
        import asyncio
        import time

        if not sc.imported:
            sc.say(msg("screen_types_need_columns"), "err")
            return
        sc.loading = msg("screen_types_inferring")
        sc.load_pct = 0.0
        sc.load_started = time.monotonic()
        app.invalidate()
        last = [0.0]

        def on_progress(frac: float) -> None:
            sc.set_progress(frac)
            now = time.monotonic()
            if now - last[0] >= 0.1 or frac >= 1.0:
                last[0] = now
                app.invalidate()

        sc.on_progress = on_progress

        async def work() -> None:
            loop = asyncio.get_running_loop()
            try:
                ok = await loop.run_in_executor(None, sc.open_types)
            finally:
                sc.loading = ""
                sc.on_progress = None
            if ok:
                app.layout.focus(types_window)
            app.invalidate()

        app.create_background_task(work())

    def do_derive() -> None:
        if sc.open_derive():
            app.layout.focus(expr_input)

    def do_preview() -> None:
        sc.preview_formula(expr_input.text, sc.derive_eps)

    def _step_eps(direction: int) -> None:
        """후보 목록에서 한 칸 이동 — 위로는 추천값(허용 최대)까지만.

        후보는 큰 값부터: [추천, 추천/10, …]. direction=+1 이 '낮추기'.
        """
        cands = sc.eps_candidates()
        if not cands:
            return
        cur = sc.derive_eps
        if cur is None or cur not in cands:
            idx = 0
        else:
            idx = max(0, min(len(cands) - 1, cands.index(cur) + direction))
        sc.preview_formula(expr_input.text, cands[idx])

    def do_lower_eps() -> None:
        _step_eps(1)

    def do_raise_eps() -> None:
        _step_eps(-1)

    def do_make() -> None:
        """입력칸의 지금 수식으로 만든다 — [미리보기]를 먼저 눌렀는지에 의존하지 않는다.

        수식을 바꾸고 미리보기 없이 [만들기]를 누르면 옛 수식이 기록되는 사고를 막는다.
        """
        text = expr_input.text.strip()
        if text != sc.derive_expr or sc.derive_prep is None:
            if not sc.preview_formula(text, sc.derive_eps):
                return
        if sc.commit_formula(newname_input.text):
            expr_input.text = ""
            newname_input.text = ""
            app.layout.focus(ws_window)

    def do_back() -> None:
        sc.step = STEP_WORKSPACE if sc.imported else STEP_OPEN
        app.layout.focus(ws_window if sc.imported else path_input)

    open_button = mk_button(msg("screen_open_btn"), do_open, 0, msg("screen_open_btn"))
    load_button = mk_button(msg("screen_sessions_btn"), do_sessions, 0, msg("screen_sessions_btn"))
    import_button = mk_button(sc.import_label(), do_import, 0, msg("screen_import_btn", n=0))
    prev_button = mk_button(msg("screen_prev_btn"), lambda: sc.page(-1), 0, msg("screen_prev_btn"))
    next_button = mk_button(msg("screen_next_btn"), lambda: sc.page(1), 0, msg("screen_next_btn"))
    sort_miss = mk_button(msg("screen_sort_missing"), lambda: sc.set_sort("missing"), 0, msg("screen_sort_missing"))
    sort_uniq = mk_button(msg("screen_sort_unique"), lambda: sc.set_sort("unique"), 0, msg("screen_sort_unique"))
    sort_name = mk_button(msg("screen_sort_name"), lambda: sc.set_sort("name"), 0, msg("screen_sort_name"))
    search_button = mk_button(msg("screen_search_btn"),
                              lambda: sc.search(search_input.text), 10,
                              msg("screen_search_btn"))
    more_button = mk_button(msg("screen_more_btn"), do_more, 0, msg("screen_more_btn"))
    sessions_button = mk_button(msg("screen_sessions_btn"), do_sessions, 0, msg("screen_sessions_btn"))
    pick_button = mk_button(msg("screen_load_btn"), do_pick_session, 0, msg("screen_load_btn"))
    back_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    dosave_button = mk_button(msg("screen_save_btn2"), lambda: do_save(False), 0, msg("screen_save_btn2"))
    overwrite_button = mk_button(msg("screen_overwrite_btn"), lambda: do_save(True), 0, msg("screen_overwrite_btn"))
    back2_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    derive_button = mk_button(msg("screen_derive_btn"), do_derive, 0, msg("screen_derive_btn"))
    preview_button = mk_button(msg("screen_derive_preview_btn"), do_preview, 0,
                               msg("screen_derive_preview_btn"))
    epsup_button = mk_button(msg("screen_derive_eps_up_btn"), do_raise_eps, 0,
                             msg("screen_derive_eps_up_btn"))
    epsdown_button = mk_button(msg("screen_derive_eps_btn"), do_lower_eps, 0,
                               msg("screen_derive_eps_btn"))
    make_button = mk_button(msg("screen_derive_make_btn"), do_make, 0,
                            msg("screen_derive_make_btn"))
    back3_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))

    def click_verify_col(y: int) -> bool:
        """컬럼 줄을 클릭하면 **그 컬럼**을 켜고 끈다.

        예전에는 한 줄에 컬럼을 전부 붙여 놓고 y 를 안 봐서, 클릭이 전체 토글로
        동작했다 — 하나씩 고르는 것이 아예 불가능했다.

        결과의 **컬럼별 줄**을 누르면 그 컬럼을 A/B 로 겹쳐 본다.
        """
        col = sc.verify_diff_at.get(y)
        if col:
            rows = sc.verify_summary()
            sc.verify_sum_row = next((i for i, x in enumerate(rows)
                                      if x["column"] == col), 0)
            do_bg(sc.open_verify_detail)
            return True
        rows = sc.verify_page_rows()
        i = y - sc.verify_top
        if not (0 <= i < len(rows)):
            return False
        sc.verify_row = i
        if rows[i]["pair"]:
            sc.toggle_verify_col(rows[i]["column"])
        return True

    def click_pad_key(y: int) -> bool:
        """키패드 줄 클릭 — 줄만 고르고, 그 줄의 현재 키를 넣는다."""
        rows = sc.pad_rows()
        idx = y - sc.pad_top
        if not (0 <= idx < len(rows)):
            return False
        sc.pad_row = idx
        sc.pad_col = min(sc.pad_col, len(rows[idx]["keys"]) - 1)
        insert_key()
        return True

    def insert_key(key: dict | None = None) -> None:
        """키패드에서 고른 조각을 수식 칸의 커서 자리에 끼워 넣는다."""
        k = key or sc.pad_pick()
        if not k:
            return
        buf = expr_input.buffer
        at = buf.cursor_position
        text = buf.text[:at] + k["insert"] + buf.text[at:]
        buf.text = text
        buf.cursor_position = at + len(k["insert"]) - k["back"]
        sc.derive_expr = text
        app.layout.focus(expr_input)

    pad_button = mk_button(msg("pad_btn"), insert_key, 0, msg("pad_btn"))
    types_button = mk_button(msg("screen_types_btn"), do_types, 0, msg("screen_types_btn"))
    cycle_button = mk_button(msg("screen_types_cycle_btn"), lambda: sc.cycle_type(1), 0,
                             msg("screen_types_cycle_btn"))
    def do_confirm_type() -> None:
        sc.confirm_type()
        if sc.step == STEP_LABELS:
            app.layout.focus(labels_window)

    confirm_button = mk_button(msg("screen_types_confirm_btn"), do_confirm_type, 0,
                               msg("screen_types_confirm_btn"))
    distv_button = mk_button(msg("screen_types_dist_btn"),
                             lambda: do_bg(sc.toggle_dist), 0,
                             msg("screen_types_dist_btn"))
    unconfirm_button = mk_button(msg("screen_types_unconfirm_btn"),
                                 sc.unconfirm_type, 0,
                                 msg("screen_types_unconfirm_btn"))
    tp_button = mk_button(msg("screen_tp_btn"), lambda: do_bg(sc.open_transpose), 0,
                          msg("screen_tp_btn"))
    tp_run_button = mk_button(msg("screen_tp_run_btn"), lambda: do_bg(sc.do_transpose),
                              0, msg("screen_tp_run_btn"))
    def do_copy_open() -> None:
        sc.open_savecopy()
        app.layout.focus(copy_input)

    copy_button = mk_button(msg("screen_copy_btn"), do_copy_open, 0,
                            msg("screen_copy_btn"))
    copy_save_button = mk_button(msg("screen_copy_save_btn"),
                                 lambda: do_bg(lambda: sc.do_savecopy(copy_input.text)),
                                 0, msg("screen_copy_save_btn"))
    copy_main_button = mk_button(
        msg("screen_copy_main_btn"),
        lambda: setattr(sc, "copy_use_main", not sc.copy_use_main), 0,
        msg("screen_copy_main_btn"))
    def do_verify_open() -> None:
        """들어가면 바로 칠 수 있어야 한다 — 커서를 경로 칸에 놓는다."""
        if sc.open_verify():
            app.layout.focus(verify_input)

    tmp_window = Window(ClickableControl(
        lambda: HTML("\n".join(sc.render_tmp())), focusable=True, show_cursor=False,
        on_click=lambda y: guard(sc.click_tmp)(y),
        on_scroll=lambda d: guard(sc.move_tmp)(d)))

    def do_tmp_open() -> None:
        if sc.open_tmp():
            app.layout.focus(tmp_window)

    tmp_button = mk_button(msg("screen_tmp_btn"), do_tmp_open, 0, msg("screen_tmp_btn"))

    find_window = Window(ClickableControl(
        lambda: HTML("\n".join(sc.render_find())), focusable=True, show_cursor=False,
        on_click=lambda y: guard(sc.click_find)(y),
        on_scroll=lambda d: guard(sc.move_find)(d)))

    def do_find_open() -> None:
        if sc.open_find():
            app.layout.focus(find_window)

    find_button = mk_button(msg("screen_find_btn"), do_find_open, 0,
                            msg("screen_find_btn"))
    find_run_button = mk_button(msg("screen_find_run_btn"),
                                lambda: do_bg(sc.find_pick), 0,
                                msg("screen_find_run_btn"))
    find_goal_button = mk_button(msg("screen_find_goal_btn"), sc.find_goal, 0,
                                 msg("screen_find_goal_btn"))
    find_adj_button = mk_button(msg("screen_find_adj_btn"), sc.cycle_find_adjust, 0,
                                msg("screen_find_adj_btn"))
    find_rule_button = mk_button(msg("screen_find_rule_btn"), sc.toggle_find_rule, 0,
                                 msg("screen_find_rule_btn"))
    find_plot_button = mk_button(msg("screen_find_plot_btn"),
                                 lambda: do_bg(sc.toggle_find_plot), 0,
                                 msg("screen_find_plot_btn"))
    find_color_button = mk_button(msg("screen_find_color_btn"), sc.find_color_cycle, 0,
                                  msg("screen_find_color_btn"))
    find_support_button = mk_button(msg("screen_find_support_btn"),
                                    lambda: do_bg(lambda: sc.find_role("support")), 0,
                                    msg("screen_find_support_btn"))
    find_guard_button = mk_button(msg("screen_find_guard_btn"),
                                  lambda: do_bg(lambda: sc.find_role("guardrail")), 0,
                                  msg("screen_find_guard_btn"))
    find_aim_button = mk_button(msg("screen_find_aim_btn"),
                                lambda: do_bg(lambda: sc.set_find_target(find_aim_input.text)),
                                0, msg("screen_find_aim_btn"))
    back11_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    tmp_del_button = mk_button(msg("screen_tmp_del_btn"),
                               lambda: do_bg(sc.delete_tmp), 0,
                               msg("screen_tmp_del_btn"))
    back10_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    verify_button = mk_button(msg("screen_verify_btn"), do_verify_open, 0,
                              msg("screen_verify_btn"))
    verify_open_button = mk_button(
        msg("screen_verify_open_btn"),
        lambda: do_bg(lambda: sc.set_verify_path(verify_input.text)), 0,
        msg("screen_verify_open_btn"))
    verify_run_button = mk_button(msg("screen_verify_run_btn"),
                                  lambda: do_bg(sc.do_verify), 0,
                                  msg("screen_verify_run_btn"))
    verify_key_button = mk_button(msg("screen_verify_key_btn"), sc.cycle_verify_key, 0,
                                  msg("screen_verify_key_btn"))
    verify_id_button = mk_button(msg("screen_verify_id_btn"),
                                 lambda: do_bg(sc.confirm_verify_id), 0,
                                 msg("screen_verify_id_btn"))
    verify_pair_button = mk_button(msg("screen_verify_pair_btn"), sc.pair_verify_col, 0,
                                   msg("screen_verify_pair_btn"))
    verify_all_button = mk_button(msg("screen_verify_all_btn"), sc.toggle_verify_all, 0,
                                  msg("screen_verify_all_btn"))

    def do_verify_pick() -> None:
        """컬럼 고르기로 돌아간다 — 결과는 버리지 않는다. 고치고 다시 대조하면 된다."""
        sc.verify_picking = True
        sc.verify_detail = -1
        sc.verify_view = []

    def do_verify_detail() -> None:
        do_bg(sc.open_verify_detail)

    def do_verify_back_sum() -> None:
        sc.back_to_summary()

    verify_pick_button = mk_button(msg("screen_verify_pick_btn"), do_verify_pick, 0,
                                   msg("screen_verify_pick_btn"))
    verify_detail_button = mk_button(msg("screen_verify_detail_btn"), do_verify_detail,
                                     0, msg("screen_verify_detail_btn"))
    verify_sum_button = mk_button(msg("screen_verify_back_sum"), do_verify_back_sum, 0,
                                  msg("screen_verify_back_sum"))
    verify_rerun_button = mk_button(msg("screen_verify_rerun"),
                                    lambda: do_bg(sc.do_verify), 0,
                                    msg("screen_verify_rerun"))
    verify_rprev_button = mk_button(msg("screen_prev_btn"),
                                    lambda: do_bg(lambda: sc.step_verify_detail(-1)), 0,
                                    "verify_rprev")
    verify_rnext_button = mk_button(msg("screen_next_btn"),
                                    lambda: do_bg(lambda: sc.step_verify_detail(1)), 0,
                                    "verify_rnext")
    verify_prev_button = mk_button(msg("screen_prev_btn"),
                                   lambda: sc.move_verify_page(-1), 0, "verify_prev")
    verify_next_button = mk_button(msg("screen_next_btn"),
                                   lambda: sc.move_verify_page(1), 0, "verify_next")

    def do_verify_set() -> None:
        """경로를 받고 나면 커서를 [대조] 로 — 다음에 누를 것이 하나뿐이다.

        경로 확인은 파일을 여는 게 아니라 존재 확인이라 바로 끝난다 (뒤로 안 뺀다).
        """
        if sc.set_verify_path(verify_input.text):
            app.layout.focus(verify_run_button)
    back7_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    # **입력칸은 전부 같은 조건이어야 한다** — focus_on_click 과 textbox 스타일이 없으면
    # 칸이 칸으로 보이지도 않고 클릭해도 커서가 안 간다. 그 상태에서 경로를 치면
    # 글자 하나하나가 단축키로 먹혀 엉뚱한 화면으로 튄다 (실제로 그랬다)
    copy_input = TextArea(height=1, multiline=False, wrap_lines=False,
                          prompt=msg("screen_copy_prompt_dir"),
                          focus_on_click=True, style="class:textbox")
    mb_plan_window = Window(ClickableControl(
        lambda: HTML("\n".join(sc.render_model_plan())),
        on_click=lambda y: guard(sc.click_model_plan)(y),
        on_scroll=lambda d: guard(sc.mb_move)(d)))
    verify_input = TextArea(height=1, multiline=False, wrap_lines=False,
                            prompt=msg("screen_verify_prompt_file"),
                            focus_on_click=True, style="class:textbox")
    # 목표 검정력 — 80% 는 관습일 뿐이라 쳐서 옮길 자리가 있어야 한다
    find_aim_input = TextArea(height=1, multiline=False, wrap_lines=False,
                              prompt=msg("screen_find_aim_prompt"),
                              focus_on_click=True, style="class:textbox")
    # 모델링 감사 (모듈 B) — 키·기대비율은 선택이다. 없으면 그 검사만 건너뛴다
    mb_key_input = TextArea(height=1, multiline=False, wrap_lines=False,
                            prompt=msg("screen_model_prompt_key"),
                            focus_on_click=True, style="class:textbox")
    mb_expect_input = TextArea(height=1, multiline=False, wrap_lines=False,
                               prompt=msg("screen_model_prompt_expect"),
                               focus_on_click=True, style="class:textbox")
    mb_code_input = TextArea(height=1, multiline=False, wrap_lines=False,
                             prompt=msg("screen_model_prompt_code"),
                             focus_on_click=True, style="class:textbox")
    def do_model_open() -> None:
        if sc.open_model():
            app.layout.focus(mb_key_input)

    model_button = mk_button(msg("screen_model_btn"), do_model_open, 0,
                             msg("screen_model_btn"))
    mb_set_input = TextArea(height=1, multiline=False, wrap_lines=False,
                            prompt=msg("screen_mb_prompt_set"),
                            focus_on_click=True, style="class:textbox")

    def do_model_plan() -> None:
        """구성 화면 — 감사에 들어가기 전에 무엇을 학습했는지 먼저 말한다."""
        if sc.open_model_plan():
            app.layout.focus(mb_plan_window)

    def do_mb_add_set() -> None:
        if sc.mb_add_set(mb_set_input.text):
            mb_set_input.text = ""

    mb_plan_button = mk_button(msg("screen_mb_plan_btn"), do_model_plan, 0,
                               msg("screen_mb_plan_btn"))
    mb_apply_button = mk_button(msg("screen_mb_apply_btn"),
                                lambda: do_bg(sc.mb_apply_plan), 0,
                                msg("screen_mb_apply_btn"))
    mb_set_button = mk_button(msg("screen_verify_open_btn"), do_mb_add_set, 0,
                              "mb_set")
    back9_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    model_run_button = mk_button(
        msg("screen_model_run_btn"),
        lambda: do_bg(lambda: sc.run_model_audit(mb_key_input.text,
                                                 mb_expect_input.text)), 0,
        msg("screen_model_run_btn"))
    model_shift_button = mk_button(
        msg("screen_model_shift_btn"),
        lambda: do_bg(lambda: sc.show_model_shift(mb_key_input.text)), 0,
        msg("screen_model_shift_btn"))
    model_code_button = mk_button(
        msg("screen_model_code_btn"),
        lambda: do_bg(lambda: sc.run_model_code(mb_code_input.text)), 0,
        msg("screen_model_code_btn"))
    back8_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    scores_button = mk_button(msg("screen_scores_btn"),
                              lambda: do_bg(sc.toggle_scores), 0,
                              msg("screen_scores_btn"))
    represent_button = mk_button(msg("screen_represent_btn"),
                                 lambda: do_bg(sc.toggle_represent), 0,
                                 msg("screen_represent_btn"))
    robust_button = mk_button(msg("screen_robust_btn"),
                              lambda: do_bg(sc.toggle_robust), 0,
                              msg("screen_robust_btn"))
    back4_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    analyze_button = mk_button(msg("screen_an_btn"), do_analyze, 0, msg("screen_an_btn"))
    anplan_button = mk_button(msg("screen_an_plan_btn"), do_an_plan, 0,
                              msg("screen_an_plan_btn"))
    anrun_button = mk_button(msg("screen_an_run_btn"), do_an_run, 0,
                             msg("screen_an_run_btn"))
    back5_button = mk_button(msg("screen_back_btn"), do_back, 0, msg("screen_back_btn"))
    anlist_button = mk_button(msg("screen_an_list_btn"), sc.an_toggle_list, 0,
                              msg("screen_an_list_btn"))
    impute_button = mk_button(msg("screen_an_impute_btn"), lambda: do_bg(sc.an_do_impute),
                              0, msg("screen_an_impute_btn"))
    ignore_na_button = mk_button(msg("screen_an_ignore_btn"), sc.an_ignore_missing_rows,
                                 0, msg("screen_an_ignore_btn"))
    plot_button = mk_button(msg("screen_an_plot_btn"), lambda: do_bg(sc.an_open_plot),
                            0, msg("screen_an_plot_btn"))
    exclude_button = mk_button(msg("screen_an_exclude_btn"),
                               lambda: do_bg(sc.an_toggle_point), 0,
                               msg("screen_an_exclude_btn"))
    back6_button = mk_button(msg("screen_back_btn"), lambda: sc.an_back_to_design(), 0,
                             msg("screen_back_btn"))
    reason_input = TextArea(multiline=False, height=1, wrap_lines=False,
                            prompt=msg("screen_an_prompt_reason"),
                            focus_on_click=True, style="class:textbox",
                            accept_handler=lambda b: (setattr(sc, "an_reason", b.text)
                                                      or False))
    redesign_button = mk_button(msg("screen_an_redesign_btn"), sc.an_back_to_design, 0,
                                msg("screen_an_redesign_btn"))
    lsave_button = mk_button(msg("screen_labels_save_btn"), sc.save_labels, 0,
                             msg("screen_labels_save_btn"))

    def do_skip_labels() -> None:
        sc.step = STEP_TYPES
        if sc.type_row < len(sc.type_rows) - 1:
            sc.type_row += 1
        app.layout.focus(types_window)

    lskip_button = mk_button(msg("screen_labels_skip_btn"), do_skip_labels, 0,
                             msg("screen_labels_skip_btn"))

    def do_web() -> None:
        """어느 화면에서든 웹으로 넘어갈 수 있어야 한다 — 서버 기동은 뒤에서 돈다."""
        import asyncio

        sc.say(msg("screen_web_starting"), "mut")
        app.invalidate()

        async def work() -> None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sc.open_in_web)
            app.invalidate()

        app.create_background_task(work())

    web_buttons = [mk_button(msg("screen_web_btn"), do_web, 0, msg("screen_web_btn"))
                   for _ in range(4)]
    refresh_buttons = [mk_button(msg("screen_refresh_btn"), sc.refresh, 0, msg("screen_refresh_btn")) for _ in range(3)]
    share_buttons = [mk_button(msg("screen_share_btn"), sc.share_state, 0,
                               msg("screen_share_btn")) for _ in range(2)]
    save_button = mk_button(msg("screen_save_btn"), do_open_save, 0, msg("screen_save_btn"))

    def flash(row: int) -> None:
        """방금 누른 행을 잠깐 반전 — 버튼만 반응하고 행은 조용하면 눌렸는지 모른다."""
        import asyncio

        sc.flash_row = row
        app.invalidate()

        async def fade() -> None:
            await asyncio.sleep(0.6)
            if sc.flash_row == row:
                sc.flash_row = -1
                app.invalidate()

        app.create_background_task(fade())

    def click_table(y: int) -> bool:
        hit = guard(sc.click_table)(y)
        if hit:
            refresh_label()
            flash(sc.view.cursor)
        return hit

    def click_ws(y: int) -> bool:
        hit = guard(sc.click_workspace)(y)
        if hit:
            flash(sc.row)
        return hit

    WHEEL = 3           # 휠 한 칸에 세 줄 — 한 줄씩이면 긴 목록에서 손이 지친다

    def wheel(move):  # noqa: ANN001, ANN202
        """휠을 그 화면의 **위아래 이동**으로 바꾼다. 화면마다 움직이는 것이 다르다."""
        def run(d: int) -> None:
            for _ in range(WHEEL):
                move(d)
        return guard(run)

    def scroll_table(d: int) -> None:
        """컬럼 표는 커서가 끝에 닿으면 쪽을 넘긴다 — 키보드 ↑↓ 와 같은 동작."""
        for _ in range(WHEEL):
            sc.move(d)

    table_window = Window(ClickableControl(lambda: HTML(sc.render_table()), focusable=True,
                                           show_cursor=False, on_click=click_table,
                                           on_scroll=guard(scroll_table)))
    ws_window = Window(ClickableControl(lambda: HTML(sc.render_workspace()),
                                        focusable=True, show_cursor=False,
                                        on_click=click_ws,
                                        on_scroll=wheel(lambda d: setattr(
                                            sc, "row",
                                            max(0, min(len(sc.imported) - 1, sc.row + d))))))

    def click_session(y: int) -> bool:
        hit = guard(sc.click_sessions)(y)
        if hit:
            app.layout.focus(ws_window)
        return hit

    types_window = Window(ClickableControl(lambda: HTML(sc.render_types()),
                                           focusable=True, show_cursor=False,
                                           on_click=guard(sc.click_types),
                                           on_scroll=wheel(sc.move_type)))
    analyze_window = Window(ClickableControl(lambda: HTML(sc.render_analyze()),
                                             focusable=True, show_cursor=False,
                                             on_click=guard(sc.click_analyze),
                                             on_scroll=wheel(sc.an_move)))
    labels_window = Window(ClickableControl(lambda: HTML(sc.render_labels()),
                                            focusable=True, show_cursor=False,
                                            on_click=guard(sc.click_labels),
                                            on_scroll=wheel(sc.move_label)))

    sessions_window = Window(ClickableControl(lambda: HTML(sc.render_sessions()),
                                              focusable=True, show_cursor=False,
                                              on_click=click_session,
                                              on_scroll=wheel(sc.move_session)))

    def screen_buttons():  # noqa: ANN202
        """지금 화면의 버튼 — 번호키 순서와 안내 문구가 어긋나지 않게 한 곳에서 만든다."""
        if sc.step == STEP_OPEN:
            return [open_button, load_button, tmp_button, web_buttons[0]]
        if sc.step == STEP_TMP:
            return [tmp_del_button, back10_button]
        if sc.step == STEP_FIND:
            return [find_run_button, find_plot_button, find_color_button,
                    find_rule_button, find_goal_button, find_adj_button,
                    find_support_button, find_guard_button,
                    find_aim_button, find_support_button, find_guard_button, back11_button]
        if sc.step == STEP_COLUMNS:
            return [sort_miss, sort_uniq, sort_name, search_button, prev_button,
                    next_button, import_button, share_buttons[0],
                    web_buttons[1], refresh_buttons[0]]
        if sc.step == STEP_WORKSPACE:
            # 한 줄에 12개를 늘어놓으면 무엇이 있는지 외워야 한다 — 두 줄로 가른다.
            # 위: 분석 흐름(순서대로 하는 것) · 아래: 파일·세션·웹(언제든 하는 것)
            return [*WS_ROW1, *WS_ROW2]
        if sc.step == STEP_SESSIONS:
            return [pick_button, back_button, web_buttons[3], refresh_buttons[2]]
        if sc.step == STEP_SAVE:
            return [dosave_button, overwrite_button, back2_button]
        if sc.step == STEP_DERIVE:
            return [pad_button, preview_button, epsup_button, epsdown_button,
                    make_button, back3_button]
        if sc.step == STEP_TRANSPOSE:
            return [tp_run_button, back7_button]
        if sc.step == STEP_SAVECOPY:
            return [copy_main_button, copy_save_button, back7_button]
        if sc.step == STEP_VERIFY:
            # 번호키는 1~9 다. 10개를 늘어놓으면 마지막 버튼은 번호로 못 누른다 —
            # **지금 화면에 있는 것만** 준다: 결과를 보는 중이면 목록 조작 버튼은 뺀다
            folded = sc.verify_result is not None and not sc.verify_picking
            if folded:
                return [verify_rprev_button, verify_rnext_button,
                        verify_detail_button, verify_sum_button, verify_pick_button,
                        verify_rerun_button, back7_button]
            return [verify_open_button, verify_key_button, verify_id_button,
                    verify_pair_button, verify_all_button, verify_prev_button,
                    verify_next_button, verify_run_button, back7_button]
        if sc.step == STEP_MODEL_PLAN:
            return [mb_set_button, mb_apply_button, back9_button]
        if sc.step == STEP_MODEL:
            return [mb_plan_button, model_run_button, model_shift_button,
                    model_code_button, back8_button]
        if sc.step == STEP_TYPES:
            return [cycle_button, confirm_button, unconfirm_button, distv_button,
                    scores_button, represent_button, robust_button,
                    back4_button]
        if sc.step == STEP_LABELS:
            return [lsave_button, lskip_button]
        if sc.step == STEP_ANALYZE:
            if sc.an_mode == "plot":
                return [exclude_button, back6_button]
            if sc.an_mode == "result":
                return [plot_button, redesign_button, back5_button]
            btns = [anlist_button, anplan_button, anrun_button]
            if any(m["n"] for m in sc.an_missing.values()) and not sc.an_ignore_missing:
                btns += [impute_button, ignore_na_button]
            return [*btns, back5_button]
        return []

    def numkey_line() -> str:
        items = "  ".join(f"{i}.{b.text}" for i, b in enumerate(screen_buttons(), 1))
        return msg("screen_numkeys", items=items)

    # 작업 영역 버튼 두 줄 — 위는 "분석을 진행하는 순서", 아래는 "파일·세션·웹"
    WS_ROW1 = [derive_button, types_button, find_button, analyze_button,
               robust_button, model_button]
    WS_ROW2 = [tp_button, copy_button, verify_button, more_button, save_button,
               share_buttons[1], web_buttons[2], refresh_buttons[1]]

    buttons = [open_button, load_button, import_button, prev_button, next_button,
               sort_miss, sort_uniq, sort_name, search_button, more_button, save_button,
               sessions_button, pick_button, back_button, dosave_button,
               overwrite_button, back2_button, derive_button, preview_button,
               epsup_button, epsdown_button, make_button, back3_button, types_button,
               cycle_button, confirm_button, unconfirm_button, distv_button,
               scores_button, represent_button, robust_button, back4_button,
               lsave_button, lskip_button, analyze_button, anplan_button,
               anrun_button, back5_button, redesign_button, impute_button,
               ignore_na_button, plot_button, exclude_button, back6_button,
               anlist_button, pad_button, tp_button, tp_run_button, copy_button,
               copy_save_button, copy_main_button, verify_button,
               verify_open_button, verify_run_button, verify_key_button,
               verify_id_button, verify_pair_button, verify_pick_button,
               verify_all_button, verify_prev_button, verify_next_button,
               verify_detail_button, verify_sum_button, verify_rerun_button,
               verify_rprev_button, verify_rnext_button, back7_button,
               tmp_button, tmp_del_button, back10_button,
               find_button, find_run_button, find_rule_button, find_plot_button,
               find_aim_button, find_support_button, find_guard_button,
               find_color_button, find_goal_button, find_adj_button, back11_button,
               model_button, mb_plan_button, mb_apply_button, mb_set_button,
               back9_button, model_run_button, model_shift_button,
               model_code_button, back8_button,
               *web_buttons, *refresh_buttons, *share_buttons]

    def track_focus() -> str:
        """지금 초점이 어느 위젯인지 이름을 붙인다 — 상태줄이 이걸 읽어 보여준다."""
        layout = app.layout
        if layout.has_focus(path_input):
            return "path"
        if layout.has_focus(search_input):
            return "search"
        if layout.has_focus(table_window):
            return "table"
        if layout.has_focus(ws_window):
            return "workspace"
        if layout.has_focus(sessions_window):
            return "sessions"
        if layout.has_focus(savedir_input):
            return "savedir"
        if layout.has_focus(types_window):
            return "types"
        if layout.has_focus(labels_window):
            return "labels"
        if layout.has_focus(analyze_window):
            return "analyze"
        if layout.has_focus(expr_input):
            return "expr"
        if layout.has_focus(newname_input):
            return "newname"
        for b in buttons:
            if layout.has_focus(b):
                return "btn:" + b.statop_tag
        return "?"

    def status_text():  # noqa: ANN202
        sc.focus = track_focus()
        return HTML(sc.render_status() + "\n  <mut>" + _esc(numkey_line()) + "</mut>")

    def at(step: str):  # noqa: ANN202
        return Condition(lambda: sc.step == step)

    def rule():  # noqa: ANN202
        """터미널 폭에 맞춰 채워지는 가로선 — 문자열로 그리면 폭을 모른다."""
        return Window(height=1, char="─", style="class:rule")

    body = HSplit([
        Window(ClickableControl(lambda: HTML(sc.render_header())), height=1),
        rule(),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML(sc.render_open())), height=D(min=1, max=9)),
            VSplit([path_input, open_button, load_button, tmp_button,
                    web_buttons[0]], height=1),
        ]), filter=at(STEP_OPEN)),
        ConditionalContainer(HSplit([
            VSplit([sort_miss, sort_uniq, sort_name, Window(width=2),
                    search_input, search_button], height=1),
            table_window,
            VSplit([prev_button, next_button, import_button, share_buttons[0],
                    web_buttons[1], refresh_buttons[0]], height=1),
        ]), filter=at(STEP_COLUMNS)),
        ConditionalContainer(HSplit([
            ws_window,
            VSplit(WS_ROW1, height=1),
            VSplit(WS_ROW2, height=1),
        ]), filter=at(STEP_WORKSPACE)),
        ConditionalContainer(HSplit([
            sessions_window,
            VSplit([pick_button, back_button, web_buttons[3],
                    refresh_buttons[2]], height=1),
        ]), filter=at(STEP_SESSIONS)),
        ConditionalContainer(HSplit([
            types_window,
            VSplit([cycle_button, confirm_button, unconfirm_button, distv_button,
                    scores_button, represent_button, robust_button,
                    back4_button], height=1),
        ]), filter=at(STEP_TYPES)),
        ConditionalContainer(HSplit([
            labels_window,
            VSplit([lsave_button, lskip_button], height=1),
        ]), filter=at(STEP_LABELS)),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML("\n".join(sc.render_transpose())))),
            VSplit([tp_run_button, back7_button], height=1),
        ]), filter=at(STEP_TRANSPOSE)),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML("\n".join(sc.render_savecopy())))),
            copy_input,
            VSplit([copy_main_button, copy_save_button, back7_button], height=1),
        ]), filter=at(STEP_SAVECOPY)),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML("\n".join(sc.render_verify())),
                                    on_scroll=lambda d: guard(sc.move_verify_row)(d),
                                    on_click=guard(click_verify_col))),
            verify_input,
            # 줄 자체가 상황에 따라 바뀐다 — 화면에 보이는 것과 번호키가 같아야 한다
            ConditionalContainer(
                VSplit([verify_rprev_button, verify_rnext_button,
                        verify_detail_button, verify_sum_button, verify_pick_button,
                        verify_rerun_button, back7_button], height=1),
                filter=Condition(lambda: sc.verify_result is not None
                                 and not sc.verify_picking)),
            ConditionalContainer(
                VSplit([verify_open_button, verify_key_button, verify_id_button,
                        verify_pair_button, verify_all_button, verify_prev_button,
                        verify_next_button, verify_run_button, back7_button],
                       height=1),
                filter=Condition(lambda: not (sc.verify_result is not None
                                              and not sc.verify_picking))),
        ]), filter=at(STEP_VERIFY)),
        ConditionalContainer(HSplit([
            find_window,
            find_aim_input,
            VSplit([find_run_button, find_plot_button, find_color_button,
                    find_rule_button, find_goal_button, find_adj_button,
                    find_support_button, find_guard_button,
                    find_support_button, find_guard_button,
                    find_aim_button, find_support_button, find_guard_button, back11_button], height=1),
        ]), filter=at(STEP_FIND)),
        ConditionalContainer(HSplit([
            tmp_window,
            VSplit([tmp_del_button, back10_button], height=1),
        ]), filter=at(STEP_TMP)),
        ConditionalContainer(HSplit([
            mb_plan_window,
            mb_set_input,
            VSplit([mb_set_button, mb_apply_button, back9_button], height=1),
        ]), filter=at(STEP_MODEL_PLAN)),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML("\n".join(sc.render_model())))),
            mb_key_input, mb_expect_input, mb_code_input,
            VSplit([mb_plan_button, model_run_button, model_shift_button,
                    model_code_button, back8_button], height=1),
        ]), filter=at(STEP_MODEL)),
        ConditionalContainer(HSplit([
            analyze_window,
            ConditionalContainer(
                VSplit([anlist_button, anplan_button, anrun_button, back5_button],
                       height=1),
                filter=Condition(lambda: sc.an_mode != "result"
                                 and (sc.an_ignore_missing
                                      or not any(m["n"] for m in sc.an_missing.values())))),
            ConditionalContainer(
                VSplit([anlist_button, anplan_button, anrun_button, impute_button,
                        ignore_na_button, back5_button], height=1),
                filter=Condition(lambda: sc.an_mode != "result"
                                 and not sc.an_ignore_missing
                                 and any(m["n"] for m in sc.an_missing.values()))),
            ConditionalContainer(
                VSplit([plot_button, redesign_button, back5_button], height=1),
                filter=Condition(lambda: sc.an_mode == "result")),
            ConditionalContainer(HSplit([
                reason_input,
                VSplit([exclude_button, back6_button], height=1),
            ]), filter=Condition(lambda: sc.an_mode == "plot")),
        ]), filter=at(STEP_ANALYZE)),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML(sc.render_derive()),
                                    on_click=guard(click_pad_key)),
                   height=D(min=1, max=20)),
            VSplit([expr_input, preview_button, epsup_button, epsdown_button], height=1),
            VSplit([newname_input, pad_button, make_button, back3_button], height=1),
        ]), filter=at(STEP_DERIVE)),
        ConditionalContainer(HSplit([
            Window(ClickableControl(lambda: HTML(sc.render_save())),
                   height=D(min=1, max=8)),
            VSplit([savedir_input, dosave_button, overwrite_button, back2_button],
                   height=1),
        ]), filter=at(STEP_SAVE)),
        rule(),
        ConditionalContainer(
            Window(ClickableControl(lambda: HTML(sc.render_web())), height=3),
            filter=Condition(lambda: bool(sc.web_url))),
        Window(ClickableControl(status_text), height=4),
    ])

    _kb = KeyBindings()

    class GuardedBindings:
        """모든 키 핸들러를 guard 로 감싼다 — 등록 지점을 빠뜨릴 수 없게 한 곳에서."""

        def add(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
            deco = _kb.add(*a, **k)
            return lambda fn: deco(guard(fn))

    kb = GuardedBindings()
    # **입력칸을 하나라도 빠뜨리면 그 칸에서는 글자가 단축키가 된다.**
    # 실제로 여기 없던 칸에서 경로를 치니 숫자가 전부 버튼으로 먹혀
    # `/storm/.../jwb419/17_...` 가 `/storm/.../jwb/_...` 로 들어갔다.
    # 새 입력칸을 만들면 여기에도 넣는다 (test_screen 이 빠진 칸을 잡는다)
    text_boxes = (path_input, search_input, savedir_input, expr_input, newname_input,
                  copy_input, verify_input, find_aim_input, mb_key_input, mb_expect_input,
                  mb_code_input, reason_input, mb_set_input)

    def typing() -> bool:
        """입력칸에 있으면 글자키는 글자여야 한다 — 검색어에 d를 못 치면 안 된다."""
        return any(app.layout.has_focus(t) for t in text_boxes)

    # 초점이 버튼에 가 있어도 목록 키는 동작한다. "왜 d가 안 되지"의 원인이 이것이었다
    in_table = Condition(lambda: sc.step == STEP_COLUMNS and not typing())
    in_ws = Condition(lambda: sc.step == STEP_WORKSPACE and not typing())
    in_sessions = Condition(lambda: sc.step == STEP_SESSIONS and not typing())

    @kb.add("f2")
    def _(e):  # noqa: ANN001
        sc.mouse_on = not sc.mouse_on
        sc.say(msg("screen_mouse_on" if sc.mouse_on else "screen_mouse_off"), "ok")

    @kb.add("c-q")
    @kb.add("c-c")
    def _(e):  # noqa: ANN001
        e.app.exit()

    def _press_nth(n: int):  # noqa: ANN202
        def run(e) -> None:  # noqa: ANN001
            bs = screen_buttons()
            if n <= len(bs) and bs[n - 1].handler is not None:
                bs[n - 1].handler()

        return run

    for _n in range(1, 10):
        # 마우스를 못 쓰는 터미널이 있다 — 번호키로 같은 버튼을 누를 수 있어야 한다
        kb.add(str(_n), filter=Condition(lambda: not typing()))(_press_nth(_n))

    @kb.add("tab")
    def _(e):  # noqa: ANN001
        e.app.layout.focus_next()

    @kb.add("s-tab")
    def _(e):  # noqa: ANN001
        e.app.layout.focus_previous()

    @kb.add("up", filter=in_table)
    def _(e):  # noqa: ANN001
        sc.move(-1)

    @kb.add("down", filter=in_table)
    def _(e):  # noqa: ANN001
        sc.move(1)

    @kb.add(" ", filter=in_table)     # 스페이스바는 리터럴 " " 다 ("space"는 글자 5개)
    def _(e):  # noqa: ANN001
        sc.toggle_at(sc.view.cursor)
        refresh_label()
        flash(sc.view.cursor)

    @kb.add("a", filter=in_table)
    def _(e):  # noqa: ANN001
        sc.toggle_page()
        refresh_label()

    on_button = Condition(lambda: sc.focus.startswith("btn:"))

    @kb.add("enter", filter=in_table & ~on_button)
    def _(e):  # noqa: ANN001
        do_import()

    @kb.add("up", filter=in_ws)
    def _(e):  # noqa: ANN001
        sc.row = max(0, sc.row - 1)

    @kb.add("down", filter=in_ws)
    def _(e):  # noqa: ANN001
        sc.row = min(max(0, len(sc.imported) - 1), sc.row + 1)

    @kb.add(" ", filter=in_ws)
    def _(e):  # noqa: ANN001
        if sc.imported:
            sc.toggle_hold(sc.imported[sc.row])
            flash(sc.row)

    @kb.add("d", filter=in_ws)
    def _(e):  # noqa: ANN001
        sc.drop_current()

    in_types = Condition(lambda: sc.step == STEP_TYPES and not typing())

    @kb.add("up", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.move_type(-1)

    @kb.add("down", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.move_type(1)

    @kb.add(" ", filter=in_types)
    @kb.add("right", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.cycle_type(1)

    @kb.add("left", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.cycle_type(-1)

    @kb.add("enter", filter=in_types & ~on_button)
    def _(e):  # noqa: ANN001
        do_confirm_type()

    @kb.add("v", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.toggle_dist()

    # 점수 목록이 펼쳐져 있을 때만 쪽을 넘긴다 — 아니면 아무 일도 안 일어난다
    @kb.add("pagedown", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.move_score_page(1)

    @kb.add("pageup", filter=in_types)
    def _(e):  # noqa: ANN001
        sc.move_score_page(-1)

    in_labels = Condition(lambda: sc.step == STEP_LABELS and not typing())

    @kb.add("up", filter=in_labels)
    def _(e):  # noqa: ANN001
        sc.move_label(-1)

    @kb.add("down", filter=in_labels)
    def _(e):  # noqa: ANN001
        sc.move_label(1)

    @kb.add("left", filter=in_labels)
    def _(e):  # noqa: ANN001
        sc.bump_code(-1)

    @kb.add("right", filter=in_labels)
    def _(e):  # noqa: ANN001
        sc.bump_code(1)

    @kb.add("enter", filter=in_labels & ~on_button)
    def _(e):  # noqa: ANN001
        if sc.save_labels():
            app.layout.focus(types_window)

    in_find = Condition(lambda: sc.step == STEP_FIND and not typing())

    @kb.add("up", filter=in_find)
    def _(e):  # noqa: ANN001
        sc.move_find(-1)

    @kb.add("down", filter=in_find)
    def _(e):  # noqa: ANN001
        sc.move_find(1)

    @kb.add("left", filter=in_find)
    def _(e):  # noqa: ANN001
        sc.find_stage_move(-1)

    @kb.add("right", filter=in_find)
    def _(e):  # noqa: ANN001
        sc.find_stage_move(1)

    @kb.add(" ", filter=in_find)
    def _(e):  # noqa: ANN001
        do_bg(sc.find_pick)

    @kb.add("enter", filter=in_find & ~on_button)
    def _(e):  # noqa: ANN001
        do_bg(sc.find_pick)

    in_tmp = Condition(lambda: sc.step == STEP_TMP and not typing())

    @kb.add("up", filter=in_tmp)
    def _(e):  # noqa: ANN001
        sc.move_tmp(-1)

    @kb.add("down", filter=in_tmp)
    def _(e):  # noqa: ANN001
        sc.move_tmp(1)

    in_mb_plan = Condition(lambda: sc.step == STEP_MODEL_PLAN and not typing())

    @kb.add("up", filter=in_mb_plan)
    def _(e):  # noqa: ANN001
        sc.mb_move(-1)

    @kb.add("down", filter=in_mb_plan)
    def _(e):  # noqa: ANN001
        sc.mb_move(1)

    @kb.add(" ", filter=in_mb_plan)
    def _(e):  # noqa: ANN001
        sc.mb_toggle_list()

    @kb.add("left", filter=in_mb_plan)
    def _(e):  # noqa: ANN001
        sc.mb_cycle(-1)

    @kb.add("right", filter=in_mb_plan)
    def _(e):  # noqa: ANN001
        sc.mb_cycle(1)

    @kb.add("enter", filter=in_mb_plan & ~on_button)
    def _(e):  # noqa: ANN001
        if sc.mb_open:
            sc.mb_choose()
        else:
            do_bg(sc.mb_apply_plan)

    in_verify = Condition(lambda: sc.step == STEP_VERIFY and not typing())

    def in_result() -> bool:
        return sc.verify_result is not None and not sc.verify_picking

    @kb.add("up", filter=in_verify)
    def _(e):  # noqa: ANN001
        sc.move_verify_sum(-1) if in_result() else sc.move_verify_row(-1)

    @kb.add("down", filter=in_verify)
    def _(e):  # noqa: ANN001
        sc.move_verify_sum(1) if in_result() else sc.move_verify_row(1)

    @kb.add("enter", filter=in_verify & ~on_button)
    def _(e):  # noqa: ANN001
        if in_result():
            do_bg(sc.open_verify_detail)

    @kb.add("escape", filter=in_verify)
    def _(e):  # noqa: ANN001
        # 상세에서 Esc 는 **요약으로** — 화면을 떠나지 않는다
        if in_result() and sc.verify_detail >= 0:
            sc.back_to_summary()
        else:
            do_back()

    @kb.add(" ", filter=in_verify)
    def _(e):  # noqa: ANN001
        r = sc.current_verify_row()
        if r and r["pair"]:
            sc.toggle_verify_col(r["column"])

    @kb.add("pagedown", filter=in_verify)
    def _(e):  # noqa: ANN001
        sc.move_verify_page(1)

    @kb.add("pageup", filter=in_verify)
    def _(e):  # noqa: ANN001
        sc.move_verify_page(-1)

    in_derive_pad = Condition(lambda: sc.step == STEP_DERIVE and not typing())

    @kb.add("up", filter=in_derive_pad)
    def _(e):  # noqa: ANN001
        sc.pad_move(drow=-1)

    @kb.add("down", filter=in_derive_pad)
    def _(e):  # noqa: ANN001
        sc.pad_move(drow=1)

    @kb.add("left", filter=in_derive_pad)
    def _(e):  # noqa: ANN001
        sc.pad_move(dcol=-1)

    @kb.add("right", filter=in_derive_pad)
    def _(e):  # noqa: ANN001
        sc.pad_move(dcol=1)

    @kb.add("enter", filter=in_derive_pad & ~on_button)
    def _(e):  # noqa: ANN001
        insert_key()

    in_analyze = Condition(lambda: sc.step == STEP_ANALYZE and not typing())

    def _an_up_down(delta: int) -> None:
        if sc.an_mode == "plot":
            sc.an_plot_move(delta)
        elif sc.an_open:
            sc.an_pick_move(delta)
        else:
            sc.an_move(delta)

    @kb.add("up", filter=in_analyze)
    def _(e):  # noqa: ANN001
        _an_up_down(-1)

    @kb.add("down", filter=in_analyze)
    def _(e):  # noqa: ANN001
        _an_up_down(1)

    def _an_left_right(delta: int) -> None:
        if sc.an_row < len(sc.an_fields):
            sc.an_cycle(delta)
        elif any(m["n"] for m in sc.an_missing.values()):
            sc.an_cycle_impute(delta)

    @kb.add("left", filter=in_analyze)
    def _(e):  # noqa: ANN001
        _an_left_right(-1)

    @kb.add("right", filter=in_analyze)
    @kb.add(" ", filter=in_analyze)
    def _(e):  # noqa: ANN001
        _an_left_right(1)

    @kb.add("enter", filter=in_analyze & ~on_button)
    def _(e):  # noqa: ANN001
        if sc.an_mode == "plot":
            sc.an_reason = reason_input.text
            do_bg(sc.an_toggle_point)
        elif sc.an_open:
            sc.an_pick_choose()
        elif sc.an_row < len(sc.an_fields):
            sc.an_toggle_list()           # 필드 위에서 Enter 는 선택지 펼치기
        elif sc.an_selected_test() is not None:
            do_an_run()
        else:
            do_an_plan()

    @kb.add("up", filter=in_sessions)
    def _(e):  # noqa: ANN001
        sc.move_session(-1)

    @kb.add("down", filter=in_sessions)
    def _(e):  # noqa: ANN001
        sc.move_session(1)

    @kb.add("enter", filter=in_sessions)
    def _(e):  # noqa: ANN001
        do_pick_session()

    @kb.add("escape")
    def _(e):  # noqa: ANN001
        """빠져나갈 길을 항상 둔다 — 들어갔다가 못 나오면 안 된다."""
        if sc.step == STEP_LABELS:
            do_skip_labels()
        elif sc.step == STEP_ANALYZE and sc.an_open:
            sc.an_open = False
        elif sc.step == STEP_ANALYZE and sc.an_mode in ("result", "plot"):
            sc.an_back_to_design()       # 결과에서 Esc 는 설계로 — 화면을 떠나지 않는다
        elif sc.step in (STEP_SESSIONS, STEP_SAVE, STEP_DERIVE, STEP_TYPES,
                         STEP_ANALYZE, STEP_TRANSPOSE, STEP_SAVECOPY, STEP_VERIFY,
                         STEP_MODEL, STEP_MODEL_PLAN, STEP_TMP, STEP_FIND):
            do_back()

    # 입력칸에서 Enter는 옆 버튼과 같은 동작 — 손이 안 움직이게
    path_input.control.key_bindings = _enter_binding(guard(do_open))
    search_input.control.key_bindings = _enter_binding(
        guard(lambda: sc.search(search_input.text)))
    expr_input.control.key_bindings = _enter_binding(guard(do_preview))
    newname_input.control.key_bindings = _enter_binding(guard(do_make))
    # 나중에 붙인 칸들도 같다 — 경로를 치고 Enter 를 눌렀는데 아무 일이 없으면
    # 칸이 살아 있는지조차 알 수 없다
    verify_input.control.key_bindings = _enter_binding(guard(do_verify_set))
    copy_input.control.key_bindings = _enter_binding(
        guard(lambda: do_bg(lambda: sc.do_savecopy(copy_input.text))))
    mb_key_input.control.key_bindings = _enter_binding(
        guard(lambda: do_bg(lambda: sc.run_model_audit(mb_key_input.text,
                                                       mb_expect_input.text))))
    mb_expect_input.control.key_bindings = mb_key_input.control.key_bindings
    find_aim_input.control.key_bindings = _enter_binding(
        guard(lambda: do_bg(lambda: sc.set_find_target(find_aim_input.text))))
    mb_set_input.control.key_bindings = _enter_binding(guard(do_mb_add_set))
    mb_code_input.control.key_bindings = _enter_binding(
        guard(lambda: do_bg(lambda: sc.run_model_code(mb_code_input.text))))

    app = Application(layout=Layout(body, focused_element=path_input), key_bindings=_kb,
                      style=style, full_screen=True,
                      # 마우스를 잡고 있으면 터미널이 드래그를 못 받아 **복사가 안 된다**.
                      # F2 로 끌 수 있게 필터로 둔다 (렌더마다 다시 읽힌다)
                      mouse_support=Condition(lambda: sc.mouse_on))
    sc.say(msg("screen_open_hint"), "mut")
    app.run()


def _enter_binding(handler):  # noqa: ANN001, ANN202
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("enter")
    def _(e):  # noqa: ANN001
        handler()

    return kb
