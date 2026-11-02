/** Standalone node:test React/Chromium probe; .check avoids Playwright auto-discovery.
 * Native fetch interception, zero backend/SQL.
 * AUTH_CONTEXT_BASELINE=4bcce27b supplies immutable old provider source to Vite.
 * Browser plugin not available; using the repository's existing Playwright.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { chromium } from '@playwright/test'

const root = fileURLToPath(new URL('../', import.meta.url))
const baseline = process.env.AUTH_CONTEXT_BASELINE
const provider = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/contexts/AuthContext.tsx`],
  { cwd: root, encoding: 'utf8' }) : undefined
const transport = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/apiClient.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const service = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/authService.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const artifactDir = path.resolve(root, '../.artifacts/auth-context-lifecycle', baseline ? 'baseline' : 'candidate')
let server, browser, url
before(async () => {
  await mkdir(artifactDir, { recursive: true })
  server = await createServer({ root, configFile: false, envFile: false, appType: 'mpa', logLevel: 'error',
    cacheDir: path.join(artifactDir, 'vite-cache'),
    plugins: [react(), { name: 'immutable-auth-context-baseline', enforce: 'pre',
      load(id) {
        if (provider && id.endsWith('/src/contexts/AuthContext.tsx')) return provider
        if (transport && id.endsWith('/src/services/apiClient.ts')) return transport
        if (service && id.endsWith('/src/services/authService.ts')) return service
      } }],
    resolve: { alias: { '@': path.join(root, 'src') } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify('/synthetic-api'),
      __APP_VERSION__: JSON.stringify('synthetic-lifecycle-test'), __APP_BUILD__: JSON.stringify('synthetic') },
    server: { host: '127.0.0.1', port: 0, strictPort: true, open: false },
  })
  await server.listen()
  url = `http://127.0.0.1:${server.httpServer.address().port}/e2e/auth-context-lifecycle/fixture.html`
  browser = await chromium.launch({ headless: true })
})
after(async () => { await browser?.close(); await server?.close() })

const user = (id) => ({ id, email: `${id}@example.invalid`, name: id, role: 'user', is_superadmin: false, companies: [] })
async function fixture(t, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1100, height: 700 } })
  t.after(() => context.close())
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const pending = []
  const pendingLogin = []
  await page.route('**/synthetic-api/api/auth/me', async (route) => {
    await new Promise((resolve) => pending.push({ route, resolve, token: route.request().headers().authorization,
      attempt: Number(route.request().headers()['x-react-probe-request']) }))
  })
  await page.route('**/api/auth/logout', (route) => route.fulfill({ status: 204 }))
  await page.route('**/synthetic-api/api/auth/login', async (route) => {
    if (options.holdLogin) await new Promise((resolve) => pendingLogin.push({ route, resolve }))
    else if (options.requireOTP && route.request().postDataJSON().otp !== '123456') {
      await route.fulfill({ status: 401, json: { detail: 'Введите код из приложения-аутентификатора' } })
    } else await route.fulfill({ status: 200,
      json: { access_token: 'synthetic-B', token_type: 'bearer', user: user('B') } })
  })
  await page.goto(url)
  await page.waitForFunction(() => !!window.fixture)
  assert.equal(await page.title(), 'AuthContext lifecycle — synthetic React probe')
  await page.evaluate(() => localStorage.setItem('clearledger-token', 'synthetic-A'))
  const f = {
    page, pending, pendingLogin,
    async mount(strict = false) { await page.evaluate((s) => window.fixture.mount(s), strict) },
    async waitRequests(n) {
      // Requests are enqueued in the Node route callback; this is a bounded
      // condition wait, not a timing assumption about the React effect.
      const deadline = Date.now() + 5000
      while (pending.length < n && Date.now() < deadline) await new Promise((r) => setTimeout(r, 5))
      assert.ok(pending.length >= n, `Expected ${n} controlled getMe requests, got ${pending.length}`)
    },
    async waitLogin() {
      const deadline = Date.now() + 5000
      while (!pendingLogin.length && Date.now() < deadline) await new Promise((r) => setTimeout(r, 5))
      assert.equal(pendingLogin.length, 1)
    },
    async settleLogin() {
      const held = pendingLogin[0]
      await held.route.fulfill({ status: 200,
        json: { access_token: 'synthetic-login-A', token_type: 'bearer', user: user('A') } })
      held.resolve()
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    },
    async settle(index, outcome = 'success', id = 'A') {
      const held = pending[index]
      assert.ok(held, `Missing request ${index}`)
      if (outcome === 'abort') await held.route.abort('failed')
      else await held.route.fulfill({ status: outcome === '401' ? 401 : 200,
        json: outcome === '401' ? { detail: 'Synthetic current session expired' } : user(id) })
      held.resolve()
      await page.waitForFunction((n) => window.fixture.completed(n), held.attempt)
      // Native response.json + provider Promise continuations + React commit.
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    },
    async state() { return JSON.parse(await page.getByTestId('auth-state').innerText()) },
    token: () => page.evaluate(() => localStorage.getItem('clearledger-token')),
    async applyB() {
      await page.evaluate(() => { window.applied = window.fixture.applySession('synthetic-B').catch(() => {}) })
      await f.waitRequests(2)
      assert.equal(pending[1].token, 'Bearer synthetic-B')
      await f.settle(1, 'success', 'B')
      await page.evaluate(() => window.applied)
    },
    async health(name) {
      assert.deepEqual(errors, [], 'No uncaught application/React errors')
      assert.equal(await page.locator('vite-error-overlay').count(), 0)
      await page.screenshot({ path: path.join(artifactDir, `${name}.png`) })
    },
  }
  return f
}

