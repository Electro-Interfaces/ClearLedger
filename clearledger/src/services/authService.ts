/**
 * Сервис аутентификации — вызовы API auth.
 */

import * as api from './apiClient'

/** Краткая карточка компании (как в backend CompanyBrief, snake_case по проводу). */
export interface CompanyRef {
  id: string
  slug: string
  name: string
  short_name?: string | null
  color?: string | null
  profile_id: string
  role?: 'user' | 'admin'   // роль пользователя в этой компании
  modules?: string[] | null
  /** Юрлицо, закреплённое за участником правами; null = видит все. */
  own_organization_id?: string | null // RBAC: разрешённые модули; null/undefined = полный доступ
}

/** Ответ /api/auth/me — пользователь + доступные компании (мультитенантность). */
export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
  is_superadmin: boolean
  default_company_id?: string | null
  /** Фото профиля — одно на пространство, показывается везде, где виден человек. */
  avatar_url?: string | null
  /** Контакты — правит сам человек. */
  phone_mobile?: string | null
  phone_office?: string | null
  /** Имя IANA: по нему считается, когда человека можно трогать. */
  tz?: string
  /** Рабочее окно, «09:00». Вне его регламентное ждёт, а не будит. */
  work_start?: string
  work_end?: string
  /**
   * Место человека в пространстве — заполняет администратор.
   * party_type: internal — сотрудник организации пространства,
   *             partner  — сотрудник внешней компании,
   *             vendor   — поддержка платформы (особый статус и права).
   */
  position?: string | null
  party_type?: 'internal' | 'partner' | 'vendor' | null
  party_org?: string | null
  company_name?: string | null
  company_role?: string | null
  companies: CompanyRef[]
}

/** Базовый пользователь из login/register (без списка компаний). */
export interface BasicUser {
  id: string
  email: string
  name: string
  role: string
  company_id?: string | null
  is_superadmin?: boolean
  is_active?: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: BasicUser
}

/** Логин по email + пароль */
export async function login(email: string, password: string): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/login', { email, password })
  api.setToken(result.access_token)
  return result
}

/** Регистрация нового пользователя */
export async function register(data: {
  email: string
  name: string
  password: string
  company_id: string
  role?: string
}): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/register', data)
  api.setToken(result.access_token)
  return result
}

/** Получить текущего пользователя + список доступных компаний по токену */
export async function getMe(): Promise<AuthUser> {
  return api.get<AuthUser>('/api/auth/me')
}

/** Продлить токен (выдаёт новый JWT) */
export async function refreshToken(): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/refresh')
  api.setToken(result.access_token)
  return result
}

/** Выход */
export function logout(): void {
  api.clearToken()
}

/** Запросить восстановление пароля — письмо со ссылкой на email. */
export async function forgotPassword(email: string): Promise<void> {
  await api.post('/api/auth/forgot-password', { email })
}

export interface ResetPreview {
  email: string
}

/** Проверить токен восстановления (валиден/истёк) перед формой. */
export async function getResetPreview(token: string): Promise<ResetPreview> {
  return api.get<ResetPreview>(`/api/auth/reset-password/${encodeURIComponent(token)}`)
}

/** Установить новый пароль по токену из письма. */
export async function resetPassword(token: string, password: string): Promise<void> {
  await api.post('/api/auth/reset-password', { token, password })
}
