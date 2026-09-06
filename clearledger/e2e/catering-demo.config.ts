import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: /catering-demo\.spec\.ts/,
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1440, height: 1000 },
  },
})
