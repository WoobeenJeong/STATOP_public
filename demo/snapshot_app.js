/* 스냅샷 화면 — **실제 웹(ui/src)의 마크업과 class 를 그대로** 쓴다.
 *
 * 다른 모양을 새로 만들면 발표에서 "실제와 다르다"가 된다. 그래서 카드 구조·클래스
 * 이름·문구를 웹 컴포넌트에서 그대로 가져왔다 (App.tsx · TypesPanel · FormulaEditor ·
 * FinderPanel). 값은 미리 박지 않고 `snapshot_lib.js` 가 그 자리에서 계산한다.
 */

const $ = (s) => document.querySelector(s);
const el = (h) => { const d = document.createElement("div"); d.innerHTML = h.trim(); return d.firstChild; };
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const APP = {
  rows: [], cols: [], types: {}, held: new Set(), derived: [],
  // 지표 찾기
  q: "", picked: [], ran: {}, goal: null, custom: [], method: "holm", adj: null,
  color: null, target: 0.80, myRole: "guardrail",
};

/** 열 하나가 숫자인가 — 의미 타입 추론의 가장 바깥 */
function isNum(c) { return APP.rows.every(r => r[c] === "" || !isNaN(+r[c])); }
function vals(c, rows) { return (rows || APP.rows).map(r => +r[c]).filter(v => isFinite(v)); }

/* ── 작업 영역 (App.tsx) ─────────────────────────────────── */
function workspace() {
  const body = APP.cols.map(c => {
    const u = new Set(APP.rows.map(r => r[c])).size;
    const miss = APP.rows.filter(r => r[c] === "" || r[c] === undefined).length / APP.rows.length;
    const dt = APP.derived.includes(c) ? "derived" : (isNum(c) ? "float64" : "str");
    return `<tr>
      <td class="col"${APP.held.has(c) ? ' style="color:var(--text-faint)"' : ""}>
        <span class="col-name" title="${c}">${c}</span></td>
      <td class="hint" style="margin:0">${dt}</td>
      <td class="num">${(miss * 100).toFixed(1)}%</td>
      <td class="num">${u.toLocaleString()}</td>
      <td><input type="checkbox" ${APP.held.has(c) ? "checked" : ""}
           onchange="toggleHold('${c}')"></td>
      <td style="text-align:right"><button class="sm" onclick="dropCol('${c}')">제외</button></td>
    </tr>`;
  }).join("");
  return `<div class="card" id="cWs">
    <div class="ttl">작업 영역 — 가져온 컬럼 ${APP.cols.length}개
      <span style="color:var(--text-faint)"> (분석에 씀 ${APP.cols.length - APP.held.size}
        · 분석에서 뺌 ${APP.held.size})</span></div>
    <table><thead><tr><th>컬럼명</th><th>타입</th>
      <th style="text-align:right">결측률</th><th style="text-align:right">고유값</th>
      <th style="width:70px;white-space:nowrap">분석 제외</th><th style="width:56px"></th>
    </tr></thead><tbody>${body}</tbody></table>
    <div class="hint">체크하면 <b>분석에서 빠집니다</b> — 다만 그림에서 색·점을 가르는 데는
      계속 씁니다 (환자 번호·기관 코드처럼 분석 변수가 아닌 것). 아예 빼려면 [제외] 입니다.</div>
  </div>`;
}
function toggleHold(c) { APP.held.has(c) ? APP.held.delete(c) : APP.held.add(c); render(); }
function dropCol(c) {
  APP.cols = APP.cols.filter(x => x !== c);
  APP.derived = APP.derived.filter(x => x !== c);
  APP.picked = APP.picked.filter(x => x !== c);
  delete APP.types[c]; APP.held.delete(c); APP.ran = {}; render();
}

/* ── 의미 타입 확정 (TypesPanel.tsx) ─────────────────────── */
const KNOWN = ["continuous", "count", "proportion", "probability", "percent", "label",
               "id", "nominal code", "ordinal code", "log-scale", "z-score", "datetime",
               "composition set", "normalized score", "expression index"];

function guess(c) {
  if (APP.derived.includes(c)) return ["log-scale", "continuous"];
  const u = new Set(APP.rows.map(r => r[c]));
  if (!isNum(c)) return u.size === APP.rows.length ? ["id", "label"]
                       : u.size <= 6 ? ["label", "nominal code"] : ["nominal code", "label"];
  const v = vals(c);
  if (v.every(x => Number.isInteger(x))) return u.size <= 8 ? ["nominal code", "count"] : ["count", "continuous"];
  if (v.every(x => x >= 0 && x <= 1)) return ["proportion", "probability"];
  return ["continuous", "z-score"];
}

