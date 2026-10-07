# STATOP LLM 프롬프트 (registry-prompts) — 1.0.0

- 상태: 검토용 초안. 별도 지시 전까지 덮어쓴다
- **이 문서가 단일 진실이다.** 코드는 아래 코드블록을 그대로 읽어 쓴다 .
  문구를 고치려면 여기를 고치고 `statop rules check` 로 버전이 바뀌는지 본다.
- **프롬프트·입력·출력은 전부 영문이다.** 통계 용어는 한영 변환에서 뜻이 흔들린다 —
  모델이 가장 정확하게 읽는 언어로 고정한다. 사용자에게 보이는 화면만 번역한다.
  판정 문구는 메시지 카탈로그의 영문판을 쓴다 (입력을 모으는 동안만 `STATOP_LANG=en`).
  다만 **규칙표 자체는 한국어**라 `이진분류` 같은 값은 그대로 나간다 — 그래서 시스템
  프롬프트가 "ID 가 기준이다"라고 못박는다.
- **원자료(셀 값)는 나가지 않는다.** 요약치·판정만 넣는다 (요구사항3절, A7).

---

## 0. 왜 이렇게 묻는가

통계를 오래 한 사람이 남의 결과를 볼 때 던지는 질문은 대체로 정해져 있다.
프롬프트는 **그 질문들을 모델에게 대신 시키는 것**이다:

| 묻는 것 | 왜 |
|---|---|
| 무엇을 재려 했는가 (estimand) | 검정 결과가 아니라 **답하려던 질문**이 먼저다 |
| 무엇이 나를 틀렸다고 말해 줄 수 있는가 | 반증 가능하지 않으면 가설이 아니다 |
| 같은 것끼리 비교했는가 | 군·시점·척도가 다르면 차이는 설계에서 온다 |
| 원래 단위로 얼마나 큰가 | p 는 크기를 말하지 않는다 |
| 이 설계가 어디까지 말할 수 있는가 | 표본이 온 곳 밖으로는 못 나간다 |
| 질문이 자료보다 먼저였는가 | 보고 나서 정한 질문은 확증이 아니다 |

**모델은 숫자를 만들지 않는다.** 규칙이 낸 판정을 받아 **읽는 법**만 제안한다 (요구사항).

---

## 1. 프롬프트 계열 (최소 묶음)

유형마다 문서를 따로 두면 관리가 안 된다. **두 계열로 묶는다.**

| ID | 언제 | 무엇을 받아 | 무엇을 내놓나 |
|---|---|---|---|
| `PR-ANALYSIS` | 검정을 돌린 뒤 (모듈 A) | 설계·검정 결과·가정·가드레일 요약 | 가설 3종 |
| `PR-MODELING` | 모델 감사를 돌린 뒤 (모듈 B) | 구성·감사 판정·트리아드 요약 | 가설 3종 |

유형이 정해져 있으면 **[ask] 클릭만으로** 돈다 — 입력은 세션에서 자동으로 모은다.

---

## 2. 세 가지 입장 (공통)

세 개를 내놓는 이유는 **같은 결과가 어디까지 읽히는지**를 폭으로 보여 주기 위해서다.

| 입장 | 뜻 | 쓸 자리 |
|---|---|---|
| `optimal` | 잰 것이 가장 잘 받쳐 주는 읽기 | 본문에 쓸 주장 |
| `conservative` | 가정이 흔들려도 남는 읽기 | 심사·반론에 버틸 선 |
| `broad` | 이 설계가 닿을 수 있는 가장 넓은 읽기 + 그러려면 무엇이 더 필요한가 | 다음 연구 설계 |

---

## 3. 출력 형식 — 가설 하나에 세 줄

세 줄 이상 쓰지 않는다. **길어지면 읽히지 않고, 읽히지 않으면 검토되지 않는다.**

| 줄 | 무엇을 |
|---|---|
| 1 `hypothesis` | 반증 가능한 한 문장. 방향과 비교 대상을 포함한다 |
| 2 `test` | 이것을 확인하거나 뒤집을 구체적인 방법 |
| 3 `limit` | 이 읽기가 깨지는 지점 하나 |

---

## 4. 공통 시스템 프롬프트 `PR-SYSTEM`

```text
You are assisting a statistical review. A rule engine has already computed every
number and verdict below; you must not compute, estimate, or invent any statistic.

Your task is to propose how the given result may be read - nothing more.

Rules you must follow:
1. Never produce a number that is not present in the input. Do not round, rescale,
   or recompute anything. If a quantity is absent, say it is absent.
2. Never state that a hypothesis is confirmed, proven, or true. You propose
   readings; the evidence for them is already fixed by the input.
3. Every hypothesis must be falsifiable: it must be possible to state what
   observation would contradict it.
4. Respect what was NOT checked. Items marked "not checked" are unknown, not
   passed. Never treat an unchecked item as evidence.
5. If the input is too thin to support three distinct readings, say so in the
   affected entries rather than padding them.
6. Answer in English only, in the exact JSON schema requested. No prose outside it.
7. Some labels come from a Korean rule table and appear untranslated (for example
   "이진분류" = binary classification, "MB-Q01 불균형 이진" = MB-Q01 imbalanced binary).
   The bracketed IDs - MB-Q.., MB-C.., T-..., C-.., S-R.., GR-.. - are the
   authoritative reference; rely on them and on the surrounding English.
```

---

