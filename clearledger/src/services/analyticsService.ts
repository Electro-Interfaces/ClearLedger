/**
 * Клиент API /api/analytics/* — 4 группы:
 *   management — pnl, paymentMix
 *   financial  — cashFlow, payablesReceivables
 *   tax        — vat, profit
 *   forecast   — monthForecast
 *
 * Все методы принимают периодные параметры в ISO (YYYY-MM-DD).
 */

import { get, post } from './apiClient'

// ─── общие типы ─────────────────────────────────────────────────────

export interface PnLLine {
  label: string
  revenue: number
  revenue_net: number
  cogs: number
  gross_margin: number
  gross_margin_pct: number
  docs_count: number
  liters: number
}

export interface PnLResponse {
  period: { from: string; to: string }
  group_by: 'station' | 'fuel' | 'month'
  lines: PnLLine[]
  totals: PnLLine
  ptu_count: number
  shifts_count: number
}

export interface FuelBalanceLine {
  label: string
  station_code: number | null
  fuel_code: number | null
  balance_start_liters: number
  receipts_liters: number
  sales_liters: number
  balance_end_liters: number
  variance_liters: number
  variance_pct: number
  loss_liters: number
  loss_pct: number
  tanks_count: number
  records_count: number
  continuity_breaks: number
}

export interface FuelBalanceTank {
  station_id: string
  station_code: number | null
  station_name: string
  tank_number: number
  fuel_code: number | null
  fuel_name: string
  fuel_changed: boolean
  first_shift: number
  last_shift: number
  first_closed_at: string | null
  last_closed_at: string | null
  balance_start_liters: number
  receipts_liters: number
  sales_liters: number
  balance_end_liters: number
  variance_liters: number
  variance_pct: number
  shift_variance_liters: number
  continuity_gap_liters: number
  continuity_breaks: number
  records_count: number
}

export interface FuelBalanceIssue {
  type: 'continuity_gap' | 'fuel_change'
  station_id: string
  station_code: number | null
  station_name: string
  tank_number: number
  fuel_name: string
  previous_shift: number
  current_shift: number
  previous_closed_at: string | null
  current_closed_at: string | null
  previous_end_liters: number
  current_start_liters: number
  gap_liters: number
}

export interface FuelBalanceResponse {
  period: { from: string; to: string }
  group_by: 'station' | 'fuel' | 'station_fuel'
  dimensions: {
    stations: { code: number; name: string }[]
    fuels: { code: number; name: string }[]
  }
  method: {
    formula: string
    variance_sign: string
    natural_loss_applied: boolean
    adjustments_applied: boolean
    continuity_tolerance_liters: number
  }
  lines: FuelBalanceLine[]
  tanks: FuelBalanceTank[]
  issues: FuelBalanceIssue[]
  totals: FuelBalanceLine
  shifts_count: number
  integrity: {
    unique_tanks: number
    records_count: number
    continuity_checks: number
    continuity_breaks: number
    continuity_gap_liters: number
    fuel_changes: number
    issues_total: number
    issues_truncated: boolean
  }
}

export interface SalesChannelLine {
  channel: string
  label: string
  liters: number
  amount: number
  count: number
  avg_price: number
  share_pct: number
}

export interface SalesChannelsResponse {
  period: { from: string; to: string }
  lines: SalesChannelLine[]
  total_amount: number
  total_liters: number
  shifts_count: number
}

// ── Зарядные сессии ЭЗС (energy) ──
export interface ChargeSessionLine {
  label: string
  sessions: number
  energy_kwh: number
  amount: number
  avg_check: number
  avg_energy: number
  avg_duration_min: number
  success_pct: number
  price_per_kwh: number
  share_pct: number
  // порт-нормированные метрики (валидны для физических разрезов: станция/коннектор/регион; и в totals)
  ports: number
  stations: number          // уникальных станций в группе (для не-станционных разрезов)
  utilization_pct: number   // time-based: активные минуты ÷ (порты × период) × 100
  throughput_port: number   // кВтч/день на порт
  revenue_port: number      // ₽ на порт за период
  unpaid_pct: number        // % сессий без отметки оплаты (paid_at пуст)
}
export interface ChargeSessionsResponse {
  period: { from: string; to: string }
  group_by: string
  lines: ChargeSessionLine[]
  totals: ChargeSessionLine
  period_days?: number
}
export type ChargeGroupBy = 'station' | 'region' | 'connector' | 'user_type' | 'client' | 'charge_type' | 'tariff' | 'hour' | 'day' | 'result'
export type ChargeMetric = 'sessions' | 'energy_kwh' | 'amount' | 'avg_check' | 'avg_energy' | 'avg_duration_min' | 'success_pct' | 'price_per_kwh'
export type ChargeBucket = 'day' | 'week' | 'decade' | 'month' | 'quarter'
/** Разрез для серий графика/строк сравнения (без временных бакетов). */
export type ChargeSeriesBy = 'station' | 'region' | 'connector' | 'user_type' | 'client' | 'charge_type' | 'tariff' | 'result'

export interface ChargeInterval { key: string; from: string; to: string; label: string; partial: boolean }
export interface ChargeSliceResponse {
  period: { from: string; to: string }
  bucket: ChargeBucket
  metric: ChargeMetric
  group_by: string  // разрез или '__net__'
  intervals: ChargeInterval[]
  lines: ChargeCompareMultiLine[]  // label, values[] по интервалам, delta_*
  totals: { values: number[] }     // «Вся сеть» по интервалам
}

export interface ChargeTimeseriesResponse {
  bucket: ChargeBucket
  metric: ChargeMetric
  series: string[]
  data: Array<Record<string, string | number | null>>  // {bucket:'2026-01', 'GBT_DC':12345, 'Прочие':42}
  period: { from: string; to: string }
}

