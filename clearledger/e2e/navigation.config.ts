import { defineConfig } from '@playwright/test'

// Отдельный локальный Vite с VITE_API_URL, без backend и рабочей авторизации.
export default defineConfig({
  testDir: '.', testMatch: 'navigation-back.spec.ts', timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0, workers: 1, reporter: 'list',
  use: {
    baseURL: process.env.NAVIGATION_BASE ?? 'http://127.0.0.1:20708',
    headless: true, screenshot: 'only-on-failure',
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
})
