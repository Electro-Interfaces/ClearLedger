/**
 * Единый список работы: документы и поручения одной лентой (этап 13б).
 *
 * Отдельный сервис, а не ветка в `docsService`/`tasksService`: у ленты своя
 * ручка и своя проекция, и приписать её к одному из контуров значило бы сказать,
 * что она принадлежит ему, — а она общая.
 */
import { get, post } from './apiClient'

/** Колонка общей оси состояния. Порядок — порядок движения работы. */
export type WorkState = 'new' | 'in_work' | 'approval' | 'external' | 'done'

export interface WorkColumn { code: WorkState; name: string }

/** Строка работы: документ или поручение, приведённые к общему виду. */
export interface WorkItem {
  id: string
  /** `doc` — документ, `task` — поручение. Род, а не тип: тип внутри рода. */
  kind: 'doc' | 'task'
  /** Как предмет называют вслух: «TF-42», «№17», «Вх-88», «черновик». */
  key: string
  title: string
  type: string | null
  /** Точная стадия внутри колонки — у поручения; у документа пусто. */
  stage: string | null
  state: WorkState
  state_name: string
  status: string
  responsible: string | null
  responsible_id: string | null
  author: string | null
  due_at: string | null
  overdue: boolean
  object_id: string | null
  object: string | null
  project: string | null
  project_id: string | null
  priority: string | null
  labels: { id: string; name: string; color: string }[]
  updated_at: string | null
  /** Как ЭТОТ человек разложил предмет у себя. `null` — не разложен, и это
   *  нормальное состояние. Приезжает вместе со строкой, одним запросом на всю
   *  страницу: без отметки действия раскладки в списках работали вслепую, а
   *  доска по личной оси не смогла бы построить колонки. */
  mark: PersonalMark | null
}

export interface WorkQueryResult {
  parsed: Record<string, string>
  unknown: string[]
  text: string | null
}

export interface WorkFilters {
  kind?: 'doc' | 'task'
  scope?: 'open' | 'mine' | 'assigned' | 'done' | 'all'
  state?: WorkState | string
  typeId?: string
  projectId?: string
  assigneeId?: string
  authorId?: string
  objectId?: string
  /** Предмет работы: `site:<uuid>`, `contract:<uuid>`, `object:<ключ>`. */
  ref?: string
  labelId?: string
  q?: string
  query?: string
  dueTo?: string
  sort?: string
  limit?: number
  offset?: number
}

export async function listWork(companyId: string, opts?: WorkFilters) {
  return get<{
    work: WorkItem[]; total: number; limit: number; offset: number
    columns: WorkColumn[]; query?: WorkQueryResult
  }>('/api/work', {
    company_id: companyId,
    kind: opts?.kind || undefined,
    scope: opts?.scope || 'open',
    state: opts?.state || undefined,
    type_id: opts?.typeId || undefined,
    project_id: opts?.projectId || undefined,
    assignee_id: opts?.assigneeId || undefined,
    author_id: opts?.authorId || undefined,
    object_id: opts?.objectId || undefined,
    ref: opts?.ref || undefined,
    label_id: opts?.labelId || undefined,
    q: opts?.q || undefined,
    query: opts?.query || undefined,
    due_to: opts?.dueTo || undefined,
    sort: opts?.sort || undefined,
    limit: opts?.limit ?? undefined,
    offset: opts?.offset || undefined,
  })
}

/** Сколько работы в каждой колонке: заголовки доски и счётчики разделов. */
export async function workSummary(companyId: string) {
  return get<{
    columns: (WorkColumn & { docs: number; tasks: number; total: number })[]
  }>('/api/work/summary', { company_id: companyId })
}

/** Куда ведёт строка работы: карточка живёт в своём контуре. */
export function workHref(item: WorkItem): string {
  return item.kind === 'doc'
    ? `/docs?view=all&doc=${item.id}`
    : `/docs/company?view=errands&task=${item.id}`
}

/** Сегодняшнее число в местном виде `YYYY-MM-DD` — им сервер помечает день.
 *  Через `toISOString` считать нельзя: у Владивостока это уже завтра. */
