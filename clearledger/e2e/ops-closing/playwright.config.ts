import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.', testMatch: '*.spec.ts', workers: 1, timeout: 30_000,
  outputDir: '/tmp/ops-closing-browser-results',
  use: { baseURL: 'http://127.0.0.1:3206', headless: true, locale: 'ru-RU',
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true } },
  ],
  webServer: { command: 'npm run dev -- --config e2e/ops-closing/vite.config.ts',
    url: 'http://127.0.0.1:3206/e2e/ops-closing/fixture.html', timeout: 60_000, reuseExistingServer: false },
})
