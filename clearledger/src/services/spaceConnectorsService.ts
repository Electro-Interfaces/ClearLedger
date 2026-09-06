/**
 * Подключения пространства — единый список источников данных компании.
 *
 * Собирается Ядром на лету: файловые каналы Учёта + платформенные сервисы + живые
 * интеграции приложений (Координатор отвечает по служебному каналу). Копии в Ядре нет —
 * состояние коннектора меняется каждые несколько минут, снимок врал бы.
 */
import { get, post, patch } from './apiClient'

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
  /** Кто инициирует обмен: 'us' — мы ходим во внешнюю систему, 'them' — она
   *  стучится к нам (вебхуки, входящие ключи), 'both' — платформенный сервис. */
  initiator?: 'us' | 'them' | 'both'
  status: string
  enabled: boolean
  last_sync_at: string | null
  /** Когда подключение последний раз ПРОВЕРЯЛИ. Не то же, что обмен: у источника
   *  обмен ведут каналы поверх него, и подменять одно другим витрине нельзя. */
  last_test_at?: string | null
  last_error: string | null
  records: number | null
  files: number
  /** Куда вести настраивать: маршрут этого же SPA… */
  settings_route?: string
  /** …или код приложения (открывается единым входом). */
  settings_app?: string
  management?: { id: string } | null
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

export interface ConnectorField {
  key: string
  group: 'endpoint' | 'config' | 'credentials'
  label: string
  secret?: boolean
  required?: boolean
  readOnly?: boolean
  list?: boolean
  fallback?: string
  placeholder?: string
  hint?: string
  choices?: {value:string;label:string}[]
  choicesFrom?: 'line'|'group'
}

export interface MangoDirectory {
  entries:{kind:'user'|'group'|'line';external_id:string;extension:string;name:string;email:string}[]
  staff:{id:string;name:string;email:string}[]
  bindings:{extension:string;user_id:string;can_call:boolean}[]
  synced_at:string|null
}

export interface ManagedConnectorProvider {
  app: string
  app_name: string
  provider: string
  title: string
  intro: string
  owner_base_url: string
  fields: ConnectorField[]
  actions: { code: string; label: string }[]
}

export interface ManagedConnectorState {
  directory?:MangoDirectory
  id: string
  provider: string
  label: string
  enabled: boolean
  configured: boolean
  values: Record<string, string | string[]>
  secrets: Record<string, boolean>
  status: string
  last_sync_at?: string | null
  last_error?: string | null
  last_check?: { ok: boolean; at: string; message: string } | null
  webhook_path?: string | null
  owner_base_url: string
}

export interface ManagedConnectorInput {
  id?: string
  provider?: string
  label: string
  enabled: boolean
  values: Record<string, string | string[]>
  credentials: Record<string, string | null>
}

const managementPath = (companyId: string, app: string, tail = '') =>
  `/api/registry/connectors/managed/${encodeURIComponent(app)}${tail}?company_id=${encodeURIComponent(companyId)}`

export const managedConnectorService = {
  catalog: (companyId: string) => get<{ providers: ManagedConnectorProvider[]; problems: { app: string; message: string }[] }>(
    '/api/registry/connectors/catalog', { company_id: companyId }),
  read: (companyId: string, app: string, id: string) => get<ManagedConnectorState>(managementPath(companyId, app, `/${encodeURIComponent(id)}`)),
  create: (companyId: string, app: string, body: ManagedConnectorInput) => post<ManagedConnectorState>(managementPath(companyId, app), body),
  update: (companyId: string, app: string, id: string, body: ManagedConnectorInput) => patch<ManagedConnectorState>(managementPath(companyId, app, `/${encodeURIComponent(id)}`), body),
  action: (companyId: string, app: string, id: string, action: string,body:Record<string,unknown>={}) => post<{ ok: boolean; at?: string; message: string }>(
    managementPath(companyId, app, `/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`), body),
}
