/**
 * Клиент API складского учёта оборудования ЭЗС (/api/equipment/*).
 *
 * Раздел «Управленческий» → группа «Оборудование» (energy/РусГидро):
 * единицы (станции-железки), движения жизненного цикла, склады, ЗИП.
 * Допустимые операции единицы приходят с сервера (allowedOps) — матрица
 * переходов НЕ дублируется на фронте.
 */

import { del, get, patch, post, put, upload } from './apiClient'

// ─── справочники состояний/операций (метки + приглушённые классы) ──────────

export type UnitState =
  | 'in_stock_new' | 'in_stock_used' | 'reserved' | 'in_installation'
  | 'in_operation' | 'in_repair' | 'returned_to_vendor' | 'written_off'

export type UnitOp =
  | 'receipt' | 'transfer' | 'reserve' | 'unreserve' | 'to_installation'
  | 'commissioning' | 'dismantle' | 'to_repair' | 'from_repair'
  | 'to_vendor' | 'write_off' | 'correction' | 'cancel'

export const UNIT_STATE_META: Record<UnitState, { label: string; cls: string }> = {
  in_stock_new: { label: 'На складе (новая)', cls: 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80' },
  in_stock_used: { label: 'На складе (б/у)', cls: 'border-emerald-400/40 text-emerald-700/80 dark:text-emerald-400/70' },
  reserved: { label: 'Резерв', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80' },
  in_installation: { label: 'В монтаже', cls: 'border-sky-400/50 text-sky-600 dark:text-sky-300/80' },
  in_operation: { label: 'В эксплуатации', cls: 'border-sky-500/50 text-sky-700 dark:text-sky-300' },
  in_repair: { label: 'В ремонте', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80' },
  returned_to_vendor: { label: 'Возвращена производителю', cls: 'border-zinc-500/60 text-zinc-500' },
  written_off: { label: 'Списана', cls: 'border-zinc-600 text-zinc-500' },
}

export const UNIT_OP_META: Record<UnitOp, { label: string }> = {
  receipt: { label: 'Поступление' },
  transfer: { label: 'Перемещение' },
  reserve: { label: 'Резервирование' },
  unreserve: { label: 'Снятие резерва' },
  to_installation: { label: 'Передача в монтаж' },
  commissioning: { label: 'Запуск в эксплуатацию' },
  dismantle: { label: 'Демонтаж' },
  to_repair: { label: 'Передача в ремонт' },
  from_repair: { label: 'Возврат из ремонта' },
  to_vendor: { label: 'Возврат производителю' },
  write_off: { label: 'Списание' },
  correction: { label: 'Корректировка' },
  cancel: { label: 'Отмена документа' },
}

/** Виды единиц учёта — единственное место, где они названы. Основной предмет — станция. */
export const UNIT_KIND_LABELS: Record<string, string> = {
  station: 'Зарядная станция', cabinet: 'Шкаф', transformer: 'Трансформатор', other: 'Прочее оборудование',
}
export const unitKindLabel = (kind?: string | null) => UNIT_KIND_LABELS[kind || 'station'] ?? kind ?? '—'

export const CUSTODIAN_LABELS: Record<string, string> = {
  warehouse: 'Склад', site: 'Станция', contractor: 'Подрядчик',
  vendor: 'Производитель', none: '—',
}

export const SPARE_CATEGORY_META: Record<string, string> = {
  power_module: 'Силовой модуль', controller: 'Контроллер', connector: 'Коннектор',
  cable: 'Кабель', display: 'Дисплей', board: 'Плата',
  tool: 'Инструмент', consumable: 'Расходные материалы', other: 'Прочее',
}
/** Запчасти к станциям; остальные категории — прочие предметы склада. */
export const SPARE_STATION_CATEGORIES = ['power_module', 'controller', 'connector', 'display', 'board']

// ─── типы ───────────────────────────────────────────────────────────────────

export interface LocBrief { id: string; name: string; type: string; address?: string | null }

export interface EquipmentUnit {
  id: string
  kind: string
  serialNumber: string | null
  vendor: string | null
  vendorRaw: string | null
  model: string | null
  stationType: string | null
  powerKwt: number | null
  connectorsCount: number | null
  connectorTypes: string | null
  inventoryNumber: string | null
  supplier: string | null
  purchaseDoc: string | null
  purchaseDate: string | null
  warrantyUntil: string | null
  purchaseAmount: number | null
  vatAmount: number | null
  state: UnitState
  stateLabel: string
  isUsed: boolean
  custodian: string
  custodianName: string | null
  location: LocBrief | null
  originLocation: LocBrief | null
  reservedFor: LocBrief | null
  notes: string | null
  /** Графы складского реестра заказчика. */
  region: string | null
  keeper: string | null
  accountingNo: string | null
  externalNo: string | null
  speedClass: string | null
  ownerName?: string | null
  /** Поставщик подтвердил количество и порты. Ложь — позиция ждёт уточнения. */
  dataConfirmed: boolean
  unconfirmedReason: string | null
  supplyId: string | null
  supplyLineId: string | null
  supplyNumber: string | null
  createdAt: string | null
  updatedAt: string | null
  allowedOps: UnitOp[]
  /** Реквизиты для 1С: номенклатура, поставщик и балансодержатель ссылками, ОС. */
  nomenclatureId?: string | null
  supplierId?: string | null
  ownerId?: string | null
  okof?: string | null
  depreciationGroup?: string | null
  usefulLifeMonths?: number | null
  bpRef?: string | null
  /** Только в карточке: названия ссылок и счёт, на котором единица сейчас. */
  nomenclature?: { id: string; name: string; kind: string; kindLabel: string; account: string } | null
  supplierName?: string | null
  ownerRefName?: string | null
  account?: string | null
}

export interface EquipmentMovement {
  id: string
  unitId: string
  op: UnitOp
  opLabel: string
  fromLocation: LocBrief | null
  toLocation: LocBrief | null
  fromState: string | null
  toState: string | null
  fromStateLabel: string | null
  toStateLabel: string | null
  counterparty: string | null
  occurredOn: string
  basis: string | null
  comment: string | null
  supplyId: string | null
  supplyNumber: string | null
  createdBy: string | null
  createdAt: string | null
  documentId?: string | null
  documentNumber?: string | null
  unit?: { serialNumber: string | null; vendor: string | null; model: string | null; inventoryNumber: string | null }
}

export interface UnitDetail extends EquipmentUnit { movements: EquipmentMovement[] }

export interface UnitInPayload {
  kind?: string
  serialNumber?: string | null
  vendor?: string | null
  model?: string | null
  stationType?: string | null
  powerKwt?: number | null
  connectorsCount?: number | null
  connectorTypes?: string | null
  inventoryNumber?: string | null
  supplier?: string | null
  purchaseDoc?: string | null
  purchaseDate?: string | null
  warrantyUntil?: string | null
  isUsed?: boolean
  notes?: string | null
  initialLocationId?: string
  occurredOn?: string
  basis?: string
  comment?: string
  nomenclatureId?: string | null
  supplierId?: string | null
  ownerId?: string | null
  purchaseAmount?: number | null
  vatAmount?: number | null
  accountingNo?: string | null
  okof?: string | null
  depreciationGroup?: string | null
  usefulLifeMonths?: number | null
  bpRef?: string | null
}

export interface MovementPayload {
  op: UnitOp
  occurredOn?: string
  toLocationId?: string
  toState?: string
  custodian?: string
  counterparty?: string
  reservedForLocationId?: string
  basis?: string
  comment?: string
  syncPassport?: boolean
}

export interface WarehouseSummaryRow {
  card?: WarehouseCard
  location: LocBrief
  status?: 'active' | 'closed'
  unitsByState: Partial<Record<UnitState, number>>
  unitsTotal: number
  sparePositions: number
  spareQty: number
  /** Стоимость остатка: единицы на складе + сумма остатка ЗИП. */
  amount?: number
}

export interface EquipmentOverview {
  countsByState: Partial<Record<UnitState, number>>
  countsByCustodian: Record<string, number>
  countsByVendor: { vendor: string; count: number }[]
  inRepairOver30d: number
  recentMovements: EquipmentMovement[]
}

export interface ImportReport {
  created: number
  updated: number
  skipped: number
  errors: { row: number; message: string }[]
  unknownColumns: string[]
  warehousesCreated: string[]
  stateUnknown: { row: number; value: string | null }[]
  dryRun: boolean
}

/** Вид номенклатуры: станция и оборудование — по экземплярам, остальное — количеством. */
export type NomenclatureKind = 'station' | 'equipment' | 'spare' | 'material' | 'inventory' | 'goods'

export interface SparePart {
  id: string
  name: string
  category: string
  vendor: string | null
  article: string | null
  compatibleModels: string | null
  unitLabel: string
  notes: string | null
  isArchived: boolean
  totalQty: number
  totalAmount?: number
  byLocation: { locationId: string; locationName: string; qty: number; amount?: number }[]
  kind?: NomenclatureKind
  kindLabel?: string
  serial?: boolean
  model?: string | null
  unitCode?: string | null
  vatRate?: string | null
  account?: string | null
  bpRef?: string | null
  /** Сколько единиц-экземпляров связано с номенклатурой (станции, оборудование). */
  units?: number
}

export interface SparePartPayload {
  name: string
  category: string
  vendor?: string | null
  article?: string | null
  compatibleModels?: string | null
  unitLabel?: string
  notes?: string | null
  kind?: NomenclatureKind
  model?: string | null
  unitCode?: string | null
  vatRate?: string | null
  account?: string | null
  bpRef?: string | null
}

export interface SpareMovementPayload {
  op: 'receipt' | 'issue' | 'transfer' | 'write_off' | 'correction'
  qty: number
  fromLocationId?: string
  toLocationId?: string
  targetUnitId?: string
  targetLocationId?: string
  occurredOn?: string
  basis?: string
  comment?: string
}

export interface SpareMovementRow {
  id: string
  part: { id: string; name: string; unitLabel: string }
  op: string
  qty: number
  /** Знаковое изменение остатка — у корректировки, инвентаризации и отмены документа. */
  delta?: number | null
  documentId?: string | null
  documentNumber?: string | null
  targetUnit?: SpareTargetUnit | null
  targetNote?: string | null
  fromLocation: LocBrief | null
  toLocation: LocBrief | null
  targetUnitId: string | null
  targetLocation: LocBrief | null
  occurredOn: string
  basis: string | null
  comment: string | null
  createdBy: string | null
}

// ─── единицы ────────────────────────────────────────────────────────────────

/**
 * Контур рабочей области. Панель фильтров стоит над разделом целиком, поэтому
 * её обещание («Приморский край · ЭЗС 648») несут все экраны группы, а не один
 * парк — замечание заказчика 24.08.2026 было про раздел.
 */
export interface EquipmentScope {
  regionIds?: string[]
  stationCodes?: string[]
  locationIds?: string[]
}

export function scopeParams(s: EquipmentScope | undefined): Record<string, string> {
  if (!s) return {}
  return {
    ...(s.regionIds?.length ? { region_ids: s.regionIds.join(',') } : {}),
    ...(s.stationCodes?.length ? { station_codes: s.stationCodes.join(',') } : {}),
    ...(s.locationIds?.length ? { location_ids: s.locationIds.join(',') } : {}),
  }
}

export async function listUnits(p: {
  companyId: string
  state?: string
  locationId?: string
  vendor?: string
  custodian?: string
  q?: string
  kind?: string
  sort?: string
  dir?: 'asc' | 'desc'
  scope?: EquipmentScope
  page?: number
  pageSize?: number
}): Promise<{
  items: EquipmentUnit[]; total: number
  /** По всему отбору, а не по странице; состояния — без учёта отбора по состоянию. */
  counts?: { byState: Partial<Record<UnitState, number>>; unconfirmed: number }
}> {
  return get('/api/equipment/units', {
    company_id: p.companyId,
    ...(p.state ? { state: p.state } : {}),
    ...(p.locationId ? { location_id: p.locationId } : {}),
    ...(p.vendor ? { vendor: p.vendor } : {}),
    ...(p.custodian ? { custodian: p.custodian } : {}),
    ...(p.q ? { q: p.q } : {}),
    ...(p.kind ? { kind: p.kind } : {}),
    ...(p.sort ? { sort: p.sort, dir: p.dir ?? 'desc' } : {}),
    ...scopeParams(p.scope),
    page: p.page ?? 1, page_size: p.pageSize ?? 100,
  })
}

export async function createUnit(companyId: string, body: UnitInPayload): Promise<EquipmentUnit & { documentNumber?: string | null }> {
  return post(`/api/equipment/units?company_id=${companyId}`, body)
}

export async function getUnit(companyId: string, unitId: string): Promise<UnitDetail> {
  return get(`/api/equipment/units/${unitId}`, { company_id: companyId })
}

export async function patchUnit(companyId: string, unitId: string, body: Partial<UnitInPayload>): Promise<EquipmentUnit> {
  return patch(`/api/equipment/units/${unitId}?company_id=${companyId}`, body)
}

export async function deleteUnit(companyId: string, unitId: string): Promise<{ deleted: string }> {
  return del(`/api/equipment/units/${unitId}?company_id=${companyId}`)
}

export async function applyUnitMovement(
  companyId: string, unitId: string, body: MovementPayload,
): Promise<{ unit: EquipmentUnit; movement: EquipmentMovement; documentNumber?: string | null }> {
  return post(`/api/equipment/units/${unitId}/movements?company_id=${companyId}`, body)
}

export async function dismantleFromSite(companyId: string, body: {
  siteLocationId: string
  warehouseId: string
  occurredOn?: string
  basis?: string
  comment?: string
  setDecommissioned?: boolean
}): Promise<{ unit: EquipmentUnit; movement: EquipmentMovement; unitCreated: boolean; documentNumber?: string | null }> {
  return post(`/api/equipment/dismantle?company_id=${companyId}`, body)
}

// ─── журнал движений ────────────────────────────────────────────────────────

export async function listMovements(p: {
  companyId: string
  op?: string
  locationId?: string
  unitId?: string
  dateFrom?: string
  dateTo?: string
  page?: number
  pageSize?: number
}): Promise<{ items: EquipmentMovement[]; total: number }> {
  return get('/api/equipment/movements', {
    company_id: p.companyId,
    ...(p.op ? { op: p.op } : {}),
    ...(p.locationId ? { location_id: p.locationId } : {}),
    ...(p.unitId ? { unit_id: p.unitId } : {}),
    ...(p.dateFrom ? { date_from: p.dateFrom } : {}),
    ...(p.dateTo ? { date_to: p.dateTo } : {}),
    page: p.page ?? 1, page_size: p.pageSize ?? 200,
  })
}

// ─── склады / обзор / импорт ────────────────────────────────────────────────

export async function getWarehousesSummary(companyId: string): Promise<{
  warehouses: WarehouseSummaryRow[]
  external: { custodian: string; custodianLabel: string; unitsTotal: number; names: string[] }[]
}> {
  return get('/api/equipment/warehouses/summary', { company_id: companyId })
}

export async function getEquipmentOverview(
  companyId: string, scope?: EquipmentScope,
): Promise<EquipmentOverview> {
  return get('/api/equipment/overview', { company_id: companyId, ...scopeParams(scope) })
}

export async function importUnitsXlsx(companyId: string, file: File, dryRun: boolean): Promise<ImportReport> {
  const fd = new FormData()
  fd.append('file', file)
  return upload(`/api/equipment/import?company_id=${companyId}&dry_run=${dryRun}`, fd)
}

// ─── ЗИП ────────────────────────────────────────────────────────────────────

export async function listSpareParts(p: {
  companyId: string
  q?: string
  category?: string
  includeArchived?: boolean
  /** Без отбора — только количественная номенклатура (ЗИП, материалы). */
  kind?: string
  includeSerial?: boolean
}): Promise<SparePart[]> {
  return get('/api/equipment/spare-parts', {
    company_id: p.companyId,
    ...(p.q ? { q: p.q } : {}),
    ...(p.category ? { category: p.category } : {}),
    ...(p.includeArchived ? { include_archived: 'true' } : {}),
    ...(p.kind ? { kind: p.kind } : {}),
    ...(p.includeSerial ? { include_serial: 'true' } : {}),
  })
}

export async function createSparePart(companyId: string, body: SparePartPayload): Promise<SparePart> {
  return post(`/api/equipment/spare-parts?company_id=${companyId}`, body)
}

export async function updateSparePart(companyId: string, partId: string, body: SparePartPayload): Promise<SparePart> {
  return patch(`/api/equipment/spare-parts/${partId}?company_id=${companyId}`, body)
}

export async function deleteSparePart(companyId: string, partId: string): Promise<{ deleted?: string; archived?: string; reason?: string }> {
  return del(`/api/equipment/spare-parts/${partId}?company_id=${companyId}`)
}

export async function applySpareMovement(
  companyId: string, partId: string, body: SpareMovementPayload,
): Promise<{ movementId: string | null; documentId: string; documentNumber: string; stock: { locationId: string; locationName: string; qty: number }[] }> {
  return post(`/api/equipment/spare-parts/${partId}/movements?company_id=${companyId}`, body)
}

export async function listSpareMovements(p: {
  companyId: string
  partId?: string
  locationId?: string
  op?: string
  dateFrom?: string
  dateTo?: string
  page?: number
  pageSize?: number
}): Promise<{ items: SpareMovementRow[]; total: number }> {
  return get('/api/equipment/spare-parts/movements/journal', {
    company_id: p.companyId,
    ...(p.partId ? { part_id: p.partId } : {}),
    ...(p.locationId ? { location_id: p.locationId } : {}),
    ...(p.op ? { op: p.op } : {}),
    ...(p.dateFrom ? { date_from: p.dateFrom } : {}),
    ...(p.dateTo ? { date_to: p.dateTo } : {}),
    page: p.page ?? 1, page_size: p.pageSize ?? 200,
  })
}

// Документы ЗИП: операция оформляется документом на несколько строк и проводится
// целиком; исправление — отменой и новым документом.

export type SpareDocOp = 'receipt' | 'issue' | 'transfer' | 'write_off' | 'inventory'
export const SPARE_DOC_META: Record<SpareDocOp, { label: string; title: string; prefix: string }> = {
  receipt: { label: 'Приход', title: 'Приходный ордер (М-4)', prefix: 'ПЗ' },
  issue: { label: 'Отпуск на станцию', title: 'Требование-накладная на отпуск (М-11)', prefix: 'РЗП' },
  transfer: { label: 'Перемещение', title: 'Накладная на перемещение', prefix: 'ПЗП' },
  write_off: { label: 'Списание', title: 'Акт на списание', prefix: 'СЗП' },
  inventory: { label: 'Инвентаризация', title: 'Инвентаризационная опись (ИНВ-3)', prefix: 'ИНВ' },
}
/** Станция-получатель: в эксплуатации — название станции, иначе модель единицы. */
export interface SpareTargetUnit { id: string; serialNumber: string | null; name: string }
export interface SpareDocLine {
  partId: string; name: string; article: string | null; category: string | null; unitLabel: string
  qty?: number; book?: number | null; fact?: number; delta?: number | null
  /** Цена без НДС (приход, оценка излишка) и сумма строки — расход идёт по средней. */
  price?: number | null; amount?: number | null
}
export interface SpareDocument {
  id: string; op: SpareDocOp; opLabel: string; title: string; number: string; docDate: string
  status: 'posted' | 'cancelled' | 'draft'
  amount?: number; primaryNumber?: string | null; primaryDate?: string | null
  bpRef?: string | null; bpExportedAt?: string | null; postedAt?: string | null
  counterpartyId: string | null; counterpartyName: string | null; contractId: string | null; contractLabel: string | null
  fromLocationId: string | null; fromLocation: string | null; toLocationId: string | null; toLocation: string | null
  targetUnit: SpareTargetUnit | null; targetLocation: string | null; targetNote: string | null
  repairDocument: { id: string; number: string | null } | null
  responsibleFrom: string | null; responsibleTo: string | null; basis: string | null; comment: string | null
  createdBy: string | null; createdAt: string | null
  cancelledAt: string | null; cancelledBy: string | null; cancelReason: string | null
  positions: number; lines?: SpareDocLine[]; warnings?: string[]
  /** Счёт и статья затрат отпуска и списания (дебет проводки в 1С). */
  costAccount?: string | null; costItem?: string | null
}
export interface SpareDocPayload {
  /** Ключ документа от формы: повторная отправка не проводит документ дважды. */
  id: string; op: SpareDocOp; docDate: string; number?: string
  lines: { partId: string; qty?: number; fact?: number; price?: number | null }[]
  fromLocationId?: string; toLocationId?: string; targetUnitId?: string; targetNote?: string
  repairDocumentId?: string; counterpartyId?: string; contractId?: string
  responsibleFrom?: string; responsibleTo?: string; basis?: string; comment?: string
  primaryNumber?: string; primaryDate?: string
  /** Счёт и статья затрат — у отпуска и списания (как в «Требовании-накладной» 1С). */
  costAccount?: string; costItem?: string
  /** Сохранить черновиком: номер занят, остатки не тронуты. */
  draft?: boolean
}
export interface SpareCountSheet {
  location: { id: string; name: string }
  lines: { partId: string; name: string; article: string | null; category: string; unitLabel: string; book: number }[]
}

export const listSpareDocuments = (p: {
  companyId: string; op?: string; status?: string; locationId?: string; counterpartyId?: string; contractId?: string
  partId?: string; dateFrom?: string; dateTo?: string; q?: string; limit?: number; offset?: number
}) => get<{ items: SpareDocument[]; total: number }>('/api/equipment/spare-documents', {
  company_id: p.companyId, op: p.op || undefined, status: p.status || undefined, location_id: p.locationId || undefined,
  counterparty_id: p.counterpartyId || undefined, contract_id: p.contractId || undefined, part_id: p.partId || undefined,
  date_from: p.dateFrom || undefined, date_to: p.dateTo || undefined, q: p.q || undefined,
  limit: p.limit ?? 50, offset: p.offset ?? 0 })
export const getSpareDocument = (companyId: string, id: string) =>
  get<SpareDocument>(`/api/equipment/spare-documents/${id}`, { company_id: companyId })
export const postSpareDocument = (companyId: string, body: SpareDocPayload) =>
  post<SpareDocument>(`/api/equipment/spare-documents?company_id=${companyId}`, body)
export const cancelSpareDocument = (companyId: string, id: string, reason: string) =>
  post<SpareDocument>(`/api/equipment/spare-documents/${id}/cancel?company_id=${companyId}`, { reason })
export const updateSpareDraft = (companyId: string, id: string, body: SpareDocPayload) =>
  patch<SpareDocument>(`/api/equipment/spare-documents/${id}?company_id=${companyId}`, body)
export const postSpareDraft = (companyId: string, id: string) =>
  post<SpareDocument>(`/api/equipment/spare-documents/${id}/post?company_id=${companyId}`, {})
export const deleteSpareDraft = (companyId: string, id: string) =>
  del<{ deleted: string; number: string }>(`/api/equipment/spare-documents/${id}?company_id=${companyId}`)
export const getSpareCountSheet = (companyId: string, locationId: string) =>
  get<SpareCountSheet>('/api/equipment/spare-documents/count-sheet', { company_id: companyId, location_id: locationId })

// ─── документы поставки/возврата (слой оснований поверх движений) ────────────

export type SupplyDocType = 'supply' | 'return'
export type SupplyStatus =
  | 'draft' | 'ordered' | 'partially_received' | 'received' | 'closed' | 'cancelled'
export type SupplyLineKind = 'station' | 'spare'

export const SUPPLY_TYPE_META: Record<SupplyDocType, { label: string; cls: string }> = {
  supply: { label: 'Поставка', cls: 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80' },
  return: { label: 'Возврат', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80' },
}

export const SUPPLY_STATUS_META: Record<SupplyStatus, { label: string; cls: string }> = {
  draft: { label: 'Черновик', cls: 'border-zinc-500/60 text-zinc-500' },
  ordered: { label: 'Проведён', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80' },
  partially_received: { label: 'Принят частично', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80' },
  received: { label: 'Принят', cls: 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80' },
  closed: { label: 'Закрыт', cls: 'border-emerald-500/50 text-emerald-700 dark:text-emerald-300' },
  cancelled: { label: 'Отменён', cls: 'border-zinc-600 text-zinc-500' },
}

export interface SupplyLine {
  id: string
  lineKind: SupplyLineKind
  partId: string | null
  name: string | null
  vendor: string | null
  model: string | null
  stationType: string | null
  powerKwt: number | null
  connectorsCount: number | null
  connectorTypes: string | null
  qtyPlanned: number
  qtyReceived: number
  unitPrice: number | null
  vatRate: string | null
  note: string | null
}

export interface SupplyHead {
  id: string
  docType: SupplyDocType
  number: string
  docDate: string
  status: SupplyStatus
  counterpartyId: string | null
  counterpartyName: string | null
  contractId: string | null
  warehouseId: string | null
  currency: string
  amountTotal: number | null
  vatTotal: number | null
  note: string | null
  createdByName: string | null
}

export interface SupplyDoc extends SupplyHead {
  lines: SupplyLine[]
  qtyPlanned: number
  qtyReceived: number
}

export interface SupplyListRow extends SupplyHead {
  linesCount: number
  qtyPlanned: number
  qtyReceived: number
}

export interface SupplierBrief { id: string; name: string; shortName: string | null; inn: string }

export interface SupplyLinePayload {
  lineKind: SupplyLineKind
  partId?: string | null
  name?: string | null
  qtyPlanned: number
  unitPrice?: number | null
  vatRate?: string | null
  note?: string | null
  vendor?: string | null
  model?: string | null
  stationType?: string | null
  powerKwt?: number | null
  connectorsCount?: number | null
  connectorTypes?: string | null
}

export interface SupplyPayload {
  docType: SupplyDocType
  number: string
  docDate?: string | null
  counterpartyId?: string | null
  counterpartyName?: string | null
  contractId?: string | null
  warehouseId?: string | null
  currency?: string
  vatTotal?: number | null
  note?: string | null
  lines?: SupplyLinePayload[]
}

export interface ReceiveUnit { serial?: string | null; inventoryNumber?: string | null; warrantyUntil?: string | null }

export interface SupplyReceivePayload {
  warehouseId?: string | null
  occurredOn?: string | null
  basis?: string | null
  comment?: string | null
  qty?: number | null
  units?: ReceiveUnit[]
  unitIds?: string[]
  allowOverage?: boolean
}

export async function listSupplies(p: {
  companyId: string
  docType?: SupplyDocType
  status?: SupplyStatus
  counterpartyId?: string
  dateFrom?: string
  dateTo?: string
  q?: string
  page?: number
  pageSize?: number
}): Promise<{ items: SupplyListRow[]; total: number }> {
  return get('/api/equipment/supplies', {
    company_id: p.companyId,
    ...(p.docType ? { doc_type: p.docType } : {}),
    ...(p.status ? { status: p.status } : {}),
    ...(p.counterpartyId ? { counterparty_id: p.counterpartyId } : {}),
    ...(p.dateFrom ? { date_from: p.dateFrom } : {}),
    ...(p.dateTo ? { date_to: p.dateTo } : {}),
    ...(p.q ? { q: p.q } : {}),
    page: p.page ?? 1, page_size: p.pageSize ?? 100,
  })
}

export async function getSupply(companyId: string, supplyId: string): Promise<SupplyDoc> {
  return get(`/api/equipment/supplies/${supplyId}`, { company_id: companyId })
}

export async function createSupply(companyId: string, body: SupplyPayload): Promise<SupplyDoc> {
  return post(`/api/equipment/supplies?company_id=${companyId}`, body)
}

export async function updateSupply(companyId: string, supplyId: string, body: Partial<SupplyPayload>): Promise<SupplyDoc> {
  return patch(`/api/equipment/supplies/${supplyId}?company_id=${companyId}`, body)
}

export async function deleteSupply(companyId: string, supplyId: string): Promise<{ deleted: string }> {
  return del(`/api/equipment/supplies/${supplyId}?company_id=${companyId}`)
}

export async function addSupplyLine(companyId: string, supplyId: string, body: SupplyLinePayload): Promise<SupplyDoc> {
  return post(`/api/equipment/supplies/${supplyId}/lines?company_id=${companyId}`, body)
}

export async function updateSupplyLine(companyId: string, supplyId: string, lineId: string, body: SupplyLinePayload): Promise<SupplyDoc> {
  return patch(`/api/equipment/supplies/${supplyId}/lines/${lineId}?company_id=${companyId}`, body)
}

export async function deleteSupplyLine(companyId: string, supplyId: string, lineId: string): Promise<SupplyDoc> {
  return del(`/api/equipment/supplies/${supplyId}/lines/${lineId}?company_id=${companyId}`)
}

export async function setSupplyStatus(companyId: string, supplyId: string, action: 'confirm' | 'close' | 'cancel'): Promise<SupplyDoc> {
  return post(`/api/equipment/supplies/${supplyId}/status?company_id=${companyId}`, { action })
}

export async function receiveSupplyLine(companyId: string, supplyId: string, lineId: string, body: SupplyReceivePayload): Promise<SupplyDoc> {
  return post(`/api/equipment/supplies/${supplyId}/lines/${lineId}/receive?company_id=${companyId}`, body)
}

export async function listSuppliers(companyId: string): Promise<{ items: SupplierBrief[] }> {
  return get('/api/equipment/suppliers', { company_id: companyId })
}

// ─── документы движения и карточка склада (04.10.2026) ──────────────────────

/** Из каких состояний доступна операция — зеркало TRANSITIONS сервера (проверяет сервер). */
export const OP_FROM: Partial<Record<UnitOp, UnitState[] | 'nonterminal'>> = {
  transfer: ['in_stock_new', 'in_stock_used', 'reserved'],
  reserve: ['in_stock_new', 'in_stock_used'],
  unreserve: ['reserved'],
  to_installation: ['in_stock_new', 'in_stock_used', 'reserved'],
  commissioning: ['in_installation'],
  dismantle: ['in_operation'],
  to_repair: ['in_stock_new', 'in_stock_used', 'reserved'],
  from_repair: ['in_repair'],
  to_vendor: ['in_stock_new', 'in_stock_used', 'in_repair'],
  write_off: 'nonterminal',
}
export const opAllowedFor = (op: UnitOp, state: UnitState) => {
  const f = OP_FROM[op]
  return f === 'nonterminal' ? state !== 'written_off' && state !== 'returned_to_vendor' : !!f?.includes(state)
}

export interface EquipmentDocsMeta {
  kinds: Record<string, { prefix: string; title: string }>
  contractTypes: Record<string, string[]>
  counterpartyRequired: string[]
  ownership: Record<string, string>
}
export interface EquipmentDocLine {
  unitId: string; serialNumber: string | null; inventoryNumber: string | null; vendor: string | null
  model: string | null; powerKwt: number | null; purchaseAmount: number | null
  from: string | null; to: string | null; fromState: string | null; toState: string | null
  /** Проводка строки: счёт до → после и стоимость единицы. */
  accountFrom?: string | null; accountTo?: string | null; amount?: number | null
}
export interface EquipmentDocument {
  id: string; op: UnitOp; opLabel: string; title: string; number: string; docDate: string
  counterpartyId: string | null; counterpartyName: string | null; contractId: string | null; contractLabel: string | null
  fromLocation: string | null; toLocation: string | null; responsibleFrom: string | null; responsibleTo: string | null
  basis: string | null; comment: string | null; createdBy: string | null; createdAt: string | null; units: number | null
  status?: 'posted' | 'cancelled' | 'draft'; cancelledAt?: string | null; cancelledBy?: string | null; cancelReason?: string | null
  fromLocationId?: string | null; toLocationId?: string | null
  lines?: EquipmentDocLine[]; warnings?: string[]
  details?: RepairDetails
  primaryNumber?: string | null; primaryDate?: string | null
  bpRef?: string | null; bpExportedAt?: string | null; postedAt?: string | null
  /** Состав черновика — то, что будет проведено. */
  draft?: { unit_ids?: string[]; to_location_id?: string; counterparty_id?: string; contract_id?: string
    responsible_from?: string; responsible_to?: string; basis?: string; comment?: string } | null
}
export interface RepairDetails {
  ticketRef?: string; repairKind?: 'warranty' | 'paid'; plannedReturn?: string
  costEstimate?: number; costActual?: number; result?: 'repaired' | 'unrepairable'
  /** Акт списания: счёт и статья затрат (дебет проводки в 1С). */
  costAccount?: string; costItem?: string
}
export interface EquipmentDocPayload {
  op: UnitOp; unitIds: string[]; docDate: string; number?: string; toLocationId?: string
  counterpartyId?: string; contractId?: string; responsibleFrom?: string; responsibleTo?: string
  basis?: string; comment?: string; custodian?: 'contractor' | 'vendor'; reservedForLocationId?: string
  toState?: UnitState; syncPassport?: boolean; details?: RepairDetails
  primaryNumber?: string; primaryDate?: string
  /** Сохранить черновиком: номер занят, движений нет. */
  draft?: boolean
}
export interface WarehouseCard {
  id: string; name: string; address: string | null
  status?: 'active' | 'closed'
  ownership?: 'own' | 'rent' | 'custody'; ownershipLabel?: string
  counterpartyId?: string | null; counterpartyName?: string; contractId?: string | null
  contractLabel?: string; contractValidUntil?: string | null
  contractStatus?: 'active' | 'expired' | 'closed' | 'missing' | null
  responsible?: string | null; responsibleUserId?: string | null; phone?: string | null; note?: string | null
  /** Код и ссылка склада в 1С — по ним выгрузка находит склад, а сверка остаток. */
  bpCode?: string | null; bpRef?: string | null
}
export type WarehousePayload = Partial<Pick<WarehouseCard, 'name' | 'address' | 'ownership' | 'counterpartyId' | 'contractId'
  | 'responsible' | 'responsibleUserId' | 'phone' | 'note' | 'bpCode' | 'bpRef'>>

export const getEquipmentDocsMeta = () => get<EquipmentDocsMeta>('/api/equipment/documents/meta')
export const listEquipmentDocuments = (p: {
  companyId: string; op?: string; q?: string; dateFrom?: string; dateTo?: string; status?: string
  contractId?: string; counterpartyId?: string; locationId?: string; unitId?: string; limit?: number; offset?: number
}) =>
  get<{ items: EquipmentDocument[]; total: number }>('/api/equipment/documents', {
    company_id: p.companyId, op: p.op || undefined, q: p.q || undefined, date_from: p.dateFrom || undefined,
    date_to: p.dateTo || undefined, status: p.status || undefined, contract_id: p.contractId || undefined,
    counterparty_id: p.counterpartyId || undefined, location_id: p.locationId || undefined,
    unit_id: p.unitId || undefined, limit: p.limit ?? 50, offset: p.offset ?? 0 })
export const cancelEquipmentDocument = (companyId: string, id: string, reason: string) =>
  post<EquipmentDocument>(`/api/equipment/documents/${id}/cancel?company_id=${companyId}`, { reason })
export const getEquipmentDocument = (companyId: string, id: string) =>
  get<EquipmentDocument>(`/api/equipment/documents/${id}`, { company_id: companyId })
export const postEquipmentDocument = (companyId: string, body: EquipmentDocPayload) =>
  post<EquipmentDocument>(`/api/equipment/documents?company_id=${companyId}`, body)
export const getWarehouseCard = (companyId: string, id: string) =>
  get<WarehouseCard>(`/api/equipment/warehouses/${encodeURIComponent(id)}/card`, { company_id: companyId })
export const createWarehouse = (companyId: string, body: WarehousePayload) =>
  post<WarehouseCard>(`/api/equipment/warehouses?company_id=${companyId}`, body)
export const updateWarehouse = (companyId: string, id: string, body: WarehousePayload) =>
  patch<WarehouseCard>(`/api/equipment/warehouses/${encodeURIComponent(id)}?company_id=${companyId}`, body)
/** Закрыть пустой склад (уходит из выбора, история остаётся) или открыть снова. */
export const setWarehouseClosed = (companyId: string, id: string, closed: boolean) =>
  post<WarehouseCard>(`/api/equipment/warehouses/${encodeURIComponent(id)}/status?company_id=${companyId}`, { closed })
/** Удалить склад, заведённый по ошибке: без единиц, остатков и истории. */
export const deleteWarehouse = (companyId: string, id: string) =>
  del<{ deleted: string; name: string }>(`/api/equipment/warehouses/${encodeURIComponent(id)}?company_id=${companyId}`)
export const listEquipmentPeople = (companyId: string) =>
  get<{ id: string; name: string }[]>('/api/equipment/people', { company_id: companyId })
export const updateEquipmentDraft = (companyId: string, id: string, body: EquipmentDocPayload) =>
  patch<EquipmentDocument>(`/api/equipment/documents/${id}?company_id=${companyId}`, body)
export const postEquipmentDraft = (companyId: string, id: string) =>
  post<EquipmentDocument>(`/api/equipment/documents/${id}/post?company_id=${companyId}`, {})
export const deleteEquipmentDraft = (companyId: string, id: string) =>
  del<{ deleted: string; number: string }>(`/api/equipment/documents/${id}?company_id=${companyId}`)

// ─── учёт под 1С: справочники, закрытый период, номенклатура по моделям ─────
export interface AccountingMeta {
  kinds: Record<NomenclatureKind, { label: string; account: string; serial: boolean }>
  accounts: Record<string, string>
  okei: Record<string, string>
  vatRates: string[]
  /** Счета затрат расхода со склада (дебет отпуска и списания) и счёт по умолчанию по операции. */
  costAccounts: Record<string, string>
  defaultCostAccount: Record<string, string>
}
export const getAccountingMeta = () => get<AccountingMeta>('/api/equipment/accounting/meta')
export const getEquipmentSettings = (companyId: string) =>
  get<{ closedUntil: string | null }>('/api/equipment/settings', { company_id: companyId })
export const setClosedPeriod = (companyId: string, closedUntil: string | null) =>
  put<{ closedUntil: string | null }>(`/api/equipment/settings?company_id=${companyId}`, { closedUntil })
export const linkNomenclatureFromUnits = (companyId: string, body: { unitIds?: string[]; dryRun?: boolean }) =>
  post<{ groups: { name: string; units: number; exists: boolean; nomenclatureId: string | null }[]; linked: number }>(
    `/api/equipment/nomenclature/from-units?company_id=${companyId}`, body)

// ─── разбор данных ──────────────────────────────────────────────────────────
export interface AuditUnit {
  id: string; serialNumber: string | null; vendor: string | null; model: string | null
  state: UnitState; stateLabel: string; location: LocBrief | null
  keeper?: string | null; supplier?: string | null; region?: string | null
  group?: string; due?: string; document?: string; reason?: string | null
}
export interface AuditSection {
  key: 'stock_no_place' | 'terminal_no_doc' | 'keeper_text' | 'warehouse_contract' | 'repair_overdue' | 'unconfirmed'
    | 'no_nomenclature' | 'no_cost'
  title: string; hint: string; action: string; count: number; items: AuditUnit[]
}
export const getEquipmentAudit = (companyId: string) =>
  get<{ sections: AuditSection[]; units: number; noCost: number }>('/api/equipment/audit', { company_id: companyId })

// ─── отчёты складского учёта ────────────────────────────────────────────────
/** Единица в отчёте: где и в каком состоянии она была на дату отчёта. */
export interface ReportUnitRow {
  id: string; serialNumber: string | null; inventoryNumber: string | null; vendor: string | null; model: string | null
  state: UnitState; stateLabel: string; placeKey: string; placeKind: 'warehouse' | 'unknown' | 'installation' | 'repair' | 'vendor' | 'written_off'
  place: string; since: string | null; noHistory: boolean; docId: string | null; docNumber: string | null; basis: string | null
  counterpartyId: string | null; counterpartyName: string | null; contractId: string | null; contractLabel: string | null
  keeper: string | null
}
export interface ReportSpareRow { partId: string; name: string; article: string | null; unitLabel: string; locationId: string; location: string }
export interface StockReport {
  date: string; total: number; noHistory: number; units: ReportUnitRow[]
  /** Работающие станции со складского учёта выбыли — в отчёте одним числом. */
  inOperation: number
  /** section: stock — складской остаток, out — на учёте вне складов, gone — выбыло (справочно). */
  groups: { key: string; kind: string; section: 'stock' | 'out' | 'gone'; name: string; total: number; noHistory: number; byState: Record<string, number> }[]
  states: { key: UnitState; label: string }[]
  spares: (ReportSpareRow & { qty: number })[]; spareCorrectionsUnknown: number
  counterparties: { id: string; name: string }[]
}
export interface TurnoverFigures {
  opening: number; income: number; outcome: number; closing: number; noHistory: number
  incomeByOp: { label: string; qty: number }[]; outcomeByOp: { label: string; qty: number }[]
}
export interface TurnoverReport {
  dateFrom: string; dateTo: string; spareCorrectionsUnknown: number
  warehouses: ({ locationId: string; location: string } & TurnoverFigures)[]
  spares: (ReportSpareRow & TurnoverFigures)[]
}
export interface HolderGroup {
  key: string; counterpartyId: string | null; name: string; linked: boolean; total: number; units: ReportUnitRow[]
  warehouses: {
    id: string; name: string; ownership: string | null; ownershipLabel: string; responsible: string | null; units: ReportUnitRow[]
    contract: { id: string | null; number: string | null; date: string | null; validUntil: string | null
      status: 'active' | 'expired' | 'closed' | 'missing'; statusLabel: string }
  }[]
}
export interface RepairRow {
  id: string; serialNumber: string | null; inventoryNumber: string | null; vendor: string | null; model: string | null
  noHistory: boolean; holder: string | null; counterpartyId: string | null; contractLabel: string | null
  docId: string | null; docNumber: string | null; sentOn: string | null; plannedReturn: string | null
  days: number | null; overdueDays: number; repairKind: string | null; ticketRef: string | null
}
export const getStockReport = (p: { companyId: string; date: string; locationId?: string; counterpartyId?: string }) =>
  get<StockReport>('/api/equipment/reports/stock', {
    company_id: p.companyId, date: p.date, location_id: p.locationId, counterparty_id: p.counterpartyId })
export const getTurnoverReport = (p: { companyId: string; dateFrom: string; dateTo: string; locationId?: string }) =>
  get<TurnoverReport>('/api/equipment/reports/turnover', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo, location_id: p.locationId })
export const getHoldersReport = (companyId: string, date: string) =>
  get<{ date: string; holders: HolderGroup[] }>('/api/equipment/reports/holders', { company_id: companyId, date })
export const getRepairsReport = (companyId: string) =>
  get<{ date: string; items: RepairRow[]; overdue: number }>('/api/equipment/reports/repairs', { company_id: companyId })

/** Остатки склада на дату: номенклатура × количество × сумма; единицы — списком. */
export interface BalanceItem {
  key: string; name: string; kind: string; account: string; unitLabel: string; qty: number; amount: number
  units: { id: string; serialNumber: string | null; inventoryNumber: string | null; state: UnitState
    stateLabel: string; since: string | null; amount: number | null }[]
}
export interface BalanceWarehouse {
  id: string; name: string; status: 'active' | 'closed'; ownershipLabel: string; responsible: string | null
  items: BalanceItem[]; amount: number; units: number; positions: number; noCost: number
}
export const getBalanceReport = (p: { companyId: string; date: string; locationId?: string }) =>
  get<{ date: string; warehouses: BalanceWarehouse[]; amount: number; noCost: number }>('/api/equipment/reports/balance', {
    company_id: p.companyId, date: p.date, location_id: p.locationId })

/** Строка оборотно-сальдовой ведомости: о — сальдо на начало, д — дебет, к — кредит, з — на конец; q — количество, s — сумма. */
export interface OsvCells { oq: number; os: number; dq: number; ds: number; cq: number; cs: number; zq: number; zs: number }
export interface OsvRow extends OsvCells {
  account: string; place: string; placeName: string; item: string; itemName: string; unitLabel: string
}
export interface OsvReport {
  dateFrom: string; dateTo: string; rows: OsvRow[]; noCost: number; noCostStock: number
  accounts: (OsvCells & { account: string; label: string; rows: number })[]
}
export const getOsvReport = (p: { companyId: string; dateFrom: string; dateTo: string; locationId?: string; account?: string }) =>
  get<OsvReport>('/api/equipment/reports/osv', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo, location_id: p.locationId, account: p.account })

