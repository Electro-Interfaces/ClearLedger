/**
 * Управленческий кокпит ЭЗС (раздел «Управленческий», energy) — обзор ситуации,
 * расхождения и рабочие списки. Бэкенд: /api/ops/* (services/ops_dashboard.py).
 *
 * Терминология энергобаланса: вход (по счетам контрагентов) = отпуск (сессии)
 * + собственные нужды станции (СН, оценка по idle-месяцам) + потери;
 * сигнал = СВЕРХНОРМАТИВНЫЙ небаланс (сверх СН).
 */
import { del, get, patch, post, put, upload } from './apiClient'

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

/** Строка состояния сети: что витрина думает о станции и что говорят сессии. */
export interface NetworkStationRow {
  locationId: string
  code: string | null
  number: string | null
  name: string
  region: string | null
  city: string | null
  status: string
  statusLabel: string
  /** Состояние словами витрины: «Нажата аварийная кнопка» и прочее вне справочника. */
  statusRaw: string | null
  lastSessionAt: string | null
  /** Дней без зарядок. null — не заряжала ни разу. */
  silentDays: number | null
  sessions90d: number
  sessions7d: number
  revenuePerMonth: number
  connectors: number | null
  /** Числится рабочей, а энергии нет больше недели. */
  mismatch: boolean
  /** Зарабатывала и замолчала: ₽/мес, которые сеть недобирает. */
  loss: number
  attention: boolean
  lifeStatus: string
}

export interface NetworkRegionRow {
  region: string
  stations: number
  working: number
  noLink: number
  silentWeek: number
  mismatch: number
  revenuePerMonth: number
}

export interface OpsSnapshot {
  asOf: string
  dataThrough: string | null
  dataLagHours: number | null
  snapshotNote?: string
}

export interface NetworkState extends OpsSnapshot {
  /** Момент, по который есть данные (последняя загруженная сессия). */
  asOf: string
  dataLagHours: number | null
  totals: {
    stations: number; active: number
    charging2d: number; chargingWeek: number
    silentWeek: number; silentMonth: number; neverCharged: number
    mismatch: number; mismatchRevenue: number
    attention: number; lossPerMonth: number
    byStatus: Record<string, number>
  }
  statusLabels: Record<string, string>
  regions: NetworkRegionRow[]
  stations: NetworkStationRow[]
  note: string
}

/** Строка надёжности: станция в сети, но клиент уезжает ни с чем. */
export interface ReliabilityRow {
  locationId: string
  code: string | null
  number: string | null
  name: string
  region: string | null
  city: string | null
  status: string
  /** Марка и модель железа: тот же разрез, что в «Производителях». */
  brand: string | null
  model: string | null
  /** Приезд клиента: несколько попыток подряд — один визит. */
  visits: number
  visitsOk: number
  visitsFailed: number
  failedVisitsPct: number
  /** Сколько раз пришлось воткнуть разъём за приезд. */
  attemptsPerVisit: number
  clientsLost: number
  sessions: number
  failed: number
  failedPct: number
  /** Исход «успех», а энергии ноль: подключился, постоял, уехал. */
  empty: number
  emptyPct: number
  clients: number
  clientsAffected: number
  energyKwh: number
  revenue: number
  kwhPerSession: number
  lastSessionAt: string | null
  connectors: number | null
}

export interface NetworkReliability extends OpsSnapshot {
  trend: { current: { visits: number; failed: number; failedPct: number }; previous: { visits: number; failed: number; failedPct: number }; deltaPp: number }
  asOf: string
  days: number
  minSessions: number
  threshold: number
  totals: {
    populationStations: number; stations: number; stationsCounted: number
    visits: number; visitsOk: number; visitsFailed: number
    failedVisitsPct: number; attemptsPerVisit: number
    sessions: number; failed: number; failedPct: number
    empty: number; emptyPct: number
    badStations: number; clientsAffected: number
  }
  regions: { region: string; stations: number; sessions: number
             failed: number; failedPct: number; bad: number
             visits: number; visitsFailed: number; failedVisitsPct: number }[]
  stations: ReliabilityRow[]
  note: string
}

