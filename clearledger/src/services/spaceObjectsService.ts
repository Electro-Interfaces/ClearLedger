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
export type SpaceEntity = 'objects' | 'organizations' | 'equipment' | 'users' | 'all'

export async function projectSpaceEntity(
  companyId: string, entity: SpaceEntity, app = 'support',
): Promise<ProjectionResult> {
  return post<ProjectionResult>(
    `/api/registry/project/${entity}?company_id=${encodeURIComponent(companyId)}&app=${encodeURIComponent(app)}`,
    {},
  )
}

export async function projectSpaceObjects(
  companyId: string, app = 'support',
): Promise<ProjectionResult> {
  return projectSpaceEntity(companyId, 'objects', app)
}

export interface SpaceOrganization {
  id: string
  name: string
  shortName?: string | null
  inn: string
  kpp?: string | null
  type: string
  legalAddress?: string | null
  phone?: string | null
  email?: string | null
}

export interface SpaceEquipmentUnit {
  id: string
  ecoObjectId?: string | null
  type: string
  model?: string | null
  manufacturer?: string | null
  serialNumber?: string | null
  inventoryNumber?: string | null
  status: string
  state?: string | null
}

/** Организации компании — общие карточки юрлиц (роль остаётся прикладной). */
export async function listSpaceOrganizations(companyId: string): Promise<SpaceOrganization[]> {
  const r = await get<{ organizations: SpaceOrganization[] }>('/api/registry/organizations', {
    company_id: companyId,
  })
  return r.organizations
}

export interface SpaceContract {
  id: string
  number: string
  date: string
  type: string
  kind?: string | null
  /** in — платит компания, out — платят ей, unknown — вид договора не задан. */
  direction: 'in' | 'out' | 'unknown'
  basis?: string | null
  counterpartyId?: string | null
  counterpartyName?: string | null
  counterpartyInn?: string | null
  /** company — весь периметр, locations — набор объектов, unassigned — охват не задан. */
  scopeType: string
  objectsCount: number
  validUntil?: string | null
  isClosed: boolean
}

/** Договоры компании — контрагент уже разрешён в имя, охват считается по объектам. */
export async function listSpaceContracts(companyId: string): Promise<SpaceContract[]> {
  const r = await get<{ contracts: SpaceContract[] }>('/api/registry/contracts', {
    company_id: companyId,
  })
  return r.contracts
}

/** Единицы оборудования компании — паспорт (что за железо и где стоит). */
export async function listSpaceEquipment(companyId: string): Promise<SpaceEquipmentUnit[]> {
  const r = await get<{ equipment: SpaceEquipmentUnit[] }>('/api/registry/equipment', {
    company_id: companyId,
  })
  return r.equipment
}

/** Сущность нормализованной базы пространства (витрина «Данные» → «База пространства»). */
export interface DataModelEntity {
  key: string
  label: string
  table: string
  records: number
  sources: string
  consumers: string
  link: string
  /** Записей с незакрытой связью: роль строкой вместо ссылки, нет объекта/договора. */
  gap: number | null
  gapLabel: string | null
}

export interface DataModelDomain {
  key: string
  label: string
  entities: DataModelEntity[]
}

export interface SpaceDataModel {
  domains: DataModelDomain[]
  totals: { entities: number; records: number; gaps: number; filled: number }
}

export async function getSpaceDataModel(companyId: string): Promise<SpaceDataModel> {
  return get<SpaceDataModel>('/api/registry/data-model', { company_id: companyId })
}

/** Одна роль, записанная текстом: сколько имён, сколько сойдётся с карточками. */
export interface LinkRoleReport {
  key: string
  label: string
  table: string
  field: string
  /** Различных значений текста и записей за ними. */
  names: number
  records: number
  /** Имён нашлось в справочнике / потребуют новой карточки. */
  matched: number
  created: number
  /** Записей будет связано и пропущено (мусорные значения вроде «уточняется»). */
  linked: number
  skipped: number
  samples: string[]
}

export interface LinkCounterpartiesResult {
  applied: boolean
  links: LinkRoleReport[]
  totals: { linked: number; created: number }
}

/**
 * Свести текстовые роли (собственник, подрядчик, поставщик, сетевая организация) с
 * карточками контрагентов. Без `apply` — только отчёт: сколько карточек придётся
 * завести, решает человек.
 */
export async function linkCounterparties(
  companyId: string, apply = false,
): Promise<LinkCounterpartiesResult> {
  const qs = new URLSearchParams({ company_id: companyId, apply: String(apply) })
  return post<LinkCounterpartiesResult>(`/api/registry/link-counterparties?${qs}`)
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
  return projectSpaceEntity(companyId, 'users', app)
}
