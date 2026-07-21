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

type P = { companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[] }
/** Базовые query-параметры + контурное сужение сети (станции/регионы). */
const params = (p: P) => ({
  company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
  ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
})

export async function getCorporateOverview(p: P): Promise<CorpOverviewResponse> {
  return get<CorpOverviewResponse>('/api/corporate/overview', params(p))
}

export async function getCorporateClients(p: P): Promise<CorpClientsResponse> {
  return get<CorpClientsResponse>('/api/corporate/clients', params(p))
}

// ── карточка одного ЮЛ ────────────────────────────────────────────────
/** Месяц реализации. `partial` — период режет месяц по краю (18 дней из 31):
 *  такой месяц нельзя сравнивать с полным, поэтому у него нет и delta. */
export interface CorpMonth {
  month: string
  sessions: number
  energy_kwh: number
  corp_revenue: number
  retail_revenue: number
  discount: number
  avg_tariff: number
  drivers: number
  stations: number
  partial: boolean
  days_covered: number
  days_in_month: number
  revenue_delta_pct: number | null
}
export interface CorpBreakdown {
  label: string
  sessions: number
  energy_kwh: number
  corp_revenue: number
}
export interface CorpClientCard {
  client: string
  period: { from: string; to: string }
  /** Горизонт ряда `months`. Равен period, пока горизонт не расширен явно. */
  months_period: { from: string; to: string }
  history_months: number
  profile: {
    phone?: string | null; ext_id?: string | null; mode?: string | null
    rate?: number | null; matrix?: Record<string, Record<string, number>> | null
    contract_start?: string | null; status?: string | null
    users?: number | null; in_registry: boolean
  }
  totals: CorpClient
  averages: { avg_check: number; avg_kwh: number; sessions_per_month: number }
  months: CorpMonth[]
  stations: CorpBreakdown[]
  regions: CorpBreakdown[]
  connectors: CorpBreakdown[]
  drivers: CorpBreakdown[]
  when: { weekday: number; weekend: number; hours: { hour: number; sessions: number }[] }
  /** За всю историю, не за период: «клиент с нами с…» и «последняя зарядка…». */
  lifetime: { first_session: string | null; last_session: string | null; sessions: number; corp_revenue: number }
}

export async function getCorporateClientCard(
  p: P & { client: string; historyMonths?: number; tz?: 'msk' | 'local' },
): Promise<CorpClientCard> {
  return get<CorpClientCard>('/api/corporate/client-card', {
    ...params(p), client: p.client, history_months: p.historyMonths ?? 0,
    ...(p.tz ? { tz: p.tz } : {}),
  })
}

/**
 * Скачать реестр к выставлению под УПД (xlsx, 2 листа: Реестр + Детализация,
 * НДС выделен). Опц. фильтр по клиенту (один клиент = один УПД).
 */
export async function exportCorporateBillingUpd(p: P & { client?: string; vatRate?: number }): Promise<void> {
  const qs = new URLSearchParams({ company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo })
  if (p.client) qs.set('client', p.client)
  if (p.vatRate != null) qs.set('vat_rate', String(p.vatRate))
  if (p.stations?.length) qs.set('stations', p.stations.join(','))
  if (p.regions?.length) qs.set('regions', p.regions.join(','))
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
