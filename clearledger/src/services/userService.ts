/**
 * Управление пользователями компании (админ) и профилем организации.
 * Работает только в API-режиме (требует бэкенд /api/users, /api/companies).
 */
import { get, post, patch, put, del } from './apiClient'
import type { BusinessGrant } from './businessAccessService'

export interface MembershipRef {
  slug: string
  name: string
  role: 'user' | 'admin'
  position?: string | null
}

export interface AdminUser {
  id: string
  email: string
  name: string             // ФИО
  role: 'user' | 'admin'   // роль в контексте запроса (компании) или глобальная
  position?: string | null // должность в контексте компании
  modules?: string[] | null // эффективные RBAC-модули; null = полный доступ
  role_id?: string | null   // назначенная именованная роль доступа
  role_name?: string | null // имя назначенной роли (для UI)
  // Принадлежность к пространству: свой сотрудник или внешний участник (подрядчик,
  // поставщик). Не права — «кто он»: видно в чатах, заявках, справочнике людей.
  party_type?: 'internal' | 'partner' | 'vendor' | null
  organization_id?: string | null    // кого представляет внешний участник
  organization_name?: string | null  // имя организации (для UI)
  // Скоуп данных: объекты, по которым человек видит данные; null = вся сеть компании.
  // Ортогонален правам: modules — какие экраны, object_scope — по каким объектам.
  object_scope?: string[] | null
  business_grants?: BusinessGrant[]
  // Основание допуска: договоры, по которым человек здесь работает. Не права и не
  // скоуп — справка «почему он в пространстве»; у своих сотрудников обычно пусто.
  contract_ids?: string[] | null
  // Подразделение штатной структуры: через него — руководитель и цепочка эскалации.
  department_id?: string | null
  department_name?: string | null
  is_superadmin: boolean
  last_seen_at?: string | null // последний вход/активность — для состава и карточки
  companies: MembershipRef[]
  has_station_pin?: boolean // задан ли PIN станции (вход на рабочем месте АЗС)
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
  position?: string
  /** Кем заводим: свой сотрудник (по умолчанию) или представитель компании-партнёра. */
  partyType?: 'internal' | 'partner' | 'vendor'
  organizationId?: string
}): Promise<AdminUser> {
  return post<AdminUser>('/api/users', {
    company_id: data.companyId,
    email: data.email,
    name: data.name,
    password: data.password,
    role: data.role,
    position: data.position || undefined,
    party_type: data.partyType,
    organization_id: data.organizationId || undefined,
  })
}

export async function updateUser(
  id: string,
  data: {
    companyId: string
    name?: string
    role?: 'user' | 'admin'
    position?: string
    partyType?: 'internal' | 'partner' | 'vendor'
    organizationId?: string          // '' → снять связь с организацией
    departmentId?: string            // '' → вне штатной структуры
  },
): Promise<AdminUser> {
  return patch<AdminUser>(`/api/users/${id}`, {
    company_id: data.companyId,
    name: data.name,
    role: data.role,
    position: data.position,
    party_type: data.partyType,
    organization_id: data.organizationId,
    department_id: data.departmentId,
  })
}

/** Назначить члену набор модулей доступа (RBAC). modules=null → полный доступ. */
export async function setMemberModules(
  id: string, companyId: string, modules: string[] | null,
): Promise<AdminUser> {
  return put<AdminUser>(`/api/users/${id}/modules`, { company_id: companyId, modules })
}

/** Назначить доступ члену: именованная роль или ad-hoc набор модулей. */
/** Ссылка сброса пароля — для передачи мессенджером, когда почта не доходит.
 *  Одноразовая, 24 часа; выдаётся админом компании, попадает в журнал. */
export async function issueResetLink(
  id: string, companyId: string,
): Promise<{ reset_url: string; expires_at: string }> {
  return post(`/api/users/${id}/reset-link?company_id=${encodeURIComponent(companyId)}`)
}

export async function setMemberAccess(
  id: string, companyId: string,
  access: { mode: 'role'; roleId: string } | { mode: 'custom'; modules: string[] | null },
): Promise<AdminUser> {
  const body = access.mode === 'role'
    ? { company_id: companyId, mode: 'role', role_id: access.roleId }
    : { company_id: companyId, mode: 'custom', modules: access.modules }
  return put<AdminUser>(`/api/users/${id}/access`, body)
}

/** Скоуп данных члена: объекты, по которым он видит данные. null/пусто = вся сеть. */
export async function setMemberScope(
  id: string, companyId: string, objectScope: string[] | null,
): Promise<AdminUser> {
  return put<AdminUser>(`/api/users/${id}/scope`, {
    company_id: companyId, object_scope: objectScope,
  })
}

/** Бизнес-роли Магазина. В отличие от одной роли доступа, grant складываются. */
export async function setBusinessGrants(
  id: string, companyId: string, grants: BusinessGrant[],
): Promise<AdminUser> {
  return put<AdminUser>(`/api/users/${id}/business-grants`, {
    company_id: companyId, grants,
  })
}

/** PIN станции члена: короткий код входа на рабочем месте АЗС (edge-агент).
 *  Пустой pin снимает PIN — быстрый вход отключается, остаётся вход по паролю. */
export async function setStationPin(
  id: string, companyId: string, pin: string,
): Promise<AdminUser> {
  return put<AdminUser>(`/api/users/${id}/station-pin`, {
    company_id: companyId, pin,
  })
}

/** Основание допуска: договоры, по которым участник работает. Справка, а не права. */
export async function setMemberContracts(
  id: string, companyId: string, contractIds: string[] | null,
): Promise<AdminUser> {
  return put<AdminUser>(`/api/users/${id}/contracts`, {
    company_id: companyId, contract_ids: contractIds,
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
