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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  addDays, addMonths, addWeeks, eachDayOfInterval, endOfMonth, endOfWeek, format,
  isSameDay, isSameMonth, isToday, startOfDay, startOfMonth, startOfWeek,
} from 'date-fns'
import { ru } from 'date-fns/locale'
import {
  CalendarCheck, CalendarDays, ChevronLeft, ChevronRight, Eye, EyeOff, Loader2,
  MapPin, NotebookPen, Rss, Video,
} from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { CalendarEvent } from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import type { SpaceTask } from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { EventDialog } from '@/components/calendar/EventDialog'
import { TimeGrid } from '@/components/calendar/TimeGrid'

type Mode = 'month' | 'week' | 'day'

const ЧАС = 60 * 60 * 1000

export function CalendarPage() {
  const { company } = useCompany()
  const companyId = company?.id ?? ''
  const qc = useQueryClient()
  const [mode, setMode] = useState<Mode>('month')
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()))
  const [scope, setScope] = useState<'mine' | 'company'>('mine')
  // Показывать ли сроки в сетке недели. Выбор человека, и он переживает
  // перезагрузку: переключать его каждое открытие никто не станет. Чтение в
  // try — приватное окно и запрет на данные сайта роняют доступ к хранилищу.
  const [showDue, setShowDue] = useState(() => {
    try { return localStorage.getItem('calendar-hide-due') !== '1' } catch { return true }
  })
  const переключитьСроки = () => setShowDue((v) => {
    try { localStorage.setItem('calendar-hide-due', v ? '1' : '0') } catch { /* пусто */ }
    return !v
  })
  const [openEvent, setOpenEvent] = useState<CalendarEvent | null>(null)
  const [newAt, setNewAt] = useState<Date | null>(null)

  // Окно сетки, а не календарного месяца: месяц начинается с хвоста прошлого,
  // и встречи этих дней обязаны в него попасть.
  const { from, to, days } = useMemo(() => {
    if (mode === 'day') {
      const d = startOfDay(anchor)
      return { from: d, to: d, days: [d] }
    }
    const start = mode === 'month'
      ? startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 })
      : startOfWeek(anchor, { weekStartsOn: 1 })
    const end = mode === 'month'
      ? endOfWeek(endOfMonth(anchor), { weekStartsOn: 1 })
      : endOfWeek(anchor, { weekStartsOn: 1 })
    return { from: start, to: end, days: eachDayOfInterval({ start, end }) }
  }, [anchor, mode])

  const eventsQ = useQuery({
    queryKey: ['calendar', companyId, scope, from.toISOString(), to.toISOString()],
    queryFn: () => workService.listEvents(companyId, from.toISOString(),
      addDays(to, 1).toISOString(), { scope }),
    enabled: !!companyId,
  })
  // Сроки — из реестра поручений: свой источник сроков разошёлся бы с очередью
  // в первый же месяц. Разрез `my_due`, а не `mine`: в календаре стоят все МОИ
  // сроки, включая свою датированную запись, — планировать день по половине
  // картины нельзя. Порученное компанией и своё различаются знаком в ячейке.
  const tasksQ = useQuery({
    queryKey: ['calendar-tasks', companyId, from.toISOString(), to.toISOString()],
    queryFn: () => tasksService.listTasks(companyId, 'my_due', {
      dueFrom: from.toISOString(), dueTo: addDays(to, 1).toISOString(), limit: 200,
    }),
    // Сроки стоят только в СВОЁМ календаре. В общем их быть не должно: срок —
    // обязательство конкретного человека, и вывешивать чужие в витрину компании
    // значит превратить календарь в табло исполнительской дисциплины.
    enabled: !!companyId && scope === 'mine',
  })
  // Личный план: на какие дни человек сам наметил себе работу. Отдельный
  // запрос, а не подмешивание к срокам, — потому что это разные обещания:
  // срок ждёт компания, план не ждёт никто, кроме самого человека.
  const planQ = useQuery({
    queryKey: ['calendar-plan', companyId, from.toISOString(), to.toISOString()],
    queryFn: () => workService.planDays(companyId, workService.todayKey(from),
      workService.todayKey(to)),
    enabled: !!companyId && scope === 'mine',
  })

  if (!companyId) return null

  // Отменённая встреча не исчезает, пока её день не прошёл: человек, увидевший
  // её вчера, должен узнать, что она отменена, и почему. Молча пропавшая встреча
  // означает, что кто-то придёт в пустую переговорную. Прошедшие отменённые
  // скрываем — они уже никого не подведут, а сетку засоряют.
  const начало = startOfDay(new Date()).getTime()
  const events = (eventsQ.data?.events ?? []).filter(
    (e) => e.status !== 'cancelled' || new Date(e.ends_at).getTime() >= начало)
  const tasks = scope === 'mine' ? (tasksQ.data?.tasks ?? []) : []
  const план = scope === 'mine' ? (planQ.data ?? {}) : {}
  const шаг = (вперёд: boolean) => setAnchor((d) => (
    mode === 'month' ? addMonths(d, вперёд ? 1 : -1)
      : mode === 'day' ? addDays(d, вперёд ? 1 : -1)
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
          {/* Общий календарь показывает только встречи с кругом «вся компания».
              Закрытые не появляются в нём даже строкой «занято»: для планирования
              есть занятость интервалами, а витрина, в которой видно чужое
              закрытое, означала бы, что круг видимости зависит от экрана. */}
          {([['mine', 'Мой'], ['company', 'Компании']] as const).map(([код, имя]) => (
            <Button key={код} size="sm" variant={scope === код ? 'secondary' : 'ghost'}
              className="h-8 px-2.5 text-xs" onClick={() => setScope(код)}>
              {имя}
            </Button>
          ))}
          <span className="mx-1 h-4 w-px bg-border" />
          {(['month', 'week', 'day'] as Mode[]).map((m) => (
            <Button key={m} size="sm" variant={mode === m ? 'secondary' : 'ghost'}
              className="h-8 px-2.5 text-xs" onClick={() => setMode(m)}>
              {m === 'month' ? 'Месяц' : m === 'week' ? 'Неделя' : 'День'}
            </Button>
          ))}
          {/* Сроки убираются только там, где они мешают: в сетке недели и дня
              полоса с двумя десятками точек съедает верх, и человек, который
              пришёл расставить встречи, смотрит сквозь неё. В месяце срок
              стоит числом в ячейке и никому не мешает — там выключать нечего. */}
          {mode !== 'month' && scope === 'mine' && (
            <Button size="sm" variant="ghost" className="h-8 px-2.5 text-xs"
              aria-pressed={showDue} onClick={переключитьСроки}
              title={showDue
                ? 'Скрыть сроки — останутся только встречи'
                : 'Показать сроки во всёдневной полосе'}>
              {showDue ? <Eye className="mr-1 h-3.5 w-3.5" />
                : <EyeOff className="mr-1 h-3.5 w-3.5" />}
              Сроки
            </Button>
          )}
          <FeedLink />
          <Button size="sm" className="h-8 px-3 text-xs"
            onClick={() => setNewAt(new Date())}>Встреча</Button>
        </div>
      </header>

      {(eventsQ.isLoading || tasksQ.isLoading) && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />Собираю…
        </p>
      )}

      {/* Неделя и день — почасовой сеткой: вопрос «когда именно» ячейками дня не
          закрывается. Месяц остаётся ячейками — там спрашивают «что за месяц». */}
      {mode !== 'month' ? (
        <TimeGrid days={days} events={events} tasks={showDue ? tasks : []}
          onEvent={setOpenEvent} onAdd={(at) => setNewAt(at)} />
      ) : (
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <div className="grid grid-cols-7 border-b border-border bg-muted/40">
          {days.slice(0, 7).map((d) => (
            <div key={d.toISOString()}
              className="px-2 py-1.5 text-center text-[12px] font-medium uppercase text-muted-foreground">
              {format(d, 'EEEEEE', { locale: ru })}
            </div>
          ))}
        </div>
        {/* Ветка только месячная: неделя и день ушли в почасовую сетку выше. */}
        <div className="grid grid-cols-7">
          {days.map((day) => (
            <DayCell key={day.toISOString()} day={day} mode={mode} anchor={anchor}
              events={events.filter((e) => пересекает(e, day))}
              tasks={tasks.filter((t) => t.due_at && isSameDay(new Date(t.due_at), day))}
              намечено={план[workService.todayKey(day)] ?? 0}
              onEvent={setOpenEvent}
              onAdd={() => setNewAt(new Date(day.getTime() + 10 * ЧАС))} />
          ))}
        </div>
      </div>

      )}

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

function DayCell({ day, mode, anchor, events, tasks, намечено, onEvent, onAdd }: {
  day: Date; mode: Mode; anchor: Date
  events: CalendarEvent[]; tasks: SpaceTask[]
  /** Сколько работы человек сам наметил на этот день. Не срок: срок ждёт
   *  компания, план — только он сам. */
  намечено: number
  onEvent: (e: CalendarEvent) => void
  onAdd: () => void
}) {
  const свой = mode === 'week' || isSameMonth(day, anchor)
  // Своё обязательство и порученное компанией считаются порознь. Одним числом
  // они читаются как одно и то же, а это разные вещи: срок поручения ставила
  // компания и спросит с человека она, срок записи он поставил себе сам.
  const записи = tasks.filter((t) => t.visibility === 'personal')
  const рабочие = tasks.filter((t) => t.visibility !== 'personal')
  const просрочено = рабочие.filter((t) => t.overdue).length
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
            title={e.status === 'cancelled'
              ? `Отменена${e.cancel_reason ? `: ${e.cancel_reason}` : ''}`
              : undefined}
            className={cn('flex w-full items-center gap-1 truncate rounded px-1 py-0.5 text-left text-[12px]',
              e.status === 'cancelled'
                ? 'text-muted-foreground line-through decoration-red-500/60'
                : e.my_response === 'declined'
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
          <span className="block px-1 text-[12px] text-muted-foreground">
            +{events.length - 2} ещё
          </span>
        )}
        {рабочие.length > 0 && (
          <span className={cn('block px-1 text-[12px]',
            просрочено ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
            {просрочено ? `${просрочено} просрочено` : `${рабочие.length} ${срок(рабочие.length)}`}
          </span>
        )}
        {/* Тихий знак: своё видно, но не спорит за внимание с обязательствами
            перед компанией. Красным не красим даже просроченное — просрочить
            обещание себе и обещание компании не одно и то же. */}
        {записи.length > 0 && (
          <span className="flex items-center gap-1 px-1 text-[12px] text-muted-foreground/70"
            title={`Своих записей со сроком: ${записи.length}`}>
            <NotebookPen className="h-3 w-3 shrink-0" />
            {записи.length}
          </span>
        )}
        {/* План на день: сколько работы человек сам наметил на это число.
            Своим знаком и своим словом — «намечено», а не «срок»: срок ждёт
            компания, план не ждёт никто. Потому и не краснеет никогда. */}
        {намечено > 0 && (
          <span className="flex items-center gap-1 px-1 text-[12px] text-sky-700/80 dark:text-sky-300/80"
            title={`Вы наметили себе работы: ${намечено}. Срок компании это не меняет`}>
            <CalendarCheck className="h-3 w-3 shrink-0" />
            намечено {намечено}
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * Лента подписки: свой календарь «Трека» там, где человек живёт остальным
 * временем, — в телефоне, в Outlook, в Google.
 *
 * Односторонняя намеренно. Двусторонняя синхронизация это петли, дубли,
 * состояние на каждый календарь и хранение заголовков чужих встреч; лента даёт
 * девять десятых пользы за сотую долю сложности.
 *
 * Оговорка про задержку стоит рядом со ссылкой, а не в справке: человек,
 * поправивший встречу и не увидевший правки в телефоне через минуту, решит,
 * что сломалось, — и будет прав, если мы промолчали.
 */
function FeedLink() {
  const qc = useQueryClient()
  const [открыт, setОткрыт] = useState(false)
  const q = useQuery({
    queryKey: ['calendar-feed'],
    queryFn: () => workService.calendarFeed(),
    enabled: открыт,
    staleTime: Infinity,
  })
  const сменить = useMutation({
    mutationFn: () => workService.rotateCalendarFeed(),
    onSuccess: (r) => {
      qc.setQueryData(['calendar-feed'], r)
      toast.success('Ключ сменён — прежняя ссылка больше не работает')
    },
  })

  return (
    <Popover open={открыт} onOpenChange={setОткрыт}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost" className="h-8 px-2.5 text-xs"
          title="Показывать этот календарь в телефоне или Outlook">
          <Rss className="mr-1 h-3.5 w-3.5" />Подписка
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 space-y-2">
        <p className="text-xs font-medium">Ваш календарь во внешнем клиенте</p>
        <p className="text-xs text-muted-foreground">
          Вставьте адрес в Google Календарь, Apple Календарь или Outlook как
          подписку по ссылке. Встречи будут видны только для чтения.
        </p>
        {q.isLoading && <p className="text-xs text-muted-foreground">Собираю адрес…</p>}
        {q.data && (
          <>
            <input readOnly value={q.data.url} onFocus={(e) => e.target.select()}
              className="w-full rounded border border-input bg-muted/40 px-2 py-1 font-mono text-[11px]" />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                onClick={() => {
                  void navigator.clipboard?.writeText(q.data.url)
                  toast.success('Адрес скопирован')
                }}>Скопировать</Button>
              <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                disabled={сменить.isPending}
                title="Прежняя ссылка перестанет работать"
                onClick={() => сменить.mutate()}>Сменить ключ</Button>
            </div>
            {q.data.note && (
              <p className="text-[11px] text-muted-foreground">{q.data.note}</p>
            )}
            <p className="text-[11px] text-muted-foreground">
              Адрес открывает ваши встречи без пароля — не публикуйте его.
            </p>
          </>
        )}
      </PopoverContent>
    </Popover>
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
