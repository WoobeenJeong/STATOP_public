"""강건성 — **지금 낸 결론이 얼마나 버티나**를 이 자료에서 직접 잰다.

문서에 "이 지표는 강건하다 / 아니다"를 등급으로 적어 두면 어떤 자료에서는 맞고 어떤
자료에서는 틀린다. 같은 `불균형`이라도 양성 1,000 : 음성 1,000 과 양성 8 : 음성 1,000 은
완전히 다른 상황인데 등급 한 글자는 둘을 구분하지 못한다 (작성자 지적).

그래서 등급을 매기지 않고 **세 가지로 흔들어 보고 결과가 어디까지 움직이는지** 보인다.

| 무엇을 흔드나 | 무엇을 묻는가 |
|---|---|
| ① 표본 (부트스트랩) | **우연만으로** 결과가 어디까지 움직이나 |
| ② 이상치 (상·하위 잘라내기) | 소수의 극단값이 결론을 만들고 있나 |
| ③ 고른 것 (다른 검정) | 방법 선택이 결론을 만들고 있나 |

**①이 기준선이다.** ②·③의 변화가 ①의 폭보다 크면 그건 우연이 아니라 그 선택이 만든
차이다.  에서 임계를 정한 방식과 같은 논리 — "관행"이라고 말하지 않고 우연만으로
나오는 크기를 먼저 보인다.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statop.messages import msg

SAMPLE, OUTLIER, CHOICE = "sample", "outlier", "choice"
DEFAULT_DRAWS = 200
TRIMS = (0.01, 0.05)          # 상·하위 몇 %를 잘라 보나


@dataclass
class Shake:
    """한 번 흔든 결과."""

    kind: str
    label: str
    effect: float | None = None
    # **검정을 바꾸면 효과크기의 종류도 바뀐다** (P(X>Y) ↔ Hedges g ↔ rank-biserial).
    # 이름을 함께 들고 다니지 않으면 단위가 다른 값을 같은 축에서 빼게 된다 (실제로 뺐다)
    effect_name: str = ""
    p: float | None = None
    flipped: bool = False          # 그 검정의 **자기 기준** 대비 방향이 뒤집혔나
    failed: str = ""               # 못 돌린 이유 (조용히 빼지 않는다)


@dataclass
class Report:
    test: str = ""
    name: str = ""
    effect_name: str = ""
    effect: float | None = None
    p: float | None = None
    ref: float = 0.0               # 효과가 '차이 없음'이 되는 값
    n_rows: int = 0
    draws: int = 0
    seed: int = 0
    # ① 표본
    boot: list = field(default_factory=list)      # 효과값들
    boot_q: dict = field(default_factory=dict)    # p5 p25 p50 p75 p95
    boot_flips: int = 0
    # ②③
    outliers: list = field(default_factory=list)
    choices: list = field(default_factory=list)

    @property
    def band(self) -> float:
        """①의 폭 — ②③의 변화가 이보다 크면 우연이 아니다."""
        if not self.boot_q:
            return 0.0
        return abs(self.boot_q["p95"] - self.boot_q["p5"])


def _flipped(value: float | None, base: float | None, ref: float) -> bool:
    """기준(차이 없음)을 사이에 두고 반대편으로 넘어갔나."""
    if value is None or base is None:
        return False
    if abs(base - ref) < 1e-12:
        return False
    return (value - ref) * (base - ref) < 0


def _trim(df: pd.DataFrame, col: str, frac: float) -> pd.DataFrame:
    """y 의 상·하위 frac 을 잘라낸다. 자르는 것은 **분석이 아니라 확인**이다 —
    결과를 이걸로 바꿔 쓰지 않는다."""
    v = pd.to_numeric(df[col], errors="coerce")
    lo, hi = v.quantile(frac), v.quantile(1 - frac)
    return df[(v >= lo) & (v <= hi)]


def build(session_file: str, draws: int = DEFAULT_DRAWS, seed: int = 0,
          sample_n: int = 10_000, progress=None) -> Report:
    """지금 세션의 마지막 검정 결과를 세 가지로 흔든다."""
    from statop.analyze.run import apply_label_maps, null_ref, run_on
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import build as build_spec
    from statop.analyze.spec import current
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import load_session, main_source, replay

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    doc = load_session(session_file)
    st = replay(doc)
    results = st["test_results"]
    if not results:
        raise ValueError(msg("robust_need_result"))
    last = results[-1]

    _, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    df = apply_label_maps(df, spec, st["label_maps"].get(src["id"], {}))

    rep = Report(test=last["test"], name=last["name"],
                 effect_name=(last.get("effect") or {}).get("name", ""),
                 effect=(last.get("effect") or {}).get("value"),
                 p=last.get("p"), n_rows=int(len(df)), draws=draws, seed=seed)
    rep.ref = null_ref(rep.effect_name)

    def eff(out) -> float | None:  # noqa: ANN001
        return (out.effect or {}).get("value")

    # ① 표본 — 우연만으로 어디까지 움직이나
    rng = np.random.default_rng(seed)
    vals = []
    for i in range(draws):
        if progress and i % 20 == 0:
            progress(0.6 * i / draws)
        boot = df.iloc[rng.integers(0, len(df), len(df))]
        try:
            out = run_on(boot, spec, rep.test)
        except Exception:
            continue          # 한 번 실패해도 분포는 남는다 — 아래에서 개수를 말한다
        v = eff(out)
        if v is not None and np.isfinite(v):
            vals.append(float(v))
            rep.boot_flips += _flipped(v, rep.effect, rep.ref)
    rep.boot = vals
    if vals:
        a = np.asarray(vals)
        rep.boot_q = {f"p{q}": float(np.percentile(a, q)) for q in (5, 25, 50, 75, 95)}

    # ② 이상치 — 소수의 극단값이 결론을 만들고 있나
    if progress:
        progress(0.7)
    numeric = pd.to_numeric(df[spec.y], errors="coerce").notna().any()
    for frac in TRIMS:
        label = msg("robust_trim_label", pct=frac * 100)
        if not numeric:
            rep.outliers.append(Shake(OUTLIER, label,
                                      failed=msg("robust_trim_not_numeric", col=spec.y)))
            continue
        try:
            out = run_on(_trim(df, spec.y, frac), spec, rep.test)
            v = eff(out)
            rep.outliers.append(Shake(OUTLIER, label, effect=v, p=out.p,
                                      effect_name=rep.effect_name,
                                      flipped=_flipped(v, rep.effect, rep.ref)))
        except Exception as e:
            rep.outliers.append(Shake(OUTLIER, label, failed=str(e)[:120]))

    # ③ 고른 것 — 방법 선택이 결론을 만들고 있나
    if progress:
        progress(0.85)
    from statop.analyze.run import RUNNERS

    # 같은 질문에 쓸 수 있었던 다른 검정들 — A2 후보 목록을 그대로 쓴다
    for c in shortlist(build_spec(session_file, spec, sample_n)):
        if c.id == rep.test or c.id not in RUNNERS:
            continue
        label = f"{c.id} {c.name}"
        try:
            out = run_on(df, spec, c.id)
            v = eff(out)
            name = (out.effect or {}).get("name", "")
            # 이 검정의 효과크기는 종류가 다르므로 **그 자신의 기준**으로 방향을 본다.
            # 원래 검정의 방향과 같은지는 부호(기준 대비 위/아래)로만 견준다
            ref2 = null_ref(name)
            same = (rep.effect is not None and v is not None
                    and (v - ref2) * (rep.effect - rep.ref) > 0)
            rep.choices.append(Shake(CHOICE, label, effect=v, effect_name=name,
                                     p=out.p, flipped=not same and v is not None))
        except Exception as e:
            rep.choices.append(Shake(CHOICE, label, failed=str(e)[:120]))
    if progress:
        progress(1.0)
    return rep


def verdict(rep: Report) -> list[str]:
    """읽는 법 — **①의 폭을 기준선으로** ②③을 읽는다."""
    out = []
    if rep.boot_q:
        out.append(msg("robust_band", lo=rep.boot_q["p5"], hi=rep.boot_q["p95"],
                       q25=rep.boot_q["p25"], q75=rep.boot_q["p75"], n=len(rep.boot)))
        out.append(msg("robust_flips", n=rep.boot_flips, total=len(rep.boot))
                   if rep.boot_flips else msg("robust_no_flip", total=len(rep.boot)))
    # **크기 비교는 ②에만** — ③은 검정마다 효과크기의 종류가 달라 뺄 수 없다.
    # ③은 방향과 유의 여부로만 견준다
    band = rep.band
    big = [s for s in rep.outliers
           if s.effect is not None and rep.effect is not None
           and abs(s.effect - rep.effect) > band > 0]
    if big:
        out.append(msg("robust_bigger_than_chance",
                       items=", ".join(s.label for s in big)))
    else:
        out.append(msg("robust_within_chance"))
    if rep.choices:
        out.append(msg("robust_choice_note"))
    flipped = [s for s in rep.outliers + rep.choices if s.flipped]
    if flipped:
        out.append(msg("robust_flipped_by", items=", ".join(s.label for s in flipped)))
    return out
