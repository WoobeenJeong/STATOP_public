"""발표용 데이터에 **심어 둔 것이 실제로 그 숫자로 나오는지** 확인한다.

이야기가 성립하지 않는 자료로 발표하면 그 자리에서 무너진다. 생성기를 고칠 때마다
이걸 돌린다 — 틀어졌으면 숫자와 함께 말한다.

사용법:  python demo/verify_talk.py [데이터디렉터리]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

OK, BAD = "  ✅", "  ⛔"


def chk(label: str, got, want: str, ok: bool) -> bool:  # noqa: ANN001
    print(f"{OK if ok else BAD} {label}: {got}   (기대: {want})", flush=True)
    return ok


def check_001(d: Path) -> bool:
    """군별 상관 · 작은 n · 지표 간 판단 차이."""
    print("\n001 — 두 군에서 따로 보기, 그리고 작은 n", flush=True)
    df = pd.read_csv(d / "001_group_correlation.csv")
    good = True
    good &= chk("아형", sorted(df.subtype.unique()),
                "eap2·eap3(normal) / lihc·paad(cancer)",
                sorted(df.subtype.unique()) == ["eap2", "eap3", "lihc", "paad"])
    n_c = int((df.group == "cancer").sum())
    good &= chk("cancer n", n_c, "27 (아슬아슬하게 쓸 만한 크기)", n_c == 27)

    # 섞으면 **가짜로** 유의해진다 — 군끼리 수준이 달라서 생기는 상관이다.
    # "따로 봐야 한다"의 근거가 바로 이것이다
    mixed = stats.pearsonr(df.cfdna_conc, df.immune_ratio)
    good &= chk("군을 안 나누면", f"r={mixed.statistic:+.3f} p={mixed.pvalue:.4f}",
                "가짜로 유의해진다 (군끼리 수준이 다르다) — 그래서 따로 본다",
                mixed.pvalue < 0.05)
    # 어려운 지표(거리상관)만 본다 — 제품이 쓰는 그 함수로 잰다
    from statop.analyze.run import RUNNERS

    c = df[df.group == "cancer"]
    sub = pd.DataFrame({"x": c.cfdna_conc.to_numpy(), "y": c.immune_ratio.to_numpy()})
    dcor = RUNNERS["T-304"](sub, "x", "y", "two-sided")
    good &= chk("cancer dCor (T-304)", f"dCor={dcor.effect['value']:.3f} p={dcor.p:.4f}",
                "유의 — 비단조라 거리로 봐야 보인다", dcor.p < 0.05)
    rho = stats.spearmanr(c.cfdna_conc, c.immune_ratio)
    good &= chk("cancer Spearman", f"rho={rho.statistic:+.3f} p={rho.pvalue:.4f}",
                "유의하지 않음 — 순위로는 안 보인다 (guardrail 로 함께 읽는다)",
                rho.pvalue > 0.05)
    pe = stats.pearsonr(c.cfdna_conc, c.immune_ratio)
    good &= chk("cancer Pearson", f"r={pe.statistic:+.3f} p={pe.pvalue:.4f}",
                "유의하지 않음 — 직선이 아니다", pe.pvalue > 0.05)
    norm = df[df.group == "normal"]
    rn = stats.pearsonr(norm.cfdna_conc, norm.immune_ratio)
    good &= chk("normal", f"p={rn.pvalue:.3f}", "유의하지 않음", rn.pvalue > 0.05)
    return good


def check_002(d: Path) -> bool:
    """분포를 잘못 보면 차이가 묻힌다."""
    print("\n002 — 같은 자료, 분포를 바꿔 보면 차이가 벌어진다", flush=True)
    df = pd.read_csv(d / "002_entropy_wrong_dist.csv")
    a, b = df[df.label == 0], df[df.label == 1]
    good = True

    def effect(col, f=lambda x: x):  # noqa: ANN001
        x, y = f(a[col]), f(b[col])
        sd = np.sqrt((x.var(ddof=1) + y.var(ddof=1)) / 2)
        t = stats.ttest_ind(x, y, equal_var=False)
        return (y.mean() - x.mean()) / sd, t.pvalue

    d0, p0 = effect("entropy")
    good &= chk("entropy 그대로", f"d={d0:+.2f} p={p0:.3f}",
                "두 군이 겹친다 (p>0.2, |d|<0.2)", p0 > 0.2 and abs(d0) < 0.2)
    ds, _ = effect("frag_len_sd")
    good &= chk("폭(frag_len_sd)", f"d={ds:+.2f}", "군마다 같다 (|d|<0.2)", abs(ds) < 0.2)
    d1, p1 = effect("frag_len_mean", np.log)
    good &= chk("1+ln(frag_len_mean)", f"d={d1:+.2f} p={p1:.2e}",
                "확실히 갈린다 (|d|>1.5)", p1 < 1e-10 and abs(d1) > 1.5)
    again = 0.5 * np.log(2 * np.pi * np.e * df.frag_len_sd ** 2)
    gap = float((again - df.entropy).abs().max())
    good &= chk("예1 이 entropy 를 재현", f"최대 차이 {gap:.1e}",
                "반올림 자리까지만 차이 (<1e-5)", gap < 1e-5)
    return good


def check_003(d: Path) -> bool:
    """이름도 척도도 다른 짝, 그리고 나이와 함께 커지는 흔들림."""
    print("\n003 — 무결성: 짝을 지어야 보이는 것", flush=True)
    a = pd.read_csv(d / "003a_integrity_before.csv")
    b = pd.read_csv(d / "003b_integrity_after.csv")
    m = a.merge(b, on="sample_id", suffixes=("_a", "_b"))
    good = True
    good &= chk("A 의 나이 컬럼", "age", "age (원값)", "age" in a.columns)
    good &= chk("B 의 나이 컬럼", "age_group", "age_group (10살 묶음)",
                "age_group" in b.columns and "age" not in b.columns)

    rho = stats.spearmanr(m.age, m.age_group).statistic
    good &= chk("age ↔ age_group 순위", f"rho={rho:.4f}",
                "거의 1 — 깨졌지만 크게 깨지진 않았다", rho > 0.95)
    exact = float((m.age == m.age_group).mean())
    good &= chk("값이 그대로 같은 비율", f"{exact:.1%}", "낮다 (값으로는 다르다)",
                exact < 0.2)

    n_diff = int((m.tumor_frac_a != m.tumor_frac_b).sum())
    good &= chk("tumor_frac 다른 행", f"{n_diff}/{len(m)}", "거의 전부, 다만 미세하게",
                n_diff > len(m) * 0.9)
    dif = (m.tumor_frac_b - m.tumor_frac_a).abs()
    young = dif[m.age < 60].mean()
    old = dif[m.age >= 60].mean()
    p = stats.spearmanr(m.age, dif).pvalue
    good &= chk("흔들림이 나이를 따라가나",
                f"60세 미만 {young:.5f} · 이상 {old:.5f} · p={p:.1e}",
                "높은 나이에서 더 흔들린다", old > young * 3 and p < 1e-6)
    return good


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "talk")
    if not (d / "001_group_correlation.csv").exists():
        raise SystemExit(f"{d} 에 발표용 데이터가 없습니다 — 먼저 make_talk.py 를 돌리세요")
    print(f"발표용 데이터 확인 — {d}", flush=True)
    results = [check_001(d), check_002(d), check_003(d)]
    n_ok = sum(results)
    print(f"\n{n_ok}/3 상황이 심어 둔 대로 나옵니다", flush=True)
    raise SystemExit(0 if n_ok == 3 else 1)


if __name__ == "__main__":
    main()
