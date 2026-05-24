/**
 * Клиент API /api/analytics/* — 4 группы:
 *   management — pnl, paymentMix
 *   financial  — cashFlow, payablesReceivables
 *   tax        — vat, profit
 *   forecast   — monthForecast
 *
 * Все методы принимают периодные параметры в ISO (YYYY-MM-DD).
 */

import { get } from './apiClient'

// ─── общие типы ─────────────────────────────────────────────────────

export interface PnLLine {
  label: string
  revenue: number
  revenue_net: number
  cogs: number
  gross_margin: number
  gross_margin_pct: number
  docs_count: number
  liters: number
}

export interface PnLResponse {
  period: { from: string; to: string }
  group_by: 'station' | 'fuel' | 'month'
  lines: PnLLine[]
  totals: PnLLine
  ptu_count: number
  shifts_count: number
}

export interface PaymentMixResponse {
  period: { from: string; to: string }
  shifts_count: number
  total_amount: number
  avg_per_shift: number
  breakdown: { cash: number; card: number; voucher: number; other: number }
  shares_pct: { cash: number; card: number; voucher: number; other: number }
}

export interface CashFlowAccountRow {
  account: string
  name: string
  debit: number
  credit: number
  net: number
}

export interface CashFlowResponse {
  period: { from: string; to: string }
  accounts: CashFlowAccountRow[]
  inflow_total: number
  outflow_total: number
  net_total: number
}

export interface ContragentBalance {
  counterparty: string
  inn: string | null
  debit: number
  credit: number
  balance: number
}

export interface PayablesReceivablesResponse {
  period: { from: string; to: string }
  payables: ContragentBalance[]
  receivables: ContragentBalance[]
  totals: { payables_balance: number; receivables_balance: number }
}

export interface VatResponse {
  period: { from: string; to: string }
  output_vat: number
  input_vat: number
  payable: number
  revenue_with_vat: number
  revenue_net: number
  effective_rate_pct: number
}

export interface ProfitResponse {
  period: { from: string; to: string }
  revenue_net: number
  cogs: number
  vat_output: number
  sga: number
  other_income: number
  other_expenses: number
  profit_before_tax: number
  tax_rate_pct: number
  tax_estimated: number
  net_profit: number
}

export interface MissingDoc {
  type: string
  reason: string
  count: number
  amount: number
}

export interface Risk {
  severity: 'info' | 'warn' | 'critical'
  type: string
  message: string
}

export interface MonthForecastResponse {
  year: number
  month: number
  days_total: number
  days_elapsed: number
  daily_avg_revenue: number
  revenue: { fact: number; projected: number }
  margin: { fact: number; projected: number }
  vat_payable: { fact: number; projected: number }
  missing_docs: MissingDoc[]
  risks: Risk[]
  period_closed: boolean
}

// ─── API methods ────────────────────────────────────────────────────

export interface PeriodParams {
  companyId: string
  dateFrom: string
  dateTo: string
  stationId?: string
}

export async function getPnL(p: PeriodParams & { groupBy?: 'station' | 'fuel' | 'month' }): Promise<PnLResponse> {
  return get<PnLResponse>('/api/analytics/pnl', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    group_by: p.groupBy ?? 'station',
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

export async function getPaymentMix(p: PeriodParams): Promise<PaymentMixResponse> {
  return get<PaymentMixResponse>('/api/analytics/payment-mix', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

export async function getCashFlow(p: PeriodParams): Promise<CashFlowResponse> {
  return get<CashFlowResponse>('/api/analytics/cash-flow', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getPayablesReceivables(p: PeriodParams): Promise<PayablesReceivablesResponse> {
  return get<PayablesReceivablesResponse>('/api/analytics/payables-receivables', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getVat(p: PeriodParams): Promise<VatResponse> {
  return get<VatResponse>('/api/analytics/vat', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getProfit(p: PeriodParams): Promise<ProfitResponse> {
  return get<ProfitResponse>('/api/analytics/profit', {
    company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  })
}

export async function getMonthForecast(p: { companyId: string; year: number; month: number; stationId?: string }): Promise<MonthForecastResponse> {
  return get<MonthForecastResponse>('/api/analytics/forecast/month', {
    company_id: p.companyId, year: p.year, month: p.month,
    ...(p.stationId ? { station_id: p.stationId } : {}),
  })
}

// ─── вспомогательные форматтеры для UI ──────────────────────────────

export function fmtMoney(n: number): string {
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)
}

export function fmtMoneyShort(n: number): string {
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' млрд'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' млн'
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' тыс'
  return fmtMoney(n)
}

export function fmtLiters(n: number): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n) + ' л'
}

export function fmtPct(n: number): string {
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

export function currentMonthBounds(): { from: string; to: string; year: number; month: number } {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth() + 1
  const first = new Date(y, m - 1, 1)
  const last = new Date(y, m, 0)
  return {
    from: first.toISOString().slice(0, 10),
    to: last.toISOString().slice(0, 10),
    year: y,
    month: m,
  }
}
