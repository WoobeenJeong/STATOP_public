"""컬럼 선택 화면 — 터미널 안의 '웹과 같은 화면' .

웹의 체크박스 = 셸의 체크박스. 같은 API 응답(missing_level·warnings)을 받아 표현만 다르다.
마우스 클릭·방향키·Enter·검색이 모두 동작하고, 페이지는 웹과 같은 25개 단위다.
"""

from dataclasses import dataclass, field

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import Style

from statop.messages import msg

PAGE = 25  # 웹과 같은 페이지 크기

# design-tokens 3절: 색 + 기호 병행. 앰버는 글자색으로 쓰지 않으므로 어두운 앰버를 쓴다.
STYLE = Style.from_dict({
    "head": "#5b6166",
    "sel": "reverse",
    "high": "#b23a17 bold",
    "mid": "#7a4a12",
    "mut": "#8a9096",
    "brand": "#35566b bold",
    "warn": "#7a4a12",
})

FLAG = {"high": "!!", "mid": "! ", "ok": "  "}

class ClickableControl(FormattedTextControl):
    """클릭을 행 번호로 바꿔 넘겨주는 컨트롤.

    prompt_toolkit 3.0은 mouse_handler를 생성자 인자로 받지 않는다 — 메서드를 덮어써야 한다.
    """

    # 마우스 이벤트가 **한 번이라도** 들어왔는지. 터미널이 마우스를 안 넘겨주는 경우가
    # 있는데, 그때 "클릭이 안 된다"고만 하면 원인을 알 수 없다
    mouse_events_seen = 0

    def __init__(self, *args, on_click=None, on_scroll=None, **kw) -> None:
        super().__init__(*args, **kw)
        self._on_click = on_click
        self._on_scroll = on_scroll

    def mouse_handler(self, mouse_event):  # noqa: ANN001, ANN201
        ClickableControl.mouse_events_seen += 1
        ev = mouse_event.event_type
        # **휠이 어디서도 안 먹었다.** 클릭만 처리하고 스크롤은 흘려보냈다 —
        # 목록이 길면 아래를 볼 방법이 키보드뿐이었다
        if ev in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
            if self._on_scroll is None:
                return super().mouse_handler(mouse_event)
            self._on_scroll(-1 if ev == MouseEventType.SCROLL_UP else 1)
            return None
        if self._on_click is None or ev != MouseEventType.MOUSE_UP:
            return super().mouse_handler(mouse_event)
        if self._on_click(mouse_event.position.y) is False:
            return super().mouse_handler(mouse_event)
        return None



