"""세션 리포트 (~) — 이 세션에서 한 일 전체를 파일 하나로.

새 분석이 아니다: 세션에 **기록된 것**을 모아 md/json/html 로 포장한다.
기록에 없는 것은 리포트에도 없다 — "한 것처럼" 쓰는 문서가 되면 안 된다.

계획의 `statop check <path>` 는 세션 기반으로 바뀌었다 — 조작 이력·검정·가설이
전부 세션에 있으므로 파일 경로만으로는 재현 가능한 리포트를 만들 수 없다.
"""

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

from statop.analyze.points import EXCLUDE_RED
from statop.messages import msg


@dataclass
class ReportData:
    session_id: str
    created: str
    source: dict | None
    n_ops: int
    ops_summary: dict = field(default_factory=dict)     # 종류별 개수·핵심 내용
    types: dict = field(default_factory=dict)
    derived: list = field(default_factory=list)
    label_maps: dict = field(default_factory=dict)
    relabels: list = field(default_factory=list)
    excluded: list = field(default_factory=list)       # 뺀 개별 샘플 — 사유와 함께
    exclude_ratio: float = 0.0                         # 제외 비율 ( 10% 임계)
    n_rows_base: int = 0
    filters: list = field(default_factory=list)
    missing_ops: list = field(default_factory=list)
    guardrail: dict | None = None
    spec: dict | None = None
    test_results: list = field(default_factory=list)
    hypothesis: dict | None = None
    notices: list = field(default_factory=list)         # 부분해시 등 상시 고지


def collect(session_file: str, sample_n: int = 10_000) -> ReportData:
    """세션에서 리포트 재료를 모은다. 가드레일은 스펙이 있을 때만 즉석 계산한다."""
    from statop.analyze.spec import current
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    st = replay(doc)
    sid = src["id"] if src else None

    kinds: dict[str, int] = {}
    for op in doc["ops"]:
        kinds[op["op"]] = kinds.get(op["op"], 0) + 1

    data = ReportData(
        session_id=doc["session_id"], created=doc["created"], source=src,
        n_ops=len(doc["ops"]), ops_summary=kinds,
        types=st["semantic_types"].get(sid, {}),
        derived=[d for d in st["derived"] if d.get("source") == sid],
        label_maps=st["label_maps"].get(sid, {}),
        relabels=st["relabels"], excluded=st["excluded"], filters=st["filters"],
        missing_ops=st["missing_ops"],
        test_results=st["test_results"],
        notices=[msg("notice_partial_hash")],
    )

    if data.excluded:
        # 제외 비율은 지금 데이터로 세야 한다 — 기록만으로는 분모를 알 수 없다
        from statop.analyze.points import status as exclude_status

        try:
            est = exclude_status(session_file, sample_n)
            data.exclude_ratio, data.n_rows_base = est.ratio, est.n_total
        except ValueError:
            pass

    spec = current(session_file)
    if spec is not None:
        data.spec = spec.as_dict()
        # 가드레일 — 세션에 기록되는 op 가 아니므로 지금 상태로 계산해 명시한다
        try:
            from statop.derive.service import apply_ops, session_frame
            from statop.guard.pipeline import run
            from statop.guard.report import to_dict

            gdoc, gsrc, df = session_frame(session_file, sample_n)
            df = apply_ops(df, gdoc, gsrc["id"])
            # 연속 x(Q-03)는 군이 아니다 — 군으로 세면 "최소 군 n=1" 같은 헛경고가 난다
            grouping = {"label", "nominal code", "ordinal code"}
            gcol = spec.group if data.types.get(spec.group) in grouping else None
            data.guardrail = to_dict(run(df, data.types, group_col=gcol))
        except Exception:  # noqa: BLE001 — 가드레일 실패가 리포트 전체를 막으면 안 된다
            data.guardrail = None
        if data.test_results:
            from statop.hypothesis.mech import build_report

            rep = build_report(session_file)
            data.hypothesis = {
                "proposals": [{"title": h.title, "statement": h.statement,
                               "interpretation": h.interpretation,
                               "direction": h.direction} for h in rep.proposals],
                "cautions": rep.cautions, "companions": rep.companions,
                "guardrail": rep.guardrail, "basis": rep.basis,
                "source": rep.source,
            }
    return data


