/**
 * Маршрут «Товародвижения» — где что смотреть и куда идти дальше.
 *
 * Пять пунктов раздела это не пять независимых экранов, а один порядок работы:
 * принял топливо → сверил книгу с замером → разобрал причины → оформил ведомость.
 * По отдельности каждый экран понятен, вместе — нет: менеджер не знал, что причины
 * расхождений живут в «Расхождениях», а ведомость уже умеет проводиться.
 *
 * Полоса показывает шаги подряд, отмечает текущий и ведёт на следующий. Цифры на
 * шагах — не украшение: они говорят, есть ли там работа, и без них маршрут был бы
 * просто картинкой.
 */
import { useSearchParams } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export type GoodsStep = 'purchases' | 'intake' | 'tanks' | 'variances' | 'inventory'

const STEPS: { key: GoodsStep; label: string; what: string }[] = [
  { key: 'purchases', label: 'Поступления', what: 'что и когда пришло по накладным' },
  { key: 'intake', label: 'Приёмка и сливы', what: 'сошёлся ли слив с ТТН по массе' },
  { key: 'tanks', label: 'Контроль баланса', what: 'книга против замера, смена за сменой' },
  { key: 'variances', label: 'Расхождения', what: 'почему не сходится: причина по резервуару' },
  { key: 'inventory', label: 'Инвентаризация', what: 'оформить корректировку документом' },
]

export function GoodsRouteBar({ current, counters }: {
  current: GoodsStep
  /** Работа на шаге: сколько там ждёт разбора. Пусто — счётчик не показываем. */
  counters?: Partial<Record<GoodsStep, { value: number; unit: string; alarm?: boolean } | null>>
}) {
  const [, setParams] = useSearchParams()
  const go = (key: GoodsStep) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    next.set('sub', key)
    return next
  })

  return (
    <nav aria-label="Порядок работы с товародвижением"
      className="flex flex-wrap items-stretch gap-1 rounded-lg border border-border/70 bg-card/60 p-1">
      {STEPS.map((s, i) => {
        const active = s.key === current
        const c = counters?.[s.key]
        return (
          <div key={s.key} className="flex items-stretch">
            {i > 0 && (
              <ChevronRight className="mx-0.5 my-auto h-3.5 w-3.5 shrink-0 text-muted-foreground/50" aria-hidden />
            )}
            <button
              type="button"
              aria-current={active ? 'step' : undefined}
              onClick={() => !active && go(s.key)}
              title={s.what}
              className={cn(
                'rounded-md px-2.5 py-1.5 text-left transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                active
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
              )}
            >
              <span className="flex items-center gap-1.5 text-xs font-medium">
                {s.label}
                {c && c.value > 0 && (
                  <span className={cn('rounded px-1 py-0.5 text-[10px] tabular-nums',
                    c.alarm ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'bg-muted text-muted-foreground')}>
                    {nf0.format(c.value)} {c.unit}
                  </span>
                )}
              </span>
              <span className={cn('mt-0.5 block text-[10px]',
                active ? 'text-primary/70' : 'text-muted-foreground/70')}>{s.what}</span>
            </button>
          </div>
        )
      })}
    </nav>
  )
}
