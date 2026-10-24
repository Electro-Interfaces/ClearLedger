import { test, expect, type Page, type Route } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

// Синтетика исключительно в тестовом harness. Код приложения фикстуры не импортирует.
const A = '11111111-1111-4111-8111-111111111111'
const B = '22222222-2222-4222-8222-222222222222'
const CHAT = '33333333-3333-4333-8333-333333333333'
const TASK = '44444444-4444-4444-8444-444444444444'
const EVENT = '55555555-5555-4555-8555-555555555555'
const companies = [
  { id: A, slug: 'a', name: 'Тестовая организация А', profile_id: 'office', role: 'admin', modules: null },
  { id: B, slug: 'b', name: 'Тестовая организация Б', profile_id: 'office', role: 'admin', modules: null },
]
const source = { code: 'local', name: 'Тестовое пространство', state: 'ok', fetched_at: '2026-10-24T12:00:00Z', error: null }
const remote = { code: 'remote', name: 'Тестовый удалённый источник', state: 'forbidden', fetched_at: null, error: 'SECRET https://internal.test TOKEN=secret' }
const item = (overrides: Record<string, unknown> = {}) => ({
  id: 'local:a:chats:1', source_id: CHAT, kind: 'chats',
  source: { code: 'local', name: source.name, company_id: A, company_name: companies[0].name },
  title: 'Тестовый рабочий чат', subtitle: 'Синтетическая запись для проверки интерфейса',
  unread_count: 3, status: 'group', href: `/?company=${A}&chat=${CHAT}`, updated_at: '2026-10-24T12:00:00Z', ...overrides,
})
const response = (overrides: Record<string, unknown> = {}) => ({
  enabled: true, fetched_at: '2026-10-24T12:00:00Z', items: [item()], sources: [source], truncated: false, ...overrides,
})
type State = {
  enabled?: boolean
  statusError?: number
  overview?: (route: Route, url: URL) => Promise<void>
  meWait?: Promise<void>
}
async function setup(page: Page, state: State = {}) {
  const requests: { path: string; company: string | undefined; method: string; params: URLSearchParams }[] = []
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.stack || error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' && /TypeError|ReferenceError|ErrorBoundary/.test(message.text())) errors.push(message.text())
  })
  await page.addInitScript(() => {
    localStorage.setItem('clearledger-token', 'management-fixture-only')
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
    sessionStorage.setItem('cl-booted', '1')
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const p = url.pathname
    requests.push({ path: p, company: route.request().headers()['x-company-id'], method: route.request().method(), params: url.searchParams })
    if (p === '/api/auth/me') {
      await state.meWait
      return route.fulfill({ json: { id: 'fixture-user', name: 'Проверка интерфейса', email: 'fixture@example.test', role: 'admin', is_superadmin: true, companies } })
    }
    if (p === '/api/management/status') return route.fulfill(state.statusError ? { status: state.statusError, json: { detail: 'SECRET internal config' } } : { json: { enabled: state.enabled ?? true } })
    if (p === '/api/management/overview') return state.overview ? state.overview(route, url) : route.fulfill({ json: response() })
    if (p === '/api/companies') return route.fulfill({ json: companies })
    if (p === '/api/partner-space/spaces') return route.fulfill({ json: { items: [] } })
    if (p.startsWith('/api/work-contexts/')) return route.fulfill({ json: { items: [] } })
    const room = {
      id: CHAT, type: 'group', scopeProduct: null, name: 'Тестовый чат оригинала', isArchived: false,
      participantCount: 1, unreadCount: 0, directPeerId: null, lastMessage: null, lastMessageAt: null,
      createdBy: 'fixture-user', pinnedMessage: null, myRole: 'member', canWrite: false,
      participants: [{ userId: 'fixture-user', name: 'Проверка интерфейса', role: 'member', online: true }],
    }
    if (p === '/api/chat/rooms') return route.fulfill({ json: [room] })
    if (p === `/api/chat/rooms/${CHAT}`) return route.fulfill({ json: room })
    if (p === `/api/tasks/${TASK}`) return route.fulfill({ json: {
      id: TASK, number: 42, title: 'Тестовая задача оригинала', status: 'done', priority: 'normal',
      route: [], stage_code: null, type_id: null, due_at: null, description: 'Оригинал задачи',
      created_at: '2026-10-24T12:00:00Z', updated_at: '2026-10-24T12:00:00Z',
    } })
    if (p === '/api/tasks') return route.fulfill({ json: { tasks: [], total: 0, offset: 0, limit: 100 } })
    if (p === '/api/tasks/people') return route.fulfill({ json: { people: [] } })
    if (p === '/api/tasks/types') return route.fulfill({ json: { types: [], default_route: [] } })
    if (p === '/api/tasks/labels') return route.fulfill({ json: { labels: [] } })
    if (p === `/api/work/calendar/${EVENT}`) return route.fulfill({ json: {
      id: EVENT, title: 'Тестовая встреча оригинала', starts_at: '2026-10-24T22:30:00Z', ends_at: '2026-10-24T23:00:00Z',
      all_day: false, tz: 'Europe/Moscow', location: null, conference_url: null, visibility: 'company', status: 'planned',
      organizer_id: 'fixture-user', is_organizer: true, my_response: null, attendees: [],
    } })
    if (p === '/api/work/calendar') return route.fulfill({ json: { events: [], total: 0 } })
    if (p === '/api/work/reminders' || p === '/api/work/placed') return route.fulfill({ json: { items: [], total: 0 } })
    if (p === '/api/work/plan') return route.fulfill({ json: { days: [] } })
    if (p === '/api/work/lists') return route.fulfill({ json: { lists: [], counts: { starred: 0, deferred: 0 } } })
    if (p === '/api/work/calendar/busy') return route.fulfill({ json: { people: [] } })
    if (p === '/api/work/mine') return route.fulfill({ json: { mine: [], notes: [], total: 0 } })
    if (p === '/api/work') return route.fulfill({ json: { items: [], total: 0 } })
    return route.fulfill({ json: [] })
  })
  return { requests, errors }
}
async function open(page: Page) {
  await page.goto('/management')
  await expect(page.getByRole('heading', { name: 'Управляющее пространство', exact: true })).toBeVisible()
}
async function shot(page: Page, name: string) {
  const dir = path.resolve('src/pages/management/qa/evidence')
  await mkdir(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, name), fullPage: true })
}