export interface ChargeCompareMultiLine {
  label: string
  values: (number | null)[]
  delta_first: number
  delta_prev: number
  delta_pct_prev: number
}
export interface ChargeCompareMultiResponse {
  periods: { from: string; to: string }[]
  group_by: string
  metric: ChargeMetric
  lines: ChargeCompareMultiLine[]
  totals: { values: number[] }
}

export interface ChargeCompareLine {
  label: string
  a_amount: number; b_amount: number; delta_amount: number; delta_pct: number
  a_energy: number; b_energy: number; delta_energy: number
  a_sessions: number; b_sessions: number; delta_sessions: number
}
export interface ChargeCompareResponse {
  period_a: { from: string; to: string }
  period_b: { from: string; to: string }
  group_by: string
  lines: ChargeCompareLine[]
  totals: { a_amount: number; b_amount: number; delta_amount: number; a_sessions: number; b_sessions: number }
}

export interface PaymentMixResponse {
  period: { from: string; to: string }
  shifts_count: number
  total_amount: number
  avg_per_shift: number
  breakdown: { cash: number; card: number; voucher: number; other: number }
  shares_pct: { cash: number; card: number; voucher: number; other: number }
}

export interface CashFlowAccountRow {
  account: string
  name: string
  debit: number
  credit: number
  net: number
}

export interface CashFlowResponse {
  period: { from: string; to: string }
  accounts: CashFlowAccountRow[]
  inflow_total: number
  outflow_total: number
  net_total: number
}

export interface ContragentBalance {
  counterparty: string
  inn: string | null
  debit: number
  credit: number
  balance: number
}

export interface PayablesReceivablesResponse {
  period: { from: string; to: string }
  payables: ContragentBalance[]
  receivables: ContragentBalance[]
  totals: { payables_balance: number; receivables_balance: number }
}

export interface VatResponse {
  period: { from: string; to: string }
  output_vat: number
  input_vat: number
  payable: number
  revenue_with_vat: number
  revenue_net: number
  effective_rate_pct: number
}

export interface ProfitResponse {
  period: { from: string; to: string }
  revenue_net: number
  cogs: number
  vat_output: number
  sga: number
  other_income: number
  other_expenses: number
  profit_before_tax: number
  tax_rate_pct: number
  tax_estimated: number
  net_profit: number
}

export interface MissingDoc {
  type: string
  reason: string
  count: number
  amount: number
}

export interface Risk {
  severity: 'info' | 'warn' | 'critical'
  type: string
  message: string
}

export interface MonthForecastResponse {
  year: number
  month: number
  days_total: number
  days_elapsed: number
  daily_avg_revenue: number
  revenue: { fact: number; projected: number }
  margin: { fact: number; projected: number }
  vat_payable: { fact: number; projected: number }
  missing_docs: MissingDoc[]
  risks: Risk[]
  period_closed: boolean
}

// ─── API methods ────────────────────────────────────────────────────

export interface PeriodParams {
  companyId: string
  dateFrom: string
  dateTo: string
  stationId?: string
  stations?: string[]   // energy: коды ЭЗС (сужение фильтром раздела)
  regions?: string[]    // energy: каноничные регионы
  dim?: string          // точечный фильтр по разрезу (drill-down): поле
  dimVal?: string       // ...и значение
}

export interface ChargeDimensions {
  stations: { code: string; name: string; sessions: number }[]
  regions: { region: string; sessions: number }[]
}
export async function getChargeDimensions(companyId: string): Promise<ChargeDimensions> {
  return get<ChargeDimensions>('/api/analytics/charge-sessions/dimensions', { company_id: companyId })
}

// ─── модель данных ЭЗС для раздела «Нормализация» (слои L1→L4 + звёздная схема) ───
export interface ChargeModelMember { label: string; count: number }
export interface ChargeModelLayer {
  key: string; code: string; title: string; desc: string
  records: number | null; unit: string; tone: 'raw' | 'clean' | 'export' | 'ref'
  status?: string
}
export interface ChargeModelMeasure {
  key: string; label: string; value: number; unit: string; agg: string
}
export interface ChargeModelDimension {
  key: string; label: string; field: string; cardinality: number
  fill_pct: number; canonical: boolean; grain?: string; members: ChargeModelMember[]
}
export interface ChargeModelQualityField {
  field: string; label: string; role: string; fill_pct: number
}
export interface ChargeModelCanon {
  name: string; from: string; to: string; members: number | null; coverage_pct: number
}
export interface ChargeModelResponse {
  rows: number
  l1_files: number
  layers: ChargeModelLayer[]
  fact: {
    table: string; name: string; grain: string; rows: number
    period: { from: string | null; to: string | null }
    measures: ChargeModelMeasure[]
  } | null
  dimensions: ChargeModelDimension[]
  quality: { fields: ChargeModelQualityField[]; canonicalization: ChargeModelCanon[] } | null
}
export async function getChargeModel(companyId: string): Promise<ChargeModelResponse> {
  return get<ChargeModelResponse>('/api/analytics/charge-sessions/model', { company_id: companyId })
}

/** Модель данных станций ЭЗС (объекты) для «Нормализации» — тот же контракт, что getChargeModel. */
export async function getStationsModel(companyId: string): Promise<ChargeModelResponse> {
  return get<ChargeModelResponse>('/api/analytics/stations/model', { company_id: companyId })
}

/** Модели данных топливного контура (ГИГ) для «Нормализации» — тот же контракт.
 *  dataset: shifts (смены STS + наливы) | receipts (ТТН) | sidegoods (сопутка/общепит ЦБ). */
