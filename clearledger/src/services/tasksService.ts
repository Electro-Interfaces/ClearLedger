/**
 * Приложение «Задачи» — работа компании (docs/TASKS.md ecosystem-deploy).
 * Движок свой, в Ядре: тип несёт маршрут, задача идёт по стадиям и переадресуется.
 */
import { del, get, patch, post, put, upload } from './apiClient'

export interface RouteStage { code: string; name: string }

export interface TaskLabel { id: string; name: string; color: string }
export interface TaskProgress { total: number; done: number }
/** План и факт по времени: оценка задачи и сумма записей о работе. */
export interface TaskTime {
  estimate: number | null; spent: number
  estimate_text: string; spent_text: string
}
export interface TaskWorkItem {
  id: string; minutes: number; duration: string; work_date: string
  description: string | null; kind: string | null; user: string | null
}
export interface TaskSubtasks { total: number; open: number }

export interface TaskType {
  id: string
  code: string
  name: string
  description: string | null
  route: RouteStage[]
  default_priority: string
  due_days: number | null
  /** NULL — тип общий для компании; иначе он свой у проекта. */
  project_id?: string | null
  is_active: boolean
  sort_order: number
  /** Часов на первый отклик исполнителя; null — за реакцией не следим. */
  reaction_hours: number | null
  /** Кому сообщить, если отклика нет; null — автору задачи. */
  escalate_to_id: string | null
}

export interface TaskProject {
  id: string
  code: string
  name: string
  description: string | null
  lead_id: string | null
  counter: number
  is_archived: boolean
  sort_order: number
  tasks: number
  open: number
}

export interface SpaceTask {
  id: string
  number: number
  /** Как задачу называют вслух и пишут в коммите: `TF-42`. У задач без проекта —
   *  просто номер, чтобы строка списка не пустовала. */
  key?: string
  project?: string | null
  project_id?: string | null
  project_number?: number | null
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
  waiting_for?: 'us' | 'external' | null
  created_at: string | null
  updated_at: string | null
  closed_at: string | null
  labels?: TaskLabel[]
  checklist?: TaskProgress
  subtasks?: TaskSubtasks
  time?: TaskTime
  visibility?: 'company' | 'private'
}

/** Как задача называется в интерфейсе: `TF-42` у задачи в проекте, `№17` — без него.
 *  Одна точка на все экраны: раньше номер печатали строкой в семи местах, и с
 *  появлением проектов это разошлось бы на первой же правке. */
export function taskKey(t: { key?: string; number: number }): string {
  return t.key && t.key !== String(t.number) ? t.key : `№${t.number}`
}

/** Значения по умолчанию для полей, которых может не быть у старого бэкенда. */
export const NO_TIME: TaskTime = {
  estimate: null, spent: 0, estimate_text: '—', spent_text: '—',
}
export const NO_PROGRESS: TaskProgress = { total: 0, done: 0 }
export const NO_SUBTASKS: TaskSubtasks = { total: 0, open: 0 }

export interface TaskEvent {
  id: string
  kind: string             // created | stage | assign | status | comment | field | work | mail
  user: string | null
  from: string | null
  to: string | null
  note: string | null
  pinned?: boolean
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
  mime_type: string; size: number; can_delete: boolean; created_at: string | null
}

export interface TaskDetails extends SpaceTask {
  description: string | null
  events: TaskEvent[]
  /** Пункты чек-листа. Прогресс «3 из 5» приходит отдельно, полем `checklist`. */
  checklist_items?: ChecklistItem[]
  watchers?: TaskWatcher[]
  attachments?: TaskAttachment[]
  links?: TaskLink[]
  participants?: TaskParticipant[]
  /** Адрес, по которому внешний отвечает письмом. null — канал не настроен. */
  reply_address: string | null
  external?: TaskExternalRef[]
  work_items?: TaskWorkItem[]
}

/** Строка списка после нормализации: `fillTask` уже проставил дефолты. */
export type ListedTask = Omit<SpaceTask, 'labels' | 'checklist' | 'subtasks' | 'time'> & {
  labels: TaskLabel[]; checklist: TaskProgress; subtasks: TaskSubtasks; time: TaskTime
}

