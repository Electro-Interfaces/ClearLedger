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

type P = { companyId: string; dateFrom: string; dateTo: string }
const params = (p: P) => ({ company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo })

export const getRetailOverview = (p: P) => get<RetailOverview>('/api/retail/overview', params(p))
export const getRetailSegments = (p: P) => get<RetailSegmentsResponse>('/api/retail/segments', params(p))
export const getRetailEconomics = (p: P) => get<RetailEconomics>('/api/retail/economics', params(p))
export const getRetailGeo = (p: P) => get<RetailGeo>('/api/retail/geo', params(p))
export const getRetailCohorts = (p: { companyId: string; months?: number }) =>
  get<RetailCohorts>('/api/retail/cohorts', { company_id: p.companyId, months: p.months ?? 12 })
