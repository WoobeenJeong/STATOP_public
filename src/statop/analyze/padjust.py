"""다중검정 보정 — **규칙표가 고른 방법을 실행하는 자리** (C-15 · P-221~225).

어느 방법을 쓸지는 이미 `rules/post.yaml` 이 정해 두었다 (P-221 Holm 기본,
P-222 Bonferroni 검정 수 ≤3, P-223 BH 검정 수 대, P-225 보정 전/후 병기).
판정(C-15)과 권고(MR-G06)도 이미 있다 — 비어 있던 것은 **p 값을 실제로 보정하는
계산**뿐이었다. 여기가 그 자리다.

한 번 재고 p<0.05 면 20번에 한 번 틀린다. 스무 번 재면 **아무 관계가 없어도** 평균
한 번은 0.05 밑이 나온다. 그래서 "몇 번 쟀는가"를 같이 세야 한다.

세 가지를 같은 자리에 둔다 — 무엇을 보장하는지가 다르다:
- Bonferroni·Holm : **한 번이라도 틀릴 확률**(family-wise)을 α 이하로
- BH(FDR)         : 유의하다고 **부른 것 중 거짓의 비율**을 q 이하로 (더 많이 살린다)

보정값 자체는 표준 정의 그대로다 — 판정 문구만 여기서 만든다.
"""

import numpy as np

from statop.messages import msg

METHODS = ("none", "bonferroni", "holm", "bh")

# 규칙표(post.yaml)의 어느 항목을 실행한 것인지 — 화면이 근거를 댈 수 있게
RULE_OF = {"bonferroni": "P-222", "holm": "P-221", "bh": "P-223"}
DEFAULT = "holm"        # post.yaml 의 P-221 이 `note: 기본값`


def adjust(pvalues, method: str = DEFAULT) -> list[float]:  # noqa: ANN001
    """보정한 p — 원래 p 와 **같은 순서**로 돌려준다.

    보정 p 는 1 을 넘지 않고, 단조성을 지킨다(작은 것이 큰 것보다 커지지 않는다).
    """
    p = np.asarray(list(pvalues), dtype="float64")
    n = p.size
    if n == 0:
        return []
    if method == "none":
        return [float(x) for x in p]
    if method == "bonferroni":
        return [float(min(1.0, x * n)) for x in p]

    order = np.argsort(p)
    ranked = p[order]
    if method == "holm":
        # 작은 것부터 (n-i) 를 곱하고, 뒤로 가며 값이 줄지 않게 누적 최대
        scaled = ranked * (n - np.arange(n))
        out_sorted = np.maximum.accumulate(scaled)
    elif method == "bh":
        # 큰 것부터 n/i 를 곱하고 누적 최소 — 작은 p 가 큰 p 보다 커지지 않게
        scaled = ranked * n / (np.arange(n) + 1)
        out_sorted = np.minimum.accumulate(scaled[::-1])[::-1]
    else:
        raise ValueError(msg("padj_unknown"))

    out = np.empty(n)
    out[order] = np.minimum(out_sorted, 1.0)
    return [float(x) for x in out]


def report(rows: list[dict], method: str = DEFAULT, alpha: float = 0.05) -> dict:
    """[{name, p}] → 보정 결과와 읽는 줄. 껍데기는 이 줄을 그대로 쓴다 ."""
    if method not in METHODS:
        raise ValueError(msg("padj_unknown"))
    usable = [r for r in rows if r.get("p") is not None]
    adj = adjust([r["p"] for r in usable], method)
    out, lines = [], []
    for r, a in zip(usable, adj):
        sig = a <= alpha
        out.append({**r, "p_adjusted": a, "significant": bool(sig)})
        lines.append("  " + msg("padj_row", name=r["name"], raw=r["p"], adj=a,
                                mark=msg("padj_sig" if sig else "padj_ns")))
    head = msg("padj_head", n=len(usable), method=msg("padj_" + method))
    return {"method": method, "rule": RULE_OF.get(method, ""), "alpha": alpha,
            "rows": out,
            "lines": [head, *lines, "  " + msg("padj_why")] if usable else [],
            "head": head, "why": msg("padj_why")}
