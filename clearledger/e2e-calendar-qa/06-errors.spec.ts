import { expect, test } from '@playwright/test'
import { authFile, апи, имя, календарь, кто, снимок, токен, пространства } from './helpers'

/**
 * Отказы источников. Пользователю важно другое, чем разработчику: что
 * случилось, что уже загружено и как повторить. Ответы подменяются на уровне
 * сети — сам продукт не меняется.
 */
test.use({ storageState: authFile('qa-cal-energy', 'organizer') })
test.describe.configure({ mode: 'serial' })

const ДЕНЬ = '2026-11-10'

test('E-01 отказ загрузки встреч объяснён и повторяется по кнопке', async ({ page }) => {
  let падать = true
  await page.route('**/api/work/calendar?**', async (route) => {
    if (падать) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"сервис недоступен"}' })
    return route.fallback()
  })
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  const тревога = page.getByRole('alert').filter({ hasText: 'встречи' })
  await expect(тревога).toBeVisible()
  await expect(тревога).toContainText('Не удалось загрузить встречи')
  await снимок(page, 'e01-load-error.png')
  падать = false
  await тревога.getByRole('button', { name: 'Повторить' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'встречи' })).toHaveCount(0)
})

test('E-02 при отказе обновления прежние данные остаются с пояснением', async ({ page, request }) => {
  // Своя встреча в дне: проверка не должна зависеть от следов других сценариев
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const r = await апи(request, t, '/api/work/calendar', {
    method: 'POST',
    data: {
      company_id: пространства['qa-cal-energy'].companyId, title: имя('остаются'),
      starts_at: `${ДЕНЬ}T06:00:00Z`, ends_at: `${ДЕНЬ}T07:00:00Z`, visibility: 'private',
    },
  })
  expect(r.status(), await r.text()).toBe(201)
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  // Дождались данных, после чего источник ломается
  await expect(page.getByRole('alert').filter({ hasText: 'встречи' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /QA-CAL-20261025/ }).first()).toBeVisible()
  const было = await page.getByRole('button', { name: /QA-CAL-20261025/ }).count()
  expect(было, 'в дне есть встречи').toBeGreaterThan(0)

  await page.route('**/api/work/calendar?**', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"сервис недоступен"}' }))
  await page.getByRole('button', { name: 'Обновить календарь' }).click()
  const тревога = page.getByRole('alert').filter({ hasText: 'встречи' })
  await expect(тревога).toContainText('Показаны ранее полученные данные')
  expect(await page.getByRole('button', { name: /QA-CAL-20261025/ }).count(),
    'уже загруженные встречи не исчезли').toBe(было)
  await снимок(page, 'e02-stale.png')
})

test('E-03 встреча по несуществующей ссылке объяснена и закрывается', async ({ page }) => {
  await page.goto(календарь({
    calendarMode: 'day', date: ДЕНЬ, event: '00000000-0000-4000-8000-000000000000',
  }))
  const тревога = page.getByRole('alert').filter({ hasText: 'Не удалось открыть встречу' })
  await expect(тревога).toBeVisible()
  await тревога.getByRole('button', { name: 'Закрыть' }).click()
  await expect(page).not.toHaveURL(/event=/)
})

test('E-04 отказ занятости не выдаётся за свободное время', async ({ page }) => {
  await page.route('**/api/work/calendar/busy**', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"нет данных"}' }))
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Встреча' }).click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel('О чём').fill('QA-CAL-20261025 занятость')
  const участник = кто('qa-cal-energy', 'required')
  await окно.getByLabel('Найти участника').fill(участник.name)
  await окно.getByLabel(участник.name, { exact: false }).first().check()
  await окно.getByRole('button', { name: 'Подобрать' }).click()
  await expect(окно.getByRole('alert')).toContainText(/Не удалось проверить занятость/)
  await снимок(page, 'e04-busy-error.png')
})

test('E-05 усечённый список встреч обозначен явно', async ({ page }) => {
  await page.route('**/api/work/calendar?**', async (route) => {
    const ответ = await route.fetch()
    const данные = await ответ.json()
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...данные, truncated: true, total: (данные.total ?? 0) + 500 }),
    })
  })
  await page.goto(календарь({ calendarMode: 'month', date: ДЕНЬ }))
  await expect(page.getByText('В периоде слишком много записей', { exact: false })).toBeVisible()
  await снимок(page, 'e05-truncated.png')
})
