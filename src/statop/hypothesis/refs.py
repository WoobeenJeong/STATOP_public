"""A6 논문 앵커  — 이 세션이 한 일과 **비슷한 논문**을 찾아 제목·PMID 를 붙인다.

세션에서 **검색어를 만들 재료**를 꺼낸다: 질문 유형(Q-xx)의 말, 실행한 검정 이름,
확정된 의미 타입, 군 라벨. 그것으로 PubMed(E-utilities)를 검색한다.

지켜야 할 것:
- **원자료는 나가지 않는다.** 나가는 것은 검정 이름·질문 유형·군 **라벨 이름**뿐이다.
  라벨 이름조차 식별이 될 수 있는 자리라면 `include_labels=False` 로 끈다
- **네트워크가 없으면 없다고 말한다.** 지어내지 않고, 추측 목록도 만들지 않는다
- v1 은 **제목 수준**이다 (요구사항). 본문·그림 해석은 하지 않는다
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from statop.messages import msg

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 8.0


@dataclass
class Paper:
    pmid: str
    title: str
    journal: str = ""
    year: str = ""

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


@dataclass
class Anchors:
    query: str = ""
    terms: list = field(default_factory=list)   # 검색어를 이루는 조각 (사람이 검토하게)
    papers: list = field(default_factory=list)
    failed: str = ""                            # 못 가져왔으면 그 이유
    broadened: bool = False                     # 좁은 질의로 0건이라 넓혀서 찾았는가


# 질문 유형의 **영문 검색어**. 규칙표의 질문 문구는 한국어라(registry-prompts 0절)
# 그대로 보내면 PubMed 에서 한 건도 안 나온다 — 실측으로 0건이었다.
# 논문 검색용 낱말일 뿐 판정에 쓰이지 않으므로 여기에 둔다.
_Q_EN = {
    "Q-01": "group difference",
    "Q-02": "proportion difference",
    "Q-03": "correlation",
    "Q-04": "interaction effect",
    "Q-05": "dose response trend",
    "Q-06": "agreement reproducibility",
    "Q-07": "distribution comparison",
    "Q-08": "regression prediction",
    "Q-09": "survival analysis",
    "Q-10": "compositional data",
    "Q-11": "planned contrast",
    "Q-12": "sample size representativeness",
}


def terms_from(session_file: str, include_labels: bool = True) -> list[str]:
    """세션에서 검색어 조각을 꺼낸다 — **셀 값은 꺼내지 않는다.**"""
    from statop.analyze.spec import current, questions
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    st = replay(doc)
    src = main_source(doc)
    sid = src["id"] if src else ""
    out: list[str] = []

    # **검정 이름을 먼저** 둔다 — 영문 고유명사라 그 방법을 다룬 논문으로 곧장 간다.
    # 질문 유형("group difference")만으로 찾으면 아무 임상 논문이나 나온다 (실측)
    for r in st["test_results"][-2:]:
        if r.get("name"):
            out.append(r["name"].replace("\u2013", "-"))
    spec = current(session_file)
    if spec is not None:
        out.append(_Q_EN.get(spec.question, ""))
    if include_labels and spec is not None and spec.group:
        levels = st["label_maps"].get(sid, {}).get(spec.group)
        if levels:
            out += [str(v) for v in list(levels)[:2]]
    # 의미 타입 중 **분야 낱말이 되는 것**만 (log-scale 같은 내부 용어는 안 보낸다)
    types = set(st["semantic_types"].get(sid, {}).values())
    if "composition set" in types:
        out.append("compositional data")
    return [t for t in dict.fromkeys(out) if t]


def search(query: str, limit: int = 5) -> tuple[list, str]:
    """PubMed 검색 → (논문 목록, 실패 사유). 네트워크가 없으면 목록이 비고 사유가 찬다."""
    try:
        # **관련도순**으로 받는다. 기본은 최신순이라, 같은 낱말이 스쳐 나온 최신 논문이
        # 위로 올라오고 정작 그 방법을 다룬 논문은 안 보인다 (실측으로 그랬다)
        url = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&sort=relevance"
               f"&retmax={limit}&term={urllib.parse.quote(query)}")
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            ids = json.loads(r.read().decode())["esearchresult"]["idlist"]
        if not ids:
            return [], ""
        url2 = (f"{EUTILS}/esummary.fcgi?db=pubmed&retmode=json"
                f"&id={','.join(ids)}")
        with urllib.request.urlopen(url2, timeout=TIMEOUT) as r:
            res = json.loads(r.read().decode())["result"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        # 못 가져온 것을 "논문 없음"으로 보이게 하면 안 된다 — 이유를 들고 돌아간다
        return [], msg("refs_offline", why=f"{type(e).__name__}: {str(e)[:80]}")

    out = []
    for i in ids:
        it = res.get(i) or {}
        out.append(Paper(pmid=i, title=(it.get("title") or "").rstrip("."),
                         journal=it.get("source", ""),
                         year=(it.get("pubdate") or "")[:4]))
    return out, ""


def build(session_file: str, limit: int = 5,
          include_labels: bool = True) -> Anchors:
    """이 세션에 붙일 논문 앵커."""
    terms = terms_from(session_file, include_labels=include_labels)
    if not terms:
        return Anchors(failed=msg("refs_nothing_to_search"))
    # AND 로 넷을 묶으면 0건이 된다 (실측). 강한 낱말 둘로 좁히고, 그래도 없으면
    # 하나로 다시 본다 — "없음"과 "너무 좁혔음"은 다르다
    def q_of(n: int) -> str:
        return " AND ".join(f'"{t}"' if " " in t else t for t in terms[:n])

    for n in (2, 1):
        query = q_of(n)
        papers, failed = search(query, limit=limit)
        if papers or failed:
            broad = n == 1 and len(terms) > 1
            return Anchors(query=query, terms=terms, papers=papers, failed=failed,
                           broadened=broad)
    return Anchors(query=q_of(2), terms=terms, papers=[], failed="")
