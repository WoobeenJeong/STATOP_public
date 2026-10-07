"""M4 가드레일 출력  — md와 json.

차단이 있으면 **맨 앞줄**이 차단 요약이다. 검사하지 않은 것도 함께 적는다 —
검사하지 않은 것과 통과한 것은 다르고, 그 차이를 감추면 리포트가 거짓말을 한다.
"""

import json

from statop.guard.pipeline import GuardReport, headline
from statop.messages import msg


def to_dict(rep: GuardReport) -> dict:
    return {
        "tier": rep.tier,
        "headline": headline(rep),
        "order": rep.order,
        "findings": [{"rule": f.rule, "check": f.check, "tier": f.tier,
                      "detail": f.detail, "numbers": f.numbers,
                      "columns": f.columns, "links": f.links}
                     for f in rep.findings],
        "skipped": rep.skipped,
        "overrides": rep.overrides,
        "cause_trace": rep.cause_trace,
    }


def to_json(rep: GuardReport, indent: int = 1) -> str:
    return json.dumps(to_dict(rep), ensure_ascii=False, indent=indent, default=str)


def to_markdown(rep: GuardReport) -> str:
    tier_label = msg(f"guard_tier_{rep.tier}")
    lines = []
    head = headline(rep)
    if head:
        lines += [f"> **{head}**", ""]     # 스크롤해야 보이는 경고는 없는 것과 같다
    lines += [f"# {msg('guard_head', n=len(rep.findings), tier=tier_label)}", ""]

    for rule in rep.order:
        items = [f for f in rep.findings if f.rule == rule]
        if not items:
            continue
        lines += [f"## {rule}", ""]
        for f in items:
            lines.append(f"- **[{msg(f'guard_tier_{f.tier}')}]** `{f.check}` — {f.detail}")
            if f.links:
                lines.append(f"  - {msg('guard_link_line', links=', '.join(f.links))}")
        lines.append("")

    if rep.cause_trace:
        lines += [f"## {msg('guard_cause_head')}", ""]
        if rep.cause_trace.get("candidate") == "loss":
            lines.append(f"- {msg('guard_cause_loss')}")
        cf = rep.cause_trace.get("counterfactual") or {}
        if cf.get("available"):
            key = "guard_counterfactual_resolved" if cf.get("resolved") \
                else "guard_counterfactual_unresolved"
            lines.append(f"- {msg(key, p=cf.get('p_restored') or float('nan'))}")
        if rep.cause_trace.get("branch"):
            lines.append(f"- {rep.cause_trace['branch']}")
        lines.append("")

    if rep.skipped:
        lines += [f"## {msg('guard_skipped_head')}", ""]
        lines += [f"- {s['rule']} — {s['reason']}" for s in rep.skipped] + [""]

    if rep.overrides:
        lines += [f"## {msg('guard_override_head')}", ""]
        lines += [f"- {msg('guard_override_line', **o)}" for o in rep.overrides] + [""]

    return "\n".join(lines).rstrip() + "\n"
