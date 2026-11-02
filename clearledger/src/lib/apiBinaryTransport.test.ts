import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test, { mock } from 'node:test'
import { createServer } from 'vite'

// Existing apiSessionRedirect harness pattern: actual apiClient loaded by Vite SSR.
// Only fetch/storage/toast/timers/DOM boundaries are synthetic; no API, DB or VM.
const root = fileURLToPath(new URL('../../', import.meta.url))
const baseline = process.env.BINARY_API_BASELINE
const source = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/apiClient.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}
const json = (status: number, detail: unknown) => new Response(JSON.stringify({ detail }), {
  status, statusText: status === 401 ? 'Unauthorized' : 'Denied', headers: { 'Content-Type': 'application/json' },
})
async function fixture() {
  const keys = ['window', 'document', 'localStorage', 'sessionStorage', 'fetch']
  const originals = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const memory = () => {
    const data = new Map<string, string>()
    return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value),
      removeItem: (key: string) => data.delete(key) }
  }
  const local = memory(), session = memory()
  const location = { origin: 'https://core.example.test', pathname: '/protected', search: '', hash: '', href: '' }
  const events: string[] = []
  const attached = new Set<object>()
  let hook: ((event: string) => void) | undefined, captured: Blob | undefined, filename = ''
  const emit = (event: string) => { events.push(event); hook?.(event) }
  const document = { createElement(tag: string) {
    assert.equal(tag, 'a'); emit('create')
    return { href: '', set download(value: string) { filename = value },
      click() { assert.equal(this.href, 'blob:synthetic'); assert.equal(attached.has(this), true); emit('click') },
      remove() { attached.delete(this); emit('remove') } }
  }, body: { appendChild(anchor: object) { attached.add(anchor); emit('append') } } }
  for (const [key, value] of Object.entries({ window: { location }, document, localStorage: local,
    sessionStorage: session, fetch: async () => new Response(new Uint8Array([0, 255, 42])) })) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  }
  const createURL = mock.method(URL, 'createObjectURL', (blob: Blob) => { captured = blob; emit('url'); return 'blob:synthetic' })
  const revokeURL = mock.method(URL, 'revokeObjectURL', (url: string) => { assert.equal(url, 'blob:synthetic'); emit('revoke') })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/binary-transport-vite-${process.pid}`,
    plugins: [{ name: 'binary-toast-probe', transform(code, id) {
      if (id.endsWith('/src/services/apiClient.ts')) return code.replace(/import\((['"])sonner\1\)/, "import('virtual:binary-toast')")
    }, resolveId(id) { if (id === 'virtual:binary-toast') return '\0binary-toast' }, load(id) {
      if (source && id.endsWith('/src/services/apiClient.ts')) return source
      if (id === '\0binary-toast') return 'export const messages=[]; export const toast={error:(...args)=>messages.push(args)}'
    } }], resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': '"https://core.example.test"', 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const toast = await server.ssrLoadModule('\0binary-toast') as { messages: unknown[][] }
  const timers = new Map<object, () => void>()
  const setOriginal = globalThis.setTimeout, clearOriginal = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((fn: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return setOriginal(fn, delay, ...args)
    const id = {}; timers.set(id, fn); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!timers.delete(id)) clearOriginal(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  return { api, local, location, toast, timers, events, captured: () => captured, filename: () => filename,
    attachedCount: () => attached.size,
    hook(fn: typeof hook) { hook = fn }, reset() {
      assert.equal(attached.size, 0, 'Previous download must leave no attached anchor')
      hook = undefined; captured = undefined; filename = ''; events.length = 0
      api.setToken('synthetic-A'); api.setApiCompany('company-A'); api.setApiOrganization('org-A')
      location.pathname = '/protected'; location.href = ''; toast.messages.length = 0
    }, async close() {
      start.mock.restore(); stop.mock.restore(); createURL.mock.restore(); revokeURL.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    } }
}

test('binary actual transport: cancellation, context, HTTP errors, bytes and DOM lifecycle', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  const pattern = process.env.BINARY_CASE_PATTERN ? new RegExp(process.env.BINARY_CASE_PATTERN) : undefined
  const probe = (name: string, run: () => Promise<void>) => t.test(name, { skip: pattern ? !pattern.test(name) : false }, run)
  const calls = {
    blob: (signal?: AbortSignal) => f.api.downloadBlob('/api/export', signal ? { signal } : undefined),
    file: (signal?: AbortSignal) => f.api.downloadFile('/api/export', 'fallback.bin', signal ? { signal } : undefined),
  }
  for (const [kind, call] of Object.entries(calls)) {
    await probe(`${kind}: old signature, bytes and current header snapshot`, async () => {
      f.reset(); let sent = 0
      const request = mock.method(globalThis, 'fetch', (async (url, options) => {
        sent++; assert.equal(url, 'https://core.example.test/api/export')
        assert.deepEqual(options?.headers, { Authorization: 'Bearer synthetic-A', 'X-Company-Id': 'company-A', 'X-Organization-Id': 'org-A' })
        return new Response(new Uint8Array([0, 255, 42]))
      }) as typeof fetch)
      try {
        const result = await call(), blob = kind === 'blob' ? result as Blob : f.captured()!
        assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], [0, 255, 42]); assert.equal(sent, 1)
        assert.equal(f.filename(), kind === 'file' ? 'fallback.bin' : '')
      } finally { request.mock.restore() }
    })
    await probe(`${kind}: later request uses new session/company/org; identical scope setters keep it live`, async () => {
      f.reset(); f.api.setToken('synthetic-B'); f.api.setApiCompany('company-B'); f.api.setApiOrganization('org-B')
      const request = mock.method(globalThis, 'fetch', (async (_url, options) => {
        assert.deepEqual(options?.headers, { Authorization: 'Bearer synthetic-B', 'X-Company-Id': 'company-B', 'X-Organization-Id': 'org-B' })
        f.api.setApiCompany('company-B'); f.api.setApiOrganization('org-B')
        return new Response('current-B')
      }) as typeof fetch)
      try {
        const result = await call(), blob = kind === 'blob' ? result as Blob : f.captured()!
        assert.equal(await blob.text(), 'current-B')
      } finally { request.mock.restore() }
    })
    for (const phase of ['before-fetch', 'after-fetch', 'during-body', 'after-body']) await probe(`${kind}: abort ${phase}`, async () => {
      f.reset(); const controller = new AbortController(), entered = deferred<void>(), released = deferred<Response | Blob>()
      let requests = 0, bodies = 0
      const request = mock.method(globalThis, 'fetch', (async (_url, options) => {
        requests++; assert.equal(options?.signal, controller.signal)
        if (phase === 'after-fetch') { entered.resolve(); return released.promise }
        const res = new Response('bytes')
        res.blob = async () => {
          bodies++
          if (phase === 'after-body') {
            queueMicrotask(() => queueMicrotask(() => controller.abort()))
            return new Blob(['late'])
          }
          entered.resolve(); return released.promise as Promise<Blob>
        }; return res
      }) as typeof fetch)
      try {
        if (phase === 'before-fetch') controller.abort()
        const failed = assert.rejects(call(controller.signal), { name: 'AbortError' })
        if (phase !== 'before-fetch' && phase !== 'after-body') {
          await entered.promise; controller.abort(); released.resolve(phase === 'after-fetch' ? new Response('late') : new Blob(['late']))
        }
        await failed; assert.equal(requests, phase === 'before-fetch' ? 0 : 1)
        assert.equal(bodies, phase === 'during-body' || phase === 'after-body' ? 1 : 0); assert.deepEqual(f.events, [])
      } finally { request.mock.restore() }
    })
    const changes = {
      token: () => f.api.setToken('synthetic-B'), company: () => f.api.setApiCompany('company-B'), org: () => f.api.setApiOrganization('org-B'),
      'company A-B-A': () => { f.api.setApiCompany('company-B'); f.api.setApiCompany('company-A') },
      'org A-B-A': () => { f.api.setApiOrganization('org-B'); f.api.setApiOrganization('org-A') },
      'token A-B-A': () => { f.api.setToken('synthetic-B'); f.api.setToken('synthetic-A') },
      'clear-set same token': () => { f.api.clearToken(); f.api.setToken('synthetic-A') },
      'set same token': () => f.api.setToken('synthetic-A'),
      'external new token': () => f.local.setItem('clearledger-token', 'synthetic-external'),
    }
    for (const phase of ['fetch', 'blob']) for (const [name, change] of Object.entries(changes)) {
      await probe(`${kind}: ${name} during ${phase} discards bytes`, async () => {
        f.reset(); const entered = deferred<void>(), released = deferred<Response | Blob>(); let bodies = 0
        const request = mock.method(globalThis, 'fetch', (async () => {
          if (phase === 'fetch') { entered.resolve(); return released.promise }
          const res = new Response('bytes'); res.blob = async () => { bodies++; entered.resolve(); return released.promise as Promise<Blob> }; return res
        }) as typeof fetch)
        try {
          const failed = assert.rejects(call(), { name: 'AbortError' }); await entered.promise; change()
          released.resolve(phase === 'fetch' ? new Response('late') : new Blob(['late']))
          await failed; assert.equal(bodies, phase === 'blob' ? 1 : 0); assert.deepEqual(f.events, [])
        } finally { request.mock.restore() }
      })
    }
    const controller = new AbortController()
    for (const [name, change] of Object.entries({ ...changes, abort: () => controller.abort() })) {
      await probe(`${kind}: ${name} during 401 body preserves current session`, async () => {
        f.reset(); const entered = deferred<void>(), released = deferred<object>()
        const request = mock.method(globalThis, 'fetch', async () => {
          const res = json(401, 'expired'); res.json = async () => { entered.resolve(); return released.promise }; return res
        })
        try {
          const failed = assert.rejects(call(controller.signal), { name: 'AbortError' }); await entered.promise; change()
          const token = f.api.getToken(); released.resolve({ detail: 'expired' }); await failed
          await new Promise<void>((r) => setImmediate(r))
          assert.equal(f.api.getToken(), token); assert.equal(f.timers.size, 0); assert.deepEqual(f.toast.messages, []); assert.deepEqual(f.events, [])
        } finally { request.mock.restore() }
      })
    }
    await probe(`${kind}: anonymous late 401 cannot expire a new session`, async () => {
      f.reset(); f.api.clearToken(); const released = deferred<Response>()
      const request = mock.method(globalThis, 'fetch', (async (_url, options) => {
        assert.equal((options?.headers as Record<string, string>).Authorization, undefined)
        return released.promise
      }) as typeof fetch)
      try {
        const failed = assert.rejects(call(), { name: 'AbortError' })
        f.api.setToken('synthetic-B'); released.resolve(json(401, 'anonymous denied')); await failed
        assert.equal(f.api.getToken(), 'synthetic-B'); assert.equal(f.timers.size, 0); assert.deepEqual(f.toast.messages, [])
      } finally { request.mock.restore() }
    })
    for (const [pathname, isPublic] of [['/protected', false], ['/developer/authorize', false],
      ['/login', true], ['/space-guest', true], ['/invite/synthetic', true]] as const) {
      await probe(`${kind}: current 401 private/public ${pathname}`, async () => {
        f.reset(); f.location.pathname = pathname
        const request = mock.method(globalThis, 'fetch', async () => json(401, 'expired'))
        try {
          await assert.rejects(call(), { name: 'ApiError', status: 401, detail: 'expired' }); await new Promise<void>((r) => setImmediate(r))
          assert.equal(f.api.getToken(), isPublic ? 'synthetic-A' : null)
          assert.equal(f.toast.messages.length, isPublic ? 0 : 1); assert.equal(f.timers.size, isPublic ? 0 : 1)
          for (const [id, fn] of f.timers) { f.timers.delete(id); fn() }
          assert.equal(f.location.href, isPublic ? '' : `/login?next=${encodeURIComponent(pathname)}`); assert.deepEqual(f.events, [])
        } finally { request.mock.restore() }
      })
    }
    const errors = [
      { res: () => json(403, 'Specific reason'), expected: { status: 403, detail: 'Specific reason' } },
      { res: () => new Response('denied', { status: 403, statusText: 'Forbidden' }), expected: { status: 403, detail: 'Доступ запрещён. Проверьте права пользователя.' } },
      { res: () => json(422, [{ loc: ['body', 'name'], msg: 'required', type: 'missing' }]), expected: { name: 'ApiValidationError', status: 422, detail: 'body.name: required', fieldErrors: [{ loc: ['body', 'name'], msg: 'required', type: 'missing' }] } },
      { res: () => json(422, 'Invalid export'), expected: { name: 'ApiValidationError', status: 422, detail: 'Invalid export', fieldErrors: [] } },
      { res: () => new Response('proxy error', { status: 502, statusText: 'Bad Gateway' }), expected: { status: 502, detail: 'Bad Gateway' } },
    ]
    for (const [i, example] of errors.entries()) await probe(`${kind}: HTTP error ${i} never becomes file`, async () => {
      f.reset(); let bodies = 0
      const request = mock.method(globalThis, 'fetch', async () => {
        const res = example.res(); res.blob = async () => { bodies++; return new Blob(['wrong']) }; return res
      })
      try { await assert.rejects(call(), example.expected); assert.equal(bodies, 0); assert.deepEqual(f.events, []) }
      finally { request.mock.restore() }
    })
    await probe(`${kind}: network/body failure propagates without fallback`, async () => {
      for (const phase of ['fetch', 'body']) {
        f.reset(); const failure = new TypeError(`synthetic ${phase}`)
        const request = mock.method(globalThis, 'fetch', async () => {
          if (phase === 'fetch') throw failure
          const res = new Response('bytes'); res.blob = async () => { throw failure }; return res
        })
        try { await assert.rejects(call(), (e) => e === failure); assert.deepEqual(f.events, []) } finally { request.mock.restore() }
      }
    })
    await probe(`${kind}: demo explicitly rejects without fetch or fake Blob`, async () => {
      f.reset(); f.location.pathname = '/demo/shop'; let requests = 0
      const request = mock.method(globalThis, 'fetch', async () => { requests++; return new Response('wrong') })
      try { await assert.rejects(call(), { name: 'DemoReadOnlyError' }); assert.equal(requests, 0); assert.deepEqual(f.events, []) }
      finally { request.mock.restore(); f.location.pathname = '/protected' }
    })
  }
  for (const [disposition, expected] of [
    ["attachment; filename=\"ascii.xlsx\"; filename*=UTF-8''%D0%A0%D0%B5%D0%B5%D1%81%D1%82%D1%80.xlsx", 'Реестр.xlsx'],
    ['attachment; filename="ascii.xlsx"', 'ascii.xlsx'],
    ["attachment; filename*=UTF-8''%E0%A4%A; filename=\"safe.xlsx\"", 'safe.xlsx'],
    ["attachment; filename*=UTF-8''%ZZ", 'fallback.bin'], ['', 'fallback.bin'],
  ]) await probe(`filename ${disposition}`, async () => {
    f.reset(); const request = mock.method(globalThis, 'fetch', async () => new Response('bytes', { headers: { 'Content-Disposition': disposition } }))
    try {
      await calls.file(); assert.equal(f.filename(), expected)
      assert.deepEqual(f.events, ['url', 'create', 'append', 'click', 'remove', 'revoke'])
      assert.equal(f.attachedCount(), 0)
    } finally { request.mock.restore() }
  })
  for (const event of ['create', 'append', 'click', 'remove']) await probe(`cleanup when ${event} throws`, async () => {
    f.reset(); const failure = new Error(`synthetic ${event}`); f.hook((current) => { if (event === current) throw failure })
    await assert.rejects(calls.file(), (e) => e === failure)
    assert.equal(f.events.at(-1), 'revoke'); assert.equal(f.events.filter((item) => item === 'revoke').length, 1)
    assert.equal(f.events.includes('remove'), event !== 'create')
    assert.equal(f.attachedCount(), 0)
  })
  for (const event of ['url', 'create', 'append']) for (const change of ['abort', 'context']) {
    await probe(`guard before download effects: ${change} at ${event}`, async () => {
      f.reset(); const controller = new AbortController()
      f.hook((current) => { if (current === event) {
        if (change === 'abort') controller.abort(); else f.api.setApiCompany('company-B')
      } })
      await assert.rejects(calls.file(controller.signal), { name: 'AbortError' })
      assert.equal(f.events.includes('click'), false); assert.equal(f.events.at(-1), 'revoke')
      assert.equal(f.attachedCount(), 0)
    })
  }
})

test('unchanged JSON actual transport success/204/403/422/malformed contracts', async (t) => {
  const f = await fixture(); t.after(() => f.close()); f.reset()
  const calls = { get: () => f.api.get('/api/json'), post: () => f.api.post('/api/json', {}), put: () => f.api.put('/api/json', {}),
    patch: () => f.api.patch('/api/json', {}), delete: () => f.api.del('/api/json'), upload: () => f.api.upload('/api/json', new FormData()) }
  for (const [name, call] of Object.entries(calls)) await t.test(name, async () => {
    const examples = [
      { response: () => new Response('{"ok":true}', { headers: { 'Content-Type': 'application/json' } }), result: { ok: true } },
      { response: () => new Response(null, { status: 204 }), result: undefined },
      { response: () => new Response('bytes'), error: { status: 502, detail: 'Сервис вернул неожиданный ответ. Обновите страницу или повторите позже.' } },
      { response: () => new Response('{', { headers: { 'Content-Type': 'application/json' } }), error: { status: 502, detail: 'Сервис вернул повреждённые данные. Обновите страницу или повторите позже.' } },
      { response: () => json(403, 'JSON reason'), error: { status: 403, detail: 'JSON reason' } },
      { response: () => json(422, [{ loc: ['body', 'x'], msg: 'required', type: 'missing' }]), error: { name: 'ApiValidationError', status: 422, detail: 'body.x: required', fieldErrors: [{ loc: ['body', 'x'], msg: 'required', type: 'missing' }] } },
    ]
    for (const example of examples) {
      const request = mock.method(globalThis, 'fetch', async () => example.response())
      try { if (example.error) await assert.rejects(call(), example.error); else assert.deepEqual(await call(), example.result) }
      finally { request.mock.restore() }
    }
  })
})
