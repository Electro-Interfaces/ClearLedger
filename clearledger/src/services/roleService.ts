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
export interface AuditEntry {
  id: string
  company_id: string
  user_id?: string | null
  user_name?: string | null
  action: string
  details?: string | null
  timestamp: string
}

export async function listAudit(companyId: string, limit = 100): Promise<AuditEntry[]> {
  return get<AuditEntry[]>('/api/audit', { company_id: companyId, limit: String(limit) })
}
