/**
 * Клиент API /api/netservice/* — Сервисный центр (3-я линия HubEx, MVP).
 * Аналитика читает синхронизированные в Postgres данные (синк — POST hubex/sync).
 */
import { get, post } from './apiClient'

export interface NetCapabilities {
  hubex: boolean
  line1: boolean
  line2: boolean
  assetsLinked: number
}

export interface NameN { name: string; n: number }
export interface NetHealthKpi { total: number; open: number; overdue: number; unassigned: number }
export interface NetPoint {
  id: string; number: string; name: string; status: string
  color: string | null; lat: number; lng: number
}
export interface NetworkHealth {
  kpi: NetHealthKpi
  funnel: { stage: string; n: number }[]
  byType: NameN[]
  byCriticality: { name: string; color: string | null; n: number }[]
  byRegion: NameN[]
  points: NetPoint[]
}

export interface SlaRow {
  name?: string
  total: number
  completed: number
  slaPct: number | null
  avgReactionSec: number | null
  avgWorkSec: number | null
  p50WorkSec: number | null
  p90WorkSec: number | null
}
export interface SlaResponse {
  period: { from: string; to: string }
  breakdown: string
  totals: SlaRow
  rows: SlaRow[]
}

export interface AssetReliability {
  period: { from: string; to: string }
  topProblematic: {
    asset_id: number; asset_name: string; location_id: string | null
    total: number; incidents: number
  }[]
  byWorkType: NameN[]
}

export interface TaskRow {
  hubex_id: string; number: string
  status: string; status_color: string | null
  stage: string; task_type: string; work_type: string
  criticality: string; criticality_color: string | null
  asset_id: number; asset_name: string; location_id: string | null
  contractor_company: string; assignee: string
  ts_created: string | null; ts_deadline: string | null; ts_closed: string | null
  is_overdue: boolean
}
export interface TasksResponse { total: number; rows: TaskRow[] }

/** Разрезы раздела (период + ось фильтрации). */
export interface NetFilters {
  dateFrom?: string
  dateTo?: string
  region?: string  // название региона (= ServiceLocation.metadata.federalSubject)
  locationId?: string
  locationType?: string
  contractor?: string
}

function p(companyId: string, f?: NetFilters): Record<string, string | number | undefined> {
  return {
    company_id: companyId,
    date_from: f?.dateFrom,
    date_to: f?.dateTo,
    region: f?.region,
    location_id: f?.locationId,
    location_type: f?.locationType,
    contractor: f?.contractor,
  }
}

export async function getCapabilities(companyId: string): Promise<NetCapabilities> {
  return get<NetCapabilities>('/api/netservice/capabilities', { company_id: companyId })
}

export async function getNetworkHealth(companyId: string, f?: NetFilters): Promise<NetworkHealth> {
  return get<NetworkHealth>('/api/netservice/analytics/network-health', p(companyId, f))
}

export async function getSla(
  companyId: string, f?: NetFilters, breakdown: string = 'criticality',
): Promise<SlaResponse> {
  return get<SlaResponse>('/api/netservice/analytics/sla', { ...p(companyId, f), breakdown })
}

export async function getAssetReliability(
  companyId: string, f?: NetFilters, top: number = 10,
): Promise<AssetReliability> {
  return get<AssetReliability>('/api/netservice/analytics/asset-reliability', { ...p(companyId, f), top })
}

export async function getTasks(
  companyId: string,
  opts: NetFilters & { status?: string; q?: string; limit?: number; offset?: number } = {},
): Promise<TasksResponse> {
  return get<TasksResponse>('/api/netservice/tasks', {
    ...p(companyId, opts),
    status: opts.status, q: opts.q, limit: opts.limit, offset: opts.offset,
  })
}

export async function runHubexSync(companyId: string): Promise<unknown> {
  return post(`/api/netservice/hubex/sync?company_id=${encodeURIComponent(companyId)}`)
}
