/**
 * Общий тулбар рабочего стола — над всеми 3 панелями.
 * Глобальные фильтры (станция, период) + счётчики.
 */

import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { useShifts } from '@/hooks/useFuel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RefreshCw, ClipboardList, Database, FileOutput } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

export function WorkspaceToolbar() {
  const settings = getSettings()
  const queryClient = useQueryClient()
  const { globalStation, setGlobalStation, exportDocs } = useWorkspace()
  const { data: shifts, isFetching } = useShifts(
    globalStation === 'all' ? undefined : Number(globalStation),
  )

  const shiftsCount = shifts?.length ?? 0
  const closedCount = shifts?.filter((s) => s.dt_close).length ?? 0
  const exportCount = exportDocs.length

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-shift-report'] })
    queryClient.invalidateQueries({ queryKey: ['sts-receipts'] })
  }

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 border-b border-border/50 bg-card/30 flex-shrink-0">
      {/* Станция */}
      <Select value={globalStation} onValueChange={setGlobalStation}>
        <SelectTrigger className="h-7 w-[160px] text-xs">
          <SelectValue placeholder="Все станции" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все станции</SelectItem>
          {settings.stations.map((s) => (
            <SelectItem key={s.code} value={String(s.code)}>
              {s.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Обновить */}
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={handleRefresh}
        disabled={isFetching}
        title="Обновить данные"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
      </Button>

      {/* Разделитель */}
      <div className="h-4 w-px bg-border/50" />

      {/* Счётчики */}
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <ClipboardList className="h-3 w-3" />
          <span>{shiftsCount} смен</span>
          {closedCount > 0 && (
            <Badge variant="secondary" className="text-[9px] h-4 px-1">
              {closedCount} закр.
            </Badge>
          )}
        </span>

        <span className="flex items-center gap-1.5">
          <Database className="h-3 w-3" />
          <span>Обработано: —</span>
        </span>

        <span className="flex items-center gap-1.5">
          <FileOutput className="h-3 w-3" />
          <span>Для 1С:</span>
          <Badge
            variant={exportCount > 0 ? 'default' : 'secondary'}
            className="text-[9px] h-4 px-1"
          >
            {exportCount}
          </Badge>
        </span>
      </div>
    </div>
  )
}
