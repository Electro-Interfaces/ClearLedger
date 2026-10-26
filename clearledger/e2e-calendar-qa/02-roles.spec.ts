import { expect, test } from '@playwright/test'
import { authFile, апи, имя, календарь, кто, снимок, токен, войти, пространства } from './helpers'

/**
 * Роли вокруг одной встречи: организатор правит, приглашённый отвечает,
 * коллега видит только то, что ему открыли, посторонний — ничего.
 */
const ДЕНЬ = '2026-11-12'
const company = пространства['qa-cal-energy'].companyId

test.describe('путь человека', () => {
  test('R-01 вход формой работает и ведёт в пространство', async ({ page }) => {
    test.setTimeout(240_000)
    // Одна повторная попытка: лимит входов (10/мин на адрес) мог быть израсходован
    // подготовкой сессий этого же прогона. Это свойство стенда, а не продукта.
    try {
      await войти(page, 'qa-cal-energy', 'required')
    } catch {
      await page.waitForTimeout(65_000)
      await войти(page, 'qa-cal-energy', 'required')
    }
    await page.goto(календарь({ calendarMode: 'agenda', date: ДЕНЬ }))
    await expect(page.getByRole('heading', { name: 'Календарь' })).toBeVisible()
  })
})

/** Встречу собирает организатор; остальные роли работают с ней через API+UI. */
async function встреча(request, параметры: Record<string, unknown> = {}) {
  const t = await токен(request, 'qa-cal-energy', 'organizer')
  const название = имя('роли')
  const r = await апи(request, t, '/api/work/calendar', {
    method: 'POST',
    data: {
      company_id: company,
      title: название,
      starts_at: '2026-11-12T08:00:00Z',
      ends_at: '2026-11-12T09:00:00Z',
      attendee_ids: [кто('qa-cal-energy', 'required').id],
      visibility: 'private',
      ...параметры,
    },
  })
  expect(r.status(), await r.text()).toBe(201)
  return { id: (await r.json()).id as string, название, t }
}

test.describe('приглашённый', () => {
  test.use({ storageState: authFile('qa-cal-energy', 'required') })

  test('R-02 ответ участника сразу виден в карточке и организатору', async ({ page, request }) => {
    const { id, t } = await встреча(request)
    await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ, event: id }))
    const карточка = page.getByRole('dialog')
    await expect(карточка).toBeVisible()
    await карточка.getByRole('button', { name: 'Буду', exact: true }).click()
    await expect(карточка.getByRole('button', { name: 'Буду', exact: true }))
      .toHaveAttribute('aria-pressed', 'true')
    await снимок(page, 'r02-response.png')

    const детали = await (await апи(request, t, `/api/work/calendar/${id}?company_id=${company}`)).json()
    const мой = детали.attendees.find((a) => a.user_id === кто('qa-cal-energy', 'required').id)
    expect(мой.response, 'организатор видит согласие').toBe('accepted')
  })

  test('R-03 приглашённый не правит встречу, но может предложить другое время',
    async ({ page, request }) => {
      const { id, t } = await встреча(request)
      await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ, event: id }))
      const карточка = page.getByRole('dialog')
      await expect(карточка.getByLabel('О чём')).toBeDisabled()
      await expect(карточка.getByRole('button', { name: 'Сохранить' })).toHaveCount(0)
      await expect(карточка.getByRole('button', { name: 'Отменить встречу' })).toHaveCount(0)
      await карточка.getByRole('button', { name: 'Другое время' }).click()
      await карточка.getByRole('button', { name: 'Отправить' }).click()
      await expect(page.getByText('Предложение отправлено организатору')).toBeVisible()

      const детали = await (await апи(request, t, `/api/work/calendar/${id}?company_id=${company}`)).json()
      const мой = детали.attendees.find((a) => a.user_id === кто('qa-cal-energy', 'required').id)
      expect(мой.proposed_starts_at, 'встречное предложение сохранено').toBeTruthy()
    })
})

