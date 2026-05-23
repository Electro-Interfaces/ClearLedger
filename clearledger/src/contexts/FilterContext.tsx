/**
 * Глобальные фильтры менеджера: компания, точки обслуживания, типы
 * документов. Применяются ко всему рабочему столу — менеджер сужает
 * свою «зону деятельности» и видит только связанные данные.
 *
 * Состояние сохраняется в localStorage (по компании) и переживает
 * перезагрузку страницы.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { useCompany } from './CompanyContext'

interface FilterState {
  /** Выбранные точки обслуживания (ID из gig-locations). Пусто = «все». */
  locationIds: string[]
  /** Выбранные типы документов (shift_report, receipt, price, ...). Пусто = «все». */
  docTypeIds: string[]
}

interface FilterContextType extends FilterState {
  setLocationIds: (ids: string[]) => void
  toggleLocation: (id: string) => void
  setDocTypeIds: (ids: string[]) => void
  toggleDocType: (id: string) => void
  clearAll: () => void
  /** Удобный helper: применить фильтр локаций к произвольному массиву по
   *  свойству locationId. Если фильтр пуст — возвращает все. */
  filterByLocation: <T extends { locationId?: string | null }>(items: T[]) => T[]
}

const FilterContext = createContext<FilterContextType | null>(null)

function storageKey(companyId: string): string {
  return `gig-filters-${companyId}`
}

function loadFilters(companyId: string): FilterState {
  try {
    const raw = localStorage.getItem(storageKey(companyId))
    if (!raw) return { locationIds: [], docTypeIds: [] }
    const parsed = JSON.parse(raw)
    return {
      locationIds: Array.isArray(parsed.locationIds) ? parsed.locationIds : [],
      docTypeIds: Array.isArray(parsed.docTypeIds) ? parsed.docTypeIds : [],
    }
  } catch {
    return { locationIds: [], docTypeIds: [] }
  }
}

function saveFilters(companyId: string, state: FilterState): void {
  try {
    localStorage.setItem(storageKey(companyId), JSON.stringify(state))
  } catch {
    // тихо игнорируем — quota и т.п.
  }
}

export function FilterProvider({ children }: { children: ReactNode }) {
  const { companyId } = useCompany()
  const [state, setState] = useState<FilterState>(() => loadFilters(companyId))

  // При смене компании — перезагрузить фильтры из её хранилища
  useEffect(() => {
    setState(loadFilters(companyId))
  }, [companyId])

  // Сохраняем при каждом изменении
  useEffect(() => {
    saveFilters(companyId, state)
  }, [companyId, state])

  const setLocationIds = useCallback((ids: string[]) => {
    setState((prev) => ({ ...prev, locationIds: ids }))
  }, [])

  const toggleLocation = useCallback((id: string) => {
    setState((prev) => {
      const set = new Set(prev.locationIds)
      if (set.has(id)) set.delete(id)
      else set.add(id)
      return { ...prev, locationIds: [...set] }
    })
  }, [])

  const setDocTypeIds = useCallback((ids: string[]) => {
    setState((prev) => ({ ...prev, docTypeIds: ids }))
  }, [])

  const toggleDocType = useCallback((id: string) => {
    setState((prev) => {
      const set = new Set(prev.docTypeIds)
      if (set.has(id)) set.delete(id)
      else set.add(id)
      return { ...prev, docTypeIds: [...set] }
    })
  }, [])

  const clearAll = useCallback(() => {
    setState({ locationIds: [], docTypeIds: [] })
  }, [])

  const filterByLocation = useCallback(
    <T extends { locationId?: string | null }>(items: T[]): T[] => {
      if (state.locationIds.length === 0) return items
      const set = new Set(state.locationIds)
      return items.filter((x) => x.locationId && set.has(x.locationId))
    },
    [state.locationIds],
  )

  const value = useMemo<FilterContextType>(() => ({
    ...state,
    setLocationIds,
    toggleLocation,
    setDocTypeIds,
    toggleDocType,
    clearAll,
    filterByLocation,
  }), [state, setLocationIds, toggleLocation, setDocTypeIds, toggleDocType, clearAll, filterByLocation])

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>
}

export function useFilters() {
  const ctx = useContext(FilterContext)
  if (!ctx) throw new Error('useFilters must be used within FilterProvider')
  return ctx
}
