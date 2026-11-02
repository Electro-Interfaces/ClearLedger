import assert from 'node:assert/strict'
import test, { mock, type TestContext } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { toast } from 'sonner'

// Actual modules, including the confService ↔ conferenceService cycle; no service,
// transport, reset hook or toast substitution. Every URL and credential is synthetic.
const root = fileURLToPath(new URL('../../', import.meta.url))
const origin = 'https://core.example.test'
const company = 'company A / synthetic', organization = 'organization-A'
const session = 'session-synthetic-A'
const meeting = {
  room: 'room-synthetic-A', session_id: session, moderator: true,
  moderator_url: 'https://meeting.example.test/moderator-synthetic',
  guest_url: 'https://meeting.example.test/guest-synthetic',
}
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})
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
type Wire = { url: string; method: string | undefined; authorization: string | null;
  company: string | null; organization: string | null; body: BodyInit | null | undefined;
  keepalive: boolean | undefined; signal: AbortSignal | null | undefined }

async function fixture() {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const storage = () => {
    const values = new Map<string, string>()
    return { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  }
  const intervals = new Map<number, () => void>()
  const listeners = new Map<string, { callback: () => void; once: boolean }[]>()
  const tabs: { closed: boolean; opener: unknown; location: { href: string }; close(): void }[] = []
  const opens: { url: string; target?: string; features?: string }[] = []
  const requests: Wire[] = []
  let nextTimer = 0, blockPopup = false
  let reply: (wire: Wire) => Promise<Response> = async () => json(meeting)
  const newTab = () => {
    const tab = { closed: false, opener: {} as unknown, location: { href: 'about:blank' },
      close() { tab.closed = true } }
    tabs.push(tab)
    return tab
  }
  const location = { origin, pathname: '/conf', search: '', hash: '', href: '' }
  for (const [key, value] of Object.entries({ localStorage: storage(), sessionStorage: storage(),
    window: { location,
      open(url: string, target?: string, features?: string) {
        opens.push({ url, target, features })
        if (blockPopup) return null
        const tab = newTab(); tab.location.href = url; return tab
      },
      setInterval(callback: () => void, delay: number) {
        assert.equal(delay, 30_000, 'Presence has a bounded, manually advanced clock')
        const id = ++nextTimer; intervals.set(id, callback); return id
      },
      clearInterval(id: number) { intervals.delete(id) },
      addEventListener(type: string, callback: () => void, options?: { once?: boolean }) {
        const items = listeners.get(type) ?? []; items.push({ callback, once: !!options?.once }); listeners.set(type, items)
      },
      removeEventListener(type: string, callback: () => void) {
        listeners.set(type, (listeners.get(type) ?? []).filter((item) => item.callback !== callback))
      },
    },
    fetch: async (url: string | URL | Request, init?: RequestInit) => {
      const address = String(url)
      assert.equal(new URL(address).origin, origin, 'No real HTTP or meeting URL may reach fetch')
      const headers = new Headers(init?.headers)
      const wire: Wire = { url: address, method: init?.method,
        authorization: headers.get('Authorization'), company: headers.get('X-Company-Id'),
        organization: headers.get('X-Organization-Id'), body: init?.body,
        keepalive: init?.keepalive, signal: init?.signal }
      requests.push(wire)
      return reply(wire)
    },
  })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/conf-context-vite-${process.pid}`,
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin), 'import.meta.env.BASE_URL': '"/"',
      'import.meta.env.VITE_VOICE_API_URL': 'undefined', 'import.meta.env.VITE_VOICE_DEV_TOKEN_URL': 'undefined' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const conf = await server.ssrLoadModule('/src/services/confService.ts') as typeof import('../services/confService.ts')
  const conference = await server.ssrLoadModule('/src/services/conferenceService.ts') as typeof import('../services/conferenceService.ts')
  const cache = await server.ssrLoadModule('/src/services/cacheReset.ts') as typeof import('../services/cacheReset.ts')
  api.setToken('core-synthetic-A'); api.setApiCompany(company); api.setApiOrganization(organization)
  cache.setServicesCompany(company)
  const toastCount = toast.getHistory().length
  const redirects = new Map<object, () => void>()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  const start = mock.method(globalThis, 'setTimeout', ((callback: () => void, delay?: number, ...args: unknown[]) => {
    if (delay !== 1500) return originalSet(callback, delay, ...args)
    const id = {}; redirects.set(id, callback); return id
  }) as typeof setTimeout)
  const stop = mock.method(globalThis, 'clearTimeout', ((id: object) => {
    if (!redirects.delete(id)) originalClear(id as ReturnType<typeof setTimeout>)
  }) as typeof clearTimeout)
  return { api, conf, conference, cache, requests, opens, tabs, intervals, listeners, location, redirects,
    newTab, respond(value: typeof reply) { reply = value }, blockPopup() { blockPopup = true },
    messages() { return toast.getHistory().slice(toastCount) },
    advance() { for (const callback of [...intervals.values()]) callback() },
    pagehide() {
      const items = listeners.get('pagehide') ?? []
      listeners.set('pagehide', items.filter((item) => !item.once))
      for (const item of items) item.callback()
    },
    async close() {
      intervals.clear(); listeners.clear()
      redirects.clear(); start.mock.restore(); stop.mock.restore()
      // No pagehide during teardown: a fixture cleanup must never produce a leave.
      await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}
type Fixture = Awaited<ReturnType<typeof fixture>>
const probe = (name: string, run: (f: Fixture, t: TestContext) => Promise<void>) =>
  test(name, { timeout: 8_000 }, async (t) => {
    const f = await fixture(); t.after(() => f.close()); await run(f, t)
  })
const path = (action: string) => `${origin}/api/conf/sessions/${session}/${action}?company_id=${encodeURIComponent(company)}`
const track = (f: Fixture) => {
  const tab = f.newTab()
  f.conf.следитьЗаВкладкой(company, session, tab as unknown as Window)
  return tab
}

probe('control: ordinary open-tab ping carries current auth, company/org and no body', async (f) => {
  track(f); f.advance(); await tick()
  assert.deepEqual(f.requests, [{ url: path('ping'), method: 'POST', authorization: 'Bearer core-synthetic-A',
    company, organization, body: undefined, keepalive: undefined, signal: undefined }])
  assert.equal(f.intervals.size, 1)
})

probe('control: closed-tab leave uses authenticated keepalive and stops its timer', async (f) => {
  const tab = track(f); tab.close(); f.advance(); await tick(); f.advance()
  assert.deepEqual(f.requests, [{ url: path('leave'), method: 'POST', authorization: 'Bearer core-synthetic-A',
    company: null, organization: null, body: undefined, keepalive: true, signal: undefined }])
  assert.equal(f.intervals.size, 0)
})

probe('control: pagehide sends keepalive once and stops ping while child stays open', async (f) => {
  const tab = track(f); f.pagehide(); f.pagehide(); f.advance(); await tick()
  assert.equal(tab.closed, false); assert.equal(f.intervals.size, 0)
  assert.equal(f.requests.length, 1); assert.equal(f.requests[0].url, path('leave'))
  assert.equal(f.requests[0].keepalive, true); assert.equal(f.requests[0].authorization, 'Bearer core-synthetic-A')
})

probe('control: missing token dispatches unauthenticated ping and leave under existing contract', async (f) => {
  f.api.clearToken(); const tab = track(f); f.advance(); await tick(); tab.close(); f.advance(); await tick()
  assert.deepEqual(f.requests.map((r) => [r.url, r.authorization, r.keepalive]), [
    [path('ping'), null, undefined], [path('leave'), null, true],
  ])
  assert.equal(f.intervals.size, 0)
})

for (const entry of ['meeting', 'room', 'calendar'] as const) {
  probe(`control: ${entry} opens blank synchronously then moderator URL and presence after response`, async (f) => {
    const response = deferred<Response>(); f.respond(() => response.promise)
    const pending = enter(f, entry)
    assert.deepEqual(f.opens, [{ url: 'about:blank', target: '_blank', features: undefined }])
    assert.equal(f.tabs[0].opener, null); assert.equal(f.tabs[0].location.href, 'about:blank')
    assert.equal(f.intervals.size, 0); assert.equal(f.requests.length, 1)
    assert.equal(f.requests[0].authorization, 'Bearer core-synthetic-A'); assert.equal(f.requests[0].body, undefined)
    response.resolve(json(meeting)); assert.deepEqual(await pending, meeting)
    assert.equal(f.tabs[0].location.href, meeting.moderator_url)
    assert.equal(f.intervals.size, 1); f.advance(); await tick()
    assert.equal(f.requests[1].url, path('ping'))
  })
}
function enter(f: Fixture, entry: 'meeting' | 'room' | 'calendar') {
  if (entry === 'meeting') return f.conf.joinMeeting(company, 'event-synthetic')
  if (entry === 'room') return f.conf.joinRoom(company, 'room-synthetic')
  return f.conference.startEventMeeting(company, 'event-synthetic')
}

probe('control: externally preopened popup is reused without opening another blank', async (f) => {
  const tab = f.newTab()
  await f.conf.joinMeeting(company, 'event-synthetic', tab as unknown as Window)
  assert.deepEqual(f.opens, []); assert.equal(tab.opener, null)
  assert.equal(tab.location.href, meeting.moderator_url); assert.equal(f.intervals.size, 1)
})

probe('control: blocked popup preserves moderator fallback and null-tab leave', async (f) => {
  f.blockPopup(); await f.conf.joinMeeting(company, 'event-synthetic')
  assert.deepEqual(f.opens, [{ url: 'about:blank', target: '_blank', features: undefined },
    { url: meeting.moderator_url, target: '_blank', features: 'noopener,noreferrer' }])
  f.advance(); await tick()
  assert.equal(f.requests.length, 2); assert.equal(f.requests[1].url, path('leave'))
  assert.equal(f.requests[1].keepalive, true); assert.equal(f.intervals.size, 0)
})

probe('control: participant join delivers existing explanation through actual toast module', async (f) => {
  f.respond(async () => json({ ...meeting, moderator: false }))
  await f.conf.joinMeeting(company, 'event-synthetic')
  assert.equal(f.messages().length, 1)
  assert.equal(f.messages()[0].title, 'Вы вошли участником: ведущий уже в комнате.')
  assert.equal(f.tabs[0].location.href, meeting.moderator_url)
})

for (const failure of ['abort', 'network', 'http'] as const) {
  probe(`control: ${failure} join error closes blank without navigation or tracking`, async (f) => {
    const error = failure === 'abort' ? new DOMException('Synthetic abort', 'AbortError') : new TypeError('Synthetic fetch failure')
    f.respond(async () => { if (failure === 'http') return json({ detail: 'Synthetic denial' }, 403); throw error })
    const outcome = await settled(f.conf.joinMeeting(company, 'event-synthetic'))
    assert.equal(outcome.ok, false)
    if (!outcome.ok) {
      if (failure === 'http') assert.equal((outcome.error as { status: number }).status, 403)
      else assert.equal(outcome.error, error)
    }
    assert.equal(f.tabs[0].closed, true); assert.equal(f.tabs[0].location.href, 'about:blank')
    assert.equal(f.intervals.size, 0); assert.equal(f.listeners.get('pagehide')?.length ?? 0, 0)
    assert.equal(f.messages().length, 0); assert.equal(f.requests.length, 1)
  })
}

probe('control: presence abort/network/HTTP failures are swallowed without retry or dangling timers', async (f) => {
  for (const error of [new DOMException('Synthetic abort', 'AbortError'), new TypeError('Synthetic fetch failure'), null]) {
    f.respond(async () => { if (error) throw error; return json({ detail: 'Synthetic failure' }, 503) })
    const tab = track(f); const before = f.requests.length
    f.advance(); await tick(); tab.close(); f.advance(); await tick()
    assert.equal(f.requests.length - before, 2); assert.equal(f.intervals.size, 0)
  }
  assert.equal(f.api.getToken(), 'core-synthetic-A')
})

const switches = {
  principal(f: Fixture) {
    // AuthContext.applySession + CompanyContext.activateContext, same company.
    f.api.setToken('core-synthetic-B'); f.api.setApiCompany(company)
    f.cache.resetServiceCaches(); f.cache.setServicesCompany(company)
  },
  company(f: Fixture) {
    f.api.setApiCompany('company-synthetic-B'); f.cache.resetServiceCaches(); f.cache.setServicesCompany('company-synthetic-B')
  },
  organization(f: Fixture) { f.api.setApiOrganization('organization-B') },
  logout(f: Fixture) { f.api.clearToken(); f.cache.resetServiceCaches(); f.api.setApiCompany(null) },
}

// These are intended boundary assertions, not an assertion that the baseline is safe.
// On the immutable baseline each red test prints the actual old URL/body/header
// or browser side effect before asserting suppression. No proposed API is imported.
for (const [name, change] of Object.entries(switches)) {
  for (const action of ['ping', 'closed-leave', 'pagehide-leave'] as const) {
    probe(`boundary: ${name} change before deferred ${action} must retire old presence`, async (f, t) => {
      const tab = track(f); change(f)
      if (action === 'closed-leave') tab.close()
      if (action === 'pagehide-leave') f.pagehide(); else f.advance()
      await tick()
      t.diagnostic(`observed deferred dispatch: ${JSON.stringify(f.requests)}`)
      assert.deepEqual(f.requests, [], 'Retired presence must not dispatch under a changed context')
    })
  }
}

for (const entry of ['meeting', 'room', 'calendar'] as const) {
  for (const phase of ['response', 'body'] as const) {
    probe(`boundary: ${entry} ${phase} completing after principal change must not navigate or start presence`, async (f, t) => {
      const entered = deferred<void>(), response = deferred<Response>(), body = deferred<unknown>()
      f.respond(async () => {
        if (phase === 'response') { entered.resolve(); return response.promise }
        const res = json({}); res.json = () => { entered.resolve(); return body.promise }; return res
      })
      const old = settled(enter(f, entry)); await entered.promise
      switches.principal(f)
      if (phase === 'response') response.resolve(json(meeting)); else body.resolve(meeting)
      const outcome = await old
      t.diagnostic(`observed completion: ${JSON.stringify({ requests: f.requests, href: f.tabs[0].location.href,
        timers: f.intervals.size, outcome, messages: f.messages().map((m) => m.title) })}`)
      assert.equal(f.requests.length, 1, 'An already sent join is not claimed to be canceled on the server')
      assert.equal(f.requests[0].authorization, 'Bearer core-synthetic-A')
      assert.equal(f.tabs[0].location.href, 'about:blank', 'Retired join must not navigate to the old moderator URL')
      assert.equal(f.tabs[0].closed, true, 'Only the prepared blank popup is closed')
      assert.equal(f.intervals.size, 0, 'Retired join must not start presence')
      assert.equal(outcome.ok, false)
      if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    })
  }
}

probe('boundary: stale join with blocked popup must not open old moderator fallback after company change', async (f, t) => {
  f.blockPopup(); const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  switches.company(f); response.resolve(json(meeting)); await pending
  t.diagnostic(`observed opens: ${JSON.stringify(f.opens)}`)
  assert.deepEqual(f.opens, [{ url: 'about:blank', target: '_blank', features: undefined }])
  assert.equal(f.intervals.size, 0)
})

probe('boundary: participant join completing after organization change must not show stale explanation', async (f, t) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  switches.organization(f); response.resolve(json({ ...meeting, moderator: false })); await pending
  t.diagnostic(`observed messages: ${JSON.stringify(f.messages().map((m) => m.title))}`)
  assert.deepEqual(f.messages(), [], 'Retired join must not explain entry into an old room to the new context')
})

probe('control: context change after ping dispatch does not replay or cancel the already sent action', async (f) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  track(f); f.advance(); assert.equal(f.requests.length, 1)
  switches.principal(f); response.resolve(json({ ok: true })); await tick()
  assert.equal(f.requests.length, 1); assert.equal(f.requests[0].url, path('ping'))
  assert.equal(f.requests[0].authorization, 'Bearer core-synthetic-A')
  assert.equal(f.requests[0].signal, undefined)
  assert.equal(f.api.getToken(), 'core-synthetic-B')
})

for (const [name, change] of Object.entries({
  'principal A-B-A': (f: Fixture) => { switches.principal(f); f.api.setToken('core-synthetic-A') },
  'company A-B-A': (f: Fixture) => { switches.company(f); f.api.setApiCompany(company) },
  'organization A-B-A': (f: Fixture) => { switches.organization(f); f.api.setApiOrganization(organization) },
  'same-token new login': (f: Fixture) => { f.api.setToken('core-synthetic-A') },
})) {
  probe(`boundary: ${name} via setters retires deferred presence even when final headers match`, async (f) => {
    const tab = track(f); change(f)
    f.advance(); f.pagehide(); await tick()
    assert.deepEqual(f.requests, []); assert.equal(tab.closed, false, 'An already open meeting stays open')
    assert.equal(f.intervals.size, 0); assert.equal(f.listeners.get('pagehide')?.length ?? 0, 0)
  })
  probe(`boundary: ${name} via setters rejects pending join even when final headers match`, async (f) => {
    const response = deferred<Response>(); f.respond(() => response.promise)
    const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
    change(f); response.resolve(json(meeting))
    const outcome = await pending
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    assert.equal(f.tabs[0].location.href, 'about:blank'); assert.equal(f.tabs[0].closed, true)
    assert.equal(f.requests.length, 1); assert.equal(f.intervals.size, 0)
  })
}

probe('control: repeated same company/org setters keep ordinary presence and pending join valid', async (f) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = f.conf.joinMeeting(company, 'event-synthetic')
  f.api.setApiCompany(company); f.api.setApiOrganization(organization)
  response.resolve(json(meeting)); assert.deepEqual(await pending, meeting)
  f.api.setApiCompany(company); f.api.setApiOrganization(organization)
  f.advance(); await tick(); f.pagehide(); await tick()
  assert.deepEqual(f.requests.map((r) => r.url), [
    `${origin}/api/conf/meetings/event-synthetic/join?company_id=${encodeURIComponent(company)}`, path('ping'), path('leave'),
  ])
  assert.equal(f.requests[2].keepalive, true); assert.equal(f.tabs[0].closed, false)
})

for (const entry of ['meeting', 'room', 'calendar'] as const) {
  probe(`boundary: ${entry} outer await hop suppresses navigation after body has resolved`, async (f) => {
    let changed = false
    f.respond(async () => {
      const response = json({})
      response.json = () => Promise.resolve(meeting).then((value) => {
        queueMicrotask(() => queueMicrotask(() => { switches.principal(f); changed = true }))
        return value
      })
      return response
    })
    const outcome = await settled(enter(f, entry))
    assert.equal(changed, true); assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    assert.equal(f.tabs[0].closed, true); assert.equal(f.tabs[0].location.href, 'about:blank')
    assert.equal(f.intervals.size, 0); assert.equal(f.requests.length, 1)
  })
}

probe('boundary: late old401 becomes context abort without logging out new principal', async (f) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  switches.principal(f); response.resolve(json({ detail: 'Synthetic old denial' }, 401))
  const outcome = await pending
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
  assert.equal(f.api.getToken(), 'core-synthetic-B'); assert.equal(f.tabs[0].closed, true)
  assert.equal(f.intervals.size, 0); assert.equal(f.messages().length, 0)
})

probe('boundary: retired pending join does not close a popup already navigated by the person', async (f) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  f.tabs[0].location.href = 'https://meeting.example.test/already-opened-by-person'
  switches.principal(f); response.resolve(json(meeting)); const outcome = await pending
  assert.equal(outcome.ok, false); assert.equal(f.tabs[0].closed, false)
  assert.equal(f.tabs[0].location.href, 'https://meeting.example.test/already-opened-by-person')
  assert.equal(f.intervals.size, 0)
})

probe('review401: same-token login before old401 must preserve new session and suppress redirect/toast', async (f, t) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  f.api.setToken('core-synthetic-A')
  response.resolve(json({ detail: 'Synthetic old401' }, 401))
  const outcome = await pending; await tick()
  t.diagnostic(`same-token old401: ${JSON.stringify({ requests: f.requests, token: f.api.getToken(),
    redirects: f.redirects.size, messages: f.messages().map((m) => m.title), outcome })}`)
  assert.equal(f.api.getToken(), 'core-synthetic-A', 'New login with same credential is still a new session')
  assert.equal(f.redirects.size, 0); assert.deepEqual(f.messages(), [])
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
})

probe('review401: setter ABA during old401 error body must preserve session and suppress redirect/toast', async (f, t) => {
  const entered = deferred<void>(), body = deferred<unknown>()
  f.respond(async () => {
    const response = json({}, 401); response.json = () => { entered.resolve(); return body.promise }; return response
  })
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  await entered.promise
  f.api.setApiCompany('company-synthetic-B'); f.api.setApiCompany(company)
  body.resolve({ detail: 'Synthetic old error body' })
  const outcome = await pending; await tick()
  t.diagnostic(`setter ABA old401: ${JSON.stringify({ requests: f.requests, token: f.api.getToken(),
    redirects: f.redirects.size, messages: f.messages().map((m) => m.title), outcome })}`)
  assert.equal(f.api.getToken(), 'core-synthetic-A')
  assert.equal(f.redirects.size, 0); assert.deepEqual(f.messages(), [])
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
})

probe('review401: ordinary current401 keeps ApiError logout toast and redirect contract', async (f, t) => {
  f.respond(async () => json({ detail: 'Synthetic current401' }, 401))
  const outcome = await settled(f.conf.joinMeeting(company, 'event-synthetic')); await tick()
  t.diagnostic(`current401: ${JSON.stringify({ token: f.api.getToken(), redirects: f.redirects.size,
    messages: f.messages().map((m) => m.title), error: !outcome.ok ? (outcome.error as Error).name : null })}`)
  assert.equal(outcome.ok, false)
  if (!outcome.ok) {
    assert.equal((outcome.error as Error).name, 'ApiError')
    assert.equal((outcome.error as { status: number }).status, 401)
  }
  assert.equal(f.api.getToken(), null); assert.equal(f.redirects.size, 1)
  assert.deepEqual(f.messages().map((m) => m.title), ['Сессия истекла'])
  assert.equal(f.tabs[0].closed, true); assert.equal(f.intervals.size, 0)
})

probe('control: default post preserves current401/422/403/204/MIME/parse/network contracts', async (f) => {
  const detail = [{ loc: ['body', 'synthetic'], msg: 'Synthetic field required', type: 'missing' }]
  const network = new TypeError('Synthetic fetch failure'), abort = new DOMException('Synthetic abort', 'AbortError')
  const cases = [
    { reply: async () => json({ detail: 'Synthetic expired' }, 401), status: 401, name: 'ApiError' },
    { reply: async () => json({ detail }, 422), status: 422, name: 'ApiValidationError' },
    { reply: async () => json({ detail: 'Synthetic forbidden' }, 403), status: 403, name: 'ApiError' },
    { reply: async () => new Response(null, { status: 204 }), status: 204, name: '' },
    { reply: async () => new Response('Synthetic HTML', { headers: { 'Content-Type': 'text/html' } }), status: 502, name: 'ApiError' },
    { reply: async () => new Response('{', { headers: { 'Content-Type': 'application/json' } }), status: 502, name: 'ApiError' },
    { reply: async () => { throw network }, status: 0, name: 'TypeError' },
    { reply: async () => { throw abort }, status: 0, name: 'AbortError' },
  ]
  for (const example of cases) {
    f.api.setToken('core-synthetic-A'); f.respond(example.reply)
    const outcome = await settled(f.api.post('/api/synthetic-post?scope=synthetic', { synthetic: 'body' })); await tick()
    const wire = f.requests.at(-1)!
    assert.equal(wire.body, '{"synthetic":"body"}'); assert.equal(wire.method, 'POST')
    assert.equal(wire.authorization, 'Bearer core-synthetic-A'); assert.equal(wire.company, company)
    assert.equal(wire.organization, organization); assert.equal(wire.keepalive, undefined)
    if (example.status === 204) { assert.deepEqual(outcome, { ok: true, value: undefined }); continue }
    assert.equal(outcome.ok, false)
    if (!outcome.ok) {
      assert.equal((outcome.error as Error).name, example.name)
      if (example.status) assert.equal((outcome.error as { status: number }).status, example.status)
      if (example.status === 422) assert.deepEqual((outcome.error as { fieldErrors: unknown }).fieldErrors, detail)
      if (example.name === 'TypeError') assert.equal(outcome.error, network)
      if (example.name === 'AbortError') assert.equal(outcome.error, abort)
    }
    assert.equal(f.api.getToken(), example.status === 401 ? null : 'core-synthetic-A')
    assert.equal(f.redirects.size, example.status === 401 ? 1 : 0)
  }
  assert.deepEqual(f.messages().map((m) => m.title), ['Сессия истекла'])
})

probe('boundary: guarded JSON parse rejection after reset stays AbortError rather than parser502', async (f) => {
  const entered = deferred<void>(), body = deferred<unknown>()
  f.respond(async () => {
    const response = json({}); response.json = () => { entered.resolve(); return body.promise }; return response
  })
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic')); await entered.promise
  f.api.setToken('core-synthetic-A'); body.reject(new SyntaxError('Synthetic truncated JSON'))
  const outcome = await pending
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
  assert.equal(f.api.getToken(), 'core-synthetic-A'); assert.equal(f.redirects.size, 0)
  assert.equal(f.tabs[0].closed, true); assert.equal(f.intervals.size, 0)
})

probe('boundary: guarded fetch rejection after reset becomes context abort without session effects', async (f) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const pending = settled(f.conf.joinMeeting(company, 'event-synthetic'))
  f.api.setToken('core-synthetic-A'); response.reject(new TypeError('Synthetic late fetch failure'))
  const outcome = await pending
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
  assert.equal(f.api.getToken(), 'core-synthetic-A'); assert.equal(f.redirects.size, 0)
  assert.deepEqual(f.messages(), []); assert.equal(f.intervals.size, 0)
})

probe('review401: already sent ping retains its original guard before late error effects', async (f) => {
  const response = deferred<Response>(); f.respond(() => response.promise)
  const tab = track(f); f.advance(); assert.equal(f.requests.length, 1)
  f.api.setApiOrganization('organization-B'); f.api.setApiOrganization(organization)
  response.resolve(json({ detail: 'Synthetic old ping401' }, 401)); await tick()
  assert.equal(f.api.getToken(), 'core-synthetic-A'); assert.equal(f.redirects.size, 0)
  assert.deepEqual(f.messages(), []); assert.equal(f.requests.length, 1)
  f.advance(); f.pagehide(); await tick()
  assert.equal(f.requests.length, 1); assert.equal(f.intervals.size, 0)
  assert.equal(tab.closed, false)
})
