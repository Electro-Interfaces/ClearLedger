/** Изолированная проверка на вымышленных данных, без production API.
 * Browser plugin not available — Playwright + системный Chromium.
 * Запуск: node e2e/megafon-voice.check.mjs
 */
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer, transformWithEsbuild } from 'vite'
import { chromium } from '@playwright/test'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const artifacts = await mkdtemp(join(tmpdir(), 'megafon-ui-qa-'))
const virtual = '\0megafon-qa.tsx'
const entry = `
import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FixtureCompanyProvider } from '@/contexts/CompanyContext';
import { VoiceLayout } from '@/pages/voice/VoiceLayout';
import MegafonVoicePage from '@/pages/voice/PbxVoicePage';
import VoiceConnectionsPage from '@/pages/voice/VoiceConnectionsPage';
import * as helpers from '@/services/megafonVoiceService';
import * as monthlyHelpers from '@/pages/voice/megafonMonthly';
import '@/index.css';
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
document.title = 'Телефония · МегаФон ВАТС · синтетическая проверка';
window.megafonMonthlyHelpers = monthlyHelpers; window.megafonHelpers = helpers; window.megafonQueryClient = client;
createRoot(document.getElementById('root')).render(<QueryClientProvider client={client}><FixtureCompanyProvider>
<p role="note">СИНТЕТИЧЕСКАЯ ПРОВЕРКА: вымышленные звонки</p>
<div style={{height: 'calc(100dvh - 3rem)', display: 'flex', flexDirection: 'column'}}>
<BrowserRouter><Routes><Route path="/voice" element={<VoiceLayout />}><Route index element={<p>Раздел узла</p>} /><Route path="calls" element={<p>Журнал узла в проверке</p>} /><Route path="stats" element={<p>Статистика узла в проверке</p>} /><Route path="report" element={<p>Отчёт узла в проверке</p>} /><Route path="connections" element={<VoiceConnectionsPage />} /><Route path="pbx" element={<MegafonVoicePage />} /><Route path="megafon" element={<MegafonVoicePage />} /></Route></Routes></BrowserRouter>
</div>
</FixtureCompanyProvider></QueryClientProvider>);
`
const companyFixture = `
import React, { createContext, useContext, useState } from 'react';
import { setApiCompany } from '@/services/apiClient';
const Context = createContext(null);
export const useCompany = () => useContext(Context);
export function FixtureCompanyProvider({ children }) {
  const [companyId, setId] = useState('qa-company-a'); setApiCompany(companyId);
  return <Context.Provider value={{companyId}}><button onClick={() => {setApiCompany('qa-company-b'); setId('qa-company-b')}}>Сменить компанию в проверке</button>{children}</Context.Provider>;
}`
let server, browser, page, nodeRequests = 0, mode = 'normal'
const errors = [], requests = [], screenshots = []
let megafonNodeRequests = 0
let liveRows = []
const sipFixture = {revision:0,primary:null,items:[],legacy:{endpoint:'PJSIP/carrier',primary:true,readonly:true},operators:
['mango','megafon','beeline','mts','other'].map((id,i)=>({id,name:['Mango Office','МегаФон','Билайн','МТС / Exolve','Другой SIP-оператор'][i],help:'Данные из кабинета оператора',docs:null,historyApi:i<2?'support':'unavailable'}))}
let sipRejected=false

