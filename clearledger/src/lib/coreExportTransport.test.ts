import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test, { mock } from 'node:test'
import { createServer } from 'vite'

// Actual service modules + actual apiClient, following the existing Vite SSR harness.
// Only external boundaries are synthetic: fetch, storage, DOM, toast and redirect timer.
const root = fileURLToPath(new URL('../../', import.meta.url))
const origin = 'https://core.example.test'
const bytes = new Uint8Array([0, 255, 42, 128])
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
const errorResponse = (status: number, detail: unknown = 'Synthetic denied') => new Response(JSON.stringify({ detail }), {
  status, statusText: 'Synthetic error', headers: { 'Content-Type': 'application/json' },
})

async function fixture() {
  const originals = new Map(['window', 'document', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const memory = () => {
    const data = new Map<string, string>()
    return { getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) }
  }
  const local = memory()
  const location = { origin, pathname: '/protected', search: '', hash: '', href: '' }
  const calls: { url: string; init?: RequestInit }[] = []
  const events: string[] = [], attached = new Set<object>()
  let reply: () => Promise<Response> = async () => new Response(bytes)
  let filename = '', captured: Blob | undefined, hook: ((event: string) => void) | undefined
  const emit = (event: string) => { events.push(event); hook?.(event) }
  const document = {
    createElement(tag: string) {
      assert.equal(tag, 'a'); emit('create')
      return { href: '', set download(value: string) { filename = value },
        click() { assert.equal(this.href, 'blob:core-export'); assert.ok(attached.has(this)); emit('click') },
        remove() { attached.delete(this); emit('remove') } }
    },
    body: { appendChild(anchor: object) { attached.add(anchor); emit('append') } },
  }
  for (const [key, value] of Object.entries({ window: { location }, document, localStorage: local,
    sessionStorage: memory(), fetch: async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), init }); return reply()
    } })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const createURL = mock.method(URL, 'createObjectURL', (blob: Blob) => {
    captured = blob; emit('url'); return 'blob:core-export'
  })
  const revokeURL = mock.method(URL, 'revokeObjectURL', (url: string) => { assert.equal(url, 'blob:core-export'); emit('revoke') })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `${root}/../.artifacts/cache/core-export-vite-${process.pid}`,
    plugins: [{ name: 'core-export-toast-probe', transform(code, id) {
      if (id.endsWith('/src/services/apiClient.ts')) return code.replace(/import\((['"])sonner\1\)/, "import('virtual:core-export-toast')")
    }, resolveId(id) { if (id === 'virtual:core-export-toast') return '\0core-export-toast' }, load(id) {
      if (id === '\0core-export-toast') return 'export const messages=[]; export const toast={error:(...args)=>messages.push(args)}'
    } }], resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin), 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const charge = await server.ssrLoadModule('/src/services/chargeSessionsService.ts') as typeof import('../services/chargeSessionsService.ts')
  const corporate = await server.ssrLoadModule('/src/services/corporateService.ts') as typeof import('../services/corporateService.ts')
  const sites = await server.ssrLoadModule('/src/services/sitesService.ts') as typeof import('../services/sitesService.ts')
  const toast = await server.ssrLoadModule('\0core-export-toast') as { messages: unknown[][] }
  const timers = new Map<object, () => void>()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((fn: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSet(fn, delay, ...args)
    const id = {}; timers.set(id, fn); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!timers.delete(id)) originalClear(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  return { api, charge, corporate, sites, calls, events, local, location, timers, toast,
    filename: () => filename, captured: () => captured,
    respond(fn: typeof reply) { reply = fn }, hook(fn: typeof hook) { hook = fn },
    reset() {
      assert.equal(attached.size, 0, 'No anchor may leak between exports')
      hook = undefined; captured = undefined; filename = ''; calls.length = 0; events.length = 0
      api.setToken('synthetic-A'); api.setApiCompany('company-A'); api.setApiOrganization('org-A')
      location.pathname = '/protected'; location.search = ''; location.hash = ''; location.href = ''; toast.messages.length = 0
      reply = async () => new Response(bytes)
    },
    runTimers() { for (const [id, fn] of timers) { timers.delete(id); fn() } },
    async close() {
      start.mock.restore(); stop.mock.restore(); createURL.mock.restore(); revokeURL.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('Core exports: actual services use the shared binary transport', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  const period = { companyId: 'company-A', dateFrom: '2026-10-01', dateTo: '2026-10-30' }
  const scope = { stations: ['ЭЗС 1', 'CCS/2'], regions: ['Москва', 'Север & Юг'] }
  const filters = {
    company_id: 'company-A', date_from: '2026-10-01', date_to: '2026-10-30',
    stations: 'ЭЗС 1,CCS/2', regions: 'Москва,Север & Юг',
  }
  type Operation = {
    name: string; path: string; query: Record<string, string>; filename: string
    call: (signal?: AbortSignal) => Promise<void>
  }
  const operations: Operation[] = [
    { name: 'monthly', path: '/api/charge-sessions/export/monthly-matrix', query: { company_id: 'company-A' },
      filename: 'station_monthly_matrix.xlsx',
      call: (signal) => signal ? f.charge.exportMonthlyMatrixXlsx('company-A', { signal }) : f.charge.exportMonthlyMatrixXlsx('company-A') },
    { name: 'sessions', path: '/api/charge-sessions/export', query: { ...filters, user_type: 'ЮЛ', client: 'Клиент + /?&#' },
      filename: 'sessions_2026-10-01_2026-10-30.xlsx',
      call: (signal) => f.charge.exportChargeSessionsXlsx({ ...period, ...scope, userType: 'ЮЛ', client: 'Клиент + /?&#' }, signal ? { signal } : undefined) },
    { name: 'pivot', path: '/api/charge-sessions/export/pivot', query: filters,
      filename: 'Сессии ЭЗС со сводной 2026-10-01 — 2026-10-30.xlsx',
      call: (signal) => f.charge.exportChargeSessionsPivotXlsx({ ...period, ...scope }, signal ? { signal } : undefined) },
    { name: 'billing', path: '/api/corporate/billing-export', query: { ...filters, client: 'Клиент + /?&#', vat_rate: '0' },
      filename: 'billing_upd_client_2026-10-01_2026-10-30.xlsx',
      call: (signal) => f.corporate.exportCorporateBillingUpd({ ...period, ...scope, client: 'Клиент + /?&#', vatRate: 0 }, signal ? { signal } : undefined) },
    { name: 'sites', path: '/api/sites/export/tech-connections',
      query: { company_id: 'company-A', ...filters, search: 'Площадка + /?&#', stage: 'construction', mine: '1', offset: '0' },
      filename: 'Мой отчёт.xlsx',
      call: (signal) => f.sites.exportXlsx('company-A', 'tech-connections', 'Мой отчёт.xlsx', {
        ...filters, search: 'Площадка + /?&#', stage: 'construction', mine: true, offset: 0,
        omitFalse: false, omitEmpty: '', omitUndefined: undefined,
      }, signal ? { signal } : undefined) },
  ]
  const assertWire = (op: Operation, signal?: AbortSignal) => {
    assert.equal(f.calls.length, 1, 'Exactly one network request per export')
    const { url, init } = f.calls[0], parsed = new URL(url)
    assert.equal(parsed.origin, origin); assert.equal(parsed.pathname, op.path)
    assert.deepEqual(Object.fromEntries(parsed.searchParams), op.query)
    assert.equal([...parsed.searchParams].length, Object.keys(op.query).length, 'No duplicate query keys')
    assert.equal(init?.method ?? 'GET', 'GET'); assert.equal(init?.body, undefined)
    assert.deepEqual(init?.headers, { Authorization: 'Bearer synthetic-A', 'X-Company-Id': 'company-A', 'X-Organization-Id': 'org-A' })
    assert.equal(init?.signal, signal)
  }
  const assertNoDownload = () => { assert.deepEqual(f.events, []); assert.equal(f.captured(), undefined) }

  for (const op of operations) {
    await t.test(`${op.name}: old caller, exact filters, fallback, bytes and cleanup`, async () => {
      f.reset(); assert.equal(await op.call(), undefined); assertWire(op)
      assert.equal(f.filename(), op.filename)
      assert.deepEqual([...new Uint8Array(await f.captured()!.arrayBuffer())], [...bytes])
      assert.deepEqual(f.events, ['url', 'create', 'append', 'click', 'remove', 'revoke'])
    })
    await t.test(`${op.name}: current context is read at invocation`, async () => {
      f.reset(); f.api.setToken('synthetic-B'); f.api.setApiCompany('company-B'); f.api.setApiOrganization('org-B')
      // Existing query params are deliberately unchanged: transport guards the in-flight context,
      // not arbitrary caller params that were already stale before the request began.
      await op.call()
      assert.deepEqual(f.calls[0].init?.headers, {
        Authorization: 'Bearer synthetic-B', 'X-Company-Id': 'company-B', 'X-Organization-Id': 'org-B',
      })
      assert.equal(f.calls.length, 1); assert.ok(f.events.includes('click'))
    })
    const names = [
      { header: undefined, expected: op.filename },
      { header: 'attachment', expected: op.filename },
      { header: 'attachment; filename="server.xlsx"', expected: 'server.xlsx' },
      { header: `attachment; filename="ascii.xlsx"; filename*=UTF-8''${encodeURIComponent('Сервер ЭЗС.xlsx')}`, expected: 'Сервер ЭЗС.xlsx' },
      { header: `attachment; filename*=UTF-8''${encodeURIComponent('Только сервер.xlsx')}`, expected: 'Только сервер.xlsx' },
      { header: "attachment; filename*=UTF-8''%ZZ", expected: op.filename },
      { header: "attachment; filename=\"ascii.xlsx\"; filename*=UTF-8''%ZZ", expected: 'ascii.xlsx' },
    ]
    for (const [index, name] of names.entries()) await t.test(`${op.name}: server filename priority/fallback ${index}`, async () => {
      f.reset(); f.respond(async () => new Response(bytes, { headers: name.header ? { 'Content-Disposition': name.header } : {} }))
      await op.call(); assertWire(op); assert.equal(f.filename(), name.expected)
    })
    for (const status of [403, 404, 422, 500]) await t.test(`${op.name}: HTTP ${status} rejects without a fake file`, async () => {
      f.reset()
      const detail = status === 422 ? [{ loc: ['query', 'date_from'], msg: 'Invalid date', type: 'value_error' }] : 'Synthetic denied'
      f.respond(async () => errorResponse(status, detail))
      await assert.rejects(op.call(), (error: unknown) => {
        assert.ok(error instanceof f.api.ApiError); assert.equal(error.status, status)
        if (status === 422) { assert.ok(error instanceof f.api.ApiValidationError); assert.deepEqual(error.fieldErrors, detail) }
        else assert.equal(error.detail, detail)
        return true
      })
      assertWire(op); assertNoDownload(); assert.equal(f.api.getToken(), 'synthetic-A'); assert.equal(f.timers.size, 0)
    })
    await t.test(`${op.name}: non-JSON HTTP error is not downloaded`, async () => {
      f.reset(); f.respond(async () => new Response('<html>error</html>', { status: 502, statusText: 'Bad Gateway' }))
      await assert.rejects(op.call(), { name: 'ApiError', status: 502, detail: 'Bad Gateway' })
      assertWire(op); assertNoDownload()
    })
    await t.test(`${op.name}: current 401 uses shared session/toast/redirect semantics`, async () => {
      f.reset(); f.respond(async () => errorResponse(401))
      await assert.rejects(op.call(), { name: 'ApiError', status: 401 })
      await new Promise<void>((resolve) => setImmediate(resolve))
      assertWire(op); assertNoDownload(); assert.equal(f.api.getToken(), null); assert.equal(f.timers.size, 1)
      assert.deepEqual(f.toast.messages, [['Сессия истекла', { description: 'Войдите в систему снова' }]])
      f.location.pathname = '/objects'; f.location.search = '?report=export'; f.runTimers()
      assert.equal(f.location.href, '/login?next=%2Fobjects%3Freport%3Dexport')
    })
    await t.test(`${op.name}: network failure rejects without a fake file`, async () => {
      f.reset(); const error = new TypeError('fetch failed'); f.respond(async () => { throw error })
      await assert.rejects(op.call(), (actual: unknown) => actual === error)
      assertWire(op); assertNoDownload()
    })
    for (const phase of ['before', 'fetch', 'blob']) await t.test(`${op.name}: abort ${phase}`, async () => {
      f.reset(); const controller = new AbortController(), entered = deferred<void>(), released = deferred<void>()
      f.respond(async () => {
        if (phase === 'fetch') { entered.resolve(); await released.promise }
        const response = new Response(bytes)
        response.blob = async () => { entered.resolve(); await released.promise; return new Blob([bytes]) }
        return response
      })
      if (phase === 'before') controller.abort()
      const failed = assert.rejects(op.call(controller.signal), { name: 'AbortError' })
      if (phase !== 'before') { await entered.promise; controller.abort(); released.resolve() }
      await failed
      if (phase === 'before') assert.equal(f.calls.length, 0); else assertWire(op, controller.signal)
      assertNoDownload(); assert.equal(f.timers.size, 0)
    })
    const changes = {
      company: () => f.api.setApiCompany('company-B'), session: () => f.api.setToken('synthetic-B'),
      organization: () => f.api.setApiOrganization('org-B'),
      'company A-B-A': () => { f.api.setApiCompany('company-B'); f.api.setApiCompany('company-A') },
      'organization A-B-A': () => { f.api.setApiOrganization('org-B'); f.api.setApiOrganization('org-A') },
      'new login same token': () => f.api.setToken('synthetic-A'),
      'external token': () => f.local.setItem('clearledger-token', 'synthetic-external'),
    }
    for (const phase of ['fetch', 'blob', '401-json']) for (const [change, mutate] of Object.entries(changes)) {
      await t.test(`${op.name}: stale ${change} during ${phase} never clicks or expires current session`, async () => {
        f.reset(); const entered = deferred<void>(), released = deferred<void>()
        let bodies = 0
        f.respond(async () => {
          if (phase === 'fetch') { entered.resolve(); await released.promise }
          const response = phase === '401-json' ? errorResponse(401) : new Response(bytes)
          response.blob = async () => { bodies++; entered.resolve(); await released.promise; return new Blob([bytes]) }
          if (phase === '401-json') response.json = async () => { entered.resolve(); await released.promise; return { detail: 'expired old scope' } }
          return response
        })
        const failed = assert.rejects(op.call(), { name: 'AbortError' })
        await entered.promise; mutate(); const currentToken = f.api.getToken(); released.resolve(); await failed
        assertWire(op); assertNoDownload(); assert.equal(bodies, phase === 'blob' ? 1 : 0)
        assert.equal(f.api.getToken(), currentToken); assert.equal(f.timers.size, 0); assert.deepEqual(f.toast.messages, [])
      })
    }
    for (const [change, mutate] of Object.entries(changes)) await t.test(`${op.name}: stale ${change} at DOM append cleans up without click`, async () => {
      f.reset(); f.hook((event) => { if (event === 'append') mutate() })
      await assert.rejects(op.call(), { name: 'AbortError' }); assertWire(op)
      assert.deepEqual(f.events, ['url', 'create', 'append', 'remove', 'revoke'])
    })
    await t.test(`${op.name}: click failure still removes anchor and revokes URL`, async () => {
      f.reset(); const error = new Error('Synthetic DOM click failed')
      f.hook((event) => { if (event === 'click') throw error })
      await assert.rejects(op.call(), (actual: unknown) => actual === error); assertWire(op)
      assert.deepEqual(f.events, ['url', 'create', 'append', 'click', 'remove', 'revoke'])
    })
  }

  const variants = [
    { name: 'sessions empty optional filters', call: () => f.charge.exportChargeSessionsXlsx({ ...period, userType: '', client: '', stations: [], regions: [] }),
      path: '/api/charge-sessions/export', query: { company_id: 'company-A', date_from: period.dateFrom, date_to: period.dateTo }, filename: 'sessions_2026-10-01_2026-10-30.xlsx' },
    { name: 'pivot all period', call: () => f.charge.exportChargeSessionsPivotXlsx({ companyId: 'company-A', dateFrom: '', dateTo: '', stations: [], regions: [] }),
      path: '/api/charge-sessions/export/pivot', query: { company_id: 'company-A' }, filename: 'Сессии ЭЗС со сводной весь период.xlsx' },
    { name: 'pivot only from', call: () => f.charge.exportChargeSessionsPivotXlsx({ companyId: 'company-A', dateFrom: period.dateFrom }),
      path: '/api/charge-sessions/export/pivot', query: { company_id: 'company-A', date_from: period.dateFrom }, filename: 'Сессии ЭЗС со сводной весь период.xlsx' },
    { name: 'pivot only to', call: () => f.charge.exportChargeSessionsPivotXlsx({ companyId: 'company-A', dateTo: period.dateTo }),
      path: '/api/charge-sessions/export/pivot', query: { company_id: 'company-A', date_to: period.dateTo }, filename: 'Сессии ЭЗС со сводной весь период.xlsx' },
    { name: 'billing all clients / VAT absent', call: () => f.corporate.exportCorporateBillingUpd({ ...period, client: '', stations: [], regions: [] }),
      path: '/api/corporate/billing-export', query: { company_id: 'company-A', date_from: period.dateFrom, date_to: period.dateTo }, filename: 'billing_upd_all_2026-10-01_2026-10-30.xlsx' },
    { name: 'billing explicit VAT', call: () => f.corporate.exportCorporateBillingUpd({ ...period, vatRate: 20 }),
      path: '/api/corporate/billing-export', query: { company_id: 'company-A', date_from: period.dateFrom, date_to: period.dateTo, vat_rate: '20' }, filename: 'billing_upd_all_2026-10-01_2026-10-30.xlsx' },
    { name: 'sites two-argument caller', call: () => f.sites.exportXlsx('company-A', 'budget'),
      path: '/api/sites/export/budget', query: { company_id: 'company-A' }, filename: 'budget.xlsx' },
    { name: 'sites three-argument caller', call: () => f.sites.exportXlsx('company-A', 'matrix', 'custom.xlsx'),
      path: '/api/sites/export/matrix', query: { company_id: 'company-A' }, filename: 'custom.xlsx' },
    { name: 'sites four-argument caller', call: () => f.sites.exportXlsx('company-A', 'funnel', undefined, { phase: 'active', archived: false, limit: 0 }),
      path: '/api/sites/export/funnel', query: { company_id: 'company-A', phase: 'active', limit: '0' }, filename: 'funnel.xlsx' },
    { name: 'sites empty explicit filename preserved', call: () => f.sites.exportXlsx('company-A', 'equipment', ''),
      path: '/api/sites/export/equipment', query: { company_id: 'company-A' }, filename: '' },
    { name: 'portfolio wrapper', call: () => f.sites.exportPortfolioXlsx('company-A'),
      path: '/api/sites/export/portfolio', query: { company_id: 'company-A' }, filename: 'projects_portfolio.xlsx' },
  ]
  for (const variant of variants) await t.test(`legacy variants: ${variant.name}`, async () => {
    f.reset(); await variant.call(); assertWire(variant); assert.equal(f.filename(), variant.filename)
    assert.deepEqual(f.events, ['url', 'create', 'append', 'click', 'remove', 'revoke'])
  })
})
