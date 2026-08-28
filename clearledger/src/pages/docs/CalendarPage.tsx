/**
 * Календарь: месяц и неделя, встречи и сроки вместе.
 *
 * Сетка своя, на CSS Grid и `date-fns`. Библиотеку календаря не берём: 150–300
 * КБ со своей темой, своим форматом события и своим представлением о том, как
 * выглядит день, — а нам нужна ячейка, в которой рядом стоят встреча и срок.
 * `react-day-picker` остаётся пикером даты в диалогах: он рендерит одну кнопку
 * на день и своей разметки под события не имеет.
 *
 * В месячной ячейке встречи стоят поштучно, а сроки — числом. Причина простая:
 * встреча занимает время, и её надо прочитать, чтобы понять, свободен ли день;
 * срок в масштабе месяца отвечает на «сколько», а не «что» — читают его в
 * «Сегодня» и в очереди.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addDays, addMonths, addWeeks, eachDayOfInterval, endOfMonth, endOfWeek, format,
  isSameDay, isSameMonth, isToday, startOfDay, startOfMonth, startOfWeek,
} from 'date-fns'
import { ru } from 'date-fns/locale'
import { CalendarDays, ChevronLeft, ChevronRight, Loader2, MapPin, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { CalendarEvent } from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import type { SpaceTask } from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { EventDialog } from '@/components/calendar/EventDialog'

type Mode = 'month' | 'week'

const ЧАС = 60 * 60 * 1000

export function CalendarPage() {
  const { company } = useCompany()
  const companyId = company?.id ?? ''
  const qc = useQueryClient()
  const [mode, setMode] = useState<Mode>('month')
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()))
  const [openEvent, setOpenEvent] = useState<CalendarEvent | null>(null)
  const [newAt, setNewAt] = useState<Date | null>(null)

  // Окно сетки, а не календарного месяца: месяц начинается с хвоста прошлого,
  // и встречи этих дней обязаны в него попасть.
  const { from, to, days } = useMemo(() => {
    const start = mode === 'month'
      ? startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 })
      : startOfWeek(anchor, { weekStartsOn: 1 })
    const end = mode === 'month'
      ? endOfWeek(endOfMonth(anchor), { weekStartsOn: 1 })
      : endOfWeek(anchor, { weekStartsOn: 1 })
    return { from: start, to: end, days: eachDayOfInterval({ start, end }) }
  }, [anchor, mode])

  const eventsQ = useQuery({
    queryKey: ['calendar', companyId, from.toISOString(), to.toISOString()],
    queryFn: () => workService.listEvents(companyId, from.toISOString(),
      addDays(to, 1).toISOString()),
    enabled: !!companyId,
  })
  // Сроки — из реестра поручений: свой источник сроков разошёлся бы с очередью
  // в первый же месяц.
  const tasksQ = useQuery({
    queryKey: ['calendar-tasks', companyId, from.toISOString(), to.toISOString()],
    queryFn: () => tasksService.listTasks(companyId, 'mine', {
      dueFrom: from.toISOString(), dueTo: addDays(to, 1).toISOString(), limit: 200,
    }),
    enabled: !!companyId,
  })

  if (!companyId) return null

  const events = (eventsQ.data?.events ?? []).filter((e) => e.status !== 'cancelled')
  const tasks = tasksQ.data?.tasks ?? []
  const шаг = (вперёд: boolean) => setAnchor((d) => (mode === 'month'
    ? addMonths(d, вперёд ? 1 : -1)
    : addWeeks(d, вперёд ? 1 : -1)))

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <CalendarDays className="h-4.5 w-4.5 text-primary" />Календарь
        </h1>
        <span className="ml-1 min-w-[11rem] text-sm capitalize text-muted-foreground">
          {mode === 'month'
            ? format(anchor, 'LLLL yyyy', { locale: ru })
            : `${format(from, 'd MMM', { locale: ru })} – ${format(to, 'd MMM yyyy', { locale: ru })}`}
        </span>
        <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => шаг(false)}
          aria-label="Назад"><ChevronLeft className="h-4 w-4" /></Button>
        <Button size="sm" variant="ghost" className="h-8 px-2.5 text-xs"
          onClick={() => setAnchor(startOfDay(new Date()))}>Сегодня</Button>
        <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => шаг(true)}
          aria-label="Вперёд"><ChevronRight className="h-4 w-4" /></Button>

        <div className="ml-auto flex items-center gap-1">
          {(['month', 'week'] as Mode[]).map((m) => (
            <Button key={m} size="sm" variant={mode === m ? 'secondary' : 'ghost'}
              className="h-8 px-2.5 text-xs" onClick={() => setMode(m)}>
              {m === 'month' ? 'Месяц' : 'Неделя'}
            </Button>
          ))}
          <Button size="sm" className="h-8 px-3 text-xs"
            onClick={() => setNewAt(new Date())}>Встреча</Button>
        </div>
      </header>

      {(eventsQ.isLoading || tasksQ.isLoading) && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />Собираю…
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <div className="grid grid-cols-7 border-b border-border bg-muted/40">
          {days.slice(0, 7).map((d) => (
            <div key={d.toISOString()}
              className="px-2 py-1.5 text-center text-[11px] font-medium uppercase text-muted-foreground">
              {format(d, 'EEEEEE', { locale: ru })}
            </div>
          ))}
        </div>
        <div className={cn('grid grid-cols-7',
          mode === 'week' && 'h-[calc(100%-2rem)]')}>
          {days.map((day) => (
            <DayCell key={day.toISOString()} day={day} mode={mode} anchor={anchor}
              events={events.filter((e) => пересекает(e, day))}
              tasks={tasks.filter((t) => t.due_at && isSameDay(new Date(t.due_at), day))}
              onEvent={setOpenEvent}
              onAdd={() => setNewAt(new Date(day.getTime() + 10 * ЧАС))} />
          ))}
        </div>
      </div>

      {(newAt || openEvent) && (
        <EventDialog companyId={companyId} event={openEvent} startAt={newAt}
          onClose={() => { setNewAt(null); setOpenEvent(null) }}
          // Календарь живёт в трёх местах: экран, док рельсы и пульт «Трека».
          // Обновлять только свой запрос значит оставить два других со вчерашней
          // картиной — встреча, собранная здесь, не появится ни там, ни там.
          onChanged={() => {
            void eventsQ.refetch()
            void qc.invalidateQueries({ queryKey: ['calendar'] })
            void qc.invalidateQueries({ queryKey: ['events'] })
          }} />
      )}
    </div>
  )
}

/** Встреча попадает в день, если задевает его: командировка идёт неделю. */
function пересекает(e: CalendarEvent, day: Date): boolean {
  const начало = new Date(e.starts_at)
  const конец = new Date(e.ends_at)
  const с = startOfDay(day)
  const по = addDays(с, 1)
  return начало < по && конец > с
}

