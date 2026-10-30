import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test, { mock } from 'node:test'
import { createServer } from 'vite'

// Actual service + apiClient, following apiSessionRedirect.test.ts. No .env or real transport.
const root = fileURLToPath(new URL('../../', import.meta.url))
const apiBase = 'https://api.example.test'
const baseline = process.env.INTAKE_SERVICE_BASELINE
const baselineSource = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/intakeDocsService.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const bytes = new Uint8Array([0, 255, 42, 128, 13, 10])
const file = () => new File([bytes], 'Первичка 01.bin', { type: 'application/octet-stream' })
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

async function fixture() {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch', 'XMLHttpRequest']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const memory = () => {
    const data = new Map<string, string>()
    return { getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) }
  }
  const local = memory()
  const location = { origin: 'https://ui.example.test', pathname: '/books', search: '', hash: '', href: '' }
  const calls: { url: string; init?: RequestInit }[] = []
  let reply: () => Promise<Response> = async () => json({})
  for (const [key, value] of Object.entries({ window: { location }, localStorage: local, sessionStorage: memory(),
    fetch: async (url: string, init?: RequestInit) => { calls.push({ url: String(url), init }); return reply() },
  })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/intake-transport-vite-${process.pid}`,
    plugins: [{ name: 'intake-toast-probe', transform(code, id) {
      if (id.endsWith('/src/services/apiClient.ts')) return code.replace(/import\((['"])sonner\1\)/, "import('virtual:intake-toast')")
    }, resolveId(id) { if (id === 'virtual:intake-toast') return '\0intake-toast' }, load(id) {
      if (baselineSource && id.endsWith('/src/services/intakeDocsService.ts')) return baselineSource
      if (id === '\0intake-toast') return 'export const messages=[]; export const toast={error:(...args)=>messages.push(args)}'
    } }], resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(apiBase), 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const intake = await server.ssrLoadModule('/src/services/intakeDocsService.ts') as typeof import('../services/intakeDocsService.ts')
  const toast = await server.ssrLoadModule('\0intake-toast') as { messages: unknown[][] }
  const timers = new Map<object, () => void>()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((fn: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSet(fn, delay, ...args)
    const id = {}; timers.set(id, fn); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!timers.delete(id)) originalClear(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  return { api, intake, calls, location, toast, timers,
    respond(fn: typeof reply) { reply = fn },
    reset() {
      api.setToken('synthetic-A'); api.setApiCompany('company-A'); api.setApiOrganization('org-A')
      calls.length = 0; toast.messages.length = 0; location.href = ''
    },
    async close() {
      start.mock.restore(); stop.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('intake actual service: multipart, shared transport, errors and session lifecycle', async (t) => {
  const f = await fixture(); t.after(() => f.close())
  t.beforeEach(() => f.reset())
  const pattern = process.env.INTAKE_CASE_PATTERN ? new RegExp(process.env.INTAKE_CASE_PATTERN) : undefined
  const probe = (name: string, run: () => Promise<void>) => t.test(name, {
    skip: pattern ? !pattern.test(name) : false, timeout: 10_000,
  }, run)

  await probe('wire has exactly four fields, original file and current headers; accept remains explicit', async () => {
    const parsed = { batchId: 'batch-synthetic', columns: ['number'], items: [], error: 'Review required', extra: { kept: true } }
    for (const context of ['A', 'B']) {
      f.reset(); f.api.setToken(`synthetic-${context}`)
      f.api.setApiCompany(`company-${context}`); f.api.setApiOrganization(`org-${context}`)
      f.respond(async () => json(parsed))
      assert.deepEqual(await f.intake.uploadIntake(`company-${context}`, file(), 'invoice'), parsed)
      assert.equal(f.calls.length, 1, 'Parsing must neither retry nor accept documents')
      const { url, init } = f.calls[0]
      assert.equal(url, `${apiBase}/api/intake-docs/upload`)
      assert.equal(init?.method, 'POST')
      assert.equal(init?.credentials, 'include')
      assert.deepEqual(init?.headers, { Authorization: `Bearer synthetic-${context}`,
        'X-Company-Id': `company-${context}`, 'X-Organization-Id': `org-${context}` })
      const request = new Request(url, init)
      assert.equal(request.credentials, 'include')
      assert.match(request.headers.get('Content-Type')!, /^multipart\/form-data; boundary=/)
      // Serialize then decode the multipart wire, rather than inspecting append calls.
      const wire = await request.arrayBuffer()
      const form = await new Response(wire, { headers: { 'Content-Type': request.headers.get('Content-Type')! } }).formData()
      assert.deepEqual([...form.keys()], ['company_id', 'declared_type', 'source', 'file'])
      assert.equal(form.get('company_id'), `company-${context}`)
      assert.equal(form.get('declared_type'), 'invoice'); assert.equal(form.get('source'), 'file')
      const sentFile = form.get('file') as File
      assert.equal(sentFile.name, file().name); assert.equal(sentFile.type, file().type)
      assert.deepEqual(new Uint8Array(await sentFile.arrayBuffer()), bytes)
    }
    f.respond(async () => json({ created: 1, skipped: 0 }))
    assert.deepEqual(await f.intake.acceptIntake('company-B', ['item-synthetic']), { created: 1, skipped: 0 })
    assert.equal(f.calls.length, 2)
    assert.equal(f.calls[1].url, `${apiBase}/api/intake-docs/accept?company_id=company-B`)
    assert.equal(f.calls[1].init?.body, '["item-synthetic"]')
  })

  await probe('fetch upload without options keeps same-origin default', async () => {
    f.respond(async () => json({ ok: true }))
    assert.deepEqual(await f.api.upload('/api/synthetic-upload', new FormData()), { ok: true })
    const call = f.calls[0]
    assert.equal(call.init?.credentials, undefined)
    assert.equal(new Request(call.url, call.init).credentials, 'same-origin')
  })

  await probe('XHR include is opt-in, progress and old default still work', async () => {
    const instances: SyntheticXHR[] = []
    class SyntheticXHR {
      withCredentials = false
      upload: { onprogress?: (event: ProgressEvent) => void } = {}
      onload?: () => void
      response = '{"ok":true}'
      status = 200
      statusText = 'OK'
      sent: Record<string, string> = {}
      opened = false
      constructor() { instances.push(this) }
      open(method: string, url: string) {
        assert.equal(method, 'POST'); assert.equal(url, `${apiBase}/api/synthetic-upload`)
        assert.equal(this.withCredentials, false); this.opened = true
      }
      setRequestHeader(key: string, value: string) { this.sent[key] = value }
      getResponseHeader() { return 'application/json' }
      send(body: FormData) {
        assert.equal(this.opened, true); assert.ok(body instanceof FormData)
        this.upload.onprogress!({ lengthComputable: true, loaded: 1, total: 2 } as ProgressEvent)
        this.onload!()
      }
    }
    Object.defineProperty(globalThis, 'XMLHttpRequest', { configurable: true, value: SyntheticXHR })
    for (const options of [undefined, { credentials: 'include' as const }]) {
      const progress: number[] = []
      assert.deepEqual(await f.api.upload('/api/synthetic-upload', new FormData(), (n) => progress.push(n), options), { ok: true })
      const xhr = instances.at(-1)!
      assert.equal(xhr.withCredentials, options?.credentials === 'include')
      assert.deepEqual(xhr.sent, { Authorization: 'Bearer synthetic-A', 'X-Company-Id': 'company-A', 'X-Organization-Id': 'org-A' })
      assert.deepEqual(progress, [0.5])
    }
    assert.equal(f.calls.length, 0)
  })

  await probe('JSON validation and nonJSON responses use common API errors without retry', async () => {
    const fieldErrors = [{ loc: ['body', 'file'], msg: 'Synthetic invalid file', type: 'value_error' }]
    const cases = [
      { response: () => json({ detail: fieldErrors }, 422), error: { name: 'ApiValidationError', status: 422,
        detail: 'body.file: Synthetic invalid file', fieldErrors } },
      { response: () => json({ detail: 'Synthetic conflict' }, 409), error: { name: 'ApiError', status: 409, detail: 'Synthetic conflict' } },
      { response: () => new Response('<html>proxy</html>', { status: 503, statusText: 'Service Unavailable' }),
        error: { name: 'ApiError', status: 503, detail: 'Service Unavailable' } },
      { response: () => new Response('<html>proxy</html>', { headers: { 'Content-Type': 'text/html' } }),
        error: { name: 'ApiError', status: 502, detail: 'Сервис вернул неожиданный ответ. Обновите страницу или повторите позже.' } },
      { response: () => new Response('{', { headers: { 'Content-Type': 'application/json' } }),
        error: { name: 'ApiError', status: 502, detail: 'Сервис вернул повреждённые данные. Обновите страницу или повторите позже.' } },
    ]
    for (const example of cases) {
      f.calls.length = 0; f.respond(async () => example.response())
      await assert.rejects(f.intake.uploadIntake('company-A', file(), 'invoice'), example.error)
      assert.equal(f.calls.length, 1)
    }
  })

  await probe('401 expires current session but a late old401 preserves a new session after body parsing', async () => {
    for (const replace of [true, false]) {
      f.reset()
      const entered = deferred<void>(), body = deferred<object>()
      f.respond(async () => {
        const response = json({}, 401)
        response.json = () => { entered.resolve(); return body.promise }
        return response
      })
      const failed = assert.rejects(f.intake.uploadIntake('company-A', file(), 'invoice'), {
        name: 'ApiError', status: 401, detail: 'Synthetic expired',
      })
      await entered.promise
      if (replace) f.api.setToken('synthetic-B')
      body.resolve({ detail: 'Synthetic expired' }); await failed
      await new Promise<void>((resolve) => setImmediate(resolve))
      assert.equal(f.api.getToken(), replace ? 'synthetic-B' : null)
      assert.equal(f.timers.size, replace ? 0 : 1)
      assert.deepEqual(f.toast.messages, replace ? [] : [['Сессия истекла', { description: 'Войдите в систему снова' }]])
      assert.equal(f.calls.length, 1)
      if (!replace) {
        for (const [id, run] of f.timers) { f.timers.delete(id); run() }
        assert.equal(f.location.href, '/login?next=%2Fbooks')
      }
    }
  })
})
