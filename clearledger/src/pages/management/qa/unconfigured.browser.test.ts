import { test, expect } from '@playwright/test'

test('missing API configuration shows an explicit unavailable state without synthetic records', async ({ page }) => {
  test.skip(!process.env.MANAGEMENT_QA_UNCONFIGURED_URL, 'Нужен второй dev server без VITE_API_URL')
  const managementRequests: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
    sessionStorage.setItem('cl-booted', '1')
  })
  await page.route('**/api/**', (route) => {
    if (route.request().url().includes('/api/management/')) managementRequests.push(route.request().url())
    return route.fulfill({ json: [] })
  })
  await page.goto(`${process.env.MANAGEMENT_QA_UNCONFIGURED_URL}/management`)
  await expect(page.getByRole('heading', { name: 'Обзор не подключён', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Обновить', exact: true })).toBeDisabled()
  await expect(page.locator('section[aria-labelledby="management-title"] a')).toHaveCount(0)
  expect(managementRequests).toEqual([])
})
