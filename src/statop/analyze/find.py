"""규칙 DB 통합 검색 — "상관계수가 어디 있지?" 에 답한다.

지표는 여러 목록에 흩어져 있다: 점수(scores) · 검정(tests) · 보고 규칙(post) ·
지표 역할(metric_roles). 사용자는 어느 목록에 있는지 모른다 — 예를 들어 **상관계수는
점수 목록이 아니라 Q-03 연관 질문의 검정**이다. 목록을 가로질러 찾고, 찾은 것이
**어디에 있고 어떻게 가는지**까지 함께 돌려준다.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from statop.messages import msg

# 같은 뜻으로 통하는 말을 한 묶음으로. 하나만 쳐도 나머지로 함께 찾는다 —
# "상관"으로 쳐도 이름에 correlation 이 없는 Pearson r 이 걸려야 한다 (Q-03 연관)
_SYNONYM_GROUPS = [
    ("상관", "correlat", "연관", "associat", "pearson", "spearman", "kendall"),  # rule-vocab
    ("생존", "surviv", "사건 시간", "kaplan", "cox", "hazard"),  # rule-vocab
    ("차이", "differ", "비교", "t-test", "위치 비교"),  # rule-vocab
    ("분산", "varian", "등분산", "퍼짐"),  # rule-vocab
    ("일치", "agree", "재현성", "icc", "bland"),  # rule-vocab
    ("엔트로피", "entrop"), ("다양성", "divers", "shannon"),  # rule-vocab
    ("거리", "distan"), ("회귀", "regress"), ("추세", "trend", "경향"),  # rule-vocab
    ("조성", "composit", "심플렉스", "clr"),  # rule-vocab
    ("정규화", "normal"), ("보정", "correct", "다중검정"),  # rule-vocab
    ("분류", "classif", "auc"), ("오차", "error"),  # rule-vocab
    ("배치", "batch"), ("효과크기", "effect"),  # rule-vocab
    ("상호작용", "interact", "교호작용", "조절"),  # rule-vocab
    ("반복측정", "repeated", "반복"),  # rule-vocab
    ("대비", "contrast", "dunnett"),  # rule-vocab
    ("분포", "distribut", "형태"),  # rule-vocab
    ("결측", "missing", "대치", "imput"),  # rule-vocab
]


@dataclass
class Hit:
    id: str
    name: str
    kind: str                     # score | test | post | relation
    direct: bool = False          # 이름에 직접 걸렸는가 (질문 유형으로만 걸린 것과 구분)
    where: str = ""               # 어느 목록·어느 질문 유형에 있는가
    how: str = ""                 # 어떻게 가는가 (명령·화면)
    detail: str = ""


@dataclass
class Found:
    query: str
    terms: list = field(default_factory=list)
    hits: list = field(default_factory=list)


@lru_cache(maxsize=1)
def _sources() -> dict:
    import yaml

    from statop.rules.build import RULES_DIR

    def load(name: str):  # noqa: ANN202
        return yaml.safe_load((RULES_DIR / name).read_text(encoding="utf-8"))

    return {"scores": load("scores.yaml"), "tests": load("tests.yaml"),
            "post": load("post.yaml"), "roles": load("metric_roles.yaml")}


def _terms(query: str) -> list[str]:
    """검색어 + 짝이 되는 반대말 — 한국어로 쳐도 영어 이름이 걸리게."""
    q = query.strip().casefold()
    out = [q]
    for group in _SYNONYM_GROUPS:
        # 다 치기 전에도 열려야 한다 — 'cor' 만 쳐도 Pearson r 이 나와야 하므로
        # 묶음의 말을 **접두로** 치는 중인 경우도 같은 묶음으로 본다
        if any(w in q or (len(q) >= 3 and w.startswith(q)) for w in group):
            out += [w for w in group if w not in out]
    return out


def _hit(term: str, blob: str) -> bool:
    """영문은 **단어 시작**에서만 — 치는 대로 좁혀지되 남의 단어 속에 걸리지 않게.

    'cor' 는 'correlation' 을 찾아야 하고(접두), 'cox' 는 'Wilcoxon' 을 찾으면 안 된다
    (단어 중간). 뒤까지 막으면 접두 입력이 아무것도 못 찾는다.
    """
    if not term:
        return False
    if term.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}", blob) is not None
    return term in blob


def _matches(terms: list[str], *fields: object) -> bool:
    blob = " ".join(str(f) for f in fields if f).casefold()
    return any(_hit(t, blob) for t in terms)


def search(query: str, limit: int = 30) -> Found:
    """점수·검정·보고 규칙·역할 관계를 한 번에 찾는다."""
    if not query.strip():
        raise ValueError(msg("find_need_query"))
    terms = _terms(query)
    src = _sources()
    out = Found(query=query, terms=terms)

    questions = {q["id"]: q["question"] for q in src["tests"]["questions"]}
    user_words = {q["id"]: q.get("user_words", "") for q in src["tests"]["questions"]}
    for t in src["tests"]["tests"]:
        qid = t.get("question") or "?"
        # 질문 유형 이름까지 본다 — "상관"은 Q-03 '연관'에 있고 검정 이름에는 없다
        if not _matches(terms, t["id"], t["name"], t.get("design"),
                        t.get("best_when"), t.get("effect_size"),
                        qid, questions.get(qid, ""), user_words.get(qid, "")):
            continue
        # 이름에 직접 걸린 것이 질문 유형으로만 걸린 것보다 앞이다
        direct = _matches(terms, t["id"], t["name"], t.get("effect_size"))
        out.hits.append(Hit(
            id=t["id"], name=t["name"], kind="test", direct=direct,
            where=msg("find_where_test", q=qid, qname=questions.get(qid, "")),
            how=msg("find_how_test", q=qid, id=t["id"]),
            detail=t.get("design") or t.get("best_when") or ""))

    for s in src["scores"]["scores"]:
        if not _matches(terms, s["id"], s["name"], s.get("section"), s.get("note"),
                        s.get("input")):
            continue
        out.hits.append(Hit(
            id=s["id"], name=s["name"], kind="score",
            direct=_matches(terms, s["id"], s["name"]),
            where=msg("find_where_score", section=s.get("section", "")),
            how=msg("find_how_score", id=s["id"]),
            detail=s.get("input") or ""))

    for p in src["post"]:
        if not _matches(terms, p["id"], p["name"], p.get("applies_to")):
            continue
        out.hits.append(Hit(
            id=p["id"], name=p["name"], kind="post",
            where=msg("find_where_post", kind=p.get("kind", "")),
            how=msg("find_how_post"), detail=p.get("applies_to") or ""))

    rel = src["roles"]
    for r in rel["support_relations"] + rel["guardrail_relations"]:
        val = r.get("support") or r.get("guardrail") or ""
        if not _matches(terms, r["id"], r.get("goal"), val):
            continue
        out.hits.append(Hit(
            id=r["id"], name=f"{r.get('goal')} → {val}", kind="relation",
            where=msg("find_where_relation"), how=msg("find_how_relation"),
            detail=str(r.get("why") or r.get("tradeoff") or "")))

    # 검정이 먼저다 — 사용자가 찾는 것은 대개 "무엇으로 재는가"이고 그것은 검정에 있다
    rank = {"test": 0, "score": 1, "post": 2, "relation": 3}
    out.hits.sort(key=lambda h: (rank[h.kind], not h.direct, h.id))
    out.hits = out.hits[:limit]
    return out


def question_of(test_id: str) -> str:
    """이 검정이 어느 질문 유형에 속하는지 — 화면에서 그 유형을 고르면 후보로 뜬다."""
    for t in _sources()["tests"]["tests"]:
        if t["id"] == test_id:
            return t.get("question") or ""
    return ""


def by_question() -> list[dict]:
    """질문 유형 11종과 그 아래 검정들 — 이름을 모를 때는 갈래로 찾아 들어간다.

    검색은 이름을 알아야 되고, 갈래는 이름을 몰라도 된다. 둘 다 있어야 한다.
    """
    src = _sources()
    tests: dict[str, list] = {}
    for t in src["tests"]["tests"]:
        tests.setdefault(t.get("question") or "?", []).append({
            "id": t["id"], "name": t["name"], "design": t.get("design") or "",
            "best_when": t.get("best_when") or "",
            "effect_size": t.get("effect_size") or "",
        })
    out = []
    for q in src["tests"]["questions"]:
        out.append({"id": q["id"], "question": q["question"],
                    "user_words": q.get("user_words") or "",
                    "tests": tests.get(q["id"], [])})
    return out
