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
  // Без reload: режим реактивный (как при клике по кнопке в шапке), а
  // перезагрузка на этом стенде теряет сессию и выбрасывает на экран входа.
  await page.evaluate((l) => {
    localStorage.setItem('clearledger-ui-level', l)
    document.documentElement.classList.toggle('cl-simple', l === 'simple')
    window.dispatchEvent(new Event('cl-uilevel-change'))
  }, level)
  const html = page.locator('html')
  if (level === 'simple') await expect(html).toHaveClass(/cl-simple/, { timeout: 15_000 })
  else await expect(html).not.toHaveClass(/cl-simple/, { timeout: 15_000 })
}

test.describe('Режим работы', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('./')
    await page.waitForLoadState('domcontentloaded')
    // Готовность приложения, а не только разметки: следующая навигация в тесте
    // иначе стартует посреди проверки сессии и попадает на /login.
    await expect(page.getByRole('button', { name: /режим включён/i })).toBeVisible({ timeout: 20_000 })
  })

  test('По умолчанию — простой режим', async ({ page }) => {
    // Проверяется поведение при пустом хранилище — единственный тест, которому
    // нужен реальный старт приложения.
    await page.evaluate(() => localStorage.removeItem('clearledger-ui-level'))
    await page.goto('./')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('html')).toHaveClass(/cl-simple/, { timeout: 15_000 })
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

  test('Эффект виден прямо на рабочем столе', async ({ page }) => {
    // Раньше переключатель выглядел мёртвым: на главном экране скрывать было
    // нечего, и клик не давал видимого отклика.
    await setLevel(page, 'simple')
    await expect(page.getByText('Источник STS')).toBeHidden()

    await setLevel(page, 'advanced')
    await expect(page.getByText('Источник STS')).toBeVisible({ timeout: 15_000 })
  })

  test('Ежедневный контур на рабочем столе не прячется', async ({ page }) => {
    // Период и область учёта — то, чем пользуются каждый день, и то, чем
    // подписаны цифры на экране. В простом режиме они обязаны остаться.
    await setLevel(page, 'simple')
    await expect(page.getByRole('button', { name: /^Период:/ })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Область учёта')).toBeVisible()
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
    // Режим ставится ДО загрузки страницы: так проверяется и то, что он
    // применяется на старте, а не только при клике.
    await page.addInitScript(() => localStorage.setItem('clearledger-ui-level', 'simple'))
    await page.goto('intake')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('html')).toHaveClass(/cl-simple/, { timeout: 15_000 })

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
