import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local dev only: proxies to the backend the way nginx does in docker-compose,
// so `npm run dev` works standalone against `docker compose up app`.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/setupTests.js",
  },
});
