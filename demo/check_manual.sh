#!/usr/bin/env bash
# MANUAL.md 에 적은 화면이 실제로 그렇게 뜨는지 대조한다.
# 설명서가 낡으면 여기서 불일치로 잡힌다 — 기능을 고쳤으면 이걸 돌려 보고 설명서도 고친다.
#   bash demo/check_manual.sh

set -e
H=$(mktemp -d); export STATOP_HOME=$H
D=/storm/User/jwb419/STATOP/demo/data/demo.csv
R() { conda run -n statop "$@" 2>&1 | grep -v Warning | grep -v "result =" | grep -v "^세션:"; }
ok=0; bad=0
chk() { if echo "$2" | grep -qF "$1"; then ok=$((ok+1)); else bad=$((bad+1)); echo "  ⛔ 매뉴얼과 다름: $1"; fi; }

R statop session new --data $D >/dev/null
R statop select $D --cols patient_id,arm,site_code,diagnosis,frac_A,frac_B,frac_C,reads_x,reads_y,pct_purity,vaf,qc_score,age >/dev/null
out=$(R statop dist $D --cols qc_score); chk "Q1 (하위 25%) 0.1918 · Q2 (중앙값) 0.352 · Q3 (상위 25%) 0.52" "$out"
chk "Q1−1.5×IQR -0.3006 · Q3+1.5×IQR 1.012" "$out"

for c in "patient_id|id" "arm|label" "site_code|nominal code" "diagnosis|label" \
  "frac_A|composition set" "frac_B|composition set" "frac_C|composition set" \
  "reads_x|count" "reads_y|count" "pct_purity|percent" "vaf|proportion" \
  "qc_score|probability" "age|continuous"; do
  R statop types --confirm "${c%%|*}" --as "${c##*|}" >/dev/null
done

out=$(R statop compat check --op correlate)
chk "적합성(Compatibility) — correlate: 분석 대상 13개 전체" "$out"
chk "[S-R09] site_code, arm, diagnosis" "$out"
chk "[S-R03] reads_x, reads_y" "$out"
chk "원클릭 수정: div100" "$out"

out=$(R statop guard run --group arm)
chk "가드레일(Guardrail) — 검사 7건, 차단" "$out"
chk "[차단] impossible — vaf — 정의역 밖 2개 (허용 0.0~1.0)" "$out"
chk "GR-03 — 손실 전후 자료가 없어 손실 검사를 하지 않았습니다" "$out"

out=$(R statop represent --repeats 8 --seed 1)
chk "식별자로 보이는 컬럼은 뺐습니다: patient_id" "$out"
chk "필요한 n 을 정하는 것은 pct_purity 입니다" "$out"

out=$(R statop analyze plan --question Q-01 --y qc_score --group arm)
chk "✅ T-104  Brunner–Munzel  — 적합" "$out"
chk "군 구성: case: n=619 · control: n=581" "$out"

R statop analyze plan --question Q-01 --y qc_score --group arm --apply >/dev/null
out=$(R statop analyze run --test T-104)
chk "통계량 15.22 · p = 1.56e-46" "$out"
chk "p=1.56e-46 < 보정 α(0.05) — 보정 후에도 유의" "$out"

out=$(R statop hypothesis)
chk "arm 군 간에 qc_score의 차이가 있다" "$out"
chk "가드레일 차단 [GR-01]" "$out"

out=$(R statop report --out $H/r.md); chk "리포트 저장" "$out"
chk "## 확정된 의미 타입 (13개)" "$(cat $H/r.md)"

# 11단계
H2=$(mktemp -d); export STATOP_HOME=$H2
DD=/storm/User/jwb419/STATOP/demo/data
R statop session new --data $DD/11_simulate_model_source.csv >/dev/null
R statop model plan --question MB-Q01 --tier MB-M0 --label label --positive 1 \
  --train $DD/12_simulate_model_train.csv --test $DD/13_simulate_model_test.csv \
  --external $DD/14_simulate_model_external.csv --validation holdout --seed 42 --apply >/dev/null
out=$(R statop model leak)
chk "세트: train=508행" "$(R statop model plan --question MB-Q01 --tier MB-M0 --label label --positive 1 --train $DD/12_simulate_model_train.csv --test $DD/13_simulate_model_test.csv --external $DD/14_simulate_model_external.csv --validation holdout --seed 42)"
chk "⛔ MB-C01 세트 간 중복 15행 — 외운 것을 맞히게 됩니다" "$out"
chk "proxy_feature: AUC=1.0000" "$out"
chk "Gate 2건 — 해결 전에는 결과를 믿을 수 없습니다" "$out"

echo
echo "매뉴얼 대조: 일치 $ok · 불일치 $bad"
rm -rf $H $H2