function DayCell({ day, mode, anchor, events, tasks, onEvent, onAdd }: {
  day: Date; mode: Mode; anchor: Date
  events: CalendarEvent[]; tasks: SpaceTask[]
  onEvent: (e: CalendarEvent) => void
  onAdd: () => void
}) {
  const свой = mode === 'week' || isSameMonth(day, anchor)
  const просрочено = tasks.filter((t) => t.overdue).length
  const видимые = mode === 'month' ? events.slice(0, 2) : events

  return (
    <div className={cn('group min-h-[6.5rem] border-b border-r border-border p-1.5 last:border-r-0',
      mode === 'week' && 'min-h-full',
      !свой && 'bg-muted/30')}>
      <div className="flex items-center justify-between">
        <span className={cn('inline-flex h-5 min-w-5 items-center justify-center rounded px-1 text-xs tabular-nums',
          isToday(day) ? 'bg-primary font-medium text-primary-foreground'
            : свой ? 'text-foreground' : 'text-muted-foreground')}>
          {format(day, 'd')}
        </span>
        <button onClick={onAdd} aria-label="Собрать встречу"
          className="invisible text-xs text-muted-foreground hover:text-foreground group-hover:visible">
          +
        </button>
      </div>

      <div className="mt-1 space-y-0.5">
        {видимые.map((e) => (
          <button key={e.id} onClick={() => onEvent(e)}
            className={cn('flex w-full items-center gap-1 truncate rounded px-1 py-0.5 text-left text-[11px]',
              e.my_response === 'declined'
                ? 'text-muted-foreground line-through'
                : 'bg-primary/10 text-foreground hover:bg-primary/20')}>
            {!e.all_day && (
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {format(new Date(e.starts_at), 'HH:mm')}
              </span>
            )}
            <span className="truncate">{e.title}</span>
            {e.conference_url && <Video className="h-3 w-3 shrink-0 text-muted-foreground" />}
            {e.location && !e.conference_url && (
              <MapPin className="h-3 w-3 shrink-0 text-muted-foreground" />
            )}
          </button>
        ))}
        {mode === 'month' && events.length > 2 && (
          <span className="block px-1 text-[11px] text-muted-foreground">
            +{events.length - 2} ещё
          </span>
        )}
        {tasks.length > 0 && (
          <span className={cn('block px-1 text-[11px]',
            просрочено ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
            {просрочено ? `${просрочено} просрочено` : `${tasks.length} ${срок(tasks.length)}`}
          </span>
        )}
      </div>
    </div>
  )
}

/** «1 срок», «2 срока», «5 сроков» — иначе счётчик читается как ошибка. */
const срок = (n: number) => {
  const две = n % 100
  if (две > 4 && две < 21) return 'сроков'
  const одна = n % 10
  if (одна === 1) return 'срок'
  if (одна > 1 && одна < 5) return 'срока'
  return 'сроков'
}

export default CalendarPage