export async function getNetworkReliability(
  companyId: string,
  options?: { days?: number; region?: string; minSessions?: number; asOf?: string },
): Promise<NetworkReliability> {
  const params: Record<string, string> = { company_id: companyId }
  if (options?.days) params.days = String(options.days)
  if (options?.region) params.region = options.region
  if (options?.minSessions) params.min_sessions = String(options.minSessions)
  if (options?.asOf) params.as_of = options.asOf
  return get<NetworkReliability>('/api/ops/reliability', params)
}

/** Марка станций: как её железо держит сеть. */
export interface VendorRow {
  vendor: string
  stations: number
  active: number
  working: number
  noLink: number
  decommissioned: number
  /** Станций, отпускавших энергию за двое суток, и их доля от действующих. */
  charging2d: number
  livePct: number
  silentWeek: number
  neverCharged: number
  visits: number
  visitsFailed: number
  failedVisitsPct: number
  attemptsPerVisit: number
  failedSessionsPct: number
  energyKwh: number
  revenue: number
  badStations: number
  models: string[]
  modelsCount: number
  avgPowerKwt: number | null
  /** Отдача, сравнимая между марками разного размера. */
  kwhPerStationDay: number
}

/** Станция марки — строка раскрытия. */
export interface VendorStationRow {
  locationId: string
  code: string | null
  number: string | null
  name: string
  region: string | null
  city: string | null
  status: string
  vendor: string
  model: string | null
  powerKwt: number | null
  connectors: number | null
  silentDays: number | null
  visits: number
  visitsFailed: number
  failedVisitsPct: number
  attemptsPerVisit: number
  energyKwh: number
  revenue: number
}

export interface NetworkVendors extends OpsSnapshot {
  asOf: string
  days: number
  threshold: number
  totals: {
    vendors: number; stations: number; visits: number
    visitsFailed: number; failedVisitsPct: number; badStations: number
  }
  /** Регионы выборки — для отбора на экране, без своего справочника. */
  regions: string[]
  vendors: VendorRow[]
  vendor: string | null
  stations: VendorStationRow[]
  note: string
}

export async function getNetworkVendors(
  companyId: string,
  /** vendor: марка — её станции; «*» — станции всех марок (для сводной). */
  options?: { days?: number; region?: string; vendor?: string; asOf?: string },
): Promise<NetworkVendors> {
  const params: Record<string, string> = { company_id: companyId }
  if (options?.days) params.days = String(options.days)
  if (options?.region) params.region = options.region
  if (options?.vendor) params.vendor = options.vendor
  if (options?.asOf) params.as_of = options.asOf
  return get<NetworkVendors>('/api/ops/vendors', params)
}

/** Шаг визита: одно втыкание разъёма и чем оно кончилось. */
export interface VisitStep {
  seq: number
  at: string
  minutes: number | null
  connector: string | null
  connectorType: string | null
  result: string | null
  /** Коротко словами: «зарядка», «ошибка», «без энергии». */
  outcome: string
  energyKwh: number
  amount: number
  tariff: number | null
  sessionId: string | null
}

/** Визит — один приезд клиента: несколько попыток подряд входят в него. */
export interface StationVisit {
  visitKey: string
  startedAt: string
  endedAt: string | null
  /** Сколько человек провозился у станции: от первой попытки до конца последней. */
  minutesAtStation: number | null
  attempts: number
  charged: boolean
  energyKwh: number
  revenue: number
  client: string | null
  clientType: string | null
  clientName: string | null
  card: string | null
  /** Картина приезда: ok · retry_same · retry_other · left_after_tries · left_first. */
  pattern: string
  steps: VisitStep[]
}

export interface StationVisits {
  asOf: string
  days: number
  station: { locationId: string; name: string; number: string | null; status: string }
  totals: {
    visits: number; failed: number; failedPct: number
    attempts: number; attemptsPerVisit: number
  }
  /** Раскладка приездов по картинам — почему приходилось пробовать снова. */
  patterns: { key: string; label: string; hint: string; visits: number; pct: number }[]
  /** Попытки без энергии: мгновенные (не дошло до тока) и затяжные (держала и не дала). */
  empty: { attempts: number; instant: number; stuck: number; hint: string }
  connectors: { connector: string; type: string | null; attempts: number
                failed: number; failedPct: number; energyKwh: number }[]
  visits: StationVisit[]
  returned: number
  note: string
}

