import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { createServer } from 'vite'
import type { AuditorEvents } from '../services/spaceAuditorService.ts'

// Real service + apiClient via the existing SSR fixture convention. Only browser
// storage and fetch boundaries are synthetic; streams/UTF-8/AbortController are real.
const root = fileURLToPath(new URL('../../', import.meta.url))
const baseline = process.env.AUDITOR_SSE_BASELINE
const source = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/spaceAuditorService.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const tick = () => new Promise<void>((done) => setImmediate(done))
const deferred = <T>() => {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const data = (type: string, content: unknown) => `data: ${JSON.stringify({ type, content })}\n`
const json = (status: number) => new Response('{}', {
  status, statusText: 'Synthetic failure', headers: { 'Content-Type': 'application/json' },
})
function stream(cancelError?: Error) {
  let writer!: ReadableStreamDefaultController<Uint8Array>, cancellations = 0
  const body = new ReadableStream<Uint8Array>({ start(controller) { writer = controller },
    cancel() { cancellations++; if (cancelError) return Promise.reject(cancelError) } })
  const response = new Response(body, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } })
  return { response, body, cancellations: () => cancellations,
    bytes(value: Uint8Array) { writer.enqueue(value) },
    send(value: string) { writer.enqueue(new TextEncoder().encode(value)) },
    close() { writer.close() }, fail(error: unknown) { writer.error(error) } }
}

