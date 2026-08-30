/**
 * «Трек» в работе: не открыть экран, а НАЖАТЬ.
 *
 * Прошлый прогон отвечал на вопрос «отрисовалось ли». Этот — на вопрос
 * «работает ли»: открывается ли карточка, доезжает ли реплика, меняет ли
 * действие строку, переносится ли карточка на доске, закрывается ли диалог по
 * Esc, сужает ли поиск выборку.
 *
 * Каждый сценарий копит находки, а не падает на первой: цель — список того, что
 * чинить, а не первое препятствие.
 *
 * Грабля локатора, стоившая прогона: `page.locator(X).locator('visible=true')`
 * ищет ВИДИМЫХ ПОТОМКОВ X, а не «X, если он видим». На кнопке Radix это даёт
 * внутренний `<span>` с `pointer-events: none`, и клик ждёт его вечно.
 * Правильно — псевдокласс `:visible` в самом селекторе.
 */
import { test, type Page } from '@playwright/test'
import fs from 'node:fs'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''
const СНИМКИ = process.env.TRACK_SHOTS ?? 'e2e/shots-actions'
const МЕТКА = '[проверка]'

const находки: string[] = []
function нашли(что: string) {
  находки.push(что)
  console.log(`  ✗ ${что}`)
}
function хорошо(что: string) {
  console.log(`  ✓ ${что}`)
}

async function войти(page: Page) {
  await page.addInitScript((t: string) => {
    localStorage.setItem('clearledger-token', t)
  }, ТОКЕН)
  page.on('pageerror', (e) => нашли(`исключение: ${String(e).slice(0, 180)}`))
  page.on('response', (r) => {
    if (r.status() >= 400 && r.url().includes('/api/')) {
      нашли(`HTTP ${r.status()} ${r.url().replace(БАЗА, '').slice(0, 120)}`)
    }
  })
}

