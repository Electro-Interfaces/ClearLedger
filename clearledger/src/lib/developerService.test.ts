import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { safeBackTo } from './safeBackTo.ts'

const root = fileURLToPath(new URL('../../', import.meta.url))
const makeRequest = () => ({ id: 'request:opaque/id', clientName: 'Тестовое приложение',
  requestedScopes: [{ code: 'openid', description: 'Подтверждать личность' }, { code: 'objects:read', description: 'Читать объекты' }],
  companies: [{ id: 'opaque-A', name: 'Компания А', eligibleScopes: ['openid', 'objects:read', 'not-requested'] },
    { id: 'opaque-B', name: 'Компания Б', eligibleScopes: ['openid'] }],
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
})
const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })

async function fixture(apiUrl = 'https://core.example.test') {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch']
    .map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]))
  const storage = () => {
    const values = new Map<string, string>()
    return { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  }
  const local = storage()
  local.setItem('clearledger-token', 'synthetic-core-session')
  const window = { location: { origin: 'https://ui.example.test', pathname: '/', search: '' } }
  const calls: { url: string; options?: RequestInit }[] = []
  let respond = async () => response(makeRequest())
  Object.defineProperties(globalThis, {
    window: { configurable: true, value: window },
    localStorage: { configurable: true, value: local },
    sessionStorage: { configurable: true, value: storage() },
    fetch: { configurable: true, writable: true, value: async (url: string, options?: RequestInit) => {
      calls.push({ url: String(url), options }); return respond()
    } },
  })
  const server = await createServer({ root, configFile: false, envFile: false, logLevel: 'silent', appType: 'custom',
    cacheDir: `/tmp/developer-service-vite-${process.pid}`,
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(apiUrl) },
    server: { middlewareMode: true, hmr: false, watch: null },
  })
  const service = await server.ssrLoadModule('/src/services/developerService.ts') as typeof import('../services/developerService.ts')
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  return { service, api, calls, local, window,
    respond: (fn: typeof respond) => { respond = fn },
    async close() {
      await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('developerService: consent contract через существующий transport', async (t) => {
  const f = await fixture()
  t.after(() => f.close())
  t.beforeEach(() => { f.calls.length = 0; f.window.location.pathname = '/'; f.api.setToken('synthetic-core-session') })

  await t.test('requestId opaque; только один внутренний intent, query redirect игнорируется', () => {
    const id = 'req:/opaque ?#ю'
    assert.equal(f.service.authorizationRequestId(`?requestId=${encodeURIComponent(id)}&redirectUrl=javascript:alert(1)`), id)
    for (const search of ['', '?requestId=', '?requestId=x&requestId=y', '?requestId=%00x', `?requestId=${'x'.repeat(1025)}`]) {
      assert.equal(f.service.authorizationRequestId(search), null)
    }
    const target = `/developer/authorize?requestId=${encodeURIComponent(id)}`
    assert.equal(safeBackTo(target), target)
    for (const value of ['https://evil.example.test', '//evil.example.test', '/\\evil.example.test']) assert.equal(safeBackTo(value), '/')
  })

  await t.test('GET не выдаёт согласие, кодирует ID и передаёт Core Bearer/signal только API', async () => {
    const controller = new AbortController()
    const request = makeRequest()
    f.respond(async () => response(request))
    assert.deepEqual(await f.service.getAuthorizationRequest(request.id, controller.signal), request)
    assert.equal(f.calls.length, 1)
    assert.equal(new URL(f.calls[0].url).pathname, `/api/developer/authorization-requests/${encodeURIComponent(request.id)}`)
    assert.equal(f.calls[0].options?.signal, controller.signal)
    assert.equal((f.calls[0].options?.headers as Record<string, string>).Authorization, 'Bearer synthetic-core-session')
    assert.equal(f.calls[0].options?.method, undefined)
  })

  await t.test('выбор ограничен requested × eligible, без добавления неизвестных действий', async () => {
    const request = makeRequest()
    assert.deepEqual(f.service.eligibleAuthorizationScopes(request, 'opaque-B'), ['openid'])
    assert.deepEqual(f.service.eligibleAuthorizationScopes(request, 'unknown'), [])
    for (const [company, scopes] of [['unknown', ['openid']], ['opaque-A', []], ['opaque-A', ['objects:read']],
      ['opaque-B', ['openid', 'objects:read']], ['opaque-A', ['openid', 'not-requested']], ['opaque-A', ['openid', 'openid']]] as const) {
      await assert.rejects(f.service.approveAuthorizationRequest(request, company, [...scopes]), { kind: 'invalid' })
    }
    assert.equal(f.calls.length, 0)
    f.respond(async () => response({ redirectUrl: 'https://client.example.test/callback?state=synthetic' }))
    assert.equal(await f.service.approveAuthorizationRequest(request, 'opaque-A', ['openid', 'objects:read']),
      'https://client.example.test/callback?state=synthetic')
    assert.deepEqual(JSON.parse(f.calls[0].options?.body as string), { companyId: 'opaque-A', scopes: ['openid', 'objects:read'] })
    assert.equal(f.calls[0].options?.method, 'POST')
  })

  await t.test('отказ не требует компании и не подставляет фиктивный результат', async () => {
    f.respond(async () => response({ redirectUrl: 'https://client.example.test/callback?error=access_denied' }))
    assert.match(await f.service.denyAuthorizationRequest('opaque-id'), /error=access_denied/)
    assert.equal(f.calls[0].url, 'https://core.example.test/api/developer/authorization-requests/opaque-id/deny')
    assert.equal(f.calls[0].options?.body, undefined)
  })

  await t.test('expired и некорректный ответ не становятся успешным пустым consent', async () => {
    const request = { ...makeRequest(), expiresAt: new Date(Date.now() - 1000).toISOString() }
    await assert.rejects(f.service.approveAuthorizationRequest(request, 'opaque-A', ['openid']), { kind: 'expired' })
    assert.equal(f.calls.length, 0)
    for (const body of [{}, null, { ...request, id: 'other' }, { ...request, expiresAt: 'bad' },
      { ...request, companies: [{ id: 'x', name: 'x', eligibleScopes: [42] }] }]) {
      f.respond(async () => response(body))
      await assert.rejects(f.service.getAuthorizationRequest(request.id), { kind: 'unavailable' })
    }
  })

  await t.test('ошибки backend отображаются по согласованным статусам, без mock fallback', async () => {
    for (const [status, kind] of [[401, 'unauthenticated'], [403, 'forbidden'], [404, 'not_found'],
      [409, 'consumed'], [410, 'expired'], [422, 'invalid'], [503, 'unavailable']] as const) {
      assert.equal(f.service.authorizationProblem(new f.api.ApiError(status, 'detail')), kind)
    }
    f.respond(async () => new Response(JSON.stringify({ detail: 'Feature disabled', code: 'PARTNER_API_DISABLED' }), {
      status: 503, headers: { 'Content-Type': 'application/json' },
    }))
    await assert.rejects(f.service.getAuthorizationRequest(makeRequest().id), { status: 503 })
    assert.equal(f.calls.length, 1)
  })

  await t.test('callback: HTTPS; loopback HTTP только dev, unsafe schemes/credentials отвергаются', () => {
    for (const value of ['https://client.example.test/callback', 'https://localhost/cb']) {
      assert.equal(f.service.authorizationRedirectUrl(value, false), value)
    }
    for (const value of ['http://localhost:8123/cb', 'http://127.0.0.1:8123/cb', 'http://[::1]:8123/cb']) {
      assert.equal(f.service.authorizationRedirectUrl(value, true), value)
      assert.throws(() => f.service.authorizationRedirectUrl(value, false), { kind: 'redirect' })
    }
    for (const value of ['javascript:alert(1)', 'data:text/html,hi', '//client.example.test', '/callback',
      'http://client.example.test/cb', 'http://localhost.evil.test/cb', 'https://u:p@client.example.test/cb',
      'https://client.example.test/\ncb', ' https://client.example.test/cb', 'https:\\evil.test', undefined]) {
      assert.throws(() => f.service.authorizationRedirectUrl(value, true), { kind: 'redirect' })
    }
  })

  await t.test('demo и отсутствие реальной сессии запрещены до любого GET/POST', async () => {
    f.window.location.pathname = '/demo/shop'
    await assert.rejects(f.service.getAuthorizationRequest('req'), { kind: 'unavailable' })
    await assert.rejects(f.service.approveAuthorizationRequest(makeRequest(), 'opaque-A', ['openid']), { kind: 'unavailable' })
    await assert.rejects(f.service.denyAuthorizationRequest('req'), { kind: 'unavailable' })
    f.window.location.pathname = '/'; f.api.clearToken()
    await assert.rejects(f.service.getAuthorizationRequest('req'), { kind: 'unauthenticated' })
    await assert.rejects(f.service.denyAuthorizationRequest('req'), { kind: 'unauthenticated' })
    assert.equal(f.calls.length, 0)
  })
})

test('developerService: без API configuration нельзя включить offline consent', async (t) => {
  const f = await fixture('')
  t.after(() => f.close())
  await assert.rejects(f.service.getAuthorizationRequest('req'), { kind: 'unavailable' })
  await assert.rejects(f.service.denyAuthorizationRequest('req'), { kind: 'unavailable' })
  assert.equal(f.calls.length, 0)
})
