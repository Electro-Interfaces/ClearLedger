/** ROOT-only synthetic QA; imports application/tool packages only after approval. */
import assert from 'node:assert/strict'
import test from 'node:test'
import { createHash } from 'node:crypto'
import { readFile, stat, lstat, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

const root = fileURLToPath(new URL('../../', import.meta.url))
const repo = path.dirname(root)
const self = fileURLToPath(import.meta.url)
const sha = (value) => createHash('sha256').update(value).digest('hex')
const sourceDir = path.join(root, 'tests/live-frontend-preservation')

async function approval() {
  const allowed = new Set(['HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'PLAYWRIGHT_BROWSERS_PATH', 'NODE_TEST_CONTEXT',
    'ROOT_APPROVED_LIVE_FRONTEND_PRESERVATION', 'LIVE_FRONTEND_RUNNER_SHA256', 'LIVE_FRONTEND_FREEZE',
    'LIVE_FRONTEND_FREEZE_SHA256', 'LIVE_FRONTEND_QA_DIR', 'LIVE_FRONTEND_TOOL_ROOT'])
  assert.deepEqual(Object.keys(process.env).filter((key) => !allowed.has(key)), [], 'clean allowlisted environment')
  assert.equal(process.env.HOME, '/home/mag')
  assert.equal(process.env.ROOT_APPROVED_LIVE_FRONTEND_PRESERVATION, '1', 'ROOT approval required')
  assert.equal(sha(await readFile(self)), process.env.LIVE_FRONTEND_RUNNER_SHA256, 'immutable runner SHA')
  const freezePath = process.env.LIVE_FRONTEND_FREEZE
  assert.ok(freezePath && path.isAbsolute(freezePath))
  const raw = await readFile(freezePath)
  assert.equal(sha(raw), process.env.LIVE_FRONTEND_FREEZE_SHA256)
  const freeze = JSON.parse(raw)
  for (const [relative, expected] of Object.entries(freeze.files)) {
    assert.ok(!path.isAbsolute(relative) && !relative.split('/').includes('..'))
    assert.equal(sha(await readFile(path.join(repo, relative))), expected, relative)
  }
  const out = process.env.LIVE_FRONTEND_QA_DIR
  const toolRoot = process.env.LIVE_FRONTEND_TOOL_ROOT
  assert.ok(out && path.isAbsolute(out) && out.includes('test'))
  assert.ok(toolRoot && path.isAbsolute(toolRoot))
  const info = await stat(out)
  assert.equal(info.uid, process.getuid())
  assert.equal(info.mode & 0o777, 0o700)
  assert.equal(info.isDirectory(), true)
  assert.deepEqual(await readdir(out), [], 'fresh evidence directory')
  for (let candidate = out; candidate !== path.dirname(candidate); candidate = path.dirname(candidate)) {
    assert.equal((await lstat(candidate)).isSymbolicLink(), false)
  }
  assert.ok(process.env.TMPDIR && path.isAbsolute(process.env.TMPDIR) && process.env.TMPDIR.includes('test'))
  const expected = freeze.toolVersions
  for (const [name, version] of Object.entries(expected)) {
    const pkg = JSON.parse(await readFile(path.join(toolRoot, 'node_modules', name, 'package.json'), 'utf8'))
    assert.equal(pkg.version, version, `verified tool ${name}`)
  }
  return { out, toolRoot, freeze }
}

function deferred() {
  let resolve
  const promise = new Promise((yes) => { resolve = yes })
  return { promise, resolve }
}
const station = (company, suffix = '') => ({ id: `station-${company}${suffix}`, code: company + suffix,
  name: `ЭЗС ${company}${suffix}`, type: 'ev_charging', address: 'Тестовый адрес · ' + company })
const site = (company, overrides = {}) => ({ id: 'project-' + company, kind: 'decommission', stage: 'construction',
  stageLabel: 'Реализация', title: 'Тест · Паспорт СМР', raw: {}, manualFields: [], gate: { items: [] },
  dismantleLocationIds: [], decommissionedOn: null, ...overrides })

const fulfill = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

test('M00/M17 frontend preservation: actual passport, shared transports, bounded desktop/mobile QA', { timeout: 360000 }, async (t) => {
  const { out, toolRoot, freeze } = await approval()
  const fromTools = createRequire(path.join(toolRoot, 'package.json'))
  const { createServer } = await import(pathToFileURL(fromTools.resolve('vite')).href)
  const react = (await import(pathToFileURL(fromTools.resolve('@vitejs/plugin-react')).href)).default
  const tailwind = (await import(pathToFileURL(fromTools.resolve('@tailwindcss/vite')).href)).default
  const { chromium, expect } = fromTools('@playwright/test')
  // ROOT supplies an owned temporary node_modules symlink to the verified tool tree.
  // Keep package/CSS exports intact (tailwindcss resolves a stylesheet, not a directory).
  const alias = { '@': path.join(root, 'src') }
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'warn',
    cacheDir: path.join(out, 'vite-cache'), resolve: { alias, dedupe: ['react', 'react-dom'] },
    optimizeDeps: { entries: [path.join(sourceDir, 'browser-entry.tsx')] },
    plugins: [react(), tailwind(), { name: 'passport-preservation-test', enforce: 'pre',
      transform(code, id) {
        if (id.split('?')[0] !== path.join(root, 'src/components/sites/ProjectTabs.tsx')) return
        assert.equal(code.split("from '@/contexts/SupportContext'").length - 1, 1)
        return code.replace("from '@/contexts/SupportContext'", "from '/tests/live-frontend-preservation/support.ts'")
      },
      configureServer(vite) {
        vite.middlewares.use(async (req, res, next) => {
          if (!req.headers.accept?.includes('text/html')) return next()
          try {
            const html = await vite.transformIndexHtml(req.url ?? '/', '<!doctype html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Паспорт СМР · synthetic QA</title></head><body><div id="root"></div><script type="module" src="/tests/live-frontend-preservation/browser-entry.tsx"></script></body></html>')
            res.setHeader('Content-Type', 'text/html'); res.end(html)
          } catch (error) { next(error) }
        })
      },
    }],
    define: { 'import.meta.env.VITE_API_URL': 'window.location.origin', '__APP_VERSION__': '"synthetic-test"', '__APP_BUILD__': '"synthetic-test"' },
    server: { host: '127.0.0.1', port: 0, hmr: false, watch: null,
      fs: { strict: true, allow: [root, path.join(toolRoot, 'node_modules'), out],
        deny: ['**/.env*', '**/.ssh/**', '**/.vault/**', '**/.claude/**'] } },
  })
  let browser
  const summary = { origin: null, baseline: freeze.baseCommit, browserPlugin: 'Browser plugin not available',
    cases: [], viewportEvidence: [], unexpectedRequests: [], console: [] }
  t.after(async () => {
    await browser?.close(); await server.close()
    await writeFile(path.join(out, 'browser-results.json'), JSON.stringify(summary, null, 2))
    assert.deepEqual(summary.unexpectedRequests, [])
    assert.deepEqual(summary.console, [])
  })
  await server.listen()
  const origin = server.resolvedUrls.local[0].replace(/\/$/, '')
  summary.origin = origin
  browser = await chromium.launch({ headless: true })

  let openAttempt = 0
  // Native Label htmlFor names this trigger; its visible text remains Выбрать ЭЗС.
  const choose = (page) => page.getByRole('button', { name: 'ЭЗС к демонтажу', exact: true })
  async function open(options = {}) {
    const { mobile = false, initial = {}, catalog, patch } = options
    const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
      isMobile: mobile, hasTouch: mobile, reducedMotion: 'reduce' })
    const page = await context.newPage()
    const calls = []
    const records = { 'company-A': site('company-A', initial), 'company-B': site('company-B') }
    page.on('pageerror', (error) => summary.console.push(error.message))
    page.on('console', (message) => { if (message.type() === 'error' || message.type() === 'warning') {
      // Controlled 4xx/5xx network responses are expected failure-path evidence.
      const expectedLate401 = options.expectedLate401 === true
        && message.location().url === origin + '/api/sites/project-company-A?company_id=company-A'
        && /^Failed to load resource: the server responded with a status of 401/.test(message.text())
      if (!expectedLate401 && !/^Failed to load resource: the server responded with a status of (403|422|503)/.test(message.text())) summary.console.push(message.text())
    } })
    await context.route('**/*', (route) => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
    await context.route('**/api/**', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      const headers = await request.allHeaders()
      const company = url.searchParams.get('company_id')
      const body = request.postData() ? request.postDataJSON() : null
      calls.push({ method: request.method(), path: url.pathname, company, headers, body })
      assert.equal(headers['x-company-id'], company)
      assert.equal(headers.authorization, 'Bearer synthetic-passport-session')
      if (request.method() === 'GET' && url.pathname === '/api/locations') {
        if (catalog) return catalog(route, company)
        return fulfill(route, [station(company), { ...station(company, '-warehouse'), type: 'warehouse' }])
      }
      if (url.pathname === '/api/sites/project-' + company) {
        if (request.method() === 'GET') return fulfill(route, records[company])
        if (request.method() === 'PATCH') {
          if (patch) return patch(route, body, company, records)
          if ('dismantle_location_ids' in body) records[company].dismantleLocationIds = body.dismantle_location_ids
          if ('decommissioned_on' in body) records[company].decommissionedOn = body.decommissioned_on
          return fulfill(route, { changed: Object.keys(body), site: records[company] })
        }
      }
      summary.unexpectedRequests.push({ method: request.method(), path: url.pathname })
      return fulfill(route, { detail: 'Unexpected synthetic request' }, 500)
    })
    const diagnosticId = ++openAttempt
    try {
      await page.goto(origin + '/passport', { waitUntil: 'domcontentloaded' })
      await expect(page.getByRole('heading', { name: 'Тестовая копия · Паспорт СМР' })).toBeVisible()
      await expect(choose(page)).toBeVisible({ timeout: 6000 })
      await expect(choose(page)).toHaveRole('button')
      await expect(choose(page)).toHaveText(/^Выбрать ЭЗС/)
      summary.chooseAria ??= await choose(page).ariaSnapshot()
      assert.equal(await page.title(), 'Паспорт СМР · synthetic QA')
      assert.equal(new URL(page.url()).pathname, '/passport')
      assert.equal(await page.locator('vite-error-overlay').count(), 0)
    } catch (error) {
      try {
        const diagnostic = { url: page.url(), title: await page.title(),
          aria: (await page.locator('body').ariaSnapshot()).slice(0, 32768),
          bodyText: (await page.locator('body').innerText()).slice(0, 16384) }
        await writeFile(path.join(out, `open-failure-${diagnosticId}.json`), JSON.stringify(diagnostic, null, 2))
        await page.screenshot({ animations: 'disabled', path: path.join(out, `open-failure-${diagnosticId}.png`) })
      } catch { /* bounded diagnostic must not replace the original failure */ }
      await context.close()
      throw error
    }
    return { context, page, calls, records, close: () => context.close() }
  }
  async function picker(page) {
    await choose(page).click()
    return page.getByRole('dialog', { name: 'ЭЗС к демонтажу' })
  }
  const save = (page) => page.getByRole('button', { name: /^Сохранить/ })
  async function done(name, run) {
    let failure
    let completed = false
    await t.test(name, { timeout: 45000 }, async () => {
      try { await run(); summary.cases.push(name); completed = true }
      catch (error) { failure = error; throw error }
    })
    // Abort the batch on its first actionable failure; successful runs still execute all 14.
    if (failure) throw failure
    assert.ok(completed, 'batch stopped after timed-out/cancelled scenario')
  }

  for (const mobile of [false, true]) await done(`roundtrip keyboard and nullable clears ${mobile ? 'mobile' : 'desktop'}`, async () => {
    const w = await open({ mobile })
    try {
      const trigger = choose(w.page)
      await trigger.focus(); await w.page.keyboard.press('Enter')
      const dialog = w.page.getByRole('dialog', { name: 'ЭЗС к демонтажу' })
      const check = dialog.getByRole('checkbox', { name: /ЭЗС company-A/ })
      await check.focus(); await w.page.keyboard.press('Space')
      await expect(check).toBeChecked()
      assert.equal(await dialog.getByRole('checkbox').count(), 1, 'warehouse excluded')
      await w.page.screenshot({ animations: 'disabled', path: path.join(out, `picker-${mobile ? 'mobile' : 'desktop'}.png`) })
      await dialog.getByRole('button', { name: /^Применить выбор/ }).click()
      await expect(trigger).toBeFocused()
      await w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true }).fill('2030-01-02')
      await save(w.page).click()
      await expect(save(w.page)).toBeDisabled()
      await expect(w.page.getByText('Сохранено полей: 2', { exact: true })).toBeVisible()
      const write = w.calls.find((call) => call.method === 'PATCH')
      assert.deepEqual(write.body, { decommissioned_on: '2030-01-02', dismantle_location_ids: ['station-company-A'] })
      await w.page.getByRole('button', { name: 'Открыть карточку заново', exact: true }).click()
      await expect(w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true })).toHaveValue('2030-01-02')
      await expect(w.page.getByRole('button', { name: /Убрать из перечня: company-A · ЭЗС company-A/ })).toBeVisible()
      const shot = `passport-${mobile ? 'mobile' : 'desktop'}.png`
      await w.page.screenshot({ animations: 'disabled', path: path.join(out, shot), fullPage: true })
      const geometry = await w.page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }))
      assert.ok(geometry.scrollWidth <= geometry.width, 'no horizontal clipping/overflow')
      summary.viewportEvidence.push({ mobile, screenshot: shot, geometry })
      if (mobile) {
        await w.page.getByRole('button', { name: 'Тема', exact: true }).click()
        await w.page.screenshot({ animations: 'disabled', path: path.join(out, 'passport-mobile-dark.png'), fullPage: true })
        const dark = await picker(w.page)
        await expect(dark.getByRole('checkbox', { name: /ЭЗС company-A/ })).toBeChecked()
        await w.page.screenshot({ animations: 'disabled', path: path.join(out, 'picker-mobile-dark.png') })
        await dark.getByRole('button', { name: 'Отмена', exact: true }).click()
        await w.page.getByRole('button', { name: 'Тема', exact: true }).click()
      }
      await w.page.getByRole('button', { name: /Убрать из перечня: company-A · ЭЗС company-A/ }).click()
      await w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true }).fill('')
      await save(w.page).click()
      await expect.poll(() => w.calls.filter((call) => call.method === 'PATCH').length).toBe(2)
      await expect(save(w.page)).toBeDisabled()
      assert.deepEqual(w.calls.filter((call) => call.method === 'PATCH').at(-1).body, { decommissioned_on: null, dismantle_location_ids: [] })
      await w.page.getByRole('button', { name: 'Открыть карточку заново', exact: true }).click()
      await expect(w.page.getByText('Станции не выбраны', { exact: true })).toBeVisible()
      await expect(w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true })).toHaveValue('')
    } finally { await w.close() }
  })

  await done('catalog loading, error retry, empty and search states', async () => {
    const gate = deferred()
    let attempt = 0
    const w = await open({ catalog: async (route) => { attempt++; if (attempt === 1) { await gate.promise; return fulfill(route, { detail: 'Unavailable' }, 503) } return fulfill(route, []) } })
    try {
      const dialog = await picker(w.page)
      await expect(dialog.getByRole('status')).toContainText('Загрузка станций')
      await expect(dialog.getByRole('button', { name: /^Применить выбор/ })).toBeDisabled()
      gate.resolve()
      await expect(dialog.getByRole('alert')).toContainText('Не удалось загрузить реестр')
      await dialog.getByRole('button', { name: 'Повторить', exact: true }).click()
      await expect(dialog.getByText('В доступном реестре нет ЭЗС.', { exact: true })).toBeVisible()
      await dialog.getByLabel('Поиск ЭЗС к демонтажу').fill('Нет такой станции')
      await expect(dialog.getByText('По запросу станции не найдены. Измените поиск.', { exact: true })).toBeVisible()
      await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
      await expect(save(w.page)).toBeDisabled()
    } finally { gate.resolve(); await w.close() }
  })

  for (const denied of ['hidden-station', 'foreign-station']) await done(`preserve ${denied}, 422 without success`, async () => {
    const w = await open({ initial: { dismantleLocationIds: [denied], decommissionedOn: '2030-01-02' },
      patch: (route) => fulfill(route, { detail: 'ЭЗС к демонтажу: одна из станций недоступна. Обновите выбор' }, 422) })
    try {
      await expect(w.page.getByText('Станция недоступна в текущем реестре', { exact: true })).toBeVisible()
      const dialog = await picker(w.page)
      assert.equal(await dialog.getByText(denied, { exact: true }).count(), 0, 'hidden identifier is not disclosed as a label')
      await dialog.getByRole('button', { name: /^Применить выбор/ }).click()
      await save(w.page).click()
      await expect(w.page.getByRole('alert')).toContainText('одна из станций недоступна')
      await expect(save(w.page)).toBeEnabled()
      assert.deepEqual(w.calls.find((call) => call.method === 'PATCH').body, { dismantle_location_ids: [denied] })
      assert.equal(await w.page.getByText(/^Сохранено полей:/).count(), 0)
      await expect(w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true })).toHaveValue('2030-01-02')
    } finally { await w.close() }
  })

  await done('date 422 keeps draft and has no success', async () => {
    const w = await open({ patch: (route) => fulfill(route, { detail: 'Дата вывода ЭЗС из эксплуатации: укажите корректную дату ГГГГ-ММ-ДД' }, 422) })
    try {
      await w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true }).fill('2030-01-02')
      await save(w.page).click()
      await expect(w.page.getByRole('alert')).toContainText('корректную дату')
      await expect(w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true })).toHaveValue('2030-01-02')
      assert.equal(await w.page.getByText(/^Сохранено полей:/).count(), 0)
    } finally { await w.close() }
  })

  for (const switchKind of ['company', 'session']) await done(`stale catalog ignored after ${switchKind} switch`, async () => {
    const gate = deferred()
    const started = deferred()
    const w = await open({ catalog: async (route, company) => {
      if (company === 'company-A') { started.resolve(); await gate.promise }
      try { return await fulfill(route, [station(company)]) } catch { /* consumed AbortSignal cancels the old browser request */ }
    } })
    try {
      await picker(w.page)
      await expect(w.page.getByRole('dialog').getByRole('status')).toContainText('Загрузка станций')
      await started.promise
      const cancelled = w.page.waitForEvent('requestfailed', (request) => {
        const url = new URL(request.url())
        return url.pathname === '/api/locations' && url.searchParams.get('company_id') === 'company-A'
      })
      // Test navigation is outside a modal's focus trap, as an application context boundary can be.
      await w.page.locator('nav[aria-label="Тестовый контекст"]')
        .getByRole('button', { name: switchKind === 'company' ? 'Компания B' : 'Новый сеанс', exact: true, includeHidden: true })
        .evaluate((button) => button.click())
      assert.match((await cancelled).failure().errorText, /ABORTED|CANCELLED/i, 'AbortSignal cancels the old catalog request')
      gate.resolve()
      await expect(w.page.getByRole('dialog')).toHaveCount(0)
      if (switchKind === 'company') {
        await expect(w.page.getByText('Текущая компания: company-B', { exact: true })).toBeVisible()
        const dialog = await picker(w.page)
        await expect(dialog.getByRole('checkbox', { name: /ЭЗС company-B/ })).toBeVisible()
        assert.equal(await dialog.getByText(/ЭЗС company-A/).count(), 0)
      } else await expect(w.page.getByRole('alert')).toContainText('Сеанс изменился')
      assert.equal(w.calls.filter((call) => call.method === 'PATCH').length, 0)
    } finally { gate.resolve(); await w.close() }
  })

  for (const switchKind of ['company', 'session']) await done(`unsaved selection discarded after ${switchKind} switch`, async () => {
    const w = await open()
    try {
      const dialog = await picker(w.page)
      await dialog.getByRole('checkbox', { name: /ЭЗС company-A/ }).check()
      await dialog.getByRole('button', { name: /^Применить выбор/ }).click()
      await expect(save(w.page)).toBeEnabled()
      await w.page.getByRole('button', { name: switchKind === 'company' ? 'Компания B' : 'Новый сеанс', exact: true }).click()
      if (switchKind === 'session') {
        await expect(w.page.getByRole('alert')).toContainText('Сеанс изменился')
        await w.page.getByRole('button', { name: 'Открыть карточку заново', exact: true }).click()
      }
      const fresh = await picker(w.page)
      await expect(fresh.getByRole('checkbox')).not.toBeChecked()
      if (switchKind === 'company') assert.equal(await fresh.getByText(/ЭЗС company-A/).count(), 0)
      assert.equal(w.calls.filter((call) => call.method === 'PATCH').length, 0)
    } finally { await w.close() }
  })

  for (const switchKind of ['company', 'session', 'A-B-A']) await done(`late save ignored after ${switchKind}`, async () => {
    const gate = deferred()
    const started = deferred()
    const w = await open({ patch: async (route, body, company, records) => {
      started.resolve(); await gate.promise
      return fulfill(route, { changed: Object.keys(body), site: records[company] })
    } })
    try {
      await w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true }).fill('2030-01-02')
      await save(w.page).click(); await started.promise
      await w.page.getByRole('button', { name: switchKind === 'session' ? 'Новый сеанс' : 'Компания B', exact: true }).click()
      if (switchKind === 'A-B-A') {
        await expect(choose(w.page)).toBeVisible()
        await w.page.getByRole('button', { name: 'Компания A', exact: true }).click()
      }
      if (switchKind !== 'session') await expect(choose(w.page)).toBeVisible()
      const completed = w.page.waitForResponse((response) => response.request().method() === 'PATCH')
      const getsBefore = w.calls.filter((call) => call.method === 'GET' && call.path.startsWith('/api/sites/')).length
      gate.resolve()
      await (await completed).finished()
      await w.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      if (switchKind === 'session') await expect(w.page.getByRole('alert')).toContainText('Сеанс изменился')
      else await expect(w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true })).toHaveValue('')
      assert.equal(await w.page.getByText(/^Сохранено полей:/).count(), 0)
      assert.equal(w.calls.filter((call) => call.method === 'PATCH').length, 1)
      assert.equal(w.calls.filter((call) => call.method === 'GET' && call.path.startsWith('/api/sites/')).length, getsBefore, 'late save cannot refetch the old project')
      assert.deepEqual(w.calls.find((call) => call.method === 'PATCH').body, { decommissioned_on: '2030-01-02' })
    } finally { gate.resolve(); await w.close() }
  })
  await done('late 401 preserves the new token and does not redirect', async () => {
    const gate = deferred()
    const started = deferred()
    const w = await open({ expectedLate401: true, patch: async (route) => {
      started.resolve(); await gate.promise
      return fulfill(route, { detail: 'Expired old synthetic session' }, 401)
    } })
    try {
      await w.page.clock.install()
      await w.page.getByLabel('Дата вывода ЭЗС из эксплуатации', { exact: true }).fill('2030-01-02')
      await save(w.page).click(); await started.promise
      await w.page.getByRole('button', { name: 'Другой сеанс', exact: true }).click()
      const completed = w.page.waitForResponse((response) => response.request().method() === 'PATCH')
      gate.resolve()
      await (await completed).finished()
      await w.page.clock.runFor(2000)
      assert.equal(await w.page.evaluate(() => localStorage.getItem('clearledger-token')), 'synthetic-passport-new-session')
      assert.equal(new URL(w.page.url()).pathname, '/passport')
      await expect(w.page.getByRole('alert')).toContainText('Сеанс изменился')
      assert.equal(await w.page.getByText('Сессия истекла', { exact: true }).count(), 0)
      assert.equal(await w.page.getByText(/^Сохранено полей:/).count(), 0)
    } finally { gate.resolve(); await w.close() }
  })
  assert.equal(summary.cases.length, 14)
})
