"""M4 실행 순서  — GR-03 → GR-02 → GR-04 → GR-01.

**진단 순서이지 인과 순서가 아니다.** 앞 검사 결과가 뒤 검사의 입력이 되기 때문에
이 순서로 돈다: 손실을 먼저 재고(GR-03), 그 손실률로 SRM의 원인 후보를 짚고(GR-02),
남은 관측의 불균형을 보고(GR-04), 마지막에 값 자체의 정의역을 본다(GR-01).

차단(gate)이 하나라도 있으면 **출력 맨 앞에** 요약이 붙는다 — 아래로 스크롤해야
보이는 경고는 없는 것과 같다.
"""

from dataclasses import dataclass, field

from statop.guard import checks, locks
from statop.messages import msg


@dataclass
class Finding:
    rule: str
    check: str
    tier: str                  # 잠금이 정한 최종 등급
    detail: str
    numbers: dict = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)   # 다른 검사와의 연결


@dataclass
class GuardReport:
    findings: list[Finding] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)   # 무엇을 못 봤는지도 말한다
    overrides: list[dict] = field(default_factory=list)
    cause_trace: dict = field(default_factory=dict)

    @property
    def tier(self) -> str:
        if any(f.tier == "gate" for f in self.findings):
            return "gate"
        if any(f.tier == "diagnostic" for f in self.findings):
            return "diagnostic"
        return "ok"

    @property
    def gates(self) -> list[Finding]:
        return [f for f in self.findings if f.tier == "gate"]


def _tier(rule: str, hint: str, lock_path=None) -> str:
    """규칙 등급과 검사 등급 중 **약한 쪽**을 쓴다.

    규칙 전체를 gate로 올려도 하위 진단 검사까지 차단이 되면 안 되고,
    사용자가 규칙을 내려도 floor 아래로는 안 간다 (tier_of가 이미 막는다).
    """
    rule_tier = locks.tier_of(rule, lock_path)
    order = locks.TIER_ORDER
    return hint if order.get(hint, 0) <= order.get(rule_tier, 0) else rule_tier


