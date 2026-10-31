import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test, { mock } from 'node:test'
import { createServer } from 'vite'

// Actual modules, with synthetic browser/transport boundaries only. No service,
// auth, toast or timer replacements; no env files, listening server or real HTTP.
const root = fileURLToPath(new URL('../../', import.meta.url))
const baseline = process.env.AUDITOR_EXPORT_BASELINE
const source = baseline ? execFileSync('git', ['show', `${baseline}:clearledger/src/services/spaceAuditorService.ts`],
  { cwd: root, encoding: 'utf8' }) : undefined
const archive = new Uint8Array([31, 139, 8, 0, 255, 42, 0, 128])
const response = () => new Response(archive, { headers: {
  'Content-Type': 'application/gzip', 'Content-Disposition': 'attachment; filename="server-name.tar.gz"',
} })
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
})
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const settled = <T>(promise: Promise<T>) => promise.then(
  (value) => ({ ok: true as const, value }), (error: unknown) => ({ ok: false as const, error }),
)
type Request = { url: string; init?: RequestInit }
type Anchor = { href: string; download: string; click(): void; remove(): void }

async function fixture() {
  const originals = new Map(['window', 'document', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const memory = () => {
    const data = new Map<string, string>(), removals: string[] = []
    return { removals, getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => data.set(key, value),
      removeItem: (key: string) => { removals.push(key); data.delete(key) } }
  }
  const local = memory(), session = memory()
  const location = { origin: 'https://ui.example.test', pathname: '/auditor', search: '', hash: '', href: '' }
  const requests: Request[] = [], events: string[] = [], urls = new Set<string>(), attached = new Set<Anchor>()
  const anchors: Anchor[] = []
  let reply: (request: Request) => Promise<Response> = async () => response()
  let hook: ((event: string) => void) | undefined, captured: Blob | undefined
  const emit = (event: string) => { events.push(event); hook?.(event) }
  const document = { createElement(tag: string): Anchor {
    assert.equal(tag, 'a'); emit('create')
    const anchor = { href: '', download: '',
      click() { assert.ok(urls.has(this.href)); emit('click') },
      remove() { attached.delete(this); emit('remove') },
    }
    anchors.push(anchor); return anchor
  }, body: { appendChild(anchor: Anchor) { attached.add(anchor); emit('append'); return anchor } } }
  for (const [key, value] of Object.entries({ window: { location }, document, localStorage: local,
    sessionStorage: session, fetch: async (url: string, init?: RequestInit) => {
      const request = { url: String(url), init }; requests.push(request)
      assert.equal(request.url, '/auditor/api/export-work', 'Auditor proxy stays relative to UI origin, separate from Core base')
      return reply(request)
    },
  })) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  const createURL = mock.method(URL, 'createObjectURL', (blob: Blob) => {
    captured = blob; emit('url'); urls.add('blob:auditor-synthetic'); return 'blob:auditor-synthetic'
  })
  const revokeURL = mock.method(URL, 'revokeObjectURL', (url: string) => {
    assert.equal(url, 'blob:auditor-synthetic'); assert.ok(urls.delete(url), 'URL must be revoked exactly once'); emit('revoke')
  })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/auditor-export-context-${process.pid}`,
    plugins: [{ name: 'auditor-export-immutable-source', load(id) {
      if (source && id.endsWith('/src/services/spaceAuditorService.ts')) return source
    } }], resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': '"https://core.example.test"', 'import.meta.env.BASE_URL': '"/"' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const auditor = await server.ssrLoadModule('/src/services/spaceAuditorService.ts') as typeof import('../services/spaceAuditorService.ts')
  return { api, auditor, events, requests, local, location, anchors, attached, urls,
    captured: () => captured, count: (event: string) => events.filter((value) => value === event).length,
    respond(fn: typeof reply) { reply = fn }, hook(fn: typeof hook) { hook = fn },
    mark(event: string) { events.push(event) },
    reset() {
      hook = undefined; reply = async () => response(); captured = undefined
      events.length = 0; requests.length = 0; anchors.length = 0; attached.clear(); urls.clear()
      api.setToken('synthetic-A'); api.setApiCompany('company-A'); api.setApiOrganization('org-A')
      local.removals.length = 0; location.href = ''
    },
    checkSession(expected = 'synthetic-A') {
      assert.equal(api.getToken(), expected); assert.equal(location.href, '')
      assert.equal(local.removals.filter((key) => key === 'clearledger-token').length, 0, 'Auditor denial must not clear Core auth')
    },
    async close() {
      createURL.mock.restore(); revokeURL.mock.restore(); await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}
type Fixture = Awaited<ReturnType<typeof fixture>>
const changes = {
  principal: (f: Fixture) => f.api.setToken('synthetic-B'),
  company: (f: Fixture) => f.api.setApiCompany('company-B'),
  organization: (f: Fixture) => f.api.setApiOrganization('org-B'),
}
function aborted(outcome: Awaited<ReturnType<typeof settled>>, f: Fixture) {
  assert.equal(f.count('url'), 0, `Stale operation must create no object URL; observed: ${f.events.join(', ')}`)
  assert.equal(f.count('click'), 0, 'Stale operation must initiate no download')
  assert.equal(outcome.ok, false)
  if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
}

test('Auditor exportWork actual-service context and download effects', { timeout: 45_000 }, async (t) => {
  const f = await fixture(); t.after(() => f.close())
  const pattern = process.env.AUDITOR_EXPORT_CASE_PATTERN ? new RegExp(process.env.AUDITOR_EXPORT_CASE_PATTERN) : undefined
  const probe = (name: string, run: () => Promise<void>) => t.test(name, {
    timeout: 8_000, skip: pattern ? !pattern.test(name) : false,
  }, async (child) => {
    f.reset()
    try { await run() } finally {
      child.diagnostic(JSON.stringify({ requests: f.requests.length, effects: f.events,
        liveUrls: f.urls.size, attachedAnchors: f.attached.size }))
    }
  })

  await probe('control: ordinary tar preserves relative proxy, headers, bytes, filename and one revoke', async () => {
    await f.auditor.exportWork()
    assert.equal(f.requests.length, 1)
    assert.deepEqual(f.requests[0].init, { headers: { Authorization: 'Bearer synthetic-A' } })
    assert.equal(f.requests[0].init?.method, undefined); assert.equal(f.requests[0].init?.body, undefined)
    assert.equal(f.requests[0].init?.credentials, undefined)
    assert.deepEqual([...new Uint8Array(await f.captured()!.arrayBuffer())], [...archive])
    assert.equal(f.captured()!.type, 'application/gzip')
    assert.equal(f.anchors[0].download, 'auditor-work.tar.gz')
    assert.equal(f.count('url'), 1); assert.equal(f.count('click'), 1); assert.equal(f.count('revoke'), 1)
    assert.equal(f.urls.size, 0); assert.equal(f.attached.size, 0); f.checkSession()
  })
  await probe('control: successful non-JSON content remains archive bytes', async () => {
    f.respond(async () => new Response(archive, { headers: { 'Content-Type': 'application/octet-stream' } }))
    await f.auditor.exportWork()
    assert.deepEqual([...new Uint8Array(await f.captured()!.arrayBuffer())], [...archive])
    assert.equal(f.count('revoke'), 1); f.checkSession()
  })
  await probe('control: later request uses new principal, preserving proxy auth profile', async () => {
    changes.principal(f); changes.company(f); changes.organization(f)
    await f.auditor.exportWork()
    assert.deepEqual(f.requests[0].init?.headers, { Authorization: 'Bearer synthetic-B' })
    assert.equal(f.count('click'), 1); assert.equal(f.count('revoke'), 1); f.checkSession('synthetic-B')
  })
  await probe('control: identical company and organization setters preserve pending export', async () => {
    const entered = deferred<void>(), released = deferred<Response>()
    f.respond(async () => { entered.resolve(); return released.promise })
    const result = settled(f.auditor.exportWork()); await entered.promise
    f.api.setApiCompany('company-A'); f.api.setApiOrganization('org-A'); released.resolve(response())
    assert.equal((await result).ok, true); assert.equal(f.count('click'), 1); assert.equal(f.count('revoke'), 1)
  })
  for (const [status, body, message] of [
    [403, { error: 'Synthetic policy denied' }, 'Synthetic policy denied'],
    [500, { error: 'Synthetic export failed' }, 'Synthetic export failed'],
    [401, { error: 'Synthetic auditor token denied' }, 'Synthetic auditor token denied'],
  ] as const) await probe(`control: HTTP ${status} preserves Auditor error and Core session`, async () => {
    f.respond(async () => json(status, body))
    await assert.rejects(f.auditor.exportWork(), { name: 'Error', message })
    assert.deepEqual(f.events, []); f.checkSession()
  })
  await probe('control: non-JSON 500 keeps status fallback without a download', async () => {
    f.respond(async () => new Response('<html>unavailable</html>', { status: 500 }))
    await assert.rejects(f.auditor.exportWork(), { message: 'Не выгрузилось (500)' })
    assert.deepEqual(f.events, []); f.checkSession()
  })
  await probe('control: network rejection propagates unchanged', async () => {
    const error = new TypeError('Synthetic connection failed'); f.respond(async () => { throw error })
    await assert.rejects(f.auditor.exportWork(), (caught) => caught === error)
    assert.deepEqual(f.events, []); f.checkSession()
  })
  await probe('control: archive body rejection propagates unchanged', async () => {
    const error = new TypeError('Synthetic body failed')
    f.respond(async () => { const res = response(); res.blob = async () => { throw error }; return res })
    await assert.rejects(f.auditor.exportWork(), (caught) => caught === error)
    assert.deepEqual(f.events, []); f.checkSession()
  })
  await probe('control: delayed error body preserves error without context transition', async () => {
    const entered = deferred<void>(), released = deferred<object>()
    f.respond(async () => { const res = json(403, {}); res.json = async () => { entered.resolve(); return released.promise }; return res })
    const result = settled(f.auditor.exportWork()); await entered.promise
    released.resolve({ error: 'Synthetic delayed denied' }); const outcome = await result
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).message, 'Synthetic delayed denied')
    assert.deepEqual(f.events, []); f.checkSession()
  })

  for (const phase of ['fetch', 'blob'] as const) for (const [name, change] of Object.entries(changes)) {
    await probe(`race: ${name} during deferred ${phase} blocks old download`, async () => {
      const entered = deferred<void>(), releaseFetch = deferred<Response>(), releaseBlob = deferred<Blob>()
      f.respond(async () => {
        if (phase === 'fetch') { entered.resolve(); return releaseFetch.promise }
        const res = response(); res.blob = async () => { entered.resolve(); return releaseBlob.promise }; return res
      })
      const result = settled(f.auditor.exportWork()); await entered.promise
      change(f); f.mark('context-change')
      releaseFetch.resolve(response()); releaseBlob.resolve(new Blob([archive]))
      const outcome = await result
      assert.equal(f.requests.length, 1); assert.deepEqual(f.requests[0].init?.headers, { Authorization: 'Bearer synthetic-A' })
      assert.equal(f.events[0], 'context-change'); aborted(outcome, f)
      f.checkSession(name === 'principal' ? 'synthetic-B' : 'synthetic-A')
    })
  }
  for (const [name, change] of Object.entries({
    'company A-B-A': (f: Fixture) => { f.api.setApiCompany('company-B'); f.api.setApiCompany('company-A') },
    'organization A-B-A': (f: Fixture) => { f.api.setApiOrganization('org-B'); f.api.setApiOrganization('org-A') },
    'principal A-B-A': (f: Fixture) => { f.api.setToken('synthetic-B'); f.api.setToken('synthetic-A') },
    'clear-set same token': (f: Fixture) => { f.api.clearToken(); f.api.setToken('synthetic-A'); f.local.removals.length = 0 },
    'set same token as new session': (f: Fixture) => f.api.setToken('synthetic-A'),
  })) await probe(`race: ${name} during blob blocks old download`, async () => {
    const entered = deferred<void>(), released = deferred<Blob>()
    f.respond(async () => { const res = response(); res.blob = async () => { entered.resolve(); return released.promise }; return res })
    const result = settled(f.auditor.exportWork()); await entered.promise; change(f)
    released.resolve(new Blob([archive])); aborted(await result, f); f.checkSession()
  })
  for (const [name, change] of Object.entries(changes)) await probe(`race: ${name} during error body rejects stale outcome without Core logout`, async () => {
    const entered = deferred<void>(), released = deferred<object>()
    f.respond(async () => { const res = json(403, {}); res.json = async () => { entered.resolve(); return released.promise }; return res })
    const result = settled(f.auditor.exportWork()); await entered.promise; change(f)
    released.resolve({ error: 'Synthetic old policy error' }); const outcome = await result
    assert.deepEqual(f.events, []); f.checkSession(name === 'principal' ? 'synthetic-B' : 'synthetic-A')
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError', 'Old error must be superseded by context cancellation')
  })
  for (const [name, change] of Object.entries(changes)) await probe(`race: ${name} after blob resolves before download continuation`, async () => {
    f.respond(async () => {
      const res = response(); res.blob = async () => {
        queueMicrotask(() => { change(f); f.mark('context-change') })
        return new Blob([archive])
      }; return res
    })
    const result = await settled(f.auditor.exportWork())
    assert.equal(f.events[0], 'context-change', 'Transition must precede any download effect')
    aborted(result, f); f.checkSession(name === 'principal' ? 'synthetic-B' : 'synthetic-A')
  })
  for (const event of ['url', 'create'] as const) await probe(`race: context changes at ${event} boundary prevent click and release URL once`, async () => {
    f.hook((current) => { if (current === event) { changes.principal(f); f.mark('context-change') } })
    const result = await settled(f.auditor.exportWork())
    assert.equal(f.count('click'), 0, 'No click after context changes at a resource boundary')
    assert.equal(result.ok, false)
    if (!result.ok) assert.equal((result.error as Error).name, 'AbortError')
    assert.equal(f.count('url'), 1); assert.equal(f.count('revoke'), 1); assert.equal(f.urls.size, 0)
    assert.equal(f.attached.size, 0); f.checkSession('synthetic-B')
  })
  for (const event of ['url', 'create', 'click'] as const) await probe(`cleanup: ${event} exception propagates and releases every created URL once`, async () => {
    const error = new Error(`Synthetic ${event} failure`)
    f.hook((current) => { if (current === event) throw error })
    await assert.rejects(f.auditor.exportWork(), (caught) => caught === error)
    assert.equal(f.count('revoke'), event === 'url' ? 0 : 1, 'Every URL actually returned by createObjectURL must be revoked exactly once')
    assert.equal(f.urls.size, 0); assert.equal(f.attached.size, 0); f.checkSession()
  })
  await probe('cleanup: revoke exception is propagated without duplicate revoke', async () => {
    const error = new Error('Synthetic revoke failure')
    f.hook((event) => { if (event === 'revoke') throw error })
    await assert.rejects(f.auditor.exportWork(), (caught) => caught === error)
    assert.equal(f.count('click'), 1); assert.equal(f.count('revoke'), 1); assert.equal(f.urls.size, 0)
  })
  // Candidate controls for the granted finally path. They are separate from the
  // original 34-case baseline: that implementation never called anchor.remove.
  await probe('candidate cleanup: created anchor is removed once after ordinary export', async () => {
    await f.auditor.exportWork()
    assert.equal(f.count('create'), 1); assert.equal(f.count('click'), 1)
    assert.equal(f.count('remove'), 1); assert.equal(f.count('revoke'), 1)
    assert.equal(f.attached.size, 0); assert.equal(f.urls.size, 0)
  })
  await probe('candidate cleanup: remove exception still revokes URL exactly once', async () => {
    const error = new Error('Synthetic anchor removal failed')
    f.hook((event) => { if (event === 'remove') throw error })
    await assert.rejects(f.auditor.exportWork(), (caught) => caught === error)
    assert.equal(f.count('click'), 1); assert.equal(f.count('remove'), 1); assert.equal(f.count('revoke'), 1)
    assert.equal(f.urls.size, 0); f.checkSession()
  })
  await probe('candidate return: context change during cleanup cannot report old export as current', async () => {
    f.hook((event) => { if (event === 'remove') changes.principal(f) })
    const outcome = await settled(f.auditor.exportWork())
    // Click has already happened and cannot be withdrawn; only completion is fenced.
    assert.equal(f.count('click'), 1); assert.equal(f.count('remove'), 1); assert.equal(f.count('revoke'), 1)
    assert.equal(outcome.ok, false)
    if (!outcome.ok) assert.equal((outcome.error as Error).name, 'AbortError')
    f.checkSession('synthetic-B')
  })
})