test('unmounted getMe network rejection preserves the shared Core token', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1)
  await f.page.evaluate(() => window.fixture.unmount())
  await f.settle(0, 'abort')
  assert.equal(await f.token(), 'synthetic-A')
})

test('unmounted getMe cancellation suppresses a late401 for the same Core token', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1)
  await f.page.evaluate(() => window.fixture.unmount())
  await f.settle(0, '401')
  assert.equal(await f.token(), 'synthetic-A')
})

test('StrictMode cleanup rejects an old effect without clearing its live retry token', async (t) => {
  const f = await fixture(t); await f.mount(true)
  await f.page.waitForFunction(() => window.fixture.started() === 2)
  const deadline = Date.now() + 5000
  while ((!f.pending.some((r) => r.attempt === 2)
      || (!f.pending.some((r) => r.attempt === 1) && !await f.page.evaluate(() => window.fixture.aborted(1))))
      && Date.now() < deadline) await new Promise((r) => setTimeout(r, 5))
  const first = f.pending.findIndex((r) => r.attempt === 1)
  if (first >= 0) await f.settle(first, 'abort')
  else await f.page.waitForFunction(() => window.fixture.completed(1))
  assert.equal(await f.token(), 'synthetic-A')
  await f.settle(f.pending.findIndex((r) => r.attempt === 2), 'success', 'A')
  assert.deepEqual(await f.state(), { user: 'A', token: 'synthetic-A', authenticated: true, loading: false })
})

test('A network failure after applySession B cannot clear B or log it out', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1); await f.applyB()
  await f.settle(0, 'abort')
  assert.equal(await f.token(), 'synthetic-B')
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
  await f.health('new-session-preserved')
})

test('A success after applySession B cannot replace B user/token state', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1); await f.applyB()
  await f.settle(0, 'success', 'A')
  assert.equal(await f.token(), 'synthetic-B')
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
})

test('A401 after applySession B must not delete B in the shared HTTP client', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1); await f.applyB()
  await f.settle(0, '401')
  assert.equal(await f.token(), 'synthetic-B')
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
})

test('current401 still logs out the current session, no authenticated render', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1)
  await f.settle(0, '401')
  assert.equal(await f.token(), null)
  assert.deepEqual(await f.state(), { user: null, token: null, authenticated: false, loading: false })
  await f.health('current401-logged-out')
})

test('current network failure remains fail-closed, no cached authenticated user', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1)
  await f.settle(0, 'abort')
  assert.equal(await f.token(), null)
  assert.deepEqual(await f.state(), { user: null, token: null, authenticated: false, loading: false })
})

