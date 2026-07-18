import { test, expect } from '@playwright/test'

/**
 * Режим работы «Простой / Расширенный».
 *
 * Главное, что здесь проверяется, — не сам факт скрытия, а его правила:
 * скрытое обозначено, переключение обратимо, а критичное для корректности
 * видно всегда (см. useUiLevel, правило 1).
 */

async function setLevel(page: import('@playwright/test').Page, level: 'simple' | 'advanced') {
  await page.evaluate((l) => localStorage.setItem('clearledger-ui-level', l), level)
  await page.reload()
  await page.waitForLoadState('networkidle')
}

test.describe('Режим работы', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('./')
    await page.waitForLoadState('networkidle')
  })

  test('По умолчанию — простой режим', async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem('clearledger-ui-level'))
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('html')).toHaveClass(/cl-simple/)
  })

  test('Простой режим убирает редкую настройку, но помечает её', async ({ page }) => {
    await setLevel(page, 'simple')
    await page.getByRole('button', { name: /Настроить фильтры/ }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    // Редкая секция убрана...
    await expect(dialog.getByText('Источник онлайн-данных STS', { exact: true })).toBeHidden()
    // ...но человек видит, что она существует — скрытие не тихое.
    await expect(dialog.getByText(/Ещё 1 .* в расширенном режиме/)).toBeVisible()
  })

  test('Ежедневный контур в простом режиме не прячется', async ({ page }) => {
    await setLevel(page, 'simple')
    await page.getByRole('button', { name: /Настроить фильтры/ }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    // Период и область учёта — то, чем пользуются каждый день. Прятать нельзя.
    await expect(dialog.getByText('Период', { exact: false }).first()).toBeVisible()
    await expect(dialog.getByText('Область учёта', { exact: false }).first()).toBeVisible()
  })

  test('Расширенный режим открывает всё', async ({ page }) => {
    await setLevel(page, 'advanced')
    await expect(page.locator('html')).not.toHaveClass(/cl-simple/)

    await page.getByRole('button', { name: /Настроить фильтры/ }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog.getByText('Источник онлайн-данных STS', { exact: true })).toBeVisible()
  })

  test('Переключение из подсказки работает и обратимо', async ({ page }) => {
    await setLevel(page, 'simple')
    await page.getByRole('button', { name: /Настроить фильтры/ }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    // «Включить» прямо из подсказки — без похода в настройки.
    await dialog.getByRole('button', { name: 'Включить' }).click()
    await expect(dialog.getByText('Источник онлайн-данных STS', { exact: true })).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('html')).not.toHaveClass(/cl-simple/)
  })
})
