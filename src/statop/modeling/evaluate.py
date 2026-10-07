"""B5 평가 감사  — MB-C16~C20 · C22 · C23.

여기서부터는 **모델이 낸 예측**을 본다. 앞의 검사들이 "자료와 설정이 온전한가"였다면
이건 "그 성능 숫자를 그대로 읽어도 되는가"다.

**여는 조건: 의미 타입이 `probability` 로 확정된 컬럼이 하나는 있어야 한다.**
예측 확률이 없으면 평가를 감사할 것이 없다. 확정 전에는 판정하지 않고 확정을 청한다 —
`[0,1]` 값이라고 다 확률은 아니고(비율·정규화 점수일 수 있다), 무엇인지 정하는 것은
사용자의 몫이다 (: 선택 → 타입 확정 → 판정).

**감사 전용이다.** 학습을 돌리지 않고 예측이 담긴 세트 파일과 설정만 본다.
"""

import numpy as np
import pandas as pd

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, load_set, skip

# 임계값이 기록되지 않았을 때 클래스별 성능을 보려고 쓰는 값. **가정이라고 반드시 적는다**
DEFAULT_THRESHOLD = 0.5
# 보정 오차(ECE)를 재는 구간 수. 10 은 관행값이고, n 이 작으면 구간이 비어 불안정해진다
ECE_BINS = 10
# 이보다 크면 "확률을 그대로 읽기 어렵다"고 본다 (SC-CLS-13)
ECE_LIMIT = 0.10
# "가장 벌어진 구간"을 대표로 보일 때 이만큼은 들어 있어야 한다.
# 2개짜리 구간이 100% 인 것은 잡음이지 보정 문제가 아니다
ECE_MIN_BIN = 10
# fold 성능의 표준편차가 이보다 크면 평균 하나로 말하기 어렵다
FOLD_SD_LIMIT = 0.05
# 검정력을 잴 기준 AUC. **관측된 AUC 로 검정력을 계산하지 않는다** — 관측 효과로 구한
# 사후 검정력은 p 값을 다시 쓴 것일 뿐이라 새 정보가 없다(잘 알려진 오류). 대신
# "이 정도는 잡고 싶다"는 기준값을 두고, 지금 n 으로 그것을 잡을 수 있는지를 본다
POWER_REF_AUC = 0.70
POWER_ALPHA = 0.05


def probability_column(spec, session_file: str) -> tuple[str | None, str]:  # noqa: ANN001
    """확률 컬럼을 고른다 — **확정된 의미 타입만 믿는다**.

    반환: (컬럼, 사유). 컬럼이 None 이면 사유가 왜 못 골랐는지 말한다.
    `[0,1]` 이라고 다 확률이 아니므로 값으로 짐작하지 않는다 (S-T02 비율·S-T14 정규화 점수와
    구분이 안 된다).
    """
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    types = replay(doc)["semantic_types"].get(src["id"] if src else "", {})
    probs = [c for c, t in types.items() if t == "probability"]
    if not probs:
        # 확정할 길이 막혀 있는 경우를 가려낸다 — 예측 컬럼이 세트 파일에만 있으면
        # 세션 main 에서는 확정할 수가 없다. "확정하세요"만 말하면 막다른 길이 된다
        if spec.score_column and src:
            from statop.io.meta import open_meta

            try:
                in_main = spec.score_column in open_meta(src["path"]).columns
            except (ValueError, OSError):
                in_main = True
            if not in_main:
                return None, msg("mb_eval_score_not_in_main",
                                 col=spec.score_column, main=src["path"])
        return None, msg("mb_eval_need_probability")
    if spec.score_column and spec.score_column in probs:
        return spec.score_column, ""
    if spec.score_column:
        # 지정한 컬럼이 확률로 확정돼 있지 않다 — 다른 걸 대신 쓰지 않는다
        return None, msg("mb_eval_score_not_probability", col=spec.score_column,
                         found=", ".join(probs))
    if len(probs) > 1:
        return None, msg("mb_eval_many_probability", cols=", ".join(probs))
    return probs[0], ""


def _eval_frame(spec, col: str, sample_n: int) -> pd.DataFrame:  # noqa: ANN001
    """평가는 **test 에서 본다.** 없으면 external, 그것도 없으면 볼 것이 없다."""
    for role in ("test", "external"):
        if role in spec.sets:
            df = load_set(spec.sets[role]).head(sample_n)
            if col in df.columns and spec.label_column in df.columns:
                out = df[[col, spec.label_column]].dropna()
                out.attrs["role"] = role
                return out
    return pd.DataFrame()


def _binary(y: pd.Series, positive: str | None) -> np.ndarray | None:
    """라벨을 0/1 로. 양성이 지정돼 있으면 그것을 1 로 (MB-C13 과 같은 기준)."""
    levels = sorted(str(v) for v in y.dropna().unique())
    if len(levels) != 2:
        return None
    pos = positive if positive in levels else levels[-1]
    return (y.astype(str) == pos).to_numpy().astype(int)


