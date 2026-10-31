import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync, statSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { inventory, writeInventory, PIN } from '../inventory-api-consumers.mjs'

function fixture(t, files) {
  const root = mkdtempSync('/tmp/api-consumer-fixture-')
  t.after(() => rmSync(root, { recursive: true, force: true }))
  for (const [file, source] of Object.entries(files)) {
    const path = resolve(root, file)
    mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, source)
  }
  return { root, scan: (options = {}) => inventory({ root, ...options }) }
}

test('shared aliases/namespaces resolve lexical imports; unrelated and shadowed get are not network', (t) => {
  const f = fixture(t, { 'src/use.ts': `
import { get as read, post, isApiEnabled } from '@/services/apiClient'
import * as api from './services/apiClient'
import { get as foreignGet } from 'some-library'
read('/api/objects')
const alias = read
alias(
  '/api/alias'
)
post('/api/docs', {})
api.downloadBlob('/api/export')
api['upload']('/api/upload', form)
api[operation]('/api/dynamic-member')
function shadow(read: (x: string) => unknown) { read('/not-network') }
function ordinary() { const get = (x: string) => x; get('/not-network') }
function nested(api: {get: Function}) { api.get('/not-network') }
foreignGet('/not-network')
isApiEnabled()
`, 'src/services/apiClient.ts': 'export const get = () => {}; export const post = () => {}' })
  const result = f.scan()
  assert.equal(result.summary.counts.shared, 6)
  assert.equal(result.summary.counts.direct, 0)
  assert.equal(result.summary.counts.unresolvedWrappers, 0)
  assert.deepEqual(result.records.map((r) => r.method), ['GET', 'GET', 'POST', 'GET', 'POST', null])
  assert.equal(result.records.at(-1).methodReason, 'dynamic-shared-member')
  assert.ok(result.records[1].endLine > result.records[1].line)
  assert.equal(result.diagnostics.length, 0)
})

test('templates, const concatenation and runtime paths retain conservative known/dynamic/unknown states', (t) => {
  const f = fixture(t, { 'src/routes.ts': `
import { get } from './services/apiClient'
const prefix = '/api/docs'
get(prefix + '/list')
get(\`/api/docs/\${id}?company=\${company}\`)
get(runtimePath)
get(\`\${base}/api/equipment\`)
get(choosePath())
` })
  const result = f.scan()
  assert.deepEqual(result.records.map((r) => [r.pathname, r.pathState]), [
    ['/api/docs/list', 'static'], ['/api/docs/{dynamic}?{redacted}', 'dynamic'], [null, 'unknown'],
    ['{dynamic}/api/equipment', 'dynamic'], [null, 'unknown'],
  ])
  assert.equal(result.summary.counts.unknownTransportPaths, 2)
  assert.equal(result.summary.counts.dynamicTransportPaths, 2)
})

test('native fetch method defaults require proof; spreads, Request-like and shadowed globals remain conservative', (t) => {
  const f = fixture(t, { 'src/native.js': `
fetch('/api/a')
window.fetch('/api/b', {method: 'post'})
globalThis.fetch('/api/c', {cache: 'no-store'})
const download = fetch
download('/api/d', options)
fetch('/api/e', {...options})
fetch('/api/f', {method: 'PATCH', ...options})
fetch('/api/g', {...options, method: 'put'})
fetch(request)
fetch('/api/i', {method})
fetch('/api/j', {__proto__: options})
function local(fetch) { fetch('/not-network') }
function shadow(window) { window.fetch('/not-network') }
function shadowGlobal(globalThis) { globalThis.fetch('/not-network') }
` })
  const result = f.scan()
  assert.deepEqual(result.records.map((r) => r.method), ['GET', 'POST', 'GET', null, null, null, 'PUT', null, null, null])
  assert.equal(result.summary.counts.direct, 10)
  assert.equal(result.summary.counts.unknownTransportMethods, 6)
})

test('stream constructors and XHR open link to lexical constructor binding, not variable spelling', (t) => {
  const f = fixture(t, { 'src/protocols.ts': `
new EventSource('/api/events')
new WebSocket('wss://synthetic.example.test/api/socket?access=secret')
const xhr = new XMLHttpRequest()
xhr.open('POST', '/api/files')
function shadow(xhr: {open: Function}) { xhr.open('DELETE', '/not-network') }
function unrelated() { const xhr = {open() {}}; xhr.open('GET', '/not-network') }
function shadowConstructors(WebSocket: Function) { new WebSocket('/not-network') }
` })
  const result = f.scan()
  assert.deepEqual(result.records.map((r) => r.transport), ['EventSource', 'WebSocket', 'XMLHttpRequest', 'XMLHttpRequest.open'])
  assert.deepEqual(result.records.map((r) => r.method), ['GET', null, null, 'POST'])
  assert.equal(result.records[1].pathname, '{origin}/api/socket?{redacted}')
  assert.equal(result.records[2].pathname, null)
  assert.equal(result.summary.counts.streamConstructors, 2)
})

test('service wrapper imports and local transport wrappers are bounded unresolved candidates, not defects', (t) => {
  const f = fixture(t, { 'src/consumer.tsx': `
import { load } from '@/services/docsService'
import * as sites from './services/sitesService'
load('company')
sites.list()
function request(path: string) { return fetch(path) }
request('/api/local')
function ordinaryGet(x: string) { return x }
ordinaryGet('/not-network')
`, 'src/services/docsService.ts': 'export const load = () => 1' })
  const result = f.scan()
  assert.equal(result.summary.counts.direct, 1)
  assert.equal(result.summary.counts.unresolvedWrappers, 3)
  assert.ok(result.records.filter((r) => r.category === 'wrapper').every((r) => r.method === null && r.pathname === null))
  const bounded = f.scan({ maxWrappers: 1 })
  assert.equal(bounded.summary.counts.unresolvedWrappers, 1)
  assert.equal(bounded.summary.counts.omittedWrappers, 2)
})

