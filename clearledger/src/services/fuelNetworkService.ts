/**
 * Клиент API сетевых срезов «Топлива» (/api/fuel/analytics/pumps|silent|abc-xyz|
 * clients|visits|insights).
 *
 * Отдельно от `fuelSalesService` (разрезы наливов) намеренно: там вопрос «сколько
 * продали и в каком разрезе», здесь — «где сеть не работает и где лежат деньги».
 * Разные вопросы, разные экраны, разный ритм изменений.
 */

import { get } from './apiClient'
import type { FuelNarrow } from './fuelSalesService'

interface Params extends FuelNarrow {
  companyId: string
  dateFrom: string
  dateTo: string
}

function narrow(p: FuelNarrow): Record<string, string> {
  return {
    ...(p.stationCodes?.length ? { station_codes: p.stationCodes.join(',') } : {}),
    ...(p.fuelCodes?.length ? { fuel_codes: p.fuelCodes.join(',') } : {}),
    ...(p.segment ? { segment: p.segment } : {}),
    ...(p.channel ? { channel: p.channel } : {}),
  }
}

// ─── Оборудование: ТРК и пистолеты ──────────────────────────────────────

export type PumpLevel = 'pos' | 'nozzle'

export interface PumpRow {
  station_code: number
  station: string
  pos: number | null
  nozzle: number | null
  fuel_name: string | null
  fuels: number
  fills: number
  liters: number
  amount: number
  avg_fill: number
  avg_check: number
  /** Наливов в сутки — метрика сравнения: абсолютные цифры зависят от размера АЗС. */
  fills_per_day: number
  liters_per_day: number
  active_days: number
  idle_days: number
  first_at: string | null
  last_at: string | null
  silent: boolean
  share_pct: number
  station_share_pct: number
}

export interface PumpsResponse {
  period: { from: string; to: string }
  level: PumpLevel
  days: number
  lines: PumpRow[]
  totals: {
    units: number; active: number; silent: number; stations: number
    fills: number; liters: number; amount: number
    median_fills_per_day: number; top_fills_per_day: number
  }
}

export async function getFuelPumps(p: Params & { level?: PumpLevel }): Promise<PumpsResponse> {
  return get<PumpsResponse>('/api/fuel/analytics/pumps', {
    date_from: p.dateFrom, date_to: p.dateTo, level: p.level ?? 'nozzle', ...narrow(p),
  })
}

// ─── Молчащие точки ─────────────────────────────────────────────────────

export interface SilentRow {
  station_code: number
  station: string
  pos: number | null
  nozzle: number | null
  last_at: string | null
  days_idle: number | null
}

export interface SilentResponse {
  period: { from: string; to: string }
  stations: SilentRow[]
  pumps: SilentRow[]
  nozzles: SilentRow[]
  counts: { stations: number; pumps: number; nozzles: number }
}

export async function getFuelSilent(p: Params): Promise<SilentResponse> {
  return get<SilentResponse>('/api/fuel/analytics/silent', {
    date_from: p.dateFrom, date_to: p.dateTo,
  })
}

// ─── ABC-XYZ и концентрация ─────────────────────────────────────────────

export type AbcDimension = 'station' | 'fuel' | 'station_fuel'
export type AbcMeasure = 'amount' | 'liters'

export interface AbcItem {
  key: string
  label: string
  station_code: number | null
  /** Станция и вид топлива приходят раздельно — это две колонки, не одна строка. */
  station_label: string | null
  fuel_name: string | null
  measure: number
  amount: number
  liters: number
  fills: number
  cards: number
  active_buckets: number
  cv: number | null
  /** Бакетов жизни позиции (от первой продажи) и окно расчёта разброса. */
  life_buckets: number
  stab_window: number | null
  /** Тренд за всю жизнь позиции — отдельный признак, а не часть разброса. */
  trend_pct: number | null
  trend: 'up' | 'down' | 'flat'
  short_history: boolean
  abc: 'A' | 'B' | 'C'
  xyz: 'X' | 'Y' | 'Z' | '—'
  class: string
  hint: string
  share_pct: number
  cum_share_pct: number
  /** Группа концентрации (1 — верхние 20 % по выручке): считает сервер. */
  quintile?: number
}

