/**
 * Клиент ABC-XYZ классификации станций ЭЗС.
 * ABC — вклад станции в результат сети (выручка/энергия), XYZ — стабильность
 * спроса (коэф. вариации по неделям/месяцам). Сервер: /analytics/charge-sessions/abc-xyz.
 */
import { get } from './apiClient'

export type AbcXyzMeasure = 'amount' | 'energy'
export type AbcXyzBucket = 'week' | 'month'

export interface AbcXyzStation {
  location_id: string
  name: string
  station_number: string | null
  region: string
  owner: string | null
  owner_cls: 'own' | 'partner' | 'unknown'
  owner_label: string
  measure: number
  share_pct: number
  cum_share_pct: number
  sessions: number
  energy_kwh: number
  amount: number
  active_buckets: number
  cv: number
  abc: 'A' | 'B' | 'C'
  xyz: 'X' | 'Y' | 'Z' | '—'
  class: string
}

export interface AbcXyzCell {
  abc: string
  xyz: string
  stations: number
  measure: number
  sessions: number
  share_pct: number
  hint: string
}

export interface AbcXyzGroup { stations: number; measure: number; share_pct: number }

export interface AbcXyzResponse {
  period: { from: string; to: string }
  measure: AbcXyzMeasure
  bucket: AbcXyzBucket
  n_buckets: number
  total_measure: number
  stations_total: number
  thresholds: { a_pct: number; b_pct: number; x_cv: number; y_cv: number }
  abc_labels: Record<string, string>
  xyz_labels: Record<string, string>
  cells: AbcXyzCell[]
  abc_summary: Record<string, AbcXyzGroup>
  xyz_summary: Record<string, AbcXyzGroup>
  core: AbcXyzGroup
  tail: AbcXyzGroup
  stations: AbcXyzStation[]
}

export async function getStationAbcXyz(p: {
  companyId: string; dateFrom: string; dateTo: string
  measure?: AbcXyzMeasure; bucket?: AbcXyzBucket
  stations?: string[]; regions?: string[]
}): Promise<AbcXyzResponse> {
  return get<AbcXyzResponse>('/api/analytics/charge-sessions/abc-xyz', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    measure: p.measure ?? 'amount', bucket: p.bucket ?? 'week',
    ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
    ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
  })
}
