"""터미널용 분포 렌더 — 같은 숫자를 웹은 막대로, 터미널은 블록 문자로 그린다.

숫자는 코어가 만들고(statop.io.distribution) 여기서는 모양만 만든다.
"""

BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(counts: list[int], width: int = 24) -> str:
    """도수 목록을 블록 문자 막대로. 구간이 많으면 합쳐서 width에 맞춘다."""
    if not counts:
        return ""
    if len(counts) > width:  # 이웃 구간을 묶어 폭을 맞춘다
        step = len(counts) / width
        merged = [sum(counts[int(i * step): max(int((i + 1) * step), int(i * step) + 1)])
                  for i in range(width)]
        counts = merged
    top = max(counts) or 1
    return "".join(BLOCKS[min(len(BLOCKS) - 1, round(c / top * (len(BLOCKS) - 1)))]
                   for c in counts)


def bar(ratio: float, width: int = 14) -> str:
    """비율(0~1)을 가로 막대로 — 범주형 수준 표시용."""
    filled = round(max(0.0, min(1.0, ratio)) * width)
    return "█" * filled + "·" * (width - filled)


def quartile_stats(d: dict) -> list[dict]:
    """상자그림의 다섯 수 + IQR + 울타리 — **이름과 값을 함께** .

    값만 있고 이름이 없으면 어느 것이 Q1 인지 세어야 하고, 울타리는 아예 없어서
    "이 값이 바깥인가"를 손으로 계산해야 했다. CLI·TUI·웹이 이 목록 하나를 쓴다.
    """
    from statop.messages import msg

    def num(v: float) -> str:
        """축 눈금(_fmt)보다 **한 자리 더** 쓴다 — 이건 읽고 적는 수치다.
        0.999 가 축에서는 `1` 로 줄어도 되지만, Q3 로 적힐 때는 안 된다.

        아주 작은 값은 `0.0000` 으로 뭉개지므로 지수로 적는다 (1e-5 부터).
        """
        if v and abs(v) < 1e-4:
            return f"{v:.3e}"
        return f"{v:,.4g}"

    q = d.get("quartiles")
    if not q:
        return []
    iqr = d.get("iqr")
    if iqr is None:
        iqr = q[3] - q[1]
    lo = d.get("fence_lo", q[1] - 1.5 * iqr)
    hi = d.get("fence_hi", q[3] + 1.5 * iqr)
    pairs = (("q_min", q[0]), ("q_q1", q[1]), ("q_q2", q[2]), ("q_q3", q[3]),
             ("q_max", q[4]), ("q_iqr", iqr), ("q_fence_lo", lo), ("q_fence_hi", hi))
    return [{"key": k, "label": msg(k), "value": float(v), "text": num(float(v))}
            for k, v in pairs]


def stat_lines(stats: list[dict]) -> list[str]:
    """다섯 수 줄 — **끊어서** 낸다. 값이 길면 한 줄에 다 못 담는다."""
    from statop.messages import msg

    def row(items) -> str:  # noqa: ANN001
        return "  " + " · ".join(f"{x['label']} {x['text']}" for x in items)

    return [row(stats[:5]), row(stats[5:]), "  " + msg("q_fence_note")]


def format_distribution(d: dict, with_stats: bool = True) -> list[str]:
    """분포 요약 한 컬럼을 터미널 줄 목록으로. 과한 정보 대신 압축 .

    with_stats=False 는 **상자그림을 이미 그린 자리**에서 쓴다 — 그림이 다섯 수를
    적고 오므로 여기서 또 적으면 같은 줄이 두 번 나온다.
    """
    from statop.messages import msg

    out: list[str] = []
    miss = msg("dist_missing_suffix", n=d["n_missing"]) if d["n_missing"] else ""
    if d["kind"] == "numeric":
        q = d["quartiles"]
        out.append(f"  {sparkline(d['bins'])}   " + msg("dist_numeric_head", n=d["n"]) + miss)
        # 이름과 값을 나란히 — 어느 수가 Q1 인지 세지 않게, 울타리는 계산하지 않게.
        # 이름 없이 "사분위 60.3–83.25" 로만 적던 줄을 이걸로 대신한다
        if with_stats:
            # 한 줄에 몰면 150자가 넘어 터미널에서 접힌다 — 값이 길어지면 더 그렇다.
            # 다섯 수 / IQR·울타리 / 설명 으로 끊는다
            stats = quartile_stats(d)
            out += stat_lines(stats)
        flags = []
        if abs(d["skewness"]) >= 1:
            flags.append(msg("dist_skew", v=d["skewness"]))
        if d["outlier_rate_iqr"] >= 0.05:
            flags.append(msg("dist_outlier_iqr", v=d["outlier_rate_iqr"]))
        if d["outlier_rate_mad"] >= 0.05:
            flags.append(msg("dist_outlier_mad", v=d["outlier_rate_mad"]))
        if d["zeros_rate"] >= 0.3:
            flags.append(msg("dist_zeros", v=d["zeros_rate"]))
        # 음수 여부는 그 자체로 문제가 아니라 의미 타입(count·확률 등)과 함께 판단해야 하므로
        # 여기서 경고로 띄우지 않는다 — C-14(척도 조건 검증)가 타입을 전제로 판정한다
        if flags:
            out.append("  " + " · ".join(flags))
    else:
        out.append("  " + msg("dist_levels_head", n_levels=d["n_levels"], n=d["n"]) + miss)
        for lv in d["levels"]:
            out.append(f"  {lv['value'][:18]:<18s} {bar(lv['ratio'])} {lv['ratio']:>5.1%} ({lv['n']:,})")
    return out
