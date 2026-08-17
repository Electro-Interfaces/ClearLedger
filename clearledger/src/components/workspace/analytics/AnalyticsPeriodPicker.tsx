/**
 * Компактный пресетный пикер периода для аналитических панелей.
 * Период приходит из единого контура рабочей области.
 */

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Calendar } from 'lucide-react'
import { type Period, PERIOD_PRESETS } from './periodPresets'
import { MetricHint } from './MetricHint'
import { TrendSpark } from '@/components/ui/trend-spark'

export type { Period } from './periodPresets'

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

export function KpiCard({ label, value, hint, accent, info, spark, sparkLabel }: {
  label: string
  value: React.ReactNode
  hint?: string
  accent?: 'success' | 'danger' | 'warning' | 'info'
  info?: string   // пояснение «что это значит» — иконкой-подсказкой у подписи
  /** Ряд за период под цифрой: само число не говорит, растёт метрика или падает.
   *  Даём только там, где ряд уже загружен экраном — плитка не ходит в сеть сама. */
  spark?: (number | null)[]
  sparkLabel?: string   // чем подписан ряд в подсказке
}) {
  const accentCls: Record<string, string> = {
    success: 'text-emerald-600 dark:text-emerald-400',
    danger:  'text-red-600 dark:text-red-400',
    warning: 'text-amber-600 dark:text-amber-400',
    info:    'text-blue-600 dark:text-blue-400',
  }
  // Две точки — это не тренд, а отрезок: рисовать нечего.
  const showSpark = spark && spark.length >= 3
  return (
    // Контракт выгрузки: первые три ребёнка — label/value/hint, спарклайн идёт после.
    <div data-kpi className="rounded-md border bg-card/40 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
        {label}{info && <MetricHint text={info} />}
      </div>
      <div className={`text-lg font-semibold mt-1 ${accent ? accentCls[accent] : ''}`}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-0.5">{hint}</div>}
      {showSpark && (
        // Линия без заливки — как спарклайны на «Обзорах»: у одинаковых по смыслу
        // элементов на соседних экранах должен быть один вид.
        <TrendSpark values={spark} full className="mt-2 h-8"
          tone={accent === 'danger' ? 'danger' : accent === 'warning' ? 'warning' : 'brand'}
          ariaLabel={sparkLabel ?? `Динамика: ${label}`} />
      )}
    </div>
  )
}