/** Карточка после нормализации: все поля на месте, экранам не нужны проверки.
 *  Именно её отдаёт `taskDetails`. */
export type LoadedTask = Omit<TaskDetails,
  'labels' | 'checklist' | 'subtasks' | 'time' | 'events' | 'checklist_items'
  | 'watchers' | 'attachments' | 'links' | 'participants' | 'external'
  | 'work_items' | 'visibility' | 'waiting_for'> & {
  labels: TaskLabel[]; checklist: TaskProgress; subtasks: TaskSubtasks; time: TaskTime
  events: TaskEvent[]; checklist_items: ChecklistItem[]; watchers: TaskWatcher[]
  attachments: TaskAttachment[]; links: TaskLink[]; participants: TaskParticipant[]
  external: TaskExternalRef[]; work_items: TaskWorkItem[]
  visibility: 'company' | 'private'; waiting_for: 'us' | 'external' | null
}

/** Ответ действия: сервер может предупредить, не отказав (открытые подзадачи). */
export interface TaskActionResult extends SpaceTask {
  warning?: string
  mentioned?: string[]
}

export type TaskScope = 'open' | 'mine' | 'assigned' | 'watching' | 'overdue'
  | 'today' | 'waiting' | 'closed' | 'all'

export interface TaskFilters {
  objectId?: string; projectId?: string; typeId?: string; assigneeId?: string; authorId?: string
  stage?: string; priority?: string; labelId?: string; q?: string
  dueFrom?: string; dueTo?: string
  sort?: string; limit?: number; offset?: number
}

/** Достроить строку задачи дефолтами: старый бэкенд может не отдать новых полей,
 *  и ни один экран не должен из-за этого падать. */
export function fillTask<T extends SpaceTask>(t: T): T & Required<
  Pick<SpaceTask, 'labels' | 'checklist' | 'subtasks' | 'time'>> {
  return {
    ...t,
    labels: t.labels ?? [],
    checklist: t.checklist ?? NO_PROGRESS,
    subtasks: t.subtasks ?? NO_SUBTASKS,
    time: t.time ?? NO_TIME,
  }
}

export async function listTasks(companyId: string, scope: TaskScope, opts?: TaskFilters) {
  return get<{ tasks: SpaceTask[]; total: number; limit: number; offset: number }>(
    '/api/tasks', {
      company_id: companyId, scope,
      object_id: opts?.objectId || undefined, project_id: opts?.projectId || undefined,
      type_id: opts?.typeId || undefined,
      assignee_id: opts?.assigneeId || undefined, author_id: opts?.authorId || undefined,
      stage: opts?.stage || undefined, priority: opts?.priority || undefined,
      label_id: opts?.labelId || undefined, q: opts?.q || undefined,
      due_from: opts?.dueFrom || undefined, due_to: opts?.dueTo || undefined,
      sort: opts?.sort || undefined,
      limit: opts?.limit ?? undefined, offset: opts?.offset || undefined,
    }).then((r) => ({ ...r, tasks: (r.tasks ?? []).map(fillTask) }))
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
    .then((t) => ({
      ...fillTask(t),
      events: t.events ?? [],
      checklist_items: t.checklist_items ?? [],
      watchers: t.watchers ?? [],
      attachments: t.attachments ?? [],
      links: t.links ?? [],
      participants: t.participants ?? [],
      external: t.external ?? [],
      work_items: t.work_items ?? [],
      visibility: t.visibility ?? 'company',
      waiting_for: t.waiting_for ?? null,
    }))
}

/** Кому можно поручить: члены пространства (доступно любому исполнителю). */
/** Человек, которому можно поручить работу. `partyType` — свой он или внешний. */
export interface TaskPerson {
  id: string
  name: string
  partyType?: 'internal' | 'partner' | 'vendor'
  avatarUrl?: string | null
}

export async function listTaskPeople(companyId: string) {
  return get<{ people: TaskPerson[] }>('/api/tasks/people', { company_id: companyId })
}

/** Проекты компании со счётчиками работы. */
export async function listTaskProjects(companyId: string, archived = false) {
  return get<{ projects: TaskProject[] }>(
    '/api/tasks/projects', { company_id: companyId, archived: archived ? 'true' : 'false' })
}

