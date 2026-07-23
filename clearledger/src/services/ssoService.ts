/**
 * Клиент SSO Ядра экосистемы (Фаза 0). Ledger — временный провайдер идентичности:
 * лаунчер получает каталог приложений и, по клику, короткоживущий URL перехода с
 * handoff-токеном. Бэкенд: routers/sso_router.py (вызывается ФРОНТОМ с bearer, не
 * редиректом — иначе токен не долетел бы).
 */
import { get } from './apiClient'

export interface SsoApp {
  code: string
  name: string
  base_url: string
  callback: string
  icon: string
  /** sso — вход по handoff-токену; link — мост, открываем по ссылке (своя авторизация). */
  mode?: 'sso' | 'link'
  /** Слой рабочего стола: service — универсальный сервис контейнера; app — приложение. */
  layer?: 'service' | 'app'
}

export interface SsoCatalog {
  /** есть что показать (мосты/чат видны и без ключа SSO) */
  enabled: boolean
  /** настроен ли единый вход (handoff-приложения) */
  sso_enabled: boolean
  /** доступен ли универсальный сервис «Чат» (Matrix) — плитка в слое сервисов */
  chat_enabled: boolean
  apps: SsoApp[]
  /** коды приложений, доступных по роли в компании (RBAC-гейт стола); null = не ограничено */
  allowed_apps: string[] | null
}

/** Каталог приложений экосистемы для рабочего стола. companyId — для RBAC-гейта по роли. */
export async function listSsoApps(companyId?: string): Promise<SsoCatalog> {
  return get<SsoCatalog>('/api/sso/apps', companyId ? { company_id: companyId } : undefined)
}

/** Выпустить handoff-токен для приложения и получить URL перехода (открывать в новой вкладке). */
export async function authorizeApp(code: string, companyId?: string): Promise<string> {
  const r = await get<{ url: string; app: string; expires_in: number }>(
    '/api/sso/authorize', { app: code, company_id: companyId },
  )
  return r.url
}
