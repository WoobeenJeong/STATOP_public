"""B2 세트가 만들어진 과정  — MB-C06 비율 · MB-C07 손실.

~ 는 **세트 안**을 봤다. 여기서 보는 것은 **세트가 만들어지는 과정**이다.
누수가 하나도 없어도, 원본을 나눌 때 비율이 계획과 달랐거나 행이 조용히 사라졌으면
성능 숫자는 의미를 잃는다.

**검사 로직은 새로 쓰지 않는다.** 둘 다 M4 가드레일에 이미 있다 (`statop.guard.checks`):
MB-C06 은 GR-02(SRM), MB-C07 은 GR-03(손실·join·편향적 손실)이다. 임계값도
가드레일 잠금에서 가져온다 — 모듈 B 가 따로 임계를 갖지 않으므로 사용자가
`statop guard set` 으로 조정한 값이 여기에도 그대로 걸린다.

**감사 전용이다.** 학습을 돌리지 않고 세트 파일만 읽는다.
"""

import pandas as pd

from statop.guard import checks, locks
from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, load_set, row_keys, skip

# 손실 검사는 원본 전체를 키로 훑는다 — 이만큼만 보고, 잘랐으면 그 사실을 적는다
LOSS_PROBE = 200_000


def _from_signal(check_id: str, sig: checks.Signal, action: str = "") -> LeakFinding:
    """가드레일 Signal 을 모듈 B 의 판정으로 옮긴다.

    이렇게 두면 CLI 출력·API 응답·웹 표시가 누수 검사(~)와 **같은 모양**이
    된다 — 사용자는 한 화면에서 같은 기호를 읽는다.
    """
    return LeakFinding(id=check_id, grade=grade_of(check_id),
                       verdict="fail" if sig.hit else "pass",
                       summary=sig.detail, numbers=sig.numbers,
                       action=action if sig.hit else "")


# 세트를 읽는 두 번째 축 — train·valid·test 를 합쳐 **개발(dev)**, 그 밖을 **외부(ext)**.
# 같은 자료를 세트별로도 보고 dev/ext 로도 봐야 "학습에 쓴 쪽 전체"와 "밖으로 뺀 쪽"의
# 구성이 비교된다. 세트별로만 보면 train 이 여럿일 때 전체 그림이 안 보인다.
DEV_ROLES = ("train", "valid", "test")


def key_from_session(session_file: str) -> str:
    """행 키를 안 주면 **이미 확정한 행 식별자**를 쓴다.

    의미 타입에서 어느 컬럼이 행 식별자인지 이미 정해 놓고 왔다. 그걸 여기서 또
    치게 하면 같은 것을 두 번 말하는 것이고, 오타가 나면 검사만 조용히 건너뛴다.
    둘 이상이면 무엇을 쓸지는 사람이 정한다 — 골라서 쓰면 틀린 짝을 맞출 수 있다.
    """
    from statop.session.core import load_session, main_source, replay

    try:
        doc = load_session(session_file)
    except (OSError, ValueError):
        return ""
    src = main_source(doc)
    if src is None:
        return ""
    types = replay(doc)["semantic_types"].get(src["id"], {})
    ids = [c for c, t in types.items() if t == "id"]
    return ids[0] if len(ids) == 1 else ""


def _as_ratio(counts: dict, digits: int = 1) -> str:
    """{train: 400, test: 220} → 'train 6.7 : test 3.3' — 합이 10 이 되게 맞춘다.

    행 수와 계획 비율을 나란히 놓으려면 단위가 같아야 한다. 8:2 로 계획했는데
    '400 : 220' 이라고 답하면 사용자가 머릿속에서 다시 환산해야 한다.
    """
    total = sum(counts.values())
    if not total:
        return " : ".join(f"{k} 0" for k in counts)
    return " : ".join(f"{k} {v / total * 10:.{digits}f}" for k, v in counts.items())


