"""M4 값 잠금  — 기준값은 읽기 전용, 사용자 조정은 별도 파일에.

`rules/guardrails.yaml`이 기준(base)이고 **아무도 이 파일을 고쳐서는 안 된다**.
사용자가 바꾸고 싶은 값은 `overrides.json`에 따로 쌓이며, 출력에는 "기본값이 아니라
사용자 값을 썼다"는 사실이 항상 함께 나간다 — 조용히 느슨해지는 경로를 막기 위함.

**완화 불가 .** 규칙마다 `override_floor`가 있다. 등급을 그 아래로 내릴 수 없다.
GR-03(손실·편향)은 floor가 gate라 차단을 해제할 방법이 아예 없다.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FILENAME = "overrides.json"

# 등급 서열 — 높을수록 강하다. off는 검사 자체를 끄는 것
TIER_ORDER = {"off": 0, "info": 1, "diagnostic": 2, "gate": 3}
TIERS = tuple(TIER_ORDER)

# 조정 가능한 임계값과 기준값. 기준값은 여기와 규칙 DB에만 있고 실행 중 바뀌지 않는다.
# (규칙 문서에 문장으로만 적힌 수치를 기계가 읽을 수 있게 옮긴 것)
BASE_THRESHOLDS: dict[str, dict] = {
    "GR-01": {
        "tail_quantile": 0.999,       # 이 밖이면 "이례적" (분포 꼬리 밖)
        "action": "flag",             # flag | drop | clip | keep
    },
    "GR-02": {
        "p_threshold": 0.0005,        # χ² p가 이보다 작으면 SRM
        "expected_ratio": None,       # None이면 균등(1:1:…)
    },
    "GR-03": {
        "join_rate_gate": 0.90,       # 매칭률이 이보다 낮으면 차단
        "join_rate_warn": 0.98,
        "bias_p_threshold": 0.01,     # 손실이 군과 연관되는지 (χ²)
        "duplicate_tolerance": 1.0,   # 조인 후 행 수 / 기준 행 수 상한
    },
    "GR-04": {
        "min_group_n": 10,            # 이보다 작으면 진단
        "severe_group_n": 5,          # 이보다 작으면 강한 경고
        "coverage_threshold": 0.80,   # 지표가 정의된 행 비율
        "smd_threshold": 0.10,        # 메타 편중 (균형처럼 보이는 불균형)
        "imbalance_ratio": 1.5,       # max n / min n
    },
}

# clip은 분포를 왜곡한다 — 자동으로 고를 수 없고 사용자가 명시해야 한다 (규칙 DB actions)
MANUAL_ONLY_ACTIONS = {"clip"}


class LockError(ValueError):
    """잠금 위반 — 조용히 무시하지 않는다."""


@dataclass
class Limit:
    """실제로 적용된 값 하나. 기본값에서 바뀌었으면 출처가 함께 남는다."""

    rule: str
    key: str
    value: object
    base: object
    overridden: bool
    floor: str | None = None


@lru_cache(maxsize=1)
def _guardrail_meta() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[3] / "rules" / "guardrails.yaml"
    doc = yaml.safe_load(path.read_text())
    return {g["id"]: g for g in doc["guardrails"]}


def execution_order() -> list[str]:
    """진단 순서 . 인과 순서가 아니라 **앞 검사 결과가 뒤 검사의 입력**이라는 뜻."""
    import yaml

    path = Path(__file__).resolve().parents[3] / "rules" / "guardrails.yaml"
    return list(yaml.safe_load(path.read_text())["execution_order"])


def base_tier(rule: str) -> str:
    """규칙 DB가 정한 기본 등급."""
    g = _guardrail_meta().get(rule, {})
    if g.get("tier"):
        return g["tier"]
    # 하위 검사마다 등급이 다르면 가장 강한 것이 그 규칙의 기본 등급이다
    tiers = [c.get("tier") for c in g.get("checks", [])] + \
            [x.get("tier") for x in g.get("grades", [])]
    tiers = [t for t in tiers if t]
    return max(tiers, key=lambda t: TIER_ORDER.get(t, 0)) if tiers else "diagnostic"


def floor(rule: str) -> str:
    """이 아래로는 내릴 수 없는 등급 ."""
    return _guardrail_meta().get(rule, {}).get("override_floor", "diagnostic")


def overrides_path(path: str | Path | None = None) -> Path:
    from statop.store import user_dir

    return Path(path) if path else user_dir() / FILENAME


def load(path: str | Path | None = None) -> dict:
    p = overrides_path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def _save(data: dict, path: str | Path | None = None) -> Path:
    p = overrides_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    return p


def set_tier(rule: str, tier: str, path: str | Path | None = None) -> Path:
    """등급을 조정한다. **floor 아래로는 거부한다**  — 예외 없다."""
    from statop.messages import msg

    if rule not in _guardrail_meta():
        raise LockError(msg("guard_unknown_rule", rule=rule))
    if tier not in TIER_ORDER:
        raise LockError(msg("guard_unknown_tier", tier=tier, allowed="|".join(TIERS)))
    fl = floor(rule)
    if TIER_ORDER[tier] < TIER_ORDER[fl]:
        raise LockError(msg("guard_floor_violation", rule=rule, tier=tier, floor=fl))

    data = load(path)
    data.setdefault(rule, {})["tier"] = tier
    return _save(data, path)


def set_threshold(rule: str, key: str, value, path: str | Path | None = None) -> Path:
    """임계값을 조정한다. 기준값 자체는 건드리지 않는다 — 덮어쓸 뿐이다."""
    from statop.messages import msg

    base = BASE_THRESHOLDS.get(rule)
    if base is None or key not in base:
        raise LockError(msg("guard_unknown_threshold", rule=rule, key=key,
                            allowed=", ".join(sorted(base or {}))))
    if key == "action" and value in MANUAL_ONLY_ACTIONS:
        # clip은 잠금 파일로 기본값이 될 수 없다 — 매번 사람이 고르게 한다
        raise LockError(msg("guard_action_manual_only", action=value))
    data = load(path)
    data.setdefault(rule, {}).setdefault("thresholds", {})[key] = value
    return _save(data, path)


def clear(rule: str | None = None, path: str | Path | None = None) -> Path:
    """조정을 되돌린다 — 기준값으로 돌아간다."""
    data = load(path)
    if rule is None:
        data = {}
    else:
        data.pop(rule, None)
    return _save(data, path)


def tier_of(rule: str, path: str | Path | None = None) -> str:
    """지금 적용되는 등급. 조정이 있어도 floor 아래로는 내려가지 않는다."""
    want = load(path).get(rule, {}).get("tier", base_tier(rule))
    fl = floor(rule)
    return want if TIER_ORDER.get(want, 0) >= TIER_ORDER[fl] else fl


def limits(rule: str, path: str | Path | None = None) -> dict[str, Limit]:
    """이 규칙에 실제로 적용되는 값들 — 기본값과 조정 여부를 함께 들고 다닌다."""
    over = load(path).get(rule, {}).get("thresholds", {})
    out = {}
    for k, base in BASE_THRESHOLDS.get(rule, {}).items():
        v = over.get(k, base)
        out[k] = Limit(rule=rule, key=k, value=v, base=base, overridden=k in over)
    out["tier"] = Limit(rule=rule, key="tier", value=tier_of(rule, path),
                        base=base_tier(rule),
                        overridden=tier_of(rule, path) != base_tier(rule),
                        floor=floor(rule))
    return out


def active_overrides(path: str | Path | None = None) -> list[Limit]:
    """기본값과 다른 것만 — 출력 배너에 항상 따라붙는다."""
    out = []
    for rule in _guardrail_meta():
        for lim in limits(rule, path).values():
            if lim.overridden:
                out.append(lim)
    return out
