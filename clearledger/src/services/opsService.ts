/**
 * Управленческий кокпит ЭЗС (раздел «Управленческий», energy) — обзор ситуации,
 * расхождения и рабочие списки. Бэкенд: /api/ops/* (services/ops_dashboard.py).
 *
 * Терминология энергобаланса: вход (по счетам контрагентов) = отпуск (сессии)
 * + собственные нужды станции (СН, оценка по idle-месяцам) + потери;
 * сигнал = СВЕРХНОРМАТИВНЫЙ небаланс (сверх СН).
 */
import { del, get, patch, post, upload } from './apiClient'

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

/* ──────────────────────────────────────────────────────────────────────────
   Закрытие месяца по затратам: что ждали, что пришло, чем закрыли.
   Бэкенд: services/ops_expectations.py + services/ops_closing.py.
   ────────────────────────────────────────────────────────────────────────── */

/** Откуда взялась сумма строки. Показывается меткой рядом с цифрой:
 *  расчётная сумма без пометки выглядит как подтверждённая. */
export type OpsChargeBasis =
  | 'document' | 'contract' | 'metered' | 'metered_prev'
  | 'prev_period' | 'average' | 'manual' | 'correction' | 'none'

export type OpsChargeStatus =
  | 'expected' | 'received' | 'matched' | 'disputed' | 'accrued' | 'corrected' | 'waived'

export type OpsVarianceClass = 'none' | 'rounding' | 'minor' | 'material'

export type OpsPeriodStatus = 'open' | 'collecting' | 'review' | 'closed' | 'reopened'

export interface OpsCharge {
  id: string
  costItem: string
  costItemLabel: string
  locationId: string | null
  locationName: string | null
  /** Тип объекта: станция, офис, склад. Общеофисные расходы — своя статья. */
  locationType: string | null
  counterpartyId: string | null
  counterpartyName: string | null
  contractId: string | null
  termId: string | null
  seq: number
  correctsChargeId: string | null
  correctionReason: string | null
  expectedGross: number | null
  expectedNet: number | null
  expectedQty: number | null
  expectedBasis: OpsChargeBasis | null
  actualGross: number | null
  actualQty: number | null
  vatPct: number | null
  docId: string | null
  docDueOn: string | null
  overdue: boolean
  status: OpsChargeStatus
  variance: number
  varianceClass: OpsVarianceClass
  reminders: number
  note: string | null
}

export interface OpsCounterBlock { count: number; gross: number }

export interface OpsClosingCounters {
  total: number
  totalGross: number
  expected: OpsCounterBlock
  received: OpsCounterBlock
  estimated: OpsCounterBlock
  variance: OpsCounterBlock
  noBasis: number
}

/** Условие, которое развернуть не удалось: без охвата или без суммы. */
export interface OpsBlockedTerm {
  termId: string
  contractId: string
  costItem: string
  locationId?: string | null
  reason: string
}

export interface OpsContractWithoutTerms {
  contractId: string
  number: string
  date: string
  typeCode: string | null
  counterpartyId: string | null
  reason: string
}

export interface OpsClosing {
  period: string
  status: OpsPeriodStatus
  closedAt: string | null
  counters: OpsClosingCounters
  charges: OpsCharge[]
  blocked: OpsBlockedTerm[]
  contractsWithoutTerms: OpsContractWithoutTerms[]
}

export interface OpsCloseResult {
  ok: boolean
  period: string
  accrued?: number
  waived?: number
  counters?: OpsClosingCounters
  blocking: Array<{ chargeId: string; locationId: string | null; costItem: string; reason: string }>
  message?: string
}

/** Рабочий стол закрытия месяца. `scope` разделяет объектные и общие затраты. */
export async function getOpsClosing(
  companyId: string, period?: string,
  scope: 'location' | 'company' | 'all' = 'location',
  status?: string,
): Promise<OpsClosing> {
  const params: Record<string, string> = { company_id: companyId, scope }
  if (period) params.period = period
  if (status) params.status = status
  return get<OpsClosing>('/api/ops/closing', params)
}