export type FuelModelDataset = 'shifts' | 'receipts' | 'sidegoods'
export async function getFuelModel(companyId: string, dataset: FuelModelDataset): Promise<ChargeModelResponse> {
  return get<ChargeModelResponse>('/api/analytics/fuel/model', { company_id: companyId, dataset })
}

// ─── связь каналов по станции (конформная размерность) ───
export interface StationsLinkageChannel {
  name: string; template: string; key: string; materialized: boolean
  stations: number; linked: number; linked_pct: number
  records: number; records_linked: number; records_pct: number
  orphans: number; orphan_examples: string[]
}
export interface StationsLinkage {
  key_label: string
  objects: number            // ЭЗС в сети (боевые: без тест/выведенных) — для KPI
  objects_total?: number     // всего объектов в каталоге
  objects_test?: number
  objects_decommissioned?: number
  objects_enriched: number
  objects_without_sessions: number
  channels: StationsLinkageChannel[]
}
export async function getStationsLinkage(companyId: string): Promise<StationsLinkage> {
  return get<StationsLinkage>('/api/analytics/stations/linkage', { company_id: companyId })
}

// ─── сводная таблица (pivot) для экспорта из «Нормализации» ───
export type ChargePivotDim =
  | 'station' | 'region' | 'connector' | 'user_type' | 'client'
  | 'charge_type' | 'result' | 'cut' | 'tariff'
  | 'month' | 'week' | 'day' | 'decade' | 'quarter' | 'hour' | 'weekday'
export interface ChargePivotResponse {
  rows_dim: ChargePivotDim
  cols_dim: ChargePivotDim | null
  metric: ChargeMetric
  row_labels: string[]
  col_labels: string[]
  matrix: number[][]
  row_totals: number[]
  col_totals: number[]
  grand_total: number
  truncated: { rows: number; cols: number }
  period: { from: string; to: string }
}
export async function getChargePivot(p: {
  companyId: string; dateFrom: string; dateTo: string
  rows: ChargePivotDim; cols?: ChargePivotDim | null; metric?: ChargeMetric
  stations?: string[]; regions?: string[]
}): Promise<ChargePivotResponse> {
  return get<ChargePivotResponse>('/api/analytics/charge-sessions/pivot', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    rows: p.rows, cols: p.cols || undefined, metric: p.metric ?? 'amount',
    stations: p.stations?.length ? p.stations.join(',') : undefined,
    regions: p.regions?.length ? p.regions.join(',') : undefined,
  })
}

// ─── детальные строки сессий (лист «Сессии» в шаблонах экспорта) ───
export interface ChargeSessionRow {
  session_ext_id: string; station_code: string | null; station_name: string | null
  region: string | null; connector_type: string | null
  started_at: string | null; finished_at: string | null; duration_min: number
  result: string | null; charge_type: string | null; user_type: string | null
  client_name: string | null; energy_kwh: number; amount: number
  /** Выручка = client_amount (ЮЛ) либо amount (розница). У ЮЛ amount=0 — реальная выручка тут. */
  revenue: number; tariff: number
  /** Договорной ₽/кВт·ч ЮЛ (NULL у розницы). */
  client_tariff: number | null
  paid_at: string | null; cut_key: string | null
}
export interface ChargeSessionRowsResponse { rows: ChargeSessionRow[]; total: number; truncated: boolean }
export async function getChargeSessionRows(p: {
  companyId: string; dateFrom: string; dateTo: string; limit?: number
  stations?: string[]; regions?: string[]
}): Promise<ChargeSessionRowsResponse> {
  return get<ChargeSessionRowsResponse>('/api/analytics/charge-sessions/rows', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo, limit: p.limit ?? 100000,
    ...narrowParams(p),
  })
}

// ── группировки реестра сессий ────────────────────────────────────────
/** Разрез реестра. `family` — раздел в селекторе: сеть · клиент · процесс · время · визит. */
export interface ChargeGroupDef { key: string; label: string; family: string }

export interface ChargeGroupRow {
  key: string
  label: string
  sessions: number
  energy_kwh: number
  revenue: number
  avg_tariff: number
  avg_check: number
  avg_duration: number
  success_pct: number
  /** Доля сессий, отпустивших энергию. Отличается от success_pct: часть
   *  Complete отдала 0 кВтч, часть CompleteError — отдала. */
  charged_pct: number
  stations: number
  users: number
  first_at: string | null
  last_at: string | null
}

export interface ChargeGroupedResponse {
  group_by: string
  label: string
  period: { from: string; to: string }
  groups: ChargeGroupRow[]
  shown: number
  /** Групп больше, чем показано (limit) — итог при этом полный. */
  truncated: boolean
  totals: {
    groups: number; sessions: number; energy_kwh: number; revenue: number
    avg_tariff: number; avg_check: number; success_pct: number
  }
}

/** Фильтры реестра — те же, что у плоского списка (иначе итоги разойдутся). */
export interface ChargeGroupFilters {
  userType?: string | null
  region?: string | null
  connector?: string | null
  result?: string | null
  paid?: string | null
  search?: string | null
  stations?: string[] | null
}

const groupFilterParams = (f: ChargeGroupFilters) => ({
  user_type: f.userType || undefined,
  region: f.region || undefined,
  connector: f.connector || undefined,
  result: f.result || undefined,
  paid: f.paid || undefined,
  search: f.search || undefined,
  stations: f.stations?.length ? f.stations.join(',') : undefined,
})

export async function getChargeGroupCatalog(): Promise<ChargeGroupDef[]> {
  return get<ChargeGroupDef[]>('/api/analytics/charge-sessions/group-catalog', {})
}

