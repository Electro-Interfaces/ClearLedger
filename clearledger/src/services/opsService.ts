/**
 * Управленческий кокпит ЭЗС (раздел «Управленческий», energy) — обзор ситуации,
 * расхождения и рабочие списки. Бэкенд: /api/ops/* (services/ops_dashboard.py).
 *
 * Терминология энергобаланса: вход (по счетам контрагентов) = отпуск (сессии)
 * + собственные нужды станции (СН, оценка по idle-месяцам) + потери;
 * сигнал = СВЕРХНОРМАТИВНЫЙ небаланс (сверх СН).
 */
import { get } from './apiClient'

export interface OpsSeriesPoint {
  period: string
  intakeKwh: number
  intakeStations: number
  dispensedKwh: number
  dispensedAtIntakeKwh: number
  ownUseEstKwh: number
  imbalanceKwh: number
  overImbalanceKwh: number
  overImbalancePct: number
  costEst: number | null
  revenue: number | null
}

export interface OpsIssueRow {
  locationId: string
  bu: string | null
  name: string
  region: string | null
  value: number | null
  note: string | null
}

export interface OpsIssue {
  key: string
  label: string
  severity: 'red' | 'amber'
  hint: string
  count: number
  unit: string
  rows: OpsIssueRow[]
}

export interface OpsKpis {
  refPeriod: string | null
  energyCostRef: number | null
  revenueRef: number | null
  rentMonthly: number
  rentContractsWithAmount: number
  overImbalancePctRef: number | null
  ownUseFleetMedianKwh: number
  issuesRed: number
  issuesTotal: number
  lastPeriod: string | null
}

export interface OpsOverview {
  series: OpsSeriesPoint[]
  kpis: OpsKpis
  issues: OpsIssue[]
  regions: string[]
  region: string | null
}

export interface OpsBalanceRow {
  locationId: string
  bu: string | null
  name: string
  region: string | null
  intakeKwh: number | null
  dispensedKwh: number
  sessions: number
  ownUseEstKwh: number | null
  imbalanceKwh: number | null
  overImbalanceKwh: number | null
  overImbalancePct: number | null
  tariff: number | null
  costEst: number | null
  revenue: number | null
  marginEst: number | null
}

export interface OpsBalance {
  period: string | null
  months: string[]
  rows: OpsBalanceRow[]
  ownUseFleetMedianKwh: number
  regions: string[]
  region: string | null
}

/** Карточка объекта (drill-down): паспорт + помесячный баланс + договорные контуры. */
export interface OpsStationSeriesPoint {
  period: string
  intakeKwh: number | null
  dispensedKwh: number
  sessions: number
  imbalanceKwh: number | null
  overImbalanceKwh: number | null
  tariff: number | null
  costEst: number | null
  revenue: number | null
}

export interface OpsStationContour {
  role: 'energy' | 'rent' | 'service'
  counterpartyName: string | null
  contractNumber: string | null
  basis: string | null
  paymentStatus: string
  paidThrough: string | null
  amountGross: number | null
  amountNet: number | null
  vatPct: number | null
  contractStart: string | null
  contractEnd: string | null
  comment: string | null
  extra: Record<string, unknown> | null
}

export interface OpsStation {
  found: boolean
  locationId: string
  bu: string | null
  name: string
  region: string | null
  address: string | null
  status: string | null
  stage: string | null
  powerKw: number | null
  connectors: number | null
  serial: string | null
  zoi: string | null
  ownUseEstKwh: number | null
  avgTariff: number | null
  series: OpsStationSeriesPoint[]
  contours: OpsStationContour[]
}

export async function getOpsOverview(companyId: string, region?: string): Promise<OpsOverview> {
  const params: Record<string, string> = { company_id: companyId }
  if (region) params.region = region
  return get<OpsOverview>('/api/ops/overview', params)
}

export async function getOpsBalance(companyId: string, period?: string, region?: string): Promise<OpsBalance> {
  const params: Record<string, string> = { company_id: companyId }
  if (period) params.period = period
  if (region) params.region = region
  return get<OpsBalance>('/api/ops/balance', params)
}

export async function getOpsStation(companyId: string, locationId: string): Promise<OpsStation> {
  return get<OpsStation>(`/api/ops/station/${locationId}`, { company_id: companyId })
}

/** «Полнота данных»: матрица «вид данных × месяц» + списки недостающего. */
export interface OpsComplMonthCell {
  period: string
  have: number
  expected: number
  pct: number | null
}

export interface OpsComplMissingRow {
  locationId: string
  bu: string | null
  name: string
  region: string | null
  months: string[]
  note: string | null
}

export interface OpsComplKind {
  key: string
  label: string
  doc: string
  monthly: boolean
  hint: string
  perMonth: OpsComplMonthCell[]
  pct: number | null
  missingCount: number
  rows: OpsComplMissingRow[]
}

export interface OpsCompleteness {
  months: string[]
  monthsAll: string[]
  from: string | null
  to: string | null
  kinds: OpsComplKind[]
  regions: string[]
  region: string | null
}

export async function getOpsCompleteness(
  companyId: string, from?: string, to?: string, region?: string,
): Promise<OpsCompleteness> {
  const params: Record<string, string> = { company_id: companyId }
  if (from) params.from = from
  if (to) params.to = to
  if (region) params.region = region
  return get<OpsCompleteness>('/api/ops/completeness', params)
}
