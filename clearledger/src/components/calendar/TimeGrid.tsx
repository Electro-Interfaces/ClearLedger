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
import { eventDaySegment, layoutDayEvents } from '@/lib/calendarLayout'
import { companyDayTime, companyMinutesNow, companyTime, isCompanyDay, isCompanyToday } from '@/lib/companyTime'

/** Высота часа. Меньше — подписи не читаются, больше — рабочий день не влезает
 *  на экран целиком, а именно его и смотрят. */
const ЧАС_PX = 44
const ЧАСЫ = Array.from({ length: 24 }, (_, i) => i)
/** Уже этого блок перестаёт быть встречей и становится полоской: в него не
 *  помещается даже «10:00» и первая буква названия. Неделя на телефоне делит
 *  колонку в 89 px, и три одновременные встречи давали по 29 px. */
const МИН_БЛОК_PX = 44

export function TimeGrid({ days, events, tasks, foreign, repeats = [], draft, onEvent, onAdd, onDay }: {
  days: Date[]
  events: CalendarEvent[]
  tasks: SpaceTask[]
  /** Встречи общего календаря компании, в которых человека нет: рамкой, не заливкой. */
  foreign?: Set<string>
  /** Повторяющиеся дела вперёд: расписание ещё не поставило их поручением. */
  repeats?: { id: string; title: string; at: Date }[]
  /** Встреча, которую сейчас собирают в панели: видно, куда она встанет. */
  draft?: { start: Date; end: Date; title: string } | null
  onEvent: (e: CalendarEvent) => void
  onAdd: (at: Date) => void
  onDay?: (day: Date) => void
}) {
  const прокрутка = useRef<HTMLDivElement>(null)

  // Открываемся на рабочем дне, а не на полуночи: иначе человек каждый раз
  // прокручивает треть сетки, прежде чем увидеть хоть что-то. Десять пикселей
  // выше границы часа — чтобы подпись «08:00» (она поднята над линией) была
  // видна целиком, а не срезана верхней полосой.
  useEffect(() => {
    if (прокрутка.current) прокрутка.current.scrollTop = 8 * ЧАС_PX - 10
  }, [])

  // Ширина колонки дня: по ней решаем, сколько встреч одного часа можно
  // показать рядом. Меряем саму колонку, а не контейнер прокрутки: неделя шире
  // экрана и прокручивается внутри себя, и ширина контейнера о колонке не говорит.
  const колонкаДня = useRef<HTMLDivElement>(null)
  const [ширинаДня, setШиринаДня] = useState(0)
  useEffect(() => {
    const el = колонкаДня.current
    if (!el) return
    const update = () => setШиринаДня(el.getBoundingClientRect().width)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [days.length])
  // Линия «сейчас» едет сама: неделя открыта часами, и застывшая линия врёт.
  const [сейчас, setСейчас] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setСейчас(new Date()), 60_000)
    return () => clearInterval(timer)
  }, [])

  const вСетке = events.filter((e) => !e.all_day)
  const сверху = events.filter((e) => e.all_day)
  // Пересчёт раз в минуту держит `сейчас`; минуты берутся по часам компании.
  const минутаСейчас = companyMinutesNow()
  const естьСегодня = days.some((d) => isCompanyToday(d))

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card" style={{ minWidth: days.length > 1 ? 672 : 0 }}>
      {/* Шапка дней: день недели и крупное число, как в настольных календарях —
          число ищут глазами первым. Сегодня — залитый круг. В режиме одного дня
          шапки нет: дата уже стоит в строке периода (замечание МАГа 07.09.2026). */}
      {days.length > 1 && <div className="flex overflow-y-hidden border-b border-border [scrollbar-gutter:stable]">
        <div className="w-14 shrink-0" />
        {days.map((d) => (
          <button key={d.toISOString()} type="button" onClick={() => onDay?.(d)}
            aria-label={`Открыть ${format(d, 'd MMMM', { locale: ru })}`}
            className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-left hover:bg-accent/50">
            <span className={cn('text-xs font-medium',
              isCompanyToday(d) ? 'text-primary' : d.getDay() % 6 === 0 ? 'text-muted-foreground/80' : 'text-muted-foreground')}>
              {format(d, 'EEEEEE', { locale: ru })}
            </span>
            <span className={cn('grid size-8 place-items-center rounded-full text-lg font-semibold tabular-nums',
              isCompanyToday(d) ? 'bg-primary text-primary-foreground' : 'text-foreground')}>
              {format(d, 'd')}
            </span>
          </button>
        ))}
      </div>}

      {/* Всёдневная полоса: командировки и СРОКИ. Срок здесь точкой — у него нет
          длительности, и место ему не в сетке часов. */}
      <div className="flex overflow-y-hidden border-b border-border [scrollbar-gutter:stable]">
        <div className="w-14 shrink-0 py-1 pr-2 text-right text-xs leading-tight text-muted-foreground">
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
          <div className="relative w-14 shrink-0">
            {ЧАСЫ.map((h) => (
              <div key={h} style={{ height: ЧАС_PX }}
                className="relative">
                <span className="absolute -top-2 right-2 text-xs tabular-nums text-muted-foreground">
                  {h === 0 ? '' : `${String(h).padStart(2, '0')}:00`}
                </span>
              </div>
            ))}
            {/* Метка «сейчас» — в колонке часов, на уровне линии: время читается
                там же, где все остальные часы, а не догадкой по положению. */}
            {естьСегодня && (
              <span className="absolute right-1 z-20 -translate-y-1/2 rounded-full bg-primary px-1.5 py-0.5 text-xs font-medium tabular-nums text-primary-foreground"
                style={{ top: минутаСейчас / 60 * ЧАС_PX }}>
                {companyTime(сейчас)}
              </span>
            )}
          </div>
          {days.map((d, индекс) => {
            const { видимые, свёрнутые } = раскладкаДня(вСетке, d, ширинаДня)
            const черновик = draft && eventDaySegment({ id: 'draft', starts_at: draft.start.toISOString(), ends_at: draft.end.toISOString() }, d)
            return (
            <div key={d.toISOString()} ref={индекс === 0 ? колонкаДня : undefined}
              className={cn('relative flex-1 border-l border-border',
              d.getDay() % 6 === 0 && 'bg-muted/30')}>
              {isCompanyToday(d) && <div aria-hidden className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-primary"
                style={{ top: минутаСейчас / 60 * ЧАС_PX }} />}
              {черновик && (
                <div aria-hidden className="pointer-events-none absolute inset-x-1 z-10 overflow-hidden rounded-md border border-dashed border-primary bg-primary/10 px-1.5 py-0.5 text-xs leading-tight text-foreground"
                  style={{ top: черновик.startMinute / 60 * ЧАС_PX, height: Math.max(18, (черновик.endMinute - черновик.startMinute) / 60 * ЧАС_PX) }}>
                  <span className="tabular-nums text-muted-foreground">{companyTime(черновик.start)}–{черновик.endMinute === 1440 ? '24:00' : companyTime(черновик.end)}</span>{' '}
                  {draft!.title.trim() || 'Новая встреча'}
                </div>
              )}
              {ЧАСЫ.map((h) => (
                <div key={h} style={{ height: ЧАС_PX }}
                  onClick={() => {
                    onAdd(companyDayTime(d, h))
                  }}
                  className="border-b border-border/40 hover:bg-accent/40" />
              ))}
              {свёрнутые.map((группа) => (
                /* Больше встреч, чем влезает в колонку этого дня: остальные —
                   одной меткой «+N». Иначе они делят ширину до полосок в одну
                   букву и из недели уже не понять, что это за встречи. */
                <button key={`more-${группа.group}`} onClick={() => onDay?.(d)}
                  aria-label={`Ещё ${группа.скрыто} ${встреч(группа.скрыто)} ${format(d, 'd MMMM', { locale: ru })}`}
                  title="Показать день списком"
                  style={{
                    top: группа.startMinute / 60 * ЧАС_PX,
                    height: Math.max(18, (группа.endMinute - группа.startMinute) / 60 * ЧАС_PX),
                    left: `${((группа.предел - 1) / группа.предел) * 100}%`,
                    width: `${(1 / группа.предел) * 100}%`,
                  }}
                  className="absolute overflow-hidden rounded border border-dashed border-border bg-muted/60
                             px-1 py-0.5 text-left text-[12px] leading-tight text-muted-foreground hover:bg-accent">
                  +{группа.скрыто}
                </button>
              ))}
              {видимые
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
            )
          })}
        </div>
      </div>
    </div>
  )
}

