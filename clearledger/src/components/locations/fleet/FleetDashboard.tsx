/**
 * Дашборд парка: блок «Требуют внимания» (4 предиката) + 6 распределений
 * (типы / опер.статус / жизн.статус / связка HubEx / топ регионов / топ владельцев).
 * Клик по бару — drill-down (срез + переход в список); клик по точке — окно станции.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  CircleSlash, Wrench, AlertTriangle, Unlink, ShieldCheck, ChevronRight,
} from 'lucide-react'
import { FleetDistributionBars } from './FleetDistributionBars'
import {
  ATTENTION, ATTENTION_META, ATTENTION_PATCH, type AttentionKey,
  type FleetStats, type LocationFilters,
} from './locationFleetService'
import { m } from './locationFleetService'
import type { ServiceLocation } from '@/types/location'

const ATTENTION_ICON: Record<AttentionKey, typeof Wrench> = {
  notWorking: CircleSlash, onRepair: Wrench, linkConflict: AlertTriangle, noBinding: Unlink,
}
const ATTENTION_KEYS: AttentionKey[] = ['notWorking', 'onRepair', 'linkConflict', 'noBinding']

// Семантичные цвета для статусных распределений.
const OP_HEX: Record<string, string> = {
  working: '#10b981', not_working: '#ef4444', on_repair: '#f59e0b', maintenance: '#3b82f6', unknown: '#94a3b8',
}
const LIFE_HEX: Record<string, string> = { active: '#10b981', closed: '#94a3b8', planned: '#3b82f6' }
const LINK_HEX: Record<string, string> = {
  ok: '#10b981', review: '#f59e0b', conflict: '#ef4444', test: '#94a3b8', no_match: '#94a3b8',
}

export function FleetDashboard({
  stats, locations, onDrillDown, onOpenLocation,
}: {
  stats: FleetStats
  /** Текущая (отфильтрованная) выборка — для списков «требуют внимания». */
  locations: ServiceLocation[]
  onDrillDown: (patch: Partial<LocationFilters>) => void
  onOpenLocation: (l: ServiceLocation) => void
}) {
  const totalAttention = ATTENTION_KEYS.reduce((s, k) => s + stats.attention[k], 0)

  return (
    <div className="space-y-4">
      {/* Требуют внимания */}
      {totalAttention === 0 ? (
        <Card className="border-emerald-500/30 bg-emerald-500/5">
          <CardContent className="flex items-center gap-3 py-4 text-sm">
            <ShieldCheck className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <span className="font-medium">Всё в порядке — точек, требующих внимания, нет.</span>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {ATTENTION_KEYS.map((k) => {
            const count = stats.attention[k]
            const Icon = ATTENTION_ICON[k]
            const items = locations.filter(ATTENTION[k]).slice(0, 5)
            return (
              <Card key={k} className={count > 0 ? 'border-amber-400/40' : undefined}>
                <CardContent className="pt-4">
                  <div className="mb-2 flex items-center gap-2">
                    <Icon className={`h-4 w-4 ${count > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`} />
                    <span className="text-sm font-medium">{ATTENTION_META[k].label}</span>
                    <Badge variant="secondary" className="ml-auto tabular-nums">{count}</Badge>
                  </div>
                  {count === 0 ? (
                    <p className="text-xs text-muted-foreground">Нет</p>
                  ) : (
                    <>
                      <div className="space-y-0.5">
                        {items.map((l) => (
                          <button key={l.id} onClick={() => onOpenLocation(l)}
                            className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-secondary/60">
                            <span className="truncate">{l.name}</span>
                            <span className="ml-auto shrink-0 font-mono text-muted-foreground">{m(l, 'number') || l.code}</span>
                          </button>
                        ))}
                      </div>
                      {count > items.length && (
                        <Button variant="ghost" size="sm" className="mt-1 h-7 w-full justify-between px-1 text-xs"
                          onClick={() => onDrillDown(ATTENTION_PATCH[k])}>
                          Показать все ({count})
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Распределения */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <FleetDistributionBars title="По типам точек" items={stats.byType} total={stats.total}
          onItemClick={(it) => onDrillDown({ types: [it.key] })} />
        <FleetDistributionBars title="По операционному статусу" items={stats.byOpStatus} total={stats.total}
          colorFor={(k) => OP_HEX[k] ?? '#94a3b8'}
          onItemClick={(it) => onDrillDown({ opStatuses: [it.key] })} />
        <FleetDistributionBars title="По жизненному статусу" items={stats.byLifeStatus} total={stats.total}
          colorFor={(k) => LIFE_HEX[k] ?? '#94a3b8'}
          onItemClick={(it) => onDrillDown({ lifeStatuses: [it.key as LocationFilters['lifeStatuses'][number]] })} />
        <FleetDistributionBars title="По связке HubEx" items={stats.byLinkStatus} total={stats.total}
          colorFor={(k) => LINK_HEX[k] ?? '#94a3b8'}
          onItemClick={(it) => onDrillDown({ linkStatuses: [it.key] })} />
        {stats.topRegions.length > 0 && (
          <FleetDistributionBars title="Топ регионов" items={stats.topRegions} total={stats.total}
            onItemClick={(it) => onDrillDown({ regions: [it.key] })} />
        )}
        {stats.topOwners.length > 0 && (
          <FleetDistributionBars title="Топ владельцев" items={stats.topOwners} total={stats.total}
            onItemClick={(it) => onDrillDown({ owners: [it.key] })} />
        )}
      </div>
    </div>
  )
}