def _ece(prob: np.ndarray, y: np.ndarray, bins: int = ECE_BINS) -> dict:
    """보정 오차 — 구간마다 "예측 확률 평균"과 "실제 비율"이 얼마나 벌어지는가.

    0.8 이라고 말한 것들이 실제로 80% 맞았는지 본다. 구간이 비면 건너뛴다.
    """
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(prob, edges[1:-1]), 0, bins - 1)
    rows, gap_sum = [], 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        conf, acc = float(prob[m].mean()), float(y[m].mean())
        rows.append({"bin": b, "n": int(m.sum()), "confidence": conf, "actual": acc})
        gap_sum += m.sum() * abs(conf - acc)
    return {"ece": gap_sum / len(prob) if len(prob) else float("nan"), "bins": rows}


# ── MB-C16 불균형인데 ROC-AUC 단독 ──────────────────────────
def auc_power(n_pos: int, n_neg: int, ref: float = POWER_REF_AUC,
              alpha: float = POWER_ALPHA) -> float:
    """지금 n 으로 AUC {ref} 를 0.5 와 구분할 수 있는가 (Hanley-McNeil 분산).

    양성이 적으면 AUC 가 높게 나와도 그 값을 믿기 어렵다 — 얼마나 믿기 어려운지를
    **기준값 대비 검정력**으로 말한다. 관측 AUC 로 계산하지 않는 이유는 위 상수 주석에.
    """
    from scipy.stats import norm

    if n_pos < 2 or n_neg < 2:
        return 0.0
    q1, q2 = ref / (2 - ref), 2 * ref**2 / (1 + ref)
    var1 = (ref * (1 - ref) + (n_pos - 1) * (q1 - ref**2)
            + (n_neg - 1) * (q2 - ref**2)) / (n_pos * n_neg)
    var0 = (n_pos + n_neg + 1) / (12 * n_pos * n_neg)      # AUC=0.5 일 때의 분산
    if var1 <= 0 or var0 <= 0:
        return 0.0
    z = norm.ppf(1 - alpha / 2)
    return float(norm.cdf((abs(ref - 0.5) - z * np.sqrt(var0)) / np.sqrt(var1)))


