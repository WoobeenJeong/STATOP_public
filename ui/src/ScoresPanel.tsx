/** 지표 찾기 + 점수 목록 (M3) — **한 카드** (·· + 찾기 통합).
 *
 * 둘을 따로 두면 "찾았는데 고를 수가 없다"가 된다. 찾기는 별도 화면이 아니라
 * **이 목록을 거르는 입력**이고, 고른 지표를 그 자리에서 Goal 로 정한다.
 *
 * **미지정(회색)은 '적합하다'가 아니라 '판정할 근거가 아직 없다'** 이다 (scores.yaml grades).
 * 초록으로 올려 버리면 규칙표의 공백이 적합 판정으로 둔갑한다.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import katex from "katex";
import { api, type PurposeGroup, type ScoreEntry } from "./api";

const ICON = { green: "✅", yellow: "⚠", red: "⛔", unset: "○" } as const;
const LABEL = { green: "문제없음", yellow: "별로", red: "안됨", unset: "미지정" } as const;
const GRADES = ["green", "yellow", "red", "unset"] as const;
const PER = 10;                 // 한 쪽에 10개 — 다 쏟으면 위쪽이 스크롤 밖으로 나간다
// 점수 목록에 **없는** 것도 찾아진다 (상관계수는 Q-03 검정이다). 그 갈래 이름
const KIND: Record<string, string> = {
  test: "검정", score: "점수", post: "보고 규칙", relation: "역할 관계",
};

/** 무엇을 재고, 어떻게 읽고, 얼마나 버티는가  */
function Axes({ s }: { s: ScoreEntry }) {
  if (!s.measures && !s.scale && !s.shaken_by) return null;
  return (
    <div className="sc-axes">
      {s.measures && <div><span className="sc-axk">재는 것</span>{s.measures}</div>}
      {s.scale && <div><span className="sc-axk">읽는 법</span>{s.scale}</div>}
      {s.shaken_by && (
        <div><span className="sc-axk">흔들림</span>{s.shaken_by}</div>
      )}
    </div>
  );
}

// 계열 코드 대신 사람이 읽는 이름 — SC-BE 같은 접두는 내부 키다
const FAMILY: Record<string, string> = {
  ERR: "오차·적합도", CLS: "분류·판별", DIST: "거리·분포차", DIV: "다양성",
  ENT: "엔트로피", VAR: "변동성", NORM: "정규화·변환", BE: "배치효과",
  CLN: "임상", INF: "정보량",
};