export async function getChargeGrouped(p: {
  companyId: string; dateFrom: string; dateTo: string; groupBy: string
  sort?: string; sortDir?: string; limit?: number
} & ChargeGroupFilters): Promise<ChargeGroupedResponse> {
  return get<ChargeGroupedResponse>('/api/analytics/charge-sessions/grouped', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy, sort: p.sort, sort_dir: p.sortDir, limit: p.limit ?? 500,
    ...groupFilterParams(p),
  })
}

export interface ChargeGroupDetailRow {
  session_ext_id: string
  started_at: string | null
  station_code: string | null
  station_name: string | null
  region: string | null
  connector_type: string | null
  user_type: string | null
  client_name: string | null
  user_id: string | null
  charge_type: string | null
  energy_kwh: number
  duration_min: number | null
  tariff: number
  revenue: number
  result: string | null
  paid_at: string | null
  visit_seq: number | null
  visit_size: number | null
}

export async function getChargeGroupDetail(p: {
  companyId: string; dateFrom: string; dateTo: string; groupBy: string; key: string
  limit?: number
} & ChargeGroupFilters): Promise<{ rows: ChargeGroupDetailRow[] }> {
  return get<{ rows: ChargeGroupDetailRow[] }>('/api/analytics/charge-sessions/grouped/detail', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy, key: p.key, limit: p.limit ?? 100,
    ...groupFilterParams(p),
  })
}

export interface ChargeHeatmapResponse {
  metric: ChargeMetric
  cells: { hour: number; weekday: number; value: number }[]
  period: { from: string; to: string }
}
export async function getChargeHeatmap(p: PeriodParams & { metric?: ChargeMetric; tz?: 'msk' | 'local' }): Promise<ChargeHeatmapResponse> {
  return get<ChargeHeatmapResponse>('/api/analytics/charge-sessions/heatmap', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    metric: p.metric ?? 'sessions',
    ...(p.tz ? { tz: p.tz } : {}),
    ...narrowParams(p),
  })
}

export async function getPnL(p: PeriodParams & { groupBy?: 'station' | 'fuel' | 'month' }): Promise<PnLResponse> {
  return get<PnLResponse>('/api/analytics/pnl', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

export async function getFuelBalance(p: PeriodParams & {
  groupBy?: 'station' | 'fuel' | 'station_fuel'
  stationCodes?: number[]
  fuelCodes?: number[]
}): Promise<FuelBalanceResponse> {
  return get<FuelBalanceResponse>('/api/analytics/fuel-balance', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...(p.stationId ? { station_id: p.stationId } : {}),
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
  })
}

/** Строка журнала: один резервуар в одной смене. Книга и факт — разные величины. */
export interface TankLedgerRow {
  station_code: number
  station_name: string
  tank_number: number
  fuel_code: number | null
  fuel_name: string
  shift_number: number
  opened_at: string | null
  closed_at: string | null
  book_start: number
  receipts: number
  sales: number
  book_end: number
  /** Замер уровнемером на начало смены = замер конца предыдущей смены по резервуару; null — начало периода. */
  fact_start: number | null
  /** Замер уровнемером на конец смены; null — станция не передала. */
  fact_end: number | null
  /** Книга минус факт: плюс — недостача, минус — излишек. */
  fact_gap: number | null
  /** (начало + приход − отпуск) − конец. Не ноль — отчёт внутренне противоречив. */
  arithmetic_gap: number
  /** Начало смены минус конец предыдущей. Не ноль — между сменами правка мимо учёта. */
  continuity_gap: number | null
  /** Причина разрыва стыка: delivery | renumber | book_reset | pulled_to_fact | gap | manual | fuel_change | unexplained. */
  continuity_kind: string | null
  /** Человеческая формулировка причины разрыва (для подсказки). */
  continuity_reason: string | null
  /** Накладные, закреплённые за этой сменой и резервуаром (подтверждение прихода). */
  receipts_docs?: { ttn: string; volume: number }[]
  mass_start: number | null
  mass_end: number | null
  mass_received: number | null
  mass_sales: number | null
  fact_mass: number | null
  density_beg: number | null
  density_end: number | null
  temp_beg: number | null
  temp_end: number | null
  level_end: number | null
  water_volume: number | null
  fuel_changed: boolean
}

export interface TankLedgerTank {
  station_code: number
  station_name: string
  tank_number: number
  fuel_code: number | null
  fuel_name: string
  shifts: number
  first_shift: number
  last_shift: number
  book_start: number
  receipts: number
  sales: number
  book_end: number
  fact_end: number | null
  fact_gap: number | null
  fact_gap_pct: number | null
  /** Расхождение книги и факта на ВХОДЕ в период — отделяет старую недостачу от новой. */
  fact_gap_opening: number | null
  mass_receipts: number
  mass_sales: number
  mass_end: number | null
  fact_mass_end: number | null
  arithmetic_breaks: number
  continuity_breaks: number
  fact_breaks: number
  worst_fact_gap: number
  worst_fact_shift: number | null
}

export interface TankLedgerIssue {
  type: 'arithmetic' | 'continuity' | 'fuel_change'
  station_code: number
  station_name: string
  tank_number: number
  fuel_name: string
  shift_number: number
  prev_shift_number?: number | null
  date: string | null
  gap_liters: number
  detail: string
}

export interface TankLedgerResponse {
  period: { from: string; to: string }
  totals: {
    book_start: number; receipts: number; sales: number; book_end: number
    fact_end: number; fact_gap: number; fact_gap_pct: number
    mass_receipts: number; mass_sales: number
    tanks: number; shifts: number
    arithmetic_breaks: number; continuity_breaks: number; fact_breaks: number
  }
  tanks: TankLedgerTank[]
  rows: TankLedgerRow[]
  rows_total: number
  rows_truncated: boolean
  issues: TankLedgerIssue[]
  issues_total: number
  tolerances: { arithmetic_liters: number; continuity_liters: number; fact_liters: number }
}

export async function getTankLedger(p: PeriodParams & {
  stationCodes?: number[]
  fuelCodes?: number[]
  tankNumber?: number
}): Promise<TankLedgerResponse> {
  return get<TankLedgerResponse>('/api/analytics/tank-ledger', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
    ...(p.tankNumber != null ? { tank_number: String(p.tankNumber) } : {}),
  })
}

