/** REST API 클라이언트 — 웹·CLI·셸이 같은 응답을 받는다 (판정 기준은 서버 한 곳). */

import { host } from "./host";

export type MissingLevel = "ok" | "mid" | "high";

export interface ColumnItem {
  column: string;
  dtype: string;
  missing_rate: number;
  n_unique: number;
  missing_level: MissingLevel;
}

export interface ColumnsResponse {
  file: { name: string; format: string; size_mb: number; transposed: boolean;
          origin: string };
  rows: { n: number; estimated: boolean };
  columns: { total: number; matched: number; offset: number; returned: number };
  page: { size: number; index: number; count: number; has_prev: boolean; has_next: boolean };
  cached: boolean;
  sample: { rows_observed: number; estimated: boolean };
  dtype_counts: Record<string, number>;
  items: ColumnItem[];
  warnings: string[];
}

export interface SourceInfo {
  id: string;
  path: string;
  format: string;
  role: "main" | "compare" | "aux";
  hash: { algo: string; mode: string; value: string };
  registered: string;
}

export interface SessionResponse {
  session_id: string;
  session_file: string;
  source_id: string | null;
  sources: SourceInfo[];
  rules_version: string | null;
  notice: string;
}

/** 토큰 역할 — 색을 나누는 기준 (F-04). 판단은 서버가 하고 웹은 칠하기만 한다. */
export type TokenRole =
  | "column" | "row_func" | "column_scalar_func" | "set_func" | "pair_func"
  | "eps" | "number" | "punct";

export interface FormulaToken { text: string; role: TokenRole }

export interface DerivePreview {
  expr: string;
  latex: string;
  tokens: FormulaToken[];
  columns: string[];
  functions: string[];
  scopes: string[];
  uses_eps: boolean;
  result_type: string;
  eps: {
    used: number | null; auto: boolean; recommended: number | null;
    min_positive: number | null; candidates: number[]; n_zeros: number;
  } | null;
  alternative: string;
  preview: {
    n: number; n_finite: number; n_nan: number; n_inf: number;
    min: number | null; max: number | null; mean: number | null;
    // 구간화·반올림에서만 실린다 — 값이 얼마나 뭉개졌는지
    distinct_before?: number; distinct_after?: number; levels?: number[];
  };
}

export type GuardTier = "gate" | "diagnostic" | "info" | "ok";

export interface GuardFinding {
  rule: string; check: string; tier: GuardTier; detail: string;
  numbers: Record<string, unknown>; columns: string[]; links: string[];
}

export interface GuardReport {
  tier: GuardTier;
  headline: string | null;          // 차단이 있을 때만. 맨 앞에 그려야 한다
  order: string[];
  findings: GuardFinding[];
  skipped: { rule: string; reason: string }[];
  overrides: { rule: string; key: string; value: unknown; base: unknown }[];
  cause_trace: Record<string, unknown>;
}

/** 지금 날아가 있는 요청들 — [중지] 가 이걸 전부 끊는다.
 *
 * 누른 것을 **되돌리지는 않는다.** 화면이 기다리는 것만 끊어 다시 누를 수 있게 한다
 * (서버가 이미 시작한 계산은 그대로 끝난다).
 */
const inflight = new Set<AbortController>();
const watchers = new Set<(n: number) => void>();

function tell(): void {
  watchers.forEach((f) => f(inflight.size));
}

/** 진행 중인 요청 수가 바뀔 때마다 알려준다. 해지 함수를 돌려준다. */
export function onInflight(f: (n: number) => void): () => void {
  watchers.add(f);
  f(inflight.size);
  return () => { watchers.delete(f); };
}

/** 지금 도는 요청을 전부 끊는다 — 끊긴 쪽은 ABORTED 를 받는다. */
export function abortAll(): number {
  const n = inflight.size;
  inflight.forEach((c) => c.abort());
  inflight.clear();
  tell();
  return n;
}

/** 중지로 끊긴 것인가 — 오류가 아니라 "중지함"으로 보여야 한다.
 *
 * 문구 자체를 사람 말로 둔다. 화면마다 따로 처리하지 않아도, 그냥 메시지를 그대로
 * 찍는 패널에서까지 "ABORTED" 같은 글자가 안 나오게 하려는 것이다. */
export const ABORTED = "중지했습니다 — 다시 누르시면 됩니다";

