import { expect, test, type Page } from '@playwright/test'

const fixture = '/e2e/ops-closing/payment-fixture.html'
const file = { name: 'synthetic.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('synthetic transport fixture') }
const summary = { periods: [], total_paid: 0, total_capital: 0, source: null }
const errors = new WeakMap<Page, string[]>()

test.beforeEach(({ page }) => {
  const values: string[] = []
  errors.set(page, values)
  page.on('pageerror', (error) => values.push(error.message))
})
test.afterEach(async ({ page }) => {
  await expect(page).toHaveURL(/\/payment-fixture\.html$/)
  await expect(page.locator('vite-error-overlay')).toHaveCount(0)
  expect(errors.get(page)).toEqual([])
})

async function reads(page: Page, seen: string[] = []) {
  await page.route('**/api/ops/payments**', async (route) => {
    if (route.request().method() !== 'GET') { await route.fallback(); return }
    const url = new URL(route.request().url())
    seen.push(url.pathname + '?' + url.searchParams.get('company_id'))
    await route.fulfill({ json: url.pathname.endsWith('/coverage')
      ? { numbers_total: 0, numbers_linked: 0, hint: 'synthetic' }
      : url.pathname.endsWith('/counterparties') ? { rows: [] } : summary })
  })
}

test('matching diagnostics render safely with a usable details control', async ({ page }, info) => {
  await reads(page)
  await page.route('**/api/ops/payments/upload?**', (route) => route.fulfill({ json: {
    saved: 4, batch_id: 'synthetic', counterparties_matched: 1, unknown_items: [],
    counterparties_ambiguous: 2, counterparties_unmatched: 1, counterparties_retained: 1,
    identity_issues: [{ external_key: 'one', counterparty_name: 'ООО <img src=x onerror=alert(1)>', status: 'ambiguous' },
      { external_key: 'two', counterparty_name: 'ООО Прежняя связь', status: 'existing_link_retained' }], identity_issues_truncated: true,
  } }))
  await page.goto(fixture)
  await page.getByLabel('Файл выгрузки списаний').setInputFiles(file)
  await expect(page.getByRole('status')).toContainText('Требуют сверки: 2')
  await expect(page.getByRole('status')).toContainText('Сохранены прежние связи: 1')
  await page.getByText('Проверить сопоставление', { exact: true }).click()
  await expect(page.getByRole('status')).toContainText('ООО <img src=x onerror=alert(1)>: несколько кандидатов')
  await expect(page.locator('img[onerror]')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `/tmp/api-payment-qa-${info.project.name}.png`, fullPage: true })
})

test('a late upload cannot show results or refresh data in the next company', async ({ page }) => {
  const seen: string[] = []
  await reads(page, seen)
  let release!: () => void
  const wait = new Promise<void>((resolve) => { release = resolve })
  let requested!: () => void
  const started = new Promise<void>((resolve) => { requested = resolve })
  await page.route('**/api/ops/payments/upload?**', async (route) => {
    requested(); await wait
    await route.fulfill({ json: { saved: 99, batch_id: 'old-company', counterparties_matched: 99, unknown_items: [] } })
  })
  await page.goto(fixture)
  await page.getByLabel('Файл выгрузки списаний').setInputFiles(file)
  await started
  await page.getByRole('button', { name: 'Компания Б', exact: true }).click()
  await expect(page.getByLabel('Файл выгрузки списаний')).toBeAttached()
  const before = seen.filter((item) => item.endsWith('?qa-b')).length
  expect(before).toBe(3)
  release()
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect.poll(() => seen.filter((item) => item.endsWith('?qa-b')).length).toBe(before)
})

test('an older response and a failed upload remain understandable', async ({ page }) => {
  await reads(page)
  let requests = 0
  await page.route('**/api/ops/payments/upload?**', (route) => {
    requests++
    return requests === 1 ? route.fulfill({ status: 400, json: { detail: 'Проверьте структуру файла' } })
      : route.fulfill({ json: { saved: 2, batch_id: 'old-backend', counterparties_matched: 1, unknown_items: [] } })
  })
  await page.goto(fixture)
  await page.getByLabel('Файл выгрузки списаний').setInputFiles(file)
  await expect(page.getByText('Проверьте структуру файла')).toBeVisible()
  await page.getByLabel('Файл выгрузки списаний').setInputFiles(file)
  await expect(page.getByRole('status')).toContainText('сопоставлено: 1')
  await expect(page.getByRole('status')).not.toContainText('однозначно')
  await expect(page.getByRole('status')).not.toContainText('undefined')
})