# ── json ─────────────────────────────────────────────────────
def to_json(data: ReportData) -> str:
    from dataclasses import asdict

    return json.dumps(asdict(data), ensure_ascii=False, indent=1, default=str)


# ── markdown ─────────────────────────────────────────────────
def to_markdown(data: ReportData) -> str:
    L: list[str] = []
    src_name = Path(data.source["path"]).name if data.source else "-"
    L.append(f"# {msg('report_title', name=src_name)}")
    L.append("")
    L.append(f"- {msg('report_session', sid=data.session_id, created=data.created)}")
    if data.source:
        h = data.source["hash"]
        L.append(f"- {msg('report_source', path=data.source['path'], hash12=h['value'][:12], mode=h['mode'])}")
    L.append(f"- {msg('report_generated', ts=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))}")
    L.append("")

    # 조작 이력 — 무엇을 얼마나 했는지 (재현의 뼈대)
    L.append(f"## {msg('report_ops_head', n=data.n_ops)}")
    L.append("")
    for kind, n in sorted(data.ops_summary.items()):
        L.append(f"- `{kind}` × {n}")
    for f in data.filters:
        L.append(f"- {msg('report_filter_line', expr=f['expr'], reason=f.get('reason') or '-')}")
    for m in data.missing_ops:
        L.append(f"- {msg('report_missing_line', op=m['op'], detail=str({k: v for k, v in m.items() if k not in ('op', 'seq', 'source')})[:80])}")
    for d in data.derived:
        eps = f", eps={d['eps']:g}" if d.get("eps") is not None else ""
        L.append(f"- {msg('report_derive_line', name=d['name'], expr=d['expr'], eps=eps)}")
    for col, mapping in data.label_maps.items():
        L.append(f"- {msg('report_labelmap_line', col=col, mapping=mapping)}")
    if data.relabels:
        L.append(f"- **{msg('report_relabel_line', n=len(data.relabels))}**")
    if data.excluded:
        # 무엇을 왜 뺐는지는 숨길 수 없다 — 사유를 하나씩 적는다
        L.append(f"- **{msg('report_excluded_line', n=len(data.excluded))}**")
        for e in data.excluded:
            L.append(f"  - {msg('report_excluded_row', key=e['key'], col=e['key_column'], reason=e.get('note') or '-')}")
        if data.exclude_ratio > EXCLUDE_RED:
            # 10%를 넘으면 표본을 고른 것이다 — 보고서 본문에서 빨간 줄로
            L.append(f"  - **{msg('points_excl_red', n=len(data.excluded), total=data.n_rows_base, ratio=data.exclude_ratio)}**")
    L.append("")

    if data.types:
        L.append(f"## {msg('report_types_head', n=len(data.types))}")
        L.append("")
        for col, t in data.types.items():
            L.append(f"- {col}: **{t}**")
        L.append("")

    if data.guardrail is not None:
        L.append(f"## {msg('report_guard_head')}")
        L.append("")
        if data.guardrail.get("headline"):
            L.append(f"> **{data.guardrail['headline']}**")
            L.append("")
        for f in data.guardrail.get("findings", []):
            L.append(f"- [{f['tier']}] {f['rule']} `{f['check']}` — {f['detail']}")
        for s in data.guardrail.get("skipped", []):
            L.append(f"- ({msg('report_guard_skipped')}) {s['rule']} — {s['reason']}")
        L.append("")

    if data.spec:
        sp = data.spec
        L.append(f"## {msg('report_spec_head')}")
        L.append("")
        L.append(f"- {msg('report_spec_line', q=sp['question'], y=sp['y'], group=sp.get('group') or '-', paired=sp['paired'], direction=sp['direction'], n=sp['n_tests'])}")
        L.append("")

    if data.test_results:
        L.append(f"## {msg('report_tests_head', n=len(data.test_results))}")
        L.append("")
        L.append(f"| {msg('report_tests_cols')} |")
        L.append("|---|---|---|---|---|")
        for r in data.test_results:
            eff = r.get("effect") or {}
            ci = (f" ({eff['ci_low']:.3g}~{eff['ci_high']:.3g})"
                  if eff.get("ci_low") is not None else "")
            L.append(f"| {r['test']} {r['name']} | {r.get('statistic'):.4g} "
                     f"| {r.get('p'):.3g} | {eff.get('name', '-')}="
                     f"{eff.get('value'):.3g}{ci} | α={r.get('alpha_adjusted'):.3g} |")
        L.append("")

    if data.hypothesis:
        hy = data.hypothesis
        L.append(f"## {msg('report_hypo_head')}")
        L.append("")
        for p in hy["proposals"]:
            L.append(f"### {p['title']}")
            L.append("")
            L.append(f"> {p['statement']}")
            L.append("")
            L.append(f"{p['interpretation']}")
            L.append("")
        if hy["cautions"]:
            L.append(f"### {msg('hypo_cautions_head')}")
            L.append("")
            L += [f"- {c}" for c in hy["cautions"]] + [""]
        if hy["companions"]:
            L.append(f"### {msg('hypo_companions_head')}")
            L.append("")
            L += [f"- {c}" for c in hy["companions"]] + [""]

    L.append("---")
    for n in data.notices:
        L.append(f"*{n}*")
    return "\n".join(L).rstrip() + "\n"


