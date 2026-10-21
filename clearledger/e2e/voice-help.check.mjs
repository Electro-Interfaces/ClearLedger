/**
 * Справка «Телефонии»: настоящая оболочка, страницы и Markdown, вымышленные API.
 * Browser plugin not available: Playwright + системный Chromium.
 * node e2e/voice-help.check.mjs
 * Переснять картинки пакета: VOICE_HELP_CAPTURE=1 node e2e/voice-help.check.mjs
 * Только переходы контекста: VOICE_HELP_FOCUS=1 node e2e/voice-help.check.mjs
 * Без флага доказательства идут во временный каталог, public/ не меняется.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile, mkdir, mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from '@playwright/test'
import { companyId, at, coreReply, nodeReply } from './fixtures/voice-help.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const artifacts = await mkdtemp(join(tmpdir(), 'voice-help-'))
const capture = process.env.VOICE_HELP_CAPTURE === '1'
const shots = capture ? join(root, 'public/help/voice') : artifacts
await mkdir(shots, { recursive: true })
const source = join(root, 'server/app/services/info_seed_voice.py')
const articles = JSON.parse(execFileSync('python3', ['-c',
  'import runpy,json,sys; print(json.dumps(runpy.run_path(sys.argv[1])["ARTICLES"],ensure_ascii=False))', source], { encoding: 'utf8' }))
const rows = articles.map((a, i) => ({ id: `voice-help-${i}`, title: a.title, summary: a.summary,
  kind: a.kind, kindLabel: 'Работа в системе', scope: 'platform', categoryId: a.category,
  tags: [], bodyMd: a.body, bindings: a.bindings.map(([appCode, sectionKey, weight]) => ({ appCode, sectionKey, weight })) }))
const categories = [...new Set(articles.map(a => a.category))].map(title => ({ id: title, title,
  articles: rows.filter(a => a.categoryId === title), count: rows.filter(a => a.categoryId === title).length, children: [] }))
const tree = { profile: 'energy', total: rows.length, groups: [{ key: 'guide', label: 'Работа в системе', hint: 'Инструкции по приложениям',
  count: rows.length, categories: [{ id: 'voice-root', title: 'Телефония', count: rows.length, articles: [], children: categories }], loose: [] }] }
const errors = [], missing = new Set(), screens = [], contexts = []
let server, browser, page
let sourceDelay = 0

function matchingArticles(section) {
  const parts = section.split(':')
  const keys = parts.map((_, index) => parts.slice(0, parts.length - index).join(':'))
  const rank = a => Math.min(...a.bindings.map(b => b.sectionKey == null ? keys.length : keys.indexOf(b.sectionKey)).filter(n => n >= 0))
  return rows.filter(a => a.bindings.some(b => !b.sectionKey || keys.includes(b.sectionKey)))
    .sort((a, b) => rank(a) - rank(b)).slice(0, 8)
    .map(a => ({ ...a, exact: a.bindings.some(b => b.sectionKey && keys.includes(b.sectionKey)) }))
}

function helpReply(path, query) {
  if (path === '/api/info/tree') return tree
  if (path === '/api/info/context') {
    const section = query.get('section_key'); contexts.push(section)
    const items = matchingArticles(section)
    return { appCode: 'voice', sectionKey: section, items, empty: !items.length }
  }
  if (path === '/api/info/search') return { query: query.get('q'), items: rows
    .filter(a => (a.title + ' ' + a.bodyMd).toLowerCase().includes(query.get('q').toLowerCase()))
    .map(a => ({ ...a, snippet: a.summary })) }
  if (path.startsWith('/api/info/articles/')) return rows.find(a => a.id === path.split('/').at(-1))
  return undefined
}

try {
  // Меняется только демонстрационное наполнение: компоненты и маршруты штатные.
  const demoCompanies = `export const defaultCompanies: Company[] = [
    { id: '${companyId}', name: 'Меридиан · учебные данные', shortName: 'Меридиан · учебные данные', color: '#006a9f', profileId: 'energy' },
  ]`
  server = await createServer({ root, cacheDir: join(root, 'node_modules/.vite-voice-help-20261020'),
    server: { host: '127.0.0.1', port: 0, open: false, watch: { ignored: ['**/public/help/voice/**'] } },
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(''), 'import.meta.env.VITE_VOICE_API_URL': JSON.stringify(''), 'import.meta.env.VITE_VOICE_DEV_TOKEN_URL': JSON.stringify('') },
    plugins: [{ name: 'voice-help-demo', enforce: 'pre',
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url.split('?')[0] !== '/voice/api/v1/now/stream') return next()
          response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
          response.write(nodeReply('/now/stream', new URLSearchParams(), 'GET').sse)
          const ping = setInterval(() => response.write(': ping\n\n'), 1000)
          request.on('close', () => clearInterval(ping))
        })
      },
      async load(id) {
        if (id.endsWith('/src/config/companies.ts')) return (await readFile(id, 'utf8'))
          .replace(/export const defaultCompanies: Company\[\] = \[[\s\S]*?\n\]/, demoCompanies)
          .replace("export const defaultCompanyId = 'gig'", `export const defaultCompanyId = '${companyId}'`)
        if (id.endsWith('/src/contexts/AuthContext.tsx')) return (await readFile(id, 'utf8')).replace("name: 'Demo'", "name: 'Анна Ветрова'")
      } }] })
  await server.listen()
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/usr/bin/chromium' })
  const context = await browser.newContext({ viewport: { width: 1680, height: 1050 }, locale: 'ru-RU', timezoneId: 'Europe/Moscow' })
  await context.addInitScript(() => {
    window.__voiceHelpNavigation = []
    for (const method of ['pushState', 'replaceState']) {
      const original = history[method]
      history[method] = function (...args) {
        window.__voiceHelpNavigation.push({ method, url: String(args[2]), stack: new Error().stack })
        return original.apply(this, args)
      }
    }
    localStorage.setItem('theme', 'light')
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
    localStorage.setItem('info:fontStep', '1')
    localStorage.setItem('clearledger-sidebar-open', 'true')
  })
  await context.addCookies([{ name: 'sidebar_state', value: 'true', url: origin }])
  // Внешние адреса блокируются. Ни проверка, ни съёмка не могут попасть в рабочий API.
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    // Съёмка автономная: внешний необязательный stylesheet заменяем пустым.
    // Остальные адреса вне loopback запрещены; шрифты берутся из системного стека.
    if (url.hostname === 'fonts.googleapis.com' && url.pathname === '/css2') return route.fulfill({ contentType: 'text/css', body: '' })
    if (url.origin !== origin) { missing.add(`external: ${url.origin}${url.pathname}`); return route.abort() }
    if (!url.pathname.includes('/api/')) return route.continue()
    if (url.pathname === '/voice/api/v1/now/stream') return route.continue()
    if (url.pathname === '/api/voice/megafon' && sourceDelay) await new Promise(resolve => setTimeout(resolve, sourceDelay))
    let data = url.pathname.startsWith('/voice/api/v1')
      ? nodeReply(url.pathname.slice('/voice/api/v1'.length), url.searchParams, request.method())
      : helpReply(url.pathname, url.searchParams) ?? coreReply(url.pathname, url.searchParams)
    if (data === undefined) {
      missing.add(`${request.method()} ${url.pathname}`)
      return route.fulfill({ status: 501, json: { detail: 'Нет учебного ответа для этого запроса' } })
    }
    if (data?.sse) return route.fulfill({ contentType: 'text/event-stream', body: data.sse })
    return route.fulfill({ json: data, headers: { ETag: '"help-3"' } })
  })
  page = await context.newPage()
  page.setDefaultTimeout(25_000)
  await page.clock.setFixedTime(new Date(at))
  page.on('pageerror', e => errors.push(e.message))
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()) })
  async function ready(path, heading) {
    await page.goto(origin + path, { waitUntil: 'domcontentloaded' })
    if (new URL(path, origin).searchParams.has('call')) await page.getByRole('dialog').getByRole('heading', { name: 'Карточка звонка', exact: true }).waitFor()
    else if (heading === 'Инфо') await page.getByPlaceholder('Поиск по знанию пространства').waitFor()
    else if (heading === 'Нужен контакт') await page.getByText('Ждут контакта', { exact: true }).waitFor()
    else await page.getByRole('heading', { name: heading, exact: true }).first().waitFor()
    await page.waitForFunction(() => !Array.from(document.querySelectorAll('[role="status"]')).some(el =>
      el.getBoundingClientRect().height && /Читаем|Проверяем|Загружаем/.test(el.textContent)))
    const later = page.getByRole('button', { name: 'Позже', exact: true })
    if (await later.isVisible()) await later.click()
    assert.equal(await page.locator('vite-error-overlay').count(), 0)
    assert.match(await page.title(), /Телефония|Инфо/)
    assert.ok((await page.locator('body').innerText()).length > 200)
    assert.doesNotMatch(await page.locator('body').innerText(), /Нет учебного ответа|Узел не пустил|Узел заказчика не отвечает/)
  }
  async function screenshot(name, directory = shots) {
    await page.waitForFunction(() => !Array.from(document.querySelectorAll('[role="status"]')).some(el =>
      el.getBoundingClientRect().height && /Читаем|Проверяем|Загружаем|Подбираем/.test(el.textContent)))
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'Нет переполнения страницы')
    await page.screenshot({ path: join(directory, `${name}.png`), animations: 'disabled' })
    screens.push({ name, route: new URL(page.url()).pathname + new URL(page.url()).search, viewport: page.viewportSize() })
  }
  const targets = [
    ['', 'Сейчас'], ['megafon', 'МегаФон ВАТС'], ['calls?source=node', 'Журнал звонков'], ['contact', 'Нужен контакт'],
    ['callbacks', 'Обратные звонки'], ['stats?source=node', 'Статистика'], ['report?source=node', 'Отчёт за месяц'],
    ['reconcile', 'Сверка с оператором связи'], ['reception', 'Правила приёма'], ['passport', 'Паспорт для КЦ'],
    ['targets', 'Сотрудники и переводы'], ['sounds', 'Звуки'], ['enrichment', 'Распознавание и подсказки'],
    ['connections', 'Настройки подключений'], ['cc', 'Контакт-центры'], ['webhooks', 'Системы и вебхуки'],
    ['versions', 'Версии и изменения'], ['audit', 'Аудит доступа'], ['retention', 'Записи и хранение'], ['health', 'Состояние узла'],
    ['extensions', 'Внутренние номера'], ['report?source=megafon', 'Отчёт за месяц'],
  ]
  const defaultKeys = { megafon: 'megafon:calls', calls: 'calls:node', stats: 'stats:node',
    report: 'report:node', reception: 'reception:hours', passport: 'passport:presentation',
    webhooks: 'webhooks:hooks', versions: 'versions:rev' }
  if (process.env.VOICE_HELP_FOCUS !== '1') {
  for (const [path, heading] of targets) {
    process.stdout.write(`Проверка: ${path || 'now'}\n`)
    const key = path.split('?')[0] || 'now'
    await ready('/voice' + (path ? '/' + path : ''), heading)
    await screenshot(path.includes('source=megafon') ? 'voice-report-megafon' : `voice-${key}`)
    // На каждом экране проверяем правую помощь, а не только наличие PNG.
    await page.getByRole('button', { name: 'Инфо', exact: true }).last().click()
    const expected = path.includes('source=megafon') ? 'report:megafon' : defaultKeys[key] ?? key
    await page.getByRole('complementary', { name: 'Контекстная помощь' }).getByText(matchingArticles(expected)[0].title, { exact: true }).waitFor()
    assert.equal(contexts.at(-1), expected, `Контекст ${path} соответствует меню`)
  }
  for (const [path, heading, name, expected] of [
    ['/voice/megafon?view=operators', 'МегаФон ВАТС', 'voice-megafon-operators', 'megafon:operators'],
    ['/voice/megafon?view=groups', 'МегаФон ВАТС', 'voice-megafon-groups', 'megafon:groups'],
    ['/voice/passport?tab=access', 'Паспорт для КЦ', 'voice-passport-access', 'passport:access'],
    ['/voice/passport?tab=privacy', 'Паспорт для КЦ', 'voice-passport-privacy', 'passport:privacy'],
    ['/voice/webhooks?tab=keys', 'Системы и вебхуки', 'voice-webhooks-keys', 'webhooks:keys'],
  ]) {
    process.stdout.write(`Проверка вкладки: ${expected}\n`)
    await ready(path, heading)
    await screenshot(name)
    await page.getByRole('button', { name: 'Инфо', exact: true }).last().click()
    await page.getByRole('complementary', { name: 'Контекстная помощь' }).getByText(matchingArticles(expected)[0].title, { exact: true }).waitFor()
    assert.equal(contexts.at(-1), expected)
  }
  await ready('/voice/megafon?call=demo-call-1', 'МегаФон ВАТС')
  await page.getByRole('dialog').getByText('МегаФон ВАТС · данные истории').waitFor()
  await screenshot('voice-megafon-card')
  await ready('/voice/calls?source=node&id=demo-call-1', 'Журнал звонков')
  await page.getByText('Зарядка восстановлена после консультации', { exact: false }).waitFor()
  await screenshot('voice-call-card')
  }

  // Интерактивная проверка: из правой помощи открывается текст нужной статьи.
  await ready('/voice/health', 'Состояние узла')
  await page.getByRole('button', { name: 'Инфо', exact: true }).last().click()
  await page.getByText('Состояние узла: найти причину отказа', { exact: true }).click()
  await page.getByText('Разобрать проблему', { exact: true }).waitFor()
  await screenshot('voice-help-context', artifacts)
  const image = page.locator('img[alt="Части узла и история состояний"]')
  await image.waitFor()
  assert.equal(await image.evaluate(img => img.complete && img.naturalWidth > 0), true, 'Иллюстрация справки загружается')

  // Переход без перезагрузки: правый док остаётся открыт и меняет содержимое.
  const help = page.getByRole('complementary', { name: 'Контекстная помощь' })
  await page.locator('a[href="/voice/calls"]').first().click()
  await help.getByText('МегаФон ВАТС: история, операторы и группы', { exact: true }).click()
  await help.getByText('Найти разговор', { exact: true }).waitFor()
  await page.getByLabel('Источник данных', { exact: true }).selectOption('node')
  await help.getByText('Журнал звонков узла: поиск и отбор', { exact: true }).waitFor()
  assert.equal(await help.getByText('МегаФон ВАТС: история, операторы и группы', { exact: true }).count(), 0)
  assert.equal(await help.getByRole('button', { name: 'Назад к списку' }).count(), 0, 'Открытая статья сброшена после смены источника')
  await screenshot('context-node-journal', artifacts)
  await help.getByText('Журнал звонков узла: поиск и отбор', { exact: true }).click()
  await help.getByText('Найти нужный звонок', { exact: true }).waitFor()
  await page.getByRole('button', { name: '7 дней', exact: true }).click()
  await help.getByText('Найти нужный звонок', { exact: true }).waitFor()
  await page.locator('table tbody tr').first().click()
  await help.getByText('Карточка звонка: участки, запись и итог', { exact: true }).waitFor()
  assert.equal(await help.getByRole('button', { name: 'Назад к списку' }).count(), 0)
  await screenshot('context-node-card', artifacts)

  // Пока автоматический выбор источника не закончен, помощь узла не мелькает.
  sourceDelay = 2000
  const before = contexts.length
  await page.goto(origin + '/voice/calls', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Инфо', exact: true }).last().click()
  await help.getByText('Подбираем помощь для источника данных…').waitFor()
  await help.getByText('МегаФон ВАТС: история, операторы и группы', { exact: true }).waitFor()
  assert.ok(contexts.slice(before).every(key => key.startsWith('calls:megafon')), 'Автоматический источник учитывается без source в URL')
  sourceDelay = 0
  await page.getByRole('tab', { name: 'Группы', exact: true }).click()
  await help.getByText('МегаФон: группы и полнота сведений', { exact: true }).waitFor()
  assert.equal(await help.getByText('МегаФон: показатели операторов', { exact: true }).count(), 0)
  await screenshot('context-megafon-groups', artifacts)

  await ready('/voice/passport?tab=privacy', 'Паспорт для КЦ')
  await page.getByRole('button', { name: 'Инфо', exact: true }).last().click()
  await help.getByText('Паспорт КЦ: приватность карточки', { exact: true }).click()
  await page.getByRole('tab', { name: 'Допуск операторов', exact: true }).click()
  await help.getByText('Паспорт КЦ: допуск операторов', { exact: true }).waitFor()
  assert.equal(await help.getByRole('button', { name: 'Назад к списку' }).count(), 0)
  await screenshot('context-passport-access', artifacts)

  for (const [route, heading, providerTitle, nodeTitle, contextKey] of [
    ['stats', 'Статистика', 'МегаФон: показатели операторов', 'Статистика: от показателя к звонкам', 'stats:node'],
    ['report', 'Отчёт за месяц', 'МегаФон: отчёт за месяц', 'Отчёт за месяц: источник, версия и выгрузка', 'report:node'],
  ]) {
    await ready(`/voice/${route}?source=megafon`, heading)
    await page.getByRole('button', { name: 'Инфо', exact: true }).last().click()
    await help.getByText(providerTitle, { exact: true }).click()
    await page.getByLabel('Источник данных', { exact: true }).selectOption('node')
    await help.getByText(nodeTitle, { exact: true }).waitFor()
    assert.equal(await help.getByText(providerTitle, { exact: true }).count(), 0)
    assert.equal(contexts.at(-1), contextKey)
    assert.equal(await page.getByLabel('Источник данных', { exact: true }).inputValue(), 'node')
    await screenshot(`context-${route}-node`, artifacts)
    await page.getByLabel('Источник данных', { exact: true }).selectOption('megafon')
    await help.getByText(providerTitle, { exact: true }).waitFor()
    assert.equal(await help.getByText(nodeTitle, { exact: true }).count(), 0)
  }

  await ready('/info', 'Инфо')
  await page.getByPlaceholder(/Поиск/).first().fill('Телефония: с чего начать')
  await page.getByText('Телефония: с чего начать', { exact: true }).first().click()
  await page.getByText('Выберите задачу', { exact: true }).waitFor()
  await screenshot('voice-help-info', artifacts)

  await page.setViewportSize({ width: 390, height: 844 })
  await ready('/voice/connections', 'Настройки подключений')
  await screenshot('voice-mobile-connections', artifacts)
  await page.getByLabel('Раздел Телефонии', { exact: true }).selectOption('/voice/health')
  await page.getByRole('heading', { name: 'Состояние узла', exact: true }).waitFor()
  await page.getByText('Учебная линия', { exact: true }).first().waitFor()
  await screenshot('voice-mobile-health', artifacts)

  assert.deepEqual([...missing], [], 'Все запросы имеют явные учебные ответы')
  assert.deepEqual(errors, [], 'Нет ошибок приложения в браузере')
  await writeFile(join(artifacts, 'evidence.json'), JSON.stringify({ browser: 'Browser plugin not available; Playwright Chromium',
    source: 'Настоящие страницы и оболочка; все API синтетические; рабочая сеть запрещена', origin, screens, contexts, errors, missing: [...missing] }, null, 2))
  process.stdout.write(`PASS: ${screens.length} снимков, контекст разделов/источников/вкладок, сброс статьи, автоматический источник, мобильный переход.\nДоказательства: ${artifacts}\n`)
} catch (error) {
  const navigation = page && !page.isClosed() ? await page.evaluate(() => window.__voiceHelpNavigation).catch(() => []) : []
  await writeFile(join(artifacts, 'failure.json'), JSON.stringify({ error: String(error), url: page?.url(), navigation, errors, missing: [...missing], contexts }, null, 2))
  if (page && !page.isClosed()) {
    await page.screenshot({ path: join(artifacts, 'failure.png') }).catch(() => {})
    await writeFile(join(artifacts, 'failure.txt'), await page.locator('body').innerText().catch(() => ''))
  }
  process.stderr.write(`Доказательства отказа: ${artifacts}\n`)
  throw error
} finally {
  await browser?.close()
  await server?.close()
}