const calls = Array.from({ length: 32 }, (_, index) => ({
  id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  call_id: `synthetic-${index + 1}`, direction: index % 2 ? 'outbound' : 'inbound', missed: index % 3 === 0,
  client_phone: `+7000000${String(index + 1).padStart(4, '0')}`,
  operator_name: index % 5 === 0 ? null : 'Оператор проверки', operator_login: index % 5 === 0 ? null : 'qa-agent',
  operator_user_id: index % 5 === 0 ? null : 'qa-user', group_name: index % 4 === 0 ? null : 'Тестовая группа',
  line_number: '+70000000999', line_name: 'Тестовая линия', started_at: new Date(Date.now() - index * 60000).toISOString(),
  wait_sec: index === 0 ? null : index, duration_sec: index % 3 === 0 ? 0 : index * 10,
  has_recording: index % 3 !== 0, source: 'megafon_history', thread_id: null,
}))
function fixture(query, companyId) {
  const filtered = mode === 'empty' ? [] : calls.filter(call =>
    (!query.has('operator') || (call.operator_name ?? '') === query.get('operator')) &&
    (!query.has('group') || (call.group_name ?? '') === query.get('group')) &&
    (!query.has('line') || call.line_number === query.get('line')) &&
    (!query.has('direction') || call.direction === query.get('direction')) &&
    (!query.has('missed') || String(call.missed) === query.get('missed')) &&
    (!query.has('search') || call.client_phone.replace(/\D/g, '').includes(query.get('search'))))
  const page = Number(query.get('page'))
  return {
    provider: query.get('source') ?? 'megafon', company_id: mode === 'wrong-company' ? 'other-company' : companyId,
    period: { from: query.get('from'), to: query.get('to') },
    connection: { configured: mode !== 'unconfigured', status: mode === 'unconfigured' ? 'unconfigured' : 'ok', last_sync_at: mode === 'unconfigured' ? null : new Date().toISOString(), last_error: null, mode: 'history', poll_interval_seconds: 300 },
    line: { name: 'Тестовая линия', public_number: '+78000000000', forwarding_number: '+70000000999', origin_verified_per_call: false },
    summary: { total: filtered.length, inbound: filtered.filter(c => c.direction === 'inbound').length, outbound: filtered.filter(c => c.direction === 'outbound').length,
      answered: filtered.filter(c => !c.missed).length, missed: filtered.filter(c => c.missed).length, avg_wait_sec: filtered.length ? 10 : null,
      avg_talk_sec: filtered.length ? 40 : null, recordings: filtered.filter(c => c.has_recording).length, operator_count: filtered.length ? 2 : 0 },
    operators: filtered.length ? [{ key: 'qa-user', name: mode === 'formula' ? '=1+1' : 'Оператор проверки', login: 'qa-agent', extension: '101', user_id: 'qa-user', total: filtered.length, inbound_answered: 5, outbound: 4, missed: 3, avg_talk_sec: 40, avg_wait_sec: 10 }] : [],
    groups: filtered.length ? [{ name: 'Тестовая группа', total: filtered.length, answered: 4, missed: 2 }, { name: '', total: 2, answered: 1, missed: 1 }] : [],
    filters: { operators: [{ key: 'qa-user', name: 'Оператор проверки' }, { key: '', name: 'Без оператора' }], groups: [{ key: 'qa-group', name: 'Тестовая группа' }, { key: '', name: 'Группа не указана' }], lines: [{ key: 'qa-line', name: 'Тестовая линия', number: '+70000000999' }] },
    calls: { items: filtered.slice((page - 1) * 25, page * 25), total: filtered.length, page, page_size: 25 },
  }
}
try {
  server = await createServer({ root: appDir, cacheDir: join(artifacts, 'vite-cache'), server: { host: '127.0.0.1', port: 0, open: false }, plugins: [{
    name: 'megafon-qa-fixture',
    resolveId(id) { if (id === 'virtual:megafon-qa') return virtual },
    async load(id) {
      if (id === virtual) return (await transformWithEsbuild(entry, 'megafon-qa.tsx', { loader: 'tsx', jsx: 'automatic' })).code
      if (id.endsWith('/src/contexts/CompanyContext.tsx')) return companyFixture
    },
    transformIndexHtml(html) { return html.replace('/src/main.tsx', '/@id/__x00__megafon-qa.tsx') },
  }] })
  await server.listen()
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium' })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'ru-RU', timezoneId: 'Europe/Moscow' })
  await context.route('**/api/voice/pbx**', async route => {
    const request = route.request(), url = new URL(request.url()), companyId = request.headers()['x-company-id']
    requests.push({ companyId, path: url.pathname, query: url.search })
    assert.ok(companyId, 'Каждый Core-запрос несёт X-Company-Id')
    if (url.pathname.endsWith('/sources')) {
      if (mode === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Синтетическая ошибка источника' }) })
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ company_id: companyId, default_source: mode === 'unconfigured' ? 'node' : 'megafon', sources: ['node','mango','megafon'].map(source => ({ source, provider: source === 'node' ? 'asterisk' : source, connector_id: source, enabled: mode !== 'unconfigured', status: mode === 'unconfigured' ? 'not_configured' : 'active', has_error: false, last_sync_at: new Date().toISOString() })) }) })
    }
    if (mode === 'slow') await new Promise(resolve => setTimeout(resolve, 700))
    if (mode === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Синтетическая ошибка источника' }) })
    if (url.pathname.includes('/calls/')) {
      const call = calls.find(call => call.id === url.pathname.split('/').at(-1))
      return route.fulfill({ status: call ? 200 : 404, contentType: 'application/json', body: JSON.stringify(call ? { call, provider: 'megafon', company_id: companyId } : { detail: 'Звонок не найден' }) })
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(fixture(url.searchParams, companyId)) })
  })
  await context.route('**/api/voice/connections', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ company_id: route.request().headers()['x-company-id'], connections: [] }) }))
  for (const pattern of ['**/voice/api/v1/**', '**/api/sso/token**']) {
    await context.route(pattern, route => {
      nodeRequests++
      if(mode==='sip-operators') {
        const request=route.request(),path=new URL(request.url()).pathname
        if(path==='/api/sso/token') return route.fulfill({json:{token:'synthetic-voice-token',expires_in:300}})
        if(path.endsWith('/me')) return route.fulfill({json:{companyId:'qa-company-a',sub:'qa-user',role:'admin',permissions:[]}})
        if(path.includes('/sip/operators')) {
          if(request.method()==='POST') {
            const b=request.postDataJSON(); if (b.revision!==sipFixture.revision) return route.fulfill({status:409,json:{error:'sip_revision_conflict',detail:'Подключения изменились. Обновите список.'}})
            if(path.endsWith('/apply')&&sipRejected) return route.fulfill({status:409,json:{error:'sip_calls_active',detail:'Дождитесь завершения звонков перед изменением линии.'}})
            if(path.endsWith('/primary')) {sipFixture.primary=path.split('/').at(-2);sipFixture.legacy.primary=false}
            else if(path.endsWith('/apply')) {sipFixture.items[0].applied={...sipFixture.items[0].draft};sipFixture.items[0].changed=false;sipFixture.items[0].status='registered'}
            else {assert.equal(b.config.password,'SyntheticPassword!');const {password,...config}=b.config;sipFixture.items=[{id:'fixture-sip',endpoint:'ch_fixture',draft:{...config,passwordConfigured:true},applied:null,changed:true,status:'draft'}]}
            sipFixture.revision++
          }
          return route.fulfill({json:sipFixture})
        }
        return route.fulfill({status:503,body:'Fixture: unrelated Node service unavailable'})
      }
      if (mode === 'live-node') {
        const path = new URL(route.request().url()).pathname
        const body = path === '/api/sso/token' ? { token: 'synthetic-voice-token', expires_in: 300 }
          : path.endsWith('/calls') ? { items: liveRows, next: null }
          : path.endsWith('/stats/operators') ? [] : { companyId: 'qa-company-a', sub: 'qa-user', role: 'admin', permissions: [] }
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
      }
      return route.fulfill({ status: 503, body: 'Node недоступен' })
    })
  }
  page = await context.newPage()
  page.setDefaultTimeout(30000)
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (['warning', 'error'].includes(message.type()) && !/503 \(Service Unavailable\)|404 \(Not Found\)/.test(message.text())) errors.push(message.text()) })
  const checkRequest = async action => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/voice/pbx')
    await action(); await response
    await page.getByRole('button', { name: 'Обновить', exact: true }).waitFor()
    return new URL(requests.filter(r => r.path === '/api/voice/pbx').at(-1).query, origin).searchParams
  }
  async function screenshot(name) {
    assert.equal(await page.locator('vite-error-overlay').count(), 0)
    assert.ok((await page.locator('body').innerText()).length > 100)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'Нет переполнения страницы')
    await page.screenshot({ path: join(artifacts, name), fullPage: false, animations: 'disabled' }); screenshots.push(name)
  }
  if (!process.env.SIP_ONLY) {
  await page.goto(`${origin}/voice/megafon`)
  await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/voice/megafon'); assert.match(await page.title(), /^Телефония · МегаФон ВАТС/)
  assert.equal(nodeRequests, 0, 'МегаФон не требует Node /me или SSO-токен')
  assert.equal(await page.locator('tbody tr').count(), 25)
  await screenshot('desktop.png')
  const bounds = await page.evaluate(() => ['today', '7d', '30d'].map(period => window.megafonHelpers.megafonPeriodBounds(period, new Date('2026-10-19T12:00:00+03:00'))))
  for (const [index, days] of [1, 7, 30].entries()) assert.equal(Date.parse(bounds[index].to) - Date.parse(bounds[index].from), days * 86400000)
  let query = await checkRequest(() => page.getByRole('button', { name: 'Далее', exact: true }).click())
  assert.equal(query.get('page'), '2'); assert.equal(query.get('page_size'), '25')
  assert.equal(await page.locator('tbody tr').count(), 7)
  const listUrl = page.url()
  await page.getByRole('button', { name: /^Открыть звонок/ }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Карточка звонка' })
  await dialog.getByText('synthetic-26', { exact: true }).waitFor()
  assert.ok(new URL(page.url()).searchParams.has('call'))
  assert.equal(await dialog.locator('audio').count(), 0); assert.equal(await dialog.getByRole('button').count(), 1)
  await screenshot('call-card.png'); await page.reload()
  await dialog.getByText('synthetic-26', { exact: true }).waitFor()
  await dialog.getByRole('button', { name: 'К журналу' }).click(); assert.equal(page.url(), listUrl)
  for (const [label, value, key] of [['Оператор', 'Оператор проверки', 'operator'], ['Оператор', '', 'operator'], ['Группа', '', 'group']]) {
    query = await checkRequest(() => page.getByLabel(label, { exact: true }).selectOption(value))
    assert.ok(query.has(key)); assert.equal(query.get(key), value); assert.equal(query.get('page'), '1')
  }
  await checkRequest(() => page.getByRole('button', { name: 'Сбросить фильтры' }).click())
  assert.equal(new URL(page.url()).searchParams.has('operator'), false)
  assert.equal(new URL(page.url()).searchParams.has('group'), false)
  for (const [label, value, key] of [['Группа', 'Тестовая группа', 'group'], ['Линия', '+70000000999', 'line'], ['Направление', 'inbound', 'direction'], ['Пропуск', 'false', 'missed'], ['Пропуск', 'true', 'missed']]) {
    query = await checkRequest(() => page.getByLabel(label, { exact: true }).selectOption(value)); assert.equal(query.get(key), value)
  }
  await checkRequest(() => page.getByRole('button', { name: 'Сбросить фильтры' }).click())
  const beforeSearch = requests.length
  await page.getByRole('textbox', { name: 'Поиск по номеру' }).fill('123')
  assert.equal(await page.getByRole('button', { name: 'Найти', exact: true }).isDisabled(), true); assert.equal(requests.length, beforeSearch)
  await page.getByRole('textbox', { name: 'Поиск по номеру' }).fill('00-26')
  query = await checkRequest(() => page.getByRole('button', { name: 'Найти', exact: true }).click())
  assert.equal(query.get('search'), '0026'); assert.equal(await page.locator('tbody tr').count(), 1)
  await checkRequest(() => page.getByRole('button', { name: 'Снять поиск' }).click())
  for (const period of ['7d', '30d', 'today']) {
    query = await checkRequest(() => page.getByLabel('Период', { exact: true }).selectOption(period))
    assert.ok(query.get('from').endsWith('Z')); assert.ok(query.get('to').endsWith('Z')); assert.ok(Date.parse(query.get('from')) < Date.parse(query.get('to')))
  }
  await page.getByRole('tab', { name: 'Операторы', exact: true }).click()
  await page.getByRole('table', { name: 'Операторы АТС' }).getByText('101', { exact: true }).waitFor()
  await page.getByRole('tab', { name: 'Группы', exact: true }).click()
  await page.getByRole('table', { name: 'Группы АТС' }).getByText('Группа не указана', { exact: true }).waitFor()
  await page.getByRole('tab', { name: 'Журнал звонков', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 }); await page.getByLabel('Раздел Телефонии').waitFor()
  await page.getByRole('heading', { name: 'АТС', exact: true }).scrollIntoViewIfNeeded()
  await screenshot('mobile.png')
  await page.getByRole('button', { name: /^Открыть звонок/ }).first().click(); await dialog.getByText('synthetic-1', { exact: true }).waitFor()
  assert.match(await dialog.innerText(), /Ожидание\s+—/); await screenshot('mobile-card.png')
  const closeBounds = await dialog.getByRole('button', { name: 'К журналу' }).boundingBox()
  assert.ok(closeBounds.y >= 0 && closeBounds.y + closeBounds.height <= 844, 'Закрытие карточки доступно без прокрутки')
  await dialog.getByRole('button', { name: 'К журналу' }).click()
  mode = 'empty'; await checkRequest(() => page.getByRole('button', { name: 'Обновить', exact: true }).click())
  await page.getByText('Звонков по выбранным условиям нет', { exact: true }).waitFor(); await screenshot('empty.png')
  mode = 'unconfigured'; await checkRequest(() => page.getByRole('button', { name: 'Обновить', exact: true }).click())
  await page.getByText('Источник МегаФон для этой компании ещё не подключён. Настройте его в разделе подключений.').waitFor()
  mode = 'error'; await checkRequest(() => page.getByRole('button', { name: 'Обновить', exact: true }).click())
  await page.getByText('Синтетическая ошибка источника', { exact: true }).waitFor(); await screenshot('error.png')
  mode = 'wrong-company'; await checkRequest(() => page.getByRole('button', { name: 'Повторить', exact: true }).click())
  await page.getByText('Ответ относится к другой компании. Обновите страницу.').waitFor()
  mode = 'slow'; await page.goto(`${origin}/voice/megafon?direction=outbound&call=${calls[0].id}`)
  await page.getByText('Загружаем звонки АТС…', { exact: true }).waitFor(); await dialog.getByText('synthetic-1', { exact: true }).waitFor()
  await dialog.getByRole('button', { name: 'К журналу' }).click(); mode = 'normal'
  await checkRequest(() => page.getByRole('button', { name: 'Сменить компанию в проверке' }).click())
  assert.equal(requests.at(-1).companyId, 'qa-company-b'); assert.equal(new URL(page.url()).searchParams.has('direction'), false)
  assert.equal(new URL(page.url()).searchParams.has('call'), false)
  const keys = await page.evaluate(() => window.megafonQueryClient.getQueryCache().getAll().map(q => q.queryKey))
  assert.ok(keys.some(key => key[0] === 'voice-pbx' && key[1] === 'qa-company-b'))
  assert.ok(keys.filter(key => key[0] === 'voice-pbx').every(key => ['from', 'to', 'page', 'page_size'].every(field => Object.hasOwn(key[3], field))))
  assert.equal(nodeRequests, 0); assert.deepEqual(errors, [])
  mode = 'normal'
  await page.goto(`${origin}/voice/megafon?search=12`)
  await page.getByText('В ссылке слишком короткий номер. Введите хотя бы 4 цифры или снимите поиск.').waitFor()
  await page.getByRole('button', { name: 'Снять поиск' }).click()
  await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor()
  await page.goto(`${origin}/voice/megafon?call=00000000-0000-4000-8000-999999999999`)
  await dialog.getByText('Звонок не найден', { exact: true }).waitFor()
  await dialog.getByRole('button', { name: 'К журналу' }).click()
  megafonNodeRequests = nodeRequests
  assert.equal(megafonNodeRequests, 0)
  // Привычные разделы используют подключённую ВАТС, даже если Node недоступен.
  await page.goto(`${origin}/voice/calls`)
  await page.getByRole('heading', { name: 'Журнал звонков', exact: true }).waitFor()
  await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor()
  assert.equal(await page.getByLabel('Источник данных', { exact: true }).inputValue(), 'megafon')
  assert.equal(new URL(page.url()).searchParams.get('source'), 'megafon')
  assert.equal(nodeRequests, 0)
  await page.goto(`${origin}/voice/stats`)
  await page.getByRole('heading', { name: 'Статистика', exact: true }).waitFor()
  await page.getByRole('table', { name: 'Операторы АТС' }).waitFor()
  await page.reload()
  await page.getByRole('table', { name: 'Операторы АТС' }).waitFor()
  assert.equal(nodeRequests, 0)
  await page.getByLabel('Источник данных', { exact: true }).selectOption('node')
  await page.getByText('Узел заказчика не отвечает', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).searchParams.get('source'), 'node')
  await page.getByLabel('Источник данных', { exact: true }).selectOption('megafon')
  await page.getByRole('table', { name: 'Операторы АТС' }).waitFor()
  await page.goto(`${origin}/voice/calls?metric=arrived&id=node-call&line=line-main`)
  await page.getByText('Узел заказчика не отвечает', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).searchParams.get('id'), 'node-call')
  assert.equal(await page.getByLabel('Источник данных', { exact: true }).inputValue(), 'node')
  // Отсутствие коннектора сохраняет прежний Node guard; ошибка источника не выдаётся за ноль.
  mode = 'unconfigured'
  await page.goto(`${origin}/voice/calls`)
  await page.getByText('Узел заказчика не отвечает', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('Источник данных', { exact: true }).inputValue(), 'node')
  mode = 'error'
  await page.goto(`${origin}/voice/calls`)
  await page.getByRole('alert').filter({ hasText: 'Не удалось определить источник' }).waitFor()
  assert.equal(await page.getByRole('table').count(), 0)
  mode = 'normal'
  const beforeMonthlyNode = nodeRequests
  await page.goto(`${origin}/voice/report`)
  await page.getByRole('heading', { name: 'Отчёт за месяц', exact: true }).waitFor()
  await page.getByRole('table', { name: 'Операторы за месяц' }).waitFor()
  assert.equal(await page.getByLabel('Источник данных', { exact: true }).inputValue(), 'megafon')
  const m = await page.evaluate(() => ({ leap: window.megafonMonthlyHelpers.monthlyBounds('2024-02'), bad: window.megafonMonthlyHelpers.monthlyBounds('2026-13'), future: window.megafonMonthlyHelpers.monthlyBounds('2099-01'), previous: window.megafonMonthlyHelpers.shiftMonth('2026-01', -1) }))
  assert.equal(Date.parse(m.leap.to) - Date.parse(m.leap.from), 29 * 86400000); assert.equal(m.bad, null); assert.equal(m.future, null); assert.equal(m.previous, '2025-12')
  const monthResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/api/voice/pbx' && new URL(r.url()).searchParams.get('from') === '2026-08-31T21:00:00.000Z')
  await page.getByLabel('Месяц', { exact: true }).fill('2026-09'); await monthResponse
  await page.getByRole('button', { name: 'Excel', exact: true }).waitFor()
  await page.getByLabel('Линия отчёта').selectOption('+70000000999')
  await page.getByRole('button', { name: 'Excel', exact: true }).waitFor({ state: 'visible' })
  await page.reload(); await page.getByRole('table', { name: 'Операторы за месяц' }).waitFor()
  assert.equal(await page.getByLabel('Месяц', { exact: true }).inputValue(), '2026-09')
  assert.equal(await page.getByLabel('Линия отчёта').inputValue(), '+70000000999')
  const csvEvent = page.waitForEvent('download'); await page.getByRole('button', { name: 'CSV', exact: true }).click(); const csv = await csvEvent
  await csv.saveAs(join(artifacts, 'monthly.csv')); const csvText = await readFile(join(artifacts, 'monthly.csv'), 'utf8')
  assert.ok(csvText.includes('Сводка') && csvText.includes('2026-09') && csvText.includes('Операторы')); assert.ok(!csvText.includes(calls[0].client_phone)); assert.ok(!csvText.includes('recording_url'))
  const xlsxEvent = page.waitForEvent('download'); await page.getByRole('button', { name: 'Excel', exact: true }).click(); const xlsx = await xlsxEvent
  await xlsx.saveAs(join(artifacts, 'monthly.xlsx')); assert.equal((await readFile(join(artifacts, 'monthly.xlsx'))).subarray(0, 2).toString(), 'PK')
  const popupEvent = context.waitForEvent('page'); await page.getByRole('button', { name: 'Печать / PDF', exact: true }).click(); const popup = await popupEvent
  await popup.getByRole('heading', { name: /отчёт за/ }).waitFor(); assert.equal(await popup.locator('script,img,iframe').count(), 0); assert.ok(!(await popup.locator('body').innerText()).includes(calls[0].client_phone)); await popup.close()
  await page.getByRole('link', { name: 'Открыть звонки этого отчёта' }).click(); await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor(); assert.equal(new URL(page.url()).pathname, '/voice/calls')
  await page.goto(`${origin}/voice/report?month=2099-01`); await page.getByRole('alert').filter({ hasText: 'Выберите корректный месяц' }).waitFor(); assert.ok(await page.getByRole('button', { name: 'Excel', exact: true }).isDisabled())
  mode = 'empty'; await page.goto(`${origin}/voice/report?month=2026-09`); await page.getByText('В загруженной истории за выбранный месяц и линию звонков нет. Проверьте период и полноту загрузки.').waitFor()
  mode = 'error'; await page.getByRole('button', { name: 'Обновить', exact: true }).click(); await page.getByRole('alert').filter({ hasText: 'Не удалось рассчитать отчёт' }).waitFor(); assert.ok(await page.getByRole('button', { name: 'Excel', exact: true }).isDisabled())
  mode = 'formula'; await page.getByRole('button', { name: 'Повторить', exact: true }).click(); await page.getByRole('table', { name: 'Операторы за месяц' }).getByText('=1+1', { exact: true }).waitFor()
  const safeEvent = page.waitForEvent('download'); await page.getByRole('button', { name: 'CSV', exact: true }).click(); await (await safeEvent).saveAs(join(artifacts, 'monthly-formula.csv')); assert.ok((await readFile(join(artifacts, 'monthly-formula.csv'), 'utf8')).includes("'=1+1;101;"))
  await page.setViewportSize({ width: 390, height: 844 }); await screenshot('monthly-mobile.png')
  assert.equal(nodeRequests, beforeMonthlyNode, 'Месячный отчёт МегаФона не обращается к Node')
  mode = 'normal'
  await page.goto(`${origin}/voice`)
  await page.getByText('Узел заказчика не отвечает', { exact: true }).waitFor()
  assert.ok(nodeRequests > 0, 'На соседнем маршруте проверка узла сохранена')
  mode = 'live-node'
  liveRows = []
  await page.goto(`${origin}/voice/pbx?source=node`)
  await page.getByRole('heading', { name: 'АТС', exact: true }).waitFor()
  await page.getByText('За этот период звонков нет', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('Источник звонков', { exact: true }).inputValue(), 'node')
  liveRows.push({ contactId: 'live-synthetic-8561', lineId: 'L-qa', number: '***8561', startedAt: new Date().toISOString(), queuedAt: null, connectedAt: null, endedAt: null, outcome: null, flags: [] })
  const liveRow = page.getByRole('row').filter({ hasText: '8561' })
  await liveRow.getByText('Входящий', { exact: true }).waitFor({ timeout: 8000 })
  liveRows[0].queuedAt = new Date().toISOString()
  await liveRow.getByText('В очереди', { exact: true }).waitFor({ timeout: 8000 })
  liveRows[0].connectedAt = new Date().toISOString()
  await liveRow.getByText('Разговор', { exact: true }).waitFor({ timeout: 8000 })
  await screenshot('live-call-mobile.png')
  liveRows[0].endedAt = new Date().toISOString(); liveRows[0].outcome = 'connected'
  await liveRow.getByText('отвечен', { exact: true }).waitFor({ timeout: 8000 })
  assert.equal(await liveRow.count(), 1, 'Переход к завершённому звонку не создаёт дубликат')
  mode = 'normal'
  await page.getByLabel('Источник звонков', { exact: true }).selectOption('mango')
  await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor()
  await page.getByLabel('Группа', { exact: true }).selectOption('Тестовая группа')
  await page.getByLabel('Источник звонков', { exact: true }).selectOption('megafon')
  await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor()
  assert.equal(new URL(page.url()).searchParams.get('group'), null)
  await page.getByLabel('Источник звонков', { exact: true }).selectOption('mango')
  await page.reload()
  await page.getByRole('table', { name: 'Журнал звонков АТС' }).waitFor()
  assert.equal(await page.getByLabel('Источник звонков', { exact: true }).inputValue(), 'mango')
  assert.ok(requests.some(r => r.path === '/api/voice/pbx' && new URLSearchParams(r.query).get('source') === 'mango'))
  await screenshot('pbx-mango-mobile.png')
  await page.goto(`${origin}/voice/connections`)
  await page.getByRole('heading', { name: 'Настройки подключений', exact: true }).waitFor()
  await page.getByLabel('Провайдер ВАТС', { exact: true }).selectOption('mango')
  await page.getByRole('button', { name: 'Настроить Mango', exact: true }).waitFor()
  assert.equal(await page.getByRole('link', { name: 'Открыть историю', exact: true }).getAttribute('href'), '/voice/pbx?source=mango')
  await page.getByLabel('Провайдер ВАТС', { exact: true }).selectOption('megafon')
  await page.getByRole('button', { name: 'Настроить МегаФон', exact: true }).waitFor()
  assert.equal(await page.getByRole('link', { name: 'Открыть историю', exact: true }).getAttribute('href'), '/voice/pbx?source=megafon')
  await page.screenshot({ path: join(artifacts, 'connections-mobile.png'), fullPage: false })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true)
  }
  mode='sip-operators'
  await page.setViewportSize({width:390,height:844})
  await page.goto(`${origin}/voice/connections`)
  const operators=page.getByRole('region',{name:'Операторы связи'})
  await operators.getByRole('button',{name:'Добавить оператора',exact:true}).click()
  const sipForm=page.getByRole('form',{name:'Настройка SIP-оператора'})
  const picker=sipForm.getByLabel('Оператор',{exact:true})
  await picker.waitFor()
  assert.equal(await picker.locator('option').count(),5)
  await picker.selectOption('beeline')
  await sipForm.getByText(/отдельный API-адаптер этого оператора пока не подключён/).waitFor()
  await sipForm.getByLabel('Название подключения',{exact:true}).fill('Билайн · тестовая линия')
  await sipForm.getByLabel('SIP-сервер',{exact:true}).fill('sip.example.net')
  await sipForm.getByLabel('SIP-логин',{exact:true}).fill('qa-account')
  await sipForm.getByLabel('SIP-пароль',{exact:true}).fill('SyntheticPassword!')
  await screenshot('sip-editor-mobile.png')
  await page.setViewportSize({width:1440,height:1000});await screenshot('sip-editor-desktop.png')
  await sipForm.getByRole('button',{name:'Сохранить черновик',exact:true}).click()
  await operators.getByText('Билайн · тестовая линия',{exact:true}).waitFor()
  assert.doesNotMatch(await page.locator('body').innerText(),/SyntheticPassword!/)
  sipRejected=true
  await operators.getByRole('button',{name:'Подключить',exact:true}).click()
  await page.getByRole('button',{name:'Подтвердить',exact:true}).click()
  await page.getByRole('alert').filter({hasText:'Дождитесь завершения звонков'}).waitFor()
  sipRejected=false
  await page.getByRole('button',{name:'Подтвердить',exact:true}).click()
  await operators.getByText('Зарегистрирован',{exact:true}).waitFor()
  await operators.getByRole('button',{name:'Для исходящих',exact:true}).click()
  await page.getByRole('button',{name:'Подтвердить',exact:true}).click()
  await operators.getByText('Линия для исходящих изменена.',{exact:true}).waitFor()
  await screenshot('sip-connected-desktop.png')
  await page.setViewportSize({width:390,height:844});await screenshot('sip-connected-mobile.png')
  await operators.getByRole('button',{name:'Изменить',exact:true}).click()
  await sipForm.getByLabel('Название подключения',{exact:true}).fill('Несохранённая правка')
  sipFixture.revision++
  await operators.getByRole('button',{name:'Проверить состояния',exact:true}).click()
  await sipForm.getByRole('button',{name:'Сохранить черновик',exact:true}).click()
  await page.getByRole('alert').filter({hasText:'Подключения изменились'}).waitFor()
  assert.equal(sipFixture.items[0].draft.name,'Билайн · тестовая линия','Фоновое обновление не позволяет затереть чужую версию старой формой')
  await sipForm.getByLabel('SIP-пароль',{exact:true}).fill('DiscardOnCompanyChange')
  await page.getByRole('button',{name:'Сменить компанию в проверке',exact:true}).click()
  await sipForm.waitFor({state:'detached'})
  assert.equal(await page.locator('input[type=password]').count(),0,'Смена компании убирает форму и введённый пароль')
  assert.match(await readFile(join(appDir, 'src/App.tsx'), 'utf8'), /path: 'megafon', element: <LazyPage><MegafonVoicePage/)
  await writeFile(join(artifacts, 'result.json'), JSON.stringify({ passed: true, origin, viewports: ['1440x1000', '390x844'], megafonNodeRequests, otherVoiceNodeRequests: nodeRequests, errors, requestCount: requests.length, screenshots }, null, 2))
  process.stdout.write(`PASS: параметры, периоды, фильтры, пагинация, карточка/reload, состояния, company isolation, Node bypass; артефакты: ${artifacts}\n`)
} catch (error) {
  if (page) {
    await page.screenshot({ path: join(artifacts, 'failure.png'), fullPage: true })
    await writeFile(join(artifacts, 'failure.txt'), JSON.stringify({ error: String(error), errors, requests, html: await page.locator('body').innerText() }, null, 2))
  }
  process.stderr.write(`FAIL: ${artifacts}\n`)
  throw error
} finally { await browser?.close(); await server?.close() }
