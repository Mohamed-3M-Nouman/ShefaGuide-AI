import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/triage": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/voice": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/escalations": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/audit-logs": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
