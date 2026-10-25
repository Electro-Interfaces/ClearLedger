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
  own_organization_id?: string | null
  /** Смотрит ли человек за чужой работой в этом пространстве: администратор —
   *  за всей, руководитель подразделения — за своей веткой. От этого зависит,
   *  показывать ли раздел «Компания». */
  oversees?: boolean // RBAC: разрешённые модули; null/undefined = полный доступ
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
  /** Куда присылать уведомления о поручениях: secretary | notices | email. */
  task_notify?: string[]
  /** Виды писем, которые человек согласен получать (notify.EMAIL_KINDS). */
  email_notify?: string[]
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
export async function login(email: string, password: string, otp?: string): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/login', otp ? { email, password, otp } : { email, password })
  api.setToken(result.access_token)
  return result
}

/**
 * Сессия демо-показа: пространство открыли из кабинета сайта по одноразовому
 * пропуску, и спрашивать пароль уже не у кого. Ручка отвечает только на стенде
 * (там задан демо-пользователь) и только через кромку кабинета.
 */
export async function demoSession(): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/demo-session', {})
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

/** Выход: токен из браузера и метка входа (HttpOnly cookie — её снимает только сервер). */
export function logout(): void {
  api.clearToken()
  void fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => { /* метка истечёт сама */ })
}

/** Второй фактор входа (TOTP): состояние, начало настройки, включение, отключение. */
export const twofaStatus = () => api.get<{ enabled: boolean }>('/api/auth/2fa')
export const twofaSetup = () => api.post<{ secret: string; uri: string }>('/api/auth/2fa/setup')
export const twofaEnable = (code: string) => api.post<{ enabled: boolean }>('/api/auth/2fa/enable', { code })
export const twofaDisable = (code: string) => api.post<{ enabled: boolean }>('/api/auth/2fa/disable', { code })
/** Сервер просит код второго фактора: пароль верен, нужен код из приложения. */
export const OTP_REQUIRED = 'Введите код из приложения-аутентификатора'

/** Выйти со всех устройств: все выданные токены учётной записи гаснут (и этот). */
export async function logoutAll(): Promise<void> {
  try { await api.post('/api/auth/logout-all') } finally { api.clearToken() }
}

/** Сменить свой пароль, зная текущий.
 *  Сервер гасит прежние входы и сразу выдаёт токен этому окну — подменяем его,
 *  иначе человек выпадет на форму входа ровно в момент смены. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const r = await api.post<{ ok: boolean; access_token: string }>(
    '/api/auth/change-password', { currentPassword, newPassword })
  if (r.access_token) api.setToken(r.access_token)
}

export interface LoginEvent {
  action: string
  label: string
  at: string | null
  ip: string | null
  device: string | null
  newPlace: boolean
  failed: boolean
}

export interface PushDevice {
  id: string
  device: string
  showPreview: boolean
  since: string | null
}

/** Последние входы в учётную запись — свои, из журнала пространства. */
export const myLogins = () => api.get<{ logins: LoginEvent[] }>('/api/auth/security/logins')

/** Устройства, которым разрешены уведомления. */
export const myDevices = () => api.get<{ devices: PushDevice[] }>('/api/auth/security/devices')

/** Отвязать устройство от уведомлений. */
export const revokeDevice = (id: string) =>
  api.del<void>(`/api/auth/security/devices/${encodeURIComponent(id)}`)

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
