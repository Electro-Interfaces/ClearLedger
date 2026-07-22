/**
 * Клиент серверного реестра приложений/модулей Ядра экосистемы.
 * Заменяет клиентский localStorage-демо (moduleConnectionService) — «что подключено
 * компании» теперь серверная конфигурация. Бэкенд: routers/app_registry_router.py.
 */
import { get, put } from './apiClient'

export interface AppModuleRec {
  code: string
  name: string
  isCore: boolean
  enabled: boolean
}

export interface CompanyAppRec {
  id: string
  code: string
  name: string
  description?: string | null
  baseUrl?: string | null
  icon?: string | null
  enabled: boolean
  modules: AppModuleRec[]
}

/** Приложения и модули компании с эффективным признаком enabled. */
export async function listCompanyApps(companyId: string): Promise<CompanyAppRec[]> {
  const r = await get<{ apps: CompanyAppRec[] }>('/api/registry/company-apps', { company_id: companyId })
  return r.apps
}

/** Включить/выключить приложение компании (только админ компании/суперадмин). */
export async function setCompanyApp(companyId: string, appId: string, enabled: boolean): Promise<void> {
  await put(`/api/registry/company-apps/${appId}?company_id=${encodeURIComponent(companyId)}`, { enabled })
}

/** Включить/выключить модуль приложения компании (только админ). */
export async function setCompanyAppModule(
  companyId: string, appId: string, moduleCode: string, enabled: boolean,
): Promise<void> {
  await put(
    `/api/registry/company-apps/${appId}/modules/${encodeURIComponent(moduleCode)}?company_id=${encodeURIComponent(companyId)}`,
    { enabled },
  )
}

// ── Каталог приложений экосистемы (Ур. 1, суперадмин) ──

export interface CatalogModule {
  code: string
  name: string
  description?: string | null
  isCore: boolean
  defaultOn: boolean
}

export interface CatalogApp {
  id: string
  code: string
  name: string
  description?: string | null
  baseUrl?: string | null
  icon?: string | null
  kind: string
  isActive: boolean
  config: Record<string, unknown>
  modules: CatalogModule[]
}

/** Каталог приложений/модулей экосистемы — что доступно подключить + настройка. */
export async function getAppCatalog(): Promise<CatalogApp[]> {
  const r = await get<{ apps: CatalogApp[] }>('/api/registry/apps')
  return r.apps
}

/** Настройка приложения при подключении (описание/адрес/конфиг/активность). */
export async function updateApp(
  appId: string,
  patch: { description?: string; base_url?: string; config?: Record<string, unknown>; is_active?: boolean },
): Promise<void> {
  await put(`/api/registry/apps/${appId}`, patch)
}
