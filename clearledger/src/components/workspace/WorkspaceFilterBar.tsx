/**
 * Свёрнутый основной фильтр рабочей области — строка со сводкой параметров.
 * Клик открывает модалку полной настройки (`WorkspaceFilterModal`).
 * Показывает установленные значения: период · станция · точки · регионы · типы.
 */

import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { SlidersHorizontal, RefreshCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useLocations } from '@/hooks/useLocations'
import { useShifts } from '@/hooks/useFuel'
import { getStsStationsFromLocations } from '@/services/locationService'
import { WorkspaceFilterModal } from './WorkspaceFilterModal'
import { ViewHistoryMenu } from './ViewHistoryMenu'
import { cn } from '@/lib/utils'

function fmtShort(iso: string): string {
  // YYYY-MM-DD → DD.MM (без внешних зависимостей)
  const [, m, d] = iso.split('-')
  return d && m ? `${d}.${m}` : iso
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'shrink-0 px-2 py-0.5 rounded text-xs transition-colors',
        active
          ? 'bg-primary/15 text-primary font-medium'
          : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
      )}
    >
      {label}
    </button>
  )
}

export function WorkspaceFilterBar() {
  const { period, stationCode, locationIds, regionIds, stationCodes, docTypeIds, clearAll, commitToHistory } = useFilters()
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const locations = useLocations()
  const stations = getStsStationsFromLocations()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { isFetching } = useShifts(stationCode === 'all' ? undefined : Number(stationCode))

  const stationLabel = useMemo(() => {
    if (isEnergy || stationCode === 'all') return 'Все станции'
    return stations.find((s) => String(s.code) === stationCode)?.name ?? `Станция ${stationCode}`
  }, [isEnergy, stationCode, stations])

  const locationLabel = useMemo(() => {
    if (locationIds.length === 0) return 'Все точки'
    if (locationIds.length === 1) return locations.find((l) => l.id === locationIds[0])?.name ?? '1 точка'
    return `Точек: ${locationIds.length}`
  }, [locationIds, locations])

  const regionLabel = regionIds.length === 0 ? 'Все регионы' : regionIds.length === 1 ? regionIds[0] : `Регионов: ${regionIds.length}`
  const docLabel = docTypeIds.length === 0 ? 'Все типы' : `Типов: ${docTypeIds.length}`
  const eszLabel = stationCodes.length === 0 ? 'Все ЭЗС' : `ЭЗС: ${stationCodes.length}`
  const activeCount = locationIds.length + regionIds.length + stationCodes.length + docTypeIds.length

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-shift-report'] })
    queryClient.invalidateQueries({ queryKey: ['sts-receipts'] })
  }

  return (
    <div className="flex items-center gap-1.5 min-w-0">
      {/* Кнопка «настроить» + свёрнутая сводка (вся строка открывает модалку) */}
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        onClick={() => setOpen(true)}
        title="Настроить фильтр рабочей области"
      >
        <SlidersHorizontal className="h-3.5 w-3.5" />
      </Button>

      <div className="flex items-center gap-0.5 min-w-0 overflow-x-auto scrollbar-hide">
        <Chip label={`${fmtShort(period.from)} – ${fmtShort(period.to)}`} active onClick={() => setOpen(true)} />
        <span className="text-border/60">·</span>
        {!isEnergy ? (
          <>
            <Chip label={stationLabel} active={stationCode !== 'all'} onClick={() => setOpen(true)} />
            <span className="text-border/60">·</span>
            <Chip label={locationLabel} active={locationIds.length > 0} onClick={() => setOpen(true)} />
          </>
        ) : (
          <Chip label={eszLabel} active={stationCodes.length > 0} onClick={() => setOpen(true)} />
        )}
        <span className="text-border/60">·</span>
        <Chip label={regionLabel} active={regionIds.length > 0} onClick={() => setOpen(true)} />
        <span className="text-border/60">·</span>
        <Chip label={docLabel} active={docTypeIds.length > 0} onClick={() => setOpen(true)} />
      </div>

      {activeCount > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs gap-1 text-muted-foreground hover:text-foreground shrink-0"
          onClick={clearAll}
          title="Сбросить выборки (период сохраняется)"
        >
          <X className="h-3.5 w-3.5" />
          {activeCount}
        </Button>
      )}

      <div className="ml-auto flex items-center gap-1 shrink-0">
        <ViewHistoryMenu />
        {!isEnergy && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleRefresh}
            disabled={isFetching}
            title="Обновить данные STS"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
          </Button>
        )}
      </div>

      <WorkspaceFilterModal
        open={open}
        onOpenChange={(v) => {
          if (!v) commitToHistory() // закрытие модалки = применение набора → в историю
          setOpen(v)
        }}
      />
    </div>
  )
}
