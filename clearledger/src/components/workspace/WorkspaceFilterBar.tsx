import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays, Database, FileText, MapPinned, RefreshCw, RotateCcw,
  SlidersHorizontal, type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useFilters } from '@/contexts/FilterContext'
import { activeFilterCount } from '@/contexts/filterState'
import { useCompany } from '@/contexts/CompanyContext'
import { useLocations } from '@/hooks/useLocations'
import { useShifts } from '@/hooks/useFuel'
import { getStsStationsFromLocations } from '@/services/locationService'
import { WorkspaceFilterModal } from './WorkspaceFilterModal'
import { ViewHistoryMenu } from './ViewHistoryMenu'
import { cn } from '@/lib/utils'

function fmtShort(iso: string): string {
  const [, m, d] = iso.split('-')
  return d && m ? `${d}.${m}` : iso
}

function SummaryControl({
  icon: Icon,
  label,
  value,
  active = false,
  onClick,
}: {
  icon: LucideIcon
  label: string
  value: string
  active?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label}: ${value}`}
      className={cn(
        'group flex h-9 shrink-0 items-center gap-2 rounded-lg px-2.5 text-left transition-colors',
        active
          ? 'bg-primary/10 text-primary hover:bg-primary/15'
          : 'text-foreground hover:bg-muted/70',
      )}
    >
      <Icon className="size-4 shrink-0 opacity-75" aria-hidden="true" />
      <span className="min-w-0">
        <span className="block text-[10px] leading-3 text-muted-foreground">{label}</span>
        <span className="block max-w-40 truncate text-xs font-medium leading-4">{value}</span>
      </span>
    </button>
  )
}

export function WorkspaceFilterBar() {
  const filters = useFilters()
  const { period, stationCode, locationIds, regionIds, stationCodes, docTypeIds, clearAll } = filters
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const locations = useLocations()
  const stations = getStsStationsFromLocations()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { isFetching } = useShifts(stationCode === 'all' ? undefined : Number(stationCode))
  const count = activeFilterCount(filters.state)

  const scopeLabel = useMemo(() => {
    if (isEnergy && stationCodes.length > 0) return stationCodes.length === 1 ? '1 ЭЗС' : `ЭЗС: ${stationCodes.length}`
    if (locationIds.length === 1) return locations.find((l) => l.id === locationIds[0])?.name ?? '1 точка'
    if (locationIds.length > 1) return `Точек: ${locationIds.length}`
    if (regionIds.length === 1) return regionIds[0]
    if (regionIds.length > 1) return `Регионов: ${regionIds.length}`
    return 'Вся сеть'
  }, [isEnergy, locationIds, locations, regionIds, stationCodes.length])

  const sourceLabel = useMemo(() => {
    if (stationCode === 'all') return 'Все станции STS'
    return stations.find((s) => String(s.code) === stationCode)?.name ?? `Станция ${stationCode}`
  }, [stationCode, stations])

  const docLabel = docTypeIds.length === 0 ? 'Все типы данных' : `Типов: ${docTypeIds.length}`

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-shift-report'] })
    queryClient.invalidateQueries({ queryKey: ['sts-receipts'] })
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
      <Button
        variant="outline"
        size="sm"
        className="h-9 rounded-lg px-2.5"
        onClick={() => setOpen(true)}
        aria-label={count > 0 ? `Настроить фильтры, активно: ${count}` : 'Настроить фильтры'}
      >
        <SlidersHorizontal data-icon="inline-start" />
        <span className="hidden sm:inline">Фильтры</span>
        {count > 0 ? <Badge className="min-w-5 px-1.5">{count}</Badge> : null}
      </Button>

      <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto scrollbar-hide">
        <SummaryControl
          icon={CalendarDays}
          label="Период"
          value={`${fmtShort(period.from)}–${fmtShort(period.to)}`}
          active
          onClick={() => setOpen(true)}
        />
        <SummaryControl
          icon={MapPinned}
          label="Область учёта"
          value={scopeLabel}
          active={locationIds.length + regionIds.length + stationCodes.length > 0}
          onClick={() => setOpen(true)}
        />
        <SummaryControl
          icon={FileText}
          label="Данные"
          value={docLabel}
          active={docTypeIds.length > 0}
          onClick={() => setOpen(true)}
        />
        {!isEnergy ? (
          <SummaryControl
            icon={Database}
            label="Источник STS"
            value={sourceLabel}
            active={stationCode !== 'all'}
            onClick={() => setOpen(true)}
          />
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {count > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-9 rounded-lg px-2.5 text-muted-foreground"
            onClick={clearAll}
            aria-label="Сбросить все ограничения, период сохранить"
          >
            <RotateCcw data-icon="inline-start" />
            <span className="hidden xl:inline">Сбросить</span>
          </Button>
        ) : null}
        <ViewHistoryMenu />
        {!isEnergy ? (
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-9 rounded-lg"
            onClick={handleRefresh}
            disabled={isFetching}
            aria-label="Обновить данные STS"
          >
            <RefreshCw className={cn(isFetching && 'animate-spin')} />
          </Button>
        ) : null}
      </div>

      <WorkspaceFilterModal key={open ? 'open' : 'closed'} open={open} onOpenChange={setOpen} />
    </div>
  )
}
