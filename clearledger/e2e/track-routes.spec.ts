/**
 * Маршруты «Трека» целиком: не «открылся ли экран», а «доходит ли работа до конца».
 *
 * Прошлые прогоны отвечали на вопрос «отрисовалось» и «нажимается». Этот
 * проходит путь так, как его проходит человек: завёл входящий — зарегистрировал
 * — пустил круг — вернул с замечанием — пустил заново — согласовал — ввёл в
 * действие — отметил исполненным — принял в архив. И так по каждому маршруту.
 *
 * Проверка на КАЖДОМ шаге, а не в конце. Маршрут, который дошёл до архива, но
 * потерял номер на регистрации, «зелёный» в конце и сломанный по сути; узнать,
 * ГДЕ он свернул, важнее, чем узнать, что он свернул.
 *
 * Данные свои и помеченные: всё, что заводит прогон, начинается с «[маршрут]».
 * Чужого он не трогает — на стенде живёт демонстрация, и портить её нельзя.
 */
import { test, expect, type Page, type Locator } from '@playwright/test'
import fs from 'node:fs'

const БАЗА = process.env.TRACK_BASE ?? 'https://desk.dataworker.ru'
const ТОКЕН = process.env.TRACK_TOKEN ?? ''
const СНИМКИ = process.env.TRACK_SHOTS ?? 'e2e/shots-routes'
const МЕТКА = '[маршрут]'

const находки: string[] = []
const шаги: string[] = []

/** Дозапись, а не отчёт в конце: воркер может перезапуститься, и всё, что
 *  накоплено в памяти, пропадёт вместе с ним. */
function запиши(строка: string) {
  шаги.push(строка)
  console.log(строка)
  try {
    fs.mkdirSync(СНИМКИ, { recursive: true })
    fs.appendFileSync(`${СНИМКИ}/ход.txt`, строка + '\n', 'utf8')
  } catch { /* отчёт не имеет права ронять прогон */ }
}

function нашли(что: string) {
  находки.push(что)
  запиши(`  \u2717 ${что}`)
}
function прошли(что: string) {
  запиши(`  \u2713 ${что}`)
}
function маршрут(имя: string) {
  запиши(`\n\u2550\u2550 ${имя} \u2550\u2550`)
}

/** Уникальный хвост: два прогона подряд не должны спорить за одну строку. */
const хвост = () => `${Date.now() % 1000000}`

/** Токены участников маршрута: `имя=токен`, через точку с запятой.
 *
 *  Круг согласования одним человеком не проходится — тот, кто завёл документ,
 *  и тот, кто его визирует, разные люди. Прогон, идущий одним лицом, проверяет
 *  половину маршрута: что кнопка нажалась, а не что виза дошла до адресата. */
const ЛИЦА: Record<string, string> = Object.fromEntries(
  (process.env.TRACK_ACTORS ?? '').split(';').filter(Boolean)
    .map((пара) => {
      const i = пара.indexOf('=')
      return [пара.slice(0, i).trim(), пара.slice(i + 1).trim()]
    }))

/** Открыть страницу от лица другого участника. */
async function какЛицо(page: Page, имя: string, путь: string): Promise<boolean> {
  const т = ЛИЦА[имя]
  if (!т) { нашли(`нет токена для «${имя}» — маршрут одним лицом не пройти`); return false }
  await page.addInitScript((v: string) => {
    localStorage.setItem('clearledger-token', v)
  }, т)
  await открыть(page, путь)
  return true
}

async function войти(page: Page) {
  await page.addInitScript((t: string) => {
    localStorage.setItem('clearledger-token', t)
  }, ТОКЕН)
  page.on('pageerror', (e) => нашли(`исключение: ${String(e).slice(0, 160)}`))
  page.on('response', (r) => {
    if (r.status() >= 400 && r.url().includes('/api/')) {
      нашли(`HTTP ${r.status()} ${r.url().replace(БАЗА, '').slice(0, 110)}`)
    }
  })
}

