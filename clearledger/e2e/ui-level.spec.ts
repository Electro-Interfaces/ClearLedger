import { test, expect } from '@playwright/test'

/**
 * Режим работы «Простой / Расширенный».
 *
 * Главное, что здесь проверяется, — не сам факт скрытия, а его правила:
 * скрытое обозначено, переключение обратимо, а критичное для корректности
 * видно всегда (см. useUiLevel, правило 1).
 */

/**
 * networkidle здесь не годится: в приложении живут поллинг и фоновые запросы,
 * сеть не затихает и ожидание упирается в таймаут. Ждём разметку и конкретный
 * признак применённого режима.
 */
async function setLevel(page: import('@playwright/test').Page, level: 'simple' | 'advanced') {
  await page.evaluate((l) => localStorage.setItem('clearledger-ui-level', l), level)
  await page.reload({ waitUntil: 'domcontentloaded' })
  const html = page.locator('html')
  if (level === 'simple') await expect(html).toHaveClass(/cl-simple/, { timeout: 15_000 })
  else await expect(html).not.toHaveClass(/cl-simple/, { timeout: 15_000 })
}

test.describe('Режим работы', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('./')
    await page.waitForLoadState('domcontentloaded')
  })

  test('По умолчанию — простой режим', async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem('clearledger-ui-level'))
    await page.reload()
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('html')).toHaveClass(/cl-simple/)
  })

  test('Переключатель доступен из шапки', async ({ page }) => {
    // Главное требование к месту: режим меняется в один клик с любого экрана,
    // без похода в настройки.
    await setLevel(page, 'simple')
    const btn = page.getByRole('button', { name: 'Простой режим включён' })
    await expect(btn).toBeVisible({ timeout: 15_000 })

    await btn.click()
    await expect(page.getByRole('button', { name: 'Расширенный режим включён' })).toBeVisible()
    await expect(page.locator('html')).not.toHaveClass(/cl-simple/)

    // И обратно — тем же кликом.
    await page.getByRole('button', { name: 'Расширенный режим включён' }).click()
    await expect(page.locator('html')).toHaveClass(/cl-simple/)
  })

  test('Простой режим убирает редкую настройку, но помечает её', async ({ page }) => {
    await setLevel(page, 'simple')
    const openFilters = page.getByRole('button', { name: /Настроить фильтры/ })
    await expect(openFilters).toBeVisible({ timeout: 15_000 })
    await openFilters.click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    // Редкая секция убрана...
    await expect(dialog.getByText('Источник онлайн-данных STS', { exact: true })).toBeHidden()
    // ...но человек видит, что она существует — скрытие не тихое.
    await expect(dialog.getByText(/Ещё 1 .* в расширенном режиме/)).toBeVisible()
  })

  test('Ежедневный контур в простом режиме не прячется', async ({ page }) => {
    await setLevel(page, 'simple')
    const openFilters = page.getByRole('button', { name: /Настроить фильтры/ })
    await expect(openFilters).toBeVisible({ timeout: 15_000 })
    await openFilters.click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    // Период и область учёта — то, чем пользуются каждый день. Прятать нельзя.
    await expect(dialog.getByText('Период', { exact: false }).first()).toBeVisible()
    await expect(dialog.getByText('Область учёта', { exact: false }).first()).toBeVisible()
  })

  test('Загрузка: служебные параметры убраны, дата документа остаётся', async ({ page }) => {
    await setLevel(page, 'simple')
    await page.goto('intake')
    await page.waitForLoadState('domcontentloaded')

    // Канал / тип / точка имеют безопасные умолчания — убраны.
    await expect(page.getByText('Точка обслуживания')).toBeHidden()
    await expect(page.getByText(/Ещё 3 параметра/)).toBeVisible({ timeout: 10_000 })

    // А дата остаётся: её умолчание — сегодня, и для документа с нераспознанной
    // датой скрытое поле молча проставило бы неверный период.
    await expect(page.getByText('Дата документа').first()).toBeVisible()
  })

  test('Расширенный режим открывает всё', async ({ page }) => {
    await setLevel(page, 'advanced')
    await expect(page.locator('html')).not.toHaveClass(/cl-simple/)

    const openFilters = page.getByRole('button', { name: /Настроить фильтры/ })
    await expect(openFilters).toBeVisible({ timeout: 15_000 })
    await openFilters.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog.getByText('Источник онлайн-данных STS', { exact: true })).toBeVisible()
  })

  test('Переключение из подсказки работает и обратимо', async ({ page }) => {
    await setLevel(page, 'simple')
    const openFilters = page.getByRole('button', { name: /Настроить фильтры/ })
    await expect(openFilters).toBeVisible({ timeout: 15_000 })
    await openFilters.click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    // «Включить» прямо из подсказки — без похода в настройки.
    await dialog.getByRole('button', { name: 'Включить' }).click()
    await expect(dialog.getByText('Источник онлайн-данных STS', { exact: true })).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('html')).not.toHaveClass(/cl-simple/)
  })
})
