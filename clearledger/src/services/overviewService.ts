/**
 * Клиент API /api/analytics/charge-sessions/overview — executive-дашборд сети ЭЗС.
 * Один запрос: KPI с Δ% к прошлому периоду + спарклайны, гейджи, тренд с оверлеем,
 * доли, топ/дно станций, корпоратив, алерты, meta. Дельты считает сервер.
 */
import { get } from './apiClient'

export type KpiFmt = 'moneyShort' | 'money' | 'int' | 'kwh' | 'pct' | 'price'
export type Accent = 'success' | 'warning' | 'danger' | 'info'
export type DeltaDir = 'up' | 'down' | 'flat'

export interface OverviewKpi {
  key: string
  label: string
  value: number
  prev: number
  fmt: KpiFmt
  unit: string
  delta_pct: number | null
  dir: DeltaDir
  spark?: (number | null)[]
  accent?: Accent
  good: 'higher' | 'lower'
}

export interface OverviewGauge {
  key: string
  label: string
  value: number        // %
  unit: string
  accent: Accent
  hint?: string
}

export interface TrendPoint {
  label: string
  current: number | null
  previous: number | null
}
export interface OverviewTrend {
  bucket: string
  points: TrendPoint[]
}

export interface ShareRow {
  label: string
  amount: number
  sessions: number
  energy_kwh?: number
  share_pct: number
}
export interface OverviewShares {
  connector: ShareRow[]
  /** Каноническая сегментация: Корпоратив (ЮЛ) / Розница (ФЛ) / Анонимные.
   * Согласована с панелями «Корпоратив» и «Частные лица». */
  by_segment: ShareRow[]
}

export interface StationRow {
  label: string
  sessions: number
  energy_kwh: number
  amount: number
  utilization_pct: number
  success_pct: number
  throughput_port: number
}
export interface OverviewStations {
  top: StationRow[]
  bottom: StationRow[]
  by_revenue: StationRow[]
  qualified: number
  min_sessions: number
}

export interface CorpTopClient {
  name: string
  corp_revenue: number
  retail_revenue: number
  discount_pct: number
  sessions: number
  energy_kwh: number
  avg_tariff: number
}
export interface OverviewCorporate {
  corp_revenue: number
  retail_revenue: number
  discount: number
  discount_pct: number
  active_clients: number
  clients: number
  corp_share_pct: number
  top_clients: CorpTopClient[]
}

export interface HourPoint { hour: number; label: string; sessions: number; amount: number }
export interface WeekdayPoint { weekday: number; label: string; amount: number; sessions: number; energy_kwh: number }
export interface OverviewWeekday { days: WeekdayPoint[]; best: number | null; worst: number | null }

export interface OverviewAlert { level: string; message: string }
export interface OverviewMeta { active_stations: number; ports: number; sessions: number }

/** Состояние сети: не «сколько заработали», а «что с активом». Простаивающие
 * станции, концентрация выручки, ядро клиентов, регионы, сходимость с реестрами
 * и деньги, застрявшие между отпуском и счётом. */
export interface OverviewNetwork {
  silent: {
    silent: number; never_worked: number; went_quiet: number
    total: number; silent_pct: number
  }
  concentration: {
    bucket: number; label: string; stations: number
    revenue: number; visits: number; avg_per_station: number; share_pct: number
  }[]
  segments: {
    tiers: { tier: number; label: string; clients: number; revenue: number; visits: number; rev_share: number; client_share: number }[]
    clients: number
    core_clients: number; core_rev_share: number
    once_clients: number; once_rev_share: number
  }
  regions: {
    top_revenue: { label: string; visits: number; charged: number; revenue: number; success_pct: number }[]
    worst_success: { label: string; visits: number; charged: number; revenue: number; success_pct: number }[]
    regions: number
  }
  energy_recon: {
    months: {
      period: string; session_kwh: number; registry_kwh: number
      diff_kwh: number; diff_pct: number | null
      coverage_pct: number | null; incomplete: boolean
      /** Продажа (отпуск сессий) > закупки (вход по счётчикам) — физ. аномалия. */
      anomaly: boolean
    }[]
    session_kwh: number; registry_kwh: number; diff_kwh: number; diff_pct: number | null
    /** Месяцы, где реестр недогружен — их не сверяют, а дозагружают. */
    incomplete_months: string[]
    /** Месяцы «продажа > закупка» — физически невозможно, требует разбора. */
    anomaly_months: string[]
    has_anomaly: boolean
    compared_months: number
  } | null
  receivable: {
    amount: number; sessions: number; kwh: number
    retail_debt: number; retail_debt_sessions: number
  }
  run_rate: {
    days_done: number; days_in_month: number
    projected_revenue: number; current_revenue: number
  } | null
}

