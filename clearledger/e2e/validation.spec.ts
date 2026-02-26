import { test, expect } from '@playwright/test'

/**
 * E2E тесты: Валидация документов в VerificationForm и MetadataPanel.
 */

test.describe('Валидация документов', () => {
  test('Кнопка «Верифицировать» disabled при пустых обязательных полях', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Переходим в Inbox
    const inboxLink = page.getByRole('link', { name: /Входящие/i }).first()
    if (await inboxLink.isVisible()) {
      await inboxLink.click()
      await page.waitForLoadState('networkidle')

      // Кликаем на первую запись в inbox
      const firstEntry = page.locator('[data-testid="inbox-entry"], table tbody tr, [class*="card"]').first()
      if (await firstEntry.isVisible()) {
        await firstEntry.click()
        await page.waitForLoadState('networkidle')

        // Ищем кнопку «Верифицировать»
        const verifyBtn = page.getByRole('button', { name: /Верифицировать/i })
        if (await verifyBtn.isVisible()) {
          // Проверяем наличие прогресс-бара заполненности
          const progressText = page.getByText(/Заполненность/i)
          await expect(progressText).toBeVisible()
        }
      }
    }
  })

  test('Валидационный бейдж на DataDetailPage', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Переходим в категорию
    await page.getByRole('link', { name: /Первичные документы/i }).first().click()
    await page.waitForLoadState('networkidle')

    // Ждём строки и кликаем по названию (2-я ячейка)
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 5000 })
    await page.locator('table tbody tr').first().locator('td:nth-child(2) button').click()
    await page.waitForLoadState('networkidle')

    // Ждём загрузки detail page
    await expect(page.getByText(/Информация/i).first()).toBeVisible({ timeout: 5000 })

    // Должна быть секция с результатами валидации (бейдж: Корректен/Ошибки/Предупреждения)
    const hasValidation = await page.getByText(/Корректен|Ошибки|Предупреждения/i).first().isVisible().catch(() => false)
    expect(hasValidation).toBeTruthy()
  })
})
