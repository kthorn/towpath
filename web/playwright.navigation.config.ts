import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/navigation',
  use: { baseURL: 'http://127.0.0.1:4174', trace: 'retain-on-failure' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4174',
    cwd: '.',
    env: { ...process.env, VITE_GOOGLE_MAPS_API_KEY: 'fixture-key' },
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
