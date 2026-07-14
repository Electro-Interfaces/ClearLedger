/**
 * Клиент API аналитики продаж топлива по наливам (/api/fuel/analytics/*,
 * /api/fuel/tariffs/*, /api/fuel/corporate/*, /api/fuel/retail/*).
 *
 * Раздел «Продажи» ГИГ, группы «Аналитика» (Наливы) и «Коммерция»
 * (Тарифы / Корпоратив / Частные лица). Зеркало charge-секции analyticsService,
 * но в топливных единицах: литры, ₽/л, виды оплаты STS, каналы/сегменты.
 */

import { get } from './apiClient'
import type { ChartFormat } from '@/components/workspace/analytics/ChargeChart'

// ─── типы разрезов/метрик ───────────────────────────────────────────

export type FuelGroupBy =
  | 'station' | 'fuel' | 'pay_type' | 'channel' | 'segment'
  | 'hour' | 'weekday' | 'shift' | 'card'
  | 'day' | 'week' | 'decade' | 'month' | 'quarter'
export type FuelMetric = 'amount' | 'liters' | 'fills' | 'avg_check' | 'avg_fill' | 'avg_price'
export type FuelBucket = 'day' | 'week' | 'decade' | 'month' | 'quarter'
/** Сегмент бизнеса: corp = топливные карты + ведомости, retail = наличные + банк. карты. */
export type FuelSegment = 'corp' | 'retail' | 'online' | 'other' | 'unmapped'

/** Общее сужение запросов панели (сегмент/канал/станции/топливо/карта). */
export interface FuelNarrow {
  stationCodes?: number[]
  fuelCodes?: number[]
  segment?: FuelSegment
  channel?: string
  card?: string
}

function narrowParams(p: FuelNarrow): Record<string, string> {
  return {
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
    ...(p.segment ? { segment: p.segment } : {}),
    ...(p.channel ? { channel: p.channel } : {}),
    ...(p.card ? { card: p.card } : {}),
  }
}

export interface FuelPeriodParams extends FuelNarrow {
  companyId: string
  dateFrom: string
  dateTo: string
}

// ─── Наливы: разрезы ────────────────────────────────────────────────

export interface FuelFillsLine {
  key: string
  label: string
  fills: number
  liters: number
  amount: number
  avg_check: number
  avg_fill: number
  avg_price: number
  stations: number
  cards: number
  share_pct: number
}

export interface FuelFillsResponse {
  period: { from: string; to: string }
  group_by: FuelGroupBy
  lines: FuelFillsLine[]
  truncated: number
  totals: FuelFillsLine & { label: 'Итого' }
}

export async function getFuelFills(p: FuelPeriodParams & { groupBy?: FuelGroupBy; top?: number }): Promise<FuelFillsResponse> {
  return get<FuelFillsResponse>('/api/fuel/analytics/fills', {
    date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...(p.top ? { top: p.top } : {}),
    ...narrowParams(p),
  })
}

// ─── Наливы: динамика / нарезка / сравнение / heatmap ──────────────

export interface FuelTimeseriesResponse {
  bucket: FuelBucket
  metric: FuelMetric
  period: { from: string; to: string }
  series: string[]
  data: Record<string, string | number | null>[]
}

export async function getFuelTimeseries(p: FuelPeriodParams & {
  bucket: FuelBucket; metric: FuelMetric; seriesBy?: FuelGroupBy; topN?: number
}): Promise<FuelTimeseriesResponse> {
  return get<FuelTimeseriesResponse>('/api/fuel/analytics/fills/timeseries', {
    date_from: p.dateFrom, date_to: p.dateTo,
    bucket: p.bucket, metric: p.metric,
    ...(p.seriesBy ? { series_by: p.seriesBy } : {}),
    ...(p.topN ? { top_n: p.topN } : {}),
    ...narrowParams(p),
  })
}

export interface FuelInterval { key: string; from: string; to: string; label: string; partial: boolean }
export interface FuelSliceLine {
  label: string
  values: (number | null)[]
  delta_first: number
  delta_prev: number
  delta_pct_prev: number
}
export interface FuelSliceResponse {
  period: { from: string; to: string }
  bucket: FuelBucket
  metric: FuelMetric
  group_by: string
  intervals: FuelInterval[]
  lines: FuelSliceLine[]
  totals: { values: (number | null)[] }
}

