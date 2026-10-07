"""정상 데이터셋 10종 — **함정이 하나도 없는** 자료 ( 과잉경고 검수).

사례 11건이 "잡아야 할 것을 잡는가"를 본다면, 이쪽은 **"안 잡아야 할 것을 안 잡는가"**를
본다. 멀쩡한 자료에 빨간 배너가 뜨면 사람은 배너를 안 읽게 되고, 그러면 진짜 경고도
같이 묻힌다. 과잉경고는 검출 실패만큼 나쁘다.

전부 합성이고, 일부러 이런 것들이 **없게** 만들었다:
정의역 밖 값 · 척도 불일치(0~1 과 0~100 섞기) · 조성(합이 1) · 극단 불균형 ·
분석 대상에 남은 식별자 · log 와 원척도 혼용 · 총합이 크게 다른 카운트 쌍
"""

import numpy as np
import pandas as pd

N = 400


def d01_two_group_continuous() -> tuple[pd.DataFrame, dict]:
    """가장 흔한 모양 — 2군 연속 결과."""
    rng = np.random.default_rng(101)
    g = rng.choice(["case", "control"], N)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": g,
        "outcome": rng.normal(10, 2, N) + (g == "case") * 0.6,
        "age": rng.normal(55, 10, N),
    }), {"arm": "label", "outcome": "continuous", "age": "continuous"}


def d02_counts() -> tuple[pd.DataFrame, dict]:
    """카운트 — 총합(depth)을 비슷하게 맞춘 두 컬럼."""
    rng = np.random.default_rng(102)
    base = rng.gamma(3, 4, N)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "reads_a": rng.poisson(base),
        "reads_b": rng.poisson(base * 1.02),      # 총합 차이 2% — 정상 범위
    }), {"arm": "label", "reads_a": "count", "reads_b": "count"}


def d03_proportion() -> tuple[pd.DataFrame, dict]:
    """[0,1] 비율 — 경계값(0·1) 없이."""
    rng = np.random.default_rng(103)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "vaf": np.clip(rng.beta(2, 6, N), 0.01, 0.99),
    }), {"arm": "label", "vaf": "proportion"}


def d04_contingency() -> tuple[pd.DataFrame, dict]:
    """분할표 — 2×2, 각 칸이 충분히 크다."""
    rng = np.random.default_rng(104)
    arm = rng.choice(["case", "control"], N)
    p = np.where(arm == "case", 0.45, 0.35)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": arm,
        "responded": (rng.random(N) < p).astype(int),
    }), {"arm": "label", "responded": "probability"}


def d05_correlation() -> tuple[pd.DataFrame, dict]:
    """두 연속 변수의 연관 — 같은 척도."""
    rng = np.random.default_rng(105)
    x = rng.normal(0, 1, N)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "x": x, "y": 0.6 * x + rng.normal(0, 0.8, N),
    }), {"x": "continuous", "y": "continuous"}


def d06_repeated() -> tuple[pd.DataFrame, dict]:
    """반복측정 — 같은 대상을 전·후로 두 번."""
    rng = np.random.default_rng(106)
    n = N // 2
    base = rng.normal(10, 2, n)
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(n)] * 2,
        "time": ["pre"] * n + ["post"] * n,
        "value": np.r_[base, base + 0.5 + rng.normal(0, 0.7, n)],
    }), {"time": "label", "value": "continuous"}


def d07_survival() -> tuple[pd.DataFrame, dict]:
    """생존 — 시간 + 사건."""
    rng = np.random.default_rng(107)
    arm = rng.choice(["case", "control"], N)
    t = rng.exponential(np.where(arm == "case", 90, 70))
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": arm,
        "days": np.round(t, 1),
        "event": (rng.random(N) < 0.7).astype(int),
    }), {"arm": "label", "days": "continuous", "event": "probability"}


def d08_three_groups() -> tuple[pd.DataFrame, dict]:
    """3군 연속 — 군 크기가 고르다."""
    rng = np.random.default_rng(108)
    g = np.repeat(["low", "mid", "high"], N // 3)
    shift = {"low": 0.0, "mid": 0.3, "high": 0.6}
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(len(g))],
        "dose": g,
        "response": [rng.normal(10 + shift[x], 2) for x in g],
    }), {"dose": "label", "response": "continuous"}


def d09_large() -> tuple[pd.DataFrame, dict]:
    """큰 n — 10,000행. n 이 커지면 사소한 차이도 유의해진다."""
    rng = np.random.default_rng(109)
    n = 10_000
    g = rng.choice(["case", "control"], n)
    return pd.DataFrame({
        "sid": [f"S{i:05d}" for i in range(n)],
        "arm": g,
        "value": rng.normal(0, 1, n) + (g == "case") * 0.05,
    }), {"arm": "label", "value": "continuous"}


def d10_some_missing() -> tuple[pd.DataFrame, dict]:
    """결측이 조금 (5%) — 무작위로 빠진 정상 상황."""
    rng = np.random.default_rng(110)
    v = rng.normal(10, 2, N)
    v[rng.random(N) < 0.05] = np.nan
    return pd.DataFrame({
        "sid": [f"S{i:03d}" for i in range(N)],
        "arm": rng.choice(["case", "control"], N),
        "value": v,
    }), {"arm": "label", "value": "continuous"}


# 자료마다 **의도한 분석**. 과잉경고는 "사용자가 하려는 것"에 대해서만 센다 —
# 2군 비교용 자료에 상관을 걸면 라벨 컬럼이 걸리는 게 당연하고, 그건 올바른 경고다
INTENT = {
    "d01_two_group_continuous": {"op": "compare", "y": "outcome", "x": "arm"},
    "d02_counts": {"op": "correlate", "y": "reads_a", "x": "reads_b"},
    "d03_proportion": {"op": "compare", "y": "vaf", "x": "arm"},
    "d04_contingency": {"op": "compare", "y": "responded", "x": "arm"},
    "d05_correlation": {"op": "correlate", "y": "y", "x": "x"},
    "d06_repeated": {"op": "compare", "y": "value", "x": "time"},
    "d07_survival": {"op": "compare", "y": "days", "x": "arm"},
    "d08_three_groups": {"op": "compare", "y": "response", "x": "dose"},
    "d09_large": {"op": "compare", "y": "value", "x": "arm"},
    "d10_some_missing": {"op": "compare", "y": "value", "x": "arm"},
}

ALL = {
    "d01_two_group_continuous": d01_two_group_continuous,
    "d02_counts": d02_counts,
    "d03_proportion": d03_proportion,
    "d04_contingency": d04_contingency,
    "d05_correlation": d05_correlation,
    "d06_repeated": d06_repeated,
    "d07_survival": d07_survival,
    "d08_three_groups": d08_three_groups,
    "d09_large": d09_large,
    "d10_some_missing": d10_some_missing,
}