test('A completion cannot finish loading while B profile is still pending', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1)
  await f.page.evaluate(() => { window.applied = window.fixture.applySession('synthetic-B').catch(() => {}) })
  await f.waitRequests(2); await f.settle(0, 'abort')
  assert.equal((await f.state()).loading, true)
  assert.equal(await f.token(), 'synthetic-B')
  await f.settle(1, 'success', 'B'); await f.page.evaluate(() => window.applied)
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
})

test('failed current applySession B removes the cached A identity and rejects the call', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1); await f.settle(0, 'success', 'A')
  await f.page.evaluate(() => { window.applyFailed = false; window.applied = window.fixture.applySession('synthetic-B')
    .catch(() => { window.applyFailed = true }) })
  await f.waitRequests(2); await f.settle(1, 'abort'); await f.page.evaluate(() => window.applied)
  assert.equal(await f.page.evaluate(() => window.applyFailed), true)
  assert.equal(await f.token(), null)
  assert.deepEqual(await f.state(), { user: null, token: null, authenticated: false, loading: false })
})

test('logout invalidates a pending refreshMe success', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1); await f.settle(0, 'success', 'A')
  await f.page.evaluate(() => { window.refreshed = window.fixture.refreshMe().catch(() => {}) })
  await f.waitRequests(2); await f.page.evaluate(() => window.fixture.logout())
  await f.settle(1, 'success', 'A'); await f.page.evaluate(() => window.refreshed)
  assert.equal(await f.token(), null)
  assert.deepEqual(await f.state(), { user: null, token: null, authenticated: false, loading: false })
})

test('late login response cannot persist A over applySession B', async (t) => {
  const f = await fixture(t, { holdLogin: true }); await f.mount(); await f.waitRequests(1)
  await f.settle(0, 'success', 'A')
  await f.page.evaluate(() => { window.loggedIn = window.fixture.login().catch(() => {}) })
  await f.waitLogin(); await f.applyB(); await f.settleLogin()
  assert.equal(await f.token(), 'synthetic-B')
  await f.page.evaluate(() => window.loggedIn)
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
  assert.equal(f.pending.length, 2, 'No stale profile request after superseded login')
})

test('late login response cannot restore a logged-out Core session', async (t) => {
  const f = await fixture(t, { holdLogin: true }); await f.mount(); await f.waitRequests(1)
  await f.settle(0, 'success', 'A')
  await f.page.evaluate(() => { window.loggedIn = window.fixture.login().catch(() => {}) })
  await f.waitLogin(); await f.page.evaluate(() => window.fixture.logout()); await f.settleLogin()
  assert.equal(await f.token(), null)
  await f.page.evaluate(() => window.loggedIn)
  assert.deepEqual(await f.state(), { user: null, token: null, authenticated: false, loading: false })
})

test('normal login stores the token before its authoritative profile request', async (t) => {
  const f = await fixture(t); await f.mount(); await f.waitRequests(1)
  await f.settle(0, 'success', 'A'); await f.page.evaluate(() => window.fixture.logout())
  await f.page.evaluate(() => { window.loggedIn = window.fixture.login().catch(() => {}) })
  await f.waitRequests(2)
  assert.equal(f.pending[1].token, 'Bearer synthetic-B')
  await f.settle(1, 'success', 'B'); await f.page.evaluate(() => window.loggedIn)
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
})

test('2FA challenge does not establish a session; successful OTP login still works', async (t) => {
  const f = await fixture(t, { requireOTP: true }); await f.mount(); await f.waitRequests(1)
  await f.settle(0, 'success', 'A'); await f.page.evaluate(() => window.fixture.logout())
  const error = await f.page.evaluate(() => window.fixture.login().then(() => null, (error) => error.detail))
  assert.equal(error, 'Введите код из приложения-аутентификатора')
  assert.equal(await f.token(), null)
  assert.equal((await f.state()).authenticated, false)
  await f.page.evaluate(() => { window.loggedIn = window.fixture.login('123456').catch(() => {}) })
  await f.waitRequests(2); await f.settle(1, 'success', 'B'); await f.page.evaluate(() => window.loggedIn)
  assert.deepEqual(await f.state(), { user: 'B', token: 'synthetic-B', authenticated: true, loading: false })
})