function typesCard() {
  const rows = APP.cols.map(c => {
    const g = guess(c), cur = APP.types[c] || g[0];
    const opts = [...g, ...KNOWN.filter(k => !g.includes(k))]
      .map(k => `<option value="${k}" ${k === cur ? "selected" : ""}>${
        g.includes(k) ? (g.indexOf(k) + 1) + ". " + k : k + " (추론 밖)"}</option>`).join("");
    const five = isNum(c) ? S.five(vals(c)) : null;
    return `<tr class="${APP.types[c] ? "" : "mid"}">
      <td class="flag">${APP.types[c] ? "✔" : "→"}</td>
      <td class="col"><span class="col-name">${c}</span>
        ${APP.derived.includes(c) ? '<div class="ty-ev">· 수식에서 — ln(frag_len_sd)</div>' : ""}</td>
      <td class="hint" style="margin:0">${five ? (S.skew(vals(c)) > .8 ? "한쪽으로 치우침" : "단봉형") : "범주형"}</td>
      <td><select onchange="setType('${c}', this.value)">${opts}</select></td>
      <td style="text-align:right;white-space:nowrap">
        <button class="sm" onclick="confirmType('${c}')">${APP.types[c] ? "다시 확정" : "확정"}</button>
        ${APP.types[c] ? ` <button class="sm" onclick="unconfirm('${c}')">확정 취소</button>` : ""}
        <button class="sm" onclick="showDist('${c}')">분포</button>
        ${APP.types[c] === "label" || APP.types[c] === "nominal code"
          ? ` <button class="sm" onclick="openMap('${c}')">코드 지정</button>` : ""}
      </td></tr>`;
  }).join("");
  const n = Object.keys(APP.types).length;
  return `<div class="card" id="cTypes">
    <div class="ttl">의미 타입 확정</div>
    <div class="row"><button class="pri" onclick="reinfer()">다시 추론</button>
      <span class="hint" style="margin:0">확정 ${n}개 · 미확정 ${APP.cols.length - n}개${
        APP._reinfer ? ` · ${APP._reinfer}` : ""}</span></div>
    <table><thead><tr><th></th><th>컬럼</th><th>분포</th><th>타입</th>
      <th style="width:190px"></th></tr></thead><tbody>${rows}</tbody></table>
    ${mapBox()}
    <div id="distBox"></div></div>`;
}
function setType(c, v) { APP._pend = APP._pend || {}; APP._pend[c] = v; }
/** 컬럼이 늘었으면 다시 본다 — 고른 것은 버리고 **추론을 처음부터** (확정한 것은 둔다) */
function reinfer() {
  APP._pend = {};
  const open = APP.cols.filter(c => !APP.types[c]);
  APP._reinfer = open.length ? `다시 추론함: ${open.join(", ")}` : "모두 확정되어 있습니다";
  render();
}
function confirmType(c) {
  APP.types[c] = (APP._pend && APP._pend[c]) || guess(c)[0];
  APP.ran = {};
  // label 확정 → 바로 코드 매핑 (CLI·웹과 같은 한 흐름)
  if (APP.types[c] === "label" || APP.types[c] === "nominal code") openMap(c);
  else render();
}
/** 어느 값이 0 이고 어느 값이 1 인가 — 방향이 뒤집히면 결과가 반대가 된다 (MB-C13) */
function openMap(c) {
  const vc = {};
  APP.rows.forEach(r => { vc[r[c]] = (vc[r[c]] || 0) + 1; });
  const order = Object.entries(vc).sort((a, b) => b[1] - a[1]).map(x => x[0]);
  APP.maps = APP.maps || {};
  if (!APP.maps[c]) APP.maps[c] = Object.fromEntries(order.map((v, i) => [v, i]));
  APP.mapCol = c; render();
}
function setCode(v, code) {
  const c = APP.mapCol;
  APP.maps[c][v] = Math.max(0, Math.min(9, code));
  render();
}
function closeMap(save) {
  if (!save) delete APP.maps[APP.mapCol];
  APP.mapCol = null; render();
}
function mapBox() {
  const c = APP.mapCol;
  if (!c) return "";
  const m = APP.maps[c], vc = {};
  APP.rows.forEach(r => { vc[r[c]] = (vc[r[c]] || 0) + 1; });
  const rows = Object.keys(m).map(v => `<tr>
    <td class="col">${esc(v)}</td>
    <td class="num">${vc[v] || 0}</td>
    <td class="num">${((vc[v] || 0) / APP.rows.length * 100).toFixed(1)}%</td>
    <td>${[0, 1, 2, 3].map(k => `<button class="sm${m[v] === k ? " on" : ""}"
      onclick="setCode('${esc(v)}', ${k})">${k}</button>`).join(" ")}</td></tr>`).join("");
  const groups = {};
  Object.entries(m).forEach(([v, k]) => (groups[k] = groups[k] || []).push(v));
  return `<div class="ty-dist">
    <div class="ttl" style="margin-bottom:6px">${c} — 코드 지정 (어느 값이 0 인가)</div>
    <table><thead><tr><th>값</th><th style="text-align:right">n</th>
      <th style="text-align:right">비율</th><th style="width:180px">코드</th>
    </tr></thead><tbody>${rows}</tbody></table>
    <div class="hint">묶으면 이렇게 됩니다 — ${Object.entries(groups)
      .map(([k, vs]) => `${k}=${vs.join("+")}`).join(" · ")}</div>
    <div class="hint" style="margin-top:4px">같은 코드를 주면 **두 수준이 한 군으로 묶입니다**.
      양성 클래스가 0 이면 AUC·민감도가 반대 방향을 가리킵니다</div>
    <div class="row" style="margin-top:6px">
      <button class="sm" onclick="closeMap(true)">이대로 저장</button>
      <button class="sm" onclick="closeMap(false)">취소</button></div></div>`;
}
function unconfirm(c) { delete APP.types[c]; APP.ran = {}; render(); }
function showDist(c) {
  // 범주형은 다섯 수가 없다 — 수준별로 얼마나 있는지가 분포다 (describe_series 와 같다)
  if (!isNum(c)) {
    const vc = {};
    APP.rows.forEach(r => { vc[r[c]] = (vc[r[c]] || 0) + 1; });
    const tot = APP.rows.length;
    const levels = Object.entries(vc).sort((a, b) => b[1] - a[1]);
    $("#distBox").innerHTML = `<div class="ty-dist">
      <div class="ttl" style="margin-bottom:6px">${c} — 범주형 · 수준 ${levels.length}개</div>
      ${levels.slice(0, 12).map(([k, n]) => `<div class="ty-level">
        <span class="col">${esc(k)}</span>
        <span class="ty-lvbar" style="width:${(n / tot * 100).toFixed(1)}%"></span>
        <span class="hint" style="margin:0">${(n / tot * 100).toFixed(1)}% (${n})</span>
      </div>`).join("")}
      ${levels.length > 12 ? `<div class="hint">나머지 ${levels.length - 12}개 수준은 접었습니다</div>` : ""}
    </div>`;
    return;
  }
  const v = vals(c), f = S.five(v);
  const lo = f.min, hi = f.max, h = S.hist(v, 20, lo, hi), top = Math.max(...h);
  const bars = h.map(b => `<div class="ty-bar" style="height:${Math.max(2, b / top * 100)}%"></div>`).join("");
  const five = [["최소", f.min], ["Q1 (하위 25%)", f.q1], ["Q2 (중앙값)", f.q2],
                ["Q3 (상위 25%)", f.q3], ["최대", f.max], ["IQR (Q3−Q1)", f.iqr],
                ["Q1−1.5×IQR", f.q1 - 1.5 * f.iqr], ["Q3+1.5×IQR", f.q3 + 1.5 * f.iqr]];
  $("#distBox").innerHTML = `<div class="ty-dist">
    <div class="ttl" style="margin-bottom:6px">${c}</div>
    <div class="ty-plot"><div class="ty-yaxis"><span>${top}</span><span>0</span></div>
      <div class="ty-plotbody"><div class="ty-hist">${bars}</div>
        <div class="ty-xaxis"><span>${S.fmt(lo)}</span><span>${S.fmt((lo + hi) / 2)}</span>
          <span>${S.fmt(hi)}</span></div></div></div>
    <div class="ty-fives">${five.map(([k, v2]) =>
      `<span><i>${k}</i>${S.fmt(v2)}</span>`).join("")}</div>
    <div class="hint">울타리 — 이 범위 밖의 값을 IQR 기준 바깥값으로 셉니다</div>
    <div class="hint" style="margin-top:4px">왜도 ${S.fmt(S.skew(v), 3)}</div></div>`;
}

/* ── 지표 찾기 (FinderPanel.tsx) ─────────────────────────── */
const QUESTIONS = [
  ["Q-01", "차이 (그룹 간 위치 비교)", '"A군과 B군이 다른가", "처리 전후"'],
  ["Q-02", "비율/빈도 차이", '"양성 비율이 다른가"'],
  ["Q-03", "연관 (두 변수 관계 강도)", '"X가 크면 Y도 큰가"'],
  ["Q-04", "상호작용/조절", '"약효가 성별에 따라 다른가"'],
  ["Q-05", "경향/추세", '"용량이 늘면 반응이 단조 증가하나"'],
  ["Q-06", "일치도/재현성", '"두 측정자가 같은 값을 내는가"'],
  ["Q-07", "분포 비교 (형태 자체)", '"두 분포가 같은가"'],
  ["Q-08", "예측/설명 (회귀)", '"Y를 X들로 설명"'],
  ["Q-09", "생존/사건 시간", '"생존 곡선이 다른가"'],
  ["Q-10", "조성 데이터", '"비율이 군 간 다른가"'],
  ["Q-11", "사전지정 대비", '"정상=교란≠암"'],
  ["Q-12", "표본 크기·대표성", '"몇 개를 골라야 전체를 대표하나"'],
];

