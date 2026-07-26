/**
 * Подключения пространства — единый список источников данных компании.
 *
 * Собирается Ядром на лету: файловые каналы Учёта + платформенные сервисы + живые
 * интеграции приложений (Координатор отвечает по служебному каналу). Копии в Ядре нет —
 * состояние коннектора меняется каждые несколько минут, снимок врал бы.
 */
import { get } from './apiClient'

export interface SpaceConnector {
  key: string
  /** Код приложения-владельца: ledger | support | core. */
  app: string
  app_name: string
  provider: string
  /** Человеческий вид подключения: «Файловый канал», «Внешний трекер», «Канал обращений». */
  kind: string
  label: string
  /** Что приносит в пространство. */
  brings: string
  direction: string
  status: string
  enabled: boolean
  last_sync_at: string | null
  last_error: string | null
  records: number | null
  files: number
  /** Куда вести настраивать: маршрут этого же SPA… */
  settings_route?: string
  /** …или код приложения (открывается единым входом). */
  settings_app?: string
}

export interface SpaceConnectorsResponse {
  companyId: string
  connectors: SpaceConnector[]
  /** Приложения, которые не ответили: список честнее молчания. */
  problems: { app: string; app_name: string; error: string }[]
  total: number
}

export async function listSpaceConnectors(companyId: string): Promise<SpaceConnectorsResponse> {
  return get<SpaceConnectorsResponse>('/api/registry/connectors', { company_id: companyId })
}
