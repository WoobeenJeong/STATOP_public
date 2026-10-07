# STATOP 디자인 토큰 · 색 팔레트 · 라벨 매핑 (design-tokens) — 1.0.0

- 연계: `stat-validator-rfp-1.0.0.md` (UI), `registry-tests.md` M1(라벨/의미 타입), `registry-guardrails.md`(등급 색)
- 상태: 검토용 초안. 별도 지시 전까지 덮어쓴다
- 원칙: **무채색 기반, 필요한 outline만.** 색은 정보일 때만 쓴다(3색 판정, 등급, 라벨 그룹). 장식용 색 금지
- 접근성: 적록색맹 고려 — 초록은 **청록(blue-green)**, 경고는 **주황(yellow-orange)**. 색 단독으로 정보를 전달하지 않고 항상 아이콘·텍스트 병행

---

## 1. 타이포그래피

| 용도 | 폰트 | 근거 |
|---|---|---|
| 한글 | **맑은 고딕(Malgun Gothic)** → 없으면 `Noto Sans KR`, `Apple SD Gothic Neo` | 지정 |
| 영문 본문 | **system-ui** 스택: `-apple-system, "Segoe UI", Roboto, Helvetica, Arial` | 공적으로 가장 보편, OS 기본 |
| 숫자·표 | 위 + `font-variant-numeric: tabular-nums` | 자릿수 정렬 |
| 코드·수식·경로 | `Consolas, "SF Mono", "DejaVu Sans Mono", monospace` | 등폭 |
| 수식 렌더 | KaTeX 기본(Computer Modern) | LaTeX 일관 |

```css
--font-sans: "Malgun Gothic", -apple-system, "Segoe UI", Roboto, "Noto Sans KR", Arial, sans-serif;
--font-mono: Consolas, "SF Mono", "DejaVu Sans Mono", monospace;
```
- 본문 14px, 표 13px, 캡션 12px. 굵기는 400/600만. 가시성 위해 본문 대비비 ≥ 7:1 (AAA) 지향.

---

## 2. 무채색 기반 (중립 UI)

라이트 기본. 다크는 미결(9절).

| 토큰 | HEX | 용도 |
|---|---|---|
| --bg | #FFFFFF | 배경 |
| --bg-subtle | #F5F6F7 | 카드·패널 |
| --border | #DDE0E3 | 기본 outline (얇게 1px) |
| --border-strong | #B8BCC0 | 활성·포커스 테두리 |
| --text | #1C1F22 | 본문 (거의 검정) |
| --text-muted | #5B6166 | 보조 |
| --text-faint | #8A9096 | 비활성 |
| --brand | #35566B | 강조 1색 (차분한 슬레이트블루). 링크·선택 |

> outline은 --border만 기본 노출, 나머지는 hover/active에만. 그림자 최소.

---

## 3. 의미 색 — 3색 판정 (핵심)

적록색맹 안전: 초록=청록, 경고=주황. 아이콘 필수.

| 판정 | 이름 | HEX | 텍스트/아이콘 | 아이콘 | 쓰임 |
|---|---|---|---|---|---|
| 문제없음 | ok (짙은 청록) | #0B6E6E | 텍스트로 사용 가능(흰 배경 대비 6.0) | ✔ | 추천·적합·통과 |
| 애매 | neutral (검정) | #1C1F22 | 텍스트 | ○ / – | 조건부·중립·"애매하면 검정" |
| 하지마 | warn (앰버) | #E8912E | **칩 배경/테두리 전용.** 텍스트는 #7A4A12(어두운 앰버) | ⚠ | 부적합·경고 |
| 차단(강) | danger (벽돌red) | #B23A17 | 텍스트로 사용 가능(대비 6.0) | ⛔ | Gate·수학적 불가능 |

