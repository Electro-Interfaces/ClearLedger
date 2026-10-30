// Browser plugin not available. Existing Playwright, actual React/providers/service,
// synthetic fetch/media boundaries; own ephemeral localhost server, no real API.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../', import.meta.url))
const baseline = process.env.AUDITOR_CALLER_BASELINE
const source = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/components/auditor/AuditorPanel.tsx`],
  { cwd: root, encoding: 'utf8' }) : undefined
const artifactDir = path.resolve(root, '../.artifacts/auditor-sse-context', baseline ? 'caller-baseline' : 'caller-final')
const data = (type, content) => `data: ${JSON.stringify({ type, content })}\n`

test('AuditorPanel actual React lifecycle', { timeout: 120_000 }, async (t) => {
  await mkdir(artifactDir, { recursive: true })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'error',
    cacheDir: `${artifactDir}/vite-cache`, plugins: [react(), tailwindcss(), {
      name: 'auditor-caller-fixture', enforce: 'pre', load(id) {
        if (source && id.endsWith('/src/components/auditor/AuditorPanel.tsx')) return source
      }, configureServer(vite) {
        vite.middlewares.use(async (req, res, next) => {
          if (!req.headers.accept?.includes('text/html')) return next()
          try {
            const html = await vite.transformIndexHtml(req.url ?? '/', '<!doctype html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Auditor lifecycle fixture</title></head><body><div id="root"></div><script type="module" src="/e2e/auditor-sse-context/fixture.tsx"></script></body></html>')
            res.setHeader('Content-Type', 'text/html'); res.end(html)
          } catch (error) { next(error) }
        })
      },
    }], resolve: { alias: { '@': path.join(root, 'src') } },
    define: { 'import.meta.env.VITE_API_URL': 'window.location.origin', __APP_VERSION__: '"synthetic"', __APP_BUILD__: '"synthetic"' },
    server: { host: '127.0.0.1', port: 0, strictPort: true, open: false, watch: null },
  })
  await server.listen()
  const url = `http://127.0.0.1:${server.httpServer.address().port}/fixture`
  const browser = await chromium.launch({ headless: true })
  t.after(async () => { await browser.close(); await server.close() })
  async function fixture(child) {
    const context = await browser.newContext({ viewport: { width: 1100, height: 850 } })
    child.after(() => context.close())
    const page = await context.newPage(), errors = [], external = []
    await context.route('**/*', (route) => {
      if (new URL(route.request().url()).origin === new URL(url).origin) return route.continue()
      external.push(route.request().url()); return route.abort()
    })
    await page.routeWebSocket('**/api/chat/ws?*', (socket) => socket.close())
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('console', (message) => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()) })
    await page.goto(url, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Проверка разговора аудитора' })).toBeVisible({ timeout: 25_000 })
    await expect(page.getByTestId('scope')).toHaveText('company-A:')
    await expect(page).toHaveTitle('Auditor lifecycle fixture')
    assert.equal(new URL(page.url()).origin, new URL(url).origin)
    const field = page.getByPlaceholder('Спросите про этот экран…')
    return { page, field,
      async ask(question, count) { await field.fill(question); await field.press('Enter'); await page.waitForFunction((n) => window.auditorFixture.asks.length === n, count) },
      async send(index, wire) { await page.evaluate(({ index, wire }) => window.auditorFixture.send(index, wire), { index, wire }) },
      async health(name) {
        assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.equal(await page.locator('vite-error-overlay').count(), 0)
        await page.screenshot({ path: `${artifactDir}/${name}.png` })
      },
    }
  }
  await t.test('org change aborts old stream, clears state and allows clean new history/files/actions', async (child) => {
    const f = await fixture(child)
    await f.page.getByRole('button', { name: 'Организация А', exact: true }).click()
    await f.ask('old question', 1)
    await f.send(0, data('text', 'old answer') + data('findings', [{ severity: 'low', title: 'old finding' }])
      + data('actions', [{ id: 'old', name: 'old action', summary: 'old summary' }]) + data('error', 'old error'))
    await expect(f.page.getByText('old answer', { exact: true })).toBeVisible()
    await f.page.getByRole('button', { name: 'Организация Б', exact: true }).click()
    await expect(f.page.getByTitle('Остановить', { exact: true })).toHaveCount(0)
    await expect(f.page.getByText('old answer', { exact: true })).toHaveCount(0)
    await expect(f.page.getByText('old finding', { exact: true })).toHaveCount(0)
    await expect(f.page.getByText('old action', { exact: true })).toHaveCount(0)
    await expect(f.page.getByText('old error', { exact: true })).toHaveCount(0)
    assert.equal(await f.page.evaluate(() => window.auditorFixture.asks[0].signal.aborted), true)
    await f.ask('new question', 2)
    assert.deepEqual(await f.page.evaluate(() => window.auditorFixture.asks[1].body.history), [])
    assert.deepEqual(await f.page.evaluate(() => window.auditorFixture.asks[1].body.files), [])
    await f.send(0, data('text', 'late old') + 'data: [DONE]\n')
    await f.send(1, data('text', 'new answer')); await expect(f.page.getByText('new answer', { exact: true })).toBeVisible()
    await expect(f.page.getByTitle('Остановить', { exact: true })).toBeVisible()
    await f.send(1, 'data: [DONE]\n'); await expect(f.page.getByTitle('Остановить', { exact: true })).toHaveCount(0)
    await f.health('org-new-answer')
  })
  for (const failed of [false, true]) await t.test(`pending upload ${failed ? 'error' : 'success'} cannot enter new org panel`, async (child) => {
    const f = await fixture(child)
    await f.page.locator('input[type=file]').setInputFiles({ name: 'synthetic.txt', mimeType: 'text/plain', buffer: Buffer.from('test') })
    await f.page.waitForFunction(() => window.auditorFixture.uploads.length === 1)
    await f.page.getByRole('button', { name: 'Организация Б', exact: true }).click()
    await f.page.evaluate(async (failed) => {
      window.auditorFixture.upload(0, failed)
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    }, failed)
    await expect(f.page.getByTitle('Приложить файл: выписку, реестр, акт')).toBeEnabled()
    await expect(f.page.getByText(/attached-0\.txt/)).toHaveCount(0)
    await expect(f.page.getByText('late upload error', { exact: true })).toHaveCount(0)
    await f.ask('fresh after upload', 1)
    assert.deepEqual(await f.page.evaluate(() => window.auditorFixture.asks[0].body.files), [])
    await f.send(0, 'data: [DONE]\n'); await f.health(`upload-${failed}`)
  })
  await t.test('attached file and pending dictation disappear across org A-B-A without text injection', async (child) => {
    const f = await fixture(child)
    await f.page.locator('input[type=file]').setInputFiles({ name: 'synthetic.txt', mimeType: 'text/plain', buffer: Buffer.from('test') })
    await f.page.waitForFunction(() => window.auditorFixture.uploads.length === 1)
    await f.page.evaluate(() => window.auditorFixture.upload(0))
    await expect(f.page.getByText(/attached-0\.txt/)).toBeVisible()
    await f.page.getByTitle('Продиктовать вопрос', { exact: true }).click()
    await f.page.getByTitle('Остановить и распознать', { exact: true }).click()
    await f.page.waitForFunction(() => window.auditorFixture.dictations.length === 1)
    await f.page.getByRole('button', { name: 'Организация Б', exact: true }).click()
    await f.page.getByRole('button', { name: 'Организация А', exact: true }).click()
    await f.field.fill('fresh draft')
    await f.page.evaluate(async () => {
      window.auditorFixture.dictate(0, 'old dictated text')
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    })
    await expect(f.field).toHaveValue('fresh draft'); await expect(f.page.getByText(/attached-0\.txt/)).toHaveCount(0)
    await f.ask('new after ABA', 1)
    assert.deepEqual(await f.page.evaluate(() => window.auditorFixture.asks[0].body.files), [])
    await f.send(0, 'data: [DONE]\n'); await f.health('org-aba-dictation')
  })
  await t.test('company switch preserves actual parent boundary and same-token logout/login permits a clean conversation', async (child) => {
    const f = await fixture(child)
    await f.ask('company-A question', 1); await f.page.getByRole('button', { name: 'Компания Б', exact: true }).click()
    await expect(f.page.getByTestId('scope')).toHaveText('company-B:')
    await f.ask('company-B question', 2)
    assert.deepEqual(await f.page.evaluate(() => window.auditorFixture.asks[1].body.history), [])
    await f.page.getByRole('button', { name: 'Выйти', exact: true }).click()
    await f.page.getByRole('button', { name: 'Войти снова', exact: true }).click()
    await expect(f.page.getByRole('heading', { name: 'Проверка разговора аудитора' })).toBeVisible()
    await f.ask('same token new login', 3)
    assert.deepEqual(await f.page.evaluate(() => window.auditorFixture.asks[2].body.history), [])
    await f.send(2, data('text', 'fresh session') + 'data: [DONE]\n')
    await expect(f.page.getByText('fresh session', { exact: true })).toBeVisible(); await f.health('relogin')
  })
})
