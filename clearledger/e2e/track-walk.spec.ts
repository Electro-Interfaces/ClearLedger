/**
 * Сквозной прогон интерфейса «Трека» на живом стенде «Элси».
 *
 * Не тест в обычном смысле: он ничего не утверждает про правильность экрана —
 * он ОТКРЫВАЕТ каждый экран, снимает его и собирает то, что человек глазами не
 * увидит: ошибки консоли, неудавшиеся запросы, горизонтальную прокрутку тела
 * страницы, пустые экраны там, где данные есть.
 *
 * Вход — токеном в localStorage, а не через форму: пароля учётки у прогона нет
 * и быть не должно. Токен выпускается на сервере и живёт сутки.
 *
 * Запуск:
 *   TRACK_TOKEN=... npx playwright test e2e/track-walk.spec.ts --config=e2e/track.config.ts
 */
import { test, expect, type Page, type ConsoleMessage } from '@playwright/test'
import fs from 'node:fs'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''
const СНИМКИ = process.env.TRACK_SHOTS ?? 'e2e/shots'

/** Экраны «Трека»: адрес и то, чем экран обязан быть непустым. */
const ЭКРАНЫ: { имя: string; путь: string; ждём?: string }[] = [
  { имя: '01-сегодня', путь: '/docs/work?view=today' },
  { имя: '02-моя-очередь', путь: '/docs/work?view=mine-all' },
  { имя: '03-важное', путь: '/docs/work?view=starred' },
  { имя: '04-отложено', путь: '/docs/work?view=deferred' },
  { имя: '05-я-поставил', путь: '/docs/work?view=assigned' },
  { имя: '06-наблюдаю', путь: '/docs/work?view=watching' },
  { имя: '07-поручения', путь: '/docs/work?view=errands' },
  { имя: '08-визы', путь: '/docs/work?view=approvals' },
  { имя: '09-ознакомиться', путь: '/docs/work?view=acquaints' },
  { имя: '10-мои-документы', путь: '/docs/work?view=own-docs' },
  { имя: '11-подборки', путь: '/docs/work?view=lists' },
  { имя: '12-календарь', путь: '/docs/work?view=calendar' },
  { имя: '13-записная-книжка', путь: '/docs/work?view=notes' },
  { имя: '14-входящие', путь: '/docs?view=incoming' },
  { имя: '15-исходящие', путь: '/docs?view=outgoing' },
  { имя: '16-приказы', путь: '/docs?view=orders' },
  { имя: '17-внутренние', путь: '/docs?view=internal' },
  { имя: '18-все-документы', путь: '/docs?view=all' },
  { имя: '19-вся-работа', путь: '/docs/company?view=work' },
  { имя: '20-разбор', путь: '/docs/company?view=triage' },
  { имя: '21-поручения-компании', путь: '/docs/company?view=errands' },
  { имя: '22-согласование', путь: '/docs/company?view=approval-board' },
  { имя: '23-доска-работы', путь: '/docs/company?view=work-board' },
  { имя: '24-доска-поручений', путь: '/docs/company?view=board' },
  { имя: '25-планирование', путь: '/docs/company?view=plan' },
  { имя: '26-приём-из-сэд', путь: '/docs/company?view=inbox' },
  { имя: '27-архив', путь: '/docs/company?view=archive' },
  { имя: '28-отчёт-документы', путь: '/docs/overview?view=docs' },
  { имя: '29-дисциплина', путь: '/docs/overview?view=discipline' },
  { имя: '30-отчёт-поручения', путь: '/docs/overview?view=errands' },
  { имя: '31-настройка-виды', путь: '/docs/setup?view=kinds' },
  { имя: '32-настройка-дела', путь: '/docs/setup?view=cases' },
  { имя: '33-настройка-нумераторы', путь: '/docs/setup?view=counters' },
  { имя: '34-настройка-замещения', путь: '/docs/setup?view=substitutions' },
]

interface Находка { экран: string; что: string }
const находки: Находка[] = []
const пусто: string[] = []

function запиши(экран: string, что: string) {
  находки.push({ экран, что })
}

