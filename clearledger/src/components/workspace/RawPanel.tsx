/**
 * Панель 2: Загруженные документы (Raw) из STS API.
 * Список смен с фильтром. Клик → выбор смены → CorePanel.
 */

import { useState } from 'react'
import { useShifts } from '@/hooks/useFuel'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'

export function RawPanel({ hideHeader = false }: { hideHeader?: boolean }) {
  const settings = getSettings()
  const queryClient = useQueryClient()
  const { selectedStationId, selectedShiftNumber, selectShift } = useWorkspace()
  const [stationFilter, setStationFilter] = useState<string>('all')

  const filterStation = stationFilter === 'all' ? undefined : Number(stationFilter)
  const { data: shifts, isLoading, isFetching } = useShifts(filterStation)

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      {!hideHeader && (
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-border/50">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Загруженные
          </h2>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleRefresh} disabled={isFetching}>
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      )}

      {/* Station filter */}
      <div className="px-3 py-2 border-b border-border/30">
        <Select value={stationFilter} onValueChange={setStationFilter}>
          <SelectTrigger className="h-8 text-xs">
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
      </div>

      {/* Shifts list */}
      <ScrollArea className="flex-1">
        {isLoading && (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {shifts && shifts.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-8">Смен не найдено</p>
        )}

        {shifts?.map((shift) => {
          const isSelected =
            selectedShiftNumber === shift.shift &&
            selectedStationId === (filterStation ?? settings.stations[0]?.code)
          const stId = filterStation ?? settings.stations[0]?.code ?? 0

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
                <Badge
                  variant={shift.dt_close ? 'secondary' : 'default'}
                  className="text-[10px] h-5"
                >
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
      </ScrollArea>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-border/50 text-[10px] text-muted-foreground">
        {shifts ? `${shifts.length} смен` : '...'}
      </div>
    </div>
  )
}
