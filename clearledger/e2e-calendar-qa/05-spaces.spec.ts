import { expect, test } from '@playwright/test'
import { authFile, апи, имя, календарь, снимок, токен, пространства } from './helpers'

/**
 * Календарь в разных пространствах. Профиль компании (energy, fuel, office)
 * меняет состав приложений, но «Трек» подключён всем трём профилям
 * (ecosystem-deploy/apps/docs.yml), значит и календарь должен работать
 * одинаково. Отдельно проверяется, что пространства не видят друг друга.
 */
test.describe.configure({ mode: 'serial' })
const ДЕНЬ = '2026-11-26'

for (const [пространство, профиль] of [
  ['qa-cal-energy', 'energy'], ['qa-cal-fuel', 'fuel'], ['qa-cal-office', 'office'],
] as const) {
  test.describe(`пространство ${профиль}`, () => {
    test.use({ storageState: authFile(пространство, 'organizer') })

    test(`S-${профиль} календарь работает: назначение, показ, поиск`, async ({ page, request }) => {
      const company = пространства[пространство].companyId
      const название = имя(`${профиль}`)
      await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
      await expect(page.getByRole('heading', { name: 'Календарь' })).toBeVisible()

      await page.getByRole('button', { name: 'Добавить', exact: true }).click()
      await page.getByRole('menuitem', { name: 'Встреча' }).click()
      const окно = page.getByRole('dialog')
      await окно.getByLabel('О чём').fill(название)
      await окно.getByRole('button', { name: 'Собрать' }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()

      await page.getByLabel('Найти в календаре').fill(название.slice(-8))
      await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()
      await снимок(page, `s-${профиль}.png`)

      const t = await токен(request, пространство, 'organizer')
      const r = await апи(request, t,
        `/api/work/calendar?company_id=${company}&from=${ДЕНЬ}T00:00:00Z&to=2026-11-27T00:00:00Z&scope=mine`)
      expect(r.ok()).toBeTruthy()
      expect((await r.json()).events.some((e) => e.title === название)).toBeTruthy()
    })
  })
}

test.describe('изоляция пространств', () => {
  test.use({ storageState: authFile('qa-cal-fuel', 'organizer') })

  test('S-изоляция календарь чужого пространства недоступен', async ({ page, request }) => {
    const свой = await токен(request, 'qa-cal-fuel', 'organizer')
    const чужая = пространства['qa-cal-energy'].companyId
    const r = await апи(request, свой,
      `/api/work/calendar?company_id=${чужая}&from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z&scope=company`)
    expect(r.status(), 'календарь другой компании закрыт').toBeGreaterThanOrEqual(400)

    // В интерфейсе человек видит только своё пространство
    await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
    await expect(page.getByText(пространства['qa-cal-fuel'].companyName).first()).toBeVisible()
    await expect(page.getByText(пространства['qa-cal-energy'].companyName)).toHaveCount(0)
  })
})
