/**
 * Подключение модулей рабочего стола к КОМПАНИИ + параметры под организацию.
 * Состояние per-company в localStorage (демо-режим, паттерн tl-<entity>-<companyId>).
 * По умолчанию (нет явной записи) модуль подключён, если его профиль подходит компании,
 * — так текущее поведение (профиль-гейт) сохраняется, но становится управляемым.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import type { WorkspaceModuleDef, ModuleProfile } from '@/config/workspaceModules'
import type { ModuleComponent } from '@/config/moduleComponents'
import { defaultComponentEnabled, getModuleComponentDefs } from '@/config/moduleComponents'

const key = (companyId: string) => `tl-module-connections-${companyId}`

export interface ModuleConn {
  connected?: boolean
  params?: Record<string, string>
  components?: Record<string, boolean>   // сборка модуля под компанию: componentId → включён
}
export type ModuleConnMap = Record<string, ModuleConn>

export function getModuleConnections(companyId: string): ModuleConnMap {
  try { return JSON.parse(localStorage.getItem(key(companyId)) || '{}') } catch { return {} }
}
function saveConnections(companyId: string, map: ModuleConnMap) {
  localStorage.setItem(key(companyId), JSON.stringify(map))
}
export function setModuleConnected(companyId: string, moduleId: string, connected: boolean) {
  const m = getModuleConnections(companyId)
  m[moduleId] = { ...m[moduleId], connected }
  saveConnections(companyId, m)
}
export function setModuleParams(companyId: string, moduleId: string, params: Record<string, string>) {
  const m = getModuleConnections(companyId)
  m[moduleId] = { ...m[moduleId], params }
  saveConnections(companyId, m)
}

export function getModuleParams(companyId: string, moduleId: string): Record<string, string> {
  return getModuleConnections(companyId)[moduleId]?.params ?? {}
}

/* ── Компоненты модуля (сборка под компанию) ── */

export function getModuleComponents(companyId: string, moduleId: string): Record<string, boolean> {
  return getModuleConnections(companyId)[moduleId]?.components ?? {}
}
export function setComponentEnabled(companyId: string, moduleId: string, cmpId: string, enabled: boolean) {
  const m = getModuleConnections(companyId)
  const components = { ...(m[moduleId]?.components ?? {}), [cmpId]: enabled }
  m[moduleId] = { ...m[moduleId], components }
  saveConnections(companyId, m)
}
/** Итог: явная запись сборки или дефолт (standard→on, specialized→off). */
export function isComponentEnabled(conn: ModuleConnMap, cmp: ModuleComponent, _profileId?: string): boolean {
  return conn[cmp.moduleId]?.components?.[cmp.id] ?? defaultComponentEnabled(cmp)
}

/** Подключён ли модуль по умолчанию (профиль компании подходит). */
export function defaultConnected(mod: WorkspaceModuleDef, profileId: string): boolean {
  return mod.profiles.includes('any') || mod.profiles.includes(profileId as ModuleProfile)
}
/** Итоговое состояние: явная запись или дефолт-по-профилю. */
export function isModuleConnected(conn: ModuleConnMap, mod: WorkspaceModuleDef, profileId: string): boolean {
  return conn[mod.id]?.connected ?? defaultConnected(mod, profileId)
}

/** Хук: реактивное состояние подключений активной компании + refresh. */
export function useModuleConnections() {
  const { companyId, company } = useCompany()
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['module-connections', companyId],
    queryFn: () => getModuleConnections(companyId),
  })
  return {
    companyId,
    profileId: company.profileId as string,
    conn: query.data ?? {},
    refresh: () => qc.invalidateQueries({ queryKey: ['module-connections', companyId] }),
  }
}

/** Параметры конкретного модуля для активной компании (реактивно). */
export function useModuleParams(moduleId: string): Record<string, string> {
  const { conn } = useModuleConnections()
  return conn[moduleId]?.params ?? {}
}

/** Хук: сборка компонентов модуля для активной компании (реактивно). */
export function useModuleComponents(moduleId: string) {
  const { companyId, profileId, conn, refresh } = useModuleConnections()
  const defs = getModuleComponentDefs(moduleId, profileId)
  const isEnabled = (cmp: ModuleComponent) => isComponentEnabled(conn, cmp, profileId)
  return {
    companyId, profileId, conn, refresh,
    defs,                                 // все компоненты, применимые к профилю
    enabledDefs: defs.filter(isEnabled),  // включённые в сборку (standard + активные specialized)
    isEnabled,
  }
}
