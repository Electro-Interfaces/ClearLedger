/**
 * Синхронизация основного фильтра с закреплёнными вкладками (закладками).
 *
 * Каждая закладка (закреплённая вкладка, ключ = URL) помнит свой набор фильтра.
 * При уходе с закреплённой вкладки её текущий фильтр сохраняется; при переходе
 * на закреплённую вкладку — восстанавливается. Обычная (незакреплённая)
 * навигация фильтр не переключает — он «переносится» с собой.
 *
 * Ничего не рендерит.
 */

import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useFilters, type FilterState } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useTabs } from '@/contexts/TabsContext'

const storeKey = (companyId: string) => `gig-tab-filters-${companyId}`

function loadAll(companyId: string): Record<string, FilterState> {
  try {
    const raw = localStorage.getItem(storeKey(companyId))
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveOne(companyId: string, tabKey: string, state: FilterState): void {
  try {
    const all = loadAll(companyId)
    all[tabKey] = state
    localStorage.setItem(storeKey(companyId), JSON.stringify(all))
  } catch {
    // тихо игнорируем
  }
}

function getOne(companyId: string, tabKey: string): FilterState | null {
  const all = loadAll(companyId)
  return all[tabKey] ?? null
}

function deleteOne(companyId: string, tabKey: string): void {
  try {
    const all = loadAll(companyId)
    delete all[tabKey]
    localStorage.setItem(storeKey(companyId), JSON.stringify(all))
  } catch {
    // тихо игнорируем
  }
}

export function TabFilterSync() {
  const location = useLocation()
  const activeKey = location.pathname + location.search
  const { state, applyState } = useFilters()
  const { companyId } = useCompany()
  const { isPinned } = useTabs()
  const activePinned = isPinned(activeKey)

  const stateRef = useRef(state)
  const routeRef = useRef<{ companyId: string; key: string; pinned: boolean } | null>(null)

  useEffect(() => {
    stateRef.current = state
  }, [state])

  useEffect(() => {
    if (!companyId || companyId === '_') return
    const previous = routeRef.current
    const companyChanged = !!previous && previous.companyId !== companyId
    const keyChanged = !!previous && previous.key !== activeKey

    if (previous && !companyChanged && keyChanged && previous.pinned) {
      saveOne(previous.companyId, previous.key, stateRef.current)
    }

    if (!previous || companyChanged || keyChanged) {
      if (activePinned) {
        const snap = getOne(companyId, activeKey)
        if (snap) applyState(snap)
        else saveOne(companyId, activeKey, stateRef.current)
      }
    } else if (!previous.pinned && activePinned) {
      saveOne(companyId, activeKey, stateRef.current)
    } else if (previous.pinned && !activePinned) {
      deleteOne(companyId, activeKey)
    }

    routeRef.current = { companyId, key: activeKey, pinned: activePinned }
  }, [activeKey, activePinned, companyId, applyState])

  useEffect(() => {
    return () => {
      const current = routeRef.current
      if (current?.pinned && current.companyId !== '_') {
        saveOne(current.companyId, current.key, stateRef.current)
      }
    }
  }, [])

  return null
}
