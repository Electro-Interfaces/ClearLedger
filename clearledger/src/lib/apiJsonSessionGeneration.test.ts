import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test, { mock } from 'node:test'
import { createServer } from 'vite'
import { toast } from 'sonner'

// Actual apiClient + actual sonner, following the existing Vite SSR harness.
// No env files, listener, HTTP, auth service substitution or runtime transforms.
const root = fileURLToPath(new URL('../../', import.meta.url))
const baseline = process.env.JSON_SESSION_BASELINE
const source = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/apiClient.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const deferred = <T>() => {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const tick = () => new Promise<void>((done) => setImmediate(done))
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, statusText: status === 401 ? 'Unauthorized' : 'Synthetic status',
  headers: { 'Content-Type': 'application/json' },
})

async function fixture() {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch', 'XMLHttpRequest']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const storage = () => {
    const values = new Map<string, string>()
    return { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  }
  const local = storage(), session = storage()
  const location = { origin: 'https://core.example.test', pathname: '/protected', search: '?q=synthetic', hash: '#part', href: '' }
  const requests: { method: string; headers: Record<string, string>; body: unknown }[] = []
  let reply: () => Promise<Response> = async () => json({ detail: 'old session expired' }, 401)
  const xhrs: SyntheticXHR[] = []
  class SyntheticXHR {
    upload: { onprogress?: (event: ProgressEvent) => void } = {}
    onload?: () => void
    onerror?: () => void
    ontimeout?: () => void
    response = '{"detail":"old session expired"}'
    status = 401
    statusText = 'Unauthorized'
    sent: Record<string, string> = {}
    withCredentials = false
    open(method: string, url: string) { assert.equal(method, 'POST'); assert.equal(url, `${location.origin}/api/synthetic`) }
    setRequestHeader(key: string, value: string) { this.sent[key] = value }
    getResponseHeader() { return 'application/json' }
    send(body: unknown) { xhrs.push(this); requests.push({ method: 'POST', headers: this.sent, body }) }
  }
  for (const [key, value] of Object.entries({ window: { location }, localStorage: local, sessionStorage: session,
    XMLHttpRequest: SyntheticXHR, fetch: async (url: string, init?: RequestInit) => {
      assert.equal(url, `${location.origin}/api/synthetic`)
      requests.push({ method: init?.method ?? 'GET', headers: init?.headers as Record<string, string>, body: init?.body })
      return reply()
    },
  })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/json-session-generation-vite-${process.pid}`,
    plugins: source ? [{ name: 'immutable-json-session-baseline', load(id) {
      if (id.endsWith('/src/services/apiClient.ts')) return source
    } }] : [],
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(location.origin), 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const timers = new Map<object, () => void>()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((callback: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSet(callback, delay, ...args)
    const id = {}; timers.set(id, callback); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!timers.delete(id)) originalClear(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  let toastStart = toast.getHistory().length
  return { api, local, session, location, requests, timers,
    xhr: () => xhrs.at(-1)!,
    respond(fn: typeof reply) { reply = fn },
    reset() {
      api.setToken('synthetic-A'); api.setApiCompany('company-A'); api.setApiOrganization('org-A')
      location.pathname = '/protected'; location.href = ''; requests.length = 0; xhrs.length = 0
      toastStart = toast.getHistory().length
    },
    effects() { return { token: api.getToken(), timers: timers.size,
      messages: toast.getHistory().slice(toastStart).map((item) => item.title), href: location.href } },
    runTimers() { for (const [id, fn] of timers) { timers.delete(id); fn() } },
    async close() {
      timers.clear(); start.mock.restore(); stop.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('JSON session generation: late 401 side effects and compatibility', { timeout: 45_000 }, async (t) => {
  const f = await fixture(); t.after(() => f.close())
  const calls = {
    GET: () => f.api.get('/api/synthetic'),
    POST: () => f.api.post('/api/synthetic', { synthetic: true }),
    PATCH: () => f.api.patch('/api/synthetic', { synthetic: true }),
    PUT: () => f.api.put('/api/synthetic', { synthetic: true }),
    DELETE: () => f.api.del('/api/synthetic'),
    'upload fetch': () => f.api.upload('/api/synthetic', new FormData()),
    'upload XHR': () => f.api.upload('/api/synthetic', new FormData(), () => {}),
  }
  const transitions = {
    'set same token': () => f.api.setToken('synthetic-A'),
    'token A-B-A': () => { f.api.setToken('synthetic-B'); f.api.setToken('synthetic-A') },
    'clear-set same token': () => { f.api.clearToken(); f.api.setToken('synthetic-A') },
  }
  const quiet = (token: string | null = 'synthetic-A') => ({ token, timers: 0, messages: [], href: '' })
  const probe = (name: string, run: () => Promise<void>) => t.test(name, { timeout: 8_000 }, run)

  // Every path includes the two independent awaits: fetch/XHR response, then error body.
  // The rejection is observed before checking effects: stale ordinary JSON stays ApiError401.
  for (const [method, call] of Object.entries(calls)) {
    for (const phase of ['response', 'error body']) for (const [change, transition] of Object.entries(transitions)) {
      await probe(`regression: ${method}, ${change} during ${phase}`, async () => {
        f.reset()
        const entered = deferred<void>(), body = deferred<object>(), response = deferred<Response>()
        const read = mock.method(Response.prototype, 'json', async () => { entered.resolve(); return body.promise })
        f.respond(() => response.promise)
        try {
          const failed = assert.rejects(call(), { name: 'ApiError', status: 401, detail: 'old session expired' })
          assert.equal(f.requests.length, 1)
          assert.deepEqual(f.requests[0].headers, { ...(method === 'POST' || method === 'PATCH' || method === 'PUT'
            ? { 'Content-Type': 'application/json' } : {}),
          Authorization: 'Bearer synthetic-A', 'X-Company-Id': 'company-A', 'X-Organization-Id': 'org-A' })
          if (phase === 'response') transition()
          if (method === 'upload XHR') f.xhr().onload!()
          else response.resolve(json({}, 401))
          await entered.promise
          if (phase === 'error body') transition()
          body.resolve({ detail: 'old session expired' }); await failed; await tick()
          assert.deepEqual(f.effects(), quiet(), 'old 401 must not clear the new session, toast or schedule redirect')
        } finally { read.mock.restore() }
      })
    }
    await probe(`control: ${method} current 401 keeps logout, exact error, toast and safe redirect`, async () => {
      f.reset(); f.respond(async () => json({ detail: 'old session expired' }, 401))
      const failed = assert.rejects(call(), { name: 'ApiError', status: 401, detail: 'old session expired' })
      if (method === 'upload XHR') f.xhr().onload!()
      await failed; await tick()
      assert.deepEqual(f.effects(), { token: null, timers: 1, messages: ['Сессия истекла'], href: '' })
      f.runTimers(); assert.equal(f.location.href, '/login?next=%2Fprotected%3Fq%3Dsynthetic%23part')
    })
  }

  const scopeTransitions = {
    'company changed': () => f.api.setApiCompany('company-B'),
    'organization changed': () => f.api.setApiOrganization('org-B'),
    'company A-B-A': () => { f.api.setApiCompany('company-B'); f.api.setApiCompany('company-A') },
    'organization A-B-A': () => { f.api.setApiOrganization('org-B'); f.api.setApiOrganization('org-A') },
    'identical scope setters': () => { f.api.setApiCompany('company-A'); f.api.setApiOrganization('org-A') },
  }
  for (const [name, change] of Object.entries(scopeTransitions)) {
    await probe(`control: ${name} is not a new user session for ordinary JSON 401`, async () => {
      f.reset(); const entered = deferred<void>(), body = deferred<object>()
      f.respond(async () => { const res = json({}, 401); res.json = async () => { entered.resolve(); return body.promise }; return res })
      const failed = assert.rejects(f.api.get('/api/synthetic'), { name: 'ApiError', status: 401 })
      await entered.promise; change(); body.resolve({ detail: 'expired' }); await failed; await tick()
      assert.deepEqual(f.effects(), { token: null, timers: 1, messages: ['Сессия истекла'], href: '' })
    })
  }
  for (const pathname of ['/login', '/invite/synthetic', '/space-guest']) {
    await probe(`control: current 401 on public page ${pathname}`, async () => {
      f.reset(); f.location.pathname = pathname; f.respond(async () => json({}, 401))
      await assert.rejects(f.api.get('/api/synthetic'), { name: 'ApiError', status: 401 }); await tick()
      assert.deepEqual(f.effects(), quiet())
    })
  }
  for (const [name, change, token] of [
    ['different setter token', () => f.api.setToken('synthetic-B'), 'synthetic-B'],
    ['direct storage different token', () => f.local.setItem('clearledger-token', 'synthetic-B'), 'synthetic-B'],
    ['logout', () => f.api.clearToken(), null],
  ] as const) {
    await probe(`control: ${name} during body retains existing string-token protection`, async () => {
      f.reset(); const entered = deferred<void>(), body = deferred<object>()
      f.respond(async () => { const res = json({}, 401); res.json = async () => { entered.resolve(); return body.promise }; return res })
      const failed = assert.rejects(f.api.get('/api/synthetic'), { status: 401 })
      await entered.promise; change(); body.resolve({ detail: 'expired' }); await failed; await tick()
      assert.deepEqual(f.effects(), quiet(token))
    })
  }
  await probe('control: parallel current 401 produces one logout and subsequent new session can expire', async () => {
    f.reset(); f.respond(async () => json({ detail: 'expired' }, 401))
    await Promise.all([assert.rejects(f.api.get('/api/synthetic'), { status: 401 }),
      assert.rejects(f.api.post('/api/synthetic'), { status: 401 })]); await tick()
    assert.deepEqual(f.effects(), { token: null, timers: 1, messages: ['Сессия истекла'], href: '' })
    f.api.setToken('synthetic-A'); assert.equal(f.timers.size, 0)
    await assert.rejects(f.api.get('/api/synthetic'), { status: 401 }); await tick()
    assert.equal(f.timers.size, 1); assert.equal(f.effects().messages.length, 2)
  })
  for (const malformed of [false, true]) {
    await probe(`regression: same-token login while 401 body ${malformed ? 'rejects' : 'resolves'}`, async () => {
      f.reset(); const entered = deferred<void>(), body = deferred<object>()
      f.respond(async () => { const res = json({}, 401); res.json = async () => { entered.resolve(); return body.promise }; return res })
      const failed = assert.rejects(f.api.get('/api/synthetic'), { status: 401,
        detail: malformed ? 'Unauthorized' : 'expired' })
      await entered.promise; f.api.setToken('synthetic-A')
      if (malformed) body.reject(new SyntaxError('synthetic invalid json')); else body.resolve({ detail: 'expired' })
      await failed; await tick(); assert.deepEqual(f.effects(), quiet())
    })
  }
  await probe('control: explicit abort during deferred 401 body preserves ApiError and session', async () => {
    f.reset(); const controller = new AbortController(), entered = deferred<void>(), body = deferred<object>()
    f.respond(async () => { const res = json({}, 401); res.json = async () => { entered.resolve(); return body.promise }; return res })
    const failed = assert.rejects(f.api.get('/api/synthetic', undefined, { signal: controller.signal }), { name: 'ApiError', status: 401 })
    await entered.promise; controller.abort(); body.resolve({ detail: 'expired' }); await failed; await tick()
    assert.deepEqual(f.effects(), quiet())
  })
  for (const [method, call] of Object.entries(calls)) {
    if (method === 'upload XHR') continue
    for (const error of [new TypeError('fetch synthetic failed'), new DOMException('synthetic abort', 'AbortError')]) {
      await probe(`control: ${method} network ${error.name} keeps identity after same-token login`, async () => {
        f.reset(); const pending = deferred<Response>(); f.respond(() => pending.promise)
        const failed = assert.rejects(call(), (actual) => actual === error)
        f.api.setToken('synthetic-A'); pending.reject(error); await failed; assert.deepEqual(f.effects(), quiet())
      })
    }
    await probe(`control: ${method} successful deferred JSON survives session change`, async () => {
      f.reset(); const entered = deferred<void>(), body = deferred<object>(), value = { synthetic: 'success A' }
      f.respond(async () => { const res = json({}); res.json = async () => { entered.resolve(); return body.promise }; return res })
      const result = call(); await entered.promise; f.api.setToken('synthetic-B'); body.resolve(value)
      assert.deepEqual(await result, value); assert.deepEqual(f.effects(), quiet('synthetic-B'))
    })
  }
  for (const change of ['session', 'scope', 'network', 'current401']) {
    await probe(`control: opt-in conf POST guard retains ${change} contract`, async () => {
      f.reset(); const entered = deferred<void>(), body = deferred<object>(), response = deferred<Response>()
      const contextGuard = f.api.captureApiContextGuard()
      f.respond(() => response.promise)
      const failed = assert.rejects(f.api.post('/api/synthetic', undefined, { contextGuard }),
        change === 'current401' ? { name: 'ApiError', status: 401 } : { name: 'AbortError' })
      if (change === 'network') {
        f.api.setToken('synthetic-A'); response.reject(new TypeError('fetch synthetic failed'))
      } else {
        const res = json({}, 401); res.json = async () => { entered.resolve(); return body.promise }
        response.resolve(res); await entered.promise
        if (change === 'session') f.api.setToken('synthetic-A')
        if (change === 'scope') { f.api.setApiCompany('company-B'); f.api.setApiCompany('company-A') }
        body.resolve({ detail: 'expired' })
      }
      await failed; await tick()
      assert.deepEqual(f.effects(), change === 'current401'
        ? { token: null, timers: 1, messages: ['Сессия истекла'], href: '' } : quiet())
    })
  }
})
