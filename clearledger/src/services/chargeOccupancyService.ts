import { get } from './apiClient'

export type OccupancyGroup = 'auto' | 'station' | 'connector'
export interface HourlyPoint {
  hour: number
  occupied_minutes: number
  available_minutes: number
  occupancy_pct: number
  starts: number
}
export interface PhysicalConnector {
  id: string
  label: string
  station_id: string
  station_code: string
  station_name: string
  connector_no: string
  connector_type: string | null
}
export interface OccupancySeries extends Omit<PhysicalConnector, 'connector_no'> {
  connector_no: string | null
  points: HourlyPoint[]
}
export interface HourlyOccupancyResponse {
  group_by: 'station' | 'connector'
  tz: 'msk' | 'local'
  period: { from: string; to: string }
  hours: number[]
  series: OccupancySeries[]
  connectors: PhysicalConnector[]
  /** Все известные типы в контуре, в том числе у сессий без номера порта. */
  connector_types?: string[]
  quality: {
    missing_interval_sessions: number
    missing_connector_sessions: number
    unmapped_station_sessions: number
    last_session_at: string | null
  }
}
export interface OccupancyScope {
  stations?: string[]
  regions?: string[]
  dim?: string
  dimVal?: string
}

/** Контракт требует все часы. Неполный ряд нельзя молча дорисовать нулями. */
export async function getHourlyOccupancy(p: OccupancyScope & {
  companyId: string; dateFrom: string; dateTo: string
  tz: 'msk' | 'local'; groupBy: OccupancyGroup
  connectorTypes: string[]; connectorIds: string[]
}): Promise<HourlyOccupancyResponse> {
  const data = await get<HourlyOccupancyResponse>('/api/analytics/charge-sessions/hourly-occupancy', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    tz: p.tz, group_by: p.groupBy,
    stations: p.stations?.length ? p.stations.join(',') : undefined,
    regions: p.regions?.length ? p.regions.join(',') : undefined,
    ...(p.dim && p.dimVal != null ? { dim: p.dim, dim_val: p.dimVal } : {}),
    connector_types: p.connectorTypes.length ? p.connectorTypes.join(',') : undefined,
    connector_ids: p.connectorIds.length ? JSON.stringify(p.connectorIds) : undefined,
  })
  const completeHours = (hours: number[]) => hours.length === 24 && new Set(hours).size === 24
    && hours.every(h => Number.isInteger(h) && h >= 0 && h <= 23)
  if (!Array.isArray(data?.hours) || !completeHours(data.hours)
    || !Array.isArray(data.series) || !Array.isArray(data.connectors) || !data.quality
    || !['station', 'connector'].includes(data.group_by) || data.tz !== p.tz
    || ![data.quality.missing_interval_sessions, data.quality.missing_connector_sessions, data.quality.unmapped_station_sessions].every(n => Number.isInteger(n) && n >= 0)
    || data.series.some(s => !Array.isArray(s.points) || !completeHours(s.points.map(p => p.hour))
      || s.points.some(p => ![p.occupied_minutes, p.available_minutes, p.occupancy_pct, p.starts].every(Number.isFinite)
        || p.occupancy_pct < 0 || p.occupancy_pct > 100 || p.starts < 0
        || p.available_minutes < 0 || p.occupied_minutes < 0 || p.occupied_minutes > p.available_minutes))) {
    throw new Error('Сервис вернул неполные или некорректные почасовые данные. Повторите запрос.')
  }
  return data
}

export function occupancySeriesLabel(s: Omit<OccupancySeries, 'points'>): string {
  const station = [s.station_code, s.station_name].filter(Boolean).join(' · ') || s.label
  return s.connector_no == null ? station
    : `${station} · порт ${s.connector_no} · ${s.connector_type || 'тип не указан'}`
}
