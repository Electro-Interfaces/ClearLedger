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
    await page.waitForLoadState('domcontentloaded')
    // Дождаться готовности приложения, а не только разметки: иначе следующая
    // навигация в тесте стартует посреди проверки сессии и попадает на /login.
    await expect(page.getByRole('button', { name: /режим включён/i })).toBeVisible({ timeout: 20_000 })
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
    // По aria-label, а не по видимому тексту: подписи чипов меняются при
    // перекомпоновке тулбара, смысл — нет. Чип «Данные» снят вместе с
    // заглушками в 613d26b, поэтому здесь его больше нет.
    await expect(page.getByRole('button', { name: /^Период:/ })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Область учёта').first()).toBeVisible()
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

  test('Прямая ссылка на служебную страницу переживает холодный старт', async ({ page }) => {
    // Сброс на рабочий стол должен касаться только экранов рабочей области.
    // Раньше он подменял ЛЮБОЙ путь, ломая ссылки из писем и открытие в новой
    // вкладке (там sessionStorage всегда пуст → любой переход «холодный»).
    // Метка снимается ДО загрузки — иначе это не холодный старт, а второй
    // переход в уже прогретом приложении (и гонка с проверкой сессии).
    await page.addInitScript(() => sessionStorage.removeItem('cl-booted'))
    await page.goto('settings')
    await page.waitForLoadState('domcontentloaded')

    // ?f=... дописывает URL-персист фильтра — на путь это не влияет.
    await expect(page).toHaveURL(/\/settings(\?|$)/)
    await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible({ timeout: 10_000 })
  })

  test('Разделы рабочей области доступны', async ({ page }) => {
    for (const name of ['Продажи', 'Магазин', 'Управленческий', 'Бухгалтерский', 'Выгрузка']) {
      await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 15_000 })
    }
  })
})
