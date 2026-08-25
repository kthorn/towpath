import { defineConfig } from '@playwright/test';

const smokeEnabled = process.env.GOOGLE_MAPS_SMOKE === '1';
const hasBrowserKey = Boolean(process.env.VITE_GOOGLE_MAPS_API_KEY);
const hasArtifact = Boolean(process.env.POUND_ARTIFACT_PATH);
const hasBoatHireEnrichment = Boolean(process.env.POUND_BOAT_HIRE_ENRICHMENT_PATH);
const runLiveSmoke = smokeEnabled && hasBrowserKey && hasArtifact && hasBoatHireEnrichment;

export default defineConfig({
  testDir: './tests/smoke',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: runLiveSmoke ? [
    {
      command: 'uv run uvicorn pound.web.app:app --host 127.0.0.1 --port 8000',
      cwd: '..',
      env: { ...process.env },
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      cwd: '.',
      env: { ...process.env },
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ] : undefined,
});