export async function getStationVisits(
  companyId: string, locationId: string,
  options?: { days?: number; onlyFailed?: boolean; limit?: number },
): Promise<StationVisits> {
  const params: Record<string, string> = { company_id: companyId }
  if (options?.days) params.days = String(options.days)
  if (options?.onlyFailed) params.only_failed = 'true'
  if (options?.limit) params.limit = String(options.limit)
  return get<StationVisits>(
    `/api/ops/station-visits/${encodeURIComponent(locationId)}`, params)
}

/** История одной станции: работа за окно, перерывы и смены состояния. */
export interface StationHistory {
  asOf: string
  days: number
  station: {
    locationId: string; code: string | null; number: string | null; name: string
    city: string | null; status: string; statusLabel: string; statusRaw: string | null
    connectors: number | null; powerKwt: number | null
    lastSessionAt: string | null; silentDays: number | null
  }
  work: {
    sessions: number; failed: number; failedPct: number; empty: number
    clients: number; energyKwh: number; revenue: number
    avgMinutes: number | null; sessionsPerPortDay: number | null
  }
  days_series: { day: string; sessions: number; failed: number
                 energyKwh: number; revenue: number }[]
  /** Паузы дольше суток; `ongoing` — станция молчит прямо сейчас. */
  breaks: { from: string; to: string | null; hours: number; days: number; ongoing: boolean }[]
  breaksTotal: number
  events: { at: string | null; kind: string; from: string | null
            to: string | null; reason: string | null; author: string | null }[]
  note: string
}

export async function getStationHistory(
  companyId: string, locationId: string, days = 90,
): Promise<StationHistory> {
  return get<StationHistory>(
    `/api/ops/station-history/${encodeURIComponent(locationId)}`,
    { company_id: companyId, days: String(days) })
}

/** Условия ответственности стороны договора: то, на что ссылается претензия. */
export interface ContractLiability {
  responseHours?: number | null
  fixDays?: number | null
  calendar?: 'calendar' | 'business' | null
  penaltyKind?: 'per_day_fixed' | 'per_day_pct' | 'none' | null
  penaltyValue?: number | null
  penaltyCap?: number | null
  warrantyUntil?: string | null
  warrantyMonths?: number | null
  escalation?: { afterDays: number; action: string }[] | null
  clauses?: { field: string; code: string; text: string; hint?: string }[] | null
  source?: 'manual' | 'parsed' | null
}

/** Договор в паспорте обязательств станции. */
export interface ObligationContract {
  id: string
  number: string
  date: string | null
  title: string | null
  type: string
  role: string
  counterpartyId: string | null
  counterparty: string | null
  validUntil: string | null
  isClosed: boolean
  basis: string | null
  scope: 'location' | 'company'
  locationsCount: number
  liability: ContractLiability | null
}

export interface ObligationTerm {
  id: string
  costItem: string
  periodicity: string
  amountGross: number | null
  tariffRub: number | null
  payDueDay: number | null
  docDueDay: number | null
  expectedDocs: string[] | null
  counterpartyEmail: string | null
  validFrom: string | null
  validTo: string | null
  note: string | null
}

export interface StationObligations {
  locationId: string
  found: boolean
  name?: string
  number?: string | null
  brand?: string | null
  model?: string | null
  installedOn?: string | null
  groups: {
    role: string; label: string
    contracts: ObligationContract[]
    terms: Record<string, ObligationTerm[]>
  }[]
  settlements: {
    role: string; counterpartyId: string | null; contractId: string | null
    paymentStatus: string; paidThrough: string | null
    basis: string | null; comment: string | null
  }[]
  documents: { id: string; kind: string; title: string; number: string | null
               date: string | null; status: string }[]
  gaps: string[]
  metering: { known: boolean; note: string }
}

export async function parseContractLiability(
  companyId: string, contractId: string, данные: { file?: File; text?: string },
): Promise<{ found: ContractLiability; reason: string | null; chars?: number }> {
  const url = `/api/ops/contracts/${encodeURIComponent(contractId)}/liability/parse`
    + `?company_id=${encodeURIComponent(companyId)}`
  if (данные.file) {
    const fd = new FormData()
    fd.append('file', данные.file)
    return upload(url, fd)
  }
  return post(url, { text: данные.text ?? '' })
}

