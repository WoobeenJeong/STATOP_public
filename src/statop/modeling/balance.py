"""B4 균형·혼란 진단  — MB-C08 · MB-C12 · 세트 간 분포 차이.

누수가 없고 비율도 계획대로여도, 모델이 **엉뚱한 것을 학습**하고 있을 수 있다.
여기서 보는 세 가지가 그 통로다:

- MB-C08 클래스 비율 — 한쪽이 드물면 정확도만으로는 아무것도 알 수 없다
- MB-C08 지름길 학습 — 메타의 분포가 라벨 간에 다르면 모델이 라벨 대신 그쪽을 학습한다
- 세트 간 분포 차이 — 개발 세트와 외부 세트의 피처 분포가 다르면 외부에서 성능이 떨어진다

**판정 로직은 새로 쓰지 않는다.** 전부 M4 가드레일 GR-04 를 부른다 ( 과 같은 방식):
클래스 비율은 `group_balance`, 지름길 학습과 분포 차이는 `smd_imbalance`.
임계도 `statop guard limits` 의 것이라 조정한 값이 그대로 걸린다.

**감사 전용이다.** 학습을 돌리지 않고 세트 파일과 설정만 본다.
"""

import pandas as pd

from statop.guard import checks, locks
from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, load_set, skip
from statop.modeling.split_audit import DEV_ROLES, _class_line, _from_signal

# 가중·샘플링을 했다고 볼 수 있는 값. 이 밖은 "기록되지 않음"으로 본다 —
# 도구는 학습 코드를 읽지 않으므로 **했는지 안 했는지가 아니라 적혀 있는지**를 본다
WEIGHTED = {"balanced", "balanced_subsample", "oversample", "undersample", "smote"}


def _by_size(sigs: list) -> list:
    """SMD 큰 순으로 — 임계만 넘으면 다 같아 보이지만 크기는 수십 배 차이가 난다."""
    return sorted(sigs, key=lambda s: -s.numbers.get("smd", 0.0))


def _smd_row(key: str, sig) -> str:  # noqa: ANN001
    """SMD 한 줄 — **표본 크기만으로 생기는 수준**을 넘었는지 함께 표시한다.

    임계(0.10)는 규칙 DB 의 것이라 바꾸지 않는다. 대신 n 이 작으면 우연만으로도
    그 값이 나온다는 사실을 옆에 적어 사용자가 크기를 스스로 읽게 한다 ( 와 같은 처리).
    """
    smd = sig.numbers.get("smd", float("nan"))
    chance = sig.numbers.get("chance_level", float("nan"))
    note = msg("mb_smd_at_chance") if smd <= chance else ""
    return msg(key, col=sig.columns[0], smd=smd, chance=chance, note=note)


def _label_frame(spec, sample_n: int, extra: list[str] | None = None):  # noqa: ANN001
    """라벨(+메타)만 읽어 세트별로 돌려준다 — 피처 전체를 읽을 일이 아니다."""
    cols = [c for c in [spec.label_column, *(extra or [])] if c]
    out = {}
    for role, path in spec.sets.items():
        df = load_set(path)
        keep = [c for c in cols if c in df.columns]
        out[role] = df[keep].head(sample_n) if keep else df.head(0)
    return out


