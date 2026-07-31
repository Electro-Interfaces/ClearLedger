/**
 * Именованные роли доступа (hybrid RBAC) + журнал аудита.
 * API-режим: /api/roles, /api/audit.
 */
import { get, post, patch, del } from './apiClient'

export interface CompanyRole {
  id: string
  name: string
  modules: string[] | null   // null = все модули
  is_system: boolean
  members_count: number
}

export async function listRoles(companyId: string): Promise<CompanyRole[]> {
  return get<CompanyRole[]>('/api/roles', { company_id: companyId })
}

export async function createRole(
  companyId: string, name: string, modules: string[] | null,
): Promise<CompanyRole> {
  return post<CompanyRole>('/api/roles', { company_id: companyId, name, modules })
}

export async function updateRole(
  id: string, companyId: string, name: string, modules: string[] | null,
): Promise<CompanyRole> {
  return patch<CompanyRole>(`/api/roles/${id}`, { company_id: companyId, name, modules })
}

export async function deleteRole(id: string, companyId: string): Promise<void> {
  await del(`/api/roles/${id}?company_id=${encodeURIComponent(companyId)}`)
}

// ─── Журнал аудита ───────────────────────────────────────────────────────────
export interface ActivitySummary {
  days: number
  totals: {
    logins: number; logins_7d: number; failed: number
    connected: number; removed: number; unique_people: number
  }
  invitations: { pending: number; expired: number; accepted: number }
  people: {
    user_id: string; name: string; active_days: number; logins: number
    last_at: string | null
    /** Процент активности: доля дней окна, когда человек что-то делал. */
    share: number
  }[]
}

/** Динамика доступа и активность людей — для «Обзора» и «Сотрудников». */
export async function activitySummary(companyId: string, days = 30): Promise<ActivitySummary> {
  return get<ActivitySummary>('/api/audit/activity', { company_id: companyId, days: String(days) })
}

export interface AuditEntry {
  id: string
  company_id: string
  user_id?: string | null
  user_name?: string | null
  action: string
  details?: string | null
  timestamp: string
}

export async function listAudit(companyId: string, limit = 100, opts: {
  userId?: string
  dateFrom?: string   // ISO-дата: события С этого дня
  dateTo?: string     // ISO-дата: события ПО этот день (включительно)
  order?: 'asc' | 'desc'
} = {}): Promise<AuditEntry[]> {
  const params: Record<string, string> = { company_id: companyId, limit: String(limit) }
  if (opts.userId) params.user_id = opts.userId
  if (opts.dateFrom) params.date_from = opts.dateFrom
  // Бэкенд сравнивает timestamp с этой строкой: чтобы «по 15-е» включало само 15-е,
  // границу сдвигаем на конец дня.
  if (opts.dateTo) params.date_to = `${opts.dateTo}T23:59:59`
  if (opts.order) params.order = opts.order
  return get<AuditEntry[]>('/api/audit', params)
}
