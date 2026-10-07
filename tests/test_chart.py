"""터미널 그림의 축약 규칙 (DECISIONS)."""

import re

import numpy as np
import pytest

from statop.io.distribution import describe_series
from statop.render.chart import MAX_Y_TICKS, boxplot, histogram, scatter

import pandas as pd


def tick_count(lines: list[str]) -> int:
    """y축 눈금(숫자 라벨)이 붙은 줄 수."""
    return sum(1 for ln in lines if re.match(r"\s*[\d.,e+-]+\s*┤", ln))


def test_histogram_y_ticks_within_limit():
    counts = list(range(1, 21))
    edges = [float(i) for i in range(21)]
    for height in (4, 6, 10, 14):
        lines = histogram(counts, edges, width=30, height=height)
        assert tick_count(lines) <= MAX_Y_TICKS       # y축 눈금 ≤ 5
        assert lines[-1].strip()                       # x축 끝값 표시


def test_histogram_merges_bins_and_says_so():
    counts = [1] * 100
    edges = [float(i) for i in range(101)]
    lines = histogram(counts, edges, width=20)
    body = [ln for ln in lines if "┤" in ln]
    assert all(len(ln.split("┤")[1]) == 20 for ln in body)   # 가로 폭에 맞춰 축약
    assert "합침" in lines[-1]                                # 합쳤다는 사실을 표기


def test_histogram_axis_shows_min_max():
    counts, edges = [3, 5, 2], [0.0, 1.0, 2.0, 3.0]
    lines = histogram(counts, edges, width=10, height=4)
    assert "0" in lines[-1] and "3" in lines[-1]


def test_boxplot_marks_median_and_whiskers():
    lines = boxplot([0.0, 25.0, 50.0, 75.0, 100.0], (0.0, 0.0), width=40)
    row = lines[0]
    assert "├" in row and "┤" in row and "│" in row and "▓" in row
    assert "0" in lines[1] and "100" in lines[1]          # 축 끝값


def test_boxplot_warns_when_box_invisible():
    """IQR이 범위의 10% 미만이면 그 사실을 말해준다 — 그림만으로는 안 보이므로."""
    lines = boxplot([0.0, 1.0, 2.0, 3.0, 1000.0], (0.0, 0.08), width=40)
    assert any("상자가 매우 좁음" in ln for ln in lines)
    assert any("outlier" in ln for ln in lines)


def test_boxplot_single_value():
    assert "하나뿐" in boxplot([5.0, 5.0, 5.0, 5.0, 5.0])[0]


def test_scatter_grid_and_axes():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 300)
    y = x * 2 + rng.normal(0, 0.5, 300)
    lines = scatter(list(x), list(y), width=30, height=10, xlab="x", ylab="y")
    assert tick_count(lines) <= MAX_Y_TICKS
    assert "x × y" in lines[-1] and "n=300" in lines[-1]
    assert any("█" in ln or "▇" in ln or "▆" in ln for ln in lines)   # 점이 찍힘


def test_scatter_handles_nan_and_empty():
    assert "없음" in scatter([], [])[0]
    lines = scatter([1.0, float("nan"), 3.0], [2.0, 1.0, float("nan")], width=10, height=4)
    assert "n=1" in lines[-1]        # 유효한 쌍만 센다


def test_chart_from_real_distribution():
    s = pd.Series(np.random.default_rng(1).lognormal(2, 1, 2000))
    d = describe_series(s, "x").as_dict()
    lines = histogram(d["bins"], d["edges"], width=40, height=6)
    assert tick_count(lines) <= MAX_Y_TICKS
    assert any("상자가 매우 좁음" in ln
               for ln in boxplot(d["quartiles"], (0.0, d["outlier_rate_iqr"])))


# ── 가로축 끝값은 절대 사라지면 안 된다  ─────────────
@pytest.mark.parametrize(("counts", "edges"), [
    ([5, 12, 30, 18, 6], [1.2e-6, 2.4e-6, 3.6e-6, 4.8e-6, 6.0e-6, 7.2e-6]),   # 지수표기
    ([5, 12, 30, 18, 6], [120000, 240000, 360000, 480000, 600000, 720000]),
    ([10, 40, 10], [0.001, 0.334, 0.667, 1.0]),                                # 구간 3개
    ([1, 2], [0.0, 0.5, 1.0]),                                                 # 구간 2개
])
def test_histogram_always_shows_both_end_values(counts, edges):
    """글자가 길면 줄을 늘려서라도 끝값을 남긴다 — 잘라내면 범위를 알 수 없다."""
    from statop.render.chart import _fmt

    lines = histogram(counts, edges, width=40)
    axis = lines[-1]
    assert _fmt(edges[0]) in axis, axis
    assert _fmt(edges[-1]) in axis, axis


def test_histogram_axis_labels_do_not_run_together():
    """예전에는 '1.2e-064.' 처럼 눈금이 붙어버렸다."""
    from statop.render.chart import _fmt

    edges = [1.2e-6, 2.4e-6, 3.6e-6, 4.8e-6, 6.0e-6, 7.2e-6]
    axis = histogram([5, 12, 30, 18, 6], edges, width=40)[-1]
    lo, hi = _fmt(edges[0]), _fmt(edges[-1])
    assert axis.strip().startswith(lo) and axis.rstrip().endswith(hi)
    assert axis.strip()[len(lo)] == " "        # 끝값 사이에 적어도 한 칸


def test_boxplot_keeps_both_end_values():
    from statop.render.chart import _fmt

    q = [1.2e-7, 3.4e-7, 5.6e-7, 7.8e-7, 9.9e-7]
    axis = boxplot(q, None, width=40)[1]
    assert _fmt(q[0]) in axis and _fmt(q[-1]) in axis


def test_axis_labels_drop_the_middle_before_the_ends():
    """자리가 모자라면 가운데를 버린다 — 끝값을 버리지 않는다."""
    from statop.render.chart import _axis_labels

    out = _axis_labels(8, [(0.0, "0.00012"), (0.5, "0.00034"), (1.0, "0.00056")])
    assert out.startswith("0.00012") and out.endswith("0.00056")
    assert "0.00034" not in out
