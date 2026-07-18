import { useState, useCallback } from 'react'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getItem, setItem } from '@/services/storage'
import type { ShiftRecord } from '@/services/fuel/types'
import type { DeliveryRecord } from '@/services/receiptExtractService'
import type { LoadedShift, LoadedReceipt } from '@/services/fuel/fuelMappingService'
import type { FsNode, ViewMode, SortConfig, RawPanelFilters, TreeState, AdvancedFilters, GroupMode } from './raw-panel-types'
import { DEFAULT_ADVANCED_FILTERS } from './raw-panel-types'
import { LS_KEY_VIEW_MODE, LS_KEY_TREE_STATE, LS_KEY_SORT_CONFIG } from './raw-panel-constants'

/** useState synced to localStorage */
function usePersisted<T>(key: string, fallback: T): [T, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => getItem<T>(key, fallback))

  const setPersisted = useCallback((v: T | ((prev: T) => T)) => {
    setValue((prev) => {
      const next = typeof v === 'function' ? (v as (p: T) => T)(prev) : v
      setItem(key, next)
      return next
    })
  }, [key])

  return [value, setPersisted]
}

export function useRawPanelState() {
  // --- Persisted state ---
  const [viewMode, setViewMode] = usePersisted<ViewMode>(LS_KEY_VIEW_MODE, 'tree')
  const [treeState, setTreeState] = usePersisted<TreeState>(LS_KEY_TREE_STATE, {
    expandedPaths: [],
    scrollTop: 0,
  })
  const [sortConfig, setSortConfig] = usePersisted<SortConfig>(LS_KEY_SORT_CONFIG, {
    column: 'date',
    direction: 'desc',
  })

  // --- Session state ---
  const [filters, setFilters] = useState<RawPanelFilters>({
    searchQuery: '',
    status: 'all',
    docType: 'all',
  })
  const [currentPath, setCurrentPath] = useState<string[]>([])
  const [openTabs, setOpenTabs] = useState<FsNode[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<FsNode | null>(null)
  const [focusedPath, setFocusedPath] = useState<string | null>(null)
  const [searchExpanded, setSearchExpanded] = useState(false)
  const [viewingShift, setViewingShift] = useState<ShiftRecord | null>(null)
  const [viewingDelivery, setViewingDelivery] = useState<DeliveryRecord | null>(null)
  // Серверные документы БД (origin: 'api') — свои просмотрщики.
  const [viewingApiShiftId, setViewingApiShiftId] = useState<string | null>(null)
  const [viewingApiReceipt, setViewingApiReceipt] = useState<LoadedReceipt | null>(null)

  // --- Advanced filter dialog ---
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [advancedFilters, setAdvancedFilters] = useState<AdvancedFilters>({ ...DEFAULT_ADVANCED_FILTERS })
  const [groupMode, setGroupMode] = useState<GroupMode>('default')

  const applyPreset = useCallback((preset: Partial<AdvancedFilters>) => {
    setAdvancedFilters(() => ({ ...DEFAULT_ADVANCED_FILTERS, ...preset }))
  }, [])

  const clearAdvancedFilters = useCallback(() => {
    setAdvancedFilters({ ...DEFAULT_ADVANCED_FILTERS })
  }, [])

  const hasAdvancedFilters = advancedFilters.query !== '' ||
    advancedFilters.dateFrom !== '' || advancedFilters.dateTo !== '' ||
    advancedFilters.category !== 'all' || advancedFilters.docType !== 'all' ||
    advancedFilters.objectId !== 'all' || advancedFilters.counterparty !== 'all' ||
    advancedFilters.source !== 'all' || advancedFilters.statuses.length > 0 ||
    advancedFilters.onlyWithIssues

  const activeFilterCount = [
    advancedFilters.query !== '',
    advancedFilters.dateFrom !== '' || advancedFilters.dateTo !== '',
    advancedFilters.category !== 'all',
    advancedFilters.docType !== 'all',
    advancedFilters.objectId !== 'all',
    advancedFilters.counterparty !== 'all',
    advancedFilters.source !== 'all',
    advancedFilters.statuses.length > 0,
    advancedFilters.onlyWithIssues,
  ].filter(Boolean).length

  // --- WorkspaceContext ---
  const workspace = useWorkspace()

  // --- Tree operations ---
  const isExpanded = useCallback((path: string) => {
    return treeState.expandedPaths.includes(path)
  }, [treeState.expandedPaths])

  const toggleExpanded = useCallback((path: string) => {
    setTreeState((prev) => {
      const paths = prev.expandedPaths.includes(path)
        ? prev.expandedPaths.filter((p) => p !== path)
        : [...prev.expandedPaths, path]
      return { ...prev, expandedPaths: paths.slice(-200) } // limit to 200
    })
  }, [setTreeState])

  const saveScrollPosition = useCallback((top: number) => {
    setTreeState((prev) => ({ ...prev, scrollTop: top }))
  }, [setTreeState])

  // --- Navigation ---
  const navigateTo = useCallback((path: string[]) => {
    setCurrentPath(path)
    setFilters((prev) => ({ ...prev, searchQuery: '' }))
  }, [])

  const goUp = useCallback(() => {
    if (currentPath.length > 0) {
      navigateTo(currentPath.slice(0, -1))
    }
  }, [currentPath, navigateTo])

  // --- File operations ---
  const openFile = useCallback((node: FsNode) => {
    // Add to tabs
    setOpenTabs((prev) => {
      if (prev.some((t) => t.path === node.path)) return prev
      return [...prev, node]
    })
    setActiveTabId(node.path)
    setSelectedNode(node)

    // Открыть просмотрщик по типу документа из узла.
    const d = node.doc
    if (!d) return
    if (d.origin === 'api') {
      // Серверные документы БД: смена — просмотрщик по id, ТТН — по строке реестра.
      if (d.docType === 'shift_report') {
        const rec = d.data as LoadedShift
        if (node.stationId != null && rec?.shift_number != null) {
          workspace.selectShift(node.stationId, rec.shift_number)
        }
        setViewingApiShiftId(d.id)
        return
      }
      if (d.docType === 'delivery' || d.docType === 'receipt') {
        setViewingApiReceipt(d.data as LoadedReceipt)
        return
      }
      return // channel_run и прочие — только выделение и панель деталей
    }
    if (d.docType === 'shift_report') {
      const rec = d.data as ShiftRecord
      if (node.stationId != null && rec?.shiftNumber != null) {
        workspace.selectShift(node.stationId, rec.shiftNumber)
      }
      setViewingShift(rec)
      return
    }
    if (d.docType === 'delivery' || d.docType === 'receipt') {
      setViewingDelivery(d.data as DeliveryRecord)
      return
    }
    // Прочие типы — пока только выделение и панель деталей (спец-модалки нет).
  }, [workspace])

  // --- Tab operations ---
  const closeTab = useCallback((path: string) => {
    setOpenTabs((prev) => prev.filter((t) => t.path !== path))
    if (activeTabId === path) setActiveTabId(null)
  }, [activeTabId])

  const switchTab = useCallback((node: FsNode) => {
    setActiveTabId(node.path)
    setSelectedNode(node)
    const d = node.doc
    if (d?.docType === 'shift_report' && node.stationId != null) {
      const rec = d.data as ShiftRecord
      if (rec?.shiftNumber != null) workspace.selectShift(node.stationId, rec.shiftNumber)
    }
  }, [workspace])

  // --- Sort operations ---
  const toggleSort = useCallback((column: SortConfig['column']) => {
    setSortConfig((prev) => ({
      column,
      direction: prev.column === column && prev.direction === 'asc' ? 'desc' : 'asc',
    }))
  }, [setSortConfig])

  // --- Filter operations ---
  const updateFilter = useCallback(<K extends keyof RawPanelFilters>(key: K, value: RawPanelFilters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }, [])

  const clearFilters = useCallback(() => {
    setFilters({ searchQuery: '', status: 'all', docType: 'all' })
  }, [])

  const hasActiveFilters = filters.status !== 'all' || filters.docType !== 'all'

  return {
    // View
    viewMode, setViewMode,
    // Tree
    treeState, isExpanded, toggleExpanded, saveScrollPosition,
    // Navigation
    currentPath, navigateTo, goUp,
    // Selection
    selectedNode, setSelectedNode, focusedPath, setFocusedPath,
    // Tabs
    openTabs, activeTabId, openFile, closeTab, switchTab,
    // Sort
    sortConfig, toggleSort,
    // Filters
    filters, updateFilter, clearFilters, hasActiveFilters,
    // Search
    searchExpanded, setSearchExpanded,
    // Modals
    viewingShift, setViewingShift, viewingDelivery, setViewingDelivery,
    viewingApiShiftId, setViewingApiShiftId, viewingApiReceipt, setViewingApiReceipt,
    // Advanced filter dialog
    filterDialogOpen, setFilterDialogOpen,
    advancedFilters, setAdvancedFilters, applyPreset, clearAdvancedFilters,
    hasAdvancedFilters, activeFilterCount,
    // Group mode
    groupMode, setGroupMode,
    // Workspace passthrough
    workspace,
  }
}

export type RawPanelState = ReturnType<typeof useRawPanelState>
