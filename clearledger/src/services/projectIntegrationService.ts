import { get, patch, post } from './apiClient'
import type { ChargeDimensionStation } from './analyticsService'
import type { GateState } from './sitesService'

export const INTEGRATION_FORMATS = { information: 'Информационная', roaming: 'Роуминг', hybrid: 'Гибридная' }
export const INTEGRATION_DIRECTIONS = { outgoing: 'Наши ЭЗС в сервисе партнёра', incoming: 'ЭЗС партнёра в нашем приложении', both: 'Двусторонняя' }
export type IntegrationSection = 'partner' | 'commercial' | 'data' | 'technical' | 'work' | 'accounting'
export interface IntegrationScenario {
  id: string; name: string; direction: 'outgoing' | 'incoming'; format: 'information' | 'roaming'
  geography: string; restrictions: string; partnerNetwork: string
  selectedIds: string[]; agreedIds: string[]; connectedIds: string[]; pilotIds: string[]
}
export interface IntegrationDocument {
  id: string; kind: string; title: string; edition: string
  fileDocId: string; agreedDocId: string; signedDocId: string; signingEvidence: string
}
export interface IntegrationResult { comment: string; workRef: string; docId: string; notApplicable: boolean }
export type IntegrationData = Record<IntegrationSection, Record<string, string>> & {
  revision: number; scenarios: IntegrationScenario[]; documents: IntegrationDocument[]; contractIds: string[]
  results: Record<string, IntegrationResult>; dates: Record<string, { start: string; end: string }>
}
export interface IntegrationTask { key: string; label: string; stage: string; role: string; required?: boolean; section: IntegrationSection | 'scenarios' | 'documents' }
export interface IntegrationState {
  data: IntegrationData; tasks: IntegrationTask[]; gates: GateState[]
  phases: { code: string; label: string; term: string; stages: string[] }[]
}
export interface IntegrationStation extends ChargeDimensionStation { id: string; network: 'outgoing' | 'incoming'; group: string }

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
  updatedAt: string | null
}
export interface IntegrationsPortfolio {
  items: IntegrationRow[]
  summary: {
    total: number; active: number; live: number; onHold: number; archived: number
    byStage: Record<string, number>
    stations: Record<string, IntegrationStationCounts & { projects: number }>
    partners: { partner: string; projects: number; selected: number; agreed: number; connected: number; stages: string[] }[]
    attention: { stale: string[]; overdue: string[]; noOwner: string[]; noScenario: string[] }
    pilots: { id: string; title: string | null; partner: string; decision: string; outcome: string }[]
  }
}
export const getIntegrationsPortfolio = (companyId: string) => get<IntegrationsPortfolio>('/api/sites/integrations', { company_id: companyId })
