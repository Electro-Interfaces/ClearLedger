/** Offline/intercepted metadata only: real pinned Swagger bytes and own glue.
 * Does not simulate a successful OAuth/token exchange or product response.
 * Browser plugin not available; existing Playwright is used for rendered metadata.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { before, after, test } from 'node:test'
import vm from 'node:vm'
import { createHash, webcrypto } from 'node:crypto'
import { chromium } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const assets = path.join(root, 'server/app/docs_portal_assets')
const artifacts = path.join(root, '../.artifacts/service-openapi-browser')
const python = process.env.API_TEST_PYTHON || '/srv/projects/api-modernization-test-env-20261029/.venv/bin/python'
const origin = 'https://partner-schema.example.invalid'
let canonical, projected, html, glue, bundle, css, browser
const config = { clientId: 'synthetic-public-docs', sandboxReady: true, ready: true, environment: 'sandbox',
  setupRequired: [], docsScopes: ['openid', 'docs:read'], authorizationUrl: origin + '/api/oauth2/authorize',
  tokenUrl: origin + '/api/oauth2/token', revokeUrl: origin + '/api/oauth2/revoke',
  apiUrl: origin + '/api/v1', swaggerRedirectUri: origin + '/api/developer/docs/oauth2-redirect' }

before(async () => {
  await mkdir(artifacts, { recursive: true })
  // Existing hermetic exporter: no config/main/auth/engine imports, no I/O.
  const exported = execFileSync(python, ['-c', `import json,runpy
m=runpy.run_path(${JSON.stringify(path.join(root, 'scripts/export-partner-openapi.py'))})
s=m['export_schema']()
from app.product_api.app import public_client_openapi
print(json.dumps({'canonical':s,'projected':public_client_openapi(s)}))`], { cwd: artifacts, encoding: 'utf8' })
  ;({ canonical, projected } = JSON.parse(exported))
  config.businessScopes = Object.keys(projected.components.securitySchemes.ProductOAuth.flows.authorizationCode.scopes)
  // Render the actual router's HTML; direct function invocation tests its bytes,
  // not authorization. The separate ASGI/Python suite tests the HTTP docs gate.
  html = execFileSync(python, ['-c', `import asyncio,json,sys
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import event
from app import database
def forbidden(*a,**kw): raise RuntimeError('SQL forbidden in metadata fixture')
event.listen(database.engine.sync_engine,'do_connect',forbidden)
from app.routers import docs_portal_router as r
data=json.load(sys.stdin)
class DB:
 async def run_sync(self,callback): return data['config']
async def main():
 with patch.object(r.portal,'product_schema',return_value=data['schema']),patch.object(r.portal,'issuer',return_value=data['origin']):
  response=await r.ui(SimpleNamespace(app=None,query_params={}),DB())
  sys.stdout.write(response.body.decode())
asyncio.run(main())`], { cwd: artifacts, encoding: 'utf8', input: JSON.stringify({ config, schema: projected, origin }),
    env: { PATH: process.env.PATH, LANG: 'C.UTF-8', PYTHONPATH: path.join(root, 'server'),
      DATABASE_URL: 'postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/schema_only_test', SECRET_KEY: 'synthetic-schema-only' } })
  glue = process.env.PORTAL_GLUE_BASELINE
    ? execFileSync('git', ['show', `${process.env.PORTAL_GLUE_BASELINE}:clearledger/server/app/docs_portal_assets/portal-init.js`], { cwd: root, encoding: 'utf8' })
    : await readFile(path.join(assets, 'portal-init.js'), 'utf8')
  bundle = await readFile(path.join(assets, 'swagger-ui-bundle.js'))
  css = await readFile(path.join(assets, 'swagger-ui.css'))
  const manifest = JSON.parse(await readFile(path.join(assets, 'manifest.json'), 'utf8'))
  assert.equal(createHash('sha256').update(bundle).digest('hex'), manifest.sha256['swagger-ui-bundle.js'])
  assert.equal(createHash('sha256').update(css).digest('hex'), manifest.sha256['swagger-ui.css'])
  browser = await chromium.launch({ headless: true })
})
after(async () => { await browser?.close() })

function interceptorFixture() {
  let options, oauthConfig
  const messages = [], fetches = [], opens = []
  const ui = { authActions: { logout() {} }, initOAuth(value) { oauthConfig = value } }
  const window = { location: { origin }, parent: {}, open: (...args) => { opens.push(args); return { closed: false, location: { replace() {} } } },
    addEventListener() {} }
  const nodes = { 'docs-config': { textContent: JSON.stringify(config) }, 'docs-mode': {}, 'docs-auth-logout': { addEventListener() {} } }
  const SwaggerUIBundle = (value) => { options = value; return ui }
  SwaggerUIBundle.presets = { apis: {} }
  const noStorage = new Proxy({}, { get() { throw new Error('Browser credential storage is forbidden') } })
  vm.runInNewContext(glue, { window, document: { getElementById: (id) => nodes[id] }, SwaggerUIBundle,
    URL, URLSearchParams, Headers, crypto: webcrypto, btoa, TextEncoder, localStorage: noStorage, sessionStorage: noStorage,
    setInterval() {}, setTimeout() { return 1 }, clearTimeout() {},
    fetch: async (...args) => { fetches.push(args); return { ok: true, json: async () => ({ sandboxReady: true }) } },
  }, { filename: 'actual-portal-init.js' })
  const actions = options.plugins[0]().statePlugins.auth.wrapActions
  const system = { errActions: { newAuthErr: (error) => messages.push(error) } }
  const authorize = (overrides = {}) => actions.authorizeOauth2((value) => value)({
    auth: { name: 'ProductOAuth', clientId: config.clientId, docsGeneration: 0, docsExpiresAt: Date.now() + 60000, ...overrides },
    token: { access_token: 'synthetic-business-memory-only', token_type: 'Bearer', scope: 'objects:read', expires_in: 60 },
  })
  return { options, oauthConfig, actions, authorize, system, messages, fetches, opens,
    intercept: (request) => options.requestInterceptor(request) }
}

test('public code interceptor preserves PKCE and strips empty secret placeholders', async () => {
  const f = interceptorFixture()
  const request = await f.intercept({ url: config.tokenUrl, method: 'POST', headers: {}, body: new URLSearchParams({
    client_id: config.clientId, grant_type: 'authorization_code', redirect_uri: config.swaggerRedirectUri,
    code: 'synthetic-code', code_verifier: 'synthetic-pkce-verifier-43-characters-long-0000', client_secret: '',
  }).toString() })
  assert.equal(new URLSearchParams(request.body).has('client_secret'), false)
  assert.equal(new URLSearchParams(request.body).has('grant_id'), false)
  assert.equal(request.credentials, 'omit')
  assert.equal(f.options.persistAuthorization, false)
  assert.equal(f.oauthConfig.usePkceWithAuthorizationCodeGrant, true)
})

test('actual interceptor rejects M2M/Basic/secret/grant_id and duplicate token parameters', async () => {
  const f = interceptorFixture()
  const code = { client_id: config.clientId, grant_type: 'authorization_code', redirect_uri: config.swaggerRedirectUri,
    code: 'synthetic-code', code_verifier: 'synthetic-verifier' }
  for (const [body, headers] of [
    [{ grant_type: 'client_credentials', grant_id: '00000000-0000-0000-0000-000000000001' }, {}],
    [code, { Authorization: 'Basic synthetic-do-not-send' }],
    [{ ...code, client_secret: 'synthetic-do-not-send' }, {}],
    [{ ...code, grant_id: '00000000-0000-0000-0000-000000000001' }, {}],
  ]) await assert.rejects(f.intercept({ url: config.tokenUrl, method: 'POST', headers, body: new URLSearchParams(body).toString() }))
  await assert.rejects(f.intercept({ url: config.tokenUrl, method: 'POST', headers: {},
    body: new URLSearchParams(code).toString() + '&grant_type=client_credentials' }))
  assert.equal(f.fetches.length, 0)
})

test('query credentials and URL userinfo never leave the browser, allowed business GET survives', async () => {
  const f = interceptorFixture(); f.authorize()
  for (const key of ['access_token', 'token', 'client_secret', 'grant_id', 'nonce']) {
    await assert.rejects(f.intercept({ url: config.apiUrl + '/objects?' + key + '=synthetic-do-not-send', method: 'GET',
      headers: { Authorization: 'Bearer synthetic-business-memory-only' } }))
  }
  await assert.rejects(f.intercept({ url: origin.replace('https://', 'https://synthetic:secret@') + '/api/v1/objects',
    headers: { Authorization: 'Bearer synthetic-business-memory-only' } }))
  assert.equal(f.fetches.length, 0)
  const allowed = await f.intercept({ url: config.apiUrl + '/objects?limit=25', method: 'GET',
    headers: { Authorization: 'Bearer synthetic-business-memory-only' } })
  assert.equal(allowed.credentials, 'omit')
  assert.equal(f.fetches.length, 1) // docs-session metadata recheck, never a product/OAuth response.
})

test('schema fetch strips Core/Basic Authorization including Headers instances', async () => {
  const f = interceptorFixture()
  for (const headers of [{ Authorization: 'Bearer synthetic-core' }, { AUTHORIZATION: 'Basic synthetic' }, new Headers({ Authorization: 'Bearer synthetic-core' })]) {
    const result = await f.intercept({ url: origin + '/api/developer/docs/openapi.json', method: 'GET', headers })
    assert.equal(new Headers(result.headers).has('Authorization'), false)
    assert.equal(result.credentials, 'same-origin')
  }
})

test('machine or secret-bearing auth state cannot enter public Swagger authorization', () => {
  const f = interceptorFixture()
  assert.throws(() => f.authorize({ name: 'ProductServiceOAuth' }))
  assert.throws(() => f.authorize({ clientSecret: 'synthetic-do-not-store' }))
  f.actions.authPopup(() => {}, f.system)(config.authorizationUrl + '?client_id=' + config.clientId + '&scope=objects%3Aread',
    { auth: { name: 'ProductServiceOAuth', clientId: config.clientId } })
  assert.equal(f.opens.length, 0)
  assert.equal(f.messages.length, 1)
})

async function renderedFixture(t, viewport = { width: 1200, height: 900 }) {
  const context = await browser.newContext({ viewport })
  t.after(() => context.close())
  const page = await context.newPage()
  const errors = [], prohibited = [], outgoing = []
  page.on('pageerror', (error) => errors.push(error.message))
  await context.route('**/*', async (route) => {
    const target = new URL(route.request().url())
    outgoing.push({ url: target.href, headers: route.request().headers() })
    const files = {
      '/api/developer/docs/ui': ['text/html', html],
      '/api/developer/docs/openapi.json': ['application/json', JSON.stringify(projected)],
      '/api/developer/docs/openapi.server.json': ['application/json', JSON.stringify(canonical)],
      '/api/developer/docs/assets/portal-init.js': ['text/javascript', glue],
      '/api/developer/docs/assets/swagger-ui-bundle.js': ['text/javascript', bundle],
      '/api/developer/docs/assets/swagger-ui.css': ['text/css', css],
    }
    const file = target.origin === origin && files[target.pathname]
    if (file) return route.fulfill({ status: 200, contentType: file[0], body: file[1] })
    if (target.pathname === '/favicon.ico') return route.fulfill({ status: 204 })
    prohibited.push(target.pathname)
    await route.abort('blockedbyclient') // No OAuth success or backend responses.
  })
  await page.goto(origin + '/api/developer/docs/ui')
  await page.locator('.opblock').nth(11).waitFor()
  return { page, errors, prohibited, outgoing }
}

