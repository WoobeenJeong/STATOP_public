/** 지표 찾기  — **무엇을 알고 싶은가 → 어느 컬럼으로 → 무엇을 쓸까.**
 *
 * 점수 목록을 세션 전체 기준으로 먼저 깔면, 컬럼 두 개를 정해 놓고 "이 둘이 관계가
 * 있나"를 볼 방도가 없다. 순서를 뒤집는다.
 *
 * - **누를 때만 계산한다.** 목록에 뜬 것을 전부 미리 돌리면 화면이 멈춘다
 * - **쓸 수 없다고 판정돼도 값은 나온다.** 숨기면 "왜 안 되는데"로 끝난다
 * - 여러 개를 돌렸으면 **몇 번 쟀는지를 센다** (C-15 · post.yaml P-221~223)
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, wasAborted } from "./api";
import FinderPlot from "./FinderPlot";
import PowerCard from "./PowerCard";

type Questions = Awaited<ReturnType<typeof api.findQuestions>>["questions"];
type Found = Awaited<ReturnType<typeof api.explore>>;
type Ran = Awaited<ReturnType<typeof api.exploreRun>>;
type Adj = Awaited<ReturnType<typeof api.padjust>>;

const ICON = { green: "✅", yellow: "⚠", red: "⛔" } as const;
const LABEL = { green: "문제없음", yellow: "별로", red: "안됨" } as const;
// post.yaml 이 정한 방법들 — 여기서 새로 만들지 않는다
const METHODS: { key: string; label: string }[] = [
  { key: "holm", label: "Holm (기본)" },
  { key: "bh", label: "BH (FDR)" },
  { key: "bonferroni", label: "Bonferroni" },
  { key: "none", label: "보정 없음" },
];

interface Props {
  sessionFile: string;
  columns: string[];              // 분석에 쓸 수 있는 컬럼
  onGoalSet?: () => void;
  onDerive?: (expr: string, name: string) => void;   // "이 식을 만들어 보라"
}

export default function FinderPanel({ sessionFile, columns, onGoalSet,
                                      onDerive }: Props) {
  const [questions, setQuestions] = useState<Questions>([]);
  const [q, setQ] = useState("");                 // 고른 질문 유형
  const [search, setSearch] = useState("");       // 이름으로 건너뛰기
  const [picked, setPicked] = useState<string[]>([]);
  const [found, setFound] = useState<Found | null>(null);
  const [ran, setRan] = useState<Record<string, Ran>>({});
  const [busy, setBusy] = useState("");           // 지금 돌리는 검정 id
  const [listBusy, setListBusy] = useState(false);
  const [method, setMethod] = useState("holm");
  const [adj, setAdj] = useState<Adj | null>(null);
  const [open, setOpen] = useState<string | null>(null);   // 근거를 펼친 줄
  const [focus, setFocus] = useState<string | null>(null);  // 검정력에서 보는 지표 하나
  const [goal, setGoal] = useState<{ name: string; test: string } | null>(null);
  const [panel, setPanel] = useState<Awaited<ReturnType<typeof api.metrics>> | null>(null);
  const [roles, setRoles] = useState<{ support: string[]; guardrail: string[] }>(
    { support: [], guardrail: [] });
  const [myRole, setMyRole] = useState<"support" | "guardrail">("guardrail");
  const [myName, setMyName] = useState("");
  const [myWhy, setMyWhy] = useState("");
  const [myHint, setMyHint] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => { api.findQuestions().then((r) => setQuestions(r.questions))
    .catch(() => {}); }, []);

  function fail(e: unknown): void {
    setErr(wasAborted(e) ? "" : String(e instanceof Error ? e.message : e));
  }

  /** 질문과 컬럼이 다 정해지면 후보만 받아 온다 — 값은 아직 아니다 */
  const load = useCallback(async () => {
    if (!q || picked.length === 0) { setFound(null); return; }
    setListBusy(true);
    setErr("");
    try {
      setFound(await api.explore(sessionFile, q, picked));
      setRan({});
      setFocus(null);
      setAdj(null);
    } catch (e) {
      setFound(null);
      fail(e);
    } finally {
      setListBusy(false);
    }
  }, [sessionFile, q, picked]);

  useEffect(() => { void load(); }, [load]);

  async function runOne(id: string) {
    setBusy(id);
    setErr("");
    try {
      const r = await api.exploreRun(sessionFile, q, picked, id);
      setRan((cur) => ({ ...cur, [id]: r }));
      setFocus(id);                       // **방금 잰 것**을 검정력에서 본다
      setAdj(null);                       // 검정이 늘면 보정도 다시 해야 한다
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  /** Goal 로 — 이건 기록된다. 정하면 **함께 볼 것**(병기)을 추천받는다 */
  async function pickGoal(test: string, name: string) {
    try {
      // 계산해 둔 것이 있으면 효과크기 이름까지 — 병기 추천 조건이 이걸 본다
      await api.setGoal(sessionFile,
        { test, name, effect_key: ran[test]?.effect_name || undefined });
      setGoal({ test, name });
      onGoalSet?.();
      const pn = await api.metrics(sessionFile);
      setPanel(pn);
      setRoles({ support: [], guardrail: [] });
    } catch (e) {
      fail(e);
    }
  }

  /** 목록에서 고른 것을 그대로 넣는다 — 직접 치는 것과 같은 자리로 들어간다 */
  async function addPicked(name: string) {
    try {
      const r = await api.metricsCustom(sessionFile, myRole, name, "");
      setMyHint(r.notice || r.hint);
      setPanel(await api.metrics(sessionFile));
    } catch (e) {
      fail(e);
    }
  }

  /** 규칙표에 없는 것도 내 추천으로 — 다음에도 이 Goal 에서 뜬다 */
  async function addMine() {
    try {
      const r = await api.metricsCustom(sessionFile, myRole, myName, myWhy);
      setMyHint(r.notice || r.hint);
      setMyName("");
      setMyWhy("");
      setPanel(await api.metrics(sessionFile));
    } catch (e) {
      fail(e);
    }
  }

  function toggleRole(kind: "support" | "guardrail", id: string) {
    setRoles((cur) => ({ ...cur,
      [kind]: cur[kind].includes(id) ? cur[kind].filter((x) => x !== id)
                                     : [...cur[kind], id] }));
  }

  async function saveRoles() {
    try {
      await api.metricsRoles(sessionFile, roles.support, roles.guardrail);
      setErr("");
    } catch (e) {
      fail(e);
    }
  }

  async function adjustAll(m: string) {
    setMethod(m);
    const rows = Object.values(ran)
      .filter((r) => r.p !== null)
      .map((r) => ({ name: r.name, p: r.p as number }));
    if (rows.length < 2) { setAdj(null); return; }
    try {
      setAdj(await api.padjust(rows, m));
    } catch (e) {
      fail(e);
    }
  }

  const shown = useMemo(() => {
    const f = search.trim().toLowerCase();
    if (!f) return questions;
    return questions.filter((x) =>
      `${x.id} ${x.question} ${x.user_words} ${x.tests.map((t) => t.name).join(" ")}`
        .toLowerCase().includes(f));
  }, [questions, search]);

  /** 색을 나눌 군 — **코어가 고른 군 컬럼**만 (연속값을 색에 넣으면 그림이 죽는다) */
  const [colorBy, setColorBy] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (colorBy && found && !found.color_columns.includes(colorBy)) setColorBy(undefined);
  }, [found, colorBy]);

  /** 결론 칸이 말하는 것은 **지금 보고 있는 지표 하나**다 */
  const shownRan = (focus && ran[focus]) || Object.values(ran).slice(-1)[0] || null;

  /** 고를 수 있는 것 — 이 질문의 다른 검정들에서 Goal 과 이미 넣은 것을 뺀다 */
  const pickable = (found?.candidates ?? []).filter((c) =>
    c.id !== goal?.test
    && !(panel?.support ?? []).some((x) => x.name === c.name)
    && !(panel?.guardrail ?? []).some((x) => x.name === c.name));

  const adjOf = (name: string) =>
    adj?.rows.find((r) => r.name === name)?.p_adjusted ?? null;

  function toggleCol(c: string) {
    setPicked((cur) => cur.includes(c) ? cur.filter((x) => x !== c)
      : cur.length >= 2 ? [cur[1], c] : [...cur, c]);
  }

  return (
    <div className="card">
      <div className="ttl">지표 찾기 — 무엇을 알고 싶은가 → 어느 컬럼으로 → 무엇을 쓸까</div>

      {/* 1 — 질문 유형. 이름을 알면 검색으로 건너뛴다 */}
      <div className="fn-step">
        <span className="fn-no">1</span>
        <div className="fn-body">
          <div className="row">
            <input type="text" value={search} style={{ flex: 1 }} autoComplete="off"
                   placeholder="이름을 알면 여기서 — 상관, 생존, 일치도…"
                   onChange={(e) => setSearch(e.target.value)} />
            {search && <button className="sm" onClick={() => setSearch("")}>지우기</button>}
          </div>
          <div className="fd-chips" style={{ marginTop: 6 }}>
            {shown.map((x) => (
              <button key={x.id} className={`fd-chip${q === x.id ? " on" : ""}`}
                      onClick={() => setQ(q === x.id ? "" : x.id)}>
                {x.question}
              </button>
            ))}
            {!shown.length && <span className="hint">'{search}' 에 맞는 갈래가 없습니다</span>}
          </div>
          {q && (
            <div className="hint" style={{ marginTop: 4 }}>
              {questions.find((x) => x.id === q)?.user_words}
            </div>
          )}
        </div>
      </div>

      {/* 2 — 컬럼. 두 개까지, 세 번째를 누르면 오래된 것이 빠진다 */}
      <div className="fn-step">
        <span className="fn-no">2</span>
        <div className="fn-body">
          <div className="fd-chips">
            {columns.map((c) => (
              <button key={c} className={`fx-chip${picked.includes(c) ? " on" : ""}`}
                      onClick={() => toggleCol(c)}>
                {picked.includes(c) ? `${picked.indexOf(c) + 1}. ${c}` : c}
              </button>
            ))}
          </div>
          <div className="hint" style={{ marginTop: 4 }}>
            두 개까지 고릅니다 · 순서가 의미를 가집니다 (첫째가 보려는 값)
          </div>
          {/* 군으로 색을 나누면 "섞여서 생긴 관계"가 그 자리에서 보인다 */}
          <div className="row" style={{ marginTop: 4 }}>
            <span className="hint" style={{ margin: 0 }}>색으로 나눌 군</span>
            <button className={`sm${!colorBy ? " on" : ""}`}
                    onClick={() => setColorBy(undefined)}>나누지 않음</button>
            {(found?.color_columns ?? []).map((c) => (
              <button key={c} className={`sm${colorBy === c ? " on" : ""}`}
                      onClick={() => setColorBy(colorBy === c ? undefined : c)}>{c}</button>
            ))}
            {found && !found.color_columns.length && (
              <span className="hint" style={{ margin: 0 }}>나눌 군 컬럼이 없습니다</span>
            )}
          </div>
        </div>
      </div>

      {/* 3 — 무엇을 쓸까 */}
      <div className="fn-step">
        <span className="fn-no">3</span>
        <div className="fn-body">
          {err && <div className="err">{err}</div>}
          {!q || !picked.length ? (
            <div className="hint" style={{ marginTop: 0 }}>
              질문과 컬럼을 고르면 여기에 쓸 수 있는 것들이 뜹니다.
            </div>
          ) : listBusy ? (
            <div className="hint" style={{ marginTop: 0 }}>찾는 중…</div>
          ) : found?.problems.length ? (
            <>
              {found.problems.map((p, i) => <div className="warnbox" key={i}>{p}</div>)}
              {/* 고르라고만 하고 무엇을 고를지 안 알려주면 거기서 막힌다 */}
              {found.second_role && (
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="hint" style={{ margin: 0 }}>
                    {found.second_columns.length ? "이 중에서 고를 수 있습니다"
                      : "이 자리에 쓸 만한 컬럼이 없습니다 — 의미 타입을 먼저 확정해 보십시오"}
                  </span>
                  {found.second_columns.map((c) => (
                    <button key={c} className="sm" onClick={() => toggleCol(c)}>{c}</button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="hint" style={{ marginTop: 0 }}>
                {found?.question_name} · {picked.join(" × ")} — {found?.candidates.length ?? 0}종
                {" · "}{found?.note}
              </div>

              {/* **모양을 먼저 본다.** 값과 p 만 보면 V 자인지 직선인지 알 수 없다 */}
              <FinderPlot sessionFile={sessionFile} question={q} columns={picked}
                          colorBy={colorBy} />

              {(found?.candidates ?? []).map((c) => {
                const r = ran[c.id];
                const a = r ? adjOf(r.name) : null;
                return (
                  <div key={c.id} className={`fn-row v-${c.verdict}`}>
                    <div className="fn-top">
                      <span className={`fn-flag f-${c.verdict}`}>
                        {ICON[c.verdict]} {LABEL[c.verdict]}
                      </span>
                      <b>{c.name}</b>
                      <span className="hint" style={{ margin: 0 }}>{c.id}</span>
                      <span className="fn-val">
                        {r ? (
                          <>
                            {r.effect_name} {r.effect?.toPrecision(4)}
                            {r.p !== null && <> · p {r.p.toPrecision(4)}</>}
                            {a !== null && <> → {a.toPrecision(4)}</>}
                          </>
                        ) : (
                          <button className="sm" disabled={!c.runnable || busy === c.id}
                                  onClick={() => runOne(c.id)}>
                            {busy === c.id ? "재는 중…" : c.runnable ? "검정" : "실행 함수 없음"}
                          </button>
                        )}
                        {" "}
                        <button className="sm"
                                onClick={() => setOpen(open === c.id ? null : c.id)}>
                          {open === c.id ? "접기" : "수식·근거"}
                        </button>
                      </span>
                    </div>
                    {c.reasons.slice(0, 2).map((x, i) => (
                      <div className="hint" style={{ margin: 0 }} key={i}>{x}</div>
                    ))}
                    {c.assumptions && (
                      <div className="hint" style={{ margin: 0 }}>가정 {c.assumptions}</div>
                    )}
                    {open === c.id && (
                      <div className="fn-rule">
                        {(found?.rule_labels ?? []).map(([k, label]) => (
                          c.rule?.[k] ? (
                            <div key={k}>
                              <span className="sc-axk">{label}</span>{c.rule[k]}
                            </div>
                          ) : null
                        ))}
                        <div className="hint" style={{ margin: 0 }}>
                          {c.rule?.section || c.id}
                        </div>
                      </div>
                    )}
                    {r && (
                      <div className="fn-acts">
                        <span className="hint" style={{ margin: 0 }}>
                          n {Object.values(r.n).join(" · ")}
                        </span>
                        <button className="sm" disabled={goal?.test === c.id}
                                onClick={() => void pickGoal(c.id, c.name)}>
                          {goal?.test === c.id ? "★ Goal" : "Goal로"}
                        </button>
                        <button className="sm" onClick={() => runOne(c.id)}>다시</button>
                        {/* 검정력은 **한 번에 하나만** — 겹쳐 놓으면 어느 값인지 모른다 */}
                        <button className={`sm${focus === c.id ? " on" : ""}`}
                                onClick={() => setFocus(c.id)}>
                          {focus === c.id ? "검정력에서 보는 중" : "검정력에서 보기"}
                        </button>
                      </div>
                    )}
                    {r?.notes?.map((x, i) => (
                      <div className="hint" style={{ margin: 0 }} key={i}>{x}</div>
                    ))}
                  </div>
                );
              })}
            </>
          )}

          {/* Goal 을 정하면 **함께 볼 것**을 고른다 (· · MR-S/MR-G) */}
          {goal && panel && (
            <div className="fn-adj">
              <div className="hint" style={{ marginTop: 0 }}>
                <b>목표 지표(Goal)</b> {goal.name} — 함께 볼 것을 고르세요
              </div>
              {(["support", "guardrail"] as const).map((kind) => (
                panel[kind].length ? (
                  <div key={kind} style={{ marginTop: 6 }}>
                    <div className="hint" style={{ margin: 0 }}>
                      {panel.head[kind]}
                    </div>
                    {panel[kind].map((x) => (
                      <label className="fn-role" key={x.id}>
                        <input type="checkbox" checked={roles[kind].includes(x.id)}
                               onChange={() => toggleRole(kind, x.id)} />
                        <span>
                          <b>{x.name}</b>
                          {x.source === "user" && <span className="fn-mine"> ✎ 사용자 지정</span>}
                          {x.why && <> — {x.why}</>}
                        </span>
                      </label>
                    ))}
                  </div>
                ) : null
              ))}
              {!panel.support.length && !panel.guardrail.length && (
                <div className="hint">{panel.head.none}</div>
              )}
              {(roles.support.length > 0 || roles.guardrail.length > 0) && (
                <button className="sm" style={{ marginTop: 6 }}
                        onClick={() => void saveRoles()}>함께 보고할 것으로 저장</button>
              )}

              {/* **고를 목록이 먼저다.** 규칙표가 정해 둔 짝이 없을 때 빈 화면에
                  타이핑만 남겨 두면 무엇을 적어야 할지 알 수 없다. 이 질문에 쓸 수
                  있는 다른 검정들을 눌러서 고른다 — 고른 것은 '사용자 지정'이다 */}
              {pickable.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div className="row">
                    <span className="hint" style={{ margin: 0 }}>목록에서 고르기 —</span>
                    {(["support", "guardrail"] as const).map((k) => (
                      <button key={k} className={`sm${myRole === k ? " on" : ""}`}
                              onClick={() => setMyRole(k)}>
                        {k === "support" ? "함께 볼 것" : "틀어지면 막을 것"}
                      </button>
                    ))}
                  </div>
                  <div className="fd-chips" style={{ marginTop: 4 }}>
                    {pickable.map((c) => (
                      <button key={c.id} className="fx-chip"
                              onClick={() => void addPicked(c.name)}>{c.name}</button>
                    ))}
                  </div>
                </div>
              )}

              {/* 목록에 없는 것도 넣을 수 있다 — 출처는 '사용자 지정'으로 남는다 */}
              <div className="row" style={{ marginTop: 8 }}>
                <select value={myRole}
                        onChange={(e) => setMyRole(e.target.value as "support" | "guardrail")}>
                  <option value="support">support (함께 볼 것)</option>
                  <option value="guardrail">guardrail (틀어지면 막을 것)</option>
                </select>
                <input type="text" value={myName} style={{ flex: 1, minWidth: 120 }}
                       placeholder="무엇을 함께 볼까요 — 예: Spearman ρ"
                       onChange={(e) => setMyName(e.target.value)} />
                <input type="text" value={myWhy} style={{ flex: 1, minWidth: 120 }}
                       placeholder="왜 (선택)"
                       onChange={(e) => setMyWhy(e.target.value)} />
                <button className="sm" disabled={!myName.trim()}
                        onClick={() => void addMine()}>내 추천에 넣기</button>
              </div>
              <div className="hint" style={{ margin: 0 }}>{myHint}</div>
            </div>
          )}

          {/* ── 결론. 재고 나면 **여기 하나만** 보면 된다 ──────────────
              값·p 는 목록에, 검정력은 그 아래, 다음에 할 일은 어디에도 없었다 */}
          {shownRan && (
            <div className="fn-sum">
              <div className="fn-sumttl">결론 — 재고 난 다음</div>
              {shownRan.next?.head && <div className="fn-sumhead">{shownRan.next.head}</div>}
              {(shownRan.next?.lines ?? []).map((x, i) => (
                <div className="fn-sumline" key={i}>{x}</div>
              ))}

              <PowerCard sessionFile={sessionFile} question={q} columns={picked}
                         colorBy={colorBy} focus={focus} onFocus={setFocus}
                         effects={Object.entries(ran).map(([id, r]) => ({
                           id, name: r.name, value: r.effect, p: r.p,
                           effect_name: r.effect_name }))} />

              {(shownRan.next?.steps ?? []).length > 0 && (
                <div className="fn-next">
                  <b>다음에 볼 것</b>
                  {shownRan.next!.steps.map((s, i) => (
                    <div className="fn-nextrow" key={i}>
                      <span>{s.text}</span>
                      {/* 말로만 권하지 않는다 — 그 자리에서 눌러 넘어간다 */}
                      {(s.kind === "color_split" || s.kind === "bent_group") && s.column && (
                        <button className="sm" onClick={() => setColorBy(s.column)}>
                          {s.column} 으로 색 나누기
                        </button>
                      )}
                      {s.kind === "other_column" && s.column && (
                        <button className="sm" onClick={() => toggleCol(s.column!)}>
                          {s.column} 로 보기
                        </button>
                      )}
                      {s.kind === "derive" && s.expr && (
                        <button className="sm"
                                onClick={() => onDerive?.(s.expr!, `ln_${s.column}`)}>
                          {s.expr} 만들기
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* 둘러본 것은 접어 둔다 — 결론을 덮지 않게 */}
              {(shownRan.next?.scan ?? []).length > 0 && (
                <details className="pw-more">
                  <summary>다른 컬럼·군으로 재 본 것</summary>
                  <table><tbody>
                    {shownRan.next!.scan.map((s) => (
                      <tr key={s.column}>
                        <td className="col">{s.column}</td>
                        <td>{s.groups
                          ? s.groups.map((g) => `${g.level} r ${g.r.toFixed(2)} (n=${g.n})`)
                              .join(" · ")
                          : `효과 ${s.effect?.toFixed(2)} · p ${s.p?.toPrecision(2)}`
                            + (s.skew !== undefined ? ` · 왜도 ${s.skew.toFixed(2)}` : "")}</td>
                      </tr>
                    ))}
                  </tbody></table>
                </details>
              )}
            </div>
          )}

          {/* 여러 번 쟀으면 그 수를 센다 */}
          {Object.keys(ran).length >= 2 && (
            <div className="fn-adj">
              <div className="row">
                <span className="hint" style={{ margin: 0 }}>
                  {Object.keys(ran).length}번 쟀습니다 — 함께 보정
                </span>
                {METHODS.map((m) => (
                  <button key={m.key} className={`sm${method === m.key ? " on" : ""}`}
                          onClick={() => void adjustAll(m.key)}>{m.label}</button>
                ))}
              </div>
              {adj && (
                <>
                  <div className="hint" style={{ marginTop: 4 }}>
                    {adj.rule} · {adj.head}
                  </div>
                  {adj.rows.map((r) => (
                    <div className="hint" style={{ margin: 0 }} key={r.name}>
                      {r.name}: p {r.p.toPrecision(4)} → {r.p_adjusted.toPrecision(4)}
                      {" "}{r.significant ? "유의" : "유의하지 않음"}
                    </div>
                  ))}
                  <div className="hint">{adj.why}</div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
