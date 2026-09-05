import { get, post } from './apiClient'
import { addDays, format } from 'date-fns'

export interface WorkContext {
  ref: string; application: string; title: string; url: string; object_id?: string | null
  defaults: { responsible_id?: string | null; title?: string | null; template_ids?: string[]; due_days?: number | null }
  suggested_people?: { id: string; name: string }[]
  actions: { code: string; label: string; text_required?: boolean; requires_file?: boolean }[]
}
export const listWorkContexts = (companyId: string) => get<{ providers: { prefix: string; label: string; application: string }[] }>('/api/work-contexts', { company_id: companyId })
export const searchWorkContexts = (companyId: string, prefix: string, q: string) => get<{ items: { ref: string; title: string; hint: string }[] }>('/api/work-contexts/search', { company_id: companyId, prefix, q })
export const resolveWorkContext = (companyId: string, ref: string) => get<WorkContext>('/api/work-contexts/resolve', { company_id: companyId, ref })
export const runContextAction = (companyId: string, body: { ref: string; action: string; message_id: string; text?: string }) => post(`/api/work-contexts/action?company_id=${encodeURIComponent(companyId)}`, body)
export const openContextChat = (companyId: string, ref: string, options: { purpose?: string; audience?: 'internal' | 'mixed'; participant_ids?: string[] } = {}) => post<{ room_id: string }>(`/api/work-contexts/room?company_id=${encodeURIComponent(companyId)}`, { ref, ...options })
export const getWorkOrigin = (companyId: string, kind: 'doc' | 'task', id: string) => get<{ origin: { room_id: string; message_id: string } | null }>(`/api/work-contexts/work/${kind}/${id}/origin`, { company_id: companyId })
export type MessageWork = { id: string; kind: 'doc' | 'task'; title: string; state: string; state_name: string; message_id: string }
export const getRoomWork = (companyId: string, roomId: string, messages: string[]) => get<{ items: MessageWork[] }>(`/api/work-contexts/rooms/${roomId}/work`, { company_id: companyId, messages: messages.slice(-200).join(',') })
export const workHref = (work: { kind: 'doc' | 'task'; id: string }) => work.kind === 'doc' ? `/docs?view=all&doc=${work.id}` : `/docs/company?view=errands&task=${work.id}`
export const contextDueDate = (context: WorkContext) => context.defaults.due_days == null ? '' : format(addDays(new Date(), context.defaults.due_days), 'yyyy-MM-dd')

export const retryWorkResult = (companyId: string, id: string) => post(`/api/work-contexts/results/${id}/retry?company_id=${encodeURIComponent(companyId)}`, {})
export const getWorkResults = (companyId: string, kind: 'doc' | 'task', id: string) => get<{ items: { id: string; title: string; url: string | null; outcome: string; pending: boolean; error: boolean; attempts: number; created_at: string; delivered_at: string | null }[] }>(`/api/work-contexts/work/${kind}/${id}/results`, { company_id: companyId })
