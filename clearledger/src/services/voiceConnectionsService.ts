/** Общие настройки связей; секреты остаются у приложения-владельца. */
import { get, post } from './apiClient'
import { authorizeApp } from './ssoService'

export type ConnectionSource = 'connector' | 'config' | 'env' | 'environment' | 'missing'
export interface ProviderConnection {
  id: string | null
  provider: 'megafon' | 'mango' | 'asterisk'
  enabled: boolean
  status: string
  configured: boolean
  endpoint: string | null
  sources: Partial<Record<'endpoint' | 'api_key' | 'crm_token' | 'webhook_secret', ConnectionSource | null>>
  readiness: { history?: { configured: boolean; enabled: boolean } | null; events?: { configured: boolean; enabled: boolean } | null }
  webhook_path: string | null
  last_sync_at: string | null
  last_error: string | null
}

function owned<T extends { company_id: string }>(data: T, companyId: string) {
  if (!companyId || data.company_id !== companyId) throw new Error('Ответ относится к другой компании. Обновите страницу.')
  return data
}

export const connections = async (cid: string) => owned(await get<{ company_id: string; connections: ProviderConnection[] }>('/api/voice/connections'), cid)
export const checkProvider = async (cid: string, id: string | null) => owned(await post<{ company_id: string; ok: boolean; at: string; message: string }>('/api/voice/connections/check', { connector_id: id }), cid)

export async function providerSettings(companyId: string, provider: 'megafon' | 'mango' | 'asterisk') {
  const target = new URL(await authorizeApp('support', companyId), window.location.origin)
  // Токен остаётся во фрагменте штатного SSO; назначение выбирается из фиксированных путей.
  const hash = new URLSearchParams(target.hash.replace(/^#/, ''))
  hash.set('next', `/admin/connectors?provider=${provider}`)
  target.hash = hash.toString()
  window.location.assign(target.href)
}

export function ccSettingsUrl(issuer: string | null | undefined) {
  if (!issuer) return null
  try {
    const url = new URL(issuer)
    if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) return null
    url.hash = '/admin/connections'
    return url.href
  } catch { return null }
}
