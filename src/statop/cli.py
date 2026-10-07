import json
import os

import typer

from statop.messages import msg

app = typer.Typer(no_args_is_help=False, help="STATOP — STATistic Ontology Platform")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    lang: str = typer.Option(None, "--lang", help="메시지 언어: ko | en"),
) -> None:
    if lang:
        os.environ["STATOP_LANG"] = lang
    # 명령 없이 `statop`만 치면 전체화면  — 경로 입력칸과 버튼이 바로 뜬다
    if ctx.invoked_subcommand is None:
        from statop.shell.screen import run_screen

        run_screen()


def _session_default(value: str | None) -> str:
    """--session 생략 시 최근 작업 세션 — 매번 경로를 복사해 붙이게 하지 않는다.

    $S 가 빈 채로 들어오면 다음 옵션이 세션 값으로 먹히는 사고도 있었다.
    어떤 세션을 골랐는지는 항상 첫 줄에 말한다 (조용히 다른 세션을 쓰지 않게).
    """
    if value:
        return value
    from pathlib import Path

    from statop.store import tmp_dir

    files = sorted(tmp_dir().glob("session_*.json"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise typer.BadParameter(msg("session_none_active"))
    typer.echo(typer.style(msg("session_auto_selected", name=files[0].name),
                           fg=typer.colors.BRIGHT_BLACK))
    return str(files[0])


@app.command()
def version() -> None:
    """설치된 statop 버전을 출력한다."""
    from statop import __version__

    typer.echo(f"statop {__version__}")


@app.command()
def columns(
    path: str,
    sample_n: int = 10_000,
    grep: str = typer.Option(None, help="컬럼명 부분일치 필터 (정규식)"),
    limit: int = typer.Option(None, help="표시할 컬럼 수. 미지정 시 앞2·중1·뒤2 요약"),
    page: int = typer.Option(None, help="페이지 번호 (1부터). 지정 시 25개씩 끊어 표시"),
    page_size: int = typer.Option(25, help="--page 사용 시 페이지당 컬럼 수"),
    sort: str = typer.Option(None, help="정렬 기준: missing | unique | name"),
    out: str = typer.Option(None, help="전체 컬럼 표를 tsv 파일로 저장"),
    session: str = typer.Option(None, help="세션 로그 — 전치 등 뷰 상태를 반영해 표시"),
) -> None:
    """파일의 컬럼 목록·요약을 표시한다. 데이터 셀은 출력하지 않는다."""
    from pathlib import Path

    from statop.io.meta import estimate_rows, open_meta
    from statop.io.profile import profile_columns, profile_frame

    from statop.export import inspect_file

    meta = open_meta(path)
    info = inspect_file(path)      # 가공된 파일이면 열 때 알린다 ()
    view_rows = None
    transposed_view = False
    if session:
        from statop.session.core import load_session, replay

        doc = load_session(session)
        target = str(Path(path).resolve())
        src_id = next((s["id"] for s in doc["sources"] if s["path"] == target), None)
        if src_id and replay(doc)["transposed"].get(src_id, False):
            from statop.io.transpose import transpose_table

            transposed_view = True
            t = transpose_table(path)
            prof = profile_frame(t)  # 전치 뷰는 전체가 메모리에 있으므로 정확치
            view_rows = t.shape[0]
    if not transposed_view:
        prof = profile_columns(path, sample_n=sample_n)
    if grep:
        prof = prof[prof["column"].str.contains(grep, regex=True)]
    if sort:
        key = {"missing": ("missing_rate", False), "unique": ("n_unique", False), "name": ("column", True)}[sort]
        prof = prof.sort_values(key[0], ascending=key[1])
    if out:
        prof.to_csv(out, sep="\t", index=False)
        typer.echo(msg("columns_saved_out", n=len(prof), out=out))
    size_mb = Path(path).stat().st_size / 1e6

    if transposed_view:
        rows_txt = f"{view_rows:,}"
    elif meta.n_rows is not None:
        rows_txt = f"{meta.n_rows:,}"
    else:
        rows_txt = msg("columns_rows_estimated", n=estimate_rows(path))

    if info:
        if info["n_relabels"] is not None:
            typer.echo(typer.style(msg("open_trimmed_banner", n=info["n_relabels"]),
                                   fg=typer.colors.YELLOW))
            if info["source"]:
                typer.echo(typer.style(msg("open_trimmed_source", path=info["source"]),
                                       fg=typer.colors.YELLOW))
        else:
            typer.echo(typer.style(msg("open_trimmed_marker"), fg=typer.colors.YELLOW))

    n_obs = int(prof["sample_rows"].iloc[0])
    suffix = msg("columns_transposed_suffix") if transposed_view else ""
    typer.echo(msg("columns_file_line", name=Path(path).name, fmt=meta.fmt, mb=size_mb, suffix=suffix))
    typer.echo(msg("columns_rows_line", rows=rows_txt, n=len(prof)))
    if len(prof) > 200:
        typer.echo(typer.style(msg("columns_warn_many", n=len(prof)), fg=typer.colors.YELLOW))
    typer.echo(msg("columns_sample_est", per=sample_n // 3, obs=n_obs)
               if bool(prof["estimated"].iloc[0]) else msg("columns_sample_full"))

    type_counts = prof["dtype"].value_counts()
    typer.echo(msg("columns_storage_types",
                   items=" · ".join(f"{t} {c:,}" for t, c in type_counts.items())))

    top_miss = prof.nlargest(10, "missing_rate")
    top_miss = top_miss[top_miss["missing_rate"] > 0]
    if len(top_miss):
        typer.echo(msg("columns_missing_top", items=" · ".join(
            f"{r.column} {r.missing_rate:.1%}" for r in top_miss.itertuples())))

    if page is not None:  # 페이지 모드 — 웹과 같은 25개 단위 (컬럼이 많아도 비용 일정)
        n_pages = max(1, -(-len(prof) // page_size))
        idx = min(max(1, page), n_pages)
        start = (idx - 1) * page_size
        show = [prof.iloc[start : start + page_size]]
        shown_n = len(show[0])
    elif limit is None and len(prof) > 5:  # 기본: 앞2 · 중1 · 뒤2
        mid = len(prof) // 2
        show = [prof.iloc[:2], None, prof.iloc[mid : mid + 1], None, prof.iloc[-2:]]
        shown_n = 5
    else:
        show = [prof.head(limit or len(prof))]
        shown_n = min(limit or len(prof), len(prof))

    typer.echo("")
    if page is not None:
        typer.echo(msg("columns_page_title", shown=shown_n, page=idx, pages=n_pages,
                       total=len(prof)))
    else:
        typer.echo(msg("columns_table_title", shown=shown_n, total=len(prof)))
    typer.echo(msg("columns_table_header"))
    # design-tokens 3절: 색만으로 구분하지 않는다 — 기호(!!/!) 병행.
    # 등급 매핑 — 심각(≥30%)=danger(빨강), 주의(≥10%)=warn(앰버)
    for part in show:
        if part is None:
            typer.echo("     …")
            continue
        for r in part.itertuples():
            line = f"{r.column:<24s} {r.dtype:<14s} {r.missing_rate:>8.1%} {r.n_unique:>10,d}"
            if r.missing_rate >= 0.30:
                typer.echo(typer.style(f"  !! {line}", fg=typer.colors.RED))
            elif r.missing_rate >= 0.10:
                typer.echo(typer.style(f"  !  {line}", fg=typer.colors.YELLOW))
            else:
                typer.echo(f"     {line}")


session_app = typer.Typer(no_args_is_help=True, help="세션(작업 기록) 관리")
app.add_typer(session_app, name="session")


@session_app.command("new")
def session_new(
    project: str = typer.Option(None, help="프로젝트 폴더 (미지정 시 기본 저장소 {STATOP_HOME}/{사용자}/)"),
    data: str = typer.Option(None, help="바로 등록할 원본 데이터 파일 (선택)"),
    user: str = typer.Option(None, help="사용자 식별자 (미지정 시 OS 로그인 이름)"),
) -> None:
    """새 세션을 만든다. 데이터 사본 없이 경로·부분 해시·조작 기록만 남긴다.
    임시본은 기본 저장소 tmp/에 생기며, 저장(save) 없이 닫으면(close) 사라진다."""
    from pathlib import Path

    from statop.session.core import new_session, register_source, save_session

    if project and not Path(project).is_dir():
        raise typer.BadParameter(msg("session_no_project", path=project))

    doc = new_session(project, user=user)
    if data:
        src_id = register_source(doc, data)
        h = doc["sources"][-1]["hash"]
        typer.echo(msg("session_source_registered", data=data, src=src_id,
                       hash12=h["value"][:12], mode=h["mode"]))
    path = save_session(doc)
    typer.echo(msg("session_created", sid=doc["session_id"]))
    typer.echo(msg("session_logfile", path=path))
    typer.echo(typer.style(msg("notice_partial_hash") + msg("cli_integrity_hint"),
                           fg=typer.colors.YELLOW))


@session_app.command("save")
def session_save(
    session: str = typer.Option(..., help="작업 중인 세션 로그 파일"),
    out_dir: str = typer.Option(None, help="저장 폴더 (기본: 프로젝트 폴더 또는 기본 저장소 sessions/)"),
    suffix: str = typer.Option(None, help="이름 뒤에 붙일 사용자 추가 이름 (__suffix)"),
    overwrite: bool = typer.Option(False, help="동일 이름 존재 시 덮어쓰기 (.bak 1개 보존)"),
) -> None:
    """세션을 자동 이름(: 날짜_프로젝트_모드_태그_행수_시각)으로 저장한다.
    단순 저장은 항상 새 파일 — 덮어쓰기는 --overwrite 명시 필요."""
    from statop.session.core import load_session, save_as, save_session

    doc = load_session(session)
    try:
        target = save_as(doc, out_dir=out_dir, suffix=suffix, overwrite=overwrite)
    except FileExistsError as e:
        typer.echo(typer.style(str(e), fg=typer.colors.RED))
        raise typer.Exit(1)
    doc["saved_at"] = target.name
    save_session(doc)  # 임시본에 "저장됨" 표식 — close가 이걸 본다
    typer.echo(msg("session_saved", path=target))


@session_app.command("load")
def session_load(saved: str) -> None:
    """정식 저장본을 불러온다 — 원본을 부분 해시로 재확인한 뒤 재생(Replay)해 상태를 복원한다."""
    from statop.session.core import check_sources, load_saved, ops_summary, save_session

    doc, state = load_saved(saved)

    problems = [r for r in check_sources(doc) if r["status"] != "ok"]
    if problems:
        for r in problems:
            key = "session_load_missing" if r["status"] == "missing" else "session_load_changed"
            typer.echo(typer.style(msg(key, src=r["id"], path=r["path"]), fg=typer.colors.RED))
        typer.echo(typer.style(msg("session_load_guide") + msg("cli_integrity_hint"),
                               fg=typer.colors.RED))
        if not typer.confirm(msg("session_load_confirm"), default=False):
            typer.echo(msg("session_load_cancelled"))
            raise typer.Exit(1)
    else:
        typer.echo(typer.style(
            msg("session_load_hash_ok") + msg("notice_partial_hash") + msg("cli_integrity_hint"),
            fg=typer.colors.YELLOW))

    path = save_session(doc)
    typer.echo(msg("session_loaded", name=doc["loaded_from"], sid=doc["session_id"]))
    typer.echo(msg("session_workfile", path=path))
    typer.echo(ops_summary(doc))
    for src_id, cols in state["selected"].items():
        typer.echo(msg("session_restored", src=src_id, n=len(cols),
                       head=", ".join(cols[:5]), more=" …" if len(cols) > 5 else ""))


@session_app.command("close")
def session_close(
    session: str = typer.Option(..., help="닫을 작업 임시본 (session_*.json)"),
    force: bool = typer.Option(False, help="저장 안 된 세션도 강제로 닫기"),
) -> None:
    """세션을 닫는다 — 작업 임시본을 삭제. 저장(save)된 적 없으면 거부 (--force로 강제)."""
    from pathlib import Path

    from statop.session.core import load_session

    p = Path(session)
    doc = load_session(p)
    if "saved_at" not in doc and not force:
        typer.echo(typer.style(msg("session_close_unsaved", n=len(doc["ops"])), fg=typer.colors.RED))
        raise typer.Exit(1)
    p.unlink()
    saved = msg("session_closed_saved_suffix", name=doc["saved_at"]) if "saved_at" in doc else ""
    typer.echo(msg("session_closed", sid=doc["session_id"], saved=saved))


@app.command("open")
def open_data(
    data: str,
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
) -> None:
    """[진단용] 세션에 open 조작을 수동 기록한다. 일반 흐름에선 select가 자동 기록 —
    저장 구조·경로 문제를 파악할 때만 사용."""
    from statop.session.core import append_op, ensure_source, load_session, save_session

    doc = load_session(session)
    src_id = ensure_source(doc, data)
    entry = append_op(doc, "open", source=src_id)
    save_session(doc)
    typer.echo(msg("op_recorded_open", seq=entry["seq"], data=data, src=src_id, n=len(doc["ops"])))


@app.command()
def select(
    data: str,
    cols: str = typer.Option(None, help="가져올 컬럼 (쉼표 구분)"),
    cols_file: str = typer.Option(None, help="컬럼 목록 파일 — 한 줄에 하나, 또는 columns --out 으로 만든 tsv"),
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
) -> None:
    """컬럼을 작업 영역으로 가져온다 (op: select). open 기록은 자동으로 선행된다."""
    from pathlib import Path

    from statop.io.meta import open_meta
    from statop.session.core import append_op, ensure_source, load_session, save_session

    if (cols is None) == (cols_file is None):
        raise typer.BadParameter(msg("select_err_xor"))
    if cols_file:
        lines = [ln.strip() for ln in Path(cols_file).read_text().splitlines() if ln.strip()]
        if lines and lines[0].split("\t")[0] == "column":  # columns --out 형식 (헤더 있는 tsv)
            lines = lines[1:]
        wanted = [ln.split("\t")[0] for ln in lines]
    else:
        wanted = [c.strip() for c in cols.split(",") if c.strip()]
    meta = open_meta(data)
    missing = [c for c in wanted if c not in meta.columns]
    if missing:
        raise typer.BadParameter(msg("select_err_missing", cols=", ".join(missing)))

    doc = load_session(session)
    src_id = ensure_source(doc, data)
    if not any(o["op"] == "open" and o.get("source") == src_id for o in doc["ops"]):
        append_op(doc, "open", source=src_id)  # 사용자가 안 쳐도 자동 녹화
    entry = append_op(doc, "select", source=src_id, cols=wanted)
    save_session(doc)
    typer.echo(msg("select_imported", n=len(wanted), head=", ".join(wanted[:5]),
                   more=" …" if len(wanted) > 5 else ""))
    typer.echo(msg("select_recorded", seq=entry["seq"], n=len(doc["ops"])))


@app.command()
def deselect(
    data: str,
    cols: str = typer.Option(..., help="제외할 컬럼 (쉼표 구분)"),
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
) -> None:
    """가져온 컬럼을 작업 영역에서 제외한다 (op: deselect) — 웹/셸의 체크 해제와 동일."""
    from statop.session.core import append_op, load_session, replay, save_session

    wanted = [c.strip() for c in cols.split(",") if c.strip()]
    doc = load_session(session)
    state = replay(doc)
    src_id = next((s["id"] for s in doc["sources"]), None)
    current = state["selected"].get(src_id, [])
    not_selected = [c for c in wanted if c not in current]
    if not_selected:
        raise typer.BadParameter(msg("deselect_err_not_selected", cols=", ".join(not_selected)))
    entry = append_op(doc, "deselect", source=src_id, cols=wanted)
    save_session(doc)
    remain = [c for c in current if c not in set(wanted)]
    typer.echo(msg("deselect_removed", n=len(wanted), cols=", ".join(wanted)))
    typer.echo(msg("deselect_recorded", seq=entry["seq"], n=len(remain)))


@app.command()
def labels(
    data: str,
    column: str = typer.Option(..., help="문자열 카테고리 컬럼"),
    session: str = typer.Option(None, help="세션 로그 (매핑 확정·조회용)"),
    map: str = typer.Option(None, "--map",
                            help="매핑 지정 — 예: control=0,hct=0,liver=1"),
    sample_n: int = 10_000,
) -> None:
    """라벨 매핑 () — 표시는 문자열, 계산은 코드. 여러 수준을 같은 코드로 묶으면 군이 바뀐다."""
    from statop.labels import groups_after, levels_of
    from statop.render.spark import bar
    from statop.session.core import append_op, load_session, main_source, replay, save_session

    mapping = None
    if map:
        try:
            mapping = {k.strip(): int(v) for k, v in
                       (item.split("=") for item in map.split(",") if item.strip())}
        except ValueError:
            raise typer.BadParameter(msg("labels_map_format"))
    elif session:
        doc = load_session(session)
        src = main_source(doc)
        if src:
            mapping = replay(doc)["label_maps"].get(src["id"], {}).get(column)

    try:
        lv = levels_of(data, column, sample_n=sample_n, mapping=mapping)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    typer.echo(msg("labels_head", column=column, n=len(lv)))
    for l in lv:
        flag = " ⚠" if l.ambiguous else ""
        cat = f" [{l.category}]" if l.category else ""
        typer.echo(f"  {l.value[:18]:<18s} → {l.code}  {bar(l.ratio, 12)} "
                   f"{l.ratio:>5.1%} ({l.n:,}){cat}{flag}")

    groups = groups_after(lv)
    if len(groups) < len(lv):   # 묶임이 일어났으면 군 구성을 반드시 보인다 (그룹 정의)
        typer.echo("")
        typer.echo(typer.style(msg("labels_regrouped", before=len(lv), after=len(groups)),
                               fg=typer.colors.YELLOW))
        for g in groups.values():
            typer.echo(f"    {msg('labels_group', code=g['code'], values=', '.join(g['values']), n=g['n'])}")

    if map and session:   # 확정 → op 기록
        doc = load_session(session)
        src = main_source(doc)
        if src is None:
            raise typer.BadParameter(msg("select_err_empty"))
        entry = append_op(doc, "label_map", source=src["id"], column=column, mapping=mapping)
        save_session(doc)
        typer.echo("")
        typer.echo(msg("labels_recorded", seq=entry["seq"], column=column))


@app.command()
def filter(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    expr: str = typer.Option(..., help='조건식 — 예: "age >= 18 and dx == \'liver\'"'),
    exclude: bool = typer.Option(False, "--exclude", help="조건에 맞는 행을 제외 (기본은 남김)"),
    reason: str = typer.Option(None, help="제외 사유 (출력에 첨부됨)"),
    apply: bool = typer.Option(False, "--apply", help="미리보기 대신 실제 기록"),
    sample_n: int = 10_000,
) -> None:
    """행 필터 (M0-6) — 기본은 **미리보기**, --apply로 기록한다. 사유는 출력에 첨부된다."""
    from statop.io.sample import sample_rows
    from statop.rowfilter import preview
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session)
    src = main_source(doc)
    if src is None:
        raise typer.BadParameter(msg("select_err_empty"))
    df = sample_rows(src["path"], n=sample_n)
    try:
        res = preview(df, expr, keep=not exclude)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    typer.echo(msg("filter_preview", expr=expr, kept=res.kept, removed=res.removed,
                   ratio=res.ratio_removed))
    if not apply:
        return
    entry = append_op(doc, "filter_rows", source=src["id"], expr=expr,
                      keep=not exclude, reason=reason)
    save_session(doc)
    typer.echo(msg("filter_recorded", seq=entry["seq"]))
    if reason:
        typer.echo(msg("filter_reason", reason=reason))


@app.command()
def derive(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    expr: str = typer.Option(..., help="수식 — 일반 표기 또는 LaTeX"),
    name: str = typer.Option(None, help="새 컬럼 이름 (생략 시 미리보기만)"),
    eps: float = typer.Option(None, help="eps 값 (추천값 이하만 허용)"),
    composition: str = typer.Option(None, help="clr/ilr용 조성 세트 (쉼표 구분)"),
    as_type: str = typer.Option(None, "--as", help="결과 의미 타입 (생략 시 수식에서 유도)"),
    sample_n: int = 10_000,
) -> None:
    """파생 컬럼 (M1-2) — 화이트리스트 수식만. **기본은 미리보기**, --name을 주면 커밋.
    eps는 추천값 이하만 허용한다(큰 eps는 log 척도를 왜곡)."""
    from statop.derive.parser import FormulaError
    from statop.derive.service import commit, prepare

    doc, src, df = _session_frame(session, sample_n)
    comp_cols = [c.strip() for c in composition.split(",")] if composition else None
    try:
        prep = prepare(df, expr, eps=eps, composition=comp_cols)
    except (FormulaError, ValueError) as e:
        raise typer.BadParameter(str(e))

    adv = prep.eps_advice
    if prep.eps_auto:
        typer.echo(typer.style(msg("eps_preview_with_recommended", value=prep.eps_used),
                               fg=typer.colors.YELLOW))
    if adv is not None and adv.recommended is not None:
        typer.echo(msg("eps_recommended", value=adv.recommended, minpos=adv.min_positive))
    if prep.alternative:
        # 규칙이 권하는 것을 도구가 못 해 주면 규칙이 거짓말이 된다 (S-R04 → F-15)
        typer.echo(typer.style("  " + prep.alternative, fg=typer.colors.CYAN))
        typer.echo("  " + msg("eps_candidates",
                              values=" · ".join(f"{c:g}" for c in adv.candidates)))

    pv = prep.preview
    typer.echo(msg("derive_preview_head", name=name or msg("derive_preview_label"),
                   expr=_color_expr(prep.tokens)))
    typer.echo("  " + msg("derive_preview_stats", n=pv["n"], n_finite=pv["n_finite"],
                          n_nan=pv["n_nan"], n_inf=pv["n_inf"]))
    if pv["n_finite"]:
        typer.echo("  " + msg("derive_preview_range", min=pv["min"], mean=pv["mean"],
                              max=pv["max"]))
    if pv["n_inf"]:
        typer.echo(typer.style("  " + msg("derive_inf_warning", n_inf=pv["n_inf"]),
                               fg=typer.colors.RED))
    if _SCALAR_ROLE in {t["role"] for t in prep.tokens}:
        typer.echo(typer.style("  " + msg("derive_scalar_note"), fg=typer.colors.YELLOW))
    if not name:
        return
    try:
        entry = commit(doc, src["id"], df, prep, name, eps,
                       composition=comp_cols, as_type=as_type)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(msg("derive_committed", name=name, type=as_type or prep.result_type))
    typer.echo(msg("derive_recorded", seq=entry["seq"]))


_SCALAR_ROLE = "column_scalar_func"

# 토큰 역할 → 터미널 색 (F-04). 웹은 같은 역할에 같은 뜻의 색을 쓴다.
_ROLE_COLOR = {
    "column": typer.colors.CYAN,
    "row_func": typer.colors.GREEN,
    _SCALAR_ROLE: typer.colors.MAGENTA,   # 행마다 변하지 않는다 — 행 단위와 섞이면 오해가 생긴다
    "set_func": typer.colors.BLUE,
    "pair_func": typer.colors.BLUE,
    "eps": typer.colors.YELLOW,
}


def _color_expr(tokens: list[dict]) -> str:
    """수식을 역할별 색으로 칠한다 — 어느 부분이 행마다 변하는지 눈으로 구분되게."""
    return "".join(typer.style(t["text"], fg=c) if (c := _ROLE_COLOR.get(t["role"]))
                   else t["text"] for t in tokens)


formula_app = typer.Typer(no_args_is_help=True, help="커스텀 수식 라이브러리 (M1-2)")
app.add_typer(formula_app, name="formula")


@formula_app.command("save")
def formula_save(
    name: str = typer.Option(..., help="수식 이름 (예: Lorentzian_Entropy)"),
    expr: str = typer.Option(..., help="수식 — 일반 표기 또는 LaTeX"),
    session: str = typer.Option(None, help="세션 (컬럼 검증용, 선택)"),
    result_type: str = typer.Option("continuous", help="결과 의미 타입"),
    note: str = typer.Option(None, help="메모"),
    overwrite: bool = typer.Option(False, help="같은 이름 덮어쓰기"),
    sample_n: int = 10_000,
) -> None:
    """수식을 이름으로 저장한다 — 쓰인 컬럼이 입력 슬롯이 된다."""
    from statop.derive.library import Formula, save
    from statop.derive.parser import FormulaError, parse

    cols = None
    if session:
        _, _, df = _session_frame(session, sample_n)
        cols = list(df.columns)
    try:
        parsed = parse(expr, cols)
    except FormulaError as e:
        raise typer.BadParameter(str(e))

    f = Formula(name=name, expr=parsed.expr,
                latex=expr if "\\" in expr else None,
                slots=parsed.columns, result_type=result_type, note=note,
                params={"uses_eps": parsed.uses_eps})
    try:
        path = save(f, overwrite=overwrite)
    except FileExistsError as e:
        typer.echo(typer.style(str(e), fg=typer.colors.RED))
        raise typer.Exit(1)
    typer.echo(msg("formula_saved", name=name, path=path))
    typer.echo("  " + msg("formula_list_line", name=name, slots=", ".join(f.slots),
                          result_type=result_type))


@formula_app.command("list")
def formula_list() -> None:
    """저장된 수식 목록 — 이름으로 찾는다 (파일명이 아니라)."""
    from statop.derive.library import load

    items = load()
    typer.echo(msg("formula_list_head", n=len(items)))
    for f in items.values():
        typer.echo("  " + msg("formula_list_line", name=f.name,
                              slots=", ".join(f.slots) or "-", result_type=f.result_type))
        if f.note:
            typer.echo(f"      {f.note}")


@formula_app.command("remove")
def formula_remove(name: str) -> None:
    """저장된 수식 삭제."""
    from statop.derive.library import remove

    try:
        remove(name)
    except KeyError as e:
        raise typer.BadParameter(str(e))
    typer.echo(msg("formula_removed", name=name))


@formula_app.command("apply")
def formula_apply(
    name: str = typer.Option(..., help="저장된 수식 이름"),
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    map: str = typer.Option(..., "--map", help="슬롯↔컬럼 — 예: frac=comp00_frac00"),
    out: str = typer.Option(None, "--out", help="새 컬럼 이름 (생략 시 미리보기)"),
    eps: float = typer.Option(None, help="eps"),
    sample_n: int = 10_000,
) -> None:
    """저장 수식을 다른 컬럼에 재사용 (M1-2). **3색 판정**을 함께 보여준다."""
    from statop.derive.library import applicability, bind, load
    from statop.derive.parser import FormulaError
    from statop.derive.service import commit, prepare
    from statop.session.core import replay

    items = load()
    if name not in items:
        raise typer.BadParameter(msg("formula_not_found", name=name))
    f = items[name]
    try:
        mapping = {k.strip(): v.strip() for k, v in
                   (item.split("=") for item in map.split(",") if item.strip())}
    except ValueError:
        raise typer.BadParameter(msg("labels_map_format"))

    doc, src, df = _session_frame(session, sample_n)
    types = replay(doc)["semantic_types"].get(src["id"], {})

    # 3색 판정 — 슬롯 타입 + 수식이 이미 적용한 권고 변환을 함께 본다
    try:
        prep = prepare(df, bind(f, mapping), eps=eps)
    except (KeyError, FormulaError, ValueError) as e:
        raise typer.BadParameter(str(e))
    verdict = applicability(f, types, mapping, functions=set(prep.parsed.functions))
    color = {"red": typer.colors.RED, "yellow": typer.colors.YELLOW,
             "green": typer.colors.GREEN}[verdict["verdict"]]
    typer.echo(typer.style(msg(f"formula_verdict_{verdict['verdict']}"), fg=color))
    if verdict["unconfirmed"]:
        typer.echo(typer.style("  " + msg("formula_unconfirmed",
                                          cols=", ".join(verdict["unconfirmed"])),
                               fg=typer.colors.YELLOW))
    for r in verdict["risks"]:
        if r["mitigated"]:
            typer.echo(typer.style("  " + msg("formula_risk_mitigated", id=r["id"],
                                              fix=r["fix"][:50]), fg=typer.colors.GREEN))
        else:
            typer.echo(typer.style(f"  [{r['id']}] {r['column']} ({r['type']}) — {r['why']}",
                                   fg=typer.colors.RED if r["verdict"] in ("red", "gate")
                                   else typer.colors.YELLOW))

    typer.echo(msg("formula_applied", name=name,
                   mapping=", ".join(f"{k}→{v}" for k, v in mapping.items()),
                   expr=_color_expr(prep.tokens)))

    pv = prep.preview
    typer.echo("  " + msg("derive_preview_stats", n=pv["n"], n_finite=pv["n_finite"],
                          n_nan=pv["n_nan"], n_inf=pv["n_inf"]))
    if not out:
        return
    try:
        entry = commit(doc, src["id"], df, prep, out, eps,
                       as_type=f.result_type, from_formula=name)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(msg("derive_committed", name=out, type=f.result_type))
    typer.echo(msg("derive_recorded", seq=entry["seq"]))


@app.command()
def types(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    confirm: str = typer.Option(None, "--confirm", help="확정할 컬럼"),
    as_type: str = typer.Option(None, "--as", help="확정할 의미 타입"),
    unconfirm: str = typer.Option(None, "--unconfirm", help="확정을 취소할 컬럼"),
    sample_n: int = 10_000,
) -> None:
    """의미 타입 판별 (M1-1) — 후보를 **순위로** 제시한다(점수 비표시).
    확정은 사용자가 하며, 추론과 다른 타입도 선택할 수 있다 — 막지 않고 위험을 고지한다."""
    from statop.semantic import infer_columns, shape_label
    from statop.semantic_risk import TYPE_RULES, risks_for
    from statop.session.core import append_op, replay, save_session

    from statop.derive.service import apply_ops

    doc, src, df = _session_frame(session, sample_n)
    # 파생 컬럼은 파일에 없다 — 이걸 안 붙이면 새로 만든 컬럼이 목록에 아예 안 뜬다
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    selected = st["selected"].get(src["id"], []) or list(df.columns)
    selected = [c for c in selected if c in df.columns]
    # 방금 만든 파생 컬럼도 확정 대상이다 (선택 목록에는 없지만 분석에는 쓰인다)
    selected += [d["name"] for d in st["derived"]
                 if d.get("source") == src["id"] and d["name"] in df.columns
                 and d["name"] not in selected]

    if unconfirm:
        # 기록을 지우지 않고 **취소했다는 조작**을 남긴다 — 되돌린 사실도 이력이다
        if unconfirm not in st["semantic_types"].get(src["id"], {}):
            raise typer.BadParameter(msg("semantic_not_confirmed", column=unconfirm))
        append_op(doc, "semantic_unconfirm", source=src["id"], column=unconfirm)
        save_session(doc)
        typer.echo(msg("semantic_unconfirmed", column=unconfirm))
        return

    if confirm:
        if confirm not in df.columns:
            raise typer.BadParameter(msg("select_err_missing", cols=confirm))
        known = sorted(set(TYPE_RULES) | {"continuous", "datetime", "composition set"})
        if not as_type:
            raise typer.BadParameter(msg("semantic_unknown_type", type="-",
                                         allowed=", ".join(known)))
        if as_type not in known:
            raise typer.BadParameter(msg("semantic_unknown_type", type=as_type,
                                         allowed=", ".join(known)))
        inferred = {c.type for t in infer_columns(df, [confirm]) for c in t.candidates}
        append_op(doc, "semantic_confirm", source=src["id"], column=confirm, type=as_type)
        save_session(doc)
        typer.echo(msg("semantic_confirmed", column=confirm, type=as_type))
        if as_type not in inferred:   # 추론에 없던 타입 — 막지 않되 고지한다 (요구사항-7)
            typer.echo(typer.style(msg("semantic_not_inferred", type=as_type),
                                   fg=typer.colors.YELLOW))
        risks = risks_for(as_type)
        if risks:
            typer.echo("")
            typer.echo(msg("semantic_risk_head"))
            for r in risks:
                color = {"red": typer.colors.RED, "gate": typer.colors.RED,
                         "yellow": typer.colors.YELLOW}.get(r["verdict"])
                typer.echo(typer.style("  " + msg("risk_line", id=r["id"],
                                                  combination=r["combination"]), fg=color))
                typer.echo("    " + msg("risk_why", why=r["why"]))
                typer.echo("    " + msg("risk_fix", fix=r["fix"]))
        return

    confirmed = st["semantic_types"].get(src["id"], {})
    infs = infer_columns(df, selected)
    for t in infs:
        mark = ""
        if t.column in confirmed:
            mark = f"  ✔ {confirmed[t.column]}"
        typer.echo(msg("semantic_head", column=t.column, shape=shape_label(t.shape)) + mark)
        for c in t.candidates[:4]:
            typer.echo("    " + msg("semantic_cand", rank=c.rank, type=c.type)
                       + "  — " + " · ".join(c.evidence[:2]))
        for cf in t.conflicts:
            typer.echo(typer.style("    ⚠ " + cf, fg=typer.colors.YELLOW))
        if t.needs_confirm and t.column not in confirmed:
            typer.echo(typer.style("    → " + t.confirm_reason, fg=typer.colors.YELLOW))
    pending = [t.column for t in infs if t.column not in confirmed]
    typer.echo("")
    typer.echo(msg("semantic_state", n_confirmed=len(confirmed), n_pending=len(pending)))


@app.command()
def groups(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    confirm: str = typer.Option(None, "--confirm", help="확정할 컬럼"),
    kind: str = typer.Option(None, help="subject|batch|site|time"),
    sample_n: int = 10_000,
) -> None:
    """그룹 구조 감지 (M0-7) — 반복측정·환자·batch·기관 후보. **확정은 사용자가 한다.**
    확정된 구조는 독립 가정 검정(C-05)에서 쓰인다."""
    from statop.groups import detect
    from statop.session.core import append_op, save_session

    doc, src, df = _session_frame(session, sample_n)

    if confirm:
        if confirm not in df.columns:
            raise typer.BadParameter(msg("select_err_missing", cols=confirm))
        if kind not in ("subject", "batch", "site", "time"):
            raise typer.BadParameter(msg("group_confirm_hint"))
        append_op(doc, "group_confirm", source=src["id"], column=confirm, kind=kind)
        save_session(doc)
        typer.echo(msg("group_confirmed", col=confirm, kind=kind))
        return

    cands = detect(df)
    real = [g for g in cands if not g.is_identifier]
    if not cands:
        typer.echo(msg("group_none"))
        return
    typer.echo(msg("group_head", n=len(real)))
    for g in cands:
        line = "  " + msg("group_line", col=g.column, kind=g.kind, levels=g.n_levels,
                          mean=g.mean_per_group, mx=g.max_per_group)
        if g.is_identifier:
            typer.echo(typer.style(line + " — " + g.reason, fg=typer.colors.BRIGHT_BLACK))
        else:
            extra = "" if g.balanced else " · " + msg("group_imbalanced")
            typer.echo(typer.style(line + extra, fg=typer.colors.YELLOW))
    typer.echo("")
    typer.echo(typer.style(msg("group_confirm_hint"), fg=typer.colors.BRIGHT_BLACK))


@app.command()
def compose(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 10_000,
) -> None:
    """구성 요약 (M0-2b) — 가져온 컬럼만 대상으로 한 눈에. 데이터 셀은 보이지 않는다."""
    from statop.derive.service import apply_ops
    from statop.groups import compose as compose_summary
    from statop.session.core import main_source, replay

    doc, src, df = _session_frame(session, sample_n)
    # 선택 목록에는 파생 컬럼도 들어 있다 — 안 붙이면 그 이름으로 프레임을 찾다 죽는다
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    sid = src["id"]
    c = compose_summary(df, st["selected"].get(sid, []), st["held"].get(sid, []))
    typer.echo(msg("compose_head", n_rows=c["n_rows"], n_selected=c["n_selected"],
                   n_analysis=c["n_analysis"], n_held=c["n_held"]))
    typer.echo("  " + msg("compose_kinds", **c["kinds"]))
    typer.echo("  " + msg("compose_missing", complete=c["complete_rows"], any=c["any_missing"]))
    # 세션에 쌓인 조작이 있으면 함께 — 무엇이 적용된 상태인지 알 수 있게
    if st["filters"]:
        typer.echo("  " + msg("filter_preview", expr=st["filters"][-1]["expr"],
                              kept=c["n_rows"], removed=0, ratio=0.0))
    if st["relabels"]:
        typer.echo(typer.style("  " + msg("relabel_notice", n=len(st["relabels"])),
                               fg=typer.colors.YELLOW))


missing_app = typer.Typer(no_args_is_help=True, help="결측 처리 (M0-6b)")
app.add_typer(missing_app, name="missing")


def _session_frame(session: str, sample_n: int):
    from statop.derive.service import session_frame

    try:
        return session_frame(session, sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))


@missing_app.command("show")
def missing_show(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 10_000,
) -> None:
    """결측 현황·패턴 (M0-6b) — 어떤 컬럼 조합이 함께 비는지까지."""
    from statop.missing import report

    _, _, df = _session_frame(session, sample_n)
    r = report(df)
    typer.echo(msg("missing_head", n_rows=r.n_rows, complete=r.complete_rows))
    for c in r.columns:
        if not c.n_missing and not c.suspect_zero_filled:
            continue
        line = "  " + msg("missing_col_line", col=c.column, n=c.n_missing, ratio=c.ratio)
        if c.suspect_zero_filled:
            line += " — " + msg("missing_suspect_zero", zero=c.zero_ratio)
            typer.echo(typer.style(line, fg=typer.colors.YELLOW))
        elif c.high:
            typer.echo(typer.style(line, fg=typer.colors.YELLOW))
        else:
            typer.echo(line)
    if r.patterns:
        typer.echo("")
        typer.echo(msg("missing_pattern_head", n=len(r.patterns)))
        for p in r.patterns:
            typer.echo("  " + msg("missing_pattern_line", cols=", ".join(p["columns"]),
                                  n=p["n"], ratio=p["ratio"]))


@missing_app.command("drop")
def missing_drop(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    cols: str = typer.Option(None, help="기준 컬럼 (쉼표 구분, 생략 시 전체)"),
    how: str = typer.Option("row", help="row=행 제거 / column=컬럼 제거"),
    apply: bool = typer.Option(False, "--apply", help="미리보기 대신 기록"),
    sample_n: int = 10_000,
) -> None:
    """NA 제거 (M0-6b) — 기본은 미리보기. 전/후 n이 항상 남는다."""
    from statop.missing import drop_na
    from statop.session.core import append_op, save_session

    doc, src, df = _session_frame(session, sample_n)
    targets = [c.strip() for c in cols.split(",")] if cols else None
    try:
        out = drop_na(df, targets, how=how)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    if how == "column":
        removed = [c for c in df.columns if c not in out.columns]
        typer.echo(msg("missing_drop_cols", cols=", ".join(removed) or "-"))
    else:
        typer.echo(msg("missing_drop_result", before=len(df), after=len(out),
                       removed=len(df) - len(out)))
    if not apply:
        return
    entry = append_op(doc, "missing_drop", source=src["id"], cols=targets, how=how,
                      n_before=len(df), n_after=len(out))
    save_session(doc)
    typer.echo(msg("missing_recorded", seq=entry["seq"], op="missing_drop"))


@missing_app.command("impute")
def missing_impute(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    method: str = typer.Option(..., help="zero|mean|median|mode|group_mean|group_median|knn|mice"),
    cols: str = typer.Option(..., help="대치할 컬럼 (쉼표 구분)"),
    group_by: str = typer.Option(None, help="그룹별 대치의 그룹 컬럼"),
    seed: int = 0,
    apply: bool = typer.Option(False, "--apply", help="미리보기 대신 기록"),
    sample_n: int = 10_000,
) -> None:
    """경량 대치 (M0-6b 1.1a) — 허용 목록 밖 방법은 실행하지 않는다."""
    from statop.missing import impute
    from statop.session.core import append_op, save_session

    doc, src, df = _session_frame(session, sample_n)
    targets = [c.strip() for c in cols.split(",") if c.strip()]
    try:
        _, info = impute(df, method, targets, group_by=group_by, seed=seed)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    except ImportError as e:
        raise typer.BadParameter(str(e))

    for w in info["warnings"]:
        typer.echo(typer.style("  ⚠ " + w, fg=typer.colors.YELLOW))
    typer.echo(msg("missing_impute_result", method=method, n_filled=info["n_filled"],
                   ratio=info["ratio_filled"]))
    if info["params"] or info["seed"] is not None:
        typer.echo(msg("missing_impute_params",
                       params={**info["params"], **({"seed": info["seed"]} if info["seed"] is not None else {})}))
    if not apply:
        return
    entry = append_op(doc, "impute", source=src["id"], method=method, cols=targets,
                      group_by=group_by, seed=info["seed"], params=info["params"],
                      n_filled=info["n_filled"])
    save_session(doc)
    typer.echo(msg("missing_recorded", seq=entry["seq"], op="impute"))


def _goal_line(g: dict) -> str:
    """Goal 한 줄 — 지정한 지표로 아직 잰 값이 없으면 남의 값을 붙이지 않는다."""
    if g.get("value") is None:
        return msg("metrics_goal_line_pending", name=g.get("name") or "-",
                   score=g.get("score") or "-",
                   measured=g.get("measured_by") or "-")
    return msg("metrics_goal_line", test=g.get("test") or "-",
               name=g.get("name") or "-", eff=g.get("effect") or "-",
               val=g["value"], p=g["p"] if g.get("p") is not None else float("nan"))


@app.command()
def metrics(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 10_000,
) -> None:
    """S170 보조(Support)·가드레일(Guardrail) 지표 병기 제안 — 실행한 검정 기준.

    Goal 하나만 보면 '얼마나'를 모르거나, 한쪽을 올리느라 다른 쪽이 무너지는 것을 놓친다."""
    from statop.analyze.metrics import compute, suggest

    try:
        panel = suggest(session, sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    g = panel.goal
    typer.echo(typer.style(_goal_line(g), bold=True))
    for role, head, color in ((panel.support, "metrics_head_support", typer.colors.CYAN),
                              (panel.guardrail, "metrics_head_guardrail",
                               typer.colors.YELLOW)):
        typer.echo("")
        typer.echo(typer.style(msg(head), fg=color, bold=True))
        if not role:
            typer.echo("  " + msg("metrics_none"))
        for sug in role:
            typer.echo(f"  [{sug.id}] {sug.name}"
                       + ("" if sug.computable else f"  ({msg('metrics_check_only')})"))
            if sug.why:
                typer.echo(typer.style(f"        {sug.why}", dim=True))
            if not sug.computable:
                continue
            try:
                for line in compute(session, sug.id, sample_n)["lines"]:
                    typer.echo(f"        · {line}")
            except (ValueError, KeyError) as e:
                typer.echo(typer.style(f"        · {e}", fg=typer.colors.RED))
    if panel.triad:
        t = panel.triad
        typer.echo("")
        typer.echo(typer.style(msg("metrics_head_triad"), bold=True))
        typer.echo("  " + msg("metrics_triad_row", id=t["id"], situation=t["situation"],
                              goal=t["goal"], support=t["support"],
                              guardrail=t["guardrail"]))


@app.command()
def tablediff(
    a: str = typer.Argument(..., help="기준 파일"),
    b: str = typer.Argument(..., help="비교할 파일"),
    key: str = typer.Option(None, help="행을 맞출 키 컬럼 (생략 시 첫 컬럼)"),
    cols: str = typer.Option(None, help="이 컬럼들만 비교 (쉼표 구분, 생략 시 전부)"),
    pair: list[str] = typer.Option(None, "--pair", help="이름이 다른 같은 컬럼: A이름=B이름 (여러 번 가능)"),
    view: str = typer.Option(None, "--view", help="한 컬럼을 A/B 로 겹쳐 본다 (개형·평균·중앙·최소·최대·분포 거리)"),
    show_values: bool = typer.Option(False, "--show-values", help="바뀐 실제 값 예시도 표시"),
) -> None:
    """표 상세 대조  — 두 파일을 키 컬럼 기준으로 맞춰 행·컬럼·셀 차이를 낸다.

    **전체 읽기**라 명시 호출 전용이다. 다르면 종료코드 1."""
    from statop.integrity import MAX_SHOWN, compare_tables

    columns = [c.strip() for c in (cols or "").split(",") if c.strip()] or None
    try:
        pairs = dict(x.split("=", 1) for x in (pair or []))
    except ValueError:
        raise typer.BadParameter(msg("labels_map_format"))
    try:
        r = compare_tables(a, b, key=key, columns=columns, show_values=show_values,
                           pairs=pairs)
    except (ValueError, FileNotFoundError) as e:
        raise typer.BadParameter(str(e))

    if view:
        # 한 컬럼만 자세히 — "바뀐 셀 2개"로는 어디가 어떻게 옮겼는지 알 수 없다
        from statop.integrity import column_view

        try:
            v = column_view(a, b, r.key, view, pairs)
        except (ValueError, OSError, KeyError) as e:
            raise typer.BadParameter(str(e))
        for line in v["lines"]:
            typer.echo(line)
        raise typer.Exit(0 if v["n_diff"] == 0 else 1)

    typer.echo(typer.style(msg("tablediff_head", key=r.key), bold=True))
    if r.note:
        typer.echo(typer.style("  " + r.note, fg=typer.colors.YELLOW))
    if r.identical:
        typer.echo(typer.style(msg("tablediff_same", rows=r.rows_a, key=r.key),
                               fg=typer.colors.GREEN))
        return

    typer.echo(typer.style(
        "  " + msg("screen_verify_verdict_diff",
                   rows=len(r.rows_added) + len(r.rows_removed),
                   cells=r.cells_changed,
                   cols=len(r.cols_added) + len(r.cols_removed)),
        fg=typer.colors.RED, bold=True))
    common = r.rows_a - len(r.rows_removed)
    typer.echo(typer.style("  " + msg("tablediff_rows", common=common,
                                      added=len(r.rows_added),
                                      removed=len(r.rows_removed)),
                           fg=typer.colors.RED))
    for mark, items in (("+", r.rows_added), ("−", r.rows_removed)):
        for k in items[:MAX_SHOWN]:
            typer.echo(typer.style(f"    {mark} {k}", fg=typer.colors.RED))
        if len(items) > MAX_SHOWN:
            typer.echo("    " + msg("tablediff_more", n=len(items) - MAX_SHOWN))
    if r.cols_added or r.cols_removed:
        typer.echo(typer.style(
            "  " + msg("tablediff_cols", added=", ".join(r.cols_added) or "-",
                       removed=", ".join(r.cols_removed) or "-"),
            fg=typer.colors.RED))
    diff_cols = [c for c in r.columns if c["n_diff"]]
    if r.columns:
        typer.echo(typer.style("  " + msg("screen_verify_bycol_head", n=len(r.columns),
                                          n_diff=len(diff_cols)), bold=True))
    for c in diff_cols[:MAX_SHOWN * 2]:
        if c["kind"] == "numeric" and c["n_diff"] == 1:
            body = msg("screen_verify_bycol_one", col=c["column"], n_diff=c["n_diff"],
                       n=f"{c['n']:,}", ratio=f"{c['ratio']:.1%}",
                       max=f"{c['max_abs']:.4g}")
        elif c["kind"] == "numeric":
            body = msg("screen_verify_bycol_num", col=c["column"], n_diff=c["n_diff"],
                       n=f"{c['n']:,}", ratio=f"{c['ratio']:.1%}",
                       median=f"{c['median_abs']:.4g}", max=f"{c['max_abs']:.4g}")
        else:
            body = msg("screen_verify_bycol_other", col=c["column"], n_diff=c["n_diff"],
                       n=f"{c['n']:,}", ratio=f"{c['ratio']:.1%}")
        typer.echo(typer.style("  ⛔ " + body, fg=typer.colors.RED))
        if c["example"]:
            e = c["example"]
            typer.echo(typer.style("       " + msg("screen_verify_bycol_ex",
                                                   key=e["key"], from_=e["from"],
                                                   to=e["to"]), dim=True))
    if r.same_columns:
        typer.echo(typer.style("  ✅ " + msg("screen_verify_same_cols",
                                             n=len(r.same_columns)),
                               fg=typer.colors.GREEN))
    if r.unmatched:
        typer.echo(typer.style("  " + msg("screen_verify_unmatched_head",
                                          n=len(r.unmatched)), bold=True))
        for u in r.unmatched[:MAX_SHOWN]:
            typer.echo(typer.style(f"    {u['column']} — {u['why']}",
                                   fg=typer.colors.YELLOW))
    if diff_cols and not show_values:
        # 컬럼마다 한 건은 이미 보였다 — 더 보려면 이라고 말해야 맞다
        typer.echo(typer.style("  " + msg("tablediff_values_hint"), dim=True))
    raise typer.Exit(1)


@app.command()
def find(
    query: str = typer.Argument(..., help="찾을 말 (예: 상관, correlation, 생존)"),
    limit: int = typer.Option(15, help="표시 개수"),
) -> None:
    """지표·검정을 이름으로 찾는다 — **어느 목록에 있는지**까지 알려준다.

    상관계수는 점수 목록이 아니라 Q-03 연관 질문의 검정이다. 어디 있는지 모르면 못 찾는다."""
    from statop.analyze.find import search

    try:
        r = search(query, limit)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    if not r.hits:
        typer.echo(msg("find_none", query=query))
        return
    typer.echo(msg("find_head", query=query, n=len(r.hits)))
    for h in r.hits:
        typer.echo(typer.style(f"  [{msg('find_kind_' + h.kind)}] {h.name}",
                               bold=h.direct))
        typer.echo(typer.style(f"      {h.where}", dim=True))
        typer.echo(typer.style(f"      {h.how}", dim=True))


def _pad(text: str, width: int) -> str:
    """터미널 칸 수 기준으로 자르고 채운다 — 한글 한 글자는 두 칸이다."""
    from unicodedata import east_asian_width

    def w(ch: str) -> int:
        return 2 if east_asian_width(ch) in "WF" else 1

    out, used = "", 0
    for ch in text:
        if used + w(ch) > width:
            break
        out += ch
        used += w(ch)
    return out + " " * (width - used)


@app.command()
def scores(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    grade: str = typer.Option(None, help="등급 필터: green|yellow|red|unset"),
    family: str = typer.Option(None, help="계열 필터: ERR|CLS|DIST|DIV|ENT|VAR|NORM|BE|CLN|INF"),
    show_latex: bool = typer.Option(False, "--latex", help="수식과 대입식도 표시"),
    by_purpose: bool = typer.Option(False, "--groups", help="같은 목적끼리 묶어 보기 "),
    detail: bool = typer.Option(False, "--detail", help="재는 것·읽는 법·강건성 이유까지"),
    page: int = typer.Option(1, "--page", help="몇 쪽을 볼지"),
    per: int = typer.Option(10, "--per", help="한 쪽에 몇 개"),
    sample_n: int = 10_000,
) -> None:
    """M3 점수 목록  — 지금 데이터에 대본 4등급.

    미지정(회색)은 '적합하다'가 아니라 '판정할 근거가 아직 없다'는 뜻이다."""
    from statop.analyze.scores import GREEN, RED, UNSET, YELLOW, catalog

    try:
        rows = catalog(session, sample_n, family=family)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    if grade:
        rows = [r for r in rows if r.verdict == grade]

    icon = {GREEN: "✅", YELLOW: "⚠ ", RED: "⛔", UNSET: "○ "}
    color = {GREEN: typer.colors.GREEN, YELLOW: typer.colors.YELLOW,
             RED: typer.colors.RED, UNSET: typer.colors.WHITE}

    def _page(items: list) -> list:
        """한 쪽만 잘라 낸다. 122줄이 한 번에 쏟아지면 위쪽은 스크롤 밖으로 사라진다."""
        pages = max(1, -(-len(items) // max(1, per)))
        if page < 1 or page > pages:
            raise typer.BadParameter(msg("list_page_out_of_range", page=page,
                                         pages=pages))
        return items[(page - 1) * per: page * per], pages

    def _foot(n: int, pages: int, extra: str = "") -> None:
        typer.echo(typer.style(msg("list_page", page=page, pages=pages, n=n), bold=True))
        if page < pages:
            nxt = f"statop scores --page {page + 1}{extra}"
            typer.echo(typer.style(msg("list_page_next", how=nxt), dim=True))
        if not detail:
            typer.echo(typer.style(
                msg("list_detail_hint", how=f"statop scores --detail{extra}"), dim=True))

    def _one_line(r, ind: str = "") -> None:  # noqa: ANN001
        """한 줄 요약 — 판정 · ID · 이름 · 강건성 · 무엇을 재는 묶음인가."""
        typer.echo(typer.style(f"{ind}{icon[r.verdict]} {r.id:<11s} {_pad(r.name, 28)}",
                               fg=color[r.verdict])
                   + typer.style(f"  {r.purpose_name}", dim=True))

    def _axes(r, ind: str = "     ") -> None:  # noqa: ANN001
        """무엇을 재고, 어떻게 읽고, 얼마나 버티는가  — --detail 일 때만."""
        if r.measures:
            typer.echo(typer.style(f"{ind}{msg('scores_measures', text=r.measures)}",
                                   dim=True))
        if r.scale:
            typer.echo(typer.style(f"{ind}{msg('scores_scale', text=r.scale)}", dim=True))
        if r.shaken_by:
            typer.echo(typer.style(f"{ind}{msg('scores_shaken_by', text=r.shaken_by)}",
                                   fg=typer.colors.CYAN))
        if r.recommend:
            typer.echo(typer.style(f"{ind}{msg('scores_recommend', text=r.recommend)}",
                                   fg=typer.colors.CYAN))
        if r.source:
            typer.echo(typer.style(f"{ind}{msg('scores_source', text=r.source)}",
                                   dim=True))

    def _legend(_: bool = False) -> None:
        typer.echo(typer.style(msg("scores_shaken_note"), dim=True))

    if by_purpose:
        from statop.analyze.scores import groups as _groups

        gs = _groups(session, sample_n, family=family)
        if grade:
            gs = [g for g in gs if any(e.verdict == grade for e in g.entries)]
        shown, pages = _page(gs)
        typer.echo(msg("scores_groups_head", n=len(gs)))
        for g in shown:
            typer.echo(typer.style(
                msg("scores_group_line", pid=g.id, name=g.name, n=len(g.entries)),
                bold=True))
            for r in g.entries:
                if grade and r.verdict != grade:
                    continue
                _one_line(r, "  ")
                if detail:
                    _axes(r, "       ")
        _legend()
        typer.echo(typer.style(msg("scores_pick_one"), dim=True))
        _foot(len(gs), pages, " --groups")
        return

    shown, pages = _page(rows)
    typer.echo(msg("scores_head", n=len(rows)))
    for r in shown:
        _one_line(r)
        if detail:
            typer.echo(typer.style(f"     {r.why}", dim=True))
            _axes(r)
            if show_latex and r.latex:
                typer.echo(f"     {r.latex}")
                if r.substituted:
                    typer.echo(f"     → {r.substituted}")
    _legend()
    typer.echo(typer.style(msg("scores_unset_meaning"), dim=True))
    _foot(len(rows), pages)


@app.command()
def represent(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    cols: str = typer.Option(None, help="볼 컬럼 (쉼표, 생략 시 선택한 컬럼 전부)"),
    metric: str = typer.Option("ks", help="연속 컬럼 거리: ks | wasserstein (범주는 항상 총변동거리)"),
    threshold: float = typer.Option(0.05, help="'충분하다'로 볼 거리 — 관행일 뿐이다"),
    repeats: int = typer.Option(20, help="n 마다 다시 뽑는 횟수"),
    seed: int = typer.Option(0, help="재현용 seed"),
    steps: int = typer.Option(10, help="n 사다리 칸 수"),
    check_n: int = typer.Option(None, "--check", help="이 n 을 남은 행과 대조해 확인 (T-1204)"),
    spread_n: int = typer.Option(None, "--spread", help="이 n 에서 여러 번 다시 뽑아 거리들의 분포를 본다"),
    draws: int = typer.Option(200, help="--spread 에서 다시 뽑는 횟수"),
    sample_n: int = 1_000_000,
) -> None:
    """Q-12 표본 크기·대표성  — 몇 행이면 전체를 닮는가.

    답이 p 값이 아니라 n 이다. 전체와의 거리가 더 안 줄어드는 지점을 찾는다."""
    from statop.analyze.represent import KS, W1, build, spread, statement, verify

    want = {"ks": KS, "wasserstein": W1, "w1": W1}.get(metric.lower())
    if want is None:
        raise typer.BadParameter(msg("represent_bad_metric", got=metric))
    picked = [c.strip() for c in cols.split(",")] if cols else None

    if check_n is not None:
        try:
            rows = verify(session, check_n, picked, seed=seed, sample_n=sample_n)
        except ValueError as e:
            raise typer.BadParameter(str(e))
        rest = rows[0].n_rest if rows else 0
        typer.echo(msg("represent_verify_head", n=check_n, rest=rest))
        typer.echo(typer.style("  " + msg("represent_verify_not_full"), dim=True))
        for h in rows:
            if h.p is not None and h.p < 0.05:
                # 유의하다고 곧장 "다르다"가 되면 안 된다 — 거리의 규모를 같이 말한다
                typer.echo(typer.style(
                    "  " + msg("represent_verify_p_small", col=h.column, p=h.p,
                               d=h.distance), fg=typer.colors.YELLOW))
                continue
            key = "represent_verify_p" if h.p is not None else "represent_verify_line"
            kw = {"col": h.column, "d": h.distance}
            kw.update({"p": h.p} if h.p is not None else {"metric": h.metric})
            typer.echo(f"  {msg(key, **kw)}")
        typer.echo(typer.style(msg("represent_verify_p_note"), fg=typer.colors.CYAN))
        return

    if spread_n is not None:
        try:
            sps = spread(session, spread_n, picked, metric=want, draws=draws,
                         seed=seed, sample_n=sample_n)
        except ValueError as e:
            raise typer.BadParameter(str(e))
        if not sps:
            raise typer.BadParameter(msg("represent_bad_n", n=spread_n, total=0))
        typer.echo(msg("represent_spread_head", n=spread_n, draws=sps[0].draws))
        typer.echo(typer.style("  " + msg("represent_spread_why"), dim=True))
        width = max(1, max(cnt for sp in sps for _, _, cnt in sp.bins))
        for sp in sps:
            typer.echo(typer.style(msg("represent_spread_q", col=sp.column,
                                       metric=sp.metric_name, **sp.q), bold=True))
            for left, right, cnt in sp.bins:
                bar = "█" * round(28 * cnt / width)
                typer.echo(typer.style(f"    {left:.4f}~{right:.4f} {bar} {cnt}",
                                       dim=not cnt))
            typer.echo(typer.style(msg("represent_spread_suggest", col=sp.column,
                                       p95=sp.q["p95"], th=threshold),
                                   fg=typer.colors.CYAN))
        return

    # 컬럼이 많으면 분 단위로 걸린다 — 즉시 반응·% ·남은 시간을 낸다
    import sys
    import time

    from statop.shell.screen import format_eta

    t0 = time.time()

    def _tick(frac: float) -> None:
        done = time.time() - t0
        eta = format_eta((done / frac - done)) if frac > 0.02 else ""
        sys.stderr.write(f"\r  {frac * 100:5.1f}%  {eta}   ")
        sys.stderr.flush()

    _tick(0.0)
    rep = build(session, picked, metric=want, threshold=threshold,
                repeats=repeats, seed=seed, steps=steps, sample_n=sample_n,
                progress=_tick)
    sys.stderr.write("\r" + " " * 40 + "\r")

    typer.echo(msg("represent_head", total=rep.total_rows))
    typer.echo(typer.style("  " + msg("represent_repeats", r=rep.repeats,
                                      seed=rep.seed), dim=True))
    if rep.skipped_ids:
        typer.echo(typer.style("  " + msg("represent_skipped_ids",
                                          cols=", ".join(rep.skipped_ids)), dim=True))
    for c in rep.curves:
        typer.echo(typer.style(msg("represent_col_head", col=c.column, kind=c.kind,
                                   metric=c.metric_name), bold=True))
        typer.echo("  " + " ".join(f"{p.n}:{p.mean:.3f}" for p in c.points))
        if c.enough_n is None:
            typer.echo(typer.style("  " + msg("represent_col_never", th=threshold),
                                   fg=typer.colors.RED))
        else:
            typer.echo(typer.style("  " + msg("represent_col_enough", n=c.enough_n,
                                              th=threshold), fg=typer.colors.GREEN))

    if rep.enough_n is not None:
        pct = round(100 * rep.enough_n / rep.total_rows, 1)
        typer.echo(typer.style(msg("represent_enough", n=rep.enough_n, th=threshold,
                                   pct=pct), fg=typer.colors.GREEN, bold=True))
        typer.echo(msg("represent_limiting", cols=", ".join(rep.limiting)))
        head, how = statement(rep)
        typer.echo(typer.style("  " + head, bold=True))
        typer.echo(typer.style("  " + how, dim=True))
    elif rep.limiting:
        typer.echo(typer.style(msg("represent_never", cols=", ".join(rep.limiting),
                                   th=threshold), fg=typer.colors.RED))
    if want == W1:
        typer.echo(typer.style(msg("represent_unit_bound"), fg=typer.colors.YELLOW))
    typer.echo(typer.style(msg("represent_threshold_convention", th=threshold),
                           fg=typer.colors.CYAN))


@app.command()
def robust(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    draws: int = typer.Option(200, help="표본을 다시 뽑는 횟수"),
    seed: int = typer.Option(0, help="재현용 seed"),
    sample_n: int = 10_000,
) -> None:
    """강건성 — 지금 낸 결론이 얼마나 버티나 (표본·이상치·고른 검정을 흔들어 본다)."""
    import sys
    import time

    from statop.analyze.robust import build, verdict
    from statop.shell.screen import format_eta

    t0 = time.time()

    def tick(frac: float) -> None:
        done = time.time() - t0
        eta = format_eta(done / frac - done) if frac > 0.02 else ""
        sys.stderr.write(f"\r  {frac * 100:5.1f}%  {eta}   ")
        sys.stderr.flush()

    tick(0.0)
    try:
        rep = build(session, draws=draws, seed=seed, sample_n=sample_n, progress=tick)
    except ValueError as e:
        sys.stderr.write("\r" + " " * 40 + "\r")
        raise typer.BadParameter(str(e))
    sys.stderr.write("\r" + " " * 40 + "\r")

    typer.echo(msg("robust_head"))
    typer.echo("  " + msg("robust_base", test=rep.test, name=rep.name,
                          eff=rep.effect_name, value=rep.effect, p=rep.p, n=rep.n_rows))

    def line(sh, ind: str = "     ") -> None:  # noqa: ANN001
        if sh.failed:
            typer.echo(typer.style(
                f"{ind}{msg('robust_line_failed', label=sh.label, why=sh.failed)}",
                fg=typer.colors.YELLOW))
            return
        txt = msg("robust_line", label=sh.label, eff=sh.effect_name or rep.effect_name,
                  value=sh.effect, p=sh.p)
        if sh.flipped:
            txt += "  ← " + msg("robust_flipped_mark")
        typer.echo(typer.style(f"{ind}{txt}",
                               fg=typer.colors.RED if sh.flipped else None))

    typer.echo()
    typer.echo(typer.style("  " + msg("robust_boot_head", draws=rep.draws,
                                      seed=rep.seed), bold=True))
    if rep.boot_q:
        typer.echo("     " + msg("robust_band", lo=rep.boot_q["p5"], hi=rep.boot_q["p95"],
                                 q25=rep.boot_q["p25"], q75=rep.boot_q["p75"],
                                 n=len(rep.boot)))
    typer.echo()
    typer.echo(typer.style("  " + msg("robust_outlier_head"), bold=True))
    for sh in rep.outliers:
        line(sh)
    typer.echo(typer.style("     " + msg("robust_caveat"), dim=True))
    typer.echo()
    typer.echo(typer.style("  " + msg("robust_choice_head"), bold=True))
    for sh in rep.choices:
        line(sh)
    typer.echo()
    typer.echo(typer.style("  " + msg("robust_read_head"), bold=True))
    band = msg("robust_band", lo=rep.boot_q.get("p5", 0), hi=rep.boot_q.get("p95", 0),
               q25=rep.boot_q.get("p25", 0), q75=rep.boot_q.get("p75", 0),
               n=len(rep.boot)) if rep.boot_q else ""
    for ln in verdict(rep):
        if ln == band:          # ①에서 이미 보였다 — 두 번 적지 않는다
            continue
        typer.echo(typer.style("     " + ln, fg=typer.colors.CYAN))


@app.command()
def refs(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    limit: int = typer.Option(5, help="가져올 논문 수"),
    no_labels: bool = typer.Option(False, "--no-labels",
                                   help="군 라벨 이름을 검색어에서 뺀다"),
) -> None:
    """A6 논문 앵커 — 비슷한 질문·검정을 다룬 논문의 제목·PMID ."""
    from statop.hypothesis.refs import build

    a = build(session, limit=limit, include_labels=not no_labels)
    typer.echo(msg("refs_head"))
    typer.echo(typer.style("  " + msg("refs_privacy"), dim=True))
    if no_labels:
        typer.echo(typer.style("  " + msg("refs_no_labels"), dim=True))
    if a.failed:
        typer.echo(typer.style("  " + a.failed, fg=typer.colors.YELLOW))
        return
    typer.echo("  " + msg("refs_query", q=a.query))
    if a.broadened:
        typer.echo(typer.style("  " + msg("refs_broadened"), fg=typer.colors.YELLOW))
    if not a.papers:
        typer.echo(typer.style("  " + msg("refs_none"), fg=typer.colors.YELLOW))
        return
    for pp in a.papers:
        typer.echo(typer.style("  " + msg("refs_line", title=pp.title), bold=True))
        typer.echo(typer.style("     " + msg("refs_meta", pmid=pp.pmid,
                                             journal=pp.journal, year=pp.year,
                                             url=pp.url), dim=True))
    typer.echo(typer.style("  " + msg("refs_title_only"), dim=True))


@app.command()
def entropy(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    column: str = typer.Option(..., help="엔트로피를 잴 컬럼"),
    sample_n: int = 10_000,
) -> None:
    """S169 분포 의존 분기 — 연속 분포 엔트로피는 분포마다 공식이 다르다."""
    from statop.analyze.scores import entropy_branch

    try:
        b = entropy_branch(session, column, sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(typer.style(msg("scores_ent_head", col=b.column), bold=True))
    typer.echo("  " + msg("scores_ent_facts", **{k: b.facts[k] for k in
                                                 ("n", "positive", "unit", "skewed",
                                                  "heavy_tail", "normal")}))
    typer.echo(typer.style(f"  → {b.picked} {b.name}", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"     {b.why}")
    typer.echo(f"     {b.latex}")
    if b.rejected:
        typer.echo(typer.style("  " + msg("scores_ent_rejected", items=""), dim=True))
        for r in b.rejected:
            typer.echo(typer.style(f"     · {r['id']} {r['name']} — {r['why']}", dim=True))


@app.command("goal")
def set_goal_cmd(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    score: str = typer.Option(None, help="점수 ID (예: SC-ERR-02)"),
    test: str = typer.Option(None, help="검정 ID (예: T-101)"),
    effect: str = typer.Option(None, help="효과크기 이름 (예: Hedges g)"),
) -> None:
    """S171 Goal 지표 지정 — 지정하지 않으면 마지막에 실행한 검정이 Goal 이다."""
    from statop.analyze.metrics import set_goal

    try:
        entry = set_goal(session, score=score, test=test, effect_key=effect)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(msg("metrics_goal_set",
                   name=entry.get("name") or entry.get("test") or entry.get("effect_key")))


@app.command()
def exclude(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    key_column: str = typer.Option(..., help="행 식별 컬럼 (예: patient_id)"),
    key: str = typer.Option(..., help="뺄 행의 값"),
    note: str = typer.Option("", help="제외 사유 — 왜 뺐는지 (필수)"),
    restore: bool = typer.Option(False, "--restore", help="뺐던 샘플을 되돌린다"),
    sample_n: int = 10_000,
) -> None:
    """개별 샘플 제외 / 되돌리기  — 사유 없이는 뺄 수 없다.

    제외 전/후를 함께 보고해야 하며, 10%를 넘게 빼면 빨간 경고가 뜬다 ."""
    from statop.analyze.points import exclude as do_exclude
    from statop.analyze.points import include, status

    try:
        if restore:
            include(session, key_column, key)
        else:
            do_exclude(session, key_column, key, note)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    st = status(session, sample_n)
    typer.echo(msg("metrics_excluded", n=st.n_excluded, total=st.n_total,
                   ratio=st.ratio, left=st.n_total - st.n_excluded))
    if st.verdict == "red":
        typer.echo(typer.style(msg("points_excl_red", n=st.n_excluded,
                                   total=st.n_total, ratio=st.ratio),
                               fg=typer.colors.RED, bold=True))
    elif st.n_excluded:
        typer.echo(typer.style(msg("points_excl_yellow", n=st.n_excluded,
                                   total=st.n_total, ratio=st.ratio),
                               fg=typer.colors.YELLOW))


@app.command()
def summarize(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    snippet_only: bool = typer.Option(False, "--snippet", help="재현 스니펫만 출력"),
    sample_n: int = 10_000,
) -> None:
    """A5 가설 재작성  + 재현 스니펫 .

    검정 하나가 아니라 Goal·Support·Guardrail 을 엮어 한 문단으로 다시 쓴다."""
    from statop.hypothesis.rewrite import build

    try:
        r = build(session, sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    if not snippet_only:
        typer.echo(typer.style(msg("a5_head"), bold=True))
        typer.echo("  " + r.statement)
        typer.echo("")
        typer.echo("  Goal: " + r.goal)
        for label, items in (("Support", r.support), ("Guardrail", r.guardrail)):
            if items:
                typer.echo(f"  {label}: " + " · ".join(items))
        if r.triad:
            t = r.triad
            typer.echo("  " + msg("a5_triad_line", id=t["id"], situation=t["situation"],
                                  goal=t["goal"], support=t["support"],
                                  guardrail=t["guardrail"]))
        for c in r.cautions:
            typer.echo(typer.style(f"  · {c}", fg=typer.colors.YELLOW))
        typer.echo("")
        typer.echo(typer.style(msg("a5_snippet_title"), bold=True))
    typer.echo(r.snippet)


@app.command("roles")
def roles_cmd(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    support: str = typer.Option("", help="보고서에 넣을 보조 관계 id (쉼표 구분)"),
    guardrail: str = typer.Option("", help="보고서에 넣을 가드레일 관계 id (쉼표 구분)"),
    note: str = typer.Option("", help="왜 이 조합인지"),
) -> None:
    """S172 병기 선택 저장 — **base 관계 중 무엇을 보고할지**만 저장한다.

    관계 자체는 base 고정이라 새로 만들 수 없다 ()."""
    from statop.analyze.metrics import apply_choices, goal_key, save_choice, suggest

    try:
        panel = suggest(session)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    key = goal_key(panel)
    if not support and not guardrail:
        panel = apply_choices(panel)
        typer.echo(_goal_line(panel.goal))
        for label, items in (("Support", panel.support), ("Guardrail", panel.guardrail)):
            for x in items:
                mark = f" ← {msg('metrics_chosen_mark')}" if x.chosen else ""
                typer.echo(f"  {label:<9s} [{x.id}] {x.name}{mark}")
        return
    sup = [x.strip() for x in support.split(",") if x.strip()]
    grd = [x.strip() for x in guardrail.split(",") if x.strip()]
    try:
        save_choice(key, sup, grd, note)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(msg("metrics_roles_saved", key=key, ns=len(sup), ng=len(grd)))


@app.command()
def export(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    out: str = typer.Option(None, help="저장 경로 (기본: 원본 옆 <원본>_trimmed)"),
    name: str = typer.Option(None, help="파일 이름(확장자 제외)"),
    overwrite: bool = typer.Option(False, help="같은 이름이 있으면 덮어쓰기"),
) -> None:
    """가공 파일 저장 () — 원본 불변. 표식 컬럼과 사이드카가 함께 남아
    이 파일을 다시 열면 가공 사실을 알린다."""
    from statop.export import export_trimmed
    from statop.session.core import load_session

    doc = load_session(session)
    try:
        res = export_trimmed(doc, out_path=out, name=name, overwrite=overwrite)
    except FileExistsError as e:
        typer.echo(typer.style(str(e), fg=typer.colors.RED))
        raise typer.Exit(1)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    typer.echo(msg("export_done", path=res.path, rows=res.n_rows, cols=res.n_cols))
    typer.echo(msg("export_sidecar", path=res.sidecar))
    if res.n_relabels:
        typer.echo(typer.style(msg("export_relabel_note", n=res.n_relabels),
                               fg=typer.colors.YELLOW))


@app.command()
def relabel(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    key_column: str = typer.Option(..., help="행 식별 컬럼 (예: patient_id)"),
    key: str = typer.Option(..., help="그 행의 값"),
    column: str = typer.Option(..., help="고칠 컬럼"),
    to: str = typer.Option(..., help="새 값"),
    note: str = typer.Option(..., help="사유 — 왜 잘못 들어갔다고 판단하는지 (필수)"),
) -> None:
    """개별 샘플 라벨 수정 () — 원본은 그대로, 기록으로만 남는다.
    모든 출력 맨 앞에 수정 건수가 표시되며 숨길 수 없다."""
    from statop.io.meta import estimate_rows, open_meta
    from statop.relabel import check_ratio, find_row
    from statop.session.core import append_op, load_session, main_source, replay, save_session

    if not note.strip():
        raise typer.BadParameter(msg("relabel_note_required"))
    doc = load_session(session)
    src = main_source(doc)
    if src is None:
        raise typer.BadParameter(msg("select_err_empty"))

    try:
        current = find_row(src["path"], key_column, key, column)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    if current is None:
        raise typer.BadParameter(msg("relabel_key_not_found", key=key))
    if current == to:
        raise typer.BadParameter(msg("relabel_same_value", value=to))

    entry = append_op(doc, "relabel", key=key, key_column=key_column, column=column,
                      **{"from": current}, to=to, note=note.strip(), source=src["id"])
    save_session(doc)

    meta = open_meta(src["path"])
    n_rows = meta.n_rows if meta.n_rows is not None else estimate_rows(src["path"])
    chk = check_ratio(len(replay(doc)["relabels"]), n_rows)
    typer.echo(msg("relabel_done", key=key, column=column, from_=current, to=to))
    typer.echo(msg("relabel_reason", note=note.strip()))
    typer.echo(typer.style(msg("relabel_notice", n=chk.n), fg=typer.colors.YELLOW))
    if chk.over_threshold:
        typer.echo(typer.style(msg("relabel_over_threshold", n=chk.n, ratio=chk.ratio),
                               fg=typer.colors.RED))


@app.command()
def hold(
    cols: str = typer.Option(..., help="hold할 컬럼 (쉼표 구분)"),
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    off: bool = typer.Option(False, "--off", help="hold 해제"),
) -> None:
    """컬럼 hold (M0-5) — 분석에서는 빼되 시각화(색·점 식별)에는 쓴다.
    제외(deselect)와 달리 작업 영역에는 남는다."""
    from statop.session.core import append_op, load_session, main_source, replay, save_session

    wanted = [c.strip() for c in cols.split(",") if c.strip()]
    doc = load_session(session)
    src = main_source(doc)
    if src is None:
        raise typer.BadParameter(msg("select_err_empty"))
    current = replay(doc)["selected"].get(src["id"], [])
    unknown = [c for c in wanted if c not in current]
    if unknown:
        raise typer.BadParameter(msg("deselect_err_not_selected", cols=", ".join(unknown)))
    entry = append_op(doc, "unhold" if off else "hold", source=src["id"], cols=wanted)
    save_session(doc)
    st = replay(doc)
    typer.echo(msg("hold_off" if off else "hold_on", n=len(wanted), cols=", ".join(wanted)))
    typer.echo(msg("hold_state", n_analysis=len(st["analysis"].get(src["id"], [])),
                   n_held=len(st["held"].get(src["id"], []))))


@app.command()
def transpose(
    data: str,
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    yes: bool = typer.Option(False, help="메모리 경고 시에도 확인 없이 진행"),
) -> None:
    """전치(Transpose) — 행/열을 뒤집는다 (op: transpose). 원본 불변, 같은 명령 2번=원상복귀."""
    from statop.io.transpose import estimate_cost, transpose_table
    from statop.session.core import append_op, ensure_source, load_session, replay, save_session

    c = estimate_cost(data)
    est = msg("estimated_suffix") if c.estimated else ""
    typer.echo(msg("transpose_estimate", rows=c.n_rows, cols=c.n_cols, est=est, mb=c.mem_mb))
    if c.warn and not yes and not typer.confirm(msg("transpose_confirm_mem"), default=False):
        typer.echo(msg("transpose_cancelled"))
        raise typer.Exit(1)

    t = transpose_table(data)  # 실제 전치 (중복 컬럼명 등 문제를 여기서 즉시 검출)

    doc = load_session(session)
    src_id = ensure_source(doc, data)
    if not any(o["op"] == "open" and o.get("source") == src_id for o in doc["ops"]):
        append_op(doc, "open", source=src_id)
    entry = append_op(doc, "transpose", source=src_id)
    save_session(doc)

    now = replay(doc)["transposed"].get(src_id, False)
    cols = list(t.columns)
    mid = len(cols) // 2
    preview = f"{cols[0]}, {cols[1]} … {cols[mid]} … {cols[-2]}, {cols[-1]}"
    typer.echo(msg("transpose_result", rows=t.shape[0], cols=t.shape[1], preview=preview))
    typer.echo(msg("transpose_recorded", seq=entry["seq"],
                   state=msg("transpose_state_on" if now else "transpose_state_off")))


@app.command()
def dist(
    data: str,
    cols: str = typer.Option(..., help="분포를 볼 컬럼 (쉼표 구분)"),
    sample_n: int = 10_000,
    chart: bool = typer.Option(False, "--chart", help="축·눈금이 있는 그림으로 보기"),
    width: int = typer.Option(40, help="--chart 폭"),
) -> None:
    """분포 미리보기 (M0-3) — 히스토그램·사분위·왜도·outlier 비율.
    기본은 한 줄 요약, --chart면 축·눈금이 있는 그림 (y축 눈금 ≤5, )."""
    from statop.io.distribution import distributions
    from statop.render.chart import boxplot, histogram
    from statop.render.spark import bar, format_distribution

    wanted = [c.strip() for c in cols.split(",") if c.strip()]
    if not wanted:
        raise typer.BadParameter(msg("select_err_empty"))
    try:
        items = distributions(data, wanted, sample_n=sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    for d in items:
        typer.echo("")
        typer.echo(f"{d['column']}  ({d['kind']})")
        if chart and d["kind"] == "numeric":
            for line in histogram(d["bins"], d["edges"], width=width):
                typer.echo(line)
            for line in boxplot(d["quartiles"],
                                (0.0, d["outlier_rate_iqr"]), width=width):
                typer.echo(line)
            # 막대 줄은 그림이, 다섯 수는 상자그림이 대신한다
            for line in format_distribution(d, with_stats=False)[1:]:
                typer.echo(line)
        elif chart:
            for lv in d["levels"]:
                typer.echo(f"  {lv['value'][:18]:<18s} {bar(lv['ratio'], width // 2)} "
                           f"{lv['ratio']:>5.1%} ({lv['n']:,})")
        else:
            for line in format_distribution(d):
                typer.echo(line)


@app.command()
def integrity(
    a: str,
    b: str = typer.Argument(None, help="대조할 두 번째 파일. 생략 시 --log 필요"),
    log: str = typer.Option(None, help="세션 로그와 대조: a가 기록 당시와 같은지 (부분 해시 기준)"),
) -> None:
    """무결성 검증(Integrity) — 두 파일 전체 대조, 다르면 어디가 얼마나 다른지 요약."""
    from pathlib import Path

    from statop.integrity import compare_files
    from statop.session.core import load_session, partial_hash

    if (b is None) == (log is None):
        raise typer.BadParameter(msg("integrity_err_xor"))

    if log:  # 세션 기록과 대조 (부분 해시 — 기록에 부분 해시만 있으므로)
        doc = load_session(log)
        target = str(Path(a).resolve())
        src = next((s for s in doc["sources"] if s["path"] == target), None)
        if src is None:
            raise typer.BadParameter(msg("integrity_err_not_registered", path=a))
        if partial_hash(a)["value"] == src["hash"]["value"]:
            typer.echo(typer.style(msg("integrity_log_match"), fg=typer.colors.GREEN))
        else:
            typer.echo(typer.style(msg("integrity_log_mismatch"), fg=typer.colors.RED))
            raise typer.Exit(1)
        return

    d = compare_files(a, b)
    if d.identical:
        typer.echo(typer.style(msg("integrity_identical"), fg=typer.colors.GREEN))
        return
    typer.echo(typer.style(msg("integrity_differ"), fg=typer.colors.RED))
    typer.echo(msg("integrity_size", a=d.size_a, b=d.size_b, delta=d.size_b - d.size_a))
    first = msg("integrity_first_diff", offset=d.first_diff_offset) if d.first_diff_offset is not None else ""
    typer.echo(msg("integrity_chunks", total=d.chunks_total, differ=d.chunks_differ, first=first))
    if d.table_diff and "unreadable" in d.table_diff:
        typer.echo(typer.style(msg("integrity_unreadable", err=d.table_diff["unreadable"][:80]),
                               fg=typer.colors.RED))
    elif d.table_diff:
        t = d.table_diff
        est = msg("estimated_suffix") if t["rows_estimated"] else ""
        typer.echo(msg("integrity_table", rows_a=t["rows_a"], rows_b=t["rows_b"], est=est,
                       cols_a=t["n_cols_a"], cols_b=t["n_cols_b"]))
        for side, key in (("cols_only_a", "integrity_only_a"), ("cols_only_b", "integrity_only_b")):
            if t[side]:
                typer.echo(msg(key, n=len(t[side]), cols=", ".join(t[side][:5]),
                               more=" …" if len(t[side]) > 5 else ""))
    raise typer.Exit(1)


rules_app = typer.Typer(no_args_is_help=True, help="규칙 DB (schema md → rules yaml)")
app.add_typer(rules_app, name="rules")


@rules_app.command("build")
def rules_build() -> None:
    """schema/registry-*.md 에서 rules/*.yaml 을 재생성한다 (md가 단일 진실)."""
    from statop.rules.build import build_all

    paths = build_all()
    for name, path in paths.items():
        typer.echo(f"  {name:24s} → {path}")
    typer.echo(msg("rules_built", n=len(paths)))


@rules_app.command("check")
def rules_check() -> None:
    """yaml이 md와 일치하는지, 규칙 간 참조가 온전한지 확인한다."""
    from statop.rules.build import check_all
    from statop.rules.validate import validate

    from statop.rules.build import rules_version

    typer.echo(msg("rules_version", version=rules_version()))
    content_stale, version_stale = check_all()
    if content_stale:
        typer.echo(typer.style(msg("rules_stale", files=", ".join(content_stale)), fg=typer.colors.RED))
    if version_stale:
        typer.echo(typer.style(msg("rules_stale_version", n=len(version_stale)), fg=typer.colors.YELLOW))
    if not content_stale and not version_stale:
        typer.echo(typer.style(msg("rules_in_sync"), fg=typer.colors.GREEN))

    rep = validate()
    typer.echo(msg("rules_id_counts", items=" · ".join(
        f"{k} {v}" for k, v in rep.known.items()), total=sum(rep.known.values())))
    if rep.issues:
        for i in rep.issues[:10]:
            typer.echo(typer.style(f"  {i.where} → {i.detail} ({i.kind})", fg=typer.colors.RED))
        typer.echo(typer.style(msg("rules_broken_refs", n=len(rep.issues)), fg=typer.colors.RED))
    else:
        typer.echo(typer.style(msg("rules_refs_ok"), fg=typer.colors.GREEN))

    if content_stale or version_stale or rep.issues:
        raise typer.Exit(1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="바인딩 주소 (원격 접속 허용 시 0.0.0.0)"),
    port: int = typer.Option(8000, help="포트"),
) -> None:
    """REST API 서버를 기동한다. 웹 UI·CLI·셸이 이 API를 공유한다."""
    import uvicorn

    from statop.api.app import ui_built

    typer.echo(msg("serve_starting", host=host, port=port))
    # 웹 화면은 /ui/ 에 있다. 주소를 안 적어 주면 사람은 / 로 들어가고 404 를 본다
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    if ui_built():
        typer.echo(typer.style(msg("serve_web_at", url=f"http://{shown}:{port}/ui/"),
                               fg=typer.colors.CYAN, bold=True))
    else:
        typer.echo(typer.style(
            msg("serve_web_missing", how="cd ui && npm ci && npm run build"),
            fg=typer.colors.YELLOW))
    uvicorn.run("statop.api.app:app", host=host, port=port, log_level="info")


@app.command()
def cleanup(
    stop_them: bool = typer.Option(False, "--stop", help="찾은 것을 정리한다"),
) -> None:
    """이 장비에 남아 있는 STATOP 프로세스를 보고, 원하면 정리한다.

    웹 서버와 계산 일꾼은 창을 닫으면 같이 꺼지지만, 그 장치가 없던 때 띄운 것들은
    그대로 남는다. 남으면 포트를 물고 메모리를 먹는다."""
    import socket

    from statop.api.ghosts import scan, stop

    found = scan()
    typer.echo(msg("doctor_head", host=socket.gethostname()))
    if not found:
        typer.echo(typer.style("  " + msg("doctor_clean"), fg=typer.colors.GREEN))
        return

    if found.servers:
        ports = ", ".join(sorted({p for *_, p in found.servers}))
        typer.echo(typer.style("  " + msg("doctor_server", n=len(found.servers),
                                          ports=ports), fg=typer.colors.YELLOW))
    if found.workers:
        typer.echo(typer.style("  " + msg("doctor_worker", n=len(found.workers),
                                          gb=found.worker_gb), fg=typer.colors.YELLOW))
    if found.orphans:
        typer.echo(typer.style("  " + msg("doctor_orphan", n=len(found.orphans)),
                               fg=typer.colors.RED))

    if not stop_them:
        typer.echo(typer.style("  " + msg("doctor_how_stop"), dim=True))
        return
    typer.echo(msg("doctor_stopped", n=stop(found)))


@app.command()
def shell() -> None:
    """대화형 셸을 연다 (`statop`를 인자 없이 실행한 것과 같다)."""
    from statop.shell.app import run_shell

    run_shell()


def main() -> None:
    app()


compat_app = typer.Typer(no_args_is_help=True, help="적합성(Compatibility) 판정 (M1-3)")
app.add_typer(compat_app, name="compat")

_VERDICT_COLOR = {"gate": typer.colors.RED, "red": typer.colors.RED,
                  "yellow": typer.colors.YELLOW, "unconfirmed": typer.colors.YELLOW,
                  "green": typer.colors.GREEN}


def _compat_context(session: str, sample_n: int):
    """판정에 필요한 것 — 분석 대상 컬럼, 확정된 의미 타입, 조성 세트."""
    from statop.compat import composition_groups
    from statop.session.core import replay

    doc, src, df = _session_frame(session, sample_n)
    st = replay(doc)
    sid = src["id"]
    cols = st["analysis"].get(sid, []) or [c for c in df.columns]
    types = st["semantic_types"].get(sid, {})
    # 파생 컬럼은 파일에 없다 — 수식으로 다시 만들어 판정 대상에 넣는다
    df = _with_derived(df, st["derived"], sid)
    comp = composition_groups(df, [c for c in cols if c in df.columns], types)
    return doc, src, df, cols, types, comp


def _with_derived(df, derived: list[dict], source_id: str):
    """service.with_derived 로 위임 — 판정 재료는 한 곳에서 만든다."""
    from statop.derive.evaluate import evaluate
    from statop.derive.parser import parse

    for d in derived:
        if d.get("source") != source_id or d["name"] in df.columns:
            continue
        try:
            p = parse(d["expr"], list(df.columns))
        except Exception:
            continue
        df = df.assign(**{d["name"]: evaluate(p, df, eps=d.get("eps"),
                                             composition=d.get("composition"))})
    return df


def _show_report(rep, indent: str = "  ") -> None:
    """9.3 순서대로 — 미확정 → Gate → 빨강 → 노랑. 근거 ID를 항상 붙인다."""
    typer.echo(typer.style(msg(f"compat_verdict_{rep.verdict}"),
                           fg=_VERDICT_COLOR[rep.verdict], bold=rep.verdict in ("gate", "red")))
    if rep.blocked:
        typer.echo(typer.style(indent + msg("compat_blocked"), fg=typer.colors.YELLOW))
        typer.echo(indent + msg("compat_unconfirmed_cols", cols=", ".join(rep.unconfirmed)))
        return
    if not rep.findings:
        typer.echo(indent + msg("compat_green"))
        return
    for f in rep.findings:
        color = _VERDICT_COLOR.get(f.verdict, typer.colors.YELLOW)
        typer.echo(typer.style(f"{indent}[{f.id}] {', '.join(f.columns)}", fg=color, bold=True))
        if f.detail:
            typer.echo(f"{indent}    {f.detail}")
        typer.echo(f"{indent}    " + msg("compat_why", why=f.why))
        typer.echo(f"{indent}    " + msg("compat_fix", fix=f.fix))
        typer.echo(typer.style(
            f"{indent}    " + (msg("compat_fix_available", action=f.fix_action)
                               if f.fix_action else msg("compat_fix_none")),
            fg=typer.colors.GREEN if f.fix_action else typer.colors.BLUE))


@compat_app.command("check")
def compat_check(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    op: str = typer.Option(..., help="연산: correlate|compare|regress|spread|aggregate"),
    cols: str = typer.Option(None, help="쌍 판정할 두 컬럼 (생략 시 분석 대상 전체 요약)"),
    sample_n: int = 10_000,
) -> None:
    """연산 적합성 판정 (M1-3). 쌍은 **명시 지정했을 때만**, 아니면 전체 요약 1건.

    의미 타입이 확정되지 않았으면 판정하지 않고 보류한다 (S-R14) — 추론값으로
    경고하면 틀린 경고가 쌓인다."""
    from statop.compat import OPERATIONS, judge_pair, judge_set

    if op not in OPERATIONS:
        raise typer.BadParameter(msg("compat_op_unknown", allowed="|".join(OPERATIONS), op=op))
    _, _, df, columns, types, comp = _compat_context(session, sample_n)

    if cols:
        pair = [c.strip() for c in cols.split(",") if c.strip()]
        if len(pair) != 2:
            raise typer.BadParameter(msg("compat_pair_needs_two"))
        missing = [c for c in pair if c not in df.columns]
        if missing:
            raise typer.BadParameter(msg("select_err_missing", cols=", ".join(missing)))
        typer.echo(msg("compat_head_pair", op=op, a=pair[0], b=pair[1]))
        _show_report(judge_pair(op, pair[0], pair[1], types, df=df, comp_groups=comp))
        return

    target = [c for c in columns if c in df.columns]
    typer.echo(msg("compat_head_set", op=op, n=len(target)))
    _show_report(judge_set(op, target, types, df=df, comp_groups=comp))


@compat_app.command("fix")
def compat_fix(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    op: str = typer.Option(..., help="연산: correlate|compare|regress|spread|aggregate"),
    rule: str = typer.Option(..., help="고칠 규칙 ID (예: S-R01)"),
    cols: str = typer.Option(None, help="쌍 판정이었으면 그 두 컬럼"),
    action: str = typer.Option(None, help="제안과 다른 조치를 쓰고 싶을 때: "
                                          "clr|alr|logit|div100|unify_scale"),
    composition: str = typer.Option(None, help="CLR/ALR용 조성 세트 (쉼표 구분)"),
    reference: str = typer.Option(None, help="ALR 기준 성분"),
    eps: float = typer.Option(None, help="eps (log 계열 조치에 필요)"),
    apply_: bool = typer.Option(False, "--apply", help="계획 대신 실제 적용"),
    sample_n: int = 10_000,
) -> None:
    """원클릭 수정  — 조치를 파생 컬럼으로 만들고 **지정을 교체한다** .

    기본은 계획만 보여준다. --apply를 줘야 기록에 남는다."""
    from statop.compat import judge_pair, judge_set
    from statop.compat_fix import apply as apply_plan
    from statop.compat_fix import plan as make_plan

    doc, src, df, columns, types, comp = _compat_context(session, sample_n)
    if cols:
        pair = [c.strip() for c in cols.split(",") if c.strip()]
        if len(pair) != 2:
            raise typer.BadParameter(msg("compat_pair_needs_two"))
        rep = judge_pair(op, pair[0], pair[1], types, df=df, comp_groups=comp)
    else:
        rep = judge_set(op, [c for c in columns if c in df.columns], types,
                        df=df, comp_groups=comp)

    found = next((f for f in rep.findings if f.id == rule), None)
    if found is None:
        raise typer.BadParameter(msg("compat_rule_not_in_report", id=rule))
    if action:
        # 제안이 늘 최선은 아니다 — 세트 일부만 가져온 경우 CLR을 직접 고를 수 있어야 한다
        from statop.compat import FIX_ACTIONS

        if action not in FIX_ACTIONS:
            raise typer.BadParameter(msg("compat_action_unknown",
                                         allowed="|".join(FIX_ACTIONS), action=action))
        found.fix_action = action

    comp_cols = [c.strip() for c in composition.split(",")] if composition else None
    try:
        p = make_plan(found, df=df, composition=comp_cols, reference=reference)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    if p.needs_composition:
        #  — 세트를 임의로 정하지 않는다. 후보를 보여주고 사용자가 고른다
        typer.echo(typer.style(p.note, fg=typer.colors.YELLOW))
        for g in comp:
            typer.echo("  " + msg("compat_comp_candidate", cols=",".join(g), n=len(g)))
        if not comp:
            typer.echo("  " + msg("compat_comp_none"))
        return

    typer.echo(msg("compat_plan_head", action=p.action, n=len(p.derives)))
    for d in p.derives:
        typer.echo("  " + msg("compat_plan_derive", name=d["name"], expr=d["expr"]))
    for old, new in p.replaces:
        typer.echo("  " + msg("compat_plan_replace", old=old, new=new))
    if p.note:
        typer.echo("  " + p.note)
    if p.needs_eps and eps is None:
        typer.echo(typer.style("  " + msg("eps_explicit_required"), fg=typer.colors.YELLOW))
    if not apply_:
        typer.echo(msg("compat_plan_dryrun"))
        return

    try:
        entries = apply_plan(doc, src["id"], df, p, eps=eps)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(typer.style(msg("compat_applied", n=len(p.derives), m=len(p.replaces)),
                           fg=typer.colors.GREEN))
    typer.echo(msg("derive_recorded", seq=entries[-1]["seq"]))

    #  — 고쳤으면 그 자리에서 다시 판정한다. 왕복이 끝나야 수정이 끝난 것
    _, _, df2, columns2, types2, comp2 = _compat_context(session, sample_n)
    if cols:
        moved = {o: n for o, n in p.replaces}
        again = judge_pair(op, moved.get(pair[0], pair[0]), moved.get(pair[1], pair[1]),
                           types2, df=df2, comp_groups=comp2)
    else:
        again = judge_set(op, [c for c in columns2 if c in df2.columns], types2,
                          df=df2, comp_groups=comp2)
    typer.echo("")
    typer.echo(msg("compat_rejudge", verdict=again.verdict))
    _show_report(again)


guard_app = typer.Typer(no_args_is_help=True, help="가드레일(Guardrail) 검사 (M4)")
app.add_typer(guard_app, name="guard")

# ── 모듈 B — 모델링 감사 ────────────────────────────────────
# 모듈 A(가설검정)와 **별개의 명령군**이다. 같은 데이터를 봐도 묻는 것이 다르다:
# A 는 "이 차이가 우연인가", B 는 "이 데이터로 학습한 결과를 믿어도 되는가".
model_app = typer.Typer(no_args_is_help=True,
                        help="모델링 감사 (모듈 B) — 학습은 실행하지 않는다")
app.add_typer(model_app, name="model")


@model_app.command("questions")
def model_questions() -> None:
    """모델링 질문(MB-Q)과 모델 티어(MB-M) 목록 — v1 판정 범위 표시."""
    from statop.modeling.spec import questions, tiers

    mark = {"full": "●", "partial": "○", "later": "—"}
    typer.echo(typer.style(msg("mb_questions_head"), bold=True))
    for q in questions():
        typer.echo(typer.style("  " + msg("mb_q_row", mark=mark[q["v1"]], id=q["id"],
                                          text=q["question"], output=q["output"]),
                               dim=q["v1"] == "later"))
    typer.echo("")
    typer.echo(typer.style(msg("mb_tiers_head"), bold=True))
    for t in tiers():
        typer.echo(typer.style("  " + msg("mb_t_row", mark=mark[t["v1"]], id=t["id"],
                                          tier=t["tier"], examples=t["examples"],
                                          need=t["audit_input"]),
                               dim=t["v1"] == "later"))
    typer.echo(typer.style("  " + msg("mb_mark_legend"), dim=True))


@model_app.command("checks")
def model_checks(
    group: str = typer.Option(None, help="data|config|evaluation|reproducibility|model_specific"),
) -> None:
    """감사 체크 목록 (MB-C01~33) — 등급과 무엇을 보고 판단하는지."""
    from statop.modeling.spec import checks

    rows = checks(group)
    color = {"Gate": typer.colors.RED, "Diag": typer.colors.YELLOW,
             "Judg": typer.colors.BLUE}
    for c in rows:
        tier = f" [{c['tier']}]" if c.get("tier") else ""
        typer.echo(typer.style("  " + msg("mb_check_row", grade=f"{c['grade']:<9s}",
                                          id=c["id"], check=c["check"], tier=tier),
                               fg=color.get(c["grade"].split("/")[0])))
        typer.echo(typer.style("             " + msg("mb_check_detail",
                                                     detect=c["detect"],
                                                     action=c["action"]), dim=True))
    typer.echo("")
    typer.echo(msg("mb_check_total", n=len(rows)))
    typer.echo(typer.style(msg("mb_scope_note"), dim=True))
    typer.echo(typer.style("  " + msg("mb_scope_why"), dim=True))


@model_app.command("leak")
def model_leak(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 50_000,
) -> None:
    """B2 누수·중복 검사 (~) — 중복·그룹 교차·시간 누수·라벨 대리변수.

    전부 Gate 다. `statop model plan --apply` 로 구성을 먼저 확정해야 한다."""
    from statop.modeling.leak import run_all
    from statop.modeling.spec import current

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    findings = run_all(spec, sample_n)

    _echo_findings(msg("mb_leak_head"), findings)


def _is_gate(finding) -> bool:  # noqa: ANN001
    """규칙표가 Gate 라고 적은 항목인가 — 'Gate/Diag' 도 Gate 로 본다."""
    return finding.grade.split("/")[0] == "Gate"


def _echo_findings(head: str, findings: list, ok_key: str = "mb_leak_all_pass",
                   note: str | None = None) -> None:
    """감사 결과를 같은 모양으로 낸다.

    **Gate 와 Diag 를 섞지 않는다** — Gate 만 막고(종료 코드 1), Diag 는 얼마나
    문제인지 말하고 통과시킨다 (: 규칙 위반은 막는 대신 크기를 말한다).
    """
    typer.echo(typer.style(head, bold=True))
    for f in findings:
        gate = _is_gate(f)
        judg = f.grade.split("/")[0] == "Judg"      # 판단 — 진단보다도 약하다
        bad = (typer.colors.RED if gate else
               typer.colors.BLUE if judg else typer.colors.YELLOW)
        color = {"fail": bad, "pass": typer.colors.GREEN,
                 "skipped": typer.colors.WHITE}
        icon = {"fail": "⛔" if gate else "ⓘ " if judg else "⚠ ",
                "pass": "✅", "skipped": "○ "}
        typer.echo(typer.style(f"  {icon[f.verdict]} {f.id} {f.summary}",
                               fg=color[f.verdict]))
        for x in f.detail:
            typer.echo(typer.style(f"       {x}", dim=True))
        if f.action:
            typer.echo(typer.style(f"       → {f.action}", dim=True))
    if note:
        # 무엇을 **보지 않는지**도 화면에 있어야 한다 — 없는 검사를 있다고 믿지 않게
        typer.echo("")
        typer.echo(typer.style(msg(note), dim=True))
        typer.echo(typer.style("  " + msg("mb_scope_why"), dim=True))
    bad = [f for f in findings if f.verdict == "fail"]
    gates = [f for f in bad if _is_gate(f)]
    typer.echo("")
    if gates:
        typer.echo(typer.style(msg("mb_leak_blocked", n=len(gates)),
                               fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)
    if bad:
        typer.echo(typer.style(msg("mb_diag_found", n=len(bad)),
                               fg=typer.colors.YELLOW, bold=True))
        return
    typer.echo(typer.style(msg(ok_key), fg=typer.colors.GREEN))


def _expect_ratio(expected: str | None) -> dict[str, float] | None:
    if not expected:
        return None
    try:
        return {k.strip(): float(v) for k, v in
                (x.split("=") for x in expected.split(",") if x.strip())}
    except ValueError:
        raise typer.BadParameter(msg("labels_map_format"))


@model_app.command("split")
def model_split(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    key: str = typer.Option(None, help="원본과 세트를 맞출 키 컬럼 — 없으면 손실 검사를 건너뛴다"),
    expect: str = typer.Option(None, help="계획한 분할 비율 — 예: train=8,test=2"),
    source: str = typer.Option(None, help="나누기 전 원본 파일 (생략 시 세션의 main)"),
    meta: str = typer.Option(None, help="편향적 손실을 함께 볼 메타 컬럼 (쉼표 구분)"),
    sample_n: int = 50_000,
) -> None:
    """B2 세트 비율·손실 검사  — MB-C06(SRM) · MB-C07(손실·join).

    가드레일 GR-02/GR-03 을 모델링 맥락에서 부른다. 임계값은 `statop guard limits` 의 것이다."""
    from statop.modeling.spec import current
    from statop.modeling.split_audit import key_from_session, run_all
    from statop.session.core import load_session, main_source

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    if not source:
        src = main_source(load_session(session))
        source = src["path"] if src else None
    if not key:
        # 의미 타입에서 이미 행 식별자를 확정했다 — 같은 것을 두 번 말하게 하지 않는다
        key = key_from_session(session)
        typer.echo(msg("mb_key_auto", col=key) if key else msg("mb_key_none"))

    findings = run_all(spec, source, key, _expect_ratio(expect),
                       [c.strip() for c in meta.split(",")] if meta else None,
                       sample_n)
    _echo_findings(msg("mb_split_head"), findings, "mb_split_all_pass")


@model_app.command("balance")
def model_balance(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    meta: str = typer.Option(None, help="라벨과의 연관을 볼 메타 컬럼 (쉼표 구분) — 기관·배치·나이 등"),
    sample_n: int = 50_000,
) -> None:
    """B4 균형·분포 진단  — 클래스 비율·숨은 불균형·세트 간 분포 차이.

    전부 Diag 다. 막지 않고 얼마나 문제인지 말한다 (MB-C08, MB-C12)."""
    from statop.modeling.balance import run_all
    from statop.modeling.spec import current

    from statop.session.core import load_session, main_source, replay

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    if meta:
        meta_cols = [c.strip() for c in meta.split(",")]
    else:
        # 지정이 없으면 hold 한 컬럼이 메타다 (요구사항) — 분석에서 뺐지만 라벨을
        # 예측하면 모델이 그쪽을 외운다
        doc = load_session(session)
        src = main_source(doc)
        meta_cols = replay(doc)["held"].get(src["id"] if src else "", [])
    findings = run_all(spec, meta_cols, sample_n)
    _echo_findings(msg("mb_balance_head"), findings, "mb_balance_all_pass")


@model_app.command("prep")
def model_prep(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 50_000,
) -> None:
    """B5 전처리·모델 적합  — 표준화 필요 여부·차원축소·EPV.

    어느 컬럼이 척도를 끌고 가는지까지 지목한다 ."""
    from statop.modeling.prep import run_all
    from statop.modeling.spec import current

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    _echo_findings(msg("mb_prep_head"), run_all(spec, sample_n), "mb_prep_all_pass")


@model_app.command("eval")
def model_eval(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 50_000,
) -> None:
    """B5 평가 감사  — ROC/PR·클래스별 성능·보정·임계값·fold 편차·test 재사용.

    **의미 타입이 probability 로 확정된 컬럼이 하나는 있어야 한다** — 예측 확률이
    없으면 평가를 감사할 것이 없다 (`statop types --confirm COL --as probability`)."""
    from statop.modeling.evaluate import run_all
    from statop.modeling.spec import current

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    _echo_findings(msg("mb_eval_head"), run_all(spec, session, sample_n),
                   "mb_eval_all_pass")


@model_app.command("triad")
def model_triad(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 50_000,
) -> None:
    """S194b MB-Q별 3-metric 트리아드 (MB-C24) — Goal 옆에 Support·Guardrail 을 세운다.

    무엇을 세울지는 규칙표(registry-models 5절)가 정한다 — 지어내지 않는다."""
    from statop.modeling.spec import current
    from statop.modeling.triad import recommend

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    _echo_findings(msg("mb_triad_head"), [recommend(spec, sample_n)],
                   "mb_triad_all_pass")


@model_app.command("report")
def model_report(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    out: str = typer.Option(None, help="저장 경로 (.md 또는 .json). 생략 시 화면에"),
    key: str = typer.Option(None, help="원본과 세트를 맞출 키 컬럼 (MB-C07)"),
    expect: str = typer.Option(None, help="계획한 분할 비율 — 예: train=8,test=2"),
    source: str = typer.Option(None, help="나누기 전 원본 파일 (생략 시 세션의 main)"),
    meta: str = typer.Option(None, help="메타 컬럼 (쉼표 구분) — 생략 시 hold 한 컬럼"),
    sample_n: int = 50_000,
) -> None:
    """S194c B6 출력 — 모듈 B 감사를 한 장으로 + 재현 명령 묶음.

    감사를 여러 명령으로 나눠 돌고 나면 무엇이 걸렸는지 한눈에 볼 자리가 없다."""
    from pathlib import Path

    from statop.modeling.report import FORMATS, collect, to_markdown

    rep = collect(session, source_path=source, key=key,
                  expected_ratio=_expect_ratio(expect),
                  meta_cols=[c.strip() for c in meta.split(",")] if meta else None,
                  sample_n=sample_n)
    if out:
        p = Path(out)
        fmt = p.suffix.lstrip(".").lower() or "md"
        if fmt not in FORMATS:
            raise typer.BadParameter(msg("report_bad_format",
                                         allowed="|".join(FORMATS), fmt=fmt))
        p.write_text(FORMATS[fmt](rep), encoding="utf-8")
        typer.echo(typer.style(msg("mb_report_saved", path=out),
                               fg=typer.colors.GREEN))
    else:
        typer.echo(to_markdown(rep))
    if rep.gates:
        raise typer.Exit(1)


@model_app.command("specific")
def model_specific(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 50_000,
) -> None:
    """S194 모델특유 검사 (MB-C28~C31, T0) — 완전분리·다중공선성·조기중단·중요도.

    같은 자료라도 어떤 모델을 쓰느냐에 따라 다른 것이 터진다."""
    from statop.modeling.spec import current
    from statop.modeling.specific import run_all

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    _echo_findings(msg("mb_specific_head"), run_all(spec, sample_n),
                   "mb_specific_all_pass", note="mb_scope_note")


@model_app.command("repro")
def model_repro(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
) -> None:
    """S192· 지표 변경·재현성 감사 (MB-C21 · C25~C27).

    세션에 쌓인 구성 기록을 본다 — 한 번의 결과만으로는 무엇이 바뀌었는지 알 수 없다."""
    from statop.modeling.repro import run_all
    from statop.modeling.spec import current

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    _echo_findings(msg("mb_repro_head"), run_all(spec, session), "mb_repro_all_pass")


@model_app.command("seed")
def model_seed(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    out: str = typer.Option(None, help="저장 경로 (생략 시 화면에만)"),
) -> None:
    """재현용 seed 고정 코드 (`seed_<id>.py`, MB-C25).

    **학습 코드를 써 주지 않는다** — seed 를 어디에 심어야 하는지만 적는다."""
    from pathlib import Path

    from statop.modeling.repro import seed_script
    from statop.modeling.spec import current

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    text = seed_script(spec, session)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        typer.echo(typer.style(msg("mb_seed_saved", path=out), fg=typer.colors.GREEN))
    else:
        typer.echo(text)


@model_app.command("families")
def model_families() -> None:
    """모델 계열과 표준화 필요 여부 (registry-models 3.6)."""
    from statop.modeling.prep import families

    # 세 상태를 그대로 보인다 — 조건부를 '불필요'로 뭉뚱그리면 규칙표가 거짓말이 된다
    label = {"required": "mb_family_required", "depends": "mb_family_depends",
             "optional": "mb_family_optional"}
    color = {"required": typer.colors.YELLOW, "depends": typer.colors.BLUE,
             "optional": typer.colors.GREEN}
    for f in families():
        typer.echo(typer.style(
            f"  {msg(label[f['scaling']]):<4s} {f['family']:<12s} {f['examples']}",
            fg=color[f["scaling"]]))
        typer.echo(typer.style(f"              {f['why']}", dim=True))


@model_app.command("compare")
def model_compare(
    model: list[str] = typer.Option(None, "--model", "-m",
                                    help='모델 하나 — "이름: 항1+항2 [n=480] [y=결과] [family=binomial]"'),
) -> None:
    """S190a 모델 비교 가능 여부 (MB-C21) — 어느 모델쌍이 왜 안 되는지 지목한다.

    학습을 돌리지 않으므로 모델 구성은 사용자가 적어 준다."""
    from statop.modeling.compare import Model, audit

    try:
        models = [Model.parse(m) for m in (model or [])]
    except (ValueError, IndexError):
        raise typer.BadParameter(msg("mb_compare_bad_model"))
    _echo_findings(msg("mb_compare_head"), [audit(models)])


@model_app.command("shift")
def model_shift(
    column: str = typer.Argument(..., help="판정이 지목한 컬럼"),
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    key: str = typer.Option(..., help="원본과 세트를 맞출 키 컬럼"),
    source: str = typer.Option(None, help="나누기 전 원본 파일 (생략 시 세션의 main)"),
) -> None:
    """결측정리 전/후 분포를 겹쳐 본다 (, MB-C07).

    "유의하다"만으로는 어느 쪽이 얼마나 달라졌는지 알 수 없다."""
    from statop.modeling.spec import current
    from statop.modeling.split_audit import shift_view
    from statop.session.core import load_session, main_source

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    if not source:
        src = main_source(load_session(session))
        source = src["path"] if src else None
    typer.echo(typer.style(msg("mb_shift_head"), bold=True))
    for line in shift_view(spec, source, key, column)["lines"]:
        typer.echo(line)


@model_app.command("labels")
def model_labels(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 50_000,
) -> None:
    """B3 라벨 인코딩 방향·매핑  — MB-C13.

    수준별 코드를 고치는 것은 `statop labels --map` 이다. 여기서는 기록과 방향만 본다."""
    from statop.modeling.label_audit import label_audit
    from statop.modeling.spec import current

    spec = current(session)
    if spec is None:
        raise typer.BadParameter(msg("mb_need_spec"))
    _echo_findings(msg("mb_c13_head"), label_audit(spec, session, sample_n),
                   "mb_c13_all_pass")


@model_app.command("code")
def model_code(
    path: str = typer.Argument(..., help="학습 코드 파일 (.py) — 읽기만 한다"),
) -> None:
    """B2 코드 정적 감지  — 나누기 전에 학습한 전처리·피처선택 (MB-C04, MB-C09).

    코드를 **실행하지 않는다.** 구문만 읽어 나누는 줄과 fit 하는 줄의 순서를 본다."""
    from statop.modeling.code_audit import audit_code

    _echo_findings(msg("mb_code_head"), audit_code(path))


@model_app.command("plan")
def model_plan(
    # 구성 확인만 할 때는 세션이 필요 없다 — 기록(--apply)할 때만 찾는다
    session: str = typer.Option(None, help="세션 로그 파일 (--apply 일 때만 필요)"),
    question: str = typer.Option(..., help="모델링 질문 (MB-Q01 …)"),
    tier: str = typer.Option(..., help="모델 티어 (MB-M0 …)"),
    label: str = typer.Option(..., help="라벨 컬럼"),
    score: str = typer.Option(None, help="확률·점수 컬럼"),
    positive: str = typer.Option(None, help="양성 클래스 수준 (MB-C13 인코딩 방향)"),
    class_weight: str = typer.Option(None, help="가중·샘플링을 썼다면 무엇으로 (MB-C12) — balanced|oversample|undersample|smote"),
    family: str = typer.Option(None, "--family", help="모델 계열 (MB-C10) — statop model families 로 목록"),
    scaling: str = typer.Option(None, help="표준화를 썼다면 무엇으로 (MB-C10/C11) — standard|minmax|robust"),
    reduction: str = typer.Option(None, help="차원축소를 썼다면 무엇으로 (MB-C11) — PCA 등"),
    threshold: float = typer.Option(None, help="민감도·특이도를 보고한 임계값 (MB-C20)"),
    averaging: str = typer.Option(None, help="다중분류 평균 방식 (MB-C17) — macro|micro|weighted"),
    fold_scores: str = typer.Option(None, help="fold 별 성능 (MB-C22) — 예: 0.81,0.79,0.85"),
    metric: str = typer.Option(None, help="무엇을 보고했는가 (MB-C21) — 예: ROC-AUC"),
    metric_reason: str = typer.Option(None, help="지표를 바꿨다면 왜 (MB-C21)"),
    environment: str = typer.Option(None, help="라이브러리·하드웨어 (MB-C26/C27) — 예: python3.12,sklearn1.9,cpu"),
    nondeterminism: str = typer.Option(None, help="비결정 연산 고지 (MB-C27) — GPU·병렬이면 재현 범위를 적는다"),
    importance: str = typer.Option(None, help="특성중요도를 보고했다면 무엇으로 (MB-C31) — gini|gain|permutation"),
    validation: str = typer.Option("kfold", help="holdout|kfold|stratified_kfold|group_kfold|time_split|loocv|nested_cv"),
    k: int = typer.Option(None, help="분할 수"),
    group_col: str = typer.Option(None, help="그룹 컬럼 (환자·배치)"),
    time_col: str = typer.Option(None, help="시간 컬럼"),
    train: str = typer.Option(None, help="train 세트 파일"),
    test: str = typer.Option(None, help="test 세트 파일"),
    valid: str = typer.Option(None, help="valid 세트 파일"),
    external: str = typer.Option(None, help="external 세트 파일"),
    seed: int = typer.Option(None, help="seed (MB-C25)"),
    apply_: bool = typer.Option(False, "--apply", help="문제없으면 세션에 기록"),
) -> None:
    """B1 데이터 구성 확인  — 세트 역할·검증 방식·MB-Q/MB-M 을 확정한다."""
    from statop.modeling.spec import ModelSpec, build, record

    sets = {r: v for r, v in (("train", train), ("valid", valid), ("test", test),
                              ("external", external)) if v}
    spec = ModelSpec(question=question, tier=tier, validation=validation, k=k,
                     group_column=group_col, time_column=time_col, sets=sets,
                     label_column=label, score_column=score,
                     positive_class=positive, class_weight=class_weight,
                     model_family=family, scaling=scaling, reduction=reduction,
                     threshold=threshold, averaging=averaging, metric=metric,
                     metric_change_reason=metric_reason, environment=environment,
                     nondeterminism=nondeterminism, importance=importance,
                     fold_scores=[float(x) for x in fold_scores.split(",")
                                  if x.strip()] if fold_scores else [],
                     seed=seed)
    res = build(spec)

    typer.echo(typer.style(msg("mb_head"), bold=True))
    for n in res.notes:
        typer.echo("  · " + n)
    if res.n_rows:
        typer.echo("  " + msg("mb_sets_line", sets=" · ".join(
            msg("mb_rows_cell", role=r, n=n) for r, n in res.n_rows.items())))
    typer.echo("  " + msg("mb_valid_line", v=validation,
                          k=msg("mb_valid_k", k=k) if k else "",
                          group=msg("mb_valid_group", col=group_col) if group_col else "",
                          time=msg("mb_valid_time", col=time_col) if time_col else ""))
    for p in res.problems:
        typer.echo(typer.style("  ⛔ " + p, fg=typer.colors.RED))
    if res.problems:
        raise typer.Exit(1)
    if apply_:
        target = _session_default(session)
        record(target, spec)
        typer.echo(typer.style(msg("mb_recorded"), fg=typer.colors.GREEN))

_GUARD_COLOR = {"gate": typer.colors.RED, "diagnostic": typer.colors.YELLOW,
                "info": typer.colors.BLUE, "ok": typer.colors.GREEN}


def _loss_materials(session: str, sample_n: int):
    """손실 검사(GR-03)의 재료 — 조작 전 원본과 지금 남은 행, 그리고 단계별 표.

    세션 기록에서 다시 만든다. 재현이 원칙이므로 기록에 없는 손실은 보고하지 않는다.
    """
    from statop.missing import drop_na
    from statop.rowfilter import apply_filter
    from statop.session.core import replay

    doc, src, df0 = _session_frame(session, sample_n)
    st = replay(doc)
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
    return doc, src, df0, cur, steps, st


@guard_app.command("run")
def guard_run(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    group: str = typer.Option(None, help="군 컬럼 (라벨) — GR-02·GR-04에 필요"),
    meta: str = typer.Option(None, help="메타 컬럼 (쉼표 구분) — 차원별 SRM·편중 검사"),
    metrics: str = typer.Option(None, help="지표 컬럼 (쉼표 구분) — 커버리지·안정성"),
    expected: str = typer.Option(None, help="기대 비율 — 예: control=1,case=1"),
    out: str = typer.Option(None, help="리포트 저장 경로 (.md 또는 .json)"),
    sample_n: int = 10_000,
) -> None:
    """가드레일 전체 검사 (M4) — GR-03 → GR-02 → GR-04 → GR-01 순.

    **진단 순서이지 인과 순서가 아니다.** 앞 검사 결과가 뒤 검사의 입력이 된다."""
    from pathlib import Path

    from statop.guard import report as guard_report
    from statop.guard.pipeline import headline, run

    doc, src, df0, cur, steps, st = _loss_materials(session, sample_n)
    df = _with_derived(cur, st["derived"], src["id"])
    types = st["semantic_types"].get(src["id"], {})
    meta_cols = [c.strip() for c in meta.split(",")] if meta else []
    metric_cols = [c.strip() for c in metrics.split(",")] if metrics else []
    ratio = None
    if expected:
        try:
            ratio = {k.strip(): float(v) for k, v in
                     (x.split("=") for x in expected.split(",") if x.strip())}
        except ValueError:
            raise typer.BadParameter(msg("labels_map_format"))

    rep = run(df, types, group_col=group, meta_cols=meta_cols, metric_cols=metric_cols,
              df_before=df0 if steps else None,
              kept_index=df.index if steps else None,
              retention_steps=steps, expected_ratio=ratio)

    head = headline(rep)
    if head:   # 차단은 맨 앞에 — 스크롤해야 보이는 경고는 없는 것과 같다
        typer.echo(typer.style(head, fg=typer.colors.RED, bold=True))
        typer.echo("")
    typer.echo(msg("guard_head", n=len(rep.findings), tier=msg(f"guard_tier_{rep.tier}")))
    for rule in rep.order:
        items = [f for f in rep.findings if f.rule == rule]
        if not items:
            continue
        typer.echo("")
        typer.echo(f"{rule}")
        for f in items:
            typer.echo(typer.style(
                f"  [{msg(f'guard_tier_{f.tier}')}] {f.check} — {f.detail}",
                fg=_GUARD_COLOR.get(f.tier)))
            if f.links:
                typer.echo("      " + msg("guard_link_line", links=", ".join(f.links)))

    if rep.cause_trace:
        typer.echo("")
        typer.echo(msg("guard_cause_head"))
        if rep.cause_trace.get("candidate") == "loss":
            typer.echo("  " + msg("guard_cause_loss"))
        cf = rep.cause_trace.get("counterfactual") or {}
        if cf.get("available"):
            key = ("guard_counterfactual_resolved" if cf.get("resolved")
                   else "guard_counterfactual_unresolved")
            typer.echo("  " + msg(key, p=cf.get("p_restored") or float("nan")))
        if rep.cause_trace.get("branch"):
            typer.echo(typer.style("  " + rep.cause_trace["branch"],
                                   fg=typer.colors.YELLOW))

    if rep.skipped:
        typer.echo("")
        typer.echo(msg("guard_skipped_head"))
        for s in rep.skipped:
            typer.echo(f"  {s['rule']} — {s['reason']}")
    if rep.overrides:
        typer.echo("")
        typer.echo(typer.style(msg("guard_override_head"), fg=typer.colors.YELLOW))
        for o in rep.overrides:
            typer.echo("  " + msg("guard_override_line", **o))

    if out:
        p = Path(out)
        text = (guard_report.to_json(rep) if p.suffix == ".json"
                else guard_report.to_markdown(rep))
        p.write_text(text, encoding="utf-8")
        typer.echo("")
        typer.echo(msg("columns_saved_out", n=len(rep.findings), out=out))


@guard_app.command("limits")
def guard_limits(
    rule: str = typer.Option(None, help="특정 규칙만 보기 (예: GR-02)"),
) -> None:
    """지금 적용되는 임계값 — 기준값과 조정 여부를 함께 보여준다 ."""
    from statop.guard import locks

    typer.echo(msg("guard_limits_head", path=locks.overrides_path()))
    for r in locks.execution_order():
        if rule and r != rule:
            continue
        typer.echo("")
        typer.echo(f"{r}")
        typer.echo("  " + msg("guard_floor_line", floor=locks.floor(r)))
        for key, lim in locks.limits(r).items():
            line = (msg("guard_limit_line_over", key=key, value=lim.value, base=lim.base)
                    if lim.overridden else msg("guard_limit_line", key=key, value=lim.value))
            typer.echo(typer.style("  " + line,
                                   fg=typer.colors.YELLOW if lim.overridden else None))


@guard_app.command("set")
def guard_set(
    rule: str = typer.Option(..., help="규칙 ID (예: GR-02)"),
    tier: str = typer.Option(None, help="등급: gate|diagnostic|info|off"),
    key: str = typer.Option(None, help="임계값 이름"),
    value: str = typer.Option(None, help="임계값"),
) -> None:
    """임계값·등급 조정 . **floor 아래로는 거부한다**  — 예외 없다."""
    from statop.guard import locks

    if not tier and not key:
        raise typer.BadParameter(msg("guard_set_needs_target"))
    try:
        if tier:
            locks.set_tier(rule, tier)
            typer.echo(msg("guard_set_ok", rule=rule, key="tier", value=tier))
        if key:
            if value is None:
                raise typer.BadParameter(msg("guard_set_needs_value"))
            try:
                v = json.loads(value)      # 숫자·true/false·null을 그대로 받는다
            except ValueError:
                v = value
            locks.set_threshold(rule, key, v)
            typer.echo(msg("guard_set_ok", rule=rule, key=key, value=v))
    except locks.LockError as e:
        raise typer.BadParameter(str(e))


@guard_app.command("reset")
def guard_reset(
    rule: str = typer.Option(None, help="특정 규칙만 초기화 (생략 시 전체)"),
) -> None:
    """조정을 되돌린다 — 기준값으로 돌아간다."""
    from statop.guard import locks

    locks.clear(rule)
    typer.echo(msg("guard_cleared", scope=rule or "all"))


analyze_app = typer.Typer(no_args_is_help=True, help="분석 설계·검정 후보 (모듈 A)")
app.add_typer(analyze_app, name="analyze")

_CAND_ICON = {"green": ("✅", typer.colors.GREEN), "yellow": ("⚠ ", typer.colors.YELLOW),
              "red": ("⛔", typer.colors.RED)}


@analyze_app.command("questions")
def analyze_questions() -> None:
    """질문 유형 11종 (Q-01~) — 사용자 말 예시와 함께."""
    from statop.analyze.spec import questions

    for q in questions():
        typer.echo(f"  {q['id']}  {q['question']}")
        typer.echo(typer.style(f"        {q['user_words']}", fg=typer.colors.BRIGHT_BLACK))


@analyze_app.command("plan")
def analyze_plan(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    question: str = typer.Option(..., help="질문 유형 (Q-01~Q-11, `analyze questions` 참조)"),
    y: str = typer.Option(..., help="측정(결과) 컬럼"),
    group: str = typer.Option(None, help="그룹/두 번째 변수 컬럼"),
    event: str = typer.Option(None, help="생존 분석의 사건 컬럼 (1=발생, 0=중도절단)"),
    by: str = typer.Option(None, help="층화 라벨 컬럼 — 전체와 수준별을 함께 본다"),
    subject: str = typer.Option(None, help="대상 ID 컬럼 (반복측정) — 회차 순서는 값에서 읽는다"),
    weights: str = typer.Option(None, help="사전지정 대비 가중치 (군 순서대로, 합 0)"),
    paired: bool = typer.Option(False, "--paired", help="같은 대상 반복 측정"),
    direction: str = typer.Option("two-sided", help="two-sided|greater|less"),
    contrast: str = typer.Option("all-pairs", help="all-pairs|vs-control"),
    control: str = typer.Option(None, help="vs-control의 기준 수준"),
    n_tests: int = typer.Option(1, help="계획한 검정 수 (다중검정 보정의 분모)"),
    apply_: bool = typer.Option(False, "--apply", help="문제없으면 세션에 기록"),
    sample_n: int = 10_000,
) -> None:
    """A1 질문 설계 — 스펙을 데이터에 대보고(적합성 자동 판정 포함) 후보까지 보여준다.

    기본은 미리보기. --apply 를 줘야 기록되고, 차단(gate)이 있으면 기록을 거부한다."""
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import Spec, build, questions, record

    spec = Spec(question=question, y=y, group=group, event=event, by=by,
                subject=subject, weights=weights, paired=paired, direction=direction,
                contrast=contrast, control=control, n_tests=n_tests)
    res = build(session, spec, sample_n=sample_n)

    typer.echo(msg("spec_head"))
    qtext = next((q["question"] for q in questions() if q["id"] == question), "")
    typer.echo("  " + msg("spec_line_question", q=question, text=qtext))
    group_part = f" · group={group} ({res.group_type})" if group else ""
    typer.echo("  " + msg("spec_line_target", y=y, y_type=res.y_type or "?",
                          group_part=group_part))
    typer.echo("  " + msg("spec_line_design", paired=paired, direction=direction,
                          contrast=contrast, n=n_tests))
    if res.group_levels:
        detail = " · ".join(f"{k}: n={v:,}" for k, v in res.group_levels.items())
        typer.echo("  " + msg("spec_line_groups", detail=detail))

    for f in res.compat.get("findings", []):
        color = typer.colors.RED if f["verdict"] in ("red", "gate") else typer.colors.YELLOW
        typer.echo(typer.style(f"  [{f['id']}] {f['detail'] or f['why']}", fg=color))

    if res.problems:
        typer.echo("")
        typer.echo(typer.style(msg("spec_problems_head"), fg=typer.colors.RED, bold=True))
        for p in res.problems:
            typer.echo(typer.style(f"  · {p}", fg=typer.colors.RED))
        raise typer.Exit(1)

    cands = shortlist(res)
    typer.echo("")
    typer.echo(msg("cand_head", q=question, n=len(cands)))
    if not cands:
        typer.echo(typer.style("  " + msg("cand_none"), fg=typer.colors.YELLOW))
    for c in cands:
        icon, color = _CAND_ICON[c.color]
        typer.echo(typer.style(f"  {icon} {c.id}  {c.name}  — {msg('cand_color_' + c.color)}",
                               fg=color, bold=c.color == "green"))
        for r in c.reasons:
            typer.echo(f"       {r}")
        if c.effect_size:
            typer.echo(typer.style("       " + msg("cand_effect", e=c.effect_size),
                                   fg=typer.colors.BRIGHT_BLACK))
        if c.color == "red" and c.alternatives:
            typer.echo(typer.style("       " + msg("cand_alt", a=c.alternatives),
                                   fg=typer.colors.BRIGHT_BLACK))

    if apply_:
        record(session, spec)
        group_txt = f" · group={group}" if group else ""
        typer.echo("")
        typer.echo(typer.style(msg("spec_recorded", q=question, y=y, group=group_txt),
                               fg=typer.colors.GREEN))


@analyze_app.command("checks")
def analyze_checks(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    sample_n: int = 10_000,
) -> None:
    """A3 가정 검사 — 현재 질문 설계(A1)에 **관련된 가정만** 돌린다.

    정규성 위배는 원인(소수 outlier/왜도/형태)까지, 검정력 부족은 어느 군이
    부족한지까지 말한다."""
    from statop.analyze.checks import run_checks
    from statop.analyze.spec import current

    try:
        results = run_checks(session, sample_n=sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    spec = current(session)
    typer.echo(msg("a3_head", q=spec.question))

    color = {"ok": typer.colors.GREEN, "violated": typer.colors.RED,
             "caution": typer.colors.YELLOW, "skipped": typer.colors.BRIGHT_BLACK}
    icon = {"ok": "✅", "violated": "⛔", "caution": "⚠ ", "skipped": "· "}
    for r in results:
        typer.echo(typer.style(
            f"  {icon[r.verdict]} {r.name} — {msg('a3_verdict_' + r.verdict)}",
            fg=color[r.verdict], bold=r.verdict == "violated"))
        typer.echo(f"       {r.summary}")
        for g in r.per_group:
            if "p" in g:            # 정규성 군별 상세
                p_txt = f"p={g['p']:.3f}" if g["p"] is not None else g["method"]
                typer.echo(typer.style(
                    f"         {g['group']:<12s} n={g['n']:<6,d} {p_txt:<14s} "
                    + msg("a3_skew_label", skew=g["skew"])
                    + (f"  ← {msg('a3_cause_' + g['cause'])}" if g.get("cause") else ""),
                    fg=color.get(g["verdict"], None)))


@analyze_app.command("run")
def analyze_run(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    test: str = typer.Option(..., help="검정 ID (예: T-101) — analyze plan의 후보에서"),
    sample_n: int = 10_000,
) -> None:
    """S152 검정 실행 — 효과크기·CI를 항상 함께, p는 보정 α와 비교해 준다."""
    from statop.analyze.run import run_test

    try:
        r = run_test(session, test, sample_n=sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(msg("run_head", id=r.id, name=r.name))
    if r.statistic is not None and r.p is not None:
        typer.echo("  " + msg("run_line_stat", stat=r.statistic, p=r.p))
    if r.effect:
        ci = (msg("run_line_ci", lo=r.effect["ci_low"], hi=r.effect["ci_high"])
              if r.effect.get("ci_low") is not None else "")
        typer.echo("  " + msg("run_line_effect", name=r.effect["name"],
                              value=r.effect["value"], ci=ci))
    typer.echo("  " + msg("run_line_n",
                          detail=" · ".join(f"{k}={v}" for k, v in r.n.items())))
    for note in r.notes:
        typer.echo(typer.style(f"  {note}", fg=typer.colors.BRIGHT_BLACK))


@app.command()
def hypothesis(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
) -> None:
    """가설 1안/2안 (A7 기본 경로) — 실행된 검정 결과에서 **기계적으로** 만든다.

    해석·방향·주의사항(CLR·log 변환, 라벨 묶음, 보정 α)과 보조지표 해석법,
    가드레일 반영까지. LLM은 쓰지 않는다 — 마음에 안 들면 `statop ask`."""
    from statop.hypothesis.mech import build_report

    try:
        rep = build_report(session)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    b = rep.basis
    typer.echo(msg("hypo_head", test=f"{b['test']} {b['name']}"))
    for h in rep.proposals:
        typer.echo("")
        typer.echo(typer.style(f"  {h.title}", bold=True))
        typer.echo(f"    {h.statement}")
        typer.echo(typer.style(f"    {h.interpretation}", fg=typer.colors.BRIGHT_BLACK))
        if h.direction:
            typer.echo(typer.style("    " + msg("hypo_direction_label", d=h.direction), fg=typer.colors.CYAN))
    if rep.cautions:
        typer.echo("")
        typer.echo(typer.style("  " + msg("hypo_cautions_head"), fg=typer.colors.YELLOW,
                               bold=True))
        for c in rep.cautions:
            typer.echo(typer.style(f"    · {c}", fg=typer.colors.YELLOW))
    if rep.companions:
        typer.echo("")
        typer.echo(typer.style("  " + msg("hypo_companions_head"), bold=True))
        for c in rep.companions:
            typer.echo(f"    · {c}")
    if rep.guardrail:
        typer.echo("")
        typer.echo(typer.style("  " + msg("hypo_guard_head"), fg=typer.colors.RED,
                               bold=True))
        for g in rep.guardrail:
            typer.echo(typer.style(f"    · {g}", fg=typer.colors.RED))
    typer.echo("")
    typer.echo(typer.style("  " + msg("hypo_ask_hint"), fg=typer.colors.BRIGHT_BLACK))


@app.command()
def ask(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    opinion: str = typer.Argument("", help="기계 가설에 대한 내 의견 (선택)"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="보내지 않고 전송될 내용만 미리 본다"),
    load: bool = typer.Option(False, "--load",
                              help="모델만 올려 둔다 (상주하지 않으므로 첫 호출이 느리다)"),
) -> None:
    """Ask Qwen  — **버튼 한 번**. 가설 3종(최적·보수적·넓게)을 받는다.

    유형(모듈 A 검정 / 모듈 B 모델 감사)은 세션이 정한다 — 적어 넣을 것이 없다.
    원자료(셀 값)는 나가지 않는다 (요약·판정만). 전송 내용은 로그로 남는다.
    모델이 안 올라와 있으면 `statop ask --load` 로 먼저 올린다."""
    from statop.hypothesis.qwen import QwenError, ask as qwen_ask, build_prompt, check_ready
    from statop.hypothesis.qwen import load as qwen_load

    if load:
        r = qwen_load()
        color = typer.colors.GREEN if r.get("warmed") else typer.colors.YELLOW
        typer.echo(typer.style(r["detail"], fg=color))
        return

    if dry_run:
        user, _ = build_prompt(session, opinion)
        typer.echo(msg("qwen_dry_head"))
        typer.echo(user)
        ok, info = check_ready()
        if not ok:
            typer.echo(typer.style(info, fg=typer.colors.YELLOW))
        return

    try:
        ans = qwen_ask(session, opinion)
    except QwenError as e:
        raise typer.BadParameter(str(e))
    except ValueError as e:
        raise typer.BadParameter(str(e))

    typer.echo(msg("qwen_head", model=ans.model))
    if ans.proposals:
        # 입장마다 세 줄 — 가설 / 확인·반증 방법 / 한계 (registry-prompts 3절)
        color = {"optimal": typer.colors.GREEN,
                 "conservative": typer.colors.BLUE,
                 "broad": typer.colors.MAGENTA}
        for p in ans.proposals:
            typer.echo("")
            typer.echo(typer.style(f"  {msg('qwen_stance_' + p['stance'])}",
                                   fg=color.get(p["stance"]), bold=True))
            for key in ("hypothesis", "test", "limit"):
                if p.get(key):
                    typer.echo(f"    {msg('qwen_line_' + key)}: {p[key]}")
    else:
        typer.echo(typer.style("  " + msg("qwen_raw_head"), fg=typer.colors.YELLOW))
        typer.echo(ans.raw)
    typer.echo("")
    typer.echo(typer.style("  " + msg("qwen_sent_log", path=ans.sent_log),
                           fg=typer.colors.BRIGHT_BLACK))


@app.command()
def report(
    session: str = typer.Option(None, help="세션 로그 파일 (생략 시 최근 작업 세션)", callback=_session_default),
    out: str = typer.Option(..., help="저장 경로 (.md / .json / .html)"),
    format: str = typer.Option(None, "--format", help="md|json|html (생략 시 확장자로)"),
    sample_n: int = 10_000,
) -> None:
    """세션 리포트 (~157) — 이 세션에서 한 일 전체를 파일 하나로.

    조작 이력·타입·가드레일·질문 설계·검정·가설을 모은다. 기록에 없는 것은
    리포트에도 없다."""
    from statop.report import write

    try:
        p = write(session, out, fmt=format, sample_n=sample_n)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    fmt = format or p.suffix.lstrip(".")
    typer.echo(typer.style(
        msg("report_written", path=p, fmt=fmt, kb=p.stat().st_size / 1024),
        fg=typer.colors.GREEN))