def run(df, types: dict[str, str], group_col: str | None = None,
        meta_cols: list[str] | None = None,
        metric_cols: list[str] | None = None,
        df_before=None, kept_index=None,
        retention_steps: list[dict] | None = None,
        expected_ratio: dict[str, float] | None = None,
        lock_path=None) -> GuardReport:
    """가드레일 전체를 순서대로 돌린다.

    df_before/kept_index: 손실 검사(GR-03)의 재료. 없으면 손실을 못 보므로
    "봤다"고 하지 않고 skipped에 남긴다 — 검사하지 않은 것과 통과한 것은 다르다.
    """
    rep = GuardReport(order=locks.execution_order())
    meta_cols = meta_cols or []
    metric_cols = metric_cols or []
    rep.overrides = [{"rule": x.rule, "key": x.key, "value": x.value, "base": x.base}
                     for x in locks.active_overrides(lock_path)]

    def add(sig: checks.Signal, links: list[str] | None = None) -> None:
        rep.findings.append(Finding(rule=sig.rule, check=sig.check,
                                    tier=_tier(sig.rule, sig.tier_hint, lock_path),
                                    detail=sig.detail, numbers=sig.numbers,
                                    columns=sig.columns, links=links or []))

    def skip(rule: str, why: str) -> None:
        rep.skipped.append({"rule": rule, "reason": why})

    # ── GR-03 손실·조인 ─────────────────────────────────────
    g3 = {k: v.value for k, v in locks.limits("GR-03", lock_path).items()}
    loss_signal = None
    if retention_steps:
        for s in checks.retention_funnel(retention_steps):
            add(s)
    if df_before is not None and kept_index is not None:
        bias_cols = ([group_col] if group_col else []) + meta_cols
        for s in checks.biased_loss(df_before, kept_index, bias_cols,
                                    p_threshold=g3["bias_p_threshold"]):
            add(s)
        if group_col and group_col in df_before.columns:
            loss_signal = checks.loss_by_group(df_before, kept_index, group_col)
            add(loss_signal)
    else:
        skip("GR-03", msg("guard_skip_no_loss_data"))

    # ── GR-02 SRM ───────────────────────────────────────────
    g2 = {k: v.value for k, v in locks.limits("GR-02", lock_path).items()}
    ratio = expected_ratio or g2["expected_ratio"]
    if group_col and group_col in df.columns:
        counts = df[group_col].value_counts().to_dict()
        sig = checks.srm(counts, ratio, g2["p_threshold"])
        if sig.hit:
            # 원인 추적  — 손실률과 연결해 **후보**만 제시한다. 인과는 단정하지 않는다
            links, trace = [], {}
            if loss_signal is not None and loss_signal.numbers.get("spread", 0) > 0.05:
                links.append("GR-03:loss_by_group")
                trace["candidate"] = "loss"
                trace["loss_by_group"] = loss_signal.numbers["by_group"]
            if df_before is not None and kept_index is not None:
                lost = df_before[~df_before.index.isin(kept_index)]
                cf = checks.srm_counterfactual(df, lost, group_col, ratio, g2["p_threshold"])
                trace["counterfactual"] = cf
                if cf.get("available") and not cf.get("resolved"):
                    # 손실을 되돌려도 안 맞으면 손실 탓이 아니다
                    trace["candidate"] = "unexplained"
            if trace.get("candidate") != "loss":
                trace.setdefault("candidate", "unexplained")
                trace["branch"] = msg("guard_gr02_unexplained")
            rep.cause_trace = trace
            add(sig, links=links)
        for s in checks.srm_by_dimension(df, group_col, meta_cols, ratio,
                                         g2["p_threshold"]):
            add(s, links=["GR-02:srm"])
    else:
        skip("GR-02", msg("guard_skip_no_group"))

    # ── GR-04 관측 불균형 ───────────────────────────────────
    g4 = {k: v.value for k, v in locks.limits("GR-04", lock_path).items()}
    if group_col and group_col in df.columns:
        for s in checks.group_balance(df, group_col, g4["min_group_n"],
                                      g4["severe_group_n"], g4["imbalance_ratio"]):
            # 그룹이 작아진 것이 손실 때문일 수 있다 — 연결만 표시하고 단정하지 않는다
            add(s, links=["GR-03:loss_by_group"] if loss_signal else [])
        for s in checks.smd_imbalance(df, group_col, meta_cols, g4["smd_threshold"]):
            add(s, links=["GR-02:srm"])
        for c in metric_cols:
            for s in checks.metric_stability(df, group_col, c, g4["min_group_n"]):
                add(s)
    else:
        skip("GR-04", msg("guard_skip_no_group"))
    for s in checks.coverage(df, metric_cols or list(types), g4["coverage_threshold"]):
        add(s)

    # ── GR-01 정의역 ────────────────────────────────────────
    g1 = {k: v.value for k, v in locks.limits("GR-01", lock_path).items()}
    confirmed = {c: t for c, t in types.items() if t in checks.DOMAIN}
    if confirmed:
        for s in checks.out_of_range(df, confirmed, g1["tail_quantile"]):
            add(s)
    else:
        # 타입이 확정돼야 정의역을 안다 — 모르면 검사한 척하지 않는다
        skip("GR-01", msg("guard_skip_no_types"))

    rep.findings.sort(key=lambda f: (rep.order.index(f.rule) if f.rule in rep.order else 9,
                                     0 if f.tier == "gate" else 1, f.check))
    return rep


def headline(rep: GuardReport) -> str | None:
    """차단이 있으면 출력 맨 앞에 붙일 한 줄 ."""
    if not rep.gates:
        return None
    rules = sorted({f.rule for f in rep.gates})
    return msg("guard_headline_gate", n=len(rep.gates), rules=", ".join(rules))
