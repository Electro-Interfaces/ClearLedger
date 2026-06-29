/**
 * Онлайн-заказы агрегаторов (MSTO) — журнал канала «Онлайн-заказы».
 * Загруженные заказы из БД (online_orders), с резолвом станции и канона топлива.
 */
import { get } from '@/services/apiClient'

export interface LoadedOnlineOrder {
  id: string
  external_id: string
  station_id: string | null
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

export const getLoadedOnlineOrders = () =>
  get<LoadedOnlineOrder[]>('/api/online-orders')

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
