/**
 * Клиент API /api/retail/* — розничное направление ЭЗС (ФЛ): аналитика в разрезе
 * аккаунтов частных лиц. Телефоны псевдонимизированы на бэке (хеш-ID + маска).
 */
import { get } from './apiClient'

export interface RetailTotals {
  accounts: number
  new_accounts: number
  sessions: number
  energy_kwh: number
  revenue: number
  arpa: number
  avg_sessions: number
  avg_check: number
  avg_tariff: number
}
export interface RetailOverview {
  period: { from: string; to: string }
  totals: RetailTotals
}

export interface RetailSegment {
  segment: string
  accounts: number
  sessions: number
  energy_kwh: number
  revenue: number
  revenue_pct: number
  avg_check: number
}
export interface RetailSegmentsResponse {
  period: { from: string; to: string }
  segments: RetailSegment[]
  totals: { accounts: number }
  thresholds?: { recency: number[]; frequency: number[] }
}

export interface ParetoPoint { top_pct: number; accounts: number; revenue_pct: number }
export interface SessionBucket { bucket: string; accounts: number; accounts_pct: number; revenue: number; revenue_pct: number }
export interface RetailEconomics {
  period: { from: string; to: string }
  pareto: ParetoPoint[]
  session_buckets: SessionBucket[]
  totals: { accounts: number; revenue: number; arpa: number }
}

export interface MobilityBucket { bucket: string; accounts: number; accounts_pct: number; revenue: number }
export interface RetailRegion { region: string; accounts: number; sessions: number; revenue: number }
export interface GeoCoverage {
  sessions_total: number
  sessions_resolved: number
  sessions_orphan: number
  resolved_pct: number
  revenue_orphan: number
  orphan_revenue_pct: number
}
export interface RetailGeo {
  period: { from: string; to: string }
  mobility: MobilityBucket[]
  avg_stations: number
  coverage: GeoCoverage
  regions: RetailRegion[]
  totals: { accounts: number }
}

export interface CohortRow {
  cohort: string
  size: number
  retention: { offset: number; count: number; pct: number }[]
}
export interface RetailCohorts { cohorts: CohortRow[]; max_offset: number }

export interface RetailAccount {
  account: string
  masked: string
  segment: string
  sessions: number
  energy_kwh: number
  revenue: number
  avg_check: number
  avg_kwh: number
  avg_tariff: number
  first_at: string | null
  last_at: string | null
  recency_days: number | null
  success_pct: number
  stations: number
  regions: number
}
export interface RetailAccountsResponse {
  period: { from: string; to: string }
  accounts: RetailAccount[]
  total: number
  returned: number
  totals: { accounts: number; sessions: number; revenue: number; energy_kwh: number; avg_check: number; arpa: number }
}

export interface DimRegion { region: string; accounts: number; sessions: number }
export interface DimStation { location_id: string; name: string; number: string | null; region: string | null; accounts: number; sessions: number }
export interface RetailDimensions { regions: DimRegion[]; stations: DimStation[] }

export interface HourBucket { hour: number; sessions: number; revenue: number }
export interface WeekdayBucket { dow: number; label: string; sessions: number; revenue: number }
export interface RetailProfile {
  period: { from: string; to: string }
  scope: { kind: string | null; label: string; value?: string; number?: string | null }
  totals: { accounts: number; sessions: number; revenue: number; energy_kwh: number; avg_check: number; avg_kwh: number }
  hourly: HourBucket[]
  weekday: WeekdayBucket[]
  top_accounts: RetailAccount[]
}

type P = { companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[] }
/** Базовые query-параметры + контурное сужение сети (станции/регионы). */
const params = (p: P) => ({
  company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
  ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
})

export const getRetailOverview = (p: P) => get<RetailOverview>('/api/retail/overview', params(p))
export const getRetailSegments = (p: P) => get<RetailSegmentsResponse>('/api/retail/segments', params(p))
export const getRetailEconomics = (p: P) => get<RetailEconomics>('/api/retail/economics', params(p))
export const getRetailGeo = (p: P) => get<RetailGeo>('/api/retail/geo', params(p))
export const getRetailCohorts = (p: { companyId: string; months?: number; stations?: string[]; regions?: string[] }) =>
  get<RetailCohorts>('/api/retail/cohorts', {
    company_id: p.companyId, months: p.months ?? 12,
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })

