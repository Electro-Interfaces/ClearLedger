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

// typeof-guard обязателен: эти функции передают напрямую как queryFn,
// и React Query подставляет QueryFunctionContext первым аргументом.
/** Журнал смен. Без периода бэкенд отдаёт последние `limit` смен — для экрана,
 *  привязанного к периоду рабочей области, период передавать обязательно. */
export const getLoadedShifts = (opts?: { limit?: number; dateFrom?: string; dateTo?: string }) =>
  get<LoadedShift[]>('/api/fuel/shifts', {
    ...(typeof opts?.limit === 'number' ? { limit: opts.limit } : {}),
    ...(opts?.dateFrom ? { date_from: opts.dateFrom } : {}),
    ...(opts?.dateTo ? { date_to: opts.dateTo } : {}),
  })
export const getLoadedReceipts = (limit?: number) =>
  get<LoadedReceipt[]>('/api/fuel/receipts', typeof limit === 'number' ? { limit } : undefined)
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

export interface ReceiptCostingChannel {
  channel: string
  liters: number
  share_pct: number
  allocations_count: number
  avg_sale_price: number
  revenue: number
  revenue_net: number
  cogs: number
  margin: number
  margin_pct: number
}

export interface ReceiptCostingMicroLot {
  id: string
  opened_at: string | null
  shift_id: string
  shift_number: number | null
  channel: string
  liters: number
  avg_sale_price: number
  revenue: number
  revenue_net: number
  cogs: number
  margin: number
  margin_pct: number
}

/** Показатели партии по FIFO: итоги, каналы оплаты и микропартии продаж. */
export interface ReceiptCosting {
  has_cost: boolean
  allocation_method?: 'shift_channel_pro_rata'
  allocation_method_label?: string
  cost_per_liter?: number
  total_liters?: number
  consumed_liters?: number
  remaining_liters?: number
  avg_sale_price?: number
  cogs_consumed?: number
  revenue_consumed?: number
  revenue_net_consumed?: number
  margin_consumed?: number
  margin_pct?: number
  channels?: ReceiptCostingChannel[]
  micro_lots?: ReceiptCostingMicroLot[]
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
  avg_sale_price: number
  avg_sale_price_net: number
  margin_pct: number
  coverage_pct: number
}
export interface CostingMarginTotals {
  liters: number
  liters_costed: number
  liters_uncosted: number
  revenue: number
  revenue_net: number
  cogs: number
  margin: number
  margin_per_liter: number
  avg_cost_per_liter: number
  avg_sale_price: number
  avg_sale_price_net: number
  margin_pct: number
  coverage_pct: number
}
export interface CostingMargin {
  period: { from: string; to: string }
  group_by: string
  lines: CostingMarginLine[]
  totals: CostingMarginTotals
}
/** group_by: fuel | payment | station | month | fuel_payment */
export const getCostingMargin = (dateFrom: string, dateTo: string, groupBy = 'fuel', fuelCodes?: number[]) =>
  get<CostingMargin>('/api/fuel/costing/margin', {
    date_from: dateFrom, date_to: dateTo, group_by: groupBy,
    ...(fuelCodes?.length ? { fuel_codes: fuelCodes.join(',') } : {}),
  })

export interface MarginDecisionDashboard {
  period: { from: string; to: string }
  previous_period: { from: string; to: string }
  fuel: CostingMargin
  station: CostingMargin
  station_fuel: CostingMargin
  month: CostingMargin
  previous: CostingMargin
  readiness: {
    positive_receipts: number
    costed_receipts: number
    uncosted_receipts: number
    nonpositive_receipts: number
    opening_balances: number
    opening_balance_liters: number
    opening_balance_value: number
  }
}

export const getMarginDecisionDashboard = (companyId: string, dateFrom: string, dateTo: string,
  fuelCodes?: number[]) =>
  get<MarginDecisionDashboard>('/api/fuel/costing/decision-dashboard', {
    company_id: companyId,
    date_from: dateFrom,
    date_to: dateTo,
    ...(fuelCodes?.length ? { fuel_codes: fuelCodes.join(',') } : {}),
  })

