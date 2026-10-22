import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { openAuthAttachment } from '@/lib/authFiles'
import type { SpaceDocument } from '@/services/referenceService'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getItem, setItem } from '@/services/storage'
import type { ShiftRecord } from '@/services/fuel/types'
import type { DeliveryRecord } from '@/services/receiptExtractService'
import type { LoadedShift, LoadedReceipt } from '@/services/fuel/fuelMappingService'
import type { FsNode, ViewMode, SortConfig, RawPanelFilters, TreeState, AdvancedFilters, GroupMode } from './raw-panel-types'
import { DEFAULT_ADVANCED_FILTERS } from './raw-panel-types'
import { LS_KEY_VIEW_MODE, LS_KEY_TREE_STATE, LS_KEY_SORT_CONFIG } from './raw-panel-constants'

import { useCompany } from '@/contexts/CompanyContext'
import { SPACE_PRODUCTS, pathAllowed } from '@/config/spaceProducts'
import { routeAllowed } from '@/config/accessModules'
import { productModuleAllowed } from '@/config/productAccess'
import { documentExplorerActions, primaryExplorerAction, pushExplorerHistory, readExplorerLocation, restoreExplorerHistory, type ExplorerAction, type ExplorerHistory } from '@/lib/documentExplorerActions'

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

export function useRawPanelState({ explorer = false } = {}) {
  const location = useLocation()
  const [, setParams] = useSearchParams()
  const { company, companyId, companyModules, canApp, canModule } = useCompany()
  const prefix = SPACE_PRODUCTS.find((product) => location.pathname.startsWith(`${product.route}/`))?.route ?? ''
  const canOpenRoute = (href: string) => {
    const pathname = href.split('?')[0]
    if (pathname === '/docs') return canApp('docs')
    if (pathname === '/projects' && !canModule('projects', 'pr_project')) return false
    return pathAllowed(pathname, company.profileId, canApp, (p) => routeAllowed(p, companyModules),
      (app, code) => productModuleAllowed(app, code, canModule, company.profileId))
  }
  const previousCompany = useRef(companyId)
  const [historyCompany, setHistoryCompany] = useState(companyId)
  const historyKey = `files-navigation:${companyId}:${location.pathname}`
  const [storedHistory, setHistory] = useState<ExplorerHistory>(() => {
    const current = readExplorerLocation(location.search)
    if (explorer) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(historyKey) ?? 'null') as ExplorerHistory | null
        return restoreExplorerHistory(saved, current)
      } catch { /* A fresh navigation still works when browser storage is unavailable. */ }
    }
    return { entries: [current], index: 0 }
  })
  const history = explorer ? restoreExplorerHistory(storedHistory, readExplorerLocation(location.search)) : storedHistory
  useEffect(() => {
    if (!explorer || previousCompany.current !== companyId) return
    try { sessionStorage.setItem(historyKey, JSON.stringify(history)) } catch { /* optional cache */ }
  }, [explorer, history, historyKey, companyId])
  const writeLocation = (folder: string[], query: string, replace = false) => {
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      if (folder.length) next.set('folder', folder.join('/')); else next.delete('folder')
      if (query) next.set('q', query); else next.delete('q')
      return next
    }, { replace })
  }

  useEffect(() => {
    if (!explorer || previousCompany.current === companyId) return
    previousCompany.current = companyId
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      next.delete('folder'); next.delete('q')
      return next
    }, { replace: true })
  }, [companyId, explorer, setParams])

  const navigate = useNavigate()
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
  const [localFilters, setFilters] = useState<RawPanelFilters>({
    searchQuery: '',
    status: 'all',
    docType: 'all',
  })
  const [localPath, setCurrentPath] = useState<string[]>([])
  const explorerLocation = useMemo(() => readExplorerLocation(location.search), [location.search])
  const currentPath = explorer ? explorerLocation.folder : localPath
  const filters = useMemo(() => explorer ? { ...localFilters, searchQuery: explorerLocation.query } : localFilters, [explorer, localFilters, explorerLocation.query])
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

  if (historyCompany !== companyId) {
    setHistoryCompany(companyId)
    setSelectedNode(null)
    setOpenTabs([])
    setActiveTabId(null)
    setCurrentPath([])
    setFilters({ searchQuery: '', status: 'all', docType: 'all' })
    setHistory({ entries: [{ folder: [], query: '' }], index: 0 })
  }

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
  const navigateTo = (path: string[]) => {
    if (explorer) {
      setHistory(pushExplorerHistory(history, { folder: path, query: '' }))
      writeLocation(path, '')
    } else {
      setCurrentPath(path)
      setFilters((prev) => ({ ...prev, searchQuery: '' }))
    }
    setSelectedNode(null)
  }

  const moveHistory = (delta: number) => {
    const index = history.index + delta
    const next = history.entries[index]
    if (!next) return
    setHistory({ ...history, index })
    writeLocation(next.folder, next.query, true)
    setSelectedNode(null)
  }
  const goBack = () => moveHistory(-1)
  const goForward = () => moveHistory(1)

  const goUp = () => {
    if (currentPath.length > 0) {
      navigateTo(currentPath.slice(0, -1))
    }
  }

  const getNodeActions = (node: FsNode): ExplorerAction[] => {
    const d = node.doc
    if (!d) return []
    if (d.docType === 'channel_run') return d.channelId && canOpenRoute(`/connectors/${encodeURIComponent(d.channelId)}`)
      ? [{ id: 'channel', label: 'Канал', href: `/connectors/${encodeURIComponent(d.channelId)}` }] : []
    if (d.docType === 'space_file' || d.docType === 'contract_card') {
      return documentExplorerActions(d.data as SpaceDocument, canOpenRoute, prefix)
    }
    return []
  }
  const runAction = (action: ExplorerAction) => {
    if (action.attachment) {
      openAuthAttachment(action.href).catch((e: unknown) => toast.error(e instanceof Error ? e.message : 'Не удалось открыть файл'))
    } else navigate(action.href)
  }

  // --- File operations ---
  const openFile = (node: FsNode) => {
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
      if (d.docType === 'space_file' || d.docType === 'contract_card' || d.docType === 'channel_run') {
        const action = primaryExplorerAction(getNodeActions(node))
        if (action) runAction(action)
        else toast.info('Нет доступной карточки или файла для этого документа')
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
  }

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
  const updateFilter = <K extends keyof RawPanelFilters>(key: K, value: RawPanelFilters[K]) => {
    if (explorer && key === 'searchQuery') {
      const query = String(value)
      setHistory({ ...history, entries: history.entries.map((entry, i) => i === history.index ? { ...entry, query } : entry) })
      writeLocation(currentPath, query, true)
      setSelectedNode(null)
    } else setFilters((prev) => ({ ...prev, [key]: value }))
  }

  const clearFilters = () => {
    setFilters({ searchQuery: '', status: 'all', docType: 'all' })
    if (explorer) writeLocation(currentPath, '', true)
  }

  const hasActiveFilters = filters.status !== 'all' || filters.docType !== 'all'

  return {
    // View
    viewMode, setViewMode,
    // Tree
    treeState, isExpanded, toggleExpanded, saveScrollPosition,
    // Navigation
    currentPath, navigateTo, goUp, goBack, goForward,
    canBack: history.index > 0, canForward: history.index < history.entries.length - 1,
    getNodeActions, runAction, canOpenRoute, prefix,
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
