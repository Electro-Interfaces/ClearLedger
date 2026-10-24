import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.', testMatch: '*.browser.test.ts', timeout: 60_000,
  workers: 1, retries: 0, reporter: 'list',
  expect: { timeout: 20_000 },
  outputDir: './results',
  use: {
    baseURL: process.env.MANAGEMENT_QA_URL || 'http://127.0.0.1:3817',
    browserName: 'chromium', headless: true, timezoneId: 'Europe/Moscow',
    viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: '/usr/bin/chromium' },
  },
})
