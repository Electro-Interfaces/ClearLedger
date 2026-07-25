/**
 * Клиент реестра объектов пространства (docs/SPACE.md §5).
 *
 * Объект компании — общая сущность: на неё ссылаются все приложения-разрезы. Ведение
 * карточки — админская функция Центра управления, поэтому UI ходит сюда, а не в
 * прикладной `/api/locations` (тот остаётся рабочим разрезом Ledger над теми же данными).
 * Бэкенд: routers/space_registry_router.py.
 */
import { get, post, patch } from './apiClient'

export interface SpaceObject {
  id: string
  companyId: string
  code: string
  name: string
  type: string
  status: string
  operationalStatus: string
  address?: string | null
  city?: string | null
  street?: string | null
  house?: string | null
  latitude?: number | null
  longitude?: number | null
  regionId?: string | null
  description?: string | null
  createdAt: string
  updatedAt: string
}

export interface SpaceObjectInput {
  code: string
  name: string
  type?: string
  status?: string
  address?: string | null
  description?: string | null
  city?: string | null
  street?: string | null
  house?: string | null
  latitude?: number | null
  longitude?: number | null
}

/** Человеческие названия типов и статусов — общие для форм и таблиц. */
export const OBJECT_TYPE_LABELS: Record<string, string> = {
  fuel_station: 'АЗС',
  ev_charging: 'ЭЗС',
  retail: 'Магазин',
  office: 'Офис',
  warehouse: 'Склад',
  other: 'Прочее',
}

export const OBJECT_STATUS_LABELS: Record<string, string> = {
  active: 'Действует',
  planned: 'Планируется',
  closed: 'Закрыт',
}

/** Объекты компании. Компания обязательна: реестр без неё не имеет смысла (§2). */
export async function listSpaceObjects(companyId: string, query?: string): Promise<SpaceObject[]> {
  const r = await get<{ objects: SpaceObject[] }>('/api/registry/objects', {
    company_id: companyId, q: query || undefined,
  })
  return r.objects
}

export async function createSpaceObject(companyId: string, data: SpaceObjectInput): Promise<SpaceObject> {
  return post<SpaceObject>(`/api/registry/objects?company_id=${encodeURIComponent(companyId)}`, data)
}

export async function updateSpaceObject(
  companyId: string, objectId: string, data: Partial<SpaceObjectInput>,
): Promise<SpaceObject> {
  return patch<SpaceObject>(
    `/api/registry/objects/${encodeURIComponent(objectId)}?company_id=${encodeURIComponent(companyId)}`,
    data,
  )
}

export interface ProjectionResult {
  app: string
  sent: number
  created: number
  updated: number
  skipped: unknown[]
}

/**
 * Отправить объекты компании в приложение-разрез. Идемпотентно: повтор обновляет
 * карточки, а не плодит дубли. Требует заданного соответствия компаний.
 */
export async function projectSpaceObjects(
  companyId: string, app = 'support',
): Promise<ProjectionResult> {
  return post<ProjectionResult>(
    `/api/registry/objects/project?company_id=${encodeURIComponent(companyId)}&app=${encodeURIComponent(app)}`,
    {},
  )
}

export interface ObjectTicket {
  id: string
  number: string | number
  title: string
  status: string
  priority?: string | null
  created_at: string
}

export interface ObjectTickets {
  app: string
  linked: boolean
  total: number
  open: number
  tickets: ObjectTicket[]
}

/**
 * Заявки соседнего разреза по этому объекту. Данные не копируются в Учёт — спрашиваем
 * Координатор в момент показа, чтобы в пространстве не завелась вторая правда о заявках.
 */
export async function getObjectTickets(
  companyId: string, objectId: string, app = 'support',
): Promise<ObjectTickets> {
  return get<ObjectTickets>(`/api/registry/objects/${encodeURIComponent(objectId)}/tickets`, {
    company_id: companyId, app,
  })
}

/**
 * Отправить сотрудников компании в приложение. Пароли не передаются: вход в приложение
 * идёт единым входом Ядра, а у кого локальный пароль уже был — он сохраняется.
 */
export async function projectSpaceUsers(
  companyId: string, app = 'support',
): Promise<ProjectionResult> {
  return post<ProjectionResult>(
    `/api/registry/users/project?company_id=${encodeURIComponent(companyId)}&app=${encodeURIComponent(app)}`,
    {},
  )
}
