"""STATOP 검증용 합성 데이터 생성 .

기본: 10,000행 × 2,000컬럼 (synth_long). --wide: 2,000행 × 10,000컬럼 (synth_wide).
의미 타입(S-T01~13)별 컬럼 블록 + 결측 + 정렬 편향 + 함정 케이스.
정렬 편향: site 컬럼 기준 정렬되어 파일 앞부분에 siteA만 몰려 있음 → 앞N행 샘플링 검증용.
seed 고정(0) — 동일 실행 = 동일 파일.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 0
OUT_DIR = Path(__file__).parent


def build(rng: np.random.Generator, n: int, n_cols: int) -> pd.DataFrame:
    cols: dict[str, np.ndarray] = {}

    # --- 구조 컬럼 ---
    cols["patient_id"] = np.array([f"PT{i:06d}" for i in range(n)])
    # 정렬 편향의 원천: site를 정렬된 상태로 둔다 (siteA가 파일 앞에 몰림)
    n_a = int(n * 0.3)
    n_b = int(n * 0.35)
    site = np.repeat(["siteA", "siteB", "siteC"], [n_a, n_b, n - n_a - n_b])
    cols["site"] = site
    cols["label"] = rng.choice([0, 1], n, p=[0.8, 0.2])
    cols["visit_date"] = pd.date_range("2024-01-01", periods=n, freq="h").astype(str).to_numpy()

    # --- 함정 케이스 (M1-1 노랑 검증용) ---
    cols["trap_binary_count"] = rng.choice([0, 1], n)                       # 0~1 정수 count ↔ 이진 코드
    cols["trap_int_percent"] = rng.integers(0, 101, n)                      # 정수로 저장된 percent ↔ count
    cols["trap_small_count"] = rng.choice([0.0, 1.0, 2.0], n)              # 소수로 저장된 count
    cols["trap_coded_ordinal"] = rng.choice([1, 2, 3, 4], n)               # 순서 있는데 코드처럼 보임

    # --- 조성 세트 (행 합 = 1, fraction) : 전체 컬럼의 10% (세트당 20성분) ---
    n_sets = max(1, n_cols // 200)
    for s in range(n_sets):
        raw = rng.gamma(2.0, 1.0, (n, 20))
        frac = raw / raw.sum(axis=1, keepdims=True)
        for j in range(20):
            cols[f"comp{s:02d}_frac{j:02d}"] = frac[:, j]

    # --- 나머지 블록: 비율 배분, 마지막 zscore 블록이 잔여분을 채워 총 n_cols 맞춤 ---
    remain = n_cols - len(cols)
    blocks = [
        ("cont", int(remain * 0.39), lambda k: rng.normal(50, 15, n) if k % 3 else rng.lognormal(2, 1, n)),  # 왜도 혼합
        ("count", int(remain * 0.22), lambda k: rng.poisson(5 + (k % 7), n).astype(float)),
        ("percent", int(remain * 0.11), lambda k: np.round(rng.beta(2, 5, n) * 100, 2)),
        ("prob", int(remain * 0.11), lambda k: rng.beta(2, 2, n)),
        ("ordinal", int(remain * 0.06), lambda k: rng.integers(0, 5, n).astype(float)),
        ("nominal", int(remain * 0.06), lambda k: rng.integers(0, 8, n).astype(float)),
    ]
    blocks.append(("zscore", remain - sum(b[1] for b in blocks), lambda k: rng.normal(0, 1, n)))
    assert len(cols) + sum(b[1] for b in blocks) == n_cols, "컬럼 수 불일치"

    t0 = time.time()
    done = 0
    total = sum(b[1] for b in blocks)
    print(f"블록 생성: {len(blocks)}종 {total}컬럼", flush=True)
    for name, cnt, gen in blocks:
        for k in range(cnt):
            cols[f"{name}{k:03d}"] = gen(k)
        done += cnt
        print(f"[{done}/{total}] done  {name}×{cnt}  {time.time()-t0:.1f}s", flush=True)

    df = pd.DataFrame(cols)

    # --- 결측 주입: 컬럼의 30%에 0~30% 다양하게, 일부는 site 의존(MNAR 흉내) ---
    miss_cols = rng.choice(np.arange(4, n_cols), size=int(n_cols * 0.3), replace=False)
    for i, ci in enumerate(miss_cols):
        col = df.columns[ci]
        rate = float(rng.choice([0.01, 0.05, 0.10, 0.30]))
        if i % 10 == 0:  # site 의존 결측
            mask = (df["site"] == "siteA") & (rng.random(n) < rate * 2)
        else:
            mask = rng.random(n) < rate
        df.loc[mask, col] = np.nan
    print(f"결측 주입: {len(miss_cols)}컬럼", flush=True)
    return df


def write_all(df: pd.DataFrame, stem: str) -> None:
    for fmt, writer in [
        ("csv", lambda p: df.to_csv(p, index=False)),
        ("tsv", lambda p: df.to_csv(p, sep="\t", index=False)),
        ("parquet", lambda p: df.to_parquet(p, index=False)),
    ]:
        path = OUT_DIR / f"{stem}.{fmt}"
        t0 = time.time()
        writer(path)
        mb = path.stat().st_size / 1e6
        print(f"[write] {path.name}  {mb:.1f}MB  {time.time()-t0:.1f}s", flush=True)


def main() -> None:
    wide = "--wide" in sys.argv[1:]
    n_rows, n_cols, stem = (2_000, 10_000, "synth_wide") if wide else (10_000, 2_000, "synth_long")
    print(f"계획: {n_rows:,}행 × {n_cols:,}컬럼 → csv/tsv/parquet 3형식 ({stem}), 출력 {OUT_DIR}", flush=True)
    rng = np.random.default_rng(SEED)
    df = build(rng, n_rows, n_cols)
    print(f"DataFrame: {df.shape[0]:,}행 × {df.shape[1]:,}컬럼, 메모리 {df.memory_usage(deep=True).sum()/1e6:.0f}MB", flush=True)
    write_all(df, stem)
    print("완료", flush=True)


if __name__ == "__main__":
    sys.exit(main())
