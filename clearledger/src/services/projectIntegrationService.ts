import { get, patch, post } from './apiClient'
import type { ChargeDimensionStation } from './analyticsService'
import type { GateState } from './sitesService'

export const INTEGRATION_FORMATS = { information: 'Информационная', roaming: 'Роуминг', hybrid: 'Гибридная' }
export const INTEGRATION_DIRECTIONS = { outgoing: 'Наши ЭЗС в сервисе партнёра', incoming: 'ЭЗС партнёра в нашем приложении', both: 'Двусторонняя' }
export type IntegrationSection = 'partner' | 'lead' | 'commercial' | 'settlement' | 'data' | 'technical' | 'work' | 'accounting'
/** Заявка: кто инициатор и какой договор предполагается (без ставок — это переговоры). */
export const LEAD_INITIATORS = { partner: 'Партнёр пришёл к нам', us: 'Мы вышли на партнёра' }
export const LEAD_CONTRACT_KINDS = { information: 'Информационный обмен без денег', roaming: 'Роуминг', agency: 'Агентский договор', other: 'Иное' }
export const INTEGRATION_PAYERS = { partner: 'Партнёр платит нам', us: 'Мы платим партнёру', none: 'Без расчётов' }
export const INTEGRATION_MODELS = { commission: 'Комиссия, %', fixed: 'Фиксированная плата', margin: 'Наценка к тарифу', none: 'Без оплаты' }
export const CONNECT_BASIS = { check: 'Проверено у принимающей стороны', session: 'Прошла первая сессия' }
export const MATCH_KINDS = { account: 'Договорной аккаунт клиента', client: 'Юрлицо клиента в сессии', card: 'Номера карт' }
export interface PartnerSessions {
  rule: { kind: keyof typeof MATCH_KINDS; label: string; values: string[] }; from: string; to: string
  total: { sessions: number; kwh: number; amount: number }
  byMonth: { month: string; sessions: number; kwh: number; amount: number }[]
  sample: { at: string | null; station: string | null; client: string | null; card: string | null; kwh: number; amount: number }[]
}
export const getPartnerSessions = (companyId: string, siteId: string, from?: string, to?: string) =>
  get<PartnerSessions>(`/api/sites/${siteId}/integration/sessions`, { company_id: companyId, from: from || undefined, to: to || undefined })
export const TEST_STATUSES = { pending: 'Не проведено', passed: 'Пройдено', failed: 'Замечание', na: 'Неприменимо' }
export interface IntegrationScenario {
  id: string; name: string; direction: 'outgoing' | 'incoming'; format: 'information' | 'roaming'
  geography: string; restrictions: string; partnerNetwork: string
  selectedIds: string[]; agreedIds: string[]; connectedIds: string[]; pilotIds: string[]
  payer?: '' | keyof typeof INTEGRATION_PAYERS; model?: '' | keyof typeof INTEGRATION_MODELS
  rate?: string; base?: string; clientPrice?: string; acquiring?: string
  connectedMeta?: Record<string, { at: string; basis: keyof typeof CONNECT_BASIS; ref: string }>
}
export interface IntegrationTest {
  id: string; scenarioId: string; title: string; required: boolean; status: keyof typeof TEST_STATUSES
  sessionRef: string; comment: string; docId: string; byName?: string; at?: string
}
export interface IntegrationReconciliation {
  id: string; kind: 'pilot' | 'monthly'; period: string; resolution: string; docId: string; from?: string; to?: string
  ours: { sessions: number; kwh: number; amount: number }; partner: { sessions: number; kwh: number; amount: number }
  byName?: string; at?: string
}
export interface IntegrationListVersion { id: string; scenarioId: string; version: number; stationIds: string[]; documentId: string; note: string; byName?: string; at?: string }
export interface IntegrationDocument {
  id: string; kind: string; title: string; edition: string
  fileDocId: string; agreedDocId: string; signedDocId: string; signingEvidence: string
}
export interface IntegrationResult { comment: string; workRef: string; docId: string; notApplicable: boolean }
export type IntegrationParty = { counterpartyId: string; side: string; note?: string }
export const PARTY_SIDES: Record<string, string> = { vendor: 'Наш вендор', contractor: 'Подрядчик', consultant: 'Консультант', partner_side: 'Со стороны партнёра', other: 'Другое' }
export type IntegrationData = Record<IntegrationSection, Record<string, string>> & {
  revision: number; scenarios: IntegrationScenario[]; documents: IntegrationDocument[]; contractIds: string[]
  tests: IntegrationTest[]; reconciliations: IntegrationReconciliation[]; listVersions: (IntegrationListVersion | Pick<IntegrationListVersion, 'scenarioId' | 'documentId' | 'note'>)[]
  results: Record<string, IntegrationResult>; dates: Record<string, { start: string; end: string }>
  /** Внешние участники кроме партнёра: наш вендор, подрядчик… — контакты в их карточке контрагента. */
  parties?: IntegrationParty[]
}
export interface IntegrationTask {
  key: string; label: string; stage: string; role: string; required?: boolean; section: IntegrationSection | 'scenarios' | 'documents' | 'tests' | 'reconciliations'
  /** Чего не хватает в данных проекта для подтверждения (null — данных достаточно). */
  need?: string | null
  /** У пункта своё требование к данным: выполнено — подтверждается без комментария. */
  dataRule?: boolean
}
export interface IntegrationState {
  data: IntegrationData; tasks: IntegrationTask[]; gates: GateState[]
  phases: { code: string; label: string; term: string; stages: string[] }[]
}
export interface IntegrationStation extends ChargeDimensionStation { id: string; network: 'outgoing' | 'incoming'; group: string }
/** Станция выведена из работы: закрыта или выведена из эксплуатации. В новый выбор не предлагается, в перечнях подсвечивается. */
export const isRetired = (s?: IntegrationStation) => !!s && (s.lifecycle === 'closed' || s.opStatus === 'decommissioned')
/** Расхождение сверки — то же правило, что на сервере (`recon_state`). */
export function reconState(r: IntegrationReconciliation): 'match' | 'resolved' | 'diff' | 'empty' {
  if (!(+r.ours.sessions || 0) && !(+r.partner.sessions || 0)) return 'empty'
  const tol = { sessions: 0, kwh: 0.1, amount: 1 } as const
  const diff = (Object.keys(tol) as (keyof typeof tol)[]).some((k) => Math.abs((+r.ours[k] || 0) - (+r.partner[k] || 0)) > tol[k])
  return !diff ? 'match' : r.resolution && r.docId ? 'resolved' : 'diff'
}