export async function getFuelSlice(p: FuelPeriodParams & {
  bucket: FuelBucket; groupBy?: FuelGroupBy; metric: FuelMetric; topN?: number
}): Promise<FuelSliceResponse> {
  return get<FuelSliceResponse>('/api/fuel/analytics/fills/slice', {
    date_from: p.dateFrom, date_to: p.dateTo,
    bucket: p.bucket, metric: p.metric,
    ...(p.groupBy ? { group_by: p.groupBy } : {}),
    ...(p.topN ? { top_n: p.topN } : {}),
    ...narrowParams(p),
  })
}

export interface FuelCompareResponse {
  periods: { from: string; to: string }[]
  group_by: string
  metric: FuelMetric
  lines: FuelSliceLine[]
  totals: { values: (number | null)[] }
}

export async function getFuelCompareMulti(p: FuelNarrow & {
  companyId: string
  periods: { from: string; to: string }[]
  groupBy?: FuelGroupBy
  metric?: FuelMetric
}): Promise<FuelCompareResponse> {
  return get<FuelCompareResponse>('/api/fuel/analytics/fills/compare', {
    periods: p.periods.map((r) => `${r.from}:${r.to}`).join(','),
    group_by: p.groupBy ?? 'station', metric: p.metric ?? 'amount',
    ...narrowParams(p),
  })
}

export interface FuelHeatmapResponse {
  metric: FuelMetric
  cells: { hour: number; weekday: number; value: number }[]
  period: { from: string; to: string }
}

export async function getFuelHeatmap(p: FuelPeriodParams & { metric?: FuelMetric }): Promise<FuelHeatmapResponse> {
  return get<FuelHeatmapResponse>('/api/fuel/analytics/fills/heatmap', {
    date_from: p.dateFrom, date_to: p.dateTo,
    metric: p.metric ?? 'fills',
    ...narrowParams(p),
  })
}

// ─── Наливы: когорты «новые карты» ──────────────────────────────────

export interface FuelNewCardsInterval extends FuelInterval {
  activeCards: number
  newCards: number
  returningCards: number
  newSharePct: number | null
  newFills: number
  newLiters: number
  newRevenue: number
  totalRevenue: number
  newRevenueSharePct: number | null
}

export interface FuelNewCardsResponse {
  period: { from: string; to: string }
  bucket: string
  intervals: FuelNewCardsInterval[]
  historyFrom: string | null
  totals: { newCards: number; activeCards: number; newRevenue: number }
}

export async function getFuelNewCards(p: FuelPeriodParams & { bucket: FuelBucket }): Promise<FuelNewCardsResponse> {
  return get<FuelNewCardsResponse>('/api/fuel/analytics/fills/new-cards', {
    date_from: p.dateFrom, date_to: p.dateTo, bucket: p.bucket,
    ...narrowParams(p),
  })
}

export interface FuelNewCardRow {
  card: string
  firstAt: string | null
  fills: number
  liters: number
  revenue: number
  stations: number
  channel: string
}

export interface FuelNewCardsListResponse {
  period: { from: string; to: string }
  count: number
  cards: FuelNewCardRow[]
}

export async function getFuelNewCardsList(p: FuelPeriodParams & { limit?: number }): Promise<FuelNewCardsListResponse> {
  return get<FuelNewCardsListResponse>('/api/fuel/analytics/fills/new-cards/list', {
    date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.limit ? { limit: p.limit } : {}),
    ...narrowParams(p),
  })
}

// ─── Тарифы ─────────────────────────────────────────────────────────

export interface FuelTariffCell {
  station_code: number
  fuel_code: number
  fills: number
  liters: number
  price_avg: number | null
  price_min: number
  price_max: number
  varies: boolean
  realized: number | null
}

export interface FuelTariffGridResponse {
  period: { from: string; to: string }
  stations: { code: number; name: string }[]
  fuels: { code: number; name: string }[]
  cells: FuelTariffCell[]
}

export async function getFuelTariffGrid(p: { companyId: string; dateFrom: string; dateTo: string }): Promise<FuelTariffGridResponse> {
  return get<FuelTariffGridResponse>('/api/fuel/tariffs/grid', { date_from: p.dateFrom, date_to: p.dateTo })
}

export interface FuelPriceDeviationLine {
  station_code: number
  station: string
  fuel_code: number
  fuel: string
  fills: number
  liters: number
  price: number
  net_avg: number
  delta: number
  delta_pct: number
}

