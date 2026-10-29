/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const bff = "http://localhost:8300";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": bff, "/auth": bff },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
