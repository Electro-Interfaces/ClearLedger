/**
 * Компактный пресетный пикер периода для аналитических панелей.
 * Состояние хранит ID компании + текущий период в localStorage,
 * чтобы переключение между management/financial/tax сохраняло выбор.
 */

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Calendar } from 'lucide-react'
import { type Period, PERIOD_PRESETS, monthFirstISO, todayISO } from './periodPresets'
import { MetricHint } from './MetricHint'

export type { Period } from './periodPresets'

const STORAGE_KEY = 'clearledger_analytics_period'

export function loadPeriod(): Period {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return { from: monthFirstISO(), to: todayISO() }
}

function savePeriod(p: Period) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)) } catch { /* ignore */ }
}

export function useAnalyticsPeriod() {
  const [period, setPeriodState] = useState<Period>(loadPeriod)
  useEffect(() => { savePeriod(period) }, [period])
  return [period, setPeriodState] as const
}

interface Props {
  period: Period
  onChange: (p: Period) => void
}

export function AnalyticsPeriodPicker({ period, onChange }: Props) {
  const presets = PERIOD_PRESETS
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/20">
      <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
      <Input
        type="date"
        value={period.from}
        onChange={(e) => onChange({ ...period, from: e.target.value })}
        className="h-7 w-[130px] text-xs"
      />
      <span className="text-xs text-muted-foreground">—</span>
      <Input
        type="date"
        value={period.to}
        onChange={(e) => onChange({ ...period, to: e.target.value })}
        className="h-7 w-[130px] text-xs"
      />
      <div className="flex items-center gap-1 ml-2">
        {presets.map((p) => (
          <Button
            key={p.label}
            variant="ghost"
            size="sm"
            className="h-7 text-xs px-2"
            onClick={() => onChange(p.value())}
          >
            {p.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

export function KpiCard({ label, value, hint, accent, info }: {
  label: string
  value: React.ReactNode
  hint?: string
  accent?: 'success' | 'danger' | 'warning' | 'info'
  info?: string   // пояснение «что это значит» — иконкой-подсказкой у подписи
}) {
  const accentCls: Record<string, string> = {
    success: 'text-emerald-600 dark:text-emerald-400',
    danger:  'text-red-600 dark:text-red-400',
    warning: 'text-amber-600 dark:text-amber-400',
    info:    'text-blue-600 dark:text-blue-400',
  }
  return (
    <div data-kpi className="rounded-md border bg-card/40 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
        {label}{info && <MetricHint text={info} />}
      </div>
      <div className={`text-lg font-semibold mt-1 ${accent ? accentCls[accent] : ''}`}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  )
}
