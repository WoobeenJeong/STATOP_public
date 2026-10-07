# STATOP 무결성 가드레일 목록 (registry-guardrails) — 1.0.0

- 연계: `stat-validator-rfp-1.0.0.md` (Gate/Diagnostic 등급), `registry-tests.md` (C-13 등), `registry-scores.md` (SC-BE 배치), `registry-errors.md` (E-11 external 중복)
- 상태: 검토용 초안. 별도 지시 전까지 덮어쓴다
- 목적: 검정·점수와 별개로, **"이 데이터·지표를 믿어도 되는가"**를 결과 앞단에서 검사하는 가드레일을 관리. 논문 13편 분류가 지목하는 무결성 문제를 실행 가능한 검사로 옮긴 것
- ID: `GR-{연번}`. 각 가드레일은 검사식·임계값·등급(Gate/Diagnostic)·범위(range) 규칙을 가진다

---

## 0. 가드레일이란 (검정·점수와의 차이)

| | 검정(T) | 점수(SC) | 가드레일(GR) |
|---|---|---|---|
| 묻는 것 | 가설이 맞나 | 얼마나 좋나 | **이 결과를 믿어도 되나** |
| 실패 시 | 결론 애매 | 값이 나쁨 | **다른 모든 결과가 무효** |
| 동작 | 사용자 선택 | 사용자 계산 | **자동 실행, 실패 시 배너/차단** |

가드레일은 SRM처럼 "코드는 정상, p값도 정상인데 결론이 틀리는" 조용한 실패를 앞단에서 잡는다. Microsoft가 모든 A/B 테스트를 SRM 통과 후에만 분석하게 한 것과 같은 구조.

---

## 1. 값 잠금 모델 (out-of-range 핵심 요구)

**원칙: 기본 정의는 잠겨 있고(read-only), 사용자는 덮어쓰기 레이어로만 조작한다.** 기본 계산 자체는 바뀌지 않는다.

| 레이어 | 내용 | 편집 |
|---|---|---|
| **base (잠금)** | 내장 점수·검정·가드레일의 기본 정의역·검사식·기본 임계값. `registry-*.md`가 원본 | 불가. 앱에서 read-only 표시 |
| **override (사용자)** | 특정 컬럼·수식·세션에 대해 기본값을 가리는 사용자 설정. `overrides.json`에 저장 | 가능. 언제든 제거해 base로 복귀 |

- 유효값 = override가 있으면 override, 없으면 base. UI에 "기본값 / 사용자 지정"을 함께 표시하고 "기본으로 되돌리기" 버튼 제공.
- override는 base를 **수정하지 않는다.** 파일도 분리(`overrides.json`). 그래서 기본 계산은 항상 원형이 남고, 조작은 추적·복원 가능.
- 모든 override는 조작 로그(M0-8)에 `{target, field, base_value, user_value, ts, reason?}`로 기록되고 출력 md에 표기된다.
- 커스텀 수식(M1-2)은 처음부터 사용자 소유라 range를 자유 지정. 단 **내장 점수의 range를 좁히거나 넓히는 것은 override로만** 가능.

---

## 2. 지표 정의역 / Out-of-range (GR-01) — 가장 중요

모든 점수·컬럼·수식 결과는 **정의역(valid range)**을 가진다. 계산 결과가 그 밖으로 나가면 계산 오류·데이터 오류·가정 위반의 신호다.

### 2.1 검사
- 각 점수의 base range는 `registry-scores.md`에서 파생(예: 확률 [0,1], 상관 [−1,1], AUC [0,1], KL [0,∞), CV(%) [0,∞), fraction [0,1], p-value [0,1]).
- 컬럼의 의미 타입에도 range가 있음(S-T): count ℕ, fraction [0,1], percent [0,100], probability [0,1].
- 결과·입력이 range 밖이면 등급에 따라 처리.

### 2.2 등급
| 상황 | 등급 | 예 |
|---|---|---|
| 수학적으로 불가능한 값 | **Gate(차단)** | 확률 1.3, 음수 카운트, fraction 1.2, \|r\|>1 |
| 정의역 경계 특수값 | Diagnostic(경고) | 확률 정확히 0/1(log 불가), 상관 정확히 ±1(완전분리 의심) |
| 통계적으로 이례적(분포 꼬리 밖) | Diagnostic | 값이 기대분포 99.9% 밖 (E-6: skew/scale 체크) |
| 물리적으로 비현실적(도메인) | Diagnostic | 나이 −5, 발현량 음수, VAF>1 |

### 2.3 override
- 사용자는 특정 컬럼/수식의 유효 range를 덮어쓸 수 있다. 예: 어떤 score를 [0, 0.5]로 좁혀 그 밖을 이상치로 표시.
- **넓히는 방향**(예: 확률을 [−0.1, 1.1]로)은 Gate 항목(수학적 불가능)에 대해서는 **차단 유지**하고, Diagnostic 항목만 완화 가능. 즉 "확률이 음수여도 통과"는 허용하지 않는다. 완화 허용/불가는 각 GR에 `override_floor`로 명시.
- override 시 사유 입력을 권고(선택), 출력에 base/user 병기.