- "추천은 초록, 애매하면 검정, 하지말라는 건 주황"을 그대로 반영. danger는 Gate 전용의 더 진한 주황-red.
- **색약 검증(시뮬 통과)**: 명도를 벌려 ok(어두운 청록, 상대휘도 0.12)와 warn(밝은 앰버, 0.38)이 deuteranopia/protanopia 시뮬 후에도 대비 2.2~3.0으로 구분됨. 그래도 **아이콘 병행 필수** — 색만으로는 절대 표현하지 않는다. (초기 후보 #0E8C8C/#D97A21은 명도가 비슷해 색약 시 대비 1.3까지 떨어져 폐기)
- **warn 텍스트 주의**: warn 앰버는 흰 배경 텍스트 대비가 낮아, 글자색으로 쓰지 않고 칩 배경·테두리로만. 글자는 어두운 앰버(#7A4A12).
- 배경 칩은 각 색의 12% 틴트 + 해당 색 1px 테두리 + 진한 텍스트.

```css
--ok:#0B6E6E;        --ok-bg:#E1EFEF;   --ok-text:#0B6E6E;
--neutral:#1C1F22;   --neutral-bg:#F0F1F2;
--warn:#E8912E;      --warn-bg:#FBEEDD;  --warn-text:#7A4A12;   /* 앰버는 배경/테두리, 글자는 어두운 앰버 */
--danger:#B23A17;    --danger-bg:#F6E1D9; --danger-text:#B23A17;
```

### 3.1 등급(Gate/Diagnostic/Judgment) ↔ 색
| 등급 | 색 | 표기 |
|---|---|---|
| Gate(차단) | danger | ⛔ + "차단" 배지, 배너 상단 고정 |
| Diagnostic(경고) | warn | ⚠ + "확인" 배지 |
| Judgment(권고) | neutral | ○ + "권고", 접힌 카드 |

---

## 4. 상태 색 — base(잠김) vs override(사용자)

| 상태 | 표기 | 색 |
|---|---|---|
| base(잠김) | 🔒 자물쇠 + "기본값" | --text-muted, 배경 --bg-subtle |
| override(사용자) | ✎ 연필 + "사용자 지정" | --brand 테두리, 값 옆 base 원값 회색 취소선 |
| override 불가(gate floor) | 🔒 회색 고정, 완화 시도 시 danger 토스트 | — |

---

## 5. 라벨/그룹 색 — 임상 카테고리 (기본 팔레트)

환자·질병 중심. **기본 세팅이며 사용자가 palette로 재정의 가능**(6절).

### 5.1 상태 축 (진단 카테고리)
| 카테고리 | 의미 | HEX | 비고 |
|---|---|---|---|
| normal | 정상군 | #9AA0A6 (회색) | 모르는 라벨의 기본값도 이 색 |
| disease | 질병(비종양) | #E3B341 (노랑) | 염증·감염 등 |
| benign | 양성종양 | #E08A3C (주황) | |
| malignant | 암(악성) | #D64545 (빨강) | stage 미상 포함 |
| malignant_late | 암 stage 3/4 (late) | #7E2B2B (검붉은빨강) | 진행성 |
| precancer | 전암/이형성 | #EBC06B (연노랑) | 선택 |
| metastasis | 전이 | #5A1F1F (더 어두운 적갈) | 선택 |

> 이 축은 색맹 고려보다 임상 관례(빨강=암)를 우선한 사용자 지정. 단 3색 판정(3절)과 화면에서 섞이지 않게, 라벨 색은 **데이터 점/범례에만**, 판정 색은 **UI 배너/배지에만** 쓴다(영역 분리).

### 5.2 조직 축 (참고: 업로드 색상표 기반)
조직/세포 유형 라벨은 업로드된 색상표의 계열을 따른다. 검색어 부분일치로 자동 할당(7절). 대표 앵커:

| 조직군 | 대표색 계열 | 예 라벨 |
|---|---|---|
| Blood/면역 | 파랑~보라 | Blood-B, T, NK, Mono, Granul |
| Epithelial(상피) | 분홍~살구 | Breast-Ep, Colon-Ep, Gastric-Ep |
| Liver | 초록 | Liver-Hep, HCC |
| Lung | 초록 계열 | Lung-Ep-Alveo/Bron |
| Neuron/뇌 | 짙은 회청 | Neuron, Oligodend |
| Muscle | 회청~청 | Skeletal/Smooth-Musc, Cardio |
| Pancreas | 주황 계열 | Acinar, Alpha, Beta, Delta, Duct |
| Fibroblast | 연분홍~연노랑 | Colon-Fibro, Dermal-Fibro |

---

## 6. 팔레트 커스터마이즈 (사용자)

- 기본 팔레트(5절)는 base(잠김). 사용자는 `palette.json`으로 재정의(가드레일 값 잠금과 동일 구조).
- 축 선택: 상태축 / 조직축 / 면역축 / 커스텀축. 한 데이터에 여러 축을 두고 전환 가능.
- 각 카테고리의 색·키워드·약어를 편집. 저장·덮어쓰기·기본 복귀.
- 저장 단위: `{axis, category, color, keywords:[...], aliases:[...]}`.

---

## 7. 라벨 자동 매핑 (부분일치)

### 7.1 요구
- `label`류 컬럼이 있으면 **통계엔 0/1/2… 정수 코드**로 쓰되 **표시는 문자열**(colon 등)로. 코드↔표시 매핑 키 옵션.
- 라벨 문자열을 **부분일치·약어**로 카테고리에 자동 배정하고 색을 준다. 예: `OV`, `ov`, `ovary`, `Ovarian-Ca` → ovary(장미빛). `HCC`, `LIHC`, `liver`, `Liver-Hep` → liver. 모르는 것은 normal 색(회색)·"미분류" 배지.

### 7.2 매핑 규칙
1. 정규화: 소문자화, 구분자(`-_./ `) 제거, 흔한 접미 제거(`cancer, ca, tumor, carcinoma, adeno, tissue, cells, ep`).
2. 약어 사전(7.3)과 **부분일치**: 라벨에 약어/키워드가 포함되면 해당 카테고리. 가장 긴 일치 우선(예: `head-neck`이 `neck`보다 우선).
3. TCGA 코드 우선 매핑(예: `LIHC→liver`, `HNSC→head_neck`).
4. 다중 일치 시: 상태축(암종) > 조직축 순, 그래도 모호하면 사용자 확인(노랑).
5. 무매칭: normal 색 + "미분류", 사용자가 한 번 지정하면 `palette.json`에 학습.
- 색 배정: 카테고리별 앵커색(7.3)을 base로, 같은 카테고리 내 변형은 명도만 다르게.

### 7.3 암종 앵커 사전 (약 50종, 부분일치 키워드 + TCGA + 앵커색)
색은 업로드 색상표 계열 참고. 상태축(암/정상)과 별개로 **암종별 색조**를 준다. HEX는 초안, 6절에서 조정 가능.

| 카테고리 | TCGA | 키워드/약어(부분일치) | 앵커색 | 계열 |
|---|---|---|---|---|
| liver | LIHC, CHOL | hcc, liver, hepat, lihc, chol, hepatocellular | #3FA66B | 초록 |
| lung | LUAD, LUSC | lung, luad, lusc, nsclc, sclc, alveo, bronch | #57C08A | 청록초록 |
| breast | BRCA | breast, brca, mammary, luminal, basal, her2, tnbc | #E8A6C2 | 분홍 |
| ovary | OV | ov, ovary, ovarian, hgsoc, serous-ov | #D96B9A | 장미빛 |
| colon | COAD | colon, coad, colorectal, crc, colo | #C08AE0 | 보라 |
| rectum | READ | rectum, read, rectal | #B77AD6 | 보라 |
| stomach | STAD | stomach, stad, gastric, gej | #C67A2E | 갈주황 |
| pancreas | PAAD | pancrea, paad, pdac, acinar, ductal-panc | #E8873C | 주황 |
| prostate | PRAD | prostate, prad | #3E7CC0 | 파랑 |
| bladder | BLCA | bladder, blca, urothelial | #E0A85C | 연주황 |
| kidney | KIRC, KIRP, KICH | kidney, kirc, kirp, kich, renal, rcc, ccRCC | #4FA3D1 | 하늘 |
| head_neck | HNSC | head, neck, hnsc, hn, oral, oropharyn, laryn | #B5892E | 황갈 |
| thyroid | THCA | thyroid, thca, papillary-thy | #5CC0C0 | 청록 |
| brain_gbm | GBM | gbm, glioblastoma, glioma-high | #4A5560 | 짙은 회청 |
| brain_lgg | LGG | lgg, glioma-low, astrocyt, oligodendro | #6E7A86 | 회청 |
| melanoma | SKCM | melanoma, skcm, cutaneous-mel | #7E4B2B | 갈색 |
| skin_scc | — | skin-scc, cutaneous-scc, keratino | #D98A6A | 살구 |
| esophagus | ESCA | esophag, esca | #C29A4E | 황토 |
| cervix | CESC | cervix, cesc, cervical | #D97AA8 | 분홍보라 |
| uterus | UCEC, UCS | uter, ucec, endometr, ucs | #CC7A9E | 분홍 |
| leukemia | LAML | leukemia, laml, aml, all-leuk, cml, cll | #4060C0 | 진파랑 |
| lymphoma | DLBC | lymphoma, dlbc, dlbcl, hodgkin, nhl | #5A6FD0 | 파랑보라 |
| myeloma | — | myeloma, multiple-myeloma, mm-plasma | #6A5ACD | 보라 |
| sarcoma | SARC | sarcoma, sarc, leiomyo, liposarc | #8A6D3B | 갈 |
| gist | — | gist, gastrointest-stromal | #A6772E | 갈주황 |
| bone | — | osteosarc, bone-tumor, chondrosarc | #B0B7BE | 회 |
| mesothelioma | MESO | mesotheli, meso | #6E8A8A | 청회 |
| adrenal | ACC | adrenal, acc-adren, pheochrom, pcpg | #C08A5C | 갈주황 |
| testis | TGCT | testi, tgct, germ-cell | #4A88C0 | 파랑 |
| eye_uveal | UVM | uveal, uvm, ocular-mel | #6B4A8A | 보라 |
| bile_duct | CHOL | cholangio, bile, chol-duct | #47986B | 초록 |
| gallbladder | — | gallbladder, gbc | #6FBF9A | 연초록 |
| gastric_ep | — | gastric-ep, stomach-ep | #C67A2E | 갈주황 |
| endocrine_panc | — | insulinoma, neuroendocrine-panc, pnet | #E89A5C | 주황 |
| neuroendocrine | — | net, neuroendocrine, carcinoid | #D98A4C | 주황 |
| glioma_other | — | ependymoma, medulloblast | #5A6570 | 회청 |
| nasopharynx | — | nasophary, npc | #B5892E | 황갈 |
| salivary | — | salivary, parotid | #C79A4E | 황토 |
| small_intestine | — | small-intest, duoden, jejun, ileum | #C99AE0 | 연보라 |
| anal | — | anal, anus-scc | #B77AD6 | 보라 |
| vulva | — | vulva, vulvar | #D97AA8 | 분홍 |
| penile | — | penile, penis-scc | #4478B0 | 파랑 |
| pleura | — | pleural, pleura | #6E8A8A | 청회 |
| thymus | THYM | thymoma, thym, thymic | #7A8A9A | 회청 |
| retinoblastoma | — | retinoblast, rb-eye | #6B4A8A | 보라 |
| wilms | — | wilms, nephroblast | #4FA3D1 | 하늘 |
| neuroblastoma | — | neuroblast, nb-child | #4A5560 | 회청 |
| germ_cell | — | germ-cell, teratoma, seminoma | #4A88C0 | 파랑 |
| unknown_primary | — | cup, unknown-primary | #9AA0A6 | 회색(normal 계열) |
| normal | — | normal, control, healthy, adjacent-normal, wt | #9AA0A6 | 회색 |

### 7.4 다른 축(조직·면역)도 동일 방식
- 조직축: 5.2 앵커 + 부분일치(예: `epithel`→상피 분홍, `fibro`→섬유아 연분홍, `endothel`→내피).
- 면역축: `CD8, cytotoxic`→한 색, `CD4, helper`, `Treg`, `Bcell`, `NK`, `macro/mono`, `DC`, `neutrophil` 등 앵커 + 부분일치.
- 규칙 구조는 7.2와 같음. 사용자 축 추가 가능.

---

## 8. 컴포넌트 표기 규칙(요약)
- 판정 배지: 색 칩 + 아이콘 + 짧은 라벨(문제없음/애매/경고/차단). 색만으로 절대 표현 안 함.
- 라벨 범례: 카테고리명 + 색 + (코드↔문자열) 토글. 미분류는 회색 + 물음표.
- plot 점: 라벨 축 색 사용. hold된 id는 테두리로 구분.
- 배너: Gate=danger 상단 고정, Diagnostic=warn 인라인, 원클릭 수정 버튼 우측.
- 잠금/사용자값: 자물쇠/연필 아이콘 + base 원값 병기.

## 9. 미결
1. 다크 모드 지원 여부 (색약·대비 재정의 필요)
2. 상태축 빨강/암 색과 3색 판정 색이 화면에서 공존할 때의 영역 분리 최종 규칙(현재: 라벨=점/범례, 판정=배너/배지)
3. 암종 앵커 HEX 최종값(초안). 색약 시뮬 통과 확인
4. 코드↔문자열 매핑을 라벨 컬럼 내에 저장할지, 별도 키 파일로 둘지
5. palette.json / label 매핑을 사용자별로 둘지 프로젝트별로 둘지

## 10. 관리 규칙
- 색·폰트·아이콘 규칙은 이 파일이 원본(base). 앱은 CSS 변수로 이 값을 읽는다.
- 암종/조직/면역 앵커 추가는 7.3/7.4에 행 추가 + 키워드·앵커색. TCGA 코드는 가능하면 명시.
- 사용자 재정의는 palette.json으로만. base 불변.
- 별도 지시 전까지 덮어쓰기.
