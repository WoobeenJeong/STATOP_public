"""규칙 DB 검증기 : 생성된 yaml 사이의 참조가 실제로 존재하는지 검사한다.

md에 "T-103/105 (R-04)"처럼 적힌 ID들이 정말 있는 규칙인지 확인한다. 오타·삭제된 ID를
가리키는 참조는 판정 엔진이 조용히 아무것도 안 하게 만들므로, 여기서 잡는다.
"""

import re
from dataclasses import dataclass, field

from statop.rules import build

# 문서 안에 섞여 있는 ID 참조를 뽑는 패턴 (T-101, C-05, P-201, R-04, S-R01, F-11, GR-02, SC-ERR-01, E-101-1)
_ID_RE = re.compile(r"\b(?:SC-[A-Z]+-\d+|S-[TR]\d+|GR-\d+|E-[\w-]*\d+|[TCPRF]-\d+)\b")


@dataclass
class Issue:
    kind: str  # broken_ref | duplicate | missing_field
    where: str  # 어느 항목에서
    detail: str


@dataclass
class Report:
    known: dict[str, int] = field(default_factory=dict)  # 종류별 등록 ID 수
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _collect_known() -> set[str]:
    """모든 yaml에서 '정의된' ID를 모은다."""
    ids: set[str] = set()
    _, st = build.build_semantic_types()
    _, sr = build.build_compat_rules()
    _, fn = build.build_derive_functions()
    _, tests = build.build_tests()
    _, cs = build.build_assumptions()
    _, post = build.build_post()
    _, verdicts = build.build_verdicts()
    _, gr = build.build_guardrails()
    _, sc = build.build_scores()
    _, err = build.build_errors()
    _, mb = build.build_models()

    ids |= {x["id"] for x in mb["questions"]} | {x["id"] for x in mb["tiers"]}
    ids |= {x["id"] for x in mb["checks"]}
    for coll in (st, sr, fn, cs, post, verdicts):
        ids |= {x["id"] for x in coll}
    ids |= {x["id"] for x in tests["tests"]} | {x["id"] for x in tests["questions"]}
    ids |= {g["id"] for g in gr["guardrails"]}
    ids |= {x["id"] for x in sc["scores"]}
    ids |= {x["id"] for x in err["errors"]}
    return ids


def _refs(text: str) -> set[str]:
    return set(_ID_RE.findall(text or ""))


def validate() -> Report:
    rep = Report()
    known = _collect_known()

    # 종류별 집계 (브리핑용)
    # 키는 영어 식별자 — 화면 표기는 messages 템플릿이 담당
    for prefix, label in (("T-", "tests"), ("C-", "assumptions"), ("P-", "post"),
                          ("R-", "verdicts"), ("Q-", "questions"), ("S-T", "semantic_types"),
                          ("S-R", "compat_rules"), ("F-", "derive_functions"),
                          ("GR-", "guardrails"), ("SC-", "scores"), ("E-", "errors"),
                          ("MB-Q", "model_questions"), ("MB-M", "model_tiers"),
                          ("MB-C", "model_checks")):
        rep.known[label] = sum(1 for i in known if i.startswith(prefix))

    # 각 규칙의 본문에서 참조를 뽑아 존재 여부 확인
    checked: list[tuple[str, str]] = []  # (출처, 텍스트)
    _, sr = build.build_compat_rules()
    checked += [(x["id"], f"{x['fix']} {x['why']}") for x in sr]
    _, cs = build.build_assumptions()
    checked += [(x["id"], f"{x['linked_tests']} {x['on_violation']}") for x in cs]
    _, verdicts = build.build_verdicts()
    checked += [(x["id"], f"{x['condition']} {x['verdict_raw']} {x['applies_to']}") for x in verdicts]
    _, tests = build.build_tests()
    checked += [(x["id"], f"{x['assumptions']} {x['alternatives']} {x['post']}") for x in tests["tests"]]
    _, err = build.build_errors()
    checked += [(x["id"], f"{x['detect']} {x['action']}") for x in err["errors"]]
    _, roles = build.build_metric_roles()
    _, mb = build.build_models()
    checked += [(x["id"], f"{x['goal']} {x['support']}") for x in roles["support_relations"]]
    checked += [(x["id"], f"{x['goal']} {x['guardrail']}") for x in roles["guardrail_relations"]]
    # 모듈 B 체크가 가리키는 가드레일·가정·오류가 실제로 있는지 (감사 전용이라 더 중요하다)
    checked += [(x["id"], f"{x['detect']} {x['action']}") for x in mb["checks"]]

    for where, text in checked:
        for ref in _refs(text) - known:
            rep.issues.append(Issue("broken_ref", where, ref))
    return rep