/** 서버가 준 LaTeX 만 그린다 — 화면에서 수식을 새로 만들지 않는다 */
function Tex({ src }: { src: string }) {
  const body = src.replace(/^\$|\$$/g, "");
  let html = "";
  try {
    html = katex.renderToString(body, { throwOnError: true });
  } catch {
    return <code className="sc-raw">{src}</code>;
  }
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

interface Props {
  sessionFile: string;
  onGoalSet?: () => void;
}

type Found = Awaited<ReturnType<typeof api.find>>;
type Questions = Awaited<ReturnType<typeof api.findQuestions>>["questions"];
type Goal = { score?: string; test?: string; name?: string } | null;

export default function ScoresPanel({ sessionFile, onGoalSet }: Props) {
  const [rows, setRows] = useState<ScoreEntry[]>([]);
  const [meaning, setMeaning] = useState("");
  const [goal, setGoal] = useState<Goal>(null);
  const [grade, setGrade] = useState<string>("");
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [byPurpose, setByPurpose] = useState(false);
  const [page, setPage] = useState(0);          // 112줄을 한 번에 쏟지 않는다
  const [gs, setGs] = useState<PurposeGroup[]>([]);
  const [gMeta, setGMeta] = useState({ note: "", pick: "" });
  const [ent, setEnt] = useState<Awaited<
    ReturnType<typeof api.entropyBranch>> | null>(null);

  // 찾기 — 이 목록을 거르는 입력이다 (별도 화면이 아니다)
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const [questions, setQuestions] = useState<Questions>([]);
  const [openQ, setOpenQ] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    setErr("");
    try {
      const r = await api.scores(sessionFile, grade || undefined);
      setRows(r.scores);
      setPage(0);                               // 등급을 바꾸면 첫 쪽부터
      setMeaning(r.unset_meaning);
      setGoal(r.goal);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }, [sessionFile, grade]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api.findQuestions().then((r) => setQuestions(r.questions))
    .catch(() => {}); }, []);

  useEffect(() => {
    if (!byPurpose) return;
    void (async () => {
      try {
        const r = await api.scoreGroups(sessionFile);
        setGs(r.groups);
        setGMeta({ note: r.shaken_note, pick: r.pick_one });
      } catch (e) {
        setErr(String(e instanceof Error ? e.message : e));
      }
    })();
  }, [byPurpose, sessionFile]);

  // 점수 목록에 **없는** 것(검정·보고 규칙)도 같은 검색어로 찾아 준다.
  // 치는 대로 찾고, 늦게 온 응답은 버린다
  useEffect(() => {
    const text = q.trim();
    if (!text) { setFound(null); return; }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      try {
        const r = await api.find(text, 40);
        if (mine === seq.current) setFound(r);
      } catch { /* 목록 거르기는 이미 됐다 — 여기 실패는 조용히 */ }
    }, 180);
    return () => clearTimeout(t);
  }, [q]);

  /** 검색어는 **목록을 거른다.** 서버를 다시 부르지 않는다 */
  const shown = useMemo(() => {
    const f = q.trim().toLowerCase();
    if (!f) return rows;
    return rows.filter((s) =>
      `${s.id} ${s.name} ${s.family} ${FAMILY[s.family] ?? ""} ${s.measures} `
      + `${s.scale} ${s.columns.join(" ")}`.toLowerCase().includes(f));
  }, [rows, q]);

  // 점수로도 찾힌 것은 위 목록에 이미 있다 — 아래에는 **그 밖의 것만**
  const otherHits = useMemo(
    () => (found?.hits ?? []).filter((h) => h.kind !== "score"), [found]);

  const opened = useMemo(
    () => questions.find((x) => x.id === openQ) ?? null, [questions, openQ]);

  async function pickGoal(id: string) {
    try {
      await api.setGoal(sessionFile, { score: id });
      await load();                    // 지금 Goal 이 무엇인지 그 자리에서 다시 읽는다
      onGoalSet?.();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }

  async function branch(column: string) {
    setErr("");
    try {
      setEnt(await api.entropyBranch(sessionFile, column));
    } catch (e) {
      setEnt(null);
      setErr(String(e instanceof Error ? e.message : e));
    }
  }

  const isGoal = (id: string) => goal?.score === id;

  return (
    <div className="card">
      <div className="ttl">지표 찾기 · 점수 목록 (M3) — 지금 데이터 기준</div>

      {/* 지금 무엇이 Goal 인지 항상 맨 위에. 아무 줄에서나 [Goal로] 로 바꾼다 */}
      <div className="sc-goal">
        {goal
          ? <><b>지금 목표 지표(Goal)</b> {goal.name ?? goal.score ?? goal.test}
              <span className="hint"> 아래 목록에서 [Goal로] 를 누르면 바뀝니다</span></>
          : <><b>목표 지표(Goal)</b> 아직 정하지 않았습니다
              <span className="hint"> 정하지 않으면 마지막에 실행한 검정을 기준으로 봅니다</span></>}
      </div>

      <div className="row">
        <input type="text" value={q} autoComplete="off" style={{ flex: 1 }}
               placeholder="이름으로 좁히기 — 치는 대로 걸러집니다 (상관, entropy, 배치…)"
               onChange={(e) => setQ(e.target.value)} />
        {q && <button className="sm" onClick={() => setQ("")}>지우기</button>}
      </div>

      <div className="row">
        {GRADES.map((g) => (
          <button key={g} className={`sm${grade === g ? " on" : ""}`}
                  onClick={() => setGrade(grade === g ? "" : g)}>
            {ICON[g]} {LABEL[g]}
          </button>
        ))}
        <button className={`sm${byPurpose ? " on" : ""}`}
                onClick={() => setByPurpose(!byPurpose)}>묶음으로 보기</button>
        <span className="hint" style={{ margin: 0 }}>{meaning}</span>
      </div>
      {err && <div className="err">{err}</div>}

      {byPurpose ? (
        <div className="sc-groups">
          <div className="hint" style={{ marginTop: 0 }}>{gMeta.pick}</div>
          <div className="hint" style={{ marginTop: 2 }}>{gMeta.note}</div>
          {gs.map((g) => (
            <details key={g.id} className="sc-group">
              <summary>{g.name} <span className="hint">({g.entries.length}종)</span></summary>
              <div className="inner">
                {g.entries.map((e) => (
                  <div key={e.id} className="sc-alt">
                    <div>
                      <span className="flag">{ICON[e.verdict]}</span> <b>{e.name}</b>{" "}
                      {isGoal(e.id) && <span className="sc-ison">★ Goal</span>}{" "}
                      <button className="sm" disabled={e.verdict === "red" || isGoal(e.id)}
                              onClick={() => pickGoal(e.id)}>Goal로</button>
                    </div>
                    <Axes s={e} />
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : (
      <table>
        <thead>
          <tr><th></th><th>지표</th><th>계열</th><th>쓸 수 있는 컬럼</th><th></th></tr>
        </thead>
        <tbody>
          {shown.slice(page * PER, (page + 1) * PER).map((s) => (
            <>
              <tr key={s.id} className={s.verdict === "red" ? "high"
                : s.verdict === "yellow" ? "mid" : s.verdict === "unset" ? "off" : ""}>
                <td className="flag">{ICON[s.verdict]}</td>
                {/* 내부 ID(SC-BE-08)는 사용자가 알 필요 없다 — 이름이 먼저, ID 는 상세에서 */}
                <td><b>{s.name}</b>{isGoal(s.id) && <span className="sc-ison">★ Goal</span>}</td>
                <td className="hint" style={{ margin: 0 }}>{FAMILY[s.family] ?? s.family}</td>
                <td className="hint" style={{ margin: 0 }}>
                  {s.columns.join(", ") || "—"}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="sm"
                          onClick={() => setOpen(open === s.id ? null : s.id)}>
                    {open === s.id ? "접기" : "수식"}
                  </button>{" "}
                  <button className="sm" disabled={s.verdict === "red" || isGoal(s.id)}
                          onClick={() => pickGoal(s.id)}>Goal로</button>
                </td>
              </tr>
              {open === s.id && (
                <tr key={`${s.id}-x`}>
                  <td colSpan={5} className="sc-detail">
                    <div className="hint" style={{ margin: 0 }}>{s.why}</div>
                    <div className="hint" style={{ margin: 0 }}>
                      규칙표 항목 {s.id} · {s.section}
                    </div>
                    <div className="sc-tex"><Tex src={s.latex} /></div>
                    {s.substituted && (
                      <>
                        <div className="hint" style={{ margin: "6px 0 0" }}>
                          이 데이터에 대입하면
                        </div>
                        <div className="sc-tex"><Tex src={s.substituted} /></div>
                      </>
                    )}
                    <Axes s={s} />
                    {s.note && <div className="hint">{s.note}</div>}
                    {s.family === "ENT" && s.columns.length > 0 && (
                      <button className="sm" style={{ marginTop: 6 }}
                              onClick={() => branch(s.columns[0])}>
                        {s.columns[0]} 의 분포로 공식 고르기
                      </button>
                    )}
                  </td>
                </tr>
              )}
            </>
          ))}
          {!shown.length && (
            <tr><td colSpan={5} className="hint">
              '{q}' 에 맞는 지표가 목록에 없습니다 — 아래에서 다른 갈래를 보세요
            </td></tr>
          )}
        </tbody>
      </table>
      )}

      {!byPurpose && shown.length > PER && (
        <div className="row" style={{ marginTop: 8 }}>
          <button className="sm" disabled={page === 0}
                  onClick={() => setPage(page - 1)}>◂ 이전</button>
          <span className="hint" style={{ margin: 0 }}>
            {page + 1}/{Math.ceil(shown.length / PER)} 쪽 · {shown.length}개
            {q && ` (전체 ${rows.length}개 중)`}
          </span>
          <button className="sm" disabled={(page + 1) * PER >= shown.length}
                  onClick={() => setPage(page + 1)}>다음 ▸</button>
        </div>
      )}

      {/* 점수 목록 밖에서 찾힌 것 — 상관계수는 점수가 아니라 Q-03 검정이다 */}
      {otherHits.length > 0 && (
        <div className="fd-results">
          <div className="hint" style={{ margin: "8px 0 4px" }}>
            점수 목록 밖에서 {otherHits.length}건 — 여기서 고르는 것이 아니라
            분석에서 그 질문 유형으로 갑니다
          </div>
          {otherHits.map((h) => (
            <div className="fd-hit" key={`${h.kind}-${h.id}`}>
              <div><b>{h.name}</b><span className="hint"> · {KIND[h.kind]}</span></div>
              <div className="hint" style={{ margin: 0 }}>{h.where}</div>
              <div className="hint" style={{ margin: 0 }}>{h.how}</div>
            </div>
          ))}
        </div>
      )}

      {/* 이름을 모를 때 — 질문 유형을 **고른 뒤에야** 세부 목록이 열린다 */}
      {!q && (
        <details className="sc-branch">
          <summary>이름을 모르겠다면 — 무엇을 알고 싶은지부터 고르기</summary>
          <div className="inner">
            <div className="fd-chips">
              {questions.map((x) => (
                <button key={x.id}
                        className={`fd-chip${openQ === x.id ? " on" : ""}`}
                        onClick={() => setOpenQ(openQ === x.id ? null : x.id)}>
                  {x.question}
                </button>
              ))}
            </div>
            {opened && (
              <div className="fd-tests">
                <div className="row">
                  <b>{opened.question}</b>
                  <span className="hint" style={{ margin: 0 }}>{opened.user_words}</span>
                </div>
                <div className="fd-scroll">
                  {opened.tests.map((t) => (
                    <div className="fd-test" key={t.id}>
                      <div><b>{t.name}</b></div>
                      <div className="hint" style={{ margin: 0 }}>
                        {t.design}{t.best_when && ` · ${t.best_when}`}
                      </div>
                      <div className="hint" style={{ margin: 0 }}>
                        분석에서 질문 유형을 「{opened.question}」 로 고르면 후보에 뜹니다
                        {t.effect_size && ` · 효과크기 ${t.effect_size}`}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </details>
      )}

      {ent && (
        <div className="sc-ent">
          <b>{ent.column} 의 엔트로피 — 연속 분포는 공식이 분포마다 다릅니다</b>
          <div className="hint" style={{ margin: 0 }}>
            n={String(ent.facts.n)} · 양수={String(ent.facts.positive)}
            {" "}· 왜도 큼={String(ent.facts.skewed)}
            {" "}· 중꼬리={String(ent.facts.heavy_tail)} · 정규={String(ent.facts.normal)}
          </div>
          <div style={{ marginTop: 6 }}><b>→ {ent.picked} {ent.name}</b></div>
          <div className="sc-tex"><Tex src={ent.latex} /></div>
          <div className="hint" style={{ margin: 0 }}>{ent.why}</div>
          {ent.rejected.length > 0 && (
            <details>
              <summary>▸ 쓰지 않은 공식 {ent.rejected.length}개</summary>
              <div className="inner">
                {ent.rejected.map((r) => (
                  <div key={r.id}>· {r.id} {r.name} — {r.why}</div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
