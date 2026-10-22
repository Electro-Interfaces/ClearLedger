/** Из clearledger: node e2e/hourly-occupancy.check.mjs
 * Browser plugin not available; используется локальный Playwright.
 * Проверяет только UI и параметры API на синтетических ответах, не backend-расчёт.
 */
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { createServer } from 'vite'
import { chromium } from '@playwright/test'

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
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium' })
const ports = [
  { id: 'station-a:1', label: 'Порт 1', station_id: 'station-a', station_code: 'S01', station_name: 'Северная', connector_no: '1', connector_type: 'CCS2' },
  { id: 'station-a:2', label: 'Порт 2', station_id: 'station-a', station_code: 'S01', station_name: 'Северная', connector_no: '2', connector_type: 'CCS2' },
  { id: 'station-b:1', label: 'Порт 1', station_id: 'station-b', station_code: 'S02', station_name: 'Южная', connector_no: '1', connector_type: 'CHAdeMO' },
]
let requestCount = 0
try {
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    const page = await browser.newPage({ viewport })
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
        series: selected.map((p, i) => ({ ...p, points: Array.from({ length: 24 }, (_, hour) => ({ hour, occupied_minutes: hour === 12 ? 60 - i * 12 : 0, available_minutes: 120, occupancy_pct: hour === 12 ? 50 - i * 10 : 0, starts: hour === 12 ? 7 - i : 0 })) })),
        quality: { missing_interval_sessions: 2, missing_connector_sessions: 1, unmapped_station_sessions: 1, last_session_at: '2026-10-02T23:10:00+03:00' },
      }
      if (mode === 'malformed' && response.series[0]) response.series[0].points.pop()
      if (mode === 'empty') response.series = []
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) })
    })
    const choose = async (field, option) => {
      await page.getByRole('combobox', { name: field, exact: true }).click()
      await page.getByRole('option', { name: option, exact: true }).click()
    }
    const ready = () => page.getByRole('heading', { name: /по часам/ }).waitFor()
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
    await page.getByText('Детализация по часам', { exact: true }).click()
    assert.match(await page.getByRole('table').innerText(), /50/)
    assert.match(await page.getByRole('table').innerText(), /120/)
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