def _class_line(counts: dict) -> str:
    """{case: 73, control: 327} → 'case 18.2% : control 81.8% (400행)'."""
    total = sum(counts.values())
    body = " : ".join(f"{k} {v / total:.1%}" for k, v in counts.items()) if total else "-"
    return msg("mb_c06_class_cell", body=body, n=total)


# ── MB-C06 세트 비율 (GR-02 재사용) ─────────────────────────
def set_ratio(spec, expected_ratio: dict[str, float] | None = None,  # noqa: ANN001
              sample_n: int = 50_000, lock_path=None) -> list[LeakFinding]:  # noqa: ANN001
    """계획한 분할 비율대로 나뉘었는가 + 세트 안 클래스 비율이 전체와 같은가.

    기대 비율을 주지 않으면 **검사하지 않는다.** 균등으로 가정하고 검정하면 8:2 분할이
    전부 "이상"으로 나온다 — 그건 비율이 틀린 게 아니라 설계를 잘못 읽은 것이다
    (`checks.srm` 이 같은 이유로 기대 비율을 출력에 항상 적는다).
    """
    p = locks.limits("GR-02", lock_path)["p_threshold"].value
    if len(spec.sets) < 2:
        return [skip("MB-C06", msg("mb_c06_need_sets"))]

    counts, frames = {}, {}
    for role, path in spec.sets.items():
        df = load_set(path, [spec.label_column] if spec.label_column else None)
        df = df.head(sample_n)
        counts[role] = int(len(df))
        frames[role] = df

    out = []
    if expected_ratio:
        # 계획에 없는 세트는 이 검정에서 뺀다. external 의 기대 몫을 0 으로 두고 넣으면
        # 0 으로 나누게 되고, 무엇보다 **사용자가 계획하지 않은 것을 계획 위반으로 센다**
        planned = {r: n for r, n in counts.items() if r in expected_ratio}
        skipped_roles = [r for r in counts if r not in expected_ratio]
        if len(planned) < 2:
            out.append(skip("MB-C06", msg("mb_c06_expect_mismatch",
                                          given=", ".join(expected_ratio),
                                          sets=", ".join(counts))))
        else:
            sig = checks.srm(planned, expected_ratio, p)
            sig.detail = msg("mb_c06_detail" if sig.hit else "mb_c06_pass",
                             p=sig.numbers.get("p", float("nan")),
                             observed=_as_ratio(planned),
                             rows=" : ".join(f"{v:,}" for v in planned.values()),
                             expected=_as_ratio(expected_ratio))
            f = _from_signal("MB-C06", sig, msg("mb_c06_action"))
            if skipped_roles:
                f.detail = [msg("mb_c06_not_planned",
                                roles=", ".join(skipped_roles))]
            out.append(f)
    else:
        out.append(skip("MB-C06", msg("mb_c06_no_expected")))

    out.append(_stratification(spec, frames, p))
    return out


