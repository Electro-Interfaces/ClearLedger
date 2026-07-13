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
import { nanoid } from 'nanoid'
import { useCompany } from './CompanyContext'
import { clearFilterSelections, sameFilterState } from './filterState'

/** Период дат [from, to] в ISO (YYYY-MM-DD). */
export interface Period {
  from: string
  to: string
}

export interface FilterState {
  /** Период дат — общий для всех разделов рабочей области. */
  period: Period
  /** Станция STS для онлайн-загрузки смен: 'all' | строковый код станции. */
  stationCode: string
  /** Выбранные точки обслуживания (ID из gig-locations). Пусто = «все». */
  locationIds: string[]
  /** Выбранные регионы (= ServiceLocation.metadata.federalSubject / канон-регион ЭЗС). Пусто = «все». */
  regionIds: string[]
  /** Коды ЭЗС-станций (energy) для сужения аналитики сессий. Пусто = «все». */
  stationCodes: string[]
  /** Выбранные типы документов (shift_report, receipt, price, ...). Пусто = «все». */
  docTypeIds: string[]
}

/** Именованный предустановленный набор фильтра. */
export interface NamedPreset {
  id: string
  name: string
  state: FilterState
}

interface FilterContextType extends FilterState {
  setPeriod: (p: Period) => void
  setStationCode: (code: string) => void
  setLocationIds: (ids: string[]) => void
  toggleLocation: (id: string) => void
  setRegionIds: (ids: string[]) => void
  toggleRegion: (id: string) => void
  setStationCodes: (codes: string[]) => void
  toggleStationCode: (code: string) => void
  setDocTypeIds: (ids: string[]) => void
  toggleDocType: (id: string) => void
  clearAll: () => void
  /** Целиком заменить состояние фильтра (для истории/пресетов). */
  applyState: (s: FilterState) => void
  /** Текущее состояние фильтра одним объектом (снимок). */
  state: FilterState

  /** История применённых наборов (новейшие первыми). */
  history: FilterState[]
  /** Зафиксировать текущий набор в историю (idempotent к последнему). */
  commitToHistory: (state?: FilterState) => void
  /** Предустановленные наборы пользователя. */
  presets: NamedPreset[]
  /** Сохранить текущий набор как именованный пресет. */
  savePreset: (name: string, state?: FilterState) => void
  /** Удалить пресет. */
  deletePreset: (id: string) => void

  /** Удобный helper: применить фильтр локаций к произвольному массиву по
   *  свойству locationId. Если фильтр пуст — возвращает все. */
  filterByLocation: <T extends { locationId?: string | null }>(items: T[]) => T[]
}

function defaultPeriod(): Period {
  const d = new Date()
  const first = new Date(d.getFullYear(), d.getMonth(), 1)
  return { from: first.toISOString().slice(0, 10), to: d.toISOString().slice(0, 10) }
}

const HISTORY_LIMIT = 12

const FilterContext = createContext<FilterContextType | null>(null)

function storageKey(companyId: string): string {
  return `gig-filters-${companyId}`
}
function historyKey(companyId: string): string {
  return `gig-filter-history-${companyId}`
}
function presetsKey(companyId: string): string {
  return `gig-filter-presets-${companyId}`
}

/** Нормализовать произвольный объект к валидному FilterState. */
function coerceState(parsed: unknown): FilterState {
  const o = (parsed ?? {}) as Record<string, unknown>
  const p = o.period as { from?: unknown; to?: unknown } | undefined
  return {
    period: p && typeof p.from === 'string' && typeof p.to === 'string' ? { from: p.from, to: p.to } : defaultPeriod(),
    stationCode: typeof o.stationCode === 'string' ? o.stationCode : 'all',
    locationIds: Array.isArray(o.locationIds) ? (o.locationIds as string[]) : [],
    regionIds: Array.isArray(o.regionIds) ? (o.regionIds as string[]) : [],
    stationCodes: Array.isArray(o.stationCodes) ? (o.stationCodes as string[]) : [],
    docTypeIds: Array.isArray(o.docTypeIds) ? (o.docTypeIds as string[]) : [],
  }
}

function loadFilters(companyId: string): FilterState {
  try {
    const raw = localStorage.getItem(storageKey(companyId))
    if (!raw) return coerceState(null)
    return coerceState(JSON.parse(raw))
  } catch {
    return coerceState(null)
  }
}

function saveFilters(companyId: string, state: FilterState): void {
  try {
    localStorage.setItem(storageKey(companyId), JSON.stringify(state))
  } catch {
    // тихо игнорируем — quota и т.п.
  }
}