export interface AbcResponse {
  period: { from: string; to: string }
  dimension: AbcDimension
  bucket: 'week' | 'month'
  measure_kind: AbcMeasure
  buckets: number
  /** Полных бакетов в периоде и до какого из них есть данные в сети. */
  period_buckets: number
  data_through: string | null
  items: AbcItem[]
  matrix: { cell: string; count: number; measure: number; share_pct: number; hint: string }[]
  quintiles: { quintile: number; count: number; measure: number; share_pct: number }[]
  labels: { abc: Record<string, string>; xyz: Record<string, string> }
  totals: { count: number; measure: number }
}

export async function getFuelAbcXyz(p: Params & {
  dimension?: AbcDimension; bucket?: 'week' | 'month'; measure?: AbcMeasure
}): Promise<AbcResponse> {
  return get<AbcResponse>('/api/fuel/analytics/abc-xyz', {
    date_from: p.dateFrom, date_to: p.dateTo,
    dimension: p.dimension ?? 'station_fuel',
    bucket: p.bucket ?? 'week',
    measure: p.measure ?? 'amount',
    ...narrow(p),
  })
}

// ─── Клиенты: когорты и движение базы ───────────────────────────────────

export interface ClientCohort {
  code: string
  label: string
  cards: number
  fills: number
  amount: number
  liters: number
  cards_pct: number
  amount_pct: number
  avg_check: number
  avg_card: number
}

export interface ClientsResponse {
  period: { from: string; to: string }
  cohorts: ClientCohort[]
  /** Что берут клиенты: у ДТ и АИ-95 разные люди и разный чек. */
  by_fuel: {
    fuel_name: string; cards: number; fills: number
    amount: number; liters: number; avg_check: number; amount_pct: number
  }[]
  concentration: {
    top1_pct: number; top5_pct: number; top10_pct: number; top20_pct: number
    cards_top10: number
  }
  movement: {
    active: number; new: number; returning: number; churned: number
    prev_active: number; retention_pct: number | null
    new_amount: number; returning_amount: number
    prev_period: { from: string; to: string }
  }
  top_cards: {
    card: string; fills: number; amount: number; liters: number; stations: number
    avg_check: number; first_at: string | null; last_at: string | null; is_new: boolean
  }[]
  totals: { cards: number; amount: number; fills: number }
}

export async function getFuelClients(p: Params): Promise<ClientsResponse> {
  return get<ClientsResponse>('/api/fuel/analytics/clients', {
    date_from: p.dateFrom, date_to: p.dateTo, ...narrow(p),
  })
}

// ─── Визиты ─────────────────────────────────────────────────────────────

export interface VisitsResponse {
  period: { from: string; to: string }
  gap_min: number
  totals: {
    visits: number; fills: number; amount: number; liters: number
    multi_visits: number; multi_pct: number; fills_per_visit: number
    multi_fuel_visits: number; multi_fuel_pct: number
    avg_visit_check: number; avg_fill_check: number; avg_visit_liters: number
  }
  distribution: { fills: number; visits: number; amount: number; share_pct: number }[]
  /** Однотопливные приезды в разрезе продукта — чек приезда «за ДТ», а не средний. */
  by_fuel: {
    fuel_name: string; visits: number; amount: number; liters: number
    avg_visit_check: number; avg_visit_liters: number
  }[]
  by_station: {
    station_code: number; station: string; visits: number; fills: number
    multi: number; multi_pct: number; amount: number; avg_visit_check: number
  }[]
}

export async function getFuelVisits(p: Params & { gapMin?: number }): Promise<VisitsResponse> {
  return get<VisitsResponse>('/api/fuel/analytics/visits', {
    date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.gapMin ? { gap_min: String(p.gapMin) } : {}),
    ...narrow(p),
  })
}

// ─── Инсайты обзора ─────────────────────────────────────────────────────

export interface FuelInsight {
  key: string
  tone: 'info' | 'warning' | 'success'
  title: string
  text: string
  link?: { sub?: string }
}

export async function getFuelInsights(p: { companyId: string; dateFrom: string; dateTo: string }):
Promise<{ period: { from: string; to: string }; insights: FuelInsight[] }> {
  return get('/api/fuel/analytics/insights', { date_from: p.dateFrom, date_to: p.dateTo })
}
