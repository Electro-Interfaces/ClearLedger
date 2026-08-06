/**
 * Приложение «Задачи» — работа компании (docs/TASKS.md ecosystem-deploy).
 * Движок свой, в Ядре: тип несёт маршрут, задача идёт по стадиям и переадресуется.
 */
import { del, get, patch, post, put, upload } from './apiClient'

export interface RouteStage { code: string; name: string }

export interface TaskLabel { id: string; name: string; color: string }
export interface TaskProgress { total: number; done: number }
export interface TaskSubtasks { total: number; open: number }

export interface TaskType {
  id: string
  code: string
  name: string
  description: string | null
  route: RouteStage[]
  default_priority: string
  due_days: number | null
  is_active: boolean
  sort_order: number
}

export interface SpaceTask {
  id: string
  number: number
  title: string
  status: string           // open | done | cancelled
  priority: string
  stage: string | null     // имя текущей стадии
  stage_code: string | null
  route: RouteStage[]
  type: string | null
  type_id: string | null
  assignee: string | null
  assignee_id: string | null
  author: string | null
  object: string | null
  object_id: string | null
  due_at: string | null
  overdue: boolean
  /** У кого мяч: `external` — ждём внешнюю сторону, `us`/null — у нас. */
  waiting_for: 'us' | 'external' | null
  created_at: string | null
  updated_at: string | null
  closed_at: string | null
  labels: TaskLabel[]
  checklist: TaskProgress
  subtasks: TaskSubtasks
}

export interface TaskEvent {
  id: string
  kind: string             // created | stage | assign | status | comment
  user: string | null
  from: string | null
  to: string | null
  note: string | null
  created_at: string | null
}

export interface ChecklistItem {
  id: string; text: string; done: boolean; position: number; done_at: string | null
}
/** Вид связи со стороны открытой карточки: `parent` и `blocked_by` — обратные
 *  прочтения `subtask` и `blocks`, второй записи в базе под них нет. */
export type LinkKind = 'subtask' | 'blocks' | 'relates' | 'duplicates'
  | 'parent' | 'blocked_by' | 'duplicated_by'
export interface TaskLink {
  id: string; kind: LinkKind; task_id: string
  number: number; title: string; status: string
}
export interface TaskWatcher { user_id: string; name: string; reason: string }
/** Внешний участник: каким каналом до него доходит слово. */
export interface TaskParticipant {
  user_id: string; name: string; email: string | null
  role: string; channel: 'space' | 'mail' | 'connector'; channel_ref: string | null
}
export interface TaskAttachment {
  id: string; event_id: string | null; file_name: string
  mime_type: string; size: number; created_at: string | null
}

export interface TaskDetails extends SpaceTask {
  description: string | null
  events: TaskEvent[]
  /** Пункты чек-листа. Прогресс «3 из 5» приходит отдельно, полем `checklist`. */
  checklist_items: ChecklistItem[]
  watchers: TaskWatcher[]
  attachments: TaskAttachment[]
  links: TaskLink[]
  participants: TaskParticipant[]
  /** Адрес, по которому внешний отвечает письмом. null — канал не настроен. */
  reply_address: string | null
}

/** Ответ действия: сервер может предупредить, не отказав (открытые подзадачи). */
export interface TaskActionResult extends SpaceTask {
  warning?: string
  mentioned?: string[]
}

export type TaskScope = 'open' | 'mine' | 'assigned' | 'watching' | 'overdue'
  | 'today' | 'waiting' | 'closed' | 'all'

export interface TaskFilters {
  objectId?: string; typeId?: string; assigneeId?: string; authorId?: string
  stage?: string; priority?: string; labelId?: string; q?: string
  dueFrom?: string; dueTo?: string
  sort?: string; limit?: number; offset?: number
}

