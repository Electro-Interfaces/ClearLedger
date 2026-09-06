import { expect, test, type Page } from '@playwright/test'

const coreApps = [
  ['Чаты', /\/messages$/, /INC-2471 · АЗС Лесная|Сеть АЗС/],
  ['Трек', /\/docs$/, /INC-2471|Акт первичной диагностики/],
  ['Управление', /\/admin\//, /Полюс Ритейл|demo-operator/],
  ['Подключения', /\/connect$/, /Шлюзы сети АЗС|АЗС Лесная/],
  ['Данные', /\/data$/, /АЗС Лесная|INC-2471|Шлюзы сети АЗС/],
  ['Инфо', /\/info$/, /Как устроено рабочее пространство/],
] as const

async function openDemo(page: Page) {
  await page.goto('./')
  await expect(page.getByText('ООО «Полюс Ритейл»')).toBeVisible()
  await expect(page.getByText('Демонстрационный контур.')).toBeVisible()
  const later = page.getByRole('button', { name: 'Позже' })
  if (await later.isVisible().catch(() => false)) await later.click()
}

test('ядро открывается, приложения остаются отключёнными', async ({ page }) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const externalRequests: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) externalRequests.push(request.url())
  })

  await openDemo(page)
  await expect(page.getByRole('button', { name: /Монитор Отдельное демо/ })).toBeDisabled()
  await expect(page.getByRole('button', { name: /Интернет-магазин Отдельное демо/ })).toBeDisabled()
  await expect(page.getByRole('button', { name: /Чаты Открыть здесь/ })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Аудитор' })).toHaveCount(0)

  await page.setViewportSize({ width: 1000, height: 900 })
  const services = page.getByRole('region', { name: 'Сервисы экосистемы: приложения' })
  const before = await services.evaluate((node) => node.scrollLeft)
  const box = await services.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x + Math.min(420, box!.width - 40), box!.y + box!.height / 2)
  await page.mouse.down()
  await page.mouse.move(box!.x + 80, box!.y + box!.height / 2, { steps: 8 })
  await page.mouse.up()
  await expect.poll(() => services.evaluate((node) => node.scrollLeft)).toBeGreaterThan(before)

  for (const [name, route, story] of coreApps) {
    await openDemo(page)
    await page.getByRole('button', { name: new RegExp(`${name} Открыть здесь`) }).click()
    await expect.poll(() => new URL(page.url()).pathname).toMatch(route)
    await expect(page.getByText('Демонстрационный контур.')).toBeVisible()
    await expect(page.getByText(story).filter({ visible: true }).first()).toBeVisible()
    await expect(page.getByText(/Демо-данные для .* пока не заданы/)).toHaveCount(0)
  }

  await openDemo(page)
  await page.getByRole('button', { name: /Конференции Открыть здесь/ }).click()
  await expect(page.getByText(/Гостевая ссылка скопирована|Конференция создана/)).toBeVisible()
  await expect(page).toHaveURL(/\/demo(?:\?|$)/)

  expect(externalRequests).toEqual([])
  expect(pageErrors).toEqual([])
  expect(consoleErrors).toEqual([])
})

test('светлая и тёмная темы, ширина 390 px', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('gig-fuel-settings', JSON.stringify({ theme: 'light' }))
  })
  await openDemo(page)
  await page.getByRole('button', { name: 'Профиль и настройки' }).click()
  await page.getByText('Тёмная тема').click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.keyboard.press('Escape')
  await page.screenshot({ path: 'artifacts/demo-polus-dark.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByText('Демонстрационный контур.')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await expect(page.getByRole('button', { name: /Монитор Отдельное демо/ })).toBeDisabled()
  await page.screenshot({ path: 'artifacts/demo-polus-mobile.png', fullPage: true })
})

test('закрытые окна взаимодействия загружаются только после открытия', async ({ page }) => {
  await openDemo(page)
  const loadedScripts = () => page.evaluate(() => performance.getEntriesByType('resource')
    .map((entry) => entry.name))

  await expect.poll(async () => (await loadedScripts()).some((url) => url.includes('/ChatPanel-')))
    .toBeFalsy()
  await expect.poll(async () => (await loadedScripts()).some((url) => url.includes('/AuditorPanel-')))
    .toBeFalsy()

  await page.getByTitle('Чаты пространства').click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText('INC-2471 · АЗС Лесная').filter({ visible: true }).first()).toBeVisible()
  await expect.poll(async () => (await loadedScripts()).some((url) => url.includes('/ChatPanel-')))
    .toBeTruthy()
})
