# STATOP

**STAT**istic **O**ntology **P**latform — 통계를 대신 해 주는 도구가 아니라,
**이 자료에 이 분석이 맞는지** 먼저 묻는 도구입니다.

- 컬럼이 무엇인지(의미 타입) 확정하고 → 질문 유형을 고르고 → **쓸 수 있는 검정만** 추립니다
- 쓸 수 없다고 판정돼도 값은 보여 줍니다. 대신 **왜 안 되는지와 고치는 법**을 같이 냅니다
- 재고 나면 **다음에 무엇을 볼지**까지 냅니다 (표본이 모자란가, 다른 컬럼이 더 갈리는가)
- 여러 번 쟀으면 그 수를 세어 **다중검정 보정**을 붙입니다
- 자료 칸은 **저장하지 않습니다** — 세션에는 조작 기록만 남습니다

CLI · 터미널 전체화면(TUI) · 웹, 셋이 같은 코어를 씁니다. 전부 **로컬에서** 돕니다.
서버도, 계정도, 인터넷도 필요 없습니다.

---

## 1. 설치

필요한 것: [conda](https://docs.conda.io/en/latest/miniconda.html) (또는 mamba).

```bash
git clone https://github.com/WoobeenJeong/STATOP_public.git statop
cd statop

conda env create -f environment.yml    # 환경 만들기 (몇 분)
conda activate statop
pip install -e .                       # statop 명령 등록
```

확인:

```bash
statop --help
pytest -q                              # 949 passed 나오면 정상
```

> **웹까지 쓰려면** — `ui/dist` 가 이미 빌드돼 들어 있어 추가 설치가 필요 없습니다.
> UI 를 직접 고치려면 Node 20+ 에서 `cd ui && npm install && npm run build` 입니다.

---

## 2. 실행 — 세 가지 중 편한 것으로

### 터미널 전체화면 (처음이면 이것)

```bash
statop
```

화면 아래 버튼을 **번호로 누르거나 마우스로 클릭**합니다. `↑↓` 로 옮기고
`Enter` 로 고릅니다. 흐름은 왼쪽 위에 늘 보입니다.

### 웹

```bash
statop serve                 # http://127.0.0.1:8000/ui 가 열립니다
```

### 명령줄 (스크립트·에이전트에 끼워 쓰기 좋음)

아래는 **실제로 돌려 본 그대로**입니다 (합성 자료 001 로 연관 분석 한 바퀴).

```bash
F=demo/talk/001_group_correlation.csv

statop columns $F                      # 어떤 컬럼이 있나 (세션 없이도 됨)
statop session new --data $F           # 세션 시작 — 이후 명령은 자동으로 이 세션을 씀
statop select $F --cols sample_id,group,cfdna_conc,immune_ratio

statop types                           # 의미 타입 추론 — 후보와 근거를 같이 낸다
statop types --confirm group        --as label
statop types --confirm cfdna_conc   --as continuous
statop types --confirm immune_ratio --as proportion

statop analyze plan --question Q-03 --y cfdna_conc --group immune_ratio
#   → 쓸 수 있는 검정이 ✅/⚠ 로 추려집니다
statop analyze plan --question Q-03 --y cfdna_conc --group immune_ratio --apply
statop analyze run --test T-304        # 고른 것 하나만 돌린다
```

마지막 줄이 내는 것:

```
검정 실행: T-304 Distance correlation
  통계량 0.3018 · p = 0.00333
  dCor = 0.302          n: pairs=145
  직선이 아닌 관계도 잡습니다 — 0이면 독립이지만 방향(양·음)은 없습니다
  계획 검정 1개 기준 보정 α = 0.05 — p는 이 값과 비교하세요
  p=0.00333 < 보정 α(0.05) — 보정 후에도 유의
```

`statop --help` 로 전체 목록을 봅니다. 자주 쓰는 것:
`columns` `select` `types` `analyze` `scores` `metrics` `integrity` `derive`
`labels` `report` `session` `serve` `shell`

---

## 3. 5분 따라 하기

딸려 오는 합성 자료로 한 바퀴 돌려 봅니다.

```bash
conda activate statop
statop
```

1. **열기** — `demo/talk/001_group_correlation.csv` 를 칸에 적고 [열기]
2. **가져오기** — 쓸 컬럼을 고르고 [가져오기]
3. **의미 타입 확정** — `group` 을 label 로 확정하면 **0/1 코드 지정**이 바로 뜹니다
4. **지표 찾기** — 질문 `연관` → 컬럼 `cfdna_conc` `immune_ratio` → [검정]
5. **결론** — 재고 나면 결론 카드 하나가 뜹니다:
   - 잡힌 값과 p
   - **검정력** — 이 표본으로 잡히는 가장 작은 크기 (목표 %는 끌거나 쳐서 바꿉니다)
   - **다음에 볼 것** — "cancer 군에서는 직선이 아닙니다 → 색으로 나눠 보십시오"

`demo/talk/002_entropy_wrong_dist.csv` 는 **분포를 잘못 보면 차이가 묻히는** 자료고,
`demo/talk/003a·003b` 는 **두 파일이 같은지 대조**하는 자료입니다.
무슨 일이 일어나야 맞는지는 `python demo/verify_talk.py` 가 확인해 줍니다.

브라우저로 먼저 구경만 하려면 — `demo/talk/001.html` 을 더블클릭하세요.
설치 없이 열리는 스냅샷입니다 (002·003 도 같습니다).

---

## 4. 에이전트(Claude·ChatGPT)와 같이 쓰기

STATOP 은 **에이전트가 읽기 좋게** 만들어져 있습니다. 작업 폴더에서 에이전트에게
이렇게 알려 주면 바로 붙습니다.

```
이 저장소는 STATOP 이다. 통계 검증 도구이고 로컬에서 돈다.
- 설치: conda activate statop
- 규칙표: rules/*.yaml 이 무엇을 쓸 수 있고 왜 안 되는지를 정한다 (손으로 고치지 말 것,
  schema/registry-*.md 가 원본이고 python -m statop.rules.build 가 생성한다)
- 명령: statop --help 로 전체 목록. 흐름은 session new → select → types --confirm
  → analyze plan --apply → analyze run 순서다
- 원칙: 자료 칸은 저장하지 않는다. 세션에는 조작 기록만 남는다
```

**에이전트에게 맡기기 좋은 일**

| 하고 싶은 것 | 시키는 말 |
|---|---|
| 내 자료 훑어보기 | "`statop columns 내파일.csv` 돌리고 의미 타입이 이상한 컬럼만 짚어 줘" |
| 검정 고르기 | "`statop analyze plan --question Q-01 --y y --group g` 돌리고 ✅ 만 추려 줘" |
| 왜 안 되는지 | "빨강으로 나온 이유를 `rules/tests.yaml` 에서 찾아 근거째로 보여 줘" |
| 재현 가능하게 | "`statop report` 로 보고서 내고, 세션 json 의 조작 기록으로 재현 스크립트 만들어 줘" |

에이전트가 **자료를 직접 해석하게 두지 마세요.** STATOP 의 판정을 읽게 하고,
에이전트는 그 판정을 설명·정리하는 데 쓰는 쪽이 안전합니다. 판정의 근거는 전부
`rules/` 에 글로 적혀 있어서, 에이전트가 지어내지 않고 인용할 수 있습니다.

---

## 5. 무엇이 들어 있나

```
src/statop/      코어 — CLI · TUI · 웹 API 가 전부 이 하나를 쓴다
rules/           규칙 DB (yaml) — 무엇을 쓸 수 있고 왜 안 되는지
schema/          규칙 DB 의 원본 (registry-*.md). 여기를 고치고 다시 생성한다
ui/              웹 화면 (dist 가 이미 빌드돼 있다)
demo/            합성 자료 + 발표 스냅샷 3종
tests/           949개
```

**자료는 전부 합성입니다.** 실제 검체·환자 자료는 한 건도 들어 있지 않습니다.

---

## 6. 자주 막히는 곳

| 증상 | 까닭 |
|---|---|
| `statop: command not found` | `conda activate statop` 을 빠뜨렸거나 `pip install -e .` 전입니다 |
| 웹이 안 열림 | `statop serve` 를 띄워 둔 터미널을 닫지 마세요. 주소는 `/ui` 까지 붙입니다 |
| 한글이 깨짐 | 터미널 인코딩을 UTF-8 로. Windows 는 `chcp 65001` |
| 검정이 안 뜸 | 컬럼을 **두 개** 골랐는지, 의미 타입을 확정했는지 보세요 — 화면이 무엇이 빠졌는지 알려 줍니다 |

저장 위치는 `~/.statop/<사용자>/` 입니다. `STATOP_HOME` 으로 바꿀 수 있습니다.

---

v1.0.0-proto · 메시지 언어는 `--lang en` 으로 바꿉니다.