export interface FuelOpeningBalance {
  id: string
  station_id: string
  station_code: number | null
  station_name: string
  fuel_code: number
  fuel_name: string
  as_of: string
  liters: number
  cost_per_liter: number
  value: number
  source: 'auto' | 'manual'
  note: string | null
}

export interface FuelOpeningBalancesResponse {
  rows: FuelOpeningBalance[]
  totals: { count: number; liters: number; value: number }
}

export const getFuelOpeningBalances = () =>
  get<FuelOpeningBalancesResponse>('/api/fuel/costing/opening-balances')

export const recalculateFuelOpeningBalances = () =>
  post<{ ok: boolean; count: number; liters: number; value: number }>('/api/fuel/costing/opening-balances/auto')

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
export interface DashStation { station_id: string; station_name: string; revenue: number; volume: number; shifts: number; avg_price: number }
export interface DashOnboarding { station_id: string; code: number | null; name: string; date: string }
export interface DashPayMethod { name: string; revenue: number; volume: number; count?: number }
export interface DashFuelRaw { name: string; code: number | null; revenue: number; volume: number; count?: number }
export interface DashHour { hour: number; label: string; count: number; amount: number }
export interface DashWeekday { weekday: number; label: string; count: number; amount: number }
export interface DashActivity { hourly: DashHour[]; weekday: DashWeekday[]; peak_hour: number | null; best_weekday: number | null }
export interface DashCard { card: string; count: number; liters: number; amount: number }
export interface ShiftDashboardData {
  period: { from: string; to: string; days: number }
  volume: { total: number; by_fuel: DashFuelItem[] }
  financial: { total_revenue: number; avg_price?: number; payment_details: Record<string, DashPaymentDetail> }
  receipts: { total_doc: number; total_fact: number; total_diff: number; ttn_count: number; by_fuel: DashReceiptFuel[]; details: DashReceiptDetail[] }
  cash_flow: { income: number; expense: number; calculated: number; closing: number; difference: number; operations_count: number; details: DashCashDetail[] }
  cashout: { total: number; count: number; details: DashCashoutDetail[] }
  operational: {
    shifts_count: number
    stations_count?: number
    fuel_types_count?: number
    /** Смены, по которым источник (STS) не отдал детализацию продаж — пробел в данных, не ноль выручки. */
    shifts_missing_sales?: number
    shifts_with_sales?: number
  }
  by_station?: DashStation[]
  onboarding?: DashOnboarding[]
  payment_methods?: DashPayMethod[]
  fuel_types_raw?: DashFuelRaw[]
  activity?: DashActivity
  top_cards?: DashCard[]
  averages?: { tx_count: number; avg_check: number; avg_fill_liters: number; ops_per_day: number }
  charts: { daily: DashDaily[]; by_fuel: DashFuelItem[] }
  trends?: { revenue: DashTrend; volume: DashTrend; shifts: DashTrend }
  /** Границы базы сравнения — период той же длины перед текущим. Приходит
   *  вместе с trends: Δ% без явной базы читать нельзя. */
  prev_period?: { from: string; to: string }
}
export const getShiftDashboard = (dateFrom: string, dateTo: string,
  opts?: { stations?: string[]; compare?: boolean; fuelCodes?: number[] }) =>
  get<ShiftDashboardData>('/api/fuel/shift-dashboard', {
    date_from: dateFrom,
    date_to: dateTo,
    stations: opts?.stations?.length ? opts.stations.join(',') : undefined,
    fuel_codes: opts?.fuelCodes?.length ? opts.fuelCodes.join(',') : undefined,
    compare: opts?.compare ? 'true' : undefined,
  })

