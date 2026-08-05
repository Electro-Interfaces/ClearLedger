/**
 * Приложение «Задачи» — работа компании (docs/TASKS.md ecosystem-deploy).
 * Движок свой, в Ядре: тип несёт маршрут, задача идёт по стадиям и переадресуется.
 */
import { get, post, put } from './apiClient'

export interface RouteStage { code: string; name: string }

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
  created_at: string | null
  updated_at: string | null
  closed_at: string | null
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

export interface TaskDetails extends SpaceTask {
  description: string | null
  events: TaskEvent[]
}

export type TaskScope = 'open' | 'mine' | 'closed' | 'all'

export async function listTasks(companyId: string, scope: TaskScope, opts?: {
  objectId?: string; typeId?: string
}) {
  return get<{ tasks: SpaceTask[]; total: number }>('/api/tasks', {
    company_id: companyId, scope,
    object_id: opts?.objectId || undefined, type_id: opts?.typeId || undefined,
  })
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
}) {
  return post<SpaceTask>(`/api/tasks/${id}/action`, {
    company_id: data.companyId,
    stage_code: data.stageCode,
    // null = снять исполнителя; undefined = не трогать.
    assignee_id: data.assigneeId === null ? '' : data.assigneeId,
    status: data.status, priority: data.priority,
    due_at: data.dueAt, note: data.note || undefined,
  })
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
