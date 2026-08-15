/**
 * «Периметр» → «Когда выдавали» — календарная карта наличных выдач.
 *
 * Таблица отвечает «сколько», карта — «когда». Один и тот же итог за месяц выглядит
 * по-разному, если он собран из тридцати мелких выдач или из двух крупных, и режим
 * виден только сеткой: пятничные расчёты, всплеск перед закрытием месяца, тишина в
 * отпуск. Пустые дни в сетке обязаны присутствовать — пропуск иначе читается как
 * отсутствие данных, а не как день без выдач.
 *
 * Средняя считается по дням С ВЫДАЧАМИ: делить на календарные дни значит утверждать,
 * что деньги выдают каждый день.
 */
import { useQuery } from '@tanstack/react-query'

import { useFilters } from '@/contexts/FilterContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import { getCashCalendar } from '@/services/perimeterService'
import { Loading } from './OfficePanels'
import { money, num } from './officeShared'

/** Насыщенность клетки: пять ступеней — больше глаз всё равно не различает. */
const level = (amount: number, max: number) => {
  if (!amount) return 0
  const share = amount / (max || 1)
  if (share > 0.66) return 4
  if (share > 0.33) return 3
  if (share > 0.15) return 2
  return 1
}

const TONE = [
  'bg-muted/40',
  'bg-primary/15',
  'bg-primary/30',
  'bg-primary/50',
  'bg-primary/70',
]

const human = (iso: string) => `${iso.slice(8)}.${iso.slice(5, 7)}`

export function CashCalendarScreen({ companyId }: { companyId: string }) {
  const { period } = useFilters()
  const q = useQuery({
    queryKey: ['perimeter', 'cash-calendar', companyId, period.from, period.to],
    queryFn: () => getCashCalendar(companyId, period.from, period.to),
    enabled: !!companyId,
  })

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось собрать карту выдач" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data
  const maxWeekday = Math.max(...d.byWeekday.map((w) => w.amount), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Выдано за период" value={`${money.format(d.total)} ₽`}
          hint={`${d.from} — ${d.to}`} />
        <MetricTile label="Дней с выдачами" value={num.format(d.activeDays)}
          hint="в остальные дни наличные не выдавали" />
        <MetricTile label="Средний день с выдачей"
          value={`${money.format(d.avgActiveDay)} ₽`}
          hint="считается по дням с выдачами, а не по календарным" />
        <MetricTile label="Самый крупный день" value={`${money.format(d.maxDay)} ₽`}
          hint="к нему привязана насыщенность карты" />
      </div>

      {!d.activeDays ? (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            За период {d.from} — {d.to} выдач наличными не было. Карта показывает только
            выдачи: отчёты документами, зачёты, списания и пересчёты кошелька в неё не
            входят — деньги при них не движутся.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div>
              <div className="text-base font-medium">Когда выдавали</div>
              <div className="text-[11px] text-muted-foreground">
                Клетка — день; чем плотнее заливка, тем крупнее выдача. Наведите, чтобы
                увидеть сумму.
              </div>
            </div>

            <div className="overflow-x-auto">
              <div className="inline-flex gap-1">
                {/* Подписи дней недели слева: без них сетка читается как узор */}
                <div className="flex flex-col gap-1 pr-1">
                  {['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'].map((l) => (
                    <div key={l} className="h-5 w-6 text-[10px] text-muted-foreground
                        leading-5 text-right">{l}</div>
                  ))}
                </div>
                {d.weeks.map((w) => (
                  <div key={w.weekStart} className="flex flex-col gap-1">
                    {w.days.map((day) => (
                      <div key={day.date}
                        title={day.inRange
                          ? `${human(day.date)}: ${day.count
                            ? `${money.format(day.amount)} ₽, ${num.format(day.count)} шт.`
                            : 'выдач не было'}`
                          : `${human(day.date)}: вне периода`}
                        className={cn('h-5 w-5 rounded-sm',
                          day.inRange ? TONE[level(day.amount, d.maxDay)] : 'bg-transparent',
                          day.inRange && !day.amount && 'ring-1 ring-inset ring-border')} />
                    ))}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>меньше</span>
              {TONE.map((t) => <span key={t} className={cn('h-3 w-3 rounded-sm', t)} />)}
              <span>больше</span>
            </div>
          </CardContent>
        </Card>
      )}

      {!!d.activeDays && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div>
              <div className="text-base font-medium">По дням недели</div>
              <div className="text-[11px] text-muted-foreground">
                Пятничные расчёты и конец месяца — самый частый режим наличных выдач
              </div>
            </div>
            <div className="space-y-1.5">
              {d.byWeekday.map((w) => (
                <div key={w.weekday} className="flex items-center gap-2">
                  <span className="w-8 text-[11px] text-muted-foreground shrink-0">
                    {w.label}
                  </span>
                  <div className="flex-1 h-4 bg-muted rounded overflow-hidden">
                    <div className="h-full bg-primary/50"
                      style={{ width: `${Math.round((w.amount / maxWeekday) * 100)}%` }} />
                  </div>
                  <span className="w-32 text-right text-sm tabular-nums shrink-0">
                    {w.amount ? `${money.format(w.amount)} ₽` : '—'}
                    {!!w.count && (
                      <span className="text-[11px] text-muted-foreground">
                        {' '}· {num.format(w.count)}
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {!!d.days.length && (
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="text-base font-medium">Крупные дни</div>
            <ul className="text-[11px] text-muted-foreground space-y-0.5">
              {[...d.days].sort((a, b) => b.amount - a.amount).slice(0, 8).map((day) => (
                <li key={day.date} className="flex justify-between gap-3">
                  <span className="truncate">
                    <span className="tabular-nums">{human(day.date)}</span>
                    {day.people.length ? ` · ${day.people.join(', ')}` : ''}
                  </span>
                  <span className="tabular-nums shrink-0">
                    {money.format(day.amount)} ₽ · {num.format(day.count)} шт.
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