const TESTS = {
  "Q-03": [
    ["T-302", "Spearman ρ", "rho", "green", "다수 outlier, 비정규, 순위", "단조성",
     (x, y) => S.spearman(x, y)],
    ["T-303", "Kendall τ", "tau", "green", "소표본, 동점 많음", "단조성",
     (x, y) => S.kendall(x, y)],
    ["T-304", "Distance correlation", "dCor", "green", "비선형·비단조 의심", "독립성",
     (x, y) => S.dcor(x, y, 300)],
    ["T-301", "Pearson r", "r", "yellow", "직선 관계, 정규에 가까움",
     "정규성·등분산·선형성 (C-01, C-03, C-08 미확인)", (x, y) => S.pearson(x, y)],
  ],
  "Q-01": [
    ["T-101", "Welch t", "Hedges g", "green", "두 군, 분산이 달라도", "정규성 (C-01)",
     (a, b) => { const w = S.welch(a, b); return { v: w.d, p: w.p, extra: w }; }],
    ["T-104", "Brunner–Munzel", "P(X>Y)", "green", "정규 아님, 분산 달라도", "없음",
     (a, b) => { const m = S.mwu(a, b); return { v: m.auc, p: m.p }; }],
  ],
};

function finder() {
  const cols = APP.cols.filter(c => !APP.held.has(c));
  const chips = QUESTIONS.map(([id, q, w]) =>
    `<button class="fd-chip${APP.q === id ? " on" : ""}" onclick="pickQ('${id}')">${q}</button>`).join("");
  const colChips = cols.map(c =>
    `<button class="fx-chip${APP.picked.includes(c) ? " on" : ""}" onclick="pickCol('${c}')">${
      APP.picked.includes(c) ? (APP.picked.indexOf(c) + 1) + ". " + c : c}</button>`).join("");
  const words = (QUESTIONS.find(q => q[0] === APP.q) || [])[2] || "";

  return `<div class="card" id="cFind">
    <div class="ttl">지표 찾기 — 무엇을 알고 싶은가 → 어느 컬럼으로 → 무엇을 쓸까</div>
    <div class="fn-step"><span class="fn-no">1</span><div class="fn-body">
      <div class="row"><input type="text" placeholder="이름을 알면 여기서 — 상관, 생존, 일치도…"
        oninput="filterQ(this.value)"></div>
      <div class="fd-chips" id="qChips" style="margin-top:6px">${chips}</div>
      ${APP.q ? `<div class="hint" style="margin-top:4px">${words}</div>` : ""}
    </div></div>

    <div class="fn-step"><span class="fn-no">2</span><div class="fn-body">
      <div class="fd-chips">${colChips}</div>
      <div class="hint" style="margin-top:4px">두 개까지 고릅니다 · 순서가 의미를 가집니다
        (첫째가 보려는 값)</div>
      <div class="row" style="margin-top:4px">
        <span class="hint" style="margin:0">색으로 나눌 군</span>
        <button class="sm${!APP.color ? " on" : ""}" onclick="setColor('')">나누지 않음</button>
        ${colorCols().map(c => `<button class="sm${APP.color === c ? " on" : ""}"
            onclick="setColor('${c}')">${c}</button>`).join("")}
        ${colorCols().length ? "" :
          `<span class="hint" style="margin:0">나눌 군 컬럼이 없습니다</span>`}
      </div>
    </div></div>

    <div class="fn-step"><span class="fn-no">3</span><div class="fn-body">
      ${step3()}
    </div></div>
  </div>`;
}

function filterQ(t) {
  const f = t.trim().toLowerCase();
  $("#qChips").innerHTML = QUESTIONS.filter(([id, q, w]) =>
    !f || (id + q + w).toLowerCase().includes(f)).map(([id, q]) =>
    `<button class="fd-chip${APP.q === id ? " on" : ""}" onclick="pickQ('${id}')">${q}</button>`).join("")
    || '<span class="hint">맞는 갈래가 없습니다</span>';
}
/** 색으로 나눌 수 있는 것 — **군 컬럼만** (explore.color_columns 와 같은 규칙).
 *  연속값이나 식별자를 색에 넣으면 점마다 다른 색이 되어 그림이 못 쓰게 된다 */
/** 군을 가리키는 컬럼인가 — **확정된 의미 타입이 먼저다.** label 이 0/1 로 적혀
 *  있다고 숫자로 보면 군이 군으로 안 보인다 (explore.GROUPY 와 같은 규칙) */
const GROUPY = ["label", "nominal code", "ordinal code"];
function isGroupy(c) {
  const t = APP.types[c];
  if (t) return GROUPY.includes(t);
  return !isNum(c);
}
function colorCols() {
  const y = APP.picked[0];           // 보려는 값 자체는 색으로 나누지 않는다
  return APP.cols.filter(c => c !== y && isGroupy(c)
    && new Set(APP.rows.map(r => r[c])).size >= 2
    && new Set(APP.rows.map(r => r[c])).size <= 8);
}
function setColor(c) { APP.color = c || null; render(); }
function pickQ(id) { APP.q = APP.q === id ? "" : id; APP.ran = {}; APP.adj = null; render(); }
function pickCol(c) {
  APP.picked = APP.picked.includes(c) ? APP.picked.filter(x => x !== c)
             : [...APP.picked, c].slice(-2);
  APP.ran = {}; APP.adj = null; render();
}

/** 이 질문·이 컬럼에 쓸 수 있는 것 — 없으면 왜 없는지 */
/** 둘째 컬럼이 무엇의 자리인가 — explore.SECOND_ROLE 과 같은 표 */
const SECOND_ROLE = { "Q-03": "value", "Q-06": "value", "Q-08": "value", "Q-09": "event" };
const ROLE_ASK = {
  group: "군 컬럼을 하나 더 고르십시오 — 무엇과 무엇을 비교할지가 있어야 계산됩니다",
  value: "수치 컬럼을 하나 더 고르십시오 — 두 값 사이를 보는 질문입니다",
  event: "사건 컬럼을 하나 더 고르십시오 — 일어났는가/아닌가를 가리키는 컬럼입니다",
};
function secondCols() {
  const role = SECOND_ROLE[APP.q] || "group";
  return APP.cols.filter(c => !APP.picked.includes(c) && !APP.held.has(c)).filter(c => {
    const k = new Set(APP.rows.map(r => r[c])).size;
    if (role === "value") return isNum(c) && !isGroupy(c) && k > 2;
    if (role === "event") return k === 2;
    return isGroupy(c) && k >= 2 && k <= 12;
  });
}

function candidates() {
  if (!APP.q) return { problems: [], list: [] };
  // **컬럼 하나로는 어느 질문도 못 돌린다.** 그런데도 목록을 내밀면 눌러도 아무 일이
  // 없는 것처럼 보인다 — 막고, 무엇을 더 고를지를 누를 수 있게 낸다
  if (APP.picked.length === 1) {
    const role = SECOND_ROLE[APP.q] || "group", cs = secondCols();
    return { problems: [ROLE_ASK[role] + (cs.length
      ? `<div class="row" style="margin-top:6px"><span class="hint" style="margin:0">이 중에서 고를 수 있습니다</span>`
        + cs.map(c => `<button class="sm" onclick="pickCol('${c}')">${c}</button>`).join("") + "</div>"
      : ` — 쓸 만한 컬럼이 없습니다`)], list: [] };
  }
  if (APP.picked.length < 2) return { problems: [], list: [] };
  const [a, b] = APP.picked;
  const unconf = APP.picked.filter(c => !APP.types[c]);
  if (unconf.length) return { problems: [`의미 타입을 먼저 확정하세요 — ${unconf.join(", ")} (S-R14)`], list: [] };
  const list = TESTS[APP.q];
  if (!list) return { problems: [`이 스냅샷은 ${APP.q} 를 계산하지 않습니다 — 실제 STATOP 는 12종 전부 돕니다`], list: [] };
  if (APP.q === "Q-03" && !(isNum(a) && isNum(b)))
    return { problems: ["연관은 두 변수가 모두 수치여야 합니다 (S-R09)"], list: [] };
  if (APP.q === "Q-01") {
    const lab = APP.types[b];
    if (!(isNum(a) && (lab === "label" || lab === "nominal code")))
      return { problems: ["차이는 [값 컬럼] × [군 컬럼] 입니다 — 둘째를 라벨로 확정하세요"], list: [] };
  }
  return { problems: [], list };
}

