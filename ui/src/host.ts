/**
 * 호스트 어댑터 (요구사항) — 화면 코드는 vscode API에 직접 의존하지 않는다.
 *
 * standalone(브라우저)과 VS Code Webview가 같은 화면 코드를 쓰되, 파일 열기·경로 선택 같은
 * 호스트 종속 기능만 이 한 겹으로 감싼다. VS Code에서는 vscode API를, standalone에서는
 * 경로 입력·HTTP로 graceful fallback 한다.
 */

export interface Host {
  kind: "standalone" | "vscode";
  /** 파일 경로 선택 — VS Code는 파일 대화상자, standalone은 직접 입력(null 반환) */
  pickPath(): Promise<string | null>;
  /** 결과 저장 — VS Code는 저장 대화상자, standalone은 서버 경로 저장 */
  saveResult(name: string, content: string): Promise<void>;
  /** API 기준 주소 */
  apiBase: string;
}

declare global {
  interface Window {
    acquireVsCodeApi?: () => unknown;
    STATOP_API_BASE?: string;
  }
}

// 기본은 같은 출처(""): dev는 Vite 프록시가, 배포는 백엔드가 정적 파일을 함께 서빙한다.
const apiBase = (): string => window.STATOP_API_BASE ?? import.meta.env.VITE_EVID_API ?? "";

class StandaloneHost implements Host {
  kind = "standalone" as const;
  apiBase = apiBase();

  /** 브라우저는 서버 파일시스템을 못 여므로 경로를 직접 입력받는다 */
  async pickPath(): Promise<string | null> {
    return null;
  }

  async saveResult(name: string, content: string): Promise<void> {
    const blob = new Blob([content], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }
}

let cached: Host | null = null;

export function host(): Host {
  if (cached) return cached;
  // VS Code Webview 어댑터는 vscode-ext 스텝에서 추가한다 — 지금은 standalone만.
  cached = new StandaloneHost();
  return cached;
}