export type ReceiptClass = 'shortfall' | 'not_measured' | 'broken_measure' | 'surplus' | 'ok'

export interface ReceiptAnalysisRow {
  ttn: string
  date: string | null
  station_code: number
  station_name: string
  tank: number | null
  fuel_code: number | null
  fuel_name: string
  supplier: string
  doc_mass_kg: number
  fact_mass_kg: number
  diff_mass_kg: number
  diff_pct: number | null
  doc_volume_l: number
  fact_volume_l: number
  density_doc: number | null
  density_fact: number | null
  density_mismatch: boolean
  temp_doc: number | null
  temp_fact: number | null
  klass: ReceiptClass
  klass_title: string
}

export interface ReceiptAnalysisResponse {
  period: { from: string; to: string }
  totals: {
    ttn: number; doc_tonn: number; fact_tonn: number; diff_kg: number
    shortfall_ttn: number; shortfall_kg: number
    surplus_ttn: number
    not_measured_ttn: number; not_measured_kg: number
    broken_measure_ttn: number
    density_mismatch: number
  }
  classes: { klass: ReceiptClass; title: string; count: number; doc_kg: number; diff_kg: number }[]
  by_station: {
    station_code: number; station_name: string; ttn: number
    doc_kg: number; diff_kg: number
    shortfall: number; surplus: number; not_measured: number; broken_measure: number
  }[]
  rows: ReceiptAnalysisRow[]
  rows_total: number
  rows_truncated: boolean
  tolerance: { pct: number; min_kg: number }
}

export async function getReceiptAnalysis(p: PeriodParams & {
  stationCodes?: number[]
  fuelCodes?: number[]
}): Promise<ReceiptAnalysisResponse> {
  return get<ReceiptAnalysisResponse>('/api/analytics/receipt-analysis', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
  })
}

export type VarianceNature = 'stable' | 'drift' | 'jump' | 'noise' | 'short'

export interface VarianceTank {
  station_code: number
  station_name: string
  tank_number: number
  fuel_code: number | null
  fuel_name: string
  shifts: number
  last_gap: number
  nature: VarianceNature
  nature_title: string
  mean_gap: number
  std_gap: number
  /** Тренд расхождения, л/смену: >0 недостача растёт, <0 излишек растёт. */
  trend_per_shift: number
  /** Насколько тренд сдвинул расхождение за период, л. */
  accumulated: number
  jump_liters: number
  jump_shift: number | null
  jump_on_receipt: boolean
  /** Доля смен, где масса держится, а объём гуляет (тепловое расширение). */
  temperature_share: number
}

export interface VarianceDiagnosticsResponse {
  period: { from: string; to: string }
  totals: {
    tanks: number
    drift: number; jump: number; noise: number; stable: number
    temperature_driven: number
  }
  natures: { nature: VarianceNature; title: string; count: number; abs_accum: number }[]
  tanks: VarianceTank[]
  tolerance: { vol_liters: number; mass_kg: number; min_shifts: number }
}

export async function getVarianceDiagnostics(p: PeriodParams & {
  stationCodes?: number[]
  fuelCodes?: number[]
}): Promise<VarianceDiagnosticsResponse> {
  return get<VarianceDiagnosticsResponse>('/api/analytics/variance-diagnostics', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
  })
}

export interface InventoryDraftRow {
  station_id: string
  station_code: number
  station_name: string
  tank_number: number
  fuel_code: number | null
  fuel_name: string
  shift_number: number
  shift_date: string | null
  book_volume: number
  fact_volume: number
  adjustment_volume: number
  book_mass: number | null
  fact_mass: number | null
  adjustment_mass: number | null
  kind: 'излишек' | 'недостача' | 'сходится'
  already_confirmed: boolean
}

export interface InventoryDraftResponse {
  inventory_date: string
  rows: InventoryDraftRow[]
  totals: { tanks: number; surplus_tanks: number; shortfall_tanks: number; adjustment_volume: number }
}

export interface InventoryGroup {
  inventory_date: string
  tanks: number
  adjustment_volume: number
  surplus_tanks: number
  shortfall_tanks: number
  confirmed_at: string | null
  rows: {
    station_code: number; station_name: string; tank_number: number; fuel_name: string | null
    book_volume: number; fact_volume: number; adjustment_volume: number; note: string | null
  }[]
}

export async function getInventoryDraft(p: {
  date: string; stationCodes?: number[]; fuelCodes?: number[]
}): Promise<InventoryDraftResponse> {
  return post<InventoryDraftResponse>('/api/fuel/inventory/draft', {
    date: p.date,
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes } : {}),
  })
}

export async function saveInventory(p: {
  date: string; rows: unknown[]; note?: string
}): Promise<{ saved: number; inventory_date: string }> {
  return post('/api/fuel/inventory', { date: p.date, rows: p.rows, note: p.note })
}

export async function getInventories(p: {
  companyId: string; stationCodes?: number[]
}): Promise<{ inventories: InventoryGroup[] }> {
  return get('/api/fuel/inventory', {
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
  })
}