/** Закрыть месяц. force — закрыть, даже если часть строк нечем закрыть. */
export async function closeOpsPeriod(
  companyId: string, period: string, force = false,
): Promise<OpsCloseResult> {
  return post<OpsCloseResult>(
    `/api/ops/closing/${period}/close?company_id=${companyId}&force=${force}`)
}

export async function reopenOpsPeriod(
  companyId: string, period: string, reason: string,
): Promise<{ ok: boolean; period: string; status: string }> {
  return post(`/api/ops/closing/${period}/reopen?company_id=${companyId}`, { reason })
}

export interface OpsAttachResult {
  chargeId: string
  variance: number
  varianceClass: OpsVarianceClass
  periodClosed: boolean
  /** Период закрыт и расхождение существенное — предложить корректировку. */
  correctionOffered: boolean
}

export async function attachOpsDoc(
  companyId: string, chargeId: string, docId: string,
  amounts?: { amountGross?: number; amountNet?: number; qty?: number },
): Promise<OpsAttachResult> {
  return post<OpsAttachResult>(
    `/api/ops/charges/${chargeId}/doc?company_id=${companyId}`, { docId, ...amounts })
}

export async function correctOpsCharge(
  companyId: string, chargeId: string, reason?: string, period?: string,
): Promise<{ correctionId: string; period: string; amount: number }> {
  return post(`/api/ops/charges/${chargeId}/correction?company_id=${companyId}`,
    { reason, period })
}

/** Затраты объектов: матрица объект × месяц × статья за диапазон. */
export interface OpsChargesMatrix {
  from: string
  to: string
  periods: string[]
  costItems: Array<{ code: string; label: string }>
  rows: Array<{
    locationId: string | null
    locationName: string
    locationType: string | null
    byPeriod: Record<string, Record<string, number>>
    total: number
  }>
  totalsByPeriod: Record<string, number>
  /** Сколько строк каждого месяца закрыто чем: документом, договором, средним… */
  byBasis: Record<string, Record<string, number>>
}

/* ── Условия начисления: из чего разворачивается ожидание ─────────────────── */

export interface OpsTerm {
  id: string
  contractId: string
  costItem: string
  scopeType: 'location' | 'company'
  locationId: string | null
  periodicity: 'monthly' | 'quarterly' | 'annual' | 'one_time'
  amountGross: number | null
  amountNet: number | null
  vatPct: number | null
  variableKind: string | null
  tariffRub: number | null
  pctOfRevenue: number | null
  expectedDocs: string[] | null
  docDueDay: number | null
  payDueDay: number | null
  estimateBasis: string | null
  indexKind: string | null
  indexPct: number | null
  indexMonth: number | null
  validFrom: string
  validTo: string | null
  docChannel: string | null
  counterpartyEmail: string | null
  ownerUserId: string | null
  source: string | null
  note: string | null
  /** Действует ли версия сегодня. */
  current: boolean
}

export interface OpsTermsList {
  terms: OpsTerm[]
  costItems: Array<{ code: string; label: string; measure: string | null; settlementRole: string | null }>
}

export async function getOpsTerms(companyId: string, contractId?: string): Promise<OpsTermsList> {
  const params: Record<string, string> = { company_id: companyId }
  if (contractId) params.contract_id = contractId
  return get<OpsTermsList>('/api/ops/terms', params)
}

export async function createOpsTerm(
  companyId: string, payload: Record<string, unknown>,
): Promise<OpsTerm> {
  return post<OpsTerm>(`/api/ops/terms?company_id=${companyId}`, payload)
}

/** `newVersion` — правильный способ поднять ставку: старая версия закрывается
 *  датой, суммы уже закрытых месяцев остаются как были. */
export async function updateOpsTerm(
  companyId: string, termId: string, payload: Record<string, unknown>, newVersion = false,
): Promise<OpsTerm> {
  return patch<OpsTerm>(
    `/api/ops/terms/${termId}?company_id=${companyId}&new_version=${newVersion}`, payload)
}

