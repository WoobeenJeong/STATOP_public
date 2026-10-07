"""대화형 셸 화면  — 웹의 체크박스 = 셸의 체크박스."""

import re

import pytest

from statop.shell.columns_view import PAGE, ColumnsView

ITEMS = [
    {"column": f"c{i:03d}", "dtype": "double", "missing_rate": i / 100,
     "n_unique": 1000 - i,
     "missing_level": "high" if i >= 30 else ("mid" if i >= 10 else "ok")}
    for i in range(60)
]


def plain(v: ColumnsView) -> str:
    return re.sub(r"<[^>]+>", "", v.render().value)


def test_page_size_matches_web():
    v = ColumnsView(items=ITEMS, title="t")
    assert PAGE == 25
    assert len(v.page_items()) == 25 and v.n_pages() == 3


def test_flags_and_selection_marks():
    v = ColumnsView(items=ITEMS, title="t", sort="missing")  # 결측 높은 것부터
    v.picked.add(v.page_items()[0]["column"])   # 1쪽에 실제로 보이는 컬럼을 선택
    out = plain(v)
    assert "☑" in out and "☐" in out
    assert "!!" in out                    # 결측 ≥30% 심각 기호
    assert "선택 1개" in out

    # 주의(≥10%) 기호는 해당 컬럼이 보이는 쪽에서 확인 — 색만으로 구분하지 않는다
    mid = ColumnsView(items=[i for i in ITEMS if i["missing_level"] == "mid"], title="t")
    assert "! " in plain(mid)


def test_search_and_sort():
    v = ColumnsView(items=ITEMS, title="t")
    v.grep = "^c00"
    assert len(v.visible()) == 10
    assert "검색" in plain(v)

    v.grep = ""
    v.sort = "missing"
    assert v.visible()[0]["missing_rate"] == max(i["missing_rate"] for i in ITEMS)
    v.sort = "name"
    assert v.visible()[0]["column"] == "c000"


def test_paging_bounds():
    v = ColumnsView(items=ITEMS, title="t")
    v.offset = 50
    assert len(v.page_items()) == 10        # 마지막 쪽은 남은 만큼만
    assert "3/3 쪽" in plain(v)


def test_warning_rendered_once():
    v = ColumnsView(items=ITEMS, title="t", warnings=["⚠ 컬럼이 200개를 넘습니다"])
    assert plain(v).count("⚠") == 1


def test_html_escaped():
    v = ColumnsView(items=[{"column": "a<b>&c", "dtype": "x", "missing_rate": 0.0,
                            "n_unique": 1, "missing_level": "ok"}], title="t")
    assert "&lt;b&gt;" in v.render().value   # 컬럼명에 꺾쇠가 있어도 화면이 깨지지 않는다
