"""발표용 데이터 3종 (001·002·003) — `demo/Users_recomend.md` 의 세 상황 그대로.

검증 세트(`make_validation.py`)는 "기능이 걸리는가"를 보는 자료다. 이건 다르다 —
**이야기 하나를 끝까지 따라갈 수 있는가**를 보는 자료다. 그래서 심어 둔 것이
실제로 그 숫자로 나오는지 `verify_talk.py` 가 매번 확인한다.

| 파일 | 상황 | 보여줄 것 |
|---|---|---|
| 001_group_correlation | 군별 상관 · 작은 n | 라벨 매핑 → 군별 상관 → Q-12 표본 크기 → 지표 간 판단 차이 → guardrail |
| 002_entropy_wrong_dist | 분포를 잘못 본 엔트로피 | 희미한 차이 → 재료 컬럼으로 파생 → 분포에 맞는 공식 → 차이가 벌어짐 |
| 003a/003b_integrity | 무결성 — 이름도 척도도 다른 짝 | age ↔ age_group 짝 짓기 → 순위는 맞음 → tumor_frac 이 높은 age 에서 흔들림 |

사용법:  python demo/make_talk.py [출력디렉터리]  (기본 demo/talk/)
확인:    python demo/verify_talk.py   — 심어 둔 것이 실제로 그렇게 나오는지
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261001


# ── 001 군별 상관 · 작은 n ──────────────────────────────────
def build_group_correlation(rng) -> pd.DataFrame:  # noqa: ANN001
    """두 군에서 cfdna_conc ↔ immune_ratio 를 따로 봐야 하는 자료.

    심어 둔 것:
    - `group` 은 문자열(normal/cancer)이고 **아형이 둘씩** 있다 (eap2·eap3 / paad·lihc).
      라벨 매핑으로 0/1 로 묶어야 군이 둘이 된다
    - cancer 는 **n=27** — 아슬아슬하게 쓸 만한 크기다 (Q-12 에서 확인)
    - cancer 군의 관계는 **비단조(V 자)** 다 — 양 끝에서 높고 가운데가 낮다.
      순위만 보는 Spearman ρ 는 못 보고(p>0.4), **거리상관 dCor(T-304)** 은 본다(p<0.03).
      dCor 은 값의 거리를 그대로 쓰므로 순위 기반보다 **덜 버티는** 대신 이런 관계를
      잡아낸다 → dCor 을 Goal, Spearman 을 guardrail 로 두고
      "지금은 dCor 만 유의하다 — 표본을 더 모으면 ρ 도 달라질 수 있다"로 읽는다
    - normal 은 n 이 넉넉하고 관계가 없다
    - **섞어 보면 r=-0.28 로 "유의"해진다** — 두 군의 수준이 달라서 생기는 가짜 상관이다.
      군을 안 나누면 없는 관계를 본다 (라벨 매핑이 먼저인 이유)
    """
    n_norm, n_canc = 118, 27

    # normal — 관계 없음
    x_n = rng.lognormal(2.3, 0.45, n_norm)
    y_n = rng.beta(5, 9, n_norm)

    # cancer — **V 자**. 양 끝에서 높고 가운데가 낮다.
    # 순위만 보는 Spearman 은 이걸 못 본다(올랐다 내렸다 하므로 순위 일치가 0 에 가깝다).
    # 거리상관 dCor 은 "값이 가까우면 값도 가까운가"를 보므로 잡아낸다
    canc = np.random.default_rng(95)        # 이 모양이 나오는 난수 (verify_talk 가 잠근다)
    x_c = canc.lognormal(2.9, 0.40, n_canc)
    y_c = (0.13 + 0.0016 * np.abs(x_c - np.median(x_c))
           + canc.normal(0, 0.010, n_canc))

    g = ["normal"] * n_norm + ["cancer"] * n_canc
    sub = ([*rng.choice(["eap2", "eap3"], n_norm)]
           + [*rng.choice(["paad", "lihc"], n_canc)])
    return pd.DataFrame({
        "sample_id": [f"T1{i:03d}" for i in range(n_norm + n_canc)],
        "group": g,
        "subtype": sub,
        "cfdna_conc": np.round(np.concatenate([x_n, x_c]), 3),
        "immune_ratio": np.round(np.concatenate([y_n, y_c]), 4),
    })


# ── 002 분포를 잘못 본 엔트로피 ─────────────────────────────
def build_entropy(rng) -> pd.DataFrame:  # noqa: ANN001
    """`entropy` 로는 두 군이 겹치는데, **가정을 바꾸면** 갈리는 자료.

    조각 길이 분포를 **정규로 보면** 엔트로피는 폭(sd)만 쓴다 — `0.5·ln(2πe·sd²)`.
    **지수로 보면** 척도(평균)를 쓴다 — `1 + ln(mean)`.

    심어 둔 것:
    - 두 군의 **폭은 같다** (둘 다 sd≈25·개체차) → 정규 가정 엔트로피는 **겹친다**
    - 두 군의 **평균은 다르다** (50 vs 25) → 지수 가정 엔트로피는 **갈린다**
      모양이 다르기 때문이다: 정상은 감마(k=4), 암은 지수(k=1)에 가깝다
    - `entropy` 는 저장된 `frag_len_sd` 로 **정확히 되살릴 수 있다** — 잡음을 섞지
      않는다. 수식 예1 을 넣으면 같은 값이 나와야 "이 컬럼이 이 가정이었다"가 보인다
    - 즉 `1 + ln(frag_len_mean)` 하나를 만들면 같은 자료에서 차이가 벌어진다.
      "분포를 무엇으로 보았는가"가 결론을 바꾼다 (SC-ENT-05, 실제 있었던 사례)
    """
    n, m = 240, 400
    label = rng.integers(0, 2, n)
    # 개체차 — 척도가 사람마다 비율로 다르다. 그래서 평균은 로그정규로 치우친다
    bump = rng.lognormal(0, 0.35, n)
    shape = np.where(label == 1, 1.0, 4.0)          # 암은 지수에 가깝다
    scale = np.where(label == 1, 25.0, 12.5) * bump  # 평균 25·50, 폭은 둘 다 25
    mean_i, sd_i = [], []
    for k, s in zip(shape, scale):
        frag = rng.gamma(k, s, m)                   # 그 사람의 조각 길이들
        mean_i.append(frag.mean())
        sd_i.append(frag.std(ddof=1))
    frag_sd = np.round(np.array(sd_i), 3)
    frag_mean = np.round(np.array(mean_i), 3)
    # 정규 가정 엔트로피 — **저장된 sd 그대로** 계산한다 (예1 이 정확히 재현한다)
    ent_normal = 0.5 * np.log(2 * np.pi * np.e * frag_sd ** 2)
    return pd.DataFrame({
        "sample_id": [f"T2{i:03d}" for i in range(n)],
        "label": label,
        "entropy": np.round(ent_normal, 6),
        "frag_len_sd": frag_sd,
        "frag_len_mean": frag_mean,
        "depth": rng.poisson(1800, n),
    })


# ── 003 무결성 — 이름도 척도도 다른 짝 ──────────────────────
def build_integrity(rng) -> tuple[pd.DataFrame, pd.DataFrame]:  # noqa: ANN001
    """두 번 내보낸 같은 표 — 그런데 한쪽은 age 를 10살 단위로 묶어 두었다.

    심어 둔 것:
    - A 의 `age` ↔ B 의 `age_group` — 이름도 값도 다르다. **짝을 지어야** 대조에
      들어오고, 들어와도 "다름"으로 나온다. 다만 **순위는 거의 그대로**다
      (10살 묶음이라 순서가 보존된다) — 그래서 "깨졌지만 크게 깨지진 않았다"
    - `tumor_frac` 은 **미세하게** 다른데, **나이가 많을수록 흔들림이 커진다.**
      age 를 짝지어 놓지 않으면 그 추세를 볼 축이 없다
    """
    n = 300
    age = rng.integers(28, 86, n)
    base = 0.07 + 0.0009 * (age - 55) + rng.normal(0, 0.012, n)
    a = pd.DataFrame({
        "sample_id": [f"T3{i:03d}" for i in range(n)],
        "age": age,
        "sex": rng.choice(["F", "M"], n),
        "tumor_frac": np.round(np.clip(base, 0.001, None), 5),
        "depth": rng.poisson(2400, n),
    })
    b = a.copy()
    b["age_group"] = (b["age"] // 10 * 10).astype(int)
    b = b.drop(columns=["age"])
    # 흔들림이 나이와 함께 커진다 — 높은 age 에서만 눈에 띈다
    jitter = rng.normal(0, 1, n) * (0.00035 + 0.00022 * np.maximum(age - 60, 0))
    b["tumor_frac"] = np.round(np.clip(a["tumor_frac"] + jitter, 0.001, None), 5)
    return a, b[["sample_id", "age_group", "sex", "tumor_frac", "depth"]]


FILES = [("001_group_correlation", build_group_correlation),
         ("002_entropy_wrong_dist", build_entropy)]


def main() -> None:
    # 검증 세트(demo/data)와 **섞지 않는다** — 발표 때 셋만 보면 된다
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1
                   else Path(__file__).parent / "talk")
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(FILES) + 2
    print(f"발표용 데이터 {total}개 생성 → {out_dir}", flush=True)
    print(f"  seed {SEED} (결정론적)", flush=True)

    done = 0
    for name, fn in FILES:
        df = fn(np.random.default_rng(SEED + done))
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        done += 1
        print(f"[{done}/{total}] done  {path.name}  "
              f"{len(df):,}행 × {len(df.columns)}컬럼", flush=True)

    a, b = build_integrity(np.random.default_rng(SEED + 50))
    for name, df in (("003a_integrity_before", a), ("003b_integrity_after", b)):
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        done += 1
        print(f"[{done}/{total}] done  {path.name}  "
              f"{len(df):,}행 × {len(df.columns)}컬럼", flush=True)

    print(f"완료 — {total}개 파일", flush=True)


if __name__ == "__main__":
    main()
