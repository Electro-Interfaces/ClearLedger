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
import { useEffect, useRef } from 'react'
import { format, isSameDay, isToday } from 'date-fns'
import { ru } from 'date-fns/locale'
import { NotebookPen, Video } from 'lucide-react'
import type { CalendarEvent } from '@/services/workService'
import type { SpaceTask } from '@/services/tasksService'
import { cn } from '@/lib/utils'

/** Высота часа. Меньше — подписи не читаются, больше — рабочий день не влезает
 *  на экран целиком, а именно его и смотрят. */
const ЧАС_PX = 44
const ЧАСЫ = Array.from({ length: 24 }, (_, i) => i)

export function TimeGrid({ days, events, tasks, onEvent, onAdd }: {
  days: Date[]
  events: CalendarEvent[]
  tasks: SpaceTask[]
  onEvent: (e: CalendarEvent) => void
  onAdd: (at: Date) => void
}) {
  const прокрутка = useRef<HTMLDivElement>(null)

  // Открываемся на рабочем дне, а не на полуночи: иначе человек каждый раз
  // прокручивает треть сетки, прежде чем увидеть хоть что-то.
  useEffect(() => {
    if (прокрутка.current) прокрутка.current.scrollTop = 8 * ЧАС_PX
  }, [])

  const вСетке = events.filter((e) => !e.all_day)
  const сверху = events.filter((e) => e.all_day)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border">
      {/* Шапка дней */}
      <div className="flex border-b border-border bg-muted/40">
        <div className="w-12 shrink-0" />
        {days.map((d) => (
          <div key={d.toISOString()}
            className="flex-1 px-2 py-1.5 text-center text-[11px] font-medium uppercase">
            <span className="text-muted-foreground">{format(d, 'EEEEEE', { locale: ru })}</span>
            <span className={cn('ml-1.5 tabular-nums',
              isToday(d) ? 'rounded bg-primary px-1 text-primary-foreground'
                : 'text-foreground')}>
              {format(d, 'd')}
            </span>
          </div>
        ))}
      </div>

      {/* Всёдневная полоса: командировки и СРОКИ. Срок здесь точкой — у него нет
          длительности, и место ему не в сетке часов. */}
      <div className="flex border-b border-border">
        <div className="w-12 shrink-0 py-1 pr-1 text-right text-[10px] text-muted-foreground">
          весь день
        </div>
        {days.map((d) => {
          const дневные = сверху.filter((e) => пересекаетДень(e, d))
          const сроки = tasks.filter((t) => t.due_at && isSameDay(new Date(t.due_at), d))
          const записи = сроки.filter((t) => t.visibility === 'personal')
          const рабочие = сроки.filter((t) => t.visibility !== 'personal')
          return (
            <div key={d.toISOString()}
              className="min-h-[1.75rem] flex-1 space-y-0.5 border-l border-border p-0.5">
              {дневные.map((e) => (
                <button key={e.id} onClick={() => onEvent(e)}
                  className={cn('block w-full truncate rounded px-1 text-[11px]',
                    e.status === 'cancelled'
                      ? 'text-muted-foreground line-through'
                      : 'bg-primary/15 text-foreground hover:bg-primary/25')}>
                  {e.title}
                </button>
              ))}
              {рабочие.length > 0 && (
                <span className={cn('block px-1 text-[11px]',
                  рабочие.some((t) => t.overdue)
                    ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                  {рабочие.length} срок{рабочие.length > 1 ? 'ов' : ''}
                </span>
              )}
              {записи.length > 0 && (
                <span className="flex items-center gap-1 px-1 text-[11px] text-muted-foreground/70">
                  <NotebookPen className="h-3 w-3 shrink-0" />{записи.length}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {/* Сетка часов */}
      <div ref={прокрутка} className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex" style={{ height: 24 * ЧАС_PX }}>
          <div className="w-12 shrink-0">
            {ЧАСЫ.map((h) => (
              <div key={h} style={{ height: ЧАС_PX }}
                className="relative border-b border-border/40">
                <span className="absolute -top-1.5 right-1 text-[10px] tabular-nums text-muted-foreground">
                  {h === 0 ? '' : `${String(h).padStart(2, '0')}:00`}
                </span>
              </div>
            ))}
          </div>
          {days.map((d) => (
            <div key={d.toISOString()} className="relative flex-1 border-l border-border">
              {ЧАСЫ.map((h) => (
                <div key={h} style={{ height: ЧАС_PX }}
                  onClick={() => {
                    const at = new Date(d)
                    at.setHours(h, 0, 0, 0)
                    onAdd(at)
                  }}
                  className="border-b border-border/40 hover:bg-accent/40" />
              ))}
              {раскладка(вСетке.filter((e) => isSameDay(new Date(e.starts_at), d)))
                .map(({ event: e, колонка, всего }) => {
                  const н = new Date(e.starts_at)
                  const к = new Date(e.ends_at)
                  const верх = (н.getHours() * 60 + н.getMinutes()) / 60 * ЧАС_PX
                  const высота = Math.max(
                    18, (к.getTime() - н.getTime()) / 3_600_000 * ЧАС_PX)
                  return (
                    <button key={e.id} onClick={() => onEvent(e)}
                      title={e.status === 'cancelled'
                        ? `Отменена${e.cancel_reason ? `: ${e.cancel_reason}` : ''}`
                        : e.title}
                      style={{
                        top: верх, height: высота,
                        left: `${(колонка / всего) * 100}%`,
                        width: `${(1 / всего) * 100}%`,
                      }}
                      className={cn('absolute overflow-hidden rounded border px-1 py-0.5 text-left text-[11px] leading-tight',
                        e.status === 'cancelled'
                          ? 'border-border bg-muted/60 text-muted-foreground line-through'
                          : e.my_response === 'declined'
                            ? 'border-border bg-muted/40 text-muted-foreground line-through'
                            : 'border-primary/40 bg-primary/15 text-foreground hover:bg-primary/25')}>
                      <span className="tabular-nums text-muted-foreground">
                        {format(н, 'HH:mm')}
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
  const с = new Date(day); с.setHours(0, 0, 0, 0)
  const по = new Date(с); по.setDate(по.getDate() + 1)
  return new Date(e.starts_at) < по && new Date(e.ends_at) > с
}

/**
 * Пересекающиеся встречи делят ширину.
 *
 * Без этого две встречи на 10:00 ложатся одна на другую, и верхняя прячет
 * нижнюю целиком — то есть сетка молча теряет встречу. Раскладка простая: идём
 * по времени начала и кладём каждую в первую колонку, где она никого не задевает.
 */
function раскладка(events: CalendarEvent[]) {
  const по_времени = events.slice().sort(
    (a, b) => a.starts_at.localeCompare(b.starts_at))
  const колонки: CalendarEvent[][] = []
  const место = new Map<string, number>()

  for (const e of по_времени) {
    const н = new Date(e.starts_at).getTime()
    let индекс = колонки.findIndex(
      (кол) => кол.every((x) => new Date(x.ends_at).getTime() <= н))
    if (индекс === -1) { колонки.push([]); индекс = колонки.length - 1 }
    колонки[индекс].push(e)
    место.set(e.id, индекс)
  }
  const всего = Math.max(1, колонки.length)
  return по_времени.map((event) => ({
    event, колонка: место.get(event.id) ?? 0, всего,
  }))
}

export default TimeGrid
