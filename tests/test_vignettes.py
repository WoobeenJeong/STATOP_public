"""S207 검정 선택 정확도 — vignette 세트 정답률 **≥ 90%**.

설계를 주고 "어느 검정이 맞나"를 묻는다. 맞다고 보는 조건:
**기대 검정 중 하나가 후보 목록의 초록(적합)에 들어 있을 것.**

초록에 없고 노랑에만 있으면 틀린 것으로 센다 — 노랑은 "확인이 더 필요하다"이지 추천이
아니다. 반대로 초록이 여러 개인 것은 벌하지 않는다: 같은 설계에 쓸 수 있는 검정이
여럿인 것은 정상이고, 그중 하나를 고르는 것은 사용자의 몫이다 .
"""

import pandas as pd
import pytest

from cases import vignettes

PASS_RATE = 0.90


def _candidates(tmp_path, monkeypatch, name: str):
    """vignette 하나를 세션으로 만들고 후보 목록을 받는다."""
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import Spec, build
    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    df, types, spec_kw, expect, why = vignettes.ALL[name]()
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    path = tmp_path / f"{name}.csv"
    df.to_csv(path, index=False)

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)

    doc = load_session(session)
    sid = main_source(doc)["id"]
    for col, typ in types.items():
        append_op(doc, "semantic_confirm", source=sid, column=col, type=typ)
    save_session(doc)

    from statop.analyze.spec import record

    fields = {k: v for k, v in spec_kw.items()
              if k in Spec.__dataclass_fields__}
    spec = Spec(**fields)
    # 사용자는 설계를 기록한 뒤(A1) 가정 검사(A3)를 돌리고 후보를 본다.
    # 기록 전에는 가정 검사가 돌지 않아 모수 검정이 초록으로 못 올라간다
    record(session, spec)
    res = build(session, spec)
    return shortlist(res), expect, why, res


def _hit(cands, expect: set) -> tuple[bool, list]:
    green = {c.id for c in cands if c.color == "green"}
    return bool(green & expect), sorted(green)


@pytest.mark.parametrize("name", sorted(vignettes.ALL))
def test_each_vignette_is_recorded(name, tmp_path, monkeypatch):
    """개별 건은 실패해도 전체 정답률로 판정한다 — 여기서는 돌아가는지만 본다."""
    cands, expect, why, res = _candidates(tmp_path, monkeypatch, name)
    assert cands or res.problems, f"{name}: 후보도 없고 사유도 없다"


def test_the_set_reaches_ninety_percent(tmp_path, monkeypatch, capsys):
    """전체 정답률 ≥ 90% — 이게  의 합격선이다."""
    rows, hits = [], 0
    for name in sorted(vignettes.ALL):
        cands, expect, why, res = _candidates(tmp_path / name, monkeypatch, name)
        ok, green = _hit(cands, expect)
        hits += ok
        rows.append((name, ok, sorted(expect), green, why))

    total = len(rows)
    rate = hits / total
    with capsys.disabled():
        print(f"\n  검정 선택 정확도 {hits}/{total} = {rate:.0%}")
        for name, ok, exp, green, why in rows:
            if not ok:
                print(f"    ⛔ {name} 기대 {exp} · 초록 {green}  ({why})")
    assert rate >= PASS_RATE, f"{hits}/{total} = {rate:.0%} < {PASS_RATE:.0%}"


def test_the_set_is_large_enough():
    """요구사항는 20~27건을 요구한다."""
    assert 20 <= len(vignettes.ALL) <= 27
