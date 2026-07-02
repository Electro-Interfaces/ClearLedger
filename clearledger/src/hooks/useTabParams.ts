/**
 * Персистируемые параметры пункта меню (второй уровень фильтров).
 *
 * Общий фильтр раздела (период/станции/регионы) живёт в FilterContext.
 * Уникальные настройки пункта (метрика, разрез, нарезка, режим, override периода)
 * хранятся здесь — по ключу (компания × пункт), переживают перезагрузку и
 * возврат в пункт. defaults мержатся поверх сохранённого — новые поля подхватывают
 * значения по умолчанию.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useCompany } from '@/contexts/CompanyContext'

function storageKey(companyId: string, tab: string): string {
  return `cl-tabparams-${companyId}-${tab}`
}

export function loadTabParams<T extends object>(companyId: string, tab: string, defaults: T): T {
  try {
    const raw = localStorage.getItem(storageKey(companyId, tab))
    if (raw) return { ...defaults, ...(JSON.parse(raw) as Partial<T>) }
  } catch { /* ignore */ }
  return defaults
}

export function saveTabParams<T extends object>(companyId: string, tab: string, params: T): void {
  try { localStorage.setItem(storageKey(companyId, tab), JSON.stringify(params)) } catch { /* ignore */ }
}

/** Событие «параметры пунктов восстановлены извне» — чтобы открытый пункт перечитал их. */
export const TAB_PARAMS_EVENT = 'cl-tabparams-restored'
export function notifyTabParamsRestored(): void {
  try { window.dispatchEvent(new Event(TAB_PARAMS_EVENT)) } catch { /* ignore */ }
}

/**
 * Возвращает [параметры, patch, setAll]. patch мержит частичное обновление.
 * defaults должен быть стабильным (модульная константа или useMemo).
 */
export function useTabParams<T extends object>(tab: string, defaults: T) {
  const { companyId } = useCompany()
  const defRef = useRef(defaults)
  const [params, setParams] = useState<T>(() => loadTabParams(companyId, tab, defRef.current))

  // перезагрузка при смене компании/пункта
  useEffect(() => { setParams(loadTabParams(companyId, tab, defRef.current)) }, [companyId, tab])
  // перезагрузка при восстановлении снимка вида (история)
  useEffect(() => {
    const reload = () => setParams(loadTabParams(companyId, tab, defRef.current))
    window.addEventListener(TAB_PARAMS_EVENT, reload)
    return () => window.removeEventListener(TAB_PARAMS_EVENT, reload)
  }, [companyId, tab])
  // персист
  useEffect(() => { saveTabParams(companyId, tab, params) }, [companyId, tab, params])

  const patch = useCallback((p: Partial<T>) => setParams((cur) => ({ ...cur, ...p })), [])
  return [params, patch, setParams] as const
}
