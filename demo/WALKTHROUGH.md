# 직접 돌려보기 — CLI 전 과정 + 웹 띄우기

여기 나오는 명령은 **전부 실제로 실행해 확인한 것들**입니다. 출력에 대한 설명도
실제로 그렇게 나오는지 확인했습니다 (예: CLR 적용 후 S-R06이 새로 뜨는 것).
데모 데이터에는 **일부러 함정을 심어 뒀습니다** — 그냥 통과하는 데이터면 검사가
동작하는지 알 수 없기 때문입니다.

| 심어 둔 것 | 어디서 잡히나 |
|---|---|
| 조성 3성분 `frac_A/B/C` | S-R01·S-R02 → CLR 수정 |
| `pct_purity`만 0~100 척도 | S-R07 → ÷100 수정 |
| `site_code` 이름뿐인 코드 | S-R09 **차단** |
| `patient_id` 식별자 | S-R10 **차단** |
| `reads_x` vs `reads_y` 총합 9배 | S-R03 |
| `vaf`에 1.4와 −0.2 | GR-01 **차단** (정의역 밖) |
| case 군의 QC가 낮음 | 필터 후 GR-03 편향 손실 → GR-02 SRM |
| `age` 결측 9% | 결측 현황·대치 |

---

## 0. 준비

```bash
conda activate statop
cd ~/STATOP

# 데모 데이터 생성 (1,200행 × 13컬럼)
python demo/make_data.py demo/data/demo.csv
```

작업 결과가 홈(`~/.statop`)에 섞이는 게 싫으면 저장소를 따로 두세요.
**이 한 줄을 빼면 이후 세션·수식·설정이 전부 `~/.statop`에 쌓입니다.**

```bash
export STATOP_HOME=/tmp/statop_demo      # 다 해보고 지우면 됨
export D=$PWD/demo/data/demo.csv
```

---

## 1. 열기 · 훑기

```bash
statop session new --data $D
```

마지막 줄에 세션 파일 경로가 나옵니다. 이후 모든 명령에 쓰이니 변수에 담으세요.

```bash
export S=$(ls $STATOP_HOME/*/tmp/session_*.json | head -1)
echo $S
```

```bash
statop columns $D --page 1            # 25개씩 페이지. 결측 10%↑는 !, 30%↑는 !!
statop columns $D --sort missing      # 결측률 순
statop columns $D --grep frac         # 이름으로 거르기
```

**무결성(Integrity) — 두 파일이 같은가**

```bash
cp $D /tmp/copy.csv
statop integrity $D /tmp/copy.csv     # 동일

sed -i '5s/control/case/' /tmp/copy.csv
statop integrity $D /tmp/copy.csv     # 어디가 몇 % 다른지 (다르면 종료코드 1)
```

---

## 2. 컬럼 고르기

```bash
statop select $D --session $S \
  --cols patient_id,arm,site_code,diagnosis,frac_A,frac_B,frac_C,reads_x,reads_y,pct_purity,vaf,qc_score,age

statop hold --cols patient_id --session $S    # 분석 제외, 시각화엔 유지
statop compose --session $S                   # 구성 요약 (데이터 셀은 안 보임)
```

---

## 3. 분포 보기 · 라벨 매핑

```bash
statop dist $D --cols vaf --chart             # y눈금 5개 이하로 축약
statop dist $D --cols diagnosis --chart       # 카테고리는 막대

# 표시는 문자열, 계산은 코드. 3수준을 2군으로 묶으면 경고가 뜹니다
statop labels $D --column diagnosis --map control=0,hcc=1,liver=1 --session $S
```

---

## 4. 결측

```bash
statop missing show --session $S                     # 함께 비는 조합까지
statop missing impute --session $S --cols age --method median        # 미리보기
statop missing impute --session $S --cols age --method median --apply
```

허용 방법은 8개뿐입니다: `zero mean median mode group_mean group_median knn mice`.
다른 걸 넣으면 거부됩니다 — 무거운 추정기는 실행 경로가 아예 없습니다.

---

## 5. 의미 타입 확정

```bash
statop types --session $S        # 점수 없이 순위만. 확정이 필요한 것은 → 로 표시
```

확정 전에는 이후 판정이 **전부 보류**됩니다. 하나씩 확정하세요.