export async function listTasks(companyId: string, scope: TaskScope, opts?: TaskFilters) {
  return get<{ tasks: SpaceTask[]; total: number; limit: number; offset: number }>(
    '/api/tasks', {
      company_id: companyId, scope,
      object_id: opts?.objectId || undefined, type_id: opts?.typeId || undefined,
      assignee_id: opts?.assigneeId || undefined, author_id: opts?.authorId || undefined,
      stage: opts?.stage || undefined, priority: opts?.priority || undefined,
      label_id: opts?.labelId || undefined, q: opts?.q || undefined,
      due_from: opts?.dueFrom || undefined, due_to: opts?.dueTo || undefined,
      sort: opts?.sort || undefined,
      limit: opts?.limit ?? undefined, offset: opts?.offset || undefined,
    })
}

/** Разрез работы: сколько в работе и просрочено, кто чем занят, что происходило. */
/** Строка разреза. `id` пустой у «без исполнителя» / «без объекта» — по такой
 *  строке провалиться некуда, кнопка просто не ведёт в список. */
export interface TasksCut { id: string | null; name: string; open: number; overdue: number; done: number }
export interface TaskActivity extends TaskEvent {
  task_id: string; number: number; title: string
}
export interface TasksSummary {
  days: number
  totals: {
    open: number; overdue: number; mine: number; unassigned: number
    created: number; done: number; avg_days: number | null
  }
  by_assignee: TasksCut[]
  by_type: TasksCut[]
  by_object: TasksCut[]
  activity: TaskActivity[]
}

export async function tasksSummary(companyId: string, days: number) {
  return get<TasksSummary>('/api/tasks/summary', { company_id: companyId, days })
}

export async function taskDetails(id: string, companyId: string) {
  return get<TaskDetails>(`/api/tasks/${id}`, { company_id: companyId })
}

/** Кому можно поручить: члены пространства (доступно любому исполнителю). */
export async function listTaskPeople(companyId: string) {
  return get<{ people: { id: string; name: string }[] }>(
    '/api/tasks/people', { company_id: companyId })
}

export async function listTaskTypes(companyId: string) {
  return get<{ types: TaskType[]; default_route: RouteStage[] }>(
    '/api/tasks/types', { company_id: companyId })
}

export async function createTask(data: {
  companyId: string; title: string; description?: string
  typeId?: string; assigneeId?: string; objectId?: string
  priority?: string; dueAt?: string
}) {
  return post<SpaceTask>('/api/tasks', {
    company_id: data.companyId, title: data.title,
    description: data.description || undefined,
    type_id: data.typeId || undefined, assignee_id: data.assigneeId || undefined,
    object_id: data.objectId || undefined, priority: data.priority || undefined,
    due_at: data.dueAt || undefined,
  })
}

/** Одно действие над задачей: стадия, переадресация, завершение или реплика. */
export async function taskAction(id: string, data: {
  companyId: string; stageCode?: string; assigneeId?: string | null
  status?: string; priority?: string; dueAt?: string; note?: string
  title?: string; description?: string; objectId?: string | null
  addLabelId?: string; removeLabelId?: string
}) {
  return post<TaskActionResult>(`/api/tasks/${id}/action`, {
    company_id: data.companyId,
    stage_code: data.stageCode,
    // null = снять исполнителя; undefined = не трогать.
    assignee_id: data.assigneeId === null ? '' : data.assigneeId,
    status: data.status, priority: data.priority,
    due_at: data.dueAt, note: data.note || undefined,
    title: data.title, description: data.description,
    object_id: data.objectId === null ? '' : data.objectId,
    add_label_id: data.addLabelId, remove_label_id: data.removeLabelId,
  })
}

/** То же действие над несколькими задачами сразу. */
export async function tasksBulk(data: {
  companyId: string; taskIds: string[]; assigneeId?: string | null
  status?: string; priority?: string; dueAt?: string; stageCode?: string; note?: string
}) {
  return post<{ changed: number; skipped: string[] }>('/api/tasks/bulk', {
    company_id: data.companyId, task_ids: data.taskIds,
    assignee_id: data.assigneeId === null ? '' : data.assigneeId,
    status: data.status, priority: data.priority, due_at: data.dueAt,
    stage_code: data.stageCode, note: data.note || undefined,
  })
}

/* ── Чек-лист, связи, наблюдатели, метки, вложения ───────────────────── */

