/** Offline AST inventory. Reads source text only; never loads application modules. */
import ts from 'typescript'
import { readFileSync, readdirSync, mkdirSync, writeFileSync, lstatSync, chmodSync } from 'node:fs'
import { resolve, relative, dirname, posix } from 'node:path'
import { createHash } from 'node:crypto'

export const PIN = '06e02207c29651682530309bea1a4157f48b3168'
const sha = (text) => createHash('sha256').update(text).digest('hex')
const canonical = (value) => `${JSON.stringify(value, null, 2)}\n`
const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0
const slash = (path) => path.replaceAll('\\', '/')
const transportMethods = { get: 'GET', post: 'POST', put: 'PUT', patch: 'PATCH', del: 'DELETE',
  upload: 'POST', downloadFile: 'GET', downloadBlob: 'GET' }
const nativeNames = new Set(['fetch', 'XMLHttpRequest', 'EventSource', 'WebSocket'])
const methods = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'CONNECT', 'TRACE'])
const excluded = new Set(['tests', '__tests__', '__fixtures__', 'fixtures', 'generated', 'build', 'dist',
  'node_modules', 'coverage', '.git', '.artifacts', 'qa', 'e2e'])
const domains = [
  ['objects', /(?:site|spaceobject|location|\/objects(?:\/|$))/i], ['equipment', /equipment/i],
  ['counterparties', /(?:counterpart|vendor)/i], ['contracts', /contract/i],
  ['documents', /(?:docs|document|intake)/i], ['monitoring', /(?:monitor|perimeter|overview)/i],
]

function filesUnder(root) {
  const files = [], exclusions = []
  function visit(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => cmp(a.name, b.name))) {
      const path = resolve(dir, entry.name)
      if (entry.isSymbolicLink()) exclusions.push({ file: slash(relative(root, path)), reason: 'symlink-not-followed' })
      if (entry.isDirectory() && excluded.has(entry.name)) exclusions.push({ file: slash(relative(root, path)), reason: 'excluded-directory' })
      if (entry.isDirectory() && !excluded.has(entry.name)) visit(path)
      if (entry.isFile() && /\.(?:ts|tsx|js|jsx)$/.test(entry.name)
          && !/\.(?:test|spec)\.[^.]+$|\.d\.[cm]?ts$/.test(entry.name)) files.push(path)
      else if (entry.isFile() && /\.(?:test|spec)\.[^.]+$|\.d\.[cm]?ts$/.test(entry.name)) {
        exclusions.push({ file: slash(relative(root, path)), reason: 'test-or-declaration-file' })
      }
    }
  }
  if (lstatSync(resolve(root, 'src')).isSymbolicLink()) throw new Error('source root must not be a symlink')
  visit(resolve(root, 'src'))
  return { paths: files.sort(cmp), exclusions }
}

function modulePath(file, specifier) {
  let path
  if (specifier.startsWith('@/')) path = `src/${specifier.slice(2)}`
  else if (specifier.startsWith('.')) path = posix.normalize(posix.join(posix.dirname(file), specifier))
  else return undefined
  return path.replace(/\.(?:ts|tsx|js|jsx)$/, '')
}

function unwrap(node) {
  while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)
      || ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node))) node = node.expression
  return node
}

function countBy(values) {
  const counts = new Map()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  return Object.fromEntries([...counts].sort(([a], [b]) => cmp(a, b)))
}