export function todayKey(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Строка очереди «На мне»: предмет плюс род действия, которого он от меня ждёт. */
export interface MyWorkItem {
  kind: 'doc' | 'task'
  id: string
  /** `approve` — виза, `acquaint` — ознакомление, `do` — работа,
   *  `unassigned` — своё поручение без исполнителя, `own` — мой документ. */
  reason: 'approve' | 'acquaint' | 'do' | 'unassigned' | 'own' | 'own_note'
  reason_name: string
  key: string
  title: string
  note: string | null
  due_at: string | null
  overdue: boolean
  bucket: 'overdue' | 'today' | 'week' | 'later'
  state?: string
  acting_for?: string | null
  acquaint_id?: string
  /** Как человек разложил этот предмет у себя. Пусто — не разложен, и это
   *  нормальное состояние, а не незаполненные поля. */
  mark?: PersonalMark | null
  /** Взят в сегодняшний день. */
  in_day?: boolean
  /** Отложен до будущего дня: строка остаётся в выдаче, но своему месту в
   *  сегодняшнем списке уже не принадлежит. */
  hidden?: boolean
}

export async function myWork(companyId: string) {
  return get<{
    mine: MyWorkItem[]
    buckets: { code: MyWorkItem['bucket']; name: string }[]
  }>('/api/work/mine', { company_id: companyId, today: todayKey() })
}

/** Куда ведёт предмет, названный словарём пространства (`task:<uuid>`).
 *  Пусто — вида не знаем, и вести человека наугад хуже, чем не вести. */
export function refHref(targetRef: string): string | null {
  const [kind, id] = targetRef.split(':')
  if (!id) return null
  if (kind === 'doc') return `/docs?view=all&doc=${id}`
  if (kind === 'task') return `/docs/company?view=errands&task=${id}`
  if (kind === 'event') return `/docs/work?view=calendar&event=${id}`
  return null
}

/** Куда ведёт строка очереди: виза открывается в карточке документа. */
export function myWorkHref(item: MyWorkItem): string {
  return item.kind === 'doc'
    ? `/docs?view=all&doc=${item.id}`
    : `/docs/company?view=errands&task=${item.id}`
}

/** Перенести предмет в колонку общей доски. Делает движок предмета: маршрут у
 *  поручения, круг виз у документа. Отказ приходит с причиной — её и показываем. */
export async function moveWork(
  kind: 'doc' | 'task', id: string, companyId: string, state: WorkState,
) {
  return post(`/api/work/${kind}/${id}/move`, { company_id: companyId, state })
}


/* ---------------------------------------------------------------------------
 * Личная раскладка (этап 14 «Трека»)
 *
 * Очередь отвечает «что от меня ждут», раскладка — «что я с этим решил». Она
 * ничего не меняет в предмете и не видна никому, кроме хозяина: срок, состояние
 * и просрочка остаются такими же, какими их видит компания.
 * ------------------------------------------------------------------------ */

/** Отметка человека на предмете: подборка, день, отложение, важность. */
export interface PersonalMark {
  /** Подборка эксклюзивна: предмет лежит в одной или ни в одной. */
  list_id: string | null
  /** На какой день взят. Прошлая дата — уже не «мой день». */
  taken_for: string | null
  /** До какого дня спрятан у себя. Срок предмета при этом не двигается. */
  deferred_until: string | null
  starred: boolean
  /** Сколько раз откладывали. Показывается хозяину и меняет предложение, а не
   *  текст; наверх не уходит никогда. */
  defer_count: number
  position: number
}

/** Именованная подборка человека. */
export interface PersonalListRow {
  id: string
  name: string
  position: number
  count: number
  /** Сколько дней подборку не открывали. `null` — ни разу не отмечали обзор. */
  stale_days: number | null
}

/** Строка раскладки: предмет плюс отметка на нём. */
export interface PlacedItem {
  kind: 'doc' | 'task'
  id: string
  title: string
  key: string
  due_at: string | null
  /** Личная запись из записной книжки, а не работа компании. */
  personal: boolean
  mark: PersonalMark | null
}

/** Предмет словарём пространства: `task:<uuid>`, `doc:<uuid>`. */
export function targetRef(item: { kind: 'doc' | 'task'; id: string }): string {
  return `${item.kind}:${item.id}`
}

/** Числа у пунктов личного раздела. Считаются вместе с подборками одним запросом:
 *  пункт, который считает себя сам, — это пять запросов на открытие «Трека». */
export interface PersonalCounts {
  day: number
  starred: number
  deferred: number
  loose: number
}

export async function myLists(companyId: string) {
  return get<{ lists: PersonalListRow[]; counts: PersonalCounts }>(
    '/api/work/lists', { company_id: companyId, today: todayKey() })
}

export async function createList(companyId: string, name: string) {
  return post<PersonalListRow>('/api/work/lists', { company_id: companyId, name })
}

/** Переименовать, отметить обзор или удалить подборку. Удаление не трогает
 *  предметы: работа возвращается в «Не разложено». */
export async function listAction(companyId: string, id: string, data: {
  name?: string; position?: number; reviewed?: boolean; delete?: boolean
}) {
  return post(`/api/work/lists/${id}`, {
    company_id: companyId, name: data.name, position: data.position,
    reviewed: data.reviewed, delete: data.delete,
  })
}

/** Разложить предмет у себя. Переданное меняется, остальное стоит.
 *
 *  Отложение может вернуться отказом: просроченное не прячется, а дата дальше
 *  срока обрезается днём срока. Сообщение сервера показываем как есть — оно и
 *  объясняет человеку правило. */
/** Напомнить о работе тому, у кого она стоит.
 *
 *  Кого толкать, решает сервер: у поручения исполнитель, у документа в круге —
 *  держащие визу. Возвращает, скольким ушло. */
export async function nudge(companyId: string, targetRef: string):
  Promise<{ sent: number }> {
  return post<{ sent: number }>('/api/work/nudge', {
    company_id: companyId, ref: targetRef,
  })
}

/** Адрес ленты подписки на свой календарь: его вставляют в Google, Apple
 *  или Outlook. Ключ живёт в самом адресе — календарные клиенты входить
 *  никуда не умеют. */
export interface CalendarPersonRow {
  id: string
  name: string
  events: number
  hours: number
  declined: number
  pending: number
}

export interface CalendarSummary {
  period: { date_from: string; date_to: string }
  totals: {
    events: number; cancelled: number; hours: number; all_day: number
    seats: number; declined: number; awaiting: number
  }
  by_organizer: { id: string | null; name: string; events: number; hours: number }[]
  by_person: CalendarPersonRow[]
  awaiting: { id: string; name: string; count: number }[]
}

/** Сводка по встречам: сколько времени компания проводит на совещаниях. */
export async function calendarSummary(
  companyId: string, from: string, to: string,
) {
  return get<CalendarSummary>('/api/work/calendar/summary', {
    company_id: companyId, date_from: from, date_to: to,
  })
}

export async function calendarFeed(): Promise<{ url: string; note?: string }> {
  return get<{ url: string; note?: string }>('/api/work/calendar/feed')
}

/** Сменить ключ: прежняя ссылка перестаёт работать. */
export async function rotateCalendarFeed(): Promise<{ url: string }> {
  return post<{ url: string }>('/api/work/calendar/feed/rotate', {})
}

/** На какие дни человек наметил себе работу: `{"2026-09-03": 2}`.
 *
 *  Отдельно от сроков намеренно: срок ждёт компания, план — только хозяин.
 *  Числом, а не списком: в масштабе месяца ячейка отвечает на «сколько». */
export async function planDays(companyId: string, from: string, to: string):
  Promise<Record<string, number>> {
  const r = await get<{ days: Record<string, number> }>(
    '/api/work/plan', { company_id: companyId, from, to })
  return r.days
}

export async function place(companyId: string, ref: string, data: {
  listId?: string; dropList?: boolean; takenFor?: string; dropDay?: boolean
  deferUntil?: string; undefer?: boolean; starred?: boolean
  position?: number; clear?: boolean
}) {
  return post<{ target_ref: string; mark: PersonalMark | null }>('/api/work/place', {
    company_id: companyId, target_ref: ref,
    list_id: data.listId, drop_list: data.dropList,
    taken_for: data.takenFor, drop_day: data.dropDay,
    defer_until: data.deferUntil, undefer: data.undefer,
    starred: data.starred, position: data.position, clear: data.clear,
  })
}

/** Что лежит в подборке, в дне, в отложенном или под звездой. Закрытая работа
 *  отсюда уходит сама — убирать руками нечего. */
export async function placed(companyId: string, opts: {
  scope?: 'list' | 'day' | 'carry' | 'deferred' | 'starred' | 'loose'
  listId?: string
  /** День для `scope: 'day'` в виде `YYYY-MM-DD`. Пусто — сегодняшний. */
  on?: string
} = {}) {
  return get<{ items: PlacedItem[] }>('/api/work/placed', {
    company_id: companyId, scope: opts.scope ?? 'list', list: opts.listId,
    on: opts.on,
    // Какой день сейчас у ЧЕЛОВЕКА: у пространства от Владивостока до Москвы
    // единого «сегодня» нет, и сервер не должен его выдумывать.
    today: todayKey(),
  })
}

/** Кому человек чаще всего поручает: плашки быстрого переназначения в календаре
 *  рельсы. Считается по его же постановкам за три месяца — у каждого свой. */
export async function frequentAssignees(companyId: string) {
  return get<{ people: { id: string; name: string; count: number }[] }>(
    '/api/work/frequent', { company_id: companyId })
}



/* ---------------------------------------------------------------------------
 * Личные напоминания
 * ------------------------------------------------------------------------ */

/** Своё напоминание о предмете пространства. Чужих не бывает: сервер отбирает
 *  строго по владельцу, и администратор здесь не исключение. */
export interface PersonalReminder {
  id: string
  /** Предмет тем же словарём, что `subject_ref`: `task:<uuid>`, `event:…`, `doc:…`. */
  target_ref: string
  note: string | null
  remind_at: string
  /** Заполнено — напоминание уже пришло и ждёт, чтобы его погасили. */
  fired_at: string | null
  snooze_count: number
}

export async function listReminders(companyId: string, opts?: { pending?: boolean }) {
  return get<{ items: PersonalReminder[]; total: number }>('/api/work/reminders', {
    company_id: companyId, pending: opts?.pending ? 'true' : undefined,
  })
}

export async function createReminder(companyId: string, data: {
  targetRef: string; remindAt: string; note?: string
}) {
  return post<PersonalReminder>('/api/work/reminders', {
    company_id: companyId, target_ref: data.targetRef,
    remind_at: data.remindAt, note: data.note || undefined,
  })
}

/** Отложить на N минут, перенести на время или погасить. */
export async function reminderAction(companyId: string, id: string, data: {
  snoozeMinutes?: number; remindAt?: string; done?: boolean
}) {
  return post<PersonalReminder>(`/api/work/reminders/${id}`, {
    company_id: companyId, snooze_minutes: data.snoozeMinutes,
    remind_at: data.remindAt, done: data.done,
  })
}


/* ---------------------------------------------------------------------------
 * Календарь
 * ------------------------------------------------------------------------ */

/** Круг видимости встречи — тот же словарь, что у поручения. */
export type EventVisibility = 'company' | 'private' | 'personal'

export type EventResponse = 'pending' | 'accepted' | 'declined' | 'tentative'

export interface EventAttendee {
  user_id: string
  name: string | null
  role: 'required' | 'optional'
  response: EventResponse
  comment: string | null
  /** Что участник предложил взамен. Время это не двигает — решает организатор. */
  proposed_starts_at?: string | null
  proposed_ends_at?: string | null
}

/** Правило повторения. Час и минута берутся у самой встречи: второе место, где
 *  записано «в 10:00», разошлось бы с ней при первом переносе. */
export interface Recurrence {
  mode: 'daily' | 'weekly' | 'monthly'
  /** Через сколько периодов. 2 при `weekly` — раз в две недели. */
  interval?: number
}

export interface CalendarEvent {
  id: string
  title: string
  description: string | null
  starts_at: string
  ends_at: string
  all_day: boolean
  tz: string
  location: string | null
  conference_url: string | null
  visibility: 'company' | 'private' | 'personal'
  /** `cancelled` — встречу отменили; из календаря она не исчезает. */
  status: 'planned' | 'cancelled' | 'poll'
  /** Заполнено — это ГОЛОВА серии; у порождённых пусто. */
  recurrence?: Recurrence | null
  recurrence_until?: string | null
  /** Голова серии, если встреча ею порождена. */
  series_id?: string | null
  cancel_reason: string | null
  subject_ref: string | null
  organizer_id: string
  is_organizer: boolean
  /** Мой ответ; `null` — я организатор и не приглашён отдельной строкой. */
  my_response: EventResponse | null
  attendees: EventAttendee[]
}

/** Встречи периода: пересекающиеся с окном, а не начинающиеся в нём. */
export async function listEvents(companyId: string, from: string, to: string,
  opts?: {
    /** `mine` — мой календарь; `company` — общий календарь компании, и в нём
     *  только встречи с кругом «вся компания». */
    scope?: 'mine' | 'company'
    /** Обсуждения по предмету: `doc:<uuid>`, `task:<uuid>`. */
    subjectRef?: string
  }) {
  return get<{ events: CalendarEvent[]; total: number }>('/api/work/calendar', {
    company_id: companyId, from, to,
    scope: opts?.scope, subject_ref: opts?.subjectRef,
  })
}

/** Кто когда занят в окне — интервалы и рабочее окно, без названий и участников.
 *  Чтобы предложить время, знать предмет чужой встречи не нужно. */
export async function calendarBusy(companyId: string, from: string, to: string,
  userIds: string[]) {
  return get<{
    from: string; to: string
    people: {
      user_id: string; name: string
      tz: string | null; work_start: string | null; work_end: string | null
      busy: { starts_at: string; ends_at: string; all_day: boolean }[]
    }[]
  }>('/api/work/calendar/busy', {
    company_id: companyId, from, to, user_ids: userIds.join(','),
  })
}

export async function createEvent(companyId: string, data: {
  title: string; startsAt: string; endsAt: string
  description?: string; location?: string; conferenceUrl?: string
  allDay?: boolean; tz?: string; attendeeIds?: string[]; subjectRef?: string
  /** Позванные «для сведения»: их занятость не блокирует подбор времени. */
  optionalIds?: string[]
  visibility?: EventVisibility
  /** От чьего имени собираем: помощник ведёт календарь владельца. */
  onBehalfOf?: string
  recurrence?: Recurrence | null; recurrenceUntil?: string | null
}) {
  return post<CalendarEvent>('/api/work/calendar', {
    company_id: companyId, title: data.title,
    starts_at: data.startsAt, ends_at: data.endsAt,
    description: data.description || undefined,
    location: data.location || undefined,
    conference_url: data.conferenceUrl || undefined,
    all_day: data.allDay ?? false,
    tz: data.tz || Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
    attendee_ids: data.attendeeIds ?? [],
    optional_ids: data.optionalIds ?? [],
    visibility: data.visibility || undefined,
    on_behalf_of: data.onBehalfOf || undefined,
    subject_ref: data.subjectRef || undefined,
    recurrence: data.recurrence ?? undefined,
    recurrence_until: data.recurrenceUntil || undefined,
  })
}

export interface EventGuest {
  id: string
  email: string
  name: string | null
  response: 'pending' | 'accepted' | 'declined' | 'tentative'
  comment: string | null
  opened_at: string | null
  proposed_starts_at: string | null
  proposed_ends_at: string | null
}

export interface EventMaterial {
  id: string
  target_ref: string
  title: string
  url: string | null
}

/** Кого позвали снаружи и что им открыли. Токенов здесь нет: ссылка видна один
 *  раз — в ответе на приглашение. */
export async function eventGuests(companyId: string, eventId: string) {
  return get<{ guests: EventGuest[]; materials: EventMaterial[] }>(
    `/api/work/calendar/${eventId}/guests`, { company_id: companyId })
}

/** Позвать внешнего участника. Учётной записи ему не заводим: она дала бы место
 *  в составе компании ради одной встречи. */
export async function inviteGuest(companyId: string, eventId: string, data: {
  email: string; name?: string
}) {
  return post<EventGuest & { token: string }>(
    `/api/work/calendar/${eventId}/guests`,
    { company_id: companyId, email: data.email, name: data.name })
}

export async function revokeGuest(companyId: string, eventId: string, guestId: string) {
  return post(`/api/work/calendar/${eventId}/guests/${guestId}`,
    { company_id: companyId, revoke: true })
}

/** Открыть гостям материал. Приглашение само по себе не открывает ничего:
 *  позвать обсудить договор и дать договор — разные решения. */
export async function openMaterial(companyId: string, eventId: string, targetRef: string) {
  return post<EventMaterial>(`/api/work/calendar/${eventId}/materials`,
    { company_id: companyId, target_ref: targetRef })
}

export async function closeMaterial(companyId: string, eventId: string, id: string) {
  return post(`/api/work/calendar/${eventId}/materials/${id}/close`
    + `?company_id=${encodeURIComponent(companyId)}`, {})
}

export interface PollOption {
  id: string
  starts_at: string
  ends_at: string
  votes: { yes: number; maybe: number; no: number }
  my_vote: 'yes' | 'maybe' | 'no' | null
}

/** Опрос — СОСТОЯНИЕ встречи, а не отдельная сущность: гости, материалы,
 *  файл для календаря и отмена продолжают работать тем же кодом. */
export async function openPoll(companyId: string, eventId: string,
  options: { starts_at: string; ends_at: string }[]) {
  return post<{ status: string; options: number }>(
    `/api/work/calendar/${eventId}/poll`,
    { company_id: companyId, options })
}

export async function readPoll(companyId: string, eventId: string) {
  return get<{ status: string; options: PollOption[] }>(
    `/api/work/calendar/${eventId}/poll`, { company_id: companyId })
}

export async function votePoll(companyId: string, eventId: string,
  optionId: string, vote: 'yes' | 'maybe' | 'no') {
  return post(`/api/work/calendar/${eventId}/poll/vote`,
    { company_id: companyId, option_id: optionId, vote })
}

/** Выбрать вариант: опрос кончился, встреча получила время. Согласия при этом
 *  обнуляются — «подходит» это готовность рассмотреть, а не обещание прийти. */
export async function pickPoll(companyId: string, eventId: string, optionId: string) {
  return post(`/api/work/calendar/${eventId}/poll/pick`,
    { company_id: companyId, option_id: optionId })
}

/** Опрос времени глазами гостя: та же выдача, что внутри, — итог считается
 *  один. Голоса своих и гостей лежат одной таблицей. */
export async function invitePoll(token: string) {
  return get<{ status: string; options: PollOption[] }>(`/api/invite/${token}/poll`)
}

export async function inviteVote(token: string, optionId: string,
  vote: 'yes' | 'maybe' | 'no') {
  return post(`/api/invite/${token}/poll/vote`, { option_id: optionId, vote })
}

export interface CalendarDelegate { id: string; user_id: string; name: string }

/** Кому я доверил вести свой календарь и чьи веду я. */
export async function calendarDelegates(companyId: string) {
  return get<{ mine: CalendarDelegate[]; for_others: CalendarDelegate[] }>(
    '/api/work/calendar-delegates', { company_id: companyId })
}

export async function addCalendarDelegate(companyId: string, userId: string) {
  return post('/api/work/calendar-delegates',
    { company_id: companyId, delegate_id: userId })
}

export async function revokeCalendarDelegate(companyId: string, id: string) {
  return post(`/api/work/calendar-delegates/${id}/revoke`
    + `?company_id=${encodeURIComponent(companyId)}`, {})
}

export interface MeetingTemplate {
  id: string
  name: string
  title: string
  description: string | null
  duration_minutes: number
  location: string | null
  attendee_ids: string[]
  recurrence: Recurrence | null
}

export async function meetingTemplates(companyId: string) {
  return get<{ templates: MeetingTemplate[] }>(
    '/api/work/calendar-templates', { company_id: companyId })
}

export async function saveMeetingTemplate(companyId: string, data: {
  name: string; title: string; description?: string
  durationMinutes: number; location?: string
  attendeeIds: string[]; recurrence?: Recurrence | null
}) {
  return post<{ id: string; name: string }>('/api/work/calendar-templates', {
    company_id: companyId, name: data.name, title: data.title,
    description: data.description || undefined,
    duration_minutes: data.durationMinutes,
    location: data.location || undefined,
    attendee_ids: data.attendeeIds,
    recurrence: data.recurrence ?? undefined,
  })
}

export async function deleteMeetingTemplate(companyId: string, id: string) {
  return post(`/api/work/calendar-templates/${id}/delete`
    + `?company_id=${encodeURIComponent(companyId)}`, {})
}

/** Правка, отмена или свой ответ — одной ручкой, как действие над задачей. */
export async function eventAction(companyId: string, id: string, data: {
  title?: string; startsAt?: string; endsAt?: string
  description?: string; location?: string; conferenceUrl?: string
  attendeeIds?: string[]
  cancel?: boolean; cancelReason?: string
  response?: Exclude<EventResponse, 'pending'>; comment?: string
  /** Встречное предложение участника. Время оно не двигает: перенос —
   *  решение организатора. */
  proposeStartsAt?: string; proposeEndsAt?: string
  /** Пустой объект снимает повторение; уже созданные встречи остаются —
   *  они стоят в чужих календарях. */
  recurrence?: Recurrence | Record<string, never> | null
  recurrenceUntil?: string | null
}) {
  return post<CalendarEvent>(`/api/work/calendar/${id}`, {
    company_id: companyId, title: data.title,
    starts_at: data.startsAt, ends_at: data.endsAt,
    description: data.description, location: data.location,
    conference_url: data.conferenceUrl,
    attendee_ids: data.attendeeIds,
    cancel: data.cancel, cancel_reason: data.cancelReason,
    propose_starts_at: data.proposeStartsAt,
    propose_ends_at: data.proposeEndsAt,
    recurrence: data.recurrence ?? undefined,
    recurrence_until: data.recurrenceUntil || undefined,
    response: data.response, comment: data.comment,
  })
}
