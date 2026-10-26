/**
 * Почасовая сетка дня и недели.
 *
 * Месяц отвечает на вопрос «что за месяц», неделя — «когда именно». Второй
 * вопрос ячейками дня не закрывается: две встречи в одной клетке не показывают,
 * что между ними час, а подбирать время глазами по списку нельзя.
 *
 * **Срок — точка во всёдневной полосе, никогда не полоса в сетке.** Решение
 * записано в плане и подтверждено чужими граблями: те, кто клал сроки в сетку,
 * лечились настройками — ClickUp завёл источник дат со стартом `None`, Asana
 * тумблер «скрыть длинные задачи». У срока нет длительности, и рисовать его
 * блоком значит выдумать её за человека.
 *
 * Всёдневное (командировка, отпуск) живёт в той же верхней полосе: в сетке оно
 * заняло бы сутки высотой и вытеснило всё остальное.
 */
import { useEffect, useRef, useState } from 'react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { NotebookPen, Repeat, Video } from 'lucide-react'
import type { CalendarEvent } from '@/services/workService'
import type { SpaceTask } from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { layoutDayEvents } from '@/lib/calendarLayout'
import { companyDayTime, companyMinutesNow, companyTime, isCompanyDay, isCompanyToday } from '@/lib/companyTime'

/** Высота часа. Меньше — подписи не читаются, больше — рабочий день не влезает
 *  на экран целиком, а именно его и смотрят. */
const ЧАС_PX = 44
const ЧАСЫ = Array.from({ length: 24 }, (_, i) => i)

