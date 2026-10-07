"""B5 지표 변경 · 재현성 감사  — MB-C21 · C25 · C26 · C27.

둘 다 **세션에 쌓인 기록**을 본다. 한 번의 결과만 보면 알 수 없고, 무엇이 바뀌었는지
남아 있어야 보이는 것들이다.

- MB-C21 지표를 바꿨는가 — 바꾸면 이전 보고와 견줄 수 없다. 바꾼 사유가 남아 있어야 한다 (Gate)
- MB-C25 seed 를 기록했는가 — 없으면 같은 코드로도 다른 결과가 나온다 (Gate)
- MB-C26 환경·버전을 기록했는가 — 라이브러리가 바뀌면 값이 달라진다
- MB-C27 비결정 연산을 고지했는가 — GPU·병렬은 seed 를 고정해도 완전히 같지 않다

**감사 전용이다.** 학습을 돌리지 않고 구성 기록만 본다. 사용자의 학습이 GPU 에서 돌든
아니든 **설정을 읽는 데는 GPU 가 필요 없다** — STATOP 자신이 도는 연산과 사용자가 돌릴
모델은 다른 이야기다 ().
"""

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, skip

# 비결정으로 알려진 실행 환경 — 여기 해당하면 seed 만으로는 같은 값이 안 나온다
NONDETERMINISTIC = ("gpu", "cuda", "mps", "multi", "parallel", "distributed")


def _history(session_file: str) -> list[dict]:
    """세션에 쌓인 모델 구성 기록 — 오래된 것부터."""
    from statop.session.core import load_session, replay

    return replay(load_session(session_file))["model_specs"]


# ── MB-C21 비교 불가 지표 변경 (Gate) ───────────────────────
def metric_change(spec, session_file: str) -> LeakFinding:  # noqa: ANN001
    """이전에 보고한 지표와 다른 지표로 바꿨는가 (내부 사례 #10).

    mean prob → median prob 처럼 지표를 바꾸면 **이전 보고와 같은 축이 아니다.**
    바꾸는 것 자체는 막지 않는다 — 다만 **왜 바꿨는지와 이전 지표 값**이 함께 있어야
    나중에 두 보고를 놓고 비교할 수 있다.
    """
    if not spec.metric:
        return skip("MB-C21", msg("mb_c21_no_metric"))
    used = [s.get("metric") for s in _history(session_file) if s.get("metric")]
    earlier = [m for m in used[:-1] if m != spec.metric] if used else []
    if not earlier:
        return LeakFinding(id="MB-C21", grade=grade_of("MB-C21"), verdict="pass",
                           summary=msg("mb_c21_same", metric=spec.metric),
                           numbers={"metric": spec.metric, "history": used})

    previous = earlier[-1]
    numbers = {"metric": spec.metric, "previous": previous, "history": used,
               "reason": spec.metric_change_reason}
    if spec.metric_change_reason:
        return LeakFinding(
            id="MB-C21", grade=grade_of("MB-C21"), verdict="pass",
            summary=msg("mb_c21_reason_given", old=previous, new=spec.metric),
            detail=[msg("mb_c21_reason", reason=spec.metric_change_reason),
                    msg("mb_c21_both", old=previous)],
            numbers=numbers)
    return LeakFinding(
        id="MB-C21", grade=grade_of("MB-C21"), verdict="fail",
        summary=msg("mb_c21_changed", old=previous, new=spec.metric),
        detail=[msg("mb_c21_why")], numbers=numbers,
        action=msg("mb_c21_change_action"))


