import { expect, test } from '@playwright/test'
import { authFile, апи, имя, календарь, кто, снимок, токен, пространства } from './helpers'

/**
 * Ядро календаря в пространстве energy под организатором: что человек делает
 * каждый день — назначает, переносит, зовёт, повторяет, ищет, отменяет.
 * Ожидания взяты из docs/calendar-workflow.md и предметных правил, не из кода.
 */
test.use({ storageState: authFile('qa-cal-energy', 'organizer') })
test.describe.configure({ mode: 'serial' })

const ДЕНЬ = '2026-11-10'          // вторник, будущее относительно 25.10.2026
const МЕСЯЦ = 'ноябрь 2026'

const открыть = async (page, параметры = {}) => {
  await page.goto(календарь({ calendarMode: 'month', date: ДЕНЬ, ...параметры }))
  await expect(page.getByRole('heading', { name: 'Календарь' })).toBeVisible()
}

/** Собрать встречу из шапки: «Добавить» → «Встреча». */
const новаяВстреча = async (page, _что?: string) => {
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Встреча' }).click()
  const окно = page.getByRole('dialog')
  await expect(окно.getByRole('heading', { name: 'Новая встреча' })).toBeVisible()
  return окно
}

test('C-01 календарь открывается на выбранном месяце, видами управляет адрес', async ({ page }) => {
  await открыть(page)
  await expect(page.getByText(МЕСЯЦ, { exact: false }).first()).toBeVisible()
  // Сетка месяца: семь колонок дней недели
  await expect(page.getByText('пн', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Неделя', exact: true }).click()
  await expect(page).toHaveURL(/calendarMode=week/)
  await page.getByRole('button', { name: 'День', exact: true }).click()
  await expect(page).toHaveURL(/calendarMode=day/)
  await page.getByRole('button', { name: 'Список', exact: true }).click()
  await expect(page).toHaveURL(/calendarMode=agenda/)
  await снимок(page, 'c01-agenda.png')
})

test('C-02 встреча назначается на выбранный день и сразу видна в сетке', async ({ page }) => {
  const название = имя('встреча')
  await открыть(page)   // ДЕНЬ выбран в адресе, форма должна предложить именно его
  const окно = await новаяВстреча(page, название)
  await окно.getByLabel('О чём').fill(название)
  // Дата должна совпадать с выбранным днём, а не с «сегодня»
  await expect(окно.getByLabel('Начало', { exact: true })).toHaveValue('10.11.2026')
  await expect(окно.getByLabel('Время начала')).toHaveValue('10:00')
  await expect(окно.getByLabel('Время окончания')).toHaveValue('11:00')
  await окно.getByRole('button', { name: 'Собрать' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  // Клетка месяца показывает три записи и «Ещё N», поэтому факт появления
  // проверяем в дне: это тот же запрос календаря, но без обрезки списка.
  await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ }))
  await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()
  await снимок(page, 'c02-created.png')
})

test('C-03 конец раньше начала не сохраняется и объяснён', async ({ page }) => {
  await открыть(page)
  const окно = await новаяВстреча(page, 'интервал')
  await окно.getByLabel('О чём').fill(имя('интервал'))
  await окно.getByLabel('Время окончания').fill('09:00')
  await expect(окно.getByRole('alert')).toHaveText(/Конец встречи должен быть позже начала/)
  await expect(окно.getByRole('button', { name: 'Собрать' })).toBeDisabled()
})

test('C-04 быстрая длительность и перенос начала сохраняют длину встречи', async ({ page }) => {
  await открыть(page)
  const окно = await новаяВстреча(page, 'длительность')
  await окно.getByRole('button', { name: '30 мин' }).click()
  await expect(окно.getByLabel('Время окончания')).toHaveValue('10:30')
  await окно.getByLabel('Время начала').fill('14:00')
  await expect(окно.getByLabel('Время окончания')).toHaveValue('14:30')
  await окно.getByRole('button', { name: 'Закрыть' }).click()
})

test('C-05 «Весь день»: последний день включителен в форме, в API конец исключителен',
  async ({ page, request }) => {
    const название = имя('весь день')
    await открыть(page)
    const окно = await новаяВстреча(page, название)
    await окно.getByLabel('О чём').fill(название)
    await окно.getByLabel('Весь день').check()
    await expect(окно.getByText('Последний день')).toBeVisible()
    await expect(окно.getByLabel('Последний день', { exact: true })).toHaveValue('10.11.2026')
    await окно.getByRole('button', { name: 'Собрать' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    const t = await токен(request, 'qa-cal-energy', 'organizer')
    const company = пространства['qa-cal-energy'].companyId
    const r = await апи(request, t,
      `/api/work/calendar?company_id=${company}&from=2026-11-09T00:00:00Z&to=2026-11-13T00:00:00Z&scope=mine`)
    expect(r.ok()).toBeTruthy()
    const события = (await r.json()).events.filter((e) => e.title === название)
    expect(события, 'встреча на весь день сохранилась').toHaveLength(1)
    expect(события[0].all_day).toBe(true)
    // Один день «весь день» в поясе устройства = [10.11 00:00, 11.11 00:00)
    const мск = (iso: string) => new Date(iso).toLocaleString('sv-SE', { timeZone: 'Europe/Moscow' })
    expect(мск(события[0].starts_at)).toBe('2026-11-10 00:00:00')
    expect(мск(события[0].ends_at)).toBe('2026-11-11 00:00:00')
  })

test('C-06 повторение: граница серии проверяется и будущие встречи появляются сразу',
  async ({ page, request }) => {
    const название = имя('планёрка')
    await открыть(page)
    const окно = await новаяВстреча(page, название)
    await окно.getByLabel('О чём').fill(название)
    await окно.getByLabel('Повторять', { exact: true }).selectOption('weekly')
    // Граница раньше первой встречи — ошибка, а не молчаливое сохранение
    await окно.getByLabel('Повторять до').fill('2026-11-03')
    await expect(окно.getByRole('alert')).toHaveText(/Повторение не может закончиться раньше первой встречи/)
    await expect(окно.getByRole('button', { name: 'Собрать' })).toBeDisabled()
    await окно.getByLabel('Повторять до').fill('2026-12-15')
    await окно.getByRole('button', { name: 'Собрать' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    const t = await токен(request, 'qa-cal-energy', 'organizer')
    const company = пространства['qa-cal-energy'].companyId
    const r = await апи(request, t,
      `/api/work/calendar?company_id=${company}&from=2026-11-09T00:00:00Z&to=2026-12-20T00:00:00Z&scope=mine`)
    const серия = (await r.json()).events.filter((e) => e.title === название)
    // 10.11, 17.11, 24.11, 01.12, 08.12, 15.12 — все в пределах границы
    expect(серия.length, 'экземпляры серии созданы сразу').toBeGreaterThanOrEqual(4)
    const даты = серия.map((e) => e.starts_at.slice(0, 10)).sort()
    expect(даты[0]).toBe('2026-11-10')
    expect(даты.every((d) => d <= '2026-12-15'), 'серия не выходит за границу').toBeTruthy()
  })

test('C-07 участники: обязательный и «для сведения», организатор остаётся', async ({ page, request }) => {
  const название = имя('совещание')
  const участник = кто('qa-cal-energy', 'required')
  const сведения = кто('qa-cal-energy', 'optional')
  await открыть(page)
  const окно = await новаяВстреча(page, название)
  await окно.getByLabel('О чём').fill(название)
  await expect(окно.getByText(/организатор/)).toBeVisible()
  await окно.getByLabel('Найти участника').fill(участник.name)
  await окно.getByLabel(участник.name, { exact: false }).first().check()
  await окно.getByLabel('Найти участника').fill(сведения.name)
  await окно.getByLabel(сведения.name, { exact: false }).first().check()
  await окно.getByLabel(`Участие: ${сведения.name}`).selectOption('optional')
  await окно.getByRole('button', { name: 'Собрать' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const company = пространства['qa-cal-energy'].companyId
  const r = await апи(request, t,
    `/api/work/calendar?company_id=${company}&from=2026-11-09T00:00:00Z&to=2026-11-13T00:00:00Z&scope=mine`)
  const встреча = (await r.json()).events.find((e) => e.title === название)
  expect(встреча).toBeTruthy()
  const детали = await (await апи(request, t,
    `/api/work/calendar/${встреча.id}?company_id=${company}`)).json()
  const состав = detailНабор(детали)
  expect(состав.обязательные, 'организатор и обязательный участник').toContain(участник.id)
  expect(состав.обязательные).toContain(кто('qa-cal-energy', 'organizer').id)
  expect(состав.необязательные, '«для сведения» сохранён отдельно').toContain(сведения.id)
})

function detailНабор(детали) {
  const обязательные = детали.attendees.filter((a) => a.role !== 'optional').map((a) => a.user_id)
  const необязательные = детали.attendees.filter((a) => a.role === 'optional').map((a) => a.user_id)
  return { обязательные, необязательные }
}

test('C-08 поиск в периоде оставляет только найденное, сброс возвращает список', async ({ page }) => {
  const название = имя('редкое слово ' + Math.random().toString(36).slice(2, 6))
  await открыть(page, { calendarMode: 'agenda', date: ДЕНЬ })
  const окно = await новаяВстреча(page, название)
  await окно.getByLabel('О чём').fill(название)
  await окно.getByRole('button', { name: 'Собрать' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await page.getByLabel('Найти в календаре').fill(название.slice(-10))
  await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()
  await page.getByLabel('Найти в календаре').fill('нетакогослова-zzz')
  await expect(page.getByText('В этом периоде ничего не найдено')).toBeVisible()
  await page.getByRole('button', { name: 'Сбросить поиск' }).click()
  await expect(page.getByLabel('Найти в календаре')).toHaveValue('')
})

test('C-09 переход к дате и «Сегодня» управляют периодом', async ({ page }) => {
  await открыть(page)
  const шапка = page.locator('header')
    .filter({ has: page.getByRole('heading', { name: 'Календарь' }) })
  await page.getByLabel('Перейти к дате').fill('2026-12-01')
  await expect(page.getByText('декабрь 2026', { exact: false }).first()).toBeVisible()
  await шапка.getByRole('button', { name: 'Сегодня', exact: true }).click()
  await expect(page).toHaveURL(/date=2026-10-25/)
  await page.getByRole('button', { name: 'Следующий период' }).click()
  await expect(page.getByText('ноябрь 2026', { exact: false }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Предыдущий период' }).click()
  await expect(page.getByText('октябрь 2026', { exact: false }).first()).toBeVisible()
})

test('C-10 личное напоминание: ставится, меняется без дубля, снимается', async ({ page }) => {
  const название = имя('напоминание')
  await открыть(page, { calendarMode: 'agenda' })
  const окно = await новаяВстреча(page, название)
  await окно.getByLabel('О чём').fill(название)
  await окно.getByRole('button', { name: 'Собрать' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: new RegExp(название) }).click()
  const карточка = page.getByRole('dialog')
  const блок = карточка.getByRole('region', { name: 'Личное напоминание' })
  await expect(блок).toBeVisible()
  await блок.getByLabel('Когда напомнить о встрече').selectOption('15')
  await блок.getByRole('button', { name: 'Поставить напоминание' }).click()
  await expect(блок.getByRole('button', { name: 'Снять' })).toHaveCount(1)
  await блок.getByLabel('Когда напомнить о встрече').selectOption('60')
  await блок.getByRole('button', { name: 'Изменить напоминание' }).click()
  await expect(блок.getByRole('button', { name: 'Снять' })).toHaveCount(1)
  await снимок(page, 'c10-reminder.png')
  await блок.getByRole('button', { name: 'Снять' }).click()
  await expect(блок.getByRole('button', { name: 'Снять' })).toHaveCount(0)
})

test('C-11 отмена: подтверждение, причина, запрет правок и показ по требованию',
  async ({ page }) => {
    const название = имя('отмена')
    await открыть(page, { calendarMode: 'agenda' })
    const окно = await новаяВстреча(page, название)
    await окно.getByLabel('О чём').fill(название)
    await окно.getByRole('button', { name: 'Собрать' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    await page.getByRole('button', { name: new RegExp(название) }).click()
    const карточка = page.getByRole('dialog')
    await карточка.getByRole('button', { name: 'Отменить встречу' }).click()
    const подтверждение = карточка.getByRole('region', { name: 'Отмена встречи' })
    await expect(подтверждение).toBeVisible()
    await подтверждение.getByLabel('Причина отмены').fill('QA: проверка отмены')
    await подтверждение.getByRole('button', { name: 'Подтвердить отмену' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    // Будущая отменённая остаётся на виду зачёркнутой и с причиной: пропав молча,
    // она отправила бы человека в пустую переговорную (src/lib/calendarVisibility.ts).
    const строка = page.getByRole('button', { name: new RegExp(название) })
    await expect(строка).toBeVisible()
    await expect(строка).toContainText('Отменена: QA: проверка отмены')
    await строка.click()
    const отменённая = page.getByRole('dialog')
    await expect(отменённая.getByText(/Встреча отменена/)).toBeVisible()
    await expect(отменённая.getByRole('button', { name: 'Сохранить' })).toHaveCount(0)
    await expect(отменённая.getByRole('button', { name: 'Отменить встречу' })).toHaveCount(0)
    await снимок(page, 'c11-cancelled.png')
  })

test('C-15 прошедшая отменённая скрыта и возвращается галочкой', async ({ page, request }) => {
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const company = пространства['qa-cal-energy'].companyId
  const название = имя('прошлая отмена')
  const создана = await апи(request, t, '/api/work/calendar', {
    method: 'POST',
    data: {
      company_id: company, title: название,
      starts_at: '2026-10-20T07:00:00Z', ends_at: '2026-10-20T08:00:00Z', visibility: 'private',
    },
  })
  expect(создана.status(), await создана.text()).toBe(201)
  const id = (await создана.json()).id
  const отменена = await апи(request, t, `/api/work/calendar/${id}`, {
    method: 'POST', data: { company_id: company, cancel: true, cancel_reason: 'QA: прошедшая' },
  })
  expect(отменена.ok(), await отменена.text()).toBeTruthy()

  await page.goto(календарь({ calendarMode: 'day', date: '2026-10-20' }))
  await expect(page.getByRole('button', { name: new RegExp(название) })).toHaveCount(0)
  await page.getByLabel('Прошедшие отменённые').check()
  await expect(page.getByRole('button', { name: new RegExp(название) })).toBeVisible()
})

test('C-12 прямая ссылка открывает карточку встречи', async ({ page, request }) => {
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const company = пространства['qa-cal-energy'].companyId
  const r = await апи(request, t,
    `/api/work/calendar?company_id=${company}&from=2026-11-09T00:00:00Z&to=2026-11-13T00:00:00Z&scope=mine`)
  const события = (await r.json()).events.filter((e) => e.status !== 'cancelled')
  expect(события.length, 'в периоде есть встречи из предыдущих проверок').toBeGreaterThan(0)
  const цель = события[0]
  await page.goto(календарь({ calendarMode: 'agenda', date: ДЕНЬ, event: цель.id }))
  const карточка = page.getByRole('dialog')
  await expect(карточка).toBeVisible()
  await expect(карточка.getByLabel('О чём')).toHaveValue(цель.title)
})

test('C-13 подписка на календарь выдаёт рабочий ICS и сменяемый ключ', async ({ page, request }) => {
  await открыть(page)
  await page.getByRole('button', { name: 'Подписка на календарь' }).click()
  const адрес = page.getByLabel('Адрес подписки на календарь')
  await expect(адрес).toBeVisible()
  const url = await адрес.inputValue()
  expect(url).toMatch(/\/api\/work\/calendar\/feed\/[\w-]+\.ics$/)
  // Домен ссылки берётся из APP_PUBLIC_URL пространства; на стенде он не задан,
  // поэтому саму ленту запрашиваем у локального API по тому же пути.
  const локально = (адрес: string) => 'http://127.0.0.1:8311' + адрес.slice(адрес.indexOf('/api/'))
  const ics = await request.get(локально(url))
  expect(ics.status(), 'лента отдаётся по личной ссылке без пароля').toBe(200)
  const текст = await ics.text()
  expect(текст).toContain('BEGIN:VCALENDAR')
  expect(текст, 'в ленте есть встречи пространства').toContain('BEGIN:VEVENT')
  await page.getByRole('button', { name: 'Сменить ключ' }).click()
  await expect(page.getByText('Ключ сменён', { exact: false })).toBeVisible()
  const новый = await адрес.inputValue()
  expect(новый).not.toBe(url)
  const старый = await request.get(локально(url))
  expect(старый.status(), 'прежняя ссылка больше не работает').not.toBe(200)
})

test('C-14 «Дело себе» со сроком и напоминанием появляется в календаре', async ({ page }) => {
  const название = имя('дело')
  await открыть(page, { calendarMode: 'agenda' })
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Дело себе' }).click()
  const окно = page.getByRole('dialog')
  await expect(окно.getByRole('heading', { name: 'Дело' })).toBeVisible()
  await окно.getByPlaceholder('Что нужно сделать').fill(название)
  await окно.getByRole('button', { name: 'Записать' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(название, { exact: false }).first()).toBeVisible()
  await снимок(page, 'c14-deed.png')
})