export function TimeGrid({ days, events, tasks, foreign, repeats = [], onEvent, onAdd, onDay }: {
  days: Date[]
  events: CalendarEvent[]
  tasks: SpaceTask[]
  /** Встречи общего календаря компании, в которых человека нет: рамкой, не заливкой. */
  foreign?: Set<string>
  /** Повторяющиеся дела вперёд: расписание ещё не поставило их поручением. */
  repeats?: { id: string; title: string; at: Date }[]
  onEvent: (e: CalendarEvent) => void
  onAdd: (at: Date) => void
  onDay?: (day: Date) => void
}) {
  const прокрутка = useRef<HTMLDivElement>(null)

  // Открываемся на рабочем дне, а не на полуночи: иначе человек каждый раз
  // прокручивает треть сетки, прежде чем увидеть хоть что-то.
  useEffect(() => {
    if (прокрутка.current) прокрутка.current.scrollTop = 8 * ЧАС_PX
  }, [])
  // Линия «сейчас» едет сама: неделя открыта часами, и застывшая линия врёт.
  const [, setСейчас] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setСейчас(new Date()), 60_000)
    return () => clearInterval(timer)
  }, [])

  const вСетке = events.filter((e) => !e.all_day)
  const сверху = events.filter((e) => e.all_day)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border" style={{ minWidth: days.length > 1 ? 672 : 0 }}>
      {/* Шапка дней. В режиме одного дня её нет: дата уже стоит заголовком в шапке
          календаря, и строка «ПН 7» под «7 сентября 2026» повторяла то же самое
          (замечание МАГа 07.09.2026). */}
      {days.length > 1 && <div className="flex overflow-y-hidden border-b border-border bg-muted/40 [scrollbar-gutter:stable]">
        <div className="w-12 shrink-0" />
        {days.map((d) => (
          <div key={d.toISOString()}
            className="min-w-0 flex-1 px-0.5 py-1.5 text-center text-[12px] font-medium uppercase">
            <span className="text-muted-foreground">{format(d, 'EEEEEE', { locale: ru })}</span>
            <span className={cn('ml-1.5 tabular-nums',
              isCompanyToday(d) ? 'rounded bg-primary px-1 text-primary-foreground'
                : 'text-foreground')}>
              {format(d, 'd')}
            </span>
          </div>
        ))}
      </div>}

      {/* Всёдневная полоса: командировки и СРОКИ. Срок здесь точкой — у него нет
          длительности, и место ему не в сетке часов. */}
      <div className="flex overflow-y-hidden border-b border-border [scrollbar-gutter:stable]">
        <div className="w-12 shrink-0 py-1 pr-1 text-right text-[12px] text-muted-foreground">
          весь день
        </div>
        {days.map((d) => {
          const дневные = сверху.filter((e) => пересекаетДень(e, d))
          const сроки = tasks.filter((t) => t.due_at && isCompanyDay(t.due_at, d))
          const записи = сроки.filter((t) => t.visibility === 'personal')
          const рабочие = сроки.filter((t) => t.visibility !== 'personal')
          const повторы = repeats.filter((r) => isCompanyDay(r.at, d))
          return (
            <div key={d.toISOString()}
              className="min-h-[1.75rem] flex-1 space-y-0.5 border-l border-border p-0.5">
              {дневные.map((e) => (
                <button key={e.id} onClick={() => onEvent(e)}
                  className={cn('block w-full truncate rounded px-1 text-[12px]',
                    e.status === 'cancelled'
                      ? 'text-muted-foreground line-through'
                      : foreign?.has(e.id) ? 'border border-border bg-background text-foreground hover:bg-accent'
                        : 'bg-primary/15 text-foreground hover:bg-primary/25')}>
                  {e.title}
                </button>
              ))}
              {рабочие.length > 0 && (
                <button onClick={() => onDay?.(d)} className={cn('block px-1 text-[12px] hover:underline',
                  рабочие.some((t) => t.overdue)
                    ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                  {рабочие.length} срок{рабочие.length > 1 ? 'ов' : ''}
                </button>
              )}
              {повторы.map((r) => (
                <span key={r.id} title={`Повторяющееся дело: поставится в ${companyTime(r.at)}`}
                  className="flex items-center gap-1 px-1 text-[12px] text-muted-foreground">
                  <Repeat className="h-3 w-3 shrink-0" /><span className="truncate">{r.title}</span>
                </span>
              ))}
              {записи.length > 0 && (
                <span className="flex items-center gap-1 px-1 text-[12px] text-muted-foreground/70">
                  <NotebookPen className="h-3 w-3 shrink-0" />{записи.length}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {/* Сетка часов */}
      <div ref={прокрутка} className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div className="flex" style={{ height: 24 * ЧАС_PX }}>
          <div className="w-12 shrink-0">
            {ЧАСЫ.map((h) => (
              <div key={h} style={{ height: ЧАС_PX }}
                className="relative border-b border-border/40">
                <span className="absolute -top-1.5 right-1 text-[12px] tabular-nums text-muted-foreground">
                  {h === 0 ? '' : `${String(h).padStart(2, '0')}:00`}
                </span>
              </div>
            ))}
          </div>
          {days.map((d) => (
            <div key={d.toISOString()} className={cn('relative flex-1 border-l border-border',
              isCompanyToday(d) ? 'bg-primary/5' : d.getDay() % 6 === 0 && 'bg-muted/30')}>
              {isCompanyToday(d) && <div aria-hidden className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-destructive"
                style={{ top: companyMinutesNow() / 60 * ЧАС_PX }} />}
              {ЧАСЫ.map((h) => (
                <div key={h} style={{ height: ЧАС_PX }}
                  onClick={() => {
                    onAdd(companyDayTime(d, h))
                  }}
                  className="border-b border-border/40 hover:bg-accent/40" />
              ))}
              {layoutDayEvents(вСетке, d)
                .map(({ event: e, column: колонка, columns: всего, startMinute, endMinute, continues }) => {
                  const н = new Date(e.starts_at)
                  const верх = startMinute / 60 * ЧАС_PX
                  const высота = Math.max(18, (endMinute - startMinute) / 60 * ЧАС_PX)
                  return (
                    <button key={e.id} onClick={() => onEvent(e)}
                      aria-label={`${e.title}, ${format(d, 'd MMMM', { locale: ru })}${continues ? ', продолжение' : ''}`}
                      title={e.status === 'cancelled'
                        ? `Отменена${e.cancel_reason ? `: ${e.cancel_reason}` : ''}`
                        : e.title}
                      style={{
                        top: верх, height: высота,
                        left: `${(колонка / всего) * 100}%`,
                        width: `${(1 / всего) * 100}%`,
                      }}
                      className={cn('absolute overflow-hidden rounded border px-1 py-0.5 text-left text-[12px] leading-tight',
                        e.status === 'cancelled'
                          ? 'border-border bg-muted/60 text-muted-foreground line-through'
                          : e.my_response === 'declined'
                            ? 'border-border bg-muted/40 text-muted-foreground line-through'
                            : foreign?.has(e.id) ? 'border-border bg-background text-foreground hover:bg-accent'
                            : 'border-primary/40 bg-primary/15 text-foreground hover:bg-primary/25')}>
                      <span className="tabular-nums text-muted-foreground">
                        {continues ? 'Продолжение' : companyTime(н)}
                      </span>{' '}
                      {e.title}
                      {e.conference_url && e.status !== 'cancelled' && (
                        <Video className="ml-1 inline h-3 w-3" />
                      )}
                    </button>
                  )
                })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** Встреча задевает день: командировка идёт неделю. */
function пересекаетДень(e: CalendarEvent, day: Date): boolean {
  const с = companyDayTime(day, 0)
  const nextDay = new Date(day); nextDay.setDate(nextDay.getDate() + 1)
  const по = companyDayTime(nextDay, 0)
  return new Date(e.starts_at) < по && new Date(e.ends_at) > с
}

export default TimeGrid
