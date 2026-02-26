import { test, expect } from '@playwright/test'

/**
 * E2E тесты: Версионность документов.
 */

async function goToCategoryAndOpenEntry(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.getByRole('link', { name: /Первичные документы/i }).first().click()
  await page.waitForLoadState('networkidle')
  await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 5000 })
  // Кликаем по названию (2-я ячейка) для перехода на detail page
  await page.locator('table tbody tr').first().locator('td:nth-child(2) button').click()
  await page.waitForLoadState('networkidle')
  // Ждём появления MetadataPanel
  await expect(page.getByText(/Информация/i).first()).toBeVisible({ timeout: 5000 })
}

test.describe('Версионность документов', () => {
  test('Кнопка «Новая версия» видна на DataDetailPage', async ({ page }) => {
    await goToCategoryAndOpenEntry(page)
    await expect(page.getByText('Новая версия')).toBeVisible({ timeout: 5000 })
  })

  test('Кнопка «Новая версия» ведёт на IntakePage с параметром', async ({ page }) => {
    await goToCategoryAndOpenEntry(page)

    // Кликаем «Новая версия»
    await page.getByText('Новая версия').click()
    await page.waitForURL(/newVersionOf=/, { timeout: 10000 })

    // Должна открыться IntakePage с заголовком «Загрузка новой версии»
    await expect(page.getByText(/Загрузка новой версии/i)).toBeVisible({ timeout: 5000 })

    // URL содержит newVersionOf
    expect(page.url()).toContain('newVersionOf=')

    // Информационная плашка видна
    await expect(page.getByText(/предыдущая версия будет помечена как устаревшая/i)).toBeVisible()
  })

  test('Чекбокс «Показать все версии» в DataCategoryPage', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    await page.getByRole('link', { name: /Первичные документы/i }).first().click()
    await page.waitForLoadState('networkidle')

    const checkbox = page.getByLabel(/Показать все версии/i)
    await expect(checkbox).toBeVisible()
  })
})
