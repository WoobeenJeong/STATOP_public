"""세션 로그 ( 스키마 v1): 데이터는 저장하지 않고 경로·부분 해시·조작 기록만 남긴다."""

import datetime
import hashlib
import json
import uuid
from pathlib import Path

import statop

CHUNK = 4 * 1024 * 1024  # 부분 해시가 읽는 선두/말미 크기 (4MB)

# 부분 해시 주의 문구 ( 사용자 확정)는 messages/*.yaml의 notice_partial_hash —
# 세션 생성·불러오기·출력 md에 동일 표기. 인터페이스 중립(호출 방법은 껍데기가 덧붙임).


def partial_hash(path: str | Path, progress=None) -> dict:
    """파일 크기 + 선두 4MB + 말미 4MB의 sha256. 로컬은 1초 내.

    네트워크 저장소의 콜드 캐시에서는 이 8MB 읽기가 열기 과정에서 가장 느린
    구간일 수 있다 — progress(0~1)로 청크 단위 진행을 알린다.
    """
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    step = 256 * 1024
    total = CHUNK + (CHUNK if size > CHUNK else 0)
    done = 0
    with open(p, "rb") as f:
        for start in (0, max(size - CHUNK, CHUNK) if size > CHUNK else None):
            if start is None:
                break
            f.seek(start)
            remain = CHUNK
            while remain > 0:
                block = f.read(min(step, remain))
                if not block:
                    break
                h.update(block)
                remain -= len(block)
                done += len(block)
                if progress:
                    progress(min(1.0, done / total))
    if progress:
        progress(1.0)
    return {"algo": "sha256", "mode": "partial", "value": h.hexdigest()}


def _rules_version() -> str | None:
    """규칙 DB 버전을 기록한다  — 어느 규칙으로 판정했는지 추적용."""
    try:
        from statop.rules.build import rules_version

        return rules_version()
    except Exception:  # 규칙 문서가 없는 배포 형태여도 세션은 열려야 한다
        return None


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def new_session(project_path: str | Path | None = None, user: str | None = None, seed: int = 0) -> dict:
    """빈 세션 문서를 만든다. project_path 미지정 시 기본 저장소를 쓴다."""
    from statop.store import user_id

    return {
        "schema_version": 1,
        "session_id": f"s_{datetime.datetime.now():%Y%m%d-%H%M}_{uuid.uuid4().hex[:4]}",
        "created": _now(),
        "statop_version": statop.__version__,
        "rules_db_version": _rules_version(),
        "project_path": str(Path(project_path).resolve()) if project_path else None,
        "user": user or user_id(),
        "seed": seed,
        "sources": [],
        "ops": [],
    }


def register_source(doc: dict, data_path: str | Path, role: str = "main",
                    progress=None) -> str:
    """원본 파일을 세션에 등록한다 — 경로·형식·부분 해시만, 데이터 사본 없음.

    role : main=분석 대상(세션당 1개) / compare=비교용 / aux=보조.
    main으로 등록하면 기존 main은 aux로 내려간다 — 세션은 유지되고 대상만 바뀐다.
    """
    p = Path(data_path).resolve()
    src_id = f"d{len(doc['sources']) + 1}"
    if role == "main":
        for s in doc["sources"]:
            if s.get("role") == "main":
                s["role"] = "aux"
    doc["sources"].append(
        {
            "id": src_id,
            "path": str(p),
            "format": p.suffix.lstrip(".").lower(),
            "role": role,
            "hash": partial_hash(p, progress=progress),
            "registered": _now(),
        }
    )
    return src_id


def main_source(doc: dict) -> dict | None:
    """현재 분석 대상(main). 없으면 첫 소스를 쓴다 (옛 로그 호환)."""
    for s in doc["sources"]:
        if s.get("role") == "main":
            return s
    return doc["sources"][0] if doc["sources"] else None