test.describe('организатор', () => {
  test.use({ storageState: authFile('qa-cal-energy', 'organizer') })

  test('R-04 перенос встречи сбрасывает согласия участников', async ({ page, request }) => {
    const { id, t } = await встреча(request)
    // Участник согласился
    const tu = await токен(request, 'qa-cal-energy', 'required')
    const ответ = await апи(request, tu, `/api/work/calendar/${id}`,
      { method: 'POST', data: { company_id: company, response: 'accepted' } })
    expect(ответ.ok(), await ответ.text()).toBeTruthy()

    await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ, event: id }))
    const карточка = page.getByRole('dialog')
    await карточка.getByLabel('Время начала').fill('15:00')
    await expect(карточка.getByText(/согласия участников сбросятся/)).toBeVisible()
    await карточка.getByRole('button', { name: 'Сохранить' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    const детали = await (await апи(request, t, `/api/work/calendar/${id}?company_id=${company}`)).json()
    const участник = детали.attendees.find((a) => a.user_id === кто('qa-cal-energy', 'required').id)
    expect(участник.response, 'после переноса ответ снова ждут').toBe('pending')
  })

  test('R-05 встречное предложение видно организатору отдельным блоком', async ({ page, request }) => {
    const { id } = await встреча(request)
    const tu = await токен(request, 'qa-cal-energy', 'required')
    const r = await апи(request, tu, `/api/work/calendar/${id}`, {
      method: 'POST',
      data: {
        company_id: company,
        propose_starts_at: '2026-11-12T12:00:00Z', propose_ends_at: '2026-11-12T13:00:00Z',
      },
    })
    expect(r.ok(), await r.text()).toBeTruthy()
    await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ, event: id }))
    const карточка = page.getByRole('dialog')
    await expect(карточка.getByText('Предложили другое время')).toBeVisible()
    await карточка.getByRole('button', { name: 'Перенести на это' }).click()
    await expect(карточка.getByLabel('Время начала')).toHaveValue('15:00')
  })
})

test.describe('круг видимости', () => {
  test.use({ storageState: authFile('qa-cal-energy', 'colleague') })

  test('R-06 встречу компании коллега видит, закрытую и личную — нет', async ({ page, request }) => {
    const общая = await встреча(request, { visibility: 'company', attendee_ids: [] })
    const закрытая = await встреча(request, { visibility: 'private', attendee_ids: [] })
    const личная = await встреча(request, { visibility: 'personal', attendee_ids: [] })
    const tc = await токен(request, 'qa-cal-energy', 'colleague')

    await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ, calendarScope: 'company' }))
    await expect(page.getByRole('button', { name: new RegExp(общая.название) })).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(закрытая.название) })).toHaveCount(0)
    await expect(page.getByRole('button', { name: new RegExp(личная.название) })).toHaveCount(0)
    await снимок(page, 'r06-company-scope.png')

    const чтение = await апи(request, tc, `/api/work/calendar/${общая.id}?company_id=${company}`)
    expect(чтение.status(), 'общая встреча читается сотрудником компании').toBe(200)
    const закрыто = await апи(request, tc, `/api/work/calendar/${закрытая.id}?company_id=${company}`)
    expect([403, 404], 'закрытая встреча недоступна постороннему для неё сотруднику')
      .toContain(закрыто.status())
    const лично = await апи(request, tc, `/api/work/calendar/${личная.id}?company_id=${company}`)
    expect([403, 404]).toContain(лично.status())

    // Просмотр не даёт права отвечать и править
    const правка = await апи(request, tc, `/api/work/calendar/${общая.id}`,
      { method: 'POST', data: { company_id: company, title: 'подмена' } })
    expect(правка.status(), 'чужую встречу сотрудник не меняет').toBeGreaterThanOrEqual(400)
  })
})

test.describe('посторонний', () => {
  test.use({ storageState: authFile('qa-cal-outside', 'outsider') })

  test('R-07 посторонняя организация не получает встречу по прямой ссылке',
    async ({ page, request }) => {
      const общая = await встреча(request, { visibility: 'company', attendee_ids: [] })
      const to = await токен(request, 'qa-cal-outside', 'outsider')
      const r = await апи(request, to, `/api/work/calendar/${общая.id}?company_id=${company}`)
      expect(r.status(), 'чужое пространство закрыто').toBeGreaterThanOrEqual(400)

      await page.goto(календарь({ calendarMode: 'day', date: ДЕНЬ, event: общая.id }))
      await expect(page.getByText(/Не удалось открыть встречу|нет доступа/)).toBeVisible()
      await снимок(page, 'r07-outsider.png')
    })
})
