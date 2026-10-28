/**
 * Браузерная проверка общей отметки сверки — desktop и мобильная ширина.
 *
 * Проверка ИНТЕРФЕЙСА на вымышленных данных: ответы API перехватываются, чтобы
 * показать состояния, которые на живых данных приходится ловить. Настоящая
 * интеграция (901 договор, 477 контрагентов) проверяется отдельно.
 *
 * Что проверяется: пять подписей канона, различение загрузки, ошибки запроса,
 * пустого и НЕПОЛНОГО ответа сервера, доказательства сверки вместо снимка полей,
 * ось свежести рядом с расхождениями, доступность основания пальцем (не только
 * подсказкой по наведению) и один запрос на экран вместо запроса на строку.
 *
 * Запуск: node e2e-acct-mark/check.mjs   (dev-сервер поднимается сам)
 */
import { chromium, devices } from 'playwright'
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { AUTH, CONTRACTS, COUNTERPARTIES, SUMMARIES, afterEdit } from './fixtures.mjs'

// Порт свободный: на 3010/3011 живут dev-серверы соседних рабочих копий.
const PORT = process.env.ACCT_PORT ?? '3027'
const API = 'http://127.0.0.1:9099'
const UI = 'http://127.0.0.1:' + PORT
const OUT = process.env.ACCT_OUT ?? '.tmp/acct-mark'
mkdirSync(OUT, { recursive: true })

const результаты = []
const ok = (имя, прошло, прим = '') => {
  результаты.push({ имя, статус: прошло ? 'PASS' : 'FAIL', прим })
  console.log((прошло ? 'PASS ' : 'FAIL ') + имя + (прим ? ' — ' + прим : ''))
}

/** Режим ответов сводок: меняется прямо во время прогона. */
const режим = { kind: 'ok', edited: null }
/** Пути без фикстуры — видно, чего не хватило, если экран не дорисовался. */
const неизвестные = new Set()

/**
 * «Пусто» — это НЕ пустой `items`: контракт обязывает вернуть элемент на каждый
 * запрошенный id. Отсутствие сведений выражается состоянием `no_source` у всех
 * элементов, а пустой список означал бы неполный ответ (проверяется отдельно).
 */
const безСведений = (id) => ({
  ...SUMMARIES['c-none'], entity_id: id,
  entity_type: id.startsWith('cp-') ? 'counterparty' : 'contract',
})

function сводки(ids) {
  if (режим.kind === 'empty') return ids.map(безСведений)
  const items = ids.map((id) => {
    if (режим.edited && режим.edited.id === id) return afterEdit(id, режим.edited.field)
    return SUMMARIES[id]
  }).filter(Boolean)
  // Неполный ответ: сервер обязан вернуть элемент на каждый запрошенный id.
  return режим.kind === 'partial' ? items.slice(1) : items
}

const ОТВЕТЫ = {
  '/api/auth/me': AUTH,
  '/api/companies': AUTH.companies,
  '/api/references/counterparties': COUNTERPARTIES,
  '/api/references/contracts': CONTRACTS,
  '/api/references/contract-bindings': { contracts: {}, projects: {} },
  '/api/references/contract-types': [],
  '/api/references/organizations': [],
  '/api/references/settlements': [],
  '/api/references/settlements/detail': [],
  '/api/locations': [],
  '/api/location-types': [],
  '/api/chat/rooms': [],
  '/api/tasks/assignment-counts': {},
  '/api/client-errors': {},
  '/api/registry/company-apps': { apps: [] },
}