function loadHistory(companyId: string): FilterState[] {
  try {
    const raw = localStorage.getItem(historyKey(companyId))
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr.map(coerceState).slice(0, HISTORY_LIMIT) : []
  } catch {
    return []
  }
}
function saveHistory(companyId: string, list: FilterState[]): void {
  try { localStorage.setItem(historyKey(companyId), JSON.stringify(list.slice(0, HISTORY_LIMIT))) } catch { /* ignore */ }
}

function loadPresets(companyId: string): NamedPreset[] {
  try {
    const raw = localStorage.getItem(presetsKey(companyId))
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr
      .filter((x) => x && typeof x.id === 'string' && typeof x.name === 'string')
      .map((x) => ({ id: x.id as string, name: x.name as string, state: coerceState(x.state) }))
  } catch {
    return []
  }
}
function savePresets(companyId: string, list: NamedPreset[]): void {
  try { localStorage.setItem(presetsKey(companyId), JSON.stringify(list)) } catch { /* ignore */ }
}

export function FilterProvider({ children }: { children: ReactNode }) {
  const { companyId } = useCompany()
  const [state, setState] = useState<FilterState>(() => loadFilters(companyId))
  const [history, setHistory] = useState<FilterState[]>(() => loadHistory(companyId))
  const [presets, setPresets] = useState<NamedPreset[]>(() => loadPresets(companyId))

  // При смене компании — перезагрузить фильтры/историю/пресеты из её хранилища
  useEffect(() => {
    setState(loadFilters(companyId))
    setHistory(loadHistory(companyId))
    setPresets(loadPresets(companyId))
  }, [companyId])

  // Персист
  useEffect(() => { saveFilters(companyId, state) }, [companyId, state])
  useEffect(() => { saveHistory(companyId, history) }, [companyId, history])
  useEffect(() => { savePresets(companyId, presets) }, [companyId, presets])

  const setPeriod = useCallback((p: Period) => {
    setState((prev) => ({ ...prev, period: p }))
  }, [])

  const setStationCode = useCallback((code: string) => {
    setState((prev) => ({ ...prev, stationCode: code }))
  }, [])

  const applyState = useCallback((s: FilterState) => {
    setState(coerceState(s))
  }, [])

  const commitToHistory = useCallback((nextState?: FilterState) => {
    setState((cur) => {
      const snapshot = coerceState(nextState ?? cur)
      setHistory((prev) => {
        if (prev.length > 0 && sameFilterState(prev[0], snapshot)) return prev
        const deduped = prev.filter((h) => !sameFilterState(h, snapshot))
        return [snapshot, ...deduped].slice(0, HISTORY_LIMIT)
      })
      return cur
    })
  }, [])

  const savePreset = useCallback((name: string, nextState?: FilterState) => {
    const trimmed = name.trim()
    if (!trimmed) return
    setState((cur) => {
      setPresets((prev) => [...prev, { id: nanoid(), name: trimmed, state: coerceState(nextState ?? cur) }])
      return cur
    })
  }, [])

  const deletePreset = useCallback((id: string) => {
    setPresets((prev) => prev.filter((p) => p.id !== id))
  }, [])

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

  const setRegionIds = useCallback((ids: string[]) => {
    setState((prev) => ({ ...prev, regionIds: ids }))
  }, [])

  const toggleRegion = useCallback((id: string) => {
    setState((prev) => {
      const set = new Set(prev.regionIds)
      if (set.has(id)) set.delete(id)
      else set.add(id)
      return { ...prev, regionIds: [...set] }
    })
  }, [])

  const setStationCodes = useCallback((codes: string[]) => {
    setState((prev) => ({ ...prev, stationCodes: codes }))
  }, [])

  const toggleStationCode = useCallback((code: string) => {
    setState((prev) => {
      const set = new Set(prev.stationCodes)
      if (set.has(code)) set.delete(code)
      else set.add(code)
      return { ...prev, stationCodes: [...set] }
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
    setState(clearFilterSelections)
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
    state,
    setPeriod,
    setStationCode,
    applyState,
    history,
    commitToHistory,
    presets,
    savePreset,
    deletePreset,
    setLocationIds,
    toggleLocation,
    setRegionIds,
    toggleRegion,
    setStationCodes,
    toggleStationCode,
    setDocTypeIds,
    toggleDocType,
    clearAll,
    filterByLocation,
  }), [state, setPeriod, setStationCode, applyState, history, commitToHistory, presets, savePreset, deletePreset, setLocationIds, toggleLocation, setRegionIds, toggleRegion, setStationCodes, toggleStationCode, setDocTypeIds, toggleDocType, clearAll, filterByLocation])

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>
}

export function useFilters() {
  const ctx = useContext(FilterContext)
  if (!ctx) throw new Error('useFilters must be used within FilterProvider')
  return ctx
}
