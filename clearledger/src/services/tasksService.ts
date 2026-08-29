/**
 * Приложение «Задачи» — работа компании (docs/TASKS.md ecosystem-deploy).
 * Движок свой, в Ядре: тип несёт маршрут, задача идёт по стадиям и переадресуется.
 */
import { del, get, patch, post, put, upload } from './apiClient'

/** Стадия маршрута. `column` — место стадии на общей доске пространства
 *  (этап 13а): его называет тот, кто рисует маршрут, потому что только он знает,
 *  что «Согласование с юристом» — это согласование, а не работа. Пусто — колонку
 *  угадывает эвристика по месту стадии в маршруте. */
export interface RouteStage { code: string; name: string; column?: WorkColumn }

/** Общая ось состояния работы: одна колонка на документ и на поручение. */
export type WorkColumn = 'new' | 'in_work' | 'approval' | 'external' | 'done'
export interface WorkColumnDef { code: WorkColumn; name: string }

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

export interface TaskVersion {
  id: string
  project_id: string
  name: string
  description: string | null
  /** open — набирается, released — выпущена, cancelled — отменена. */
  state: 'open' | 'released' | 'cancelled'
  released_on: string | null
  sort_order: number
  /** Состав: сколько задач закрыто в этой версии и сколько ещё висит. */
  fixed: number
  open: number
}

export interface TaskSprint {
  id: string
  project_id: string
  name: string
  /** planned — план, active — идёт, closed — итог подведён. */
  state: 'planned' | 'active' | 'closed'
  starts_on: string | null
  ends_on: string | null
  /** Сколько задач ушло обратно в бэклог при закрытии. */
  carried_over: number
  /** Итог тремя числами: взято, сделано, осталось. */
  taken: number
  done: number
  left: number
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
  /** «Исправлено в 1.4.2» — ответ заявителю; «обнаружено в» — с чего разбираться. */
  fix_version?: string | null
  fix_version_id?: string | null
  found_version?: string | null
  found_version_id?: string | null
  /** Колонка общей оси: где работа стоит, одинаково с документами. */
  state?: WorkColumn
  state_name?: string
  /** Пусто — задача в бэклоге: решили делать, не решили когда. */
  sprint?: string | null
  sprint_id?: string | null
  title: string
  /** Начало описания (200 знаков): о чём запись, не открывая её. */
  preview?: string | null
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
  /** Предмет работы: `site:<uuid>`, `contract:<uuid>`. Расшифровывается
   *  `docsService.resolveRefs` — сырая ссылка человеку ничего не говорит. */
  subject_ref?: string | null
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
  /** Как ЭТОТ человек разложил задачу у себя: день, подборка, звезда, сокрытие.
   *  `null` — не разложена. Есть только в списке задач; в карточке раскладка не
   *  показывается — там решают о самой работе. */
  mark?: import('./workService').PersonalMark | null
  visibility?: TaskVisibility
  /** Приложенные файлы — коротко, для строки списка. В записной книжке скриншот
   *  и есть содержание записи: узнавать о нём, открыв карточку, поздно. */
  attachments?: TaskFile[]
}

/** Вложение в строке списка: без прав и события — их спрашивают у карточки. */
export interface TaskFile {
  id: string
  file_name: string
  mime_type: string
  size: number
}

/** Кто видит запись: вся компания, причастные или только автор.
 *  Третье значение — личная записная книжка: её не видит и администратор. */
export type TaskVisibility = 'company' | 'private' | 'personal'

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
  visibility: TaskVisibility; waiting_for: 'us' | 'external' | null
}

/** Ответ действия: сервер может предупредить, не отказав (открытые подзадачи). */
export interface TaskActionResult extends SpaceTask {
  warning?: string
  mentioned?: string[]
}

export type TaskScope = 'open' | 'mine' | 'assigned' | 'watching' | 'overdue'
  | 'today' | 'waiting' | 'closed' | 'all'
  /** На разбор: живая работа без исполнителя — её надо взять, отдать или закрыть. */
  | 'triage'

