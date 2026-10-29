import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { chromium, expect, type Page } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const origin = process.env.DOCS_E2E_ORIGIN!
const output = process.env.DOCS_E2E_DIR!
const company = process.env.DOCS_E2E_COMPANY!
if (!origin?.startsWith('https://127.0.0.1:') || !output || !process.env.DOCS_E2E_HANDSHAKE) throw new Error('Run through the guarded local pytest harness')

test('real HTTPS: public gate callback → docs cookie → separate Swagger PKCE → product read', { timeout: 240000 }, async (t) => {
  await mkdir(output, { recursive: true })
  const publicDir = `${output}/public`
  const mainDir = `${output}/main`
  await build({ root, configFile: `${root}/vite.public.config.ts`, envFile: false, logLevel: 'silent',
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin) }, build: { outDir: publicDir, emptyOutDir: true } })
  const publicScripts = await readdir(`${publicDir}/assets`)
  for (const name of publicScripts.filter((name) => name.endsWith('.js'))) {
    const code = await readFile(`${publicDir}/assets/${name}`, 'utf8')
    assert.equal(code.includes('swagger-ui-bundle.js'), false, `Swagger bytes in public build: ${name}`)
    assert.equal(code.includes('ElsyPlus Product Read API'), false, `Product schema in public build: ${name}`)
  }
  await build({ root, configFile: false, envFile: false, logLevel: 'silent', plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin), '__APP_VERSION__': '"test"', '__APP_BUILD__': '"test"' },
    build: { outDir: mainDir, emptyOutDir: true, rollupOptions: { input: `${root}/index.html`, external: ['tesseract.js'] } } })
  await writeFile(process.env.DOCS_E2E_HANDSHAKE!, JSON.stringify({ mainDir, publicDir }))
  const browser = await chromium.launch({ headless: true })
  t.after(() => browser.close())
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } })
  t.after(() => context.close())
  const externalAttempts: string[] = []
  await context.route('**/*', (route) => {
    const host = new URL(route.request().url()).origin
    if (host === origin) return route.continue()
    externalAttempts.push(host); return route.abort()
  })
  const page = await context.newPage()
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const traffic: { path: string; authorization?: string; referer?: string; body?: string }[] = []
  const statuses: { path: string; status: number }[] = []
  page.on('response', (response) => statuses.push({ path: new URL(response.url()).pathname, status: response.status() }))
  page.on('request', (request) => traffic.push({ path: new URL(request.url()).pathname,
    authorization: request.headers().authorization, referer: request.headers().referer, body: request.postData() ?? undefined }))
  async function approve(target: Page, docs = true, loseGateBeforeSubmit = false) {
    await expect(target.getByLabel('Компания', { exact: true })).toBeVisible({ timeout: 20000 })
    await target.getByLabel('Компания', { exact: true }).selectOption(company)
    if (docs) {
      await target.getByRole('checkbox', { name: /Вход через пространство/ }).check()
      await target.getByRole('checkbox', { name: /Чтение документации API/ }).check()
    } else await target.getByRole('checkbox', { name: /Чтение объектов компании/ }).check()
    // The real private consent chunk must finish loading before simulating an
    // expired gate. Clearing on URL commit races the chunk and tests a different
    // condition (correct 403 for private assets), rather than the public callback.
    if (loseGateBeforeSubmit) await context.clearCookies({ name: 'cl_gate' })
    await target.getByRole('button', { name: 'Разрешить выбранные действия' }).click()
  }

  // Actual anonymous public build -> actual login -> Core gate -> main component.
  try {
  await page.goto(`${origin}/developer/api`)
  await page.waitForURL((url) => url.pathname === '/login')
  assert.equal(new URL(page.url()).searchParams.get('next'), '/developer/api')
  assert.equal((await context.request.get(`${origin}/api/developer/docs/assets/swagger-ui-bundle.js`)).status(), 401)
  await page.getByLabel('Email', { exact: true }).fill(process.env.DOCS_E2E_USER!)
  await page.getByLabel('Пароль', { exact: true }).fill('synthetic-password')
  await page.getByRole('button', { name: 'Войти', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Открыть документацию', exact: true })).toBeVisible({ timeout: 30000 })
  const core = await page.evaluate(() => localStorage.getItem('clearledger-token'))
  assert.ok(core)
  await page.getByRole('button', { name: 'Открыть документацию', exact: true }).click()
  await page.waitForURL((url) => url.pathname === '/developer/authorize')
  // Lose only nginx gate after consent loads; callback must run public build.
  await approve(page, true, true)
  const frame = page.frameLocator('iframe[title="Защищённая Swagger документация"]')
  await expect(frame.locator('.swagger-ui')).toBeVisible({ timeout: 30000 })
  assert.equal(new URL(page.url()).pathname, '/developer/api')
  assert.equal(await page.evaluate(() => localStorage.getItem('clearledger-token')), core)
  assert.equal(await page.evaluate(() => sessionStorage.getItem('elsy.docs.pkce')), null)
  const stored = await page.evaluate(() => Object.keys(sessionStorage).filter((key) => /docs|oauth|authorized/i.test(key)))
  assert.deepEqual(stored, [])
  assert.equal((await context.request.get(`${origin}/api/v1/objects`)).status(), 401)
  for (const request of traffic) {
    if (request.path.startsWith('/p/') || request.path.includes('/assets/')) assert.equal(/(?:code|state)=/.test(request.referer ?? ''), false)
  }
  await expect(frame.locator('.opblock-summary-path[data-path="/objects"]')).toBeVisible({ timeout: 20000 })
  await page.screenshot({ path: `${output}/portal-desktop.png`, fullPage: true })

  // Native pinned Swagger Authorize is a SECOND real public Code+PKCE flow.
  await frame.getByRole('button', { name: 'Authorize', exact: true }).click()
  await frame.locator('.auth-container .checkbox label').filter({ hasText: 'objects:read' }).click()
  await expect(frame.locator('input[data-value="objects:read"]')).toBeChecked()
  await expect(frame.locator('input[data-name="clientSecret"]')).toBeHidden()
  const popupEvent = context.waitForEvent('page')
  await frame.locator('.dialog-ux .auth-btn-wrapper button.authorize').click()
  const popup = await popupEvent
  await popup.waitForURL((url) => url.pathname === '/developer/authorize')
  const exchanges = traffic.filter((request) => request.path === '/api/oauth2/token').length
  await popup.goto(`${origin}/api/developer/docs/oauth2-redirect?code=synthetic-invalid-code&state=wrong`)
  await expect(popup.locator('body')).toContainText('Недействительный или просроченный ответ')
  assert.equal(traffic.filter((request) => request.path === '/api/oauth2/token').length, exchanges)
  await popup.close()
  const retryPopup = context.waitForEvent('page')
  await frame.locator('.dialog-ux .auth-btn-wrapper button.authorize').click()
  await approve(await retryPopup, false)
  await expect(frame.locator('.auth-container')).toContainText('Authorized', { timeout: 20000 })
  await frame.getByRole('button', { name: 'Close', exact: true }).click()
  const operation = frame.locator('.opblock').filter({ has: frame.locator('.opblock-summary-path[data-path="/objects"]') })
  await operation.locator('.opblock-summary').click()
  await operation.getByRole('button', { name: 'Try it out', exact: true }).click()
  await operation.getByRole('button', { name: 'Execute', exact: true }).click()
  await expect(operation.locator('.responses-wrapper')).toContainText('Synthetic docs object', { timeout: 20000 })
  const business = traffic.findLast((request) => request.path === '/api/v1/objects')?.authorization
  const docs = traffic.find((request) => request.path === '/api/developer/docs/session' && request.authorization)?.authorization
  assert.ok(business && docs && business !== docs && business !== `Bearer ${core}` && docs !== `Bearer ${core}`)
  for (const request of traffic.filter((request) => request.path === '/api/oauth2/token')) {
    assert.equal(request.authorization, undefined)
    assert.equal(new URLSearchParams(request.body).has('client_secret'), false)
  }
  assert.equal(await page.evaluate(() => localStorage.getItem('authorized')), null)
  assert.equal(await page.evaluate(() => localStorage.getItem('clearledger-token')), core)
  const readCount = traffic.filter((request) => request.path === '/api/v1/objects').length
  await writeFile(process.env.DOCS_E2E_MODE_FILE!, 'production')
  await operation.getByRole('button', { name: 'Execute', exact: true }).click()
  await expect(operation.locator('.responses-wrapper')).toContainText('Выполнение запроса отключено', { timeout: 10000 })
  assert.equal(traffic.filter((request) => request.path === '/api/v1/objects').length, readCount)
  await writeFile(process.env.DOCS_E2E_MODE_FILE!, 'sandbox')
  await page.setViewportSize({ width: 390, height: 844 })
  await frame.locator('body').evaluate((body) => body.ownerDocument.defaultView?.scrollTo(0, 0))
  await page.screenshot({ path: `${output}/portal-mobile.png`, fullPage: true })
  await page.getByRole('button', { name: 'Выйти из документации', exact: true }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  assert.equal((await context.request.get(`${origin}/api/developer/docs/openapi.json`)).status(), 401)
  await expect.poll(async () => (await context.request.get(`${origin}/api/v1/objects`, { headers: { Authorization: business! } })).status()).toBe(401)

  // Real code generated before losing Core; expired Core must safely restart in public build.
  await page.getByRole('button', { name: 'Открыть документацию', exact: true }).click()
  await page.waitForURL((url) => url.pathname === '/developer/authorize')
  const id = new URL(page.url()).searchParams.get('requestId')!
  const approved = await context.request.post(`${origin}/api/developer/authorization-requests/${id}/approve`, {
    headers: { Authorization: `Bearer ${core}` }, data: { companyId: company, scopes: ['openid', 'docs:read'] } })
  assert.equal(approved.status(), 200)
  const redirect = (await approved.json()).redirectUrl
  await context.clearCookies({ name: 'cl_gate' })
  await page.evaluate(() => localStorage.setItem('clearledger-token', 'invalid-synthetic-core'))
  await page.goto(redirect)
  await expect(page.getByRole('alert')).toContainText('заново', { timeout: 20000 })
  assert.equal(new URL(page.url()).search, '')
  const restart = await page.getByRole('link', { name: 'Войти и начать заново' }).getAttribute('href')
  assert.equal(new URL(restart!, origin).searchParams.get('next'), '/developer/api')
  assert.equal(restart?.includes('code='), false)
  assert.deepEqual(errors, [])
  assert.deepEqual(externalAttempts, [])
  } catch (error) {
    await writeFile(`${output}/failure.json`, JSON.stringify({ path: new URL(page.url()).pathname,
      text: await page.locator('body').innerText(), frames: await Promise.all(page.frames().filter((frame) => frame !== page.mainFrame()).map(async (frame) => ({ text: await frame.locator('body').innerText() }))), errors, statuses }, null, 2))
    await page.screenshot({ path: `${output}/failure.png`, fullPage: true })
    throw error
  }
})