export async function putContractLiability(
  companyId: string, contractId: string, body: ContractLiability,
): Promise<ContractLiability> {
  return put(`/api/ops/contracts/${encodeURIComponent(contractId)}/liability`
    + `?company_id=${encodeURIComponent(companyId)}`, body)
}

/** Строка маппинга: под каким ключом станция известна внешней системе. */
export interface MappingRow {
  id: string | null
  system: string
  systemLabel: string
  role: string
  roleLabel: string
  value: string
  note: string | null
  /** own — наш ключ, snapshot — из загрузки, registry — ведём вручную. */
  source: 'own' | 'snapshot' | 'registry'
  validFrom: string | null
  validTo: string | null
  basis: string | null
  author: string | null
}

export interface StationMapping {
  locationId: string
  found: boolean
  name?: string
  own: MappingRow[]
  snapshot: MappingRow[]
  registry: MappingRow[]
  roaming: MappingRow[]
  systems: { code: string; label: string }[]
  roles: { code: string; label: string }[]
  note: string
}

export async function getStationMapping(
  companyId: string, locationId: string,
): Promise<StationMapping> {
  return get<StationMapping>(
    `/api/ops/station-mapping/${encodeURIComponent(locationId)}`,
    { company_id: companyId })
}

export async function addStationExternalId(
  companyId: string, locationId: string,
  body: { system: string; role: string; value: string; valid_from?: string; note?: string },
): Promise<{ id: string; system: string; role: string; value: string }> {
  return post(`/api/ops/station-mapping/${encodeURIComponent(locationId)}`
    + `?company_id=${encodeURIComponent(companyId)}`, body)
}

export async function closeStationExternalId(
  companyId: string, locationId: string, linkId: string, reason?: string,
): Promise<{ id: string; validTo: string }> {
  const qs = new URLSearchParams({ company_id: companyId })
  if (reason) qs.set('reason', reason)
  return del(`/api/ops/station-mapping/${encodeURIComponent(locationId)}`
    + `/${encodeURIComponent(linkId)}?${qs}`)
}

export async function getStationObligations(
  companyId: string, locationId: string,
): Promise<StationObligations> {
  return get<StationObligations>(
    `/api/ops/station-obligations/${encodeURIComponent(locationId)}`,
    { company_id: companyId })
}

/** Причина, по которой станция попала в рабочий лист. */
export interface WorkReason {
  kind: 'silent' | 'failing' | 'breached' | 'meter' | 'service' | 'check'
  label: string
  note?: string | null
}

/** Строка рабочего листа: станция, причины и цена вопроса. */
export interface WorklistRow {
  locationId: string
  code: string | null
  number: string | null
  name: string
  region: string | null
  city: string | null
  status: string
  statusLabel: string | null
  reasons: WorkReason[]
  silentDays: number | null
  lossPerMonth: number
  clientsLost: number
  failedVisitsPct: number | null
  visits: number
  /** Приездов в сутки — загруженность площадки, третий ключ порядка очереди. */
  visitsPerDay: number | null
  /** Ход работы из «Поддержки»: сколько открытых заявок и есть ли срыв срока. */
  openTickets: number
  breachedTickets: number
  lastTicketId: string | null
  lastTicketNumber: string | null
}

export interface OpsWorklist extends OpsSnapshot {
  asOf: string
  dataLagHours: number | null
  threshold: number
  totals: {
    rows: number; silent: number; failing: number; breached: number
    notTaken: number | null; lossPerMonth: number; lossNotTaken: number | null; clientsLost: number
    /** Профилактика: поверка счётчика, просроченное ТО, нарушения осмотра. */
    meter: number; service: number; check: number
    /** Сроки, которые вообще не заполнены: не работа, но и не «в порядке». */
    upkeepUnknown: number
  }
  dataGaps: (NetworkStationRow & { units: number; meterUnknown: number; serviceUnknown: number })[]
  rows: WorklistRow[]
  /** false — «Поддержка» недоступна, пометки «взято/не взято» неизвестны. */
  workKnown: boolean
  note: string
}