// ─── Реестр пооперационных транзакций (реализаций) ───
export interface FuelTxRow {
  id: string
  ext_id: number
  dt: string | null
  station_code: number
  station_name: string
  shift_number: number | null
  receipt: number | null
  pos: number | null
  nozzle: number | null
  tank: number | null
  fuel_code: number | null
  fuel_name: string | null
  pay_type_name: string | null
  /** Нормализованный вид оплаты — по нему сгруппированы карточки и фильтры. */
  payment_method: string | null
  card: string | null
  liters: number
  price: number | null
  amount: number
  mass: number | null
  density: number | null
  /** Заказ клиента до отпуска («залей на 1000 ₽»), если был. */
  order_qty: number | null
  order_cost: number | null
  status: string
}
export interface FuelTxRowsResp {
  total: number
  totals: { count: number; liters: number; amount: number }
  rows: FuelTxRow[]
}
export interface FuelTxFilters {
  stations: { code: number; name: string }[]
  fuels: { code: number; name: string }[]
  pay_types: string[]
}
export interface FuelTxRowsParams {
  dateFrom: string
  dateTo: string
  stationCode?: number
  fuelCodes?: number[]
  payTypes?: string[]
  /** Свободный остаток строки поиска (карта, топливо, число). */
  search?: string
  // Точные поля умного поиска — «смена 9 азс 6 чек 42 карта 1234».
  shift?: number
  receipt?: number
  pos?: number
  card?: string
  status?: string
  sort?: string
  order?: 'asc' | 'desc'
  limit?: number
  offset?: number
}
export const getFuelTxRows = (p: FuelTxRowsParams) =>
  get<FuelTxRowsResp>('/api/fuel/transactions/rows', {
    date_from: p.dateFrom, date_to: p.dateTo,
    station_code: p.stationCode,
    fuel_codes: p.fuelCodes?.length ? p.fuelCodes.join(',') : undefined,
    pay_types: p.payTypes?.length ? p.payTypes.join(',') : undefined,
    search: p.search, shift: p.shift, receipt: p.receipt, pos: p.pos, card: p.card,
    status: p.status,
    sort: p.sort, order: p.order, limit: p.limit, offset: p.offset,
  })
/** Лист сводной: агрегат по набору измерений. Иерархию собирает браузер. */
export interface FuelPivotResp {
  dims: string[]
  labels: string[]
  /** Код станции → имя: в ключах код, на экране название. */
  stationNames: Record<string, string>
  rows: { keys: (string | null)[]; ops: number; liters: number; amount: number }[]
  /** Упёрлись в потолок строк: показать плашку, а не молча обрезать. */
  truncated: boolean
}

/**
 * Листья сводной по тем же фильтрам, что и реестр.
 *
 * `dims` — НАБОР измерений; порядок уровней на экране к серверу отношения не имеет,
 * поэтому ключ кэша строится по отсортированному набору (см. `FuelTxPivot`).
 */
export const getFuelTxPivot = (p: FuelTxRowsParams & { dims: string[] }) =>
  get<FuelPivotResp>('/api/fuel/transactions/pivot', {
    date_from: p.dateFrom, date_to: p.dateTo,
    dims: p.dims.join(','),
    station_code: p.stationCode,
    fuel_codes: p.fuelCodes?.length ? p.fuelCodes.join(',') : undefined,
    pay_types: p.payTypes?.length ? p.payTypes.join(',') : undefined,
    search: p.search, shift: p.shift, receipt: p.receipt, pos: p.pos, card: p.card,
    status: p.status,
  })

/** Справочник измерений для конструктора (тот же, что режет SQL на сервере). */
export const getFuelPivotDims = () =>
  get<{ dims: { key: string; label: string }[] }>('/api/fuel/transactions/pivot/dims')

export const getFuelTxFilters = (dateFrom: string, dateTo: string) =>
  get<FuelTxFilters>('/api/fuel/transactions/filters', { date_from: dateFrom, date_to: dateTo })

/** Дата выдачи купона, которым оплачена реализация (живёт только в STS). */
export const getFuelTxCoupon = (stationCode: number, dt: string, number: string) =>
  get<{ issued_at: string | null }>('/api/fuel/transactions/coupon', {
    station_code: stationCode, dt, number,
  })