export function initialIntegration(partner: string, format: keyof typeof INTEGRATION_FORMATS, direction: keyof typeof INTEGRATION_DIRECTIONS) {
  return {
    partner: { name: partner },
    scenarios: (direction === 'both' ? ['outgoing', 'incoming'] : [direction]).flatMap((d) =>
      (format === 'hybrid' ? ['information', 'roaming'] : [format]).map((f) => ({
        id: crypto.randomUUID(), name: '', direction: d, format: f,
        selectedIds: [], agreedIds: [], connectedIds: [], pilotIds: [],
      }))),
  }
}
export const getIntegration = (companyId: string, siteId: string) => get<IntegrationState>(`/api/sites/${siteId}/integration`, { company_id: companyId })
export const getIntegrationStations = (companyId: string, siteId: string) => get<IntegrationStation[]>(`/api/sites/${siteId}/integration/stations`, { company_id: companyId })
export const saveIntegration = (companyId: string, siteId: string, data: Partial<IntegrationData> & { revision: number }) => patch<IntegrationData>(`/api/sites/${siteId}/integration?company_id=${companyId}`, data)
export const confirmIntegration = (companyId: string, siteId: string, key: string, revision: number) => post<IntegrationData>(`/api/sites/${siteId}/integration/confirm?company_id=${companyId}`, { key, revision })

/* ── Раздел «Интеграции»: реестр и отчёт ─────────────────────────────────── */
export interface IntegrationStationCounts { selected: number; agreed: number; connected: number; pilot: number }
export interface IntegrationRow {
  id: string; projectNo: string | null; title: string | null; stage: string; stageLabel: string
  owner: string | null; nextAction: string | null; nextActionDue: string | null; overdue: boolean
  partner: string; legalEntity: string
  formats: ('information' | 'roaming')[]; directions: ('outgoing' | 'incoming')[]
  scenarios: (IntegrationStationCounts & { direction: 'outgoing' | 'incoming'; format: 'information' | 'roaming'; name: string })[]
  stations: IntegrationStationCounts
  pilotDecision: string; pilotOutcome: string; launchDate: string
  checklist: { required: number; closed: number; stale: number }
  tests: { total: number; required: number; passed: number; failed: number }
  reconciliation: { kind: string; period: string; state: 'match' | 'resolved' | 'diff' } | null
  launchOpen: boolean
  updatedAt: string | null
}
export interface IntegrationsPortfolio {
  items: IntegrationRow[]
  summary: {
    total: number; active: number; live: number; onHold: number; archived: number
    byStage: Record<string, number>
    stations: Record<string, IntegrationStationCounts & { projects: number }>
    partners: { partner: string; projects: number; selected: number; agreed: number; connected: number; stages: string[] }[]
    attention: { stale: string[]; overdue: string[]; noOwner: string[]; noScenario: string[]; testsFailed: string[]; reconDiff: string[]; launchOpen: string[] }
    pilots: { id: string; title: string | null; partner: string; decision: string; outcome: string }[]
  }
}
export const getIntegrationsPortfolio = (companyId: string) => get<IntegrationsPortfolio>('/api/sites/integrations', { company_id: companyId })
