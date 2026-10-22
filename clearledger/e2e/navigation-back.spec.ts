import { test, expect, type Page } from '@playwright/test'

// Browser plugin not available: обычный Playwright, только синтетические ответы API.
const searchPlaceholder = 'Номер, контрагент, станция (название, код, № БУ) или проект…'
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('clearledger-token', 'synthetic-navigation-test')
    sessionStorage.setItem('cl-booted', '1')
  })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/auth/me') data = {
      id: 'test-user', name: 'Проверка навигации', email: 'navigation@example.test',
      role: 'admin', is_superadmin: true,
      companies: ['first', 'second'].map((id) => ({
        id, slug: id, name: id === 'first' ? 'Тестовая компания' : 'Другая компания', profile_id: 'energy',
      })),
    }
    if (path === '/api/sso/apps' || path === '/api/registry/company-apps') data = { apps: [] }
    if (path === '/api/sso/apps/favorites') data = { codes: [] }
    if (path === '/api/books/counterparties') data = { rows: [] }
    if (path === '/api/references/counterparties') data = [
      { id: 'cp-1', name: 'Тестовый арендодатель', aliases: [], type: 'ЮЛ', companyId: 'first' },
    ]
    if (path === '/api/references/contracts') data = [
      { id: 'c-1', number: 'ДГ-42', type: 'Аренда', date: '2026-10-01', currency: 'RUB',
        counterpartyId: 'cp-1', organizationId: 'org-1', scopeType: 'company', raw: {} },
      { id: 'c-2', number: 'ДГ-43', type: 'Услуги', date: '2026-10-02', currency: 'RUB',
        counterpartyId: 'cp-1', organizationId: 'org-1', scopeType: 'company', raw: {} },
    ]
    if (path === '/api/references/contract-bindings') data = {
      contracts: { 'c-1': { apps: ['ops'], projects: [], linked: [] } }, projects: {}, locations: {},
    }
    await route.fulfill({ json: data })
  })
})

async function openSection(page: Page, path: string) {
  if ((page.viewportSize()?.width ?? 1440) < 768) {
    await page.getByRole('button', { name: 'Модули', exact: true }).click()
    const space = page.getByRole('button', { name: 'Пространство', exact: true })
    if (await space.getAttribute('aria-expanded') === 'false') await space.click()
  }
  await page.locator(`a[href$="${path}"]:visible`).first().click()
}

test('Назад и Вперёд восстанавливают поиск, отборы и группировку договоров', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  await page.goto('/contractors?sub=contracts')
  const search = page.getByPlaceholder(searchPlaceholder)
  await expect(search).toBeVisible()
  // В mobile-эмуляции Chromium посимвольный Unicode-ввод переставляет каретку
  // и с исходным useState. Здесь проверяется возврат, виртуальный ввод — fill.
  if ((page.viewportSize()?.width ?? 1440) < 768) await search.fill('ДГ-4')
  else await search.pressSequentially('ДГ-4')
  await expect(search).toBeFocused()
  await page.getByRole('button', { name: 'Аренда · 1', exact: true }).click()
  await page.getByRole('checkbox', { name: 'по контрагентам' }).uncheck()
  // Этот отбор делает REPLACE URL — прежний ввод должен пережить и его.
  await page.getByRole('combobox', { name: 'Приложение', exact: true }).selectOption('ops')
  await expect(search).toHaveValue('ДГ-4')
  const originalUrl = page.url()
  await expect(page.getByRole('button', { name: 'ДГ-42', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'ДГ-43', exact: true })).toHaveCount(0)
  await openSection(page, '/files')
  await expect(page).toHaveURL(/\/files/)
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page).toHaveURL(originalUrl)
  await expect(search).toHaveValue('ДГ-4')
  await expect(page.getByRole('combobox', { name: 'Приложение', exact: true })).toHaveValue('ops')
  await expect(page.getByRole('checkbox', { name: 'по контрагентам' })).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Аренда · 1', exact: true })).toHaveClass(/bg-primary/)
  await expect(page.getByRole('button', { name: 'ДГ-43', exact: true })).toHaveCount(0)
  await page.goForward()
  await expect(page).toHaveURL(/\/files/)
  await page.goBack()
  await expect(search).toHaveValue('ДГ-4')
  await expect(page.locator('vite-error-overlay')).toHaveCount(0)
  expect(errors).toEqual([])
  const back = page.getByRole('button', { name: 'Назад', exact: true })
  const bounds = await back.boundingBox()
  expect(bounds?.width).toBeGreaterThanOrEqual(44)
  expect(bounds?.height).toBeGreaterThanOrEqual(44)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if ((page.viewportSize()?.width ?? 1440) >= 1024) {
    const version = page.locator('header p').first()
    await expect(version).toBeVisible()
    expect(await version.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  }
  await test.info().attach('Возврат к отобранным договорам', {
    body: await page.screenshot(), contentType: 'image/png',
  })
})

test('прямой вход возвращает на рабочий стол, а не на внешний сайт', async ({ page }) => {
  await page.goto('/contractors?sub=contracts')
  await expect(page.getByPlaceholder(searchPlaceholder)).toBeVisible()
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page).toHaveURL(/^http:\/\/[^/]+\/(?:\?.*)?$/)
  await expect(page.getByPlaceholder(searchPlaceholder)).toHaveCount(0)
})

test('переключение компании сбрасывает поиск и историю предыдущей', async ({ page }) => {
  await page.goto('/contractors?sub=contracts')
  const search = page.getByPlaceholder(searchPlaceholder)
  await search.fill('ДГ-42')
  // На телефоне селектор организации находится в полосе под шапкой.
  await page.getByRole('combobox').filter({ hasText: 'Тестовая компания', visible: true }).click()
  await page.getByRole('option', { name: /Другая компания/ }).click()
  await expect(search).toHaveValue('')
  await expect(page.getByRole('button', { name: 'Назад', exact: true })).toHaveAttribute('title', 'На рабочий стол')
})

test('перезагрузка вкладки сохраняет поиск и тип договора', async ({ page }) => {
  await page.goto('/contractors?sub=contracts')
  const search = page.getByPlaceholder(searchPlaceholder)
  await search.fill('ДГ-42')
  await page.getByRole('button', { name: 'Аренда · 1', exact: true }).click()
  await page.reload()
  await expect(search).toHaveValue('ДГ-42')
  await expect(page.getByRole('button', { name: 'Аренда · 1', exact: true })).toHaveClass(/bg-primary/)
})

test('закреплённый вид сохраняет собственный поиск', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'Полоса закреплённых вкладок есть только на desktop')
  await page.goto('/contractors?sub=contracts')
  const search = page.getByPlaceholder(searchPlaceholder).filter({ visible: true })
  await search.fill('ДГ-42')
  await page.getByRole('button', { name: 'Закрепить экран', exact: true }).click()
  await expect(page.getByRole('tab')).toHaveCount(2)
  await page.getByRole('combobox', { name: 'Приложение', exact: true }).selectOption('ops')
  // Новый вид уже показан: кнопка закрепления снова доступна. До этого
  // React может оставлять на экране прежний закреплённый экземпляр.
  await expect(page.getByRole('button', { name: 'Закрепить экран', exact: true })).toBeEnabled()
  await search.fill('ДГ-43')
  await page.getByRole('tab').nth(1).click()
  await expect(search).toHaveValue('ДГ-42')
})
