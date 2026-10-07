"""S206 과잉경고 검수 — **정상 데이터셋 10개에서 red 0, yellow ≤ 2**.

멀쩡한 자료에 빨간 배너가 뜨면 사람은 배너를 안 읽게 되고, 그러면 진짜 경고도 같이
묻힌다. **과잉경고는 검출 실패만큼 나쁘다.**

세는 것은 두 가지다.
- 적합성(M1-3): 빨강·회색(Gate) = red, 노랑 = yellow
- 가드레일(M4): 차단 = red, 진단 = yellow  (`검사하지 않은 것`은 세지 않는다 — 그건
  "못 봤다"이지 경고가 아니다)

식별자(sid)는 **hold 로 뺀 상태**로 본다 — 그게 문서가 안내하는 정상 흐름이다.
"""

import pandas as pd
import pytest

from cases import normal

RED_LIMIT = 0
YELLOW_LIMIT = 2


def _prepare(tmp_path, monkeypatch, name: str):
    """정상 자료 하나로 세션을 만들고, 타입 확정 + sid hold 까지 한다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    df, types = normal.ALL[name]()
    path = tmp_path / f"{name}.csv"
    df.to_csv(path, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)

    doc = load_session(session)
    sid = main_source(doc)["id"]
    if "sid" in df.columns:
        # 식별자는 분석에서 빼는 것이 정상 흐름이다 (S-R10 이 안내하는 조치)
        append_op(doc, "hold", source=sid, cols=["sid"])
        append_op(doc, "semantic_confirm", source=sid, column="sid", type="id")
    for col, typ in types.items():
        append_op(doc, "semantic_confirm", source=sid, column=col, type=typ)
    save_session(doc)
    return session, df


def _count(session: str, name: str) -> dict:
    """이 세션에서 나오는 경고를 등급별로 센다."""
    from statop.compat import composition_groups, judge_set
    from statop.derive.service import apply_ops, session_frame
    from statop.guard.pipeline import run as run_guard
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session)
    _, src, df = session_frame(session)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})
    cols = [c for c in st["analysis"].get(src["id"], []) if c in df.columns]

    red, yellow, detail = 0, 0, []
    comp = composition_groups(df, cols, types)
    intent = normal.INTENT[name]
    op = intent["op"]

    def add(rid: str, verdict: str, where: str, columns) -> None:  # noqa: ANN001
        nonlocal red, yellow
        if verdict in ("red", "gate"):
            red += 1
        elif verdict in ("yellow", "diag"):
            yellow += 1
        else:
            return
        detail.append(f"{where}:{rid}({verdict}) {list(columns)}")

    # ① 사용자가 **하려는 분석**에 대해서만 본다 — 의도하지 않은 연산을 걸면 당연히
    #    경고가 나오고, 그건 과잉경고가 아니라 올바른 경고다
    from statop.compat import judge_pair

    for f in judge_pair(op, intent["y"], intent["x"], types, df=df,
                        comp_groups=comp).findings:
        add(f.id, f.verdict, op, f.columns)
    # ② 전체 집합 요약  — **의도한 분석이 쓰는 컬럼**으로 좁힌다.
    #    쓰지도 않는 컬럼에 그 연산을 걸면 당연히 걸리고(예: 상관 분석 프레임에 남아 있는
    #    라벨 컬럼 → S-R09), 그건 과잉경고가 아니라 "그 컬럼엔 이 연산을 쓰지 말라"는
    #    맞는 말이다. 여기서 재는 것은 **하려는 분석에 대한** 거짓 경보다
    used = [c for c in (intent["y"], intent["x"]) if c in df.columns]
    for f in judge_set(op, used, types, df=df, comp_groups=comp).findings:
        add(f.id, f.verdict, f"{op}-set", f.columns)

    group = intent["x"] if types.get(intent["x"]) == "label" else None
    guard = run_guard(df, types, group_col=group)
    for f in guard.findings:
        add(f.rule, f.tier, "guard", f.columns)
    return {"red": red, "yellow": yellow, "detail": detail}


@pytest.mark.parametrize("name", sorted(normal.ALL))
def test_a_clean_dataset_raises_no_red_and_few_yellow(name, tmp_path, monkeypatch):
    session, _ = _prepare(tmp_path, monkeypatch, name)
    got = _count(session, name)
    assert got["red"] <= RED_LIMIT, f"{name}: 거짓 차단 {got['detail']}"
    assert got["yellow"] <= YELLOW_LIMIT, f"{name}: 노랑 과다 {got['detail']}"


def test_ten_normal_datasets_exist():
    """10개 미만이면 검수라고 할 수 없다."""
    assert len(normal.ALL) >= 10