def set_main(doc: dict, src_id: str) -> dict:
    """메인 파일을 교체한다 (op: set_main). 세션·조작기록·임시본은 그대로 유지."""
    target = next((s for s in doc["sources"] if s["id"] == src_id), None)
    if target is None:
        raise KeyError(src_id)
    previous = main_source(doc)
    for s in doc["sources"]:
        if s.get("role") == "main":
            s["role"] = "aux"
    target["role"] = "main"
    return append_op(doc, "set_main", source=src_id,
                     previous=previous["id"] if previous else None)


def ensure_source(doc: dict, data_path: str | Path, role: str = "aux",
                  progress=None) -> str:
    """같은 경로가 이미 등록돼 있으면 그 id를 재사용, 없으면 새로 등록한다."""
    p = str(Path(data_path).resolve())
    for src in doc["sources"]:
        if src["path"] == p:
            return src["id"]
    return register_source(doc, data_path, role=role, progress=progress)


def append_op(doc: dict, op: str, **fields) -> dict:
    entry = {"seq": len(doc["ops"]) + 1, "ts": _now(), "op": op, **fields}
    doc["ops"].append(entry)
    return entry


def session_file(doc: dict) -> Path:
    """작업 중 임시본은 항상 기본 저장소의 tmp/ — 프로젝트 폴더를 어지럽히지 않는다 ."""
    from statop.store import tmp_dir

    return tmp_dir() / f"session_{doc['session_id']}.json"


