import { expect, test } from '@playwright/test'

test('общепит: рабочее место сети на desktop и mobile', async ({ page }) => {
  await page.goto('/demo/shop')
  await page.getByRole('button', { name: 'Скрыть уведомление о демонстрационном контуре' }).click()
  await page.getByRole('button', { name: 'Общепит', exact: true }).click()
  await page.getByRole('button', { name: 'Меню и экономика', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'Общепит', exact: true })).toBeVisible()
  await expect(page.getByText('Фактическая экономика', { exact: true })).toBeVisible()
  await expect(page.getByText(/Задачи не создаются/)).toBeVisible()
  await expect(page.getByText('Станции и недели', { exact: true })).toBeVisible()
  await expect(page.getByText('Наблюдаемая связь с топливом', { exact: true })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'АЗС 101' }).first().locator('td').first()).toContainText('Точно')
  await expect(page.locator('body')).not.toContainText('NaN')
  await expect(page.locator('body')).not.toContainText('undefined')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'artifacts/catering-network-desktop.png', fullPage: true })

  const dishRow = page.getByRole('row', { name: 'Кофе американо 300 мл — состав и продажи' })
  await expect(dishRow.locator('td').first()).toContainText('Точно')
  await dishRow.click()
  await expect(page.getByRole('dialog')).toContainText('Состав ТТК')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()

  await page.setViewportSize({ width: 390, height: 844 })
  const economy = page.getByText('Фактическая экономика', { exact: true })
  await economy.scrollIntoViewIfNeeded()
  await expect(economy).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'artifacts/catering-network-mobile.png' })
  await page.getByText('Меню', { exact: true }).last().scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'artifacts/catering-network-mobile-menu.png' })
})
