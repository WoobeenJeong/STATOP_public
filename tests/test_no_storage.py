"""S209 무저장 보장 검수 — **서버 디스크에 원자료 사본이 생기는 경로 0**.

이 도구의 약속 중 하나다 (요구사항8절): 남기는 것은 원본 경로·해시와 조작 로그뿐이고,
셀 값은 어디에도 남지 않는다. 약속은 문서가 아니라 **검사**로 지켜야 한다.

방법: 셀 값을 **그 자료에만 있는 표식 문자열**로 심고, 전 기능을 한 바퀴 돌린 뒤
STATOP_HOME 아래 모든 파일을 훑어 그 표식이 나오는지 본다. 나오면 그 경로가 곧 누설 지점이다.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 이 문자열이 파일에 남으면 셀 값이 샌 것이다 — 다른 데서 나올 수 없게 독특하게
MARK = "ZQX7MARKER"


def _leaks(root: Path) -> list[str]:
    """MARK 가 들어 있는 파일 경로 — 원자료가 샌 자리."""
    out = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        try:
            if MARK in f.read_text(errors="ignore"):
                out.append(str(f))
        except OSError:
            continue
    return out


@pytest.fixture
def marked(tmp_path, monkeypatch):
    """셀 값마다 표식이 박힌 자료 + 그것으로 만든 세션."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(1)
    n = 120
    path = tmp_path / "marked.csv"
    pd.DataFrame({
        "sid": [f"{MARK}{i:03d}" for i in range(n)],
        "arm": rng.choice([f"{MARK}_case", f"{MARK}_ctrl"], n),
        "v": rng.normal(0, 1, n),
        "cnt": rng.poisson(4, n),
    }).to_csv(path, index=False)

    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    return str(sc.session_file), str(path), tmp_path / "home"


def test_the_session_log_holds_no_cell_values(marked):
    """세션 로그에 남는 것은 경로·해시·조작뿐이다."""
    session, path, home = marked
    doc = json.loads(Path(session).read_text())
    text = json.dumps(doc, ensure_ascii=False)
    # 원본 **경로**에는 파일 이름이 들어가므로 그 부분만 빼고 본다
    text = text.replace(path, "").replace(Path(path).name, "")
    assert MARK not in text, "세션 로그에 셀 값이 들어 있다"


def test_a_full_run_leaves_no_copy_of_the_data(marked):
    """전 기능을 한 바퀴 돌려도 STATOP_HOME 에 셀 값이 남지 않는다."""
    from statop.analyze.scores import catalog
    from statop.derive.service import apply_ops, commit, prepare, session_frame
    from statop.groups import compose, detect
    from statop.semantic import infer_columns
    from statop.session.core import append_op, load_session, main_source, save_session

    session, path, home = marked
    doc = load_session(session)
    sid = main_source(doc)["id"]

    _, src, df = session_frame(session)
    commit(doc, src["id"], df, prepare(df, "log(cnt + 1)"), "lg", eps=None)
    append_op(doc, "semantic_confirm", source=sid, column="v", type="continuous")
    append_op(doc, "semantic_confirm", source=sid, column="arm", type="label")
    save_session(doc)

    doc = load_session(session)
    _, src, df = session_frame(session)
    df = apply_ops(df, doc, src["id"])
    infer_columns(df, [c for c in df.columns])
    compose(df, list(df.columns), [])
    detect(df)
    catalog(session)

    leaked = _leaks(Path(home))
    assert not leaked, f"원자료가 남은 파일: {leaked}"


def test_a_report_carries_the_path_and_hash_but_not_the_values(marked, tmp_path):
    """리포트는 '무엇을 근거로 했는지'를 남겨야 하지만 셀 값은 아니다."""
    from statop.report import write

    session, path, home = marked
    out = tmp_path / "r.md"
    write(session, str(out))
    text = out.read_text()
    assert path in text, "원본 경로가 없으면 나중에 대조할 수 없다"
    assert MARK not in text.replace(path, ""), "리포트에 셀 값이 들어 있다"


def test_the_column_screen_shows_no_cell_values(marked):
    """화면에 값이 보이면 캡처만으로도 자료가 샌다 ."""
    import re

    from statop.shell.screen import Screen

    session, path, home = marked
    sc = Screen()
    sc.open_path(path)
    rendered = re.sub(r"</?[a-z.]+>", "", sc.render_table())
    assert MARK not in rendered