async function fixture() {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const storage = () => {
    const values = new Map<string, string>()
    return { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  }
  const local = storage(), session = storage()
  const location = { origin: 'https://ui.example.test', pathname: '/auditor', search: '', hash: '', href: '' }
  const requests: { url: string; init?: RequestInit }[] = [], events: [string, unknown][] = []
  let respond: () => Promise<Response> = async () => json(503)
  let hook: ((name: string) => void) | undefined
  for (const [key, value] of Object.entries({ window: { location }, localStorage: local, sessionStorage: session,
    fetch: async (url: string, init?: RequestInit) => {
      assert.equal(url, '/auditor/api/ask'); requests.push({ url, init }); return respond()
    },
  })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/auditor-sse-context-${process.pid}`,
    plugins: source ? [{ name: 'immutable-auditor-sse-baseline', load(id) {
      if (id.endsWith('/src/services/spaceAuditorService.ts')) return source
    } }] : [], resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': '"https://core.example.test"', 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const auditor = await server.ssrLoadModule('/src/services/spaceAuditorService.ts') as typeof import('../services/spaceAuditorService.ts')
  const emit = (name: string, value?: unknown) => { events.push([name, value]); hook?.(name) }
  const callbacks: AuditorEvents = {
    onStatus: (value) => emit('status', value), onSkills: (value) => emit('skills', value),
    onText: (value) => emit('text', value), onFindings: (value) => emit('findings', value),
    onActions: (value) => emit('actions', value), onRun: (value) => emit('run', value),
    onError: (value) => emit('error', value), onDone: () => emit('done'),
  }
  return { api, auditor, local, location, requests, events,
    respond(fn: typeof respond) { respond = fn }, hook(fn: typeof hook) { hook = fn },
    ask(ev = callbacks, company = 'explicit-company') {
      return auditor.ask('Вопрос', { path: '/synthetic', product: 'Контроль', params: { q: 'а' } }, company,
        [{ role: 'user', content: 'История' }], ev, ['file-A'], true)
    },
    reset() {
      hook = undefined; respond = async () => json(503); requests.length = 0; events.length = 0
      api.setToken('synthetic-A'); api.setApiCompany('company-A'); api.setApiOrganization('org-A'); location.href = ''
    },
    checkSession(token: string | null = 'synthetic-A') { assert.equal(api.getToken(), token); assert.equal(location.href, '') },
    async close() {
      await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}
type Fixture = Awaited<ReturnType<typeof fixture>>
const changes = {
  company: (f: Fixture) => f.api.setApiCompany('company-B'),
  organization: (f: Fixture) => f.api.setApiOrganization('org-B'),
  session: (f: Fixture) => f.api.setToken('synthetic-B'),
  'company A-B-A': (f: Fixture) => { f.api.setApiCompany('company-B'); f.api.setApiCompany('company-A') },
  'organization A-B-A': (f: Fixture) => { f.api.setApiOrganization('org-B'); f.api.setApiOrganization('org-A') },
  'token A-B-A': (f: Fixture) => { f.api.setToken('synthetic-B'); f.api.setToken('synthetic-A') },
  'same token login': (f: Fixture) => f.api.setToken('synthetic-A'),
  'logout relogin same token': (f: Fixture) => { f.api.clearToken(); f.api.setToken('synthetic-A') },
  logout: (f: Fixture) => f.api.clearToken(),
}

test('Auditor ask actual-service SSE context boundaries', { timeout: 45_000 }, async (t) => {
  const f = await fixture(); t.after(() => f.close())
  const probe = (name: string, run: () => Promise<void>) => t.test(name, { timeout: 5_000 }, async (child) => {
    f.reset()
    try { await run() } finally { child.diagnostic(JSON.stringify({ requests: f.requests.length, callbacks: f.events })) }
  })
  await probe('control: fragmented UTF-8, data lines and all callbacks preserve wire contract', async () => {
    const s = stream(); f.respond(async () => s.response)
    const controller = f.ask(); assert.ok(controller instanceof AbortController); await tick()
    const expected: [string, unknown][] = [['status', 'Думаю'], ['skills', ['audit']], ['text', 'Ёж 🦔'],
      ['findings', [{ severity: 'low', title: 'Проверка' }]], ['actions', [{ id: 'A', name: 'Проверить' }]],
      ['run', 'run-A'], ['error', 'Сообщение']]
    const wire = ': keepalive\ndata: malformed\ndata:{"type":"text","content":"ignored"}\n'
      + expected.map(([type, content]) => data(type, content)).join('')
      + 'data: {"type":"unknown"}\ndata: [DONE]\n' + data('text', 'after done')
    const bytes = new TextEncoder().encode(wire)
    for (let i = 0; i < bytes.length; i += 2) s.bytes(bytes.slice(i, i + 2))
    await tick(); assert.deepEqual(f.events, [...expected, ['done', undefined]])
    assert.equal(s.body.locked, false); assert.equal(s.cancellations(), 1)
    assert.equal(f.requests.length, 1)
    const init = f.requests[0].init!
    assert.deepEqual(init.headers, { 'Content-Type': 'application/json', Authorization: 'Bearer synthetic-A', 'X-Company-Id': 'explicit-company' })
    assert.equal(init.method, 'POST'); assert.equal(init.signal, controller.signal); assert.equal(init.credentials, undefined)
    assert.deepEqual(JSON.parse(init.body as string), { question: 'Вопрос', context: { path: '/synthetic', product: 'Контроль', params: { q: 'а' } },
      history: [{ role: 'user', content: 'История' }], files: ['file-A'], workshop: true })
    f.checkSession()
  })
  await probe('control: EOF ignores unterminated line and finishes once', async () => {
    const s = stream(); f.respond(async () => s.response); f.ask(); await tick()
    s.send(data('text', 'one') + 'data: {"type":"text","content":"unfinished"}'); s.close(); await tick()
    assert.deepEqual(f.events, [['text', 'one'], ['done', undefined]])
    assert.equal(s.body.locked, false); assert.equal(s.cancellations(), 0)
  })
  await probe('control: identical scope setters keep pending response current', async () => {
    const pending = deferred<Response>(); f.respond(() => pending.promise); f.ask()
    f.api.setApiCompany('company-A'); f.api.setApiOrganization('org-A')
    const s = stream(); s.send(data('text', 'current') + 'data: [DONE]\n'); pending.resolve(s.response); await tick()
    assert.deepEqual(f.events, [['text', 'current'], ['done', undefined]])
  })
  for (const [name, change] of Object.entries(changes)) for (const phase of ['response', 'error JSON', 'read chunk'] as const) {
    await probe(`race: ${name} during ${phase} suppresses old callbacks`, async () => {
      const response = deferred<Response>(), body = deferred<object>(), entered = deferred<void>(), s = stream()
      f.respond(async () => {
        if (phase === 'response') return response.promise
        if (phase === 'read chunk') return s.response
        const res = json(401); res.json = async () => { entered.resolve(); return body.promise }; return res
      })
      f.ask(); if (phase === 'error JSON') await entered.promise; else await tick()
      change(f)
      if (phase === 'response') { s.send(data('text', 'stale') + 'data: [DONE]\n'); response.resolve(s.response) }
      if (phase === 'error JSON') body.resolve({ error: 'stale denial' })
      if (phase === 'read chunk') s.send(data('text', 'stale') + 'data: [DONE]\n')
      await tick(); assert.deepEqual(f.events, [], 'No old text/error/done may reach panel state')
      f.checkSession(name === 'session' ? 'synthetic-B' : name === 'logout' ? null : 'synthetic-A')
      assert.equal(s.body.locked, false, 'Own stream lock is released on stale exit')
    })
  }
  for (const type of ['status', 'skills', 'text', 'findings', 'actions', 'run', 'error']) {
    await probe(`race: context change inside ${type} callback stops remaining buffered lines`, async () => {
      const s = stream(); f.respond(async () => s.response); f.hook((name) => { if (name === type) f.api.setToken('synthetic-A') })
      f.ask(); s.send(data(type, 'first') + data('text', 'late') + 'data: [DONE]\n'); await tick()
      assert.deepEqual(f.events, [[type, 'first']]); assert.equal(s.body.locked, false)
    })
  }
  for (const phase of ['response', 'error JSON', 'read chunk']) await probe(`abort: pending ${phase} emits no callbacks`, async () => {
    const pending = deferred<Response>(), body = deferred<object>(), s = stream()
    f.respond(async () => {
      if (phase === 'response') return pending.promise
      if (phase === 'read chunk') return s.response
      const res = json(403); res.json = () => body.promise; return res
    })
    const controller = f.ask(); await tick(); controller.abort()
    if (phase === 'response') { s.send('data: [DONE]\n'); pending.resolve(s.response) }
    if (phase === 'error JSON') body.resolve({ error: 'late' })
    if (phase === 'read chunk') await tick()
    await tick(); assert.deepEqual(f.events, []); assert.equal(s.body.locked, false)
  })
  await probe('race: stopped old reader cannot finish or overwrite a new panel answer', async () => {
    const old = stream(), fresh = stream(); f.respond(async () => old.response)
    let answer = '', busy = true
    const callbacks = { onText: (chunk: string) => { answer += chunk }, onDone: () => { busy = false } }
    const controller = f.ask(callbacks); await tick(); controller.abort()
    f.respond(async () => fresh.response); f.ask(callbacks); fresh.send(data('text', 'new')); await tick()
    assert.equal(answer, 'new'); assert.equal(busy, true, 'Old EOF after abort must not clear new busy state')
    fresh.send('data: [DONE]\n'); await tick(); assert.equal(busy, false)
    assert.equal(old.cancellations(), 1); assert.equal(old.body.locked, false); assert.equal(fresh.body.locked, false)
  })
  for (const status of [401, 403, 503]) for (const malformed of [false, true]) {
    await probe(`control: HTTP ${status} ${malformed ? 'invalid' : 'valid'} error JSON preserves session`, async () => {
      f.respond(async () => { const res = json(status); res.json = async () => {
        if (malformed) throw new SyntaxError('invalid'); return { error: 'Synthetic denied' }
      }; return res })
      f.ask(); await tick(); assert.deepEqual(f.events, [['error', malformed ? `${status} Synthetic failure` : 'Synthetic denied'], ['done', undefined]])
      f.checkSession()
    })
  }
  await probe('control: non-SSE HTML reports disconnected auditor', async () => {
    f.respond(async () => new Response('<html>SPA</html>')); f.ask(); await tick()
    assert.deepEqual(f.events, [['error', 'Аудитор в этом пространстве не подключён'], ['done', undefined]])
  })
  await probe('control: no body retains JSON/status fallback', async () => {
    f.respond(async () => new Response(null, { status: 204 })); f.ask(); await tick()
    assert.deepEqual(f.events, [['error', '204 '], ['done', undefined]])
  })
  for (const phase of ['fetch', 'reader']) for (const stale of [false, true]) {
    await probe(`${stale ? 'race' : 'control'}: ${phase} rejection ${stale ? 'after session change' : 'current'}`, async () => {
      const pending = deferred<Response>(), s = stream()
      f.respond(() => phase === 'fetch' ? pending.promise : Promise.resolve(s.response)); f.ask(); await tick()
      if (stale) f.api.setToken('synthetic-A')
      if (phase === 'fetch') pending.reject(new TypeError('Synthetic network error')); else s.fail(new TypeError('Synthetic network error'))
      await tick(); assert.deepEqual(f.events, stale ? [] : [['error', 'Synthetic network error'], ['done', undefined]])
      f.checkSession()
    })
  }
  await probe('race: context change inside HTTP onError suppresses onDone', async () => {
    f.hook((name) => { if (name === 'error') f.api.setApiOrganization('org-B') }); f.ask(); await tick()
    assert.deepEqual(f.events, [['error', '503 Synthetic failure']])
  })
  await probe('race: read after an already delivered chunk cannot publish into changed context', async () => {
    const s = stream(); f.respond(async () => s.response); f.ask(); await tick()
    s.send(data('text', 'before')); await tick(); f.api.setApiCompany('company-B')
    s.send(data('text', 'after') + 'data: [DONE]\n'); await tick()
    assert.deepEqual(f.events, [['text', 'before']]); assert.equal(s.body.locked, false)
  })
  for (const kind of ['non-SSE', 'no body']) await probe(`race: stale ${kind} response stays silent`, async () => {
    const pending = deferred<Response>(); f.respond(() => pending.promise); f.ask(); f.api.setToken('synthetic-A')
    pending.resolve(kind === 'no body' ? new Response(null, { status: 204 }) : new Response('<html>SPA</html>'))
    await tick(); assert.deepEqual(f.events, []); f.checkSession()
  })
  await probe('race: rejected error JSON after same-token relogin stays silent', async () => {
    const pending = deferred<object>(), entered = deferred<void>()
    f.respond(async () => { const res = json(401); res.json = () => { entered.resolve(); return pending.promise }; return res })
    f.ask(); await entered.promise; f.api.clearToken(); f.api.setToken('synthetic-A')
    pending.reject(new SyntaxError('bad old response')); await tick(); assert.deepEqual(f.events, []); f.checkSession()
  })
  for (const stop of ['abort', 'context']) await probe(`cleanup: rejecting cancellation after ${stop} releases reader without callbacks`, async () => {
    const s = stream(new Error('Synthetic cancel failed')); f.respond(async () => s.response)
    const controller = f.ask(); await tick()
    if (stop === 'abort') controller.abort()
    else { f.api.setToken('synthetic-A'); s.send(data('text', 'stale')) }
    await tick(); assert.deepEqual(f.events, []); assert.equal(s.cancellations(), 1); assert.equal(s.body.locked, false)
  })
  await probe('race: abort inside text callback stops same-chunk callbacks', async () => {
    const s = stream(); f.respond(async () => s.response)
    const controller = f.ask(); f.hook((name) => { if (name === 'text') controller.abort() })
    s.send(data('text', 'first') + data('text', 'late') + 'data: [DONE]\n'); await tick()
    assert.deepEqual(f.events, [['text', 'first']]); assert.equal(s.cancellations(), 1); assert.equal(s.body.locked, false)
  })
  for (const phase of ['SSE DONE', 'HTTP error']) await probe(`cleanup: throwing onDone at ${phase} is not retried or unhandled`, async () => {
    const s = stream(); f.respond(async () => phase === 'SSE DONE' ? s.response : json(503))
    let done = 0, errors = 0
    f.ask({ onText: () => {}, onError: () => { errors++ }, onDone: () => { done++; throw new Error('Synthetic callback failed') } })
    if (phase === 'SSE DONE') s.send('data: [DONE]\n')
    await tick(); assert.equal(done, 1); assert.equal(errors, phase === 'HTTP error' ? 1 : 0); assert.equal(s.body.locked, false)
  })
  await probe('cleanup: throwing onError cannot escape the void service API', async () => {
    f.respond(async () => { throw new TypeError('Synthetic offline') }); let errors = 0, done = 0
    f.ask({ onText: () => {}, onError: () => { errors++; throw new Error('Synthetic callback failed') }, onDone: () => { done++ } })
    await tick(); assert.equal(errors, 1); assert.equal(done, 0)
  })
  await probe('control: SSE text callback failure keeps existing ignored-line behavior', async () => {
    const s = stream(); f.respond(async () => s.response); let text = 0, done = 0
    f.ask({ onText: () => { text++; throw new Error('Synthetic text callback failed') }, onDone: () => { done++ } })
    s.send(data('text', 'one') + data('text', 'two') + 'data: [DONE]\n'); await tick()
    assert.equal(text, 2); assert.equal(done, 1); assert.equal(s.body.locked, false)
  })
  await probe('control: optional callbacks and default body fields remain supported', async () => {
    const s = stream(); f.respond(async () => s.response); let text = ''
    f.auditor.ask('q', {}, 'company-A', [], { onText: (chunk) => { text += chunk } })
    s.send(data('status', 'ignored') + data('text', 'ok') + 'data: [DONE]\n'); await tick()
    assert.equal(text, 'ok'); assert.deepEqual(JSON.parse(f.requests[0].init!.body as string), {
      question: 'q', context: {}, history: [], files: [], workshop: false,
    })
  })
})