/** Заявка в срезе эксплуатации: поля «Поддержки» плюс станция из реестра. */
export interface TicketRow {
  isOpen: boolean
  /** Заведена внутри окна. false — попала в список как открытая работа. */
  inWindow: boolean
  id: string
  number: string
  title: string
  status: string
  statusLabel: string
  priority: string | null
  priorityLabel: string | null
  kind: string
  stage: string | null
  source: string
  createdAt: string
  closedAt: string | null
  /** Сколько дней заявке — считает сервер. */
  ageDays: number | null
  slaBreached: boolean
  assignee: string | null
  locationId: string | null
  station: string | null
  stationNumber: string | null
  brand: string
  region: string
  city: string | null
  ownerClass: string
  owner: string
  stationStatus: string | null
}

export interface TicketsCut { key: string; count: number; open?: number; breached?: number }

export interface OpsTickets extends OpsSnapshot {
  days: number
  totals: {
    total: number; open: number; inWindow: number; breached: number
    /** Открытые, заведённые до окна: работа, которую окно прятало. */
    openBeforeWindow: number
    urgentOpen: number; staleOpen: number; objects: number
    /** Станции с открытой работой — то же множество, что «взято» в очереди. */
    openObjects: number
    avgHours: number | null
  }
  by: Record<string, TicketsCut[]>
  rows: TicketRow[]
  shown: number
  withoutStation: number
  gaps: string[]
  note: string
}

export async function getOpsTickets(
  companyId: string, options?: { days?: number; limit?: number; region?: string; asOf?: string },
): Promise<OpsTickets> {
  const params: Record<string, string> = { company_id: companyId }
  if (options?.days) params.days = String(options.days)
  if (options?.limit) params.limit = String(options.limit)
  if (options?.region) params.region = options.region
  if (options?.asOf) params.as_of = options.asOf
  return get<OpsTickets>('/api/ops/tickets', params)
}

/** Состояние ежедневной выгрузки: свежесть, пропавшие поля, потери. */
export interface IntakeHealth {
  everLoaded: boolean
  hours: number | null
  level: 'ok' | 'late' | 'alarm' | 'unknown'
  lastLoadAt: string | null
  dataThrough: string | null
  thresholdHours?: number
  lostFields: { field: string; label: string; lastSeen: string | null; rowsWithout: number }[]
  payments: { total: number; orphans: number; orphanAmount: number }
  sessionsWithoutStation: number
  note: string
}

export async function getIntakeHealth(companyId: string): Promise<IntakeHealth> {
  return get<IntakeHealth>('/api/ops/intake-health', { company_id: companyId })
}

export async function getOpsWorklist(
  companyId: string, options?: { region?: string; asOf?: string },
): Promise<OpsWorklist> {
  const params: Record<string, string> = { company_id: companyId }
  if (options?.region) params.region = options.region
  if (options?.asOf) params.as_of = options.asOf
  return get<OpsWorklist>('/api/ops/worklist', params)
}

