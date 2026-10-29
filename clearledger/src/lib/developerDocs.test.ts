/** Intercepted unit checks only. Real HTTPS OAuth/Swagger acceptance is in pytest. */
import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { DocsMetadata } from '../services/developerDocsService.ts'

const root = fileURLToPath(new URL('../../', import.meta.url))
const origin = 'https://space.example.test'
const transactionKey = 'elsy.docs.pkce'
const config: DocsMetadata = { ready: true, environment: 'sandbox', sandboxReady: true, setupRequired: [], clientId: 'public-docs',
  authorizationUrl: origin + '/api/oauth2/authorize', tokenUrl: origin + '/api/oauth2/token', revokeUrl: origin + '/api/oauth2/revoke',
  redirectUri: origin + '/developer/api/callback', docsScopes: ['openid', 'docs:read'], coreUserId: 'core-user-A' }
const session = { expiresAt: new Date(Date.now() + 180000).toISOString(), csrfToken: 'csrf-proof', userId: 'core-user-A', companyId: 'company-A', clientId: 'public-docs' }
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })

test('docs client: PKCE one-use state, separate credentials and generation', async (t) => {
  const originals = new Map(['window', 'history', 'localStorage', 'sessionStorage', 'fetch'].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const storage = () => {
    const data = new Map<string, string>()
    return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) }, clear: () => data.clear() }
  }
  const local = storage(), pending = storage()
  let assigned = ''
  const location = { origin, pathname: '/developer/api', search: '', assign: (url: string) => { assigned = url } }
  const history = { replaceState: (_state: unknown, _title: string, path: string) => { location.pathname = path; location.search = '' } }
  const calls: { path: string; options: RequestInit }[] = []
  let customToken: (() => Promise<Response>) | undefined
  Object.defineProperties(globalThis, {
    window: { configurable: true, value: { location } }, history: { configurable: true, value: history },
    localStorage: { configurable: true, value: local }, sessionStorage: { configurable: true, value: pending },
    fetch: { configurable: true, writable: true, value: async (url: string, options: RequestInit = {}) => {
      const path = new URL(String(url), origin).pathname; calls.push({ path, options })
      if (path.endsWith('/metadata')) return json(config)
      if (path.endsWith('/oauth2/token')) return customToken ? customToken() : json({ access_token: 'synthetic-partner-docs', token_type: 'Bearer', scope: 'openid docs:read' })
      if (path.endsWith('/session')) return options.method === 'DELETE' ? new Response(null, { status: 204 }) : json(session)
      if (path.endsWith('/revoke')) return json({})
      throw new Error('Unexpected request in unit fixture')
    } },
  })
  const server = await createServer({ root, configFile: false, envFile: false, appType: 'custom', logLevel: 'silent',
    cacheDir: `/tmp/docs-unit-vite-${process.pid}`, resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin) }, server: { middlewareMode: true, hmr: false, watch: null } })
  const service = await server.ssrLoadModule('/src/services/developerDocsService.ts') as typeof import('../services/developerDocsService.ts')
  const core = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  t.after(async () => { await server.close(); for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key)
  } })
  t.beforeEach(async () => {
    await service.logoutDocs(); local.clear(); pending.clear(); calls.length = 0; customToken = undefined
    local.setItem('clearledger-token', 'synthetic-Core-session'); location.pathname = '/developer/api'; location.search = ''; assigned = ''
  })
  async function prepare() {
    await service.beginDocsLogin(await service.getDocsMetadata())
    const saved = JSON.parse(pending.getItem(transactionKey)!)
    location.pathname = '/developer/api/callback'
    return { saved, query: `?code=synthetic-one-use-code&state=${encodeURIComponent(saved.state)}` }
  }

  await t.test('public callback is public, protected consent/api remain protected', () => {
    assert.equal(core.isPublicPage('/developer/api/callback'), true)
    assert.equal(core.isPublicPage('/developer/authorize'), false)
    assert.equal(core.isPublicPage('/developer/api'), false)
  })
  await t.test('crypto state/verifier/nonce only in sessionStorage, no tokens or secret', async () => {
    const { saved } = await prepare()
    const url = new URL(assigned)
    assert.equal(url.origin, origin); assert.equal(url.searchParams.get('code_challenge_method'), 'S256')
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(saved.verifier))
    assert.equal(url.searchParams.get('code_challenge'), Buffer.from(digest).toString('base64url'))
    assert.equal(url.searchParams.get('state'), saved.state); assert.equal(url.searchParams.get('nonce'), saved.nonce)
    assert.equal(saved.state.length, 43); assert.ok(saved.expiresAt <= Date.now() + 300000)
    assert.deepEqual(Object.keys(saved).sort(), ['expiresAt', 'generation', 'nonce', 'state', 'verifier'])
    assert.equal(local.getItem('clearledger-token'), 'synthetic-Core-session')
  })
  await t.test('code exchange exactly once, memory-only partner and Core transport separation', async () => {
    const { query } = await prepare()
    const first = service.finishDocsLogin(query), second = service.finishDocsLogin(query)
    assert.equal(first, second)
    assert.deepEqual(await first, session)
    assert.equal(pending.getItem(transactionKey), null)
    await assert.rejects(service.finishDocsLogin(query))
    assert.equal(calls.filter((call) => call.path.endsWith('/oauth2/token')).length, 1)
    const token = calls.find((call) => call.path.endsWith('/oauth2/token'))!
    assert.equal(token.options.credentials, 'omit'); assert.equal(new Headers(token.options.headers).has('Authorization'), false)
    assert.equal(new URLSearchParams(token.options.body as URLSearchParams).has('client_secret'), false)
    const cookie = calls.find((call) => call.path.endsWith('/session') && call.options.method === 'POST')!
    assert.equal(new Headers(cookie.options.headers).get('Authorization'), 'Bearer synthetic-partner-docs')
    assert.equal(new Headers(cookie.options.headers).get('X-Docs-CSRF'), 'bootstrap')
    assert.equal(local.getItem('clearledger-token'), 'synthetic-Core-session')
    await service.logoutDocs(session, config)
    assert.ok(calls.some((call) => call.options.method === 'DELETE' && new Headers(call.options.headers).get('X-Docs-CSRF') === 'csrf-proof'))
    assert.ok(calls.some((call) => call.path.endsWith('/revoke')))
  })
  await t.test('wrong state preserves current transaction; expired state is removed without exchange', async () => {
    const { saved, query } = await prepare()
    await assert.rejects(service.finishDocsLogin('?code=other&state=wrong'))
    assert.ok(pending.getItem(transactionKey))
    pending.setItem(transactionKey, JSON.stringify({ ...saved, expiresAt: Date.now() - 1 }))
    await assert.rejects(service.finishDocsLogin(query))
    assert.equal(pending.getItem(transactionKey), null)
    assert.equal(calls.some((call) => call.path.endsWith('/oauth2/token')), false)
  })
  await t.test('late token after logout is revoked, cannot establish cookie session', async () => {
    const { query } = await prepare()
    let resolve!: (value: Response) => void
    let started!: () => void
    const incoming = new Promise<Response>((yes) => { resolve = yes })
    const sent = new Promise<void>((yes) => { started = yes })
    customToken = async () => { started(); return incoming }
    const finished = service.finishDocsLogin(query)
    const rejection = assert.rejects(finished)
    await sent; await service.logoutDocs()
    resolve(json({ access_token: 'late-docs-token', token_type: 'Bearer', scope: 'openid docs:read' }))
    await rejection
    assert.equal(calls.some((call) => call.path.endsWith('/session') && call.options.method === 'POST'), false)
    assert.ok(calls.some((call) => call.path.endsWith('/revoke')))
  })
})