export function wasAborted(e: unknown): boolean {
  return String(e instanceof Error ? e.message : e).includes(ABORTED);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const ctl = new AbortController();
  inflight.add(ctl);
  tell();
  let r: Response;
  try {
    r = await fetch(`${host().apiBase}${path}`, {
      headers: { "Content-Type": "application/json" },
      signal: ctl.signal,
      ...init,
    });
  } catch (e) {
    if (ctl.signal.aborted) throw new Error(ABORTED);
    throw e;
  } finally {
    inflight.delete(ctl);
    tell();
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(body.detail ?? `${r.status}`);
  }
  return r.json() as Promise<T>;
}

export interface PathStatus {
  color: "green" | "yellow" | "red";
  exists: boolean; readable: boolean; writable: boolean;
  can_create: boolean; reason: string;
}

export interface SavedItem {
  file: string; name: string; modified: number;
  session_id: string; source: string | null; ops: number; rules_version: string | null;
}

export type ScoreEntry = {
  id: string; name: string; family: string; section: string; latex: string;
  input: string; verdict: "green" | "yellow" | "red" | "unset"; why: string;
  substituted: string; columns: string[]; note: string; coverage: string;
  //  대안 묶음 축 — "왜 이것 대신 저것인가"
  purpose: string; purpose_name: string; measures: string; scale: string;
  shaken_by: string;
  recommend: string; source: string;
};

export type PurposeGroup = { id: string; name: string; entries: ScoreEntry[] };

/** A6 논문 앵커 — 제목 수준 (v1) */
export type Anchors = {
  query: string; terms: string[]; failed: string; broadened: boolean;
  papers: { pmid: string; title: string; journal: string; year: string;
            url: string }[];
  head: string; privacy: string; title_only: string;
  broadened_note: string; none: string;
};

/** 강건성 — 등급이 아니라 이 자료에서 직접 잰 흔들림 */
export type Shake = {
  kind: string; label: string; effect: number | null; effect_name: string;
  p: number | null; flipped: boolean; failed: string;
};

export type Robust = {
  test: string; name: string; effect_name: string; effect: number | null;
  p: number | null; ref: number; n_rows: number; draws: number; seed: number;
  boot_n: number; boot_q: Record<string, number>; boot_flips: number;
  outliers: Shake[]; choices: Shake[];
  base: string; band: string; caveat: string; verdict: string[];
  heads: { boot: string; outlier: string; choice: string; read: string };
};

export type Represent = {
  total_rows: number; repeats: number; seed: number; threshold: number;
  ladder: number[];
  curves: { column: string; kind: string; metric: string; metric_name: string;
            unit_free: boolean; n_used: number; enough_n: number | null;
            points: { n: number; mean: number; lo: number; hi: number }[] }[];
  enough_n: number | null; limiting: string[];
  hypothesis: string; hypothesis_how: string;
  repeats_note: string; threshold_note: string; unit_bound: string;
  skipped_note: string;
  skipped_ids: string[];
};

export type RepresentCheck = {
  rows: { column: string; kind: string; n_picked: number; n_rest: number;
          distance: number; metric: string; p: number | null; test: string;
          line: string }[];
  not_full_note: string; p_note: string;
};

/** 한 n 에서 다시 뽑을 때마다 나온 거리들 — 임계를 감으로 잡지 않게 */
export type RepresentSpread = {
  n: number; head: string; why: string;
  spreads: { column: string; kind: string; metric: string; metric_name: string;
             n: number; draws: number; values: number[];
             q: Record<string, number>; bins: [number, number, number][];
             summary: string; suggest: string }[];
};

export type MetricSuggestion = {
  id: string; role: "support" | "guardrail"; name: string; why: string;
  source?: "base" | "user";          // 규칙표에서 온 것인가, 내가 더한 것인가
  computable: boolean; value: { lines: string[] } | null; error: string;
};

