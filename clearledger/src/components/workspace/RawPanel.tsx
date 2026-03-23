/**
 * Панель 2: Загруженные документы (Raw).
 * Режимы: Список / Каталог. Поиск, фильтр по типу.
 */

import { useState, useMemo } from 'react'
import { useShifts } from '@/hooks/useFuel'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, RefreshCw, List, FolderTree, Search, ChevronRight, FolderOpen, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import type { StsShift } from '@/services/fuel/types'

type ViewMode = 'list' | 'catalog'
type DocFilter = 'all' | 'shifts' | 'receipts'

export function RawPanel({ hideHeader = false }: { hideHeader?: boolean }) {
  const settings = getSettings()
  const queryClient = useQueryClient()
  const { globalStation, selectedStationId, selectedShiftNumber, selectShift } = useWorkspace()

  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [docFilter, setDocFilter] = useState<DocFilter>('shifts')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())

  const filterStation = globalStation === 'all' ? undefined : Number(globalStation)
  const { data: shifts, isLoading, isFetching } = useShifts(filterStation)

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
  }

  // Фильтрация по поиску
  const filteredShifts = useMemo(() => {
    if (!shifts) return []
    if (!searchQuery.trim()) return shifts
    const q = searchQuery.toLowerCase()
    return shifts.filter((s) =>
      String(s.shift).includes(q) ||
      (s.dt_open && format(new Date(s.dt_open), 'dd.MM.yyyy').includes(q))
    )
  }, [shifts, searchQuery])

  // Глубокая иерархия: Год → Месяц → АЗС → Тип (Смены/ТТН)
  const catalogTree = useMemo(() => {
    const tree: Record<string, Record<string, StsShift[]>> = {} // year → month → shifts
    for (const s of filteredShifts) {
      const d = s.dt_open ? new Date(s.dt_open) : null
      const year = d ? String(d.getFullYear()) : '—'
      const month = d ? String(d.getMonth() + 1).padStart(2, '0') : '00'
      const key = `${year}-${month}`
      if (!tree[year]) tree[year] = {}
      if (!tree[year][key]) tree[year][key] = []
      tree[year][key].push(s)
    }
    return tree
  }, [filteredShifts])

  const stId = filterStation ?? settings.stations[0]?.code ?? 0
  const stationName = settings.stations.find(s => s.code === stId)?.name ?? `АЗС-${stId}`

  const MONTH_NAMES = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

  function toggleFolder(key: string) {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      {!hideHeader && (
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/50">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Загруженные
          </h2>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setViewMode(viewMode === 'list' ? 'catalog' : 'list')}
            title={viewMode === 'list' ? 'Каталог' : 'Список'}>
            {viewMode === 'list' ? <FolderTree className="h-3.5 w-3.5" /> : <List className="h-3.5 w-3.5" />}
          </Button>
        </div>
      )}

      {/* Toolbar: тип + поиск + счётчик + обновить */}
      <div className="px-2 py-1.5 border-b border-border/30 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Select value={docFilter} onValueChange={(v) => setDocFilter(v as DocFilter)}>
            <SelectTrigger className="h-7 w-[90px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все</SelectItem>
              <SelectItem value="shifts">Смены</SelectItem>
              <SelectItem value="receipts">ТТН</SelectItem>
            </SelectContent>
          </Select>

          {/* Переключатель вида */}
          <div className="flex items-center border border-border/40 rounded-md">
            <Button variant={viewMode === 'list' ? 'secondary' : 'ghost'} size="icon" className="h-7 w-7 rounded-r-none"
              onClick={() => setViewMode('list')} title="Список">
              <List className="h-3 w-3" />
            </Button>
            <Button variant={viewMode === 'catalog' ? 'secondary' : 'ghost'} size="icon" className="h-7 w-7 rounded-l-none"
              onClick={() => setViewMode('catalog')} title="Каталог">
              <FolderTree className="h-3 w-3" />
            </Button>
          </div>

          <div className="ml-auto flex items-center gap-1">
            <Badge variant="secondary" className="text-[9px] h-4 px-1.5">
              {filteredShifts.length}
            </Badge>
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleRefresh} disabled={isFetching} title="Обновить">
              <RefreshCw className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>

        {/* Поиск */}
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Поиск по номеру, дате..."
            className="h-7 text-xs pl-7"
          />
        </div>
      </div>

      {/* Content */}
      <ScrollArea className="flex-1">
        {isLoading && (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!isLoading && filteredShifts.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-8">
            {searchQuery ? 'Ничего не найдено' : 'Смен не найдено'}
          </p>
        )}

        {/* Режим СПИСОК */}
        {viewMode === 'list' && filteredShifts.map((shift) => {
          const isSelected = selectedShiftNumber === shift.shift && selectedStationId === stId

          return (
            <button
              key={`${stId}-${shift.shift}`}
              onClick={() => selectShift(stId, shift.shift)}
              className={`w-full text-left px-3 py-2.5 border-b border-border/20 transition-colors hover:bg-accent/50 ${
                isSelected ? 'bg-primary/10 border-l-2 border-l-primary' : ''
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`text-sm font-semibold ${isSelected ? 'text-primary' : ''}`}>
                  Смена №{shift.shift}
                </span>
                <Badge variant={shift.dt_close ? 'secondary' : 'default'} className="text-[10px] h-5">
                  {shift.dt_close ? 'Закр.' : 'Откр.'}
                </Badge>
              </div>
              <div className="text-[11px] text-muted-foreground mt-0.5">
                {shift.dt_open ? format(new Date(shift.dt_open), 'dd.MM.yyyy HH:mm') : '—'}
                {shift.dt_close ? ` — ${format(new Date(shift.dt_close), 'HH:mm')}` : ''}
              </div>
            </button>
          )
        })}

        {/* Режим КАТАЛОГ — Год → Месяц → АЗС → Смены/ТТН */}
        {viewMode === 'catalog' && (
          <div className="py-1">
            {Object.entries(catalogTree).sort(([a], [b]) => b.localeCompare(a)).map(([year, months]) => {
              const yearKey = `y-${year}`
              const yearExpanded = expandedFolders.has(yearKey) || expandedFolders.size === 0

              return (
                <div key={year}>
                  {/* Уровень 1: Год */}
                  <button onClick={() => toggleFolder(yearKey)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-accent/30 transition-colors">
                    <ChevronRight className={`h-3 w-3 text-muted-foreground transition-transform ${yearExpanded ? 'rotate-90' : ''}`} />
                    <FolderOpen className="h-3.5 w-3.5 text-amber-500" />
                    <span className="font-bold">{year}</span>
                  </button>

                  {yearExpanded && Object.entries(months).sort(([a], [b]) => b.localeCompare(a)).map(([monthKey, monthShifts]) => {
                    const monthNum = Number(monthKey.split('-')[1])
                    const monthExpanded = expandedFolders.has(monthKey) || expandedFolders.size === 0

                    return (
                      <div key={monthKey}>
                        {/* Уровень 2: Месяц */}
                        <button onClick={() => toggleFolder(monthKey)}
                          className="w-full flex items-center gap-2 pl-6 pr-2 py-1.5 text-xs hover:bg-accent/30 transition-colors">
                          <ChevronRight className={`h-3 w-3 text-muted-foreground transition-transform ${monthExpanded ? 'rotate-90' : ''}`} />
                          <FolderOpen className="h-3.5 w-3.5 text-blue-400" />
                          <span className="font-medium">{MONTH_NAMES[monthNum] || monthKey}</span>
                          <Badge variant="outline" className="text-[9px] h-4 px-1 ml-auto">{monthShifts.length}</Badge>
                        </button>

                        {monthExpanded && (() => {
                          const stationKey = `${monthKey}-s-${stId}`
                          const stationExpanded = expandedFolders.has(stationKey) || expandedFolders.size === 0

                          return (
                            <div>
                              {/* Уровень 3: АЗС */}
                              <button onClick={() => toggleFolder(stationKey)}
                                className="w-full flex items-center gap-2 pl-10 pr-2 py-1.5 text-xs hover:bg-accent/30 transition-colors">
                                <ChevronRight className={`h-3 w-3 text-muted-foreground transition-transform ${stationExpanded ? 'rotate-90' : ''}`} />
                                <FolderOpen className="h-3.5 w-3.5 text-emerald-400" />
                                <span className="font-medium">{stationName}</span>
                              </button>

                              {stationExpanded && (
                                <div>
                                  {/* Уровень 4: Тип — Смены */}
                                  {(() => {
                                    const shiftsKey = `${stationKey}-shifts`
                                    const shiftsExpanded = expandedFolders.has(shiftsKey) || expandedFolders.size === 0
                                    return (
                                      <div>
                                        <button onClick={() => toggleFolder(shiftsKey)}
                                          className="w-full flex items-center gap-2 pl-14 pr-2 py-1 text-xs hover:bg-accent/30 transition-colors">
                                          <ChevronRight className={`h-2.5 w-2.5 text-muted-foreground transition-transform ${shiftsExpanded ? 'rotate-90' : ''}`} />
                                          <FolderOpen className="h-3 w-3 text-purple-400" />
                                          <span className="font-medium text-muted-foreground">Смены</span>
                                          <Badge variant="outline" className="text-[8px] h-3.5 px-1 ml-auto">{monthShifts.length}</Badge>
                                        </button>

                                        {shiftsExpanded && monthShifts.map((shift) => {
                                          const isSelected = selectedShiftNumber === shift.shift && selectedStationId === stId
                                          return (
                                            <button key={shift.shift}
                                              onClick={() => selectShift(stId, shift.shift)}
                                              className={`w-full flex items-center gap-2 pl-[4.5rem] pr-2 py-1 text-[11px] hover:bg-accent/50 transition-colors ${
                                                isSelected ? 'bg-primary/10 text-primary' : ''
                                              }`}>
                                              <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                                              <span className={isSelected ? 'font-semibold text-primary' : ''}>
                                                №{shift.shift}
                                              </span>
                                              <span className="text-[10px] text-muted-foreground ml-auto">
                                                {shift.dt_open ? format(new Date(shift.dt_open), 'dd.MM') : ''}
                                              </span>
                                              <Badge variant={shift.dt_close ? 'secondary' : 'default'} className="text-[7px] h-3 px-0.5">
                                                {shift.dt_close ? 'З' : 'О'}
                                              </Badge>
                                            </button>
                                          )
                                        })}
                                      </div>
                                    )
                                  })()}

                                  {/* Уровень 4: Тип — ТТН (placeholder) */}
                                  <button className="w-full flex items-center gap-2 pl-14 pr-2 py-1 text-xs text-muted-foreground/50">
                                    <FolderOpen className="h-3 w-3" />
                                    <span>ТТН</span>
                                    <Badge variant="outline" className="text-[8px] h-3.5 px-1 ml-auto">0</Badge>
                                  </button>
                                </div>
                              )}
                            </div>
                          )
                        })()}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        )}
      </ScrollArea>

      {/* Footer */}
      <div className="px-3 py-1.5 border-t border-border/50 text-[10px] text-muted-foreground flex items-center justify-between">
        <span>{filteredShifts.length} документов</span>
        <span className="capitalize">{viewMode === 'list' ? 'Список' : 'Каталог'}</span>
      </div>
    </div>
  )
}