export async function getSalesChannels(p: PeriodParams): Promise<SalesChannelsResponse> {
  return get<SalesChannelsResponse>('/api/analytics/sales-channels', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

/** Общие параметры сужения (energy): коды станций/регионы + точечный dim-фильтр. */
function narrowParams(p: { stations?: string[]; regions?: string[]; stationId?: string; dim?: string; dimVal?: string }): Record<string, string> {
  return {
    ...(p.stationId ? { station_id: p.stationId } : {}),
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
    ...(p.dim && p.dimVal != null ? { dim: p.dim, dim_val: p.dimVal } : {}),
  }
}

export async function getChargeSessions(p: PeriodParams & { groupBy?: ChargeGroupBy; tz?: 'msk' | 'local' }): Promise<ChargeSessionsResponse> {
  return get<ChargeSessionsResponse>('/api/analytics/charge-sessions', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...(p.tz ? { tz: p.tz } : {}),
    ...narrowParams(p),
  })
}

// ─── Надёжность станций в разрезе производителя оборудования (на модели визитов) ───
/** Станция с брендом и метриками надёжности. Считается на склейке визитов
 *  (совпадает с «Повторными попытками»). Все проценты — доля от явной базы. */
export interface StationReliabilityRow {
  code: string | null
  label: string
  brand: string
  /** Визит = попытки одного клиента на станции подряд (≤gap_min мин) склеены. */
  visits: number
  /** Визиты, где отпущена энергия («человек уехал заряженным»). */
  charged_visits: number
  /** Визиты, где клиент так и не зарядился. = visits − charged_visits. */
  failed_visits: number
  /** Зарядившиеся визиты, где получилось НЕ с первой попытки (attempts>1). */
  retried_visits: number
  sessions: number
  /** Повторных сессий = сессий − визитов (лишние переподключения разъёма). */
  repeat_sessions: number
  /** Неудачных сессий = сессии без отпуска энергии (пробы/сорвы). */
  wasted_sessions: number
  /** Успех визита = charged_visits ÷ visits × 100. Главная метрика надёжности. */
  visit_success_pct: number
  /** Отпуск энергии по СЕССИЯМ = (sessions−wasted) ÷ sessions. «Сырой» успех. */
  charged_pct: number
  failed_pct: number
  retried_pct: number
  /** Ср. попыток = sessions ÷ visits (1.0 = всегда с первой). */
  avg_attempts: number
  energy_kwh: number
  amount: number
  /** Паспортная мощность станции, кВт — справка (не «факт против паспорта»). */
  power_kwt: number | null
  connectors: number | null
  /** Станция риска: ≥min_visits визитов и успех визита <success_pct. */
  risk: boolean
}
export interface BrandReliabilityResponse {
  period: { from: string; to: string }
  gap_min: number
  risk: { min_visits: number; success_pct: number }
  totals: {
    brands: number; stations: number; visits: number; sessions: number
    charged_visits: number; failed_visits: number; repeat_sessions: number
    wasted_sessions: number; visit_success_pct: number
    energy_kwh: number; amount: number; risk_stations: number
  }
  stations: StationReliabilityRow[]
}
export async function getChargeBrandReliability(p: PeriodParams): Promise<BrandReliabilityResponse> {
  return get<BrandReliabilityResponse>('/api/analytics/charge-sessions/reliability-brands', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...narrowParams(p),
  })
}

/** Составные визиты: смежные попытки одного клиента на одной станции, склеенные
 * в одно событие. Сырая сессия ≠ попытка зарядки — CPO пишет каждое касание
 * разъёма отдельной строкой, поэтому «успех сессий» и «человек зарядился» —
 * разные показатели. Разбор в разделе Надёжность → «Повторные попытки». */
export interface VisitTotals {
  visits: number
  sessions: number
  charged: number
  failed: number
  retried: number
  unpaid: number
  wasted_sessions: number
  max_attempts: number
  amount: number
  kwh: number
  success_pct: number
  session_success_pct: number
  retried_pct: number
}
export interface VisitDimRow {
  label: string
  visits: number
  charged: number
  retried: number
  failed: number
  sessions: number
  wasted: number
  amount: number
  avg_attempts: number
}
export interface VisitWorstRow {
  visit_key: string
  first_at: string
  attempts: number
  charged: boolean
  wasted: number
  station: string
  station_code: string
  region: string | null
  connector_type: string | null
  client: string | null
  kwh: number
  amount: number
  duration_min: number
}
export interface ChargeVisitsResponse {
  gap_min: number
  totals: VisitTotals
  distribution: { attempts: number; visits: number; charged: number; kwh: number }[]
  stations: VisitDimRow[]
  connectors: VisitDimRow[]
  regions: VisitDimRow[]
  clients: VisitDimRow[]
  worst: VisitWorstRow[]
}
export async function getChargeVisits(p: PeriodParams & { top?: number }): Promise<ChargeVisitsResponse> {
  return get<ChargeVisitsResponse>('/api/analytics/charge-sessions/visits', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.top ? { top: String(p.top) } : {}),
    ...narrowParams(p),
  })
}

/** Отпуск энергии без оплаты. Три разные природы под одним ярлыком, складывать
 * их нельзя: долг розницы (энергия ушла, денег нет), постоплата ЮЛ (счёт ещё не
 * выставлен — дебиторка, не убыток) и неоплаченные пробы (энергии не было). */