export interface AccountsParams extends P {
  region?: string; station?: string; segment?: string
  minSessions?: number; search?: string; sort?: string; order?: string; limit?: number
}
export function getRetailAccounts(p: AccountsParams): Promise<RetailAccountsResponse> {
  const q: Record<string, string> = { company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo }
  if (p.stations?.length) q.stations = p.stations.join(',')
  if (p.regions?.length) q.regions = p.regions.join(',')
  if (p.region) q.region = p.region
  if (p.station) q.station = p.station
  if (p.segment) q.segment = p.segment
  if (p.minSessions) q.min_sessions = String(p.minSessions)
  if (p.search) q.search = p.search
  if (p.sort) q.sort = p.sort
  if (p.order) q.order = p.order
  if (p.limit) q.limit = String(p.limit)
  return get<RetailAccountsResponse>('/api/retail/accounts', q)
}

export const getRetailDimensions = (p: P) => get<RetailDimensions>('/api/retail/dimensions', params(p))

export function getRetailProfile(p: P & { station?: string; region?: string; tz?: 'msk' | 'local' }): Promise<RetailProfile> {
  const q: Record<string, string> = { company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo }
  if (p.stations?.length) q.stations = p.stations.join(',')
  if (p.regions?.length) q.regions = p.regions.join(',')
  if (p.station) q.station = p.station
  if (p.region) q.region = p.region
  if (p.tz) q.tz = p.tz
  return get<RetailProfile>('/api/retail/profile', q)
}

export interface AccountStation { name: string; number: string | null; sessions: number; revenue: number; energy_kwh: number }
export interface AccountMonth { month: string; sessions: number; revenue: number }
export interface AccountConnector { type: string; sessions: number }
export interface AccountSession { started_at: string | null; station: string | null; connector: string | null; energy_kwh: number; amount: number; result: string | null }
export interface RetailAccountDetail {
  found: boolean
  period?: { from: string; to: string }
  account?: RetailAccount
  by_station?: AccountStation[]
  by_month?: AccountMonth[]
  hourly?: { hour: number; sessions: number }[]
  connectors?: AccountConnector[]
  recent?: AccountSession[]
}
export function getRetailAccount(p: P & { account: string }): Promise<RetailAccountDetail> {
  return get<RetailAccountDetail>('/api/retail/account', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo, account: p.account,
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })
}

export interface MarketingKpis {
  accounts: number; new_accounts: number; returning_accounts: number; new_share: number
  repeat_rate: number; one_time_share: number; one_time_revenue_share: number
  aov: number; frequency: number; arpa: number
  core_accounts_share: number; core_revenue_share: number
  risk_accounts_share: number; risk_revenue: number; risk_revenue_share: number
  top10_revenue_share: number; top20_revenue_share: number
  retention_m1: number | null; retention_m3: number | null
}
export interface MarketingInsight { level: string; text: string }
export interface RetailMarketing { period: { from: string; to: string }; kpis: Partial<MarketingKpis>; insights: MarketingInsight[] }
export const getRetailMarketing = (p: P) => get<RetailMarketing>('/api/retail/marketing', params(p))

export interface DashDelta { cur: number; prev: number; delta_pct: number | null }
export interface DashDynamics { month: string; new: number; returning: number; reactivated: number; active: number; revenue: number }
export interface RetentionPoint { offset: number; pct: number | null }
export interface ClvSegment { segment: string; accounts: number; monthly_arpu: number; ltv: number }
export interface DashClv { monthly_arpu: number; expected_months: number; ltv: number; avg_lifetime_months: number; by_segment: ClvSegment[] }
export interface HeatCell { dow: number; hour: number; sessions: number }
export interface DashConnector { type: string; sessions: number; revenue: number }
export interface DashPayment { rfid_pct: number; app_pct: number; unpaid_pct: number }
export interface DashSuccess { pct: number; by_month: { month: string; pct: number }[] }
export interface LorenzPoint { pop: number; rev: number }
export interface DistBucket { bucket: string; accounts: number; accounts_pct: number }
export interface DashConcentration { gini: number; lorenz: LorenzPoint[]; session_buckets: DistBucket[]; spend_buckets: DistBucket[] }
export interface RetailDashboard {
  period: { from: string; to: string }
  dynamics: DashDynamics[]
  deltas: Record<string, DashDelta>
  retention_curve: RetentionPoint[]
  clv: DashClv
  heatmap: HeatCell[]
  connectors: DashConnector[]
  payment: DashPayment
  success: DashSuccess
  concentration: DashConcentration
}
export const getRetailDashboard = (p: P) => get<RetailDashboard>('/api/retail/dashboard', params(p))
