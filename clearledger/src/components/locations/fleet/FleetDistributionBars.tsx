/**
 * Блок распределения парка — лёгкие CSS-бары (count + % + цвет + клик-drill-down).
 * Переиспользуется для всех 6 распределений дашборда.
 */
import { Card, CardContent } from '@/components/ui/card'
import type { CountItem } from './locationFleetService'

/** Нейтральная многоцветная палитра для категорий без семантики (типы/регионы/владельцы). */
export const BAR_COLORS = [
  '#3b82f6', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b',
  '#ef4444', '#ec4899', '#6366f1', '#14b8a6', '#a3a3a3',
]

export function FleetDistributionBars({
  title, items, total, colorFor, onItemClick,
}: {
  title: string
  items: CountItem[]
  total: number
  /** Цвет полосы по ключу/индексу (для семантичных распределений). */
  colorFor?: (key: string, index: number) => string
  onItemClick?: (item: CountItem) => void
}) {
  const max = Math.max(...items.map((i) => i.count), 1)

  return (
    <Card>
      <CardContent className="pt-5">
        <div className="mb-3 text-xs font-medium text-muted-foreground">{title}</div>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Нет данных.</p>
        ) : (
          <div className="space-y-2">
            {items.map((it, i) => {
              const pct = total > 0 ? Math.round((it.count / total) * 100) : 0
              const w = Math.max((it.count / max) * 100, 2)
              const color = colorFor?.(it.key, i) ?? BAR_COLORS[i % BAR_COLORS.length]
              return (
                <button
                  key={it.key}
                  onClick={onItemClick ? () => onItemClick(it) : undefined}
                  className={`block w-full text-left ${onItemClick ? 'group cursor-pointer' : 'cursor-default'}`}
                >
                  <div className="mb-0.5 flex items-center justify-between gap-2 text-xs">
                    <span className={`truncate ${onItemClick ? 'group-hover:text-foreground' : ''}`}>{it.label}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">{it.count} · {pct}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full transition-all" style={{ width: `${w}%`, backgroundColor: color }} />
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