# ── MB-C25 seed (Gate) · C26 환경 · C27 비결정 ──────────────
def reproducibility(spec, session_file: str) -> list[LeakFinding]:  # noqa: ANN001
    """같은 입력에서 같은 결과가 나오는가 — 나오게 하려면 무엇이 적혀 있어야 하는가."""
    out = []

    # MB-C25 — seed 가 없으면 split·초기화·샘플링이 매번 달라진다
    if spec.seed is not None:
        out.append(LeakFinding(id="MB-C25", grade=grade_of("MB-C25"), verdict="pass",
                               summary=msg("mb_c25_recorded", seed=spec.seed),
                               numbers={"seed": spec.seed}))
    else:
        out.append(LeakFinding(
            id="MB-C25", grade=grade_of("MB-C25"), verdict="fail",
            summary=msg("mb_c25_missing"), detail=[msg("mb_c25_why")],
            numbers={"seed": None}, action=msg("mb_c25_action")))

    # MB-C26 — 라이브러리가 바뀌면 같은 seed 로도 값이 달라진다
    if spec.environment:
        out.append(LeakFinding(id="MB-C26", grade=grade_of("MB-C26"), verdict="pass",
                               summary=msg("mb_c26_recorded", env=spec.environment),
                               numbers={"environment": spec.environment}))
    else:
        out.append(LeakFinding(
            id="MB-C26", grade=grade_of("MB-C26"), verdict="fail",
            summary=msg("mb_c26_missing"), detail=[msg("mb_c26_why")],
            numbers={"environment": None}, action=msg("mb_c26_action")))

    # MB-C27 — GPU·병렬은 seed 를 고정해도 완전히 같지 않다. **고지했는가만 본다**
    env = (spec.environment or "").lower()
    looks_nondet = [k for k in NONDETERMINISTIC if k in env]
    if spec.nondeterminism:
        out.append(LeakFinding(id="MB-C27", grade=grade_of("MB-C27"), verdict="pass",
                               summary=msg("mb_c27_noted", note=spec.nondeterminism),
                               numbers={"nondeterminism": spec.nondeterminism}))
    elif looks_nondet:
        out.append(LeakFinding(
            id="MB-C27", grade=grade_of("MB-C27"), verdict="fail",
            summary=msg("mb_c27_suspected", found=", ".join(looks_nondet)),
            detail=[msg("mb_c27_why")], numbers={"found": looks_nondet},
            action=msg("mb_c27_action")))
    else:
        # 환경 문자열에 흔적이 없다고 결정적이라는 뜻은 아니다 — 못 봤다고 말한다
        out.append(skip("MB-C27", msg("mb_c27_unknown")))
    return out


# ── seed_<id>.py — 재현 스크립트 ────────────────────────────
def seed_script(spec, session_file: str) -> str:  # noqa: ANN001
    """`seed_<세션id>.py` — 이 구성을 같은 값으로 다시 돌리기 위한 고정 코드.

    **학습 코드를 써 주지 않는다.** seed 를 어디에 심어야 하는지만 적는다 — 무엇을
    학습할지는 사용자의 코드이고, 도구가 그것까지 지어내면 틀린 코드를 주게 된다.
    """
    from statop.session.core import load_session

    doc = load_session(session_file)
    seed = spec.seed if spec.seed is not None else 0
    assumed = spec.seed is None
    lines = [
        f'"""{msg("mb_seed_script_head", session=doc["session_id"])}',
        "",
        msg("mb_seed_script_note"),
    ]
    if assumed:
        lines.append(msg("mb_seed_script_assumed", seed=seed))
    if spec.environment:
        lines.append(msg("mb_seed_script_env", env=spec.environment))
    lines += ['"""', "", "import os", "import random", "", "import numpy as np", "",
              f"SEED = {seed}", "",
              'os.environ["PYTHONHASHSEED"] = str(SEED)',
              "random.seed(SEED)", "np.random.seed(SEED)", "",
              "# " + msg("mb_seed_script_torch"),
              "# import torch",
              "# torch.manual_seed(SEED)",
              "# torch.cuda.manual_seed_all(SEED)",
              "# torch.use_deterministic_algorithms(True)", "",
              "# " + msg("mb_seed_script_split"),
              f"# train_test_split(X, y, random_state=SEED)",
              f"# KFold(n_splits={spec.k or 5}, shuffle=True, random_state=SEED)"]
    return "\n".join(lines) + "\n"


def run_all(spec, session_file: str) -> list[LeakFinding]:  # noqa: ANN001
    """S192· 전부 — 하나가 실패해도 나머지는 돈다."""
    out = []
    for fn in (lambda: [metric_change(spec, session_file)],
               lambda: reproducibility(spec, session_file)):
        try:
            out += fn()
        except (ValueError, OSError, KeyError) as e:
            out.append(skip("MB-C25", str(e)))
    return out
