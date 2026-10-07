"""B3 라벨 인코딩 방향·매핑 감사  — MB-C13.

라벨이 `case`/`control` 같은 문자열이면 어딘가에서 0/1 로 바뀐다. **어느 쪽이 1인지**가
기록돼 있지 않으면 AUC·민감도·위험비가 전부 반대 방향을 가리켜도 숫자만 봐서는 알 수 없다.
흔한 통로는 알파벳 순 인코딩이다 — `case` < `control` 이라 의도와 무관하게 case 가 0 이 된다.

**편집 UI 는 여기 없다.** 수준별 코드를 고치는 화면은 (`statop labels`, 전체화면
라벨 매핑)에 이미 있고, 여기서는 그 기록을 읽어 "기록됐는가 · 방향이 무엇인가 ·
세트마다 같은가"만 확인한다.
"""

from statop.labels import levels_of
from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, skip


def _finding(verdict: str, summary: str, detail=None, numbers=None,  # noqa: ANN001
             action: str = "") -> LeakFinding:
    return LeakFinding(id="MB-C13", grade=grade_of("MB-C13"), verdict=verdict,
                       summary=summary, detail=detail or [], numbers=numbers or {},
                       action=action)


def recorded_mapping(session_file: str | None, column: str) -> dict[str, int] | None:
    """세션에 남은 이 컬럼의 수준 매핑 ( `label_map` op). 없으면 None."""
    if not session_file:
        return None
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    maps = replay(doc)["label_maps"].get(src["id"] if src else "", {})
    return maps.get(column)


def label_audit(spec, session_file: str | None = None,  # noqa: ANN001
                sample_n: int = 50_000) -> list[LeakFinding]:
    """세트별 라벨 구성 + 매핑 기록 + 인코딩 방향."""
    col = spec.label_column
    if not col:
        return [skip("MB-C13", msg("mb_need_label"))]
    if not spec.sets:
        return [skip("MB-C13", msg("mb_c13_need_sets"))]

    # 세트별 수준·n·비율 (요구사항 "라벨 결정 후 클래스 비율·세트별 비율 재표시")
    per_set, numbers = {}, {}
    for role, path in spec.sets.items():
        try:
            levels = levels_of(path, col, sample_n)
        except ValueError as e:
            return [skip("MB-C13", str(e))]
        per_set[role] = levels
        numbers[role] = {lv.value: {"n": lv.n, "ratio": lv.ratio} for lv in levels}

    out = []
    detail = [msg("mb_c13_set_row", role=role,
                  levels=" · ".join(f"{lv.value} {lv.n}({lv.ratio:.1%})"
                                    for lv in levels))
              for role, levels in per_set.items()]

    # 세트마다 수준 집합이 같은가. 두 방향을 **따로** 본다 — 학습된 적 없는 클래스를
    # 맞히라는 것과, 어떤 세트에 그 클래스가 아예 없어 성능을 잴 수 없는 것은 다른 문제다
    sets_of_levels = {role: {lv.value for lv in lvs} for role, lvs in per_set.items()}
    train = sets_of_levels.get("train") or next(iter(sets_of_levels.values()))
    every = set().union(*sets_of_levels.values())
    extra = {r: sorted(v - train) for r, v in sets_of_levels.items() if v - train}
    absent = {r: sorted(every - v) for r, v in sets_of_levels.items() if every - v}
    if extra:
        out.append(_finding("fail", msg("mb_c13_level_mismatch", detail=" · ".join(
            msg("mb_c13_level_mismatch_row", role=r, values=", ".join(v))
            for r, v in extra.items())), detail=detail, numbers=numbers,
            action=msg("mb_c13_level_mismatch_action")))
    elif absent:
        out.append(_finding("fail", msg("mb_c13_level_absent", detail=" · ".join(
            msg("mb_c13_level_mismatch_row", role=r, values=", ".join(v))
            for r, v in absent.items())), detail=detail, numbers=numbers,
            action=msg("mb_c13_level_absent_action")))
    else:
        out.append(_finding("pass", msg("mb_c13_levels_ok", n=len(train)),
                            detail=detail, numbers=numbers))

    all_values = sorted({lv.value for lvs in per_set.values() for lv in lvs})
    mapping = recorded_mapping(session_file, col)
    pos = spec.positive_class
    # 기록된 매핑이 없으면 학습 코드가 알파벳 순으로 붙일 가능성이 높다 (sklearn 기본).
    # **도구는 그 코드를 보지 않았다** — 그래서 "된다"가 아니라 "가능성"으로 말한다.
    implied = {v: i for i, v in enumerate(all_values)}
    codes = mapping or implied
    table = msg("mb_c13_table", body=" · ".join(
        msg("mb_c13_table_cell", value=v, code=c,
            role=msg("mb_c13_role_pos") if pos and v == pos else "")
        for v, c in sorted(codes.items(), key=lambda kv: kv[1])))
    source = msg("mb_c13_recorded" if mapping else "mb_c13_implied")
    numbers = {"codes": codes, "recorded": mapping is not None, "positive": pos}

    if not pos:
        out.append(_finding("fail", msg("mb_c13_no_positive"),
                            detail=[source, table], numbers=numbers,
                            action=msg("mb_c13_positive_action")))
    elif pos not in codes:
        out.append(_finding("fail", msg("mb_c13_positive_unknown", pos=pos),
                            detail=[source, table], numbers=numbers,
                            action=msg("mb_c13_positive_action")))
    elif codes[pos] != max(codes.values()):
        # 양성이 가장 큰 코드가 아니면 점수·AUC 가 반대쪽을 가리킨다.
        # 매핑이 기록돼 있으면 사실이고, 없으면 흔한 기본값을 근거로 한 추정이다
        out.append(_finding("fail",
                            msg("mb_c13_flipped" if mapping
                                else "mb_c13_flipped_maybe", pos=pos,
                                code=codes[pos]),
                            detail=[source, table, msg("mb_c13_flip_risk")],
                            numbers=numbers, action=msg("mb_c13_action")))
    elif not mapping:
        out.append(_finding("fail", msg("mb_c13_no_mapping", col=col),
                            detail=[source, table], numbers=numbers,
                            action=msg("mb_c13_action")))
    else:
        out.append(_finding("pass", msg("mb_c13_pass", pos=pos, code=codes[pos]),
                            detail=[source, table], numbers=numbers))
    return out