export async function deleteOpsTerm(
  companyId: string, termId: string,
): Promise<{ ok: boolean; removedCharges: number }> {
  return del(`/api/ops/terms/${termId}?company_id=${companyId}`)
}

/* ── Документы контрагентов ───────────────────────────────────────────────── */

export interface OpsDoc {
  id: string
  docType: string
  number: string | null
  docDate: string | null
  counterpartyId: string | null
  counterpartyName: string | null
  contractId: string | null
  period: string | null
  periodFrom: string | null
  periodTo: string | null
  amountGross: number | null
  amountNet: number | null
  qty: number | null
  channel: string
  parseStatus: string
  matchStatus: string
  fileId: string | null
  /** Сколько ожиданий уже закрыто этим документом. */
  linkedCharges: number
  createdAt: string | null
  note: string | null
}

export async function getOpsDocs(
  companyId: string, matchStatus?: string, counterpartyId?: string,
): Promise<{ docs: OpsDoc[] }> {
  const params: Record<string, string> = { company_id: companyId }
  if (matchStatus) params.match_status = matchStatus
  if (counterpartyId) params.counterparty_id = counterpartyId
  return get<{ docs: OpsDoc[] }>('/api/ops/docs', params)
}

export async function createOpsDoc(
  companyId: string, payload: Record<string, unknown>,
): Promise<{ id: string; docType: string; number: string | null; amountGross: number | null }> {
  return post(`/api/ops/docs?company_id=${companyId}`, payload)
}

/** Загрузить скан и завести документ; `chargeId` сразу закрывает им ожидание. */
export async function uploadOpsDoc(
  companyId: string, file: File, fields: Record<string, string | number | undefined>,
): Promise<{ id: string; attach?: { variance: number; varianceClass: OpsVarianceClass; correctionOffered: boolean } }> {
  const params = new URLSearchParams({ company_id: companyId })
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== '' && v !== null) params.set(k, String(v))
  }
  const form = new FormData()
  form.append('file', file)
  return upload(`/api/ops/docs/upload?${params}`, form)
}

/** Прикрепить скан к уже заведённому документу: сумму часто вбивают раньше,
 *  чем доходят до сканера. */
export async function attachOpsDocFile(
  companyId: string, docId: string, file: File,
): Promise<{ id: string; fileId: string; fileName: string }> {
  const form = new FormData()
  form.append('file', file)
  return upload(`/api/ops/docs/${docId}/file?company_id=${companyId}`, form)
}

/** Ссылка на скан. Отдаёт общая файловая ручка со своей проверкой владельца. */
export const opsDocFileUrl = (fileId: string) => `/api/files/${fileId}`

/** Состояние одного отчётного периода в шкале. */
export interface OpsPeriodRow {
  period: string
  status: OpsPeriodStatus
  closedAt: string | null
  total: number
  withDoc: number
  accrued: number
  waiting: number
  overdue: number
  noBasis: number
  /** Доля строк, закрытых документом, — процент выполнения периода. */
  docPct: number | null
  /** Доля денег, подтверждённая документом: мелких строк может быть закрыто много,
   *  а крупная аренда как раз и не пришла. */
  docMoneyPct: number | null
  totalGross: number
  docGross: number
}

export interface OpsPeriodsScale {
  from: string
  to: string
  periods: OpsPeriodRow[]
  avgDocPct: number | null
  worst: OpsPeriodRow[]
}

export async function getOpsPeriods(
  companyId: string, months = 12, ahead = 2,
): Promise<OpsPeriodsScale> {
  return get<OpsPeriodsScale>('/api/ops/periods', {
    company_id: companyId, months: String(months), ahead: String(ahead),
  })
}