```bash
for t in frac_A frac_B frac_C; do statop types --session $S --confirm $t --as proportion; done
statop types --session $S --confirm reads_x    --as count
statop types --session $S --confirm reads_y    --as count
statop types --session $S --confirm pct_purity --as percent
statop types --session $S --confirm vaf        --as proportion
statop types --session $S --confirm patient_id --as id
statop types --session $S --confirm site_code  --as "nominal code"
statop types --session $S --confirm arm        --as "nominal code"
statop types --session $S --confirm diagnosis  --as "nominal code"
statop types --session $S --confirm qc_score   --as continuous
statop types --session $S --confirm age        --as continuous
```

하나라도 빼면 **전체 판정이 통째로 보류됩니다.** 남은 게 있는지 확인:

```bash
statop types --session $S | tail -3
```

확정할 때마다 그 타입으로 계산하면 무엇이 틀어지는지 함께 나옵니다.

---

## 6. 파생 컬럼 (수식)

```bash
# eps가 추천값보다 크면 차단됩니다 (경고가 아니라 거부)
statop derive --session $S --expr "log2(frac_A + eps)" --eps 1e-1 --name bad

# --name 없이 실행하면 미리보기만
statop derive --session $S --expr "log2(frac_A + eps)" --eps 1e-8
statop derive --session $S --expr "log2(frac_A + eps)" --eps 1e-8 --name log_A
```

**색으로 구분됩니다**: 청록 = 컬럼, 초록 = 행 단위 함수,
보라+점선 = 컬럼 스칼라(행마다 변하지 않음), 노랑 = eps.

```bash
statop derive --session $S --expr "log2(frac_A / mean(reads_x) + eps)" --eps 1e-8
```

LaTeX도 같은 식으로 읽습니다.

```bash
statop derive --session $S --expr '\log_2\left(\texttt{frac_B} + \varepsilon\right)' --eps 1e-8
```

**수식 라이브러리** — 이름으로 저장해 다른 컬럼에 재사용

```bash
statop formula save --name MyLog --expr "log2(frac_A + eps)" --session $S --result-type log-scale
statop formula list
statop formula apply --name MyLog --session $S --map frac_A=frac_B --eps 1e-8 --out log_B
statop formula remove MyLog
```

---

## 7. 연산 적합성 (이 계산을 해도 되는가)

```bash
# 쌍은 지정했을 때만 봅니다
statop compat check --session $S --op correlate --cols frac_A,frac_B    # S-R01
statop compat check --session $S --op compare   --cols frac_A,frac_B    # S-R02 (다른 규칙!)

# 전체 요약 — 분석 대상 12개면 쌍이 66개지만 규칙당 1건만
statop compat check --session $S --op correlate
```

연산은 `correlate | compare | regress | spread | aggregate` 다섯입니다.

**원클릭 수정 → 지정 교체 → 재판정**

```bash
# 기본은 계획만 (기록하지 않음)
statop compat fix --session $S --op correlate --cols frac_A,frac_B --rule S-R01

# eps 없이 적용하면 거부됩니다
statop compat fix --session $S --op correlate --cols frac_A,frac_B --rule S-R01 --apply

statop compat fix --session $S --op correlate --cols frac_A,frac_B --rule S-R01 --eps 1e-8 --apply
```

적용하면 그 자리에서 다시 판정합니다. 이후 전체 요약을 다시 보면
S-R01은 사라지고 **S-R06이 새로 뜹니다** — CLR 결과가 log 척도라 원척도와 섞였기 때문입니다.

```bash
statop compat check --session $S --op correlate
statop compat fix --session $S --op correlate --rule S-R07 --eps 1e-8 --apply   # ÷100
```

---

## 8. 가드레일 (이 데이터를 근거로 써도 되는가)

```bash
statop guard run --session $S --group arm --meta site_code
```

아직 손실이 없으므로 GR-03은 "**검사하지 않았다**"로 나옵니다.
검사하지 않은 것과 통과한 것은 다릅니다.

```bash
statop filter --session $S --expr "qc_score >= 0.3" --reason "QC 미달"           # 미리보기
statop filter --session $S --expr "qc_score >= 0.3" --reason "QC 미달" --apply

statop guard run --session $S --group arm --meta site_code,age --metrics vaf
```

이제 차단이 뜹니다. SRM(GR-02)에 `연결: GR-03:loss_by_group`이 붙고,
**반사실 확인**(손실을 되돌리면 비율이 맞는가)이 원인 후보의 근거로 나옵니다.

**설정 잠금**