def _stratification(spec, frames: dict, p: float) -> LeakFinding:  # noqa: ANN001
    """세트 안 클래스 비율이 전체와 같은가 — **세트별**과 **dev/ext** 두 축으로 본다.

    세트를 여러 번 보므로 임계를 세트 수로 나눈다 (도구가 스스로 다중비교 오류를
    범하지 않게 — GR-02 의 차원별 SRM 과 같은 처리).
    """
    col = spec.label_column
    if not col or any(col not in f.columns for f in frames.values()):
        return skip("MB-C06", msg("mb_c06_no_label"))
    pooled = pd.concat([f[col] for f in frames.values()]).value_counts()
    if len(pooled) < 2:
        return skip("MB-C06", msg("mb_c06_one_class"))

    ratio = {str(k): float(v) for k, v in pooled.items()}
    adj = p / len(frames)
    per_set, bad, one_class = {}, [], []
    for role, f in frames.items():
        c = {str(k): int(v) for k, v in f[col].value_counts().items()}
        per_set[role] = c
        if len(c) < 2:
            one_class.append(role)          # 한 종류뿐이면 비율 비교가 성립하지 않는다
            continue
        if checks.srm(c, ratio, adj).hit:
            bad.append(role)

    # 두 번째 축 — 개발(dev)과 외부(ext)를 합쳐서 본다
    axes = {"dev": [r for r in frames if r in DEV_ROLES],
            "ext": [r for r in frames if r not in DEV_ROLES]}
    dev_ext = {k: pd.concat([frames[r][col] for r in rs]).value_counts().to_dict()
               for k, rs in axes.items() if rs}
    dev_ext = {k: {str(a): int(b) for a, b in v.items()} for k, v in dev_ext.items()}

    detail = [msg("mb_c06_axis_set", body=" · ".join(
        f"{r} {_class_line(c)}" for r, c in per_set.items()))]
    if len(dev_ext) > 1:
        detail.append(msg("mb_c06_axis_devext", body=" · ".join(
            f"{k} {_class_line(v)}" for k, v in dev_ext.items())))
    else:
        detail.append(msg("mb_c06_axis_no_ext"))
    for role in one_class:
        detail.append(msg("mb_c06_set_one_class", role=role))

    numbers = {"per_set": per_set, "dev_ext": dev_ext, "pooled": ratio,
               "failed": bad, "p_threshold_adjusted": adj}
    if not bad:
        return LeakFinding(id="MB-C06", grade=grade_of("MB-C06"), verdict="pass",
                           summary=msg("mb_c06_strat_pass"), detail=detail,
                           numbers=numbers)
    # 특정 그룹을 일부러 external 로 뺀 설계라면 이 경고는 그 설계를 본 것뿐이다 —
    # 그 경우 무엇을 다시 해야 하는지 함께 말한다 (행 필터로 그룹을 빼고 재판정)
    detail.append(msg("mb_c06_group_note", col=col))
    return LeakFinding(id="MB-C06", grade=grade_of("MB-C06"), verdict="fail",
                       summary=msg("mb_c06_strat_detail", roles=", ".join(bad),
                                   adj=adj),
                       detail=detail, numbers=numbers,
                       action=msg("mb_c06_strat_action"))


def before_after(src, kept_index, col: str) -> dict:  # noqa: ANN001
    """한 컬럼이 손실 전후로 어떻게 달라졌는가 — 겹쳐 볼 재료.

    "유의하다"만 말하면 **얼마나 달라졌길래** 유의한지 알 수 없다. 범주형은 수준별
    비율을, 수치형은 값 자체를 전후로 돌려준다 (그림은 껍데기가 그린다).
    """
    s = src[col]
    after = s[s.index.isin(kept_index)]
    if pd.api.types.is_numeric_dtype(s) and s.nunique() > 10:
        return {"kind": "numeric", "column": col,
                "before": s.dropna().tolist(), "after": after.dropna().tolist()}
    tab = lambda x: {str(k): int(v) for k, v in x.value_counts().items()}  # noqa: E731
    return {"kind": "categorical", "column": col,
            "before": tab(s.dropna()), "after": tab(after.dropna())}


def _shift_cell(col: str, info: dict, p: float) -> str:
    """전후 한 줄 — 범주형은 수준별 비율, 수치형은 평균과 표준편차. p 는 컬럼마다 붙인다."""
    import numpy as np

    if info["kind"] == "categorical":
        return msg("mb_c07_shift_cat", col=col, p=p,
                   before=_class_line(info["before"]).split(" (")[0],
                   after=_class_line(info["after"]).split(" (")[0])
    b, a = np.asarray(info["before"]), np.asarray(info["after"])
    return msg("mb_c07_shift_num", col=col, p=p,
               mb=float(b.mean()), sb=float(b.std(ddof=1)) if len(b) > 1 else 0.0,
               ma=float(a.mean()), sa=float(a.std(ddof=1)) if len(a) > 1 else 0.0)


