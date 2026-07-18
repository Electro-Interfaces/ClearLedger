/**
 * Снимок «вида» рабочей области = единый снимок двух уровней фильтров:
 *   раздел (FilterState) + активный пункт (mode/sub) + параметры всех пунктов.
 *
 * Используется историей видов: «Сохранить вид» снимает текущее состояние,
 * «Вернуть» восстанавливает раздел (через FilterContext.applyState), параметры
 * пунктов (перезапись localStorage + событие перезагрузки) и переключает пункт.
 */

import type { FilterState } from '@/contexts/FilterContext'

const TAB_PREFIX = 'cl-tabparams-'
function tabPrefix(companyId: string): string {
  return `${TAB_PREFIX}${companyId}-`
}

export interface ViewSnapshot {
  id: string
  at: number
  name?: string  // имя вида (§6.4 «имя = описание данных»); нет → авто-подпись
  isDefault?: boolean  // вид по умолчанию (§6.4 «точка входа») — визуально выделен и наверху
  mode: string   // ?mode=
  sub: string    // ?sub=
  section: FilterState
  tabParams: Record<string, string>  // ключ пункта (без префикса) → сырой JSON
}

/** Снять параметры всех пунктов компании (по префиксу localStorage). */
export function captureTabParams(companyId: string): Record<string, string> {
  const out: Record<string, string> = {}
  const pfx = tabPrefix(companyId)
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(pfx)) {
        const v = localStorage.getItem(k)
        if (v != null) out[k.slice(pfx.length)] = v
      }
    }
  } catch { /* ignore */ }
  return out
}

/** Восстановить параметры пунктов (перезапись localStorage). */
export function restoreTabParams(companyId: string, tabParams: Record<string, string>): void {
  const pfx = tabPrefix(companyId)
  try {
    for (const [key, raw] of Object.entries(tabParams)) localStorage.setItem(pfx + key, raw)
  } catch { /* ignore */ }
}

const VIEW_HISTORY_LIMIT = 15
function historyKey(companyId: string): string {
  return `cl-view-history-${companyId}`
}

export function loadViewHistory(companyId: string): ViewSnapshot[] {
  try {
    const raw = localStorage.getItem(historyKey(companyId))
    if (raw) { const a = JSON.parse(raw); return Array.isArray(a) ? (a as ViewSnapshot[]).slice(0, VIEW_HISTORY_LIMIT) : [] }
  } catch { /* ignore */ }
  return []
}

export function saveViewHistory(companyId: string, list: ViewSnapshot[]): void {
  try { localStorage.setItem(historyKey(companyId), JSON.stringify(list.slice(0, VIEW_HISTORY_LIMIT))) } catch { /* ignore */ }
}

export { VIEW_HISTORY_LIMIT }
