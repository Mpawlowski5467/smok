import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: 'http://127.0.0.1:38765',
    viewport: { width: 1440, height: 1000 },
    headless: true,
    launchOptions: {
      executablePath:
        process.env.SMOK_BROWSER ||
        (process.platform === 'darwin'
          ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
          : undefined),
    },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: '../.venv/bin/python ../tests/gui_fixture.py',
    url: 'http://127.0.0.1:38765/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