function step3() {
  if (!APP.q || !APP.picked.length)
    return `<div class="hint" style="margin-top:0">질문과 컬럼을 고르면 여기에
      쓸 수 있는 것들이 뜹니다.</div>`;
  const { problems, list } = candidates();
  if (problems.length) return problems.map(p => `<div class="warnbox">${p}</div>`).join("");

  const head = plotCard();
  const rows = list.map(t => {
    const [id, name, eff, verdict, why, assume] = t;
    const r = APP.ran[id];
    const adj = APP.adj ? (APP.adj.find(x => x.id === id) || {}).p_adjusted : null;
    return `<div class="fn-row v-${verdict}">
      <div class="fn-top">
        <span class="fn-flag">${verdict === "green" ? "✅ 문제없음" : "⚠ 별로"}</span>
        <b>${name}</b><span class="hint" style="margin:0">${id}</span>
        <span class="fn-val">${r
          ? `${eff} ${S.fmt(r.v)} · p ${S.fmtP(r.p)}${adj != null ? ` → ${S.fmtP(adj)}` : ""}`
          : `<button class="sm" onclick="runTest('${id}')">검정</button>`}
          <button class="sm" onclick="toggleRule('${id}')">수식·근거</button></span>
      </div>
      <div class="hint" style="margin:0">${why}</div>
      ${APP._rule === id ? `<div class="fn-rule">
        <div><span class="sc-axk">가정</span>${assume}</div>
        <div><span class="sc-axk">효과크기</span>${eff}</div>
        <div class="hint" style="margin:0">규칙표 2.3 Q-03 연관</div></div>` : ""}
      ${r ? `<div class="fn-acts">
        <span class="hint" style="margin:0">n ${r.n}</span>
        <button class="sm" ${APP.goal === id ? "disabled" : ""}
          onclick="setGoal('${id}','${name}')">${APP.goal === id ? "★ Goal" : "Goal로"}</button>
        <button class="sm" onclick="runTest('${id}')">다시</button>
        <button class="sm${APP.focus === id ? " on" : ""}" onclick="focusTest('${id}')">${
          APP.focus === id ? "검정력에서 보는 중" : "검정력에서 보기"}</button></div>` : ""}
    </div>`;
  }).join("");

  const n = Object.keys(APP.ran).length;
  const adjBox = n >= 2 ? `<div class="fn-adj">
      <div class="row"><span class="hint" style="margin:0">${n}번 쟀습니다 — 함께 보정</span>
        ${["holm:Holm (기본)", "bh:BH (FDR)", "bonferroni:Bonferroni", "none:보정 없음"]
          .map(x => { const [k, l] = x.split(":");
            return `<button class="sm${APP.method === k ? " on" : ""}" onclick="adjust('${k}')">${l}</button>`;
          }).join("")}</div>
      ${APP.adj ? `<div class="hint" style="margin-top:4px">여러 번 재면 우연히 작은 p 가
        나온다 — 몇 번 쟀는지를 같이 세야 한다</div>` : ""}</div>` : "";

  setTimeout(drawPlot, 0);
  return head + rows + sumCard() + adjBox + goalBox();
}

function runTest(id) {
  const t = TESTS[APP.q].find(x => x[0] === id);
  const [a, b] = APP.picked;
  let out, n;
  if (APP.q === "Q-03") {
    const rows = APP.rows.filter(r => isFinite(+r[a]) && isFinite(+r[b]));
    out = t[6](rows.map(r => +r[a]), rows.map(r => +r[b]));
    n = `pairs ${rows.length}`;
  } else {
    const g = [...new Set(APP.rows.map(r => r[b]))];
    const A = APP.rows.filter(r => r[b] === g[0]).map(r => +r[a]);
    const B = APP.rows.filter(r => r[b] === g[1]).map(r => +r[a]);
    out = t[6](A, B);
    n = `${g[0]} ${A.length} · ${g[1]} ${B.length}`;
  }
  APP.ran[id] = { ...out, n };
  APP.focus = id;              // **방금 잰 것**을 검정력에서 본다 (덧씌우지 않는다)
  APP.adj = null;
  render();
}
function toggleRule(id) { APP._rule = APP._rule === id ? null : id; render(); }
function focusTest(id) { APP.focus = id; render(); }
function adjust(m) {
  APP.method = m;
  const items = Object.entries(APP.ran).map(([id, r]) => ({ id, p: r.p }));
  if (items.length < 2 || m === "none") { APP.adj = m === "none" ? null : APP.adj; render(); return; }
  const n = items.length;
  const order = [...items].sort((a, b) => a.p - b.p);
  let out = [];
  if (m === "bonferroni") out = items.map(x => ({ ...x, p_adjusted: Math.min(1, x.p * n) }));
  else if (m === "holm") {
    let run = 0;
    out = order.map((x, i) => { run = Math.max(run, x.p * (n - i)); return { ...x, p_adjusted: Math.min(1, run) }; });
  } else {
    let run = 1;
    out = [...order].reverse().map((x, i) => {
      run = Math.min(run, x.p * n / (n - i)); return { ...x, p_adjusted: Math.min(1, run) };
    }).reverse();
  }
  APP.adj = out; render();
}
function setGoal(id, name) { APP.goal = id; APP.goalName = name; render(); }