async function войти(page: Page) {
  await page.addInitScript((t: string) => {
    localStorage.setItem('clearledger-token', t)
  }, ТОКЕН)
}

/** Ошибки консоли и сорванные запросы — то, чего человек на экране не видит. */
function слушать(page: Page, экран: () => string) {
  page.on('console', (m: ConsoleMessage) => {
    if (m.type() !== 'error') return
    const t = m.text()
    // Шум сторонних расширений и предзагрузки к продукту отношения не имеет.
    if (/favicon|ERR_INTERNET_DISCONNECTED|net::ERR_ABORTED/i.test(t)) return
    запиши(экран(), `консоль: ${t.slice(0, 220)}`)
  })
  page.on('pageerror', (e) => запиши(экран(), `исключение: ${String(e).slice(0, 220)}`))
  page.on('response', (r) => {
    if (r.status() >= 400 && r.url().includes('/api/')) {
      запиши(экран(), `HTTP ${r.status()} ${r.url().replace(БАЗА, '').slice(0, 140)}`)
    }
  })
}

test.describe('Трек: сквозной прогон', () => {
  test.beforeAll(() => {
    if (!ТОКЕН) throw new Error('нет TRACK_TOKEN')
    fs.mkdirSync(СНИМКИ, { recursive: true })
  })

  test('десктоп 1440×1000', async ({ page }) => {
    test.setTimeout(15 * 60_000)
    let текущий = 'старт'
    слушать(page, () => текущий)
    await войти(page)
    await page.setViewportSize({ width: 1440, height: 1000 })

    for (const э of ЭКРАНЫ) {
      текущий = э.имя
      await page.goto(`${БАЗА}${э.путь}`, { waitUntil: 'domcontentloaded' })
      // Ждём, пока витрина отрисует что-то своё, а не белый лист.
      await page.waitForTimeout(2500)
      await page.screenshot({ path: `${СНИМКИ}/${э.имя}.png`, fullPage: false })

      // Горизонтальная прокрутка тела — раскладка вылезла за экран.
      const шире = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 2)
      if (шире) запиши(э.имя, 'тело страницы прокручивается вбок')

      // Пустой экран: ни строк, ни объяснения.
      const текст = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
      if (текст.length < 200) запиши(э.имя, `на экране почти ничего: «${текст.slice(0, 120)}»`)
      if (/Что-то пошло не так|не удалось загрузить|Ошибка загрузки|Ошибка сети/i
        .test(текст)) {
        запиши(э.имя, `экран сообщает об ошибке: «${текст.slice(0, 160)}»`)
      }
      if (/Пусто|Ничего нет|нет данных/i.test(текст) && текст.length < 600) {
        пусто.push(э.имя)
      }
    }
  })

  test('мобильный 390×844', async ({ page }) => {
    test.setTimeout(10 * 60_000)
    let текущий = 'мобильный старт'
    слушать(page, () => `моб ${текущий}`)
    await войти(page)
    await page.setViewportSize({ width: 390, height: 844 })

    for (const э of ЭКРАНЫ.slice(0, 20)) {
      текущий = э.имя
      await page.goto(`${БАЗА}${э.путь}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(2000)
      await page.screenshot({ path: `${СНИМКИ}/m-${э.имя}.png`, fullPage: false })
      const шире = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 2)
      if (шире) запиши(`моб ${э.имя}`, 'страница уезжает вбок на 390 px')
    }
  })

  test.afterAll(() => {
    const отчёт = [
      `Экранов пройдено: ${ЭКРАНЫ.length}`,
      `Снимки: ${СНИМКИ}`,
      '',
      находки.length ? 'НАХОДКИ:' : 'Находок нет.',
      ...находки.map((f) => `  ✗ ${f.экран}: ${f.что}`),
      '',
      пусто.length ? `Пустые экраны: ${pretty(пусто)}` : '',
    ].join('\n')
    fs.writeFileSync(`${СНИМКИ}/отчёт.txt`, отчёт, 'utf8')
    console.log('\n' + отчёт)
  })
})

function pretty(xs: string[]) {
  return Array.from(new Set(xs)).join(', ')
}
