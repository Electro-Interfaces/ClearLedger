import { test, expect } from '@playwright/test'

/**
 * Smoke-приёмка рабочей области и результатов волн UX (0-4).
 *
 * Старые спеки (lifecycle/validation/versioning/audit-reports-export) написаны
 * под навигацию «Первичные документы», которой в интерфейсе больше нет —
 * они ждут переписывания. Этот набор проверяет то, что есть сейчас:
 * иерархию управления (CLAUDE.md, «Иерархия управления рабочей области»)
 * и ключевые правки волн.
 */

test.describe('Рабочая область', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('./')
    await page.waitForLoadState('networkidle')
  })

  test('Старт приложения — рабочий стол, а не список документов', async ({ page }) => {
    // Волна 0: холодный старт уводит на рабочий стол.
    await expect(page.getByText('Рабочий стол').first()).toBeVisible({ timeout: 15_000 })
  })

  test('Главный сайдбар свёрнут по умолчанию', async ({ page }) => {
    // Волна 0: развёрнутый сайдбар показывал бы текстовые подписи пунктов.
    // Свёрнутый — только иконки, поэтому подписи навигации не видны.
    const expanded = page.getByRole('navigation').getByText('Настройки', { exact: true })
    await expect(expanded).toBeHidden()
  })

  test('Уровень 2: чипы фильтра рабочей области видны', async ({ page }) => {
    // Двухслойный фильтр: на Слое 0 — период, область учёта, типы данных.
    await expect(page.getByText('ПЕРИОД').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('ОБЛАСТЬ УЧЁТА').first()).toBeVisible()
    await expect(page.getByText('ДАННЫЕ').first()).toBeVisible()
  })

  test('Глубина фильтра открывается по «Фильтры» и закрывается', async ({ page }) => {
    // Слой 1 не должен быть развёрнут заранее — только по явному действию.
    // Имя берётся из aria-label кнопки (текст «Фильтры» скрыт на узких экранах).
    const btn = page.getByRole('button', { name: /Настроить фильтры/ })
    await expect(btn).toBeVisible({ timeout: 15_000 })

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeHidden()

    await btn.click()
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    // И сворачивается обратно — раскрытие обратимо.
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden({ timeout: 10_000 })
  })

  test('Разделы рабочей области доступны', async ({ page }) => {
    for (const name of ['Продажи', 'Магазин', 'Управленческий', 'Бухгалтерский', 'Выгрузка']) {
      await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 15_000 })
    }
  })
})