export interface UnpaidResponse {
  totals: {
    debt: { sessions: number; kwh: number; amount: number }
    postpaid: { sessions: number; kwh: number; amount: number; estimated: boolean }
    probes: { sessions: number }
  }
  stations: {
    station_code: string; label: string; debt_sessions: number; debt_amount: number
    corp_sessions: number; corp_kwh: number; probe_sessions: number
  }[]
  clients: { label: string; sessions: number; kwh: number; amount: number }[]
  trend: { month: string; debt_sessions: number; debt_amount: number; corp_sessions: number; corp_kwh: number }[]
  /** Аккаунты-должники: разовый сбой или повторяющийся клиент (cases > 1). */
  accounts: {
    account: string; cases: number; kwh: number; amount: number
    stations: number; first_at: string; last_at: string
  }[]
  cases: {
    session_ext_id: string; started_at: string; station_name: string | null; station_code: string
    region: string | null; connector_type: string | null; client: string
    energy_kwh: number; tariff: number; result: string | null; amount: number
  }[]
}
export async function getChargeUnpaid(p: PeriodParams & { top?: number }): Promise<UnpaidResponse> {
  return get<UnpaidResponse>('/api/analytics/charge-sessions/unpaid', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.top ? { top: String(p.top) } : {}),
    ...narrowParams(p),
  })
}

/** Детали неоплаты по одной станции — раскрывается кликом по строке. */
export interface UnpaidStationDetail {
  station_code: string
  retail: {
    session_ext_id: string; started_at: string; connector_type: string | null
    client: string; energy_kwh: number; tariff: number; result: string | null; amount: number
  }[]
  corp: { label: string; sessions: number; kwh: number; amount: number }[]
  probes: number
}
export async function getChargeUnpaidStation(p: {
  companyId: string; dateFrom: string; dateTo: string; code: string
}): Promise<UnpaidStationDetail> {
  return get<UnpaidStationDetail>('/api/analytics/charge-sessions/unpaid/station', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo, code: p.code,
  })
}

/** Длинный горизонт отпуска (2024→сейчас): сводная контрагента + сессии (склейка). */
export interface ChargeLongTrendMonth {
  period: string
  source: 'file' | 'sessions'
  kwh: number
  rub: number | null
  dims: Record<string, number> | null
}
export interface ChargeLongTrendResponse {
  months: ChargeLongTrendMonth[]
  groupBy: string
  dimKeys: string[]
  cutoff: string | null
}
export async function getChargeLongTrend(
  companyId: string, groupBy: 'none' | 'connector' | 'speed' | 'location_class',
  opts?: { stations?: string[]; regions?: string[] },
): Promise<ChargeLongTrendResponse> {
  return get<ChargeLongTrendResponse>('/api/analytics/charge-sessions/long-trend', {
    company_id: companyId, group_by: groupBy,
    ...(opts?.stations?.length ? { stations: opts.stations.join(',') } : {}),
    ...(opts?.regions?.length ? { regions: opts.regions.join(',') } : {}),
  })
}

export async function getChargeSessionsCompare(p: {
  companyId: string; aFrom: string; aTo: string; bFrom: string; bTo: string; groupBy?: 'station' | 'region' | 'connector' | 'user_type'
}): Promise<ChargeCompareResponse> {
  return get<ChargeCompareResponse>('/api/analytics/charge-sessions/compare', {
    company_id: p.companyId, a_from: p.aFrom, a_to: p.aTo, b_from: p.bFrom, b_to: p.bTo,
    group_by: p.groupBy ?? 'station',
  })
}

export async function getChargeTimeseries(p: PeriodParams & {
  bucket: ChargeBucket; seriesBy?: ChargeSeriesBy; metric: ChargeMetric; topN?: number
}): Promise<ChargeTimeseriesResponse> {
  return get<ChargeTimeseriesResponse>('/api/analytics/charge-sessions/timeseries', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    bucket: p.bucket, metric: p.metric,
    ...(p.seriesBy ? { series_by: p.seriesBy } : {}),
    ...(p.topN ? { top_n: p.topN } : {}),
    ...narrowParams(p),
  })
}

export async function getChargeCompareMulti(p: {
  companyId: string; periods: { from: string; to: string }[]; groupBy?: ChargeSeriesBy; metric?: ChargeMetric
  // dim/dimVal — точечный фильтр по разрезу (ФЛ/ЮЛ); narrowParams шлёт их как dim/dim_val
  stations?: string[]; regions?: string[]; dim?: string; dimVal?: string
}): Promise<ChargeCompareMultiResponse> {
  return get<ChargeCompareMultiResponse>('/api/analytics/charge-sessions/compare', {
    company_id: p.companyId, group_by: p.groupBy ?? 'station', metric: p.metric ?? 'amount',
    periods: p.periods.map((r) => `${r.from}:${r.to}`).join(','),  // одна строка — обход searchParams.set
    ...narrowParams(p),
  })
}

export async function getChargeSlice(p: PeriodParams & {
  bucket: ChargeBucket; groupBy?: ChargeSeriesBy; metric: ChargeMetric; topN?: number
}): Promise<ChargeSliceResponse> {
  return get<ChargeSliceResponse>('/api/analytics/charge-sessions/slice', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    bucket: p.bucket, metric: p.metric,
    ...(p.groupBy ? { group_by: p.groupBy } : {}),  // отсутствует → «Вся сеть»
    ...(p.topN ? { top_n: p.topN } : {}),
    ...narrowParams(p),
  })
}

/** Когорты: НОВЫЕ клиенты по интервалам нарезки периода (впервые за всю историю). */
export interface ChargeNewClientsInterval {
  key: string
  from: string
  to: string
  label: string
  partial: boolean
  activeClients: number
  newClients: number
  returningClients: number
  newSharePct: number | null
  newSessions: number
  newKwh: number
  newRevenue: number
  totalRevenue: number
  newRevenueSharePct: number | null
}

