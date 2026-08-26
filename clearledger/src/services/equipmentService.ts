/**
 * Клиент API складского учёта оборудования ЭЗС (/api/equipment/*).
 *
 * Раздел «Управленческий» → группа «Оборудование» (energy/РусГидро):
 * единицы (станции-железки), движения жизненного цикла, склады, ЗИП.
 * Допустимые операции единицы приходят с сервера (allowedOps) — матрица
 * переходов НЕ дублируется на фронте.
 */

import { del, get, patch, post, upload } from './apiClient'

// ─── справочники состояний/операций (метки + приглушённые классы) ──────────

export type UnitState =
  | 'in_stock_new' | 'in_stock_used' | 'reserved' | 'in_installation'
  | 'in_operation' | 'in_repair' | 'returned_to_vendor' | 'written_off'

export type UnitOp =
  | 'receipt' | 'transfer' | 'reserve' | 'unreserve' | 'to_installation'
  | 'commissioning' | 'dismantle' | 'to_repair' | 'from_repair'
  | 'to_vendor' | 'write_off' | 'correction'

export const UNIT_STATE_META: Record<UnitState, { label: string; cls: string }> = {
  in_stock_new: { label: 'На складе (новая)', cls: 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80' },
  in_stock_used: { label: 'На складе (б/у)', cls: 'border-emerald-400/40 text-emerald-700/80 dark:text-emerald-400/70' },
  reserved: { label: 'Резерв', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80' },
  in_installation: { label: 'В монтаже', cls: 'border-sky-400/50 text-sky-600 dark:text-sky-300/80' },
  in_operation: { label: 'В эксплуатации', cls: 'border-sky-500/50 text-sky-700 dark:text-sky-300' },
  in_repair: { label: 'В ремонте', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80' },
  returned_to_vendor: { label: 'Возврат производителю', cls: 'border-zinc-500/60 text-zinc-500' },
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
}

export const CUSTODIAN_LABELS: Record<string, string> = {
  warehouse: 'Склад', site: 'Площадка', contractor: 'Подрядчик',
  vendor: 'Производитель', none: '—',
}

export const SPARE_CATEGORY_META: Record<string, string> = {
  power_module: 'Силовой модуль', controller: 'Контроллер', connector: 'Коннектор',
  cable: 'Кабель', display: 'Дисплей', board: 'Плата', other: 'Прочее',
}

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
  /** Поставщик подтвердил количество и порты. Ложь — позиция ждёт уточнения. */
  dataConfirmed: boolean
  unconfirmedReason: string | null
  supplyId: string | null
  supplyLineId: string | null
  supplyNumber: string | null
  createdAt: string | null
  updatedAt: string | null
  allowedOps: UnitOp[]
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
  location: LocBrief
  unitsByState: Partial<Record<UnitState, number>>
  unitsTotal: number
  sparePositions: number
  spareQty: number
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
  byLocation: { locationId: string; locationName: string; qty: number }[]
}

export interface SparePartPayload {
  name: string
  category: string
  vendor?: string | null
  article?: string | null
  compatibleModels?: string | null
  unitLabel?: string
  notes?: string | null
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

export async function listUnits(p: {
  companyId: string
  state?: string
  locationId?: string
  vendor?: string
  custodian?: string
  q?: string
  /** Контур рабочей области: регионы, коды станций, точки. */
  regionIds?: string[]
  stationCodes?: string[]
  locationIds?: string[]
  page?: number
  pageSize?: number
}): Promise<{ items: EquipmentUnit[]; total: number }> {
  return get('/api/equipment/units', {
    company_id: p.companyId,
    ...(p.state ? { state: p.state } : {}),
    ...(p.locationId ? { location_id: p.locationId } : {}),
    ...(p.vendor ? { vendor: p.vendor } : {}),
    ...(p.custodian ? { custodian: p.custodian } : {}),
    ...(p.q ? { q: p.q } : {}),
    ...(p.regionIds?.length ? { region_ids: p.regionIds.join(',') } : {}),
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.locationIds?.length ? { location_ids: p.locationIds.join(',') } : {}),
    page: p.page ?? 1, page_size: p.pageSize ?? 500,
  })
}

export async function createUnit(companyId: string, body: UnitInPayload): Promise<EquipmentUnit> {
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
): Promise<{ unit: EquipmentUnit; movement: EquipmentMovement }> {
  return post(`/api/equipment/units/${unitId}/movements?company_id=${companyId}`, body)
}

export async function dismantleFromSite(companyId: string, body: {
  siteLocationId: string
  warehouseId: string
  occurredOn?: string
  basis?: string
  comment?: string
  setDecommissioned?: boolean
}): Promise<{ unit: EquipmentUnit; movement: EquipmentMovement; unitCreated: boolean }> {
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

export async function getEquipmentOverview(companyId: string): Promise<EquipmentOverview> {
  return get('/api/equipment/overview', { company_id: companyId })
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
}): Promise<SparePart[]> {
  return get('/api/equipment/spare-parts', {
    company_id: p.companyId,
    ...(p.q ? { q: p.q } : {}),
    ...(p.category ? { category: p.category } : {}),
    ...(p.includeArchived ? { include_archived: 'true' } : {}),
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
): Promise<{ movementId: string; stock: { locationId: string; locationName: string; qty: number }[] }> {
  return post(`/api/equipment/spare-parts/${partId}/movements?company_id=${companyId}`, body)
}

export async function listSpareMovements(p: {
  companyId: string
  partId?: string
  locationId?: string
  dateFrom?: string
  dateTo?: string
  page?: number
  pageSize?: number
}): Promise<{ items: SpareMovementRow[]; total: number }> {
  return get('/api/equipment/spare-parts/movements/journal', {
    company_id: p.companyId,
    ...(p.partId ? { part_id: p.partId } : {}),
    ...(p.locationId ? { location_id: p.locationId } : {}),
    ...(p.dateFrom ? { date_from: p.dateFrom } : {}),
    ...(p.dateTo ? { date_to: p.dateTo } : {}),
    page: p.page ?? 1, page_size: p.pageSize ?? 200,
  })
}

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
