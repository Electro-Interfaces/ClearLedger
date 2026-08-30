/**
 * Снимки для справки «Трека».
 *
 * Справку пишут по тому, что человек видит, а не по тому, что помнит автор:
 * скриншот, снятый руками, устаревает на первой же правке подписи и никем не
 * пересобирается. Здесь снимок — часть репозитория: прогон гоняется заново
 * после изменений интерфейса, и все картинки в справке обновляются разом.
 *
 * Снимается демонстрация «Меридиан» на стенде `desk`: вымышленные люди,
 * вымышленные контрагенты, живые маршруты. Настоящих фамилий в кадре быть не
 * должно — это проверяется отдельно, обходом по схеме (см. память проекта).
 *
 * Шаги независимы. Снимок, который не удался, печатается пропуском и не уносит
 * с собой остальные двадцать девять: разметка одной кнопки меняется чаще, чем
 * весь набор экранов, и терять из-за неё всю съёмку — цена ни за что.
 *
 * Кадр — рабочая область без правой рельсы: в справке она только отвлекает, а
 * место на странице занимает. Ширина 1440 задана в `track.config.ts`.
 *
 * Запуск:
 *   TRACK_TOKEN=… npx playwright test -c e2e/track.config.ts e2e/track-help-shots.spec.ts
 */
