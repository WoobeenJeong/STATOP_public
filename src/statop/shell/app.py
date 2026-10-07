"""STATOP 대화형 셸  — `statop` 단독 실행 시 뜨는 화면.

`/명령` 슬래시 방식이고, 목록 화면에서는 방향키·클릭·Enter가 동작한다.
웹과 같은 코어·같은 판정을 쓰고 표현만 터미널이다. 현재 세션을 셸이 기억하므로
`--session 경로`를 매번 지정할 필요가 없다.
"""

from dataclasses import dataclass, field
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import print_formatted_text as printf

from statop.messages import msg

COMMANDS = ["/open", "/columns", "/select", "/selected", "/hold", "/transpose", "/integrity",
            "/save", "/load", "/close", "/help", "/quit"]


@dataclass
class ShellState:
    session_file: Path | None = None
    data_path: str | None = None
    picked: list[str] = field(default_factory=list)


def _p(text: str) -> None:
    printf(HTML(text))


def _help() -> None:
    _p("  " + msg("shell_help_title"))
    for key in ("open", "columns", "select", "selected", "hold", "transpose", "integrity",
                "session", "etc"):
        _p(f"    {msg('shell_help_' + key)}")


def run_shell() -> None:
    from statop.io.meta import open_meta
    from statop.io.profile import profile_columns
    from statop.session.core import (append_op, ensure_source, load_saved, load_session,
                                   main_source, new_session, replay, save_as, save_session)
    from statop.shell.columns_view import run_columns_view

    st = ShellState()
    session: PromptSession = PromptSession(completer=WordCompleter(COMMANDS))
    _p(msg("shell_welcome"))
    # 빈 프롬프트만 띄우면 첫 수를 알 수 없다 — 다음에 칠 것을 바로 보여준다
    _p("  " + msg("shell_first_step"))
    _p("  <ansigray>" + msg("shell_scope_note") + "</ansigray>")

    def need_session() -> dict | None:
        if st.session_file is None:
            _p(f"  <ansired>{msg('shell_need_session')}</ansired>")
            return None
        return load_session(st.session_file)

    while True:
        try:
            line = session.prompt(HTML("<b>statop</b> › ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        cmd, _, arg = line.partition(" ")
        arg = arg.strip()

        if cmd in ("/quit", "/exit"):
            break
        if cmd == "/help":
            _help()
            continue

        if cmd == "/open":
            if not arg:
                _p(f"  <ansired>{msg('shell_need_path')}</ansired>")
                continue
            if not Path(arg).exists():
                _p(f"  <ansired>{msg('path_not_exist')}: {arg}</ansired>")
                continue
            try:
                open_meta(arg)
            except ValueError as e:
                _p(f"  <ansired>{e}</ansired>")
                continue
            if st.session_file is None:
                doc = new_session()
                ensure_source(doc, arg, role="main")
                st.session_file = save_session(doc)
            else:  # 세션은 유지하고 메인 파일만 교체
                doc = load_session(st.session_file)
                src_id = ensure_source(doc, arg, role="main")
                if not any(o["op"] == "open" and o.get("source") == src_id for o in doc["ops"]):
                    append_op(doc, "open", source=src_id)
                save_session(doc)
            st.data_path = arg
            _p("  " + msg("shell_opened", name=Path(arg).name,
                            sid=load_session(st.session_file)["session_id"]))
            continue

        if cmd == "/columns":
            doc = need_session()
            if doc is None:
                continue
            prof = profile_columns(st.data_path, sample_n=3000)
            items = [
                {"column": r.column, "dtype": r.dtype, "missing_rate": float(r.missing_rate),
                 "n_unique": int(r.n_unique),
                 "missing_level": "high" if r.missing_rate >= 0.30 else
                                  ("mid" if r.missing_rate >= 0.10 else "ok")}
                for r in prof.itertuples()
            ]
            warns = [msg("columns_warn_many", n=len(items))] if len(items) > 200 else []
            picked = run_columns_view(items, Path(st.data_path).name, warns)
            if picked:
                doc = load_session(st.session_file)
                src_id = ensure_source(doc, st.data_path, role="main")
                entry = append_op(doc, "select", source=src_id, cols=picked)
                save_session(doc)
                st.picked = picked
                _p(f"  {msg('select_imported', n=len(picked), head=', '.join(picked[:5]), more=' …' if len(picked) > 5 else '')}")
                _p(f"  <ansigray>{msg('select_recorded', seq=entry['seq'], n=len(doc['ops']))}</ansigray>")
            continue

        if cmd == "/select":
            doc = need_session()
            if doc is None:
                continue
            cols = [c.strip() for c in arg.split(",") if c.strip()]
            meta = open_meta(st.data_path)
            missing = [c for c in cols if c not in meta.columns]
            if missing:
                _p(f"  <ansired>{msg('select_err_missing', cols=', '.join(missing))}</ansired>")
                continue
            src_id = ensure_source(doc, st.data_path, role="main")
            append_op(doc, "select", source=src_id, cols=cols)
            save_session(doc)
            _p(f"  {msg('select_imported', n=len(cols), head=', '.join(cols[:5]), more='')}")
            continue

        if cmd == "/selected":
            doc = need_session()
            if doc is None:
                continue
            src = main_source(doc)
            st = replay(doc)
            sel = st["selected"].get(src["id"], []) if src else []
            hel = st["held"].get(src["id"], []) if src else []
            _p("  " + msg("shell_workspace", n=len(sel), head=", ".join(sel[:10]),
                            more=" …" if len(sel) > 10 else ""))
            if hel:
                _p(f"  <ansigray>{msg('hold_state', n_analysis=len(sel) - len(hel), n_held=len(hel))}"
                   f" — {', '.join(hel)}</ansigray>")
            continue

        if cmd == "/hold":
            doc = need_session()
            if doc is None:
                continue
            off = arg.endswith("--off")
            cols = [c.strip() for c in arg.replace("--off", "").split(",") if c.strip()]
            src = main_source(doc)
            current = replay(doc)["selected"].get(src["id"], []) if src else []
            unknown = [c for c in cols if c not in current]
            if not cols or unknown:
                _p(f"  <ansired>{msg('deselect_err_not_selected', cols=', '.join(unknown) or '-')}</ansired>")
                continue
            append_op(doc, "unhold" if off else "hold", source=src["id"], cols=cols)
            save_session(doc)
            st = replay(doc)
            _p("  " + msg("hold_off" if off else "hold_on", n=len(cols), cols=", ".join(cols)))
            _p("  " + msg("hold_state", n_analysis=len(st["analysis"].get(src["id"], [])),
                          n_held=len(st["held"].get(src["id"], []))))
            continue

        if cmd == "/transpose":
            doc = need_session()
            if doc is None:
                continue
            src_id = ensure_source(doc, st.data_path, role="main")
            entry = append_op(doc, "transpose", source=src_id)
            save_session(doc)
            now = replay(doc)["transposed"].get(src_id, False)
            _p(f"  {msg('transpose_recorded', seq=entry['seq'], state=msg('transpose_state_on' if now else 'transpose_state_off'))}")
            continue

        if cmd == "/integrity":
            if not arg or not st.data_path:
                _p(f"  <ansired>{msg('shell_integrity_usage')}</ansired>")
                continue
            from statop.integrity import compare_files

            d = compare_files(st.data_path, arg)
            if d.identical:
                _p(f"  <ansigreen>{msg('integrity_identical')}</ansigreen>")
            else:
                _p(f"  <ansired>{msg('integrity_differ')}</ansired>")
                _p(f"  {msg('integrity_size', a=d.size_a, b=d.size_b, delta=d.size_b - d.size_a)}")
            continue

        if cmd == "/save":
            doc = need_session()
            if doc is None:
                continue
            try:
                target = save_as(doc, overwrite=bool(arg == "--overwrite"))
            except FileExistsError as e:
                _p(f"  <ansired>{e}</ansired>")
                _p(f"  <ansigray>{msg('shell_overwrite_hint')}</ansigray>")
                continue
            doc["saved_at"] = target.name
            save_session(doc)
            _p(f"  {msg('session_saved', path=target)}")
            continue

        if cmd == "/load":
            from statop.store import sessions_dir

            base = Path(arg) if arg else sessions_dir()
            files = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                _p(f"  <ansigray>{msg('shell_no_saved', dir=base)}</ansigray>")
                continue
            for i, f in enumerate(files[:10], 1):
                _p(f"    {i}. {f.name}")
            pick = session.prompt(HTML(f"  {msg('shell_pick_number')} › ")).strip()
            if not pick.isdigit() or not (1 <= int(pick) <= min(10, len(files))):
                continue
            doc, state = load_saved(files[int(pick) - 1])
            st.session_file = save_session(doc)
            src = main_source(doc)
            st.data_path = src["path"] if src else None
            sel = list(state["selected"].values())
            _p("  " + msg("shell_loaded", name=doc["loaded_from"],
                            n=len(sel[0]) if sel else 0))
            continue

        if cmd == "/close":
            if st.session_file and st.session_file.exists():
                doc = load_session(st.session_file)
                if "saved_at" not in doc and arg != "--force":
                    _p(f"  <ansired>{msg('session_close_unsaved', n=len(doc['ops']))}</ansired>")
                    continue
                st.session_file.unlink()
            st.session_file = st.data_path = None
            st.picked = []
            _p("  " + msg("shell_closed"))
            continue

        _p(f"  <ansired>{msg('shell_unknown_cmd', cmd=cmd)}</ansired>  <ansigray>/help</ansigray>")
