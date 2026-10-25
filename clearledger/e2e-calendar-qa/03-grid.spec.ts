import { expect, test } from '@playwright/test'
import { authFile, апи, имя, календарь, снимок, токен, пространства } from './helpers'

/**
 * Почасовая сетка: ночная встреча, пересечения по ширине и «Ещё N» в месяце.
 * Проверяется то, что человек видит глазами, а не только расчёт раскладки
 * (его отдельно покрывают юнит-тесты calendarLayout).
 */
test.use({ storageState: authFile('qa-cal-energy', 'organizer') })
test.describe.configure({ mode: 'serial' })

const company = пространства['qa-cal-energy'].companyId

async function собрать(request, название: string, начало: string, конец: string) {
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const r = await апи(request, t, '/api/work/calendar', {
    method: 'POST',
    data: { company_id: company, title: название, starts_at: начало, ends_at: конец, visibility: 'private' },
  })
  expect(r.status(), await r.text()).toBe(201)
  return (await r.json()).id as string
}

test('G-01 встреча через полночь показана в обоих днях, второй день — продолжение',
  async ({ page, request }) => {
    const название = имя('ночная')
    // 20:00 → 01:00 по Москве
    await собрать(request, название, '2026-11-16T17:00:00Z', '2026-11-16T22:00:00Z')
    await page.goto(календарь({ calendarMode: 'week', date: '2026-11-16' }))
    await expect(page.getByRole('button', { name: `${название}, 16 ноября` })).toBeVisible()
    await expect(page.getByRole('button', { name: `${название}, 17 ноября, продолжение` })).toBeVisible()
    await снимок(page, 'g01-midnight.png')
  })

test('G-02 ширину делят только действительно пересекающиеся встречи', async ({ page, request }) => {
  const первая = имя('пересечение-A')
  const вторая = имя('пересечение-B')
  const отдельная = имя('отдельная-C')
  await собрать(request, первая, '2026-11-18T07:00:00Z', '2026-11-18T08:00:00Z')    // 10:00–11:00
  await собрать(request, вторая, '2026-11-18T07:30:00Z', '2026-11-18T08:30:00Z')    // 10:30–11:30
  await собрать(request, отдельная, '2026-11-18T10:00:00Z', '2026-11-18T11:00:00Z') // 13:00–14:00
  await page.goto(календарь({ calendarMode: 'day', date: '2026-11-18' }))

  const a = await page.getByRole('button', { name: `${первая}, 18 ноября` }).boundingBox()
  const b = await page.getByRole('button', { name: `${вторая}, 18 ноября` }).boundingBox()
  const c = await page.getByRole('button', { name: `${отдельная}, 18 ноября` }).boundingBox()
  expect(a && b && c).toBeTruthy()
  // Две пересекающиеся занимают по половине ширины и не накрывают друг друга
  expect(Math.abs(a!.width - b!.width)).toBeLessThan(4)
  expect(a!.width).toBeLessThan(c!.width * 0.6)
  expect(a!.x + a!.width).toBeLessThanOrEqual(b!.x + 2)
  // Непересекающаяся занимает всю ширину дня
  expect(c!.width).toBeGreaterThan(a!.width * 1.7)
  await снимок(page, 'g02-overlap.png')
})

test('G-03 в месяце день с четырьмя записями предлагает «Ещё» и открывает список',
  async ({ page, request }) => {
    for (const i of [1, 2, 3, 4]) {
      const час = String(5 + i).padStart(2, '0')
      const конец = String(6 + i).padStart(2, '0')
      await собрать(request, имя(`плотный день ${i}`),
        `2026-11-19T${час}:00:00Z`, `2026-11-19T${конец}:00:00Z`)
    }
    await page.goto(календарь({ calendarMode: 'month', date: '2026-11-19' }))
    const ещё = page.getByRole('button', { name: /^Ещё \d+$/ })
    await expect(ещё.first()).toBeVisible()
    await ещё.first().click()
    await expect(page).toHaveURL(/calendarMode=agenda/)
    await снимок(page, 'g03-more.png')
  })
