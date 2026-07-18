import { defineConfig } from '@playwright/test'

/**
 * ⚠ Набор e2e написан ДО появления авторизации и сейчас проходит не полностью:
 * `goto` приводит на экран входа, поэтому всё, что требует навигации по
 * сайдбару, падает по таймауту (15 из 17 на 18.07.2026). Чтобы оживить набор,
 * нужен вход: поднятый бэкенд (:8000 + PG :5435) и storageState с сессией —
 * см. `test.use({ storageState })` в документации Playwright.
 * Порт и base-path уже исправлены: было :3000 без `/ClearLedger/`.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    // Порт — 3010 (vite.config.ts:62). В конфиге стоял 3000: тесты уходили
    // в никуда и падали по таймауту webServer.
    baseURL: 'http://localhost:3010/ClearLedger/',
    headless: false,
    viewport: { width: 1280, height: 800 },
    screenshot: 'only-on-failure',
  },
  projects: [
    // Логинится один раз и складывает сессию в e2e/.auth/admin.json.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      testIgnore: /auth\.setup\.ts/,
      use: { browserName: 'chromium', storageState: 'e2e/.auth/admin.json' },
      dependencies: ['setup'],
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3010/ClearLedger/',
    reuseExistingServer: true,
    // Холодный старт vite с этим объёмом зависимостей не укладывался в 15 с.
    timeout: 60_000,
  },
})