/** Станция парка без сессий за период — раскрывается с карточки «Молчат». */
export interface SilentStation {
  id: string; code: string; name: string; city: string | null
  operational_status: string | null
  last_at: string | null
  sessions_ever: number
}
export interface SilentStationsResponse {
  stations: SilentStation[]
  silent: number; never_worked: number; went_quiet: number
  total: number; silent_pct: number
}
export async function getSilentStations(p: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[]
}): Promise<SilentStationsResponse> {
  return get<SilentStationsResponse>('/api/analytics/charge-sessions/overview/silent-stations', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })
}

/** Парк по владельцу: свои (РусГидро) vs партнёрские (СНК) — простой, сессии, надёжность. */
export interface OwnerBreakdownRow {
  cls: 'own' | 'partner' | 'unknown'
  label: string
  stations: number
  working: number
  active: number
  silent: number
  silent_pct: number
  sessions: number
  energy_kwh: number
  amount: number
  visits: number
  charged: number
  success_pct: number
}
export interface OwnersResponse {
  period: { from: string; to: string }
  owners: OwnerBreakdownRow[]
}
export async function getOwnersBreakdown(p: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[]
}): Promise<OwnersResponse> {
  return get<OwnersResponse>('/api/analytics/charge-sessions/owners', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })
}

/** Станция во списке владельца (раскрытие карточки «Парк по владельцу»). */
export interface OwnerStation {
  id: string
  code: string
  name: string
  city: string | null
  owner: string | null
  operational_status: string | null
  sessions: number
  energy_kwh: number
  amount: number
  success_pct: number | null
  last_at: string | null
}
export interface OwnerStationsResponse {
  period: { from: string; to: string }
  cls: 'own' | 'partner' | 'unknown'
  label: string
  total: number
  active: number
  silent: number
  stations: OwnerStation[]
}
export async function getOwnerStations(p: {
  companyId: string; dateFrom: string; dateTo: string; cls: 'own' | 'partner' | 'unknown'
}): Promise<OwnerStationsResponse> {
  return get<OwnerStationsResponse>('/api/analytics/charge-sessions/owners/stations', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo, cls: p.cls,
  })
}

/** Качество использования портов: занятость ≠ работа.
 * idle — порт занят, но не заряжает; считается только по быстрым (DC) портам,
 * где 3 кВт означают проблему, а не паспортную скорость. */
export interface PortEfficiencyResponse {
  thresholds: { idle_kw: number; idle_min: number; dc_connectors: string[] }
  totals: {
    sessions: number; port_hours: number; dc_port_hours: number
    idle_sessions: number; idle_hours: number; idle_time_pct: number
    kwh: number; median_min: number
  }
  connectors: {
    label: string; is_dc: boolean; sessions: number
    median_kw: number | null; p90_kw: number | null; median_min: number
    idle_sessions: number; idle_hours: number; port_hours: number
    kwh: number; idle_time_pct: number | null
  }[]
  stations: {
    label: string; station_code: string; idle_sessions: number
    idle_hours: number; dc_port_hours: number; median_kw: number | null
    idle_time_pct: number
  }[]
  bands: { band: number; label: string; sessions: number; port_hours: number; kwh: number }[]
}
export async function getPortEfficiency(p: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[]
}): Promise<PortEfficiencyResponse> {
  return get<PortEfficiencyResponse>('/api/analytics/charge-sessions/port-efficiency', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })
}

export interface OverviewResponse {
  period: { from: string; to: string }
  prev_period: { from: string; to: string }
  has_baseline: boolean
  compare: string
  period_days: number
  kpis: OverviewKpi[]
  gauges: OverviewGauge[]
  trend: OverviewTrend
  shares: OverviewShares
  stations: OverviewStations
  hourly: HourPoint[]
  weekday: OverviewWeekday
  corporate: OverviewCorporate
  alerts: OverviewAlert[]
  network: OverviewNetwork
  meta: OverviewMeta
}

export async function getChargeOverview(p: {
  companyId: string; dateFrom: string; dateTo: string; compare?: string
  stations?: string[]; regions?: string[]; tz?: 'msk' | 'local'
}): Promise<OverviewResponse> {
  return get<OverviewResponse>('/api/analytics/charge-sessions/overview', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    compare: p.compare ?? 'prev',
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
    ...(p.tz ? { tz: p.tz } : {}),
  })
}

// ─── метрики сессий по станции (для раскраски/размера точек на «Карте») ───
export interface StationMetric {
  location_id: string
  sessions: number
  energy_kwh: number
  amount: number
  success_pct: number
  utilization_pct: number
}
export interface StationMetricsResponse {
  period: { from: string; to: string }
  metrics: StationMetric[]
}
/** Агрегаты сессий по станции (location_id) за период — джойнится на фронте по id локации. */
export async function getStationMetrics(p: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[]
}): Promise<StationMetricsResponse> {
  return get<StationMetricsResponse>('/api/analytics/charge-sessions/station-metrics', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })
}
