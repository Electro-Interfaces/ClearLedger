import assert from 'node:assert/strict'
import test, { mock, type TestContext } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { toast } from 'sonner'

// Actual conferenceService, apiClient, demo router and sonner; no service or guard
// replacements. All storage, browser actions, HTTP and response bodies are synthetic.
const root = fileURLToPath(new URL('../../', import.meta.url))
const origin = 'https://core.example.test'
const token = 'synthetic-token-A', company = 'synthetic-company-A', organization = 'synthetic-org-A'
const ticket = 'synthetic ticket /?#%'
const meeting = { room: 'synthetic-room', moderator_url: 'https://meeting.example.test/moderator',
  guest_url: 'https://meeting.example.test/guest', session_id: 'synthetic-session' }
const joinUrl = 'https://meeting.example.test/ticket-entry'
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})
const deferred = <T>() => {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const settled = <T>(promise: Promise<T>) => promise.then(
  (value) => ({ ok: true as const, value }), (error: unknown) => ({ ok: false as const, error }),
)
const tick = () => new Promise<void>((done) => setImmediate(done))
type Entry = 'quick' | 'ticket'
type Wire = { url: string; method?: string; authorization: string | null; company: string | null;
  organization: string | null; body: BodyInit | null | undefined; signal: AbortSignal | null | undefined }

async function fixture() {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const storage = () => {
    const values = new Map<string, string>()
    return { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  }
  const opens: { url: string; target?: string; features?: string }[] = []
  const navigation: { method: 'href' | 'replace'; url: string }[] = []
  const tabs: { href: string; closed: boolean; opener: unknown; unreadable: boolean }[] = []
  const requests: Wire[] = []
  const location = { origin, pathname: '/conf', search: '', hash: '', href: '' }
  let blocked = false, openHook: (() => void) | undefined, openerHook: (() => void) | undefined
  let navigationHook: (() => void) | undefined
  let reply: () => Promise<Response> = async () => json(meeting)
  for (const [key, value] of Object.entries({ localStorage: storage(), sessionStorage: storage(), window: {
    location,
    open(url: string, target?: string, features?: string) {
      opens.push({ url, target, features }); openHook?.()
      if (blocked) return null
      const state = { href: url, closed: false, opener: {} as unknown, unreadable: false }
      tabs.push(state)
      return { get opener() { return state.opener }, set opener(value: unknown) { state.opener = value; openerHook?.() },
        location: {
          get href() { if (state.unreadable) throw new DOMException('Synthetic cross-origin', 'SecurityError'); return state.href },
          set href(value: string) { state.href = value; navigation.push({ method: 'href', url: value }); navigationHook?.() },
          replace(value: string) { state.href = value; navigation.push({ method: 'replace', url: value }); navigationHook?.() },
        },
        close() { state.closed = true },
      }
    },
    setInterval() { assert.fail('These entry points must not start presence tracking') },
    addEventListener() { assert.fail('These entry points must not register presence listeners') },
  }, fetch: async (url: string | URL | Request, init?: RequestInit) => {
    const address = String(url)
    assert.equal(new URL(address).origin, origin, 'No real HTTP may reach fetch')
    assert.match(new URL(address).pathname, /^\/api\/(meetings$|chat\/tickets\/[^/]+\/video$)/)
    const headers = new Headers(init?.headers)
    requests.push({ url: address, method: init?.method, authorization: headers.get('Authorization'),
      company: headers.get('X-Company-Id'), organization: headers.get('X-Organization-Id'),
      body: init?.body, signal: init?.signal })
    return reply()
  } })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/meeting-start-context-vite-${process.pid}`, resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin), 'import.meta.env.BASE_URL': '"/"',
      'import.meta.env.VITE_VOICE_API_URL': 'undefined', 'import.meta.env.VITE_VOICE_DEV_TOKEN_URL': 'undefined' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const conference = await server.ssrLoadModule('/src/services/conferenceService.ts') as typeof import('../services/conferenceService.ts')
  api.setToken(token); api.setApiCompany(company); api.setApiOrganization(organization)
  const toastStart = toast.getHistory().length
  const redirects = new Map<object, () => void>()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((callback: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSet(callback, delay, ...args)
    const id = {}; redirects.set(id, callback); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!redirects.delete(id)) originalClear(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  let returns = 0
  return { api, conference, location, opens, tabs, navigation, requests, redirects,
    returned: () => returns,
    enter(entry: Entry) {
      const result = entry === 'quick' ? conference.startMeeting() : conference.startTicketMeeting(ticket)
      return result.then((value) => { returns++; return value })
    },
    respond(fn: typeof reply) { reply = fn }, block() { blocked = true },
    onOpen(fn: () => void) { openHook = fn }, onOpener(fn: () => void) { openerHook = fn },
    onNavigation(fn: () => void) { navigationHook = fn },
    messages: () => toast.getHistory().slice(toastStart).map((item) => item.title),
    async close() {
      redirects.clear(); start.mock.restore(); stop.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}
type Fixture = Awaited<ReturnType<typeof fixture>>
const probe = (name: string, run: (f: Fixture, t: TestContext) => Promise<void>) =>
  test(name, { timeout: 10_000 }, async (t) => { const f = await fixture(); t.after(() => f.close()); await run(f, t) })
const payload = (entry: Entry) => entry === 'quick' ? meeting : { joinUrl }
const destination = (entry: Entry) => entry === 'quick' ? meeting.moderator_url : joinUrl
const changes = {
  'token change': (f: Fixture) => f.api.setToken('synthetic-token-B'),
  logout: (f: Fixture) => f.api.clearToken(),
  'same-token login': (f: Fixture) => f.api.setToken(token),
  'clear-set new session': (f: Fixture) => { f.api.clearToken(); f.api.setToken(token) },
  'token A-B-A': (f: Fixture) => { f.api.setToken('synthetic-token-B'); f.api.setToken(token) },
  'company A-B-A': (f: Fixture) => { f.api.setApiCompany('synthetic-company-B'); f.api.setApiCompany(company) },
  'organization A-B-A': (f: Fixture) => { f.api.setApiOrganization('synthetic-org-B'); f.api.setApiOrganization(organization) },
}
const abort = (outcome: Awaited<ReturnType<typeof settled>>) => {
  assert.equal(outcome.ok, false, 'Retired entry must reject rather than release an old URL to its caller')
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
}
const quiet = (f: Fixture) => {
  assert.equal(f.redirects.size, 0); assert.deepEqual(f.messages(), []); assert.equal(f.location.href, '')
}
const wire = (f: Fixture, entry: Entry) => {
  assert.deepEqual(f.requests, [{ url: `${origin}${entry === 'quick' ? '/api/meetings' : `/api/chat/tickets/${encodeURIComponent(ticket)}/video`}`,
    method: 'POST', authorization: `Bearer ${token}`, company, organization,
    body: entry === 'quick' ? undefined : '{}', signal: undefined }], 'Exactly one mutation, original headers and original payload')
}
const stage = (f: Fixture, phase: 'fetch' | 'body', value: unknown, status = 200) => {
  const entered = deferred<void>(), response = deferred<Response>(), body = deferred<unknown>()
  f.respond(async () => {
    if (phase === 'fetch') { entered.resolve(); return response.promise }
    const res = json({}, status); res.json = () => { entered.resolve(); return body.promise }; return res
  })
  return { entered: entered.promise, release() { if (phase === 'fetch') response.resolve(json(value, status)); else body.resolve(value) } }
}

for (const entry of ['quick', 'ticket'] as const) {
  for (const blocked of [false, true]) {
    probe(`control: ${entry} current success, popup ${blocked ? 'blocked' : 'prepared'}`, async (f) => {
      if (blocked) f.block()
      const delayed = stage(f, 'body', payload(entry))
      const pending = f.enter(entry)
      assert.deepEqual(f.opens, [{ url: 'about:blank', target: '_blank', features: undefined }], 'Popup is synchronous before any await')
      if (!blocked) assert.equal(f.tabs[0].opener, null)
      await delayed.entered
      f.api.setApiCompany(company); f.api.setApiOrganization(organization)
      delayed.release()
      assert.deepEqual(await pending, entry === 'quick' ? meeting : undefined)
      wire(f, entry); quiet(f); assert.equal(f.returned(), 1)
      if (blocked) assert.deepEqual(f.opens[1], { url: destination(entry), target: '_blank', features: 'noopener,noreferrer' })
      else {
        assert.deepEqual(f.navigation, [{ method: entry === 'quick' ? 'href' : 'replace', url: destination(entry) }])
        assert.equal(f.tabs[0].closed, false)
      }
    })
  }
  for (const [name, change] of Object.entries(changes)) {
    for (const phase of ['fetch', 'body'] as const) for (const blocked of [false, true]) {
      probe(`boundary: ${entry} ${name} during ${phase}, popup ${blocked ? 'blocked' : 'prepared'}`, async (f, t) => {
        if (blocked) f.block()
        const delayed = stage(f, phase, payload(entry)), pending = settled(f.enter(entry))
        await delayed.entered; change(f); delayed.release(); const outcome = await pending
        t.diagnostic(JSON.stringify({ navigation: f.navigation, opens: f.opens, returned: f.returned(),
          error: !outcome.ok ? (outcome.error as Error).name : null }))
        wire(f, entry); quiet(f)
        assert.deepEqual(f.navigation, []); assert.equal(f.opens.length, 1)
        if (!blocked) { assert.equal(f.tabs[0].href, 'about:blank'); assert.equal(f.tabs[0].closed, true) }
        assert.equal(f.returned(), 0); abort(outcome)
      })
    }
  }
  for (const status of [401, 403]) for (const phase of ['fetch', 'body'] as const) {
    for (const name of ['same-token login', 'company A-B-A', 'organization A-B-A'] as const) {
      probe(`boundary: ${entry} stale ${status} ${phase} after ${name}`, async (f, t) => {
        const delayed = stage(f, phase, { detail: 'Synthetic old denial' }, status), pending = settled(f.enter(entry))
        await delayed.entered; changes[name](f); delayed.release(); const outcome = await pending; await tick()
        t.diagnostic(JSON.stringify({ token: f.api.getToken(), redirects: f.redirects.size, messages: f.messages(),
          error: !outcome.ok ? (outcome.error as Error).name : null }))
        wire(f, entry); assert.equal(f.api.getToken(), token); quiet(f)
        assert.deepEqual(f.navigation, []); assert.equal(f.tabs[0].closed, true)
        assert.equal(f.returned(), 0); abort(outcome)
      })
    }
  }
  for (const kind of ['401', '403', '422', 'network', 'abort', 'parse'] as const) {
    probe(`control: ${entry} current ${kind} preserves errors and blank cleanup`, async (f) => {
      const error = kind === 'abort' ? new DOMException('Synthetic abort', 'AbortError') : new TypeError('Synthetic fetch failed')
      const fields = [{ loc: ['body', 'synthetic'], msg: 'Synthetic required', type: 'missing' }]
      f.respond(async () => {
        if (kind === 'network' || kind === 'abort') throw error
        if (kind === 'parse') return new Response('{', { headers: { 'Content-Type': 'application/json' } })
        return json({ detail: kind === '422' ? fields : 'Synthetic current denial' }, Number(kind))
      })
      const outcome = await settled(f.enter(entry)); await tick(); wire(f, entry)
      assert.equal(outcome.ok, false)
      if (!outcome.ok) {
        if (kind === 'network' || kind === 'abort') assert.equal(outcome.error, error)
        else {
          assert.equal((outcome.error as Error).name, kind === '422' ? 'ApiValidationError' : 'ApiError')
          assert.equal((outcome.error as { status: number }).status, kind === 'parse' ? 502 : Number(kind))
          if (kind === '422') assert.deepEqual((outcome.error as { fieldErrors: unknown }).fieldErrors, fields)
          if (kind === '403' || kind === '401') assert.equal((outcome.error as Error).message, 'Synthetic current denial')
        }
      }
      assert.deepEqual(f.navigation, []); assert.equal(f.tabs[0].closed, true); assert.equal(f.returned(), 0)
      if (kind === '401') {
        assert.equal(f.api.getToken(), null); assert.equal(f.redirects.size, 1)
        assert.deepEqual(f.messages(), ['Сессия истекла'])
      } else { assert.equal(f.api.getToken(), token); quiet(f) }
    })
  }
  for (const failure of ['fetch', 'parse'] as const) {
    probe(`boundary: ${entry} late ${failure} rejection after new session is context abort`, async (f) => {
      const entered = deferred<void>(), response = deferred<Response>(), body = deferred<unknown>()
      f.respond(async () => {
        if (failure === 'fetch') { entered.resolve(); return response.promise }
        const res = json({}); res.json = () => { entered.resolve(); return body.promise }; return res
      })
      const pending = settled(f.enter(entry)); await entered.promise; changes['same-token login'](f)
      if (failure === 'fetch') response.reject(new TypeError('Synthetic late fetch'))
      else body.reject(new SyntaxError('Synthetic late parse'))
      abort(await pending); wire(f, entry); quiet(f); assert.equal(f.tabs[0].closed, true)
    })
  }
  for (const hook of ['open', 'opener'] as const) {
    probe(`boundary: ${entry} reentrant ${hook} retires context before mutation dispatch`, async (f) => {
      const change = () => changes['same-token login'](f)
      if (hook === 'open') f.onOpen(change); else f.onOpener(change)
      abort(await settled(f.enter(entry)))
      assert.deepEqual(f.requests, []); assert.deepEqual(f.navigation, [])
      assert.equal(f.tabs[0].opener, null); assert.equal(f.tabs[0].closed, true); quiet(f)
    })
  }
  for (const blocked of [false, true]) {
    probe(`boundary: ${entry} reentrant ${blocked ? 'fallback' : 'navigation'} suppresses return without undoing opened URL`, async (f) => {
      f.respond(async () => json(payload(entry)))
      if (blocked) { f.block(); f.onOpen(() => { if (f.opens.length > 1) changes['same-token login'](f) }) }
      else f.onNavigation(() => changes['same-token login'](f))
      abort(await settled(f.enter(entry))); wire(f, entry); quiet(f); assert.equal(f.returned(), 0)
      if (blocked) assert.equal(f.opens[1].url, destination(entry))
      else { assert.equal(f.tabs[0].href, destination(entry)); assert.equal(f.tabs[0].closed, false) }
    })
  }
  for (const unreadable of [false, true]) {
    probe(`boundary: ${entry} stale cleanup preserves ${unreadable ? 'cross-origin' : 'person-navigated'} tab`, async (f) => {
      const delayed = stage(f, 'fetch', payload(entry)), pending = settled(f.enter(entry))
      await delayed.entered
      f.tabs[0].href = 'https://meeting.example.test/person-opened'; f.tabs[0].unreadable = unreadable
      changes['same-token login'](f); delayed.release(); abort(await pending)
      assert.deepEqual(f.navigation, []); assert.equal(f.tabs[0].closed, false)
      assert.equal(f.tabs[0].href, 'https://meeting.example.test/person-opened'); quiet(f)
    })
  }
  probe(`boundary: ${entry} outer await hop rechecks context after successful body`, async (f) => {
    let changed = false
    f.respond(async () => {
      const res = json({}); res.json = () => Promise.resolve(payload(entry)).then((value) => {
        queueMicrotask(() => queueMicrotask(() => { changes['same-token login'](f); changed = true })); return value
      }); return res
    })
    abort(await settled(f.enter(entry))); assert.equal(changed, true)
    assert.deepEqual(f.navigation, []); assert.equal(f.returned(), 0); assert.equal(f.tabs[0].closed, true)
    wire(f, entry); quiet(f)
  })
}

probe('control: standalone createMeeting retains the unguarded JSON caller contract', async (f) => {
  const delayed = stage(f, 'body', meeting), pending = f.conference.createMeeting()
  await delayed.entered; changes['same-token login'](f); delayed.release()
  assert.deepEqual(await pending, meeting); wire(f, 'quick'); quiet(f)
  assert.deepEqual(f.opens, []); assert.deepEqual(f.navigation, [])
})

probe('control: quick demo route uses actual demo response with no popup or fetch', async (f) => {
  f.location.pathname = '/demo/conf'
  const value = await f.enter('quick')
  assert.equal(typeof value?.room, 'string'); assert.equal(typeof value?.moderator_url, 'string')
  assert.equal(typeof value?.guest_url, 'string'); assert.equal(f.returned(), 1)
  assert.deepEqual(f.opens, []); assert.deepEqual(f.requests, []); quiet(f)
})

probe('control: ticket demo keeps actual unsupported ACL-video route error and closes blank', async (f) => {
  f.location.pathname = '/demo/conf'
  const outcome = await settled(f.enter('ticket'))
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.match((outcome.error as Error).message, /демо|demo/i)
  assert.equal(f.opens.length, 1); assert.equal(f.tabs[0].opener, null); assert.equal(f.tabs[0].closed, true)
  assert.deepEqual(f.requests, []); assert.deepEqual(f.navigation, []); quiet(f)
})