def save_session(doc: dict) -> Path:
    path = session_file(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    return path


def load_session(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


# ── 화면 상태 공유 (웹 ↔ CLI) ────────────────────────────────
# ops는 데이터 조작의 기록이고 재생 대상이다. 화면 상태(어느 단계인지, 무엇을
# 체크해뒀는지)는 조작이 아니므로 ops에 넣지 않는다 — 대신 마지막 것 하나만
# view 블록에 둔다. **저장한 쪽이 있어야 반영할 것이 생긴다** (동기화 키).

VIEW_KEYS = {"by", "step", "picked", "ts"}


def save_view(session_file: str | Path, by: str, step: str,
              picked: list[str] | None = None) -> dict:
    """지금 화면 상태를 세션에 남긴다 — 상대(웹/CLI)가 이걸 읽어 같은 화면이 된다."""
    doc = load_session(session_file)
    doc["view"] = {"by": by, "step": step, "picked": sorted(picked or []),
                   "ts": _now()}
    save_session(doc)
    return doc["view"]


def remove_columns(doc: dict, source_id: str, cols: list) -> tuple[list, list, list]:
    """작업 영역에서 컬럼을 뺀다 — **원본 컬럼이면 선택 해제, 파생이면 파생 취소.**

    예전에는 선택 목록에 없는 이름을 전부 거절해서 **파생 컬럼은 지울 길이 아예
    없었다.** 둘은 다른 조작이지만 사용자에게는 같은 [제외] 한 번이다.

    돌려주는 것: (선택 해제한 것, 파생 취소한 것, 모르는 이름)
    """
    st = replay(doc)
    selected = st["selected"].get(source_id, [])
    derived = {d["name"] for d in st["derived"]
               if d.get("source") in (None, source_id)}
    # **파생인지 먼저 본다.** 재생이 파생 이름을 선택 목록에 합쳐 넣으므로(아래 replay),
    # 선택부터 보면 파생도 "선택된 컬럼"으로 잡힌다 — 그러면 deselect 를 기록하는데
    # 다음 재생에서 derive 가 그 이름을 도로 넣어 **영영 안 지워진다** (실제로 그랬다)
    gone = [c for c in cols if c in derived]
    off = [c for c in cols if c in selected and c not in derived]
    unknown = [c for c in cols if c not in selected and c not in derived]
    if off:
        append_op(doc, "deselect", source=source_id, cols=off)
    for name in gone:
        append_op(doc, "derive_drop", source=source_id, name=name)
    return off, gone, unknown


def peek_state(session_file: str | Path) -> dict:
    """반영 전에 가볍게 확인할 것만 — 전체 재생 없이 view와 조작 개수만 읽는다."""
    doc = load_session(session_file)
    return {"session_id": doc["session_id"], "n_ops": len(doc["ops"]),
            "view": doc.get("view")}


def replay(doc: dict) -> dict:
    """조작 기록(ops)을 순서대로 재생해 최종 상태를 계산한다 (M0-8, 3.7).

    현재 상태 = 소스별 '가져온 컬럼' 목록(선택 순서 유지, 중복 없음).
    새 op 타입이 생기면 여기에 재생 규칙을 함께 추가한다 — 로그만으로 재현이 원칙.
    """
    selected: dict[str, list[str]] = {}
    transposed: dict[str, bool] = {}
    held: dict[str, list[str]] = {}      # 분석 제외, 시각화에는 사용 (M0-5)
    label_maps: dict[str, dict[str, dict[str, int]]] = {}  # 소스 → 컬럼 → {값: 코드}
    relabels: list[dict] = []   # 개별 샘플 수정 — 원본 불변, 기록으로만
    excluded: list[dict] = []   # 개별 샘플 제외 — 사유 없이는 뺄 수 없다
    metric_goal: dict | None = None    #  사용자가 지정한 Goal 지표
    model_specs: list[dict] = []       # 모듈 B 구성  — 모듈 A 와 섞지 않는다
    filters: list[dict] = []    # 행 필터 — 제외 사유는 출력에 항상 첨부 (M0-6)
    missing_ops: list[dict] = []  # 결측 제거·대치 — 방법·비율이 출력에 남는다 (M0-6b)
    group_structure: dict[str, str] = {}  # 확정된 그룹 구조 — C-05 독립 가정에 쓰인다 (M0-7)
    semantic_types: dict[str, dict[str, str]] = {}  # 확정된 의미 타입 (M1-1) — 이후 판정의 전제
    derived: list[dict] = []    # 파생 컬럼 — 수식·eps가 출력에 남는다 (M1-2)
    # 적합성 수정으로 자리를 넘긴 컬럼 (M1-3 ) — 원본은 남되 분석에서 빠진다
    replaced: dict[str, dict[str, str]] = {}
    specs: list[dict] = []      # 질문 설계 (A1) — 마지막 것이 현재 전제
    test_results: list[dict] = []   # 실행한 검정  — 가설(A7)의 근거
    main: str | None = None
    for op in doc["ops"]:
        if op["op"] == "select":
            cur = selected.setdefault(op["source"], [])
            for c in op["cols"]:
                if c not in cur:
                    cur.append(c)
        elif op["op"] == "hold":
            cur = held.setdefault(op["source"], [])
            for c in op["cols"]:
                if c not in cur:
                    cur.append(c)
        elif op["op"] == "unhold":
            cur = held.get(op["source"], [])
            held[op["source"]] = [c for c in cur if c not in set(op["cols"])]
        elif op["op"] == "deselect":
            cur = selected.get(op["source"], [])
            selected[op["source"]] = [c for c in cur if c not in set(op["cols"])]
        elif op["op"] == "set_main":
            main = op["source"]
        elif op["op"] == "label_map":
            # 같은 컬럼을 다시 매핑하면 마지막 것이 이긴다 (되돌리기도 기록으로 남음)
            label_maps.setdefault(op["source"], {})[op["column"]] = dict(op["mapping"])
        elif op["op"] == "derive_drop":
            # 만든 파생 컬럼을 작업 영역에서 뺀다. 수식 기록은 남는다 —
            # "무엇을 만들었다가 뺐는가"도 이력이다 (semantic_unconfirm 과 같은 규칙)
            derived = [d for d in derived
                       if not (d["name"] == op["name"]
                               and d.get("source") in (None, op.get("source")))]
        elif op["op"] == "derive":
            derived.append({k: v for k, v in op.items() if k != "ts"})
            # 자동 확정은 하지 않는다 — 확정은 사용자의 명시 행위다 (id·label 포함 전부).
            # 예외: 적합성 수정(from_fix)은 사용자가 그 변환(CLR 등)을 직접 골라 적용한
            # 것이므로 결과 타입도 그 선택에 포함된 것으로 본다
            if op.get("from_fix") and op.get("result_type"):
                semantic_types.setdefault(op["source"], {})[op["name"]] = op["result_type"]
        elif op["op"] == "replace":
            cur = replaced.setdefault(op["source"], {})
            for old, new in op["pairs"]:
                cur[old] = new
        elif op["op"] == "analysis_spec":
            specs.append({k: v for k, v in op.items() if k not in ("ts",)})
        elif op["op"] == "test_result":
            test_results.append({k: v for k, v in op.items() if k != "ts"})
        elif op["op"] == "semantic_confirm":
            semantic_types.setdefault(op["source"], {})[op["column"]] = op["type"]
        elif op["op"] == "semantic_unconfirm":
            # 되돌리기도 **기록**이다 — 지우지 않고 취소한 사실을 남긴다.
            # 확정을 전제로 한 판정(적합성·가드레일)이 다시 미확정으로 돌아간다
            semantic_types.get(op["source"], {}).pop(op["column"], None)
        elif op["op"] == "group_confirm":
            group_structure[op["column"]] = op["kind"]
        elif op["op"] in ("missing_drop", "impute"):
            missing_ops.append({k: v for k, v in op.items() if k != "ts"})
        elif op["op"] == "model_spec":
            model_specs.append({k: v for k, v in op.items() if k != "ts"})
        elif op["op"] == "metric_goal":
            metric_goal = {k: v for k, v in op.items() if k != "ts"}
        elif op["op"] == "exclude_row":
            excluded = [e for e in excluded
                        if not (e["key"] == op["key"]
                                and e["key_column"] == op["key_column"])]
            excluded.append({k: v for k, v in op.items() if k != "ts"})
        elif op["op"] == "include_row":
            excluded = [e for e in excluded
                        if not (e["key"] == op["key"]
                                and e["key_column"] == op["key_column"])]
        elif op["op"] == "filter_rows":
            filters.append({"expr": op["expr"], "keep": op.get("keep", True),
                            "reason": op.get("reason"), "seq": op["seq"]})
        elif op["op"] == "relabel":
            # 같은 행을 다시 고치면 마지막이 이기되, 이력은 ops에 그대로 남는다
            relabels = [r for r in relabels
                        if not (r["key"] == op["key"] and r["column"] == op["column"])]
            relabels.append({"key": op["key"], "column": op["column"],
                             "from": op["from"], "to": op["to"],
                             "note": op["note"], "seq": op["seq"], "ts": op["ts"]})
        elif op["op"] == "transpose":
            transposed[op["source"]] = not transposed.get(op["source"], False)  # 2번=원상복귀
        elif op["op"] == "open":
            pass  # 소스 등록은 sources에 이미 있음
        else:
            from statop.messages import msg

            raise ValueError(msg("replay_unknown_op", op=op["op"], seq=op["seq"]))
    # 파생 컬럼은 선택 목록에 없지만 분석 대상이다 — 수식으로 만든 것도 분석 대상이므로
    for d in derived:
        cur = selected.setdefault(d["source"], [])
        if d["name"] not in cur:
            cur.append(d["name"])
    # hold된 컬럼은 선택에 남아 있되 분석 대상에서는 빠진다 (시각화용)
    # 자리를 넘긴 원본도 마찬가지 — 남아 있되 분석에서는 빠진다
    analysis = {src: [c for c in cols
                      if c not in set(held.get(src, [])) | set(replaced.get(src, {}))]
                for src, cols in selected.items()}
    return {"selected": selected, "held": held, "analysis": analysis,
            "label_maps": label_maps, "relabels": relabels, "excluded": excluded,
            "metric_goal": metric_goal, "model_specs": model_specs,
            "filters": filters,
            "missing_ops": missing_ops, "group_structure": group_structure,
            "semantic_types": semantic_types, "derived": derived,
            "replaced": replaced, "specs": specs, "test_results": test_results,
            "transposed": transposed, "main": main}


def load_saved(path: str | Path) -> tuple[dict, dict]:
    """정식 저장본을 불러와 새 세션(새 id)으로 복제하고 재생 상태를 반환한다.

    원래 세션과 무관한 새 세션이 열린다 (요구사항). 출처는 loaded_from에 기록.
    """
    src_doc = load_session(path)
    doc = new_session(src_doc.get("project_path"), user=src_doc.get("user"),
                      seed=src_doc.get("seed", 0))
    doc["sources"] = src_doc["sources"]
    doc["ops"] = src_doc["ops"]
    doc["loaded_from"] = Path(path).name
    return doc, replay(doc)


def check_sources(doc: dict) -> list[dict]:
    """등록된 원본들의 부분 해시를 다시 계산해 기록과 대조한다 .

    반환: [{id, path, status}] — ok(일치) | changed(해시 불일치) | missing(파일 없음).
    부분 해시만 재계산하므로 대용량이어도 빠르다 — 전체 대조는 무결성 검증(Integrity) 몫.
    """
    results = []
    for src in doc["sources"]:
        p = Path(src["path"])
        if not p.exists():
            status = "missing"
        else:
            status = "ok" if partial_hash(p)["value"] == src["hash"]["value"] else "changed"
        results.append({"id": src["id"], "path": src["path"], "status": status})
    return results


def ops_summary(doc: dict, last: int = 3) -> str:
    """ops를 전체 나열하지 않고 요약한다 — 총 개수, 종류별, 마지막 N개."""
    from collections import Counter

    from statop.messages import msg

    counts = Counter(o["op"] for o in doc["ops"])
    kinds = " · ".join(f"{k}×{v}" for k, v in counts.items()) or "-"
    tail = " → ".join(f"#{o['seq']} {o['op']}" for o in doc["ops"][-last:])
    return msg("ops_summary", n=len(doc["ops"]), kinds=kinds) + (
        msg("ops_summary_tail", tail=tail) if tail else "")


def auto_name(doc: dict, when: datetime.datetime | None = None) -> str:
    """ 자동 이름: {yymmdd}_{프로젝트명}_{mode}_{판정태그}_{n행수}_{am12|pm03}.json

    시각은 시간 단위(am/pm) — 분까지 붙이면 파일이 너무 늘어남. 같은 시간대 재저장은
    이름이 겹치므로 overwrite 명시 + .bak 교체(항상 원본-bak 쌍 1개)로 처리된다.
    """
    from statop.io.meta import estimate_rows, open_meta

    when = when or datetime.datetime.now()
    project = Path(doc["project_path"]).name if doc.get("project_path") else (doc.get("user") or "default")
    mode = doc.get("mode") or "hypo"
    flags = "-".join(doc.get("flags") or ["clean"])  # 판정 태그는 규칙 엔진(Phase 5~) 연동 전까지 clean
    n = 0
    src = main_source(doc)
    if src:
        meta = open_meta(src["path"])
        n = meta.n_rows if meta.n_rows is not None else estimate_rows(src["path"])
    ampm = ("am" if when.hour < 12 else "pm") + f"{when.hour % 12 or 12:02d}"
    return f"{when:%y%m%d}_{project}_{mode}_{flags}_n{n}_{ampm}.json"


def save_as(doc: dict, out_dir: str | Path | None = None, suffix: str | None = None,
            overwrite: bool = False) -> Path:
    """자동 이름으로 저장. 동일 이름 존재 시 overwrite 명시 없이는 실패, 명시 시 .bak 1개 보존."""
    from statop.store import sessions_dir

    name = auto_name(doc)
    if suffix:
        name = name.replace(".json", f"__{suffix}.json")
    target = Path(out_dir or doc.get("project_path") or sessions_dir()) / name
    if target.exists():
        if not overwrite:
            from statop.messages import msg

            raise FileExistsError(msg("session_save_exists", path=target))
        target.replace(target.with_suffix(".json.bak"))  # 직전 버전 1개 보존
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    return target
