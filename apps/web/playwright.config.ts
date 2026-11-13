import { defineConfig } from "@playwright/test";
import { config as loadEnv } from "dotenv";
import path from "node:path";

// Seeded test-user password lives in the API env file (never committed).
loadEnv({ path: path.resolve(__dirname, "../api/.env"), quiet: true });

const python =
  process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 60_000,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port 8000`,
      cwd: path.resolve(__dirname, "../api"),
      url: "http://127.0.0.1:8000/healthz",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- -p 3000",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