# ── html  — md 를 우리 스타일로 감싼다 ─────────────────
_HTML_STYLE = """
body { max-width: 860px; margin: 2rem auto; padding: 0 1rem; line-height: 1.65;
  font-family: system-ui, -apple-system, 'Noto Sans KR', sans-serif; color: #141a18; }
h1 { border-bottom: 2px solid #141a18; padding-bottom: .4rem; }
h2 { color: #0b6e63; margin-top: 2rem; }
blockquote { border-left: 3px solid #0b6e63; margin: 0; padding: .2rem .9rem;
  background: #f0f5f4; }
code { background: #eef1ef; padding: .1em .3em; border-radius: 2px; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { border: 1px solid #dde2dd; padding: .35rem .6rem; text-align: left; }
"""


def to_html(data: ReportData) -> str:
    """md → 최소 html. 외부 의존 없이 열리는 한 파일."""
    import html as _h
    import re

    md = to_markdown(data)
    out, in_table = [], False
    for line in md.split("\n"):
        e = _h.escape(line)
        e = re.sub(r"`([^`]+)`", r"<code>\1</code>", e)
        e = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", e)
        e = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", e)
        if line.startswith("| ") and "---" not in line:
            cells = [c.strip() for c in e.split("|")[1:-1]]
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table and not line.startswith("|"):
            out.append("</table>")
            in_table = False
        if "---" in line and line.startswith("|"):
            continue
        if line.startswith("# "):
            out.append(f"<h1>{e[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{e[3:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{e[4:]}</h3>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{e[5:]}</blockquote>")
        elif line.startswith("- "):
            out.append(f"<li>{e[2:]}</li>")
        elif line == "---":
            out.append("<hr>")
        elif line:
            out.append(f"<p>{e}</p>")
    if in_table:
        out.append("</table>")
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            f"<title>STATOP report</title><style>{_HTML_STYLE}</style></head><body>"
            + "\n".join(out) + "</body></html>")


FORMATS = {"md": to_markdown, "json": to_json, "html": to_html}


def write(session_file: str, out_path: str, fmt: str | None = None,
          sample_n: int = 10_000) -> Path:
    p = Path(out_path)
    fmt = fmt or p.suffix.lstrip(".").lower() or "md"
    if fmt not in FORMATS:
        raise ValueError(msg("report_bad_format", allowed="|".join(FORMATS), fmt=fmt))
    data = collect(session_file, sample_n=sample_n)
    p.write_text(FORMATS[fmt](data), encoding="utf-8")
    return p
