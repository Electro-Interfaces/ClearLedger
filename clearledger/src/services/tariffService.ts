/**
 * Клиент API /api/tariffs/* — тарифная аналитика ЭЗС (ценообразование, розница):
 * прайс-сетка регион×коннектор + факт vs номинал.
 */
import { get } from './apiClient'

export interface TariffGridCell {
  row: string           // регион или станция (в зависимости от by)
  connector: string
  sessions: number
  energy_kwh: number
  tariff: number        // преобладающий (mode)
  tariff_min: number
  tariff_max: number
  varies: boolean
  realized: number      // факт ₽/кВтч (выручка÷энергия)
}
export interface TariffGridResponse {
  period: { from: string; to: string }
  by: string            // region | station
  rows: string[]        // строки сетки (регионы или станции)
  connectors: string[]
  cells: TariffGridCell[]
}

export interface FvnLine {
  label: string
  sessions: number
  energy_kwh: number
  nominal: number       // энерговзвеш. tariff (номинал/прайс)
  realized: number      // выручка÷энергия (факт)
  delta: number         // факт − номинал (<0 = скидка)
  delta_pct: number
}
export interface FvnResponse {
  period: { from: string; to: string }
  group_by: string
  lines: FvnLine[]
  totals: { energy_kwh: number; nominal: number; realized: number; delta: number }
}

type P = { companyId: string; dateFrom: string; dateTo: string; userType?: string; stations?: string[]; regions?: string[] }
function qp(p: P): Record<string, string> {
  const o: Record<string, string> = { company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo }
  if (p.userType) o.user_type = p.userType
  if (p.stations?.length) o.stations = p.stations.join(',')
  if (p.regions?.length) o.regions = p.regions.join(',')
  return o
}

export async function getTariffGrid(p: P & { by?: string }): Promise<TariffGridResponse> {
  return get<TariffGridResponse>('/api/tariffs/grid', { ...qp(p), ...(p.by ? { by: p.by } : {}) })
}

export async function getFactVsNominal(p: P & { groupBy: string }): Promise<FvnResponse> {
  return get<FvnResponse>('/api/tariffs/fact-vs-nominal', { ...qp(p), group_by: p.groupBy })
}
