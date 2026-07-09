/**
 * Клиент /api/metrika/* — коннектор Яндекс.Метрики. Токен хранится на бэке
 * (шифрованным) и наружу не отдаётся; фронт получает только статус и агрегаты.
 */
import { get, put, post, del } from './apiClient'

export interface MetrikaStatus {
  configured: boolean
  counter_id?: string
  counter_name?: string | null
  enabled?: boolean
  status?: string            // ok | error | unknown
  last_error?: string | null
  updated_at?: string | null
}
export interface MetrikaSummary {
  totals: {
    visits: number; users: number; pageviews: number; bounce_rate: number
    avg_duration_sec: number; page_depth: number; new_pct: number
  }
  sampled: boolean
  sample_share: number
  period: { from: string; to: string }
}
export interface MetrikaTsRow { date: string; visits: number; users: number; pageviews: number }
export interface MetrikaSourceRow { source: string; visits: number; users: number; bounce_rate: number }

const qp = (o: Record<string, string | undefined>) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(o)) if (v != null) u.set(k, v)
  return u.toString()
}

export const getMetrikaStatus = (companyId: string) =>
  get<MetrikaStatus>('/api/metrika/status', { company_id: companyId })

export const saveMetrikaConnection = (companyId: string, counter_id: string, token: string) =>
  put<MetrikaStatus>(`/api/metrika/connection?${qp({ company_id: companyId })}`, { counter_id, token })

export const deleteMetrikaConnection = (companyId: string) =>
  del(`/api/metrika/connection?${qp({ company_id: companyId })}`)

export const testMetrikaConnection = (companyId: string) =>
  post<{ ok: boolean; counter_name?: string; error?: string | null }>(`/api/metrika/test?${qp({ company_id: companyId })}`)

export const getMetrikaSummary = (companyId: string, date1 = '7daysAgo', date2 = 'today') =>
  get<MetrikaSummary>('/api/metrika/summary', { company_id: companyId, date1, date2 })

export const getMetrikaTimeseries = (companyId: string, date1 = '30daysAgo', date2 = 'today') =>
  get<{ rows: MetrikaTsRow[]; sampled: boolean }>('/api/metrika/timeseries', { company_id: companyId, date1, date2 })

export const getMetrikaSources = (companyId: string, date1 = '30daysAgo', date2 = 'today') =>
  get<{ rows: MetrikaSourceRow[] }>('/api/metrika/sources', { company_id: companyId, date1, date2 })
