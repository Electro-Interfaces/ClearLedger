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

/** Строка очереди «На мне»: предмет плюс род действия, которого он от меня ждёт. */
export interface MyWorkItem {
  kind: 'doc' | 'task'
  id: string
  /** `approve` — виза, `acquaint` — ознакомление, `do` — работа, `own` — мой документ. */
  reason: 'approve' | 'acquaint' | 'do' | 'own'
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
}

export async function myWork(companyId: string) {
  return get<{
    mine: MyWorkItem[]
    buckets: { code: MyWorkItem['bucket']; name: string }[]
  }>('/api/work/mine', { company_id: companyId })
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
export async function listEvents(companyId: string, from: string, to: string) {
  return get<{ events: CalendarEvent[]; total: number }>('/api/work/calendar', {
    company_id: companyId, from, to,
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
