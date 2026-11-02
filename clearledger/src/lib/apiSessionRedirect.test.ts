import assert from 'node:assert/strict'
import test, { mock } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { execFileSync } from 'node:child_process'

const root = fileURLToPath(new URL('../../', import.meta.url))
// Необязательный regression proof: загрузить настоящий старый transport из Git,
// не подменяя и не меняя рабочий файл. Обычный прогон всегда проверяет этот worktree.
const baselineSource = process.env.CONSENT_API_BASELINE
  ? execFileSync('git', ['show', `${process.env.CONSENT_API_BASELINE}:clearledger/src/services/apiClient.ts`], { cwd: root, encoding: 'utf8' })
  : undefined

async function fixture(base = '/') {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch', 'XMLHttpRequest']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const memory = () => {
    const data = new Map<string, string>()
    return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value),
      removeItem: (key: string) => data.delete(key) }
  }
  const local = memory()
  const location = { origin: 'https://core.example.test', pathname: '/protected', search: '', hash: '', href: '' }
  Object.defineProperties(globalThis, {
    window: { configurable: true, value: { location } },
    localStorage: { configurable: true, value: local }, sessionStorage: { configurable: true, value: memory() },
    fetch: { configurable: true, writable: true, value: async () => new Response(JSON.stringify({ detail: 'Expired fixture' }), {
      status: 401, headers: { 'Content-Type': 'application/json' },
    }) },
  })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/api-session-redirect-vite-${process.pid}`,
    plugins: [{ name: 'session-toast-probe', transform(code, id) {
      if (id.endsWith('/src/services/apiClient.ts')) return code.replace(/import\((['"])sonner\1\)/, "import('virtual:session-toast')")
    }, resolveId(id) { if (id === 'virtual:session-toast') return '\0session-toast' },
    load(id) {
      if (baselineSource && id.endsWith('/src/services/apiClient.ts')) return baselineSource
      if (id === '\0session-toast') return 'export const messages=[]; export const toast={error:(...args)=>messages.push(args)}'
    } }],
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': '"https://core.example.test"', 'import.meta.env.BASE_URL': JSON.stringify(base) },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const toast = await server.ssrLoadModule('\0session-toast') as { messages: unknown[][] }
  const timers = new Map<object, () => void>()
  const originalSetTimeout = globalThis.setTimeout
  const originalClearTimeout = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((fn: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSetTimeout(fn, delay, ...args)
    const id = {}; timers.set(id, fn); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!timers.delete(id)) originalClearTimeout(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  return { api, local, location, timers, toast,
    async expired() { await assert.rejects(api.get('/api/protected'), { status: 401 }); await new Promise<void>((resolve) => setImmediate(resolve)) },
    runTimers() { for (const [id, fn] of timers) { timers.delete(id); fn() } },
    async close() {
      start.mock.restore(); stop.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('общий 401 redirect: intent, новая сессия и прежняя индикация', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  t.beforeEach(() => { f.api.setToken('synthetic-expired'); f.location.pathname = '/protected';
    f.location.search = ''; f.location.hash = ''; f.location.href = ''; f.toast.messages.length = 0 })

  await t.test('достигнутый login с safe next не перезаписывается старым таймером', async () => {
    await f.expired()
    assert.equal(f.api.getToken(), null)
    assert.equal(f.timers.size, 1)
    assert.deepEqual(f.toast.messages, [['Сессия истекла', { description: 'Войдите в систему снова' }]])
    f.location.pathname = '/login'; f.location.search = '?next=%2Fdeveloper%2Fauthorize%3FrequestId%3Dopaque'
    f.runTimers()
    assert.equal(f.location.href, '')
    assert.equal(f.location.search, '?next=%2Fdeveloper%2Fauthorize%3FrequestId%3Dopaque')
  })

  await t.test('setToken при новом входе отменяет pending redirect и снимает guard', async () => {
    await f.expired()
    f.api.setToken('synthetic-new-principal')
    assert.equal(f.timers.size, 0)
    f.runTimers()
    assert.equal(f.api.getToken(), 'synthetic-new-principal')
    assert.equal(f.location.href, '')
    await f.expired()
    assert.equal(f.timers.size, 1)
  })

  await t.test('новая сессия из другой вкладки не удаляется старым таймером', async () => {
    await f.expired()
    f.local.setItem('clearledger-token', 'synthetic-other-tab')
    f.runTimers()
    assert.equal(f.api.getToken(), 'synthetic-other-tab')
    assert.equal(f.location.href, '')
  })

  await t.test('несколько 401 дают одно уведомление и один таймер', async () => {
    await Promise.all([f.expired(), f.expired()])
    assert.equal(f.timers.size, 1)
    assert.equal(f.toast.messages.length, 1)
  })

  await t.test('защищённый текущий путь возвращается только через внутренний safe next', async () => {
    await f.expired()
    f.location.pathname = '/objects'; f.location.search = '?q=test'; f.location.hash = '#details'
    f.runTimers()
    assert.equal(f.location.href, '/login?next=%2Fobjects%3Fq%3Dtest%23details')
    f.api.setToken('synthetic-expired-again'); f.location.href = ''; f.location.pathname = '//evil.example.test'
    f.location.search = ''; f.location.hash = ''; await f.expired(); f.runTimers()
    assert.equal(f.location.href, '/login?next=%2F')
  })
})

test('401 redirect учитывает basename и не добавляет его во внутренний next', async (t) => {
  const f = await fixture('/space/'); t.after(() => f.close())
  f.api.setToken('synthetic-expired'); f.location.pathname = '/space/developer/authorize'
  f.location.search = '?requestId=opaque'; await f.expired(); f.runTimers()
  assert.equal(f.location.href, '/space/login?next=%2Fdeveloper%2Fauthorize%3FrequestId%3Dopaque')
})

test('поздний 401 всех fetch transport сохраняет новую сессию после чтения body', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  const transports = {
    GET: () => f.api.get('/api/protected'),
    POST: () => f.api.post('/api/protected', {}),
    PATCH: () => f.api.patch('/api/protected', {}),
    PUT: () => f.api.put('/api/protected', {}),
    DELETE: () => f.api.del('/api/protected'),
    'upload fetch': () => f.api.upload('/api/protected', new FormData()),
  }
  for (const [name, call] of Object.entries(transports)) {
    await t.test(name, async () => {
      f.api.setToken('synthetic-A'); f.location.pathname = '/protected'; f.toast.messages.length = 0
      let releaseBody!: (body: object) => void
      let enterBody!: () => void
      const entered = new Promise<void>((resolve) => { enterBody = resolve })
      const body = new Promise<object>((resolve) => { releaseBody = resolve })
      const request = mock.method(globalThis, 'fetch', (async (_url, options) => {
        assert.equal((options?.headers as Record<string, string>).Authorization, 'Bearer synthetic-A')
        const response = new Response('{}', { status: 401, headers: { 'Content-Type': 'application/json' } })
        response.json = async () => { enterBody(); return body }
        return response
      }) as typeof fetch)
      try {
        const failed = assert.rejects(call(), { status: 401 })
        await entered
        f.api.setToken('synthetic-B')
        releaseBody({ detail: 'Synthetic A expired' })
        await failed
        assert.equal(f.api.getToken(), 'synthetic-B')
        assert.equal(f.timers.size, 0)
        assert.equal(f.toast.messages.length, 0)
      } finally { request.mock.restore() }
    })
  }
})

test('анонимный поздний 401 не удаляет новую Core сессию', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  f.api.clearToken(); f.location.pathname = '/protected'
  let release!: (response: Response) => void
  const request = mock.method(globalThis, 'fetch', (async (_url, options) => {
    assert.equal((options?.headers as Record<string, string>).Authorization, undefined)
    return new Promise<Response>((resolve) => { release = resolve })
  }) as typeof fetch)
  try {
    const failed = assert.rejects(f.api.get('/api/protected'), { status: 401 })
    f.api.setToken('synthetic-B')
    release(new Response('{"detail":"Synthetic anonymous denial"}', { status: 401 }))
    await failed
    assert.equal(f.api.getToken(), 'synthetic-B')
    assert.equal(f.timers.size, 0)
    assert.equal(f.toast.messages.length, 0)
  } finally { request.mock.restore() }
})

test('abort при чтении 401 body не завершает действующую сессию', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  f.api.setToken('synthetic-A'); f.location.pathname = '/protected'
  const controller = new AbortController()
  let releaseBody!: (body: object) => void
  let enterBody!: () => void
  const entered = new Promise<void>((resolve) => { enterBody = resolve })
  const body = new Promise<object>((resolve) => { releaseBody = resolve })
  const request = mock.method(globalThis, 'fetch', (async () => {
    const response = new Response('{}', { status: 401 })
    response.json = async () => { enterBody(); return body }
    return response
  }) as typeof fetch)
  try {
    const failed = assert.rejects(f.api.get('/api/protected', undefined, { signal: controller.signal }), { status: 401 })
    await entered
    controller.abort()
    releaseBody({ detail: 'Synthetic canceled response' })
    await failed
    assert.equal(f.api.getToken(), 'synthetic-A')
    assert.equal(f.timers.size, 0)
    assert.equal(f.toast.messages.length, 0)
  } finally { request.mock.restore() }
})

test('XHR upload401 относится к отправленному Bearer, текущий401 остаётся logout', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  let active!: SyntheticXHR
  class SyntheticXHR {
    upload: { onprogress?: (event: ProgressEvent) => void } = {}
    onload?: () => void
    onerror?: () => void
    ontimeout?: () => void
    response = '{"detail":"Synthetic XHR expired"}'
    status = 401
    statusText = 'Unauthorized'
    sent: Record<string, string> = {}
    constructor() { active = this }
    open() {}
    setRequestHeader(key: string, value: string) { this.sent[key] = value }
    getResponseHeader() { return 'application/json' }
    send() {}
  }
  Object.defineProperty(globalThis, 'XMLHttpRequest', { configurable: true, value: SyntheticXHR })
  f.location.pathname = '/protected'
  for (const replace of [true, false]) {
    f.api.setToken('synthetic-A'); f.toast.messages.length = 0
    const failed = assert.rejects(f.api.upload('/api/protected', new FormData(), () => {}), { status: 401 })
    assert.equal(active.sent.Authorization, 'Bearer synthetic-A')
    if (replace) f.api.setToken('synthetic-B')
    active.onload!()
    await failed
    await new Promise<void>((resolve) => setImmediate(resolve))
    assert.equal(f.api.getToken(), replace ? 'synthetic-B' : null)
    assert.equal(f.timers.size, replace ? 0 : 1)
    assert.equal(f.toast.messages.length, replace ? 0 : 1)
  }
})
