"""eps 추천·차단 (F-01, registry-tests 10.1).

규칙: 추천값 = `10^(floor(log10(min_positive(x))) - k)`, k 기본 2.
**추천값 이하만 허용한다** — 큰 eps는 log 척도를 왜곡한다(내부 사례 #2).
"""

import math
from dataclasses import dataclass

K_DEFAULT = 2       # 추천값을 최소 양수보다 몇 자리 아래로 둘지
N_CANDIDATES = 4    # 화면에 보일 후보 수


@dataclass
class EpsAdvice:
    needed: bool            # 0이 있어 eps가 필요한가
    min_positive: float | None
    recommended: float | None
    candidates: list[float]  # 추천값 이하의 선택지 (이산)
    n_zeros: int
    n_negative: int


def advise(values, k: int = K_DEFAULT) -> EpsAdvice:
    """대상 값에서 eps 추천을 만든다. 0이 없으면 needed=False."""
    import numpy as np

    x = np.asarray(values, dtype="float64")
    x = x[~np.isnan(x)]
    n_zero = int((x == 0).sum())
    n_neg = int((x < 0).sum())
    pos = x[x > 0]
    if pos.size == 0:
        return EpsAdvice(needed=n_zero > 0, min_positive=None, recommended=None,
                         candidates=[], n_zeros=n_zero, n_negative=n_neg)

    min_pos = float(pos.min())
    exp = math.floor(math.log10(min_pos)) - k
    rec = 10.0 ** exp
    cands = [10.0 ** (exp - i) for i in range(N_CANDIDATES)]
    return EpsAdvice(needed=n_zero > 0, min_positive=min_pos, recommended=rec,
                     candidates=cands, n_zeros=n_zero, n_negative=n_neg)


def validate(given: float, advice: EpsAdvice) -> None:
    """추천값 초과면 거부한다 — 커밋되는 경로가 없어야 한다 (검수 기준)."""
    from statop.messages import msg

    if advice.recommended is None:
        return
    if given > advice.recommended * 1.0000001:   # 부동소수 여유
        raise ValueError(msg("eps_too_large", given=given, limit=advice.recommended))
