"""검증용 최소 데이터셋 — 지금 구현된 기능이 **실제로 걸리는지** 확인하는 세트.

한 파일에 하나의 목적만 담는다. 그냥 통과하는 자료로는 검사가 도는지 알 수 없으므로
파일마다 **걸려야 할 것을 일부러 심어 둔다**. 무엇을 심었는지는 각 build_* 의 docstring에.

| 파일 | 목적 | 확인하는 기능 |
|---|---|---|
| 01_simulate_types | 의미 타입·함정 | M1-1 S-T 15종,  함정,  조성 감지 |
| 02_simulate_missing | 결측 현황·대치 | M0-6b ~,  |
| 03_simulate_correlation | 상관 전반 | S-R01/02/06/07, CLR·ALR·비례성(), VIF |
| 04_simulate_groupdiff | 군 비교·가정 위배 | Q-01/02, A3 정규성·등분산·소표본 |
| 05_simulate_repeated | 반복측정·그룹 구조 | M0-7 , 반복측정 검정, C-05 독립성 |
| 06_simulate_survival | 생존 | Q-09, Kaplan-Meier·Cox |
| 07_simulate_simpson | 심슨의 역설 |  층화 병기·반전 배너 |
| 08_simulate_guardrail | 가드레일 | GR-01 정의역, GR-02 SRM, GR-03 손실, GR-04 불균형 |
| 09_simulate_sortbias | 정렬 편향 | M0-1 앞/중/뒤 샘플러  |
| 10_simulate_labels | 라벨 매핑·팔레트 | , label_palette 앵커·충돌 |
| 11_simulate_model_source | 모듈 B 원본 | MB-C07 손실 대조의 기준 |
| 12_simulate_model_train | 모듈 B 학습 세트 | MB-C01/02/03/05, MB-C06 비율 |
| 13_simulate_model_test | 모듈 B 시험 세트 | 〃 (중복·그룹 교차·시간 겹침) |
| 14_simulate_model_external | 모듈 B 외부 세트 |  개발 vs 외부 분포 차이 |
| 15_simulate_model_predictions | 모듈 B 예측 |  평가 감사 — ROC/PR·보정·클래스별 성능 |
| 16_integrity_same | 무결성 — 같은 파일 | 01 과 **한 글자도 다르지 않은** 사본 (✅ 가 나와야 한다) |
| 17_integrity_changed | 무결성 — 달라진 파일 | 01 에서 행·값·컬럼을 일부러 건드린 사본 (⛔ 가 나와야 한다) |

사용법:  python demo/make_validation.py [출력디렉터리]
확인:    python demo/verify_validation.py  — 심어 둔 것이 실제로 걸리는지
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

N = 400          # 검증에 충분하고 git 에 넣어도 가벼운 크기
SEED = 20260916


def build_types(rng) -> pd.DataFrame:  # noqa: ANN001
    """의미 타입 15종 + 함정 3종.

    함정: trap_binary_count(0/1 정수 — count 인가 이진 코드인가) ·
    grade_code(정수 수준 — ordinal 인가 nominal 인가) · log2_ratio(음수 포함 — 원척도 아님).
    셋 다 conflicts 로 떠서 **확정을 요구**해야 한다 .
    """
    comp = rng.dirichlet([5, 3, 2], size=N)
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],                  # id
        "visit_date": pd.date_range("2024-01-01", periods=N, freq="D"),  # datetime
        "age_years": rng.normal(61, 11, N).round(1),                   # continuous
        "read_count": rng.poisson(4200, N),                            # count
        "trap_binary_count": rng.integers(0, 2, N),                    # 함정 ①
        "grade_code": rng.integers(0, 4, N),                           # 함정 ②
        "site_code": rng.integers(1, 6, N),                            # nominal code
        "prob_score": rng.beta(2, 5, N).round(4),                      # probability
        "pct_purity": (rng.beta(5, 2, N) * 100).round(1),              # percent
        "frac_a": comp[:, 0].round(4),                                 # 조성 세트 3성분
        "frac_b": comp[:, 1].round(4),
        "frac_c": comp[:, 2].round(4),
        "log2_ratio": rng.normal(0, 1.4, N).round(3),                  # 함정 ③ log-scale
        "zscore_expr": rng.normal(0, 1, N).round(3),                   # z-score
        "rank_pos": rng.permutation(N) + 1,                            # rank
        "odds_ratio": np.exp(rng.normal(0, 0.6, N)).round(3),          # ratio
        "tumor_type": rng.choice(["LUAD", "BRCA", "COAD"], N),         # label
    })


def build_missing(rng) -> pd.DataFrame:
    """결측 현황·패턴·대치.

    심은 것: ①panel_x/y/z 가 **함께 빈다**(같은 검사 묶음) ②sparse_col 45% 결측
    (30% 초과 → 제거 제안) ③zero_filled 는 0 이 과반인데 결측도 있다
    ("0으로 채워진 결측 의심"). arm 은 group_mean 대치용.
    """
    df = pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "arm": rng.choice(["control", "case"], N),
        "age_years": rng.normal(60, 10, N).round(1),
        "panel_x": rng.normal(10, 2, N).round(3),
        "panel_y": rng.normal(20, 4, N).round(3),
        "panel_z": rng.normal(30, 6, N).round(3),
        "sparse_col": rng.normal(0, 1, N).round(3),
        "zero_filled": np.where(rng.random(N) < 0.6, 0.0,
                                rng.gamma(2, 3, N).round(3)),
        "complete_col": rng.normal(5, 1, N).round(3),
    })
    panel_missing = rng.random(N) < 0.18          # 세 컬럼이 같은 행에서 함께 빈다
    df.loc[panel_missing, ["panel_x", "panel_y", "panel_z"]] = np.nan
    df.loc[rng.random(N) < 0.45, "sparse_col"] = np.nan
    df.loc[rng.random(N) < 0.12, "zero_filled"] = np.nan
    df.loc[rng.random(N) < 0.05, "age_years"] = np.nan
    return df


def build_correlation(rng) -> pd.DataFrame:
    """상관 전반 — 조성·척도 혼재·다중공선성·순위.

    심은 것: ①comp_a~d 4성분 조성(합=1) → **인위적인 상관(Closure effect)**,
    CLR/ALR 로 답이 갈린다 () ②pct_scale 만 0~100 (척도 혼재, S-R07)
    ③vif_x3 = x1+x2+잡음 (다중공선성) ④monotone 쌍은 단조이지만 비선형
    (Pearson 과 Spearman 이 갈린다) ⑤indep 쌍은 무관 (거짓양성 확인용).
    """
    comp = rng.dirichlet([6, 4, 3, 2], size=N)
    x1, x2 = rng.normal(0, 1, N), rng.normal(0, 1, N)
    lin_x = rng.normal(0, 1, N)
    mono_x = rng.uniform(0.1, 4, N)
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "comp_a": comp[:, 0].round(4), "comp_b": comp[:, 1].round(4),
        "comp_c": comp[:, 2].round(4), "comp_d": comp[:, 3].round(4),
        "pct_scale": (comp[:, 0] * 100).round(2),          # 같은 값의 0~100 판
        "linear_x": lin_x.round(3),
        "linear_y": (0.85 * lin_x + rng.normal(0, 0.5, N)).round(3),
        "monotone_x": mono_x.round(3),
        "monotone_y": np.exp(mono_x + rng.normal(0, 0.15, N)).round(3),
        "vif_x1": x1.round(3), "vif_x2": x2.round(3),
        "vif_x3": (x1 + x2 + rng.normal(0, 0.05, N)).round(3),
        "indep_a": rng.normal(0, 1, N).round(3),
        "indep_b": rng.normal(0, 1, N).round(3),
    })


def build_groupdiff(rng) -> pd.DataFrame:
    """군 비교와 가정 위배 — 어느 가정이 왜 깨졌는지 분기가 보여야 한다 ().

    심은 것: ①y_normal 은 군 차이가 뚜렷(정상 경로) ②y_skewed 는 로그정규(왜도)
    ③y_outlier 는 정규지만 극단값 4개(Outlier 소수) ④y_hetero 는 군마다 분산이 다름
    (등분산 위반) ⑤arm3 의 C 군은 n=8 (소표본·검정력) ⑥binary_out 은 2×2 표.
    """
    arm = rng.choice(["control", "case"], N)
    shift = np.where(arm == "case", 0.8, 0.0)
    y_outlier = rng.normal(0, 1, N) + shift
    y_outlier[:4] = [9.5, -8.7, 10.2, -9.1]        # 극단값 소수
    # C 군만 아주 작게 — 소표본 경고와 검정력 경로
    arm3 = np.where(np.arange(N) < 8, "C",
                    rng.choice(["A", "B"], N))
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "arm": arm, "arm3": arm3,
        "y_normal": (rng.normal(0, 1, N) + shift).round(3),
        "y_skewed": np.exp(rng.normal(0, 1, N) + shift).round(3),
        "y_outlier": y_outlier.round(3),
        "y_hetero": (rng.normal(0, 1, N)
                     * np.where(arm == "case", 3.5, 1.0) + shift).round(3),
        "binary_out": (rng.random(N) < np.where(arm == "case", 0.45, 0.2)).astype(int),
        "age_years": rng.normal(60, 10, N).round(1),
    })


def build_repeated(rng) -> pd.DataFrame:
    """반복측정 — 같은 대상을 3회 잰다. 독립 가정(C-05)이 깨지는 자료.

    subject_id 당 3행이므로 **값 구조만으로 그룹 구조가 감지**돼야 한다 .
    회차 순서는 값에서 읽는다 (T1<T2<T3, ).
    """
    n_subj = 120
    subj = np.repeat([f"P{i:04d}" for i in range(n_subj)], 3)
    arm = np.repeat(rng.choice(["control", "case"], n_subj), 3)
    offset = np.repeat(rng.normal(0, 2.0, n_subj), 3)       # 개인차 (랜덤 절편)
    visit = np.tile(["T1", "T2", "T3"], n_subj)
    time_eff = np.tile([0.0, 0.6, 1.3], n_subj)
    arm_eff = np.where(arm == "case", 0.9, 0.0)
    return pd.DataFrame({
        "subject_id": subj, "visit": visit, "arm": arm,
        "value": (offset + time_eff + arm_eff
                  + rng.normal(0, 0.7, n_subj * 3)).round(3),
        "age_years": np.repeat(rng.normal(60, 10, n_subj), 3).round(1),
    })


def build_survival(rng) -> pd.DataFrame:
    """생존 — 군마다 위험이 다르고 중도절단이 섞여 있다 (Q-09)."""
    arm = rng.choice(["control", "case"], N)
    scale = np.where(arm == "case", 380.0, 700.0)          # case 가 더 빨리 사건
    true_time = rng.exponential(scale)
    censor_at = rng.uniform(200, 1100, N)
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "arm": arm,
        "time_days": np.minimum(true_time, censor_at).round(1),
        "event": (true_time <= censor_at).astype(int),     # 1=사건, 0=중도절단
        "age_years": rng.normal(63, 9, N).round(1),
        "stage": rng.choice(["I", "II", "III"], N),
    })


def build_simpson(rng) -> pd.DataFrame:
    """심슨의 역설 — 층마다는 case 가 낫고, 합치면 반대로 보인다 .

    층별 배정이 치우쳐 있어서 생긴다: S1 에는 control 이, S2 에는 case 가 몰려 있고
    두 층의 기저 성공률 자체가 크게 다르다.
    """
    rows = []
    # (층, 군, n, 성공률) — 층 안에서는 언제나 case 가 높다
    for stratum, arm, n, p in [("S1", "control", 180, 0.80), ("S1", "case", 20, 0.90),
                               ("S2", "control", 20, 0.20), ("S2", "case", 180, 0.30)]:
        rows.append(pd.DataFrame({
            "stratum": stratum, "arm": arm,
            "outcome": (rng.random(n) < p).astype(int),
            "age_years": rng.normal(60, 10, n).round(1)}))
    df = pd.concat(rows, ignore_index=True)
    df.insert(0, "sample_id", [f"S{i:04d}" for i in range(len(df))])
    return df


def build_guardrail(rng) -> pd.DataFrame:
    """가드레일 4종이 모두 걸리는 자료.

    심은 것: ①prob_bad 에 1.4·-0.2, count_bad 에 음수, pct_bad 에 150 → GR-01 **차단**
    ②arm 이 3:1 (기대 1:1 이면 SRM) → GR-02 ③qc 가 case 쪽에서 낮다 — 필터를 걸면
    손실이 군에 치우친다 → GR-03 ④tiny_arm 의 한 수준이 n=3, site 가 arm 에 편중 → GR-04.
    """
    arm = np.where(rng.random(N) < 0.75, "control", "case")      # 3:1
    prob_bad = rng.beta(2, 6, N)
    prob_bad[:2] = [1.4, -0.2]
    count_bad = rng.poisson(30, N).astype(float)
    count_bad[2:4] = [-5.0, -1.0]
    pct_bad = rng.uniform(0, 100, N)
    pct_bad[4] = 150.0
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "arm": arm,
        "tiny_arm": np.where(np.arange(N) < 3, "rare",
                             rng.choice(["big", "mid"], N)),
        # site 가 arm 에 편중 — 라벨은 3:1 인데 메타는 더 치우쳐 있다 (SMD)
        "site": np.where(arm == "case",
                         rng.choice(["A", "B"], N, p=[0.15, 0.85]),
                         rng.choice(["A", "B"], N, p=[0.85, 0.15])),
        "prob_bad": prob_bad.round(4),
        "count_bad": count_bad,
        "pct_bad": pct_bad.round(1),
        # case 쪽 QC 가 낮다 — qc>0.5 필터를 걸면 편향적 손실이 된다
        "qc": np.where(arm == "case", rng.random(N) * 0.55, rng.random(N)).round(3),
        "value": rng.normal(0, 1, N).round(3),
    })


def build_sortbias(rng) -> pd.DataFrame:
    """정렬 편향 — 앞 1/3 이 전부 한 군이다.

    앞 N행만 읽으면 군 비율이 100:0 으로 보이고, 앞/중/뒤 구간 샘플링이면
    실제 비율에 가깝게 보인다. **두 방식의 차이가 눈에 보여야** 샘플러를 믿을 수 있다.
    """
    third = N // 3
    arm = np.array(["control"] * third + list(rng.choice(["control", "case"],
                                                        N - third)))
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "arm": arm,
        "batch": ["B1"] * third + ["B2"] * third + ["B3"] * (N - 2 * third),
        "value": (rng.normal(0, 1, N)
                  + np.where(arm == "case", 0.7, 0.0)).round(3),
    })


def build_labels(rng) -> pd.DataFrame:
    """라벨 매핑·팔레트 — 표시 문자열과 계산 코드를 가르는 자료 ().

    심은 것: ①TCGA 코드(LUAD·BRCA)와 자유 문자열("lung adenocarcinoma")이 섞여 있다
    ②`germ-cell` 은 팔레트에서 **키워드 충돌**로 등록된 값(testis / germ_cell) —
    모호 표시가 떠야 한다 ③normal 은 TCGA 코드가 없는 카테고리 ④수준별 n 이 고르지 않다.
    """
    values = (["LUAD"] * 90 + ["BRCA"] * 70 + ["lung adenocarcinoma"] * 40
              + ["breast carcinoma"] * 30 + ["germ-cell"] * 25 + ["normal"] * 60
              + ["COAD"] * 50 + ["unknown_x"] * 35)
    values = values[:N] + list(rng.choice(values, max(0, N - len(values))))
    return pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(N)],
        "tumor_type": values[:N],
        "outcome": rng.integers(0, 2, N),
        "value": rng.normal(0, 1, N).round(3),
    })


def build_model_sets(rng) -> dict[str, pd.DataFrame]:
    """모듈 B — 원본 1벌 + 세트 3벌. 감사 항목이 **전부 하나씩** 걸리게 짠다.

    심은 것:
      MB-C01 중복       train 의 앞 15행을 test 에 그대로 넣는다
      MB-C02 그룹 교차  patient_id 1명당 2샘플이라 나누면 양쪽에 걸친다
      MB-C03 시간 누수  test 의 시작일이 train 의 끝보다 앞이다
      MB-C05 대리변수   proxy_feature 가 라벨을 거의 그대로 담는다
      MB-C06 비율       계획 8:2 인데 실제 500:300 으로 나눈다
      MB-C07 손실       label==1 행 대부분이 어느 세트에도 안 들어간다
      MB-C08 불균형     label 이 약 12% 만 1 · site 가 라벨을 예측한다
        분포 차이   external 만 age_years 가 12 높다
      MB-C28 완전분리   proxy_feature 가 라벨을 완전히 가른다 (MB-C05 와 같은 통로)
      MB-C29/C31        marker_z = marker_y×2 + 잡음 (VIF 폭발 · 중요도가 갈라 실린다)
    """
    n = 1000
    label = (rng.random(n) < 0.12).astype(int)
    src = pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(n)],
        "patient_id": [f"P{i // 2:04d}" for i in range(n)],   # 1명당 2샘플
        "enroll_date": pd.date_range("2023-01-01", periods=n, freq="D"),
        "age_years": rng.normal(60, 8, n).round(1),
        "marker_x": rng.normal(0, 1, n).round(3),
        "marker_y": rng.normal(5, 2, n).round(3),
        "proxy_feature": (label * 10 + rng.normal(0, 0.01, n)).round(4),
        "site": np.where(label == 1, "B",
                         np.where(rng.random(n) < 0.9, "A", "B")),
        "label": label,
    })
    # 겹치는 변수 한 쌍 — VIF 가 폭발하고 중요도가 둘로 갈려 실린다 (MB-C29·C31)
    src["marker_z"] = (src["marker_y"] * 2 + rng.normal(0, 0.05, n)).round(3)

    # 손실 — label==1 의 절반 넘게를 어느 세트에도 넣지 않는다 (결측정리로 빠진 셈).
    # 라벨 분포가 12% → 5% 로 움직여 MB-C07 이 잡는다
    keep = pd.concat([src[src.label == 0], src[src.label == 1].iloc[:45]])
    keep = keep.sample(frac=1, random_state=1).reset_index(drop=True)

    # 층화해서 나눈다 — 세트마다 양성이 있어야 그 세트에서 성능을 잴 수 있다.
    # (여기서 층화하지 않으면 external 에 양성이 0개가 되어 MB-C13 이 그것부터 짚는다)
    pos = keep[keep.label == 1].reset_index(drop=True)
    neg = keep[keep.label == 0].reset_index(drop=True)
    cuts = [(0.0, 0.55), (0.55, 0.89), (0.89, 1.0)]        # train · test · external
    train, test, ext = (
        pd.concat([pos.iloc[int(a * len(pos)):int(b * len(pos))],
                   neg.iloc[int(a * len(neg)):int(b * len(neg))]])
          .sample(frac=1, random_state=2).reset_index(drop=True)
        for a, b in cuts)

    test = pd.concat([test, train.iloc[:15]], ignore_index=True)   # MB-C01 중복
    # MB-C03 — test 가 train 보다 과거에서 시작하도록 날짜만 당긴다
    test["enroll_date"] = pd.date_range("2022-06-01", periods=len(test), freq="D")
    ext["age_years"] = (ext["age_years"] + 12).round(1)            #  분포 차이

    # 예측이 담긴 세트 ( 평가 감사) — 순위는 꽤 맞지만 **확률값이 과신**이고,
    # 0.5 임계에서는 양성을 거의 못 잡는다 (불균형에서 흔한 모습)
    pred = test.copy()
    signal = rng.normal(0, 1, len(pred)) + pred["label"].to_numpy() * 1.6
    raw = 1 / (1 + np.exp(-signal))
    pred["pred_prob"] = np.clip(raw ** 2.2 * 0.45, 0, 1).round(4)   # 과신 쪽으로 눌림
    return {"source": src, "train": train, "test": test, "external": ext,
            "pred": pred}


def build_integrity_same(types: pd.DataFrame) -> pd.DataFrame:
    """01 을 그대로 복사한 것 — 대조하면 **같다**가 나와야 한다.

    "다른 것을 찾아낸다"만 확인하면 반쪽이다. 같은 파일을 다르다고 하지 않는 것도
    같이 봐야 검사를 믿을 수 있다.
    """
    return types.copy()


def build_integrity_changed(types: pd.DataFrame) -> pd.DataFrame:
    """01 에서 **일부러** 건드린 사본 — 무엇을 건드렸는지 여기 적어 둔다.

    ① 행 3개 삭제 (S0010·S0011·S0012) — 원본에만 있는 행
    ② 행 2개 추가 (S9001·S9002)       — 사본에만 있는 행
    ③ 값 4개 변경 — pct_purity 2건 · prob_score 1건 · tumor_type 1건
    ④ 컬럼 1개 삭제 (odds_ratio)      — 다시 내보내며 빠진 컬럼

    대조 키는 sample_id 다. 키 없이 맞추면 ①② 때문에 줄이 밀려 **전부 다르다**로
    보인다 — 그것도 한 번 해보면 키가 왜 필요한지 바로 보인다.
    """
    df = types.copy()
    df = df[~df["sample_id"].isin(["S0010", "S0011", "S0012"])]

    extra = types.iloc[:2].copy()
    extra["sample_id"] = ["S9001", "S9002"]
    df = pd.concat([df, extra], ignore_index=True)

    at = {sid: df.index[df["sample_id"] == sid][0]
          for sid in ("S0100", "S0101", "S0200", "S0300")}
    df.loc[at["S0100"], "pct_purity"] = round(float(df.loc[at["S0100"], "pct_purity"]) + 7.3, 1)
    df.loc[at["S0101"], "pct_purity"] = 0.0
    df.loc[at["S0200"], "prob_score"] = 0.9999
    df.loc[at["S0300"], "tumor_type"] = "UNKNOWN"
    return df.drop(columns=["odds_ratio"])


FILES = [
    ("01_simulate_types", build_types),
    ("02_simulate_missing", build_missing),
    ("03_simulate_correlation", build_correlation),
    ("04_simulate_groupdiff", build_groupdiff),
    ("05_simulate_repeated", build_repeated),
    ("06_simulate_survival", build_survival),
    ("07_simulate_simpson", build_simpson),
    ("08_simulate_guardrail", build_guardrail),
    ("09_simulate_sortbias", build_sortbias),
    ("10_simulate_labels", build_labels),
]
MODEL_FILES = [("11_simulate_model_source", "source"),
               ("12_simulate_model_train", "train"),
               ("13_simulate_model_test", "test"),
               ("14_simulate_model_external", "external"),
               ("15_simulate_model_predictions", "pred")]


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1
                   else Path(__file__).parent / "data")
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(FILES) + len(MODEL_FILES) + 2   # +2 = 무결성 대조 한 쌍
    print(f"검증 데이터 {total}개 생성 → {out_dir}", flush=True)
    print(f"  기본 행 수 {N} · seed {SEED} (결정론적)", flush=True)

    done = 0
    types = None
    for name, fn in FILES:
        df = fn(np.random.default_rng(SEED + done))
        if name.startswith("01_"):
            types = df                      # 무결성 파일 둘은 이것에서 나온다
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        done += 1
        print(f"[{done}/{total}] done  {path.name}  "
              f"{len(df):,}행 × {len(df.columns)}컬럼  "
              f"{path.stat().st_size / 1024:.0f}KB", flush=True)

    sets = build_model_sets(np.random.default_rng(SEED + 100))
    for name, key in MODEL_FILES:
        df = sets[key]
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        done += 1
        print(f"[{done}/{total}] done  {path.name}  "
              f"{len(df):,}행 × {len(df.columns)}컬럼  "
              f"{path.stat().st_size / 1024:.0f}KB", flush=True)

    for name, fn in (("16_integrity_same", build_integrity_same),
                     ("17_integrity_changed", build_integrity_changed)):
        df = fn(types)
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        done += 1
        print(f"[{done}/{total}] done  {path.name}  "
              f"{len(df):,}행 × {len(df.columns)}컬럼  "
              f"{path.stat().st_size / 1024:.0f}KB", flush=True)

    print(f"완료 — {total}개 파일", flush=True)


if __name__ == "__main__":
    main()
