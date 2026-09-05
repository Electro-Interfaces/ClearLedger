import { get, post, put } from './apiClient'

export interface ScenarioStep {
  code: string; name: string; result: string; requirement: 'done' | 'approved' | 'signed'
  fields: string[]; responsible_id: string | null; template_id: string | null; due_days: number | null
}
export interface ScenarioDefinition {
  name: string; fields: Record<string, string>; steps: ScenarioStep[]
  message_actions: ('discussion' | 'decision' | 'file')[]
}
export interface ScenarioSettings {
  kind: string; revision: number; version: number
  published: ScenarioDefinition; draft: ScenarioDefinition | null
  published_at?: string; updated_at?: string
  history: { version: number; definition: ScenarioDefinition; published_at?: string | null }[]
  readiness: { ready: boolean; checks: { key: string; ok: boolean; message: string }[] }
}
const base = (companyId: string, suffix = '') => `/api/project-scenarios${suffix}?company_id=${encodeURIComponent(companyId)}`
export const getProjectScenarios = (companyId: string) => get<{ can_manage: boolean; demo_available: boolean; items: ScenarioSettings[] }>(base(companyId))
export const prepareScenarioDemo = (companyId: string) => post<{ site_id: string; created: boolean }>(base(companyId, '/demo'), {})
export const saveScenarioDraft = (companyId: string, kind: string, revision: number, definition: ScenarioDefinition) =>
  put<ScenarioSettings>(base(companyId, `/${kind}/draft`), { expected_revision: revision, definition })
export const publishScenario = (companyId: string, kind: string, revision: number) =>
  post<ScenarioSettings>(base(companyId, `/${kind}/publish`), { expected_revision: revision })
