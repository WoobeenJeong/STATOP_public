"""S213 A6 논문 앵커 — 검색어를 만드는 규칙과 **원자료가 안 나가는 것**을 본다.

네트워크는 있을 수도 없을 수도 있다. 그래서 **네트워크 없이도 도는 검사**를 기본으로
두고, 실제 조회는 붙을 때만 돈다 — CI 가 남의 서버 상태에 흔들리면 안 된다.
"""

import numpy as np
import pandas as pd
import pytest

MARK = "ZQX7SECRET"


@pytest.fixture
def session(tmp_path, monkeypatch):
    """검정을 한 번 돌려 둔 세션 — 셀 값에 표식을 심는다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(2)
    n = 200
    g = rng.choice(["case", "control"], n)
    path = tmp_path / "d.csv"
    pd.DataFrame({"sid": [f"{MARK}{i}" for i in range(n)], "arm": g,
                  "y": rng.normal(0, 1, n) + (g == "case") * 0.6}).to_csv(path, index=False)

    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)

    doc = load_session(s)
    sid = main_source(doc)["id"]
    for col, typ in (("sid", "id"), ("arm", "label"), ("y", "continuous")):
        append_op(doc, "semantic_confirm", source=sid, column=col, type=typ)
    save_session(doc)
    record(s, Spec(question="Q-01", y="y", group="arm"))
    run_test(s, "T-104")
    return s


def test_the_test_name_comes_first(session):
    """검정 이름이 가장 강한 앵커다 — 질문 유형만으로 찾으면 아무 논문이나 나온다."""
    from statop.hypothesis.refs import terms_from

    terms = terms_from(session)
    assert terms, "검색어 조각이 없다"
    assert "Brunner" in terms[0], terms
    assert "group difference" in terms      # 질문 유형은 영문으로 (한국어면 0건)


def test_no_cell_value_leaves_the_machine(session):
    """나가는 것은 검정 이름·질문 유형·군 라벨뿐이다 — 셀 값은 아니다."""
    from statop.hypothesis.refs import terms_from

    joined = " ".join(terms_from(session))
    assert MARK not in joined, f"셀 값이 검색어에 들어갔다: {joined}"


def test_labels_can_be_left_out(session):
    """군 라벨조차 식별이 될 수 있는 자리가 있다 — 끌 수 있어야 한다."""
    from statop.hypothesis.refs import terms_from

    with_labels = terms_from(session, include_labels=True)
    without = terms_from(session, include_labels=False)
    assert len(without) <= len(with_labels)
    assert all(t in with_labels for t in without)


def test_a_network_failure_is_reported_not_swallowed(session, monkeypatch):
    """못 가져온 것을 '논문 없음'으로 보이게 하면 안 된다."""
    from statop.hypothesis import refs

    def boom(*a, **kw):
        raise OSError("no route to host")

    monkeypatch.setattr(refs.urllib.request, "urlopen", boom)
    a = refs.build(session)
    assert not a.papers
    assert a.failed, "네트워크가 없는데 조용히 빈 목록을 돌려줬다"
    assert "OSError" in a.failed


def test_nothing_to_search_says_so(tmp_path, monkeypatch):
    """검정도 설계도 없으면 지어내지 않고 그렇다고 말한다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(tmp_path / "x.csv", index=False)

    from statop.hypothesis.refs import build
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(tmp_path / "x.csv"))
    sc.toggle_page()
    sc.import_picked()
    a = build(str(sc.session_file))
    assert not a.papers and a.failed


def test_results_are_sorted_by_relevance():
    """기본(최신순)이면 낱말이 스쳐 나온 최신 논문이 위로 온다 — 실측으로 그랬다."""
    import inspect

    from statop.hypothesis import refs

    assert "sort=relevance" in inspect.getsource(refs.search)


@pytest.mark.network
def test_a_real_lookup_returns_titles_and_pmids(session):
    """네트워크가 붙어 있으면 실제로 제목·PMID 가 온다."""
    from statop.hypothesis.refs import build

    a = build(session, limit=3)
    if a.failed:
        pytest.skip(f"네트워크 없음: {a.failed}")
    assert a.papers, a.query
    for p in a.papers:
        assert p.pmid.isdigit() and p.title
        assert p.url.endswith(f"/{p.pmid}/")
