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
