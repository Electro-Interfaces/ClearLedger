/** Focused local UI regression. Explicit synthetic API mocks; no real accounts.
 * VITE_API_URL=http://127.0.0.1:18898 webdev dev
 * TASK_QUEUE_ORIGIN=http://127.0.0.1:18898 node e2e/task-queue.check.mjs
 * Browser plugin not available; use the project's Playwright.
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium, devices, expect as baseExpect } from '@playwright/test'
const expect = baseExpect.configure({ timeout: 20000 })
const origin = process.env.TASK_QUEUE_ORIGIN ?? 'http://127.0.0.1:18898'
assert.match(origin, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/)
const out = new URL('../../.artifacts/queue-ui/', import.meta.url)
await mkdir(out, { recursive: true })
const cid = '11111111-1111-4111-8111-111111111111', uid = '22222222-2222-4222-8222-222222222222'
const tid = '33333333-3333-4333-8333-333333333333', other = '44444444-4444-4444-8444-444444444444'
const title = 'Тест · Проверить поручение и сохранить место в очереди'
const longTitle = ('Тест · ' + 'Длинное поручение для проверки доступной ширины '.repeat(10)).slice(0, 300)
const task = { id: tid, number: 901, title, description: 'Тест · Полная карточка',
  status: 'open', priority: 'medium', stage: 'Постановка', stage_code: 'new',
  route: [{ code: 'new', name: 'Постановка' }], assignee: 'Тест · Исполнитель', assignee_id: uid,
  author: 'Тест · Автор', due_at: '2026-10-21T15:00:00Z', overdue: true,
  created_at: '2026-10-20T10:00:00Z',
  events: [], checklist_items: [], watchers: [], attachments: [], participants: [], external: [], work_items: [], labels: [],
  links: [{ id: 'link-1', task_id: other, number: 902, title: 'Тест · Связанное поручение', kind: 'related', status: 'open' }],
  checklist: { total: 0, done: 0 }, subtasks: { total: 0, open: 0 },
  time: { estimate: null, spent: 0, estimate_text: '—', spent_text: '0м' } }
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium' })
const results = []
let debugPage, debugErrors
async function setup(options = {}) {
  const context = await browser.newContext({ locale: 'ru-RU', timezoneId: 'Europe/Moscow', ...options })
  await context.addInitScript(() => {
    localStorage.setItem('clearledger-token', 'synthetic-ui-mock-session')
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
  })
  const page = await context.newPage(), errors = [], requests = [], actions = []
  let boardDue = '2026-10-23T15:00:00Z'
  debugPage = page; debugErrors = errors
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('WebSocket')) errors.push(m.text()) })
  page.on('pageerror', e => errors.push(e.message))
  await context.routeWebSocket('**/api/chat/ws*', ws => {
    ws.onMessage(m => { if (JSON.parse(String(m)).type === 'ping') ws.send(JSON.stringify({ type: 'pong' })) })
  })
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname
    let data = {}
    if (p === '/api/auth/me') data = { id: uid, email: 'queue@example.test', name: 'Тест · Исполнитель', role: 'user', is_superadmin: true, default_company_id: cid,
      companies: [{ id: cid, slug: 'rushydro', name: 'Тест · РусГидро', short_name: 'Тест · РусГидро', profile_id: 'energy' }] }
    else if (p === '/api/registry/company-apps') data = { apps: [{ code: 'docs', enabled: true, name: 'Трек', modules: [] }] }
    else if (p === '/api/chat/rooms') data = []
    else if (p === '/api/tasks/assignment-counts') data = { new: 1, overdue: 1 }
    else if (p === `/api/tasks/${tid}/action`) {
      const body = route.request().postDataJSON()
      actions.push(body)
      boardDue = body.due_at
      data = { ...task, due_at: boardDue }
    }
    else if (p === `/api/tasks/${tid}` || p === `/api/tasks/${other}`) {
      data = p.endsWith(other) ? { ...task, id: other, number: 902, title: 'Тест · Связанное поручение', links: [] } : task
    } else if (p === '/api/tasks') {
      requests.push(Object.fromEntries(url.searchParams))
      const filtered = url.searchParams.get('assignee_id') === '55555555-5555-4555-8555-555555555555'
      data = { tasks: filtered ? [] : [task], total: filtered ? 0 : 1 }
    } else if (p === '/api/tasks/people') data = { people: [{ id: uid, name: 'Тест · Исполнитель' }, { id: '55555555-5555-4555-8555-555555555555', name: 'Тест · Другой' }] }
    else if (p === '/api/tasks/types') data = { types: [{ id: 'call', name: 'Звонок', route: [] }] }
    else if (p === '/api/tasks/labels') data = { labels: [] }
    else if (p === '/api/tasks/summary') data = { totals: { open: 1, overdue: 1, mine: 1, unassigned: 0, created: 1, done: 2 },
      by_assignee: [{ id: uid, name: 'Тест · Исполнитель', open: 1, overdue: 1, done: 2 }],
      by_type: [{ id: 'call', name: 'Звонок', open: 1, overdue: 1, done: 2 }], by_object: [], activity: [] }
    else if (p === '/api/work/mine') data = { mine: [{ kind: 'task', id: tid, reason: 'do', reason_name: 'Поручено', key: '901', title, due_at: task.due_at, overdue: true, bucket: 'overdue', mark: null },
      { kind: 'task', id: other, reason: 'do', reason_name: 'Поручено', key: '902', title: longTitle, due_at: task.due_at, overdue: true, bucket: 'overdue', mark: null }],
      buckets: [{ code: 'overdue', name: 'Просрочено' }, { code: 'today', name: 'Сегодня' }] }
    else if (p === '/api/work/lists') data = { lists: [], counts: { starred: 0, deferred: 0, day: 1, unplaced: 0 } }
    else if (p === '/api/work/placed') data = { items: [{ kind: 'task', id: tid, key: '901', title, due_at: task.due_at, mark: {} }] }
    else if (p === '/api/work/reminders') data = { items: [], total: 0 }
    else if (p === '/api/work/calendar') data = { events: [], total: 0 }
    else if (p === '/api/work/plan') data = { days: {} }
    else if (p === '/api/work') data = { work: [{ ...task, kind: 'task', key: '901', state: 'in_work', state_name: 'В работе', due_at: boardDue, overdue: boardDue === '2026-10-22T15:00:00.000Z' }], total: 1, columns: [] }
    else if (p.endsWith('/organizations')) data = []
    else if (p.endsWith('/results')) data = { items: [] }
    else if (p.endsWith('/origin')) data = { origin: null }
    else if (p === '/api/partner-space/spaces') data = { items: [] }
    else if (p === '/api/registry/objects') data = { objects: [] }
    else if (p.includes('/registry/')) data = { apps: [], catalog: [] }
    else if (p.includes('/docs')) data = { items: [], docs: [], kinds: [], total: 0 }
    return route.fulfill({ json: data })
  })
  return { context, page, errors, requests, actions }
}
async function selectQueue(page, queue) {
  await expect(queue.getByRole('button').filter({ hasText: title }).first()).toBeVisible()
  const desktop = queue.getByRole('button', { name: /^Моя очередь/ })
  if (await desktop.count()) await desktop.click()
  else {
    await queue.getByRole('button', { name: /^Сегодня/ }).click()
    await page.getByRole('menuitem', { name: /^Моя очередь/ }).click()
  }
}
try {
  for (const [name, options] of (process.env.TASK_QUEUE_PART === 'routes' ? [] : [
    ['desktop', { viewport: { width: 1440, height: 1000 } }],
    ['pixel-landscape', { ...devices['Pixel 5 landscape'], viewport: { width: 802, height: 293 } }],
    ['pixel-portrait', { ...devices['Pixel 5'] }],
    ['iphone-landscape', { ...devices['iPhone 13 landscape'], viewport: { width: 664, height: 390 } }],
    ['touch-767', { viewport: { width: 767, height: 390 }, hasTouch: true }],
    ['touch-768', { viewport: { width: 768, height: 390 }, hasTouch: true }],
    ['narrow', { viewport: { width: 320, height: 740 }, hasTouch: true, isMobile: true }],
  ])) {
    const { context, page, errors } = await setup(options)
    await page.goto(origin + '/docs/work')
    await expect(page.getByRole('heading', { name: 'Сегодня', exact: true })).toBeVisible()
    await page.getByRole('button', { name: /^Трек · новые назначения:/ }).first().click()
    const queue = page.getByRole('dialog').first()
    await selectQueue(page, queue)
    const line = queue.getByRole('button').filter({ hasText: title }).first()
    await expect(line).toBeVisible()
    const box = await line.boundingBox()
    assert.ok(box.width >= 80, `${name}: title control width ${box.width}`)
    await page.screenshot({ path: new URL(`${name}.png`, out).pathname })
    if (options.hasTouch) await line.tap()
    else { await line.focus(); await page.keyboard.press('Enter') }
    const card = page.getByRole('dialog', { name: 'Карточка поручения' })
    await expect(card).toBeVisible()
    await expect(card.getByText('Тест · Полная карточка', { exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(card).toHaveCount(0)
    await expect(line).toBeFocused()
    const longLine = queue.getByRole('button').filter({ hasText: longTitle }).first()
    const longBox = await longLine.boundingBox()
    assert.ok(longBox.width >= 80, `${name}: long title control width ${longBox.width}`)
    if (options.hasTouch) await longLine.tap()
    else await longLine.click()
    await expect(card).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(longLine).toBeFocused()
    if (name === 'desktop') {
      await page.keyboard.press('Tab')
      assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'BUTTON')
      await expect(queue.locator(':focus')).toHaveCount(1)
      assert.equal(await longLine.evaluate(el => el === document.activeElement), false)
      await line.click()
      await card.getByRole('tab', { name: /Связи/ }).click()
      await card.getByRole('button', { name: /№902 Тест · Связанное поручение/ }).click()
      await expect(card.getByText('Тест · Связанное поручение', { exact: true }).first()).toBeVisible()
      await card.getByRole('button', { name: 'к списку', exact: true }).click()
      await expect(line).toBeFocused()
      const dayLine = queue.locator('aside').getByRole('button').filter({ hasText: title })
      await dayLine.click()
      await card.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dayLine).toBeFocused()
    }
    if (name === 'pixel-landscape') {
      const input = queue.getByPlaceholder('Записать задачу себе — Enter поставит')
      await input.fill('Тест · Черновик при повороте')
      await line.tap()
      await page.setViewportSize({ width: 393, height: 727 })
      await expect(card).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(input).toHaveValue('Тест · Черновик при повороте')
      await expect(line).toBeFocused()
      await page.setViewportSize({ width: 802, height: 293 })
      await expect(line).toBeVisible()
    }
    assert.deepEqual(errors, [], `${name}: runtime errors`)
    results.push({ name, width: box.width, focus: 'passed', errors })
    process.stdout.write(`${name}: passed, title width ${box.width}px\n`)
    await context.close()
  }
  const { context, page, requests, errors, actions } = await setup({ viewport: { width: 1440, height: 1000 } })
  const filter = '55555555-5555-4555-8555-555555555555'
  const url = `/docs/company?view=errands&assignee=${filter}&q=счёт&sort=due`
  await page.goto(origin + '/docs/company?view=errands&q=счёт&sort=due')
  await page.locator('button').filter({ hasText: 'Любой исполнитель' }).click()
  await page.getByRole('listbox').getByRole('option', { name: 'Тест · Другой', exact: true }).click()
  await expect(page.locator('button').filter({ hasText: 'Тест · Другой' })).toBeVisible()
  assert.equal(new URL(page.url()).searchParams.get('assignee'), filter)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.goto(origin + url)
  await expect(page.locator('button').filter({ hasText: 'Тест · Другой' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  assert.equal(new URL(page.url()).searchParams.get('assignee'), filter)
  await page.reload()
  await expect(page.locator('button').filter({ hasText: 'Тест · Другой' })).toBeVisible()
  assert.equal(new URL(page.url()).searchParams.get('assignee'), filter)
  assert.ok(requests.some(r => r.assignee_id === filter && r.q === 'счёт' && r.sort === 'due'))
  await page.goto(origin + '/docs/overview?view=errands&date_from=2026-10-01&date_to=2026-10-22')
  await page.goBack()
  await expect(page.locator('button').filter({ hasText: 'Тест · Другой' })).toBeVisible()
  assert.equal(new URL(page.url()).searchParams.get('assignee'), filter)
  await page.goto(origin + '/docs/overview?view=errands&date_from=2026-10-01&date_to=2026-10-22')
  await page.getByRole('button').filter({ hasText: /^Закрыто2/ }).click()
  await expect(page.getByText(/Закрытые поручения · закрыты/)).toBeVisible()
  let params = new URL(page.url()).searchParams
  assert.equal(params.get('scope'), 'closed')
  assert.equal(params.get('closed_from'), '2026-10-01')
  assert.equal(params.get('closed_to'), '2026-10-22')
  await expect.poll(() => requests.some(r => r.scope === 'closed' && r.closed_from === '2026-10-01' && r.closed_to === '2026-10-22')).toBe(true)
  await page.reload()
  await expect(page.getByText(/Закрытые поручения · закрыты/)).toBeVisible()
  await page.getByRole('button', { name: 'Снять отбор отчёта', exact: true }).click()
  assert.equal(new URL(page.url()).searchParams.has('scope'), false)
  assert.equal(new URL(page.url()).searchParams.has('closed_from'), false)
  assert.equal(new URL(page.url()).searchParams.has('closed_to'), false)
  for (const [label, scope, field, value] of [
    ['Тест · Исполнитель · В работе: 1', 'open', 'assignee', uid],
    ['Тест · Исполнитель · Просрочено: 1', 'overdue', 'assignee', uid],
    ['Звонок · Закрыто за период: 2', 'closed', 'type', 'call'],
  ]) {
    await page.goto(origin + '/docs/overview?view=errands&date_from=2026-10-01&date_to=2026-10-22')
    await page.getByRole('button', { name: label, exact: true }).click()
    params = new URL(page.url()).searchParams
    assert.equal(params.get('scope'), scope)
    assert.equal(params.get(field), value)
    assert.equal(params.has('closed_from'), scope === 'closed')
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await page.goto(origin + '/docs/company?view=errands&draft=Тест%20черновик&draft_assignee=' + uid)
  await expect(page.getByRole('dialog', { name: 'Новая задача' })).toBeVisible()
  assert.equal(new URL(page.url()).searchParams.has('draft'), false)
  await page.keyboard.press('Escape')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Поручения компании', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.clock.setFixedTime(new Date('2026-10-22T20:05:00+03:00'))
  await page.goto(origin + '/docs/company?view=work-board&axis=due')
  await expect(page.getByText(/После 18:00 перенос в «Сегодня» попадёт в «Просрочено»/)).toBeVisible()
  await expect(page.locator('[data-col="today"]').getByText('Срок — сегодня в 18:00. После 18:00 — в «Просрочено»')).toBeVisible()
  await page.locator('[data-col="tomorrow"] [draggable="true"]').dragTo(page.locator('[data-col="today"]'))
  await expect(page.getByText('Срок — 22 октября, 18:00', { exact: true })).toBeVisible()
  await expect(page.getByText('Срок уже прошёл: поручение в «Просрочено».', { exact: true })).toBeVisible()
  assert.equal(actions.at(-1).due_at, '2026-10-22T15:00:00.000Z')
  await expect(page.locator('[data-col="overdue"]').getByText(title)).toBeVisible()
  assert.deepEqual(errors, [])
  results.push({ name: 'URL draft/filter/report/board', passed: true, errors })
  await context.close()
  await writeFile(new URL('result.json', out), JSON.stringify({ origin, api: 'synthetic mocks', results }, null, 2))
  process.stdout.write(JSON.stringify(results, null, 2) + '\n')
} catch (e) {
  if (debugPage && !debugPage.isClosed()) {
    await debugPage.screenshot({ path: new URL('failure.png', out).pathname }).catch(() => {})
    await writeFile(new URL('failure.txt', out), `${e.stack}\nErrors: ${JSON.stringify(debugErrors)}\n${await debugPage.locator('body').innerText().catch(() => '')}`)
  }
  throw e
} finally { await browser.close() }
