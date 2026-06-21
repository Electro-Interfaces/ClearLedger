/**
 * Общий тулбар рабочего стола — над панелями режимов.
 * Станция, обновление, переключатель режимов (Сверка/Управленческий/.../Выгрузка).
 * «Нормализация» вынесена в отдельный пункт левого меню (/normalization).
 */

import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getStsStationsFromLocations } from '@/services/locationService'
import { useLocations } from '@/hooks/useLocations'
import { useShifts } from '@/hooks/useFuel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { RefreshCw, BarChart3, Landmark, BookOpen, Receipt, FileOutput } from 'lucide-react'
import type { CoreMode } from '@/contexts/WorkspaceContext'
import { useQueryClient } from '@tanstack/react-query'

export function WorkspaceToolbar() {
  useLocations()   // гидратация точек активной компании
  const stations = getStsStationsFromLocations()
  const queryClient = useQueryClient()
  const { globalStation, setGlobalStation, coreMode, setCoreMode } = useWorkspace()
  const { isFetching } = useShifts(
    globalStation === 'all' ? undefined : Number(globalStation),
  )

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-shift-report'] })
    queryClient.invalidateQueries({ queryKey: ['sts-receipts'] })
  }

  return (
    <div className="flex items-center px-3 py-1.5 border-b border-border/50 bg-background flex-shrink-0">
      {/* Станция */}
      <Select value={globalStation} onValueChange={setGlobalStation}>
        <SelectTrigger className="h-7 w-[160px] text-xs">
          <SelectValue placeholder="Все станции" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все станции</SelectItem>
          {stations.map((s) => (
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
        className="h-7 w-7 ml-1"
        onClick={handleRefresh}
        disabled={isFetching}
        title="Обновить данные"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
      </Button>

      <div className="h-4 w-px bg-border/50 mx-2" />

      {/* Конвейер — переключатель режимов */}
      <div className="flex items-center gap-0.5 bg-muted/40 rounded-md p-0.5">
        {([
          { mode: 'management' as CoreMode, icon: BarChart3, label: 'Управленческий' },
          { mode: 'financial' as CoreMode, icon: Landmark, label: 'Финансовый' },
          { mode: 'accounting' as CoreMode, icon: BookOpen, label: 'Бухгалтерский' },
          { mode: 'tax' as CoreMode, icon: Receipt, label: 'Налоговый' },
          { mode: 'export' as CoreMode, icon: FileOutput, label: 'Выгрузка' },
        ]).map(({ mode, icon: Icon, label }) => (
          <button
            key={mode}
            onClick={() => setCoreMode(mode)}
            className={`flex items-center gap-1 px-2 py-1 rounded text-sm font-medium transition-colors ${
              coreMode === mode ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="h-3 w-3" />
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
