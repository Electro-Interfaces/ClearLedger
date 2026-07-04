/**
 * Клиент API /api/corporate/* — корпоративное направление ЭЗС (ЮЛ):
 * реестр клиентов, KPI-обзор, рентабельность (розница vs договор), биллинг.
 */
import { get, getToken } from './apiClient'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

export interface CorpClient {
  name: string
  phone: string
  ext_id?: string | null
  mode: string                 // matrix | flat | retail
  rate?: number | null         // ставка для flat
  matrix?: Record<string, Record<string, number>> | null  // {регион: {CCS2,TYPE2,TYPE1}}
  contract_start?: string | null
  status?: string | null
  users?: number | null
  sessions: number
  energy_kwh: number
  corp_revenue: number         // договорная выручка
  retail_revenue: number       // розница-эквивалент (energy×tariff)
  discount: number             // corp − retail (<0 = скидка ЮЛ)
  discount_pct: number
  avg_tariff: number
  success_pct: number
}

export interface CorpTotals {
  clients: number
  active_clients: number
  sessions: number
  energy_kwh: number
  corp_revenue: number
  retail_revenue: number
  discount: number
  discount_pct: number
  avg_tariff: number
}

export interface CorpClientsResponse {
  period: { from: string; to: string }
  clients: CorpClient[]
  totals: CorpTotals
}

export interface CorpAlert { level: string; message: string }
export interface CorpOverviewResponse {
  period: { from: string; to: string }
  totals: CorpTotals
  top_clients: CorpClient[]
  alerts: CorpAlert[]
}

type P = { companyId: string; dateFrom: string; dateTo: string }
const params = (p: P) => ({ company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo })

export async function getCorporateOverview(p: P): Promise<CorpOverviewResponse> {
  return get<CorpOverviewResponse>('/api/corporate/overview', params(p))
}

export async function getCorporateClients(p: P): Promise<CorpClientsResponse> {
  return get<CorpClientsResponse>('/api/corporate/clients', params(p))
}

/**
 * Скачать реестр к выставлению под УПД (xlsx, 2 листа: Реестр + Детализация,
 * НДС выделен). Опц. фильтр по клиенту (один клиент = один УПД).
 */
export async function exportCorporateBillingUpd(p: P & { client?: string; vatRate?: number }): Promise<void> {
  const qs = new URLSearchParams({ company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo })
  if (p.client) qs.set('client', p.client)
  if (p.vatRate != null) qs.set('vat_rate', String(p.vatRate))
  const token = getToken()
  const res = await fetch(`${API_BASE}/api/corporate/billing-export?${qs.toString()}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error(`Выгрузка не удалась (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `billing_upd_${p.client ? 'client' : 'all'}_${p.dateFrom}_${p.dateTo}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