/** 규칙표(MR-S/MR-G)가 이 Goal 에 정해 둔 짝 — 실제 STATOP 가 내는 것만 적는다 */
const RECS = {
  "T-304": { support: [["MR-S10", "산점도·Pearson r", "방향 없는 연관 → 그림·단순 상관으로"]],
             guardrail: [] },
  "T-101": { support: [["MR-S15", "원척도 평균차 + CI (P-203)", "표준화 효과 → 원단위"]],
             guardrail: [] },
};
function toggleRec(id) {
  APP.roles = APP.roles || {};
  APP.roles[id] = !APP.roles[id];
  render();
}
function goalBox() {
  if (!APP.goal) return "";
  APP.roles = APP.roles || {};
  const base = RECS[APP.goal] || { support: [], guardrail: [] };
  const list = (kind, head) => base[kind].length ? `<div style="margin-top:6px">
      <div class="hint" style="margin:0">${head}</div>
      ${base[kind].map(([id, name, why]) => `<label class="fn-role">
        <input type="checkbox" ${APP.roles[id] ? "checked" : ""} onchange="toggleRec('${id}')">
        <span><b>${name}</b> <span class="hint" style="margin:0">${id}</span> — ${why}</span>
      </label>`).join("")}</div>` : "";
  const mine = APP.custom.map((c) => `<label class="fn-role">
      <input type="checkbox" checked> <span><b>${esc(c.name)}</b>
      <span class="fn-mine">✎ 사용자 지정</span>${c.why ? " — " + esc(c.why) : ""}</span></label>`).join("");
  const nPicked = Object.values(APP.roles).filter(Boolean).length + APP.custom.length;
  return `<div class="fn-adj">
    <div class="hint" style="margin-top:0"><b>목표 지표(Goal)</b> ${APP.goalName}
      — 함께 볼 것을 고르세요</div>
    ${list("support", "함께 볼 것 (support)")}
    ${list("guardrail", "틀어지면 막을 것 (guardrail)")}
    ${base.support.length || base.guardrail.length ? ""
      : `<div class="hint">규칙표가 이 조합에 정해 둔 짝은 없습니다 (짝을 강제하지 않습니다)</div>`}
    ${mine}
    ${nPicked ? `<button class="sm" style="margin-top:6px">함께 보고할 것으로 저장</button>` : ""}
    ${pickable().length ? `<div style="margin-top:8px">
      <div class="row"><span class="hint" style="margin:0">목록에서 고르기 —</span>
        ${["support", "guardrail"].map(k => `<button class="sm${APP.myRole === k ? " on" : ""}"
          onclick="setMyRole('${k}')">${k === "support" ? "함께 볼 것" : "틀어지면 막을 것"}</button>`).join("")}
      </div>
      <div class="fd-chips" style="margin-top:4px">
        ${pickable().map(c => `<button class="fx-chip"
          onclick="addPicked('${esc(c)}')">${esc(c)}</button>`).join("")}
      </div></div>` : ""}
    <div class="row" style="margin-top:8px">
      <select id="myRole" onchange="setMyRole(this.value)">
        <option value="support"${APP.myRole === "support" ? " selected" : ""}>support (함께 볼 것)</option>
        <option value="guardrail"${APP.myRole !== "support" ? " selected" : ""}>guardrail (틀어지면 막을 것)</option></select>
      <input type="text" id="myName" placeholder="무엇을 함께 볼까요 — 예: Spearman ρ"
             style="min-width:120px">
      <input type="text" id="myWhy" placeholder="왜 (선택)" style="min-width:120px">
      <button class="sm" onclick="addMine()">내 추천에 넣기</button></div>
    <div class="hint" style="margin:0">규칙표에 없는 것도 넣을 수 있습니다.
      출처가 '사용자 지정'으로 남습니다</div></div>`;
}
/** 고를 수 있는 것 — 이 질문의 다른 검정에서 Goal 과 이미 넣은 것을 뺀다 */
function pickable() {
  const mine = APP.custom.map(c => c.name);
  return (TESTS[APP.q] || []).filter(t => t[0] !== APP.goal && !mine.includes(t[1]))
                             .map(t => t[1]);
}
function setMyRole(r) { APP.myRole = r; render(); }
function addPicked(name) {
  APP.custom.push({ role: APP.myRole || "guardrail", name, why: "" });
  render();
}
function addMine() {
  const name = $("#myName").value.trim();
  if (!name) return;
  APP.custom.push({ role: APP.myRole || "guardrail", name, why: $("#myWhy").value.trim() });
  render();
}

/* ── 파생 컬럼 만들기 (FormulaEditor.tsx) ────────────────── */
const FUNCS = ["log", "ln", "log2", "log10", "sqrt", "abs", "pow", "exp", "round",
               "zscore", "rank", "arcsinh"];
const CONSTS = { pi: Math.PI, e: Math.E };

function deriveCard() {
  const cols = APP.cols.filter(c => isNum(c));
  const chips = cols.map(c => `<button class="fx-chip" onclick="ins('${c}')">${c}</button>`).join("");
  const keys = FUNCS.map(f => `<button class="fx-key r-row_func" onclick="ins('${f}()', 1)">${f}</button>`).join("");
  return `<div class="card" id="cDerive">
    <div class="ttl">파생 컬럼 만들기</div>
    ${(typeof DATA !== "undefined" && DATA.examples || []).length ? `
    <div class="fx-ex">
      <div class="hint" style="margin:0">이 자료에서 쓸 만한 식 — 누르면 칸에 들어갑니다</div>
      ${DATA.examples.map((e, i) => `<div class="fx-exrow">
        <button class="sm" onclick="useExample(${i})">예${i + 1}</button>
        <code>${esc(e.expr)}</code>
        <span class="hint" style="margin:0">${e.why}</span></div>`).join("")}
    </div>` : ""}
    <div class="row">
      <input type="text" id="expr" spellcheck="false" placeholder="log2(frac_A + eps)"
             value="${APP._expr || ""}" oninput="preview()">
      <button class="sm" onclick="setExpr('')">지우기</button></div>
    <div class="fx-chips">${chips}</div>
    <div class="fx-pad"><div class="fx-padrow"><span class="fx-tag r-row_func">행 단위 함수</span>${keys}</div>
      <div class="fx-padrow"><span class="fx-tag">연산</span>
        ${["+", "-", "*", "/", "**"].map(o => `<button class="fx-key" onclick="ins(' ${o} ')">${o}</button>`).join("")}
        <button class="fx-key" onclick="ins('()', 1)">( )</button>
        <button class="fx-key r-eps" onclick="ins('eps')">eps</button>
        <button class="fx-key r-const" onclick="ins('pi')">pi</button>
        <button class="fx-key r-const" onclick="ins('e')">e</button></div></div>
    <div id="fxOut"></div>
    <div class="row" style="margin-top:12px">
      <input type="text" id="newName" placeholder="새 컬럼 이름" style="min-width:160px"
             value="${APP._name || ""}" oninput="APP._name=this.value">
      <button class="pri" id="mkBtn" onclick="commit()">파생 컬럼 만들기</button>
      <span class="hint" id="mkWhy" style="margin:0"></span></div>
  </div>`;
}
function setExpr(v) { APP._expr = v; render(); }
function useExample(i) {
  const e = DATA.examples[i];
  APP._expr = e.expr; APP._name = e.name; render();
  preview();
}
function ins(t, back = 0) {
  const e = $("#expr");
  const at = e.selectionStart ?? e.value.length;
  e.value = e.value.slice(0, at) + t + e.value.slice(e.selectionEnd ?? at);
  APP._expr = e.value;
  e.focus(); e.setSelectionRange(at + t.length - back, at + t.length - back);
  preview();
}

/** 수식을 계산한다 — 화이트리스트 함수와 컬럼 이름만 */
function evalExpr(expr) {
  const names = [...new Set(expr.match(/[A-Za-z_][A-Za-z0-9_]*/g) || [])];
  const used = names.filter(n => APP.cols.includes(n));
  const bad = names.filter(n => !APP.cols.includes(n) && !FUNCS.includes(n)
    && !(n in CONSTS) && n !== "eps");
  if (bad.length) throw new Error(`모르는 이름: ${bad.join(", ")}`);
  if (!used.length) throw new Error("컬럼이 하나도 없습니다");
  const F = { log: Math.log, ln: Math.log, log2: Math.log2, log10: Math.log10,
              sqrt: Math.sqrt, abs: Math.abs, pow: Math.pow, exp: Math.exp,
              round: (x, k = 0) => Math.round(x * 10 ** k) / 10 ** k,
              arcsinh: Math.asinh };
  const body = "return " + expr.replace(/\b([A-Za-z_][A-Za-z0-9_]*)\b/g,
    (m) => APP.cols.includes(m) ? `(+r["${m}"])`
         : (FUNCS.includes(m) ? `F.${m}` : (m in CONSTS ? `C.${m}` : m)));
  const fn = new Function("r", "F", "C", "eps", body);
  return APP.rows.map(r => fn(r, F, CONSTS, 1e-6));
}