# ── MB-C08 클래스 비율 ──────────────────────────────────────
def class_balance(spec, sample_n: int = 50_000,  # noqa: ANN001
                  lock_path=None) -> list[LeakFinding]:  # noqa: ANN001
    """어느 클래스가 얼마나 드문가 — 드물면 정확도가 아무것도 말해주지 않는다."""
    col = spec.label_column
    if not col:
        return [skip("MB-C08", msg("mb_need_label"))]
    frames = _label_frame(spec, sample_n)
    dev = [f for r, f in frames.items() if r in DEV_ROLES and col in f.columns]
    if not dev:
        return [skip("MB-C08", msg("mb_c08_no_dev"))]

    df = pd.concat(dev, ignore_index=True)
    counts = {str(k): int(v) for k, v in df[col].value_counts().items()}
    if len(counts) < 2:
        return [skip("MB-C08", msg("mb_c06_one_class"))]

    g4 = {k: v.value for k, v in locks.limits("GR-04", lock_path).items()}
    detail = [msg("mb_c08_dev_row", body=_class_line(counts))]
    detail += [msg("mb_c08_set_row", role=r, body=_class_line(
        {str(k): int(v) for k, v in f[col].value_counts().items()}))
        for r, f in frames.items() if col in f.columns and len(f)]

    sigs = checks.group_balance(df, col, g4["min_group_n"], g4["severe_group_n"],
                                g4["imbalance_ratio"])
    lo, hi = min(counts.values()), max(counts.values())
    ratio = hi / lo if lo else float("inf")
    minority = min(counts, key=counts.get)
    numbers = {"counts": counts, "ratio": ratio, "minority": minority,
               "n_minority": lo}

    out = []
    if sigs:
        out.append(LeakFinding(
            id="MB-C08", grade=grade_of("MB-C08"), verdict="fail",
            summary=msg("mb_c08_imbalanced", minority=minority, n=lo, ratio=ratio),
            detail=[*detail, msg("mb_c08_why"), msg("mb_c08_metrics")],
            numbers=numbers,
            action=msg("mb_c08_action")))
    else:
        out.append(LeakFinding(id="MB-C08", grade=grade_of("MB-C08"), verdict="pass",
                               summary=msg("mb_c08_pass", ratio=ratio),
                               detail=detail, numbers=numbers))

    # MB-C12 — 치우쳤는데 가중·샘플링이 기록되지 않았는가.
    # **했는지 안 했는지**가 아니라 **적혀 있는지**를 본다 (학습 코드를 읽지 않는다)
    if not sigs:
        out.append(skip("MB-C12", msg("mb_c12_balanced")))
    elif (spec.class_weight or "").lower() in WEIGHTED:
        out.append(LeakFinding(id="MB-C12", grade=grade_of("MB-C12"), verdict="pass",
                               summary=msg("mb_c12_pass", how=spec.class_weight),
                               numbers={"class_weight": spec.class_weight}))
    else:
        out.append(LeakFinding(
            id="MB-C12", grade=grade_of("MB-C12"), verdict="fail",
            summary=msg("mb_c12_missing", ratio=ratio),
            detail=[msg("mb_c12_how", allowed=", ".join(sorted(WEIGHTED)))],
            numbers={"class_weight": spec.class_weight, "ratio": ratio},
            action=msg("mb_c12_action")))
    return out


# ── MB-C08 지름길 학습 위험 (메타 → 라벨) ──────────────────
def hidden_imbalance(spec, meta_cols: list[str] | None = None,  # noqa: ANN001
                     sample_n: int = 50_000, lock_path=None) -> LeakFinding:  # noqa: ANN001
    """기관·배치·나이 같은 메타의 분포가 라벨 간에 다른가 — **지름길 학습** 위험.

    모델이 라벨이 아니라 그 특성을 학습하면 다른 기관·배치 자료에서 무너진다.
    여기서 말하는 것은 **관찰한 연관**까지다 — 인과(교란)를 주장하지 않는다.
    2군일 때만 본다 (3군 이상의 SMD 는 정의가 갈린다).
    """
    col = spec.label_column
    if not col:
        return skip("MB-C08", msg("mb_need_label"))
    if not meta_cols:
        return skip("MB-C08", msg("mb_c08_no_meta"))

    frames = _label_frame(spec, sample_n, meta_cols)
    dev = [f for r, f in frames.items() if r in DEV_ROLES and col in f.columns]
    if not dev:
        return skip("MB-C08", msg("mb_c08_no_dev"))
    df = pd.concat(dev, ignore_index=True)
    have = [c for c in meta_cols if c in df.columns]
    if not have:
        return skip("MB-C08", msg("select_err_missing", cols=", ".join(meta_cols)))
    if df[col].dropna().nunique() != 2:
        # 못 보는 것을 통과라고 하지 않는다 ( 원칙)
        return skip("MB-C08", msg("mb_c08_multiclass",
                                  n=int(df[col].dropna().nunique())))

    thr = locks.limits("GR-04", lock_path)["smd_threshold"].value
    hits = _by_size(checks.smd_imbalance(df, col, have, thr))
    if not hits:
        return LeakFinding(id="MB-C08", grade=grade_of("MB-C08"), verdict="pass",
                           summary=msg("mb_c08_meta_pass", cols=", ".join(have)))
    return LeakFinding(
        id="MB-C08", grade=grade_of("MB-C08"), verdict="fail",
        summary=msg("mb_c08_meta", cols=", ".join(s.columns[0] for s in hits),
                    limit=thr),
        detail=[_smd_row("mb_c08_meta_row", s) for s in hits]
        + [msg("mb_c08_meta_why")],
        numbers={s.columns[0]: s.numbers for s in hits},
        action=msg("mb_c08_meta_action"))


