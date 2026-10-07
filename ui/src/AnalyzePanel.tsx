/** 분석 패널 (모듈 A) — 질문 → 후보 → 실행 → 가설. CLI [분석] 화면과 같은 REST.
 *
 * 후보는 ✅⚠⛔ 아이콘+텍스트 병행 . 실행 결과에는 효과크기·CI·보정 α가
 * 항상 붙고, 가설 1안/2안과 주의사항까지 한 카드에서 이어진다.
 */

import { useState } from "react";
import { api, type MetricSuggestion } from "./api";
import PointsPlot from "./PointsPlot";

type Candidate = {
  id: string; name: string; color: "green" | "yellow" | "red";
  reasons: string[]; effect_size: string; alternatives: string; design: string;
  runnable: boolean;
};

type PlanOut = {
  y_type: string | null; group_type: string | null;
  group_levels: Record<string, number>;
  problems: string[]; candidates: Candidate[]; recorded: boolean;
  compat: { findings: { id: string; verdict: string; detail: string; why: string }[] };
  missing: Record<string, { n: number; ratio: number }>;
  n_rows: number; n_complete: number;
  repeat_candidates: { column: string; subjects: number; rows: number }[];
};

type RunOut = {
  id: string; name: string; statistic: number; p: number;
  effect: { name: string; value: number; ci_low: number | null; ci_high: number | null };
  n: Record<string, unknown>; notes: string[];
  assumptions: { id: string; name: string; verdict: string; summary: string;
                 action: string | null }[];
  assumptions_head: string;
  exclusion?: { n_excluded: number; n_total: number; ratio: number;
                verdict: "green" | "yellow" | "red"; flipped: boolean; alpha: number;
                alternatives: { id: string; name: string; why: string }[];
                before: { statistic: number; p: number;
                          effect: { name: string; value: number } } | null };
  strata: { level: string; n: number; p?: number; error?: string;
            effect?: { name: string; value: number; ci_low: number | null;
                       ci_high: number | null } }[];
};

type Hypo = {
  proposals: { title: string; statement: string; interpretation: string;
               direction: string | null }[];
  cautions: string[]; companions: string[]; guardrail: string[];
};

const ICON = { green: "✅", yellow: "⚠", red: "⛔" };
const IMPUTE = ["median", "mean", "group_median", "group_mean", "mode", "knn",
                "mice", "zero"];
const VERDICT_ICON: Record<string, string> = {
  ok: "✅", caution: "⚠", violated: "⛔", skipped: "○",
};
const QUESTIONS_FALLBACK = ["Q-01", "Q-02", "Q-03"];

interface Props {
  sessionFile: string;
  columns: string[];          // 분석 대상 (id 제외는 서버 판정이 잡는다)
  onDataChanged?: () => void; // 값을 바꾸면 사본 저장 안내를 다시 확인한다
}