test('desktop: real route, navigation, partial/truncated, safe links and read-only GETs', async ({ page }) => {
  const { requests, errors } = await setup(page, { overview: async (route) => route.fulfill({ json: response({
    items: [item(), item({ id: 'unsafe', title: 'Тестовая небезопасная ссылка', href: 'javascript:alert(1)' })], sources: [source, remote], truncated: true,
  }) }) })
  await open(page)
  await expect(page.getByText('Часть источников недоступна', { exact: true })).toBeVisible()
  await expect(page.getByText('Показана часть результатов.', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toHaveAttribute('href', `/?company=${A}&chat=${CHAT}`)
  await expect(page.getByRole('link', { name: 'Тестовая небезопасная ссылка' })).toHaveCount(0)
  await expect(page.getByText('Только просмотр', { exact: true })).toBeVisible()
  await page.locator('summary').filter({ hasText: 'Источники:' }).click()
  await expect(page.getByText('Доступ не предоставлен', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('SECRET')
  await expect(page.locator('body')).not.toContainText('internal.test')
  await page.getByRole('button', { name: 'Профиль и настройки', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: /Обзор пространств/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-slot="dropdown-menu-content"]')).toHaveCount(0)
  expect(requests.filter((r) => r.path.startsWith('/api/management')).every((r) => r.method === 'GET' && r.company === A)).toBeTruthy()
  expect(errors).toEqual([])
  await shot(page, 'desktop.png')
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect.poll(() => requests.filter((r) => r.path.endsWith('/overview')).length).toBe(2)
})

test('search, source, kind, dates/time zone and company scope never reuse another company', async ({ page }) => {
  let releaseB: (() => void) | undefined
  const gateB = new Promise<void>((resolve) => { releaseB = resolve })
  const { requests, errors } = await setup(page, { overview: async (route, url) => {
    const company = route.request().headers()['x-company-id']
    if (company === B) { await gateB; return route.fulfill({ json: response({ items: [] }) }) }
    if (url.searchParams.get('kind') === 'tasks') return route.fulfill({ json: response({ items: [
      item({ id: 'task', kind: 'tasks', title: 'Тестовое поручение со сроком', status: 'open', due_at: '2026-10-25', href: `/docs/work?company=${A}&view=errands&task=${TASK}` }),
    ] }) })
    if (url.searchParams.get('kind') === 'calendar') return route.fulfill({ json: response({ items: [
      item({ id: 'meeting', kind: 'calendar', status: 'planned', title: 'Тестовая встреча после полуночи', starts_at: '2026-10-24T22:30:00Z', ends_at: '2026-10-24T23:00:00Z' }),
    ] }) })
    return route.fulfill({ json: response() })
  } })
  await open(page)
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toBeVisible()
  await page.getByLabel('Поиск', { exact: true }).fill('проверка & срок')
  await page.getByRole('button', { name: 'Найти', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.params.get('query')).toBe('проверка & срок')
  await page.getByRole('combobox', { name: 'Пространство', exact: true }).click()
  await page.getByRole('option', { name: source.name, exact: true }).click()
  await expect.poll(() => requests.filter((r) => r.path.endsWith('/overview')).at(-1)?.params.get('space')).toBe('local')
  await page.getByRole('tab', { name: 'Задачи', exact: true }).click()
  await expect(page.getByText('В работе', { exact: true })).toBeVisible()
  await expect(page.getByText(/^Срок: 25 окт/)).toBeVisible()
  await page.getByRole('tab', { name: 'Календарь', exact: true }).click()
  await expect(page.getByText(/Начало: 25 окт.*01:30/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Сроки', exact: true })).toHaveCount(0)
  await page.getByLabel('С даты', { exact: true }).fill('2026-10-25')
  await page.getByLabel('По дату включительно', { exact: true }).fill('2026-10-26')
  await expect.poll(() => requests.filter((r) => r.path.endsWith('/overview')).at(-1)?.params.get('date_to')).toBe('2026-10-26')
  const calendar = requests.filter((r) => r.path.endsWith('/overview')).at(-1)!
  expect(Object.fromEntries(calendar.params)).toMatchObject({ kind: 'calendar', space: 'local', query: 'проверка & срок', date_from: '2026-10-25', date_to: '2026-10-26', time_zone: 'Europe/Moscow', limit: '100' })
  await shot(page, 'calendar.png')
  await page.locator('header').getByRole('combobox').first().click()
  await page.getByRole('option', { name: companies[1].name, exact: true }).click()
  await expect(page.getByLabel('Поиск', { exact: true })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: 'Пространство', exact: true })).toContainText('Все доступные')
  await expect(page.getByText('Тестовая встреча после полуночи', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Получаем обзор…', { exact: true })).toBeVisible()
  const bReq = requests.filter((r) => r.path.endsWith('/overview') && r.company === B).at(-1)!
  expect(Object.fromEntries(bReq.params)).toMatchObject({ kind: 'chats', space: 'all', query: '', limit: '100' })
  releaseB!()
  await expect(page.getByRole('heading', { name: 'Записей не найдено', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('loading/error/retry, sanitized errors, empty and source configuration failure', async ({ page }) => {
  let count = 0
  let release: (() => void) | undefined
  const wait = new Promise<void>((resolve) => { release = resolve })
  const { errors } = await setup(page, { overview: async (route) => {
    count++
    if (count === 1) { await wait; return route.fulfill({ status: 502, json: { detail: 'SECRET http://internal.test?token=sensitive' } }) }
    return route.fulfill({ json: response({ items: [], sources: [{ ...remote, state: 'not_configured' }] }) })
  } })
  await open(page)
  await expect(page.getByText('Получаем обзор…', { exact: true })).toBeVisible()
  release!()
  await expect(page.getByRole('alert')).toContainText('Не удалось получить обзор')
  await expect(page.locator('body')).not.toContainText('SECRET')
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByText('Источники недоступны', { exact: true })).toBeVisible()
  await expect(page.getByText(`${remote.name}: Подключение не настроено`, { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'В доступной части обзора записей нет' })).toBeVisible()
  expect(errors).toEqual([])
})

test('disabled status hides menu and prevents overview requests; retry after status error', async ({ page }) => {
  const state: State = { statusError: 503 }
  const { requests } = await setup(page, state)
  await open(page)
  await expect(page.getByRole('heading', { name: 'Не удалось проверить доступность обзора' })).toBeVisible()
  await page.getByRole('button', { name: 'Профиль и настройки', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: /Обзор пространств/ })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-slot="dropdown-menu-content"]')).toHaveCount(0)
  state.statusError = undefined
  state.enabled = false
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Обзор отключён' })).toBeVisible()
  expect(requests.filter((r) => r.path.endsWith('/overview'))).toHaveLength(0)
})

test('mobile: no overflow, filters and normal navigation remain reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const { errors } = await setup(page)
  await open(page)
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, 'mobile.png')
  await page.getByRole('link', { name: 'Тестовый рабочий чат' }).scrollIntoViewIfNeeded()
  await expect(page.getByText('Синтетическая запись для проверки интерфейса', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Профиль и настройки', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: /Обзор пространств/ })).toBeVisible()
  await page.getByRole('menuitem', { name: /Обзор пространств/ }).click()
  await expect(page.getByRole('heading', { name: 'Управляющее пространство', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('deep links wait for membership, select company, open task and event; unknown company fails closed', async ({ page }) => {
  let release: (() => void) | undefined
  const meWait = new Promise<void>((resolve) => { release = resolve })
  const { requests, errors } = await setup(page, { meWait })
  await page.goto(`/docs/work?company=${B}&view=errands&task=${TASK}`)
  expect(requests.some((r) => r.path === `/api/tasks/${TASK}`)).toBe(false)
  release!()
  await expect(page.getByText('Тестовая задача оригинала', { exact: true }).first()).toBeVisible().catch((error) => {
    if (errors.length) throw new Error(errors.join('\n'))
    throw error
  })
  expect(requests.filter((r) => r.path === `/api/tasks/${TASK}`).every((r) => r.company === B && r.params.get('company_id') === B)).toBe(true)
  await page.goto(`/docs/work?company=${B}&view=calendar&event=${EVENT}`)
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('textbox').first()).toHaveValue('Тестовая встреча оригинала')
  expect(requests.filter((r) => r.path === `/api/work/calendar/${EVENT}`).every((r) => r.company === B)).toBe(true)
  await page.goto(`/docs/work?company=unknown&view=errands&task=${TASK}`)
  await expect(page.getByRole('heading', { name: 'Организация недоступна' })).toBeVisible()
  expect(errors).toEqual([])
})

test('backend root chat href opens the actual original room and homepage menu reaches management', async ({ page }) => {
  const { requests, errors } = await setup(page)
  await page.goto(`/?company=${B}&chat=${CHAT}`)
  await expect(page.getByText('Тестовый чат оригинала', { exact: true }).first()).toBeVisible()
  const roomRequests = requests.filter((r) => r.path === `/api/chat/rooms/${CHAT}`)
  expect(roomRequests.length).toBeGreaterThan(0)
  expect(roomRequests.every((r) => r.company === B)).toBe(true)
  await expect(page).not.toHaveURL(/company=|chat=/)
  // Возвращаемся на сам стол: общий пункт меню доступен и здесь на desktop.
  await page.goto('/')
  await page.getByRole('button', { name: 'Профиль и настройки', exact: true }).click()
  await page.getByRole('menuitem', { name: /Обзор пространств/ }).click()
  await expect(page.getByRole('heading', { name: 'Управляющее пространство', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('empty/config states, overview disabled and failed refresh keep clear recovery', async ({ page }) => {
  let mode: 'empty' | 'disabled' | 'error' | 'sources' = 'empty'
  await setup(page, { overview: async (route) => mode === 'error'
    ? route.fulfill({ status: 502, json: { detail: 'SECRET internal token=hidden' } })
    : route.fulfill({ json: response({ items: [], sources: mode === 'sources' ? [] : [source], enabled: mode !== 'disabled' }) }) })
  await open(page)
  await expect(page.getByRole('heading', { name: 'Записей не найдено', exact: true })).toBeVisible()
  mode = 'error'
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Не удалось получить обзор')
  await expect(page.getByText('Показан предыдущий ответ.', { exact: false })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('SECRET')
  mode = 'disabled'
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Обзор отключён', exact: true })).toBeVisible()
  mode = 'sources'
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Нет подключённых источников', exact: true })).toBeVisible()
})

for (const status of [403, 404]) test(`grant revoked (${status}): old content and links disappear, retry recovers`, async ({ page }) => {
  let revoked = false
  let calls = 0
  await setup(page, { overview: async (route) => {
    calls++
    return revoked ? route.fulfill({ status, json: { detail: 'SECRET revoked internal config' } })
      : route.fulfill({ json: response() })
  } })
  await open(page)
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toBeVisible()
  revoked = true
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('Тестовый рабочий чат', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('SECRET')
  expect(calls).toBe(2)
  revoked = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toBeVisible()
  expect(calls).toBe(3)
})

test('successful partial forbidden replaces earlier remote records without retaining old links', async ({ page }) => {
  let forbidden = false
  await setup(page, { overview: async (route) => route.fulfill({ json: response(forbidden ? {
    sources: [source, remote], items: [item()],
  } : {
    sources: [source, { ...remote, state: 'ok', error: null }],
    items: [item(), item({ id: 'remote-old', title: 'Тестовая отозванная запись', source: { code: 'remote', name: remote.name, company_id: B, company_name: companies[1].name } })],
  }) }) })
  await open(page)
  await expect(page.getByRole('link', { name: 'Тестовая отозванная запись' })).toBeVisible()
  forbidden = true
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(page.getByText('Часть источников недоступна', { exact: true })).toBeVisible()
  await expect(page.getByText('Тестовая отозванная запись', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toBeVisible()
})

test('partial transport error keeps healthy records; status disabled on refresh clears the snapshot', async ({ page }) => {
  const state: State = { overview: async (route) => route.fulfill({ json: response({ sources: [source, { ...remote, state: 'error' }] }) }) }
  const { requests, errors } = await setup(page, state)
  await open(page)
  await expect(page.getByText(`${remote.name}: Не удалось получить данные`, { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toBeVisible()
  state.enabled = false
  const count = requests.filter((r) => r.path.endsWith('/overview')).length
  await page.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Обзор отключён', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Тестовый рабочий чат' })).toHaveCount(0)
  expect(requests.filter((r) => r.path.endsWith('/overview'))).toHaveLength(count)
  expect(errors).toEqual([])
})