def _shifted_columns(src, kept_index, cols: list[str],  # noqa: ANN001
                     p_threshold: float) -> LeakFinding:
    """손실 뒤 분포가 달라진 컬럼들을 **하나의 판정**으로 모은다.

    컬럼마다 따로 경고를 쏟으면 몇 개가 걸렸는지가 아니라 화면 길이만 남는다.
    """
    hits = checks.biased_loss(src, kept_index, cols, p_threshold)
    changed = {c: p for c in cols
               for sig in hits if sig.columns == [c]
               for p in [sig.numbers.get("p", float("nan"))]}
    if not changed:
        return LeakFinding(id="MB-C07", grade=grade_of("MB-C07"), verdict="pass",
                           summary=msg("mb_c07_bias_pass", cols=", ".join(cols)))
    shifts = {c: before_after(src, kept_index, c) for c in changed}
    detail = [_shift_cell(c, info, changed[c]) for c, info in shifts.items()]
    detail += [msg("mb_c07_shift_why"), msg("mb_c07_shift_risk"),
               msg("mb_c07_shift_see", cols=", ".join(changed))]
    return LeakFinding(
        id="MB-C07", grade=grade_of("MB-C07"), verdict="fail",
        summary=msg("mb_c07_shift", cols=", ".join(changed), n=len(changed)),
        detail=detail, action=msg("mb_c07_bias_action"),
        numbers={"p": changed,
                 # 값 목록은 그림용이라 판정 기록에는 요약만 남긴다 (점진 노출)
                 "kinds": {c: i["kind"] for c, i in shifts.items()}})


