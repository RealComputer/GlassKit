import { defineConfig } from "vitest/config";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import { fileURLToPath, URL } from "node:url";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] })],
  build: {
    outDir: fileURLToPath(new URL("../src/glasskit/eval/review/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.GLASSKIT_REVIEW_BACKEND ?? "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
