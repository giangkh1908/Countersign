import { defineConfig } from "@playwright/test";

// Chromium không đọc hosts của Windows: ánh xạ issuer của Keycloak về 127.0.0.1 ngay trong trình duyệt.
export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:8300",
    headless: true,
    launchOptions: { args: ["--host-resolver-rules=MAP keycloak.acme.local 127.0.0.1"] },
    trace: "off",
  },
});
