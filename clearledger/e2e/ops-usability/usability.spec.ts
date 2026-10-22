import { test, expect, type Page } from '@playwright/test'
import { responses } from './data'

const fixture = '/e2e/ops-usability/fixture.html'
test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-22T12:00:00Z') })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const data = responses[url.pathname]
    if (data === undefined) return route.fulfill({ status: 501, json: { detail: 'Нет учебного ответа: ' + url.pathname } })
    await route.fulfill({ json: data })
  })
})

function recordErrors(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (e) => { if (e.type() === 'error' || e.type() === 'warning') errors.push(e.text()) })
  return errors
}

test('ширины одинаковы на страницах 1 → 2 → 3 → 1, после сортировки и смены размера', async ({ page }) => {
  const errors = recordErrors(page)
  await page.goto(fixture)
  await page.getByLabel('Строк на странице', { exact: true }).selectOption('25')
  const widths = () => page.locator('thead th').evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().width)))
  await expect(page.locator('tbody tr')).toHaveCount(25)
  const first = await widths()
  await page.getByRole('button', { name: 'Следующая страница', exact: true }).click()
  await expect(page.getByText('Строки 26–50 из 60')).toBeVisible()
  expect(await widths()).toEqual(first)
  await page.getByRole('button', { name: 'Следующая страница', exact: true }).click()
  await expect(page.locator('tbody tr')).toHaveCount(10)
  expect(await widths()).toEqual(first)
  await page.getByRole('button', { name: 'Предыдущая страница', exact: true }).click()
  await page.getByRole('button', { name: 'Предыдущая страница', exact: true }).click()
  expect(await widths()).toEqual(first)
  await page.getByRole('button', { name: 'Приездов', exact: true }).focus()
  await page.keyboard.press('Enter')
  expect(await widths()).toEqual(first)
  await page.getByLabel('Строк на странице', { exact: true }).selectOption('100')
  await expect(page.locator('tbody tr')).toHaveCount(60)
  expect(await widths()).toEqual(first)
  expect(errors).toEqual([])
})

