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

/** Состояние обращения — общий словарь обеих сторон (docs/BRIDGE.md §4.1). */
export type TopicState = 'new' | 'in_progress' | 'waiting' | 'resolved' | 'closed'

export interface PartnerTopic {
  code: string
  title: string
  state: TopicState
  /** Номер у той стороны: для клиента — номер заявки поддержки. */
  number: string | null
  subjectLabel: string | null
  createdAt: string | null
  lastMessageAt: string | null
}

export const TOPIC_STATE_NAME: Record<TopicState, string> = {
  new: 'Принято',
  in_progress: 'В работе',
  waiting: 'Ждём вас',
  resolved: 'Решено',
  closed: 'Закрыто',
}

export const listTopics = (code: string, companyId: string) =>
  get<{ items: PartnerTopic[]; general: number }>(
    `/api/partner-space/${encodeURIComponent(code)}/topics`, { company_id: companyId })

export const openTopic = (
  code: string, companyId: string,
  body: { title: string; body: string; subject_kind?: string; subject_ref?: string; subject_label?: string },
) =>
  post<{ code: string; state: TopicState; delivered: boolean; error: string | null }>(
    `/api/partner-space/${encodeURIComponent(code)}/topics?company_id=${encodeURIComponent(companyId)}`,
    body)

export const topicFeed = (code: string, topicCode: string, companyId: string) =>
  get<{
    topic: { code: string; title: string; state: TopicState; number: string | null; subjectLabel: string | null }
    messages: PartnerMessage[]
  }>(
    `/api/partner-space/${encodeURIComponent(code)}/topics/${encodeURIComponent(topicCode)}/feed`,
    { company_id: companyId })

export const sendToTopic = (code: string, topicCode: string, companyId: string, body: string) =>
  post<{ id: string; delivered: boolean; error: string | null }>(
    `/api/partner-space/${encodeURIComponent(code)}/topics/${encodeURIComponent(topicCode)}/message`
    + `?company_id=${encodeURIComponent(companyId)}`, { body })

export const listPartnerSpaces = (companyId: string) =>
  get<{ items: PartnerSpaceRef[] }>('/api/partner-space/spaces', { company_id: companyId })

export const partnerFeed = (code: string, companyId: string) =>
  get<{ partner: { code: string; name: string; role: PartnerRole; linked: boolean }; messages: PartnerMessage[] }>(
    `/api/partner-space/${encodeURIComponent(code)}/feed`, { company_id: companyId })

export const sendToPartner = (code: string, companyId: string, body: string) =>
  post<{ id: string; delivered: boolean; error: string | null }>(
    `/api/partner-space/${encodeURIComponent(code)}/message?company_id=${encodeURIComponent(companyId)}`,
    { body })

/** Пропуск в пространство клиента: заходим туда своей учётной записью. */
export const visitPartnerSpace = (code: string, companyId: string) =>
  post<{ url: string; space: string; name: string }>(
    `/api/partner-space/${encodeURIComponent(code)}/visit?company_id=${encodeURIComponent(companyId)}`)
