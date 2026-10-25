import { test as setup, expect } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { API, authFile, кто, токен, QA, пространства } from './helpers'

/**
 * Сессии для проверок. Берутся тем же эндпоинтом входа, что и у человека, но из
 * HTTP-клиента и с кешем: у `/api/auth/login` лимит 10 запросов в минуту на
 * адрес (`server/app/rate_limit.py`), а в кросс-origin стенде каждый вход
 * браузера расходует две единицы (preflight OPTIONS + POST). Путь человека
 * через форму проверяется сценарием `02-roles.spec.ts` отдельно.
 */
const СЕССИИ: [string, string][] = [
  ['qa-cal-energy', 'organizer'],
  ['qa-cal-energy', 'required'],
  ['qa-cal-energy', 'optional'],
  ['qa-cal-energy', 'colleague'],
  ['qa-cal-fuel', 'organizer'],
  ['qa-cal-office', 'organizer'],
  ['qa-cal-outside', 'outsider'],
]

setup('сессии ролей', async ({ request }) => {
  mkdirSync(resolve(QA, '.auth'), { recursive: true })
  for (const [пространство, роль] of СЕССИИ) {
    const файл = authFile(пространство, роль)
    if (existsSync(файл)) {
      const сохранено = JSON.parse(readFileSync(файл, 'utf8'))
      const t = сохранено.origins?.[0]?.localStorage?.[0]?.value
      if (t) {
        const r = await request.get(`${API}/api/auth/me`, {
          headers: { Authorization: `Bearer ${t}` },
        })
        if (r.ok()) continue      // действующая сессия — вход не расходуем
      }
    }
    const t = await токен(request, пространство, роль)
    writeFileSync(файл, JSON.stringify({
      cookies: [],
      origins: [{
        origin: 'http://127.0.0.1:8312',
        localStorage: [{ name: 'clearledger-token', value: t }],
      }],
    }, null, 2))
  }
})

setup('состав стенда', async () => {
  expect(Object.keys(пространства)).toHaveLength(4)
  expect(кто('qa-cal-energy', 'organizer').companyRole).toBe('admin')
})