export default function AnalyzePanel({ sessionFile, columns,
                                      onDataChanged }: Props) {
  const [questions, setQuestions] = useState<{ id: string; question: string;
                                               user_words: string }[]>([]);
  const [q, setQ] = useState("Q-01");
  const [y, setY] = useState(columns[0] ?? "");
  const [group, setGroup] = useState("");
  const [event, setEvent] = useState("");
  const [paired, setPaired] = useState(false);
  const [nTests, setNTests] = useState(1);
  const [plan, setPlan] = useState<PlanOut | null>(null);
  const [run, setRun] = useState<RunOut | null>(null);
  const [hypo, setHypo] = useState<Hypo | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [method, setMethod] = useState("median");
  const [ignoreNa, setIgnoreNa] = useState(false);
  const [by, setBy] = useState("");
  const [weights, setWeights] = useState("");
  const [control, setControl] = useState("");
  const [subject, setSubject] = useState("");
  const [showPoints, setShowPoints] = useState(false);
  const [lastTest, setLastTest] = useState("");
  const [metrics, setMetrics] = useState<Awaited<
    ReturnType<typeof api.metrics>> | null>(null);

  async function loadQuestions() {
    if (questions.length) return;
    try {
      const r = await api.analyzeQuestions();
      setQuestions(r.questions);
    } catch { /* 폴백 목록으로 동작 */ }
  }

  async function checkPlan(apply = false) {
    setBusy(true);
    setErr("");
    setRun(null);
    setHypo(null);
    setMetrics(null);
    try {
      const r = await api.analyzePlan(sessionFile, {
        question: q, y, group: group || null, event: event || null,
        by: by || null, subject: subject || null, weights: weights || null,
        control: control || null, paired, n_tests: nTests, apply,
      });
      setPlan(r);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  /** 이 설계에 쓰이는 컬럼만 채운다 — 상관없는 컬럼까지 손대지 않는다 */
  async function doImpute() {
    const cols = Object.entries(plan?.missing ?? {})
      .filter(([, m]) => m.n > 0).map(([c]) => c);
    if (!cols.length) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.impute(sessionFile, method, cols,
                                 method.startsWith("group_") ? group || null : null,
                                 true);
      if (r.warnings.length) setErr(r.warnings.join(" / "));
      setIgnoreNa(false);
      onDataChanged?.();                   // 원본과 다른 데이터가 되었다 — 사본 저장 안내
      await checkPlan();                   // 값이 바뀌었으니 후보를 다시 뽑는다
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  }

  async function runTest(testId: string) {
    setBusy(true);
    setErr("");
    try {
      // 실행 전에 스펙을 기록한다 — 검정·가설이 이 전제를 쓴다
      await api.analyzePlan(sessionFile, {
        question: q, y, group: group || null, event: event || null,
        by: by || null, subject: subject || null, weights: weights || null,
        control: control || null, paired, n_tests: nTests, apply: true,
      });
      const r = await api.analyzeRun(sessionFile, testId);
      setRun(r);
      setLastTest(testId);
      // Goal 옆에 병기할 것 — 실패해도 검정 결과는 살린다
      setMetrics(await api.metrics(sessionFile).catch(() => null));
      setHypo(await api.hypothesis(sessionFile));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  // 전체와 부호가 반대인 수준 — 비(OR·IRR·HR)는 1이, 확률적 우위는 0.5가 기준이다
  const flips = (() => {
    const base = run?.effect?.value;
    if (base == null || !run?.strata?.length) return [];
    const kind = (run.effect.name ?? "").split(" (")[0].trim();
    const ref = ["OR", "IRR", "HR"].includes(kind) ? 1
      : kind === "P(X>Y)" ? 0.5 : 0;
    if (Math.abs(base - ref) < 1e-12) return [];
    return run.strata.filter((s) => s.effect?.value != null
      && (s.effect.value - ref) * (base - ref) < 0).map((s) => s.level);
  })();

  const qlist = questions.length ? questions
    : QUESTIONS_FALLBACK.map((id) => ({ id, question: "", user_words: "" }));

  return (
    <div onMouseEnter={loadQuestions}>
      <div className="hint" style={{ marginTop: 0 }}>
        질문 → 후보 → 실행 → 가설. 결측·제외·층화는 아래에서 이어집니다.
      </div>

      <div className="row an-form">
        <label>질문
          <select value={q} disabled={busy} onChange={(e) => setQ(e.target.value)}>
            {qlist.map((x) => (
              <option key={x.id} value={x.id}>{x.id} {x.question}</option>
            ))}
          </select>
        </label>
        <label>측정값 y
          <select value={y} disabled={busy} onChange={(e) => setY(e.target.value)}>
            {columns.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>군/변수 x
          <select value={group} disabled={busy} onChange={(e) => setGroup(e.target.value)}>
            <option value="">(없음)</option>
            {columns.filter((c) => c !== y).map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>대상 ID (반복측정)
          <select value={subject} disabled={busy}
                  onChange={(e) => setSubject(e.target.value)}>
            <option value="">(없음)</option>
            {columns.filter((c) => c !== y).map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        {/* 층화 — 전체값과 수준별 값을 함께 본다. 상호작용(Q-04)의 둘째 요인이기도 하다 */}
        <label>층화 라벨
          <select value={by} disabled={busy} onChange={(e) => setBy(e.target.value)}>
            <option value="">(없음)</option>
            {columns.filter((c) => c !== y && c !== group).map((c) =>
              <option key={c}>{c}</option>)}
          </select>
        </label>
        {/* 생존 분석에서만 쓰인다 — 없으면 모든 행을 사건 발생으로 보게 되어 값이 치우친다 */}
        <label>사건 여부 (생존)
          <select value={event} disabled={busy}
                  onChange={(e) => setEvent(e.target.value)}>
            <option value="">(없음)</option>
            {columns.filter((c) => c !== y && c !== group).map((c) =>
              <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>짝지음
          <input type="checkbox" checked={paired} disabled={busy}
                 onChange={(e) => setPaired(e.target.checked)} />
        </label>
        <label>계획 검정 수
          <input type="number" min={1} max={20} value={nTests} disabled={busy}
                 style={{ width: 52 }}
                 onChange={(e) => setNTests(Math.max(1, Number(e.target.value)))} />
        </label>
        {q === "Q-11" && (
          <>
            <label>대비 가중치
              <input type="text" value={weights} disabled={busy} style={{ width: 90 }}
                     placeholder="1,1,-2"
                     onChange={(e) => setWeights(e.target.value)} />
            </label>
            <label>대조군 수준
              <input type="text" value={control} disabled={busy} style={{ width: 80 }}
                     onChange={(e) => setControl(e.target.value)} />
            </label>
          </>
        )}
        <button className="pri" disabled={busy || !y} onClick={() => checkPlan()}>
          {busy ? "확인 중…" : "계획 확인"}
        </button>
      </div>
      {err && <div className="err">{err}</div>}

      {plan?.repeat_candidates?.map((r) => (
        <div className="hint" key={r.column}>
          {r.column}에 같은 값이 여러 번 있습니다 — 대상 {r.subjects}명 × 총 {r.rows}행.
          반복측정 검정을 쓰려면 [대상 ID]로 지정하세요
        </div>
      ))}

      {plan && Object.values(plan.missing).some((m) => m.n > 0) && ignoreNa && (
        <div className="an-missing">
          결측 행을 빼고 봅니다 — {plan.n_rows}행 중 {plan.n_complete}행으로
          계산합니다 (채우지 않았습니다){" "}
          <button className="sm" onClick={() => setIgnoreNa(false)}>대치 안내 다시 보기</button>
        </div>
      )}

      {plan && Object.values(plan.missing).some((m) => m.n > 0) && !ignoreNa && (
        <div className="an-missing">
          <b>결측 있음</b> — 이 설계로 실제 쓰이는 행은 {plan.n_rows}행 중{" "}
          {plan.n_complete}행입니다
          {Object.entries(plan.missing).filter(([, m]) => m.n > 0).map(([c, m]) => (
            <div key={c}>· {c}: {m.n}행 비어 있음 ({(m.ratio * 100).toFixed(1)}%)</div>
          ))}
          <div className="row" style={{ marginTop: 6 }}>
            <select value={method} disabled={busy}
                    onChange={(e) => setMethod(e.target.value)}>
              {IMPUTE.map((m) => <option key={m}>{m}</option>)}
            </select>
            <button className="sm" disabled={busy} onClick={doImpute}>결측 대치</button>
            {/* 채우지 않고 그대로 보는 길 — 세션은 건드리지 않는다 */}
            <button className="sm" disabled={busy}
                    onClick={() => setIgnoreNa(true)}>결측 무시하고 보기</button>
            <span className="hint" style={{ margin: 0 }}>
              대치 방법과 채운 칸 수는 세션에 기록되어 보고서에 남습니다.
              무시하면 그 행이 검정에서 빠지며 기록되지 않습니다
            </span>
          </div>
        </div>
      )}

      {plan && plan.problems.length > 0 && (
        <div className="an-problems">
          <b>진행 전에 풀 것</b>
          {plan.problems.map((p, i) => <div key={i}>· {p}</div>)}
          {plan.compat.findings.filter((f) => f.verdict !== "yellow").map((f, i) => (
            <div key={`c${i}`}>· [{f.id}] {f.detail || f.why}</div>
          ))}
        </div>
      )}

      {plan && !plan.problems.length && (
        <table>
          <thead>
            <tr><th></th><th>검정</th><th>사유</th><th>효과크기</th><th></th></tr>
          </thead>
          <tbody>
            {plan.candidates.map((c) => (
              <tr key={c.id} className={!c.runnable ? "off" :
                                        c.color === "red" ? "high" :
                                        c.color === "yellow" ? "mid" : ""}>
                <td className="flag">{c.runnable ? ICON[c.color] : "○"}</td>
                <td className="col">{c.id} {c.name}</td>
                <td className="hint" style={{ margin: 0 }}>{c.reasons[0] ?? ""}</td>
                <td className="hint" style={{ margin: 0 }}>{c.effect_size}</td>
                <td style={{ textAlign: "right" }}>
                  {/* 빨강도 실행은 된다 — 왜 부적합한지는 사유에 남고, 값은 값대로 본다 */}
                  {c.runnable
                    ? <button className="sm" disabled={busy}
                              onClick={() => runTest(c.id)}>실행</button>
                    : <span className="hint" style={{ margin: 0 }}>계산기 없음</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {run && flips.length > 0 && (
        <div className="an-alarm">
          <b>⛔ 전체와 방향이 반대인 수준: {flips.join(", ")}</b>
          <div>전체값만 보면 결론이 뒤집힙니다 (심슨의 역설) —
               수준별 값을 반드시 함께 보고하세요</div>
        </div>
      )}

      {/* : 제외가 있으면 전/후를 함께 — 제외 후 값만 보이면 숨길 수 있다 */}
      {run?.exclusion && run.exclusion.n_excluded > 0 && (
        <div className={run.exclusion.verdict === "red" ? "an-alarm" : "an-missing"}>
          <b>
            전체 {run.exclusion.n_total}행 중 {run.exclusion.n_excluded}행
            ({(run.exclusion.ratio * 100).toFixed(1)}%)을 뺐습니다
          </b>
          <div>
            {run.exclusion.verdict === "red"
              ? "10%를 넘으면 분석이 아니라 표본을 고른 것입니다"
              : "제외 전 결과와 반드시 함께 보고하세요"}
          </div>
          {run.exclusion.flipped && (
            <div><b>⛔ 제외 때문에 결론이 바뀌었습니다 (한쪽만 유의)</b></div>
          )}
          {run.exclusion.before && (
            <div style={{ marginTop: 4 }}>
              제외 전: 통계량 {run.exclusion.before.statistic?.toPrecision(4)},
              p = {run.exclusion.before.p?.toPrecision(3)} ·
              {" "}{run.exclusion.before.effect?.name}
              = {run.exclusion.before.effect?.value?.toPrecision(4)}
            </div>
          )}
        </div>
      )}

      {run && (
        <div className="an-result">
          <b>{run.id} {run.name}</b> — 통계량 {run.statistic?.toPrecision(4)},
          p = {run.p?.toPrecision(3)} ·
          {" "}{run.effect.name} = {run.effect.value?.toPrecision(3)}
          {run.effect.ci_low != null &&
            ` (95% CI ${run.effect.ci_low.toPrecision(3)}~${run.effect.ci_high?.toPrecision(3)})`}
          {run.notes.map((n, i) => <div className="hint" key={i}>{n}</div>)}
          <button className="sm" style={{ marginTop: 6 }}
                  onClick={() => setShowPoints((v) => !v)}>
            {showPoints ? "개별 점 접기" : "개별 점 보기"}
          </button>
          {/* 그 검정이 요구하는 가정 — 값 바로 아래 (TUI와 같은 문구) */}
          {run.assumptions?.length > 0 && (
            <div className="an-assump">
              <b>{run.assumptions_head}</b>
              {run.assumptions.map((a) => (
                <div key={a.id} className={`as-${a.verdict}`}>
                  {VERDICT_ICON[a.verdict] ?? "○"} {a.id} {a.name} — {a.summary}
                  {a.action && <div className="hint" style={{ margin: 0 }}>{a.action}</div>}
                </div>
              ))}
            </div>
          )}

          {run.strata?.length > 0 && (
            <div className="an-strata">
              <b>{by} 수준별 ({run.strata.length}개)</b> — 전체와 함께 보세요
              {run.strata.map((s) => (
                <div key={s.level} className={flips.includes(s.level) ? "flip" : ""}>
                  · {s.level} (n={s.n}){s.error ? ` — ${s.error}`
                    : ` : ${s.effect?.name}=${s.effect?.value?.toPrecision(4)}, p=${s.p?.toPrecision(3)}`}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 점을 빼면 같은 검정을 다시 돌려 결과·가설을 맞춘다 — 화면마다 다른 값이면 안 된다 */}
      {run && showPoints && (
        <PointsPlot sessionFile={sessionFile}
                    alternatives={run.exclusion?.alternatives ?? []}
                    onChanged={() => lastTest && runTest(lastTest)} />
      )}

      {metrics && (
        <div className="an-metrics">
          {(["support", "guardrail"] as const).map((role) => (
              <div key={role} className={`mt-${role}`}>
                <b>{metrics.head[role]}</b>
                {!metrics[role].length && (
                  <div className="hint">{metrics.head.none}</div>
                )}
                {metrics[role].map((s: MetricSuggestion) => (
                  <div className="mt-item" key={s.id}>
                    <div><b>[{s.id}]</b> {s.name}
                      {!s.computable && <span className="hint"> (확인만)</span>}</div>
                    {s.why && <div className="hint" style={{ margin: 0 }}>{s.why}</div>}
                    {s.value?.lines.map((l, i) => <div key={i}>· {l}</div>)}
                    {s.error && <div className="err">{s.error}</div>}
                  </div>
                ))}
              </div>
            ))}
          {metrics.triad && (
            <div className="mt-triad">
              <b>{metrics.head.triad}</b>
              <div>
                {metrics.triad.id} {metrics.triad.situation} — Goal {metrics.triad.goal}
                {" / "}Support {metrics.triad.support}
                {" / "}Guardrail {metrics.triad.guardrail}
              </div>
            </div>
          )}
        </div>
      )}

      {hypo && (
        <div className="an-hypo">
          <div className="ttl" style={{ marginBottom: 6 }}>가설 (기계 생성)</div>
          {hypo.proposals.map((p) => (
            <div key={p.title} className="an-prop">
              <b>{p.title}</b>
              <div>{p.statement}</div>
              <div className="hint">{p.interpretation}</div>
            </div>
          ))}
          {hypo.cautions.length > 0 && (
            <div className="an-cautions">
              <b>주의사항</b>
              {hypo.cautions.map((c, i) => <div key={i}>· {c}</div>)}
            </div>
          )}
          {hypo.companions.length > 0 && (
            <details>
              <summary>▸ 보조지표 해석 {hypo.companions.length}건</summary>
              <div className="inner">
                {hypo.companions.map((c, i) => <div key={i}>· {c}</div>)}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
