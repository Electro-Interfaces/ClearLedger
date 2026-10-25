import { expect, type Page, type APIRequestContext } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

export const QA = '/srv/projects/qa-calendar-20261025/.qa'
export const API = 'http://127.0.0.1:8311'

type Учётка = {
  id: string; name: string; email: string; password: string; companyRole: string
}
type Пространство = {
  companyId: string; companyName: string; profile: string; prefix: string
  users: Record<string, Учётка>
}

export const пространства: Record<string, Пространство> =
  JSON.parse(readFileSync(resolve(QA, 'accounts.json'), 'utf8'))

export const кто = (пространство: string, роль: string) =>
  пространства[пространство].users[роль]

export const authFile = (пространство: string, роль: string) =>
  resolve(QA, '.auth', `${пространство}-${роль}.json`)

/**
 * Вход обычной формой: тот же путь, которым входит человек.
 *
 * Оговорка оснастки: у `/api/auth/login` стоит лимит 10 запросов в минуту на
 * адрес (`server/app/rate_limit.py`). Серия подготовительных входов в него
 * упирается, поэтому при отказе ждём окно и пробуем ещё раз. Это свойство
 * стенда, а не проверка продукта: отказы самого входа проверяются отдельно.
 */
export async function войти(page: Page, пространство: string, роль: string) {
  const u = кто(пространство, роль)
  await page.goto('./')
  await page.locator('#email').fill(u.email)
  await page.locator('#password').fill(u.password)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.locator('#email')).toHaveCount(0, { timeout: 30_000 })
}

/**
 * Токен для прямых HTTP-проверок ожиданий, которые не видны в интерфейсе.
 *
 * С кешем: вход ограничен 10 запросами в минуту на адрес, а один прогон
 * обращается к ролям десятки раз. Берём сохранённую сессию, пока она жива.
 */
const _токены = new Map<string, string>()
export async function токен(request: APIRequestContext, пространство: string, роль: string) {
  const ключ = `${пространство}/${роль}`
  const сохранённый = _токены.get(ключ) ?? прочитатьТокен(пространство, роль)
  if (сохранённый) {
    const r = await request.get(`${API}/api/auth/me`, {
      headers: { Authorization: `Bearer ${сохранённый}` },
    })
    if (r.ok()) { _токены.set(ключ, сохранённый); return сохранённый }
  }
  const u = кто(пространство, роль)
  const r = await request.post(`${API}/api/auth/login`, {
    data: { email: u.email, password: u.password },
  })
  expect(r.ok(), `вход ${u.email}: ${r.status()}`).toBeTruthy()
  const t = (await r.json()).access_token as string
  _токены.set(ключ, t)
  return t
}

function прочитатьТокен(пространство: string, роль: string): string | null {
  try {
    const файл = JSON.parse(readFileSync(authFile(пространство, роль), 'utf8'))
    return файл.origins?.[0]?.localStorage?.[0]?.value ?? null
  } catch { return null }
}

export async function апи(
  request: APIRequestContext, token: string, путь: string,
  init: { method?: string; data?: unknown } = {},
) {
  const r = await request.fetch(`${API}${путь}`, {
    method: init.method ?? 'GET',
    headers: { Authorization: `Bearer ${token}` },
    ...(init.data ? { data: init.data } : {}),
  })
  return r
}

export const календарь = (параметры: Record<string, string> = {}) => {
  const qs = new URLSearchParams({ view: 'calendar', ...параметры })
  return `./docs/work?${qs.toString()}`
}

/** Уникальное название: боевые данные тут не используются, но следы отличимы. */
export const имя = (что: string) =>
  `QA-CAL-20261025 ${что} ${Math.random().toString(36).slice(2, 7)}`

export const снимок = (page: Page, файл: string) =>
  page.screenshot({ path: resolve(QA, 'artifacts/shots', файл), fullPage: false })