export interface FuelDeviationsResponse {
  period: { from: string; to: string }
  lines: FuelPriceDeviationLine[]
  discounts_by_channel: { channel: string; label: string; amount: number; discount: number }[]
}

export async function getFuelPriceDeviations(p: { companyId: string; dateFrom: string; dateTo: string }): Promise<FuelDeviationsResponse> {
  return get<FuelDeviationsResponse>('/api/fuel/tariffs/deviations', { date_from: p.dateFrom, date_to: p.dateTo })
}

export interface FuelPriceTimeseriesResponse {
  period: { from: string; to: string }
  bucket: 'week' | 'month'
  series: string[]
  data: Record<string, string | number | null>[]
}

export async function getFuelPriceTimeseries(p: {
  companyId: string; dateFrom: string; dateTo: string; bucket?: 'week' | 'month'; fuelCodes?: number[]
}): Promise<FuelPriceTimeseriesResponse> {
  return get<FuelPriceTimeseriesResponse>('/api/fuel/tariffs/timeseries', {
    date_from: p.dateFrom, date_to: p.dateTo,
    bucket: p.bucket ?? 'week',
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
  })
}

// ─── Корпоратив ─────────────────────────────────────────────────────

export interface FuelBreakdownRow {
  label: string
  fills: number
  liters: number
  amount: number
  share_pct: number
  avg_check?: number
}

export interface FuelCorporateOverviewResponse {
  period: { from: string; to: string }
  kpi: {
    amount: number
    liters: number
    fills: number
    active_cards: number
    stations: number
    avg_fill: number
    avg_price: number
    share_of_total_pct: number
  }
  by_fuel: FuelBreakdownRow[]
  by_station: FuelBreakdownRow[]
  by_channel: FuelBreakdownRow[]
  monthly: { month: string; fills: number; liters: number; amount: number; cards: number }[]
}

export async function getFuelCorporateOverview(p: { companyId: string; dateFrom: string; dateTo: string }): Promise<FuelCorporateOverviewResponse> {
  return get<FuelCorporateOverviewResponse>('/api/fuel/corporate/overview', { date_from: p.dateFrom, date_to: p.dateTo })
}

export interface FuelCounterpartyRow {
  name: string
  channel: string
  fills: number
  liters: number
  amount: number
  avg_fill: number
  avg_price: number
  stations: number
  cards: number
  share_pct: number
  trend: number[]
}

export interface FuelCounterpartiesResponse {
  period: { from: string; to: string }
  months: string[]
  rows: FuelCounterpartyRow[]
  totals: { amount: number; fills: number; liters: number }
}

export async function getFuelCorporateCounterparties(p: { companyId: string; dateFrom: string; dateTo: string }): Promise<FuelCounterpartiesResponse> {
  return get<FuelCounterpartiesResponse>('/api/fuel/corporate/counterparties', { date_from: p.dateFrom, date_to: p.dateTo })
}

export interface FuelCardRow {
  card: string
  /** Точка расширения НСИ «карта → организация»: пока всегда null. */
  org: string | null
  pay_type: string | null
  fills: number
  liters: number
  amount: number
  avg_fill: number
  stations: number
  fuels: number
  first_dt: string | null
  last_dt: string | null
  trend: number[]
}

export interface FuelCardsResponse {
  period: { from: string; to: string }
  total: number
  months: string[]
  totals: { cards: number; fills: number; liters: number; amount: number }
  rows: FuelCardRow[]
}

export type FuelCardsSort = 'amount' | 'liters' | 'fills' | 'avg_fill' | 'first_dt' | 'last_dt'

export async function getFuelCorporateCards(p: {
  companyId: string; dateFrom: string; dateTo: string
  sort?: FuelCardsSort; order?: 'asc' | 'desc'; limit?: number; offset?: number
  search?: string; segment?: FuelSegment
}): Promise<FuelCardsResponse> {
  return get<FuelCardsResponse>('/api/fuel/corporate/cards', {
    date_from: p.dateFrom, date_to: p.dateTo,
    sort: p.sort ?? 'amount', order: p.order ?? 'desc',
    limit: p.limit ?? 50, offset: p.offset ?? 0,
    ...(p.search ? { search: p.search } : {}),
    ...(p.segment ? { segment: p.segment } : {}),
  })
}

// ─── Частные лица ───────────────────────────────────────────────────

