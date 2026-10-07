"""터미널 그림 — 축·눈금이 있는 축약 그림 (DECISIONS).

규칙: y축 눈금 ≤ 5개 · 가로 구간은 화면 폭에 맞춰 축약(합친 사실을 표기) · 축 끝값은 항상 표시.
정밀 확인은 웹이 한다. 여기서는 "이상 신호를 알아채는" 수준을 목표로 한다.
"""

import math

BLOCKS = " ▁▂▃▄▅▆▇█"
MAX_Y_TICKS = 5


def _fmt(v: float) -> str:
    """축 눈금 숫자 — 자릿수를 아껴 쓴다."""
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 10_000 or a < 0.001:
        return f"{v:.1e}"
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:.3g}"
    return f"{v:.2g}"


def _tick_rows(height: int, max_ticks: int = MAX_Y_TICKS) -> set[int]:
    """눈금을 표시할 행 번호 집합 — 위·아래 끝을 포함해 최대 max_ticks개 ."""
    n = min(max_ticks, height)
    if n <= 1:
        return {height}
    return {height - round(i * (height - 1) / (n - 1)) for i in range(n)}


def _axis_labels(span: int, ticks: list[tuple[float, str]]) -> str:
    """가로축 눈금 줄 — 양 끝은 **반드시** 보이고, 가운데는 자리가 남을 때만 .

    끝값을 잘라내면 그림이 어느 범위인지 알 수 없다. 글자가 길면 줄을 늘려서라도
    남긴다 — 폭에 맞추자고 최댓값을 지우면 그림이 거짓말을 한다.
    """
    if not ticks:
        return ""
    first, last = ticks[0][1], ticks[-1][1]
    if len(ticks) == 1:
        return first
    total = max(span, len(first) + len(last) + 1)
    buf = list(" " * total)
    buf[0:len(first)] = first
    buf[total - len(last):total] = last
    for frac, text in ticks[1:-1]:
        start = min(max(0, round(frac * (total - 1)) - len(text) // 2), total - len(text))
        lo, hi = max(0, start - 1), min(total, start + len(text) + 1)
        if all(ch == " " for ch in buf[lo:hi]):      # 좌우로 한 칸씩 띄어야 읽힌다
            buf[start:start + len(text)] = text
    return "".join(buf)


def histogram(counts: list[int], edges: list[float], width: int = 40,
              height: int = 6) -> list[str]:
    """축이 있는 히스토그램. 구간이 폭을 넘으면 이웃을 합치고 그 사실을 표기한다."""
    if not counts:
        return []
    merged, note = counts, ""
    if len(counts) > width:
        step = len(counts) / width
        merged = [sum(counts[int(i * step): max(int((i + 1) * step), int(i * step) + 1)])
                  for i in range(width)]
        from statop.messages import msg

        note = "  " + msg("chart_bins_merged", n=len(counts), w=width)

    top = max(merged) or 1
    tick_rows = _tick_rows(height)      # y축 눈금 ≤ MAX_Y_TICKS
    lab_w = max(len(_fmt(top * r / height)) for r in tick_rows)
    lines: list[str] = []
    for row in range(height, 0, -1):  # 위에서 아래로
        lo = top * (row - 1) / height
        hi = top * row / height
        label = _fmt(hi).rjust(lab_w) if row in tick_rows else " " * lab_w
        cells = []
        for c in merged:
            if c >= hi:
                cells.append("█")
            elif c <= lo:
                cells.append(" ")
            else:
                frac = (c - lo) / (hi - lo) if hi > lo else 0
                cells.append(BLOCKS[max(1, round(frac * (len(BLOCKS) - 1)))])
        lines.append(f"{label} ┤{''.join(cells)}")

    lo, hi = edges[0], edges[-1]
    lines.append(" " * lab_w + " └" + "─" * len(merged))
    lines.append(" " * (lab_w + 2) + _axis_labels(
        len(merged), [(0.0, _fmt(lo)), (0.5, _fmt((lo + hi) / 2)), (1.0, _fmt(hi))]) + note)
    return lines


def boxplot(quartiles: list[float], outliers: tuple[float, float] | None = None,
            width: int = 40) -> list[str]:
    """박스플롯 한 줄 + 축 눈금. quartiles = [min, q1, median, q3, max]."""
    mn, q1, med, q3, mx = quartiles
    if mx <= mn:
        from statop.messages import msg

        return ["  " + msg("chart_single_value", v=_fmt(mn))]

    def pos(v: float) -> int:
        return max(0, min(width - 1, round((v - mn) / (mx - mn) * (width - 1))))

    from statop.messages import msg

    row = [" "] * width
    for i in range(pos(mn), pos(mx) + 1):   # 수염 전체
        row[i] = "─"
    for i in range(pos(q1), pos(q3) + 1):   # 상자
        row[i] = "▓"
    row[pos(mn)] = "├"
    row[pos(mx)] = "┤"
    row[pos(med)] = "│"

    out = ["  " + "".join(row)]
    out.append("  " + _axis_labels(width, [
        (0.0, _fmt(mn)), ((med - mn) / (mx - mn), _fmt(med)), (1.0, _fmt(mx))]))
    # 그림만 보면 상자의 양 끝이 얼마인지 알 수 없다 — **이름과 값을 적는다**
    from statop.render.spark import quartile_stats, stat_lines

    out += stat_lines(quartile_stats({"quartiles": list(quartiles)}))[:2]
    out.append("  " + msg("q_whisker_note"))
    # 상자가 사실상 안 보이면 그 자체가 신호다 — 왜 좁은지 말해준다
    iqr_ratio = (q3 - q1) / (mx - mn) if mx > mn else 0
    if iqr_ratio < 0.10:      # IQR이 전체 범위의 10% 미만이면 상자가 사실상 안 보인다
        out.append("  " + msg("chart_box_narrow", ratio=iqr_ratio))
    if outliers:
        lo_r, hi_r = outliers
        if lo_r or hi_r:
            out.append("  " + msg("chart_outlier_sides", lo=lo_r, hi=hi_r))
    return out


def scatter(xs: list[float], ys: list[float], width: int = 40, height: int = 10,
            xlab: str = "x", ylab: str = "y") -> list[str]:
    """산점도 — 격자 칸당 점 개수를 농도로. 관계 파악용(정밀 확인은 웹)."""
    pts = [(x, y) for x, y in zip(xs, ys)
           if x is not None and y is not None and not (math.isnan(x) or math.isnan(y))]
    if not pts:
        from statop.messages import msg

        return ["  " + msg("chart_no_points")]
    xmin, xmax = min(p[0] for p in pts), max(p[0] for p in pts)
    ymin, ymax = min(p[1] for p in pts), max(p[1] for p in pts)
    grid = [[0] * width for _ in range(height)]
    for x, y in pts:
        cx = 0 if xmax == xmin else round((x - xmin) / (xmax - xmin) * (width - 1))
        cy = 0 if ymax == ymin else round((y - ymin) / (ymax - ymin) * (height - 1))
        grid[height - 1 - cy][cx] += 1

    top = max(max(r) for r in grid) or 1
    # 히스토그램과 같은 규칙으로 눈금을 고른다 (행 번호는 아래에서 1..height)
    tick_rows = _tick_rows(height)
    lab_w = max(len(_fmt(ymin + (ymax - ymin) * (r - 1) / max(1, height - 1)))
                for r in tick_rows)
    lines = []
    for r, row in enumerate(grid):
        val = ymax - (ymax - ymin) * r / (height - 1)
        label = _fmt(val).rjust(lab_w) if (height - r) in tick_rows else " " * lab_w
        cells = "".join(" " if c == 0 else BLOCKS[max(1, round(c / top * (len(BLOCKS) - 1)))]
                        for c in row)
        lines.append(f"{label} ┤{cells}")
    lines.append(" " * lab_w + " └" + "─" * width)
    from statop.messages import msg

    lines.append(" " * (lab_w + 2) + _axis_labels(
        width, [(0.0, _fmt(xmin)), (0.5, _fmt((xmin + xmax) / 2)), (1.0, _fmt(xmax))]))
    lines.append(" " * (lab_w + 2) + msg("chart_scatter_axes", x=xlab, y=ylab, n=len(pts)))
    return lines


def strip_plot(groups: dict[str, list[float]], width: int = 46) -> list[str]:
    """군별 점 그림 — 상자 요약이 아니라 **점 하나하나**를 찍는다 .

    상자만 보면 어느 샘플이 결과를 끌고 있는지 알 수 없다. 겹치는 자리는 개수를 농도로
    쓰되, 표시할 점(marks)은 겹쳐도 그 글자가 이긴다 — 뺄 후보를 눈으로 찾아야 한다.
    """
    vals = [v for arr in groups.values() for v in arr]
    if not vals:
        from statop.messages import msg

        return ["  " + msg("chart_no_points")]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    lab_w = max(len(g[:10]) for g in groups)
    lines = []
    for name, arr in groups.items():
        row = [" "] * width
        counts = [0] * width
        for v in arr:
            i = max(0, min(width - 1, round((v - lo) / span * (width - 1))))
            counts[i] += 1
        for i, c in enumerate(counts):
            if c:
                row[i] = BLOCKS[min(len(BLOCKS) - 1, max(1, c))]
        lines.append(f"{name[:10]:<{lab_w}s} │{''.join(row)}")
    lines.append(" " * lab_w + " └" + "─" * width)
    lines.append(" " * (lab_w + 2) + _axis_labels(
        width, [(0.0, _fmt(lo)), (0.5, _fmt((lo + hi) / 2)), (1.0, _fmt(hi))]))
    return lines