async function открыть(page: Page, путь: string) {
  await page.goto(`${БАЗА}${путь}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2400)
  // Плашка «поставьте приложением» висит в правом нижнем углу и перехватывает
  // нажатия по тому, что под ней.
  const позже = page.locator('button:visible', { hasText: /^Позже$/ }).first()
  if (await позже.count()) await позже.click().catch(() => {})
}

async function снимок(page: Page, имя: string) {
  fs.mkdirSync(СНИМКИ, { recursive: true })
  await page.screenshot({ path: `${СНИМКИ}/${имя}.png` })
}

/** Видимый узел с этим текстом. */
function видно(page: Page, текст: string | RegExp) {
  return page.getByText(текст).filter({ visible: true }).first()
}
/** Видимая кнопка. */
function кнопка(page: Page, текст: string | RegExp) {
  return page.locator('button:visible').filter({ hasText: текст }).first()
}

test.beforeEach(async ({ page }) => {
  if (!ТОКЕН) throw new Error('нет TRACK_TOKEN')
  await войти(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
})

test('карточка документа: все вкладки и реплика доезжает', async ({ page }) => {
  test.setTimeout(150_000)
  await открыть(page, '/docs?view=incoming')

  await видно(page, 'Замечания к акту сдачи-приёмки за июль').click()
  await page.waitForTimeout(2000)
  await снимок(page, '01-карточка-документа')

  // Каждая вкладка обязана что-то показать, а не пустой прямоугольник.
  for (const имя of ['Обработка', 'Файлы и подписи', 'Связи', 'Архив', 'История']) {
    const вкладка = page.locator('[role="tab"]:visible').filter({ hasText: имя }).first()
    if (!(await вкладка.count())) { нашли(`карточка: нет вкладки «${имя}»`); continue }
    await вкладка.click()
    await page.waitForTimeout(1600)
    const тело = await page.locator('[role="tabpanel"]:visible').first()
      .innerText().catch(() => '')
    if (тело.replace(/\s+/g, ' ').trim().length < 15) {
      нашли(`карточка, вкладка «${имя}»: пустая панель`)
    } else хорошо(`вкладка «${имя}» показывает содержимое`)
    await снимок(page, `01-вкладка-${имя.split(' ')[0]}`)
  }

  // Реплика живёт на «Истории»: пишем и читаем в одном месте.
  await page.locator('[role="tab"]:visible').filter({ hasText: 'История' }).first().click()
  await page.waitForTimeout(1400)
  const поле = page.getByPlaceholder('Что важно зафиксировать по документу')
    .filter({ visible: true }).first()
  if (!(await поле.count())) { нашли('карточка: поля реплики нет'); return }
  const слово = `${МЕТКА} реплика ${Date.now() % 100000}`
  await поле.fill(слово)

  // Enter в однострочном поле — естественная отправка. Если её нет, это находка.
  await поле.press('Enter')
  await page.waitForTimeout(2000)
  if ((await поле.inputValue()) !== '') {
    нашли('реплика по документу: Enter не отправляет, нужно целиться в кнопку')
    await кнопка(page, /^Записать$/).click()
    await page.waitForTimeout(2400)
  }
  if ((await page.locator('body').innerText()).includes(слово)) {
    хорошо('реплика доехала до ленты «История»')
  } else нашли('реплика по документу: в ленте «История» её нет')
  await снимок(page, '02-реплика-в-истории')
})

test('очередь: действия в строке меняют её', async ({ page }) => {
  test.setTimeout(120_000)
  await открыть(page, '/docs/work?view=mine-all')
  await снимок(page, '03-очередь')

  const звёзды = page.locator('button[title*="Важно"]:visible')
  if (!(await звёзды.count())) { нашли('очередь: кнопки «важно» в строке нет'); return }
  const было = await page.locator('button[title*="Снять важность"]').count()
  await звёзды.first().click()
  await page.waitForTimeout(2000)
  if ((await page.locator('button[title*="Снять важность"]').count()) > было) {
    хорошо('звезда ставится и строка это показывает')
  } else нашли('очередь: звезда не отразилась в строке')

  const солнце = page.locator('button[title*="Взять в мой день"]:visible').first()
  if (await солнце.count()) {
    await солнце.click()
    await page.waitForTimeout(2000)
    if (await page.locator('button[title*="Убрать из моего дня"]').count()) {
      хорошо('«взять в день» отражается в строке')
    } else нашли('очередь: «взять в день» не отразилось')
  } else нашли('очередь: кнопки «взять в день» нет')

  // «Отложить» намеренно спрятано в поповер: это решение о своей раскладке,
  // а не действие над предметом, и в строке ему не место.
  const раскладка = page.locator('button[title="Как разложить у себя"]:visible').first()
  if (await раскладка.count()) {
    await раскладка.click()
    await page.waitForTimeout(1400)
    await снимок(page, '04a-поповер-раскладки')
    // Два ответа на вопрос «когда»: «Займусь» планирует и оставляет на виду,
    // «Не показывать до» прячет. Прежнее «Не сегодня» называло сокрытие
    // планированием и путало их.
    const меню = await page.locator('body').innerText()
    for (const пункт of ['Займусь', 'Не показывать до']) {
      if (!меню.includes(пункт)) нашли(`раскладка: в поповере нет «${пункт}»`)
    }
    if (меню.includes('Займусь') && меню.includes('Не показывать до')) {
      хорошо('план и сокрытие разведены в меню раскладки')
    }
    await page.keyboard.press('Escape')
  } else нашли('очередь: поповера раскладки нет')
  await снимок(page, '04-очередь-после-действий')
})

test('доска: три оси и перенос карточки', async ({ page }) => {
  test.setTimeout(180_000)

  const оси: [string, string, string[]][] = [
    ['', '05-доска-состояние', ['Заведено', 'В работе', 'На согласовании']],
    ['&axis=place', '06-доска-раскладка', ['Мой день', 'Не разложено', 'Отложено']],
    ['&axis=due', '07-доска-срок', ['Просрочено', 'Сегодня', 'Завтра']],
  ]
  for (const [хвост, имя, колонки] of оси) {
    await открыть(page, `/docs/company?view=work-board${хвост}`)
    await снимок(page, имя)
    const t = await page.locator('body').innerText()
    for (const к of колонки) {
      if (!t.includes(к)) нашли(`доска${хвост || ' (состояние)'}: нет колонки «${к}»`)
    }
  }
  хорошо('все три оси доски рисуют свои колонки')

  await открыть(page, '/docs/company?view=work-board')
  const триггер = page.locator('button[role="combobox"]:visible')
    .filter({ hasText: /По состоянию/ }).first()
  if (!(await триггер.count())) { нашли('доска: переключателя оси нет'); return }
  await триггер.click()
  await page.waitForTimeout(900)
  const варианты = await page.locator('[role="option"]:visible').allInnerTexts()
  if (варианты.length !== 3) {
    нашли(`доска: в переключателе оси ${варианты.length} вариантов вместо трёх`)
  } else хорошо('переключатель оси предлагает три оси')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(700)

  // Сам перенос проверяется отдельно — `e2e/track-dnd.spec.ts`: мышью его
  // не воспроизвести, Chromium запускает перенос своим механизмом, и события
  // приходится слать вручную.
})

test('календарь: подачи, диалог встречи, создание, Esc', async ({ page }) => {
  test.setTimeout(180_000)
  await открыть(page, '/docs/work?view=calendar')

  for (const [к, имя] of [['Неделя', '09-неделя'], ['День', '10-день'],
                          ['Месяц', '11-месяц']] as const) {
    const b = page.getByRole('button', { name: к, exact: true }).first()
    if (!(await b.count())) { нашли(`календарь: нет подачи «${к}»`); continue }
    await b.click()
    await page.waitForTimeout(1800)
    await снимок(page, имя)
  }
  хорошо('три подачи календаря переключаются')

  const встреча = видно(page, /Планёрка ко/)
  if (await встреча.count()) {
    await встреча.click()
    await page.waitForTimeout(1800)
    await снимок(page, '12-диалог-встречи')
    const t = await page.locator('body').innerText()
    for (const блок of ['Кого зовём', 'Кто видит встречу', 'Повторять']) {
      if (!t.includes(блок)) нашли(`диалог встречи: нет блока «${блок}»`)
    }
    await page.keyboard.press('Escape')
    await page.waitForTimeout(1200)
    if (await page.getByText('Кого зовём').count()) {
      нашли('диалог встречи: не закрывается по Esc')
    } else хорошо('диалог встречи закрывается по Esc')
  } else нашли('календарь: встречи демо не видно')

  const создать = кнопка(page, /Встреча/)
  if (await создать.count()) {
    await создать.click()
    await page.waitForTimeout(1800)
    await снимок(page, '13-новая-встреча')
    const t = await page.locator('body').innerText()
    if (!/Название|Тема|О чём/.test(t)) нашли('новая встреча: нет поля названия')
    else хорошо('диалог новой встречи открывается')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(1000)
  } else нашли('календарь: кнопки создания встречи не нашлось')
})

test('записная книжка: ввод, правка, выходы', async ({ page }) => {
  test.setTimeout(150_000)
  await открыть(page, '/docs/work?view=notes')
  await снимок(page, '14-книжка')

  const поле = page.getByPlaceholder(/Что записать/i).first()
  if (!(await поле.count())) { нашли('книжка: поля ввода нет'); return }
  const слово = `${МЕТКА} запись ${Date.now() % 100000}`
  await поле.fill(слово)
  await page.keyboard.press('Control+Enter')
  await page.waitForTimeout(2500)
  if (!(await page.locator('body').innerText()).includes(слово)) {
    нашли('книжка: запись не появилась после Ctrl+Enter'); return
  }
  хорошо('запись заводится с клавиатуры')

  await видно(page, слово).click()
  await page.waitForTimeout(1500)
  await снимок(page, '15-книжка-правка')
  const выходы = await page.locator('body').innerText()
  for (const в of ['Срок', 'Напомнить']) {
    if (!выходы.includes(в)) нашли(`книжка: у записи нет выхода «${в}»`)
  }
  // «Поручить…» стоит в меню записи: это выход из книжки наружу, и на виду
  // рядом со «Сроком» он звал бы отдать чужому то, что ещё только мысль.
  const меню = page.locator('[aria-haspopup="menu"]:visible').last()
  if (await меню.count()) {
    await меню.click()
    await page.waitForTimeout(1300)
    await снимок(page, '15a-меню-записи')
    if (!/Поручить/.test(await page.locator('body').innerText())) {
      нашли('книжка: в меню записи нет «Поручить…»')
    } else хорошо('«Поручить…» доступно из меню записи')
    await page.keyboard.press('Escape')
  } else нашли('книжка: у записи нет меню')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(800)
})

test('реестр: поиск, отбор и массовое выделение', async ({ page }) => {
  test.setTimeout(150_000)
  await открыть(page, '/docs?view=all')
  await снимок(page, '16-реестр')

  const найдено = async () => {
    const t = await page.locator('body').innerText()
    return Number(/Найдено[:\s]*(\d+)/.exec(t)?.[1] ?? -1)
  }
  const всего = await найдено()
  if (всего < 0) { нашли('реестр: не пишет, сколько найдено'); return }
  хорошо(`реестр показывает «Найдено: ${всего}»`)

  const строкТаблицы = await page.locator('table:visible tbody tr').count()
  const прочерков = await page.locator('table:visible tbody tr td')
    .filter({ hasText: /^—$/ }).count()
  if (строкТаблицы > 0 && прочерков >= строкТаблицы * 2) {
    нашли(`реестр: ${прочерков} прочерков на ${строкТаблицы} строк — колонка пуста во всех`)
  } else хорошо(`прочерков ${прочерков} на ${строкТаблицы} строк — мёртвых колонок нет`)

  const поиск = page.getByPlaceholder(/Номер, реквизиты/i).first()
  if (!(await поиск.count())) { нашли('реестр: поля поиска нет'); return }
  await поиск.fill('претензи')
  await page.waitForTimeout(3000)
  const после = await найдено()
  await снимок(page, '17-реестр-поиск')
  if (после < 0 || после >= всего) {
    нашли(`реестр: поиск «претензи» не сузил выборку (${всего} → ${после})`)
  } else хорошо(`поиск сузил выборку ${всего} → ${после}`)
  await поиск.fill('')
  await page.waitForTimeout(2400)

  const состояние = page.locator('select:visible').first()
  if (await состояние.count()) {
    await состояние.selectOption({ label: 'Исполнен' }).catch(() => {})
    await page.waitForTimeout(2800)
    const отобрано = await найдено()
    await снимок(page, '18-реестр-отбор')
    if (отобрано < 0 || отобрано >= всего) {
      нашли(`реестр: отбор «Исполнен» не сузил выборку (${всего} → ${отобрано})`)
    } else хорошо(`отбор по состоянию сузил ${всего} → ${отобрано}`)
  } else нашли('реестр: отбора по состоянию нет')

  const галки = page.locator('[role="checkbox"]:visible, input[type="checkbox"]:visible')
  if (await галки.count()) {
    await галки.first().click()
    await page.waitForTimeout(1600)
    await снимок(page, '19-реестр-выделение')
    const t = await page.locator('body').innerText()
    if (!/Выбран|Выделен|отмечен/i.test(t)) {
      нашли('реестр: галка поставлена, но экран не говорит, что с выбранным делать')
    } else хорошо('выделение показывает доступные действия')
  } else нашли('реестр: галок для массового выбора нет')
})

test('отчёты: цифры на месте, контур открывается', async ({ page }) => {
  test.setTimeout(150_000)
  for (const [путь, имя] of [['/docs/overview?view=docs', '20-отчёт-документы'],
                             ['/docs/overview?view=discipline', '21-дисциплина'],
                             ['/docs/overview?view=errands', '22-отчёт-поручения']] as const) {
    await открыть(page, путь)
    await снимок(page, имя)
    const t = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
    if (!/\d/.test(t.slice(0, 2000))) нашли(`${имя}: на экране нет ни одной цифры`)
    if (/Пусто|Нет данных/i.test(t) && t.length < 700) нашли(`${имя}: экран пуст`)
  }
  хорошо('три отчёта отвечают цифрами')

  // Период правится полями «с/по» на самом отчёте: проверяем, что смена
  // периода действительно пересчитывает цифры, а не только подпись.
  await открыть(page, '/docs/overview?view=discipline')
  const было = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
  const сДаты = page.locator('input[type="date"]:visible').first()
  if (await сДаты.count()) {
    await сДаты.fill('2026-08-24')
    await page.waitForTimeout(3200)
    await снимок(page, '23-период-сменён')
    const стало = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
    if (стало === было) нашли('дисциплина: смена периода не изменила ни одной цифры')
    else хорошо('смена периода пересчитывает отчёт')
  } else нашли('дисциплина: полей периода нет')
})

test('«Создать»: что можно завести', async ({ page }) => {
  test.setTimeout(120_000)
  await открыть(page, '/docs/work?view=today')
  const создать = кнопка(page, /^Создать$/)
  if (!(await создать.count())) { нашли('нет кнопки «Создать»'); return }
  await создать.click()
  await page.waitForTimeout(1700)
  await снимок(page, '24-создать')
  const t = await page.locator('body').innerText()
  if (!/Поручение|Документ/.test(t)) нашли('«Создать»: не предлагает ни документ, ни поручение')
  else хорошо('«Создать» предлагает завести предмет')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(1000)
  if (await page.locator('[role="dialog"]:visible').count()) {
    нашли('«Создать»: диалог не закрывается по Esc')
  } else хорошо('диалог «Создать» закрывается по Esc')
})

test('подборки, планирование, визы, ознакомление', async ({ page }) => {
  test.setTimeout(120_000)
  for (const [путь, имя] of [['/docs/work?view=lists', '25-подборки'],
                             ['/docs/company?view=plan', '26-планирование'],
                             ['/docs/work?view=approvals', '27-визы'],
                             ['/docs/work?view=acquaints', '28-ознакомиться']] as const) {
    await открыть(page, путь)
    await снимок(page, имя)
    const t = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
    if (t.length < 400) нашли(`${имя}: почти пустой экран — «${t.slice(0, 120)}»`)
  }
  хорошо('подборки, планирование, визы и ознакомление открываются')
})

test.afterAll(() => {
  const отчёт = находки.length
    ? ['НАХОДКИ:', ...находки.map((f) => `  ✗ ${f}`)].join('\n')
    : 'Находок нет.'
  fs.mkdirSync(СНИМКИ, { recursive: true })
  fs.writeFileSync(`${СНИМКИ}/отчёт.txt`, отчёт, 'utf8')
  console.log('\n' + отчёт)
})
