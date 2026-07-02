/**
 * Клиент API маппингов топливных каналов STS → 1С (TradeLedger).
 * Каналы оплаты, маппинг видов оплат, виды топлива + предпросмотр документов.
 */
import { get, post, put, patch, del } from '@/services/apiClient'

export interface PaymentChannel {
  id: string
  code: string
  name: string
  warehouse_name: string | null
  requires_transfer: boolean
  counterparty_name: string | null
  sort_order: number
}

export interface PaymentMapping {
  id: string
  pattern: string
  channel_code: string
  warehouse_override: string | null
  sort_order: number
}

export interface FuelMapping {
  id: string
  service_code: number
  fuel_name: string
  nomenclature_tonnes: string | null
  nomenclature_liters: string | null
  nomenclature_t_ref?: string | null
  nomenclature_l_ref?: string | null
  density: number | null
  sort_order: number
}

export interface FuelMappingsAll {
  payment_channels: PaymentChannel[]
  payment_mappings: PaymentMapping[]
  fuel_mappings: FuelMapping[]
}

export interface FuelDocument {
  kind: string
  idem_key: string
  payload: Record<string, unknown>
}

export interface FuelDocumentsResponse {
  shift_id?: string
  receipt_id?: string
  count: number
  documents: FuelDocument[]
}

// ─── Загруженные смены/ТТН из БД (API) — для отображения «Загружено» канала ───
export interface LoadedShift {
  id: string
  station_id: string
  station_code: number
  station_name: string | null
  shift_number: number
  opened_at: string | null
  closed_at: string | null
  status: string
  total_liters: number
  total_amount: number
  cash: number
  card: number
  voucher: number
  has_corrections: boolean
  created_at: string
}

export interface LoadedReceipt {
  id: string
  station_id: string
  station_code: number
  station_name: string | null
  ttn: string
  fuel_name: string
  fuel_code?: number | null
  supplier: string
  shift_number?: number | null
  tank?: number | null
  doc_volume_liters: number
  fact_volume_liters: number
  diff_volume: number
  doc_mass_kg?: number
  fact_mass_kg?: number
  diff_mass?: number
  density: number | null
  fact_density?: number | null
  doc_temp?: number | null
  fact_temp?: number | null
  status: string
  received_at?: string | null
  created_at: string
  /** Корректировка ТТН (L2). src_* — исходные STS-значения документа. */
  is_manual?: boolean
  has_corrections?: boolean
  src_volume?: number | null
  src_mass?: number | null
  src_density?: number | null
  note?: string | null
  /** Себестоимость партии (L2). cost_per_liter — норм. ₽/л для FIFO-маржи. */
  has_cost?: boolean
  cost_unit?: string | null
  cost_unit_price?: number | null
  cost_per_liter?: number | null
}

// ─── Детали смены (5 секций как TradeFrame) ───
export interface TankDetail {
  tank_number: number; fuel_type: string; fuel_code: number | null
  volume_start: number; volume_end: number; sales: number; volume_received: number
  density: number | null; density_beg: number | null; temp_end: number | null
  level_end: number | null; water_level: number | null; water_volume: number | null
}
export interface PumpDetail {
  pump_number: number; nozzle: string | null; fuel_type: string; fuel_code: number | null
  tank_number: number | null; sales_volume: number; amount: number
  psm_beg: number | null; psm_end: number | null; price: number | null; density: number | null
}
export interface CashMovement {
  operation_id: number; operation_name: string; amount: number; pos_number: number | null
}
export interface ShiftSale {
  payment_channel: string; fuel_code: number; liters: number; amount: number
  discount: number; warehouse_name: string | null
  /** Строка скорректирована вручную (L2). src_* — исходные STS-значения. */
  is_manual?: boolean
  src_liters?: number | null; src_amount?: number | null; src_discount?: number | null
  note?: string | null
}
export interface ShiftDetail extends LoadedShift {
  operator: string | null
  tanks: TankDetail[]
  pumps: PumpDetail[]
  cash_movements: CashMovement[]
  sales: ShiftSale[]
  receipts: LoadedReceipt[]
  /** Сырой сменный отчёт STS — вход эталонного просмотрщика. null у старых смен. */
  raw_report?: Record<string, any> | null
  /** Комментарий менеджера по корректировке (в целом по документу). */
  correction_note?: string | null
  correction_note_author?: string | null
}
export const getShiftDetail = (id: string) => get<ShiftDetail>(`/api/fuel/shifts/${id}`)

