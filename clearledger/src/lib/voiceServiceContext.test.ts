import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test, { mock } from 'node:test'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../../', import.meta.url))
const baseline = process.env.VOICE_SERVICE_BASELINE
const source = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/voiceService.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const cid = 'company-synthetic'
const core = 'https://core.example.test', node = 'https://node.example.test/api/v1'
const json = (body: unknown, status = 200, headers?: HeadersInit) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', ...headers },
})
const denied = () => json({ error: 'invalid_token', detail: 'Synthetic node denial' }, 401)
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const settled = <T>(promise: Promise<T>) => promise.then(
  (value) => ({ ok: true as const, value }), (error: unknown) => ({ ok: false as const, error }),
)
const tick = () => new Promise<void>((done) => setImmediate(done))
type Call = { url: string; init?: RequestInit; authorization: string | null }

async function fixture() {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const memory = () => {
    const data = new Map<string, string>()
    return { getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) }
  }
  const location = { origin: core, pathname: '/voice', search: '', hash: '', href: '' }
  const issues: Call[] = [], nodes: Call[] = []
  let issueReply: ((call: Call) => Promise<Response>) | undefined
  let nodeReply: (call: Call) => Promise<Response> = async () => json({ synthetic: true })
  for (const [key, value] of Object.entries({ window: { location }, localStorage: memory(), sessionStorage: memory(),
    fetch: async (url: string, init?: RequestInit) => {
      const call = { url: String(url), init, authorization: new Headers(init?.headers).get('Authorization') }
      if (call.url.startsWith(`${core}/api/sso/token?`)) {
        issues.push(call)
        assert.equal(new URL(call.url).searchParams.get('company_id'), cid)
        assert.equal(new URL(call.url).searchParams.get('app'), 'voice')
        if (issueReply) return issueReply(call)
        return json({ token: `voice-${call.authorization?.endsWith('B') ? 'B' : 'A'}-${issues.length}`, expires_in: 300 })
      }
      assert.ok(call.url.startsWith(node), 'Only synthetic Core issuer and node transport are allowed')
      nodes.push(call); return nodeReply(call)
    },
  })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const clock = mock.method(Date, 'now', () => 1_700_000_000_000)
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/voice-service-context-${process.pid}`,
    plugins: [{ name: 'voice-context-boundaries', transform(code, id) {
      if (id.endsWith('/src/services/apiClient.ts')) return code.replace(/import\((['"])sonner\1\)/, "import('virtual:voice-context-toast')")
    }, resolveId(id) { if (id === 'virtual:voice-context-toast') return '\0voice-context-toast' }, load(id) {
      if (source && id.endsWith('/src/services/voiceService.ts')) return source
      if (id === '\0voice-context-toast') return 'export const messages=[]; export const toast={error:(...args)=>messages.push(args)}'
    } }], resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(core), 'import.meta.env.VITE_VOICE_API_URL': JSON.stringify(node),
      'import.meta.env.VITE_VOICE_DEV_TOKEN_URL': 'undefined', 'import.meta.env.DEV': 'false', 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const voice = await server.ssrLoadModule('/src/services/voiceService.ts') as typeof import('../services/voiceService.ts')
  const cache = await server.ssrLoadModule('/src/services/cacheReset.ts') as typeof import('../services/cacheReset.ts')
  const toast = await server.ssrLoadModule('\0voice-context-toast') as { messages: unknown[][] }
  const timers = new Map<object, () => void>()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((fn: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSet(fn, delay, ...args)
    const id = {}; timers.set(id, fn); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!timers.delete(id)) originalClear(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  const stops: (() => void)[] = []
  return { api, voice, cache, issues, nodes, toast, timers, location,
    respondIssue(reply: typeof issueReply) { issueReply = reply },
    respondNode(reply: typeof nodeReply) { nodeReply = reply },
    switchSession(principal: 'A' | 'B') {
      // CompanyContext.activateContext: Core token already changed, same company, explicit cache reset.
      api.setToken(`core-${principal}`); api.setApiCompany(cid)
      cache.resetServiceCaches(); cache.setServicesCompany(cid)
    },
    addStop(stop: () => void) { stops.push(stop) },
    async close() {
      stops.forEach((stop) => stop()); start.mock.restore(); stop.mock.restore(); clock.mock.restore()
      await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('voice actual-service context and protocol boundary', { timeout: 45_000 }, async (t) => {
  const pattern = process.env.VOICE_CASE_PATTERN ? new RegExp(process.env.VOICE_CASE_PATTERN) : undefined
  const probe = (name: string, run: (f: Awaited<ReturnType<typeof fixture>>) => Promise<void>) => t.test(name, {
    skip: pattern ? !pattern.test(name) : false, timeout: 8_000,
  }, async (t) => { const f = await fixture(); t.after(() => f.close()); f.switchSession('A'); await run(f) })

  await probe('reset during token issue must prevent old intent HTTP dispatch', async (f) => {
    const entered = deferred<void>(), oldIssue = deferred<Response>()
    f.respondIssue(async () => { entered.resolve(); return oldIssue.promise })
    const old = settled(f.voice.configSaveDraft(cid, 'passport', 1, '"etag-A"', { synthetic: 'old-intent' }))
    await entered.promise
    f.switchSession('B'); f.respondIssue(undefined)
    assert.equal((await f.voice.voiceToken(cid)).token, 'voice-B-2')
    oldIssue.resolve(json({ token: 'voice-A-1', expires_in: 300 }))
    const outcome = await old
    assert.deepEqual(f.issues.map((call) => call.authorization), ['Bearer core-A', 'Bearer core-B'])
    assert.deepEqual(f.nodes.map((call) => call.authorization), [], 'Old intent must not dispatch after reset, including with a late A token')
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
  })

  await probe('reset before late node401 must not replay mutation under new principal', async (f) => {
    const entered = deferred<void>(), oldNode = deferred<Response>()
    f.respondNode(async () => { entered.resolve(); return oldNode.promise })
    const old = settled(f.voice.configSaveDraft(cid, 'passport', 1, '"etag-A"', { synthetic: 'old-intent' }))
    await entered.promise
    f.switchSession('B')
    const fresh = await f.voice.voiceToken(cid)
    f.respondNode(async () => json({ synthetic: true }))
    oldNode.resolve(denied())
    const outcome = await old
    assert.deepEqual(f.nodes.map((call) => call.authorization), ['Bearer voice-A-1'], 'Stale PUT must not be replayed with B credentials')
    assert.deepEqual(f.issues.map((call) => call.authorization), ['Bearer core-A', 'Bearer core-B'], 'Old401 must not invalidate B cache or issue B again')
    assert.equal((await f.voice.voiceToken(cid)).token, fresh.token)
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    assert.equal(f.api.getToken(), 'core-B')
  })

  await probe('reset during refresh token issue must prevent old retry dispatch', async (f) => {
    const entered = deferred<void>(), refresh = deferred<Response>()
    f.respondIssue(async () => {
      if (f.issues.length === 2) { entered.resolve(); return refresh.promise }
      return json({ token: 'voice-A-1', expires_in: 300 })
    })
    f.respondNode(async () => f.nodes.length === 1 ? denied() : json({ synthetic: true }))
    const old = settled(f.voice.configSaveDraft(cid, 'passport', 1, '"etag-A"', { synthetic: 'old-intent' }))
    await entered.promise
    f.switchSession('B'); f.respondIssue(undefined)
    await f.voice.voiceToken(cid)
    refresh.resolve(json({ token: 'voice-A-2', expires_in: 300 }))
    const outcome = await old
    assert.deepEqual(f.nodes.map((call) => call.authorization), ['Bearer voice-A-1'], 'A refresh completed after reset must not send the old PUT')
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    assert.equal((await f.voice.voiceToken(cid)).token, 'voice-B-3')
  })

  await probe('reset during exported voiceToken issue rejects late token to old caller', async (f) => {
    const entered = deferred<void>(), response = deferred<Response>()
    f.respondIssue(async () => { entered.resolve(); return response.promise })
    const old = settled(f.voice.voiceToken(cid))
    await entered.promise
    f.switchSession('B'); f.respondIssue(undefined)
    const fresh = await f.voice.voiceToken(cid)
    response.resolve(json({ token: 'voice-A-1', expires_in: 300 }))
    const outcome = await old
    assert.equal(outcome.ok, false, 'Old caller must not receive an issued A token after explicit reset')
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    assert.equal((await f.voice.voiceToken(cid)).token, fresh.token)
    assert.equal(f.nodes.length, 0)
  })

  await probe('reset during issuer error prevents late error ownership by new context', async (f) => {
    const entered = deferred<void>(), response = deferred<Response>()
    f.respondIssue(async () => { entered.resolve(); return response.promise })
    const old = settled(f.voice.voiceToken(cid))
    await entered.promise; f.switchSession('B')
    response.resolve(json({ detail: 'Synthetic issuer unavailable' }, 503))
    const outcome = await old
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    assert.equal(f.api.getToken(), 'core-B'); assert.equal(f.nodes.length, 0)
  })

  await probe('reset during JSON/health/export/audio body reads blocks stale result and objectURL', async (f) => {
    const create = mock.method(URL, 'createObjectURL', () => 'blob:synthetic-voice')
    try {
      const cases = [
        { call: () => f.voice.configActive(cid, 'passport'), kind: 'json', value: { version: 1 } },
        { call: () => f.voice.health(cid), kind: 'json', value: { ok: true } },
        { call: () => f.voice.monthlyExport(cid, '2026-01', 'csv'), kind: 'blob', value: new Blob(['synthetic']) },
        { call: () => f.voice.soundAudio(cid, 'synthetic'), kind: 'blob', value: new Blob(['synthetic']) },
      ]
      for (const example of cases) {
        f.switchSession('A')
        const entered = deferred<void>(), body = deferred<unknown>()
        f.respondNode(async () => {
          const response = json({})
          if (example.kind === 'json') response.json = () => { entered.resolve(); return body.promise }
          else response.blob = () => { entered.resolve(); return body.promise as Promise<Blob> }
          return response
        })
        const old = settled(example.call())
        await entered.promise; f.switchSession('B'); body.resolve(example.value)
        const outcome = await old
        assert.equal(outcome.ok, false, `Retired ${example.kind} result must not reach the old caller`)
        if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
      }
      assert.equal(create.mock.callCount(), 0, 'Retired audio bytes must not create an object URL')
    } finally { create.mock.restore() }
  })

  await probe('reset during body rejection returns context abort rather than stale parse error', async (f) => {
    const entered = deferred<void>(), body = deferred<object>()
    f.respondNode(async () => {
      const response = json({}); response.json = () => { entered.resolve(); return body.promise }; return response
    })
    const old = settled(f.voice.configActive(cid, 'passport'))
    await entered.promise; f.switchSession('B'); body.reject(new SyntaxError('Synthetic truncated JSON'))
    const outcome = await old
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
  })

  await probe('reset in HTTP helper await hop must not invalidate new context token cache', async (f) => {
    f.respondNode(async () => denied())
    let fresh: ReturnType<typeof f.voice.voiceToken> | undefined
    const transport = globalThis.fetch
    const intercept = mock.method(globalThis, 'fetch', ((url, init) => {
      const response = transport(url, init)
      if (!String(url).startsWith(node)) return response
      return response.then((value) => {
        // Reset lands after run() checks but before the service's outer await resumes.
        queueMicrotask(() => queueMicrotask(() => { f.switchSession('B'); fresh = f.voice.voiceToken(cid) }))
        return value
      })
    }) as typeof fetch)
    try {
      const outcome = await settled(f.voice.me(cid))
      assert.ok(fresh)
      const issued = await fresh
      assert.equal((await f.voice.voiceToken(cid)).token, issued.token, 'Stale401 must not discard new in-flight/cache generation')
      assert.equal(f.issues.length, 2, 'New principal needs one issuer call, even across the helper await hop')
      assert.equal(f.nodes.length, 1); assert.equal(outcome.ok, false)
      if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    } finally { intercept.mock.restore() }
  })

  await probe('reset in blob helper await hop must prevent objectURL side effect', async (f) => {
    const create = mock.method(URL, 'createObjectURL', () => 'blob:synthetic-voice')
    try {
      f.respondNode(async () => {
        const response = json({})
        response.blob = () => Promise.resolve(new Blob(['synthetic'])).then((blob) => {
          queueMicrotask(() => queueMicrotask(() => f.switchSession('B')))
          return blob
        })
        return response
      })
      const outcome = await settled(f.voice.soundAudio(cid, 'synthetic'))
      assert.equal(create.mock.callCount(), 0, 'No retired objectURL between run() check and outer await continuation')
      assert.equal(outcome.ok, false)
      if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    } finally { create.mock.restore() }
  })

  await probe('ordinary node401 refreshes once and preserves mutation body, ETag and response', async (f) => {
    const data = { version: 2, body: { synthetic: true } }
    f.respondNode(async () => f.nodes.length === 1 ? denied() : json(data, 200, { ETag: '"etag-B"' }))
    assert.deepEqual(await f.voice.configSaveDraft(cid, 'passport', 1, '"etag-A"', { synthetic: true }, 'Synthetic reason'), { data, etag: '"etag-B"' })
    assert.equal(f.issues.length, 2); assert.equal(f.nodes.length, 2)
    assert.deepEqual(f.nodes.map((call) => call.authorization), ['Bearer voice-A-1', 'Bearer voice-A-2'])
    for (const call of f.nodes) {
      assert.equal(call.init?.method, 'PUT')
      assert.equal(new Headers(call.init?.headers).get('If-Match'), '"etag-A"')
      assert.equal(new Headers(call.init?.headers).get('Content-Type'), 'application/json')
      assert.equal(call.init?.body, '{"body":{"synthetic":true},"comment":"Synthetic reason"}')
    }
    assert.equal(f.api.getToken(), 'core-A'); assert.equal(f.timers.size, 0); assert.equal(f.toast.messages.length, 0)
  })

  await probe('invalid node credentials stop after one refresh without Core logout', async (f) => {
    f.respondNode(async () => denied())
    await assert.rejects(f.voice.me(cid), { status: 401, code: 'invalid_token' })
    assert.equal(f.issues.length, 2); assert.equal(f.nodes.length, 2)
    assert.equal(f.api.getToken(), 'core-A'); assert.equal(f.timers.size, 0); assert.equal(f.toast.messages.length, 0)
    assert.equal((await f.voice.voiceToken(cid)).token, 'voice-A-3', 'Second rejected node token is invalidated for next manual operation')
  })

  await probe('problem JSON, nonJSON error, accepted503,204 and multipart keep existing contracts', async (f) => {
    const issues = [{ path: 'synthetic', code: 'invalid', level: 'error' as const }]
    f.respondNode(async () => json({ error: 'synthetic_problem', detail: 'Synthetic detail', issues }, 422))
    await assert.rejects(f.voice.me(cid), { status: 422, code: 'synthetic_problem', message: 'Synthetic detail', issues })
    f.respondNode(async () => new Response('Synthetic proxy error', { status: 500 }))
    await assert.rejects(f.voice.me(cid), { status: 500, code: '500', message: 'Узел ответил ошибкой 500' })
    f.respondNode(async () => json({ error: 'precondition_failed' }, 412))
    await assert.rejects(f.voice.me(cid), { status: 412, message: 'Настройки успели поменять: обновите экран и повторите' })
    const health = { ok: false, parts: { synthetic: { ok: false } } }
    f.respondNode(async () => json(health, 503)); assert.deepEqual(await f.voice.health(cid), health)
    f.respondNode(async () => new Response(null, { status: 204 })); assert.equal(await f.voice.configDeleteDraft(cid, 'passport', 1), undefined)
    const bytes = new Uint8Array([0, 255, 42])
    f.respondNode(async (call) => {
      assert.equal(call.init?.method, 'POST'); assert.equal(new Headers(call.init?.headers).get('Content-Type'), null)
      const wire = await new Request(call.url, call.init).formData()
      assert.deepEqual([...wire.keys()], ['name', 'title', 'replace', 'file'])
      assert.equal(wire.get('name'), 'synthetic'); assert.equal(wire.get('replace'), 'true')
      const file = wire.get('file') as File
      assert.equal(file.name, 'synthetic.wav'); assert.deepEqual(new Uint8Array(await file.arrayBuffer()), bytes)
      return json({ name: 'synthetic' })
    })
    assert.deepEqual(await f.voice.uploadSound(cid, { name: 'synthetic', title: 'Synthetic', replace: true,
      file: new File([bytes], 'synthetic.wav', { type: 'audio/wav' }) }), { name: 'synthetic' })
    assert.equal(f.issues.length, 1)
    f.respondNode(async () => new Response(bytes, { headers: { 'Content-Disposition': 'attachment; filename="synthetic.csv"' } }))
    const exported = await f.voice.monthlyExport(cid, '2026-01', 'csv')
    assert.equal(exported.имя, 'synthetic.csv'); assert.deepEqual(new Uint8Array(await exported.blob.arrayBuffer()), bytes)
    const create = mock.method(URL, 'createObjectURL', () => 'blob:synthetic-voice')
    try {
      assert.equal(await f.voice.soundAudio(cid, 'synthetic'), 'blob:synthetic-voice')
      assert.deepEqual(new Uint8Array(await (create.mock.calls[0].arguments[0] as Blob).arrayBuffer()), bytes)
    } finally { create.mock.restore() }
    f.switchSession('A'); f.respondIssue(async () => json({ detail: 'Synthetic issuer unavailable' }, 503))
    await assert.rejects(f.voice.voiceToken(cid), { status: 503, code: 'token_issue', message: 'Synthetic issuer unavailable' })
    assert.equal(f.api.getToken(), 'core-A'); assert.equal(f.toast.messages.length, 0)
  })

  await probe('SSE ordinary401 refreshes once, parses event and stops without Core logout', async (f) => {
    const received = deferred<unknown>(), states: string[] = []
    f.respondNode(async (call) => {
      assert.equal(new Headers(call.init?.headers).get('Accept'), 'text/event-stream')
      if (f.nodes.length === 1) return denied()
      const body = new ReadableStream<Uint8Array>({ start(controller) {
        controller.enqueue(new TextEncoder().encode(':ping\n\nevent: trunk\ndata: {"trunk":"up"}\n\n'))
        call.init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Synthetic stop', 'AbortError')), { once: true })
      } })
      return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    })
    const stop = f.voice.nowStream(cid, (event) => received.resolve(event), (state) => states.push(state)); f.addStop(stop)
    assert.deepEqual(await received.promise, { type: 'trunk', data: { trunk: 'up' } })
    stop(); await tick()
    assert.deepEqual(states, ['live']); assert.equal(f.nodes.length, 2); assert.equal(f.issues.length, 2)
    assert.equal(f.api.getToken(), 'core-A'); assert.equal(f.toast.messages.length, 0)
  })

  await probe('SSE reset before late401 must not reopen old stream under new principal', async (f) => {
    const entered = deferred<void>(), response = deferred<Response>()
    const states: string[] = []
    f.respondNode(async () => { entered.resolve(); return response.promise })
    const stop = f.voice.nowStream(cid, () => {}, (state) => states.push(state)); f.addStop(stop)
    await entered.promise
    f.switchSession('B'); const fresh = await f.voice.voiceToken(cid)
    f.respondNode(async () => denied()); response.resolve(denied())
    const signal = f.nodes[0].init?.signal
    for (let i = 0; i < 50 && f.nodes.length === 1 && !signal?.aborted; i++) await tick()
    assert.deepEqual(f.nodes.map((call) => call.authorization), ['Bearer voice-A-1'], 'Old stream cannot refresh/reopen with B credentials')
    assert.equal(signal?.aborted, true, 'Retired stream is terminal')
    assert.deepEqual(states, [])
    assert.equal((await f.voice.voiceToken(cid)).token, fresh.token)
    assert.equal(f.issues.length, 2); assert.equal(f.api.getToken(), 'core-B')
  })

  await probe('SSE reset during token issue must prevent any old stream dispatch', async (f) => {
    const entered = deferred<void>(), response = deferred<Response>(), states: string[] = []
    f.respondIssue(async () => { entered.resolve(); return response.promise })
    f.respondNode(async () => denied())
    const stop = f.voice.nowStream(cid, () => {}, (state) => states.push(state)); f.addStop(stop)
    await entered.promise
    f.switchSession('B'); f.respondIssue(undefined); await f.voice.voiceToken(cid)
    response.resolve(json({ token: 'voice-A-1', expires_in: 300 }))
    await tick(); await tick()
    assert.deepEqual(f.nodes, [], 'A retired stream waiting for token issue must never open HTTP')
    assert.deepEqual(states, []); assert.equal(f.issues.length, 2)
  })

  await probe('SSE invalid credentials fail after one refresh without Core logout', async (f) => {
    const failed = deferred<unknown>(), states: string[] = []
    f.respondNode(async () => denied())
    const stop = f.voice.nowStream(cid, () => {}, (state, error) => {
      states.push(state); if (state === 'failed') failed.resolve(error)
    }); f.addStop(stop)
    const error = await failed.promise as { status: number; code: string }
    assert.equal(error.status, 401); assert.equal(error.code, 'invalid_token')
    assert.deepEqual(states, ['failed']); assert.equal(f.nodes.length, 2); assert.equal(f.issues.length, 2)
    assert.equal(f.api.getToken(), 'core-A'); assert.equal(f.toast.messages.length, 0); assert.equal(f.timers.size, 0)
  })

  await probe('SSE reset during reader await suppresses buffered events and releases retired reader', async (f) => {
    const live = deferred<void>(), delivered: unknown[] = [], states: string[] = []
    let controller!: ReadableStreamDefaultController<Uint8Array>, canceled = false
    f.respondNode(async () => new Response(new ReadableStream<Uint8Array>({
      start(value) { controller = value }, cancel() { canceled = true },
    }), { headers: { 'Content-Type': 'text/event-stream' } }))
    const stop = f.voice.nowStream(cid, (event) => delivered.push(event), (state) => {
      states.push(state); if (state === 'live') live.resolve()
    }); f.addStop(stop)
    try {
      await live.promise; await tick()
      f.switchSession('B')
      // Buffered body ignores fetch abort on purpose: the service must guard read/callback too.
      controller.enqueue(new TextEncoder().encode('event: trunk\ndata: {"trunk":"up"}\n\n'))
      for (let i = 0; i < 50 && !canceled && delivered.length === 0; i++) await tick()
      assert.deepEqual(delivered, []); assert.equal(canceled, true)
      assert.deepEqual(states, ['live']); assert.equal(f.nodes.length, 1); assert.equal(f.issues.length, 1)
    } finally { stop(); if (!canceled) controller.close(); await tick() }
  })
})
