import { test, expect } from '@playwright/test'

/**
 * E2E тесты: Жизненный цикл документов (архив, исключение, восстановление).
 */

// Хелпер: перейти в категорию и дождаться таблицы
async function goToCategory(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.getByRole('link', { name: /Первичные документы/i }).first().click()
  await page.waitForLoadState('networkidle')
  await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 5000 })
}

// Хелпер: кликнуть по названию первой записи (2-я ячейка) для перехода на detail page
async function clickFirstEntry(page: import('@playwright/test').Page) {
  await page.locator('table tbody tr').first().locator('td:nth-child(2) button').click()
  await page.waitForLoadState('networkidle')
  // Ждём появления MetadataPanel
  await expect(page.getByText(/Информация/i).first()).toBeVisible({ timeout: 5000 })
}

test.describe('Жизненный цикл документов', () => {
  test('Архивирование и восстановление записи', async ({ page }) => {
    await goToCategory(page)
    const rowsBefore = await page.locator('table tbody tr').count()
    expect(rowsBefore).toBeGreaterThan(0)

    // Переходим на detail page
    await clickFirstEntry(page)

    // Нажимаем «В архив»
    const archiveBtn = page.getByRole('button', { name: /В архив/i }).first()
    await expect(archiveBtn).toBeVisible({ timeout: 3000 })
    await archiveBtn.click()

    // Подтверждаем в диалоге
    await page.locator('[role="alertdialog"]').getByRole('button', { name: /В архив/i }).click()
    await page.waitForTimeout(500)

    // Должно перенаправить на список (navigate в handleArchive)
    await expect(page.locator('table')).toBeVisible({ timeout: 5000 })

    // Записей стало меньше
    const rowsAfter = await page.locator('table tbody tr').count()
    expect(rowsAfter).toBeLessThan(rowsBefore)

    // Включаем «Показать архив»
    await page.getByLabel(/Показать архив/i).check()
    await page.waitForTimeout(500)

    // Записей снова столько же или больше
    const rowsWithArchive = await page.locator('table tbody tr').count()
    expect(rowsWithArchive).toBeGreaterThanOrEqual(rowsBefore)
  })

  test('Исключение из анализа и возврат', async ({ page }) => {
    await goToCategory(page)
    await clickFirstEntry(page)

    // Нажимаем «Исключить из анализа»
    const excludeBtn = page.getByRole('button', { name: /Исключить из анализа/i })
    await expect(excludeBtn).toBeVisible({ timeout: 3000 })
    await excludeBtn.click()
    await page.waitForTimeout(500)

    // Должна появиться жёлтая плашка
    await expect(page.getByText(/Исключён из анализа/i)).toBeVisible()

    // Нажимаем «Вернуть в анализ»
    await page.getByRole('button', { name: /Вернуть в анализ/i }).click()
    await page.waitForTimeout(500)

    // Плашка исчезла
    await expect(page.getByText(/Исключён из анализа/i)).not.toBeVisible()
  })

  test('Массовый архив через BulkActionsBar', async ({ page }) => {
    await goToCategory(page)

    const rows = page.locator('table tbody tr')
    const count = await rows.count()
    if (count < 2) return

    // Выбираем первые 2 записи чекбоксами
    for (let i = 0; i < 2; i++) {
      await rows.nth(i).locator('[role="checkbox"]').first().click()
    }

    // Должна появиться панель массовых действий
    await expect(page.getByText(/Выбрано: 2/i)).toBeVisible()

    // Нажимаем «В архив» в BulkActionsBar
    const bulkArchive = page.locator('.sticky').getByRole('button', { name: /В архив/i })
    await expect(bulkArchive).toBeVisible()
    await bulkArchive.click()

    // Подтверждаем
    await page.locator('[role="alertdialog"]').getByRole('button', { name: /В архив/i }).click()
    await page.waitForTimeout(500)
  })
})