export async function getNetworkState(
  companyId: string,
  /** `asOf` — состояние НА этот день (ISO), а не на границу данных. */
  options?: { region?: string; onlyProblems?: boolean; asOf?: string },
): Promise<NetworkState> {
  const params: Record<string, string> = { company_id: companyId }
  if (options?.region) params.region = options.region
  if (options?.onlyProblems) params.only_problems = 'true'
  if (options?.asOf) params.as_of = options.asOf
  return get<NetworkState>('/api/ops/network-state', params)
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

// ── Осмотр станции (чек-лист) ───────────────────────────────────────────────
// Телеметрия отвечает, идёт ли ток. Есть ли на корпусе заводской номер, видна
// ли цена до оплаты и цела ли оклейка — видно только на месте.
// Бэкенд: services/station_checklist.py (регламент) + station_check.py (отметки).

/** Вывод по пункту: чем плоха станция прямо сейчас. */
export type CheckVerdict = 'ok' | 'stale' | 'fail' | 'never' | 'na'

export interface StationCheckItem {
  key: string
  group: string
  group_label: string
  label: string
  /** Норма, на которую ссылаемся, либо честное «требование сети». */
  basis: string
  hint: string
  /** Отметка без снимка по этому пункту считается неподтверждённой. */
  photo: boolean
  /** Срок годности отметки в днях. */
  days: number
  verdict: CheckVerdict
  state: string | null
  stateLabel: string | null
  checkedOn: string | null
  ageDays: number | null
  note: string | null
  checkedBy: string | null
  fileId: string | null
  fileName: string | null
  unconfirmed: boolean
}

export interface StationCheckState {
  station: { locationId: string; name: string; number: string | null
             brand: string | null; model: string | null; serial: string | null }
  totals: {
    ok: number; stale: number; fail: number; never: number; na: number
    items: number; counted: number; okPct: number
    unconfirmed: number; lastCheck: string | null
  }
  groups: { code: string; label: string; items: StationCheckItem[] }[]
  note: string
}

export async function getStationCheck(
  companyId: string, locationId: string,
): Promise<StationCheckState> {
  return get(`/api/ops/station-check/${encodeURIComponent(locationId)}`,
    { company_id: companyId })
}

/** Записать отметку осмотра. Прежние остаются — это история станции. */
export async function addStationCheck(
  companyId: string, locationId: string,
  fields: { itemKey: string; state: string; note?: string; checkedOn?: string },
  file?: File | null,
): Promise<{ id: string; itemKey: string; state: string; checkedOn: string }> {
  const params = new URLSearchParams({
    company_id: companyId, item_key: fields.itemKey, state: fields.state })
  if (fields.note) params.set('note', fields.note)
  if (fields.checkedOn) params.set('checked_on', fields.checkedOn)
  const form = new FormData()
  if (file) form.append('file', file)
  return upload(
    `/api/ops/station-check/${encodeURIComponent(locationId)}?${params}`, form)
}

export interface StationCheckHistoryRow {
  id: string; itemKey: string; itemLabel: string
  state: string; stateLabel: string
  checkedOn: string; note: string | null; checkedBy: string | null
  fileId: string | null
}

export async function getStationCheckHistory(
  companyId: string, locationId: string, itemKey?: string,
): Promise<StationCheckHistoryRow[]> {
  const params: Record<string, string> = { company_id: companyId }
  if (itemKey) params.item_key = itemKey
  return get(`/api/ops/station-check/${encodeURIComponent(locationId)}/history`, params)
}


/** Срок: состояние и сколько дней осталось (минус — просрочено). */
export interface UpkeepTerm {
  state: 'ok' | 'soon' | 'overdue' | 'unknown'
  stateLabel: string
  daysLeft: number | null
}

export interface StationUpkeep {
  hasUnit: boolean
  note: string
  unitId?: string
  serial?: string | null
  vendor?: string | null
  model?: string | null
  stationType?: string | null
  warrantyUntil?: string | null
  meter?: UpkeepTerm & {
    serial: string | null
    verifiedOn: string | null
    verifyUntil: string | null
  }
  service?: UpkeepTerm & {
    intervalDays: number
    /** true — интервал взят из норматива типа, человек его не задавал. */
    intervalDefault: boolean
    lastOn: string | null
    nextOn: string | null
  }
}

export async function getStationUpkeep(
  companyId: string, locationId: string,
): Promise<StationUpkeep> {
  return get(`/api/ops/station-upkeep/${encodeURIComponent(locationId)}`,
    { company_id: companyId })
}

/** Записать метрологию и график ТО. Пустая строка стирает значение. */
export async function putStationUpkeep(
  companyId: string, locationId: string,
  body: {
    meterSerial?: string | null
    meterVerifiedOn?: string | null
    meterVerifyUntil?: string | null
    serviceIntervalDays?: number | null
    lastServiceOn?: string | null
  },
): Promise<StationUpkeep> {
  return put(`/api/ops/station-upkeep/${encodeURIComponent(locationId)}` +
    `?company_id=${encodeURIComponent(companyId)}`, body)
}

export interface NetworkUpkeep {
  totals: {
    units: number
    meterOverdue: number; meterSoon: number; meterUnknown: number
    serviceOverdue: number; serviceSoon: number; serviceUnknown: number
  }
  rows: (StationUpkeep & { locationId: string })[]
  note: string
}

export async function getNetworkUpkeep(companyId: string): Promise<NetworkUpkeep> {
  return get('/api/ops/network-upkeep', { company_id: companyId })
}
