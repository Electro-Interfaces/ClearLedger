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

export type EventResponse = 'pending' | 'accepted' | 'declined' | 'tentative'

export interface EventAttendee {
  user_id: string
  name: string | null
  role: 'required' | 'optional'
  response: EventResponse
  comment: string | null
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
  status: 'planned' | 'cancelled'
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

export async function createEvent(companyId: string, data: {
  title: string; startsAt: string; endsAt: string
  description?: string; location?: string; conferenceUrl?: string
  allDay?: boolean; tz?: string; attendeeIds?: string[]; subjectRef?: string
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
    subject_ref: data.subjectRef || undefined,
  })
}

/** Правка, отмена или свой ответ — одной ручкой, как действие над задачей. */
export async function eventAction(companyId: string, id: string, data: {
  title?: string; startsAt?: string; endsAt?: string
  description?: string; location?: string; conferenceUrl?: string
  attendeeIds?: string[]
  cancel?: boolean; cancelReason?: string
  response?: Exclude<EventResponse, 'pending'>; comment?: string
}) {
  return post<CalendarEvent>(`/api/work/calendar/${id}`, {
    company_id: companyId, title: data.title,
    starts_at: data.startsAt, ends_at: data.endsAt,
    description: data.description, location: data.location,
    conference_url: data.conferenceUrl,
    attendee_ids: data.attendeeIds,
    cancel: data.cancel, cancel_reason: data.cancelReason,
    response: data.response, comment: data.comment,
  })
}
