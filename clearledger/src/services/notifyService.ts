/**
 * Оповещения пространства: на что подписана организация и куда это доставлять.
 *
 * Каталог категорий приходит с сервера (`notify_catalog`) — интерфейс не держит свою
 * копию, иначе в таблице появились бы галочки за событиями, которых система не порождает.
 */
import { get, post, put } from './apiClient'

export interface NotifyCategory {
  code: string
  label: string
  description: string
  prefixes: string[]
  default_on: boolean
}

export interface NotifyRule {
  id?: string
  category: string
  enabled: boolean
  via_chat: boolean
  via_email: boolean
  /** null — администраторы организации (состав следует за составом админов). */
  recipients: string[] | null
}

export interface NotifyTestResult {
  category: string
  skipped?: boolean
  reason?: string
  recipients?: number
  chat?: boolean
  email?: boolean
}

export async function getNotifyCatalog(): Promise<NotifyCategory[]> {
  return get<NotifyCategory[]>('/api/notifications/catalog')
}

export async function listNotifyRules(companyId: string): Promise<NotifyRule[]> {
  return get<NotifyRule[]>('/api/notifications', { company_id: companyId })
}

export async function saveNotifyRules(companyId: string, rules: NotifyRule[]): Promise<NotifyRule[]> {
  return put<NotifyRule[]>(`/api/notifications?company_id=${encodeURIComponent(companyId)}`,
    rules.map((r) => ({
      category: r.category, enabled: r.enabled,
      via_chat: r.via_chat, via_email: r.via_email,
      recipients: r.recipients && r.recipients.length ? r.recipients : null,
    })))
}

/** Проверочное оповещение тем же путём, каким пойдёт настоящее. */
export async function testNotifyDelivery(
  companyId: string, category: string,
): Promise<NotifyTestResult> {
  return post<NotifyTestResult>(
    `/api/notifications/test?company_id=${encodeURIComponent(companyId)}`
    + `&category=${encodeURIComponent(category)}`, {})
}