export const api = {
  health: () => req<{ status: string; statop_version: string; rules_version: string }>("/health"),

  createSession: (data?: string) =>
    req<SessionResponse>("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ data }),
    }),

  /** 메인 파일 교체 — 세션·조작기록은 유지된다  */
  setMain: (sessionFile: string, path: string) =>
    req<{ source_id: string; main: string; sources: SourceInfo[] }>("/v1/datasets", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, path, role: "main" }),
    }),

  /** 선택한 컬럼을 작업 영역으로 가져온다 (select op) */
  importColumns: (sessionFile: string, path: string, cols: string[]) =>
    req<{ source_id: string; selected: string[]; n_selected: number; ops: number }>(
      "/v1/views/import",
      { method: "POST", body: JSON.stringify({ session_file: sessionFile, path, cols }) },
    ),

  /** 가져온 컬럼을 제외한다 (deselect op) */
  dropColumns: (sessionFile: string, cols: string[]) =>
    req<{ selected: string[]; n_selected: number; derived: string[];
          dropped_derived: string[]; notice: string }>("/v1/views/drop", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, cols }),
    }),

  checkPath: (path: string, need: "read" | "write" = "write") =>
    req<PathStatus>(`/v1/paths/check?path=${encodeURIComponent(path)}&need=${need}`),

  saveSession: (sessionFile: string, outDir?: string, suffix?: string, overwrite = false) =>
    req<{ saved: string; name: string }>("/v1/sessions/save", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, out_dir: outDir, suffix, overwrite }),
    }),

  listSessions: (path?: string) =>
    req<{ dir: string; items: SavedItem[] }>(
      `/v1/sessions/list${path ? `?path=${encodeURIComponent(path)}` : ""}`),

  loadSession: (saved: string) =>
    req<{
      session_id: string; session_file: string; loaded_from: string;
      selected: Record<string, string[]>; main: string | null; ops: number;
      source_problems: { id: string; path: string; status: string; message: string }[];
      notice: string;
    }>("/v1/sessions/load", { method: "POST", body: JSON.stringify({ saved }) }),

  /** 컬럼 hold — 분석 제외, 시각화 유지 (M0-5) */
  holdColumns: (sessionFile: string, cols: string[], hold = true) =>
    req<{ held: string[]; analysis: string[]; n_analysis: number }>("/v1/views/hold", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, cols, hold }),
    }),

  /** 반영 전 가벼운 확인 — 저장된 화면 상태(view)와 조작 개수만 */
  sessionState: (sessionFile: string) =>
    req<{ session_id: string; n_ops: number;
          view: { by: string; step: string; picked: string[]; ts: string } | null }>(
      `/v1/sessions/state?session_file=${encodeURIComponent(sessionFile)}`),

  /** 화면 상태 저장 — 저장한 쪽이 있어야 상대가 반영할 것이 생긴다 (동기화 키) */
  saveView: (sessionFile: string, step: string, picked: string[]) =>
    req<{ by: string; step: string; picked: string[]; ts: string }>("/v1/sessions/view", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, by: "web", step, picked }),
    }),

  /** 세션 ID로 파일을 찾는다 — 주소를 짧게 유지하기 위한 것 */
  resolveSession: (sessionId: string) =>
    req<{ session_id: string; session_file: string }>(
      `/v1/sessions/resolve?session_id=${encodeURIComponent(sessionId)}`),

  /** 터미널에서 만든 세션을 그대로 이어받는다 — 같은 파일이므로 상태가 갈라지지 않는다 */
  adoptSession: (sessionFile: string) =>
    req<{ session_id: string; source_id: string | null; path?: string;
          selected: string[]; held: string[]; analysis: string[];
          derived: string[]; n_selected: number; n_analysis: number }>(
      `/v1/views/selected?session_file=${encodeURIComponent(sessionFile)}`),

  /** 의미 타입 후보 — 순위만, 점수 없음 (M1-1) */
  semanticTypes: (sessionFile: string) =>
    req<{ items: {
            column: string; shape: string; shape_label: string;
            confirmed: string | null; needs_confirm: boolean;
            confirm_reason: string | null; conflicts: string[];
            candidates: { rank: number; type: string; evidence: string[] }[];
          }[];
          known_types: string[]; n_confirmed: number; n_pending: number }>(
      `/v1/semantic/types?session_file=${encodeURIComponent(sessionFile)}`),

  /** 타입 확정 — 추론에 없던 타입도 막지 않고, 그 타입의 계산 위험을 돌려준다 */
  semanticConfirm: (sessionFile: string, column: string, type: string) =>
    req<{ column: string; type: string; was_inferred: boolean; notice: string | null;
          risks: { id: string; verdict: string; why: string; fix: string }[] }>(
      "/v1/semantic/confirm", {
        method: "POST",
        body: JSON.stringify({ session_file: sessionFile, column, type }),
      }),

  /** 확정 취소 — 기록은 지우지 않고 취소했다는 조작을 남긴다 */
  semanticUnconfirm: (sessionFile: string, column: string) =>
    req<{ column: string; notice: string }>("/v1/semantic/unconfirm", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, column }),
    }),

  /** 분포 (M0-3) — 숫자만 받고 그림은 화면이 그린다 */
  distribution: (path: string, cols: string[], sessionFile?: string) =>
    req<{ items: {
            column: string; kind: "numeric" | "categorical";
            bins?: number[]; edges?: number[]; quartiles?: number[];
            stats?: { key: string; label: string; value: number; text: string }[];
            fence_note?: string;
            levels?: { value: string; n: number; ratio: number }[];
          }[] }>("/v1/views/distribution", {
      method: "POST",
      body: JSON.stringify({ path, cols, session_file: sessionFile }),
    }),

  /** 라벨 수준 목록 () — 표시 값·빈도·현재 코드 */
  labelLevels: (path: string, column: string, sessionFile?: string) =>
    req<{ levels: { value: string; n: number; ratio: number; code: number }[];
          groups: Record<string, { code: number; values: string[]; n: number }> }>(
      `/v1/labels/levels?path=${encodeURIComponent(path)}&column=${encodeURIComponent(column)}`
      + (sessionFile ? `&session_file=${encodeURIComponent(sessionFile)}` : "")),

  /** 라벨 매핑 확정 — 같은 코드는 같은 군으로 묶인다 (군 재정의) */
  labelMap: (sessionFile: string, column: string, mapping: Record<string, number>) =>
    req<{ op_seq: number; groups: Record<string, unknown> }>("/v1/labels/map", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, column, mapping }),
    }),

  /** 질문 유형 11종 (A1) */
  analyzeQuestions: () =>
    req<{ questions: { id: string; question: string; user_words: string }[] }>(
      "/v1/analyze/questions"),

  /** A1 질문 설계 — 적합성 자동 판정 + A2 후보까지 */
  analyzePlan: (sessionFile: string, body: {
    question: string; y: string; group: string | null; event?: string | null;
    by?: string | null; subject?: string | null; weights?: string | null;
    control?: string | null; paired: boolean; n_tests: number; apply: boolean;
  }) =>
    req<{
      y_type: string | null; group_type: string | null;
      group_levels: Record<string, number>; problems: string[];
      candidates: { id: string; name: string; color: "green" | "yellow" | "red";
                    reasons: string[]; effect_size: string; alternatives: string;
                    design: string; runnable: boolean }[];
      recorded: boolean;
      compat: { findings: { id: string; verdict: string; detail: string;
                            why: string }[] };
      missing: Record<string, { n: number; ratio: number }>;
      n_rows: number; n_complete: number;
      repeat_candidates: { column: string; subjects: number; rows: number }[];
    }>("/v1/analyze/plan", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, ...body }),
    }),

  /**  검정 실행 — 효과크기·CI·보정 α 동반 */
  analyzeRun: (sessionFile: string, test: string) =>
    req<{ id: string; name: string; statistic: number; p: number;
          effect: { name: string; value: number; ci_low: number | null;
                    ci_high: number | null };
          n: Record<string, unknown>; notes: string[];
          strata: { level: string; n: number; p?: number; error?: string;
                    effect?: { name: string; value: number; ci_low: number | null;
                               ci_high: number | null } }[];
          assumptions: { id: string; name: string; verdict: string;
                         summary: string; action: string | null }[];
          assumptions_head: string;
          exclusion?: { n_excluded: number; n_total: number; ratio: number;
                        verdict: "green" | "yellow" | "red"; flipped: boolean;
                        alpha: number;
                        alternatives: { id: string; name: string; why: string }[];
                        before: { statistic: number; p: number;
                                  effect: { name: string; value: number } } | null };
        }>("/v1/analyze/run", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, test }),
    }),

  /** 결측 현황 */
  missing: (sessionFile: string) =>
    req<{ n_rows: number;
          columns: { column: string; n_missing: number; ratio: number }[];
          patterns: { columns: string[]; n: number; ratio: number }[] }>(
      `/v1/missing?session_file=${encodeURIComponent(sessionFile)}`),

  /** 경량 대치 — apply 전에는 몇 칸이 채워지는지만 돌려준다 */
  impute: (sessionFile: string, method: string, cols: string[],
           groupBy: string | null, apply: boolean) =>
    req<{ method: string; cols: string[]; n_filled: number; ratio: number;
          warnings: string[]; params: Record<string, unknown>;
          seed: number | null; recorded: boolean }>("/v1/missing/impute", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, method, cols,
                             group_by: groupBy, apply }),
    }),

  /** 검정이 실제로 본 개별 점 */
  points: (sessionFile: string) =>
    req<{ x: (number | string)[]; y: number[]; keys: string[]; key_column: string;
          group: string[]; by: string | null; x_kind: "numeric" | "category";
          x_label: string; y_label: string;
          excluded: { key: string; reason: string }[];
          outliers: { key: string; x: number | string; y: number; why: string }[] }>(
      `/v1/points?session_file=${encodeURIComponent(sessionFile)}`),

  /** 개별 샘플 제외 / 되돌리기 */
  excludePoint: (sessionFile: string, keyColumn: string, key: string,
                 note: string, restore = false) =>
    req<{ seq: number; key: string; restored: boolean }>("/v1/points/exclude", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, key_column: keyColumn,
                             key, note, restore }),
    }),

  /**  보조·가드레일 지표 병기 제안 */
  metrics: (sessionFile: string) =>
    req<{ goal: { test: string; name: string; effect: string; value: number;
                  p: number };
          triad: { id: string; situation: string; goal: string; support: string;
                   guardrail: string } | null;
          support: MetricSuggestion[]; guardrail: MetricSuggestion[];
          head: { support: string; guardrail: string; triad: string;
                  none: string } }>(
      `/v1/metrics?session_file=${encodeURIComponent(sessionFile)}`),

  /** 지표·검정 통합 검색 — 어느 목록에 있는지까지 */
  find: (q: string, limit = 30) =>
    req<{ query: string; terms: string[];
          hits: { id: string; name: string; kind: "score" | "test" | "post" | "relation";
                  direct: boolean; where: string; how: string; detail: string }[] }>(
      `/v1/find?q=${encodeURIComponent(q)}&limit=${limit}`),

  /** 질문 유형 11종과 그 아래 검정 — 이름을 몰라도 갈래로 찾기 */
  findQuestions: () =>
    req<{ questions: { id: string; question: string; user_words: string;
                       tests: { id: string; name: string; design: string;
                                best_when: string; effect_size: string }[] }[] }>(
      "/v1/find/questions"),

  /** / 점수 목록 + 4등급 + 수식·대입식 */
  scores: (sessionFile: string, grade?: string, family?: string) => {
    const q = new URLSearchParams({ session_file: sessionFile });
    if (grade) q.set("grade", grade);
    if (family) q.set("family", family);
    return req<{ scores: ScoreEntry[]; unset_meaning: string;
          goal: { score?: string; test?: string; name?: string } | null }>(`/v1/scores?${q}`);
  },

  /**  지표 찾기 — 이 질문·이 컬럼에 쓸 수 있는 것들 (값은 아직 안 낸다) */
  explore: (sessionFile: string, question: string, columns: string[]) =>
    req<{ question: string; question_name: string; columns: string[];
          problems: string[]; note: string; rule_labels: [string, string][];
          color_columns: string[]; second_role: string; second_columns: string[];
          candidates: { id: string; name: string; verdict: "green" | "yellow" | "red";
                        reasons: string[]; assumptions: string; effect_size: string;
                        design: string; runnable: boolean;
                        rule: Record<string, string> }[] }>(
      `/v1/explore?session_file=${encodeURIComponent(sessionFile)}`
      + `&question=${encodeURIComponent(question)}`
      + `&columns=${encodeURIComponent(columns.join(","))}`),

  /** 이 표본으로 **무엇이 잡히나** — 잰 값이 그 선의 어느 쪽인지까지  */
  explorePower: (sessionFile: string, question: string, columns: string[],
                 effects: { id: string; name: string; value: number | null;
                            effect_name: string }[] = [], target = 0.80) =>
    req<{ n: number; kind: string; cut?: number; head?: string; note: string;
          target: number;
          why: string; band: string; scale_note?: string;
          ladder?: { n: number; cut: number }[];
          rows?: { id: string; name: string; value: number; catchable?: boolean;
                   edge?: boolean; comparable?: boolean; needed_n?: number;
                   line: string }[] }>(
      "/v1/explore/power", {
        method: "POST",
        body: JSON.stringify({ session_file: sessionFile, question, columns,
                               effects, target }),
      }),

  /**  고른 컬럼의 **모양** — 값과 p 만으로는 알 수 없는 것 */
  explorePoints: (sessionFile: string, question: string, columns: string[],
                  colorBy?: string) =>
    req<{ kind: "scatter" | "groups"; x_label: string; y_label: string;
          color_by: string; n: number; edges?: number[];
          series: { name: string; pts?: [number, number][]; bins?: number[];
                    n?: number; q1?: number; med?: number; q3?: number;
                    min?: number; max?: number }[] }>(
      `/v1/explore/points?session_file=${encodeURIComponent(sessionFile)}`
      + `&question=${encodeURIComponent(question)}`
      + `&columns=${encodeURIComponent(columns.join(","))}`
      + (colorBy ? `&color_by=${encodeURIComponent(colorBy)}` : "")),

  /** 누른 검정 **하나만** 돌린다 — 기록하지 않는다 */
  exploreRun: (sessionFile: string, question: string, columns: string[], test: string) =>
    req<{ test: string; name: string; effect_name: string; effect: number | null;
          p: number | null; n: Record<string, number>; statistic: number | null;
          direction: string; notes: string[]; recorded: boolean;
          next?: { head: string; lines: string[];
                   steps: { kind: string; text: string; column?: string;
                            expr?: string; level?: string }[];
                   scan: { column: string; effect?: number; p?: number; skew?: number;
                           log_skew?: number; log_helps?: boolean; overall?: number;
                           groups?: { level: string; r: number; n: number;
                                      dcor?: number }[] }[] } }>(
      "/v1/explore/run", {
        method: "POST",
        body: JSON.stringify({ session_file: sessionFile, question, columns, test }),
      }),

  /** 다중검정 보정 (C-15 · post.yaml P-221~223) */
  padjust: (rows: { name: string; p: number }[], method: string) =>
    req<{ method: string; rule: string; alpha: number; head: string; why: string;
          lines: string[];
          rows: { name: string; p: number; p_adjusted: number;
                  significant: boolean }[] }>(
      "/v1/padjust", {
        method: "POST",
        body: JSON.stringify({ rows, method }),
      }),

  /** A6 논문 앵커 — 비슷한 질문·검정을 다룬 논문 */
  references: (sessionFile: string, limit = 5, includeLabels = true) =>
    req<Anchors>(`/v1/hypothesis/references?session_file=`
                 + `${encodeURIComponent(sessionFile)}&limit=${limit}`
                 + `&include_labels=${includeLabels}`),

  /** 강건성 — 지금 결론을 표본·이상치·다른 검정으로 흔들어 본다 */
  robust: (sessionFile: string, draws = 200) =>
    req<Robust>(`/v1/robust?session_file=${encodeURIComponent(sessionFile)}`
                + `&draws=${draws}`),

  /** Q-12 부분표집 곡선  — 답이 p 값이 아니라 n 이다 */
  represent: (sessionFile: string,
              o: { metric?: string; threshold?: number; cols?: string } = {}) => {
    const q = new URLSearchParams({ session_file: sessionFile });
    if (o.metric) q.set("metric", o.metric);
    if (o.threshold !== undefined) q.set("threshold", String(o.threshold));
    if (o.cols) q.set("cols", o.cols);
    return req<Represent>(`/v1/represent?${q}`);
  },

  /** 한 n 에서 여러 번 다시 뽑았을 때 거리들의 분포 */
  representSpread: (sessionFile: string, n: number, metric = "ks",
                    threshold = 0.05) =>
    req<RepresentSpread>(
      `/v1/represent/spread?session_file=${encodeURIComponent(sessionFile)}`
      + `&n=${n}&metric=${metric}&threshold=${threshold}`),

  /** T-1204 고른 n 검증 — 뽑은 n 행 vs 남은 행 */
  representCheck: (sessionFile: string, n: number) =>
    req<RepresentCheck>(
      `/v1/represent/check?session_file=${encodeURIComponent(sessionFile)}&n=${n}`),

  /**  같은 목적의 지표 묶음 — 고르는 것은 사용자다 */
  scoreGroups: (sessionFile: string, family?: string) => {
    const q = new URLSearchParams({ session_file: sessionFile });
    if (family) q.set("family", family);
    return req<{ groups: PurposeGroup[]; shaken_note: string;
                 pick_one: string }>(
      `/v1/scores/groups?${q}`);
  },

  /**  분포 의존 분기 */
  entropyBranch: (sessionFile: string, column: string) =>
    req<{ column: string; picked: string; name: string; latex: string; why: string;
          facts: Record<string, number | boolean>;
          rejected: { id: string; name: string; why: string }[] }>(
      `/v1/scores/entropy?session_file=${encodeURIComponent(sessionFile)}`
      + `&column=${encodeURIComponent(column)}`),

  /**  Goal 지표 지정 */
  /**  함께 볼 것을 **직접** 더한다 — 다음에도 추천으로 뜬다 */
  metricsCustom: (sessionFile: string, role: string, name: string, why = "",
                  remove?: string) =>
    req<{ key: string; notice: string; head: string; hint: string;
          custom: { support: { id: string; name: string; why: string }[];
                    guardrail: { id: string; name: string; why: string }[] } }>(
      "/v1/metrics/custom", {
        method: "POST",
        body: JSON.stringify({ session_file: sessionFile, role, name, why, remove }),
      }),

  /**  병기 선택 저장 — 무엇을 함께 보고할지 */
  metricsRoles: (sessionFile: string, support: string[], guardrail: string[],
                 note = "") =>
    req<{ key: string; support: string[]; guardrail: string[] }>(
      "/v1/metrics/roles", {
        method: "POST",
        body: JSON.stringify({ session_file: sessionFile, support, guardrail, note }),
      }),

  setGoal: (sessionFile: string, body: { score?: string; test?: string;
                                         effect_key?: string; name?: string }) =>
    req<{ seq: number; score: string | null; test: string | null;
          name: string | null }>("/v1/metrics/goal", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, ...body }),
    }),

  /** B2 누수·중복 검사 (모듈 B) */
  modelLeak: (sessionFile: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/leak?session_file=${encodeURIComponent(sessionFile)}`),

  /** B2 세트 비율·손실  — 키·기대비율이 없으면 그 검사만 건너뛴다 */
  modelSplit: (sessionFile: string, key: string, expect: string) =>
    req<{ head: string; n_failed: number; key: string; key_note: string;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/split?session_file=${encodeURIComponent(sessionFile)}`
      + `&key=${encodeURIComponent(key)}&expect=${encodeURIComponent(expect)}`),

  /** 결측정리 전/후 분포 — 그림은 코어가 문자열로 만든다 (CLI·TUI와 같은 것) */
  modelShift: (sessionFile: string, key: string, columns: string) =>
    req<{ head: string;
          views: { column: string; kind: string; lines: string[] }[] }>(
      `/v1/model/shift?session_file=${encodeURIComponent(sessionFile)}`
      + `&key=${encodeURIComponent(key)}&columns=${encodeURIComponent(columns)}`),

  /** B4 균형·분포 진단  — 전부 Diag, 막지 않는다 */
  modelBalance: (sessionFile: string, meta: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/balance?session_file=${encodeURIComponent(sessionFile)}`
      + `&meta=${encodeURIComponent(meta)}`),

  /** · 지표 변경·재현성 감사 (MB-C21 · C25~C27) */
  modelRepro: (sessionFile: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/repro?session_file=${encodeURIComponent(sessionFile)}`),

  /** 재현용 seed 고정 코드 (MB-C25) — 코어가 만든 문자열 그대로 */
  modelSeed: (sessionFile: string) =>
    req<{ code: string }>(
      `/v1/model/seed?session_file=${encodeURIComponent(sessionFile)}`),

  /** B5 평가 감사  — probability 로 확정된 컬럼이 있어야 열린다 */
  modelEval: (sessionFile: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/eval?session_file=${encodeURIComponent(sessionFile)}`),

  /** B5 전처리·모델 적합  — 표준화·차원축소·EPV */
  modelPrep: (sessionFile: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/prep?session_file=${encodeURIComponent(sessionFile)}`),

  /**  모델 비교 가능 여부 (MB-C34) — 모델은 줄바꿈으로 구분 */
  modelCompare: (models: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/compare?models=${encodeURIComponent(models)}`),

  /** B3 라벨 인코딩 방향·매핑  */
  modelLabels: (sessionFile: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/labels?session_file=${encodeURIComponent(sessionFile)}`),

  /** B2 코드 정적 감지  */
  modelCode: (path: string) =>
    req<{ head: string; n_failed: number;
          findings: { id: string; grade: string; verdict: string; summary: string;
                      detail: string[]; action: string;
                      numbers: Record<string, unknown> }[] }>(
      `/v1/model/code?path=${encodeURIComponent(path)}`),

  /** 가드레일 한계값 — 기준값·완화 하한과 함께 */
  guardLimits: () =>
    req<{ order: string[]; overrides_path: string;
          rules: { rule: string; floor: string | null; base_tier: string;
                   limits: { key: string; value: unknown; base: unknown;
                             overridden: boolean }[] }[] }>("/v1/guard/limits"),

  /** 한계값·등급 조정 — floor 아래로는 서버가 거부한다 */
  setGuardLimit: (body: { rule: string; tier?: string; key?: string;
                          value?: unknown }) =>
    req<{ rule: string; tier: string; limits: Record<string, unknown> }>(
      "/v1/guard/limits", { method: "POST", body: JSON.stringify(body) }),

  /** Ask Qwen 준비 상태 + 예상 대기 */
  qwenStatus: (sessionFile?: string) =>
    req<{ stage: "no_endpoint" | "unreachable" | "model_missing" | "ready";
          stage_label: string; detail: string; model: string; loaded: boolean;
          latency_ms: number | null;
          wait: { samples: number; seconds: number | null };
          wait_label: string;
          // A7 은 덧붙임이다 — 못 쓰면 이 패널만 끄고 이유를 보인다
          available: boolean; why: string; optional_note: string }>(
      "/v1/hypothesis/qwen/status"
      + (sessionFile ? `?session_file=${encodeURIComponent(sessionFile)}` : "")),

  /** 모델 올리기  — 상주하지 않으므로 [가설 받기] 전에 한 번 */
  loadQwen: () =>
    req<{ stage: string; detail: string; warmed?: boolean; took_ms?: number;
          model: string }>("/v1/hypothesis/qwen/load", { method: "POST" }),

  /** Ask Qwen — 버튼 한 번. dry_run 이면 보내지 않고 전송될 내용만 */
  askQwen: (sessionFile: string, dryRun = false) =>
    req<{ dry_run: boolean; would_send?: string; ready?: boolean; note?: string;
          proposals?: { stance: "optimal" | "conservative" | "broad";
                        hypothesis: string; test: string; limit: string }[];
          raw?: string; model?: string; sent_log?: string;
          labels?: Record<string, string> }>("/v1/hypothesis/qwen", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, dry_run: dryRun }),
    }),

  /** 저장하지 않은 값 변경 — 사본 저장이 필요한 상태인지 */
  pending: (sessionFile: string) =>
    req<{ counts: Record<string, number>; total: number; needs_export: boolean;
          labels: Record<string, string> }>(
      `/v1/pending?session_file=${encodeURIComponent(sessionFile)}`),

  /** 가설 1안/2안 (기계 생성) */
  hypothesis: (sessionFile: string) =>
    req<{ proposals: { title: string; statement: string; interpretation: string;
                       direction: string | null }[];
          cautions: string[]; companions: string[]; guardrail: string[] }>(
      `/v1/hypothesis?session_file=${encodeURIComponent(sessionFile)}`),

  /** 가드레일 전체 검사 (M4) — 차단이 있으면 headline이 채워진다 */
  guardRun: (sessionFile: string, group?: string, meta: string[] = [],
             metrics: string[] = []) =>
    req<GuardReport>("/v1/guard/run", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, group, meta, metrics }),
    }),

  /** 수식 편집기 키패드 — 허용 함수는 규칙 DB가 원본이므로 서버에서 받아온다 */
  deriveFunctions: () =>
    req<{ groups: { role: TokenRole | "binning"; functions: string[] }[];
          scalar_note: string }>(
      "/v1/derive/functions"),

  /** 수식 미리보기 — 파싱·eps 추천·±inf 개수. 커밋하지 않는다 */
  derivePreview: (sessionFile: string, expr: string, eps?: number | null,
                  composition?: string[]) =>
    req<DerivePreview>("/v1/derive/preview", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, expr, eps, composition }),
    }),

  /** 파생 컬럼 커밋 — 수식과 eps가 세션에 남는다 */
  deriveCommit: (sessionFile: string, expr: string, name: string, eps?: number | null,
                 composition?: string[], asType?: string) =>
    req<{ op_seq: number; name: string; expr: string; eps: number | null;
          result_type: string; notice: string }>("/v1/derive/commit", {
      method: "POST",
      body: JSON.stringify({ session_file: sessionFile, expr, name, eps,
                             composition, as_type: asType }),
    }),

  columns: (p: {
    path: string;
    sampleN?: number;
    grep?: string;
    sort?: "missing" | "unique" | "name";
    limit?: number;
    offset?: number;
    sessionFile?: string;
  }) => {
    const q = new URLSearchParams({ path: p.path });
    if (p.sampleN) q.set("sample_n", String(p.sampleN));
    if (p.grep) q.set("grep", p.grep);
    if (p.sort) q.set("sort", p.sort);
    if (p.limit) q.set("limit", String(p.limit));
    if (p.offset) q.set("offset", String(p.offset));
    if (p.sessionFile) q.set("session_file", p.sessionFile);
    return req<ColumnsResponse>(`/v1/datasets/columns?${q}`);
  },
};
