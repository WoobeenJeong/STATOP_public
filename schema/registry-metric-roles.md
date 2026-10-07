# STATOP 지표 역할·추천 관계 목록 (registry-metric-roles) — 1.0.0

- 연계: `registry-scores.md` (SC-ID), `registry-tests.md` (검정·효과크기), `stat-validator-rfp-1.0.0.md` A5 3-metric·M3
- 상태: 검토용 초안. 별도 지시 전까지 덮어쓴다
- 목적: 사용자가 보려는 지표를 **Goal**로 두고, 그에 대한 **Support**(해석 보조)와 **Guardrail**(trade-off 감시)을 함께 볼 수 있게 추천 관계를 관리. 검정(hypothesis)과 모델링(input) 양쪽에서 동일하게 동작하며 **옵션**이다
- ID: `MR-{연번}` (추천 관계)

---

## 0. 세 역할의 정의

| 역할 | 정의 | 복잡도 | 예 |
|---|---|---|---|
| **Goal** | 가설이 검증됨을 확인하는 주 지표 | 해석 가능하면 복잡해도 됨 | RMSE, Mahalanobis, AUC, CLR-차이, C-index |
| **Support** | 같은 방향을 확인하되 **해석이 쉬운** 보조 지표. Goal이 "얼마나"를 안 알려줄 때 보완 | 복잡성 비허용, 직관적 | MAE, Euclidean, raw 값, 원척도 차이 |
| **Guardrail** | Goal을 올리면 **대가로 나빠질 수 있는** trade-off 지표. 함께 봐야 결론이 흔들리지 않음 | — | specificity(↔sensitivity), 배치 보존(↔혼합), 검정력(↔α) |

- Goal은 필수. Support·Guardrail은 **옵션**(선택해서 켬).
- 추천 관계가 있으면 Goal 선택 시 Support/Guardrail 후보가 **"추천"으로 최상단**에 뜨고, 나머지는 그 아래.
- 이 관계는 검정 지표(hypothesis)와 입력/모델 지표(input) 모두에 적용된다. 어디에 쓰든 구조는 같다.

---

## 1. Support 관계 (해석 보완) — Goal → 추천 Support

"Goal은 검증엔 좋지만 크기·방향 해석이 어렵다 → 쉬운 짝을 같이"

| MR | Goal | 추천 Support | 왜 (Support가 채우는 해석) |
|---|---|---|---|
| MR-S01 | RMSE (SC-ERR-02) | MAE (SC-ERR-01) | RMSE는 큰 오차를 제곱해 "몇 배"인지 감이 안 옴. MAE는 평균적으로 몇 단위 틀렸는지 직관적 |
| MR-S02 | RMSE / MAE | MAPE·sMAPE (SC-ERR-03/04) | 절대 단위 대신 상대 오차(%)로 스케일 감 |
| MR-S03 | Mahalanobis (SC-DIST-03) | 표준화 Euclidean (SC-DIST-01) | 공분산 보정 거리 3.2가 뭔지 안 와닿음. 표준화 유클리드는 "몇 SD 떨어짐" |
| MR-S04 | Cosine similarity (SC-DIST-04) | Euclidean (SC-DIST-01) / raw 크기 | 코사인은 방향만. 크기 정보를 raw로 |
| MR-S05 | log/CLR 값 (SC-NORM-09) | raw 비율·원척도 | log-ratio 차이 1이 "e배"인지 감이 안 옴. raw 비율 병기 |
| MR-S06 | KL divergence (SC-DIST-12) | Jensen–Shannon (SC-DIST-11) / TV | KL은 비대칭·무한대 가능. JS는 대칭·유계라 크기 비교 쉬움 |
| MR-S07 | AUC (SC-CLS-06) | Sens·Spec at 임계 (SC-CLS-01/02) | AUC 0.8이 실제 임계에서 어떤 민감도인지 |
| MR-S08 | C-index (SC-CLS-15) | KM 곡선·중위 생존차 | 일치도 숫자보다 곡선이 직관적 |
| MR-S09 | Brier / log loss (SC-ERR-10/11) | 보정 곡선·정확도 | 손실값 자체는 크기 감 없음 |
| MR-S10 | dCor / MMD (SC-DIST-14) | 산점도·Pearson r | 방향 없는 연관 → 그림·단순 상관으로 |
| MR-S11 | Aitchison distance (SC-DIST-09) | 최대 기여 성분 top-k | 조성 거리 값 → 어떤 성분이 벌렸는지 |
| MR-S12 | Shannon 엔트로피 (SC-DIV-01) | richness·top 우점종 비율 | 엔트로피 수치 → 종 수·우점도로 |
| MR-S13 | Rényi/Hill (SC-DIV-04/05) | Hill q=0,1,2 세 값 | 한 α보다 프로파일이 직관적 |
| MR-S14 | η²/ω² (P-202) | 군 평균·차이 원값 | 분산설명비 → 실제 평균차 |
| MR-S15 | Cohen d (P-201) | 원척도 평균차 + CI (P-203) | 표준화 효과 → 원단위 |
| MR-S16 | Batch entropy/LISI (SC-BE-04/11) | 이웃 배치 비율 표 | 지수값 → 실제 섞임 비율 |
| MR-S17 | Wasserstein (SC-DIST-13) | 중위수·분위수 차 | 분포 이동을 대표값 차로 |
| MR-S18 | Beta-회귀 계수 (T-805) | 원척도 비율 예측 | logit 계수 → 예측 비율 |

