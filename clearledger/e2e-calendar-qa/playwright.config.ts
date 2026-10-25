import { defineConfig, devices } from '@playwright/test'

/**
 * Проверка календаря пространства на локальном стенде:
 * API — настоящий бэкенд Ядра (127.0.0.1:8311) с отдельной БД calendar_qa,
 * фронт — Vite этой же ветки (127.0.0.1:8312).
 * Повторов нет намеренно: нестабильность — тоже результат.
 */
export default defineConfig({
  testDir: '.',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  retries: 0,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: '../../.qa/artifacts/report.json' }]],
  outputDir: '../../.qa/artifacts/test-results',
  use: {
    baseURL: 'http://127.0.0.1:8312/',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
  },
  projects: [
    { name: 'setup', testMatch: /00-auth\.setup\.ts/ },
    {
      name: 'desktop',
      testIgnore: [/00-auth\.setup\.ts/, /04-mobile\.spec\.ts/],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      dependencies: ['setup'],
    },
    {
      name: 'mobile',
      testMatch: /04-mobile\.spec\.ts/,
      use: { ...devices['Pixel 7'] },
      dependencies: ['setup'],
    },
  ],
})
