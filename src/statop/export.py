"""가공 파일 저장 (DECISIONS ) — 가공된 파일은 자기가 가공되었음을 스스로 알린다.

원본은 절대 건드리지 않는다. 선택 컬럼·필터·개별 수정을 적용한 **새 파일**을 만들고,
표식 컬럼과 사이드카(`<name>.statop.json`)를 함께 남긴다. 그 파일을 STATOP로 다시 열면
"인위적 변경 N건"을 배너로 알린다 — 파일이 손을 떠나도 사실이 따라가도록.
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from statop.messages import msg

SIDECAR_SUFFIX = ".statop.json"
MARKER_COLUMNS = ("_relabeled", "_relabel_from", "_relabel_note")


@dataclass
class ExportResult:
    path: Path
    sidecar: Path
    n_rows: int
    n_cols: int
    n_relabels: int


def sidecar_path(data_path: str | Path) -> Path:
    p = Path(data_path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def build_frame(doc: dict, sample_n: int | None = None):
    """세션 기록을 적용한 DataFrame을 만든다 (선택 컬럼 · 필터 · 개별 수정).

    sample_n=None이면 전체를 읽는다 — 내보내기는 전체가 대상이므로.
    """
    import pandas as pd

    from statop.relabel import apply_relabels
    from statop.rowfilter import apply_filter
    from statop.session.core import main_source, replay

    src = main_source(doc)
    if src is None:
        raise ValueError("no source")
    path = Path(src["path"])
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, sep="," if suffix == ".csv" else "\t")
    if sample_n:
        df = df.head(sample_n)

    st = replay(doc)
    sid = src["id"]

    # 행 필터 (기록된 순서대로)
    for op in doc["ops"]:
        if op["op"] == "filter_rows" and op.get("source") == sid:
            df = apply_filter(df, op["expr"], keep=op.get("keep", True))

    # 개별 라벨 수정 — 표식 컬럼이 함께 붙는다
    relabels = st["relabels"]
    if relabels:
        key_col = next((o["key_column"] for o in reversed(doc["ops"])
                        if o["op"] == "relabel"), None)
        if key_col and key_col in df.columns:
            df = apply_relabels(df, relabels, key_col)

    # 파생 → 결측 대치/제거 → 개별 제외. 분석이 보는 것과 **같은 데이터**여야 한다 —
    # 사본이 분석과 다르면 그 사본으로 낸 결과는 재현되지 않는다
    from statop.derive.service import apply_ops

    df = apply_ops(df, doc, sid)

    # 선택 컬럼만 (표식 컬럼은 유지). 파생 컬럼도 남긴다 — 파일에는 없던 값이다
    selected = st["selected"].get(sid, [])
    if selected:
        derived = [d["name"] for d in st["derived"] if d.get("source") == sid]
        # 같은 이름이 두 번 들어가면 pandas 가 v2 / v2.1 로 갈라 쓴다
        keep = [c for c in dict.fromkeys([*selected, *derived]) if c in df.columns]
        keep += [c for c in MARKER_COLUMNS if c in df.columns and c not in keep]
        key_col = next((o["key_column"] for o in reversed(doc["ops"])
                        if o["op"] == "relabel"), None)
        if key_col and key_col in df.columns and key_col not in keep:
            keep.insert(0, key_col)   # 수정된 행을 식별할 수 있어야 한다
        df = df[keep]
    return df


def export_trimmed(doc: dict, out_path: str | Path | None = None,
                   name: str | None = None, overwrite: bool = False,
                   use_as_main: bool = False) -> ExportResult:
    """사본 저장 — 가공 파일 + 사이드카. 기본 위치는 **원본과 같은 디렉토리**, `<원본>_trimmed`.

    원본은 절대 건드리지 않는다. `use_as_main=True` 면 이후 작업이 **이 사본을 기준으로**
    이어지도록 세션의 메인 파일을 교체한다 (원본은 기록에 그대로 남는다).
    """
    from statop.session.core import main_source, partial_hash, replay

    src = main_source(doc)
    if src is None:
        raise ValueError("no source")
    origin = Path(src["path"])

    if out_path:
        target = Path(out_path)
    else:
        stem = name or f"{origin.stem}_trimmed"
        target = origin.with_name(stem + origin.suffix)
    if target.resolve() == origin.resolve():
        from statop.messages import msg

        raise ValueError(msg("export_same_as_source"))
    if target.exists() and not overwrite:
        from statop.messages import msg

        raise FileExistsError(msg("session_save_exists", path=target))

    df = build_frame(doc)
    suffix = target.suffix.lower()
    if suffix == ".parquet":
        df.to_parquet(target, index=False)
    else:
        df.to_csv(target, sep="," if suffix == ".csv" else "\t", index=False)

    st = replay(doc)
    meta = {
        "statop_sidecar": 1,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"path": str(origin), "hash": src["hash"]},
        "session_id": doc["session_id"],
        "rules_version": doc.get("rules_db_version"),
        "n_rows": int(len(df)), "n_cols": int(df.shape[1]),
        "selected": st["selected"].get(src["id"], []),
        "filters": [{"expr": o["expr"], "keep": o.get("keep", True),
                     "reason": o.get("reason")}
                    for o in doc["ops"] if o["op"] == "filter_rows"],
        # 인위적 변경 — 이 파일을 다시 열 때 배너로 알리는 근거
        "relabels": st["relabels"],
        "n_relabels": len(st["relabels"]),
    }
    side = sidecar_path(target)
    side.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    # 저장 사실을 기록해야 "마지막 저장 이후 무엇이 더 바뀌었는지"를 알 수 있다
    from statop.session.core import append_op, ensure_source, set_main

    append_op(doc, "export", source=src["id"], path=str(target),
              sidecar=str(side), n_rows=int(len(df)), n_cols=int(df.shape[1]),
              use_as_main=use_as_main)
    if use_as_main:
        # 앞으로는 이 사본이 기준이다. 사본에는 조작이 **이미 반영돼 있으므로** 다시 얹으면
        # 두 번 적용된다 — 메인만 바꾸고 조작 기록은 그대로 둔다 (replay 는 source 로 거른다)
        set_main(doc, ensure_source(doc, target, role="aux"))
    return ExportResult(path=target, sidecar=side, n_rows=len(df), n_cols=df.shape[1],
                        n_relabels=len(st["relabels"]))


def inspect_file(path: str | Path) -> dict | None:
    """이 파일이 STATOP로 가공된 것인지 확인한다 — 열 때마다 호출된다.

    사이드카가 있으면 그것을, 없으면 표식 컬럼(`_relabeled`)만으로 감지한다.
    """
    from statop.io.meta import open_meta

    p = Path(path)
    side = sidecar_path(p)
    if side.exists():
        try:
            meta = json.loads(side.read_text())
            # 옛 이름(evid_sidecar)으로 적힌 파일도 가공된 것이다
            if meta.get("statop_sidecar") or meta.get("evid_sidecar"):
                return {"trimmed": True, "source": meta["source"]["path"],
                        "n_relabels": meta.get("n_relabels", 0),
                        "relabels": meta.get("relabels", []),
                        "filters": meta.get("filters", []),
                        "via": "sidecar"}
        except (json.JSONDecodeError, KeyError):
            pass
    try:  # 사이드카가 없어도 표식 컬럼으로 감지
        cols = open_meta(p).columns
    except ValueError:
        return None
    if "_relabeled" in cols:
        return {"trimmed": True, "source": None, "n_relabels": None,
                "relabels": [], "filters": [], "via": "marker_column"}
    return None


def origin_line(path: str | Path) -> str:
    """경로가 보이는 자리에 붙일 "가공 전 파일 위치" 한 줄. 아니면 빈 문자열.

    가공 파일을 기준으로 작업하다 보면 **원본이 어디였는지 잊는다.** 다시 열거나
    추가로 불러오려면 그 경로가 필요하므로, 경로가 드러나는 화면마다 함께 보인다.
    사이드카를 지웠으면 표식 컬럼으로 가공 사실만 알 수 있고 경로는 모른다 —
    그때는 모른다고 말한다.
    """
    try:
        info = inspect_file(path)
    except (OSError, ValueError):
        return ""          # 읽을 수 없는 경로에서 줄 하나 때문에 화면이 죽지 않게
    if not info or not info.get("trimmed"):
        return ""
    if info.get("source"):
        return msg("origin_line", path=info["source"])
    return msg("origin_unknown")


# ── 사본 저장이 필요한 상태인가 ─────────────────────────────
# 값을 바꾸는 조작(결측 대치·행 제거·라벨 수정·개별 제외)을 하고 나면 **원본과 다른 데이터**로
# 작업하고 있는 것이다. 원본은 건드리지 않으므로, 그 상태를 남기려면 사본을 저장해야 한다.
MUTATING_OPS = ("impute", "missing_drop", "relabel", "exclude_row", "filter_rows")


def pending_changes(doc: dict) -> dict:
    """사본 저장 전에 쌓여 있는 값 변경 — 종류별 건수와 마지막 저장 이후 여부."""
    ops = doc.get("ops", [])
    last_export = max((o["seq"] for o in ops if o["op"] == "export"), default=-1)
    counts: dict[str, int] = {}
    for o in ops:
        if o["op"] in MUTATING_OPS and o["seq"] > last_export:
            counts[o["op"]] = counts.get(o["op"], 0) + 1
    return {"counts": counts, "total": sum(counts.values()),
            "needs_export": bool(counts), "last_export_seq": last_export}
