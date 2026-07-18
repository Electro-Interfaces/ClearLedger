import { test, expect, type Page } from '@playwright/test'

/**
 * Сквозная проверка: контур доходит до цифр.
 *
 * Остальные наборы проверяют ПОВЕДЕНИЕ окон фильтра (черновик, подтверждение,
 * отмена). Здесь — то, ради чего фильтр существует: после «Применить» данные
 * действительно пересчитываются, и на экране ровно то, что отдаёт API за этот
 * период. Без такой проверки можно было бы «починить» окна и не заметить, что
 * выбор никуда не доходит.
 */

const API = 'http://localhost:8000'

/** Выручка за период прямо из API — источник истины для сверки с экраном. */
async function revenueFromApi(page: Page, from: string, to: string): Promise<number> {
  const token = await page.evaluate(() => localStorage.getItem('clearledger-token'))
  const companyId = await page.evaluate(() => localStorage.getItem('clearledger-company'))
  const res = await page.request.get(`${API}/api/fuel/shift-dashboard`, {
    params: { date_from: from, date_to: to },
    headers: {
      Authorization: `Bearer ${token}`,
      ...(companyId ? { 'X-Company-Id': companyId.replace(/"/g, '') } : {}),
    },
  })
  expect(res.ok(), `API вернул ${res.status()}`).toBeTruthy()
  const data = await res.json()
  return Number(data?.totals?.revenue ?? data?.kpi?.revenue ?? 0)
}

/**
 * Текст плитки KPI: «Выручка 95.21 млн ₽ продажи топлива».
 *
 * Подписи ищем по DOM-тексту («Выручка»), а не по видимому («ВЫРУЧКА») —
 * заглавные делает CSS text-transform, и getByText о нём не знает.
 */
async function kpiText(page: Page, label: string): Promise<string> {
  const caption = page.getByText(label, { exact: true }).first()
  await expect(caption).toBeVisible({ timeout: 20_000 })
  const card = caption.locator('xpath=..')
  return (await card.innerText()).replace(/\s+/g, ' ').trim()
}

async function ready(page: Page) {
  await page.goto('./')
  await page.waitForLoadState('domcontentloaded')
  await expect(page.getByRole('button', { name: /режим включён/i })).toBeVisible({ timeout: 20_000 })
}

/** Ставит период через окно чипа и подтверждает. */
async function applyPeriod(page: Page, preset: string) {
  await page.getByRole('button', { name: /^Период:/ }).click()
  await page.getByRole('button', { name: preset }).click()
  await page.getByRole('button', { name: /^(Применить|Готово)$/ }).click()
  await page.waitForTimeout(1500)  // перезапрос данных под окном
}

test.describe('Контур доходит до цифр', () => {
  test('Смена периода пересчитывает дашборд', async ({ page }) => {
    test.setTimeout(120_000)
    await ready(page)

    const before = await kpiText(page, 'Выручка')
    await applyPeriod(page, 'Прошлый квартал')
    const after = await kpiText(page, 'Выручка')

    // Главное: цифра не «залипла» на прежнем периоде.
    expect(after).not.toBe(before)
  })

  test('Число на экране совпадает с API за тот же период', async ({ page }) => {
    test.setTimeout(120_000)
    await ready(page)

    // Контур лежит в localStorage под ключом gig-filters-{companyId}
    // (FilterContext.storageKey) — ищем по префиксу, id компании нам не важен.
    const period = await page.evaluate(() => {
      const key = Object.keys(localStorage).find((k) => k.startsWith('gig-filters-'))
      const raw = key ? localStorage.getItem(key) : null
      return raw ? JSON.parse(raw) : null
    })
    const from = period?.period?.from
    const to = period?.period?.to
    test.skip(!from || !to, 'Период не найден в localStorage — нечего сверять')

    const apiRevenue = await revenueFromApi(page, from, to)
    test.skip(apiRevenue === 0, 'За период нет выручки — сверять нечего')

    // На экране выручка в млн: «95.21 млн ₽». Сверяем с точностью до 1%,
    // чтобы округление в UI не роняло проверку.
    const shown = await kpiText(page, 'Выручка')
    const millions = Number((shown.match(/([\d.,]+)\s*млн/)?.[1] ?? '0').replace(',', '.'))
    expect(millions, `на экране «${shown}», в API ${apiRevenue}`).toBeGreaterThan(0)
    expect(Math.abs(millions * 1e6 - apiRevenue) / apiRevenue).toBeLessThan(0.01)
  })

  test('Сужение области учёта уменьшает выборку', async ({ page }) => {
    test.setTimeout(120_000)
    await ready(page)

    const before = await kpiText(page, 'АЗС (с продажами)')

    // Оставляем одну точку — счётчик АЗС обязан отреагировать.
    await page.getByRole('button', { name: /Область учёта/i }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    const boxes = dialog.getByRole('checkbox')
    await expect(boxes.first()).toBeVisible({ timeout: 15_000 })
    await boxes.first().click()
    await dialog.getByRole('button', { name: /Применить/ }).click()
    await page.waitForTimeout(1800)

    const after = await kpiText(page, 'АЗС (с продажами)')
    expect(after).not.toBe(before)
  })
})
