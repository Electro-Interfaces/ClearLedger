/**
 * Компактный пресетный пикер периода для аналитических панелей.
 * Состояние хранит ID компании + текущий период в localStorage,
 * чтобы переключение между management/financial/tax сохраняло выбор.
 */

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Calendar } from 'lucide-react'

export interface Period {
  from: string
  to: string
}

const STORAGE_KEY = 'clearledger_analytics_period'

function todayISO() {
  return new Date().toISOString().slice(0, 10)
}

function monthAgoISO() {
  const d = new Date()
  d.setDate(d.getDate() - 30)
  return d.toISOString().slice(0, 10)
}

function currentMonthFirst() {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)
}

function currentMonthLast() {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10)
}

function prevMonthBounds() {
  const d = new Date()
  const first = new Date(d.getFullYear(), d.getMonth() - 1, 1)
  const last = new Date(d.getFullYear(), d.getMonth(), 0)
  return { from: first.toISOString().slice(0, 10), to: last.toISOString().slice(0, 10) }
}

export function loadPeriod(): Period {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return { from: currentMonthFirst(), to: todayISO() }
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
  const presets = [
    { label: '30 дн', value: () => ({ from: monthAgoISO(), to: todayISO() }) },
    { label: 'Тек. месяц', value: () => ({ from: currentMonthFirst(), to: todayISO() }) },
    { label: 'Прошл. месяц', value: prevMonthBounds },
    { label: 'YTD', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: todayISO() }) },
  ]
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

export function KpiCard({ label, value, hint, accent }: {
  label: string
  value: React.ReactNode
  hint?: string
  accent?: 'success' | 'danger' | 'warning' | 'info'
}) {
  const accentCls: Record<string, string> = {
    success: 'text-emerald-400',
    danger:  'text-red-400',
    warning: 'text-amber-400',
    info:    'text-blue-400',
  }
  return (
    <div className="rounded-md border bg-card/40 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold mt-1 ${accent ? accentCls[accent] : ''}`}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  )
}
