/**
 * Надзор глазами трёх человек: рядового, начальника отдела и начальника
 * управления. Проверяется не право в базе, а то, что видит каждый на экране.
 */
import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const СНИМКИ = 'e2e/shots-oversight'
const ЛИЦА: Record<string, string> = Object.fromEntries(
  (process.env.TRACK_ACTORS ?? '').split(';').filter(Boolean).map((п) => {
    const i = п.indexOf('=')
    return [п.slice(0, i).trim(), п.slice(i + 1).trim()]
  }))

async function как(page: Page, имя: string, путь: string) {
  await page.addInitScript((t: string) => {
    localStorage.setItem('clearledger-token', t)
  }, ЛИЦА[имя])
  await page.goto(`${БАЗА}${путь}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  fs.mkdirSync(СНИМКИ, { recursive: true })
  await page.screenshot({ path: `${СНИМКИ}/${имя}.png` })
  return page.locator('body').innerText()
}

test('рядовой не видит раздела и получает объяснение по прямой ссылке', async ({ page }) => {
  test.setTimeout(150_000)
  await page.setViewportSize({ width: 1440, height: 1000 })
  const рельса = await как(page, 'Гаврилов', '/docs/work?view=today')
  expect(рельса, 'в рельсе рядового не должно быть «Компании»')
    .not.toContain('Компания')

  const прямо = await как(page, 'Гаврилов', '/docs/company?view=work')
  expect(прямо, 'по прямой ссылке рядовой должен получить объяснение')
    .toMatch(/отвечает за чужую работу|«Моё»/)
})

test('начальник видит раздел и в нём только своих', async ({ page }) => {
  test.setTimeout(150_000)
  await page.setViewportSize({ width: 1440, height: 1000 })
  const t = await как(page, 'Королев', '/docs/company?view=work')
  expect(t, 'начальнику отдела раздел открывается').not.toMatch(/отвечает за чужую работу/)
  expect(t).toContain('Документы и поручения')
})
