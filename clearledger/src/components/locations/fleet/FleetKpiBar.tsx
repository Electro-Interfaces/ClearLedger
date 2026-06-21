/**
 * KPI-полоса парка точек — кликабельные карточки (срез/сброс/переход в дашборд).
 */
import { Card, CardContent } from '@/components/ui/card'
import {
  MapPin, CheckCircle2, AlertTriangle, Unlink, Layers, Globe, type LucideIcon,
} from 'lucide-react'
import type { LocationFilters, FleetStats } from './locationFleetService'

function KpiCard({
  label, value, icon: Icon, accent, onClick,
}: {
  label: string
  value: number
  icon: LucideIcon
  accent?: 'default' | 'danger' | 'warn'
  onClick?: () => void
}) {
  const tone =
    accent === 'danger' ? 'text-red-600 dark:text-red-400 bg-red-500/10'
    : accent === 'warn' ? 'text-amber-600 dark:text-amber-400 bg-amber-500/10'
    : 'text-primary bg-primary/10'
  return (
    <Card className={onClick ? 'cursor-pointer transition-colors hover:bg-secondary/40' : undefined}>
      <CardContent className="flex items-center gap-3 p-3" onClick={onClick} role={onClick ? 'button' : undefined}>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tone}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-lg font-semibold leading-none tabular-nums">{value}</div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  )
}

export function FleetKpiBar({
  stats, fullTotal, onSlice, onShowDashboard,
}: {
  stats: FleetStats
  fullTotal: number
  /** patch=null → сброс фильтров; иначе срез (replace). */
  onSlice: (patch: Partial<LocationFilters> | null) => void
  onShowDashboard: () => void
}) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <KpiCard label="Всего точек" value={fullTotal} icon={MapPin} onClick={() => onSlice(null)} />
      <KpiCard label="Активных" value={stats.active} icon={CheckCircle2}
        onClick={() => onSlice({ lifeStatuses: ['active'] })} />
      <KpiCard label="Не работают / ремонт" value={stats.notWorkingOrRepair} icon={AlertTriangle}
        accent={stats.notWorkingOrRepair > 0 ? 'danger' : 'default'}
        onClick={() => onSlice({ opStatuses: ['not_working', 'on_repair'] })} />
      <KpiCard label="Без привязки" value={stats.noBindingCount} icon={Unlink}
        accent={stats.noBindingCount > 0 ? 'warn' : 'default'}
        onClick={() => onSlice({ sourceBinding: 'unbound' })} />
      <KpiCard label="Типов" value={stats.byType.length} icon={Layers} onClick={onShowDashboard} />
      <KpiCard label="Регионов" value={stats.regionCount} icon={Globe} onClick={onShowDashboard} />
    </div>
  )
}