# ──  세트 간 분포 차이 (개발 vs 외부) ───────────────────
def set_shift(spec, sample_n: int = 50_000, lock_path=None) -> LeakFinding:  # noqa: ANN001
    """개발 세트와 외부 세트의 피처 분포가 다른가 (요구사항, P1).

    다르면 외부에서 성능이 떨어져도 **모델 탓인지 자료 탓인지** 가릴 수 없다.
    두 덩이를 한 표로 합치고 '어느 쪽에서 왔는가'를 군으로 삼아 GR-04 의 SMD 를 그대로 쓴다.
    """
    dev_roles = [r for r in spec.sets if r in DEV_ROLES]
    ext_roles = [r for r in spec.sets if r not in DEV_ROLES]
    if not dev_roles or not ext_roles:
        return skip("MB-C08", msg("mb_shift_no_ext"))

    drop = {spec.label_column, spec.group_column, spec.time_column, spec.score_column}
    parts, mark = [], []
    for side, roles in (("dev", dev_roles), ("ext", ext_roles)):
        for r in roles:
            df = load_set(spec.sets[r]).head(sample_n)
            parts.append(df)
            mark += [side] * len(df)
    shared = [c for c in parts[0].columns
              if c not in drop and all(c in p.columns for p in parts)]
    if not shared:
        return skip("MB-C08", msg("mb_leak_no_shared_cols"))

    df = pd.concat(parts, ignore_index=True)
    # 식별자는 피처가 아니다. sid 는 세트마다 다른 값이니 당연히 "분포가 다르다"고
    # 나오는데, 그건 자료의 문제가 아니라 그 컬럼이 피처가 아니라는 뜻이다.
    # 고유값 비율( 의 ID_UNIQUE_RATIO)만으로 가르면 **연속형 피처가 전부 걸린다** —
    # 나이·발현량은 원래 고유값이 거의 전부다. 그래서 수치형은 빼지 않는다.
    # 수치로 된 id(1..n)는 이 규칙으로 못 거른다 — 그건 hold로 빼는 것이 맞다
    from statop.groups import ID_UNIQUE_RATIO

    ids = [c for c in shared
           if not pd.api.types.is_numeric_dtype(df[c]) and len(df)
           and df[c].nunique(dropna=True) / len(df) >= ID_UNIQUE_RATIO]
    shared = [c for c in shared if c not in ids]
    if not shared:
        return skip("MB-C08", msg("mb_shift_only_ids", cols=", ".join(ids)))
    df["_side"] = mark          # 군 컬럼 — 피처 이름과 겹치지 않게 밑줄로 시작
    thr = locks.limits("GR-04", lock_path)["smd_threshold"].value
    hits = _by_size(checks.smd_imbalance(df, "_side", shared, thr))
    n_dev, n_ext = mark.count("dev"), mark.count("ext")
    base = {"n_dev": n_dev, "n_ext": n_ext, "n_features": len(shared),
            "identifiers": ids}
    if not hits:
        return LeakFinding(id="MB-C08", grade=grade_of("MB-C08"), verdict="pass",
                           summary=msg("mb_shift_pass", n=len(shared)), numbers=base)
    return LeakFinding(
        id="MB-C08", grade=grade_of("MB-C08"), verdict="fail",
        summary=msg("mb_shift_fail", n=len(hits), total=len(shared), limit=thr),
        detail=[_smd_row("mb_shift_row", s) for s in hits]
        + ([msg("mb_shift_ids", cols=", ".join(ids))] if ids else [])
        + [msg("mb_shift_why")],
        numbers={**base, "columns": {s.columns[0]: s.numbers for s in hits}},
        action=msg("mb_shift_action"))


def run_all(spec, meta_cols: list[str] | None = None,  # noqa: ANN001
            sample_n: int = 50_000) -> list[LeakFinding]:
    """B4 전부 — 하나가 실패해도 나머지는 돈다 (leak.run_all 과 같은 모양)."""
    out = []
    for fn in (lambda: class_balance(spec, sample_n),
               lambda: [hidden_imbalance(spec, meta_cols, sample_n)],
               lambda: [set_shift(spec, sample_n)]):
        try:
            out += fn()
        except (ValueError, OSError, KeyError) as e:
            out.append(skip("MB-C08", str(e)))
    return out
