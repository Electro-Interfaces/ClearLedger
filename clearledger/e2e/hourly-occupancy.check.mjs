/** Из clearledger: node e2e/hourly-occupancy.check.mjs
 * Browser plugin not available; используется локальный Playwright.
 * Проверяет только UI и параметры API на синтетических ответах, не backend-расчёт.
 */
import assert from 'node:assert/strict'
import { mkdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { createServer } from 'vite'
import XLSX from 'xlsx'
const { chromium, firefox, webkit, devices, expect } = await import(process.env.RH_PW_MODULE || '@playwright/test')

const artifactDir = resolve(process.env.RH_HOURLY_ARTIFACT_DIR || resolve(tmpdir(), 'hourly-occupancy-artifacts'))
mkdirSync(artifactDir, { recursive: true })
const server = await createServer({
  server: { host: '127.0.0.1', port: 4318, strictPort: true, open: false },
  plugins: [{ name: 'hourly-ui-fixture', configureServer(vite) {
    vite.middlewares.use('/hourly-check', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html; charset=utf-8')
      res.end(await vite.transformIndexHtml('/hourly-check', '<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Почасовая занятость · UI проверка</title></head><body><div id="root"></div><script type="module" src="/e2e/hourly-occupancy.fixture.tsx"></script></body></html>'))
    })
  } }],
})
await server.listen()
const engine = process.env.RH_HOURLY_BROWSER || 'chromium'
const browser = await ({ chromium, firefox, webkit })[engine].launch({ headless: true, ...(engine === 'chromium' ? { executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium' } : {}) })
const profiles = process.env.RH_HOURLY_DEVICE
  ? [[process.env.RH_HOURLY_DEVICE, devices[process.env.RH_HOURLY_DEVICE]]]
  : [['desktop', { viewport: { width: 1440, height: 1000 } }], ['mobile', { viewport: { width: 390, height: 844 } }]]
const ports = [
  { id: 'station-a:1', label: 'Порт 1', station_id: 'station-a', station_code: 'S01', station_name: 'Северная', connector_no: '1', connector_type: 'CCS2' },
  { id: 'station-a:2', label: 'Порт 2', station_id: 'station-a', station_code: 'S01', station_name: 'Северная', connector_no: '2', connector_type: 'CCS2' },
  { id: 'station-b:1', label: 'Порт 1', station_id: 'station-b', station_code: 'S02', station_name: 'Южная', connector_no: '1', connector_type: 'CHAdeMO' },
  ...Array.from({ length: 46 }, (_, i) => ({ id: `station-${i + 3}:1`, label: 'Порт 1', station_id: `station-${i + 3}`, station_code: `S${String(i + 3).padStart(2, '0')}`, station_name: `Станция с длинным названием ${i + 3}`, connector_no: '1', connector_type: 'CCS2' })),
]
let requestCount = 0
try {
  for (const [name, profile] of profiles) {
    const page = await browser.newPage(profile)
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => { if (message.type() === 'error' && !message.text().includes('status of 503')) errors.push(message.text()) })
    let latest
    let mode = 'ok'
    await page.route('**/api/analytics/charge-sessions/hourly-occupancy?**', async route => {
      requestCount++
      latest = new URL(route.request().url()).searchParams
      if (mode === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Тестовая недоступность сервиса' }) })
      const scope = ports.filter(p => latest.get('stations').split(',').includes(p.station_code))
      const ids = JSON.parse(latest.get('connector_ids') || '[]')
      const types = latest.get('connector_types')?.split(',') || []
      const filtered = scope.filter(p => (!ids.length || ids.includes(p.id)) && (!types.length || types.includes(p.connector_type)))
      const group = latest.get('group_by') === 'auto' ? (latest.get('stations') === 'S01' ? 'connector' : 'station') : latest.get('group_by')
      const selected = group === 'connector' ? filtered : [...new Map(filtered.map(p => [p.station_id, { ...p, id: p.station_id, connector_no: null, connector_type: null }])).values()]
      const response = {
        group_by: group, tz: latest.get('tz'), period: { from: '2026-10-01', to: '2026-10-02' }, hours: Array.from({ length: 24 }, (_, h) => h),
        connectors: scope, connector_types: ['CCS2', 'CHAdeMO', 'Type 2'],
        series: selected.map((p, i) => ({ ...p, points: Array.from({ length: 24 }, (_, hour) => {
          const occupied = hour === 0 ? 30 : hour === 1 ? 60 : hour === 12 ? 60 - (i % 3) * 12 : 0
          return { hour, occupied_minutes: occupied, available_minutes: 120, occupancy_pct: 100 * occupied / 120, starts: hour === 1 ? 1 : hour === 12 ? 7 - (i % 3) : 0, ...(mode === 'unknown' && i === 0 && hour === 0 ? { occupancy_complete: false, starts_complete: false } : {}) }
        }) })),
        quality: { missing_interval_sessions: 2, missing_connector_sessions: 1, unmapped_station_sessions: 1, last_session_at: '2026-10-02T23:10:00+03:00' },
      }
      if (mode === 'malformed' && response.series[0]) response.series[0].points.pop()
      if (mode === 'empty') response.series = []
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) })
    })
    const choose = async (field, option) => {
      await page.getByRole('combobox', { name: field, exact: true }).click()
      await page.getByRole('option', { name: option, exact: true }).click()
      await expect(page.getByRole('combobox', { name: field, exact: true })).toHaveText(option)
    }
    const ready = async () => { await page.getByRole('heading', { name: /по часам/ }).waitFor(); await expect(page.locator('section')).toHaveAttribute('data-export-state', 'ready') }
    await page.goto('http://127.0.0.1:4318/hourly-check')
    await ready()
    assert.match(await page.title(), /Почасовая/)
    assert.equal(latest.get('group_by'), 'auto')
    assert.equal(latest.get('regions'), 'region-test')
    assert.equal(latest.get('dim_val'), 'ФЛ')
    assert.equal(latest.get('date_to'), '2026-10-02')
    await page.getByText('Есть ограничения качества данных', { exact: true }).waitFor()
    await choose('Разрез', 'Коннекторы')
    await ready()
    const legend = page.getByRole('list', { name: 'Легенда графика' })
    assert.equal(await legend.getByRole('listitem').count(), 3)
    assert.match(await legend.innerText(), /порт 1 · CCS2/)
    assert.match(await legend.innerText(), /порт 2 · CCS2/)
    await page.getByText('Детализация за интервал', { exact: true }).click()
    await choose('Начало интервала', '12:00')
    await choose('Конец интервала', '13:00')
    const table = page.getByRole('table')
    assert.match(await table.innerText(), /50/)
    assert.match(await table.innerText(), /120/)
    await choose('Начало интервала', '00:00')
    await choose('Конец интервала', '06:00')
    await expect(table.locator('tbody tr').first().locator('td')).toHaveText(['12,5', '90', '720', '1'])
    await page.getByRole('button', { name: 'Экспорт', exact: true }).click()
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: /Excel/ }).click()
    const download = await downloadPromise
    const exportPath = `${artifactDir}/${name}.xlsx`
    await download.saveAs(exportPath)
    const book = XLSX.read(readFileSync(exportPath), { type: 'buffer' })
    const detail = XLSX.utils.sheet_to_json(book.Sheets['Детализация интервала'], { header: 1, defval: null })
    assert.deepEqual(detail[1], ['S01 · Северная · порт 1 · CCS2', 12.5, 90, 720, 1])
    assert.equal(detail[0].length, detail[1].length, 'значения стоят под своими заголовками')
    assert.deepEqual(XLSX.utils.sheet_to_json(book.Sheets['Заголовок строки'], { header: 1 })[1], ['Контрольная станция', '90'], 'fallback сохраняет th вместе с td')
    const params = XLSX.utils.sheet_to_json(book.Sheets['Параметры'], { header: 1 }).flat().join(' ')
    for (const text of ['2026-10-01', '2026-10-02', '00:00–06:00', 'ФЛ', 'region-test', 'Московское время']) assert.ok(params.includes(text), `в файле есть ${text}`)
    assert.equal(XLSX.utils.sheet_to_json(book.Sheets['Легенда']).length, 3)
    assert.equal(XLSX.utils.sheet_to_json(book.Sheets['Данные графика']).length, 72)
    assert.ok(book.SheetNames.includes('Графики'))
    if (name === 'mobile') {
      const targets = await page.locator('section button:visible, section summary:visible').evaluateAll(nodes => nodes.map(node => ({ label: node.getAttribute('aria-label') || node.textContent, height: node.getBoundingClientRect().height })))
      assert.deepEqual(targets.filter(target => target.height < 44), [], 'мобильные цели минимум 44px')
    }
    await page.screenshot({ path: `${artifactDir}/${name}.png`, fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'нет горизонтального скролла страницы')
    await page.getByRole('button', { name: 'Физические порты: все', exact: true }).click()
    await page.getByRole('textbox', { name: 'Поиск: физические порты' }).fill('порт 1')
    assert.equal(await page.getByRole('checkbox').count(), 2)
    await page.getByRole('checkbox').nth(0).check()
    await page.getByRole('checkbox').nth(1).check()
    await page.getByRole('button', { name: 'Применить', exact: true }).click()
    await ready()
    assert.deepEqual(JSON.parse(latest.get('connector_ids')), ['station-a:1', 'station-b:1'])
    await choose('Разрез', 'Станции')
    await ready()
    assert.deepEqual(JSON.parse(latest.get('connector_ids')), ['station-a:1', 'station-b:1'])
    await page.getByRole('button', { name: 'Типы коннекторов: все', exact: true }).click()
    await page.getByRole('textbox', { name: 'Поиск: типы коннекторов' }).fill('CCS')
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Применить', exact: true }).click()
    await ready()
    assert.equal(latest.get('connector_types'), 'CCS2')
    assert.equal(await legend.getByRole('listitem').count(), 1)
    const beforeMetric = requestCount
    await choose('Показатель', 'Начатые сессии, шт.')
    await ready()
    assert.equal(requestCount, beforeMetric, 'оба показателя из одного отфильтрованного ответа')
    assert.match(await page.getByRole('heading', { name: /по часам/ }).innerText(), /Начатые сессии/)
    await page.getByRole('button', { name: 'Местное', exact: true }).click()
    await ready()
    assert.equal(latest.get('tz'), 'local')
    assert.equal(latest.get('connector_types'), 'CCS2')
    await page.getByRole('button', { name: 'Одна станция', exact: true }).click()
    await ready()
    assert.equal(latest.get('connector_ids'), null)
    assert.equal(latest.get('group_by'), 'auto')
    assert.equal(await legend.getByRole('listitem').count(), 2)
    assert.match(await legend.innerText(), /порт 2/)
    await page.getByRole('button', { name: 'Другая компания', exact: true }).click()
    await ready()
    assert.equal(latest.get('company_id'), 'company-b')
    assert.equal(latest.get('connector_ids'), null)
    mode = 'unknown'
    await page.getByRole('button', { name: 'Много станций', exact: true }).click()
    await ready()
    assert.equal(await legend.getByRole('listitem').count(), 48)
    await page.getByText('Детализация за интервал', { exact: true }).click()
    await choose('Конец интервала', '06:00')
    await expect(page.getByRole('table').locator('tbody tr').first().locator('td')).toHaveText(['Неизвестно', 'Неизвестно', '720', 'Неизвестно'])
    const chart = page.locator('[data-chart]')
    await chart.scrollIntoViewIfNeeded()
    const bounds = await chart.boundingBox()
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 80)
    const tooltip = page.getByRole('region', { name: 'Станции в подсказке' })
    await tooltip.waitFor({ state: 'visible' })
    await tooltip.hover()
    if (engine === 'webkit' && profile.isMobile) {
      // Playwright не поддерживает wheel в mobile WebKit; проверяем нативную
      // клавиатурную прокрутку. Жест пальцем на физическом iPhone — NOT RUN.
      await tooltip.focus()
      await page.keyboard.press('PageDown')
    } else await page.mouse.wheel(0, 3000)
    await page.waitForFunction(() => document.querySelector('[aria-label="Станции в подсказке"]')?.scrollTop > 100)
    assert.equal(await tooltip.isVisible(), true, 'подсказка остаётся открытой при прокрутке')
    await tooltip.focus()
    if (engine === 'webkit' && profile.isMobile) {
      for (let step = 0; step < 30; step++) {
        const state = await tooltip.evaluate(t => ({ top: t.scrollTop, end: t.scrollTop + t.clientHeight >= t.scrollHeight - 3 }))
        if (state.end) break
        await page.keyboard.press('PageDown')
        await page.waitForFunction(top => document.querySelector('[aria-label="Станции в подсказке"]')?.scrollTop > top, state.top)
      }
    } else await page.keyboard.press('Control+End')
    await page.waitForFunction(() => { const t = document.querySelector('[aria-label="Станции в подсказке"]'); return t && t.scrollTop + t.clientHeight >= t.scrollHeight - 3 })
    await expect(tooltip.getByText('S48 · Станция с длинным названием 48', { exact: true })).toBeInViewport()
    await page.screenshot({ path: `${artifactDir}/${name}-tooltip.png` })
    await expect(tooltip.getByText('S48 · Станция с длинным названием 48', { exact: true })).toBeInViewport()
    await page.mouse.move(0, 0)
    await page.getByRole('button', { name: 'Экспорт', exact: true }).click()
    const manyDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: /Excel/ }).click()
    const manyPath = `${artifactDir}/${name}-many.xlsx`
    await (await manyDownload).saveAs(manyPath)
    const manyBook = XLSX.read(readFileSync(manyPath), { type: 'buffer' })
    const manyRows = XLSX.utils.sheet_to_json(manyBook.Sheets['Детализация интервала'], { header: 1, defval: null })
    assert.deepEqual(manyRows[1].slice(1), [null, null, 720, null], 'неизвестное не выгружается нулём')
    assert.equal(manyRows.length, 49)
    assert.match(manyRows[48][0], /48/)
    assert.equal(XLSX.utils.sheet_to_json(manyBook.Sheets['Легенда']).length, 48)
    assert.equal(XLSX.utils.sheet_to_json(manyBook.Sheets['Данные графика']).length, 48 * 24)
    mode = 'error'
    await choose('Разрез', 'Станции')
    await page.getByRole('alert').waitFor()
    assert.match(await page.getByRole('alert').innerText(), /Тестовая недоступность/)
    mode = 'ok'
    await page.getByRole('button', { name: 'Повторить запрос' }).click()
    await ready()
    mode = 'malformed'
    await page.getByRole('button', { name: 'МСК', exact: true }).click()
    await page.getByRole('alert').waitFor()
    assert.match(await page.getByRole('alert').innerText(), /неполные или некорректные/)
    mode = 'empty'
    await page.getByRole('button', { name: 'Повторить запрос' }).click()
    await page.getByText(/Нет почасовых данных для выбранного периода/).waitFor()
    assert.deepEqual(errors, [], 'нет ошибок React/браузера')
    await page.close()
    process.stdout.write(`${name}: график, детализация, фильтры, МСК/местное, сброс контура, ошибки и retry — OK\n`)
  }
  process.stdout.write(`Артефакты: ${artifactDir}\n`)
} finally {
  await browser.close()
  await server.close()
}
