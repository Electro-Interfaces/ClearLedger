import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { chromium, expect, type Route } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const artifactDir = process.env.CONSENT_QA_DIR ?? '/tmp/developer-authorize-20261029'
const user = { id: 'synthetic-user', email: 'user@example.test', name: 'Тестовый сотрудник', role: 'user',
  is_superadmin: false, companies: [{ id: 'company-A', name: 'Компания А', profile_id: 'fuel', slug: 'company-a' }] }
const request = (id = 'request-A') => ({ id, clientName: `Приложение ${id}`,
  requestedScopes: [{ code: 'openid', description: 'Подтверждать личность' },
    { code: 'objects:read', description: 'Читать объекты' }, { code: 'docs:read', description: 'Читать документы' }],
  companies: [{ id: 'company-A', name: 'Компания А', eligibleScopes: ['openid', 'objects:read', 'not-requested'] },
    { id: 'company-B', name: 'Компания Б', eligibleScopes: ['openid', 'docs:read'] }],
  expiresAt: new Date(Date.now() + 120_000).toISOString(),
})
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => { resolve = yes })
  return { promise, resolve }
}
const fulfill = (route: Route, body: unknown, status = 200) => route.fulfill({ status,
  contentType: 'application/json', body: JSON.stringify(body) })

