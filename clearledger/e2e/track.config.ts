import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: /track-.*\.spec\.ts/,
  timeout: 15 * 60_000,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    browserName: 'chromium',
    headless: true,
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  },
})
