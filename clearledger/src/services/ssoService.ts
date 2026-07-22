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
}

/** Каталог приложений экосистемы для лаунчера. enabled=false → SSO не настроен (нет ключа). */
export async function listSsoApps(): Promise<{ enabled: boolean; apps: SsoApp[] }> {
  return get<{ enabled: boolean; apps: SsoApp[] }>('/api/sso/apps')
}

/** Выпустить handoff-токен для приложения и получить URL перехода (открывать в новой вкладке). */
export async function authorizeApp(code: string, companyId?: string): Promise<string> {
  const r = await get<{ url: string; app: string; expires_in: number }>(
    '/api/sso/authorize', { app: code, company_id: companyId },
  )
  return r.url
}
