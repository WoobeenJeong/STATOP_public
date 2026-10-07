import { useEffect, useState } from "react";
import "./App.css";
import FormulaEditor from "./FormulaEditor";
import AnalyzePanel from "./AnalyzePanel";
import AskQwen from "./AskQwen";
import CliOnlyPanel from "./CliOnlyPanel";
import PendingBanner from "./PendingBanner";
import GuardBanner from "./GuardBanner";
import GuardLimits from "./GuardLimits";
import ModelLeak from "./ModelLeak";
import RepresentPanel from "./RepresentPanel";
import RefsPanel from "./RefsPanel";
import StopBar from "./StopBar";
import RobustPanel from "./RobustPanel";
import FinderPanel from "./FinderPanel";
import TypesPanel from "./TypesPanel";
import { api, type ColumnItem, type ColumnsResponse, type SavedItem, type SessionResponse } from "./api";

type Sort = "missing" | "unique" | "name";

const FLAG: Record<ColumnItem["missing_level"], string> = { high: "!!", mid: "!", ok: "" };

export default function App() {
  const [path, setPath] = useState("");
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [cols, setCols] = useState<ColumnsResponse | null>(null);
  // 지표 찾기가 "이 식을 만들어 보라"고 하면 수식 편집기로 넘긴다
  const [suggested, setSuggested] = useState<{ expr: string; name: string } | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [grep, setGrep] = useState("");
  const [sort, setSort] = useState<Sort | undefined>();
  const [offset, setOffset] = useState(0);
  const [imported, setImported] = useState<string[] | null>(null);   // 가져온 뒤엔 이것만 본다
  const [derived, setDerived] = useState<string[]>([]);              // 수식으로 만든 컬럼
  const [held, setHeld] = useState<string[]>([]);                    // 분석 제외·시각화 유지 (M0-5)
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState("");                       // 저장 결과 안내
  const [saveList, setSaveList] = useState<SavedItem[] | null>(null);  // 불러오기 목록
  const [problems, setProblems] = useState<string[]>([]);       // 원본 변경 경고

  const PAGE = 25;  // 페이지당 컬럼 수 — 컬럼이 수천 개여도 비용이 일정하다

  const [synced, setSynced] = useState("");   // 반영 결과 — 눌렀는데 조용하면 된 건지 모른다
  const [confirmSync, setConfirmSync] = useState(false);   // 웹→CLI 2단계 확인
  // 목록에서 본 컬럼 정보를 쌓아 둔다 — 가져온 뒤에도 타입·결측률이 보여야 판단이 된다
  const [profile, setProfile] = useState<Record<string, ColumnItem>>({});
  const [nConfirmed, setNConfirmed] = useState(0);   // 타입 확정 수 — 아래 패널의 문턱
  const [pendingKey, setPendingKey] = useState(0);   // 값이 바뀌면 배너를 다시 확인한다

  /** CLI가 저장한 상태를 이 화면에 반영한다 (웹에 반영).

      단계·체크까지 그대로 따라간다: CLI가 컬럼 목록에서 3개를 체크해뒀으면
      웹도 그 3개가 체크된 컬럼 목록이 된다. */
  async function applyToWeb(file?: string) {
    const target = file ?? session?.session_file;
    if (!target) return;
    setBusy(true);
    try {
      const v = await api.adoptSession(target);
      // 낡은 서버에는 state 엔드포인트가 없다 — 그때도 첫 화면으로 떨어지지 않고
      // 조작 기록만으로 반영한다 (view 없이)
      const st = await api.sessionState(target).catch(() => ({ view: null }));
      setSession({ session_id: v.session_id, session_file: target,
                   source_id: v.source_id, sources: [], rules_version: null,
                   notice: "" });
      if (v.path) setPath(v.path);
      setErr("");
      const view = st.view;
      const wantColumns = view?.step === "columns" || (!v.selected.length && v.path);
      if (wantColumns && v.path) {
        // 컬럼 목록 단계 — 목록을 띄우고 저장된 체크까지 복원한다
        setImported(null);
        const cr = await api.columns({ path: v.path, sampleN: 3000, limit: PAGE,
                                       offset: 0, sessionFile: target });
        setCols(cr);
        setProfile((cur) => ({ ...cur,
          ...Object.fromEntries(cr.items.map((it) => [it.column, it])) }));
        setOffset(0);
        setPicked(new Set(view?.picked ?? []));
        setSynced(view
          ? `CLI→웹 반영됨 (${view.by} 저장) — 컬럼 목록 · 체크 ${view.picked.length}개`
          : "CLI→웹 반영됨 — 컬럼 목록 (저장된 체크 없음)");
      } else if (v.selected.length) {
        setImported(v.selected);
        setDerived(v.derived ?? []);
        setHeld(v.held);
        setCols(null);
        setSynced(`CLI→웹 반영됨 — 가져온 컬럼 ${v.selected.length}개 · 분석에서 뺀 것 ${v.held.length}개`);
      } else {
        setSynced("CLI→웹 반영됨 — 아직 연 파일이 없습니다");
      }
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setSynced("");
    } finally {
      setBusy(false);
    }
  }

  /** 지금 화면 상태를 세션에 저장한다 — CLI가 [CLI에 반영]으로 가져간다. */
  /** 웹 → CLI 는 **두 쪽이 모두 눌러야** 반영된다.
   *
   *  CLI 가 메인이다. 웹에서 누른 것이 터미널 상태를 조용히 덮으면, 다른 창에서 하던
   *  작업이 사라져도 알 수가 없다. 그래서 웹에서 한 번, CLI 에서 한 번 — 두 번 확인한다.
   */
  async function shareState() {
    if (!session) return;
    if (!confirmSync) { setConfirmSync(true); return; }
    const step = imported ? "workspace" : cols ? "columns" : "open";
    try {
      await api.saveView(session.session_file, step, [...picked]);
      setConfirmSync(false);
      setSynced(`웹 상태를 보냈습니다 (${step} 단계 · 체크 ${picked.size}개) — `
        + `아직 반영되지 않았습니다. CLI 에서도 [웹→CLI 반영]을 눌러야 적용됩니다`);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }

  // 터미널 화면이 ?s=세션ID 를 붙여 보낸다. 같은 파일을 열어야 양쪽이 같은 상태가 된다
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const short = q.get("s");
    const want = q.get("session");
    if (!short && !want) return;
    (async () => {
      try {
        const file = want ?? (await api.resolveSession(short!)).session_file;
        await applyToWeb(file);
      } catch (e) {
        setErr(String(e instanceof Error ? e.message : e));
      }
    })();
    // 최초 1회만 — syncSession은 매 렌더 새로 만들어지므로 의존성에 넣으면 무한 루프다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load(p = path, s = sort, g = grep, off = 0) {
    if (!p.trim()) return;
    setBusy(true);
    setErr("");
    try {
      // 세션이 없으면 만들고, 있으면 메인 파일만 교체한다 (: 세션은 유지)
      const sess = session
        ? (await api.setMain(session.session_file, p), session)
        : await api.createSession(p);
      setSession(sess);
      const r = await api.columns({ path: p, sampleN: 3000, sort: s,
                                    grep: g || undefined, limit: PAGE, offset: off,
                                    sessionFile: sess.session_file });
      setCols(r);
      // 본 것은 쌓아 둔다 — 가져온 뒤에도 타입·결측률을 보여주려면 필요하다
      setProfile((cur) => ({ ...cur,
        ...Object.fromEntries(r.items.map((it) => [it.column, it])) }));
      setOffset(off);
      if (off === 0) setPicked(new Set());   // 페이지 이동 시 선택은 유지
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setCols(null);
    } finally {
      setBusy(false);
    }
  }

  async function importPicked() {
    if (!session || picked.size === 0) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.importColumns(session.session_file, path, [...picked]);
      setImported(r.selected);
      setHeld([]);
      setCols(null);          // 전체 목록은 버린다 — 가져온 컬럼만 다룬다 (M0-4)
      setPicked(new Set());
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function dropColumn(name: string) {
    if (!session) return;
    setErr("");
    try {
      const r = await api.dropColumns(session.session_file, [name]);
      // 파생 컬럼은 선택 목록에 없다 — 둘을 합쳐야 화면에서 사라진다
      setImported([...r.selected, ...r.derived.filter((c) => !r.selected.includes(c))]);
      setDerived(r.derived);
      setHeld((h) => h.filter((c) => c !== name));
      if (r.notice) setSynced(r.notice);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }

  async function toggleHold(name: string) {
    if (!session) return;
    const r = await api.holdColumns(session.session_file, [name], !held.includes(name));
    setHeld(r.held);
  }

  async function doSave(overwrite = false) {
    if (!session) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.saveSession(session.session_file, undefined, undefined, overwrite);
      setSaved(r.name);
    } catch (e) {
      const m = String(e instanceof Error ? e.message : e);
      // 같은 이름이 있으면 덮어쓰기는 별도 확인을 거친다 (단순 저장과 분리)
      if (m.includes("이미 존재") && confirm(`${m}\n\n덮어쓸까요? (직전 버전은 .bak으로 보존)`)) {
        return doSave(true);
      }
      setErr(m);
    } finally {
      setBusy(false);
    }
  }

  async function openList() {
    setBusy(true);
    setErr("");
    try {
      setSaveList((await api.listSessions()).items);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function doLoad(file: string) {
    setBusy(true);
    setErr("");
    try {
      const r = await api.loadSession(file);
      setProblems(r.source_problems.map((p) => p.message));
      if (r.source_problems.length && !confirm(`${r.notice}\n\n그래도 진행할까요?`)) {
        setProblems([]);
        return;
      }
      const cols = Object.values(r.selected).flat();
      setSession({ session_id: r.session_id, session_file: r.session_file,
                   source_id: r.main, sources: [], rules_version: null, notice: r.notice });
      setImported(cols);
      setCols(null);
      setSaveList(null);
      setSaved("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  function toggle(name: string) {
    const next = new Set(picked);
    next.has(name) ? next.delete(name) : next.add(name);
    setPicked(next);
  }

  return (
    <div className="wrap">
      <div className="brand">STAT<span className="brand-v">OP</span></div>
      {/* 멈췄을 때 끊을 자리는 **맨 위**다 — 찾아 헤매면 그 사이도 기다리는 시간이다 */}
      <StopBar />
      <div className="frame">
        {/* 어느 세션에 붙어 있는지 항상 보인다 — 터미널과 같은 세션인지 눈으로 확인 */}
        {session && (
          <div className="sessbar">
            <span className="sessid">세션 {session.session_id}</span>
            <button className={confirmSync ? "sm danger" : "sm"} disabled={busy}
                    onClick={shareState}>
              {confirmSync ? "정말 반영 — 한 번 더" : "웹→CLI 반영"}
            </button>
            {confirmSync && (
              <button className="sm" onClick={() => setConfirmSync(false)}>취소</button>
            )}
            <button className="sm" disabled={busy} onClick={() => applyToWeb()}>
              {busy ? "반영 중…" : "CLI→웹 반영"}
            </button>
            <span className="hint" style={{ margin: 0 }}>
              {confirmSync
                ? "정말 CLI에 반영하시겠습니까? 보낸 뒤 CLI에서도 [웹→CLI 반영]을 선택해야 적용됩니다"
                : synced || "내 상태를 보내려면 [웹→CLI 반영] · CLI 것을 가져오려면 [CLI→웹 반영]"}
            </span>
          </div>
        )}

        {/* 가드레일은 본문보다 앞이다 — 차단을 스크롤해서 보게 하면 안 된다  */}
        {imported && session && (
          <GuardBanner sessionFile={session.session_file}
                       metrics={imported.filter((c) => !held.includes(c))} />
        )}

        {/* 1) 경로 — 첫 화면은 이 카드 하나뿐 */}
        <div className="card">
          <div className="ttl">데이터 경로</div>
          <div className="row">
            <input
              type="text"
              value={path}
              placeholder="/nas/cohortB/data.parquet"
              spellCheck={false}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && load()}
            />
            <button className="pri" disabled={busy || !path.trim()} onClick={() => load()}>
              {busy ? "여는 중…" : session ? "다시 열기" : "열기"}
            </button>
            <button className="sm" disabled={busy} onClick={openList}>불러오기</button>
          </div>
          {!cols && !err && (
            <div className="hint">경로만 입력하면 됩니다. 파일을 열어도 데이터는 표시되지 않습니다.</div>
          )}
          {problems.map((p, i) => <div className="err" key={i}>{p}</div>)}
          {err && <div className="err">{err}</div>}
        </div>

        {saveList && (
          <div className="card">
            <div className="ttl">저장된 세션 불러오기</div>
            {saveList.length === 0 && <div className="hint" style={{ marginTop: 0 }}>저장된 세션이 없습니다.</div>}
            <table>
              <tbody>
                {saveList.map((it) => (
                  <tr key={it.file}>
                    <td className="col">{it.name}</td>
                    <td className="hint" style={{ margin: 0 }}>조작 {it.ops}개</td>
                    <td style={{ textAlign: "right" }}>
                      <button className="sm" onClick={() => doLoad(it.file)}>불러오기</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="sm" onClick={() => setSaveList(null)}>닫기</button>
            </div>
          </div>
        )}

        {imported && (
          <div className="card">
            <div className="ttl">
              작업 영역 — 가져온 컬럼 {imported.length}개
              <span style={{ color: "var(--text-faint)" }}>
                {" "}(분석에 씀 {imported.length - held.length} · 분석에서 뺌 {held.length})
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>컬럼명</th><th>타입</th>
                  <th style={{ textAlign: "right" }}>결측률</th>
                  <th style={{ textAlign: "right" }}>고유값</th>
                  <th style={{ width: 70, whiteSpace: "nowrap" }}>분석 제외</th><th style={{ width: 56 }}></th>
                </tr>
              </thead>
              <tbody>
                {imported.map((c) => {
                  const p = profile[c];
                  return (
                    <tr key={c}>
                      {/* 이름만 줄바꿈한다 — td 에 inline-block 을 걸면 그 칸이
                          테이블 셀에서 빠져 줄(테두리)이 끊기고 칸이 어긋난다 */}
                      <td className="col"
                          style={held.includes(c) ? { color: "var(--text-faint)" } : undefined}>
                        <span className="col-name" title={c}>{c}</span>
                      </td>
                      <td className="hint" style={{ margin: 0 }}>{p?.dtype ?? "—"}</td>
                      <td className="num">
                        {p ? `${(p.missing_rate * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="num">{p ? p.n_unique.toLocaleString() : "—"}</td>
                      <td>
                        <input type="checkbox" checked={held.includes(c)}
                               onChange={() => toggleHold(c)} />
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button className="sm" onClick={() => dropColumn(c)}>제외</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="hint">
              체크하면 <b>분석에서 빠집니다</b> — 다만 그림에서 색·점을 가르는 데는 계속 씁니다
              (환자 번호·기관 코드처럼 분석 변수가 아닌 것). 아예 빼려면 [제외] 입니다.
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="sm" onClick={() => { setImported(null); load(path, sort, grep, 0); }}>
                컬럼 더 가져오기
              </button>
              <span className="hint" style={{ margin: 0 }}>
                이제 이 컬럼들에 대해서만 분석이 진행됩니다
              </span>
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="sm" disabled={busy} onClick={() => doSave()}>세션 저장</button>
              {saved && <span className="hint" style={{ margin: 0 }}>저장됨: {saved}</span>}
            </div>
          </div>
        )}

        {/* 순서가 곧 안내다: 파생 컬럼 → 타입 확정 → 분석.
            분석을 위에 두면 아직 세팅도 안 끝났는데 가설부터 눈에 들어온다 */}
        {imported && session && (
          <FormulaEditor
            suggested={suggested}
            sessionFile={session.session_file}
            columns={[...imported.filter((c) => !held.includes(c)),
                      ...derived.filter((c) => !imported.includes(c))]}
            onCommitted={(n) => { setImported((cur) => (cur ? [...cur, n] : cur));
                                  setDerived((cur) => [...cur, n]); }}
          />
        )}

        {/* 타입 확정은 이후 판정(적합성·가드레일)의 전제다 */}
        {imported && session && path && (
          <TypesPanel sessionFile={session.session_file} path={path}
                      onConfirmedChange={setNConfirmed} />
        )}

        {/* 타입을 하나도 확정하지 않았으면 아래는 판정할 근거가 없다 — 열지 않는다 */}
        {imported && session && nConfirmed === 0 && (
          <div className="card hint">
            쓸 컬럼의 의미 타입을 **하나 이상** 확정하면 지표 찾기와 분석이 열립니다.
            전부 확정할 필요는 없습니다 — 쓸 것만 정하면 됩니다.
          </div>
        )}

        {imported && session && (
          <PendingBanner sessionFile={session.session_file} reloadKey={pendingKey} />
        )}

        {/* 모듈 B — 가설검정과 별개 흐름 */}
        {imported && session && <ModelLeak sessionFile={session.session_file} />}

        {imported && session && <GuardLimits />}

        {imported && session && <CliOnlyPanel />}

        {/* 질문 → 컬럼 → 무엇을 쓸까. 점수 목록은 이 아래로 접어 둔다 —
            "쓸 수 있는 것 전부"는 고르고 난 뒤에 보는 것이다 */}
        {imported && session && nConfirmed > 0 && (
          <FinderPanel sessionFile={session.session_file}
                       onDerive={(expr, name) => {
                         setSuggested({ expr, name });
                         document.getElementById("fx")?.scrollIntoView({ behavior: "smooth" });
                       }}
                       columns={imported.filter((c) => !held.includes(c))} />
        )}



        {/* Q-12 는 분석 전 설계 질문이다 — 검정 패널보다 앞에 둔다 */}
        {imported && session && (
          <RepresentPanel sessionFile={session.session_file} />
        )}

        {/* 강건성은 검정을 돌린 뒤에 본다 — 결론이 있어야 흔들 수 있다 */}
        {imported && session && nConfirmed > 0 && (
          <RobustPanel sessionFile={session.session_file} />
        )}

        {/* 분석은 **접은 채로** 시작한다 — 준비가 끝났을 때 사용자가 연다 */}
        {/* A6 는 A7 앞에 — 논문은 LLM 없이도 된다 */}
        {imported && session && nConfirmed > 0 && (
          <RefsPanel sessionFile={session.session_file} />
        )}

        {imported && session && nConfirmed > 0 && (
          <AskQwen sessionFile={session.session_file} />
        )}

        {imported && session && nConfirmed > 0 && (
          <details className="card an-gate">
            <summary>
              <b>분석 (모듈 A)</b>
              <span className="hint" style={{ margin: 0 }}>
                {" "}— 파생 컬럼과 타입 확정을 마친 뒤 펼치세요 (확정 {nConfirmed}개)
              </span>
            </summary>
            <AnalyzePanel sessionFile={session.session_file}
                          columns={imported.filter((c) => !held.includes(c))}
                          onDataChanged={() => setPendingKey((k) => k + 1)} />
          </details>
        )}

        {cols && !imported && (
          <>
            {/* 2) 요약 — 네 가지만 */}
            <div className="card quiet">
              {/* 가공 파일이면 원본이 어디였는지 — 다시 열거나 더 불러오려면 필요하다 */}
              {cols.file.origin && (
                <div className="hint" style={{ marginTop: 0, marginBottom: 8 }}>
                  {cols.file.origin}
                </div>
              )}
              <div className="kv">
                <div><span>형식</span>{cols.file.format} · {cols.file.size_mb.toFixed(0)}MB</div>
                <div><span>행</span>{cols.rows.n.toLocaleString()}{cols.rows.estimated ? " (추정)" : ""}</div>
                <div><span>컬럼</span>{cols.columns.total.toLocaleString()}</div>
                <div>
                  <span>이 쪽 결측 ≥30%</span>
                  <span style={{ color: "var(--red)", fontSize: 13 }}>
                    {cols.items.filter((i) => i.missing_level === "high").length}개
                  </span>
                </div>
              </div>
            </div>

            {/* 3) 컬럼 선택 */}
            <div className="card">
              <div className="ttl">컬럼 선택</div>
              <div className="row">
                <input
                  type="text"
                  placeholder="컬럼명 검색"
                  value={grep}
                  style={{ minWidth: 180 }}
                  onChange={(e) => setGrep(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && load(path, sort, e.currentTarget.value, 0)}
                />
                {(["missing", "unique", "name"] as Sort[]).map((s) => (
                  <button key={s} className={`sm${sort === s ? " on" : ""}`}
                          onClick={() => { setSort(s); load(path, s, grep, 0); }}>
                    {{ missing: "결측률 순", unique: "고유값 순", name: "이름 순" }[s]}
                  </button>
                ))}
              </div>

              {/* 25개씩 페이지 — 스크롤 대신 끊어 보여 컬럼이 많아도 느려지지 않는다 */}
              <div style={{ marginTop: 12 }}>
                <table>
                  <thead>
                    <tr>
                      <th className="chk"></th><th></th><th>컬럼명</th><th>타입</th>
                      <th style={{ textAlign: "right" }}>결측률</th>
                      <th style={{ textAlign: "right" }}>고유값</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cols.items.map((c) => (
                      <tr key={c.column} className={c.missing_level === "ok" ? "" : c.missing_level}>
                        <td className="chk">
                          <input type="checkbox" checked={picked.has(c.column)}
                                 onChange={() => toggle(c.column)} />
                        </td>
                        <td className="flag">{FLAG[c.missing_level]}</td>
                        <td className="col"><span className="col-name" title={c.column}>{c.column}</span></td>
                        <td>{c.dtype}</td>
                        <td className="num">{(c.missing_rate * 100).toFixed(1)}%</td>
                        <td className="num">{c.n_unique.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="row" style={{ marginTop: 12 }}>
                <button className="sm" disabled={!cols.page.has_prev || busy}
                        onClick={() => load(path, sort, grep, Math.max(0, offset - PAGE))}>← 이전</button>
                <span className="hint" style={{ margin: 0 }}>
                  {cols.page.index} / {cols.page.count} 쪽
                  {cols.columns.matched !== cols.columns.total &&
                    ` · 검색 ${cols.columns.matched.toLocaleString()}개`}
                </span>
                <button className="sm" disabled={!cols.page.has_next || busy}
                        onClick={() => load(path, sort, grep, offset + PAGE)}>다음 →</button>
              </div>

              <div className="row" style={{ marginTop: 14 }}>
                <button className="pri" disabled={picked.size === 0 || busy}
                        onClick={importPicked}>
                  선택 {picked.size}개 가져오기
                </button>
                <span className="hint" style={{ margin: 0 }}>
                  빨강 <b>!!</b> 결측 ≥30% · 주황 <b>!</b> ≥10%
                </span>
              </div>
            </div>

            {/* 4) 부가 정보 — 펼칠 때만 */}
            {cols.warnings.length > 0 && (
              <details>
                <summary>▸ <b>경고 {cols.warnings.length}건</b></summary>
                <div className="inner">
                  {cols.warnings.map((w, i) => <div className="warnbox" key={i}>{w}</div>)}
                </div>
              </details>
            )}
            <details>
              <summary>▸ <b>샘플 기준</b> — 결측률·고유값수는 어떻게 계산됐나</summary>
              <div className="inner">
                앞/중/뒤 구간에서 {cols.sample.rows_observed.toLocaleString()}행을 관측했습니다.
                {cols.sample.estimated ? " 전체가 아니므로 결측률·고유값수는 추정치입니다." : " 전체 행을 관측했습니다."}
                <div style={{ marginTop: 6 }}>
                  저장 타입: {Object.entries(cols.dtype_counts)
                    .map(([t, n]) => `${t} ${n.toLocaleString()}`).join(" · ")}
                </div>
              </div>
            </details>
            <details>
              <summary>▸ <b>세션</b> — {session?.session_id}</summary>
              <div className="inner">
                {session?.notice}
                <div style={{ marginTop: 6 }}>규칙 DB 버전: {session?.rules_version}</div>
              </div>
            </details>
          </>
        )}
      </div>
    </div>
  );
}