export interface FuelRetailOverviewResponse {
  period: { from: string; to: string }
  kpi: {
    amount: number
    liters: number
    fills: number
    avg_check: number
    avg_fill: number
    cashless_pct: number
    share_of_total_pct: number
    check_median: number
    check_p90: number
  }
  by_pay: (FuelBreakdownRow & { channel: string })[]
  by_fuel: FuelBreakdownRow[]
  by_station: FuelBreakdownRow[]
  check_histogram: { label: string; count: number; amount: number }[]
  weekly: { week: string; fills: number; amount: number; avg_check: number }[]
}

export async function getFuelRetailOverview(p: { companyId: string; dateFrom: string; dateTo: string }): Promise<FuelRetailOverviewResponse> {
  return get<FuelRetailOverviewResponse>('/api/fuel/retail/overview', { date_from: p.dateFrom, date_to: p.dateTo })
}

export interface FuelRetailLoyaltyResponse {
  period: { from: string; to: string }
  kpi: {
    cards: number
    repeat_cards: number
    repeat_share_pct: number
    repeat_revenue_pct: number
    avg_fills_per_card: number
    card_coverage_fills_pct: number
    card_coverage_amount_pct: number
  }
  freq_histogram: { label: string; cards: number; fills: number; amount: number }[]
  top_cards: { card: string; fills: number; liters: number; amount: number }[]
}

export async function getFuelRetailLoyalty(p: { companyId: string; dateFrom: string; dateTo: string }): Promise<FuelRetailLoyaltyResponse> {
  return get<FuelRetailLoyaltyResponse>('/api/fuel/retail/loyalty', { date_from: p.dateFrom, date_to: p.dateTo })
}

// ─── подписи и форматирование топливных метрик ──────────────────────

export const FUEL_METRIC_LABELS: Record<FuelMetric, string> = {
  amount: 'Выручка, ₽',
  liters: 'Объём, л',
  fills: 'Наливы',
  avg_check: 'Средний чек, ₽',
  avg_fill: 'Ср. налив, л',
  avg_price: 'Цена, ₽/л',
}

export const FUEL_RATIO_METRICS: FuelMetric[] = ['avg_check', 'avg_fill', 'avg_price']
export const isFuelRatio = (m: FuelMetric): boolean => FUEL_RATIO_METRICS.includes(m)

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Полное форматирование значения топливной метрики (тултипы/таблицы). */
export function fmtFuelMetric(metric: FuelMetric, value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  switch (metric) {
    case 'fills': return nf0.format(value)
    case 'liters': return nf0.format(value) + ' л'
    case 'avg_fill': return nf1.format(value) + ' л'
    case 'amount':
    case 'avg_check': return nf2.format(value) + ' ₽'
    case 'avg_price': return nf2.format(value) + ' ₽/л'
    default: return String(value)
  }
}

/** Компактно (ячейки широких таблиц): без дробных копеек у крупных сумм. */
export function fmtFuelMetricCompact(metric: FuelMetric, value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  switch (metric) {
    case 'fills': return nf0.format(value)
    case 'liters': return nf0.format(value)
    case 'avg_fill': return nf1.format(value)
    case 'amount': return nf0.format(value)
    case 'avg_check': return nf0.format(value)
    case 'avg_price': return nf2.format(value)
    default: return String(value)
  }
}

/** Кратко для осей графиков (тыс/млн). */
export function fmtFuelMetricShort(metric: FuelMetric, value: number): string {
  const abs = Math.abs(value)
  if (metric === 'amount' || metric === 'liters') {
    if (abs >= 1e9) return (value / 1e9).toFixed(1) + ' млрд'
    if (abs >= 1e6) return (value / 1e6).toFixed(1) + ' млн'
    if (abs >= 1e3) return (value / 1e3).toFixed(0) + ' тыс'
  }
  if (metric === 'avg_price' || metric === 'avg_check') return nf0.format(value)
  return nf0.format(value)
}

/** Адаптер форматирования для общего графика ChargeChart/ChartControls. */
export function fuelChartFormat(metric: FuelMetric): ChartFormat {
  return {
    label: FUEL_METRIC_LABELS[metric],
    ratio: isFuelRatio(metric),
    fmt: (v) => fmtFuelMetric(metric, v),
    fmtShort: (v) => fmtFuelMetricShort(metric, v),
  }
}

/** Рубли без копеек (сводки/бейджи). */
export function fmtRub0(n: number): string {
  return nf0.format(n) + ' ₽'
}
