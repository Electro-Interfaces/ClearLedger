const { defineConfig, devices } = require(process.env.TEST_PW_MODULE || '@playwright/test')
const cross = process.env.QA_CROSS === '1'
module.exports = defineConfig({
  testDir: __dirname, testMatch: 'validation-grants.spec.cjs', workers: 1, retries: 0,
  timeout: 30000, expect: { timeout: 6000 },
  reporter: [['list'], ['json', { outputFile: process.env.QA_OUT + '/results.json' }]],
  outputDir: process.env.QA_OUT + '/artifacts',
  use: { baseURL: 'http://127.0.0.1:3823', headless: true, serviceWorkers: 'block', timezoneId: 'Europe/Moscow', trace: 'on', screenshot: 'only-on-failure' },
  projects: cross ? [
    { name: 'desktop-firefox', use: { browserName: 'firefox', viewport: { width: 1440, height: 900 } } },
    { name: 'iphone-webkit', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ] : [
    { name: 'desktop-chromium', use: { browserName: 'chromium', launchOptions: { executablePath: '/usr/bin/chromium' }, viewport: { width: 1440, height: 900 } } },
    { name: 'pixel-chromium', use: { ...devices['Pixel 5'], browserName: 'chromium', launchOptions: { executablePath: '/usr/bin/chromium' } } },
  ],
})