// ─── Удаление загруженных смен/ТТН за период по станциям ───
export interface DeletePeriodBody {
  kind: 'shift' | 'receipt'
  station_codes?: number[]
  date_from?: string
  date_to?: string
}
export const deleteFuelPeriod = (body: DeletePeriodBody) =>
  post<{ deleted: number; kind: string }>(`/api/fuel/delete-period`, body)

// Станции, по которым есть загруженные данные (для диалога удаления/обновления)
export const getLoadedStations = () =>
  get<{ code: number; name: string }[]>(`/api/fuel/loaded-stations`)

export const getLoadedShifts = () => get<LoadedShift[]>('/api/fuel/shifts')
export const getLoadedReceipts = () => get<LoadedReceipt[]>('/api/fuel/receipts')
/** Реальное число загруженных смен/ТТН (без limit) — для карточки «Загружено». */
export const getLoadedCount = () => get<{ shifts: number; receipts: number }>('/api/fuel/count')

// ─── Свод ───
export const getFuelMappings = () => get<FuelMappingsAll>('/api/fuel-mappings')
// Справочник видов топлива (для канонического наименования по fuel_code).
export const getFuelTypes = () => get<FuelMapping[]>('/api/fuel-mappings/fuel-types')

// ─── payment_mappings (образец → канал) ───
export const createPaymentMapping = (body: Partial<PaymentMapping>) =>
  post<PaymentMapping>('/api/fuel-mappings/payment-mappings', body)
export const updatePaymentMapping = (id: string, body: Partial<PaymentMapping>) =>
  put<PaymentMapping>(`/api/fuel-mappings/payment-mappings/${id}`, body)
export const deletePaymentMapping = (id: string) =>
  del(`/api/fuel-mappings/payment-mappings/${id}`)

// ─── payment_channels ───
export const updatePaymentChannel = (id: string, body: Partial<PaymentChannel>) =>
  put<PaymentChannel>(`/api/fuel-mappings/payment-channels/${id}`, body)

// ─── fuel_mappings ───
export const updateFuelMapping = (id: string, body: Partial<FuelMapping>) =>
  put<FuelMapping>(`/api/fuel-mappings/fuel-types/${id}`, body)

// ─── Документы 1С (предпросмотр + материализация) ───
export const getShiftDocuments = (shiftId: string) =>
  get<FuelDocumentsResponse>(`/api/fuel/shifts/${shiftId}/documents`)
export const buildShiftPackets = (shiftId: string) =>
  post<{ created: number; updated: number; total: number }>(`/api/fuel/shifts/${shiftId}/build-packets`)
export const getReceiptDocuments = (receiptId: string) =>
  get<FuelDocumentsResponse>(`/api/fuel/receipts/${receiptId}/documents`)
export const buildReceiptPackets = (receiptId: string) =>
  post<{ created: number; updated: number; total: number }>(`/api/fuel/receipts/${receiptId}/build-packets`)

// ─── Корректировка значений смены (слой L2 CLEAN, override поверх STS) ───
export interface ShiftSaleEdit {
  payment_channel: string
  fuel_code: number
  liters?: number | null
  amount?: number | null
  discount?: number | null
  warehouse_name?: string | null
  note?: string | null
}
/** Сохранить ручные корректировки строк продаж смены (переживают reingest). */
export const patchShiftSales = (shiftId: string, edits: ShiftSaleEdit[]) =>
  patch<{ ok: boolean; count: number }>(`/api/fuel/shifts/${shiftId}/sales`, edits)
/** Откатить все корректировки смены к исходным STS-значениям. */
export const resetShiftSaleOverrides = (shiftId: string) =>
  del(`/api/fuel/shifts/${shiftId}/sales/override`)