/**
 * Что показать в колонке дня, когда встреч на один час больше, чем помещается.
 *
 * Раскладка делит ширину между пересекающимися встречами. На широком экране это
 * и нужно, но колонка дня в неделе на телефоне — 89 px, и три одновременные
 * встречи превращаются в полоски по 29 px: в них не помещается ни время, ни
 * первая буква названия. Поэтому у цепочки пересечений есть предел колонок по
 * фактической ширине: сколько влезает — показываем, остальные сворачиваем в
 * «+N» на месте последней колонки. Ноль ширины (первый кадр до измерения) —
 * предела нет, рисуем как раньше.
 */
function раскладкаДня(события: CalendarEvent[], день: Date, ширина: number) {
  const блоки = layoutDayEvents(события, день)
  const предел = ширина > 0 ? Math.max(1, Math.floor(ширина / МИН_БЛОК_PX)) : Number.POSITIVE_INFINITY
  const видимые: typeof блоки = []
  const скрытыеПоГруппам = new Map<number, typeof блоки>()
  for (const блок of блоки) {
    if (блок.columns <= предел || блок.column < предел - 1) {
      видимые.push(блок)
      continue
    }
    const группа = скрытыеПоГруппам.get(блок.group) ?? []
    группа.push(блок)
    скрытыеПоГруппам.set(блок.group, группа)
  }
  const свёрнутые = [...скрытыеПоГруппам.entries()].map(([group, блоки]) => ({
    group,
    скрыто: блоки.length,
    предел: предел === Number.POSITIVE_INFINITY ? 1 : предел,
    startMinute: Math.min(...блоки.map((b) => b.startMinute)),
    endMinute: Math.max(...блоки.map((b) => b.endMinute)),
  }))
  // Видимые делят ширину по пределу, а не по числу встреч в цепочке: иначе
  // место свёрнутых осталось бы пустым.
  return {
    видимые: видимые.map((b) => (b.columns > предел ? { ...b, columns: предел } : b)),
    свёрнутые,
  }
}

/** «1 встреча», «2 встречи», «5 встреч» — иначе метка читается как ошибка. */
function встреч(n: number) {
  const две = n % 100
  if (две > 4 && две < 21) return 'встреч'
  const одна = n % 10
  if (одна === 1) return 'встреча'
  if (одна > 1 && одна < 5) return 'встречи'
  return 'встреч'
}

/** Встреча задевает день: командировка идёт неделю. */
function пересекаетДень(e: CalendarEvent, day: Date): boolean {
  const с = companyDayTime(day, 0)
  const nextDay = new Date(day); nextDay.setDate(nextDay.getDate() + 1)
  const по = companyDayTime(nextDay, 0)
  return new Date(e.starts_at) < по && new Date(e.ends_at) > с
}

export default TimeGrid
