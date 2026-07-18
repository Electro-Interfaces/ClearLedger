/**
 * «Горизонт анализа» — единственный разрешённый способ выйти за период контура.
 *
 * Применим ТОЛЬКО к видам, где время само является предметом анализа: Динамика
 * (тренд), Нарезка, Сравнение периодов. Виды-срезы (Разрезы, Обзор, Время и
 * загрузка, Надёжность) своего периода не имеют — они всегда живут в контуре.
 *
 * Правила (см. CLAUDE.md → «Взаимодействие верхнего фильтра и параметров таба»):
 *  - расхождение с контуром всегда видно бейджем;
 *  - сбрасывается при смене периода наверху;
 *  - НЕ персистится между сессиями (держать в useState, не в useTabParams).
 */

import { PeriodRangePicker } from './analytics/PeriodRangePicker'
import { Button } from '@/components/ui/button'
import type { Period } from './analytics/periodPresets'

/** Насколько горизонт отличается от контура: шире / уже / совпадает. */
function describeDiff(h: Period, from: string, to: string): string | null {
  const wider = h.from < from || h.to > to
  const narrower = h.from > from || h.to < to
  if (wider && narrower) return 'смещён'
  if (wider) return 'шире фильтра'
  if (narrower) return 'уже фильтра'
  return null
}

export function HorizonControl({
  horizon,
  scopeFrom,
  scopeTo,
  onChange,
}: {
  horizon: Period | null
  scopeFrom: string
  scopeTo: string
  onChange: (p: Period | null) => void
}) {
  if (!horizon) {
    return (
      <label className="flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Горизонт</span>
        <Button
          variant="outline"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => onChange({ from: scopeFrom, to: scopeTo })}
        >
          Период фильтра
        </Button>
      </label>
    )
  }

  const diff = describeDiff(horizon, scopeFrom, scopeTo)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Горизонт</span>
      <PeriodRangePicker period={horizon} onChange={(p) => onChange(p)} />
      {diff ? (
        <span
          className="inline-flex items-center rounded-md border border-amber-400/50 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300/90"
          title={`Данные показаны за собственный горизонт вида, а не за период фильтра (${scopeFrom} — ${scopeTo})`}
        >
          {diff}
        </span>
      ) : null}
      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => onChange(null)}>
        ← период фильтра
      </Button>
    </div>
  )
}