/** Комментарий менеджера по корректировке смены (в целом по документу). Пустой текст удаляет. */
export const setShiftCorrectionNote = (shiftId: string, note: string) =>
  put<{ ok: boolean; note: string; author: string | null }>(`/api/fuel/shifts/${shiftId}/correction-note`, { note })

// ─── Корректировка ТТН перед выгрузкой (L2 CLEAN, override поверх STS) ───
export interface ReceiptEdit {
  doc_volume_liters?: number | null
  doc_mass_kg?: number | null
  density?: number | null
  note?: string | null
}
/** Сохранить корректировку значений ТТН (переживает reingest). */
export const patchReceipt = (receiptId: string, edit: ReceiptEdit) =>
  patch<{ ok: boolean }>(`/api/fuel/receipts/${receiptId}/override`, edit)
/** Откатить корректировку ТТН к исходным STS-значениям. */
export const resetReceiptOverride = (receiptId: string) =>
  del(`/api/fuel/receipts/${receiptId}/override`)

// ─── Себестоимость партии (ТТН) для FIFO-маржи ───
export interface ReceiptCostEdit {
  unit: 'liter' | 'kg'
  unit_cost: number
  density?: number | null
  note?: string | null
}
/** Задать себестоимость партии (₽/л или ₽/кг). */
export const setReceiptCost = (receiptId: string, edit: ReceiptCostEdit) =>
  patch<{ ok: boolean; cost_per_liter: number }>(`/api/fuel/receipts/${receiptId}/cost`, edit)
/** Убрать себестоимость партии. */
export const deleteReceiptCost = (receiptId: string) =>
  del(`/api/fuel/receipts/${receiptId}/cost`)

/** Показатели партии по FIFO (списано/остаток/маржа). */
export interface ReceiptCosting {
  has_cost: boolean
  cost_per_liter?: number
  total_liters?: number
  consumed_liters?: number
  remaining_liters?: number
  avg_sale_price?: number
  cogs_consumed?: number
  revenue_consumed?: number
  margin_consumed?: number
}
export const getReceiptCosting = (receiptId: string) =>
  get<ReceiptCosting>(`/api/fuel/receipts/${receiptId}/costing`)

// ─── Управленческая маржа по FIFO-себестоимости (по разрезам) ───
export interface CostingMarginLine {
  label: string
  liters: number
  liters_costed: number
  liters_uncosted: number
  revenue: number
  revenue_net: number
  cogs: number
  margin: number
  margin_per_liter: number
  avg_cost_per_liter: number
}
export interface CostingMargin {
  period: { from: string; to: string }
  group_by: string
  lines: CostingMarginLine[]
  totals: {
    liters: number; liters_costed: number; liters_uncosted: number
    revenue: number; revenue_net: number; cogs: number; margin: number
  }
}
/** group_by: fuel | payment | station | month | fuel_payment */
export const getCostingMargin = (dateFrom: string, dateTo: string, groupBy = 'fuel') =>
  get<CostingMargin>('/api/fuel/costing/margin', { date_from: dateFrom, date_to: dateTo, group_by: groupBy })

// ─── Станции (для выбора АЗС в закупочной партии) ───
export interface FuelStationRef {
  id: string
  code: number
  name: string
  sts_system_code?: number | null
}
export const getFuelStations = () => get<FuelStationRef[]>('/api/fuel/stations')

// ─── Закупочные партии (Шаг 2): крупная закупка → FIFO-распределение на ТТН ───
export interface PurchaseBatch {
  id: string
  supplier: string | null
  fuel_code: number
  fuel_name: string | null
  total_liters: number
  unit: string
  unit_cost: number
  cost_per_liter: number
  density: number | null
  purchase_date: string | null
  target_station_ids: string[]
  status: string
  allocated_liters: number
  note: string | null
}
export interface PurchaseBatchCreate {
  supplier?: string | null
  fuel_code: number
  fuel_name?: string | null
  total_liters: number
  unit: 'liter' | 'kg'
  unit_cost: number
  density?: number | null
  purchase_date?: string | null
  target_station_ids: string[]
  note?: string | null
}
export const getPurchaseBatches = () => get<PurchaseBatch[]>('/api/fuel/purchase-batches')
export const createPurchaseBatch = (body: PurchaseBatchCreate) =>
  post<PurchaseBatch>('/api/fuel/purchase-batches', body)