## 2. Guardrail 관계 (trade-off 감시) — Goal ↑ → 함께 볼 Guardrail

"Goal을 좋게 만들면 대가로 나빠질 수 있는 것"

| MR | Goal | 추천 Guardrail | trade-off 내용 |
|---|---|---|---|
| MR-G01 | Sensitivity (SC-CLS-01) | Specificity (SC-CLS-02) | 문턱 낮추면 민감도↑ 특이도↓. 항상 쌍 |
| MR-G02 | PPV | NPV / 유병률 | 한쪽 올리면 다른 쪽·기저율 의존 |
| MR-G03 | Recall (재현율) | Precision (SC-CLS-09) | PR 곡선의 양 축 |
| MR-G04 | ROC-AUC (SC-CLS-06) | PR-AUC (SC-CLS-08) + 기저율 | 불균형에서 ROC 낙관적, PR로 견제 (#6) |
| MR-G05 | 배치 혼합 iLISI/kBET (SC-BE-03/04) | 생물 보존 cLISI/label silhouette (SC-BE-02/04) | 배치 지우면 신호도 지워짐. 혼합↔보존 |
| MR-G06 | 검정력 / 표본 확대 | 1종 오류 α, 다중검정 (C-15) | 많이 검정하면 검출↑ 위양성↑ |
| MR-G07 | 모델 정확도 | 보정 ECE (SC-CLS-13) | 정확해도 확률이 과신될 수 있음 |
| MR-G08 | 민감도 높은 임계 | 결정곡선 net benefit (SC-CLS-14) | 임상 순이득으로 과잉진단 견제 |
| MR-G09 | fold 성능 평균 | fold 간 분산 / 최악 fold | 평균 좋아도 불안정 |
| MR-G10 | 차등발현 유의 수 | log2FC 크기 + FDR (P-223) | p만 낮고 효과 미미 |
| MR-G11 | in-sample 적합(R²) | 검증셋 성능 / 과적합 격차 | 훈련 성능↔일반화 |
| MR-G12 | 특이 유전자 선택 수 | 안정성(재표본 재현율, AIRepr) | 많이 고를수록 불안정 |
| MR-G13 | 클러스터 분리(silhouette) | 생물학적 타당성/마커 | 수치 분리↔의미 |
| MR-G14 | 데이터 정제(이상치 제거) | 제거 비율·남은 n (A4) | 깨끗해질수록 표본 편향·축소 |
| MR-G15 | 정규화 강도(배치보정) | 그룹 간 실제 신호 잔존 | 과보정 위험 |
| MR-G16 | 조성 성분 증가 | 다른 성분 필연 감소(심플렉스) | 합=1 제약, CLR로 봐야 (S-R01) |
| MR-G17 | 생존 HR 개선 | 경쟁위험·추적손실 (E-807-3) | 다른 사건·검열 편향 |
| MR-G18 | 지표 커버리지 확대 | 관측 불균형 (GR-04) | 합치며 소수군 왜곡 |

## 3. bio/의학 특화 트리아드 (자주 쓰는 세트)

한 번에 Goal+Support+Guardrail을 제안하는 프리셋. 사용자가 Goal만 골라도 나머지가 추천으로 뜬다.

| MR | 상황 | Goal | Support | Guardrail |
|---|---|---|---|---|
| MR-T01 | 이진 진단 모델 | AUC | Sens·Spec@임계 | PR-AUC + 기저율 |
| MR-T02 | 불균형 진단 | PR-AUC | Recall·Precision | MCC / balanced acc |
| MR-T03 | 생존 예측 | C-index | KM 곡선 | 경쟁위험·추적손실 |
| MR-T04 | 회귀 예측 | RMSE | MAE + 원척도차 | fold 분산 / 잔차 진단 |
| MR-T05 | scRNA 배치통합 | iLISI/kBET | 이웃 배치비율 | cLISI/label silhouette |
| MR-T06 | 미생물 조성 비교 | Aitchison + PERMANOVA | top 기여 성분 | 0 비율·부분조성 (E-1001) |
| MR-T07 | alpha 다양성 | Shannon | richness·우점도 | 깊이 균일성(rarefaction) |
| MR-T08 | 차등발현 | log2FC + FDR | 발현 원값 | p-분포·독립필터 누수 |
| MR-T09 | 바이오마커 선택 | 선택 성능 | 마커 수·해석 | 안정성(재표본 재현) |
| MR-T10 | 확률 변동성(#3) | Bernoulli 정규화 변동성 (SC-VAR-04) | SD + raw 값 | 2σ 밴드 밖 비율 |
| MR-T11 | 군 간 차이(3군, 대비) | planned contrast (T-1101) | 군 평균±CI | omnibus로 본 전체차 |
| MR-T12 | 두 측정법 일치 | Lin's CCC | Bland–Altman | 크기 의존 편향(깔때기) |
| MR-T13 | 고차원 이상탐지 | Mahalanobis | 표준화 Euclidean | Σ 안정성(d/n) |
| MR-T14 | 분류 보정 | ECE | 보정 곡선 | 판별력(AUC) 손실 |

## 4. 저장 대상 3종 (사용자별)

세션이 아니라 **사용자 라이브러리**에 저장. 3.5 저장/불러오기 UI·경로 검사 공유.

| 저장물 | 파일 | 내용 | 편집 |
|---|---|---|---|
| **① 세션 로그 (입력 재현)** | `session_*.json` | 원본 경로·해시, 컬럼 선택/hold, 파생 수식, 검정·점수·가드레일 선택, override, **선택한 Goal/Support/Guardrail 옵션** | 3.4 재생 복원 |
| **② 내 지표(자주 쓰는)** | `formulas.json` | 커스텀 수식(M1-2). 이름·LaTeX·슬롯·매개변수·결과타입 | 추가/덮어쓰기/삭제 |
| **③ 내 추천 관계** | `metric_roles.json` | 사용자가 추가한 Goal→Support/Guardrail 관계(MR). 내장 관계를 가리거나 신규 추가 | 추가/덮어쓰기/삭제 |

- ③은 base(이 파일의 MR)와 분리. 사용자 관계가 있으면 추천 최상단에 "내 추천"으로, 그 아래 내장 추천, 그 아래 나머지 지표.
- ③ 항목: `{goal: SC-ID or 커스텀, role: support|guardrail, metric: SC-ID or 커스텀, note?}`. 이름 중복은 덮어쓰기.
- 세 저장물 모두 **base 정의를 수정하지 않는다**(가드레일 값 잠금과 동일 원칙). 내장 SC·MR은 read-only.

## 5. UI 동작 (M3·A5 연동)

1. 사용자가 **Goal** 지표 선택 (검정 결과 지표 또는 입력/모델 지표)
2. 도구가 추천 조회 순서: **내 추천(③)** → 내장 트리아드(3절) → Support/Guardrail 관계(1·2절) → 없으면 없음
3. 추천은 **"추천" 뱃지로 최상단**, 나머지 호환 지표는 아래. 사용자가 Support/Guardrail을 0개 이상 선택(옵션)
4. 선택된 3역할이 함께 계산·표시. Support는 해석 문구, Guardrail은 "함께 보라" 경고와 함께
5. 선택 구성은 세션 로그(①)에 저장. 마음에 들면 관계를 ③에 저장해 다음에 자동 추천
6. Goal만 쓰고 Support/Guardrail을 비워도 됨(옵션). 강제하지 않음 — 단 A5 확정에서 Goal은 필수(R-15)

## 6. 관리 규칙
- 내장 MR 추가 시 Goal·역할·근거를 채운다. bio 사례는 3절 트리아드에 우선 반영.
- 사용자 관계(③)는 내장을 덮어쓸 수 있으나 base MR 파일은 불변.
- Support는 "해석 쉬움", Guardrail은 "trade-off"라는 정의를 벗어난 항목은 넣지 않는다(둘을 섞으면 추천이 무의미).
- 별도 지시 전까지 덮어쓰기.
