/**
 * Тулбар Сервисного центра: переключатель режимов (Обзор/Заявки/SLA) + период +
 * кнопка синхронизации HubEx (для админа). Pill-стиль — как WorkspaceToolbar.
 */
import { LayoutDashboard, ClipboardList, Gauge, RefreshCw, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

export type NetMode = 'overview' | 'requests' | 'sla'
export type PeriodPreset = '30' | '90' | '365' | 'all'

const MODES: { key: NetMode; icon: React.ComponentType<{ className?: string }>; label: string }[] = [
  { key: 'overview', icon: LayoutDashboard, label: 'Обзор сети' },
  { key: 'requests', icon: ClipboardList, label: 'Заявки' },
  { key: 'sla', icon: Gauge, label: 'SLA' },
]

const PERIODS: { key: PeriodPreset; label: string }[] = [
  { key: '30', label: '30 дней' },
  { key: '90', label: '90 дней' },
  { key: '365', label: 'Год' },
  { key: 'all', label: 'Всё время' },
]

export function NetServiceToolbar({
  mode, onModeChange, period, onPeriodChange,
  canSync, syncing, onSync,
}: {
  mode: NetMode
  onModeChange: (m: NetMode) => void
  period: PeriodPreset
  onPeriodChange: (p: PeriodPreset) => void
  canSync: boolean
  syncing: boolean
  onSync: () => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5 flex-wrap">
      <div className="inline-flex rounded-md bg-muted/40 p-0.5">
        {MODES.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            onClick={() => onModeChange(key)}
            className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              mode === key ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <Select value={period} onValueChange={(v) => onPeriodChange(v as PeriodPreset)}>
          <SelectTrigger className="h-8 w-[130px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {PERIODS.map((x) => <SelectItem key={x.key} value={x.key}>{x.label}</SelectItem>)}
          </SelectContent>
        </Select>
        {canSync && (
          <Button variant="outline" size="sm" onClick={onSync} disabled={syncing}>
            {syncing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            Синхронизировать
          </Button>
        )}
      </div>
    </div>
  )
}

/** Преобразовать пресет периода в ISO-диапазон (для query). */
export function periodRange(preset: PeriodPreset): { dateFrom: string; dateTo: string } {
  const to = new Date()
  const from = new Date()
  if (preset === '30') from.setDate(to.getDate() - 30)
  else if (preset === '90') from.setDate(to.getDate() - 90)
  else if (preset === '365') from.setDate(to.getDate() - 365)
  else from.setFullYear(2020, 0, 1)
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  return { dateFrom: iso(from), dateTo: iso(to) }
}