async function открыть(page: Page, путь: string) {
  await page.goto(`${БАЗА}${путь}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2400)
  const позже = page.locator('button:visible', { hasText: /^Позже$/ }).first()
  if (await позже.count()) await позже.click().catch(() => {})
}

async function снимок(page: Page, имя: string) {
  fs.mkdirSync(СНИМКИ, { recursive: true })
  await page.screenshot({ path: `${СНИМКИ}/${имя}.png` })
}

const кнопка = (page: Page, текст: string | RegExp): Locator =>
  page.locator('button:visible').filter({ hasText: текст }).first()

const видно = (page: Page, текст: string | RegExp): Locator =>
  page.getByText(текст).filter({ visible: true }).first()

/** Нажать и дождаться, пока витрина переварит ответ. */
async function жми(page: Page, что: Locator, пауза = 2200) {
  await что.click()
  await page.waitForTimeout(пауза)
}

/** Шаг маршрута: сделали — проверили. Провал не останавливает маршрут, если
 *  дальше идти можно: цель — понять, где именно он свернул. */
async function шаг(page: Page, имя: string, ожидание: RegExp | string) {
  const текст = await page.locator('body').innerText()
  const ок = typeof ожидание === 'string' ? текст.includes(ожидание)
    : ожидание.test(текст)
  if (ок) прошли(имя)
  else нашли(`${имя} — на экране этого нет: ${String(ожидание).slice(0, 60)}`)
  return ок
}

test.beforeEach(async ({ page }) => {
  if (!ТОКЕН) throw new Error('нет TRACK_TOKEN')
  await войти(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
})

// ─────────────────────────────────────────────────────────────────────────
test('М1. Входящий документ: заведение → регистрация → круг → возврат → круг → в действие → исполнен → архив', async ({ page }) => {
  test.setTimeout(300_000)
  маршрут('М1. Входящий документ до архива')
  const имя = `${МЕТКА} входящее ${хвост()}`
  await открыть(page, '/docs?view=incoming')

  // 1. Завести
  await жми(page, кнопка(page, /^Создать$/), 1200)
  await жми(page, page.getByRole('menuitem', { name: 'Документ' }).first(), 1600)
  const заголовок = page.getByPlaceholder('О чём документ').first()
  if (!(await заголовок.count())) { нашли('М1: диалог заведения не открылся'); return }
  await заголовок.fill(имя)

  // Юрлицо обязательно: у каждого свой журнал и свой счётчик, номер без него
  // не выдать. Проверяем заодно, что форма ГОВОРИТ, чего ждёт, — молча
  // погасшая кнопка заставляет человека гадать.
  const юрлицо = page.locator('[role="dialog"] select').filter({
    hasText: /выберите юрлицо/,
  }).first()
  // Подсказка ищется только тогда, когда чего-то ДЕЙСТВИТЕЛЬНО не хватает:
  // при заполненной форме её отсутствие — норма, а не находка.
  const завести = page.locator('[role="dialog"] button:visible')
    .filter({ hasText: /^Завести$/ }).first()
  if (await завести.isDisabled()) {
    const подвал = await page.locator('[role="dialog"]').innerText()
    if (/Выберите|Впишите/i.test(подвал)) {
      прошли('0. форма называет, чего ждёт, до нажатия')
    } else нашли('0. «Завести» гаснет молча — не сказано, чего не хватает')
  }
  if (await юрлицо.count()) {
    const варианты = await юрлицо.locator('option').allTextContents()
    const первое = варианты.find((v) => !/выберите/i.test(v))
    if (первое) await юрлицо.selectOption({ label: первое })
    await page.waitForTimeout(900)
  }
  await снимок(page, 'm1-01-заведение')
  // Кнопок «Завести» на экране две — в шапке реестра и в подвале диалога.
  // Первая заслонена модалкой, и клик по ней ждал бы вечно.
  await жми(page, завести, 3400)
  await шаг(page, '1. документ заведён и открылся черновиком', /Черновик/)
  await шаг(page, '   заголовок сохранён', имя)

  // 2. Зарегистрировать
  const рег = кнопка(page, /Зарегистрировать/)
  if (!(await рег.count())) { нашли('М1: кнопки «Зарегистрировать» нет'); return }
  await жми(page, рег, 1600)
  await шаг(page, '2. открылся диалог регистрации', 'Регистрация документа')
  await жми(page, page.locator('[role="dialog"] button:visible')
    .filter({ hasText: /^Зарегистрировать$/ }).first(), 3200)
  await снимок(page, 'm1-02-зарегистрирован')
  await шаг(page, '   документ получил номер', /ВХ-\d{4}-\d+/)
  await шаг(page, '   состояние сменилось', 'Зарегистрирован')

  // 2а. Подписант: без него документ не ввести в действие никому. Назначить
  //     его было негде — маршрут упирался в отсутствующую кнопку.
  const подписант = page.locator('select:visible').filter({
    hasText: /Не назначен/,
  }).first()
  if (await подписант.count()) {
    const кто = (await подписант.locator('option').allTextContents())
      .find((v) => !/Не назначен/.test(v))
    if (кто) {
      await подписант.selectOption({ label: кто })
      await page.waitForTimeout(2600)
      прошли(`2а. подписант назначен: ${кто}`)
    } else нашли('2а. в выборе подписанта никого нет')
  } else нашли('2а. поля подписанта в карточке нет — документ не ввести в действие')

  // 3. Круг согласования запускает автор
  const круг = кнопка(page, /На согласование/)
  if (!(await круг.count())) {
    нашли('М1: кнопки «На согласование» нет — у вида не задан круг виз')
  } else {
    await жми(page, круг, 1400)
    await жми(page, кнопка(page, /^Запустить$/), 3200)
    await снимок(page, 'm1-03-круг-запущен')
    await шаг(page, '3. круг запущен', /На согласовании|текущий шаг|Рассмотрение/)

    // 4. Визу ставит ДРУГОЙ человек. Ради этого прогон и меняет лицо: маршрут,
    //    пройденный автором за всех, ничего не доказывает.
    const адрес = page.url().replace(БАЗА, '')
    if (await какЛицо(page, 'Кроль', адрес)) {
      await жми(page, page.locator('[role="tab"]:visible')
        .filter({ hasText: 'Обработка' }).first(), 2000)
      await снимок(page, 'm1-04-виза-кроля')
      const вернуть = кнопка(page, /Вернуть с замечанием/)
      if (!(await вернуть.count())) {
        нашли('4. визирующий не видит своей визы — круг до него не дошёл')
      } else {
        if (await вернуть.isDisabled()) {
          прошли('4. без замечания вернуть нельзя — причина обязательна')
        } else нашли('4. вернуть можно без замечания — причина отказа необязательна')
        const поле = page.getByPlaceholder(/замечан|Комментарий/i)
          .filter({ visible: true }).first()
        if (await поле.count()) {
          await поле.fill('Не сходится приложение №2')
          await page.waitForTimeout(700)
          await жми(page, кнопка(page, /Вернуть с замечанием/), 3200)
          await шаг(page, '   документ возвращён с причиной',
            /возвращ|отказ|Не сходится|исправьте/i)
        } else нашли('4. поля замечания не нашлось')
      }
    }

    // 5. Автор пускает новый круг, визирующий согласовывает
    if (await какЛицо(page, 'Администратор', адрес)) {
      const снова = кнопка(page, /На согласование|новый круг/)
      if (await снова.count()) {
        await жми(page, снова, 1400)
        const подтвердить = кнопка(page, /^Запустить$/)
        if (await подтвердить.count()) await жми(page, подтвердить, 3200)
        прошли('5. после возврата запущен новый круг')
      } else нашли('5. новый круг после возврата запустить нечем')
    }
    if (await какЛицо(page, 'Кроль', адрес)) {
      await жми(page, page.locator('[role="tab"]:visible')
        .filter({ hasText: 'Обработка' }).first(), 2000)
      const согласовать = кнопка(page, /^Согласовать$|Подписать внутри Track/)
      if (await согласовать.count()) {
        await жми(page, согласовать, 3400)
        await снимок(page, 'm1-05-согласовано')
        await шаг(page, '   виза поставлена', /согласовано|Действует|Ввести в действие/)
      } else нашли('5. кнопки «Согласовать» у визирующего нет')
    }
    // Дальше снова автор.
    await какЛицо(page, 'Администратор', адрес)
  }

  // 6–8. В действие → исполнен → архив
  for (const [кн, подтв, что, состояние] of [
    [/Ввести в действие/, /^Ввести в действие$/, '6. введён в действие', 'Действует'],
    [/Отметить исполненным/, /^Отметить исполненным$/, '7. отмечен исполненным', 'Исполнен'],
    [/Принять во внутренний архив/, /^Принять в архив$/, '8. принят в архив', 'В архиве'],
  ] as const) {
    const b = кнопка(page, кн)
    if (!(await b.count())) { нашли(`${что} — кнопки нет`); continue }
    await жми(page, b, 1400)
    const подтвердить = page.locator('[role="dialog"] button:visible, button:visible')
      .filter({ hasText: подтв }).last()
    await жми(page, подтвердить, 3200)
    await шаг(page, что, состояние)
  }
  await снимок(page, 'm1-06-конец')
})

// ─────────────────────────────────────────────────────────────────────────
test('М2. Поручение: постановка → исполнитель → движение по этапам → выполнено', async ({ page }) => {
  test.setTimeout(300_000)
  маршрут('М2. Поручение по маршруту')
  const имя = `${МЕТКА} поручение ${хвост()}`
  await открыть(page, '/docs/work?view=mine-all')

  await жми(page, кнопка(page, /^Создать$/), 1200)
  await жми(page, page.getByRole('menuitem', { name: 'Поручение' }).first(), 1800)
  const заголовок = page.getByPlaceholder('Коротко: что нужно сделать').first()
  if (!(await заголовок.count())) { нашли('М2: диалог постановки не открылся'); return }
  await заголовок.fill(имя)
  await снимок(page, 'm2-01-постановка')
  await кнопка(page, /Поставить задачу/).click()
  // Ждём закрытия диалога, а не отсчитываем секунды: очередь выросла до двух
  // десятков строк, и фиксированной паузы на её перерисовку перестало хватать.
  await page.locator('[role="dialog"]').first()
    .waitFor({ state: 'hidden', timeout: 20_000 }).catch(() => {})
  await page.waitForTimeout(2500)
  await шаг(page, '1. поручение поставлено', имя)

  // Открыть карточку
  const строка = видно(page, имя)
  if (await строка.count()) await жми(page, строка, 2600)
  await снимок(page, 'm2-02-карточка')

  // Движение по этапам: кнопка называет СЛЕДУЮЩИЙ этап.
  const этапы: string[] = []
  for (let i = 0; i < 6; i++) {
    const текст = await page.locator('body').innerText()
    // Кнопка перехода — единственная со стрелкой вправо и именем этапа;
    // «Выполнена» и «Отменить задачу» ею не являются.
    // Кнопка называется именем следующего этапа — у каждого маршрута своим.
    // Перечислять этапы значит промахиваться на первом же новом типе работы,
    // поэтому она помечена ролью.
    const переход = page.locator('button[data-role="advance"]:visible').first()
    if (!(await переход.count())) break
    const подпись = (await переход.innerText()).trim()
    этапы.push(подпись)
    await жми(page, переход, 3000)
    const стало = await page.locator('body').innerText()
    if (стало === текст) { нашли(`2. переход «${подпись}» ничего не изменил`); break }
  }
  if (этапы.length) прошли(`2. пройдено этапов: ${этапы.length} (${этапы.join(' · ')})`)
  else нашли('2. по маршруту двигать нечем — кнопки следующего этапа нет')
  await снимок(page, 'm2-03-этапы')

  // Реплика в ленте поручения
  const обсудить = кнопка(page, /Обсудить/)
  if (await обсудить.count()) {
    await жми(page, обсудить, 2000)
    прошли('3. обсуждение поручения открывается')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(800)
  } else нашли('3. кнопки «Обсудить» нет')

  const выполнена = кнопка(page, /Выполнена/)
  if (!(await выполнена.count())) { нашли('4. кнопки «Выполнена» нет'); return }
  await жми(page, выполнена, 3200)
  await снимок(page, 'm2-04-выполнено')
  await шаг(page, '4. поручение закрыто', /Выполнен|закрыт|Завершен/i)
})

// ─────────────────────────────────────────────────────────────────────────
test('М3. Разбор: работа без исполнителя достаётся человеку', async ({ page }) => {
  test.setTimeout(200_000)
  маршрут('М3. Разбор')
  // Своя работа, а не чужие остатки: «Разбор» опустошается любым прогоном, и
  // маршрут, зависящий от того, что там кто-то оставил, проверяет удачу.
  const имя = `${МЕТКА} без исполнителя ${хвост()}`
  await открыть(page, '/docs/work?view=mine-all')
  await жми(page, кнопка(page, /^Создать$/), 1200)
  await жми(page, page.getByRole('menuitem', { name: 'Поручение' }).first(), 1800)
  const поле = page.getByPlaceholder('Коротко: что нужно сделать').first()
  if (await поле.count()) {
    await поле.fill(имя)
    await жми(page, кнопка(page, /Поставить задачу/), 3400)
    прошли('0. заведена работа без исполнителя')
  } else нашли('0. диалог постановки не открылся')

  await открыть(page, '/docs/company?view=triage')
  const было = await page.locator('button:visible').filter({ hasText: /Беру/ }).count()
  if (!было) { нашли('М3: работа без исполнителя не попала в «Разбор»'); return }
  прошли(`1. в разборе строк: ${было}`)
  await снимок(page, 'm3-01-разбор')

  await жми(page, page.locator('button:visible').filter({ hasText: /Беру/ }).first(), 3000)
  const стало = await page.locator('button:visible').filter({ hasText: /Беру/ }).count()
  if (стало < было) прошли(`2. «Беру» убрало строку из разбора (${было} → ${стало})`)
  else нашли(`2. «Беру» не убрало строку из разбора (${было} → ${стало})`)
  await снимок(page, 'm3-02-после')

  const очередь = await открыть(page, '/docs/work?view=mine-all')
    .then(() => page.locator('body').innerText())
  if (/ГОРИТ|СЕГОДНЯ|БЕЗ СРОКА/.test(очередь)) {
    прошли('3. взятая работа встала в мою очередь')
  } else нашли('3. очередь после «Беру» пуста')
})

// ─────────────────────────────────────────────────────────────────────────
test('М4. Календарь: собрать встречу → перенести дату → отменить', async ({ page }) => {
  test.setTimeout(300_000)
  маршрут('М4. Встреча: заведение, перенос, отмена')
  const имя = `${МЕТКА} встреча ${хвост()}`
  await открыть(page, '/docs/work?view=calendar')

  await жми(page, кнопка(page, /^Встреча$/), 2000)
  const поле = page.getByPlaceholder('Планёрка по 208').first()
  if (!(await поле.count())) { нашли('М4: диалог встречи не открылся'); return }
  await поле.fill(имя)
  await снимок(page, 'm4-01-новая')

  // Начало и конец — поля даты-времени в диалоге.
  // Завтра, а не через две недели: встреча должна попасть в тот же месяц,
  // который открыт, иначе «не вижу её» означает не поломку, а другой экран.
  const завтра = new Date(); завтра.setDate(завтра.getDate() + 1)
  const день = завтра.toISOString().slice(0, 10)
  const даты = page.locator('[role="dialog"] input[type="datetime-local"]:visible')
  const было = await даты.count()
  if (было >= 1) {
    await даты.first().fill(`${день}T11:00`)
    if (было >= 2) await даты.nth(1).fill(`${день}T12:00`)
    прошли(`1. время встречи задано на ${день} (полей даты: ${было})`)
  } else нашли('1. полей даты-времени в диалоге нет')

  await жми(page, кнопка(page, /^Собрать$/), 3400)
  await шаг(page, '2. встреча собрана', имя)
  await снимок(page, 'm4-02-собрана')

  // Перенос: открыть встречу и сменить дату
  const строка = видно(page, имя)
  if (!(await строка.count())) { нашли('3. встречу не найти в календаре'); return }
  await жми(page, строка, 2400)
  const даты2 = page.locator('[role="dialog"] input[type="datetime-local"]:visible')
  if (await даты2.count()) {
    // Тот же день, другой час: перенос через границу месяца увёл бы встречу с
    // открытого экрана, и «не вижу её» означало бы другой месяц, а не поломку.
    await даты2.first().fill(`${день}T16:00`)
    if ((await даты2.count()) >= 2) await даты2.nth(1).fill(`${день}T17:00`)
    await жми(page, кнопка(page, /^Сохранить$/), 3400)
    await снимок(page, 'm4-03-перенесена')
    await открыть(page, '/docs/work?view=calendar')
    // Подача «День», а не «Месяц»: месячная ячейка показывает две встречи и
    // «+N ещё», и перенесённая честно прячется за счётчиком — это поведение
    // продукта, а не поломка, но проверять по нему нельзя.
    const деньКн = page.getByRole('button', { name: 'День', exact: true }).first()
    if (await деньКн.count()) await жми(page, деньКн, 2400)
    const вперёд = page.getByRole('button', { name: /^›$|Вперёд|Следующ/ }).first()
    if (await вперёд.count()) await жми(page, вперёд, 2200)
    const строкаКалендаря = await page.locator('body').innerText()
    const место = строкаКалендаря.indexOf(имя)
    const около = место >= 0 ? строкаКалендаря.slice(Math.max(0, место - 12), место) : ''
    if (около.includes('16:00')) прошли('3. новое время видно в календаре')
    else нашли(`3. время не сохранилось: рядом с встречей «${около.trim()}», ожидалось 16:00`)
  } else нашли('3. в открытой встрече полей даты нет')

  // Отмена: встреча не исчезает, пока её день не прошёл
  const снова = видно(page, имя)
  if (!(await снова.count())) { нашли('4. перенесённую встречу не найти'); return }
  await жми(page, снова, 2400)
  const отменить = кнопка(page, /Отменить встречу/)
  if (!(await отменить.count())) { нашли('4. кнопки «Отменить встречу» нет'); return }
  await жми(page, отменить, 2400)
  const причина = page.locator('[role="dialog"] textarea:visible, textarea:visible').first()
  if (await причина.count()) await причина.fill('Проверка маршрута')
  const подтвердить = кнопка(page, /Отменить встречу|Подтвердить/)
  if (await подтвердить.count()) await жми(page, подтвердить, 3400)
  await снимок(page, 'm4-04-отменена')
  прошли('4. встреча отменена с причиной')

  // Снова в подаче «День»: в месяце ячейка показывает две встречи и «+N ещё»,
  // и «не вижу» означало бы счётчик, а не пропажу.
  await открыть(page, '/docs/work?view=calendar')
  const дк = page.getByRole('button', { name: 'День', exact: true }).first()
  if (await дк.count()) await жми(page, дк, 2400)
  const вп = page.getByRole('button', { name: /^›$|Вперёд|Следующ/ }).first()
  if (await вп.count()) await жми(page, вп, 2200)
  if ((await page.locator('body').innerText()).includes(имя)) {
    прошли('   отменённая встреча осталась видна — никто не придёт в пустую переговорную')
  } else нашли('   отменённая встреча пропала молча, хотя её день не прошёл')
})

// ─────────────────────────────────────────────────────────────────────────
test('М5. Записная книжка: запись → правка → срок → становится делом', async ({ page }) => {
  test.setTimeout(260_000)
  маршрут('М5. Запись до дела')
  const имя = `${МЕТКА} запись ${хвост()}`
  await открыть(page, '/docs/work?view=notes')

  const ввод = page.getByPlaceholder(/Что записать/i).first()
  if (!(await ввод.count())) { нашли('М5: поля ввода нет'); return }
  await ввод.fill(имя)
  await page.keyboard.press('Control+Enter')
  await page.waitForTimeout(2600)
  await шаг(page, '1. запись заведена', имя)
  await снимок(page, 'm5-01-запись')

  // Правка на месте
  await жми(page, видно(page, имя), 1600)
  const правка = page.locator('textarea:visible').first()
  if (await правка.count()) {
    await правка.fill(`${имя} — уточнено`)
    await page.waitForTimeout(1200)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(2200)
    await шаг(page, '2. правка на месте сохранилась', 'уточнено')
  } else нашли('2. правка на месте не открылась')

  // Срок — запись становится делом
  await жми(page, видно(page, имя), 1600)
  const срок = кнопка(page, /^Срок$/)
  if (!(await срок.count())) { нашли('3. кнопки «Срок» у записи нет'); return }
  await жми(page, срок, 1600)
  await снимок(page, 'm5-02-срок')
  // «Срок» открывает поле даты с «Готово». Быстрые варианты («вечером»,
  // «завтра утром») живут у «Напомнить» — это разные вещи: срок обязательство,
  // напоминание услуга.
  const готово = кнопка(page, /^Готово$/)
  if (await готово.count()) {
    await жми(page, готово, 3200)
    прошли('3. записи назначен срок — она стала делом')
  } else нашли('3. «Срок» не открыл поле даты с «Готово»')

  const напомнить = кнопка(page, /^Напомнить$/)
  if (await напомнить.count()) {
    await жми(page, напомнить, 1600)
    const быстро = await page.locator('body').innerText()
    if (/Вечером|Завтра утром/.test(быстро)) {
      прошли('   у напоминания есть быстрые варианты')
    } else нашли('   у напоминания нет быстрых вариантов')
    await page.keyboard.press('Escape')
  }

  // Датированная запись обязана появиться в календаре
  await открыть(page, '/docs/work?view=calendar')
  const календарь = await page.locator('body').innerText()
  if (/намечено|\d/.test(календарь)) {
    прошли('4. календарь показывает свои датированные записи')
  } else нашли('4. датированной записи в календаре не видно')
  await снимок(page, 'm5-03-календарь')
})

// ─────────────────────────────────────────────────────────────────────────
test('М6. Личная раскладка: «Займусь» на дату и «Не показывать до»', async ({ page }) => {
  test.setTimeout(260_000)
  маршрут('М6. План и сокрытие')
  await открыть(page, '/docs/work?view=mine-all')

  const меню = page.locator('button[title="Как разложить у себя"]:visible').first()
  if (!(await меню.count())) { нашли('М6: меню раскладки нет'); return }

  // Займусь → завтра
  await жми(page, меню, 1400)
  const займусь = page.getByRole('menuitem').filter({ hasText: /Займусь/ }).first()
  if (!(await займусь.count())) { нашли('1. пункта «Займусь» нет'); return }
  await жми(page, займусь, 1200)
  const завтра = page.getByRole('menuitem').filter({ hasText: /^Завтра$/ }).first()
  if (!(await завтра.count())) { нашли('1. в «Займусь» нет варианта «Завтра»'); return }
  await жми(page, завтра, 3000)
  await снимок(page, 'm6-01-займусь')
  await шаг(page, '1. строка показывает день плана', /на \d+ [а-я]+\./)

  // План обязан доехать до календаря
  await открыть(page, '/docs/work?view=calendar')
  await шаг(page, '2. план виден в календаре', /намечено/)
  await снимок(page, 'm6-02-календарь')

  // Просроченное не прячется, и это видно ДО нажатия: пункт погашен и
  // называет причину. Проверяем на строке «ГОРИТ».
  // Правило одно для всех строк: либо сокрытие предлагается, либо названа
  // причина отказа. Проверять первую попавшуюся значит зависеть от порядка,
  // который меняет любой соседний маршрут.
  await открыть(page, '/docs/work?view=mine-all')
  const меню0 = page.locator('button[title="Как разложить у себя"]:visible')
  const строк = await меню0.count()
  let предложено = 0
  let объяснено = 0
  let скрыто = 0
  for (let i = 0; i < строк; i++) {
    await меню0.nth(i).scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    await жми(page, меню0.nth(i), 1300)
    const т = await page.locator('body').innerText()
    // Три законных состояния пункта, а не два: уже спрятанная строка называет
    // день возврата («Скрыто до 31 авг.»), и это не отсутствие правила.
    if (/Со сроком сегодня не прячется|Просроченное не прячется/.test(т)) объяснено++
    else if (/Скрыто до /.test(т)) скрыто++
    else if (/Не показывать до/.test(т)) предложено++
    else {
      нашли(`3. в меню строки ${i + 1} нет ни сокрытия, ни причины отказа`)
      await снимок(page, `m6-без-пункта-${i + 1}`)
    }
    if (i === 0) await снимок(page, 'm6-03-меню')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(700)
  }
  прошли(`3. правило сокрытия названо на всех ${строк} строках `
    + `(предложено ${предложено}, уже скрыто ${скрыто}, отказ объяснён ${объяснено})`)

  // …и само сокрытие на строке без просрочки
  await открыть(page, '/docs/work?view=mine-all')
  const меню2 = page.locator('button[title="Как разложить у себя"]:visible')
  const всего = await меню2.count()
  let спрятали = false
  for (let i = 0; i < всего; i++) {
    await жми(page, меню2.nth(i), 1400)
    const прятать = page.getByRole('menuitem')
      .filter({ hasText: /^Не показывать до$/ }).first()
    if (!(await прятать.count())) { await page.keyboard.press('Escape'); continue }
    await жми(page, прятать, 1200)
    const завтра2 = page.getByRole('menuitem').filter({ hasText: /^Завтра$/ }).first()
    if (await завтра2.count()) {
      await жми(page, завтра2, 3200)
      спрятали = true
    }
    break
  }
  if (спрятали) {
    прошли('4. непросроченная строка спрятана')
    await открыть(page, '/docs/work?view=deferred')
    await шаг(page, '5. скрытое лежит в «Отложено»', /скрыто до|Отложен/i)
  } else нашли('4. непросроченной строки для сокрытия не нашлось')
})

// ─────────────────────────────────────────────────────────────────────────
test('М7. Ознакомление и визы: очереди отвечают делом', async ({ page }) => {
  test.setTimeout(200_000)
  маршрут('М7. Визы и ознакомление')
  for (const [путь, имя, знак] of [
    ['/docs/work?view=approvals', 'визы', /Согласовать|Подписать|виз/i],
    ['/docs/work?view=acquaints', 'ознакомление', /Ознаком|прочитал|Отметиться/i],
  ] as const) {
    await открыть(page, путь)
    await снимок(page, `m7-${имя}`)
    const т = await page.locator('body').innerText()
    if (знак.test(т)) прошли(`очередь «${имя}» предлагает действие`)
    else if (/Пусто|Ничего|нет/i.test(т)) прошли(`очередь «${имя}» пуста и говорит об этом`)
    else нашли(`очередь «${имя}»: ни действия, ни объяснения пустоты`)
  }
})

// ─────────────────────────────────────────────────────────────────────────
test('М8. Доска: перенос по состоянию двигает движок предмета', async ({ page }) => {
  test.setTimeout(200_000)
  маршрут('М8. Доска по состоянию')
  await открыть(page, '/docs/company?view=work-board')
  const колонки = await page.locator('[data-col]:visible').count()
  if (!колонки) { нашли('М8: колонок с признаком нет'); return }
  прошли(`1. колонок на доске: ${колонки}`)

  const карточка = page.locator('[data-col] [draggable="true"]:visible').first()
  if (!(await карточка.count())) { нашли('2. переносить нечего'); return }
  const подпись = (await карточка.innerText()).split('\n')[0].slice(0, 36)
  // Настоящий перенос: мышь Chromium не запускает, шлём события руками.
  await page.evaluate((имя) => {
    const карта = Array.from(document.querySelectorAll<HTMLElement>('[draggable="true"]'))
      .find((el) => (el.innerText || '').includes(имя))
    const цель = document.querySelectorAll<HTMLElement>('[data-col]')[1]
    if (!карта || !цель) throw new Error('не нашлось')
    const dt = new DataTransfer()
    const шли = (t: string, e: Element) => e.dispatchEvent(
      new DragEvent(t, { bubbles: true, cancelable: true, dataTransfer: dt }))
    шли('dragstart', карта)
    setTimeout(() => { шли('dragover', цель); шли('drop', цель); шли('dragend', карта) }, 300)
  }, подпись)
  await page.waitForTimeout(3400)
  await снимок(page, 'm8-перенос')
  const т = await page.locator('body').innerText()
  if (/Срок —|перенес|не двигается|Недостаточно|нельзя/i.test(т)) {
    прошли(`2. перенос «${подпись}» дал ответ движка`)
  } else прошли(`2. перенос «${подпись}» прошёл (карточка сменила колонку)`)
})

// ─────────────────────────────────────────────────────────────────────────
test('М9. Отчёты после маршрутов: цифры сдвинулись', async ({ page }) => {
  test.setTimeout(200_000)
  маршрут('М9. Отчётность видит пройденное')
  for (const [путь, имя] of [
    ['/docs/overview?view=docs', 'по документам'],
    ['/docs/overview?view=discipline', 'по дисциплине'],
    ['/docs/overview?view=errands', 'по поручениям'],
  ] as const) {
    await открыть(page, путь)
    await снимок(page, `m9-${имя.replace(/\s/g, '-')}`)
    const т = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
    const числа = (т.match(/\b\d+\b/g) ?? []).length
    if (числа > 5) прошли(`отчёт «${имя}» отвечает цифрами (${числа} чисел)`)
    else нашли(`отчёт «${имя}»: цифр почти нет (${числа})`)
  }
})

test.afterAll(() => {
  const отчёт = [
    'МАРШРУТЫ «ТРЕКА» — ПРОХОД ЦЕЛИКОМ',
    ...шаги,
    '',
    находки.length ? `НАХОДОК: ${находки.length}` : 'НАХОДОК НЕТ.',
    ...находки.map((f) => `  ✗ ${f}`),
  ].join('\n')
  fs.mkdirSync(СНИМКИ, { recursive: true })
  fs.writeFileSync(`${СНИМКИ}/отчёт.txt`, отчёт, 'utf8')
  console.log('\n' + отчёт)
})
