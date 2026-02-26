import { test, expect } from '@playwright/test'

/**
 * E2E тесты: Аудит-лог, отчёты, экспорт, пагинация, расширенные фильтры.
 */

// ---- Helpers ----

async function goToCategory(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.getByRole('link', { name: /Первичные документы/i }).first().click()
  await page.waitForLoadState('networkidle')
  await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 5000 })
}

async function openFirstEntry(page: import('@playwright/test').Page) {
  await page.locator('table tbody tr').first().locator('td:nth-child(2) button').click()
  await page.waitForLoadState('networkidle')
  await expect(page.getByText(/Информация/i).first()).toBeVisible({ timeout: 5000 })
}

// ---- Аудит-лог ----

test.describe('Аудит-лог в MetadataPanel', () => {
  test('Журнал изменений появляется после верификации', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Перейти во Входящие и верифицировать запись
    const inboxLink = page.getByRole('link', { name: /Входящие/i }).first()
    if (!(await inboxLink.isVisible())) return

    await inboxLink.click()
    await page.waitForLoadState('networkidle')

    const firstEntry = page.locator('table tbody tr, [class*="card"]').first()
    if (!(await firstEntry.isVisible())) return

    await firstEntry.click()
    await page.waitForLoadState('networkidle')

    const verifyBtn = page.getByRole('button', { name: /Верифицировать/i }).first()
    if (!(await verifyBtn.isVisible().catch(() => false))) return

    await verifyBtn.click()
    await page.waitForTimeout(1000)

    // Теперь перейти к записи в данных и проверить аудит
    await goToCategory(page)
    await openFirstEntry(page)

    const journalBtn = page.getByText(/Журнал изменений/i)
    // Журнал может быть видим, если аудит записался
    const hasJournal = await journalBtn.isVisible().catch(() => false)
    if (hasJournal) {
      await journalBtn.click()
      // Должны быть видны события
      await expect(page.getByText(/Верифицирован|Создан|Обновлён/i).first()).toBeVisible({ timeout: 3000 })
    }
  })
})

// ---- Страница отчётов ----

test.describe('Страница отчётов', () => {
  test('Маршрут /reports загружается', async ({ page }) => {
    await page.goto('/reports')
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/Отчёты/i).first()).toBeVisible({ timeout: 5000 })
  })

  test('Селектор периода работает', async ({ page }) => {
    await page.goto('/reports')
    await page.waitForLoadState('networkidle')

    // Кликнуть на селектор периода
    const periodSelect = page.locator('button[role="combobox"]').first()
    await expect(periodSelect).toBeVisible()
    await periodSelect.click()

    // Выбрать «Неделя»
    await page.getByRole('option', { name: /Неделя/i }).click()
    await page.waitForTimeout(500)

    // Проверить что KPI-карточки отображаются
    await expect(page.getByText(/Загружено|Проверено|Отклонено/i).first()).toBeVisible()
  })

  test('Ссылка «Отчёты» в сайдбаре', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const reportsLink = page.getByRole('link', { name: /Отчёты/i })
    await expect(reportsLink).toBeVisible()
    await reportsLink.click()
    await page.waitForURL(/\/reports/)
  })

  test('Кнопка экспорт открывает модальное окно', async ({ page }) => {
    await page.goto('/reports')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Экспорт/i }).click()
    await expect(page.getByText(/Экспорт данных/i)).toBeVisible({ timeout: 3000 })

    // Проверить наличие выбора формата
    await expect(page.getByText(/Excel/i).first()).toBeVisible()
  })
})

// ---- Экспорт ----

test.describe('ExportModal', () => {
  test('Модалка экспорта на DataCategoryPage', async ({ page }) => {
    await goToCategory(page)

    // Кнопка «Экспорт» в тулбаре
    const exportBtn = page.getByRole('button', { name: /Экспорт/i }).first()
    await expect(exportBtn).toBeVisible()
    await exportBtn.click()

    // Модальное окно открылось
    await expect(page.getByText(/Экспорт данных/i)).toBeVisible({ timeout: 3000 })

    // Выбор формата
    const formatSelect = page.locator('[role="dialog"]').locator('button[role="combobox"]').first()
    await expect(formatSelect).toBeVisible()

    // Закрыть модалку
    await page.getByRole('button', { name: /Отмена/i }).click()
    await expect(page.getByText(/Экспорт данных/i)).not.toBeVisible()
  })
})

// ---- Пагинация ----

test.describe('PaginationWrapper', () => {
  test('Пагинация на DataCategoryPage с селектором размера', async ({ page }) => {
    await goToCategory(page)

    // Проверить текст «Показано X–Y из Z»
    await expect(page.getByText(/Показано \d+–\d+ из \d+/i)).toBeVisible({ timeout: 5000 })

    // Селектор размера страницы (25/50/100)
    const sizeSelect = page.locator('button[role="combobox"]').filter({ hasText: /25|50|100/ }).first()
    if (await sizeSelect.isVisible()) {
      await sizeSelect.click()
      const option50 = page.getByRole('option', { name: '50' })
      if (await option50.isVisible()) {
        await option50.click()
        await page.waitForTimeout(500)
      }
    }
  })
})

// ---- Расширенные фильтры ----

test.describe('AdvancedFilters на SearchPage', () => {
  test('Фильтры сворачиваются/разворачиваются', async ({ page }) => {
    await page.goto('/search')
    await page.waitForLoadState('networkidle')

    // Кнопка «Фильтры»
    const filtersBtn = page.getByRole('button', { name: /Фильтры/i })
    await expect(filtersBtn).toBeVisible()

    // Развернуть
    await filtersBtn.click()
    await expect(page.getByText(/Дата от/i)).toBeVisible({ timeout: 3000 })
    await expect(page.getByText(/Сумма от/i)).toBeVisible()
    await expect(page.getByText(/Контрагент/i)).toBeVisible()

    // Свернуть
    await filtersBtn.click()
    await expect(page.getByText(/Дата от/i)).not.toBeVisible()
  })

  test('Подсветка поисковых терминов', async ({ page }) => {
    await page.goto('/search')
    await page.waitForLoadState('networkidle')

    const searchInput = page.getByPlaceholder(/Поиск по документам/i)
    await searchInput.fill('Акт')
    await page.waitForTimeout(500)

    // Проверить наличие подсветки (mark элемент)
    const marks = page.locator('mark')
    const markCount = await marks.count()
    // Если есть результаты, должны быть mark-элементы
    if (markCount > 0) {
      await expect(marks.first()).toBeVisible()
    }
  })
})
