import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:3000/ClearLedger/',
    headless: false,
    viewport: { width: 1280, height: 800 },
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000/ClearLedger/',
    reuseExistingServer: true,
    timeout: 15_000,
  },
})
