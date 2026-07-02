/**
 * Клиент API /api/analytics/* — 4 группы:
 *   management — pnl, paymentMix
 *   financial  — cashFlow, payablesReceivables
 *   tax        — vat, profit
 *   forecast   — monthForecast
 *
 * Все методы принимают периодные параметры в ISO (YYYY-MM-DD).
 */

import { get } from './apiClient'

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
  balance_start_liters: number
  receipts_liters: number
  sales_liters: number
  balance_end_liters: number
  loss_liters: number
  loss_pct: number
  tanks_count: number
}

export interface FuelBalanceResponse {
  period: { from: string; to: string }
  group_by: 'station' | 'fuel' | 'station_fuel'
  lines: FuelBalanceLine[]
  totals: FuelBalanceLine
  shifts_count: number
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
export type ChargeGroupBy = 'station' | 'region' | 'connector' | 'user_type' | 'charge_type' | 'tariff' | 'hour' | 'day' | 'result'
export type ChargeMetric = 'sessions' | 'energy_kwh' | 'amount' | 'avg_check' | 'avg_energy' | 'avg_duration_min' | 'success_pct' | 'price_per_kwh'
export type ChargeBucket = 'day' | 'week' | 'decade' | 'month' | 'quarter'
/** Разрез для серий графика/строк сравнения (без временных бакетов). */
export type ChargeSeriesBy = 'station' | 'region' | 'connector' | 'user_type' | 'charge_type' | 'tariff' | 'result'

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

export interface ChargeHeatmapResponse {
  metric: ChargeMetric
  cells: { hour: number; weekday: number; value: number }[]
  period: { from: string; to: string }
}
export async function getChargeHeatmap(p: PeriodParams & { metric?: ChargeMetric }): Promise<ChargeHeatmapResponse> {
  return get<ChargeHeatmapResponse>('/api/analytics/charge-sessions/heatmap', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    metric: p.metric ?? 'sessions',
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

export async function getFuelBalance(p: PeriodParams & { groupBy?: 'station' | 'fuel' | 'station_fuel' }): Promise<FuelBalanceResponse> {
  return get<FuelBalanceResponse>('/api/analytics/fuel-balance', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...(p.stationId ? { station_id: p.stationId } : {}),
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

export async function getChargeSessions(p: PeriodParams & { groupBy?: ChargeGroupBy }): Promise<ChargeSessionsResponse> {
  return get<ChargeSessionsResponse>('/api/analytics/charge-sessions', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...narrowParams(p),
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
  stations?: string[]; regions?: string[]
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