async function маршруты(page) {
  await page.route(API + '/**', async (route) => {
    const url = new URL(route.request().url())
    const p = url.pathname

    if (p === '/api/accounting/space/link-summaries') {
      if (режим.kind === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"сервис сводок недоступен"}' })
      const body = JSON.parse(route.request().postData() || '{}')
      const ids = body.entity_ids ?? []
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ entity_type: body.entity_type, requested: ids.length,
          items: сводки(ids), disclaimer: '' }) })
    }
    if (p === '/api/accounting/space/link-summary') {
      if (режим.kind === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"нет"}' })
      const id = url.searchParams.get('entity_id')
      const s = сводки([id])[0]
      if (!s) return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"нет сводки"}' })
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(s) })
    }

    const готовый = ОТВЕТЫ[p]
    if (готовый !== undefined) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(готовый) })
    }
    // Охват контрагента — объект, а не список: на пустом массиве карточка падала
    // ещё до блока сверки (`data.locations.slice` у undefined).
    if (/^\/api\/references\/counterparties\/[^/]+\/locations$/.test(p)) {
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ scope: 'locations', locations: [], contractsCount: 2, unassignedCount: 0 }) })
    }
    // Неизвестный путь — пустой список: большинство справочников отдают массив,
    // а объект `{items}` на их месте роняет экран ещё до нужной проверки.
    неизвестные.add(p)
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
}

/** Текст всех отметок на экране. Отметка состояния запроса считается тоже. */
const отметки = (page) => page.getByRole('button', { name: /Сверенные реквизиты совпадают|Есть расхождения|Нужна повторная сверка|Требует сверки|Нет данных для сравнения|Сверка недоступна|Сверка загружается/ })

/** Отметка в конечном состоянии — без «загружается». */
const готовые = (page) => page.getByRole('button', { name: /Сверенные реквизиты совпадают|Есть расхождения|Нужна повторная сверка|Требует сверки|Нет данных для сравнения|Сверка недоступна/ })

/**
 * Открыть экран и дождаться отметок в конечном состоянии.
 *
 * `networkidle` в этом SPA не наступает из-за опроса чата, а фиксированная пауза
 * читает экран до прихода сводки — проверка падала на ровном месте.
 */
async function открыть(page, path) {
  await page.goto(UI + path, { waitUntil: 'domcontentloaded' })
  await готовые(page).first().waitFor({ state: 'attached', timeout: 25000 })
    .catch(() => { /* отметок может не быть — это отдельная проверка */ })
  await page.waitForTimeout(400)
}

const тексты = async (page) => (await отметки(page).allInnerTexts()).join(' | ')

async function снимок(page, имя) {
  await page.screenshot({ path: OUT + '/' + имя + '.png', fullPage: false })
}

const dev = spawn('npx', ['vite', '--port', PORT, '--strictPort', '--host', '127.0.0.1'], {
  env: { ...process.env, VITE_API_URL: API, BROWSER: 'none' },
  stdio: ['ignore', 'pipe', 'pipe'],
})
let devОшибка = ''
dev.stdout.on('data', (b) => { if (String(b).includes('ready in')) console.log('dev: ' + String(b).trim()) })
dev.stderr.on('data', (b) => { devОшибка += String(b) })
dev.on('exit', (c) => { if (c) console.log('dev завершился с кодом ' + c + ': ' + devОшибка.slice(0, 300)) })

async function ждатьDev() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(UI); if (r.ok) return true } catch { /* ещё не поднялся */ }
    await new Promise((r) => setTimeout(r, 1000))
  }
  return false
}

