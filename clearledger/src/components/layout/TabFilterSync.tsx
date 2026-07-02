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

export function TabFilterSync() {
  const location = useLocation()
  const activeKey = location.pathname + location.search
  const { state, applyState } = useFilters()
  const { companyId } = useCompany()
  const { isPinned } = useTabs()

  // Свежие ссылки — чтобы эффект перехода не зависел от state/isPinned в deps.
  const stateRef = useRef(state)
  stateRef.current = state
  const isPinnedRef = useRef(isPinned)
  isPinnedRef.current = isPinned
  const keyRef = useRef(activeKey)

  useEffect(() => {
    const prevKey = keyRef.current
    if (prevKey === activeKey) return

    // Уход с закреплённой закладки → сохранить её текущий фильтр.
    if (isPinnedRef.current(prevKey)) saveOne(companyId, prevKey, stateRef.current)

    // Переход на закреплённую закладку → восстановить её фильтр (если сохранён).
    if (isPinnedRef.current(activeKey)) {
      const snap = getOne(companyId, activeKey)
      if (snap) applyState(snap)
    }

    keyRef.current = activeKey
  }, [activeKey, companyId, applyState])

  // Размонтирование / смена компании — сохранить фильтр текущей закладки.
  useEffect(() => {
    return () => {
      if (isPinnedRef.current(keyRef.current)) saveOne(companyId, keyRef.current, stateRef.current)
    }
  }, [companyId])

  return null
}