/** Origins, credentials, query/hash values and coordinate-like path segments are never retained. */
function safePath(value) {
  if (!value || value === '{dynamic}') return null
  let text = value.replace(/[\r\n\t]/g, '')
  if (/^(?:https?|wss?):\/\//i.test(text)) text = text.replace(/^[a-z]+:\/\/[^/?#]*/i, '{origin}')
  else if (text.startsWith('//')) text = text.replace(/^\/\/[^/?#]*/, '{origin}')
  else if (/^[a-z][a-z\d+.-]*:/i.test(text)) return '{non-http-resource}'
  const query = text.indexOf('?'), fragment = text.indexOf('#')
  const end = Math.min(...[query, fragment, text.length].filter((n) => n >= 0))
  let path = text.slice(0, end)
  // A dynamic leading origin can be followed by arbitrary expressions; preserve only slash-led suffixes.
  if (!/^(?:\/|\{origin\}|\{dynamic\}\/)/.test(path)) return '{relative-resource}'
  path = path.split('/').map((segment) => {
    if (segment === '{origin}' || segment === '{dynamic}') return segment
    if (/[.@%:\\]/.test(segment) || /^\d+$|\d{4,}|^[a-f\d]{8,}$|^[a-f\d]{8}-(?:[a-f\d-]{27})$/i.test(segment)
        || segment.length > 64) return '{literal}'
    return segment.replace(/[^a-zA-Z\d_{}-]/g, '_')
  }).join('/')
  return `${path}${query >= 0 ? '?{redacted}' : ''}${fragment >= 0 ? '#{redacted}' : ''}`
}

export function inventory({ root, revision = PIN, maxWrappers = 5000 }) {
  root = resolve(root)
  if (!/^[a-f\d]{40}$/.test(revision)) throw new Error('revision must be a full source commit')
  const { paths, exclusions } = filesUnder(root)
  const sources = new Map(paths.map((path) => [path, readFileSync(path)]))
  const manifest = paths.map((path) => ({ file: slash(relative(root, path)), sha256: sha(sources.get(path)),
    lines: sources.get(path).toString('utf8').split(/\r\n|\n|\r/).length }))
  const options = { noLib: true, noResolve: true, allowJs: true, target: ts.ScriptTarget.Latest, jsx: ts.JsxEmit.Preserve }
  // No compiler fallback to disk, tsconfig, libraries, package discovery or app execution.
  const host = {
    getSourceFile: (file, version) => sources.has(file) ? ts.createSourceFile(file, sources.get(file).toString('utf8'), version, true) : undefined,
    getDefaultLibFileName: () => '', writeFile: () => {}, getCurrentDirectory: () => root,
    getDirectories: () => [], fileExists: (file) => sources.has(file),
    readFile: (file) => sources.get(file)?.toString('utf8'), getCanonicalFileName: (file) => file,
    useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
  }
  const program = ts.createProgram(paths, options, host), checker = program.getTypeChecker()
  const records = [], diagnostics = [], localWrappers = new Set(), candidates = []
  const symbol = (node) => checker.getSymbolAtLocation(node)
  function origin(node, file, seen = new Set()) {
    node = unwrap(node)
    if (!node || seen.has(node)) return undefined
    seen.add(node)
    if (ts.isIdentifier(node)) {
      const sym = symbol(node), declaration = sym?.declarations?.[0]
      if (!declaration && nativeNames.has(node.text)) return { kind: 'native', name: node.text }
      if (declaration && (ts.isImportSpecifier(declaration) || ts.isNamespaceImport(declaration))) {
        const clause = ts.isImportSpecifier(declaration) ? declaration.parent.parent : declaration.parent
        if (clause.isTypeOnly || (ts.isImportSpecifier(declaration) && declaration.isTypeOnly)) return undefined
        const imported = clause.parent
        const module = modulePath(file, imported.moduleSpecifier.text)
        if (!module?.startsWith('src/services/')) return undefined
        const name = ts.isNamespaceImport(declaration) ? '*' : (declaration.propertyName ?? declaration.name).text
        return { kind: module === 'src/services/apiClient' ? 'shared' : 'wrapper', name, module }
      }
      if (declaration && ts.isVariableDeclaration(declaration) && declaration.initializer
          && (declaration.parent.flags & ts.NodeFlags.Const)) return origin(declaration.initializer, file, seen)
      return undefined
    }
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      const base = node.expression
      const property = ts.isPropertyAccessExpression(node) ? node.name.text
        : ts.isStringLiteralLike(node.argumentExpression) ? node.argumentExpression.text : '{dynamic}'
      if (ts.isIdentifier(base) && ['window', 'globalThis', 'self'].includes(base.text)
          && !symbol(base)?.declarations?.length && nativeNames.has(property)) return { kind: 'native', name: property }
      const parent = origin(base, file, seen)
      if (parent?.name === '*') return { ...parent, name: property }
    }
    return undefined
  }
  function stringValue(node, seen = new Set()) {
    node = unwrap(node)
    if (!node || seen.has(node)) return { text: '{dynamic}', known: false }
    seen.add(node)
    if (ts.isStringLiteralLike(node)) return { text: node.text, known: true }
    if (ts.isTemplateExpression(node)) {
      const parts = node.templateSpans.map((span) => [stringValue(span.expression, new Set(seen)), span.literal.text])
      return { text: node.head.text + parts.map(([value, tail]) => value.text + tail).join(''), known: parts.every(([value]) => value.known) }
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const a = stringValue(node.left, new Set(seen)), b = stringValue(node.right, new Set(seen))
      return { text: a.text + b.text, known: a.known && b.known }
    }
    if (ts.isIdentifier(node)) {
      const declaration = symbol(node)?.declarations?.[0]
      if (declaration && ts.isVariableDeclaration(declaration) && declaration.initializer
          && (declaration.parent.flags & ts.NodeFlags.Const)) return stringValue(declaration.initializer, seen)
    }
    return { text: '{dynamic}', known: false }
  }
  function methodOf(node, stringInput) {
    node = unwrap(node)
    let method = stringInput ? 'GET' : null, reason = stringInput ? 'fetch-default' : 'input-may-be-request'
    if (!node || (ts.isIdentifier(node) && node.text === 'undefined' && !symbol(node)?.declarations?.length)) return { method, methodReason: reason }
    if (!ts.isObjectLiteralExpression(node)) return { method: null, methodReason: 'dynamic-options' }
    for (const property of node.properties) {
      if (ts.isSpreadAssignment(property) || (property.name && ts.isComputedPropertyName(property.name))) {
        method = null; reason = 'spread-or-computed-options'
      } else if (property.name?.getText().replace(/['"]/g, '') === '__proto__') {
        method = null; reason = 'object-prototype-options'
      } else if (property.name?.getText().replace(/['"]/g, '') === 'method') {
        const value = ts.isPropertyAssignment(property) ? stringValue(property.initializer) : { known: false }
        method = value.known && methods.has(value.text.toUpperCase()) ? value.text.toUpperCase() : null
        reason = method ? 'explicit' : 'dynamic-or-nonstandard-method'
      }
    }
    return { method, methodReason: reason }
  }
  function enclosing(node) {
    for (let parent = node.parent; parent; parent = parent.parent) {
      if (ts.isFunctionLike(parent)) return parent
    }
    return undefined
  }
  function record(sf, node, target, arg, extra = {}) {
    const start = sf.getLineAndCharacterOfPosition(node.getStart(sf)), end = sf.getLineAndCharacterOfPosition(node.end)
    const value = stringValue(arg)
    const file = slash(relative(root, sf.fileName))
    const pathname = target.kind === 'wrapper' ? null : safePath(value.text)
    const domain = domains.filter(([, pattern]) => pattern.test(`${file} ${pathname ?? ''}`)).map(([name]) => name)
    return { file, line: start.line + 1, column: start.character + 1, endLine: end.line + 1,
      category: target.kind, transport: target.kind === 'wrapper' ? 'service-wrapper-candidate' : target.name,
      protocol: target.name === 'WebSocket' ? 'websocket' : target.name === 'EventSource' ? 'event-stream' : 'http-or-unknown',
      wrapperModule: target.module ?? null, method: null, methodReason: 'unresolved-wrapper',
      pathname,
      pathState: pathname === null ? 'unknown' : value.known ? 'static' : 'dynamic',
      pathExpressionKind: arg ? ts.SyntaxKind[arg.kind] : 'missing',
      expressionSha256: sha(node.getText(sf)), pathExpressionSha256: arg ? sha(arg.getText(sf)) : null,
      sourceSha256: sha(sources.get(sf.fileName)), heuristicDomains: domain.length ? domain : ['unknown'], ...extra }
  }
  for (const path of paths) {
    const sf = program.getSourceFile(path), file = slash(relative(root, path))
    for (const diagnostic of program.getSyntacticDiagnostics(sf)) {
      diagnostics.push({ file, line: sf.getLineAndCharacterOfPosition(diagnostic.start ?? 0).line + 1,
        code: diagnostic.code, messageSha256: sha(ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')) })
    }
    function visit(node) {
      if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
        const target = origin(node.expression, file)
        if (target?.kind === 'shared' && (transportMethods[target.name] || target.name === '{dynamic}')) {
          records.push(record(sf, node, target, node.arguments?.[0], {
            method: transportMethods[target.name] ?? null, methodReason: target.name === '{dynamic}' ? 'dynamic-shared-member' : 'shared-contract',
          })); if (enclosing(node)) localWrappers.add(enclosing(node))
        } else if (target?.kind === 'native' && ((target.name === 'fetch' && ts.isCallExpression(node))
            || (target.name !== 'fetch' && ts.isNewExpression(node)))) {
          const arg = node.arguments?.[0], value = stringValue(arg)
          const method = target.name === 'fetch' ? methodOf(node.arguments?.[1], value.known || ts.isTemplateExpression(unwrap(arg) ?? {})
            || ts.isStringLiteralLike(unwrap(arg) ?? {})) : { method: target.name === 'EventSource' ? 'GET' : null, methodReason: 'constructor' }
          records.push(record(sf, node, target, target.name === 'XMLHttpRequest' ? undefined : arg, method))
          if (enclosing(node)) localWrappers.add(enclosing(node))
        } else if (target?.kind === 'wrapper') candidates.push({ sf, node, target })
        else if (ts.isCallExpression(node)) {
          const callee = unwrap(node.expression)
          const receiver = ts.isPropertyAccessExpression(callee) && callee.name.text === 'open' ? callee.expression : undefined
          const declaration = receiver && ts.isIdentifier(receiver) ? symbol(receiver)?.declarations?.[0] : undefined
          const initializer = declaration && ts.isVariableDeclaration(declaration)
            && (declaration.parent.flags & ts.NodeFlags.Const) ? unwrap(declaration.initializer) : undefined
          const constructor = initializer && ts.isNewExpression(initializer) ? origin(initializer.expression, file) : undefined
          if (constructor?.kind === 'native' && constructor.name === 'XMLHttpRequest') {
            const value = stringValue(node.arguments[0])
            const method = value.known && methods.has(value.text.toUpperCase()) ? value.text.toUpperCase() : null
            records.push(record(sf, node, { kind: 'native', name: 'XMLHttpRequest.open' }, node.arguments[1], {
              method, methodReason: method ? 'xhr-open-literal' : 'dynamic-or-nonstandard-method',
            }))
            if (enclosing(node)) localWrappers.add(enclosing(node))
          } else candidates.push({ sf, node })
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(sf)
  }
  // Local function calls are candidates only when a lexical declaration directly contains transport.
  // Imported service functions stay unresolved: no speculative inter-module call graph or URL inference.
  let omittedWrappers = 0, wrapperCount = 0
  for (const { sf, node, target } of candidates) {
    let resolved = target
    if (!resolved && ts.isIdentifier(node.expression)) {
      const declaration = symbol(node.expression)?.declarations?.[0]
      const fn = declaration && ts.isVariableDeclaration(declaration) ? unwrap(declaration.initializer) : declaration
      if (localWrappers.has(fn)) resolved = { kind: 'wrapper', name: 'local', module: slash(relative(root, sf.fileName)) }
    }
    if (!resolved) continue
    if (wrapperCount >= maxWrappers) { omittedWrappers++; continue }
    records.push(record(sf, node, resolved, undefined))
    wrapperCount++
  }
  records.sort((a, b) => cmp(a.file, b.file) || a.line - b.line || a.column - b.column || cmp(a.category, b.category))
  diagnostics.sort((a, b) => cmp(a.file, b.file) || a.line - b.line || a.code - b.code)
  const transport = records.filter((r) => r.category !== 'wrapper')
  const shared = transport.filter((r) => r.category === 'shared'), direct = transport.filter((r) => r.category === 'native')
  const summary = {
    schemaVersion: 1, sourceRevision: revision, sourceRevisionProvenance: 'explicit-label; verify Git externally; manifest fingerprints actual bytes',
    pinnedBase: PIN, typescriptVersion: ts.version,
    generator: { file: 'scripts/inventory-api-consumers.mjs', sha256: sha(readFileSync(import.meta.filename)) },
    scope: 'production src ts/tsx/js/jsx; no tests/declarations/generated/build/symlinks; AST only',
    source: { files: manifest.length, lines: manifest.reduce((n, f) => n + f.lines, 0), manifestSha256: sha(canonical(manifest)) },
    counts: { records: records.length, shared: shared.length, direct: direct.length,
      streamConstructors: direct.filter((r) => ['WebSocket', 'EventSource'].includes(r.transport)).length,
      unresolvedWrappers: records.length - transport.length, omittedWrappers, syntacticDiagnostics: diagnostics.length,
      staticTransportPaths: transport.filter((r) => r.pathState === 'static').length,
      dynamicTransportPaths: transport.filter((r) => r.pathState === 'dynamic').length,
      unknownTransportPaths: transport.filter((r) => r.pathname === null).length,
      unknownTransportMethods: transport.filter((r) => r.method === null).length },
    exclusions: countBy(exclusions.map((e) => e.reason)),
    transports: countBy(transport.map((r) => `${r.category}:${r.transport}`)),
    protocols: countBy(transport.map((r) => r.protocol)), methods: countBy(transport.map((r) => r.method ?? 'unknown')),
    unknownMethodReasons: countBy(transport.filter((r) => r.method === null).map((r) => r.methodReason)),
    unknownPathExpressionKinds: countBy(transport.filter((r) => r.pathname === null).map((r) => r.pathExpressionKind)),
    heuristicDomains: Object.fromEntries([...domains.map(([name]) => name), 'unknown'].map((name) => [name, {
      shared: shared.filter((r) => r.heuristicDomains.includes(name)).length,
      direct: direct.filter((r) => r.heuristicDomains.includes(name)).length,
      unresolvedWrappers: records.filter((r) => r.category === 'wrapper' && r.heuristicDomains.includes(name)).length,
    }])),
    wrapperFamilies: Object.entries(countBy(records.filter((r) => r.category === 'wrapper').map((r) => r.wrapperModule)))
      .sort(([a, x], [b, y]) => y - x || cmp(a, b)).slice(0, 24).map(([module, calls]) => ({ module, calls })),
    wrapperFamiliesTotal: new Set(records.filter((r) => r.category === 'wrapper').map((r) => r.wrapperModule)).size,
    directFamilies: Object.entries(countBy(direct.map((r) => r.file)))
      .sort(([a, x], [b, y]) => y - x || cmp(a, b)).slice(0, 24).map(([file, calls]) => ({ file, calls })),
    directFamiliesTotal: new Set(direct.map((r) => r.file)).size,
    familySources: manifest.filter((f) => f.file.startsWith('src/services/') && /(?:apiClient|voiceService|spaceAuditorService|mstoApiClient|stsApiClient|siteService|sitesService|spaceObjectsService|equipmentService|referenceService|opsService|docsService|intakeDocsService|monitor|contract)/i.test(f.file))
      .slice(0, 32),
    limits: { wrapperRecords: maxWrappers, publicWrapperFamilies: 24, publicDirectFamilies: 24, publicFamilySources: 32 },
    limitations: ['Callsites are source evidence, not runtime requests or ownership.',
      'Service/local wrapper candidates may be helpers; unresolved is not a defect.',
      'No backend-route validation, partners inventory, dataflow, re-export or runtime dispatch proof.',
      'Domains are nonexclusive filename/sanitized-path heuristics; unknown remains unknown.',
      'Native construction/open is not proof of send; XHR open is linked only to a direct const constructor binding.',
      'No semantic/type diagnostics; only syntactic diagnostics under a closed compiler host.'],
  }
  return { summary, manifest, exclusions, diagnostics, records }
}

export function writeInventory({ root, output, summaryOutput, revision = PIN, maxWrappers }) {
  if (!root || !output) throw new Error('explicit root and private output required')
  const privateOutput = slash(resolve(output)), sourceRoot = slash(resolve(root, 'src'))
  if (!privateOutput.includes('/.artifacts/private/') || privateOutput.startsWith(`${sourceRoot}/`)) throw new Error('output must be under .artifacts/private outside source')
  if (summaryOutput && (resolve(summaryOutput) === resolve(output) || slash(resolve(summaryOutput)).startsWith(`${sourceRoot}/`))) throw new Error('summary output must be separate and outside source')
  const result = inventory({ root, revision, maxWrappers })
  mkdirSync(dirname(output), { recursive: true }); writeFileSync(output, canonical(result), { mode: 0o600 })
  chmodSync(output, 0o600)
  if (summaryOutput) { mkdirSync(dirname(summaryOutput), { recursive: true }); writeFileSync(summaryOutput, canonical(result.summary)) }
  return result.summary
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  try {
    const args = process.argv.slice(2), allowed = new Set(['--root', '--output', '--summary-output', '--revision'])
    const options = {}
    for (let i = 0; i < args.length; i += 2) {
      if (!allowed.has(args[i]) || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error('invalid arguments')
      options[args[i]] = args[i + 1]
    }
    const summary = writeInventory({ root: options['--root'], output: options['--output'],
      summaryOutput: options['--summary-output'], revision: options['--revision'] })
    process.stdout.write(canonical(summary))
  } catch {
    process.stderr.write('API inventory failed: check explicit arguments and source readability.\n')
    process.exitCode = 1
  }
}