test('privacy, no source execution and exclusions; source paths stay relative', (t) => {
  const f = fixture(t, {
    'src/privacy.ts': `
globalThis.__inventoryExecuted = true
throw new Error('must never execute')
fetch('https://USER_CANARY:PASS_CANARY@tenant-canary.example.test/api/docs?key=QUERY_CANARY#HASH_CANARY')
fetch('/api/192.0.2.123/docs?token=QUERY_CANARY')
fetch('data:text/plain,CONTENT_CANARY')
`,
    'src/ignored.test.ts': 'fetch("/should-not-appear")',
    'src/generated/schema.ts': 'fetch("/should-not-appear")',
    'src/model.d.ts': 'declare const a: string',
    'src/fixtures/seed.ts': 'fetch("/should-not-appear")',
    '.env': 'ENV_CANARY=not-a-source-file',
  })
  const outside = resolve(f.root, 'outside.ts')
  writeFileSync(outside, 'fetch("/outside-canary")'); symlinkSync(outside, resolve(f.root, 'src/link.ts'))
  const before = readFileSync(resolve(f.root, 'src/privacy.ts'))
  const result = f.scan(), text = JSON.stringify(result)
  for (const canary of ['USER_CANARY', 'PASS_CANARY', 'tenant-canary.example.test', 'QUERY_CANARY', 'HASH_CANARY',
    'CONTENT_CANARY', '192.0.2.123', 'ENV_CANARY', '/should-not-appear', '/outside-canary', f.root]) assert.equal(text.includes(canary), false, canary)
  assert.equal(globalThis.__inventoryExecuted, undefined)
  assert.deepEqual(readFileSync(resolve(f.root, 'src/privacy.ts')), before)
  assert.equal(result.summary.source.files, 1)
  assert.deepEqual(result.exclusions.filter((e) => e.reason === 'symlink-not-followed'), [{ file: 'src/link.ts', reason: 'symlink-not-followed' }])
  assert.ok(result.manifest.every((row) => row.file.startsWith('src/') && /^[a-f\d]{64}$/.test(row.sha256)))
})

test('deterministic canonical private output and bounded summary; changing source bytes changes manifest hash', (t) => {
  const f = fixture(t, { 'src/z.ts': "fetch('/api/z')", 'src/a.ts': "fetch('/api/a')" })
  const output = resolve(f.root, '.artifacts/private/inventory.json'), summaryOutput = resolve(f.root, 'summary.json')
  const options = { root: f.root, output, summaryOutput, revision: PIN }
  const summary = writeInventory(options), first = readFileSync(output)
  const publicFirst = readFileSync(summaryOutput)
  writeInventory(options)
  assert.deepEqual(readFileSync(output), first); assert.deepEqual(readFileSync(summaryOutput), publicFirst)
  assert.equal(statSync(output).mode & 0o777, 0o600)
  assert.equal(summary.records, undefined); assert.equal(summary.manifest, undefined)
  assert.equal(publicFirst.toString().includes('/api/a'), false)
  assert.deepEqual(JSON.parse(first).manifest.map((r) => r.file), ['src/a.ts', 'src/z.ts'])
  const other = fixture(t, { 'src/z.ts': "fetch('/api/z')", 'src/a.ts': "fetch('/api/a')" })
  assert.deepEqual(other.scan(), f.scan(), 'Absolute temp root and traversal order must not affect payload')
  writeFileSync(resolve(f.root, 'src/a.ts'), "fetch('/api/a')\n")
  assert.notEqual(f.scan().summary.source.manifestSha256, summary.source.manifestSha256)
  assert.throws(() => writeInventory({ root: f.root, output: resolve(f.root, 'public.json') }), /private/)
  assert.throws(() => writeInventory({ output }), /explicit/)
})

test('syntax diagnostics are retained as location/code/hash without source snippets or diagnostic text', (t) => {
  const f = fixture(t, { 'src/bad.ts': 'const PRIVATE_DIAGNOSTIC_CANARY =' })
  const result = f.scan()
  assert.ok(result.diagnostics.length > 0)
  assert.equal(result.summary.counts.syntacticDiagnostics, result.diagnostics.length)
  assert.ok(result.diagnostics.every((r) => r.line === 1 && /^[a-f\d]{64}$/.test(r.messageSha256)))
  assert.equal(JSON.stringify(result).includes('PRIVATE_DIAGNOSTIC_CANARY'), false)
})

test('six domain groups use nonexclusive source/path heuristics while unknown stays visible', (t) => {
  const f = fixture(t, { 'src/services/opsService.ts': `
import { get } from './apiClient'
get('/api/objects')
get('/api/equipment')
get('/api/counterparties')
get('/api/contracts')
get('/api/documents')
get('/api/monitoring')
get(dynamicPath)
` })
  const result = f.scan()
  for (const name of ['objects', 'equipment', 'counterparties', 'contracts', 'documents', 'monitoring', 'unknown']) {
    assert.equal(result.summary.heuristicDomains[name].shared, 1, name)
  }
  assert.equal(result.summary.counts.unknownTransportPaths, 1)
})
