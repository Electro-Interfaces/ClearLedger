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

  test('Незавершённый диапазон не применяется', async ({ page }) => {
    await ready(page)
    await page.getByRole('button', { name: /^Период:/ }).click()

    // Один клик по дате = выбрано только начало. Раньше это схлопывало период
    // в один день; теперь подтверждение недоступно, пока нет второй границы.
    // Ищем строго внутри поповера: на фоне есть таблицы данных с числами.
    const popover = page.locator('[data-radix-popper-content-wrapper]')
    await expect(popover).toBeVisible({ timeout: 10_000 })
    const day = popover.locator('button', { hasText: /^15$/ }).first()
    await expect(day).toBeVisible({ timeout: 10_000 })
    await day.click()

    await expect(page.getByText('Укажите конец периода')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('button', { name: /^(Применить|Готово)$/ })).toBeDisabled()
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
