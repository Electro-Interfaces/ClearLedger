import { test, expect } from '@playwright/test'

/**
 * Окна выбора периода и области учёта — модель диалога 1С:
 * набрал в черновике → подтвердил кнопкой. До подтверждения контур не меняется.
 *
 * Проверяются ровно те дефекты, на которые указал МАГ:
 * — клик по параметру закрывал окно, хотя нужно выбрать ещё что-то;
 * — период «слетал»: первый клик по дате схлопывал интервал в один день.
 */

async function ready(page: import('@playwright/test').Page) {
  await page.goto('./')
  await page.waitForLoadState('domcontentloaded')
  await expect(page.getByRole('button', { name: /режим включён/i })).toBeVisible({ timeout: 20_000 })
}

test.describe('Выбор периода', () => {
  test('Пресет не закрывает окно и не меняет контур до подтверждения', async ({ page }) => {
    await ready(page)
    const chip = page.getByRole('button', { name: /^Период:/ })
    const before = (await chip.textContent())?.trim()

    await chip.click()
    await page.getByRole('button', { name: 'Прошлый квартал' }).click()

    // Окно осталось открытым — можно поправить границы.
    await expect(page.getByRole('button', { name: /^(Применить|Готово)$/ })).toBeVisible()
    // Контур не тронут: таблицы под окном не перезапрашивались.
    expect((await chip.textContent())?.trim()).toBe(before)
  })

  test('Применение переносит выбор в контур', async ({ page }) => {
    await ready(page)
    const chip = page.getByRole('button', { name: /^Период:/ })
    const before = (await chip.textContent())?.trim()

    await chip.click()
    await page.getByRole('button', { name: 'Прошлый квартал' }).click()
    await page.getByRole('button', { name: /^(Применить|Готово)$/ }).click()

    await expect(chip).not.toHaveText(before ?? '', { timeout: 10_000 })
  })

  test('Отмена оставляет период прежним', async ({ page }) => {
    await ready(page)
    const chip = page.getByRole('button', { name: /^Период:/ })
    const before = (await chip.textContent())?.trim()

    await chip.click()
    await page.getByRole('button', { name: 'Весь год' }).click()
    await page.getByRole('button', { name: 'Отмена' }).click()

    await page.waitForTimeout(400)
    expect((await chip.textContent())?.trim()).toBe(before)
  })

  test('Календарь на русском и показывает выбранный период', async ({ page }) => {
    await ready(page)
    await page.getByRole('button', { name: /^Период:/ }).click()

    const popover = page.locator('[data-radix-popper-content-wrapper]')
    await expect(popover).toBeVisible({ timeout: 10_000 })

    // Дни недели по-русски и неделя начинается с понедельника.
    await expect(popover.getByText('пн', { exact: true }).first()).toBeVisible()
    await expect(popover.getByText('Su', { exact: true })).toHaveCount(0)

    // Пресет перематывает календарь к началу периода: раньше можно было
    // набрать «1–23 июня» и смотреть при этом на июль с августом.
    // Проверяем по полю «Начало» — заголовок месяца живёт в скрытом <select>
    // (react-day-picker держит его для доступности), видимую подпись рисует сам.
    await page.getByRole('button', { name: 'Прошлый квартал' }).click()
    const from = popover.locator('input[type="date"]').first()
    await expect(from).toHaveValue(/-04-01$/, { timeout: 10_000 })
  })

  test('Клик по дате правит границу, а не сбрасывает период', async ({ page }) => {
    await ready(page)
    await page.getByRole('button', { name: /^Период:/ }).click()

    // Главный дефект, на который указал МАГ: раньше первый клик схлопывал
    // интервал в один день ({from: X, to: X}), и выбор «слетал». Теперь
    // диапазон отдаётся календарю как есть — клик двигает границу, а период
    // остаётся периодом.
    const popover = page.locator('[data-radix-popper-content-wrapper]')
    await expect(popover).toBeVisible({ timeout: 10_000 })

    const days = popover.locator('button').filter({ hasText: /^\d{1,2}$/ })
    await expect(days.first()).toBeVisible({ timeout: 10_000 })
    await days.nth(10).click()

    // В подвале — по-прежнему интервал из двух дат, а не «одна дата».
    const selected = popover.getByText(/\d{1,2} \S+ – \d{1,2} \S+ \d{4}/)
    await expect(selected).toBeVisible({ timeout: 10_000 })
  })
})

test.describe('Область учёта', () => {
  test('Выбор точки не закрывает окно', async ({ page }) => {
    await ready(page)
    await page.getByRole('button', { name: /Область учёта/i }).first().click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    const boxes = dialog.getByRole('checkbox')
    await expect(boxes.first()).toBeVisible({ timeout: 15_000 })
    await boxes.first().click()

    // Окно остаётся открытым — можно отметить ещё, — а изменение видно как
    // непринятое: появилась кнопка «Применить».
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: /Применить/ })).toBeVisible()
  })

  test('Отмена не переносит выбор в контур', async ({ page }) => {
    await ready(page)
    const chip = page.getByRole('button', { name: /Область учёта/i }).first()
    const before = (await chip.textContent())?.trim()

    await chip.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    const boxes = dialog.getByRole('checkbox')
    await expect(boxes.first()).toBeVisible({ timeout: 15_000 })
    await boxes.first().click()
    await dialog.getByRole('button', { name: 'Отмена' }).click()

    await page.waitForTimeout(500)
    expect((await chip.textContent())?.trim()).toBe(before)
  })
})
