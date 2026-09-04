import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  // Съёмка справки «Инфо» живёт по тем же правилам, что и «Трека»:
  // один конфиг, одна ширина кадра, один способ входа.
  testMatch: /(track|info)-.*\.spec\.ts/,
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
