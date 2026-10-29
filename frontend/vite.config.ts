import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버는 /api 로 시작하는 요청을 백엔드로 넘긴다. 백엔드 주소는 .env 의 VITE_API_BASE_URL
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/api": env.VITE_API_BASE_URL || "http://localhost:8000" },
    },
  };
});
