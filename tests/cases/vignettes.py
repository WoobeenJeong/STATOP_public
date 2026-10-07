"""검정 선택 vignette 세트  — 설계를 주고 **어느 검정이 맞나**를 묻는다.

요구사항는 공개 vignette 20~27건 기준 정답률 ≥ 90% 를 요구한다. 논문에 실린 vignette 을
그대로 옮기지 않고 **같은 결정 공간을 덮는 22건을 직접 만들었다** — 인용·권리 문제를
피하고, 무엇을 묻는지 우리가 알 수 있게 하기 위해서다. 출처가 다르다는 점은 그대로
밝혀 둔다.

각 건은 이렇게 생겼다.
- `df` — 그 설계에 맞는 합성 자료 (가정을 일부러 맞추거나 어긋나게 만든다)
- `types` — 확정된 의미 타입
- `spec` — 사용자가 A1 에서 고를 질문 설계
- `expect` — 맞는 검정. 여럿이면 그중 하나면 맞다 (예: 비정규 2군 → MWU 또는 BM)
- `why` — 왜 그것이 맞는가 (사람이 읽고 검토할 수 있게)
"""

import numpy as np
import pandas as pd

N = 200


def _rng(seed: int):
    return np.random.default_rng(1000 + seed)


def v01():
    """2군 독립 · 연속 · 정규 · 등분산 → 평균 비교."""
    r = _rng(1)
    g = np.repeat(["a", "b"], N // 2)
    y = np.r_[r.normal(10, 2, N // 2), r.normal(10.8, 2, N // 2)]
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-01", "y": "y", "group": "grp"},
            {"T-101", "T-102"}, "정규·등분산이면 t 계열")


def v02():
    """2군 독립 · 연속 · 정규 · **이분산** → Welch."""
    r = _rng(2)
    g = np.repeat(["a", "b"], N // 2)
    y = np.r_[r.normal(10, 1, N // 2), r.normal(11, 4, N // 2)]
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-01", "y": "y", "group": "grp"},
            {"T-101"}, "분산이 다르면 Student 가 아니라 Welch")


def v03():
    """2군 독립 · 연속 · **비정규(중꼬리)** → 순위·확률적 우위."""
    r = _rng(3)
    g = np.repeat(["a", "b"], N // 2)
    y = np.r_[r.standard_cauchy(N // 2), r.standard_cauchy(N // 2) + 1.5]
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-01", "y": "y", "group": "grp"},
            {"T-103", "T-104", "T-105"}, "중꼬리에 평균 기반은 못 쓴다")


def v04():
    """대응 2조건 · 연속 · 정규 → paired t."""
    r = _rng(4)
    n = N // 2
    base = r.normal(10, 2, n)
    return (pd.DataFrame({"sid": [f"S{i}" for i in range(n)] * 2,
                          "time": ["pre"] * n + ["post"] * n,
                          "y": np.r_[base, base + 0.6 + r.normal(0, 0.8, n)]}),
            {"time": "label", "y": "continuous", "sid": "id"},
            {"question": "Q-01", "y": "y", "group": "time", "paired": True},
            {"T-111"}, "같은 대상을 두 번 쟀으면 대응 검정")


def v05():
    """대응 2조건 · 연속 · **비정규** → Wilcoxon signed-rank."""
    r = _rng(5)
    n = N // 2
    base = r.exponential(3, n)
    return (pd.DataFrame({"sid": [f"S{i}" for i in range(n)] * 2,
                          "time": ["pre"] * n + ["post"] * n,
                          "y": np.r_[base, base * r.lognormal(0.3, 0.8, n)]}),
            {"time": "label", "y": "continuous", "sid": "id"},
            {"question": "Q-01", "y": "y", "group": "time", "paired": True},
            {"T-112", "T-113"}, "대응 + 비정규면 부호순위")


def v06():
    """3군 독립 · 연속 · 정규 → ANOVA."""
    r = _rng(6)
    g = np.repeat(["a", "b", "c"], N // 3)
    y = np.concatenate([r.normal(m, 2, N // 3) for m in (10, 10.6, 11.2)])
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-01", "y": "y", "group": "grp"},
            {"T-121", "T-122"}, "3군 이상 평균 비교")


def v07():
    """3군 독립 · 연속 · **비정규** → Kruskal–Wallis."""
    r = _rng(7)
    g = np.repeat(["a", "b", "c"], N // 3)
    y = np.concatenate([r.lognormal(m, 1.2, N // 3) for m in (0, 0.4, 0.8)])
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-01", "y": "y", "group": "grp"},
            {"T-123", "T-124"}, "3군 + 비정규면 순위 기반")


def v08():
    """반복측정 3조건 · 연속 → RM ANOVA / Friedman."""
    r = _rng(8)
    n = 60
    base = r.normal(10, 2, n)
    y = np.r_[base, base + 0.5 + r.normal(0, 0.6, n), base + 1.0 + r.normal(0, 0.6, n)]
    return (pd.DataFrame({"sid": [f"S{i}" for i in range(n)] * 3,
                          "time": ["t1"] * n + ["t2"] * n + ["t3"] * n, "y": y}),
            {"time": "label", "y": "continuous", "sid": "id"},
            {"question": "Q-01", "y": "y", "group": "time", "paired": True},
            {"T-131", "T-132", "T-133"}, "같은 대상을 세 번 쟀다")


def v09():
    """2×2 분할표 · 기대빈도 충분 → 카이제곱."""
    r = _rng(9)
    g = r.choice(["a", "b"], N)
    y = (r.random(N) < np.where(g == "a", 0.5, 0.3)).astype(int)
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "nominal code"},
            {"question": "Q-02", "y": "y", "group": "grp"},
            {"T-201", "T-203", "T-221"}, "칸이 충분하면 카이제곱")


def v10():
    """2×2 분할표 · **기대빈도 작음** → Fisher."""
    r = _rng(10)
    n = 24
    g = np.repeat(["a", "b"], n // 2)
    y = np.r_[(r.random(n // 2) < 0.15).astype(int),
              (r.random(n // 2) < 0.6).astype(int)]
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "nominal code"},
            {"question": "Q-02", "y": "y", "group": "grp"},
            {"T-202"}, "기대빈도가 5 미만이면 정확검정")


def v11():
    """대응 이진 (같은 대상 전·후) → McNemar."""
    r = _rng(11)
    n = 100
    pre = (r.random(n) < 0.4).astype(int)
    post = np.where(r.random(n) < 0.25, 1 - pre, pre)
    return (pd.DataFrame({"sid": [f"S{i}" for i in range(n)] * 2,
                          "time": ["pre"] * n + ["post"] * n,
                          "y": np.r_[pre, post]}),
            {"time": "label", "y": "nominal code", "sid": "id"},
            {"question": "Q-02", "y": "y", "group": "time", "paired": True},
            {"T-211", "T-212"}, "대응 이진은 McNemar")


def v12():
    """두 연속 · 선형 · 정규 → Pearson."""
    r = _rng(12)
    x = r.normal(0, 1, N)
    return (pd.DataFrame({"x": x, "y": 0.7 * x + r.normal(0, 0.7, N)}),
            {"x": "continuous", "y": "continuous"},
            {"question": "Q-03", "y": "y", "group": "x"},
            {"T-301"}, "정규·선형이면 Pearson")


def v13():
    """두 연속 · **단조 비선형** → Spearman."""
    r = _rng(13)
    x = r.uniform(0, 5, N)
    return (pd.DataFrame({"x": x, "y": np.exp(x) + r.normal(0, 3, N)}),
            {"x": "continuous", "y": "continuous"},
            {"question": "Q-03", "y": "y", "group": "x"},
            {"T-302", "T-303", "T-304", "T-305"}, "단조지만 비선형이면 순위 상관")


def v14():
    """생존 · 2군 · 비례위험 → 로그순위."""
    r = _rng(14)
    g = np.repeat(["a", "b"], N // 2)
    t = np.r_[r.exponential(60, N // 2), r.exponential(95, N // 2)]
    return (pd.DataFrame({"grp": g, "time": np.round(t, 1),
                          "event": (r.random(N) < 0.75).astype(int)}),
            {"grp": "label", "time": "continuous", "event": "probability"},
            {"question": "Q-09", "y": "time", "group": "grp", "event": "event"},
            {"T-901", "T-902", "T-903"}, "생존 곡선 비교")


def v15():
    """생존 · **공변량 조정 필요** → Cox."""
    r = _rng(15)
    g = np.repeat(["a", "b"], N // 2)
    age = r.normal(60, 10, N)
    t = r.exponential(np.where(g == "a", 60, 95) * (70 / age))
    return (pd.DataFrame({"grp": g, "age": age, "time": np.round(t, 1),
                          "event": (r.random(N) < 0.75).astype(int)}),
            {"grp": "label", "age": "continuous", "time": "continuous",
             "event": "probability"},
            {"question": "Q-09", "y": "time", "group": "grp", "event": "event",
             "covariates": ["age"]},
            {"T-807", "T-904"}, "공변량을 조정하려면 Cox")


def v16():
    """순서 있는 3군의 추세 → 경향 검정."""
    r = _rng(16)
    g = np.repeat(["low", "mid", "high"], N // 3)
    shift = {"low": 0.0, "mid": 0.7, "high": 1.4}
    y = np.array([r.normal(10 + shift[x], 2) for x in g])
    return (pd.DataFrame({"dose": g, "y": y}),
            {"dose": "ordinal code", "y": "continuous"},
            {"question": "Q-05", "y": "y", "group": "dose"},
            {"T-501", "T-504", "T-503"}, "순서가 있으면 추세를 본다")


def v17():
    """조성 자료 군 간 비교 → CLR 경로."""
    r = _rng(17)
    g = np.repeat(["a", "b"], N // 2)
    a = np.vstack([r.dirichlet([2, 3, 5], N // 2), r.dirichlet([3, 3, 4], N // 2)])
    return (pd.DataFrame({"grp": g, "f1": a[:, 0], "f2": a[:, 1], "f3": a[:, 2]}),
            {"grp": "label", "f1": "composition set", "f2": "composition set",
             "f3": "composition set"},
            {"question": "Q-10", "y": "f1", "group": "grp"},
            {"T-1001", "T-1002", "T-1003", "T-1004"}, "조성은 변환 후 검정")


def v18():
    """분포 **형태** 비교 (위치가 아니라) → KS 계열."""
    r = _rng(18)
    g = np.repeat(["a", "b"], N // 2)
    y = np.r_[r.normal(10, 2, N // 2), r.normal(10, 5, N // 2)]
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-07", "y": "y", "group": "grp"},
            {"T-701", "T-702", "T-703", "T-704"}, "위치가 아니라 형태를 묻는다")


def v19():
    """두 측정자의 일치도 (상관이 아니라) → ICC / Bland–Altman."""
    r = _rng(19)
    a = r.normal(50, 10, N)
    return (pd.DataFrame({"m1": a, "m2": a + r.normal(1.5, 3, N)}),
            {"m1": "continuous", "m2": "continuous"},
            {"question": "Q-06", "y": "m1", "group": "m2"},
            {"T-601", "T-602", "T-603"}, "일치도는 상관으로 재지 않는다")


def v20():
    """두 요인의 교호작용 → 이원 ANOVA."""
    r = _rng(20)
    a = np.tile(np.repeat(["a1", "a2"], N // 4), 2)
    b = np.repeat(["b1", "b2"], N // 2)
    y = (r.normal(10, 2, N) + (a == "a2") * 0.5 + (b == "b2") * 0.5
         + ((a == "a2") & (b == "b2")) * 1.5)
    return (pd.DataFrame({"fa": a, "fb": b, "y": y}),
            {"fa": "label", "fb": "label", "y": "continuous"},
            {"question": "Q-04", "y": "y", "group": "fa", "by": "fb"},
            {"T-401", "T-402", "T-403", "T-404"}, "두 요인이 함께 작용하나")


def v21():
    """사전지정 대비 (정상=교란≠암) → planned contrast."""
    r = _rng(21)
    g = np.repeat(["normal", "confound", "tumor"], N // 3)
    y = np.array([r.normal(10 + (x == "tumor") * 1.5, 2) for x in g])
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "continuous"},
            {"question": "Q-11", "y": "y", "group": "grp", "contrast": "planned"},
            {"T-1101", "T-1103", "T-1104", "T-1102"}, "패턴을 미리 정했으면 대비")


def v22():
    """카운트 결과 · 과산포 → 음이항 회귀."""
    r = _rng(22)
    g = np.repeat(["a", "b"], N // 2)
    lam = np.where(g == "a", 4, 7)
    y = r.negative_binomial(2, 2 / (2 + lam))
    return (pd.DataFrame({"grp": g, "y": y}),
            {"grp": "label", "y": "count"},
            {"question": "Q-08", "y": "y", "group": "grp"},
            {"T-803"}, "과산포 카운트는 Poisson 이 아니라 음이항")


ALL = {f"v{i:02d}": fn for i, fn in enumerate(
    [v01, v02, v03, v04, v05, v06, v07, v08, v09, v10, v11,
     v12, v13, v14, v15, v16, v17, v18, v19, v20, v21, v22], start=1)}