export async function addChecklistItem(taskId: string, companyId: string, text: string) {
  return post<ChecklistItem>(`/api/tasks/${taskId}/checklist`,
    { company_id: companyId, text })
}

export async function updateChecklistItem(taskId: string, itemId: string, data: {
  companyId: string; done?: boolean; text?: string
}) {
  return patch<ChecklistItem>(`/api/tasks/${taskId}/checklist/${itemId}`,
    { company_id: data.companyId, done: data.done, text: data.text })
}

export async function deleteChecklistItem(taskId: string, itemId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/checklist/${itemId}?company_id=${encodeURIComponent(companyId)}`)
}

export async function addTaskLink(taskId: string, data: {
  companyId: string; relatedTaskId: string; kind: LinkKind
}) {
  return post<TaskLink>(`/api/tasks/${taskId}/links`, {
    company_id: data.companyId, related_task_id: data.relatedTaskId, kind: data.kind,
  })
}

export async function deleteTaskLink(taskId: string, linkId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/links/${linkId}?company_id=${encodeURIComponent(companyId)}`)
}

export async function addWatcher(taskId: string, companyId: string, userId?: string) {
  return post(`/api/tasks/${taskId}/watchers`, { company_id: companyId, user_id: userId })
}

export async function removeWatcher(taskId: string, userId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/watchers/${userId}?company_id=${encodeURIComponent(companyId)}`)
}

/** Поручить тому, кто в пространство не заходит: письмо + ответ в ленту. */
export async function delegateByMail(taskId: string, data: {
  companyId: string; email: string; name?: string; note?: string
}) {
  return post<{ ok: boolean; user_id: string; email: string; reply_address: string | null }>(
    `/api/tasks/${taskId}/delegate`, {
      company_id: data.companyId, email: data.email,
      name: data.name || undefined, note: data.note || undefined,
    })
}

export async function removeParticipant(taskId: string, userId: string, companyId: string) {
  return del<{ deleted: string; participants_left: number }>(
    `/api/tasks/${taskId}/participants/${userId}?company_id=${encodeURIComponent(companyId)}`)
}

export async function listTaskLabels(companyId: string) {
  return get<{ labels: TaskLabel[] }>('/api/tasks/labels', { company_id: companyId })
}

export async function createTaskLabel(companyId: string, name: string, color = 'slate') {
  return post<TaskLabel>('/api/tasks/labels', { company_id: companyId, name, color })
}

export async function deleteTaskLabel(id: string, companyId: string) {
  return del(`/api/tasks/labels/${id}?company_id=${encodeURIComponent(companyId)}`)
}

export async function uploadTaskFile(taskId: string, companyId: string, file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return upload<{ id: string; file_name: string; size: number }>(
    `/api/tasks/${taskId}/attachments?company_id=${encodeURIComponent(companyId)}`, fd)
}

export async function deleteTaskFile(taskId: string, attachmentId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/attachments/${attachmentId}?company_id=${encodeURIComponent(companyId)}`)
}

/** Адрес файла вложения: ссылку отдаём браузеру, второй раз в память не тянем. */
export function taskFileUrl(attachmentId: string, companyId: string): string {
  return `/api/tasks/attachments/${attachmentId}?company_id=${encodeURIComponent(companyId)}`
}

export async function saveTaskType(data: {
  companyId: string; id?: string; code: string; name: string
  description?: string; route: RouteStage[]; defaultPriority: string
  dueDays?: number | null; isActive?: boolean; sortOrder?: number
}) {
  const body = {
    company_id: data.companyId, code: data.code, name: data.name,
    description: data.description || undefined, route: data.route,
    default_priority: data.defaultPriority, due_days: data.dueDays ?? null,
    is_active: data.isActive ?? true, sort_order: data.sortOrder ?? 100,
  }
  return data.id
    ? put<TaskType>(`/api/tasks/types/${data.id}`, body)
    : post<TaskType>('/api/tasks/types', body)
}

/** Завести заготовки типов (поручение, согласование, инцидент). Идемпотентно. */
export async function createStarterTypes(companyId: string) {
  return post<{ added: number }>(
    `/api/tasks/types/starter?company_id=${encodeURIComponent(companyId)}`, {})
}