export const deletePurchaseBatch = (id: string) => del(`/api/fuel/purchase-batches/${id}`)
export const allocatePurchaseBatch = (id: string) =>
  post<{ ok: boolean; allocated_liters: number; receipts_covered: number; remaining_liters: number }>(
    `/api/fuel/purchase-batches/${id}/allocate`)

// ─── Дашборд аналитики по сменным отчётам ───
export interface DashFuelItem { fuel_code: number; fuel_name: string; volume: number; revenue: number; percent: number }
export interface DashPayFuel { fuel_code: number; fuel_name: string; revenue: number; volume: number }
export interface DashPaymentDetail { revenue: number; volume: number; volume_only: boolean; by_fuel: DashPayFuel[] }
export interface DashReceiptFuel { fuel_code: number; fuel_name: string; doc_volume: number; fact_volume: number; diff: number; ttn_count: number }
export interface DashReceiptDetail { ttn: string; fuel_code: number; fuel_name: string; doc_volume: number; fact_volume: number; diff: number; supplier: string | null; tank: number | null; datetime: string | null }
export interface DashCashDetail { operation: string; type: string; amount: number; pos: number | null; shift: number | null }
export interface DashCashoutDetail { operation: string; amount: number; pos: number | null; shift: number | null }
export interface DashDaily { date: string; revenue: number; volume: number; cash: number; card: number; online: number; corporate: number; coupon: number }
export interface DashTrend { current: number; previous: number; delta: number; percent: number; direction: 'up' | 'down' | 'neutral' }
export interface ShiftDashboardData {
  period: { from: string; to: string; days: number }
  volume: { total: number; by_fuel: DashFuelItem[] }
  financial: { total_revenue: number; payment_details: Record<string, DashPaymentDetail> }
  receipts: { total_doc: number; total_fact: number; total_diff: number; ttn_count: number; by_fuel: DashReceiptFuel[]; details: DashReceiptDetail[] }
  cash_flow: { income: number; expense: number; calculated: number; closing: number; difference: number; operations_count: number; details: DashCashDetail[] }
  cashout: { total: number; count: number; details: DashCashoutDetail[] }
  operational: { shifts_count: number }
  charts: { daily: DashDaily[]; by_fuel: DashFuelItem[] }
  trends?: { revenue: DashTrend; volume: DashTrend; shifts: DashTrend }
}
export const getShiftDashboard = (dateFrom: string, dateTo: string, opts?: { stations?: string[]; compare?: boolean }) =>
  get<ShiftDashboardData>('/api/fuel/shift-dashboard', {
    date_from: dateFrom,
    date_to: dateTo,
    stations: opts?.stations?.length ? opts.stations.join(',') : undefined,
    compare: opts?.compare ? 'true' : undefined,
  })

// ─── Готовность к 1С (агрегация статусов за период) ───
export interface FuelReadiness {
  period: { from: string; to: string }
  shifts: { total: number; corrected: number }
  receipts: { total: number; pending: number; confirmed: number; corrected: number; rejected: number; with_corrections: number }
  packets: { draft: number; in_flight: number; acked: number; rejected: number }
}
export const getFuelReadiness = (dateFrom: string, dateTo: string, opts?: { stations?: string[] }) =>
  get<FuelReadiness>('/api/fuel/readiness', {
    date_from: dateFrom,
    date_to: dateTo,
    stations: opts?.stations?.length ? opts.stations.join(',') : undefined,
  })

// ─── Подтверждение приёмки ТТН (workflow статусов) ───
export type ReceiptStatus = 'pending' | 'confirmed' | 'corrected' | 'rejected'
export const setReceiptStatus = (id: string, status: ReceiptStatus, reason?: string) =>
  patch<{ ok: boolean; status: string }>(`/api/fuel/receipts/${id}/status`, { status, reason })
export const bulkReceiptStatus = (ids: string[], status: ReceiptStatus) =>
  post<{ ok: boolean; updated: number }>(`/api/fuel/receipts/status/bulk`, { ids, status })
