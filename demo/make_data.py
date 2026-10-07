"""데모용 임시 데이터 생성 — 실제로 걸리는 것이 나오도록 함정을 심어 둔다.

심어 둔 것:
  조성 3성분 (frac_A/B/C)      → S-R01·S-R02, CLR 수정 경로
  척도 혼재 (pct_purity 0~100) → S-R07, ÷100 수정 경로
  이름뿐인 코드 (site_code)     → S-R09 차단
  식별자 (patient_id)          → S-R10 차단
  총합이 다른 count 두 개       → S-R03
  정의역 밖 값 (vaf에 2개)      → GR-01 차단
  QC가 case 쪽에서 더 낮음      → 필터를 걸면 GR-03 편향 손실 → GR-02 SRM

사용법:  python demo/make_data.py [출력경로]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def build(seed: int = 9, n: int = 1200) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    comp = rng.dirichlet([4, 3, 2], size=n)
    arm = rng.choice(["control", "case"], n)
    # case 쪽 QC가 낮다 — 나중에 QC 필터를 걸면 손실이 군에 치우친다
    qc = np.where(arm == "case", rng.random(n) * 0.55, rng.random(n))

    vaf = np.clip(rng.beta(2, 8, n), 0, 1)
    vaf[:2] = [1.4, -0.2]          # 정의역 밖 — GR-01이 차단으로 잡아야 한다

    return pd.DataFrame({
        "patient_id": [f"PT{i:05d}" for i in range(n)],
        "arm": arm,
        "site_code": rng.integers(0, 4, n),
        "diagnosis": rng.choice(["control", "hcc", "liver"], n, p=[.5, .3, .2]),
        "frac_A": comp[:, 0].round(6),
        "frac_B": comp[:, 1].round(6),
        "frac_C": comp[:, 2].round(6),
        "reads_x": rng.poisson(1.0e5, n),
        "reads_y": rng.poisson(9.0e5, n),      # 총합이 9배 — S-R03
        "pct_purity": rng.uniform(10, 99, n).round(1),
        "vaf": vaf.round(4),
        "qc_score": qc.round(3),
        "age": np.where(rng.random(n) < 0.09, np.nan,
                        rng.normal(60, 12, n).round(1)),   # 결측 9%
    })


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo/data/demo.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df = build()
    df.to_csv(out, index=False)
    print(f"{len(df):,}행 × {df.shape[1]}컬럼 → {out.resolve()}", flush=True)
