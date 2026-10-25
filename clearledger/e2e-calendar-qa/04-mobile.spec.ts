import { expect, test } from '@playwright/test'
import { authFile, апи, имя, календарь, снимок, токен, пространства } from './helpers'

/**
 * Телефон. Проверяется результат, а не только ширина стартовой страницы:
 * список на семь дней, одна строка управления, плавающая кнопка, форма под
 * «Подробнее», точки в месяце и работа на 320 px.
 */
test.use({ storageState: authFile('qa-cal-energy', 'organizer') })
// Тесты независимы: каждый готовит свои данные. Serial здесь скрывал бы
// второе падение за первым (Playwright пропускает хвост serial-файла).

const company = пространства['qa-cal-energy'].companyId
const ДЕНЬ = '2026-11-24'

/** Баннер «поставьте приложением» стоит поверх плавающей кнопки (см. M-07). */
async function убратьБаннер(page) {
  // Баннер появляется через секунду-две после загрузки, поэтому ждём его явно.
  await page.getByRole('button', { name: 'Позже' })
    .click({ timeout: 15_000 }).catch(() => { /* баннера нет — тем лучше */ })
}

async function собрать(request, название: string) {
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const r = await апи(request, t, '/api/work/calendar', {
    method: 'POST',
    data: {
      company_id: company, title: название,
      starts_at: `${ДЕНЬ}T08:00:00Z`, ends_at: `${ДЕНЬ}T09:00:00Z`, visibility: 'private',
    },
  })
  expect(r.status(), await r.text()).toBe(201)
  return (await r.json()).id as string
}

test('M-01 на телефоне календарь открывается списком и управляется одной строкой',
  async ({ page }) => {
    await page.goto(календарь({ date: ДЕНЬ }))           // без calendarMode — вид по умолчанию
    await expect(page.getByRole('button', { name: 'Предыдущий период' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Следующий период' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Поиск в периоде' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Список/ })).toBeVisible()
    await expect(page.getByLabel('Перейти к дате')).toBeVisible()
    // Заголовка «Календарь» и второй строки подписи периода на телефоне нет
    await expect(page.getByRole('heading', { name: 'Календарь' })).toHaveCount(0)
    await снимок(page, 'm01-agenda.png')
  })

test('M-02 плавающая кнопка доступна и предлагает три записи', async ({ page }) => {
  await page.goto(календарь({ date: ДЕНЬ }))
  await убратьБаннер(page)
  const кнопка = page.getByRole('button', { name: 'Новое событие' })
  await expect(кнопка).toBeVisible()
  const рамка = await кнопка.boundingBox()
  const размер = page.viewportSize()!
  expect(рамка!.y + рамка!.height, 'кнопка не уходит под нижний край').toBeLessThanOrEqual(размер.height)
  expect(рамка!.width, 'размер под палец').toBeGreaterThanOrEqual(44)
  await кнопка.click()
  await expect(page.getByRole('menuitem', { name: 'Встреча' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Дело себе' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Событие компании' })).toBeVisible()
  await снимок(page, 'm02-fab.png')
})

