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
}

/**
 * Каталог приложений экосистемы для лаунчера.
 * `enabled` — есть что показать (мосты видны и без ключа SSO);
 * `sso_enabled` — настроен ли единый вход.
 */
export async function listSsoApps(): Promise<{ enabled: boolean; sso_enabled: boolean; apps: SsoApp[] }> {
  return get<{ enabled: boolean; sso_enabled: boolean; apps: SsoApp[] }>('/api/sso/apps')
}

/** Выпустить handoff-токен для приложения и получить URL перехода (открывать в новой вкладке). */
export async function authorizeApp(code: string, companyId?: string): Promise<string> {
  const r = await get<{ url: string; app: string; expires_in: number }>(
    '/api/sso/authorize', { app: code, company_id: companyId },
  )
  return r.url
}