export interface ChargeNewClientsResponse {
  period: { from: string; to: string }
  bucket: string
  intervals: ChargeNewClientsInterval[]
  historyFrom: string | null
  totals: { newClients: number; activeClients: number; newRevenue: number }
}

export interface ChargeNewClientRow {
  key: string
  userType: string | null
  clientName: string | null
  userId: string | null
  firstAt: string | null
  sessions: number
  kwh: number
  revenue: number
  stations: number
}

export interface ChargeNewClientsListResponse {
  period: { from: string; to: string }
  count: number
  clients: ChargeNewClientRow[]
}

export async function getChargeNewClients(p: PeriodParams & { bucket: ChargeBucket }): Promise<ChargeNewClientsResponse> {
  return get<ChargeNewClientsResponse>('/api/analytics/charge-sessions/new-clients', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    bucket: p.bucket,
    ...narrowParams(p),
  })
}

export async function getChargeNewClientsList(p: PeriodParams & { limit?: number }): Promise<ChargeNewClientsListResponse> {
  return get<ChargeNewClientsListResponse>('/api/analytics/charge-sessions/new-clients/list', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.limit ? { limit: String(p.limit) } : {}),
    ...narrowParams(p),
  })
}

export async function getPaymentMix(p: PeriodParams): Promise<PaymentMixResponse> {
  return get<PaymentMixResponse>('/api/analytics/payment-mix', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

export async function getCashFlow(p: PeriodParams): Promise<CashFlowResponse> {
  return get<CashFlowResponse>('/api/analytics/cash-flow', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getPayablesReceivables(p: PeriodParams): Promise<PayablesReceivablesResponse> {
  return get<PayablesReceivablesResponse>('/api/analytics/payables-receivables', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getVat(p: PeriodParams): Promise<VatResponse> {
  return get<VatResponse>('/api/analytics/vat', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getProfit(p: PeriodParams): Promise<ProfitResponse> {
  return get<ProfitResponse>('/api/analytics/profit', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getMonthForecast(p: { companyId: string; year: number; month: number; stationId?: string }): Promise<MonthForecastResponse> {
  return get<MonthForecastResponse>('/api/analytics/forecast/month', {
    company_id: p.companyId, year: p.year, month: p.month,
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

// ─── вспомогательные форматтеры для UI ──────────────────────────────

export function fmtMoney(n: number): string {
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)
}

export function fmtMoneyShort(n: number): string {
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' млрд'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' млн'
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' тыс'
  return fmtMoney(n)
}

export function fmtLiters(n: number): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n) + ' л'
}

export function fmtPct(n: number): string {
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

// ── метрики зарядных сессий: подписи и форматирование ──
export const CHARGE_METRIC_LABELS: Record<ChargeMetric, string> = {
  sessions: 'Сессии',
  energy_kwh: 'Энергия, кВтч',
  amount: 'Выручка, ₽',
  avg_check: 'Средний чек, ₽',
  avg_energy: 'Ср. энергия/сессия, кВтч',
  avg_duration_min: 'Ср. длительность, мин',
  success_pct: 'Успешных, %',
  price_per_kwh: 'Цена, ₽/кВтч',
}

/** Полное форматирование значения метрики (тултипы/таблицы). */
export function fmtMetric(metric: ChargeMetric, value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  switch (metric) {
    case 'sessions': return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value)
    case 'energy_kwh':
    case 'avg_energy': return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value) + ' кВтч'
    case 'amount':
    case 'avg_check': return fmtMoney(value) + ' ₽'
    case 'price_per_kwh': return fmtMoney(value) + ' ₽/кВтч'
    case 'success_pct': return value.toFixed(1) + '%'
    case 'avg_duration_min': return Math.round(value) + ' мин'
    default: return String(value)
  }
}

/** Значение метрики БЕЗ суффикса единицы (₽/кВтч/мин) — для плотных таблиц,
 * где единица вынесена в заголовок. Проценты оставляем (компактно и однозначно). */
export function fmtMetricCompact(metric: ChargeMetric, value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  switch (metric) {
    case 'sessions': return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value)
    case 'energy_kwh':
    case 'avg_energy': return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)
    case 'amount':
    case 'avg_check':
    case 'price_per_kwh': return fmtMoney(value)
    case 'success_pct': return value.toFixed(1) + '%'
    case 'avg_duration_min': return Math.round(value).toString()
    default: return String(value)
  }
}

/** Единица метрики для подписи заголовка/шапки. */
export function metricUnit(metric: ChargeMetric): string {
  switch (metric) {
    case 'amount': case 'avg_check': return '₽'
    case 'price_per_kwh': return '₽/кВтч'
    case 'energy_kwh': case 'avg_energy': return 'кВтч'
    case 'success_pct': return '%'
    case 'avg_duration_min': return 'мин'
    default: return 'шт'
  }
}

/** Компактное форматирование для осей графика. */
export function fmtMetricShort(metric: ChargeMetric, value: number | null): string {
  if (value == null || Number.isNaN(value)) return ''
  switch (metric) {
    case 'sessions': return new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
    case 'energy_kwh':
    case 'avg_energy': return new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
    case 'amount':
    case 'avg_check':
    case 'price_per_kwh': return fmtMoneyShort(value)
    case 'success_pct': return value.toFixed(0) + '%'
    case 'avg_duration_min': return Math.round(value) + 'м'
    default: return String(value)
  }
}

export function currentMonthBounds(): { from: string; to: string; year: number; month: number } {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth() + 1
  const first = new Date(y, m - 1, 1)
  const last = new Date(y, m, 0)
  return {
    from: first.toISOString().slice(0, 10),
    to: last.toISOString().slice(0, 10),
    year: y,
    month: m,
  }
}