### 2.4 out-of-range 액션
| 액션 | 설명 |
|---|---|
| flag | 범위 밖 셀을 표시(음영)하고 개수 보고. 기본 |
| drop | 범위 밖 행 제거 (결측 정책과 동일 로그) |
| clip | 경계로 자르기. **경고**: 분포 왜곡. 사용자 명시적 선택만, 로그 필수 |
| keep | 그대로 두되 배너 유지 (Diagnostic만) |

> clip은 데이터를 조작하므로 base 계산에는 절대 자동 적용하지 않는다. 사용자 override로만.

---

## 3. 표본 비율 불일치 / SRM (GR-02)

- **정의**: 설계상 배정 비율(예: 1:1)과 실제 관측 비율이 통계적으로 다른 상태. `registry-errors-guide.md` SRM 항목 참조.
- **검사**: 그룹별 관측 수 vs 기대 비율로 카이제곱(또는 이항). base 임계값 `p < 0.0005`(Microsoft 관례). override로 조정 가능하되 완화 시 경고.
- **차원별 SRM**(Eppo 방식): hold된 메타 컬럼(기관·batch·platform 등)의 값마다 SRM을 검사하고 다중비교 보정(Bonferroni). "전체는 균형인데 하위군에서 깨진" 숨은 불균형 검출 → 규칙 #6, #11.
- **등급**: 기본 Gate — SRM이면 효과 분석·검정 결과에 빨간 배너, 원인 진단(GR-03/04) 먼저 보도록 유도. override로 Diagnostic 강등 가능(사유 기록).
- **연결**: 여러 데이터셋을 selection·가공해 합칠 때(내부 #11) 자동 실행. external에 학습 샘플 중복이 SRM으로 드러나는 경우 포함.

| 필드 | base |
|---|---|
| 검사식 | χ² on 그룹 카운트 vs 기대 비율 |
| 기대 비율 | 사용자 입력(기본 1:1) |
| 임계 | p < 0.0005 |
| 차원 검사 | 메타 컬럼별, Bonferroni |
| 등급 | Gate |
| override_floor | Diagnostic까지 완화 허용 |
| 원인 추적 | GR-03 군별 손실률·GR-04 불균형과 연결해 **원인 후보** 제시 (인과 단정 금지) |
| 반사실 확인 | 해당 군 손실을 제외한 예상 비율을 재계산해 SRM 해소 여부 병기 |
| 미설명 분기 | 손실로 설명되지 않으면 "기대 비율 설정 오류 또는 모집단 불균형 확인 필요" |

---

## 4. 데이터 손실 / Join rate (GR-03)

여러 파일·테이블을 합칠 때 얼마나 살아남았는지. 조용한 데이터 손실은 편향의 흔한 원인.

| 검사 | 정의 | 등급 |
|---|---|---|
| Join/match rate | 조인 후 매칭된 행 / 조인 전 좌측(또는 기준) 행 | 낮으면 Diagnostic, 매우 낮으면 Gate |
| Row retention | 각 처리 단계 후 남은 행 / 이전 단계 | 단계별 표(퍼널) |
| 손실의 편향 | 손실된 행이 라벨·그룹·메타와 연관되는지(카이제곱/SMD) | 연관되면 **Gate** (무작위 손실이 아님) |
| 중복 폭증 | 조인 후 행 수가 기준보다 늘면(다대다 조인 실수) | Gate |
| 키 무결성 | 조인 키 결측·타입 불일치·중복 키 | Diagnostic |
| 군별 손실률 | 그룹·메타 컬럼 값별 손실률과 전체 대비 편차 | Diagnostic (GR-02 원인 추적 입력) |

- base 임계: match rate < 0.95 노랑, < 0.8 빨강(조정 가능). "손실이 라벨과 연관"은 임계와 무관하게 Gate.
- 출력에 **손실 퍼널**(단계별 n)을 항상 첨부. 이게 없으면 "200명이 어디서 120명이 됐는지" 추적 불가(E-X-4).
- 근거: Kapoor L2.2(비독립), Wynants 표본 손실, 내부 #11.

---

## 5. 지표 관측 불균형 / Metric observation imbalance (GR-04)

지표를 계산할 때 그룹·세그먼트마다 **관측 수가 크게 다른** 상태. 평균·비율이 소수 관측 그룹에서 불안정하거나, 가중 없이 합산해 왜곡됨.

| 검사 | 정의 | 등급 |
|---|---|---|
| 그룹별 n 편차 | max n / min n 비, 또는 최소 그룹 n | 최소 n < 임계(기본 10) Diagnostic, < 5 강한 경고 |
| 지표 커버리지 | 지표가 정의된(비결측) 행 / 전체 | 낮으면 "부분 지표" 경고 |
| 가중 필요 | 세그먼트 합산 시 그룹 크기 무시 | Simpson 위험(S-R11) → P(Y), P(Y\\|Z) 병기 권고 |
| 균형처럼 보이는 불균형 | 라벨은 50:50인데 메타(기관·age·immune)가 편중 | SC-BE-09(SMD)로 검출 → 규칙 #6 |
| 지표 안정성 | 소표본 그룹의 지표 부트스트랩 CI 폭 | 넓으면 Diagnostic (P-231) |

- base 임계: 최소 그룹 n 10. override로 도메인에 맞게 조정.
- 불균형 지표에는 **PR-AUC 병기**(SC-CLS-08), 소수 그룹 CI 표시를 기본 권고.
- 근거: Whalen P5, 내부 #6.

---

## 6. 논문 13편 → 가드레일/등급 매핑

가드레일이 어느 논문 항목을 실행 가능하게 옮겼는지. (분류 원문은 `registry-tests.md`·`registry-errors.md`)

| 가드레일 | 논문 근거 |
|---|---|
| GR-01 out-of-range | Makin 2019(범위·이상치), 내부 #6(scale), 일반 데이터 검증 |
| GR-02 SRM | Fabijan KDD 2019, Microsoft ExP, Eppo(차원별), 내부 #11 |
| GR-03 data loss/join | Kapoor L2.2·L1.4, Wynants(표본), Yang 2022(누수), 내부 #11 |
| GR-04 observation imbalance | Whalen P5·P3, Saito 2015(PR vs ROC), 내부 #6 |
| (연결) 배치효과 | SC-BE 계열, Leek 2010, Whalen P3 |

13편 목록 자체는 `stat-validator-rfp-1.0.0.md` 부록 A에 유지. 여기서는 그 중 **무결성 검사로 실행 가능한 것**만 가드레일화한다.

---

## 7. 가드레일 실행 순서 (파이프라인 앞단)

```
데이터/지표 준비
   ↓
GR-03 join/손실  →  손실이 편향적? → Gate
   ↓
GR-02 SRM (전체 + 차원별)  →  깨짐? → Gate, 원인은 GR-03/04
   ↓
GR-04 관측 불균형  →  숨은 불균형/소표본? → Diagnostic + 병기 권고
   ↓
GR-01 out-of-range (입력·결과)  →  불가능값? Gate / 이례값? Diagnostic
   ↓
검정(T) · 점수(SC) 실행 허용
```

- **위 순서는 진단 순서이지 인과관계가 아니다** (DECISIONS). SRM이 반드시 데이터 손실의 결과인 것은 아니며, 모집단 자체가 불균형할 수 있다. 문구에서 "손실 때문에 SRM"으로 단정하지 않는다.
- **원인 추적(cause_trace)**: 검사 간 연결을 추적해 **원인 후보**를 제시한다 — 군별 손실률 편차 → SRM 관측/기대 비율 → 영향받은 군. 여기에 **반사실 확인**("그 손실이 없었다면 SRM이 해소되는가")을 함께 계산해 붙인다. 해소되지 않으면 원인 후보에서 내린다.
- **손실로 설명되지 않는 SRM은 별도 분기**: "손실로 설명되지 않음 → 기대 비율 설정 오류 또는 모집단 불균형 확인 필요". 손실이 0에 가까운데 SRM이 뜨는 경우가 더 중요하다.
- Gate가 하나라도 걸리면 검정·점수 결과에 빨간 배너가 남고, 출력 md에 가드레일 요약이 맨 앞에 온다.
- 모든 GR은 override 가능하나 `override_floor`가 Gate로 고정된 항목(수학적 불가능값, 편향적 손실, SRM 원판정)은 완화해도 배너가 사라지지 않는다.

---

## 8. 스키마 (가드레일 추가 시)
```yaml
id: GR-01
name: out_of_range
tier: gate            # gate | diagnostic (기본)
check: "value in valid_range(target)"
base_range_source: registry-scores | semantic_type
thresholds: {...}
override_floor: diagnostic   # 사용자가 완화 가능한 하한 등급. gate면 완화 불가
actions: [flag, drop, clip, keep]
default_action: flag
sources: [...]
short_tag: oor
```

## 9. 관리 규칙
- 가드레일은 항상 자동 실행. 새 GR 추가 시 등급·override_floor·기본 액션을 반드시 지정.
- base 정의는 이 파일과 `registry-scores`가 원본이며 앱에서 read-only. 사용자 조작은 `overrides.json`으로만.
- `override_floor: gate`인 필드는 어떤 override로도 base 계산·차단을 무력화하지 못한다.
- 별도 지시 전까지 덮어쓰기.