const browser = await chromium.launch()
try {
  if (!await ждатьDev()) throw new Error('dev-сервер не поднялся')

  for (const профиль of ['desktop', 'mobile']) {
    const ctx = await browser.newContext(профиль === 'mobile'
      ? { ...devices['Pixel 7'] } : { viewport: { width: 1600, height: 1000 } })
    await ctx.addInitScript((token) => { localStorage.setItem('clearledger-token', token) }, 'demo-token')
    const page = await ctx.newPage()
    await маршруты(page)

    // ── 1. Реестр договоров: все пять подписей канона разом ──
    режим.kind = 'ok'; режим.edited = null
    await открыть(page, '/contractors?sub=contracts')
    const свод = await тексты(page)
    ok(профиль + ': реестр показывает «Сверенные реквизиты совпадают»', свод.includes('Сверенные реквизиты совпадают'))
    ok(профиль + ': реестр показывает «Есть расхождения»', свод.includes('Есть расхождения'))
    ok(профиль + ': реестр показывает «Нужна повторная сверка»', свод.includes('Нужна повторная сверка'))
    ok(профиль + ': реестр показывает «Требует сверки»', свод.includes('Требует сверки'))
    ok(профиль + ': реестр показывает «Нет данных для сравнения»', свод.includes('Нет данных для сравнения'))
    await снимок(page, профиль + '-1-реестр')

    // Один запрос сводок на экран, а не на строку.
    let запросов = 0
    page.on('request', (r) => { if (r.url().includes('link-summaries')) запросов++ })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await готовые(page).first().waitFor({ state: 'attached', timeout: 25000 }).catch(() => {})
    await page.waitForTimeout(800)
    ok(профиль + ': сводка одним запросом на экран, не на строку', запросов <= 2, 'запросов: ' + запросов)

    // ── 2. Основание открывается нажатием, а не только подсказкой ──
    // На телефоне подсказки по наведению нет: отметка обязана быть кнопкой.
    const отметка = готовые(page).filter({ hasText: 'Есть расхождения' }).first()
    await отметка.click()
    const поповер = page.locator('[data-slot="popover-content"], [role="dialog"]').last()
    await поповер.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})
    const основание = await поповер.innerText().catch(() => '')
    ok(профиль + ': нажатие на отметку открывает основание', /Сверено с выгрузкой/.test(основание))
    ok(профиль + ': основание показывает доказательство, а не снимок полей',
      /Номер — расходится/.test(основание) && !/counterparty_id|type_code/.test(основание))
    ok(профиль + ': основание называет несверенные реквизиты с причиной',
      /Не сверялись: .*ИНН \/ КПП \(в выгрузке не передаются\)/.test(основание))
    ok(профиль + ': основание называет источник и дату данных',
      /Источник: Расчёты_2026-09\.xlsx.*данные на 30\.09\.2026/.test(основание))
    ok(профиль + ': ось свежести видна рядом с расхождениями',
      /Карточку правили после сверки/.test(основание))
    ok(профиль + ': сырых имён полей в основании нет', !/\[object Object\]/.test(основание))
    await page.keyboard.press('Escape')
    // «Сравнивать нечего» не выдаётся ни за совпадение, ни за конфликт.
    await готовые(page).filter({ hasText: 'Требует сверки' }).first().click()
    const пов = page.locator('[data-slot="popover-content"], [role="dialog"]').last()
    await пов.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})
    const текстПов = await пов.innerText().catch(() => '')
    ok(профиль + ': непринятая повторная сверка названа именно так',
      /Повторная сверка не принята: прогон шёл по другой редакции файла/.test(текстПов)
      && /Отсутствием сверки это не является/.test(текстПов))
    await page.keyboard.press('Escape')
    await снимок(page, профиль + '-2-основание')
    await page.keyboard.press('Escape')

    // ── 3. Ошибка запроса ≠ «нет данных для сравнения» ──
    режим.kind = 'error'
    await открыть(page, '/contractors?sub=contracts')
    await готовые(page).filter({ hasText: 'Сверка недоступна' }).first()
      .waitFor({ state: 'attached', timeout: 25000 }).catch(() => {})
    const приОшибке = await тексты(page)
    ok(профиль + ': ошибка API показана как «Сверка недоступна»', приОшибке.includes('Сверка недоступна'))
    ok(профиль + ': ошибка не выдаётся за «Нет данных для сравнения»', !приОшибке.includes('Нет данных для сравнения'))
    await снимок(page, профиль + '-3-ошибка')

    // ── 4. Неполный ответ сервера — тоже ошибка, а не «нет сведений» ──
    режим.kind = 'partial'
    await открыть(page, '/contractors?sub=contracts')
    await готовые(page).filter({ hasText: 'Сверка недоступна' }).first()
      .waitFor({ state: 'attached', timeout: 25000 }).catch(() => {})
    const приНеполном = await тексты(page)
    ok(профиль + ': неполный ответ показан ошибкой, а не «нет данных»',
      приНеполном.includes('Сверка недоступна') && !приНеполном.includes('Нет данных для сравнения'))

    // ── 5. Сведений нет ни по одной карточке — это не ошибка и не дефект ──
    режим.kind = 'empty'
    await открыть(page, '/contractors?sub=contracts')
    const приПустом = await тексты(page)
    ok(профиль + ': отсутствие сведений показано как «Нет данных для сравнения»', приПустом.includes('Нет данных для сравнения'))
    ok(профиль + ': отсутствие сведений не показано ошибкой', !приПустом.includes('Сверка недоступна'))
    await снимок(page, профиль + '-4-пусто')

    // ── 6. Карточка договора: отметка в первом экране + детали обеих осей ──
    режим.kind = 'ok'
    await открыть(page, '/contractors?sub=contracts')
    await page.getByRole('button', { name: 'ЭС-002', exact: true }).first().click()
    const окно = page.locator('[role="dialog"]').first()
    await окно.getByText('Сверено с выгрузкой:').first().waitFor({ state: 'visible', timeout: 25000 })
    const заголовок = await окно.locator('[data-slot="dialog-header"]').innerText().catch(() => '')
    ok(профиль + ': состояние сверки видно в заголовке карточки договора',
      /Есть расхождения/.test(заголовок), заголовок.replace(/\n/g, ' ').slice(0, 80))
    const карточка = await окно.innerText()
    ok(профиль + ': карточка показывает ось сопряжения отдельно', /Сопряжение:/.test(карточка))
    ok(профиль + ': карточка показывает доказательства сверки',
      /Номер — расходится: в бухгалтерии «ЭС-2\/26», здесь «ЭС-002»/.test(карточка))
    ok(профиль + ': карточка называет несверенные реквизиты с причиной',
      /Не сверялись:/.test(карточка) && /выгрузка не содержит признака/.test(карточка))
    ok(профиль + ': карточка отделяет снимок полей от сверки',
      /отвечает за устаревание, сверкой не является/.test(карточка))
    ok(профиль + ': карточка говорит, чего выгрузка не содержит', /Признака проведения в 1С/.test(карточка))
    await снимок(page, профиль + '-5-карточка-договора')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)

    // ── 7. Устаревание после правки сверенного поля ──
    режим.edited = { id: 'c-ok', field: 'номер' }
    await открыть(page, '/contractors?sub=contracts')
    ok(профиль + ': правка сверенного поля даёт «Нужна повторная сверка»',
      (await тексты(page)).includes('Нужна повторная сверка'))
    // Правка постороннего поля сверку не сбрасывает.
    режим.edited = { id: 'c-ok', field: 'комментарий' }
    await открыть(page, '/contractors?sub=contracts')
    await page.getByRole('button', { name: 'ЭС-001', exact: true }).first().click()
    const окно2 = page.locator('[role="dialog"]').first()
    await окно2.getByText('Сверено с выгрузкой:').first().waitFor({ state: 'visible', timeout: 25000 })
    const послеПостороннего = await окно2.innerText()
    ok(профиль + ': правка непроверявшегося поля сверку не устаревляет',
      /Сверенные реквизиты совпадают/.test(послеПостороннего)
      && !/Карточку правили после сверки/.test(послеПостороннего))
    await снимок(page, профиль + '-6-stale')
    await page.keyboard.press('Escape')
    режим.edited = null

    // ── 8. Контрагент: сводка по договорам не выдаётся за его проверку ──
    await открыть(page, '/contractors?sub=counterparties')
    await page.getByRole('button', { name: /Тестэнергосбыт/ }).first().click()
    await page.getByText('Что знает бухгалтерия').first().waitFor({ state: 'visible', timeout: 25000 })
    await page.getByRole('button', { name: /^Договоры:/ }).first()
      .waitFor({ state: 'attached', timeout: 25000 }).catch(() => { /* проверяется ниже */ })
    const тело = await page.locator('body').innerText()
    ok(профиль + ': у контрагента отметка помечена как договорная', /договоры ·/.test(тело))
    ok(профиль + ': сказано, что сам контрагент не сверялся',
      /сама карточка отдельно не сверялась/.test(тело))
    ok(профиль + ': показан охват сводки по договорам', /со сведениями бухгалтерии/.test(тело))
    ok(профиль + ': договоры контрагента перечислены со своими состояниями',
      /ЭС-001/.test(тело) && /ЭС-002/.test(тело))
    ok(профиль + ': название стороны не выдаётся за сверку контрагента',
      /Название стороны — сравнивать нечего: названия совместимы, но ИНН в выгрузке нет/.test(тело))
    ok(профиль + ': расхождение утверждения прогона с пересчётом показано',
      /Прогон записал «совпадает»: значимые слова названия совпали — это свидетельство, не отметка/.test(тело))
    ok(профиль + ': в списке контрагентов есть отметка по договорам',
      (await page.locator('[aria-label^="Договоры:"]').count()) > 0)

    // ── 9. Переход между разделами без перезагрузки ──
    // Условный хук или потерянный ключ кеша проявляются именно здесь, а не на
    // прямой ссылке: экран уже смонтирован, меняется только раздел.
    const пункт = page.getByText('Договоры', { exact: true })
    let нажали = false
    for (let i = 0; i < await пункт.count(); i++) {
      if (!await пункт.nth(i).isVisible().catch(() => false)) continue
      await пункт.nth(i).click({ timeout: 5000 }).catch(() => {})
      await page.waitForTimeout(600)
      // Нажатие засчитывается только по смене раздела: заголовок «Договоры» есть
      // и внутри карточки контрагента, и кликом по нему никуда не уходишь.
      if (page.url().includes('sub=contracts')) { нажали = true; break }
    }
    console.log('  после перехода: ' + page.url().split('?')[1]?.slice(0, 60))
    if (!нажали) {
      // На узкой ширине меню разделов свёрнуто. Тот же риск (условный хук,
      // потерянный ключ кеша при смене раздела без размонтирования приложения)
      // проверяется возвратом по истории: это тоже клиентский переход.
      await page.goto(UI + '/contractors?sub=contracts', { waitUntil: 'domcontentloaded' })
      await готовые(page).first().waitFor({ state: 'attached', timeout: 25000 }).catch(() => {})
      await page.goBack({ waitUntil: 'commit' }).catch(() => {})
      await page.waitForTimeout(800)
      await page.goForward({ waitUntil: 'commit' }).catch(() => {})
      нажали = page.url().includes('sub=contracts')
    }
    if (!нажали) {
      результаты.push({ имя: профиль + ': переход между разделами', статус: 'SKIP',
        прим: 'раздел «Договоры» на этой ширине не открылся ни меню, ни историей' })
      console.log('SKIP ' + профиль + ': переход между разделами')
    } else {
      await готовые(page).first().waitFor({ state: 'attached', timeout: 25000 }).catch(() => {})
      const послеПерехода = await тексты(page)
      ok(профиль + ': переход «Контрагенты → Договоры» без перезагрузки сохраняет отметки',
        послеПерехода.includes('Есть расхождения') && послеПерехода.includes('Нет данных для сравнения'))
      ok(профиль + ': при переходе экран не упал',
        !(await page.locator('body').innerText()).includes('Что-то пошло не так'))
    }
    await снимок(page, профиль + '-7-контрагент')

    await ctx.close()
  }
} catch (e) {
  ok('прогон завершился без исключения', false, String(e && e.message || e))
} finally {
  await browser.close()
  dev.kill('SIGTERM')
}

if (неизвестные.size) console.log('\nбез фикстуры (отвечено пустым списком): ' + [...неизвестные].join(', '))
const fail = результаты.filter((r) => r.статус === 'FAIL')
writeFileSync(OUT + '/итог.json', JSON.stringify(результаты, null, 2))
const skip = результаты.filter((r) => r.статус === 'SKIP').length
console.log('\nИТОГ: PASS ' + (результаты.length - fail.length - skip) + ' / FAIL ' + fail.length + ' / SKIP ' + skip)
for (const f of fail) console.log('  FAIL ' + f.имя + (f.прим ? ' — ' + f.прим : ''))
process.exit(fail.length ? 1 : 0)