test('consent browser: настоящий router, вход и явное решение пользователя', { timeout: 240_000 }, async (t) => {
  await mkdir(artifactDir, { recursive: true })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `${artifactDir}/vite-cache`,
    plugins: [react(), tailwindcss(), { name: 'consent-test-html', configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (!req.headers.accept?.includes('text/html')) return next()
        try {
          const html = await vite.transformIndexHtml(req.url ?? '/', '<!doctype html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Проверка согласия</title></head><body><div id="root"></div><script type="module" src="/tests/developer-authorization/browser-entry.tsx"></script></body></html>')
          res.setHeader('Content-Type', 'text/html'); res.end(html)
        } catch (error) { next(error) }
      })
    } }],
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': 'window.location.origin', '__APP_VERSION__': '"test"', '__APP_BUILD__': '"test"' },
    server: { host: '127.0.0.1', port: 0, hmr: false, watch: null },
  })
  await server.listen()
  const origin = server.resolvedUrls!.local[0].replace(/\/$/, '')
  const browser = await chromium.launch({ headless: true })
  const unexpectedErrors: string[] = []
  t.after(async () => { await browser.close(); await server.close(); assert.deepEqual(unexpectedErrors, []) })

  async function open(id = 'request-A', options: {
    loggedOut?: boolean; demo?: boolean; search?: string; clockTime?: number; expiredSession?: boolean;
    onRequest?: (route: Route, id: string) => Promise<void>;
    onDecision?: (route: Route) => Promise<void>;
  } = {}) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addInitScript(({ loggedOut, expired, appOrigin }) => {
      if (window.location.origin !== appOrigin) return
      if (!loggedOut) localStorage.setItem('clearledger-token', expired ? 'synthetic-expired-session' : 'synthetic-core-session')
    }, { loggedOut: options.loggedOut || options.demo, expired: options.expiredSession, appOrigin: origin })
    const calls: { path: string; method: string; body: unknown; headers: Record<string, string> }[] = []
    const callbacks: Record<string, string>[] = []
    const pageErrors: string[] = []
    // Любая внешняя сеть запрещена; callback тоже синтетический и не покидает runner.
    await context.route('**/*', (route) => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
    await context.route('https://client.example.test/**', async (route) => {
      callbacks.push(await route.request().allHeaders())
      await route.fulfill({ contentType: 'text/html', body: '<title>Callback fixture</title>Решение получено' })
    })
    await context.route('**/api/**', async (route) => {
      const incoming = route.request()
      const path = new URL(incoming.url()).pathname
      let body: unknown
      try { body = incoming.postDataJSON() } catch { body = incoming.postData() }
      calls.push({ path, method: incoming.method(), body, headers: await incoming.allHeaders() })
      if (path === '/api/auth/me') return options.expiredSession && incoming.headers().authorization === 'Bearer synthetic-expired-session'
        ? fulfill(route, { detail: 'Expired synthetic session' }, 401) : fulfill(route, user)
      if (path === '/api/auth/login') return fulfill(route, { access_token: 'synthetic-core-session', token_type: 'bearer', user })
      if (path === '/api/registry/company-apps') return fulfill(route, { apps: [] })
      if (path === '/api/sso/apps/favorites') return fulfill(route, { codes: [] })
      const match = /^\/api\/developer\/authorization-requests\/([^/]+)(?:\/(approve|deny))?$/.exec(path)
      if (match) {
        if (match[2]) return options.onDecision ? options.onDecision(route)
          : fulfill(route, { redirectUrl: 'https://client.example.test/callback?state=synthetic' })
        const decoded = decodeURIComponent(match[1])
        return options.onRequest ? options.onRequest(route, decoded) : fulfill(route, request(decoded))
      }
      // Штатные провайдеры login могут читать реестры; здесь нет рабочих данных.
      return fulfill(route, [])
    })
    const page = await context.newPage()
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('pageerror', (error) => unexpectedErrors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error' && !message.text().includes('Failed to load resource:')) unexpectedErrors.push(message.text())
    })
    if (options.clockTime) await page.clock.install({ time: options.clockTime })
    await page.goto(`${origin}/developer/authorize?requestId=${encodeURIComponent(id)}${options.demo ? '&demo=1' : ''}${options.search ?? ''}`, { waitUntil: 'domcontentloaded' })
    return { page, calls, callbacks, pageErrors, context,
      async ready(name = id) { await expect(page.getByRole('heading', { name: `«Приложение ${name}» запрашивает доступ` })).toBeVisible({ timeout: 20_000 }) },
      decisions: () => calls.filter((call) => /\/(approve|deny)$/.test(call.path)),
    }
  }

  await t.test('обычный user: нет autoapprove, только allowed selection, responsive light/dark', async (t) => {
    const f = await open(); t.after(() => f.context.close()); await f.ready()
    assert.equal(user.is_superadmin, false)
    await expect(f.page).toHaveTitle('Доступ внешнего приложения')
    await expect(f.page.getByLabel('Компания', { exact: true })).toHaveValue('')
    await expect(f.page.getByRole('button', { name: 'Разрешить выбранные действия' })).toBeDisabled()
    assert.equal(f.decisions().length, 0)
    await f.page.getByLabel('Компания', { exact: true }).selectOption('company-A')
    await expect(f.page.getByRole('checkbox', { name: /Читать документы/ })).toBeDisabled()
    await f.page.getByRole('checkbox', { name: /Читать объекты/ }).check()
    await expect(f.page.getByRole('button', { name: 'Разрешить выбранные действия' })).toBeDisabled()
    await f.page.getByRole('checkbox', { name: /Подтверждать личность/ }).check()
    await expect(f.page.getByRole('button', { name: 'Разрешить выбранные действия' })).toBeEnabled()
    await f.page.getByLabel('Компания', { exact: true }).selectOption('company-B')
    await expect(f.page.getByRole('checkbox', { name: /Подтверждать личность/ })).not.toBeChecked()
    await expect(f.page.getByRole('checkbox', { name: /Читать объекты/ })).toBeDisabled()
    assert.equal(f.decisions().length, 0)
    await f.page.screenshot({ path: `${artifactDir}/desktop.png`, fullPage: true })
    await f.page.setViewportSize({ width: 390, height: 844 })
    await f.page.evaluate(() => document.documentElement.classList.add('dark'))
    await f.page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished)))
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
    await f.page.screenshot({ path: `${artifactDir}/mobile-dark.png`, fullPage: true })
    await writeFile(`${artifactDir}/styles.json`, JSON.stringify(await f.page.getByRole('button', { name: 'Отказать', exact: true }).evaluate((button) => {
      const style = getComputedStyle(button)
      return { background: style.backgroundColor, color: style.color, opacity: style.opacity, disabled: button.hasAttribute('disabled') }
    })))
    assert.deepEqual(f.pageErrors, [])
    assert.equal(await f.page.locator('vite-error-overlay').count(), 0)
  })

  await t.test('явный approve, double submit даёт один POST; callback без Core Bearer', async (t) => {
    const gate = deferred<void>()
    const started = deferred<void>()
    const f = await open('request-A', { search: '&redirectUrl=https://ignored.example.test/evil', onDecision: async (route) => {
      started.resolve(); await gate.promise
      await fulfill(route, { redirectUrl: 'https://client.example.test/callback?state=synthetic' })
    } }); t.after(() => f.context.close()); await f.ready()
    await f.page.getByLabel('Компания', { exact: true }).selectOption('company-A')
    await f.page.getByRole('checkbox', { name: /Подтверждать личность/ }).check()
    await f.page.getByRole('checkbox', { name: /Читать объекты/ }).check()
    await f.page.getByRole('button', { name: 'Разрешить выбранные действия' }).evaluate((button) => { button.click(); button.click() })
    await started.promise
    assert.equal(f.decisions().length, 1)
    await expect(f.page.getByRole('button', { name: 'Отказать', exact: true })).toBeDisabled()
    assert.deepEqual(f.decisions()[0].body, { companyId: 'company-A', scopes: ['openid', 'objects:read'] })
    assert.equal(f.decisions()[0].headers.authorization, 'Bearer synthetic-core-session')
    gate.resolve()
    await f.page.waitForURL('https://client.example.test/**')
    assert.equal(f.callbacks.length, 1)
    assert.equal(f.callbacks[0].authorization, undefined)
    assert.equal(await f.page.evaluate(() => localStorage.getItem('clearledger-token')), null)
  })

  await t.test('явный deny доступен без компании и отметок', async (t) => {
    const f = await open('request-A', { onRequest: (route, id) => fulfill(route, { ...request(id), companies: [] }) })
    t.after(() => f.context.close()); await f.ready()
    await expect(f.page.getByText('Нет компаний с доступными действиями. Вы можете отказать приложению.')).toBeVisible()
    await f.page.getByRole('button', { name: 'Отказать', exact: true }).click()
    await f.page.waitForURL('https://client.example.test/**')
    assert.equal(f.decisions().length, 1)
    assert.match(f.decisions()[0].path, /\/deny$/)
    assert.equal(f.callbacks[0].authorization, undefined)
  })

  const changeRequest = async (page: Awaited<ReturnType<typeof open>>['page']) => page.evaluate(() => {
    history.pushState({ ...history.state, idx: (history.state?.idx ?? 0) + 1 }, '', '/developer/authorize?requestId=request-B')
    window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
  })

  await t.test('late GET A после request B не показывает прежнее согласие', async (t) => {
    const gate = deferred<void>(); const started = deferred<void>(); const released = deferred<void>()
    const f = await open('request-A', { onRequest: async (route, id) => {
      if (id === 'request-A') { started.resolve(); await gate.promise }
      await fulfill(route, request(id)).catch(() => {}) // браузер вправе уже отменить fetch A.
      if (id === 'request-A') released.resolve()
    } }); t.after(() => f.context.close()); await started.promise
    await changeRequest(f.page); await f.ready('request-B')
    gate.resolve(); await released.promise
    await expect(f.page.getByRole('heading', { name: /Приложение request-A/ })).toHaveCount(0)
    await expect(f.page.getByLabel('Компания', { exact: true })).toHaveValue('')
    assert.equal(f.decisions().length, 0)
  })

  await t.test('late POST A после request B не уводит на callback старого запроса', async (t) => {
    const gate = deferred<void>(); const started = deferred<void>()
    const f = await open('request-A', { onDecision: async (route) => {
      started.resolve(); await gate.promise
      await fulfill(route, { redirectUrl: 'https://client.example.test/old-callback' })
    } }); t.after(() => f.context.close()); await f.ready()
    await f.page.getByRole('button', { name: 'Отказать', exact: true }).click(); await started.promise
    await changeRequest(f.page); await f.ready('request-B')
    const finished = f.page.waitForEvent('requestfinished', (r) => r.url().endsWith('/deny'))
    gate.resolve(); await finished
    await f.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(new URL(f.page.url()).searchParams.get('requestId'), 'request-B')
    assert.equal(f.callbacks.length, 0)
    assert.equal(f.decisions().length, 1)
  })

  await t.test('ошибки expired/revoked/consumed/feature disabled без успешной подмены', async (t) => {
    for (const [status, title] of [[410, 'Срок запроса истёк'], [403, 'Доступ запрещён или отозван'],
      [404, 'Запрос не найден или недоступен'], [409, 'Запрос уже обработан'],
      [503, 'Подключение внешних приложений недоступно'], [422, 'Некорректный запрос подключения']] as const) {
      const f = await open('request-A', { onRequest: (route) => fulfill(route, { detail: 'Synthetic contract error' }, status) })
      t.after(() => f.context.close())
      await expect(f.page.getByRole('alert')).toContainText(title)
      assert.equal(f.decisions().length, 0)
      assert.equal(f.callbacks.length, 0)
    }
  })

  await t.test('expiry видимого запроса отключает обе команды', async (t) => {
    const expiresAt = new Date(Date.now() + 60_000).toISOString()
    const f = await open('request-A', { clockTime: Date.parse(expiresAt) - 60_000,
      onRequest: (route, id) => fulfill(route, { ...request(id), expiresAt }) })
    t.after(() => f.context.close()); await f.ready()
    await f.page.clock.fastForward(60_001)
    await expect(f.page.getByRole('alert')).toContainText('Срок запроса истёк')
    await expect(f.page.getByRole('button', { name: 'Отказать', exact: true })).toBeDisabled()
    assert.equal(f.decisions().length, 0)
  })

  await t.test('небезопасный server redirect не выполняется', async (t) => {
    const f = await open('request-A', { onDecision: (route) => fulfill(route, { redirectUrl: 'javascript:alert(1)' }) })
    t.after(() => f.context.close()); await f.ready()
    await f.page.getByRole('button', { name: 'Отказать', exact: true }).click()
    await expect(f.page.getByRole('alert')).toContainText('Не удалось безопасно вернуться в приложение')
    assert.equal(new URL(f.page.url()).pathname, '/developer/authorize')
    assert.equal(f.callbacks.length, 0)
  })

  await t.test('отзыв при POST показывает ошибку и не подменяется успехом', async (t) => {
    const f = await open('request-A', { onDecision: (route) => fulfill(route, { detail: 'Authorization revoked' }, 403) })
    t.after(() => f.context.close()); await f.ready()
    await f.page.getByRole('button', { name: 'Отказать', exact: true }).click()
    await expect(f.page.getByRole('alert')).toContainText('Доступ запрещён или отозван')
    assert.equal(f.decisions().length, 1)
    assert.equal(f.callbacks.length, 0)
  })

  await t.test('смена Core-сессии во время POST запрещает прежний callback', async (t) => {
    const gate = deferred<void>(); const started = deferred<void>()
    const f = await open('request-A', { onDecision: async (route) => {
      started.resolve(); await gate.promise
      await fulfill(route, { redirectUrl: 'https://client.example.test/old-session' })
    } }); t.after(() => f.context.close()); await f.ready()
    await f.page.getByRole('button', { name: 'Отказать', exact: true }).click(); await started.promise
    await f.page.evaluate(() => localStorage.setItem('clearledger-token', 'different-synthetic-session'))
    gate.resolve()
    await expect(f.page.getByRole('alert')).toContainText('Необходимо войти снова')
    assert.equal(f.callbacks.length, 0)
    const login = f.page.getByRole('link', { name: 'Войти снова' })
    assert.equal(new URL(await login.getAttribute('href') ?? '', origin).searchParams.get('next'), '/developer/authorize?requestId=request-A')
  })

  await t.test('смена Core-сессии во время GET не показывает старый запрос', async (t) => {
    const gate = deferred<void>(); const started = deferred<void>()
    const f = await open('request-A', { onRequest: async (route, id) => {
      started.resolve(); await gate.promise; await fulfill(route, request(id))
    } }); t.after(() => f.context.close()); await started.promise
    await f.page.evaluate(() => localStorage.setItem('clearledger-token', 'different-synthetic-session'))
    gate.resolve()
    await expect(f.page.getByRole('alert')).toContainText('Необходимо войти снова')
    await expect(f.page.getByRole('heading', { name: /Приложение request-A/ })).toHaveCount(0)
    assert.equal(f.decisions().length, 0)
  })

  await t.test('реальный login сохраняет внутренний requestId intent и не выдаёт autoapprove', async (t) => {
    const id = 'request:opaque/id'
    const f = await open(id, { loggedOut: true }); t.after(() => f.context.close())
    await f.page.waitForURL((url) => url.pathname === '/login')
    assert.equal(new URL(f.page.url()).searchParams.get('next'), `/developer/authorize?requestId=${encodeURIComponent(id)}`)
    assert.equal(f.calls.some((call) => call.path.includes('/authorization-requests/')), false)
    await f.page.getByLabel('Email', { exact: true }).fill('user@example.test')
    await f.page.getByLabel('Пароль', { exact: true }).fill('synthetic-password')
    await f.page.getByRole('button', { name: 'Войти', exact: true }).click()
    await f.ready(id)
    assert.equal(new URL(f.page.url()).searchParams.get('requestId'), id)
    assert.equal(f.decisions().length, 0)
  })

  await t.test('demo не может вызвать consent API', async (t) => {
    const f = await open('request-A', { demo: true }); t.after(() => f.context.close())
    await expect(f.page.getByRole('alert')).toContainText('Подключение внешних приложений недоступно')
    assert.equal(f.calls.some((call) => call.path.includes('/authorization-requests/')), false)
    assert.equal(f.decisions().length, 0)
  })

  await t.test('expired Core session сохраняет next после окна отложенного 401 redirect', async (t) => {
    const f = await open('request-A', { expiredSession: true, clockTime: Date.now() })
    t.after(() => f.context.close())
    await f.page.waitForURL((url) => url.pathname === '/login' && !!url.searchParams.get('next'))
    await f.page.clock.fastForward(1600)
    await f.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(f.page).toHaveURL((url) => url.pathname === '/login'
      && url.searchParams.get('next') === '/developer/authorize?requestId=request-A')
  })

  await t.test('новый login до старого 401 timer не теряет валидную сессию', async (t) => {
    const f = await open('request-A', { expiredSession: true, clockTime: Date.now() })
    t.after(() => f.context.close())
    await f.page.waitForURL((url) => url.pathname === '/login' && !!url.searchParams.get('next'))
    await f.page.getByLabel('Email', { exact: true }).fill('user@example.test')
    await f.page.getByLabel('Пароль', { exact: true }).fill('synthetic-password')
    await f.page.getByRole('button', { name: 'Войти', exact: true }).click()
    await f.ready()
    await f.page.clock.fastForward(1600)
    await f.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(new URL(f.page.url()).pathname, '/developer/authorize')
    assert.equal(await f.page.evaluate(() => localStorage.getItem('clearledger-token')), 'synthetic-core-session')
    assert.equal(f.decisions().length, 0)
  })
})
