"""REST API (요구사항8절) — UI 없이 단독 호출 가능. 웹·CLI·셸이 같은 코어를 이 층으로 공유한다.

원칙: 응답에 데이터 셀을 담지 않는다(점진 노출). 모든 사용자 문장은 messages 템플릿 경유.
세션은 파일(session_*.json)이 진실이므로 서버는 상태를 메모리에 들고 있지 않는다 —
여러 껍데기(웹·CLI·셸)가 같은 세션을 열어도 어긋나지 않게 하기 위함.
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import statop
from statop.messages import msg

app = FastAPI(
    title="STATOP API",
    version=statop.__version__,
    description="STATistic Ontology Platform",
)


@app.middleware("http")
async def _no_cache_html(request, call_next):  # noqa: ANN001, ANN201
    """/ui/ 의 HTML은 캐시하지 않는다 — 옛 빌드가 브라우저에 남으면
    수정해도 사용자는 계속 옛 화면을 본다. 해시 붙은 assets는 그대로 캐시된다."""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if request.url.path.startswith("/ui") and "text/html" in ct:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def _mount_ui() -> None:
    """빌드된 UI(ui/dist)가 있으면 같은 포트에서 서빙한다 — 배포 시 포트 하나로 끝낸다.
    개발 중에는 Vite(5173)가 /v1·/health를 이 서버로 프록시한다."""
    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).resolve().parents[3] / "ui" / "dist"
    if dist.is_dir():
        app.mount("/ui", StaticFiles(directory=dist, html=True), name="ui")


def ui_built() -> bool:
    return (Path(__file__).resolve().parents[3] / "ui" / "dist").is_dir()


def code_stamp() -> int:
    """statop 패키지 소스의 최신 수정시각 — 서버가 낡은 코드로 돌고 있는지 구별하는 지문.

    코드를 고친 뒤에도 옛 서버가 계속 재사용되면, 웹은 새 화면인데 API는 옛것이라
    "없는 엔드포인트 404 → 첫 화면"이 된다. 버전 문자열은 안 바뀌므로 mtime을 쓴다.
    """
    root = Path(__file__).resolve().parents[1]
    return max(int(f.stat().st_mtime) for f in root.rglob("*.py"))


_STAMP_AT_START = code_stamp()     # 서버가 든 코드의 지문 (기동 시점 고정)


@app.get("/health")
def health() -> dict:
    """기동 확인 — 버전·규칙 DB 버전·코드 지문을 함께 반환한다."""
    from statop.rules.build import rules_version

    try:
        rules = rules_version()
    except Exception:
        rules = None
    return {"status": "ok", "statop_version": statop.__version__, "rules_version": rules,
            "code_stamp": _STAMP_AT_START}


class NewSession(BaseModel):
    project: str | None = None
    data: str | None = None
    user: str | None = None


@app.post("/v1/sessions")
def create_session(body: NewSession) -> dict:
    """새 세션 (요구사항8절). 데이터 사본 없이 경로·부분 해시·조작 기록만 남긴다."""
    from statop.session.core import new_session, register_source, save_session

    if body.project and not Path(body.project).is_dir():
        raise HTTPException(400, msg("session_no_project", path=body.project))

    doc = new_session(body.project, user=body.user)
    src_id = None
    if body.data:
        if not Path(body.data).exists():
            raise HTTPException(404, msg("path_not_exist"))
        src_id = register_source(doc, body.data)
    path = save_session(doc)
    return {
        "session_id": doc["session_id"],
        "session_file": str(path),
        "source_id": src_id,
        "sources": doc["sources"],
        "rules_version": doc["rules_db_version"],
        "notice": msg("notice_partial_hash"),  # 껍데기가 호출 방법을 덧붙인다 (인터페이스 중립)
    }


def _load(session_file: str) -> dict:
    from statop.session.core import load_session

    p = Path(session_file)
    if not p.exists():
        raise HTTPException(404, msg("path_not_exist"))
    return load_session(p)


class RegisterData(BaseModel):
    session_file: str
    path: str
    role: str = "aux"   # main=분석 대상 교체 / compare=비교용 / aux=보조


@app.post("/v1/datasets")
def register_dataset(body: RegisterData) -> dict:
    """파일 등록 → source_id (요구사항8절 POST /v1/datasets)."""
    from statop.io.meta import open_meta
    from statop.session.core import ensure_source, main_source, save_session, set_main

    if not Path(body.path).exists():
        raise HTTPException(404, msg("path_not_exist"))
    doc = _load(body.session_file)
    try:
        open_meta(body.path)  # 지원 형식인지 여기서 확인 (등록 후 실패하지 않게)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.role not in ("main", "compare", "aux"):
        raise HTTPException(400, "role: main | compare | aux")
    before = len(doc["sources"])
    src_id = ensure_source(doc, body.path, role=body.role)
    if body.role == "main" and len(doc["sources"]) == before:
        set_main(doc, src_id)  # 이미 등록된 파일을 main으로 승격 — 교체를 op로 기록
    save_session(doc)
    src = next(s for s in doc["sources"] if s["id"] == src_id)
    return {"source_id": src_id, "source": src,
            "main": (main_source(doc) or {}).get("id"),
            "sources": doc["sources"], "notice": msg("notice_partial_hash")}


_mount_ui()


@app.get("/", include_in_schema=False)
def root():  # noqa: ANN201
    """주소창에 호스트만 친 사람을 화면으로 보낸다.

    웹 화면은 `/ui/` 에 붙어 있는데 `/` 가 맨 404 를 내면 "서버가 안 떴다"로 읽힌다
    (실제로 그렇게 읽혔다).
    """
    from fastapi.responses import JSONResponse, RedirectResponse

    if ui_built():
        return RedirectResponse("/ui/")
    return JSONResponse({"detail": msg("serve_root_hint", url="/docs")})



class ImportCols(BaseModel):
    session_file: str
    path: str
    cols: list[str]


@app.post("/v1/views/import")
def import_columns(body: ImportCols) -> dict:
    """선택한 컬럼을 작업 영역으로 가져온다 (op: select).

    가져온 뒤에는 **선택한 컬럼만** 다룬다 — 전체 목록은 더 들고 있지 않는다 (M0-4).
    """
    from statop.io.meta import open_meta
    from statop.session.core import append_op, ensure_source, load_session, replay, save_session

    doc = _load(body.session_file)
    p = Path(body.path)
    if not p.exists():
        raise HTTPException(404, msg("path_not_exist"))
    try:
        meta = open_meta(p)
    except ValueError as e:
        raise HTTPException(400, str(e))

    missing = [c for c in body.cols if c not in meta.columns]
    if missing:
        raise HTTPException(400, msg("select_err_missing", cols=", ".join(missing)))
    if not body.cols:
        raise HTTPException(400, msg("select_err_empty"))

    src_id = ensure_source(doc, str(p), role="main")
    if not any(o["op"] == "open" and o.get("source") == src_id for o in doc["ops"]):
        append_op(doc, "open", source=src_id)
    entry = append_op(doc, "select", source=src_id, cols=body.cols)
    save_session(doc)

    selected = replay(doc)["selected"].get(src_id, [])
    return {"source_id": src_id, "op_seq": entry["seq"],
            "selected": selected, "n_selected": len(selected),
            "ops": len(doc["ops"])}


class DropCols(BaseModel):
    session_file: str
    cols: list[str]


@app.post("/v1/views/drop")
def drop_columns(body: DropCols) -> dict:
    """작업 영역에서 뺀다 — 원본이면 선택 해제, **파생이면 파생 취소**.

    사용자에게는 같은 [제외] 한 번이다. 예전에는 파생 이름을 거절해서 지울 길이 없었다.
    """
    from statop.session.core import main_source, remove_columns, replay, save_session

    doc = _load(body.session_file)
    src = main_source(doc)
    if src is None:
        raise HTTPException(400, msg("select_err_empty"))
    off, gone, unknown = remove_columns(doc, src["id"], body.cols)
    if unknown:
        raise HTTPException(400, msg("drop_err_unknown", cols=", ".join(unknown)))
    save_session(doc)
    st = replay(doc)
    selected = st["selected"].get(src["id"], [])
    return {"source_id": src["id"], "selected": selected,
            "n_selected": len(selected),
            "derived": [d["name"] for d in st["derived"]
                        if d.get("source") == src["id"]],
            "dropped_derived": gone,
            "notice": msg("derive_dropped", name=", ".join(gone)) if gone else ""}


@app.get("/v1/views/selected")
def view_selected(session_file: str) -> dict:
    """현재 작업 영역 — 가져온 컬럼·hold·분석 대상 (전체 목록 아님)."""
    from statop.session.core import main_source, replay

    doc = _load(session_file)
    src = main_source(doc)
    # 세션 ID는 서버가 준다 — 웹이 파일명에서 짐작하면 터미널 표시와 달라 보인다
    if src is None:
        return {"session_id": doc["session_id"], "source_id": None,
                "selected": [], "held": [], "analysis": [], "derived": []}
    st = replay(doc)
    sid = src["id"]
    return {"session_id": doc["session_id"], "source_id": sid, "path": src["path"],
            "selected": st["selected"].get(sid, []),
            # 파생 컬럼은 선택 목록에 없다 — 이걸 안 주면 다시 연 화면에서 방금 만든
            # 컬럼으로 다음 식을 못 만든다 (셸의 formula_columns 와 같은 규칙)
            "derived": [d["name"] for d in st["derived"] if d.get("source") == sid],
            "held": st["held"].get(sid, []),
            "analysis": st["analysis"].get(sid, []),
            "n_selected": len(st["selected"].get(sid, [])),
            "n_analysis": len(st["analysis"].get(sid, []))}


class HoldCols(BaseModel):
    session_file: str
    cols: list[str]
    hold: bool = True   # False면 해제


@app.post("/v1/views/hold")
def hold_columns(body: HoldCols) -> dict:
    """컬럼 hold (M0-5) — **분석에서는 빼되 시각화(색·점 식별)에는 쓴다.**

    제외(deselect)와 다르다: 제외는 작업 영역에서 사라지고, hold는 남아서 그림에 쓰인다.
    """
    from statop.session.core import append_op, main_source, replay, save_session

    doc = _load(body.session_file)
    src = main_source(doc)
    if src is None:
        raise HTTPException(400, msg("select_err_empty"))
    st = replay(doc)
    sid = src["id"]
    current = st["selected"].get(sid, [])
    unknown = [c for c in body.cols if c not in current]
    if unknown:
        raise HTTPException(400, msg("deselect_err_not_selected", cols=", ".join(unknown)))
    if not body.cols:
        raise HTTPException(400, msg("select_err_empty"))

    entry = append_op(doc, "hold" if body.hold else "unhold", source=sid, cols=body.cols)
    save_session(doc)
    st = replay(doc)
    return {"source_id": sid, "op_seq": entry["seq"],
            "held": st["held"].get(sid, []), "analysis": st["analysis"].get(sid, []),
            "n_analysis": len(st["analysis"].get(sid, []))}


class DistReq(BaseModel):
    path: str
    cols: list[str]
    session_file: str | None = None   # 있으면 파생 컬럼도 재계산해 분포 대상에 넣는다
    sample_n: int = 10_000


@app.post("/v1/views/distribution")
async def view_distribution(body: DistReq) -> dict:
    """M0-3 분포 미리보기 — **클릭할 때만** 계산한다 (요구사항 지연 렌더).

    숫자만 반환하고 그림은 껍데기가 그린다 — 웹은 막대, 셸·CLI는 블록 문자.
    """
    from statop.api.tasks import distribution_task
    from statop.api.workers import run_isolated

    p = Path(body.path)
    if not p.exists():
        raise HTTPException(404, msg("path_not_exist"))
    if not body.cols:
        raise HTTPException(400, msg("select_err_empty"))
    try:
        if body.session_file:
            # 파생 컬럼은 파일에 없다 — 세션 기록에서 재계산해 붙인 뒤 계산한다.
            # **스레드에서 돈다.** 이 함수는 async 라, 여기서 그냥 계산하면 도는 동안
            # 서버의 이벤트 루프가 잡혀 다른 클릭이 전부 줄을 선다 (화면이 멈춘다)
            import asyncio

            from statop.derive.service import apply_ops, session_frame
            from statop.io.distribution import distributions_of

            def work() -> list:
                doc, src, df = session_frame(body.session_file, body.sample_n)
                return distributions_of(apply_ops(df, doc, src["id"]), body.cols)

            res = await asyncio.get_running_loop().run_in_executor(None, work)
        else:
            res = await run_isolated(f"dist:{p}", distribution_task, str(p), body.cols,
                                     body.sample_n)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    # 다섯 수·IQR·울타리의 **이름과 값**은 코어가 만든다 — 터미널과 웹이 같은 글자를 본다
    from statop.render.spark import quartile_stats

    for it in res:
        it["stats"] = quartile_stats(it)
        it["fence_note"] = msg("q_fence_note") if it.get("quartiles") else ""
    return {"items": res}


@app.get("/v1/labels/levels")
def label_levels(path: str, column: str, session_file: str | None = None,
                 sample_n: int = 10_000) -> dict:
    """문자열 카테고리 컬럼의 수준 목록 () — 표시 값·n·코드·색.

    여러 수준을 같은 코드로 묶으면 **군이 재정의된다** — groups에 묶은 결과를 함께 준다.
    """
    from statop.labels import groups_after, levels_of

    p = Path(path)
    if not p.exists():
        raise HTTPException(404, msg("path_not_exist"))

    mapping = None
    if session_file:
        from statop.session.core import main_source, replay

        doc = _load(session_file)
        src = main_source(doc)
        if src:
            mapping = replay(doc)["label_maps"].get(src["id"], {}).get(column)
    try:
        levels = levels_of(p, column, sample_n=sample_n, mapping=mapping)
    except ValueError as e:
        raise HTTPException(400, str(e))

    groups = groups_after(levels)
    return {
        "column": column, "n_levels": len(levels), "mapped": mapping is not None,
        "levels": [
            {"value": lv.value, "n": lv.n, "ratio": lv.ratio, "code": lv.code,
             "color": lv.color, "category": lv.category, "ambiguous": lv.ambiguous}
            for lv in levels
        ],
        "groups": list(groups.values()),
        "regrouped": len(groups) < len(levels),   # 묶임이 일어났는가
    }


class LabelMap(BaseModel):
    session_file: str
    column: str
    mapping: dict[str, int]


@app.post("/v1/labels/map")
def set_label_map(body: LabelMap) -> dict:
    """라벨 매핑 확정 (op: label_map). 무엇을 어떻게 묶었는지 기록에 남는다."""
    from statop.session.core import append_op, main_source, replay, save_session

    doc = _load(body.session_file)
    src = main_source(doc)
    if src is None:
        raise HTTPException(400, msg("select_err_empty"))
    if not body.mapping:
        raise HTTPException(400, msg("select_err_empty"))

    entry = append_op(doc, "label_map", source=src["id"], column=body.column,
                      mapping=body.mapping)
    save_session(doc)
    groups: dict[int, list[str]] = {}
    for value, code in body.mapping.items():
        groups.setdefault(code, []).append(value)
    return {"op_seq": entry["seq"], "column": body.column,
            "n_levels": len(body.mapping), "n_groups": len(groups),
            "groups": [{"code": c, "values": v} for c, v in sorted(groups.items())],
            "current": replay(doc)["label_maps"].get(src["id"], {}).get(body.column)}


class Relabel(BaseModel):
    session_file: str
    key_column: str          # 행을 식별하는 컬럼 (예: patient_id)
    key: str                 # 그 행의 값
    column: str              # 고칠 컬럼
    to: str                  # 새 값
    note: str                # 사유 — 필수 ()


@app.post("/v1/labels/relabel")
def relabel_row(body: Relabel) -> dict:
    """개별 샘플 라벨 수정 () — 원본은 그대로, 기록으로만 남는다.

    사유(note)가 없으면 거부한다. 수정 비율이 임계(1%)를 넘으면 경고를 함께 돌려준다.
    """
    from statop.io.meta import estimate_rows, open_meta
    from statop.relabel import check_ratio, find_row
    from statop.session.core import append_op, main_source, replay, save_session

    doc = _load(body.session_file)
    src = main_source(doc)
    if src is None:
        raise HTTPException(400, msg("select_err_empty"))
    if not body.note.strip():
        raise HTTPException(400, msg("relabel_note_required"))

    path = src["path"]
    try:
        current = find_row(path, body.key_column, body.key, body.column)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if current is None:
        raise HTTPException(404, msg("relabel_key_not_found", key=body.key))
    if current == body.to:
        raise HTTPException(400, msg("relabel_same_value", value=body.to))

    entry = append_op(doc, "relabel", key=body.key, key_column=body.key_column,
                      column=body.column, **{"from": current}, to=body.to,
                      note=body.note.strip(), source=src["id"])
    save_session(doc)

    relabels = replay(doc)["relabels"]
    meta = open_meta(path)
    n_rows = meta.n_rows if meta.n_rows is not None else estimate_rows(path)
    chk = check_ratio(len(relabels), n_rows)
    return {
        "op_seq": entry["seq"], "key": body.key, "column": body.column,
        "from": current, "to": body.to, "note": body.note.strip(),
        "n_relabels": chk.n, "ratio": chk.ratio, "over_threshold": chk.over_threshold,
        "warning": msg("relabel_over_threshold", n=chk.n, ratio=chk.ratio)
                   if chk.over_threshold else None,
        # 출력 맨 앞에 강제 표시되는 문구 — 숨기는 경로가 없다
        "notice": msg("relabel_notice", n=chk.n),
    }


@app.get("/v1/labels/relabels")
def list_relabels(session_file: str) -> dict:
    """이 세션의 개별 수정 목록 — 리포트 맨 앞에 붙는 내용."""
    from statop.session.core import replay

    doc = _load(session_file)
    rl = replay(doc)["relabels"]
    return {"n": len(rl), "items": rl,
            "notice": msg("relabel_notice", n=len(rl)) if rl else None}


@app.get("/v1/paths/check")
def check_path_api(path: str, need: str = "write") -> dict:
    """경로 검사 (요구사항) — 초록/노랑/빨강. 저장·불러오기 입력창의 신호등."""
    from statop.io.pathcheck import check_path

    if need not in ("read", "write"):
        raise HTTPException(400, "need: read | write")
    st = check_path(path, need)
    return {"color": st.color, "exists": st.exists, "readable": st.readable,
            "writable": st.writable, "can_create": st.can_create, "reason": st.reason}


class SaveSession(BaseModel):
    session_file: str
    out_dir: str | None = None
    suffix: str | None = None
    overwrite: bool = False


@app.post("/v1/sessions/save")
def save_session_api(body: SaveSession) -> dict:
    """세션 저장 ( 자동 이름). 단순 저장은 항상 새 파일 — 덮어쓰기는 명시해야 한다."""
    from statop.session.core import auto_name, load_session, save_as, save_session

    doc = _load(body.session_file)
    try:
        target = save_as(doc, out_dir=body.out_dir, suffix=body.suffix,
                         overwrite=body.overwrite)
    except FileExistsError as e:
        raise HTTPException(409, str(e))   # 409 = 이미 있음 → UI가 덮어쓰기 확인을 띄운다
    except (PermissionError, OSError) as e:
        raise HTTPException(400, str(e))
    doc["saved_at"] = target.name
    save_session(doc)
    return {"saved": str(target), "name": target.name,
            "auto_name": auto_name(load_session(target))}


@app.get("/v1/sessions/list")
def list_sessions(path: str | None = None) -> dict:
    """저장된 세션 목록 (불러오기 화면). 기본은 기본 저장소 sessions/."""
    import json as _json

    from statop.store import sessions_dir

    base = Path(path) if path else sessions_dir()
    if not base.is_dir():
        raise HTTPException(404, msg("path_not_exist"))
    items = []
    for f in sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            doc = _json.loads(f.read_text())
        except Exception:
            continue
        src = next((s for s in doc.get("sources", []) if s.get("role") == "main"),
                   (doc.get("sources") or [None])[0])
        items.append({
            "file": str(f), "name": f.name,
            "modified": f.stat().st_mtime,
            "session_id": doc.get("session_id"),
            "source": src["path"] if src else None,
            "ops": len(doc.get("ops", [])),
            "rules_version": doc.get("rules_db_version"),
        })
    return {"dir": str(base), "items": items}


class LoadSession(BaseModel):
    saved: str


@app.post("/v1/sessions/load")
def load_saved_api(body: LoadSession) -> dict:
    """저장본 불러오기 → 새 세션으로 재생. 원본은 부분 해시로 자동 재확인한다 ."""
    from statop.session.core import check_sources, load_saved, save_session

    if not Path(body.saved).exists():
        raise HTTPException(404, msg("path_not_exist"))
    doc, state = load_saved(body.saved)
    problems = [r for r in check_sources(doc) if r["status"] != "ok"]
    path = save_session(doc)
    return {
        "session_id": doc["session_id"], "session_file": str(path),
        "loaded_from": doc["loaded_from"], "sources": doc["sources"],
        "selected": state["selected"], "main": state.get("main"),
        "ops": len(doc["ops"]),
        # 원본이 바뀌었으면 UI가 빨간 경고 + 진행 여부를 묻는다 (S029와 같은 흐름)
        "source_problems": [
            {**r, "message": msg("session_load_missing" if r["status"] == "missing"
                                 else "session_load_changed", src=r["id"], path=r["path"])}
            for r in problems
        ],
        "notice": msg("session_load_guide") if problems else msg("notice_partial_hash"),
    }


@app.on_event("shutdown")
def _shutdown_pool() -> None:
    from statop.api.workers import shutdown

    shutdown()


@app.get("/v1/datasets/columns")
async def dataset_columns(
    path: str,
    sample_n: int = 10_000,
    grep: str | None = None,
    sort: str | None = None,
    limit: int = 25,      # 페이지당 기본 25개 — 컬럼이 많아도 일정한 비용 (웹·CLI 공통)
    offset: int = 0,
    session_file: str | None = None,
) -> dict:
    """컬럼 목록·요약 (M0-2). **데이터 셀은 반환하지 않는다.**

    웹은 이 응답으로 표를 그리고, CLI·셸은 같은 응답을 터미널 형태로 렌더한다.
    """
    import re

    from statop.api import cache
    from statop.api.tasks import profile_task
    from statop.api.workers import run_isolated
    from statop.io.meta import open_meta

    p = Path(path)
    if not p.exists():
        raise HTTPException(404, msg("path_not_exist"))
    try:
        open_meta(p)  # 지원 형식·헤더 확인은 가볍다 — 여기서 먼저 거른다
    except ValueError as e:
        raise HTTPException(400, str(e))
    if sort and sort not in ("missing", "unique", "name"):
        raise HTTPException(400, f"sort: missing | unique | name (got {sort!r})")

    transposed = False
    if session_file:
        from statop.session.core import replay

        doc = _load(session_file)
        target = str(p.resolve())
        src_id = next((s["id"] for s in doc["sources"] if s["path"] == target), None)
        transposed = bool(src_id and replay(doc)["transposed"].get(src_id, False))

    # 프로파일은 캐시 — 페이지를 넘기거나 정렬을 바꿔도 파일을 다시 읽지 않는다.
    # (정렬은 캐시된 전체 목록 기준이므로 "전체 정렬 후 25개씩"이 유지된다)
    ck = cache.cache_key(p, sample_n, transposed)
    res = cache.get(ck)
    cached = res is not None
    if res is None:
        # 무거운 계산은 프로세스 풀에서 (세션별 동시 1개, )
        key = session_file or f"anon:{p.resolve()}"
        res = await run_isolated(key, profile_task, str(p), sample_n, transposed)
        cache.put(ck, res)

    records = res["records"]
    total_columns = len(records)
    if grep:
        pat = re.compile(grep)
        records = [r for r in records if pat.search(r["column"])]
    if sort:
        keys = {"missing": ("missing_rate", True), "unique": ("n_unique", True),
                "name": ("column", False)}
        col, desc = keys[sort]
        records = sorted(records, key=lambda r: r[col], reverse=desc)
    matched = len(records)
    page_size = max(1, limit)
    page = records[offset : offset + page_size]

    dtype_counts: dict[str, int] = {}
    for r in records:
        dtype_counts[r["dtype"]] = dtype_counts.get(r["dtype"], 0) + 1

    from statop.export import origin_line

    return {
        # 가공 파일이면 **원본이 어디였는지**도 — 다시 열거나 더 불러오려면 그 경로가 필요하다
        "file": {"name": p.name, "format": res["fmt"], "size_mb": res["size_mb"],
                 "transposed": transposed, "origin": origin_line(str(p))},
        "rows": {"n": res["n_rows"], "estimated": res["rows_estimated"]},
        "columns": {"total": total_columns, "matched": matched, "offset": offset,
                    "returned": len(page)},
        "page": {"size": page_size, "index": offset // page_size + 1,
                 "count": max(1, -(-matched // page_size)),
                 "has_prev": offset > 0, "has_next": offset + page_size < matched},
        "cached": cached,
        "sample": {"rows_observed": res["sample_rows"], "estimated": res["sample_estimated"]},
        "dtype_counts": dtype_counts,
        "items": [
            {"column": r["column"], "dtype": r["dtype"],
             "missing_rate": float(r["missing_rate"]), "n_unique": int(r["n_unique"]),
             # 표시 등급: 색만으로 구분하지 않도록 껍데기가 기호·아이콘을 붙인다
             "missing_level": "high" if r["missing_rate"] >= 0.30 else
                              ("mid" if r["missing_rate"] >= 0.10 else "ok")}
            for r in page
        ],
        "warnings": ([msg("columns_warn_many", n=total_columns)] if total_columns > 200 else []),
    }


# ── 파생 컬럼 (M1-2) ─────────────────────────────────────────
@app.get("/v1/derive/functions")
def derive_functions() -> dict:
    """수식 편집기 키패드에 쓸 화이트리스트 — 허용 함수는 규칙 DB가 원본이다.

    범위(scope)를 함께 준다: 행 단위는 행마다 값이 달라지고, 컬럼 스칼라는 한 수로 줄어든다.
    """
    from statop.derive.parser import (COLUMN_FUNCS, PAIR_FUNCS, ROW_FUNCS, SET_FUNCS,
                                    ROLE_PAIR_FUNC, ROLE_ROW_FUNC, ROLE_SCALAR_FUNC,
                                    ROLE_SET_FUNC)

    # 구간·자리수는 따로 묶는다 — 가장 자주 쓰는데 행 함수 20개 속에 묻히면 못 찾는다
    binning = ["floor_to", "round_to", "ceil_to", "bin", "round", "trunc"]
    return {"groups": [
        {"role": "binning", "functions": binning},
        {"role": ROLE_ROW_FUNC, "functions": sorted(ROW_FUNCS - set(binning))},
        {"role": ROLE_SCALAR_FUNC, "functions": sorted(COLUMN_FUNCS)},
        {"role": ROLE_SET_FUNC, "functions": sorted(SET_FUNCS)},
        {"role": ROLE_PAIR_FUNC, "functions": sorted(PAIR_FUNCS)},
    ], "scalar_note": msg("derive_scalar_note")}


class DeriveReq(BaseModel):
    session_file: str
    expr: str
    eps: float | None = None
    composition: list[str] | None = None
    sample_n: int = 10_000


@app.post("/v1/derive/preview")
def derive_preview(body: DeriveReq) -> dict:
    """수식 미리보기 (M1-2) — 파싱·eps 추천·±inf 개수까지. **커밋하지 않는다.**

    토큰에 역할이 붙어 오므로 껍데기는 색만 입히면 된다 (F-04) — 어디까지가 행 단위이고
    어디부터가 컬럼 스칼라인지 판단을 웹이 다시 하지 않게 하기 위함.
    """
    from statop.derive.parser import FormulaError, to_latex
    from statop.derive.service import prepare, session_frame

    try:
        _, _, df = session_frame(body.session_file, body.sample_n)
        prep = prepare(df, body.expr, eps=body.eps, composition=body.composition)
    except (FormulaError, ValueError, KeyError) as e:
        raise HTTPException(400, str(e))

    adv = prep.eps_advice
    pv = prep.preview
    return {
        "expr": prep.parsed.expr,
        "latex": to_latex(prep.parsed),   # 입력 문자열이 아니라 계산되는 트리에서 뽑는다
        "tokens": prep.tokens,
        "columns": prep.parsed.columns,
        "functions": prep.parsed.functions,
        "scopes": sorted(prep.parsed.scopes),
        "uses_eps": prep.parsed.uses_eps,
        "result_type": prep.result_type,
        "eps": {"used": prep.eps_used, "auto": prep.eps_auto,
                "recommended": adv.recommended if adv else None,
                "min_positive": adv.min_positive if adv else None,
                "candidates": adv.candidates if adv else [],
                "n_zeros": adv.n_zeros if adv else 0} if adv else None,
        "alternative": prep.alternative,
        "preview": {k: pv[k] for k in
                    ("n", "n_finite", "n_nan", "n_inf", "min", "max", "mean")},
    }


class DeriveCommit(DeriveReq):
    name: str
    as_type: str | None = None


@app.post("/v1/derive/commit")
def derive_commit(body: DeriveCommit) -> dict:
    """파생 컬럼을 세션에 기록 — 수식과 eps가 함께 남아 재생 가능하다."""
    from statop.derive.parser import FormulaError
    from statop.derive.service import commit, prepare, session_frame

    try:
        doc, src, df = session_frame(body.session_file, body.sample_n)
        prep = prepare(df, body.expr, eps=body.eps, composition=body.composition)
        entry = commit(doc, src["id"], df, prep, body.name, body.eps,
                       composition=body.composition, as_type=body.as_type)
    except (FormulaError, ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return {"op_seq": entry["seq"], "name": body.name,
            "expr": prep.parsed.expr, "eps": body.eps,
            "result_type": body.as_type or prep.result_type,
            "notice": msg("derive_recorded", seq=entry["seq"])}


# ── 연산 적합성 (M1-3) ───────────────────────────────────────
def _compat_ctx(session_file: str, sample_n: int):
    from statop.compat import composition_groups
    from statop.derive.evaluate import evaluate
    from statop.derive.parser import parse
    from statop.derive.service import session_frame
    from statop.session.core import replay

    doc, src, df = session_frame(session_file, sample_n)
    st = replay(doc)
    sid = src["id"]
    for d in st["derived"]:        # 파생 컬럼은 파일에 없다 — 기록에서 다시 만든다
        if d.get("source") != sid or d["name"] in df.columns:
            continue
        p = parse(d["expr"], list(df.columns))
        df = df.assign(**{d["name"]: evaluate(p, df, eps=d.get("eps"),
                                              composition=d.get("composition"))})
    cols = [c for c in (st["analysis"].get(sid) or list(df.columns)) if c in df.columns]
    types = st["semantic_types"].get(sid, {})
    return doc, src, df, cols, types, composition_groups(df, cols, types)


def _finding_json(f) -> dict:
    return {"id": f.id, "verdict": f.verdict, "scope": f.scope, "columns": f.columns,
            "why": f.why, "fix": f.fix, "fix_action": f.fix_action,
            "detail": f.detail, "targets": f.targets, "composition": f.composition}


def _report_json(rep) -> dict:
    return {"verdict": rep.verdict, "blocked": rep.blocked,
            "unconfirmed": rep.unconfirmed,
            "findings": [_finding_json(f) for f in rep.findings]}


class CompatReq(BaseModel):
    session_file: str
    op: str
    cols: list[str] | None = None      # 2개를 주면 쌍 판정, 없으면 전체 요약
    sample_n: int = 10_000


@app.post("/v1/compat/check")
def compat_check(body: CompatReq) -> dict:
    """연산 적합성 판정 (M1-3). 쌍은 **명시 지정했을 때만** 본다 .

    의미 타입이 미확정이면 판정하지 않고 보류한다 — 추론값으로 경고하면
    틀린 경고가 쌓인다.
    """
    from statop.compat import OPERATIONS, judge_pair, judge_set

    if body.op not in OPERATIONS:
        raise HTTPException(400, msg("compat_op_unknown",
                                     allowed="|".join(OPERATIONS), op=body.op))
    try:
        _, _, df, cols, types, comp = _compat_ctx(body.session_file, body.sample_n)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))

    if body.cols:
        if len(body.cols) != 2:
            raise HTTPException(400, msg("compat_pair_needs_two"))
        missing = [c for c in body.cols if c not in df.columns]
        if missing:
            raise HTTPException(400, msg("select_err_missing", cols=", ".join(missing)))
        rep = judge_pair(body.op, body.cols[0], body.cols[1], types, df=df, comp_groups=comp)
        return {"scope": "pair", "columns": body.cols, **_report_json(rep)}
    rep = judge_set(body.op, cols, types, df=df, comp_groups=comp)
    return {"scope": "set", "columns": cols, **_report_json(rep)}


class CompatFixReq(CompatReq):
    rule: str
    action: str | None = None          # 제안과 다른 조치를 쓰고 싶을 때
    composition: list[str] | None = None
    reference: str | None = None
    eps: float | None = None
    apply: bool = False                # 기본은 계획만 — 기록은 명시해야 남는다


@app.post("/v1/compat/fix")
def compat_fix(body: CompatFixReq) -> dict:
    """원클릭 수정  — 계획을 돌려주고, apply면 기록한 뒤 **다시 판정한다** ."""
    from statop.compat import FIX_ACTIONS, OPERATIONS, judge_pair, judge_set
    from statop.compat_fix import apply as apply_plan
    from statop.compat_fix import plan as make_plan

    if body.op not in OPERATIONS:
        raise HTTPException(400, msg("compat_op_unknown",
                                     allowed="|".join(OPERATIONS), op=body.op))
    try:
        doc, src, df, cols, types, comp = _compat_ctx(body.session_file, body.sample_n)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))

    pair = body.cols if body.cols and len(body.cols) == 2 else None
    rep = (judge_pair(body.op, pair[0], pair[1], types, df=df, comp_groups=comp) if pair
           else judge_set(body.op, cols, types, df=df, comp_groups=comp))
    found = next((f for f in rep.findings if f.id == body.rule), None)
    if found is None:
        raise HTTPException(400, msg("compat_rule_not_in_report", id=body.rule))
    if body.action:
        if body.action not in FIX_ACTIONS:
            raise HTTPException(400, msg("compat_action_unknown",
                                         allowed="|".join(FIX_ACTIONS), action=body.action))
        found.fix_action = body.action

    try:
        p = make_plan(found, df=df, composition=body.composition, reference=body.reference)
    except ValueError as e:
        raise HTTPException(400, str(e))

    out = {"action": p.action, "derives": p.derives,
           "replaces": [list(x) for x in p.replaces],
           "needs_eps": p.needs_eps, "needs_composition": p.needs_composition,
           "note": p.note, "applied": False}
    if p.needs_composition:
        #  — 세트를 임의로 정하지 않는다. 후보를 돌려주고 사용자가 고른다
        out["candidates"] = comp
        return out
    if not body.apply:
        return out

    try:
        entries = apply_plan(doc, src["id"], df, p, eps=body.eps)
    except ValueError as e:
        raise HTTPException(400, str(e))

    _, _, df2, cols2, types2, comp2 = _compat_ctx(body.session_file, body.sample_n)
    moved = dict(p.replaces)
    again = (judge_pair(body.op, moved.get(pair[0], pair[0]), moved.get(pair[1], pair[1]),
                        types2, df=df2, comp_groups=comp2) if pair
             else judge_set(body.op, cols2, types2, df=df2, comp_groups=comp2))
    out.update(applied=True, op_seq=entries[-1]["seq"], rejudged=_report_json(again))
    return out


# ── 의미 타입 (M1-1) ─────────────────────────────────────────
def _known_types() -> list[str]:
    from statop.semantic_risk import TYPE_RULES

    return sorted(set(TYPE_RULES) | {"continuous", "datetime", "composition set"})


@app.get("/v1/semantic/types")
def semantic_types(session_file: str, sample_n: int = 10_000) -> dict:
    """의미 타입 후보를 **순위로** 돌려준다 (M1-1). 점수는 싣지 않는다 —
    숫자가 보이면 사용자가 그 숫자를 믿고 확정을 건너뛴다."""
    from statop.derive.service import apply_ops, session_frame
    from statop.semantic import infer_columns, shape_label
    from statop.session.core import replay

    try:
        doc, src, df = session_frame(session_file, sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 파생 컬럼은 파일에 없다 — 이걸 안 붙이면 새로 만든 컬럼이 타입 목록에 아예 안 뜬다
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    confirmed = st["semantic_types"].get(src["id"], {})
    selected = [c for c in (st["selected"].get(src["id"]) or list(df.columns))
                if c in df.columns]
    # 방금 만든 파생 컬럼도 확정 대상이다 (선택 목록에는 없지만 분석에는 쓰인다)
    selected += [d["name"] for d in st["derived"]
                 if d.get("source") == src["id"] and d["name"] in df.columns
                 and d["name"] not in selected]

    # 파생 컬럼의 **수식이 유도한 타입**을 1순위 후보로 올린다 (셸과 같은 규칙).
    # 값만 보면 log(x) 는 그냥 연속값이라 continuous 가 1순위로 나온다 — 무엇으로
    # 만들었는지는 수식이 알고 있는데 웹에서는 그걸 안 쓰고 있었다
    hint = {d["name"]: (d.get("result_type"), d["expr"]) for d in st["derived"]
            if d.get("source") == src["id"]}

    items = []
    for t in infer_columns(df, selected):
        cands = [{"rank": c.rank, "type": c.type, "evidence": c.evidence[:3]}
                 for c in t.candidates[:4]]
        h = hint.get(t.column)
        if h and h[0]:
            rest = [c for c in cands if c["type"] != h[0]]
            cands = [{"rank": 1, "type": h[0],
                      "evidence": [msg("ev_from_formula", expr=h[1])]},
                     *[{**c, "rank": i + 2} for i, c in enumerate(rest)]]
        items.append({
            "column": t.column,
            "shape": t.shape, "shape_label": shape_label(t.shape),
            "confirmed": confirmed.get(t.column),
            "needs_confirm": ((t.needs_confirm or bool(h))
                              and t.column not in confirmed),
            "confirm_reason": t.confirm_reason,
            "conflicts": t.conflicts,
            "candidates": cands,
        })
    return {"items": items, "known_types": _known_types(),
            "n_confirmed": sum(1 for i in items if i["confirmed"]),
            "n_pending": sum(1 for i in items if not i["confirmed"])}


class ConfirmType(BaseModel):
    session_file: str
    column: str
    type: str
    sample_n: int = 10_000


@app.post("/v1/semantic/confirm")
def semantic_confirm(body: ConfirmType) -> dict:
    """의미 타입 확정. **추론에 없던 타입도 막지 않는다** — 대신 그 타입으로 계산할 때
    무엇이 틀어지는지 규칙 DB에서 가져와 함께 돌려준다 (요구사항-7)."""
    from statop.derive.service import apply_ops, session_frame
    from statop.semantic import infer_columns
    from statop.semantic_risk import risks_for
    from statop.session.core import append_op, save_session

    known = _known_types()
    if body.type not in known:
        raise HTTPException(400, msg("semantic_unknown_type", type=body.type,
                                     allowed=", ".join(known)))
    try:
        doc, src, df = session_frame(body.session_file, body.sample_n)
        # 파생 컬럼은 파일에 없다 — 이걸 안 붙이면 방금 만든 컬럼을 확정하려 할 때
        # "파일에 없는 컬럼"이라고 거절한다 (실제로 그랬다)
        df = apply_ops(df, doc, src["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.column not in df.columns:
        raise HTTPException(400, msg("select_err_missing", cols=body.column))

    inferred = {c.type for t in infer_columns(df, [body.column]) for c in t.candidates}
    entry = append_op(doc, "semantic_confirm", source=src["id"],
                      column=body.column, type=body.type)
    save_session(doc)
    return {"column": body.column, "type": body.type, "op_seq": entry["seq"],
            "was_inferred": body.type in inferred,
            "notice": None if body.type in inferred else msg("semantic_not_inferred",
                                                             type=body.type),
            "risks": risks_for(body.type)}


class UnconfirmType(BaseModel):
    session_file: str
    column: str


@app.post("/v1/semantic/unconfirm")
def semantic_unconfirm(body: UnconfirmType) -> dict:
    """확정 취소 — 잘못 확정했을 때 되돌릴 길 (기록은 지우지 않고 취소를 남긴다)."""
    from statop.session.core import (append_op, load_session, main_source, replay,
                                   save_session)

    try:
        doc = load_session(body.session_file)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e))
    src = main_source(doc)
    if src is None:
        raise HTTPException(400, msg("select_err_empty"))
    if body.column not in replay(doc)["semantic_types"].get(src["id"], {}):
        raise HTTPException(400, msg("semantic_not_confirmed", column=body.column))
    entry = append_op(doc, "semantic_unconfirm", source=src["id"], column=body.column)
    save_session(doc)
    return {"column": body.column, "op_seq": entry["seq"],
            "notice": msg("semantic_unconfirmed", column=body.column)}


class UnconfirmType(BaseModel):
    session_file: str
    column: str


@app.post("/v1/semantic/unconfirm")
def semantic_unconfirm(body: UnconfirmType) -> dict:
    """확정 취소 — 잘못 확정했을 때 되돌릴 길 (기록은 지우지 않고 취소를 남긴다)."""
    from statop.session.core import (append_op, load_session, main_source, replay,
                                   save_session)

    try:
        doc = load_session(body.session_file)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e))
    src = main_source(doc)
    if src is None:
        raise HTTPException(400, msg("select_err_empty"))
    if body.column not in replay(doc)["semantic_types"].get(src["id"], {}):
        raise HTTPException(400, msg("semantic_not_confirmed", column=body.column))
    entry = append_op(doc, "semantic_unconfirm", source=src["id"], column=body.column)
    save_session(doc)
    return {"column": body.column, "op_seq": entry["seq"],
            "notice": msg("semantic_unconfirmed", column=body.column)}


# ── 가드레일 (M4) ────────────────────────────────────────────
def _guard_materials(session_file: str, sample_n: int):
    """손실 검사의 재료 — 세션 기록에서 조작 전후를 다시 만든다."""
    from statop.derive.evaluate import evaluate
    from statop.derive.parser import parse
    from statop.derive.service import session_frame
    from statop.missing import drop_na
    from statop.rowfilter import apply_filter
    from statop.session.core import load_session, replay

    doc, src, df0 = session_frame(session_file, sample_n)
    st = replay(load_session(session_file))
    steps, cur = [], df0
    for op in doc["ops"]:
        if op["op"] == "filter_rows":
            before = len(cur)
            cur = apply_filter(cur, op["expr"], keep=op.get("keep", True))
            steps.append({"label": f"filter #{op['seq']}", "n_before": before,
                          "n_after": len(cur)})
        elif op["op"] == "missing_drop":
            before = len(cur)
            cur = drop_na(cur, op.get("cols"), how=op.get("how", "row"))
            steps.append({"label": f"missing_drop #{op['seq']}", "n_before": before,
                          "n_after": len(cur)})
    for d in st["derived"]:
        if d.get("source") != src["id"] or d["name"] in cur.columns:
            continue
        p = parse(d["expr"], list(cur.columns))
        cur = cur.assign(**{d["name"]: evaluate(p, cur, eps=d.get("eps"),
                                                composition=d.get("composition"))})
    return doc, src, df0, cur, steps, st


class GuardReq(BaseModel):
    session_file: str
    group: str | None = None
    meta: list[str] = []
    metrics: list[str] = []
    expected_ratio: dict[str, float] | None = None
    sample_n: int = 10_000


@app.post("/v1/guard/run")
def guard_run(body: GuardReq) -> dict:
    """가드레일 전체 (M4) — GR-03 → GR-02 → GR-04 → GR-01.

    차단이 있으면 headline이 채워진다. 껍데기는 그것을 **맨 앞에** 그려야 한다.
    """
    from statop.guard.pipeline import run
    from statop.guard.report import to_dict

    try:
        _, src, df0, cur, steps, st = _guard_materials(body.session_file, body.sample_n)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))

    rep = run(cur, st["semantic_types"].get(src["id"], {}), group_col=body.group,
              meta_cols=body.meta, metric_cols=body.metrics,
              df_before=df0 if steps else None,
              kept_index=cur.index if steps else None,
              retention_steps=steps, expected_ratio=body.expected_ratio)
    return to_dict(rep)


@app.get("/v1/guard/limits")
def guard_limits() -> dict:
    """지금 적용되는 임계값 — 기준값·조정 여부·완화 하한을 함께 ."""
    from statop.guard import locks

    return {"order": locks.execution_order(),
            "overrides_path": str(locks.overrides_path()),
            "rules": [{
                "rule": r, "floor": locks.floor(r), "base_tier": locks.base_tier(r),
                "limits": [{"key": k, "value": v.value, "base": v.base,
                            "overridden": v.overridden}
                           for k, v in locks.limits(r).items()],
            } for r in locks.execution_order()]}


class GuardSet(BaseModel):
    rule: str
    tier: str | None = None
    key: str | None = None
    value: object = None


@app.post("/v1/guard/limits")
def guard_set(body: GuardSet) -> dict:
    """임계값·등급 조정. **완화 하한 아래는 거부한다**  — 예외 경로가 없다."""
    from statop.guard import locks

    if not body.tier and not body.key:
        raise HTTPException(400, msg("guard_set_needs_target"))
    try:
        if body.tier:
            locks.set_tier(body.rule, body.tier)
        if body.key:
            if body.value is None:
                raise HTTPException(400, msg("guard_set_needs_value"))
            locks.set_threshold(body.rule, body.key, body.value)
    except locks.LockError as e:
        raise HTTPException(400, str(e))
    return {"rule": body.rule, "tier": locks.tier_of(body.rule),
            "limits": [{"key": k, "value": v.value, "base": v.base,
                        "overridden": v.overridden}
                       for k, v in locks.limits(body.rule).items()]}


@app.get("/v1/sessions/resolve")
def resolve_session(session_id: str) -> dict:
    """세션 ID로 파일을 찾는다 — 웹 주소를 짧게 유지하기 위한 것.

    전체 경로를 주소에 넣으면 터미널에서 줄바꿈돼 Ctrl+클릭이 안 먹는다.
    작업 중(tmp)과 저장본(sessions) 양쪽을 본다.
    """
    from statop.store import sessions_dir, tmp_dir

    for d in (tmp_dir(), sessions_dir()):
        for f in d.glob("*.json"):
            try:
                if json.loads(f.read_text()).get("session_id") == session_id:
                    return {"session_id": session_id, "session_file": str(f)}
            except (OSError, ValueError):
                continue
    raise HTTPException(404, msg("session_resolve_not_found", id=session_id))


@app.get("/v1/sessions/state")
def session_state(session_file: str) -> dict:
    """반영 전 가벼운 확인 — view(마지막 저장된 화면 상태)와 조작 개수만.

    전체 재생 없이 읽으므로 자주 불러도 부담이 없다.
    """
    from statop.session.core import peek_state

    try:
        return peek_state(session_file)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e))


class ViewSave(BaseModel):
    session_file: str
    by: str                     # "web" | "cli"
    step: str
    picked: list[str] = []


@app.post("/v1/sessions/view")
def save_view_state(body: ViewSave) -> dict:
    """화면 상태 저장 — **저장한 쪽이 있어야 반영할 것이 생긴다** (동기화 키)."""
    from statop.session.core import save_view

    try:
        return save_view(body.session_file, body.by, body.step, body.picked)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e))


# ── 모듈 A (A1~A3 + 실행) ────────────────────────────────────
class SpecReq(BaseModel):
    session_file: str
    question: str
    y: str
    group: str | None = None
    event: str | None = None
    by: str | None = None
    subject: str | None = None
    weights: str | None = None
    paired: bool = False
    direction: str = "two-sided"
    contrast: str = "all-pairs"
    control: str | None = None
    n_tests: int = 1
    apply: bool = False
    sample_n: int = 10_000


@app.get("/v1/analyze/questions")
def analyze_questions() -> dict:
    from statop.analyze.spec import questions

    return {"questions": questions()}


@app.post("/v1/analyze/plan")
def analyze_plan(body: SpecReq) -> dict:
    """A1 질문 설계 — 적합성 자동 판정과 후보(A2)까지 한 번에.

    기본은 미리보기. apply=true 여도 문제(problems)가 있으면 기록하지 않는다.
    """
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import Spec, build, record

    spec = Spec(question=body.question, y=body.y, group=body.group, event=body.event,
                by=body.by, subject=body.subject, weights=body.weights,
                paired=body.paired, direction=body.direction,
                contrast=body.contrast, control=body.control, n_tests=body.n_tests)
    try:
        res = build(body.session_file, spec, sample_n=body.sample_n)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))

    cands = [] if res.problems else [c.__dict__ for c in shortlist(res)]
    recorded = False
    if body.apply and not res.problems:
        record(body.session_file, spec)
        recorded = True
    return _pynative({
        "spec": spec.as_dict(), "y_type": res.y_type, "group_type": res.group_type,
        "group_levels": res.group_levels, "compat": res.compat,
        "problems": res.problems, "candidates": cands, "recorded": recorded,
        "missing": res.missing, "n_rows": res.n_rows, "n_complete": res.n_complete,
        "repeat_candidates": res.repeat_candidates})


@app.get("/v1/missing")
def missing_show(session_file: str, sample_n: int = 10_000) -> dict:
    """결측 현황과 패턴 — 무엇을 대치할지 정하려면 먼저 보여야 한다."""
    from statop.derive.service import apply_ops, session_frame
    from statop.missing import report

    try:
        doc, src, df = session_frame(session_file, sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    df = apply_ops(df, doc, src["id"])
    rep = report(df)
    return _pynative({"n_rows": rep.n_rows, "columns": rep.columns,
                      "patterns": rep.patterns})


class ImputeReq(BaseModel):
    session_file: str
    method: str
    cols: list[str]
    group_by: str | None = None
    seed: int = 0
    apply: bool = False
    sample_n: int = 10_000


@app.post("/v1/missing/impute")
def missing_impute(body: ImputeReq) -> dict:
    """경량 대치 — 허용 목록 밖은 실행하지 않는다. apply 전에는 미리보기."""
    from statop.derive.service import apply_ops, session_frame
    from statop.missing import impute
    from statop.session.core import append_op, save_session

    try:
        doc, src, df = session_frame(body.session_file, body.sample_n)
        df = apply_ops(df, doc, src["id"])
        _, info = impute(df, body.method, body.cols, group_by=body.group_by,
                         seed=body.seed)
    except (ValueError, ImportError) as e:
        raise HTTPException(400, str(e))

    out = {"method": body.method, "cols": body.cols, "n_filled": info["n_filled"],
           "ratio": info["ratio_filled"], "warnings": info["warnings"],
           "params": info["params"], "seed": info["seed"], "recorded": False}
    if body.apply:
        append_op(doc, "impute", source=src["id"], method=body.method,
                  cols=body.cols, group_by=body.group_by, seed=info["seed"],
                  params=info["params"], n_filled=info["n_filled"])
        save_session(doc)
        out["recorded"] = True
    return _pynative(out)


class DropReq(BaseModel):
    session_file: str
    cols: list[str] | None = None
    how: str = "row"
    apply: bool = False
    sample_n: int = 10_000


@app.post("/v1/missing/drop")
def missing_drop(body: DropReq) -> dict:
    """결측 행/열 제거 — 몇 행이 사라지는지 먼저 보여준다."""
    from statop.derive.service import apply_ops, session_frame
    from statop.missing import drop_na
    from statop.session.core import append_op, save_session

    try:
        doc, src, df = session_frame(body.session_file, body.sample_n)
        df = apply_ops(df, doc, src["id"])
        kept = drop_na(df, body.cols or None, how=body.how)
    except ValueError as e:
        raise HTTPException(400, str(e))

    out = {"before": len(df), "after": len(kept), "removed": len(df) - len(kept),
           "how": body.how, "cols": body.cols, "recorded": False}
    if body.apply:
        append_op(doc, "missing_drop", source=src["id"], cols=body.cols or [],
                  how=body.how, n_removed=len(df) - len(kept))
        save_session(doc)
        out["recorded"] = True
    return _pynative(out)


def _pynative(x):  # noqa: ANN001, ANN202
    """numpy 스칼라를 파이썬 기본형으로 — REST 직렬화가 numpy.int64 에서 터진다."""
    import numpy as np

    if isinstance(x, dict):
        return {str(k): _pynative(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_pynative(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    return x


@app.get("/v1/analyze/checks")
def analyze_checks(session_file: str, sample_n: int = 10_000) -> dict:
    """A3 가정 검사 — **클릭할 때만** 계산하고( 지연 렌더) 세션 내 캐시한다."""
    from statop.api import cache
    from statop.session.core import load_session

    p = Path(session_file)
    if not p.exists():
        raise HTTPException(404, msg("path_not_exist"))
    # 캐시 키: 세션 파일 상태 — 조작이 추가되면 mtime이 바뀌어 자동 무효화된다
    key = ("a3", str(p.resolve()), p.stat().st_mtime_ns, sample_n)
    hit = cache.get(key)
    if hit is not None:
        return {**hit, "cached": True}

    from statop.analyze.checks import run_checks

    try:
        results = run_checks(session_file, sample_n=sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    out = {"checks": [_pynative({"id": r.id, "name": r.name, "verdict": r.verdict,
                                 "summary": r.summary, "per_group": r.per_group,
                                 "cause": r.cause, "numbers": r.numbers,
                                 "plot": r.plot})
                      for r in results], "cached": False}
    cache.put(key, out)
    return out


class RunReq(BaseModel):
    session_file: str
    test: str
    sample_n: int = 10_000


@app.post("/v1/analyze/run")
def analyze_run(body: RunReq) -> dict:
    """S152 검정 실행 — 효과크기·CI·보정 α 비교를 항상 동반한다 ( 전/후 병기)."""
    from dataclasses import asdict

    from statop.analyze.points import both_ways

    try:
        both = both_ways(body.session_file, body.test, sample_n=body.sample_n)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    r = both["after"]
    # : 제외가 있으면 전/후를 **항상 함께** 내보낸다. 후만 보면 숨길 수 있다
    b = both["before"]
    extra = {"exclusion": {**asdict(both["status"]), "flipped": both["flipped"],
                           "alpha": both["alpha"],
                           "before": None if b is None else
                           {"statistic": b.statistic, "p": b.p, "effect": b.effect,
                            "n": b.n}}}
    # 그 검정이 요구하는 가정을 결과와 **함께** 준다 — 따로 눌러야 보이면 안 본다.
    # TUI 와 같은 계산·같은 문구를 쓰므로 양쪽 화면이 갈리지 않는다
    from statop.analyze.checks import checks_for_test

    try:
        assumptions = [{"id": c.id, "name": c.name, "verdict": c.verdict,
                        "summary": c.summary,
                        "action": (c.numbers or {}).get("action")}
                       for c in checks_for_test(body.session_file, body.test,
                                                body.sample_n)]
    except (ValueError, KeyError):
        assumptions = []
    return _pynative({"id": r.id, "name": r.name, "statistic": r.statistic, "p": r.p,
                      "effect": r.effect, "n": r.n, "direction": r.direction,
                      "notes": r.notes, "strata": r.strata,
                      "assumptions": assumptions,
                      "assumptions_head": msg("a3_auto_head", n=len(assumptions)),
                      **extra})


@app.get("/v1/points")
def points_get(session_file: str, sample_n: int = 10_000) -> dict:
    """검정이 실제로 본 개별 점 — 그림에 찍고 하나를 골라 뺄 수 있게 ."""
    from dataclasses import asdict

    from statop.analyze.points import collect

    try:
        p = collect(session_file, sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _pynative(asdict(p))


class ExcludeReq(BaseModel):
    session_file: str
    key_column: str
    key: str
    note: str = ""
    restore: bool = False


@app.post("/v1/points/exclude")
def points_exclude(body: ExcludeReq) -> dict:
    """개별 샘플 제외/되돌리기 — 뺄 때는 사유가 있어야 한다."""
    from statop.analyze.points import exclude, include

    try:
        entry = (include(body.session_file, body.key_column, body.key) if body.restore
                 else exclude(body.session_file, body.key_column, body.key, body.note))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"seq": entry["seq"], "key": body.key, "restored": body.restore}


@app.get("/v1/metrics")
def metrics_get(session_file: str, sample_n: int = 10_000) -> dict:
    """S170 보조·가드레일 지표 자동 병기 제안 — 계산 가능한 것은 값까지."""
    from dataclasses import asdict

    from statop.analyze.metrics import apply_choices, compute, suggest, with_custom

    try:
        # 규칙표 추천 + **내가 더한 추천**, 그리고 저장해 둔 선택 반영
        panel = apply_choices(with_custom(suggest(session_file, sample_n)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 제목 문구도 서버가 준다 — 화면마다 다르게 쓰면 같은 기능인 줄 모른다
    out = {"goal": panel.goal, "triad": panel.triad, "support": [], "guardrail": [],
           "head": {"support": msg("metrics_head_support"),
                    "guardrail": msg("metrics_head_guardrail"),
                    "triad": msg("metrics_head_triad"),
                    "none": msg("metrics_none")}}
    for role in ("support", "guardrail"):
        for sug in getattr(panel, role):
            d = asdict(sug)
            if sug.computable:
                # 값이 안 나오는 이유도 정보다 — 조용히 빈칸으로 두지 않는다
                try:
                    d["value"] = compute(session_file, sug.id, sample_n)
                except (ValueError, KeyError) as e:
                    d["error"] = str(e)
            out[role].append(d)
    return _pynative(out)


class TableDiffReq(BaseModel):
    a: str
    b: str
    key: str | None = None
    columns: list[str] | None = None
    show_values: bool = False


@app.post("/v1/tablediff")
def tablediff(body: TableDiffReq) -> dict:
    """S032 표 상세 대조 — 전체 읽기라 **명시 호출 전용**. 자동으로 돌지 않는다."""
    from dataclasses import asdict

    from statop.integrity import compare_tables

    try:
        r = compare_tables(body.a, body.b, key=body.key, columns=body.columns,
                           show_values=body.show_values)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return _pynative(asdict(r))


@app.get("/v1/find")
def find_get(q: str, limit: int = 30) -> dict:
    """지표·검정 통합 검색 — 어느 목록·어느 질문 유형에 있는지까지."""
    from dataclasses import asdict

    from statop.analyze.find import search

    try:
        return _pynative(asdict(search(q, limit)))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/v1/model/leak")
def model_leak(session_file: str, sample_n: int = 50_000) -> dict:
    """B2 누수·중복 검사 — 전부 Gate (~)."""
    from dataclasses import asdict

    from statop.modeling.leak import run_all
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in run_all(spec, sample_n)]
    return _pynative({"findings": findings,
                      "head": msg("mb_leak_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/code")
def model_code(path: str) -> dict:
    """B2 코드 정적 감지 — 나누기 전에 학습한 전처리·피처선택 (, MB-C04/C09).

    코드를 읽기만 한다 — 실행하지 않는다."""
    from dataclasses import asdict

    from statop.modeling.code_audit import audit_code

    findings = [asdict(f) for f in audit_code(path)]
    return _pynative({"findings": findings,
                      "head": msg("mb_code_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/split")
def model_split(session_file: str, key: str | None = None,
                expect: str | None = None, source: str | None = None,
                meta: str | None = None, sample_n: int = 50_000) -> dict:
    """B2 세트 비율·손실 검사 — MB-C06(GR-02) · MB-C07(GR-03) ."""
    from dataclasses import asdict

    from statop.modeling.spec import current
    from statop.modeling.split_audit import key_from_session, run_all
    from statop.session.core import load_session, main_source

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    if not source:
        src = main_source(load_session(session_file))
        source = src["path"] if src else None
    # 의미 타입에서 이미 확정한 행 식별자를 쓴다 — 화면이 같은 것을 또 묻지 않게
    key = key or key_from_session(session_file)
    try:
        ratio = ({k.strip(): float(v) for k, v in
                  (x.split("=") for x in expect.split(",") if x.strip())}
                 if expect else None)
    except ValueError:
        raise HTTPException(400, msg("labels_map_format"))

    findings = [asdict(f) for f in
                run_all(spec, source, key, ratio,
                        [c.strip() for c in meta.split(",")] if meta else None,
                        sample_n)]
    return _pynative({"findings": findings, "head": msg("mb_split_head"),
                      "key": key,
                      "key_note": msg("mb_key_auto", col=key) if key else msg("mb_key_none"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/balance")
def model_balance(session_file: str, meta: str | None = None,
                  sample_n: int = 50_000) -> dict:
    """B4 균형·분포 진단 — 클래스 비율·숨은 불균형·세트 간 분포 ."""
    from dataclasses import asdict

    from statop.modeling.balance import run_all
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in
                run_all(spec, [c.strip() for c in meta.split(",")] if meta else None,
                        sample_n)]
    return _pynative({"findings": findings, "head": msg("mb_balance_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/triad")
def model_triad(session_file: str, sample_n: int = 50_000) -> dict:
    """S194b MB-Q별 3-metric 트리아드 (MB-C24)."""
    from dataclasses import asdict

    from statop.modeling.spec import current
    from statop.modeling.triad import recommend

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(recommend(spec, sample_n))]
    return _pynative({"findings": findings, "head": msg("mb_triad_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/report")
def model_report(session_file: str, key: str | None = None,
                 source: str | None = None, meta: str | None = None,
                 sample_n: int = 50_000) -> dict:
    """S194c B6 출력 — 감사 전체 + 재현 명령. 화면은 md 를 그대로 보인다."""
    from statop.modeling.report import collect, to_markdown

    try:
        rep = collect(session_file, source_path=source, key=key,
                      meta_cols=[c.strip() for c in meta.split(",")] if meta else None,
                      sample_n=sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _pynative({"markdown": to_markdown(rep), "snippet": rep.snippet,
                      "triad": rep.triad,
                      "counts": {"gate": len(rep.gates),
                                 "diagnostic": len(rep.diagnostics),
                                 "skipped": len(rep.skipped)}})


@app.get("/v1/model/specific")
def model_specific(session_file: str, sample_n: int = 50_000) -> dict:
    """S194 모델특유 검사 (MB-C28~C31, T0)."""
    from dataclasses import asdict

    from statop.modeling.spec import current
    from statop.modeling.specific import run_all

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in run_all(spec, sample_n)]
    return _pynative({"findings": findings, "head": msg("mb_specific_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/repro")
def model_repro(session_file: str) -> dict:
    """S192· 지표 변경·재현성 감사 (MB-C21 · C25~C27)."""
    from dataclasses import asdict

    from statop.modeling.repro import run_all
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in run_all(spec, session_file)]
    return _pynative({"findings": findings, "head": msg("mb_repro_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/seed")
def model_seed(session_file: str) -> dict:
    """재현용 seed 고정 코드 — 화면에서 복사해 쓰게 문자열로 준다 (MB-C25)."""
    from statop.modeling.repro import seed_script
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    return {"code": seed_script(spec, session_file)}


@app.get("/v1/model/eval")
def model_eval(session_file: str, sample_n: int = 50_000) -> dict:
    """B5 평가 감사 — probability 로 확정된 컬럼이 있어야 열린다 ."""
    from dataclasses import asdict

    from statop.modeling.evaluate import run_all
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in run_all(spec, session_file, sample_n)]
    return _pynative({"findings": findings, "head": msg("mb_eval_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/prep")
def model_prep(session_file: str, sample_n: int = 50_000) -> dict:
    """B5 전처리·모델 적합 — 표준화·차원축소·EPV ."""
    from dataclasses import asdict

    from statop.modeling.prep import run_all
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in run_all(spec, sample_n)]
    return _pynative({"findings": findings, "head": msg("mb_prep_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/compare")
def model_compare(models: str) -> dict:
    """S190a 모델 비교 가능 여부 — 모델은 줄바꿈으로 구분해 보낸다 (MB-C21)."""
    from dataclasses import asdict

    from statop.modeling.compare import Model, audit

    try:
        items = [Model.parse(m) for m in models.splitlines() if m.strip()]
    except (ValueError, IndexError):
        raise HTTPException(400, msg("mb_compare_bad_model"))
    findings = [asdict(audit(items))]
    return _pynative({"findings": findings, "head": msg("mb_compare_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/model/shift")
def model_shift(session_file: str, columns: str, key: str = "",
                source: str | None = None) -> dict:
    """결측정리 전/후 분포 — 판정이 지목한 컬럼을 눌렀을 때 (, MB-C07).

    그림은 코어가 문자열로 만든다 — CLI·TUI·웹이 같은 것을 본다 ."""
    from statop.modeling.spec import current
    from statop.modeling.split_audit import key_from_session, shift_view
    from statop.session.core import load_session, main_source

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    key = key or key_from_session(session_file)
    if not source:
        src = main_source(load_session(session_file))
        source = src["path"] if src else None
    out = []
    for col in [c.strip() for c in columns.split(",") if c.strip()]:
        try:
            v = shift_view(spec, source, key, col)
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        out.append({"column": col, "kind": v["info"]["kind"], "lines": v["lines"]})
    return _pynative({"head": msg("mb_shift_head"), "views": out})


@app.get("/v1/model/labels")
def model_labels(session_file: str, sample_n: int = 50_000) -> dict:
    """B3 라벨 인코딩 방향·매핑 — MB-C13 . 편집은 /v1/labels/map 이다."""
    from dataclasses import asdict

    from statop.modeling.label_audit import label_audit
    from statop.modeling.spec import current

    spec = current(session_file)
    if spec is None:
        raise HTTPException(400, msg("mb_need_spec"))
    findings = [asdict(f) for f in label_audit(spec, session_file, sample_n)]
    return _pynative({"findings": findings, "head": msg("mb_c13_head"),
                      "n_failed": sum(1 for f in findings if f["verdict"] == "fail")})


@app.get("/v1/find/questions")
def find_questions() -> dict:
    """질문 유형 11종과 그 아래 검정 — 이름을 몰라도 갈래로 찾아 들어가게."""
    from statop.analyze.find import by_question

    return _pynative({"questions": by_question()})


@app.get("/v1/scores")
def scores_get(session_file: str, grade: str | None = None,
               family: str | None = None, sample_n: int = 10_000) -> dict:
    """S167 점수 목록 + 4등급 ·  수식·대입식."""
    from dataclasses import asdict

    from statop.analyze.scores import catalog

    try:
        rows = catalog(session_file, sample_n, family=family)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if grade:
        rows = [r for r in rows if r.verdict == grade]
    # 지금 무엇이 Goal 인지 같이 준다 — 목록에서 바로 바꿀 수 있어야 하므로
    # 화면이 "지금 무엇인지"를 알아야 한다
    from statop.session.core import load_session, replay

    goal = replay(load_session(session_file)).get("metric_goal") or None
    return _pynative({"scores": [asdict(r) for r in rows],
                      "goal": goal,
                      "unset_meaning": msg("scores_unset_meaning")})


@app.get("/v1/hypothesis/references")
def hypothesis_references(session_file: str, limit: int = 5,
                          include_labels: bool = True) -> dict:
    """A6 논문 앵커 . 나가는 것은 검정 이름·질문 유형·군 라벨뿐이다."""
    from dataclasses import asdict

    from statop.hypothesis.refs import build

    a = build(session_file, limit=limit, include_labels=include_labels)
    return _pynative({
        **asdict(a),
        "papers": [{**asdict(p), "url": p.url} for p in a.papers],
        "head": msg("refs_head"), "privacy": msg("refs_privacy"),
        "title_only": msg("refs_title_only"),
        "broadened_note": msg("refs_broadened") if a.broadened else "",
        "none": msg("refs_none") if not a.papers and not a.failed else "",
    })


@app.get("/v1/robust")
def robust_get(session_file: str, draws: int = 200, seed: int = 0,
               sample_n: int = 10_000) -> dict:
    """강건성 — 지금 낸 결론을 표본·이상치·다른 검정으로 흔들어 본다."""
    from dataclasses import asdict

    from statop.analyze.robust import build, verdict

    try:
        rep = build(session_file, draws=draws, seed=seed, sample_n=sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    band = msg("robust_band", lo=rep.boot_q["p5"], hi=rep.boot_q["p95"],
               q25=rep.boot_q["p25"], q75=rep.boot_q["p75"],
               n=len(rep.boot)) if rep.boot_q else ""
    return _pynative({
        **{k: v for k, v in asdict(rep).items() if k != "boot"},
        "boot_n": len(rep.boot),
        "base": msg("robust_base", test=rep.test, name=rep.name, eff=rep.effect_name,
                    value=rep.effect, p=rep.p, n=rep.n_rows),
        "band": band,
        "heads": {"boot": msg("robust_boot_head", draws=rep.draws, seed=rep.seed),
                  "outlier": msg("robust_outlier_head"),
                  "choice": msg("robust_choice_head"),
                  "read": msg("robust_read_head")},
        "caveat": msg("robust_caveat"),
        # ①의 폭은 위에 이미 있다 — 읽는 법에서 두 번 적지 않는다
        "verdict": [x for x in verdict(rep) if x != band],
    })


@app.get("/v1/represent")
def represent_get(session_file: str, cols: str | None = None, metric: str = "ks",
                  threshold: float = 0.05, repeats: int = 20, seed: int = 0,
                  steps: int = 10, sample_n: int = 1_000_000) -> dict:
    """Q-12 부분표집 곡선  — 답이 p 값이 아니라 n 이다."""
    from dataclasses import asdict

    from statop.analyze.represent import KS, W1, build, statement

    want = {"ks": KS, "wasserstein": W1, "w1": W1}.get(metric.lower())
    if want is None:
        raise HTTPException(400, msg("represent_bad_metric", got=metric))
    picked = [c.strip() for c in cols.split(",")] if cols else None
    try:
        rep = build(session_file, picked, metric=want, threshold=threshold,
                    repeats=repeats, seed=seed, steps=steps, sample_n=sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    head, how = statement(rep)
    return _pynative({
        **asdict(rep),
        "hypothesis": head, "hypothesis_how": how,
        "repeats_note": msg("represent_repeats", r=rep.repeats, seed=rep.seed),
        "skipped_note": (msg("represent_skipped_ids", cols=", ".join(rep.skipped_ids))
                         if rep.skipped_ids else ""),
        "threshold_note": msg("represent_threshold_convention", th=threshold),
        "unit_bound": msg("represent_unit_bound") if want == W1 else "",
    })


@app.get("/v1/represent/spread")
def represent_spread(session_file: str, n: int, cols: str | None = None,
                     metric: str = "ks", draws: int = 200, seed: int = 0,
                     threshold: float = 0.05, sample_n: int = 1_000_000) -> dict:
    """한 n 에서 다시 뽑을 때마다 나온 **거리들의 분포** — 임계를 감으로 잡지 않게."""
    from dataclasses import asdict

    from statop.analyze.represent import KS, W1, spread

    want = {"ks": KS, "wasserstein": W1, "w1": W1}.get(metric.lower())
    if want is None:
        raise HTTPException(400, msg("represent_bad_metric", got=metric))
    picked = [c.strip() for c in cols.split(",")] if cols else None
    try:
        sps = spread(session_file, n, picked, metric=want, draws=draws, seed=seed,
                     sample_n=sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _pynative({
        "n": n,
        "spreads": [{**asdict(sp),
                     "summary": msg("represent_spread_q", col=sp.column,
                                    metric=sp.metric_name, **sp.q),
                     "suggest": msg("represent_spread_suggest", col=sp.column,
                                    p95=sp.q["p95"], th=threshold)} for sp in sps],
        "head": msg("represent_spread_head", n=n,
                    draws=sps[0].draws if sps else draws),
        "why": msg("represent_spread_why"),
    })


@app.get("/v1/represent/check")
def represent_check(session_file: str, n: int, cols: str | None = None,
                    seed: int = 0, sample_n: int = 1_000_000) -> dict:
    """T-1204 — 뽑은 n 행 vs 남은 행. 전체와 대조하지 않는다."""
    from dataclasses import asdict

    from statop.analyze.represent import verify

    picked = [c.strip() for c in cols.split(",")] if cols else None
    try:
        rows = verify(session_file, n, picked, seed=seed, sample_n=sample_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    def _line(r) -> str:  # noqa: ANN001
        if r.p is not None and r.p < 0.05:
            return msg("represent_verify_p_small", col=r.column, p=r.p,
                       d=r.distance)
        if r.p is not None:
            return msg("represent_verify_p", col=r.column, d=r.distance, p=r.p)
        return msg("represent_verify_line", col=r.column, d=r.distance,
                   metric=r.metric)

    return _pynative({
        "rows": [{**asdict(r), "line": _line(r)} for r in rows],
        "not_full_note": msg("represent_verify_not_full"),
        "p_note": msg("represent_verify_p_note"),
    })


@app.get("/v1/scores/groups")
def scores_groups(session_file: str, family: str | None = None,
                  sample_n: int = 10_000) -> dict:
    """S058b 대안 묶음 — 같은 것을 재는 지표를 묶어 보여준다. 고르는 것은 사용자다."""
    from dataclasses import asdict

    from statop.analyze.scores import groups

    try:
        gs = groups(session_file, sample_n, family=family)
    except ValueError as e:
        raise HTTPException(400, str(e))
    flat = [e for g in gs for e in g.entries]
    return _pynative({
        "groups": [asdict(g) for g in gs],
        "shaken_note": msg("scores_shaken_note"),
        "pick_one": msg("scores_pick_one"),
    })


@app.get("/v1/scores/entropy")
def scores_entropy(session_file: str, column: str, sample_n: int = 10_000) -> dict:
    """S169 분포 의존 분기 — 어느 공식을 쓰고 무엇을 왜 버렸는지."""
    from dataclasses import asdict

    from statop.analyze.scores import entropy_branch

    try:
        return _pynative(asdict(entropy_branch(session_file, column, sample_n)))
    except ValueError as e:
        raise HTTPException(400, str(e))


class GoalReq(BaseModel):
    session_file: str
    score: str | None = None
    test: str | None = None
    effect_key: str | None = None
    name: str | None = None      # 검정으로 지정할 때 — 이름이 없으면 ID 만 남는다


@app.post("/v1/metrics/goal")
def metrics_goal(body: GoalReq) -> dict:
    """S171 Goal 지표 지정 — 사용자가 정한다."""
    from statop.analyze.metrics import set_goal

    try:
        entry = set_goal(body.session_file, score=body.score, test=body.test,
                         effect_key=body.effect_key, name=body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _pynative({"seq": entry["seq"], "score": entry.get("score"),
                      "test": entry.get("test"), "name": entry.get("name")})


class ExploreRun(BaseModel):
    session_file: str
    question: str
    columns: list[str]
    test: str
    sample_n: int = 10_000


@app.get("/v1/explore")
def explore_get(session_file: str, question: str, columns: str,
                sample_n: int = 10_000) -> dict:
    """지표 찾기  — 이 질문·이 컬럼에 **쓸 수 있는 것들**. 값은 아직 안 낸다."""
    from dataclasses import asdict

    from statop.analyze.explore import find

    cols = [c.strip() for c in columns.split(",") if c.strip()]
    try:
        return _pynative(asdict(find(session_file, question, cols, sample_n)))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


class PowerReq(BaseModel):
    session_file: str
    question: str
    columns: list[str]
    effects: list[dict] = []     # [{id, name, value, effect_name}]
    sample_n: int = 10_000
    target: float = 0.80         # 목표 검정력 — 화면에서 옮긴다


@app.post("/v1/explore/power")
def explore_power(body: PowerReq) -> dict:
    """이 표본으로 **무엇이 잡히나**  — 잰 값이 그 선의 어느 쪽인지까지.

    작은 표본에서 "유의하지 않다"가 "관계가 없다"로 읽히는 것을 막는다.
    """
    from statop.analyze.explore import power

    try:
        return _pynative(power(body.session_file, body.question, body.columns,
                               body.effects, body.sample_n, body.target))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.get("/v1/explore/points")
def explore_points(session_file: str, question: str, columns: str,
                   color_by: str | None = None, sample_n: int = 10_000) -> dict:
    """고른 컬럼을 **그림으로 볼 재료**  — 값과 p 만으로는 모양을 알 수 없다."""
    from statop.analyze.explore import points

    cols = [c.strip() for c in columns.split(",") if c.strip()]
    try:
        return _pynative(points(session_file, question, cols, color_by, sample_n))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/v1/explore/run")
def explore_run(body: ExploreRun) -> dict:
    """**누른 검정 하나만** 돌린다 — 기록하지 않는다 .

    쓸 수 없다고 판정된 조합도 돌린다. 값을 숨기면 "왜 안 되는데"로 끝난다.
    """
    from statop.analyze.explore import run

    try:
        return _pynative(run(body.session_file, body.question, body.columns,
                             body.test, body.sample_n))
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))


class AdjustReq(BaseModel):
    rows: list[dict]          # [{name, p}]
    method: str = "holm"      # post.yaml P-221 이 기본값
    alpha: float = 0.05


@app.post("/v1/padjust")
def padjust_post(body: AdjustReq) -> dict:
    """다중검정 보정 (C-15) — 여러 번 쟀으면 그 수를 센다."""
    from statop.analyze.padjust import report

    try:
        return _pynative(report(body.rows, body.method, body.alpha))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.get("/v1/summarize")
def summarize_get(session_file: str, sample_n: int = 10_000) -> dict:
    """S173 재작성 가설 +  재현 스니펫."""
    from dataclasses import asdict

    from statop.hypothesis.rewrite import build

    try:
        return _pynative(asdict(build(session_file, sample_n)))
    except ValueError as e:
        raise HTTPException(400, str(e))


class RolesReq(BaseModel):
    session_file: str
    support: list[str] = []
    guardrail: list[str] = []
    note: str = ""


class CustomRole(BaseModel):
    session_file: str
    role: str                 # support | guardrail
    name: str
    why: str = ""
    remove: str | None = None  # 지울 항목 id


@app.post("/v1/metrics/custom")
def metrics_custom(body: CustomRole) -> dict:
    """함께 볼 것을 **직접** 더한다  — 다음에도 이 Goal 에서 추천으로 뜬다.

    규칙표(base)는 건드리지 않는다. 더한 것은 출처가 '사용자 지정'으로 남는다.
    """
    from statop.analyze.metrics import (add_custom, custom_for, goal_key,
                                      remove_custom, suggest)

    try:
        key = goal_key(suggest(body.session_file))
        if body.remove:
            ok = remove_custom(key, body.remove)
            notice = msg("metrics_custom_removed", name=body.remove) if ok else ""
        else:
            entry = add_custom(key, body.role, body.name, body.why)
            notice = msg("metrics_custom_added", name=entry["name"], role=body.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"key": key, "notice": notice, "custom": custom_for(key),
            "head": msg("metrics_custom_head"), "hint": msg("metrics_custom_hint")}


@app.post("/v1/metrics/roles")
def metrics_roles(body: RolesReq) -> dict:
    """S172 병기 선택 저장 — base 관계 중 무엇을 보고할지만 ()."""
    from statop.analyze.metrics import goal_key, save_choice, suggest

    try:
        key = goal_key(suggest(body.session_file))
        saved = save_choice(key, body.support, body.guardrail, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"key": key, **saved}


@app.get("/v1/hypothesis/qwen/status")
def qwen_status(session_file: str | None = None) -> dict:
    """Ask Qwen 버튼이 지금 무엇을 기다리는지 — 준비 단계와 예상 대기."""
    from statop.hypothesis.qwen import estimate_wait, probe

    out = probe()
    out["stage_label"] = msg("qwen_stage_" + out["stage"])
    wait = estimate_wait(session_file) if session_file else {"samples": 0,
                                                            "seconds": None}
    out["wait"] = wait
    out["wait_label"] = (msg("qwen_wait_known", sec=wait["seconds"],
                             last=wait["last_seconds"], n=wait["samples"])
                         if wait["samples"] else msg("qwen_wait_unknown"))
    # A7 은 덧붙임이다 — 못 쓰면 **이 패널만** 끄고 A1~A6 는 그대로 돈다 .
    # 끄기만 하면 사용자는 무엇을 하면 되는지 모르므로 **이유도 함께** 준다
    from statop.hypothesis.qwen import check_ready

    ok, why = check_ready()
    out["available"] = ok
    out["why"] = "" if ok else why
    out["optional_note"] = msg("a7_optional_note")
    return _pynative(out)


@app.get("/v1/pending")
def pending_get(session_file: str) -> dict:
    """저장하지 않은 값 변경 — 원본과 다른 데이터로 일하는 중인지 알려준다."""
    from statop.export import pending_changes
    from statop.session.core import load_session

    try:
        doc = load_session(session_file)
    except (ValueError, OSError, KeyError) as e:
        raise HTTPException(400, str(e))
    out = pending_changes(doc)
    out["labels"] = {k: msg("op_" + k) for k in out["counts"]}
    return _pynative(out)


@app.get("/v1/hypothesis")
def hypothesis_get(session_file: str) -> dict:
    """가설 1안/2안 (기계 생성) — 실행된 검정이 있어야 한다."""
    from dataclasses import asdict

    from statop.hypothesis.mech import build_report

    try:
        rep = build_report(session_file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _pynative({
        "proposals": [asdict(h) for h in rep.proposals],
        "cautions": rep.cautions, "companions": rep.companions,
        "guardrail": rep.guardrail, "basis": rep.basis, "source": rep.source,
    })


class AskReq(BaseModel):
    session_file: str
    opinion: str = ""
    dry_run: bool = False


@app.post("/v1/hypothesis/qwen/load")
def hypothesis_qwen_load() -> dict:
    """모델을 올려 둔다  — 상주하지 않으므로 [ask] 전에 한 번 누른다."""
    from statop.hypothesis.qwen import load

    return load()


@app.post("/v1/hypothesis/qwen")
def hypothesis_qwen(body: AskReq) -> dict:
    """Ask Qwen — dry_run 이면 보내지 않고 전송될 내용만 돌려준다."""
    from statop.hypothesis.qwen import QwenError, ask, build_prompt, check_ready

    if body.dry_run:
        try:
            user, _ = build_prompt(body.session_file, body.opinion)
        except ValueError as e:
            raise HTTPException(400, str(e))
        ok, info = check_ready()
        return {"dry_run": True, "would_send": user, "ready": ok, "note": info}
    ok, info = check_ready()
    if not ok:
        # **501 Not Implemented** — 이 서버에 LLM 이 안 붙어 있다는 뜻이다.
        # 400 으로 내면 "내가 뭘 잘못 보냈나"로 읽히고, 화면도 패널을 끌 근거가 없다.
        # A1~A6 는 그대로 돌아야 하므로 이 패널만 비활성이 된다 (요구사항)
        raise HTTPException(501, info)
    try:
        ans = ask(body.session_file, body.opinion)
    except (QwenError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"dry_run": False, "proposals": ans.proposals, "raw": ans.raw,
            "model": ans.model, "sent_log": ans.sent_log,
            # 입장·줄 이름은 서버가 준다 — 화면이 제목을 지어내지 않게 ( 과 같은 규칙)
            "labels": {**{s: msg(f"qwen_stance_{s}") for s in
                          ("optimal", "conservative", "broad")},
                       **{k: msg(f"qwen_line_{k}") for k in
                          ("hypothesis", "test", "limit")},
                       "raw_head": msg("qwen_raw_head")}}