// KPI-агрегаты периода для «Операций» (итого + по топливу + по оплате + кросс)
export interface FuelTxOverview {
  kpi: { count: number; liters: number; amount: number }
  by_fuel: { fuel_code: number | null; fuel_name: string; count: number; liters: number; amount: number }[]
  by_payment: { name: string; count: number; liters: number; amount: number }[]
  /** Топливо × оплата — для перекрёстного пересчёта карточек без похода в сеть. */
  by_fuel_payment: {
    fuel_code: number | null; fuel_name: string; name: string
    count: number; liters: number; amount: number
  }[]
}
export const getFuelTxOverview = (dateFrom: string, dateTo: string, stationCode?: number, fuelCodes?: number[]) =>
  get<FuelTxOverview>('/api/fuel/transactions/overview', {
    date_from: dateFrom, date_to: dateTo, station_code: stationCode,
    fuel_codes: fuelCodes?.length ? fuelCodes.join(',') : undefined,
  })
export const getFuelTxCount = () => get<{ transactions: number }>('/api/fuel/transactions/count')

export interface SalesChannelMetrics {
  count: number
  liters: number
  amount: number
  share: number
  avg_check: number
  avg_fill: number
  avg_price: number
}
export interface SalesChannelsAnalytics {
  period: { from: string; to: string }
  totals: SalesChannelMetrics & { stations: number }
  by_station: (SalesChannelMetrics & { code: number; name: string })[]
  by_payment: (SalesChannelMetrics & { name: string })[]
  by_fuel: (SalesChannelMetrics & { code: number | null; name: string })[]
  daily: { date: string; count: number; liters: number; amount: number }[]
  station_payment: (SalesChannelMetrics & {
    station_code: number
    station_name: string
    payment: string
  })[]
}
export interface SalesChannelsParams {
  dateFrom: string
  dateTo: string
  stationCodes?: number[]
  fuelCodes?: number[]
  payTypes?: string[]
}
export const getSalesChannelsAnalytics = (p: SalesChannelsParams) =>
  get<SalesChannelsAnalytics>('/api/fuel/sales-channels', {
    date_from: p.dateFrom,
    date_to: p.dateTo,
    station_codes: p.stationCodes?.length ? p.stationCodes.join(',') : undefined,
    fuel_codes: p.fuelCodes?.length ? p.fuelCodes.join(',') : undefined,
    pay_types: p.payTypes?.length ? p.payTypes.join(',') : undefined,
  })

// Загрузка реализаций из STS (фон) + статус прогона
export interface FuelTxSyncStatus { running: boolean; stations_done: number; stations_total: number; loaded: number; message: string }
export const syncFuelTransactions = (body: { date_from?: string; date_to?: string; all_period?: boolean; station_codes?: number[] }) =>
  post<{ status: string }>('/api/fuel/transactions/sync', body)
export const getFuelTxSyncStatus = () => get<FuelTxSyncStatus>('/api/fuel/transactions/sync-status')

// ─── Карта АЗС (координаты + метрики за период) ───
export interface FuelMapStation {
  code: number
  name: string
  address: string | null
  latitude: number | null
  longitude: number | null
  transactions: number
  liters: number
  amount: number
  cards: number
  last_at: string | null
  /** Метрики, не следующие за размером станции: чек, цена, интенсивность. */
  avg_check: number
  avg_price: number
  fills_per_day: number
  /** Прошлый период той же длины и рост к нему (null — сравнивать не с чем). */
  prev_amount: number
  growth_pct: number | null
  /** Структура спроса: ведущий продукт и его доля в выручке станции. */
  top_fuel: string | null
  top_fuel_pct: number | null
  by_fuel: { fuel_name: string; amount: number; liters: number }[]
}
export interface FuelMapResp {
  stations: FuelMapStation[]; with_coords: number; total: number
  days: number
  prev_period: { from: string; to: string }
}
export const getFuelStationsMap = (dateFrom: string, dateTo: string) =>
  get<FuelMapResp>('/api/fuel/stations/map', { date_from: dateFrom, date_to: dateTo })
export const syncFuelStationsGeo = () =>
  post<{ updated: number; with_coords: number }>('/api/fuel/stations/sync-geo')

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
