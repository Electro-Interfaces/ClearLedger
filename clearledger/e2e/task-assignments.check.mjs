/** Local UI regression with explicit API mocks; synthetic users, no real tokens.
 * Vite: VITE_API_URL=http://127.0.0.1:3019 npm run dev -- --port 3019
 * Run: node e2e/task-assignments.check.mjs
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium, expect } from '@playwright/test'
const origin = process.env.TASK_BADGES_ORIGIN ?? 'http://127.0.0.1:3019'
assert.match(origin, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/)
const out = new URL('../../.artifacts/', import.meta.url)
await mkdir(out, { recursive: true })
const cid = '11111111-1111-4111-8111-111111111111', uid = '22222222-2222-4222-8222-222222222222'
const tid = '33333333-3333-4333-8333-333333333333', rev = '44444444-4444-4444-8444-444444444444'
const title = 'Тест · Проверить назначение', description = 'Полная карточка поручения: описание и лента.'
const task = { id: tid, number: 901, key: '901', title, description, assignment_revision: rev,
  status: 'open', priority: 'medium', stage: 'Постановка', stage_code: 'new',
  route: [{ code: 'new', name: 'Постановка' }, { code: 'in_progress', name: 'В работе' }],
  assignee: 'Тест · Исполнитель', assignee_id: uid, author: 'Тест · Автор',
  due_at: new Date(Date.now() - 86400000).toISOString(), overdue: true, created_at: '2026-10-22T10:00:00Z',
  events: [{ id: 'e1', kind: 'created', user: 'Тест · Автор', created_at: '2026-10-22T10:00:00Z' }],
  checklist_items: [], watchers: [], attachments: [], links: [], participants: [], external: [], work_items: [], labels: [],
  checklist: { total: 0, done: 0 }, subtasks: { total: 0, open: 0 }, time: { estimate: null, spent: 0, estimate_text: '—', spent_text: '0м' } }
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium' })
const results = []
let debugPage, debugErrors
try {
  for (const [device, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport, locale: 'ru-RU' })
    await context.addInitScript(() => {
      localStorage.setItem('clearledger-token', 'synthetic-ui-mock-session')
      localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
    })
    const page = await context.newPage(), errors = []
    debugPage = page; debugErrors = errors
    page.on('pageerror', e => errors.push(e.stack ?? e.message))
    page.on('console', m => { if (m.type() === 'error' && !m.text().includes('WebSocket')) errors.push(m.text()) })
    let incoming = 1, acks = 0, loaded = 0, fail = false, gate, release, queueVisible = true
    const sockets = []
    await context.routeWebSocket('**/api/chat/ws*', ws => {
      sockets.push(ws)
      ws.onMessage(m => { if (JSON.parse(String(m)).type === 'ping') ws.send(JSON.stringify({ type: 'pong' })) })
    })
    await context.route('**/api/**', async route => {
      const p = new URL(route.request().url()).pathname
      let data = {}
      if (p === '/api/auth/me') data = { id: uid, email: 'ui@example.test', name: 'Тест · Исполнитель', role: 'user', is_superadmin: true, default_company_id: cid,
        companies: [{ id: cid, slug: 'rushydro', name: 'Тест · РусГидро', short_name: 'Тест · РусГидро', profile_id: 'energy' }] }
      else if (p === '/api/registry/company-apps') data = { apps: [{ code: 'docs', enabled: true, name: 'Трек', modules: [] }, { code: 'plan', enabled: false, modules: [] }] }
      else if (p === '/api/chat/rooms') data = []
      else if (p === '/api/tasks/assignment-counts') data = { new: incoming, overdue: 1 }
      else if (p === `/api/tasks/${tid}/assignment-view`) {
        assert.ok(loaded > 0, 'ACK before detail load')
        assert.equal(route.request().postDataJSON().assignment_revision, rev)
        acks++; incoming = 0; data = { acknowledged: true }
      } else if (p === `/api/tasks/${tid}`) {
        if (gate) await gate
        if (fail) return route.fulfill({ status: 500, json: { detail: 'Тест · Карточка недоступна' } })
        loaded++; data = task
      } else if (p === '/api/tasks') data = { tasks: queueVisible ? [task] : [], total: queueVisible ? 1 : 0 }
      else if (p === '/api/tasks/people') data = { people: [{ id: uid, name: 'Тест · Исполнитель', email: 'ui@example.test' }] }
      else if (p === '/api/tasks/types') data = { types: [] }
      else if (p === '/api/tasks/labels') data = { labels: [] }
      else if (p === '/api/tasks/summary') data = { open: 1, overdue: 1 }
      else if (p === '/api/work/mine') data = { mine: queueVisible ? [{ kind: 'task', id: tid, reason: 'do', reason_name: 'Поручено', key: '901', title, due_at: task.due_at, overdue: true, bucket: 'overdue', mark: null }] : [], buckets: [{ code: 'overdue', name: 'Просрочено' }, { code: 'today', name: 'Сегодня' }, { code: 'week', name: 'На неделе' }, { code: 'later', name: 'Позже' }] }
      else if (p === '/api/work/lists') data = { lists: [], counts: { starred: 0, deferred: 0, day: 0, unplaced: 0 } }
      else if (p === '/api/work/placed') data = { items: [] }
      else if (p === '/api/work/reminders') data = { items: [], total: 0 }
      else if (p === '/api/work/calendar') data = { events: [], total: 0 }
      else if (p.endsWith('/organizations')) data = []
      else if (p.endsWith('/results')) data = { items: [] }
      else if (p.endsWith('/origin')) data = { origin: null }
      else if (p === '/api/partner-space/spaces') data = { items: [] }
      else if (p === '/api/work/plan') data = { days: {} }
      else if (p === '/api/registry/objects') data = { objects: [] }
      else if (p.includes('/registry/')) data = { apps: [], catalog: [] }
      else if (p.includes('/docs')) data = { items: [], docs: [], kinds: [], total: 0 }
      return route.fulfill({ json: data })
    })
    await page.goto(origin + '/docs/work')
    const track = page.getByRole('button', { name: 'Трек · новые назначения: 1 · просрочено: 1', exact: true }).first()
    await expect(track).toBeVisible({ timeout: 20000 })
    await page.screenshot({ path: new URL(`task-badges-${device}.png`, out).pathname })
    await track.click()
    const queue = page.getByRole('dialog').first()
    await expect(queue).toBeVisible()
    if (device === 'mobile') {
      await queue.getByRole('button', { name: /^Сегодня/ }).click()
      await page.getByRole('menuitem', { name: /^Моя очередь/ }).click()
    } else {
      await queue.getByRole('button', { name: /^Моя очередь/ }).click()
    }
    assert.equal(acks, 0)
    const line = () => queue.getByRole('button').filter({ hasText: title }).first()
    await expect(line()).toBeVisible()
    const before = page.url()
    gate = new Promise(resolve => { release = resolve })
    await line().click()
    const card = page.getByRole('dialog', { name: 'Карточка поручения' })
    await expect(card).toBeVisible()
    await expect(card.locator('.animate-spin')).toBeVisible()
    assert.equal(acks, 0, 'Loading must not ACK')
    release(); gate = null
    await expect(card.getByText(description, { exact: true })).toBeVisible()
    await expect.poll(() => acks).toBe(1)
    await expect(page.locator('button[aria-label="Трек · новые назначения: 0 · просрочено: 1"]').first()).toBeAttached()
    assert.equal(page.url(), before)
    await page.screenshot({ path: new URL(`task-card-${device}.png`, out).pathname })
    const box = await card.boundingBox()
    assert.ok(box && box.x >= -1 && box.x + box.width <= viewport.width + 1, 'Viewport overflow')
    await page.keyboard.press('Escape')
    await expect(card).toHaveCount(0)
    await expect(line()).toBeVisible()
    await page.screenshot({ path: new URL(`task-queue-${device}.png`, out).pathname })
    // Incoming changes also refresh the already open mixed queue.
    assert.ok(sockets.length > 0)
    queueVisible = false
    const signal = () => sockets.forEach(ws => ws.send(JSON.stringify({ type: 'task:assignments-changed', companyId: cid })))
    signal()
    await expect(line()).toHaveCount(0)
    queueVisible = true; incoming = 1
    signal()
    await expect(line()).toBeVisible()
    await expect(page.locator('button[aria-label="Трек · новые назначения: 1 · просрочено: 1"]').first()).toBeAttached()
    await line().click()
    await expect(card.getByText(description, { exact: true })).toBeVisible()
    await card.getByRole('button', { name: 'Открыть в Треке', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/docs/company\\?view=errands&task=${tid}`))
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByText(description, { exact: true })).toBeVisible()
    const previous = acks
    await page.reload()
    await expect(page.getByText(description, { exact: true })).toBeVisible()
    await expect.poll(() => acks).toBeGreaterThan(previous)
    const successAcks = acks
    fail = true
    await page.reload()
    await expect(page.getByText('Не удалось загрузить задачу', { exact: false }).first()).toBeVisible()
    assert.equal(acks, successAcks, 'Failed card must not ACK')
    const relevant = errors.filter(e => !e.includes('500 (Internal Server Error)'))
    assert.deepEqual(relevant, [], `${device}: console errors`)
    results.push({ device, loaded, acknowledgements: acks, url: page.url(), viewport, errors: relevant })
    await context.close()
  }
  await writeFile(new URL('task-badges-browser.json', out), JSON.stringify({ mode: 'explicit API mocks', results }, null, 2))
  process.stdout.write(JSON.stringify(results, null, 2) + '\n')
} catch (error) {
  if (debugPage && !debugPage.isClosed()) {
    await debugPage.screenshot({ path: new URL('task-badges-failure.png', out).pathname })
    await writeFile(new URL('task-badges-failure.txt', out), (await debugPage.locator('body').innerText()) + '\n' + JSON.stringify(debugErrors, null, 2))
  }
  throw error
} finally { await browser.close() }