function preview() {
  const expr = ($("#expr") || {}).value || "";
  APP._expr = expr;
  const out = $("#fxOut"), why = $("#mkWhy");
  if (!expr.trim()) { out.innerHTML = ""; if (why) why.textContent = "식을 먼저 쓰세요"; return; }
  try {
    const v = evalExpr(expr).filter(x => isFinite(x));
    const f = S.five(v);
    out.innerHTML = `<div class="fx-stats">
      <span>n ${APP.rows.length.toLocaleString()}</span>
      <span>유한 ${v.length.toLocaleString()}</span>
      <span class="${APP.rows.length - v.length ? "bad" : ""}">NaN ${APP.rows.length - v.length}</span>
      <span>${S.fmt(f.min)} ~ ${S.fmt(f.max)}</span>
      <span class="fx-rtype">${/log|ln/.test(expr) ? "log-scale" : "continuous"}</span></div>
      <div class="hint">왜도 ${S.fmt(S.skew(v), 3)} · 중앙 ${S.fmt(f.q2)}</div>`;
    if (why) why.textContent = APP._name ? "" : "새 컬럼 이름을 쓰세요";
  } catch (e) {
    out.innerHTML = `<div class="err">${esc(e.message)}</div>`;
    if (why) why.textContent = "식에 오류가 있습니다";
  }
}

function commit() {
  const expr = ($("#expr") || {}).value || "", name = ($("#newName") || {}).value.trim();
  if (!expr.trim() || !name) return;
  let v;
  try { v = evalExpr(expr); } catch (e) { return; }
  APP.rows.forEach((r, i) => r[name] = isFinite(v[i]) ? Number(v[i].toFixed(6)) : "");
  APP.cols.push(name); APP.derived.push(name);
  APP._expr = ""; APP._name = ""; APP.ran = {};
  render();
}


/* ── 결론 — 재고 나면 **여기 하나만** 보면 된다 (explore.next_steps) ──────── */
const GROUP_MIN = 15, DCOR_GAP = .15, SKEW_HIGH = .8, SKEW_OK = .5, SMALL_D = .5;

/** 차이에서 다음에 볼 것 — 다른 컬럼이 더 갈리는가, 그 컬럼이 치우쳤는가 */
function stepsDiff(focus) {
  const [y, g] = APP.picked, lv = [...new Set(APP.rows.map(r => r[g]))];
  if (lv.length !== 2) return null;
  const by = c => lv.map(l => vals(c, APP.rows.filter(r => r[g] === l)));
  const dOf = c => { const [a, b] = by(c); return S.hedges ? S.hedges(a, b) : hedges(a, b); };
  const [a0, b0] = by(y), d0 = Math.abs(hedges(a0, b0));
  const sig = focus.p < .05;
  const out = { head: `${y} 를 ${g} 로 갈라 봤습니다 — ${focus.name}`, lines: [], steps: [], scan: [] };
  out.lines.push(sig ? `차이가 있습니다 (효과크기 ${d0.toFixed(2)} · p ${S.fmtP(focus.p)})`
                     : `차이라고 하기 어렵습니다 (효과크기 ${d0.toFixed(2)} · p ${S.fmtP(focus.p)})`);
  if (sig && d0 < SMALL_D)
    out.lines.push(`다만 효과크기(${d0.toFixed(2)})는 작습니다 — 유의하다고 해서 큰 차이는 아닙니다`);
  APP.cols.forEach(c => {
    if (c === y || c === g || !isNum(c) || isGroupy(c)) return;
    const [a, b] = by(c);
    if (a.length < 3 || b.length < 3) return;
    const v = vals(c), sk = S.skew(v);
    const row = { column: c, effect: hedges(a, b), skew: sk };
    if (Math.abs(sk) >= SKEW_HIGH && v.every(x => x > 0)) {
      row.log_skew = S.skew(v.map(Math.log));
      row.log_helps = Math.abs(row.log_skew) <= SKEW_OK;
    }
    out.scan.push(row);
  });
  out.scan.sort((p1, p2) => Math.abs(p2.effect) - Math.abs(p1.effect));
  const best = out.scan[0];
  if (best && Math.abs(best.effect) > d0 * 1.5) {
    out.steps.push({ kind: "other_column", column: best.column,
      text: `${best.column} 로 보면 훨씬 크게 갈립니다 (효과크기 ${Math.abs(best.effect).toFixed(2)}`
          + ` · 지금 컬럼은 ${d0.toFixed(2)})` });
    if (best.log_helps)
      out.steps.push({ kind: "derive", column: best.column, expr: `1 + ln(${best.column})`,
        text: `${best.column} 이(가) 한쪽으로 치우쳐 있습니다 (왜도 ${Math.abs(best.skew).toFixed(2)})`
            + ` — 로그를 취하면 펴집니다 (왜도 ${Math.abs(best.log_skew).toFixed(2)}).`
            + ` 파생 컬럼으로 만들어 보십시오` });
  }
  if (out.scan.length)
    out.lines.push(`아래는 같은 군을 다른 컬럼으로 재 본 것입니다 (${out.scan.length}개)`
                 + ` — 둘러보기이므로 기록하지 않고, 여러 번 잰 만큼 보정이 필요합니다`);
  return out;
}

/** 연관에서 다음에 볼 것 — 군마다 상관이 다른가, 그 군 안에서 직선이 아닌가 */
function stepsAssoc(focus) {
  const [x, y] = APP.picked;
  const rows = APP.rows.filter(r => isFinite(+r[x]) && isFinite(+r[y]));
  const rAll = S.pearson(rows.map(r => +r[x]), rows.map(r => +r[y])).v;
  const sig = focus.p < .05;
  const out = { head: `${x} 와 ${y} 의 관계를 봤습니다 — ${focus.name}`,
                lines: [], steps: [], scan: [] };
  out.lines.push(sig ? `관계가 있습니다 (${focus.eff} ${S.fmt(focus.v)} · p ${S.fmtP(focus.p)})`
                     : `관계라고 하기 어렵습니다 (${focus.eff} ${S.fmt(focus.v)} · p ${S.fmtP(focus.p)})`);
  let split = null, bent = null;
  colorCols().forEach(c => {
    const gs = [];
    [...new Set(APP.rows.map(r => r[c]))].forEach(l => {
      const s = rows.filter(r => r[c] === l);
      if (s.length < GROUP_MIN) return;
      const xs = s.map(r => +r[x]), ys = s.map(r => +r[y]);
      gs.push({ level: l, r: S.pearson(xs, ys).v, n: s.length, dcor: S.dcor(xs, ys, 0).v });
    });
    if (gs.length < 2) return;
    out.scan.push({ column: c, overall: rAll, groups: gs });
    for (let i = 0; i < gs.length; i++) for (let j = i + 1; j < gs.length; j++) {
      const z = Math.abs(Math.atanh(gs[i].r) - Math.atanh(gs[j].r)) /
                Math.sqrt(1 / (gs[i].n - 3) + 1 / (gs[j].n - 3));
      if (z >= 1.96 && !split) split = [c, gs[i], gs[j]];
    }
    gs.forEach(u => { if (u.dcor - Math.abs(u.r) >= DCOR_GAP && !bent) bent = [c, u]; });
  });
  if (split) out.steps.push({ kind: "color_split", column: split[0],
    text: `${split[0]} 군마다 관계가 다릅니다 (${split[1].level} 에서 ${split[1].r.toFixed(2)},`
        + ` ${split[2].level} 에서 ${split[2].r.toFixed(2)} · 전체는 ${rAll.toFixed(2)})`
        + ` — 색으로 나눠 보십시오` });
  if (bent) out.steps.push({ kind: "bent_group", column: bent[0], level: bent[1].level,
    text: `${bent[0]}=${bent[1].level} 군에서는 직선이 아닙니다 (거리상관 ${bent[1].dcor.toFixed(2)} 가`
        + ` |r| ${Math.abs(bent[1].r).toFixed(2)} 보다 큽니다 · n=${bent[1].n})`
        + ` — 색으로 나눠 그림을 보십시오` });
  return out;
}