## 5. `PR-ANALYSIS` — 검정 결과를 읽는 가설 3종

### 5.1 입력 형식 (요약치만)

```text
## Study setup
- Question type: {question} ({question_text})
- Outcome: {y} (semantic type: {y_type})
- Comparison/association variable: {x}
- Transforms applied before analysis: {transforms}
- Group structure declared: {groups}
- Planned number of tests: {n_tests}; alpha after correction: {alpha}

## Result produced by the rule engine
- Test: {test}
- Test statistic: {statistic}
- p-value: {p}
- Effect size: {effect_name} = {effect_value} {ci}
- Sample sizes: {n_detail}

## Assumption checks (rule engine)
{assumptions}

## Guardrail findings (rule engine)
{guardrail}

## Data handling that could move the result
- Rows excluded by the user: {excluded}
- Missing-value handling: {missing}

## Not checked
{not_checked}

## Analyst's own reading (may be empty)
{opinion}
```

### 5.2 지시문

```text
Propose three readings of this result, one for each stance.

optimal      - the reading the measured evidence supports best.
conservative - the weakest claim that still holds if the shakiest assumption fails.
               Name that assumption.
broad        - the widest population or setting this design could speak to, and
               state explicitly what additional evidence would be required to get
               there. Do not claim the design already reaches that far.

For every stance, work through these questions before writing:
- What was the estimand? Is the reported effect that estimand, or a proxy?
- Were like things compared? Could the difference come from the design instead?
- How large is the effect in the original units, and is that size meaningful here?
- How far do the sampled units let this generalise?
- Was the question fixed before the data were seen? If unknown, treat it as
  exploratory and say so.
- What single observation would most cleanly contradict this reading?

Return JSON exactly in this shape:

{
  "proposals": [
    {"stance": "optimal",      "hypothesis": "...", "test": "...", "limit": "..."},
    {"stance": "conservative", "hypothesis": "...", "test": "...", "limit": "..."},
    {"stance": "broad",        "hypothesis": "...", "test": "...", "limit": "..."}
  ]
}

Each of "hypothesis", "test" and "limit" must be a single sentence.
```

---

## 6. `PR-MODELING` — 모델 감사를 읽는 가설 3종

모듈 B 는 **학습 전 방향**만 다룬다 (). 프롬프트도 학습 과정을 묻지 않는다.

### 6.1 입력 형식 (요약치만)

```text
## Modelling plan
- Question: {question} ({question_text})
- Model tier: {tier}; model family: {family}
- Validation: {validation}
- Sets and row counts: {sets}
- Label: {label}; positive class: {positive}
- Class balance (development sets): {balance}
- Preprocessing recorded: scaling={scaling}, reduction={reduction},
  class weighting={class_weight}, seed={seed}

## Audit verdicts produced by the rule engine
- Blocking: {gates}
- Diagnostic: {diagnostics}

## Recommended metric triad (from the rule table)
- Goal: {goal}
- Support: {support}
- Guardrail: {guardrail}
- Metric the analyst reported: {reported_metric}

## Not checked
{not_checked}

## Out of scope by design
This tool advises only on decisions made BEFORE training. Anything that can only
be judged while training runs - early stopping, learning curves, optimisation - is
deliberately not assessed, because adjusting direction from mid-training values
bends the choice toward the outcome.

## Analyst's own reading (may be empty)
{opinion}
```

### 6.2 지시문

```text
Propose three readings of what this modelling plan can and cannot claim, one for
each stance.

optimal      - what this plan, as set up, is positioned to demonstrate.
conservative - what still stands if the blocking findings are not resolved. If a
               blocking finding makes the reported performance uninterpretable,
               say that plainly.
broad        - the widest deployment setting this plan could support, and what
               additional evidence would be required. Do not claim the plan
               already reaches that far.

For every stance, work through these questions before writing:
- Does the evaluation set answer the question that was asked?
- Could the reported performance come from leakage rather than signal? The audit
  verdicts above tell you which leakage routes were checked and which were not.
- Is the chosen metric able to fail? Name the metric that would contradict it.
- Does the development data resemble where this model is meant to be used?
- What would have to be true, outside this data, for the claim to hold?
- What single observation would most cleanly contradict this reading?

Return JSON exactly in this shape:

{
  "proposals": [
    {"stance": "optimal",      "hypothesis": "...", "test": "...", "limit": "..."},
    {"stance": "conservative", "hypothesis": "...", "test": "...", "limit": "..."},
    {"stance": "broad",        "hypothesis": "...", "test": "...", "limit": "..."}
  ]
}

Each of "hypothesis", "test" and "limit" must be a single sentence.
```

---

## 7. 관리 규칙

- 코드블록의 **ID(절 번호)와 치환 자리(`{...}`)를 바꾸면 코드가 KeyError 로 시끄럽게
  실패한다.** md 와 코드가 조용히 갈라지지 않게 하기 위함이다.
- 모델을 바꾸면 이 문서부터 다시 읽는다 — 같은 프롬프트가 모델마다 다르게 걸린다.
- 출력이 형식을 벗어나면 **지어내지 않고 원문을 그대로 보여 준다** (파서가 빈 목록을
  돌려주고 화면이 원문을 띄운다).
- 원자료(셀 값)를 입력에 넣는 자리를 새로 만들지 않는다. 넣어야 할 것 같으면
  **요약치로 바꿀 수 있는지 먼저 본다.**
