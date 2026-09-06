import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: /demo-polus\.spec\.ts/,
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: process.env.DEMO_BASE_URL ?? 'http://127.0.0.1:3012/demo-run/space/app/demo/',
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
  },
})
