/* eslint-disable react-refresh/only-export-components */
/**
 * Глобальные фильтры менеджера: компания, точки обслуживания, типы
 * документов. Применяются ко всему рабочему столу — менеджер сужает
 * свою «зону деятельности» и видит только связанные данные.
 *
 * Состояние сохраняется в localStorage (по компании) и переживает
 * перезагрузку страницы.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { useSearchParams } from 'react-router-dom'
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
  /**
   * Виды нефтепродуктов (коды STS) — сквозное измерение топливного профиля.
   * Пусто = «все».
   *
   * Топливо на АЗС — не один товар: у АИ-92, АИ-95 и ДТ разная маржа, разный
   * спрос и разные клиенты, и «выручка сети» без указания вида — среднее по
   * больнице. Поэтому вид стоит рядом с периодом и областью учёта, а не внутри
   * отдельных экранов: разрез, который меняет ответ везде, обязан жить в общем
   * фильтре.
   */
  fuelCodes: string[]
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
  setFuelCodes: (codes: string[]) => void
  toggleFuelCode: (code: string) => void
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
  const year = String(d.getFullYear())
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return { from: `${year}-${month}-01`, to: `${year}-${month}-${day}` }
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
    fuelCodes: Array.isArray(o.fuelCodes) ? (o.fuelCodes as string[]) : [],
  }
}

// URL-персист фильтра (§11): выборка кодируется в query-параметр `f`, чтобы
// состояние переживало F5 и ссылку на выборку можно было скопировать/поделиться.
// Запись merge-safe и не затирает ?mode/?sub. Back/Forward тоже меняет фильтр:
// URL — воспроизводимый снимок рабочего контура, а не одноразовый импорт.
const URL_FILTER_PARAM = 'f'
let lastFilterCompanyId: string | null = null
function decodeFilterParam(raw: string | null): FilterState | null {
  if (!raw) return null
  try {
    return coerceState(JSON.parse(raw))
  } catch {
    try {
      return coerceState(JSON.parse(decodeURIComponent(raw)))
    } catch {
      return null
    }
  }
}
function encodeFilterParam(state: FilterState): string {
  return JSON.stringify(state)
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

export function FilterProvider({ children, syncUrl = true }: { children: ReactNode; syncUrl?: boolean }) {
  const { companyId } = useCompany()
  const [searchParams, setSearchParams] = useSearchParams()
  const companyChanged = lastFilterCompanyId !== null && lastFilterCompanyId !== companyId
  const ignoreInitialUrlRef = useRef(companyChanged)
  const initialUrlState = companyChanged || !syncUrl ? null
    : decodeFilterParam(searchParams.get(URL_FILTER_PARAM))
  const [state, setState] = useState<FilterState>(() => initialUrlState ?? loadFilters(companyId))
  const [history, setHistory] = useState<FilterState[]>(() => loadHistory(companyId))
  const [presets, setPresets] = useState<NamedPreset[]>(() => loadPresets(companyId))
  const stateRef = useRef(state)
  const pendingUrlStateRef = useRef<FilterState | null>(null)

  useEffect(() => {
    stateRef.current = state
  }, [state])

  useEffect(() => {
    lastFilterCompanyId = companyId
  }, [companyId])

  // Смена компании перемонтирует провайдер (TabsProvider key={companyId} в App),
  // поэтому init перечитает хранилище новой компании — отдельный reload-эффект не нужен.

  // Персист
  useEffect(() => { saveFilters(companyId, state) }, [companyId, state])
  useEffect(() => { saveHistory(companyId, history) }, [companyId, history])
  useEffect(() => { savePresets(companyId, presets) }, [companyId, presets])

  const rawUrlFilter = searchParams.get(URL_FILTER_PARAM)

  // Ссылка и Back/Forward восстанавливают контур. При смене компании первое `f`
  // принадлежит предыдущей компании — его один раз игнорируем и заменяем локальным.
  useEffect(() => {
    if (!syncUrl) return
    if (ignoreInitialUrlRef.current) {
      ignoreInitialUrlRef.current = false
      return
    }
    if (!rawUrlFilter) return
    const fromUrl = decodeFilterParam(rawUrlFilter)
    if (!fromUrl) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set(URL_FILTER_PARAM, encodeFilterParam(stateRef.current))
        return next
      }, { replace: true })
      return
    }
    if (!sameFilterState(fromUrl, stateRef.current)) {
      pendingUrlStateRef.current = fromUrl
      // URL — внешний источник состояния: переход Back/Forward обязан восстановить контур.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState(fromUrl)
    }
  }, [rawUrlFilter, setSearchParams, syncUrl])

  // URL-персист текущей выборки: merge-safe, replace — без спама history.
  useEffect(() => {
    if (!syncUrl) return
    const pending = pendingUrlStateRef.current
    if (pending && !sameFilterState(state, pending)) return
    if (pending) pendingUrlStateRef.current = null
    const encoded = encodeFilterParam(state)
    if (rawUrlFilter === encoded) return
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set(URL_FILTER_PARAM, encoded)
      return next
    }, { replace: true })
  }, [rawUrlFilter, setSearchParams, state, syncUrl])

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

  const setFuelCodes = useCallback((codes: string[]) => {
    setState((prev) => ({ ...prev, fuelCodes: codes }))
  }, [])

  const toggleFuelCode = useCallback((code: string) => {
    setState((prev) => {
      const set = new Set(prev.fuelCodes)
      if (set.has(code)) set.delete(code)
      else set.add(code)
      return { ...prev, fuelCodes: [...set] }
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
    setFuelCodes,
    toggleFuelCode,
    clearAll,
    filterByLocation,
  }), [state, setPeriod, setStationCode, applyState, history, commitToHistory, presets, savePreset, deletePreset, setLocationIds, toggleLocation, setRegionIds, toggleRegion, setStationCodes, toggleStationCode, setFuelCodes, toggleFuelCode, clearAll, filterByLocation])

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>
}

export function useFilters() {
  const ctx = useContext(FilterContext)
  if (!ctx) throw new Error('useFilters must be used within FilterProvider')
  return ctx
}