```bash
statop guard limits                              # 전체
statop guard limits --rule GR-02

statop guard set --rule GR-03 --tier off         # 거부 — 완화 하한이 gate
statop guard set --rule GR-03 --tier diagnostic  # 거부
statop guard set --rule GR-02 --tier diagnostic  # 허용 (하한까지)
statop guard set --rule GR-01 --key action --value '"clip"'    # 거부
statop guard set --rule GR-04 --key min_group_n --value 3      # 허용

statop guard run --session $S --group arm        # 조정이 출력 끝에 항상 따라붙음
statop guard reset
```

**리포트 파일**

```bash
statop guard run --session $S --group arm --out demo/data/guard.md
statop guard run --session $S --group arm --out demo/data/guard.json
cat demo/data/guard.md
```

---

## 9. 저장

```bash
statop session save --session $S      # 날짜_프로젝트_모드_행수_시각 이름으로
ls $STATOP_HOME/*/sessions/           # 저장본 목록 (CLI 목록 명령은 아직 없음)
```

가공본 저장 — **원본은 안 바뀝니다.** 표식 컬럼과 사이드카가 함께 남습니다.

```bash
statop export --session $S --name demo_trimmed
statop columns $PWD/demo/data/demo_trimmed.csv --page 1   # 다시 열면 가공 사실을 알림
```

개별 샘플 라벨 수정 — 사유가 필수이고, 이후 모든 출력 맨 앞에 건수가 뜹니다.

```bash
statop relabel --session $S --key-column patient_id --key PT00007 \
  --column diagnosis --to control --note "검체 취합 오류로 재확인"
```

---

## 10. 전체화면 (statop)

```bash
statop                 # 명령 없이 실행하면 전체화면이 바로 뜬다
```

경로 입력칸이 먼저 나옵니다. 경로를 붙여넣고 **Enter** 또는 **[열기]** 클릭.

| 화면 | 되는 것 |
|---|---|
| 열기 | 경로 입력 · [열기] · [불러오기] (최근 저장 세션) |
| 컬럼 고르기 | 클릭·↑↓·space 체크 · `a` 이 쪽 전체 · 정렬 3버튼 · 검색 · 25개 페이지 · [선택 N개 가져오기] |
| 작업 영역 | 클릭·space hold · `d` 제외 · [컬럼 더 가져오기] · [세션 저장] |

`Tab`으로 버튼 사이를 이동하고 `Ctrl-Q`로 나갑니다.

**마우스가 안 되는 터미널이면** 상태줄에 `마우스 신호 없음`이 뜹니다. 그때는
맨 아래 `버튼: 1.결측률 순  2.고유값 순 …` 목록의 **번호키**로 같은 버튼을 누르면 됩니다.

이 화면이 다루는 건 **열기·컬럼 선택·세션**까지입니다. 타입 확정부터는 위의 CLI 명령으로
이어서 하며, 마지막 화면이 그 명령을 세션 경로까지 넣어 그대로 보여줍니다.

---

## 11. 검정하고 가설 뽑기 (모듈 A)

**화면으로**: `statop` 전체화면의 작업 영역에서 `[ 분석 ]`(번호키 2) — 질문 유형과
컬럼을 ←→로 고르고 → `[ 계획 확인 ]` → 후보(✅⚠⛔)에서 Enter로 실행 → 가설까지
한 화면입니다. 웹에도 같은 "분석 (모듈 A)" 카드가 있습니다.

**명령으로** 하려면 아래. 여기서 하는 일을 먼저 말로 하면:

> **"case군과 control군의 vaf가 다른가?"를 확인하고 싶다.**
> 그러려면 ① 그 질문을 도구에 등록하고 → ② 맞는 검정을 골라 →
> ③ 가정을 확인하고 → ④ 실행한 뒤 → ⑤ 결과를 가설 문장으로 받는다.

이 절부터는 `--session`을 안 써도 됩니다 — 최근 작업 세션이 자동으로 잡히고,
어느 세션인지 첫 줄에 표시됩니다.

### ① 질문 등록 (`analyze plan`)

"무엇을 물을 것인가"를 등록하는 단계입니다. 통계 용어로 고르지 않아도 되게
질문 유형 11종에 일상 표현이 붙어 있습니다:

```bash
statop analyze questions        # "A군과 B군이 다른가" → Q-01 처럼 찾기
```

vaf가 arm(군)에 따라 다른지 묻는 경우:

```bash
statop analyze plan --question Q-01 --y vaf --group arm --n-tests 3
```

- `--y` 측정값 · `--group` 비교할 군 · `--n-tests` 오늘 몇 번 검정할 계획인지
  (많이 할수록 유의 기준이 엄격해집니다 — 그래서 미리 적습니다)
