import { expect, test } from '@playwright/test'
import { authFile, календарь, снимок } from './helpers'

/**
 * Качество подачи: читаемость в обеих темах, имена полей для программы чтения
 * с экрана, видимый фокус, размер целей. Дизайн продукта не меняем — проверяем,
 * выполняет ли он собственные правила.
 */
test.use({ storageState: authFile('qa-cal-energy', 'organizer') })
const ДЕНЬ = '2026-11-10'

/** Контраст текста к фактическому фону по WCAG 2.1. */
const КОНТРАСТ = `(el) => {
  const разбор = (s) => (s.match(/[\\d.]+/g) || []).map(Number)
  const яркость = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  const слой = (node) => {
    for (let n = node; n; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor
      const части = разбор(bg)
      if (части.length >= 3 && (части[3] === undefined || части[3] > 0.95)) return части
    }
    return [255, 255, 255]
  }
  const стиль = getComputedStyle(el)
  const текст = разбор(стиль.color)
  const фон = слой(el)
  const a = яркость(текст), b = яркость(фон)
  const k = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
  return { контраст: Math.round(k * 100) / 100, размер: parseFloat(стиль.fontSize), вес: стиль.fontWeight }
}`

for (const тема of ['light', 'dark'] as const) {
  test(`U-01 ${тема}: подписи календаря читаемы`, async ({ page }) => {
    await page.goto(календарь({ calendarMode: 'month', date: ДЕНЬ, theme: тема }))
    await expect(page.getByRole('heading', { name: 'Календарь' })).toBeVisible()
    await снимок(page, `u01-${тема}.png`)

    const проверить = async (локатор, подпись: string, порог = 4.5) => {
      const r = await локатор.evaluate(eval(КОНТРАСТ))
      expect(r.контраст, `${подпись} (${тема}): контраст ${r.контраст}:1 при ${r.размер}px`)
        .toBeGreaterThanOrEqual(r.размер >= 24 || (r.размер >= 18.66 && Number(r.вес) >= 700) ? 3 : порог)
    }
    await проверить(page.getByRole('heading', { name: 'Календарь' }), 'заголовок')
    await проверить(page.locator('p.capitalize').first(), 'подпись периода')
    await проверить(page.getByText('пн', { exact: true }).first(), 'день недели в шапке сетки')
    const чип = page.getByRole('button', { name: /QA-CAL-20261025/ }).first()
    if (await чип.count()) await проверить(чип, 'название встречи в клетке')
  })
}

test('U-02 поля даты встречи различимы по доступному имени', async ({ page }) => {
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Встреча' }).click()
  const окно = page.getByRole('dialog')
  await expect(окно.getByRole('heading', { name: 'Новая встреча' })).toBeVisible()
  // Доступное имя поля: aria-label, иначе связанная подпись <label for>.
  const имена = await окно.locator('input[placeholder="дд.мм.гггг"]').evaluateAll(
    (поля) => поля.map((п) => п.getAttribute('aria-label')
      || (п.labels && п.labels[0] ? (п.labels[0].textContent || '').trim() : '')))
  await снимок(page, 'u02-event-form.png')
  // Ожидание: программа чтения с экрана различает начало и конец встречи
  expect(new Set(имена).size, `имена полей даты: ${имена.join(' / ')}`).toBe(имена.length)
})

test('U-03 фокус с клавиатуры виден на управлении календарём', async ({ page }) => {
  await page.goto(календарь({ calendarMode: 'month', date: ДЕНЬ }))
  const кнопка = page.getByRole('button', { name: 'Неделя', exact: true })
  await кнопка.focus()
  const стиль = await кнопка.evaluate((el) => {
    const s = getComputedStyle(el)
    return { outline: s.outlineWidth, ring: s.boxShadow, border: s.borderColor }
  })
  const естьФокус = parseFloat(стиль.outline) > 0 || (стиль.ring && стиль.ring !== 'none')
  expect(естьФокус, `фокус: outline=${стиль.outline}, shadow=${стиль.ring}`).toBeTruthy()
})

test('U-04 управление календарём помещается в палец на телефоне', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(календарь({ date: ДЕНЬ }))
  await page.getByRole('button', { name: 'Позже' }).click({ timeout: 10_000 }).catch(() => {})
  for (const имя of ['Предыдущий период', 'Следующий период', 'Поиск в периоде']) {
    const рамка = await page.getByRole('button', { name: имя }).boundingBox()
    expect(Math.min(рамка!.width, рамка!.height), `${имя}: ${рамка!.width}×${рамка!.height}`)
      .toBeGreaterThanOrEqual(36)
  }
  await снимок(page, 'u04-mobile-controls.png')
})

test('U-05 первая метка часа видна целиком при открытии сетки', async ({ page }) => {
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  const метка = page.getByText('08:00').first()
  await expect(метка).toBeVisible()
  const зазор = await метка.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const окно = el.closest('[class*="overflow-y-auto"]')!.getBoundingClientRect()
    return Math.round(r.top - окно.top)
  })
  expect(зазор, `верх метки относительно верха прокрутки: ${зазор} px`).toBeGreaterThanOrEqual(0)
})
