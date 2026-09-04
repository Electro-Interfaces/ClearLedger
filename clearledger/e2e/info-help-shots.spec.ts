/**
 * Снимки для справки по приложению «Инфо».
 *
 * Тот же приём, что у «Трека» (`track-help-shots.spec.ts`): снимок - часть
 * репозитория, а не разовая картинка. Снимается демонстрация «Меридиан» на
 * стенде `desk`: вымышленная компания, вымышленные люди, вымышленные документы.
 * Настоящих фамилий в кадре быть не должно.
 *
 * Шаги независимы: неудавшийся кадр печатается пропуском и не уносит остальные.
 *
 * Запуск:
 *   TRACK_TOKEN=… npx playwright test -c e2e/track.config.ts e2e/info-help-shots.spec.ts
 */
import { test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''
const ПАПКА = process.env.HELP_SHOTS ?? 'public/help/info'

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

async function войти(page: Page) {
  await page.addInitScript((v: string) => {
    localStorage.setItem('clearledger-token', v)
    localStorage.setItem('cl-install-dismissed-at:v3', String(Date.now()))
    // Размер текста читалки - средний: на крупном в кадр помещается три абзаца.
    localStorage.setItem('info:fontStep', '1')
  }, ТОКЕН)
  await page.context().addCookies([{ name: 'sidebar_state', value: 'true', url: БАЗА }])
}

async function экран(page: Page, путь: string) {
  await page.goto(`${БАЗА}${путь}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2400)
}

async function снимок(page: Page, имя: string) {
  await page.screenshot({ path: path.join(ПАПКА, `${имя}.png`) })
  снято.push(`${имя}.png`)
  console.log(`  + ${имя}.png`)
}

async function шаг(имя: string, дело: () => Promise<void>) {
  try {
    await дело()
  } catch (e) {
    пропущено.push(`${имя}: ${(e as Error).message.split('\n')[0]}`)
    console.log(`  - ${имя}`)
  }
}

test('снимки справки «Инфо»', async ({ page }) => {
  test.setTimeout(10 * 60_000)
  await войти(page)

  // Рабочее место целиком: дерево слева, стартовый экран справа.
  await шаг('if-center', async () => {
    await экран(page, '/info')
    await снимок(page, 'if-center')
  })

  // Пласт «Документы компании» с раскрытым разделом: ради него приложение и
  // отличается от коробочной справки.
  await шаг('if-tree-lnd', async () => {
    await экран(page, '/info?kind=lnd')
    await page.locator('button:has-text("Регламенты и приказы")')
      .filter({ visible: true }).first().click({ timeout: 10_000 })
    await page.waitForTimeout(900)
    await снимок(page, 'if-tree-lnd')
  })

  // Открытый документ компании: номер, дата вступления, текст.
  await шаг('if-article', async () => {
    await page.locator('button:has-text("Регламент документооборота")')
      .filter({ visible: true }).first().click({ timeout: 10_000 })
    await page.waitForTimeout(1400)
    await снимок(page, 'if-article')
  })

  // Поиск: свой список с подсветкой, дерево при этом не фильтруется.
  await шаг('if-search', async () => {
    await экран(page, '/info')
    await page.locator('input[placeholder*="Поиск"]').first()
      .fill('виза', { timeout: 10_000 })
    await page.waitForTimeout(1800)
    await снимок(page, 'if-search')
  })

  // Форма документа компании и её нижняя часть с привязками.
  await шаг('if-editor', async () => {
    await экран(page, '/info')
    await page.locator('button:has-text("Добавить документ компании")')
      .filter({ visible: true }).first().click({ timeout: 10_000 })
    await page.waitForTimeout(1400)
    await снимок(page, 'if-editor')
  })

  await шаг('if-editor-bindings', async () => {
    // Кнопка называется «Добавить место»: привязка в интерфейсе - это место,
    // где документ всплывёт, а не термин модели.
    await page.locator('button:has-text("Добавить место")')
      .filter({ visible: true }).first().click({ timeout: 8_000 })
    await page.waitForTimeout(900)
    await снимок(page, 'if-editor-bindings')
    await page.keyboard.press('Escape')
  })

  // Подсказка справа на живом экране: у «Виз» лежит частый вопрос компании,
  // привязанный именно к этому разделу.
  await шаг('if-context', async () => {
    await экран(page, '/docs/work?view=approvals')
    await page.locator('[data-zone^="Взаимодействие"] button:has-text("Инфо"), button[title*="Инфо"], button:has-text("Инфо")')
      .filter({ visible: true }).last().click({ timeout: 10_000 })
    await page.waitForTimeout(1800)
    await снимок(page, 'if-context')
  })
})