function hedges(a, b) {
  const m = v => v.reduce((s, x) => s + x, 0) / v.length;
  const va = v => { const u = m(v); return v.reduce((s, x) => s + (x - u) ** 2, 0) / (v.length - 1); };
  const s = Math.sqrt((va(a) + va(b)) / 2);
  return s ? (m(a) - m(b)) / s : 0;
}

function sumCard() {
  const done = Object.entries(APP.ran);
  if (!done.length) return "";
  const list = TESTS[APP.q] || [];
  const all = done.map(([id, r]) => {
    const t = list.find(z => z[0] === id) || [];
    return { id, name: t[1], eff: t[2], v: r.v, p: r.p };
  });
  const focus = all.find(r => r.id === APP.focus) || all[all.length - 1];
  const nx = APP.q === "Q-01" ? stepsDiff(focus) : stepsAssoc(focus);
  if (!nx) return "";
  const act = s => s.kind === "color_split" || s.kind === "bent_group"
    ? `<button class="sm" onclick="setColor('${s.column}')">${s.column} 으로 색 나누기</button>`
    : s.kind === "other_column"
      ? `<button class="sm" onclick="pickCol('${s.column}')">${s.column} 로 보기</button>`
      : s.kind === "derive"
        ? `<button class="sm" onclick="useSuggested('${s.expr}','ln_${s.column}')">${s.expr} 만들기</button>`
        : "";
  return `<div class="fn-sum">
    <div class="fn-sumttl">결론 — 재고 난 다음</div>
    <div class="fn-sumhead">${nx.head}</div>
    ${nx.lines.map(x => `<div class="fn-sumline">${x}</div>`).join("")}
    ${powerCard()}
    ${nx.steps.length ? `<div class="fn-next"><b>다음에 볼 것</b>
      ${nx.steps.map(s => `<div class="fn-nextrow"><span>${s.text}</span>${act(s)}</div>`).join("")}
    </div>` : ""}
    ${nx.scan.length ? `<details class="pw-more"><summary>다른 컬럼·군으로 재 본 것</summary>
      <table><tbody>${nx.scan.map(s => `<tr><td class="col">${s.column}</td><td>${
        s.groups ? s.groups.map(g => `${g.level} r ${g.r.toFixed(2)} (n=${g.n})`).join(" · ")
                 : `효과 ${s.effect.toFixed(2)}` + (s.skew !== undefined
                     ? ` · 왜도 ${s.skew.toFixed(2)}` : "")}</td></tr>`).join("")}
      </tbody></table></details>` : ""}
  </div>`;
}
function useSuggested(expr, name) {
  APP._expr = expr; APP._name = name; render();
  const e = document.getElementById("expr");
  if (e) { e.value = expr; preview(); }
  const n = document.getElementById("newName");
  if (n) n.value = name;
}

/* ── 그림 (FinderPlot.tsx) ───────────────────────────────── */
const SERIES_COL = ["#2f6f6f", "#b26a17", "#4a4ab2", "#8a2f6f"];
const MARKS = ["circle", "square", "triangle", "diamond"];

function plotCard() {
  if (!APP.q || APP.picked.length < 2) return "";
  const { problems } = candidates();
  if (problems.length) return "";
  return `<div class="fn-plot">
    <canvas id="fnPlot" width="560" height="260"></canvas>
    <div class="hint" id="fnPlotCap" style="margin:0"></div></div>`;
}