test('M-03 встреча собирается с телефона, участники — под «Подробнее»', async ({ page }) => {
  const название = имя('мобильная')
  await page.goto(календарь({ date: ДЕНЬ }))
  await убратьБаннер(page)
  await page.getByRole('button', { name: 'Новое событие' }).click()
  await page.getByRole('menuitem', { name: 'Встреча' }).click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel('О чём').fill(название)
  // Простой вид: участников и напоминания сразу нет
  await expect(окно.getByLabel('Найти участника')).toHaveCount(0)
  await окно.getByRole('button', { name: 'Подробнее' }).click()
  await expect(окно.getByLabel('Найти участника')).toBeVisible()
  await снимок(page, 'm03-more.png')
  await окно.getByRole('button', { name: 'Собрать' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()
})

test('M-04 поиск раскрывается кнопкой и отбирает записи периода', async ({ page, request }) => {
  const название = имя('поиск-моб')
  await собрать(request, название)
  await page.goto(календарь({ date: ДЕНЬ }))
  await убратьБаннер(page)
  await page.getByRole('button', { name: 'Поиск в периоде' }).click()
  const поле = page.getByLabel('Найти в календаре')
  await expect(поле).toBeVisible()
  await поле.fill(название.slice(-8))
  await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()
  await поле.fill('нетакогослова-zzz')
  await expect(page.getByText('В этом периоде ничего не найдено')).toBeVisible()
})

test('M-05 в месяце день показан точками и открывается списком', async ({ page, request }) => {
  await собрать(request, имя('точка'))
  await page.goto(календарь({ calendarMode: 'month', date: ДЕНЬ }))
  const день = page.getByRole('button', { name: /24 ноября: \d+ запис/ })
  await expect(день).toBeVisible()
  await снимок(page, 'm05-dots.png')
  await день.click()
  await expect(page).toHaveURL(/calendarMode=agenda/)
})

test('M-06 на 320 px нет горизонтальной прокрутки страницы, управление доступно',
  async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 720 })
    await page.goto(календарь({ date: ДЕНЬ }))
    await убратьБаннер(page)
    await expect(page.getByRole('button', { name: 'Новое событие' })).toBeVisible()
    const перелив = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(перелив, 'страница не шире экрана').toBeLessThanOrEqual(1)
    await снимок(page, 'm06-320.png')

    // Неделя прокручивается внутри календаря, а не растягивает страницу.
    // Меряем только после отрисовки сетки: на пустом экране проверка ничего не значит.
    await page.goto(календарь({ calendarMode: 'week', date: ДЕНЬ }))
    await expect(page.getByText('весь день', { exact: true })).toBeVisible()
    await expect(page.getByText('08:00').first()).toBeVisible()
    const переливНедели = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(переливНедели, 'сетка недели не растягивает страницу').toBeLessThanOrEqual(1)
    await снимок(page, 'm06-week-320.png')
  })

test('M-08 три одновременные встречи в сетке недели остаются читаемыми', async ({ page, request }) => {
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  // Свободный день: иначе следы прошлых прогонов добавят пересечений и
  // замер перестанет отвечать на вопрос «что видно при ровно трёх встречах».
  const день = `2027-01-${String(10 + Math.floor(Math.random() * 15)).padStart(2, '0')}`
  const названия = [имя('ряд-1'), имя('ряд-2'), имя('ряд-3')]
  for (const название of названия) {
    const r = await апи(request, t, '/api/work/calendar', {
      method: 'POST',
      data: {
        company_id: company, title: название,
        starts_at: `${день}T09:00:00Z`, ends_at: `${день}T10:00:00Z`, visibility: 'private',
      },
    })
    expect(r.status(), await r.text()).toBe(201)
  }
  await page.goto(календарь({ calendarMode: 'week', date: день }))
  await expect(page.getByText('весь день', { exact: true })).toBeVisible()
  const блок = page.getByRole('button', { name: new RegExp(названия[0]) }).first()
  await expect(блок).toBeVisible()
  const рамка = (await блок.boundingBox())!
  await снимок(page, 'm08-overlap-mobile.png')
  // Ожидание: в сетке видно, что это за встреча, либо показан счётчик «+N».
  expect(рамка.width, `ширина блока одной из трёх одновременных встреч: ${Math.round(рамка.width)} px`)
    .toBeGreaterThanOrEqual(44)
})

test('M-07 первое нажатие на кнопку записи попадает в баннер установки приложения',
  async ({ page }) => {
    await page.goto(календарь({ date: ДЕНЬ }))
    const кнопка = page.getByRole('button', { name: 'Новое событие' })
    await expect(кнопка).toBeVisible()
    const рамка = (await кнопка.boundingBox())!
    const центр = { x: рамка.x + рамка.width / 2, y: рамка.y + рамка.height / 2 }
    const подКурсором = await page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y)
      return el ? (el.textContent || el.tagName).trim().slice(0, 40) : 'ничего'
    }, центр)
    await снимок(page, 'm07-fab-overlap.png')
    // Ожидание: в точке кнопки создания — сама кнопка, а нажатие открывает меню записи.
    expect(подКурсором, 'кнопку создания ничем не перекрывают').not.toBe('Позже')
    await кнопка.click({ timeout: 10_000 })
    await expect(page.getByRole('menuitem', { name: 'Встреча' })).toBeVisible()
  })