- **미리보기입니다.** 문제(타입 미확정, id를 군에 넣음 등)가 있으면 여기서 멈춥니다.
- 아래에 검정 후보가 ✅적합/⚠확인 필요/⛔부적합으로 나옵니다.

문제 없으면 `--apply`를 붙여 기록:

```bash
statop analyze plan --question Q-01 --y vaf --group arm --n-tests 3 --apply
```

### ② 가정 확인 (`analyze checks`)

⚠ 후보들의 "확인 필요"가 실제로 괜찮은지 봅니다:

```bash
statop analyze checks
```

확인할 것: 정규성 위배 시 **원인**(소수 outlier/왜도/형태)이 붙는지,
검정력에 **어느 군이 부족한지**가 나오는지.

### ③ 실행 (`analyze run`)

후보에서 고른 검정을 돌립니다. p값만 주지 않고 효과크기·CI·보정 α 비교가 항상 붙습니다:

```bash
statop analyze run --test T-101      # Welch t
statop analyze run --test T-103      # Mann–Whitney (보조로)
```

### ④ 가설 받기 (`hypothesis`)

실행 결과를 **가설 문장 1안/2안 + 해석 + 주의사항**으로 받습니다:

```bash
statop hypothesis
```

확인할 것: CLR 변환 컬럼이면 "배수로 읽으면 안 된다" 주의가 붙는지,
보조지표 해석(spearman↔pearson 등)이 맞는 방향인지, **문장이 실제로 쓸 만한지.**

### ⑤ (선택) Ask Qwen

기계 가설이 마음에 안 들 때만. 보내기 전에 뭐가 나가는지 먼저:

```bash
statop ask --dry-run "상관 크기가 과대해 보임"
```

GPU 노드에 Qwen3 서버가 있으면 (`vllm serve Qwen/Qwen3-8B --port 8001`):

```bash
export STATOP_QWEN_URL=http://<GPU노드>:8001/v1
statop ask "상관 크기가 과대해 보임"
```

확인할 것: dry-run에 원자료 셀 값이 없는지, 사설망 밖 주소는 거부되는지.

### ⑥ 리포트

이 세션에서 한 일 전체를 파일 하나로:

```bash
statop report --out demo/data/report.html    # 브라우저로 열기
statop report --out demo/data/report.md
statop report --out demo/data/report.json
```

---

## 웹 띄우기

```bash
conda activate statop
cd ~/STATOP

# ui/dist가 없으면 먼저 빌드 (conda의 node를 써야 함 — 시스템 node는 glibc 때문에 실패)
export PATH=$HOME/anaconda3/envs/statop-node/bin:$PATH
cd ui && npm install && npm run build && cd ..

statop serve --port 8000
```

| 주소 | 무엇 |
|---|---|
| `http://127.0.0.1:8000/ui/` | 웹 화면 |
| `http://127.0.0.1:8000/docs` | REST API 문서 (직접 호출해볼 수 있음) |
| `http://127.0.0.1:8000/health` | 기동 확인 |

**서버 포트에 브라우저로 접근이 안 되는 경우**, 로컬 PC에서 터널을 뚫으면 됩니다.
(내 PC 터미널에서 실행 — 서버가 아니라)

```bash
ssh -N -L 8000:127.0.0.1:8000 jwb419@<서버주소>
```

그 다음 내 PC 브라우저에서 `http://127.0.0.1:8000/ui/`.

터널도 안 되면 브라우저 없이 REST를 직접 호출해 확인할 수 있습니다.

```bash
statop serve --port 8000 &

curl -s localhost:8000/health

curl -s -X POST localhost:8000/v1/compat/check \
  -H 'Content-Type: application/json' \
  -d "{\"session_file\":\"$S\",\"op\":\"correlate\",\"cols\":[\"frac_A\",\"frac_B\"]}" | python -m json.tool

curl -s -X POST localhost:8000/v1/guard/run \
  -H 'Content-Type: application/json' \
  -d "{\"session_file\":\"$S\",\"group\":\"arm\",\"meta\":[\"site_code\"]}" | python -m json.tool
```

### 웹 화면에서 되는 것 / 아직 CLI에만 있는 것

되는 것: 파일 열기 · 컬럼 선택(25개 페이지) · hold · 세션 저장/불러오기 ·
수식 편집기(KaTeX 렌더, 키패드, 컬럼 칩, eps 선택) · 가드레일 배너.

아직 CLI에만 있는 것: 행 필터 · 결측 대치 · 라벨 매핑 · 적합성 판정/수정 · 가공본 저장.
즉 **웹에서는 손실을 만들 수 없어** GR-03이 계속 "검사하지 않음"으로 나옵니다.