@dataclass
class ColumnsView:
    """API 응답(items 전체)을 받아 터미널에서 고르게 한다."""

    items: list[dict]
    title: str
    warnings: list[str] = field(default_factory=list)
    cursor: int = 0
    offset: int = 0
    picked: set[str] = field(default_factory=set)
    grep: str = ""
    searching: bool = False
    sort: str | None = None
    result: list[str] | None = None  # Enter로 확정한 컬럼 목록

    # ── 데이터 ────────────────────────────────────────────────
    def visible(self) -> list[dict]:
        import re

        xs = self.items
        if self.grep:
            try:
                pat = re.compile(self.grep)
                xs = [x for x in xs if pat.search(x["column"])]
            except re.error:
                pass
        if self.sort == "missing":
            xs = sorted(xs, key=lambda x: -x["missing_rate"])
        elif self.sort == "unique":
            xs = sorted(xs, key=lambda x: -x["n_unique"])
        elif self.sort == "name":
            xs = sorted(xs, key=lambda x: x["column"])
        return xs

    def page_items(self) -> list[dict]:
        return self.visible()[self.offset : self.offset + PAGE]

    def n_pages(self) -> int:
        return max(1, -(-len(self.visible()) // PAGE))

    # ── 렌더 ──────────────────────────────────────────────────
    def render(self) -> HTML:
        rows = self.page_items()
        page_no = self.offset // PAGE + 1
        out = [
            f"  <brand>{_esc(self.title)}</brand>",
            f"  <mut>{msg('view_col_count', n=len(self.visible()))}"
            + (f" ({_esc(msg('view_search_label'))} {_esc(self.grep)})" if self.grep else "")
            + f" · {msg('view_page', page=page_no, pages=self.n_pages())}</mut>",
        ]
        if self.warnings:
            out.append(f"  <warn>{_esc(self.warnings[0])}</warn>")
        out.append("")
        out.append(f"     <head>{_esc(msg('view_header'))}</head>")
        for i, r in enumerate(rows):
            mark = "☑" if r["column"] in self.picked else "☐"
            cur = "▸" if i == self.cursor else " "
            line = (f"{r['column']:<24.24s} {r['dtype']:<12.12s} "
                    f"{r['missing_rate']*100:>6.1f}% {r['n_unique']:>9,d}")
            tag = r["missing_level"] if r["missing_level"] != "ok" else "mut"
            body = f"{cur} {mark} {FLAG[r['missing_level']]}{_esc(line)}"
            out.append(f"<sel>{body}</sel>" if i == self.cursor else f"<{tag}>{body}</{tag}>")
        if not rows:
            out.append(f"  <mut>{_esc(msg('view_empty'))}</mut>")
        out.append("")
        if self.searching:
            out.append(f"  <brand>{_esc(self.grep)}</brand>"
                       f"<mut>▏ {_esc(msg('view_search_hint'))}</mut>")
        else:
            out.append(f"  <mut>{_esc(msg('view_keys', n=len(self.picked)))}</mut>")
        return HTML("\n".join(out))


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cwidth(s: str) -> int:
    """터미널이 실제로 쓰는 칸 수 — 한글 한 글자는 두 칸이다."""
    from prompt_toolkit.utils import get_cwidth

    return get_cwidth(str(s))


def _pad_cells(s: str, width: int) -> str:
    """칸 수 기준으로 자르고 채운다. 글자 수로 채우면 줄마다 끝이 안 맞는다."""
    out = ""
    for ch in str(s):
        if _cwidth(out + ch) > width:
            break
        out += ch
    return out + " " * (width - _cwidth(out))


def run_columns_view(items: list[dict], title: str, warnings: list[str]) -> list[str] | None:
    """화면을 띄우고, Enter로 확정한 컬럼 목록을 반환한다 (q/Esc면 None)."""
    view = ColumnsView(items=items, title=title, warnings=warnings)
    kb = KeyBindings()

    def move(delta: int) -> None:
        rows = view.page_items()
        if not rows:
            return
        view.cursor = max(0, min(len(rows) - 1, view.cursor + delta))

    @kb.add("up")
    def _(e):  # noqa: ANN001
        if view.cursor == 0 and view.offset > 0:
            view.offset -= PAGE
            view.cursor = PAGE - 1
        else:
            move(-1)

    @kb.add("down")
    def _(e):  # noqa: ANN001
        rows = view.page_items()
        if view.cursor == len(rows) - 1 and view.offset + PAGE < len(view.visible()):
            view.offset += PAGE
            view.cursor = 0
        else:
            move(1)

    @kb.add(" ")
    def _(e):  # noqa: ANN001
        rows = view.page_items()
        if rows:
            name = rows[view.cursor]["column"]
            view.picked.discard(name) if name in view.picked else view.picked.add(name)

    @kb.add("n")
    def _(e):  # noqa: ANN001
        if view.offset + PAGE < len(view.visible()):
            view.offset += PAGE
            view.cursor = 0

    @kb.add("p")
    def _(e):  # noqa: ANN001
        if view.offset > 0:
            view.offset -= PAGE
            view.cursor = 0

    @kb.add("s")
    def _(e):  # noqa: ANN001
        order = [None, "missing", "unique", "name"]
        view.sort = order[(order.index(view.sort) + 1) % len(order)]
        view.offset = view.cursor = 0

    @kb.add("/")
    def _(e):  # noqa: ANN001
        view.searching = True

    @kb.add("enter")
    def _(e):  # noqa: ANN001
        if view.searching:
            view.searching = False
            view.offset = view.cursor = 0
        else:
            view.result = sorted(view.picked)
            e.app.exit()

    @kb.add("escape")
    def _(e):  # noqa: ANN001
        if view.searching:
            view.searching = False
            view.grep = ""
        else:
            e.app.exit()

    @kb.add("backspace")
    def _(e):  # noqa: ANN001
        if view.searching:
            view.grep = view.grep[:-1]

    @kb.add("q")
    def _(e):  # noqa: ANN001
        if view.searching:
            view.grep += "q"
        else:
            e.app.exit()

    @kb.add("<any>")
    def _(e):  # noqa: ANN001
        if view.searching and e.data and e.data.isprintable():
            view.grep += e.data

    def on_click(y: int) -> bool:
        """클릭으로 커서 이동 + 선택 토글 (웹의 체크박스 클릭과 같은 동작)."""
        header_lines = 5 + (1 if view.warnings else 0)   # 제목·요약·경고·빈줄·헤더
        idx = y - header_lines
        rows = view.page_items()
        if not (0 <= idx < len(rows)):
            return False
        view.cursor = idx
        name = rows[idx]["column"]
        view.picked.discard(name) if name in view.picked else view.picked.add(name)
        return True

    control = ClickableControl(view.render, focusable=True, show_cursor=False,
                               on_click=on_click)
    app = Application(layout=Layout(HSplit([Window(control)])), key_bindings=kb,
                      style=STYLE, full_screen=True, mouse_support=True)
    app.run()
    return view.result


def summarize(cols: list[str]) -> str:
    return msg("select_imported", n=len(cols), head=", ".join(cols[:5]),
               more=" …" if len(cols) > 5 else "")
