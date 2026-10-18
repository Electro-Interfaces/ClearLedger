/**
 * Сквозная проверка экранов против настоящего HTTP API ContactHub и PGlite.
 * CONTACT_HUB_DIR указывает на checkout с node/test/space-wave7.ts.
 * Подменяется только справочник сотрудников Ядра, не ответы API узла.
 * Ключи/БД/порты временные; Browser plugin not available — Playwright Chromium.
 */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { access, mkdtemp, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const hubDir = process.env.CONTACT_HUB_DIR
assert.ok(hubDir, 'Задайте CONTACT_HUB_DIR: checkout ContactHub с node/test/space-wave7.ts')
const artifacts = await mkdtemp(join(tmpdir(), 'voice-real-node-qa-'))
const children = []
const errors = []
const network = []
const screens = []
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
let browser
let cleaning
let reservedPort

const cleanup = () => cleaning ??= (async () => {
  try { await browser?.close() }
  finally {
    await Promise.allSettled(children.reverse().map(stop))
    if (reservedPort) await reservedPort.release()
  }
})()
for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  process.once(signal, () => { cleanup().finally(() => process.exit(code)) })
}

function child(command, args, options) {
  const process = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'], ...options })
  process.errors = ''
  process.stderr.on('data', data => { process.errors += data })
  children.push(process)
  return process
}

async function stop(process) {
  if (process.exitCode !== null || process.signalCode !== null) return
  const exited = once(process, 'exit')
  process.kill('SIGTERM')
  const timer = setTimeout(() => process.kill('SIGKILL'), 10_000)
  try { await exited } finally { clearTimeout(timer) }
}

async function reservePort() {
  const socket = createServer()
  await new Promise((resolve, reject) => {
    socket.once('error', reject)
    socket.listen(0, '127.0.0.1', resolve)
  })
  const port = socket.address().port
  return { port, release: () => new Promise((resolve, reject) => socket.close(error => error ? reject(error) : resolve())) }
}

async function metadataOf(process) {
  return new Promise((resolve, reject) => {
    let output = ''
    const fail = error => { clearTimeout(timeout); reject(error) }
    const timeout = setTimeout(() => fail(new Error(`Узел не стартовал: ${process.errors}`)), 60_000)
    process.once('error', fail)
    process.once('exit', code => fail(new Error(`Узел завершился (${code}): ${process.errors}`)))
    process.stdout.on('data', data => {
      output += data
      const line = output.split('\n')[0]
      if (!output.includes('\n')) return
      try { const metadata = JSON.parse(line); clearTimeout(timeout); resolve(metadata) }
      catch (error) { clearTimeout(timeout); reject(error) }
    })
  })
}

async function ready(url, process) {
  const until = Date.now() + 60_000
  while (Date.now() < until) {
    assert.equal(process.exitCode, null, `Vite завершился: ${process.errors}`)
    try { if ((await fetch(url, { signal: AbortSignal.timeout(1000) })).ok) return } catch { /* старт */ }
    await sleep(100)
  }
  throw new Error(`Vite не стартовал: ${process.errors}`)
}

