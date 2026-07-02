/**
 * Переиспользуемые пикеры периода:
 *  - PeriodRangePicker — один диапазон (два date-инпута + быстрые пресеты).
 *  - MultiPeriodPicker — 2–4 диапазона со «+ период»/удалением + генераторы
 *    N периодов (месяцы/кварталы/год-к-году) от опорного периода.
 */

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { X, Plus } from 'lucide-react'
import {
  type Period, PERIOD_PRESETS, buildMoM, buildQoQ, buildYoY, prevMonthBounds,
} from './periodPresets'

export function PeriodRangePicker({ period, onChange, onRemove, showPresets = true, label }: {
  period: Period
  onChange: (p: Period) => void
  onRemove?: () => void
  showPresets?: boolean
  label?: string
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {label && <span className="text-xs text-muted-foreground w-[70px] shrink-0">{label}</span>}
      <Input
        type="date" value={period.from}
        onChange={(e) => onChange({ ...period, from: e.target.value })}
        className="h-7 w-[130px] text-xs"
      />
      <span className="text-xs text-muted-foreground">—</span>
      <Input
        type="date" value={period.to}
        onChange={(e) => onChange({ ...period, to: e.target.value })}
        className="h-7 w-[130px] text-xs"
      />
      {showPresets && (
        <div className="flex items-center gap-1">
          {PERIOD_PRESETS.map((p) => (
            <Button key={p.label} variant="ghost" size="sm" className="h-7 text-xs px-2"
              onClick={() => onChange(p.value())}>
              {p.label}
            </Button>
          ))}
        </div>
      )}
      {onRemove && (
        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground" onClick={onRemove}>
          <X className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  )
}

const MAX_PERIODS = 4

export function MultiPeriodPicker({ periods, onChange, anchor }: {
  periods: Period[]
  onChange: (p: Period[]) => void
  anchor: Period
}) {
  const setAt = (i: number, p: Period) => onChange(periods.map((x, j) => (j === i ? p : x)))
  const removeAt = (i: number) => onChange(periods.filter((_, j) => j !== i))
  const add = () => { if (periods.length < MAX_PERIODS) onChange([...periods, prevMonthBounds()]) }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-xs text-muted-foreground mr-1">Быстро:</span>
        <Button variant="outline" size="sm" className="h-7 text-xs px-2" onClick={() => onChange(buildMoM(anchor, 3))}>3 месяца</Button>
        <Button variant="outline" size="sm" className="h-7 text-xs px-2" onClick={() => onChange(buildQoQ(anchor, 3))}>3 квартала</Button>
        <Button variant="outline" size="sm" className="h-7 text-xs px-2" onClick={() => onChange(buildYoY(anchor, 2))}>Год к году</Button>
      </div>
      <div className="space-y-1.5">
        {periods.map((p, i) => (
          <PeriodRangePicker
            key={i} period={p} label={`Период ${i + 1}`} showPresets={false}
            onChange={(np) => setAt(i, np)}
            onRemove={periods.length > 2 ? () => removeAt(i) : undefined}
          />
        ))}
      </div>
      {periods.length < MAX_PERIODS && (
        <Button variant="ghost" size="sm" className="h-7 text-xs px-2" onClick={add}>
          <Plus className="h-3.5 w-3.5 mr-1" />Добавить период
        </Button>
      )}
    </div>
  )
}
