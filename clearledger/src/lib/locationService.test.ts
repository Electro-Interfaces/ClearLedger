import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { QueryClient, QueryObserver } from '@tanstack/react-query'

const root = fileURLToPath(new URL('../../', import.meta.url))
const companyA = 'company:A/opaque'
const companyB = 'company:B/opaque'
const storageKey = (id: string) => `tl-locations-${id}`
const location = (name: string) => ({ id: 'opaque-location/id', code: name, name,
  type: 'ev_charging', status: 'active', sourceBindings: [],
  createdAt: '2026-10-29T10:00:00Z', updatedAt: '2026-10-29T10:00:00Z' })
const json = (body: unknown) => new Response(JSON.stringify(body), {
  headers: { 'Content-Type': 'application/json' },
})
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function memoryStorage() {
  const entries = new Map<string, string>()
  return {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, value) },
    removeItem: (key: string) => { entries.delete(key) },
    clear: () => entries.clear(),
  }
}

// Vite загружает настоящие services с их aliases/import.meta.env. Ни HTTP-сервер,
// ни .env не нужны: любой fetch перехвачен, по умолчанию тест его запрещает.
async function fixture(baseUrl = 'https://api.example.test') {
  const originals = new Map(['window', 'localStorage', 'sessionStorage', 'fetch']
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const local = memoryStorage()
  const session = memoryStorage()
  const window = { location: { origin: 'https://ui.example.test', pathname: '/', search: '' } }
  const calls: { url: string; init?: RequestInit }[] = []
  let respond: (url: string, init?: RequestInit) => Promise<Response> = async () => {
    throw new Error('Незапланированный HTTP-запрос')
  }
  Object.defineProperties(globalThis, {
    window: { configurable: true, value: window },
    localStorage: { configurable: true, value: local },
    sessionStorage: { configurable: true, value: session },
    fetch: { configurable: true, writable: true, value: (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), init })
      return respond(String(url), init)
    } },
  })
  const server = await createServer({ root, configFile: false, envFile: false,
    logLevel: 'silent', appType: 'custom',
    plugins: [{
      name: 'location-hook-test-boundaries',
      transform(code, id) {
        if (!id.endsWith('/src/hooks/useLocations.ts')) return
        return code.replace('@/contexts/CompanyContext', 'virtual:test-company')
          .replace('@tanstack/react-query', 'virtual:test-query')
      },
      resolveId(source) {
        if (source === 'virtual:test-company') return '\0test-company'
        if (source === 'virtual:test-query') return '\0test-query'
      },
      load(id) {
        if (id === '\0test-company') return `export const useCompany = () => ({ companyId: ${JSON.stringify(companyA)} })`
        if (id === '\0test-query') return 'export const queries = []; export const useQuery = (options) => { queries.push(options); return {} }'
      },
    }],
    resolve: { alias: { '@': `${root}/src` } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(baseUrl) },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  const service = await server.ssrLoadModule('/src/services/locationService.ts') as typeof import('../services/locationService.ts')
  const api = await server.ssrLoadModule('/src/services/apiClient.ts') as typeof import('../services/apiClient.ts')
  const docs = await server.ssrLoadModule('/src/services/docsService.ts') as typeof import('../services/docsService.ts')
  const hook = await server.ssrLoadModule('/src/hooks/useLocations.ts') as typeof import('../hooks/useLocations.ts')
  const queryProbe = await server.ssrLoadModule('\0test-query') as {
    queries: { queryKey: string[]; queryFn: (context: { signal: AbortSignal }) => Promise<unknown> }[]
  }
  return { service, api, docs, hook, queryProbe, calls, local, session, window,
    respond: (fn: typeof respond) => { respond = fn },
    activate: (company: string) => { service.setActiveCompany(company); api.setApiCompany(company) },
    save: (company: string, name: string) => local.setItem(storageKey(company), JSON.stringify([location(name)])),
    read: (company: string) => JSON.parse(local.getItem(storageKey(company)) ?? '[]'),
    async close() {
      await server.close()
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

test('locationService: граница компании, отмена и совместимость зеркала', async (t) => {
  const f = await fixture()
  t.after(() => f.close())
  t.beforeEach(() => { f.service.resetCache(); f.local.clear(); f.calls.length = 0 })

  await t.test('late A после B не меняет ни один кеш и останавливает await→mutation', async () => {
    f.activate(companyA)
    f.save(companyA, 'cached A')
    f.save(companyB, 'cached B')
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const operation = (async () => {
      await f.service.loadLocations(companyA)
      f.service.createLocation({ code: 'bad', name: 'bad', type: 'ev_charging' })
    })()
    const rejected = assert.rejects(operation, { name: 'AbortError' })
    f.service.resetCache(); f.activate(companyB)
    f.respond(async () => json([location('backend B')]))
    assert.equal((await f.service.loadLocations(companyB))[0].name, 'backend B')
    late.resolve(json([location('late A')]))
    await rejected
    assert.equal(f.read(companyA)[0].name, 'cached A')
    assert.equal(f.read(companyB)[0].name, 'backend B')
    assert.equal(f.service.getLocations()[0].name, 'backend B')
    assert.equal(f.calls.length, 2)
  })

  await t.test('reset и возврат в ту же компанию создают новое поколение', async () => {
    f.activate(companyA); f.save(companyA, 'current')
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const rejected = assert.rejects(f.service.loadLocations(companyA), { name: 'AbortError' })
    f.service.resetCache(); f.activate(companyA)
    late.resolve(json([location('old generation')]))
    await rejected
    assert.equal(f.read(companyA)[0].name, 'current')
  })

  await t.test('смена компании без reset и старый вызов не выбирают компанию обратно', async () => {
    f.activate(companyA)
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const rejected = assert.rejects(f.service.loadLocations(companyA), { name: 'AbortError' })
    f.activate(companyB); f.save(companyB, 'B')
    late.resolve(json([location('A')]))
    await rejected
    await assert.rejects(f.service.loadLocations(companyA), { name: 'AbortError' })
    assert.equal(f.calls.length, 1)
    assert.equal(f.service.getLocations()[0].name, 'B')
  })

  await t.test('пустой stale backend не отправляет локальные записи в mirror', async () => {
    f.activate(companyA); f.save(companyA, 'local A'); f.save(companyB, 'local B')
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const rejected = assert.rejects(f.service.loadLocations(companyA), { name: 'AbortError' })
    f.service.resetCache(); f.activate(companyB)
    late.resolve(json([]))
    await rejected
    assert.equal(f.calls.length, 1)
    assert.equal(f.read(companyA)[0].name, 'local A')
    assert.equal(f.read(companyB)[0].name, 'local B')
  })

  await t.test('ошибка старого запроса не возвращает fallback новой компании', async () => {
    f.activate(companyA)
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const rejected = assert.rejects(f.service.loadLocations(companyA), { name: 'AbortError' })
    f.service.resetCache(); f.activate(companyB); f.save(companyB, 'secret B')
    late.reject(new TypeError('fetch failed'))
    await rejected
  })

  await t.test('reset без новой компании не оживляет старый запрос', async () => {
    f.activate(companyA); f.save(companyA, 'A')
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const rejected = assert.rejects(f.service.loadLocations(companyA), { name: 'AbortError' })
    f.service.resetCache()
    late.resolve(json([]))
    await rejected
    assert.equal(f.calls.length, 1)
    assert.deepEqual(f.service.getLocations(), [])
  })

  await t.test('пустой актуальный backend без локальных строк ничего не отправляет', async () => {
    f.activate(companyA)
    f.respond(async () => json([]))
    assert.deepEqual(await f.service.loadLocations(companyA), [])
    assert.equal(f.calls.length, 1)
  })

  await t.test('актуальная сетевая ошибка сохраняет local fallback, не подставляя demo', async (t) => {
    f.activate(companyA); f.save(companyA, 'offline copy')
    f.respond(async () => { throw new TypeError('fetch failed') })
    const warning = t.mock.method(console, 'warn', () => {})
    assert.equal((await f.service.loadLocations(companyA))[0].name, 'offline copy')
    assert.equal(warning.mock.callCount(), 1)
    assert.equal(f.calls.length, 1)
  })

  await t.test('актуальный запрос гидратирует свою компанию, повторный set не отменяет её', async () => {
    f.activate(companyA); f.save(companyB, 'B')
    const late = deferred<Response>()
    f.respond(async () => late.promise)
    const loading = f.service.loadLocations(companyA)
    f.activate(companyA)
    late.resolve(json([location('backend A')]))
    assert.equal((await loading)[0].name, 'backend A')
    assert.equal(f.read(companyA)[0].name, 'backend A')
    assert.equal(f.read(companyB)[0].name, 'B')
    assert.equal(new URL(f.calls[0].url).searchParams.get('company_id'), companyA)
    assert.equal((f.calls[0].init?.headers as Record<string, string>)['X-Company-Id'], companyA)
  })

  await t.test('пустой актуальный backend сохраняет прежнюю миграцию только своей компании', async () => {
    f.activate(companyA); f.save(companyA, 'local A'); f.save(companyB, 'local B')
    f.respond(async (_url, init) => json(init?.method === 'POST' ? {} : []))
    assert.equal((await f.service.loadLocations(companyA))[0].name, 'local A')
    assert.equal(f.calls.length, 2)
    const body = JSON.parse(f.calls[1].init?.body as string)
    assert.equal(body.company_id, companyA)
    assert.equal(body.name, 'local A')
    assert.equal(body.id, 'opaque-location/id')
  })

  await t.test('отмена fetch и поздний ответ без поддержки abort не запускают fallback/mirror', async () => {
    f.activate(companyA); f.save(companyA, 'local A')
    for (const cooperative of [true, false]) {
      const controller = new AbortController()
      const late = deferred<Response>()
      f.respond(async (_url, init) => {
        assert.equal(init?.signal, controller.signal)
        if (cooperative) init?.signal?.addEventListener('abort', () => late.reject(controller.signal.reason), { once: true })
        return late.promise
      })
      const rejected = assert.rejects(f.service.loadLocations(companyA, controller.signal), { name: 'AbortError' })
      controller.abort()
      if (!cooperative) late.resolve(json([]))
      await rejected
    }
    assert.equal(f.calls.length, 2)
    assert.equal(f.read(companyA)[0].name, 'local A')
    const aborted = new AbortController(); aborted.abort()
    await assert.rejects(f.api.get('/api/locations', undefined, { signal: aborted.signal }), { name: 'AbortError' })
    assert.equal(f.calls.length, 2)
  })

  await t.test('React Query clear отменяет GET; поздний ответ не заполняет localStorage', async () => {
    f.activate(companyA); f.save(companyA, 'local A')
    const late = deferred<Response>()
    let signal: AbortSignal | undefined
    f.respond(async (_url, init) => { signal = init?.signal ?? undefined; return late.promise })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // Настоящий hook регистрирует options; настоящий QueryObserver исполняет их.
    f.hook.useLocations()
    const options = f.queryProbe.queries.at(-1)!
    assert.deepEqual(options.queryKey, ['locations', companyA])
    const observer = new QueryObserver(client, options)
    const unsubscribe = observer.subscribe(() => {})
    client.clear()
    assert.equal(signal?.aborted, true)
    late.resolve(json([location('late')]))
    await new Promise<void>((resolve) => setImmediate(resolve))
    assert.equal(f.read(companyA)[0].name, 'local A')
    assert.equal(client.getQueryData(['locations', companyA]), undefined)
    unsubscribe()
  })

  await t.test('late operational-status не меняет кеш и отклоняет продолжение mutation', async () => {
    for (const nextCompany of [companyA, companyB]) {
      f.activate(companyA); f.save(companyA, 'A'); f.save(companyB, 'B')
      const late = deferred<Response>()
      f.respond(async () => late.promise)
      const requestsBefore = f.calls.length
      const mutation = (async () => {
        await f.service.setOperationalStatus('opaque-location/id', 'repair')
        f.service.createLocation({ code: 'bad', name: 'bad', type: 'ev_charging' })
      })()
      const rejected = assert.rejects(mutation, { name: 'AbortError' })
      f.service.resetCache(); f.activate(nextCompany)
      late.resolve(json({}))
      await rejected
      assert.equal(f.read(companyA)[0].operationalStatus, undefined)
      assert.equal(f.read(companyB)[0].operationalStatus, undefined)
      assert.equal(f.read(companyA).length, 1)
      assert.equal(f.read(companyB).length, 1)
      assert.equal(f.calls.length, requestsBefore + 1)
    }
  })

  await t.test('актуальная mutation обновляет операционный статус', async () => {
    f.activate(companyA); f.save(companyA, 'A')
    f.respond(async () => json({}))
    await f.service.setOperationalStatus('opaque-location/id', 'repair')
    assert.equal(f.read(companyA)[0].operationalStatus, 'repair')
    assert.equal(f.calls[0].init?.method, 'PATCH')
  })

  await t.test('typed ref сериализуется без изменения opaque ID и существующих фильтров', async () => {
    const ref = 'contract:opaque/id ?#ю'
    f.respond(async () => json({ docs: [], count: 0 }))
    assert.deepEqual(await f.docs.listDocs(companyA, { ref, limit: 10, mine: false }), { docs: [], count: 0 })
    const params = new URL(f.calls[0].url).searchParams
    assert.equal(params.get('ref'), ref)
    assert.equal(params.get('company_id'), companyA)
    assert.equal(params.get('mine'), 'false')
    assert.equal(params.get('limit'), '10')
  })
})

test('locationService: offline/demo сохраняют существующий режим', async (t) => {
  const f = await fixture('')
  t.after(() => f.close())
  f.activate(companyA); f.save(companyA, 'offline A')
  assert.equal(f.api.isApiEnabled(), false)
  assert.equal((await f.service.loadLocations(companyA))[0].name, 'offline A')
  const created = f.service.createLocation({ code: 'local', name: 'offline created', type: 'ev_charging' })
  assert.equal(f.service.getLocation(created.id)?.name, 'offline created')
  assert.equal(f.calls.length, 0)
  f.window.location.pathname = '/demo/shop'
  assert.equal(f.api.isApiEnabled(), true)
  const warning = t.mock.method(console, 'warn', () => {})
  const demo = await f.service.loadLocations(companyA)
  // В существующем demoApi нет /api/locations: остаётся прежняя локальная копия.
  assert.equal(warning.mock.callCount(), 1)
  assert.match(String(warning.mock.calls[0].arguments[1]), /Демо-данные/)
  assert.equal(demo[0].name, 'offline A')
  assert.deepEqual(f.service.getLocations(), demo)
  assert.equal(f.calls.length, 0)
})