try {
  reservedPort = await reservePort()
  const origin = `http://127.0.0.1:${reservedPort.port}`
  const node = child(process.execPath, ['--experimental-strip-types', '--no-warnings=ExperimentalWarning', 'node/test/space-wave7.ts'], {
    cwd: resolve(hubDir), env: { ...process.env, GATEWAY_ORIGINS: origin },
  })
  const meta = await metadataOf(node)
  // Fixture listen(0) не сможет занять зарезервированный порт Vite.
  await reservedPort.release()
  reservedPort = undefined
  const vite = child(process.execPath, [join(appDir, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', new URL(origin).port, '--strictPort'], {
    cwd: appDir,
    env: { ...process.env, BROWSER: 'none', VITE_API_URL: '', VITE_BASE_PATH: '/', VITE_VOICE_API_URL: meta.api, VITE_VOICE_DEV_TOKEN_URL: meta.tokenUrl },
  })
  // Vite stdout постоянно читается: длинный вывод не блокирует дочерний процесс.
  vite.stdout.resume()
  await ready(origin, vite)
  const token = (await (await fetch(`${meta.tokenUrl}?cid=${meta.companyId}`)).json()).token
  async function api(path, options = {}) {
    const response = await fetch(meta.api + path, { ...options, headers: { authorization: `Bearer ${token}`, ...options.headers } })
    assert.ok(response.ok, `${options.method ?? 'GET'} ${path}: ${response.status} ${await response.clone().text()}`)
    return response.json()
  }
  const me = await api('/me')
  assert.equal(me.companyId, meta.companyId)
  const otherToken = (await (await fetch(`${meta.tokenUrl}?cid=wrong-company`)).json()).token
  assert.equal((await fetch(meta.api + '/me', { headers: { authorization: `Bearer ${otherToken}` } })).status, 403)
  assert.equal((await fetch(meta.api + '/me', { headers: { authorization: `Bearer ${token.slice(0, -10)}invalidsig` } })).status, 401)
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) })
  const context = await browser.newContext({ locale: 'ru-RU', timezoneId: 'Europe/Moscow', viewport: { width: 1440, height: 1000 } })
  // Ядро в offline/demo режиме; справочник не относится к данным или логике узла.
  await context.route('**/api/tasks/people?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ people: [
    { id: 'qa-staff', name: 'Сотрудник проверки', partyType: 'internal' },
    { id: 'qa-staff-2', name: 'Второй сотрудник проверки', partyType: 'internal' },
  ] }) }))
  const page = await context.newPage()
  page.setDefaultTimeout(20_000)
  page.on('console', message => { if (['warning', 'error'].includes(message.type())) errors.push(`${message.type()}: ${message.text()}`) })
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    if (!response.url().startsWith(meta.api)) return
    const request = response.request()
    const url = new URL(response.url())
    // Разовый media ticket тоже даёт доступ: в артефактах не оставляем его значение.
    const event = { method: request.method(), path: url.pathname.replace(/\/media\/[^/]+$/, '/media/<ticket>'), query: url.search, status: response.status() }
    network.push(event)
    if (response.status() >= 400) errors.push(`HTTP ${response.status()}: ${event.method} ${event.path}`)
  })
  const responseFor = (path, method = 'GET') => page.waitForResponse(response => response.url().startsWith(meta.api + path) && response.request().method() === method)
  const result = { origin, backend: { kind: 'PGlite + createSpace + HTTP JWKS', companyId: me.companyId }, checks: {}, artifacts }
  const check = (name, detail) => { result.checks[name] = detail }
  async function screenshot(name) {
    const installLater = page.getByRole('button', { name: 'Позже', exact: true })
    if (await installLater.isVisible()) await installLater.click()
    assert.equal(await page.locator('vite-error-overlay').count(), 0, 'Нет Vite overlay')
    assert.ok((await page.locator('body').innerText()).length > 100, 'Экран не пуст')
    const title = await page.title()
    const url = new URL(page.url())
    assert.equal(url.origin, origin, 'Открыт проверяемый локальный интерфейс')
    assert.ok(url.pathname.startsWith('/voice/'), 'Открыт экран телефонии')
    assert.match(title, /^Телефония · /, 'Заголовок вкладки соответствует телефонии')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'Нет горизонтального переполнения')
    await page.screenshot({ path: join(artifacts, name), fullPage: true })
    await writeFile(join(artifacts, name.replace(/\.png$/, '.dom.txt')), await page.locator('body').innerText())
    screens.push({ screenshot: name, url: page.url(), title, viewport: page.viewportSize(), fullPage: true })
  }

  // Р1: положительные выборки обязательных плиток; линия/период переживают карточку и возврат.
  await page.setViewportSize({ width: 1024, height: 900 })
  const statsUrl = `${origin}/voice/stats?period=week&line=${encodeURIComponent(meta.lineId)}`
  const metrics = []
  for (const [metric, label] of [['arrived', 'Поступило'], ['afterHours', 'Вне часов'], ['noDisposition', 'Итог не записан'], ['missed', 'Пропущено']]) {
    const statsResponse = responseFor('/stats/summary')
    await page.goto(statsUrl)
    const summaryResponse = await statsResponse
    const statsQuery = new URL(summaryResponse.url()).searchParams
    assert.equal(statsQuery.get('line'), meta.lineId, 'Сводка действительно отобрана по линии')
    const stats = await summaryResponse.json()
    assert.ok(stats[metric] > 0, `Seed должен содержать ${label}`)
    const tile = page.getByRole('link', { name: new RegExp(`${label}: ${stats[metric]}`) })
    await tile.waitFor()
    const callsResponse = responseFor('/calls?')
    await tile.click()
    const drillResponse = await callsResponse
    const requestQuery = new URL(drillResponse.url()).searchParams
    const drill = await drillResponse.json()
    assert.equal(drill.metric.key, metric)
    assert.equal(drill.metric.total, stats[metric])
    assert.equal(drill.items.length, drill.metric.calls)
    assert.equal(new Set(drill.items.map(call => call.contactId)).size, drill.items.length, 'Перевод не дублирует карточки')
    assert.equal(drill.items.reduce((total, row) => total + row.count, 0), drill.metric.total)
    const listUrl = page.url()
    const callUrl = new URL(listUrl)
    for (const query of [callUrl.searchParams, requestQuery]) {
      assert.equal(query.get('metric'), metric)
      assert.equal(query.get('line'), meta.lineId)
      for (const key of ['from', 'to']) {
        assert.equal(query.get(key), statsQuery.get(key), `Сохранён ${key} сводки`)
        assert.equal(new Date(query.get(key)).toISOString(), drill.metric[key])
      }
    }
    await page.getByLabel('Отбор по показателю').waitFor()
    assert.match(await page.getByLabel('Отбор по показателю').innerText(), /обращений|отрезков на линии|задач перезвона/, 'Видна единица счёта')
    const journalRows = page.locator('table tbody tr')
    await journalRows.first().waitFor()
    assert.equal(await journalRows.count(), drill.items.length, 'В журнале отрисованы все звонки показателя')
    for (const [index, call] of drill.items.entries()) {
      assert.ok((await journalRows.nth(index).innerText()).includes(call.number), `Видна строка ${call.contactId}`)
      assert.equal((await journalRows.nth(index).locator('td').last().innerText()).trim(), String(call.count))
    }
    await screenshot(`1024-metric-${metric}.png`)
    const cardResponse = responseFor(`/calls/${drill.items[0].contactId}`)
    await journalRows.first().click()
    assert.equal((await cardResponse).status(), 200)
    await page.getByRole('button', { name: 'К журналу', exact: true }).click()
    assert.equal(page.url(), listUrl, 'Из карточки возвращаемся к той же выборке')
    await journalRows.first().waitFor()
    assert.equal(await journalRows.count(), drill.items.length)
    await page.getByRole('link', { name: 'Вернуться', exact: true }).click()
    assert.equal(page.url(), new URL(callUrl.searchParams.get('back'), origin).href, 'Восстановлен адрес исходной сводки вместе с общим фильтром Ядра')
    const returned = new URL(page.url()).searchParams
    assert.equal(returned.get('line'), meta.lineId)
    assert.equal(returned.get('period'), 'week')
    await page.getByRole('heading', { name: 'Статистика', exact: true }).waitFor()
    await page.getByRole('button', { name: '7 дней', exact: true, pressed: true }).waitFor()
    await tile.waitFor()
    metrics.push({ metric, total: drill.metric.total, uniqueCalls: drill.metric.calls, unit: drill.metric.unit,
      request: Object.fromEntries(['metric', 'line', 'from', 'to'].map(key => [key, requestQuery.get(key)])),
      items: drill.items.map(call => ({ contactId: call.contactId, count: call.count })), cardReturn: true, statsReturn: true })
  }
  check('R1', { metrics })
  await page.setViewportSize({ width: 1440, height: 1000 })

  // Р3: участники/консультация/попытки берутся из истории настоящего узла.
  await page.goto(`${origin}/voice/calls?id=${encodeURIComponent(meta.seed.transfer)}`)
  await page.getByRole('heading', { name: 'Кто говорил со звонящим' }).waitFor()
  const card = await api('/calls/' + meta.seed.transfer)
  assert.ok(card.legs.some(leg => leg.kind === 'consult'), 'Seed: консультация')
  assert.ok(card.legs.some(leg => leg.kind === 'attempt'), 'Seed: неудачная попытка')
  const legs = page.getByRole('region', { name: 'Участки звонка' })
  const mainLegs = card.legs.filter(leg => ['queue', 'talk', 'consult', 'attempt'].includes(leg.kind))
  const rows = legs.locator('ol').last().locator(':scope > li')
  assert.equal(await rows.count(), mainLegs.length, 'Каждый основной участок имеет отдельную строку')
  for (const [index, leg] of mainLegs.entries()) {
    const text = await rows.nth(index).innerText()
    if (leg.who) assert.ok(text.includes(leg.who.label ?? leg.who.id), `Участник именно участка ${index} (${leg.kind})`)
    if (leg.kind === 'consult') assert.match(text, /Консультация|консультация/)
    if (leg.kind === 'attempt') assert.match(text, /Не ответил|Перевод не состоялся/)
    if (leg.kind === 'talk') assert.match(text, /Разговор|Передан|Соединён/)
    if (leg.durationSec < 60) assert.ok(text.includes(`${Math.round(leg.durationSec)} с`), `Длительность участка ${index}`)
    if (leg.result === 'busy') assert.match(text, /занят/)
    if (leg.result === 'declined') assert.match(text, /отклонил/)
  }
  const technical = page.locator('details').filter({ hasText: 'Технические этапы' })
  assert.equal(await technical.getAttribute('open'), null)
  await technical.locator('summary').click()
  assert.notEqual(await technical.getAttribute('open'), null)
  const recordedLegs = [
    { index: mainLegs.findIndex(leg => leg.kind === 'talk' && leg.role === 'consult_transfer'), recordingId: meta.seed.recordings.operator2, label: 'consult-transfer' },
    { index: mainLegs.findLastIndex(leg => leg.kind === 'talk'), recordingId: meta.seed.recordings.operator3, label: 'after-transfer' },
  ]
  assert.ok(recordedLegs.every(leg => leg.index >= 0), 'Есть разговор после консультации и возврата с перевода')
  const playbacks = []
  for (const recordedLeg of recordedLegs) for (const side of ['operator', 'caller']) {
    const part = mainLegs[recordedLeg.index].recordings.find(recording => recording.side === side)
    assert.ok(part, `У участка есть запись стороны ${side}`)
    assert.equal(part.recordingId, side === 'operator' ? recordedLeg.recordingId : meta.seed.recordings.caller, 'Выбран WAV именно участника участка')
    if (side === 'operator') assert.notEqual(part.recordingId, meta.seed.recordings.operator, 'После передачи звучит новый target WAV')
    await rows.nth(recordedLeg.index).getByRole('button', { name: side === 'operator' ? /^Запись оператора с / : /^Запись звонящего с / }).click()
    const reason = 'Проверка качества синтетического разговора'
    await page.getByRole('dialog').getByLabel('Причина', { exact: true }).fill(reason)
    const ticketResponse = responseFor(`/calls/${meta.seed.transfer}/recordings/${part.recordingId}/ticket`, 'POST')
    const mediaResponse = responseFor('/media/')
    await page.getByRole('dialog').getByRole('button', { name: 'Открыть', exact: true }).click()
    assert.equal((await ticketResponse).status(), 201)
    const media = await mediaResponse
    assert.ok([200, 206].includes(media.status()), 'Запись отдана настоящим media API')
    assert.equal(media.headers()['content-type'], 'audio/wav')
    await page.waitForFunction(offset => {
      const audio = document.querySelector('audio')
      return audio && audio.readyState >= 2 && !audio.paused && audio.currentTime >= offset && audio.currentTime < offset + 10
    }, part.offsetSec)
    const startedAt = await page.locator('audio').evaluate(audio => audio.currentTime)
    await page.waitForFunction(start => {
      const audio = document.querySelector('audio')
      return audio && !audio.paused && audio.currentTime >= start + 0.25
    }, startedAt)
    const audioState = await page.locator('audio').evaluate(audio => ({ duration: audio.duration, currentTime: audio.currentTime, paused: audio.paused, error: audio.error?.code ?? null }))
    await screenshot(`1440-${recordedLeg.label}-${side}-playback.png`)
    await page.locator('audio').evaluate(audio => audio.pause())
    assert.equal(audioState.error, null)
    assert.ok(Math.abs(audioState.duration - card.recordings.find(recording => recording.id === part.recordingId).durationSec) < 0.2)
    const mediaAudit = await api(`/audit?contactId=${encodeURIComponent(meta.seed.transfer)}&limit=100`)
    assert.ok(mediaAudit.items.some(item => item.action === 'recording.ticket' && item.reason === reason && item.detail.recordingId === part.recordingId))
    assert.ok(mediaAudit.items.some(item => item.action === 'recording.play' && item.detail.recordingId === part.recordingId))
    playbacks.push({ leg: recordedLeg.label, side, recordingId: part.recordingId, offset: part.offsetSec, startedAt, ...audioState, audited: true })
  }
  await screenshot('1440-call-legs.png')
  check('R3', { legs: card.legs.map(leg => leg.kind), technicalDetailsExpandable: true, playbacks })

  // Р2: создать долг из реального звонка, передать сотруднику, отметить попытку и закрыть.
  await page.goto(`${origin}/voice/calls?id=${encodeURIComponent(meta.seed.ordinary)}`)
  await page.getByRole('button', { name: 'Завести перезвон' }).click()
  await page.getByRole('radio', { name: 'Сотруднику', exact: true }).click()
  await page.getByLabel('Сотрудник', { exact: true }).fill('Сотрудник проверки')
  const createResponse = responseFor('/callbacks', 'POST')
  await page.getByRole('button', { name: 'Завести', exact: true }).click()
  const created = await (await createResponse).json()
  assert.equal(created.callback.assignee.kind, 'staff')
  assert.equal(created.callback.assignee.name, 'Сотрудник проверки')
  const id = created.callback.id
  await page.getByRole('link', { name: 'Открыть долг' }).click()
  await page.getByRole('button', { name: 'Не дозвонились', exact: true }).waitFor()
  const attemptResponse = responseFor(`/callbacks/${id}/attempts`, 'POST')
  await page.getByRole('button', { name: 'Не дозвонились', exact: true }).click()
  const attempted = await (await attemptResponse).json()
  assert.equal(attempted.attempts, created.callback.attempts + 1)
  assert.equal(attempted.result, null)
  await page.getByText(/Попытка отмечена, долг открыт/).waitFor()
  await page.getByRole('radio', { name: 'Сотруднику', exact: true }).click()
  await page.getByLabel('Сотрудник', { exact: true }).fill('Второй сотрудник проверки')
  const assignResponse = responseFor(`/callbacks/${id}/assign`, 'POST')
  await page.getByRole('button', { name: 'Передать', exact: true }).click()
  const assigned = await (await assignResponse).json()
  assert.equal(assigned.assignee.name, 'Второй сотрудник проверки')
  assert.equal(assigned.assignee.id, 'qa-staff-2')
  assert.equal((await api('/callbacks/' + id)).assignee.id, 'qa-staff-2')
  await screenshot('1440-contact-debt.png')
  await page.getByLabel('Причина закрытия').fill('Проверка: вопрос решён сотрудником')
  const closeResponse = responseFor(`/callbacks/${id}/close`, 'POST')
  await page.getByRole('button', { name: 'Закрыть долг', exact: true }).click()
  const closed = await (await closeResponse).json()
  assert.equal(closed.result, 'reached')
  const open = await api('/callbacks?state=open&limit=100')
  assert.ok(!open.items.some(item => item.id === id), 'Закрытый долг исчез из открытых')
  const audit = await api(`/audit?contactId=${encodeURIComponent(meta.seed.ordinary)}&limit=100`)
  for (const action of ['callback.create', 'callback.attempt', 'callback.assign', 'callback.close']) {
    assert.ok(audit.items.some(item => item.action === action), `В БД записан аудит ${action}`)
  }
  check('R2', { created: true, attemptPersisted: true, reassigned: true, closedRemovedFromOpen: true, audited: true })

  // Р5: изменить и сразу симулировать; сервер читает сохранённый draft, active не меняется.
  const activeBefore = await api('/config/reception')
  await page.goto(origin + '/voice/reception?tab=callback')
  await page.getByRole('heading', { name: 'Правила приёма', exact: true }).waitFor()
  await page.getByRole('switch', { name: 'Перезвонить пропущенным', exact: true }).click()
  const delay = page.getByLabel('Через сколько минут перезванивать')
  await delay.waitFor()
  await page.getByRole('button', { name: /Проверить на примере/ }).click()
  await delay.fill('7')
  const simulationResponse = page.waitForResponse(response => response.url().startsWith(meta.api + '/config/reception/versions/') && response.url().endsWith('/simulate'))
  await page.getByRole('button', { name: 'Показать маршрут' }).click()
  const simulation = await (await simulationResponse).json()
  assert.ok(simulation.versions.reception > activeBefore.version)
  const draft = await api('/config/reception/versions/' + simulation.versions.reception)
  assert.equal(draft.body.missedCallback.delayMin, 7)
  assert.equal(simulation.state.reception, 'draft')
  const activeAfter = await api('/config/reception')
  assert.deepEqual(activeAfter.body, activeBefore.body, 'Симуляция не применяет настройки')
  await page.getByText(/Ответит оператор контакт-центра|Звонящий услышит сообщение|Уйдёт переадресацией/).first().waitFor()
  await screenshot('1440-draft-simulation.png')
  check('R5', { savedVersion: draft.version, delayMin: draft.body.missedCallback.delayMin, activeUnchanged: true })

  for (const [width, height] of [[1024, 900], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.goto(`${origin}/voice/calls?id=${encodeURIComponent(meta.seed.transfer)}`)
    await page.getByRole('heading', { name: 'Кто говорил со звонящим' }).waitFor()
    await screenshot(`${width}-call-legs.png`)
    if (width === 390) {
      await page.getByRole('region', { name: 'Участки звонка' }).locator('ol').last().locator(':scope > li').last().scrollIntoViewIfNeeded()
      await screenshot('390-call-recordings.png')
    }
    await page.getByRole('button', { name: 'К журналу', exact: true }).waitFor()
  }
  assert.deepEqual(errors, [], 'Браузерные/HTTP ошибки')
  assert.ok(network.length > 20, 'Проверка выполнила реальные запросы к узлу')
  check('browser', { version: browser.version(), identity: true, notBlank: true, noOverlay: true, noConsoleErrors: true, widths: [1440, 1024, 390], nodeRequests: network.length })
  await cleanup()
  assert.equal(node.exitCode, 0, 'Узел штатно закрыл БД')
  await assert.rejects(access(meta.dataDir), 'Временные БД и ключи удалены')
  await assert.rejects(fetch(meta.gateway + '/jwks.json'), 'Слушатель шлюза закрыт')
  await assert.rejects(fetch(origin), 'Vite остановлен')
  check('cleanup', { processesStopped: true, temporaryDatabaseAndKeysRemoved: true })
  await writeFile(join(artifacts, 'network.json'), JSON.stringify(network, null, 2))
  await writeFile(join(artifacts, 'console.json'), JSON.stringify(errors, null, 2))
  await writeFile(join(artifacts, 'screens.json'), JSON.stringify(screens, null, 2))
  await writeFile(join(artifacts, 'result.json'), JSON.stringify(result, null, 2))
  process.stdout.write(JSON.stringify(result, null, 2) + '\n')
} catch (error) {
  await writeFile(join(artifacts, 'console.json'), JSON.stringify(errors, null, 2))
  await writeFile(join(artifacts, 'network.json'), JSON.stringify(network, null, 2))
  await writeFile(join(artifacts, 'screens.json'), JSON.stringify(screens, null, 2))
  process.stderr.write(`${error.stack ?? error}\nАртефакты: ${artifacts}\n`)
  if (browser) {
    const page = browser.contexts()[0]?.pages()[0]
    if (page) {
      await page.screenshot({ path: join(artifacts, 'failure.png'), fullPage: true }).catch(() => {})
      await writeFile(join(artifacts, 'failure.txt'), await page.locator('body').innerText().catch(() => '')).catch(() => {})
    }
  }
  process.exitCode = 1
} finally {
  await cleanup()
}
