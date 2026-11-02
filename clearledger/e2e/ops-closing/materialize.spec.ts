import { test, expect, type Page } from '@playwright/test'

type Write = { company: string; period: string; method: string; body: string | null }

async function scenario(page: Page, options: { hold?: Promise<void>; fail?: boolean; closed?: boolean } = {}) {
  const reads = new Map<string, number>()
  const prepared = new Set<string>()
  const writes: Write[] = []
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.route('**/api/ops/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const company = url.searchParams.get('company_id')!
    const period = url.searchParams.get('period')!
    const key = `${company}:${period}`
    if (url.pathname.endsWith('/materialize')) {
      const targetPeriod = decodeURIComponent(url.pathname.split('/').at(-2)!)
      writes.push({ company, period: targetPeriod, method: request.method(), body: request.postData() })
      if (options.hold) await options.hold
      if (options.fail) return route.fulfill({ status: 503, json: { detail: 'Синтетическая ошибка подготовки' } })
      prepared.add(`${company}:${targetPeriod}`)
      return route.fulfill({ json: { period: targetPeriod, created: 1, updated: 0, skipped: 0, blocked: [] } })
    }
    expect(request.method()).toBe('GET')
    if (url.pathname.endsWith('/periods')) {
      expect(url.searchParams.get('expand_all')).toBe('false')
      return route.fulfill({ json: { periods: [], avgDocPct: null, worst: [] } })
    }
    if (url.pathname.endsWith('/calendar')) return route.fulfill({ json: { buckets: [], today: '2026-10-01', horizonDays: 45 } })
    expect(url.pathname).toBe('/api/ops/closing')
    reads.set(key, (reads.get(key) ?? 0) + 1)
    const ready = prepared.has(key) || options.closed
    const charges = ready ? [{ id: `${company}-charge`, costItem: 'rent', costItemLabel: 'Аренда',
      locationId: company, locationName: `Учебная ЭЗС ${company}`, counterpartyName: 'Учебный поставщик',
      seq: 0, expectedGross: 1200, expectedNet: 1000, expectedBasis: 'contract', actualGross: null,
      variance: 0, varianceClass: 'none', status: options.closed ? 'accrued' : 'expected',
      docId: null, docDueOn: '2026-11-10', overdue: false, reminders: 0 }] : []
    return route.fulfill({ json: { period, status: options.closed ? 'closed' : 'open', closedAt: null,
      counters: { total: charges.length, totalGross: ready ? 1200 : 0, noBasis: 0,
        expected: { count: charges.length, gross: ready ? 1200 : 0 }, received: { count: 0, gross: 0 },
        estimated: { count: 0, gross: 0 }, variance: { count: 0, gross: 0 } },
      charges, blocked: [], contractsWithoutTerms: [], preparation: { required: !ready, missing: ready ? 0 : 1, stale: 0 } } })
  })
  await page.goto('/e2e/ops-closing/fixture.html')
  await expect(page).toHaveTitle('Закрытие месяца — синтетическая проверка')
  await expect(page.getByRole('button', { name: 'Обновить расчёт', exact: true })).toBeVisible()
  return { reads, writes, errors }
}

test('mount is read-only; explicit command prepares and refreshes real service transport', async ({ page }, info) => {
  let release!: () => void
  const hold = new Promise<void>((resolve) => { release = resolve })
  const state = await scenario(page, { hold })
  await expect(page.getByRole('status')).toContainText('ещё не подготовлен')
  expect(state.writes).toEqual([])
  const period = `${await page.locator('input[type=month]').inputValue()}-01`
  await page.getByRole('button', { name: 'Обновить расчёт', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Обновляем расчёт…' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Закрыть месяц', exact: true })).toBeDisabled()
  release()
  await expect(page.getByRole('status')).toHaveCount(0)
  expect(state.writes).toEqual([{ company: 'qa-a', period, method: 'POST', body: null }])
  expect(state.reads.get(`qa-a:${period}`)).toBe(2)
  await expect(page.locator('[data-zone="Итоги месяца"]')).toContainText('1')
  expect(state.errors).toEqual([])
  expect(await page.locator('vite-error-overlay').count()).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `/tmp/ops-closing-${info.project.name}.png`, fullPage: true })
})

test('failure is visible and can be retried', async ({ page }) => {
  const state = await scenario(page, { fail: true })
  await page.getByRole('button', { name: 'Обновить расчёт', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Не удалось обновить расчёт')
  await expect(page.getByRole('button', { name: 'Обновить расчёт', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Обновить расчёт', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(2)
  expect(state.errors).toEqual([])
})

test('company switch during pending command invalidates the origin company only', async ({ page }) => {
  let release!: () => void
  const state = await scenario(page, { hold: new Promise<void>((resolve) => { release = resolve }) })
  const period = `${await page.locator('input[type=month]').inputValue()}-01`
  await page.getByRole('button', { name: 'Обновить расчёт', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Обновляем расчёт…' })).toBeVisible()
  await page.getByRole('button', { name: 'Компания Б', exact: true }).click()
  await expect.poll(() => state.reads.get(`qa-b:${period}`)).toBe(1)
  const completed = page.waitForResponse((r) => r.url().includes('/materialize'))
  release()
  await completed
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(state.reads.get(`qa-b:${period}`)).toBe(1)
  expect(state.writes[0].company).toBe('qa-a')
  await expect(page.getByRole('status')).toContainText('ещё не подготовлен')
  await page.getByRole('button', { name: 'Компания А', exact: true }).click()
  await expect.poll(() => state.reads.get(`qa-a:${period}`)).toBe(2)
  await expect(page.getByRole('status')).toHaveCount(0)
})

test('period switch during pending command keeps the new period unprepared', async ({ page }) => {
  let release!: () => void
  const state = await scenario(page, { hold: new Promise<void>((resolve) => { release = resolve }) })
  const initial = await page.locator('input[type=month]').inputValue()
  const other = initial === '2026-06' ? '2026-05' : '2026-06'
  await page.getByRole('button', { name: 'Обновить расчёт', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Обновляем расчёт…' })).toBeVisible()
  await page.locator('input[type=month]').fill(other)
  await expect.poll(() => state.reads.get(`qa-a:${other}-01`)).toBe(1)
  const completed = page.waitForResponse((r) => r.url().includes('/materialize'))
  release()
  await completed
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(state.reads.get(`qa-a:${other}-01`)).toBe(1)
  expect(state.writes[0].period).toBe(`${initial}-01`)
  await expect(page.getByRole('status')).toContainText('ещё не подготовлен')
  await page.locator('input[type=month]').fill(initial)
  await expect.poll(() => state.reads.get(`qa-a:${initial}-01`)).toBe(2)
})

test('closed period does not offer a preparation command', async ({ page }) => {
  const state = await scenario(page, { closed: true })
  await expect(page.getByRole('button', { name: 'Обновить расчёт', exact: true })).toBeDisabled()
  expect(state.writes).toEqual([])
})
