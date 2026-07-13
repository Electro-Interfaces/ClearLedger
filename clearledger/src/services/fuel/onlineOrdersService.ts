/**
 * Онлайн-заказы агрегаторов (MSTO) — журнал канала «Онлайн-заказы».
 * Загруженные заказы из БД (online_orders), с резолвом станции и канона топлива.
 */
import { get, post } from '@/services/apiClient'

export interface LoadedOnlineOrder {
  id: string
  external_id: string
  station_id: string | null
  station_code: number | null
  station_name: string | null
  service_point_id: number | null
  service_point_name: string | null
  post_number: number | null
  aggregator: string | null
  fuel_name: string | null
  fuel_code: number | null
  order_date: string | null
  ordered_sum: number
  ordered_volume: number
  actual_sum: number
  actual_volume: number
  operation_result: string | null
  created_at: string | null
}

export interface OnlineOrdersQuery {
  companyId?: string
  dateFrom?: string
  dateTo?: string
  stationCode?: string
  limit?: number
}

export const getLoadedOnlineOrders = (query: OnlineOrdersQuery = {}) =>
  get<LoadedOnlineOrder[]>('/api/online-orders', {
    company_id: query.companyId,
    date_from: query.dateFrom,
    date_to: query.dateTo,
    station_code: query.stationCode && query.stationCode !== 'all' ? query.stationCode : undefined,
    limit: query.limit ?? 5000,
  })

export interface OnlineOrdersRefreshResult {
  created: number
  updated?: number
  fetched: number
  warning?: string
  mode?: 'full' | 'incremental'
  date_from?: string
  date_to?: string
}

export const refreshOnlineOrders = (query: OnlineOrdersQuery = {}) => {
  const qs = new URLSearchParams()
  if (query.companyId) qs.set('company_id', query.companyId)
  if (query.dateFrom) qs.set('date_from', query.dateFrom)
  if (query.dateTo) qs.set('date_to', query.dateTo)
  if (query.stationCode && query.stationCode !== 'all') qs.set('station_code', query.stationCode)
  return post<OnlineOrdersRefreshResult>(`/api/online-orders/refresh${qs.size ? `?${qs}` : ''}`)
}

/** Результат проверки доступности данных MSTO (без сохранения). */
export interface OnlineOrdersCheck {
  available: boolean
  service_points?: number
  orders?: number
  period?: [string, string]
  aggregators?: Record<string, number>
  error?: string
}

/** Проверить, что MSTO на связи и отдаёт онлайн-заказы за период (probe, не грузит). */
export const checkOnlineOrders = (dateFrom?: string, dateTo?: string) => {
  const qs = new URLSearchParams()
  if (dateFrom) qs.set('date_from', dateFrom)
  if (dateTo) qs.set('date_to', dateTo)
  const q = qs.toString()
  return get<OnlineOrdersCheck>(`/api/online-orders/check${q ? `?${q}` : ''}`)
}
