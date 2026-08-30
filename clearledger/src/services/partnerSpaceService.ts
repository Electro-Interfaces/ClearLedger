/**
 * Разговор с пространством-партнёром (docs/CORE.md, мост пространств).
 *
 * У клиента это «Техподдержка»: он пишет нам, не выходя из своего контура. У нас —
 * та же переписка с другой стороны, плюс зеркало в очереди Координатора. Ручки
 * общие, потому что событие одно.
 */
import { get, post } from './apiClient'

/** Кто нам это пространство: `client` — мы его обслуживаем, `vendor` — оно нас. */
export type PartnerRole = 'client' | 'vendor'

export interface PartnerSpaceRef {
  code: string
  name: string
  role: PartnerRole
  isActive: boolean
  /** Связь включена: есть адрес и ключ. Ключ наружу не отдаётся никогда. */
  linked: boolean
  lastSeenAt: string | null
}

export interface PartnerMessage {
  id: string
  direction: 'in' | 'out'
  body: string
  authorName: string | null
  authorEmail: string | null
  createdAt: string | null
  delivered: boolean
  error: string | null
}

export const listPartnerSpaces = (companyId: string) =>
  get<{ items: PartnerSpaceRef[] }>('/api/partner-space/spaces', { company_id: companyId })

export const partnerFeed = (code: string, companyId: string) =>
  get<{ partner: { code: string; name: string; role: PartnerRole; linked: boolean }; messages: PartnerMessage[] }>(
    `/api/partner-space/${encodeURIComponent(code)}/feed`, { company_id: companyId })

export const sendToPartner = (code: string, companyId: string, body: string) =>
  post<{ id: string; delivered: boolean; error: string | null }>(
    `/api/partner-space/${encodeURIComponent(code)}/message?company_id=${encodeURIComponent(companyId)}`,
    { body })
