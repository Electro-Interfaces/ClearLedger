import { useMemo } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Search, BarChart3, FolderTree } from 'lucide-react'
import { RawPanelFilterTab } from './RawPanelFilterTab'
import { RawPanelStatsTab } from './RawPanelStatsTab'
import { RawPanelGroupTab } from './RawPanelGroupTab'
import type { FsNode, DocumentStats, StatsBreakdown } from './raw-panel-types'
import type { RawPanelState } from './useRawPanelState'

interface Props {
  state: RawPanelState
  flatFiles: FsNode[]
  totalCount: number
}

function computeStats(files: FsNode[], total: number): DocumentStats {
  const byStatusMap = new Map<string, number>()
  const byCategoryMap = new Map<string, number>()
  const byObjectMap = new Map<string, number>()
  const byMonthMap = new Map<string, number>()
  const bySourceMap = new Map<string, number>()

  for (const f of files) {
    // Status
    const st = f.status ?? 'Неизвестен'
    byStatusMap.set(st, (byStatusMap.get(st) ?? 0) + 1)

    // Category (derive from docType or name)
    const cat = f.docType === 'delivery' || f.name.includes('ТТН') ? 'Поступления' : 'Торговля'
    byCategoryMap.set(cat, (byCategoryMap.get(cat) ?? 0) + 1)

    // Object (station)
    const obj = f.stationId != null ? `Станция ${f.stationId}` : 'Не привязан'
    byObjectMap.set(obj, (byObjectMap.get(obj) ?? 0) + 1)

    // Month
    if (f.date && f.date !== '—') {
      const parts = f.date.split('.')
      if (parts.length >= 3) {
        const monthKey = `${parts[1]}.${parts[2].slice(0, 4)}`
        byMonthMap.set(monthKey, (byMonthMap.get(monthKey) ?? 0) + 1)
      }
    }

    // Source
    const src = 'STS API'
    bySourceMap.set(src, (bySourceMap.get(src) ?? 0) + 1)
  }

  function toBreakdown(map: Map<string, number>): StatsBreakdown[] {
    const t = files.length || 1
    return [...map.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, count]) => ({ label, count, percent: Math.round((count / t) * 100) }))
  }

  return {
    total,
    filtered: files.length,
    byStatus: toBreakdown(byStatusMap),
    byCategory: toBreakdown(byCategoryMap),
    byObject: toBreakdown(byObjectMap),
    byMonth: toBreakdown(byMonthMap),
    bySource: toBreakdown(bySourceMap),
  }
}

export function RawPanelFilterDialog({ state, flatFiles, totalCount }: Props) {
  const { filterDialogOpen, setFilterDialogOpen, advancedFilters, setAdvancedFilters,
    applyPreset, clearAdvancedFilters, groupMode, setGroupMode, sortConfig, toggleSort } = state

  // Derive dynamic options from data
  const options = useMemo(() => {
    const categories = new Set<string>()
    const docTypes = new Set<string>()
    const objects: { id: string; name: string }[] = []
    const objectIds = new Set<string>()

    for (const f of flatFiles) {
      const cat = f.docType === 'delivery' || f.name.includes('ТТН') ? 'Поступления' : 'Торговля'
      categories.add(cat)
      const dt = f.docType === 'delivery' ? 'ТТН' : 'Сменный отчёт'
      docTypes.add(dt)
      if (f.stationId != null) {
        const id = String(f.stationId)
        if (!objectIds.has(id)) {
          objectIds.add(id)
          objects.push({ id, name: `Станция ${f.stationId}` })
        }
      }
    }

    return {
      categories: [...categories],
      docTypes: [...docTypes],
      objects,
      sources: ['STS API'],
    }
  }, [flatFiles])

  // Compute stats for current data
  const stats = useMemo(() => computeStats(flatFiles, totalCount), [flatFiles, totalCount])

  return (
    <Dialog open={filterDialogOpen} onOpenChange={setFilterDialogOpen}>
      <DialogContent className="max-w-[700px] max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Фильтр и аналитика документов</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="filters" className="flex-1 min-h-0 flex flex-col">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="filters" className="gap-1.5">
              <Search className="h-3.5 w-3.5" /> Фильтры
            </TabsTrigger>
            <TabsTrigger value="stats" className="gap-1.5">
              <BarChart3 className="h-3.5 w-3.5" /> Статистика
            </TabsTrigger>
            <TabsTrigger value="group" className="gap-1.5">
              <FolderTree className="h-3.5 w-3.5" /> Группировка
            </TabsTrigger>
          </TabsList>

          <div className="flex-1 overflow-y-auto min-h-0 py-4">
            <TabsContent value="filters" className="mt-0">
              <RawPanelFilterTab
                filters={advancedFilters}
                onChange={setAdvancedFilters}
                onPreset={applyPreset}
                onClear={clearAdvancedFilters}
                filteredCount={flatFiles.length}
                totalCount={totalCount}
                categories={options.categories}
                docTypes={options.docTypes}
                objects={options.objects}
                sources={options.sources}
              />
            </TabsContent>

            <TabsContent value="stats" className="mt-0">
              <RawPanelStatsTab stats={stats} />
            </TabsContent>

            <TabsContent value="group" className="mt-0">
              <RawPanelGroupTab
                groupMode={groupMode}
                onGroupModeChange={setGroupMode}
                sortConfig={sortConfig}
                onSortChange={(cfg) => {
                  toggleSort(cfg.column)
                }}
              />
            </TabsContent>
          </div>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={clearAdvancedFilters}>Очистить</Button>
          <Button onClick={() => setFilterDialogOpen(false)}>Применить</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