function drawPlot() {
  const c = document.getElementById("fnPlot");
  if (!c) return;
  const g = c.getContext("2d"), W = c.width, H = c.height;
  const PAD = { l: 56, r: 14, t: 14, b: 36 };
  const css = getComputedStyle(document.documentElement);
  const line = css.getPropertyValue("--border").trim();
  const faint = css.getPropertyValue("--text-faint").trim();
  const ink = css.getPropertyValue("--text").trim();
  g.clearRect(0, 0, W, H);
  g.font = "11px ui-monospace, monospace";
  g.strokeStyle = line;
  g.beginPath(); g.moveTo(PAD.l, PAD.t); g.lineTo(PAD.l, H - PAD.b);
  g.lineTo(W - PAD.r, H - PAD.b); g.stroke();

  const [a, b] = APP.picked;
  const cap = document.getElementById("fnPlotCap");
  if (APP.q === "Q-03") {
    const by = APP.color;
    const groups = by ? [...new Set(APP.rows.map(r => r[by]))] : [""];
    const all = APP.rows.filter(r => isFinite(+r[a]) && isFinite(+r[b]));
    const xs = all.map(r => +r[a]), ys = all.map(r => +r[b]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const X = v => PAD.l + (v - x0) / (x1 - x0 || 1) * (W - PAD.l - PAD.r);
    const Y = v => H - PAD.b - (v - y0) / (y1 - y0 || 1) * (H - PAD.t - PAD.b);
    groups.forEach((lv, i) => {
      g.fillStyle = SERIES_COL[i % 4];
      all.filter(r => !by || r[by] === lv).forEach(r => mk(g, X(+r[a]), Y(+r[b]), MARKS[i % 4]));
    });
    g.fillStyle = faint;
    g.fillText(S.fmt(x0), PAD.l, H - PAD.b + 15);
    g.fillText(S.fmt(x1), W - PAD.r - 44, H - PAD.b + 15);
    g.fillText(S.fmt(y1), 4, PAD.t + 9); g.fillText(S.fmt(y0), 4, H - PAD.b);
    g.fillStyle = ink; g.fillText(a, W / 2 - 28, H - 6);
    let lx = PAD.l + 6;
    groups.forEach((lv, i) => {
      if (!lv) return;
      g.fillStyle = SERIES_COL[i % 4]; mk(g, lx, PAD.t + 4, MARKS[i % 4]);
      g.fillStyle = ink; g.fillText(lv, lx + 9, PAD.t + 8);
      lx += 24 + String(lv).length * 7;
    });
    cap.textContent = `${all.length}행 · ${a} × ${b}` + (by ? ` · 색 = ${by}` : "");
  } else {
    const lv = [...new Set(APP.rows.map(r => r[b]))];
    const vv = APP.rows.map(r => +r[a]).filter(isFinite);
    const lo = Math.min(...vv), hi = Math.max(...vv);
    const nb = 20, top = Math.max(...lv.map(l =>
      Math.max(...S.hist(APP.rows.filter(r => r[b] === l).map(r => +r[a]), nb, lo, hi))));
    const bw = (W - PAD.l - PAD.r) / nb;
    lv.forEach((l, i) => {
      const h = S.hist(APP.rows.filter(r => r[b] === l).map(r => +r[a]), nb, lo, hi);
      g.fillStyle = SERIES_COL[i % 4]; g.globalAlpha = .58;
      h.forEach((v, j) => {
        const bh = v / top * (H - PAD.t - PAD.b);
        g.fillRect(PAD.l + j * bw + i * bw / lv.length + 1, H - PAD.b - bh,
                   bw / lv.length - 1.5, bh);
      });
      g.globalAlpha = 1;
    });
    g.fillStyle = faint;
    g.fillText(S.fmt(lo), PAD.l, H - PAD.b + 15);
    g.fillText(S.fmt(hi), W - PAD.r - 44, H - PAD.b + 15);
    g.fillText(String(top), 4, PAD.t + 9);
    g.fillStyle = ink; g.fillText(a, W / 2 - 28, H - 6);
    let lx = PAD.l + 6;
    lv.forEach((l, i) => {
      g.fillStyle = SERIES_COL[i % 4]; g.fillRect(lx, PAD.t, 9, 9);
      g.fillStyle = ink; g.fillText(l, lx + 13, PAD.t + 8);
      lx += 30 + String(l).length * 7;
    });
    cap.textContent = `${a} 를 ${b} 군별로 — ` + lv.map(l => {
      const f = S.five(APP.rows.filter(r => r[b] === l).map(r => +r[a]).filter(isFinite));
      return `${l}: 중앙 ${S.fmt(f.q2)}`;
    }).join(" · ");
  }
}
function mk(g, x, y, kind) {
  const r = 3.2; g.beginPath();
  if (kind === "square") g.rect(x - r, y - r, r * 2, r * 2);
  else if (kind === "triangle") { g.moveTo(x, y - r); g.lineTo(x + r, y + r); g.lineTo(x - r, y + r); }
  else if (kind === "diamond") { g.moveTo(x, y - r); g.lineTo(x + r, y); g.lineTo(x, y + r); g.lineTo(x - r, y); }
  else g.arc(x, y, r, 0, Math.PI * 2);
  g.fill();
}

/* ── 검정력 (PowerCard.tsx) ──────────────────────────────── */
const R_LIKE = ["r", "rho", "bicor"];
/** 표준정규 분위수 (Acklam) — 목표 검정력을 옮기려면 z(power) 가 매번 달라진다 */
function probit(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
             138.3577518672690, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
             66.80131188771972, -13.28068155288572];
  const c = [-.007784894002430293, -.3223964580411365, -2.400758277161838,
             -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [.007784695709041462, .3224671290700398, 2.445134137142996, 3.754408661907416];
  const lo = .02425;
  if (p < lo) { const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
           ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p > 1 - lo) return -probit(1 - p);
  const q = p - .5, r = q * q;
  return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q /
         (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}
const zSum = (target) => 1.959963985 + probit(Math.min(.99, Math.max(.5, target)));
const minR = (n, target = APP.target) =>
  Math.tanh(zSum(target) / Math.sqrt(Math.max(1, n - 3)));
const nForR = (r, target = APP.target) => {
  const a = Math.abs(r);
  if (a <= 1e-6 || a >= .999) return 0;
  return Math.ceil(3 + (zSum(target) / Math.atanh(a)) ** 2);
};
function setTarget(v) { APP.target = Math.min(.99, Math.max(.5, v / 100)); render(); }

/** 잡히는 크기를 선으로 긋고 **잰 값을 그 위에 얹는다** */
function powerCard() {
  if (APP.q !== "Q-03" || APP.picked.length < 2) return "";
  const done = Object.entries(APP.ran);
  if (!done.length) return "";
  const n = APP.rows.filter(r => APP.picked.every(c => isFinite(+r[c]))).length;
  if (n < 5) return "";
  const cut = minR(n);
  const list = TESTS["Q-03"];
  // **한 번에 하나만 선 위에 올린다.** 여럿을 겹쳐 놓으면 어느 값이 어느 지표인지
  // 알 수 없고, 새로 재면 앞의 것 위에 덧씌워진다
  const all = done.map(([id, r]) => {
    const t = list.find(x => x[0] === id);
    return { id, name: t[1], eff: t[2], v: r.v, p: r.p, comparable: R_LIKE.includes(t[2]) };
  });
  const focus = all.find(r => r.id === APP.focus) || all[all.length - 1];
  const onLine = focus.comparable ? [focus] : [], off = focus.comparable ? [] : [focus];
  const top = Math.max(1, cut * 1.2, ...onLine.map(r => Math.abs(r.v) * 1.2));
  const pct = v => Math.min(100, v / top * 100);
  const pw = (APP.target * 100).toFixed(0);
  const lane = { [focus.id]: 0 }, lanes = [0];

  return `<div class="pw">
    <div class="pw-head">n=${n} — |상관| ${cut.toFixed(2)} 이상만 ${pw}% 확률로 잡힙니다
      <span class="hint" style="margin:0"> · α=0.05 양측 · 목표 검정력 ${pw}%</span></div>
    <div class="hint" style="margin:0">고른 컬럼 <b>${APP.picked.join(" × ")}</b>
      ${APP.color ? ` · 색 = ${APP.color}` : ""} · 지금 보는 지표 <b>${focus.name}</b>
      (${focus.eff} ${S.fmt(focus.v)} · p ${S.fmtP(focus.p)})</div>
    ${all.length > 1 ? `<div class="row" style="margin-top:0">
      <span class="hint" style="margin:0">바꿔 보기</span>
      ${all.map(r => `<button class="sm${r.id === focus.id ? " on" : ""}"
        onclick="focusTest('${r.id}')">${r.name}</button>`).join("")}
      <span class="hint" style="margin:0">한 번에 하나씩 봅니다 — 잰 값은 그대로 남습니다</span>
    </div>` : ""}
    <div class="pw-aim">
      <span class="hint" style="margin:0">목표 검정력</span>
      <input type="range" min="50" max="99" step="1" value="${pw}"
             oninput="setTarget(+this.value)" aria-label="목표 검정력 끌기">
      <input class="pw-aimin" type="number" min="50" max="99" value="${pw}"
             aria-label="목표 검정력 입력"
             onkeydown="if(event.key==='Enter'){setTarget(+this.value);}"
             onblur="setTarget(+this.value)">
      <span class="hint" style="margin:0">% · 엔터</span>
      <span class="hint" style="margin:0">더 확실히 잡으려 할수록 필요한 크기가 커집니다</span>
    </div>
    <div class="pw-axis" style="height:${26 + (Math.max(1, lanes.length) - 1) * 15}px">
      <div class="pw-dead" style="width:${pct(cut)}%"></div>
      <div class="pw-cut" style="left:${pct(cut)}%"></div>
      ${onLine.map(r => `<div class="pw-mark${Math.abs(r.v) >= cut ? " ok" : ""}"
        style="left:${pct(Math.abs(r.v))}%;top:${2 + lane[r.id] * 15}px"
        title="${r.name}"><i></i>${Math.abs(r.v).toFixed(2)}</div>`).join("")}
    </div>
    <div class="pw-scale"><span>0</span>
      <span class="pw-cutlab" style="left:${pct(cut)}%">${cut.toFixed(2)}</span>
      <span>${top.toFixed(1)}</span></div>
    <div class="hint" style="margin:0"><span class="pw-swatch"></span>
      이 표본으로는 잡기 어려운 크기</div>
    ${onLine.map(r => {
      const ok = Math.abs(r.v) >= cut;
      const need = ok ? "" : nForR(r.v);
      return `<div class="pw-row${ok ? "" : " short"}"><b>${r.name}</b>
        ${r.v.toFixed(4)} — ${ok ? "잡을 수 있는 크기입니다"
          : `이 크기는 n=${need.toLocaleString()} 쯤 되어야 ${pw}% 로 잡힙니다 (지금 ${n})`}</div>`;
    }).join("")}
    ${off.length ? `<div class="pw-off">${off.map(r =>
      `<div class="hint" style="margin:0"><b>${r.name}</b> ${r.v.toFixed(4)} —
       ${r.eff} 는 상관계수와 다른 척도입니다 — 이 선과 직접 비교하지 않습니다</div>`).join("")}</div>` : ""}
    <div class="hint" style="margin:0">작은 표본에서 "유의하지 않다"는 "관계가 없다"가
      아닙니다 — 있어도 못 잡았을 수 있습니다</div>
    <div class="hint" style="margin:0">선은 <b>상관계수(r·ρ) 척도</b>입니다.
      τ·dCor 처럼 다른 척도의 값은 이 선에 얹지 않습니다</div></div>`;
}
