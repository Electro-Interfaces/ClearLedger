import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  outputDir: process.env.OPS_QA_OUTPUT ?? '/tmp/ops-usability-results',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:3199',
    headless: true,
    locale: 'ru-RU',
    viewport: { width: 1440, height: 900 },
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
      // В headless Chromium по умолчанию прячет полосы. Здесь они — предмет проверки.
      ignoreDefaultArgs: ['--hide-scrollbars'],
    },
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --config e2e/ops-usability/vite.config.ts',
    url: 'http://127.0.0.1:3199/e2e/ops-usability/fixture.html',
    timeout: 60_000,
    reuseExistingServer: false,
  },
})
