"""실제 있었던 사례건의 합성 자료 — 오류를 **일부러** 심는다 .

멀쩡한 자료로는 검사가 도는지 알 수 없다. 사례마다 그 오류가 확실히 들어가게 만들고,
`test_cases.py` 가 기대한 규칙이 걸리는지 본다.
"""

import numpy as np
import pandas as pd

N = 300


def case01_distribution_ignored() -> pd.DataFrame:
    """#1 분포 무시 metric — 중꼬리·왜곡 자료에 평균·SD 기반 지표를 쓴다."""
    rng = np.random.default_rng(1)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        # 로그정규 + 극단값 몇 개 — 평균이 꼬리에 끌린다
        "value": np.r_[rng.lognormal(0, 1.4, N - 5), [80.0, 95.0, 110.0, 130.0, 150.0]],
    })


def case02_arbitrary_log() -> pd.DataFrame:
    """#2 단일 지표 / 임의 log — log 척도와 원척도를 섞어 차이·상관을 낸다."""
    rng = np.random.default_rng(2)
    raw = rng.lognormal(1, 1, N)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "raw_scale": raw,                 # 원척도
        "log_scale": np.log(raw),         # 같은 양의 log — 둘을 섞으면 비교가 안 된다
    })


def case03_probability_variability() -> pd.DataFrame:
    """#3 확률값 변동성 scale — [0,1] 확률의 변동을 SD 로 잰다 (0.5 근처가 원래 크다)."""
    rng = np.random.default_rng(3)
    p = np.clip(rng.beta(2, 2, N), 0.001, 0.999)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "prob": p,
    })


def case04_small_sample() -> pd.DataFrame:
    """#4 소표본 가정검정 — n 이 작은데 정규성 '통과'를 근거로 t 검정을 쓴다."""
    rng = np.random.default_rng(4)
    n = 9
    return pd.DataFrame({
        "sid": [f"S{i:02d}" for i in range(2 * n)],
        "arm": ["case"] * n + ["control"] * n,
        "value": np.r_[rng.normal(0, 1, n), rng.normal(0.4, 3, n)],
    })


def case05_simpson() -> pd.DataFrame:
    """#5 Simpson — 전체 방향과 층별 방향이 반대."""
    rng = np.random.default_rng(5)
    rows = []
    # 층 A: 대부분 case, 성공률 낮음 / 층 B: 대부분 control, 성공률 높음
    for site, n_case, n_ctrl, p_case, p_ctrl in (("A", 180, 20, 0.30, 0.20),
                                                 ("B", 20, 180, 0.90, 0.80)):
        for arm, n, p in (("case", n_case, p_case), ("control", n_ctrl, p_ctrl)):
            for _ in range(n):
                rows.append({"site": site, "arm": arm,
                             "success": int(rng.random() < p)})
    df = pd.DataFrame(rows)
    df.insert(0, "sid", [f"S{i:03d}" for i in range(len(df))])
    return df


def case06_hidden_imbalance() -> pd.DataFrame:
    """#6 숨은 불균형 — 군과 메타(배치)가 거의 겹친다."""
    rng = np.random.default_rng(6)
    arm = np.r_[["case"] * 150, ["control"] * 150]
    # batch 가 arm 을 거의 그대로 따라간다 — 어느 것의 효과인지 못 가른다
    batch = np.where(rng.random(300) < 0.95, np.where(arm == "case", "B1", "B2"),
                     np.where(arm == "case", "B2", "B1"))
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(300)],
        "arm": arm, "batch": batch,
        "value": rng.normal(0, 1, 300) + (batch == "B1") * 0.8,
    })


def case07_composition() -> pd.DataFrame:
    """#7 조성 자료에 일반 상관 — 합이 1인 성분들."""
    rng = np.random.default_rng(7)
    a = rng.dirichlet([2, 3, 5], N)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "frac_A": a[:, 0], "frac_B": a[:, 1], "frac_C": a[:, 2],
    })


def case08_multiplicity() -> pd.DataFrame:
    """#8 다중검정 — 비교할 컬럼이 20개인데 보정 없이 훑는다."""
    rng = np.random.default_rng(8)
    d = {"sid": [f"S{i:03d}" for i in range(N)],
         "arm": rng.choice(["case", "control"], N)}
    for k in range(20):                       # 전부 진짜 차이가 없는 컬럼
        d[f"m{k:02d}"] = rng.normal(0, 1, N)
    return pd.DataFrame(d)


def case09_hypothesis_mismatch() -> pd.DataFrame:
    """#9 가설-검정 불일치 — "정상=교란≠암" 을 묻는데 3군 omnibus 를 쓴다."""
    rng = np.random.default_rng(9)
    grp = np.r_[["normal"] * 100, ["confound"] * 100, ["tumor"] * 100]
    base = np.where(grp == "tumor", 1.2, 0.0)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(300)],
        "grp": grp, "value": base + rng.normal(0, 1, 300),
    })


def case10_metric_changed() -> pd.DataFrame:
    """#10 비교 불가 metric 변경 — 두 세트에서 다른 척도로 잰 점수."""
    rng = np.random.default_rng(10)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "score_0_1": rng.beta(2, 2, N),            # 0~1 척도
        "score_0_100": rng.beta(2, 2, N) * 100,    # 0~100 척도 — 같은 것을 다르게 잼
    })


def case11_external_overlap(tmp: str) -> dict:
    """#11 external 중복 — 학습 세트와 외부 세트에 같은 행이 들어 있다."""
    rng = np.random.default_rng(11)
    n = 240
    base = pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(n)],
        "x1": rng.normal(0, 1, n), "x2": rng.normal(0, 1, n),
        "label": rng.integers(0, 2, n),
    })
    train = base.iloc[:180]
    # 외부 세트의 절반이 train 에서 그대로 왔다 — 외운 것을 맞히게 된다
    ext = pd.concat([base.iloc[150:180], base.iloc[180:]], ignore_index=True)
    paths = {}
    for name, d in (("source", base), ("train", train), ("external", ext)):
        p = f"{tmp}/case11_{name}.csv"
        d.to_csv(p, index=False)
        paths[name] = p
    return paths


ALL = {
    1: case01_distribution_ignored, 2: case02_arbitrary_log,
    3: case03_probability_variability, 4: case04_small_sample,
    5: case05_simpson, 6: case06_hidden_imbalance, 7: case07_composition,
    8: case08_multiplicity, 9: case09_hypothesis_mismatch,
    10: case10_metric_changed,
}
