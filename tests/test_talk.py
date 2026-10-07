"""발표용 데이터 3종 — **심어 둔 이야기가 실제로 그 숫자로 나오는지** (demo/talk).

이야기가 성립하지 않는 자료로 발표하면 그 자리에서 무너진다. 생성기를 건드리면
여기서 걸린다. 파일이 아니라 **생성기**를 보고 검사한다 — demo/talk 는 사용자가
직접 만져 보는 자리다.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats


@pytest.fixture(scope="module")
def made():
    gen = Path(__file__).resolve().parents[1] / "demo" / "make_talk.py"
    if not gen.exists():
        pytest.skip("발표용 생성기가 없음")
    spec = importlib.util.spec_from_file_location("make_talk", gen)
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    a, b = mk.build_integrity(np.random.default_rng(mk.SEED + 50))
    return {
        "001": mk.build_group_correlation(np.random.default_rng(mk.SEED)),
        "002": mk.build_entropy(np.random.default_rng(mk.SEED + 1)),
        "003a": a, "003b": b,
    }


def test_001_only_the_hard_measure_sees_it(made):
    """순위로는 안 보이고 **거리상관**으로는 보인다 — 그래서 Spearman 을 guardrail 로."""
    from statop.analyze.run import RUNNERS

    df = made["001"]
    c = df[df.group == "cancer"]
    assert len(c) == 27, "작은 n 이 이야기의 전제다"

    sub = pd.DataFrame({"x": c.cfdna_conc.to_numpy(), "y": c.immune_ratio.to_numpy()})
    dcor = RUNNERS["T-304"](sub, "x", "y", "two-sided")
    assert dcor.p < 0.05, f"dCor 이 못 본다: p={dcor.p}"
    assert stats.spearmanr(c.cfdna_conc, c.immune_ratio).pvalue > 0.05
    assert stats.pearsonr(c.cfdna_conc, c.immune_ratio).pvalue > 0.05

    # 섞으면 가짜로 유의해진다 — 군을 나눠야 하는 이유
    assert stats.pearsonr(df.cfdna_conc, df.immune_ratio).pvalue < 0.05
    assert stats.pearsonr(df[df.group == "normal"].cfdna_conc,
                          df[df.group == "normal"].immune_ratio).pvalue > 0.05
    assert sorted(df.subtype.unique()) == ["eap2", "eap3", "lihc", "paad"]


def test_002_the_distribution_decides_the_answer(made):
    """같은 자료인데 분포를 바꿔 보면 차이가 벌어진다 (실제 있었던 사례)."""
    df = made["002"]
    a, b = df[df.label == 0], df[df.label == 1]

    def effect(col, f=lambda x: x):  # noqa: ANN001
        x, y = f(a[col]), f(b[col])
        sd = np.sqrt((x.var(ddof=1) + y.var(ddof=1)) / 2)
        return (y.mean() - x.mean()) / sd, stats.ttest_ind(x, y, equal_var=False).pvalue

    # 정규 가정 엔트로피는 폭만 쓴다 — 두 군의 폭이 같으니 **겹쳐야** 한다
    d0, p0 = effect("entropy")
    assert p0 > 0.2 and abs(d0) < 0.2, f"처음부터 갈리면 이야기가 없다 (d={d0})"
    ds, _ = effect("frag_len_sd")
    assert abs(ds) < 0.2, f"폭이 군마다 다르면 겹칠 수가 없다 (d={ds})"

    # 지수 가정은 척도를 쓴다 — 그건 다르다
    d1, p1 = effect("frag_len_mean", np.log)
    assert abs(d1) > 1.5 and p1 < 1e-10, f"고쳐도 안 갈린다 (d={d1})"

    # **저장된 entropy 를 수식으로 정확히 되살릴 수 있어야** 한다 (반올림 자리까지만 차이)
    again = 0.5 * np.log(2 * np.pi * np.e * df.frag_len_sd ** 2)
    assert float((again - df.entropy).abs().max()) < 1e-5, "예1 이 그 컬럼을 재현하지 못한다"
    assert {"frag_len_sd", "frag_len_mean"} <= set(df.columns)


def test_003_the_pairing_is_what_reveals_the_drift(made):
    """age ↔ age_group 을 짝지어야 tumor_frac 의 흔들림을 나이 축에서 볼 수 있다."""
    m = made["003a"].merge(made["003b"], on="sample_id", suffixes=("_a", "_b"))
    assert "age" in made["003a"] and "age_group" in made["003b"]
    assert "age" not in made["003b"], "B 에 age 가 있으면 짝 지을 일이 없다"

    assert stats.spearmanr(m.age, m.age_group).statistic > 0.95   # 순위는 맞는다
    assert float((m.age == m.age_group).mean()) < 0.2             # 값은 다르다

    dif = (m.tumor_frac_b - m.tumor_frac_a).abs()
    assert int((dif > 0).sum()) > len(m) * 0.9
    assert dif.max() < 0.02, "미세한 변동이어야 한다 — 크게 틀어지면 이야기가 아니다"
    assert dif[m.age >= 60].mean() > dif[m.age < 60].mean() * 3
    assert stats.spearmanr(m.age, dif).pvalue < 1e-6