def auc_pair(prob: np.ndarray, y: np.ndarray) -> dict:
    """ROC-AUC 와 PR-AUC 를 함께. 기저율(양성 비율)이 PR-AUC 를 읽는 기준이다."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    return {"roc_auc": float(roc_auc_score(y, prob)),
            "pr_auc": float(average_precision_score(y, prob)),
            "base_rate": float(y.mean()), "n_positive": n_pos, "n_negative": n_neg,
            "power": auc_power(n_pos, n_neg), "power_ref": POWER_REF_AUC}


def _metrics(spec, session_file: str, sample_n: int):  # noqa: ANN001
    """공통 재료 — 확률 컬럼·평가 세트·이진 라벨. 하나라도 없으면 (None, 사유)."""
    col, why = probability_column(spec, session_file)
    if col is None:
        return None, why
    df = _eval_frame(spec, col, sample_n)
    if not len(df):
        return None, msg("mb_eval_no_test", col=col)
    y = _binary(df[spec.label_column], spec.positive_class)
    if y is None:
        return None, msg("mb_eval_binary_only",
                         n=int(df[spec.label_column].nunique()))
    prob = pd.to_numeric(df[col], errors="coerce").to_numpy()
    return {"col": col, "prob": prob, "y": y, "role": df.attrs.get("role", ""),
            "n": len(df)}, ""


def metric_pair(spec, session_file: str, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """MB-C16 — 불균형에서 ROC-AUC 만 보면 낙관적으로 읽힌다 (MR-G04)."""
    m, why = _metrics(spec, session_file, sample_n)
    if m is None:
        return skip("MB-C16", why)
    a = auc_pair(m["prob"], m["y"])
    detail = [msg("mb_c16_values", roc=a["roc_auc"], pr=a["pr_auc"],
                  base=a["base_rate"], role=m["role"], n=m["n"])]
    numbers = {**a, "column": m["col"], "role": m["role"], "n": m["n"]}
    # 기저율이 낮을수록 ROC 와 PR 이 갈린다 — 갈린 정도를 그대로 보여준다
    if a["base_rate"] >= 0.2:
        return LeakFinding(id="MB-C16", grade=grade_of("MB-C16"), verdict="pass",
                           summary=msg("mb_c16_balanced", base=a["base_rate"]),
                           detail=detail, numbers=numbers)
    return LeakFinding(
        id="MB-C16", grade=grade_of("MB-C16"), verdict="fail",
        summary=msg("mb_c16_imbalanced", n_pos=a["n_positive"],
                    ref=a["power_ref"], power=a["power"],
                    roc=a["roc_auc"], pr=a["pr_auc"]),
        detail=[*detail, msg("mb_c16_why")], numbers=numbers,
        action=msg("mb_c16_action"))


# ── MB-C18 소수 클래스 성능 · MB-C20 임계값 ─────────────────
def class_performance(spec, session_file: str, sample_n: int = 50_000) -> list[LeakFinding]:  # noqa: ANN001
    """MB-C18/C20 — 임계값을 정해야 클래스별 성능이 나온다. 그 임계값이 기록돼 있는가."""
    m, why = _metrics(spec, session_file, sample_n)
    if m is None:
        return [skip("MB-C18", why), skip("MB-C20", why)]

    recorded = spec.threshold is not None
    thr = spec.threshold if recorded else DEFAULT_THRESHOLD
    pred = (m["prob"] >= thr).astype(int)
    y = m["y"]
    out = []

    # MB-C20 — 임계값이 없으면 민감도·특이도가 어느 지점의 값인지 알 수 없다
    if recorded:
        out.append(LeakFinding(id="MB-C20", grade=grade_of("MB-C20"), verdict="pass",
                               summary=msg("mb_c20_recorded", thr=thr),
                               numbers={"threshold": thr, "recorded": True}))
    else:
        out.append(LeakFinding(
            id="MB-C20", grade=grade_of("MB-C20"), verdict="fail",
            summary=msg("mb_c20_missing", thr=DEFAULT_THRESHOLD),
            detail=[msg("mb_c20_why")], numbers={"threshold": None, "assumed": thr},
            action=msg("mb_c20_action")))

    # MB-C18 — 클래스별로 몇 개나 맞혔는가. 소수 클래스가 0 이면 전체 지표는 의미가 없다
    rows, collapsed = [], []
    for cls, name in ((0, msg("mb_c18_negative")), (1, msg("mb_c18_positive"))):
        mask = y == cls
        n = int(mask.sum())
        hit = int((pred[mask] == cls).sum()) if n else 0
        recall = hit / n if n else float("nan")
        rows.append({"class": name, "n": n, "recall": recall})
        if n and recall == 0:
            collapsed.append(name)
    detail = [msg("mb_c18_row", name=r["class"], n=r["n"], recall=r["recall"])
              for r in rows]
    if not recorded:
        detail.append(msg("mb_c18_assumed", thr=DEFAULT_THRESHOLD))
    numbers = {"threshold": thr, "recorded": recorded, "classes": rows}
    if collapsed:
        out.append(LeakFinding(
            id="MB-C18", grade=grade_of("MB-C18"), verdict="fail",
            summary=msg("mb_c18_collapsed", names=", ".join(collapsed), thr=thr),
            detail=detail, numbers=numbers, action=msg("mb_c18_action")))
    else:
        out.append(LeakFinding(id="MB-C18", grade=grade_of("MB-C18"), verdict="pass",
                               summary=msg("mb_c18_pass", thr=thr), detail=detail,
                               numbers=numbers))
    return out


# ── MB-C19 확률 보정 ────────────────────────────────────────
def calibration(spec, session_file: str, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """MB-C19 — 0.8 이라고 말한 것들이 실제로 80% 맞았는가 (SC-CLS-13 ECE)."""
    m, why = _metrics(spec, session_file, sample_n)
    if m is None:
        return skip("MB-C19", why)
    r = _ece(m["prob"], m["y"])
    big = [b for b in r["bins"] if b["n"] >= ECE_MIN_BIN]
    worst = max(big, key=lambda b: abs(b["confidence"] - b["actual"]), default=None)
    detail = [msg("mb_c19_bins", n=len(r["bins"]))]
    if worst:
        detail.append(msg("mb_c19_worst", conf=worst["confidence"],
                          actual=worst["actual"], n=worst["n"]))
    else:
        # 대표로 보일 만한 구간이 없다 — 없는 것을 있다고 하지 않는다
        detail.append(msg("mb_c19_thin_bins", limit=ECE_MIN_BIN))
    numbers = {"ece": r["ece"], "bins": r["bins"], "limit": ECE_LIMIT}
    if r["ece"] <= ECE_LIMIT:
        return LeakFinding(id="MB-C19", grade=grade_of("MB-C19"), verdict="pass",
                           summary=msg("mb_c19_pass", ece=r["ece"], limit=ECE_LIMIT),
                           detail=detail, numbers=numbers)
    return LeakFinding(
        id="MB-C19", grade=grade_of("MB-C19"), verdict="fail",
        summary=msg("mb_c19_high", ece=r["ece"], limit=ECE_LIMIT),
        detail=[*detail, msg("mb_c19_why")], numbers=numbers,
        action=msg("mb_c19_action"))


# ── MB-C17 다중분류 평균 방식 ───────────────────────────────
def averaging(spec, session_file: str, sample_n: int = 50_000) -> LeakFinding:  # noqa: ANN001
    """MB-C17 — 다중분류에서 macro/micro/weighted 중 무엇으로 평균했는지 적혀 있는가."""
    col, why = probability_column(spec, session_file)
    if col is None:
        return skip("MB-C17", why)
    df = _eval_frame(spec, col, sample_n)
    n_classes = int(df[spec.label_column].nunique()) if len(df) else 0
    if n_classes <= 2:
        return skip("MB-C17", msg("mb_c17_binary", n=n_classes))
    if spec.averaging:
        return LeakFinding(id="MB-C17", grade=grade_of("MB-C17"), verdict="pass",
                           summary=msg("mb_c17_recorded", how=spec.averaging,
                                       n=n_classes),
                           numbers={"averaging": spec.averaging, "classes": n_classes})
    return LeakFinding(
        id="MB-C17", grade=grade_of("MB-C17"), verdict="fail",
        summary=msg("mb_c17_missing", n=n_classes), detail=[msg("mb_c17_why")],
        numbers={"averaging": None, "classes": n_classes},
        action=msg("mb_c17_action"))


# ── MB-C22 fold 간 분산 ─────────────────────────────────────
def fold_spread(spec) -> LeakFinding:  # noqa: ANN001
    """MB-C22 — 평균 하나만 보고하면 어느 fold 에서 무너졌는지 가려진다."""
    scores = spec.fold_scores
    if not scores:
        return skip("MB-C22", msg("mb_c22_no_folds"))
    arr = np.asarray(scores, dtype="float64")
    sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    worst = float(arr.min())
    numbers = {"scores": [float(x) for x in arr], "mean": float(arr.mean()),
               "sd": sd, "worst": worst, "limit": FOLD_SD_LIMIT}
    detail = [msg("mb_c22_values", mean=arr.mean(), sd=sd, worst=worst,
                  n=len(arr))]
    if sd <= FOLD_SD_LIMIT:
        return LeakFinding(id="MB-C22", grade=grade_of("MB-C22"), verdict="pass",
                           summary=msg("mb_c22_pass", sd=sd, limit=FOLD_SD_LIMIT),
                           detail=detail, numbers=numbers)
    return LeakFinding(
        id="MB-C22", grade=grade_of("MB-C22"), verdict="fail",
        summary=msg("mb_c22_wide", sd=sd, mean=arr.mean(), worst=worst),
        detail=[*detail, msg("mb_c22_why")], numbers=numbers,
        action=msg("mb_c22_action"))


# ── MB-C23 테스트셋 반복 사용 ───────────────────────────────
def test_reuse(spec, session_file: str) -> LeakFinding:  # noqa: ANN001
    """MB-C23 — 같은 test 세트를 몇 번이나 보고 설정을 고쳤는가.

    볼 때마다 조금씩 맞춰가면 test 는 사실상 검증셋이 된다. 세션에 남은 구성 기록으로
    **몇 번 고쳤는지**만 센다 — 그 이상은 알 수 없고, 아는 만큼만 말한다.
    """
    from statop.session.core import load_session, replay

    if "test" not in spec.sets:
        return skip("MB-C23", msg("mb_c23_no_test"))
    specs = replay(load_session(session_file))["model_specs"]
    same = [s for s in specs if (s.get("sets") or {}).get("test") == spec.sets["test"]]
    numbers = {"revisions": len(same), "test": spec.sets["test"]}
    if len(same) <= 1:
        return LeakFinding(id="MB-C23", grade=grade_of("MB-C23"), verdict="pass",
                           summary=msg("mb_c23_pass"), numbers=numbers)
    return LeakFinding(
        id="MB-C23", grade=grade_of("MB-C23"), verdict="fail",
        summary=msg("mb_c23_repeated", n=len(same)),
        detail=[msg("mb_c23_why"), msg("mb_c23_limit")], numbers=numbers,
        action=msg("mb_c23_action"))


def run_all(spec, session_file: str, sample_n: int = 50_000) -> list[LeakFinding]:  # noqa: ANN001
    """B5 평가 감사 전부 — 하나가 실패해도 나머지는 돈다."""
    out = []
    for fn in (lambda: [metric_pair(spec, session_file, sample_n)],
               lambda: class_performance(spec, session_file, sample_n),
               lambda: [calibration(spec, session_file, sample_n)],
               lambda: [averaging(spec, session_file, sample_n)],
               lambda: [fold_spread(spec)],
               lambda: [test_reuse(spec, session_file)]):
        try:
            out += fn()
        except (ValueError, OSError, KeyError) as e:
            out.append(skip("MB-C16", str(e)))
    return out