export async function createTaskProject(data: {
  companyId: string; code: string; name: string
  description?: string; leadId?: string; sortOrder?: number
}) {
  return post<TaskProject>('/api/tasks/projects', {
    company_id: data.companyId, code: data.code.toUpperCase(), name: data.name,
    description: data.description || undefined, lead_id: data.leadId || undefined,
    sort_order: data.sortOrder ?? 100,
  })
}

export async function updateTaskProject(id: string, data: {
  companyId: string; name?: string; description?: string
  leadId?: string; sortOrder?: number; isArchived?: boolean
}) {
  return patch<TaskProject>(`/api/tasks/projects/${id}`, {
    company_id: data.companyId, name: data.name, description: data.description,
    lead_id: data.leadId, sort_order: data.sortOrder, is_archived: data.isArchived,
  })
}

export async function listTaskTypes(companyId: string) {
  return get<{ types: TaskType[]; default_route: RouteStage[] }>(
    '/api/tasks/types', { company_id: companyId })
}

export async function createTask(data: {
  companyId: string; title: string; description?: string
  projectId?: string; typeId?: string; assigneeId?: string; objectId?: string
  priority?: string; dueAt?: string
}) {
  return post<SpaceTask>('/api/tasks', {
    company_id: data.companyId, title: data.title,
    description: data.description || undefined,
    project_id: data.projectId || undefined,
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
  projectId?: string
  addLabelId?: string; removeLabelId?: string; estimate?: string
  visibility?: 'company' | 'private'
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
    project_id: data.projectId,
    add_label_id: data.addLabelId, remove_label_id: data.removeLabelId,
    estimate: data.estimate, visibility: data.visibility,
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

/* ── Регламент: представления, шаблоны, расписания ───────────────────── */

/** Сохранённый отбор реестра. `shared` — общее представление компании. */
export interface TaskView {
  id: string; name: string; query: Record<string, string>; shared: boolean
  position?: number; can_delete?: boolean
}

export async function listTaskViews(companyId: string) {
  return get<{ views: TaskView[] }>('/api/tasks/views', { company_id: companyId })
}

export async function createTaskView(data: {
  companyId: string; name: string; query: Record<string, string>; shared?: boolean
}) {
  return post<TaskView>('/api/tasks/views', {
    company_id: data.companyId, name: data.name, query: data.query,
    shared: data.shared ?? false,
  })
}

export async function deleteTaskView(id: string, companyId: string) {
  return del(`/api/tasks/views/${id}?company_id=${encodeURIComponent(companyId)}`)
}

export interface TaskTemplate {
  id: string; name: string; title: string; description: string | null
  type_id: string | null; doc_kind_id: string | null
  assignee_id: string | null; object_id: string | null
  priority: string | null; due_days: number | null; checklist: string[]
}

export async function listTaskTemplates(companyId: string) {
  return get<{ templates: TaskTemplate[] }>('/api/tasks/templates', { company_id: companyId })
}

export async function createTaskTemplate(data: {
  companyId: string; name: string; title: string; description?: string
  typeId?: string; docKindId?: string; assigneeId?: string
  priority?: string; dueDays?: number | null
  checklist: string[]
}) {
  return post<TaskTemplate>('/api/tasks/templates', {
    company_id: data.companyId, name: data.name, title: data.title,
    description: data.description || undefined, type_id: data.typeId || undefined,
    doc_kind_id: data.docKindId || undefined,
    assignee_id: data.assigneeId || undefined, priority: data.priority || undefined,
    due_days: data.dueDays ?? undefined, checklist: data.checklist,
  })
}

export async function deleteTaskTemplate(id: string, companyId: string) {
  return del(`/api/tasks/templates/${id}?company_id=${encodeURIComponent(companyId)}`)
}

export interface TemplateProcessLaunch {
  kind: 'document'; docId: string; title: string
  templateId: string; templateName: string
  state: 'preparation' | 'approval'; started: boolean; steps: number
  round?: number; approvals?: number; reason: string | null
}

export interface TaskRecurrence {
  id: string; template_id: string; template: string
  rule: { mode?: string; at?: string; weekday?: number; day?: number; tz?: string }
  enabled: boolean; next_run_at: string | null; last_run_at: string | null
}

export async function listTaskRecurrences(companyId: string) {
  return get<{ recurrences: TaskRecurrence[] }>('/api/tasks/recurrences',
    { company_id: companyId })
}

export async function createTaskRecurrence(data: {
  companyId: string; templateId: string; rule: Record<string, unknown>
}) {
  return post<TaskRecurrence>('/api/tasks/recurrences', {
    company_id: data.companyId, template_id: data.templateId, rule: data.rule,
  })
}

export async function deleteTaskRecurrence(id: string, companyId: string) {
  return del(`/api/tasks/recurrences/${id}?company_id=${encodeURIComponent(companyId)}`)
}

/** Команда одной строкой к одной или нескольким задачам: «на меня срочная срок завтра». */
export async function applyCommand(data: {
  companyId: string; taskIds: string[]; command: string
}) {
  return post<{
    changed: number; skipped: string[]; unknown: string[]
    applied: Record<string, unknown>
  }>('/api/tasks/command', {
    company_id: data.companyId, task_ids: data.taskIds, command: data.command,
  })
}

/** Закрепить или открепить реплику ленты (переключатель). */
export async function pinEvent(taskId: string, eventId: string, companyId: string) {
  return post<{ id: string; pinned: boolean }>(
    `/api/tasks/${taskId}/events/${eventId}/pin?company_id=${encodeURIComponent(companyId)}`, {})
}

/** Записать время по задаче. Длительность строкой — «2ч 30м», «1,5ч», «90м». */
export async function addWorkItem(taskId: string, data: {
  companyId: string; duration: string; description?: string
  workDate?: string; kind?: string; userId?: string
}) {
  return post<{ id: string; minutes: number; duration: string; work_date: string }>(
    `/api/tasks/${taskId}/work`, {
      company_id: data.companyId, duration: data.duration,
      description: data.description || undefined,
      work_date: data.workDate || undefined, kind: data.kind || undefined,
      user_id: data.userId || undefined,
    })
}

export async function deleteWorkItem(taskId: string, itemId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/work/${itemId}?company_id=${encodeURIComponent(companyId)}`)
}

/** Зеркало работы во внешней системе: у нас наша задача, у них своя. */
export interface TaskExternalRef {
  id: string; connector_key: string; connector_label: string | null
  external_id: string | null; external_number: string | null
  external_status: string | null; external_url: string | null
  direction: string; mirror_close: boolean; last_sync_at: string | null
}

export async function linkExternal(taskId: string, data: {
  companyId: string; connectorKey: string; connectorLabel?: string
  externalNumber?: string; externalId?: string; externalUrl?: string
  mirrorClose?: boolean; note?: string
}) {
  return post<TaskExternalRef>(`/api/tasks/${taskId}/external`, {
    company_id: data.companyId, connector_key: data.connectorKey,
    connector_label: data.connectorLabel || undefined,
    external_number: data.externalNumber || undefined,
    external_id: data.externalId || undefined,
    external_url: data.externalUrl || undefined,
    mirror_close: data.mirrorClose ?? false, note: data.note || undefined,
  })
}

/** Ответ синхронизации: `ok:false` — приложение состояния не отдало, и это
 *  надо показать словами, а не молча оставить старую отметку. */
export async function syncExternal(taskId: string, refId: string, companyId: string) {
  return post<TaskExternalRef & { ok: boolean; reason?: string; stages_added?: number }>(
    `/api/tasks/${taskId}/external/${refId}/sync?company_id=${encodeURIComponent(companyId)}`, {})
}

export async function unlinkExternal(taskId: string, refId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/external/${refId}?company_id=${encodeURIComponent(companyId)}`)
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
  reactionHours?: number | null; escalateToId?: string | null
}) {
  const body = {
    company_id: data.companyId, code: data.code, name: data.name,
    description: data.description || undefined, route: data.route,
    default_priority: data.defaultPriority, due_days: data.dueDays ?? null,
    is_active: data.isActive ?? true, sort_order: data.sortOrder ?? 100,
    reaction_hours: data.reactionHours ?? null,
    escalate_to_id: data.escalateToId || null,
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