---

## 정리

```bash
rm -rf /tmp/statop_demo demo/data
unset STATOP_HOME S D
```

---

## 12. Phase 14 — 개별 점·지표 역할·재현 스니펫 (이번에 추가된 것)

11절까지가 "검정 하나를 돌린다"였다면, 여기서는 **그 결과를 믿어도 되는지**를 본다.

### 12-1. 개별 점을 보고, 결과를 끌고 있는 샘플을 뺀다

```bash
statop analyze run --test T-101          # 먼저 검정 하나
statop exclude --key-column sid --key  --note "장비 오류 — 재측정 불가"
statop analyze run --test T-101          # 제외 전/후가 함께 나온다
```

- **사유 없이는 못 뺀다.** 나중에 왜 뺐는지 답할 수 있어야 한다
- **제외 전/후가 항상 같이** 나온다. 유의성이 뒤집히면 그 사실 자체를 빨간 줄로 알린다
- **10%를 넘게 빼면 빨강** — "분석이 아니라 표본을 고른 것입니다"
- 빼기 전에 **이상점에 둔한 검정**(T-103, T-104, T-105)을 먼저 권한다

화면으로 하려면: 전체화면 `statop` → 분석 → 실행 → `[ 개별 점 보기 ]`.
웹은 산점도에서 점을 **클릭**해 고른다. 색은 층화 라벨로 나뉜다.

### 12-2. 점수 목록과 수식

```bash
statop scores --grade green --latex       # 지금 데이터로 쓸 수 있는 지표
statop scores --grade unset               # 판정할 근거가 없는 것
```

122종을 **4등급**으로 나눈다: 안됨 / 별로 / 문제없음 / **미지정**.

> **미지정은 "적합하다"가 아니다.** 규칙표의 칸이 비어 있거나 무엇이 필요한지 안 적혀
> 있으면 회색으로 둔다. 초록으로 올리면 규칙표의 공백이 적합 판정으로 둔갑한다.

`--latex` 를 주면 원식과 **대입식**(변수 자리에 내 컬럼 이름을 넣은 것)이 같이 나온다.
웹에서는 KaTeX 로 그려진다.

### 12-3. 엔트로피는 분포마다 공식이 다르다

```bash
statop entropy --column conc
```

연속 분포의 엔트로피는 정규·지수·로그정규·감마·Cauchy·디리클레가 **각각 다른 공식**이다.
어느 것을 쓸지 데이터에서 판단하고, **버린 공식과 그 이유**도 함께 보여준다.
카운트·라벨 컬럼은 애초에 대상이 아니므로 거부하고 SC-DIV-01 Shannon 으로 안내한다.

### 12-4. Goal 옆에 Support·Guardrail

```bash
statop metrics                                  # 병기 제안 + 계산까지
statop goal --score SC-ERR-02                   # Goal 을 직접 지정 (안 하면 마지막 검정)
statop roles                                    # 지금 제안 목록 보기
statop roles --support MR-S15 --guardrail MR-G06,MR-G16 --note "보고 기준"
```

- **Support**: 같은 방향을 쉬운 값으로 (표준화 효과크기는 "몇 단위"인지 말하지 않는다)
- **Guardrail**: 이걸 놓치면 결론이 뒤집힌다 (다중검정·제외 비율·조성 심플렉스·추적손실)
- **짝이 없는 Goal 도 정상이다.** 강제로 붙이지 않는다
- 관계 자체는 **base 고정**이라 새로 만들 수 없다 . 저장되는 것은
  "제안된 것 중 무엇을 보고할지"라는 선택뿐이다

### 12-5. 재작성된 가설과 재현 스니펫

```bash
statop summarize                # 한 문단 + 스니펫
statop summarize --snippet > repro.sh
```

스니펫은 **세션 생성부터 제외·대치·설계·실행까지 실제로 돌아가는** 명령 묶음이다.
빈 환경에서 `bash repro.sh` 를 돌리면 통계량·p·제외 기록이 같게 나온다 — 테스트로 잠가 뒀다.

### 웹에서 한 번에 보기

```bash
statop serve            # 주소가 출력된다
```

한 화면에 순서대로: 세션 바 → 컬럼/타입 → **점수 목록** → 파생 컬럼 →
**분석 패널**(질문·층화·대상 ID·사건 → 후보 → 실행 → 제외 전/후 → 층별 → 병기 지표 → 가설).