import { test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''
const ПАПКА = process.env.HELP_SHOTS ?? 'public/help/track'

const снято: string[] = []
const пропущено: string[] = []

test.beforeAll(() => {
  fs.mkdirSync(ПАПКА, { recursive: true })
})

test.afterAll(() => {
  console.log(`снимков: ${снято.length}`)
  for (const имя of снято) console.log('  ' + имя)
  if (пропущено.length) {
    console.log(`пропущено: ${пропущено.length}`)
    for (const строка of пропущено) console.log('  ' + строка)
  }
})

/** Вход по токену: тот же способ, каким живут остальные прогоны «Трека». */
async function войти(page: Page) {
  await page.addInitScript((v: string) => {
    localStorage.setItem('clearledger-token', v)
    // Пункты раздела развёрнуты: в справке человек должен видеть имена экранов,
    // а не колонку значков.
    localStorage.setItem('cl-docs-views-collapsed', '0')
    // Плашка «поставьте приложением» садится поверх нижней трети кадра.
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
  }, ТОКЕН)
  // Рельса приложения развёрнута: свёрнутая до значков, она в справке не
  // объясняет, куда нажимать.
  await page.context().addCookies([{ name: 'sidebar_state', value: 'true', url: БАЗА }])
}

/** Открыть экран и дождаться, пока он перестанет мигать скелетонами. */
async function экран(page: Page, путь: string) {
  await page.goto(`${БАЗА}${путь}`, { waitUntil: 'domcontentloaded' })
  // Данные приезжают запросами: без паузы в кадр попадает «Загрузка…».
  await page.waitForTimeout(2600)
  await page.evaluate(() => {
    // Правая рельса — это управление, а не содержание экрана: в справке она
    // съедает восьмую часть ширины и ничего не объясняет.
    document.querySelectorAll('[data-zone^="Взаимодействие"]')
      .forEach((el) => ((el as HTMLElement).style.display = 'none'))
  })
  await page.waitForTimeout(300)
}

async function снимок(page: Page, имя: string) {
  await page.screenshot({ path: path.join(ПАПКА, `${имя}.png`) })
  снято.push(`${имя}.png`)
  console.log(`  + ${имя}.png`)
}

/** Шаг съёмки, который не имеет права уронить весь набор. */
async function шаг(имя: string, дело: () => Promise<void>) {
  try {
    await дело()
  } catch (e) {
    пропущено.push(`${имя}: ${(e as Error).message.split('\n')[0]}`)
    console.log(`  - ${имя}`)
  }
}

/** Простой снимок экрана по адресу. */
function экранныйШаг(page: Page, путь: string, имя: string) {
  return шаг(имя, async () => {
    await экран(page, путь)
    await снимок(page, имя)
  })
}

test('снимки справки «Трека»', async ({ page }) => {
  test.setTimeout(20 * 60_000)
  await войти(page)

  // ── Моё: рабочее место человека ─────────────────────────────────────────
  for (const [вид, имя] of [
    ['today', 'tr-my-today'], ['queue', 'tr-my-queue'],
    ['approvals', 'tr-my-visas'], ['errands', 'tr-my-errands'],
  ] as const) {
    await экранныйШаг(page, `/docs/work?view=${вид}`, имя)
  }

  // ── Документы: журнал ───────────────────────────────────────────────────
  await экранныйШаг(page, '/docs?view=incoming', 'tr-registry-incoming')
  await экранныйШаг(page, '/docs?view=all', 'tr-registry-all')

  // Карточка: щелчок по заголовку, а не по первой кнопке строки — первой идёт
  // галочка выбора, и клик по ней открывает панель массовых действий.
  await шаг('tr-card', async () => {
    await page.locator('table tbody tr td:nth-child(6) button').first()
      .click({ timeout: 15_000 })
    await page.waitForTimeout(2600)
    await снимок(page, 'tr-card')
  })

  // Вкладки карточки. Приложение держит в разметке обе раскладки сразу, поэтому
  // без фильтра по видимости `.first()` попадает в скрытую копию и клик виснет.
  for (const [вкладка, имя] of [['Обработка', 'tr-card-approval'],
                                ['История', 'tr-card-history']] as const) {
    await шаг(имя, async () => {
      await page.locator(`button:has-text("${вкладка}")`)
        .filter({ visible: true }).first().click({ timeout: 10_000 })
      await page.waitForTimeout(1800)
      await снимок(page, имя)
    })
  }

  await шаг('tr-new-doc', async () => {
    await экран(page, '/docs?view=incoming')
    await page.locator('button:has-text("Завести")').first().click({ timeout: 10_000 })
    await page.waitForTimeout(1600)
    await снимок(page, 'tr-new-doc')
    await page.keyboard.press('Escape')
  })

  // ── Компания: надзор ────────────────────────────────────────────────────
  for (const [вид, имя] of [
    ['work', 'tr-company-work'], ['triage', 'tr-triage'],
    ['docs', 'tr-approval'], ['work-board', 'tr-board'],
    ['errands', 'tr-company-errands'],
  ] as const) {
    await экранныйШаг(page, `/docs/company?view=${вид}`, имя)
  }

  // ── Календарь ───────────────────────────────────────────────────────────
  await экранныйШаг(page, '/docs/calendar', 'tr-calendar')

  // ── Отчёты ──────────────────────────────────────────────────────────────
  for (const [вид, имя] of [
    ['docs', 'tr-report-docs'], ['discipline', 'tr-report-discipline'],
    ['errands', 'tr-report-errands'], ['calendar', 'tr-report-calendar'],
  ] as const) {
    await экранныйШаг(page, `/docs/overview?view=${вид}`, имя)
  }

  // Нижняя половина отчёта по документам — разрезы, ради которых он и нужен.
  await шаг('tr-report-docs-cuts', async () => {
    await экран(page, '/docs/overview?view=docs')
    await page.evaluate(() => {
      const el = [...document.querySelectorAll('*')]
        .find((e) => e.scrollHeight > e.clientHeight + 200 && e.clientHeight > 300)
      if (el) el.scrollTop = el.scrollHeight
    })
    await page.waitForTimeout(900)
    await снимок(page, 'tr-report-docs-cuts')
  })

  // ── Настройка ───────────────────────────────────────────────────────────
  for (const [вид, имя] of [
    ['kinds', 'tr-setup-kinds'], ['counters', 'tr-setup-counters'],
    ['cases', 'tr-setup-cases'], ['labels', 'tr-setup-labels'],
    ['substitutions', 'tr-setup-substitutions'], ['exchange', 'tr-setup-exchange'],
    ['types', 'tr-setup-types'], ['templates', 'tr-setup-templates'],
    ['recurrences', 'tr-setup-recurrences'], ['projects', 'tr-setup-projects'],
    ['views', 'tr-setup-views'],
  ] as const) {
    await экранныйШаг(page, `/docs/setup?view=${вид}`, имя)
  }

  // Редактор вида: там задаётся маршрут согласования — самое частое «а где это».
  await шаг('tr-setup-kind-editor', async () => {
    await экран(page, '/docs/setup?view=kinds')
    await page.locator('button:has-text("Изменить")').first().click({ timeout: 10_000 })
    await page.waitForTimeout(1900)
    await снимок(page, 'tr-setup-kind-editor')
  })
})