export interface TaskFilters {
  objectId?: string; projectId?: string; typeId?: string; assigneeId?: string; authorId?: string
  fixVersionId?: string; foundVersionId?: string
  /** `backlog` — задачи без спринта; вместе с `sprintId` не используется. */
  sprintId?: string; backlog?: boolean
  /** Строка запроса: «проект: TF #нерешённые исполнитель: я». Разбирает сервер —
   *  одна реализация на форму и на строку, иначе они разойдутся. */
  query?: string
  stage?: string; priority?: string; labelId?: string; q?: string
  /** Круг записи: `personal` — своя записная книжка, её не видит никто. */
  visibility?: TaskVisibility
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

/** Что сервер понял из строки запроса. `unknown` показываем человеку: молча
 *  проглоченная опечатка сужает список, а он думает, что работы просто нет. */
export interface ParsedQuery {
  parsed: Record<string, string>
  unknown: string[]
  text: string | null
}

export async function listTasks(companyId: string, scope: TaskScope, opts?: TaskFilters) {
  return get<{
    tasks: SpaceTask[]; total: number; limit: number; offset: number
    query?: ParsedQuery
  }>(
    '/api/tasks', {
      company_id: companyId, scope,
      object_id: opts?.objectId || undefined, project_id: opts?.projectId || undefined,
      fix_version_id: opts?.fixVersionId || undefined,
      found_version_id: opts?.foundVersionId || undefined,
      sprint_id: opts?.sprintId || undefined,
      backlog: opts?.backlog ? 'true' : undefined,
      query: opts?.query || undefined,
      type_id: opts?.typeId || undefined,
      assignee_id: opts?.assigneeId || undefined, author_id: opts?.authorId || undefined,
      stage: opts?.stage || undefined, priority: opts?.priority || undefined,
      label_id: opts?.labelId || undefined, q: opts?.q || undefined,
      visibility: opts?.visibility || undefined,
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

/** Версии проекта. Без `projectId` — все версии компании: карточка задачи
 *  получает одним запросом всё, из чего может выбрать. */
export async function listTaskVersions(companyId: string, projectId?: string) {
  return get<{ versions: TaskVersion[] }>(
    '/api/tasks/versions',
    { company_id: companyId, project_id: projectId || undefined })
}

export async function createTaskVersion(data: {
  companyId: string; projectId: string; name: string
  description?: string; releasedOn?: string; sortOrder?: number
}) {
  return post<TaskVersion>('/api/tasks/versions', {
    company_id: data.companyId, project_id: data.projectId, name: data.name,
    description: data.description || undefined,
    released_on: data.releasedOn || undefined, sort_order: data.sortOrder ?? 100,
  })
}

export async function updateTaskVersion(id: string, data: {
  companyId: string; name?: string; description?: string
  state?: TaskVersion['state']; releasedOn?: string; sortOrder?: number
}) {
  return patch<TaskVersion>(`/api/tasks/versions/${id}`, {
    company_id: data.companyId, name: data.name, description: data.description,
    state: data.state, released_on: data.releasedOn, sort_order: data.sortOrder,
  })
}

/** Состав версии: что вошло, что осталось, что в ней обнаружено. Он же
 *  черновик списка изменений для ответа заявителю. */
export async function taskVersionSummary(id: string, companyId: string) {
  return get<{
    version: TaskVersion
    done: SpaceTask[]; left: SpaceTask[]; found: SpaceTask[]
  }>(`/api/tasks/versions/${id}/summary`, { company_id: companyId })
    .then((r) => ({
      ...r,
      done: (r.done ?? []).map(fillTask),
      left: (r.left ?? []).map(fillTask),
      found: (r.found ?? []).map(fillTask),
    }))
}

/** Спринты проекта. Без `projectId` — все спринты компании. */
/** Что сделано в коде по задаче: ветка, коммит, запрос на слияние.
 *  «Исправлено в версии» отвечает заявителю, это — разработчику: каким
 *  изменением. Ссылка, а не копия: содержимое живёт там, где живёт код. */
export interface TaskCodeRef {
  id: string
  kind: 'branch' | 'commit' | 'pr' | 'other'
  url: string
  title: string
  repo: string | null
  added_by?: string | null
  created_at?: string | null
}

export async function listTaskCode(taskId: string, companyId: string) {
  return get<{ code: TaskCodeRef[] }>(
    `/api/tasks/${taskId}/code`, { company_id: companyId })
}

export async function addTaskCode(taskId: string, data: {
  companyId: string; url: string; kind?: TaskCodeRef['kind']; title?: string
}) {
  return post<TaskCodeRef>(`/api/tasks/${taskId}/code`, {
    company_id: data.companyId, url: data.url,
    kind: data.kind, title: data.title,
  })
}

export async function deleteTaskCode(taskId: string, refId: string, companyId: string) {
  return del(`/api/tasks/${taskId}/code/${refId}?company_id=${encodeURIComponent(companyId)}`)
}

export async function listTaskSprints(companyId: string, projectId?: string) {
  return get<{ sprints: TaskSprint[] }>(
    '/api/tasks/sprints',
    { company_id: companyId, project_id: projectId || undefined })
}

export async function createTaskSprint(data: {
  companyId: string; projectId: string; name: string
  startsOn?: string; endsOn?: string
}) {
  return post<TaskSprint>('/api/tasks/sprints', {
    company_id: data.companyId, project_id: data.projectId, name: data.name,
    starts_on: data.startsOn || undefined, ends_on: data.endsOn || undefined,
  })
}

/** Правка спринта. `state: 'closed'` подводит итог: незакрытые задачи уходят в
 *  бэклог, их число остаётся в спринте как «перенесено». */
export async function updateTaskSprint(id: string, data: {
  companyId: string; name?: string; state?: TaskSprint['state']
  startsOn?: string; endsOn?: string
}) {
  return patch<TaskSprint>(`/api/tasks/sprints/${id}`, {
    company_id: data.companyId, name: data.name, state: data.state,
    starts_on: data.startsOn, ends_on: data.endsOn,
  })
}

export async function taskSprintSummary(id: string, companyId: string) {
  return get<{ sprint: TaskSprint; done: SpaceTask[]; left: SpaceTask[] }>(
    `/api/tasks/sprints/${id}/summary`, { company_id: companyId })
    .then((r) => ({
      ...r, done: (r.done ?? []).map(fillTask), left: (r.left ?? []).map(fillTask),
    }))
}

export async function listTaskTypes(companyId: string) {
  return get<{ types: TaskType[]; default_route: RouteStage[]; columns?: WorkColumnDef[] }>(
    '/api/tasks/types', { company_id: companyId })
}

export async function createTask(data: {
  companyId: string; title: string; description?: string
  projectId?: string; typeId?: string; assigneeId?: string; objectId?: string
  foundVersionId?: string; fixVersionId?: string
  priority?: string; dueAt?: string
  /** Круг с самого начала: выставлять его вторым вызовом значит на миг
   *  показать личную запись всей компании. */
  visibility?: TaskVisibility
  /** Своё напоминание о записи — ставится вместе с ней. */
  remindAt?: string
}) {
  return post<SpaceTask>('/api/tasks', {
    company_id: data.companyId, title: data.title,
    description: data.description || undefined,
    project_id: data.projectId || undefined,
    type_id: data.typeId || undefined, assignee_id: data.assigneeId || undefined,
    object_id: data.objectId || undefined, priority: data.priority || undefined,
    due_at: data.dueAt || undefined,
    visibility: data.visibility || undefined,
    remind_at: data.remindAt || undefined,
  })
}

/** Одно действие над задачей: стадия, переадресация, завершение или реплика. */
export async function taskAction(id: string, data: {
  companyId: string; stageCode?: string; assigneeId?: string | null
  status?: string; priority?: string; dueAt?: string; note?: string
  title?: string; description?: string; objectId?: string | null
  projectId?: string
  /** null = снять версию; undefined = не трогать. */
  fixVersionId?: string | null; foundVersionId?: string | null
  /** null = вернуть в бэклог; undefined = не трогать. */
  sprintId?: string | null
  addLabelId?: string; removeLabelId?: string; estimate?: string
  visibility?: TaskVisibility
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
    fix_version_id: data.fixVersionId === null ? '' : data.fixVersionId,
    found_version_id: data.foundVersionId === null ? '' : data.foundVersionId,
    sprint_id: data.sprintId === null ? '' : data.sprintId,
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

export async function listTaskViews(companyId: string, listScope: 'task' | 'doc' | 'work' = 'task') {
  return get<{ views: TaskView[] }>(
    '/api/tasks/views', { company_id: companyId, list_scope: listScope })
}

/** Сохранённый отбор. `listScope`: `task` — реестр поручений, `doc` —
 *  документов, `work` — общая лента работы. Справочник один на все три. */
export async function createTaskView(data: {
  companyId: string; name: string; query: Record<string, string>; shared?: boolean
  listScope?: 'task' | 'doc' | 'work'
}) {
  return post<TaskView>('/api/tasks/views', {
    company_id: data.companyId, name: data.name, query: data.query,
    shared: data.shared ?? false, list_scope: data.listScope ?? 'task',
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

/**
 * Завести обычный набор заготовок работы: разбор ошибки, задача разработки,
 * выпуск версии, разбор обращения. Идемпотентно по имени — нажатие второй раз
 * ничего не задвоит и не тронет переписанное под себя.
 */
export async function createStarterTemplates(companyId: string) {
  return post<{ added: number }>(
    `/api/tasks/templates/starter?company_id=${encodeURIComponent(companyId)}`, {})
}