def shift_lines(info: dict, width: int = 40) -> list[str]:
    """정리 전/후 분포를 **같은 축에 겹쳐** 그린다 — 얼마나 달라졌길래 유의한지 보게.

    "유의하다"는 방향도 크기도 말해주지 않는다. 눈으로 겹쳐 봐야 어느 수준이 줄고
    어느 쪽이 늘었는지 안다. 그림은 껍데기가 아니라 여기서 문자열로 만든다 —
    CLI·TUI·웹이 같은 그림을 본다 .
    """
    from statop.render.chart import strip_plot
    from statop.render.spark import bar

    head = [msg("mb_c07_view_head", col=info["column"])]
    if info["kind"] == "numeric":
        return head + strip_plot({msg("mb_c07_view_before"): info["before"],
                                  msg("mb_c07_view_after"): info["after"]}, width)
    b, a = info["before"], info["after"]
    nb, na = sum(b.values()) or 1, sum(a.values()) or 1
    out = head
    for lv in sorted(set(b) | set(a), key=lambda k: -b.get(k, 0)):
        rb, ra = b.get(lv, 0) / nb, a.get(lv, 0) / na
        out.append(msg("mb_c07_view_row", value=lv[:18], kind=msg("mb_c07_view_before"),
                       bar=bar(rb, width // 2), ratio=rb, n=b.get(lv, 0)))
        out.append(msg("mb_c07_view_row", value="", kind=msg("mb_c07_view_after"),
                       bar=bar(ra, width // 2), ratio=ra, n=a.get(lv, 0)))
    return out


def shift_view(spec, source_path: str, key: str, column: str,  # noqa: ANN001
               sample_n: int = LOSS_PROBE) -> dict:
    """한 컬럼의 정리 전/후 분포 — 판정에서 지목한 컬럼을 눌렀을 때 보는 화면."""
    src = load_set(source_path).head(sample_n)
    for need in (key, column):
        if need not in src.columns:
            raise ValueError(msg("select_err_missing", cols=need))
    src_key = row_keys(src, [key])
    matched: set[str] = set()
    for path in spec.sets.values():
        matched |= set(row_keys(load_set(path, [key]).head(sample_n), [key]))
    info = before_after(src, src.index[src_key.isin(matched)], column)
    return {"info": info, "lines": shift_lines(info)}


# ── MB-C07 원본 → 세트 손실 (GR-03 재사용) ──────────────────
def source_loss(spec, source_path: str, key: str | None = None,  # noqa: ANN001
                meta_cols: list[str] | None = None,
                sample_n: int = LOSS_PROBE, lock_path=None) -> list[LeakFinding]:  # noqa: ANN001
    """원본의 행이 어느 세트에도 안 들어갔다면, 무엇이 빠졌는가.

    키가 없으면 **검사하지 않는다.** 행을 1:1 로 맞출 수 없는데 맞춘 척하면
    없는 손실을 만들어낸다 ( 표 대조와 같은 원칙). 키 중복도 마찬가지다.
    """
    if not key:
        return [skip("MB-C07", msg("mb_c07_no_key"))]
    if not spec.sets:
        return [skip("MB-C07", msg("mb_c07_need_sets"))]

    src = load_set(source_path).head(sample_n)
    if key not in src.columns:
        return [skip("MB-C07", msg("mb_c07_key_missing", col=key, path=source_path))]
    src_key = row_keys(src, [key])
    if src_key.duplicated().any():
        return [skip("MB-C07", msg("mb_c07_key_dup", col=key,
                                   n=int(src_key.duplicated().sum())))]

    matched: set[str] = set()
    detail = []
    for role, path in spec.sets.items():
        df = load_set(path, [key]).head(sample_n)
        if key not in df.columns:
            return [skip("MB-C07", msg("mb_c07_key_missing", col=key, path=path))]
        k = set(row_keys(df, [key]))
        detail.append(msg("mb_c07_set_row", role=role, n=len(df), matched=len(k & set(src_key))))
        matched |= k

    kept_mask = src_key.isin(matched)
    kept_index = src.index[kept_mask]
    n_matched = int(kept_mask.sum())

    g3 = {k: v.value for k, v in locks.limits("GR-03", lock_path).items()}
    out = []

    # 퍼널 — 원본 n 에서 세트에 들어간 n 으로
    for sig in checks.retention_funnel([{"label": msg("mb_c07_funnel_label"),
                                         "n_before": len(src), "n_after": n_matched}]):
        out.append(_from_signal("MB-C07", sig, msg("mb_c07_action")))
    # 매칭률 — 낮으면 차단
    join = checks.join_rate(len(src), n_matched, g3["join_rate_gate"],
                            g3["join_rate_warn"])
    f = _from_signal("MB-C07", join, msg("mb_c07_action"))
    f.detail = detail
    out.append(f)

    # 편향적 손실 — 빠진 행이 라벨·그룹·메타와 연관되는가
    bias_cols = [c for c in ([spec.label_column, spec.group_column]
                             + (meta_cols or [])) if c and c in src.columns]
    if n_matched == len(src):
        out.append(LeakFinding(id="MB-C07", grade=grade_of("MB-C07"), verdict="pass",
                               summary=msg("mb_c07_no_loss", n=len(src))))
    elif bias_cols:
        out.append(_shifted_columns(src, kept_index, bias_cols,
                                    g3["bias_p_threshold"]))
        if spec.group_column and spec.group_column in src.columns:
            sig = checks.loss_by_group(src, kept_index, spec.group_column)
            out.append(_from_signal("MB-C07", sig, msg("mb_c07_bias_action")))
    else:
        out.append(skip("MB-C07", msg("mb_c07_no_bias_cols")))
    return out


def run_all(spec, source_path: str | None = None, key: str | None = None,  # noqa: ANN001
            expected_ratio: dict[str, float] | None = None,
            meta_cols: list[str] | None = None,
            sample_n: int = 50_000) -> list[LeakFinding]:
    """세트 비율·손실 검사 전부 — 하나가 실패해도 나머지는 돈다 (leak.run_all 과 같은 모양)."""
    out = []
    try:
        out += set_ratio(spec, expected_ratio, sample_n)
    except (ValueError, OSError, KeyError) as e:
        out.append(skip("MB-C06", str(e)))
    if source_path:
        try:
            out += source_loss(spec, source_path, key, meta_cols)
        except (ValueError, OSError, KeyError) as e:
            out.append(skip("MB-C07", str(e)))
    else:
        out.append(skip("MB-C07", msg("mb_c07_no_source")))
    return out