for (const width of [1440, 1024, 390]) {
  test(`верхняя прокрутка доступна и синхронизирована, ширина ${width}`, async ({ page }) => {
    const errors = recordErrors(page)
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.goto(fixture)
    const bar = page.getByRole('region', { name: 'Горизонтальная прокрутка таблицы' })
    const box = page.locator('div[tabindex="0"]').filter({ has: page.locator('table') }).last()
    await expect(bar).toBeVisible()
    expect((await bar.boundingBox())!.y).toBeLessThan(300)
    const top = await box.evaluate((el) => { el.scrollTop = 400; return el.scrollTop })
    await bar.focus()
    await bar.press('ArrowRight')
    await expect.poll(() => box.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
    await bar.press('End')
    await expect.poll(() => box.evaluate((el) => Math.abs(el.scrollLeft - (el.scrollWidth - el.clientWidth)))).toBeLessThan(2)
    expect(await box.evaluate((el) => el.scrollTop)).toBe(top)
    await box.evaluate((el) => { el.scrollLeft = 0 })
    await expect.poll(() => bar.evaluate((el) => el.scrollLeft)).toBe(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors).toEqual([])
    await page.screenshot({ path: `${test.info().outputDir}/table-${width}.png` })
  })
}

test('полоса скрывается, когда столбцы помещаются; ручная ширина сохраняется', async ({ page }) => {
  await page.goto(fixture)
  await page.getByLabel('Строк на странице', { exact: true }).selectOption('25')
  const header = page.locator('thead th').nth(1)
  const initial = (await header.boundingBox())!.width
  const handle = await page.getByRole('separator', { name: 'Ширина столбца «Станция»', exact: true }).boundingBox()
  await page.mouse.move(handle!.x + 2, handle!.y + 8)
  await page.mouse.down()
  await page.mouse.move(handle!.x + 62, handle!.y + 8)
  await page.mouse.up()
  await expect.poll(async () => Math.round((await header.boundingBox())!.width)).toBe(Math.round(initial + 60))
  await page.getByRole('button', { name: 'Следующая страница', exact: true }).click()
  expect(Math.round((await header.boundingBox())!.width)).toBe(Math.round(initial + 60))
  await page.setViewportSize({ width: 2560, height: 900 })
  await expect(page.locator('[aria-label="Горизонтальная прокрутка таблицы"]')).toBeHidden()
  await page.setViewportSize({ width: 1024, height: 900 })
  await expect(page.getByRole('region', { name: 'Горизонтальная прокрутка таблицы' })).toBeVisible()
})

for (const width of [1440, 390]) for (const screen of ['state', 'reliability', 'vendors', 'tickets']) {
  test(`календарь ${screen}, ${width}: месяцы не применяют дату; отмена и применение`, async ({ page }) => {
    const errors = recordErrors(page)
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    const requests: string[] = []
    page.on('request', (r) => { if (r.url().includes('/api/ops/')) requests.push(r.url()) })
    await page.goto(`${fixture}?screen=${screen}`)
    await expect(page.locator('table').first()).toBeVisible()
    const trigger = page.getByRole('button', { name: /Открыть выбор периода/ })
    const initial = await trigger.innerText()
    const initialRequests = requests.length
    await trigger.click()
    const dialog = page.getByRole('dialog')
    for (let i = 0; i < 3; i++) {
      await dialog.getByRole('button', { name: 'Go to the Previous Month', exact: true }).first().click()
      await expect(dialog).toBeVisible()
    }
    await dialog.getByRole('button', { name: 'Go to the Next Month', exact: true }).first().click()
    await dialog.getByRole('combobox').first().selectOption('0')
    await dialog.getByRole('button', { name: /15 января 2026/ }).click()
    await expect(dialog).toBeVisible()
    expect(requests.length).toBe(initialRequests)
    await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
    expect(await trigger.innerText()).toBe(initial)
    expect(requests.length).toBe(initialRequests)
    await trigger.click()
    const dates = dialog.locator('input[type="date"]')
    await dates.first().fill('2026-09-01')
    await dates.last().fill('2026-09-09')
    expect(requests.length).toBe(initialRequests)
    await dialog.getByRole('button', { name: 'Применить', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect.poll(() => requests.some((url) => new URL(url).searchParams.get('as_of') === '2026-09-09')).toBe(true)
    await expect(page.locator('table').first()).toBeVisible()
    expect(errors).toEqual([])
  })
}

for (const width of [1440, 390]) for (const screen of ['state', 'reliability']) {
  test(`сводка ${screen}, ${width}: отдельный вид, фильтры над таблицей и работают`, async ({ page }) => {
    const errors = recordErrors(page)
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.goto(`${fixture}?screen=${screen}`)
    await expect(page.getByRole('tab', { name: 'Список', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('button', { name: /Раскрыть станции Учебный регион/ })).toHaveCount(0)
    await page.getByRole('button', { name: /^Фильтры/ }).click()
    const region = page.locator(`#${screen === 'state' ? 'state' : 'reliability'}-region`)
    expect((await region.boundingBox())!.y).toBeLessThan((await page.locator('table').first().boundingBox())!.y)
    await region.click()
    await page.getByRole('option', { name: 'Учебный регион А', exact: true }).click()
    await expect(page.locator('tbody tr[data-report-row]')).toHaveCount(30)
    await page.getByRole('button', { name: 'Свернуть фильтры', exact: true }).click()
    await expect(region).toHaveCount(0)
    await page.getByRole('tab', { name: 'По регионам', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Раскрыть станции Учебный регион А', exact: true })).toBeVisible()
    await page.getByRole('tab', { name: 'Список', exact: true }).click()
    await expect(page.getByRole('button', { name: /Раскрыть станции Учебный регион/ })).toHaveCount(0)
    expect(errors).toEqual([])
  })
}