/** Дисциплина контрагента: как он с нами работает и по какому телефону звонить. */
export interface OpsCounterpartyRow {
  counterpartyId: string | null
  name: string
  inn: string | null
  email: string | null
  phone: string | null
  director: string | null
  expected: number
  delivered: number
  onTime: number
  late: number
  missing: number
  onTimePct: number | null
  deliveredPct: number | null
  avgLateDays: number | null
  gross: number
  docGross: number
  periods: number
  objects: number
  costItems: string[]
}

export interface OpsCounterparties {
  from: string
  to: string
  rows: OpsCounterpartyRow[]
  totals: {
    counterparties: number
    expected: number
    delivered: number
    missing: number
    gross: number
    noContact: number
  }
}

export async function getOpsCounterparties(
  companyId: string, from?: string, to?: string,
): Promise<OpsCounterparties> {
  const params: Record<string, string> = { company_id: companyId }
  if (from) params.from = from
  if (to) params.to = to
  return get<OpsCounterparties>('/api/ops/counterparties', params)
}

/** Календарь сбора: что и от кого ждём вперёд, что уже просрочено. */
export interface OpsCalendarBucket {
  due: string | null
  overdue: boolean
  count: number
  gross: number
  byCounterparty: Array<{ name: string; count: number; gross: number; objects: string[] }>
}

export interface OpsCalendar {
  today: string
  horizonDays: number
  buckets: OpsCalendarBucket[]
}

export async function getOpsCalendar(
  companyId: string, horizon = 45,
): Promise<OpsCalendar> {
  return get<OpsCalendar>('/api/ops/calendar', {
    company_id: companyId, horizon: String(horizon),
  })
}

export async function getOpsCharges(
  companyId: string, from?: string, to?: string,
  scope: 'location' | 'company' | 'all' = 'location',
): Promise<OpsChargesMatrix> {
  const params: Record<string, string> = { company_id: companyId, scope }
  if (from) params.from = from
  if (to) params.to = to
  return get<OpsChargesMatrix>('/api/ops/charges', params)
}

/** Кассовый факт: сколько заплачено против того, сколько начислено. */
export interface OpsPaymentsPeriod {
  period: string
  granularity: 'month' | 'year'
  paid: number
  capital: number
  expected: number
  diff: number
  items: Record<string, { paid: number; expected: number }>
}

export interface OpsPaymentsSummary {
  periods: OpsPaymentsPeriod[]
  total_paid: number
  total_capital: number
  /** Откуда цифра: файл выгрузки и когда его приняли. */
  source: { file: string | null; loaded_at: string; rows: number } | null
}

export async function getOpsPayments(
  companyId: string, from?: string, to?: string,
): Promise<OpsPaymentsSummary> {
  const params: Record<string, string> = { company_id: companyId }
  if (from) params.date_from = from
  if (to) params.date_to = to
  return get<OpsPaymentsSummary>('/api/ops/payments', params)
}

/** Кому платим больше всего: разрез выгрузки по контрагентам. */
export interface OpsPaymentsParty {
  name: string
  known: boolean
  paid: number
  items: number
  objects: number
  first_period: string
  last_period: string
}

export async function getOpsPaymentsParties(
  companyId: string, limit = 50,
): Promise<{ rows: OpsPaymentsParty[] }> {
  return get('/api/ops/payments/counterparties', {
    company_id: companyId, limit: String(limit),
  })
}

/** Принять сводную выгрузку списаний. Повтор того же файла не двоит суммы. */
export interface OpsPaymentsUploadResult {
  batch_id: string
  saved: number
  counterparties_matched: number
  unknown_items: string[]
}

export async function uploadOpsPayments(
  companyId: string, file: File,
): Promise<OpsPaymentsUploadResult> {
  const form = new FormData()
  form.append('file', file)
  return upload(`/api/ops/payments/upload?company_id=${encodeURIComponent(companyId)}`, form)
}

/** Сколько бухгалтерских номеров выгрузки связано с объектами сети. */
export async function getOpsPaymentsCoverage(
  companyId: string,
): Promise<{ numbers_total: number; numbers_linked: number; hint: string }> {
  return get('/api/ops/payments/coverage', { company_id: companyId })
}
