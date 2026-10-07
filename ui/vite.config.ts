import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 개발 서버: /v1·/health 요청을 백엔드(8000)로 넘긴다 — CORS 설정 없이 같은 출처로 동작.
export default defineConfig({
  // API 서버가 /ui/ 아래에 붙인다. 이게 없으면 자바스크립트를 /assets/ 에서 찾다가
  // 404가 나고 **빈 화면**이 된다 (HTML은 200이라 더 헷갈린다)
  base: "/ui/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