test('pinned Swagger renders12 operations/6groups with CodePKCE only, no visible secret input', async (t) => {
  const f = await renderedFixture(t)
  assert.equal(await f.page.title(), 'Документация API')
  assert.equal(await f.page.locator('.opblock').count(), 12)
  assert.equal(await f.page.locator('.opblock-tag').count(), 6)
  const canonicalLink = f.page.locator('a[href="/api/developer/docs/openapi.server.json"]')
  assert.equal(await canonicalLink.count(), 1)
  await f.page.getByRole('button', { name: 'Authorize', exact: true }).first().click()
  assert.equal(await f.page.locator('.auth-container').count(), 1)
  assert.match(await f.page.locator('.auth-container').innerText(), /ProductOAuth/)
  assert.doesNotMatch(await f.page.locator('.auth-container').innerText(), /ProductServiceOAuth|clientCredentials|client_secret/)
  assert.equal(await f.page.locator('input[data-name="clientSecret"]:visible').count(), 0)
  assert.deepEqual(f.errors, [])
  assert.deepEqual(f.prohibited, [])
  assert.equal(await f.page.locator('vite-error-overlay').count(), 0)
  await f.page.screenshot({ path: path.join(artifacts, 'public-code-only.png'), fullPage: true })
  await f.page.locator('.auth-container .checkbox label').filter({ hasText: 'objects:read' }).click()
  const popup = f.page.context().waitForEvent('page')
  const authorizationRequest = f.page.context().waitForEvent('request', {
    predicate: (request) => new URL(request.url()).pathname === '/api/oauth2/authorize', timeout: 5000,
  })
  await f.page.locator('.dialog-ux .auth-btn-wrapper button.authorize').click()
  await popup
  const sent = await authorizationRequest
  const authorization = { url: sent.url(), headers: sent.headers() }
  assert.ok(authorization, 'Pinned UI reaches own public Code+PKCE popup wrapper')
  const target = new URL(authorization.url)
  assert.equal(target.searchParams.get('client_id'), config.clientId)
  assert.equal(target.searchParams.get('response_type'), 'code')
  assert.equal(target.searchParams.get('code_challenge_method'), 'S256')
  assert.equal(target.searchParams.has('client_secret'), false)
  assert.equal(target.searchParams.has('access_token'), false)
  assert.equal(authorization.headers.authorization, undefined)
  assert.equal(f.outgoing.some((request) => new URL(request.url).pathname === '/api/oauth2/token'), false)
})

export { renderedFixture, artifacts }
