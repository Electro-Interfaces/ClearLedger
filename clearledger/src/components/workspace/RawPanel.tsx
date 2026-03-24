/**
 * Панель 2: Проводник загруженных документов.
 * Breadcrumb-путь, навигация по папкам, поиск, виды (список/плитка).
 */

import { useState, useMemo } from 'react'
import { useShifts } from '@/hooks/useFuel'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Loader2, RefreshCw, List, LayoutGrid, Search, GitBranchPlus, SlidersHorizontal,
  ChevronRight, ChevronDown, FolderOpen, Folder, FileText, ArrowUp, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import type { StsShift } from '@/services/fuel/types'

type ViewMode = 'list' | 'grid' | 'tree'

interface FsNode {
  name: string
  type: 'folder' | 'file'
  path: string
  /** Для файлов — данные смены */
  shift?: StsShift
  stationId?: number
  /** Для папок — кол-во элементов внутри */
  childCount?: number
  date?: string
  status?: string
  size?: string
}

/** Рекурсивный компонент дерева */
function TreeView({ fsTree, path, depth, selectedShiftNumber, selectedStationId, onSelectFile }: {
  fsTree: Map<string, FsNode[]>
  path: string[]
  depth: number
  selectedShiftNumber: number | null
  selectedStationId: number | null
  onSelectFile: (node: FsNode) => void
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const key = path.join('/')
  const nodes = fsTree.get(key) ?? []

  function toggle(name: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  const pl = depth * 16

  return (
    <div>
      {nodes.map((node) => {
        const isFolder = node.type === 'folder'
        const isOpen = expanded.has(node.name)
        const isSelected = !isFolder && node.shift && selectedShiftNumber === node.shift.shift && selectedStationId === node.stationId

        return (
          <div key={node.path}>
            <button
              onClick={() => isFolder ? toggle(node.name) : onSelectFile(node)}
              className={`w-full flex items-center gap-1.5 py-1 pr-2 text-[11px] hover:bg-accent/40 transition-colors ${
                isSelected ? 'bg-primary/10' : ''
              }`}
              style={{ paddingLeft: `${pl + 8}px` }}
            >
              {isFolder ? (
                <>
                  {isOpen
                    ? <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
                    : <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
                  }
                  {isOpen
                    ? <FolderOpen className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                    : <Folder className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                  }
                </>
              ) : (
                <>
                  <span className="w-3" />
                  <FileText className={`h-3.5 w-3.5 shrink-0 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                </>
              )}
              <span className={`truncate text-left ${
                isSelected ? 'font-semibold text-primary' : isFolder ? 'font-medium' : ''
              }`}>
                {node.name}
              </span>
              {isFolder && node.childCount != null && (
                <Badge variant="outline" className="text-[8px] h-3.5 px-1 ml-auto shrink-0">{node.childCount}</Badge>
              )}
              {!isFolder && node.status && (
                <Badge variant={node.status === 'Закрыта' ? 'secondary' : 'default'} className="text-[7px] h-3 px-0.5 ml-auto shrink-0">
                  {node.status === 'Закрыта' ? 'З' : 'О'}
                </Badge>
              )}
            </button>

            {isFolder && isOpen && (
              <TreeView
                fsTree={fsTree}
                path={[...path, node.name]}
                depth={depth + 1}
                selectedShiftNumber={selectedShiftNumber}
                selectedStationId={selectedStationId}
                onSelectFile={onSelectFile}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

export function RawPanel({ collapseButton }: { hideHeader?: boolean; collapseButton?: React.ReactNode }) {
  const settings = getSettings()
  const queryClient = useQueryClient()
  const { globalStation, selectedStationId, selectedShiftNumber, selectShift } = useWorkspace()

  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [searchQuery, setSearchQuery] = useState('')
  const [currentPath, setCurrentPath] = useState<string[]>([])
  const [openTabs, setOpenTabs] = useState<FsNode[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [showFilter, setShowFilter] = useState(false)
  const [filterStatus, setFilterStatus] = useState<'all' | 'open' | 'closed'>('all')
  const [filterDocType, setFilterDocType] = useState<'all' | 'shifts' | 'receipts'>('all')

  const filterStation = globalStation === 'all' ? undefined : Number(globalStation)
  const { data: shifts, isLoading, isFetching } = useShifts(filterStation)

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
  }

  const stId = filterStation ?? settings.stations[0]?.code ?? 0
  // stationName используется в fsTree
  void stId

  const MONTH_NAMES = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

  // Построить виртуальную файловую систему
  const fsTree = useMemo(() => {
    if (!shifts) return new Map<string, FsNode[]>()

    const tree = new Map<string, FsNode[]>()

    // Корень: папки по станциям
    const rootNodes: FsNode[] = []
    const stationCodes = new Set<number>()

    // Определяем станцию (пока одна)
    stationCodes.add(stId)

    for (const code of stationCodes) {
      const name = settings.stations.find(st => st.code === code)?.name ?? `АЗС-${code}`
      rootNodes.push({ name, type: 'folder', path: name, childCount: 0 })
    }

    // Группируем смены по году→месяцу
    // Применяем фильтр статуса
    let filtered = shifts
    if (filterStatus === 'open') filtered = filtered.filter(s => !s.dt_close)
    if (filterStatus === 'closed') filtered = filtered.filter(s => !!s.dt_close)
    // Применяем поиск
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      filtered = filtered.filter(s =>
        String(s.shift).includes(q) ||
        (s.dt_open && format(new Date(s.dt_open), 'dd.MM.yyyy').includes(q))
      )
    }

    const byYearMonth = new Map<string, StsShift[]>()
    for (const s of filtered) {
      const d = s.dt_open ? new Date(s.dt_open) : null
      const year = d ? String(d.getFullYear()) : '—'
      const month = d ? String(d.getMonth() + 1).padStart(2, '0') : '00'
      const key = `${year}/${month}`
      if (!byYearMonth.has(key)) byYearMonth.set(key, [])
      byYearMonth.get(key)!.push(s)
    }

    // Для каждой станции → годы
    for (const code of stationCodes) {
      const sName = settings.stations.find(st => st.code === code)?.name ?? `АЗС-${code}`
      const years = new Set<string>()
      for (const [ym] of byYearMonth) years.add(ym.split('/')[0])

      const yearNodes: FsNode[] = []
      for (const year of [...years].sort().reverse()) {
        yearNodes.push({ name: year, type: 'folder', path: `${sName}/${year}` })
      }
      tree.set(sName, yearNodes)

      // Для каждого года → месяцы
      for (const year of years) {
        const monthNodes: FsNode[] = []
        // Смены
        const smenyNode: FsNode = { name: 'Смены', type: 'folder', path: `${sName}/${year}/Смены`, childCount: 0 }

        for (const [ym, ymShifts] of byYearMonth) {
          if (!ym.startsWith(year + '/')) continue
          const monthNum = Number(ym.split('/')[1])
          const monthName = MONTH_NAMES[monthNum] || ym
          monthNodes.push({ name: monthName, type: 'folder', path: `${sName}/${year}/${monthName}`, childCount: ymShifts.length })

          // Внутри месяца: файлы-смены
          const shiftFiles: FsNode[] = ymShifts.map(s => ({
            name: `Смена №${s.shift}`,
            type: 'file' as const,
            path: `${sName}/${year}/${monthName}/Смена №${s.shift}`,
            shift: s,
            stationId: code,
            date: s.dt_open ? format(new Date(s.dt_open), 'dd.MM.yyyy HH:mm') : '—',
            status: s.dt_close ? 'Закрыта' : 'Открыта',
            size: '—',
          }))
          tree.set(`${sName}/${year}/${monthName}`, shiftFiles)
        }

        // Также добавим папки Смены/ТТН внутри года
        smenyNode.childCount = [...byYearMonth.entries()]
          .filter(([ym]) => ym.startsWith(year + '/'))
          .reduce((sum, [, s]) => sum + s.length, 0)

        tree.set(`${sName}/${year}`, [...monthNodes])
      }

      // Обновим childCount корневой папки
      const rootIdx = rootNodes.findIndex(n => n.name === sName)
      if (rootIdx >= 0) rootNodes[rootIdx].childCount = shifts.length
    }

    tree.set('', rootNodes)
    return tree
  }, [shifts, stId, settings.stations, MONTH_NAMES, filterStatus, searchQuery])

  // Текущий контент папки
  const currentNodes = useMemo(() => {
    const key = currentPath.join('/')
    let nodes = fsTree.get(key) ?? []

    // Поиск
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      // Поиск по всем файлам
      const allFiles: FsNode[] = []
      for (const [, items] of fsTree) {
        for (const item of items) {
          if (item.type === 'file' && item.name.toLowerCase().includes(q)) {
            allFiles.push(item)
          }
          if (item.type === 'file' && item.date?.includes(q)) {
            allFiles.push(item)
          }
        }
      }
      return [...new Map(allFiles.map(f => [f.path, f])).values()]
    }

    return nodes
  }, [fsTree, currentPath, searchQuery])

  function navigateTo(path: string[]) {
    setCurrentPath(path)
    setSearchQuery('')
  }

  function goUp() {
    if (currentPath.length > 0) {
      navigateTo(currentPath.slice(0, -1))
    }
  }

  function openFolder(name: string) {
    navigateTo([...currentPath, name])
  }

  function openFile(node: FsNode) {
    if (node.shift && node.stationId != null) {
      selectShift(node.stationId, node.shift.shift)
      // Добавить вкладку
      setOpenTabs(prev => {
        if (prev.some(t => t.path === node.path)) return prev
        return [...prev, node]
      })
      setActiveTabId(node.path)
    }
  }

  function closeTab(path: string) {
    setOpenTabs(prev => prev.filter(t => t.path !== path))
    if (activeTabId === path) {
      setActiveTabId(null)
    }
  }

  function switchTab(node: FsNode) {
    setActiveTabId(node.path)
    if (node.shift && node.stationId != null) {
      selectShift(node.stationId, node.shift.shift)
    }
  }

  const breadcrumbParts = [{ name: 'Хранилище', path: [] as string[] }, ...currentPath.map((seg, i) => ({
    name: seg,
    path: currentPath.slice(0, i + 1),
  }))]

  return (
    <div className="flex flex-col h-full">
      {/* Breadcrumb + open tabs */}
      <div className="border-b border-border/40 bg-card/20">
        {/* Path bar */}
        <div className="flex items-center gap-0.5 px-2 py-1 min-h-[28px] overflow-x-auto">
          {collapseButton}
          {currentPath.length > 0 && (
            <Button variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={goUp} title="Вверх">
              <ArrowUp className="h-3 w-3" />
            </Button>
          )}
          {breadcrumbParts.map((part, i) => (
            <span key={i} className="flex items-center shrink-0">
              {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground/40 mx-0.5" />}
              <button
                onClick={() => navigateTo(part.path)}
                className={`text-[11px] px-1 py-0.5 rounded hover:bg-accent/50 transition-colors ${
                  i === breadcrumbParts.length - 1 ? 'font-semibold text-foreground' : 'text-muted-foreground'
                }`}
              >
                {part.name}
              </button>
            </span>
          ))}
        </div>

        {/* Open document tabs */}
        {openTabs.length > 0 && (
          <div className="flex items-center gap-0.5 px-2 py-0.5 overflow-x-auto border-t border-border/20">
            {openTabs.map((tab) => (
              <div key={tab.path}
                className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] cursor-pointer transition-colors shrink-0 ${
                  activeTabId === tab.path
                    ? 'bg-primary/15 text-primary font-semibold'
                    : 'text-muted-foreground hover:bg-accent/40'
                }`}
              >
                <button onClick={() => switchTab(tab)} className="flex items-center gap-1">
                  <FileText className="h-3 w-3 shrink-0" />
                  <span className="max-w-[100px] truncate">{tab.name}</span>
                </button>
                <button onClick={() => closeTab(tab.path)}
                  className="h-3.5 w-3.5 flex items-center justify-center rounded hover:bg-destructive/20 hover:text-destructive transition-colors ml-0.5">
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Toolbar: поиск + вид + обновить */}
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border/30">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
          <Input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={`Поиск в: ${currentPath.length > 0 ? currentPath[currentPath.length - 1] : 'Хранилище'}`}
            className="h-7 text-xs pl-7" />
        </div>
        <div className="flex items-center border border-border/40 rounded-md">
          <Button variant={viewMode === 'list' ? 'secondary' : 'ghost'} size="icon" className="h-7 w-7 rounded-r-none"
            onClick={() => setViewMode('list')} title="Список">
            <List className="h-3 w-3" />
          </Button>
          <Button variant={viewMode === 'tree' ? 'secondary' : 'ghost'} size="icon" className="h-7 w-7 rounded-none border-x border-border/40"
            onClick={() => setViewMode('tree')} title="Дерево">
            <GitBranchPlus className="h-3 w-3" />
          </Button>
          <Button variant={viewMode === 'grid' ? 'secondary' : 'ghost'} size="icon" className="h-7 w-7 rounded-l-none"
            onClick={() => setViewMode('grid')} title="Плитка">
            <LayoutGrid className="h-3 w-3" />
          </Button>
        </div>
        <Button variant={showFilter ? 'secondary' : 'ghost'} size="icon" className="h-7 w-7 shrink-0"
          onClick={() => setShowFilter(!showFilter)} title="Фильтр">
          <SlidersHorizontal className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={handleRefresh} disabled={isFetching} title="Обновить">
          <RefreshCw className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* Filter panel */}
      {showFilter && (
        <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border/30 bg-card/30">
          <Select value={filterDocType} onValueChange={(v) => setFilterDocType(v as typeof filterDocType)}>
            <SelectTrigger className="h-7 w-[90px] text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все типы</SelectItem>
              <SelectItem value="shifts">Смены</SelectItem>
              <SelectItem value="receipts">ТТН</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterStatus} onValueChange={(v) => setFilterStatus(v as typeof filterStatus)}>
            <SelectTrigger className="h-7 w-[100px] text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все статусы</SelectItem>
              <SelectItem value="open">Открытые</SelectItem>
              <SelectItem value="closed">Закрытые</SelectItem>
            </SelectContent>
          </Select>
          {(filterDocType !== 'all' || filterStatus !== 'all') && (
            <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0"
              onClick={() => { setFilterDocType('all'); setFilterStatus('all') }} title="Сбросить">
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>
      )}

      {/* Content */}
      <ScrollArea className="flex-1">
        {isLoading && (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!isLoading && currentNodes.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-8">
            {searchQuery ? 'Ничего не найдено' : 'Пустая папка'}
          </p>
        )}

        {/* Вид СПИСОК */}
        {viewMode === 'list' && currentNodes.length > 0 && (
          <div>
            {/* Заголовок таблицы */}
            <div className="flex items-center gap-2 px-3 py-1 border-b border-border/30 text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wider">
              <span className="flex-1">Имя</span>
              <span className="w-28 text-right">Дата</span>
              <span className="w-16 text-right">Тип</span>
              <span className="w-14 text-right">Размер</span>
            </div>

            {/* Папки сначала, потом файлы */}
            {currentNodes.filter(n => n.type === 'folder').map((node) => (
              <button key={node.path}
                onDoubleClick={() => openFolder(node.name)}
                onClick={() => openFolder(node.name)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/40 transition-colors border-b border-border/10">
                <Folder className="h-4 w-4 text-amber-500 shrink-0" />
                <span className="flex-1 font-medium text-left truncate">{node.name}</span>
                <span className="w-28 text-right text-muted-foreground">—</span>
                <span className="w-16 text-right text-muted-foreground">Папка</span>
                <span className="w-14 text-right text-muted-foreground">
                  {node.childCount != null ? `${node.childCount}` : '—'}
                </span>
              </button>
            ))}

            {currentNodes.filter(n => n.type === 'file').map((node) => {
              const isSelected = node.shift && selectedShiftNumber === node.shift.shift && selectedStationId === node.stationId
              return (
                <button key={node.path}
                  onClick={() => openFile(node)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/40 transition-colors border-b border-border/10 ${
                    isSelected ? 'bg-primary/10' : ''
                  }`}>
                  <FileText className={`h-4 w-4 shrink-0 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                  <span className={`flex-1 text-left truncate ${isSelected ? 'font-semibold text-primary' : 'font-medium'}`}>
                    {node.name}
                  </span>
                  <span className="w-28 text-right text-muted-foreground">{node.date ?? '—'}</span>
                  <span className="w-16 text-right">
                    {node.status && (
                      <Badge variant={node.status === 'Закрыта' ? 'secondary' : 'default'} className="text-[8px] h-4 px-1">
                        {node.status === 'Закрыта' ? 'Закр.' : 'Откр.'}
                      </Badge>
                    )}
                  </span>
                  <span className="w-14 text-right text-muted-foreground">{node.size ?? '—'}</span>
                </button>
              )
            })}
          </div>
        )}

        {/* Вид ПЛИТКА */}
        {viewMode === 'grid' && currentNodes.length > 0 && (
          <div className="p-2 grid grid-cols-2 gap-1.5">
            {currentNodes.map((node) => {
              const isSelected = node.shift && selectedShiftNumber === node.shift.shift && selectedStationId === node.stationId
              const isFolder = node.type === 'folder'

              return (
                <button key={node.path}
                  onClick={() => isFolder ? openFolder(node.name) : openFile(node)}
                  className={`flex flex-col items-center gap-1 p-3 rounded-lg hover:bg-accent/40 transition-colors text-center ${
                    isSelected ? 'bg-primary/10 ring-1 ring-primary/30' : ''
                  }`}>
                  {isFolder
                    ? <FolderOpen className="h-8 w-8 text-amber-500" />
                    : <FileText className={`h-8 w-8 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                  }
                  <span className="text-[11px] font-medium truncate w-full">{node.name}</span>
                  {!isFolder && node.date && (
                    <span className="text-[9px] text-muted-foreground">{node.date}</span>
                  )}
                  {isFolder && node.childCount != null && (
                    <span className="text-[9px] text-muted-foreground">{node.childCount} эл.</span>
                  )}
                </button>
              )
            })}
          </div>
        )}
        {/* Вид ДЕРЕВО */}
        {viewMode === 'tree' && !isLoading && (
          <TreeView
            fsTree={fsTree}
            path={[]}
            depth={0}
            selectedShiftNumber={selectedShiftNumber}
            selectedStationId={selectedStationId}
            onSelectFile={openFile}
          />
        )}
      </ScrollArea>

      {/* Footer — статус */}
      <div className="px-3 py-1 border-t border-border/50 text-[10px] text-muted-foreground flex items-center justify-between">
        <span>{currentNodes.length} элементов</span>
        <span>{currentPath.length > 0 ? currentPath.join(' / ') : 'Хранилище'}</span>
      </div>
    </div>
  )
}
