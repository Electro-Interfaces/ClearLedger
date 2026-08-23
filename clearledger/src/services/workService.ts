/**
 * Единый список работы: документы и поручения одной лентой (этап 13б).
 *
 * Отдельный сервис, а не ветка в `docsService`/`tasksService`: у ленты своя
 * ручка и своя проекция, и приписать её к одному из контуров значило бы сказать,
 * что она принадлежит ему, — а она общая.
 */
import { get } from './apiClient'

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
