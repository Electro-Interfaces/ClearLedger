import { openContextChat, resolveWorkContext, retryWorkResult } from './workContextService'
import { get, post, put } from './apiClient'
import type { SiteTrackItem } from './sitesService'

export type WorkLink = { kind: 'doc' | 'task'; id: string }
export type ProjectEvent = {
  id: string; kind: string; text: string; author: string | null; at: string
  changes: { room_id?: string; message_id?: string; work_ref?: string; deadline?: { from: string; to: string }; budget?: { from: number; to: number } }[] | null
}
export interface ProjectScenario {
  name: string; stage: string; fields: Record<string, string>; values: Record<string, string>
  steps: { code: string; name: string; result: string; requirement: string; fields?: string[] }[]
  templates: Record<string, string>
  evidence: Record<string, { ref: string; by: string; at: string; revision: number | null }>
}
export interface ProjectOverview {
  work: { items: SiteTrackItem[]; total: number; waiting: number }
  pending_results?: { items: SiteTrackItem[]; total: number }
  next_work: { id?: string; kind?: 'doc' | 'task'; title?: string; due_at?: string; status?: string; unavailable?: boolean } | null
  external_wait: { waiting_for: string; owner_id: string; owner_name: string; follow_up: string } | null
  scenario: ProjectScenario | null; unread: number; target_date?: string | null; budget?: number | null
  team: { id: string; name: string; role: string }[]; events: ProjectEvent[]
}
const base = (companyId: string, siteId: string, action = '') =>
  `/api/project-workspace/${siteId}${action}?company_id=${encodeURIComponent(companyId)}`
export const getProjectOverview = (companyId: string, siteId: string) => get<ProjectOverview>(base(companyId, siteId))
export const openProjectChat = async (companyId: string, siteId: string) => {
  const context = await resolveWorkContext(companyId, `site:${siteId}`)
  return openContextChat(companyId, context.ref, { purpose: 'main', audience: 'internal', participant_ids: context.suggested_people?.map((p) => p.id) })
}
export const linkProjectWork = (companyId: string, siteId: string, body: { kind: 'doc' | 'task' | 'message'; id: string }) => post(base(companyId, siteId, '/link'), body)
export const unlinkedWork = (companyId: string, q: string, offset = 0, onlyUnlinked = true) => get<{ items: SiteTrackItem[]; total: number }>('/api/project-workspace/unlinked', { company_id: companyId, q, offset, only_unlinked: onlyUnlinked ? 1 : 0 })
export const setProjectNext = (companyId: string, siteId: string, body: { work?: WorkLink; waiting_for?: string; owner_id?: string; follow_up?: string }) => put(base(companyId, siteId, '/next'), body)
export const recordProjectDecision = (companyId: string, siteId: string, body: { text: string; source_message_id?: string; work?: WorkLink; deadline?: string; budget?: number }) => post(base(companyId, siteId, '/decision'), body)
export const retryProjectResult = (companyId: string, _siteId: string, requestId: string) => retryWorkResult(companyId, requestId)
export const addMessageFile = (companyId: string, siteId: string, messageId: string) => post(base(companyId, siteId, '/file'), { message_id: messageId })
export const promoteProjectFile = (companyId: string, siteId: string, fileId: string, kindId: string, title: string) => post<{ doc_id: string }>(base(companyId, siteId, '/promote'), { file_id: fileId, kind_id: kindId, title })
export const updateProjectScenario = (companyId: string, siteId: string, body: { fields: Record<string, string>; templates?: Record<string, string | null>; advance?: boolean; expected_stage?: string; evidence?: WorkLink }) => put(base(companyId, siteId, '/scenario'), body)
export const projectWorkHref = (work: WorkLink) => work.kind === 'doc' ? `/docs?view=all&doc=${work.id}` : `/docs/company?view=errands&task=${work.id}`
