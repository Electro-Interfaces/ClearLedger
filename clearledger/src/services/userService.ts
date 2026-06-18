/**
 * Управление пользователями компании (админ) и профилем организации.
 * Работает только в API-режиме (требует бэкенд /api/users, /api/companies).
 */
import { get, post, patch, del } from './apiClient'

export interface MembershipRef {
  slug: string
  name: string
  role: 'user' | 'admin'
}

export interface AdminUser {
  id: string
  email: string
  name: string
  role: 'user' | 'admin'   // роль в контексте запроса (компании) или глобальная
  is_superadmin: boolean
  companies: MembershipRef[]
}

export async function listUsers(companyId: string): Promise<AdminUser[]> {
  return get<AdminUser[]>('/api/users', { company_id: companyId })
}

/** Все пользователи системы (только суперадмин) — для админ-раздела. */
export async function listAllUsers(): Promise<AdminUser[]> {
  return get<AdminUser[]>('/api/users')
}

/** Выдать пользователю членство в компании. */
export async function grantCompany(userId: string, companyId: string): Promise<AdminUser> {
  return post<AdminUser>(`/api/users/${userId}/companies`, { company_id: companyId })
}

/** Отозвать членство пользователя в компании. */
export async function revokeCompany(userId: string, companyId: string): Promise<void> {
  await del(`/api/users/${userId}/companies/${encodeURIComponent(companyId)}`)
}

export async function createUser(data: {
  companyId: string
  email: string
  name: string
  password: string
  role: 'user' | 'admin'
}): Promise<AdminUser> {
  return post<AdminUser>('/api/users', {
    company_id: data.companyId,
    email: data.email,
    name: data.name,
    password: data.password,
    role: data.role,
  })
}

export async function updateUser(
  id: string,
  data: { companyId: string; name?: string; role?: 'user' | 'admin' },
): Promise<AdminUser> {
  return patch<AdminUser>(`/api/users/${id}`, {
    company_id: data.companyId,
    name: data.name,
    role: data.role,
  })
}

export async function removeUser(id: string, companyId: string): Promise<void> {
  // company_id — query-параметр
  await del(`/api/users/${id}?company_id=${encodeURIComponent(companyId)}`)
}

// ─── Профиль организации ───────────────────────────────────────────────────
export interface OrgProfile {
  id: string
  name: string
  slug: string
  short_name: string | null
  profile_id: string
  color: string | null
  inn: string | null
}

export async function updateCompany(
  id: string,
  data: { name?: string; short_name?: string; profile_id?: string; color?: string; inn?: string },
): Promise<OrgProfile> {
  return patch<OrgProfile>(`/api/companies/${id}`, data)
}

/** Все компании (суперадмину — все; иначе свои). */
export async function listCompanies(): Promise<OrgProfile[]> {
  return get<OrgProfile[]>('/api/companies')
}

/** Создать (подключить) новую компанию — только суперадмин. */
export async function createCompany(data: {
  name: string
  slug: string
  short_name?: string
  profile_id: string
  color?: string
  inn?: string
}): Promise<OrgProfile> {
  return post<OrgProfile>('/api/companies', data)
}
