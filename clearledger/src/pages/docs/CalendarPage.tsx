import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import {
  addDays, addMonths, addWeeks, eachDayOfInterval, endOfMonth, endOfWeek, format,
  isSameDay, isSameMonth, isToday, isValid, parseISO, startOfDay, startOfMonth, startOfWeek,
} from 'date-fns'
import { ru } from 'date-fns/locale'
import { CalendarDays, ChevronLeft, ChevronRight, Loader2, Plus, RefreshCw, Rss, Search, Video } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { CalendarEvent } from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { eventDaySegment } from '@/lib/calendarLayout'
import { EventDialog } from '@/components/calendar/EventDialog'
import { TimeGrid } from '@/components/calendar/TimeGrid'

const MODES = { agenda: 'Список', month: 'Месяц', week: 'Неделя', day: 'День' }
type Mode = keyof typeof MODES

export function CalendarPage() {
  const { company } = useCompany()
  const companyId = company?.id ?? ''
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [defaultMode] = useState<Mode>(() => window.matchMedia('(max-width: 767px)').matches ? 'agenda' : 'month')
  const requestedMode = params.get('calendarMode')
  const mode = requestedMode && Object.hasOwn(MODES, requestedMode) ? requestedMode as Mode : defaultMode
  const requestedDate = params.get('date') ?? ''
  const anchor = /^\d{4}-\d{2}-\d{2}$/.test(requestedDate) && isValid(parseISO(requestedDate))
    ? startOfDay(parseISO(requestedDate)) : startOfDay(new Date())
  const scope = params.get('calendarScope') === 'company' ? 'company' : 'mine'
  const eventId = params.get('event')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [newAt, setNewAt] = useState<Date | null>(null)
  const [showDue, setShowDue] = useState(() => {
    try { return localStorage.getItem('calendar-hide-due') !== '1' } catch { return true }
  })
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250)
    return () => clearTimeout(timer)
  }, [search])

  const update = (values: Record<string, string | null>) => setParams(current => {
    const next = new URLSearchParams(current)
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    return next
  }, { flushSync: true })
  const dateKey = format(anchor, 'yyyy-MM-dd')
  const { from, to, days } = useMemo(() => {
    const at = parseISO(dateKey)
    const from = mode === 'month' ? startOfWeek(startOfMonth(at), { weekStartsOn: 1 })
      : mode === 'week' ? startOfWeek(at, { weekStartsOn: 1 }) : at
    const to = mode === 'month' ? addDays(startOfDay(endOfWeek(endOfMonth(at), { weekStartsOn: 1 })), 1)
      : addDays(from, mode === 'day' ? 1 : 7)
    return { from, to, days: eachDayOfInterval({ start: from, end: addDays(to, -1) }) }
  }, [dateKey, mode])

  const eventsQ = useQuery({
    queryKey: ['calendar', companyId, scope, from.toISOString(), to.toISOString(), query],
    queryFn: () => workService.listEvents(companyId, from.toISOString(), to.toISOString(), { scope, q: query || undefined }),
    enabled: !!companyId, staleTime: 30_000, refetchOnWindowFocus: true,
  })
  const tasksQ = useQuery({
    queryKey: ['calendar-tasks', companyId, from.toISOString(), to.toISOString()],
    queryFn: () => tasksService.listTasks(companyId, 'my_due', { dueFrom: from.toISOString(), dueTo: to.toISOString(), limit: 200 }),
    enabled: !!companyId && scope === 'mine', refetchOnWindowFocus: true,
  })
  const planQ = useQuery({
    queryKey: ['calendar-plan', companyId, from.toISOString(), to.toISOString()],
    queryFn: () => workService.planDays(companyId, workService.todayKey(from), workService.todayKey(addDays(to, -1))),
    enabled: !!companyId && scope === 'mine', refetchOnWindowFocus: true,
  })
  const eventQ = useQuery({
    queryKey: ['calendar-event', companyId, eventId],
    queryFn: () => workService.getEvent(companyId, eventId!),
    enabled: !!companyId && !!eventId, retry: false,
  })
  const changed = () => {
    for (const key of ['calendar', 'events', 'calendar-event', 'calendar-summary', 'calendar-busy', 'calendar-tasks', 'work-mine']) {
      void qc.invalidateQueries({ queryKey: [key, companyId] })
    }
  }
  const open = (event: CalendarEvent) => {
    qc.setQueryData(['calendar-event', companyId, event.id], event)
    update({ event: event.id })
  }
  const openDay = (day: Date, nextMode: Mode = 'day') => update({ date: format(day, 'yyyy-MM-dd'), calendarMode: nextMode })
  const createAt = (day: Date) => {
    const at = new Date(day)
    at.setHours(10, 0, 0, 0)
    if (isToday(at) && at < new Date()) {
      at.setTime(Math.ceil(Date.now() / 1_800_000) * 1_800_000)
    }
    setNewAt(at)
  }
  const move = (step: number) => {
    const at = mode === 'month' ? addMonths(anchor, step) : mode === 'day' ? addDays(anchor, step) : addWeeks(anchor, step)
    update({ date: format(at, 'yyyy-MM-dd') })
  }
  if (!companyId) return null

  const events = (eventsQ.data?.events ?? []).filter(e => e.status !== 'cancelled' || new Date(e.ends_at) >= startOfDay(new Date()))
  const tasks = scope === 'mine' ? (tasksQ.data?.tasks ?? []).filter(t => !query || t.title.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru'))) : []
  const plan = scope === 'mine' && !query ? (planQ.data ?? {}) : {}
  const busy = eventsQ.isFetching || (scope === 'mine' && (tasksQ.isFetching || planQ.isFetching))
  const errors = [
    { q: eventsQ, label: 'встречи' },
    ...(scope === 'mine' ? [{ q: tasksQ, label: 'сроки поручений' }, { q: planQ, label: 'личный план' }] : []),
  ].filter(row => row.q.isError)
  const caption = mode === 'month' ? format(anchor, 'LLLL yyyy', { locale: ru })
    : mode === 'day' ? format(anchor, 'd MMMM yyyy', { locale: ru })
      : `${format(from, 'd MMM', { locale: ru })} — ${format(addDays(to, -1), 'd MMM yyyy', { locale: ru })}`

  return <div className="flex min-h-full min-w-0 flex-col gap-3 p-3 md:h-full md:min-h-0 md:p-4">
    <header className="space-y-2">
      <div className="flex items-center gap-2">
        <h1 className="flex flex-1 items-center gap-2 text-lg font-semibold"><CalendarDays className="h-5 w-5 text-primary" />Календарь</h1>
        <Button variant="ghost" size="icon" aria-label="Обновить календарь" disabled={busy} onClick={changed}>
          <RefreshCw className={cn('h-4 w-4', busy && 'animate-spin')} />
        </Button>
        <FeedLink />
        <Button aria-label="Встреча" title="Назначить встречу на выбранную дату" className="w-10 shrink-0 px-0 md:w-auto md:px-4" onClick={() => createAt(anchor)}><Plus className="h-4 w-4 md:mr-1" /><span className="hidden md:inline">Встреча</span></Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button size="icon" variant="outline" className="w-9 md:w-10" aria-label="Предыдущий период" onClick={() => move(-1)}><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="outline" className="px-2 md:px-4" onClick={() => update({ date: format(new Date(), 'yyyy-MM-dd') })}>Сегодня</Button>
          <Button size="icon" variant="outline" className="w-9 md:w-10" aria-label="Следующий период" onClick={() => move(1)}><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <Input type="date" aria-label="Перейти к дате" className="w-32 text-base md:w-40 md:text-sm" value={dateKey}
          onChange={e => { if (e.target.value) update({ date: e.target.value }) }} />
        <div className="hidden items-center gap-1 md:ml-auto md:flex">
          {(Object.entries(MODES) as [Mode, string][]).map(([key, label]) => <Button key={key} variant={mode === key ? 'secondary' : 'ghost'} aria-pressed={mode === key} onClick={() => update({ calendarMode: key })}>{label}</Button>)}
        </div>

      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {([['mine', 'Мой'], ['company', 'Компании']] as const).map(([key, label]) => <Button key={key} variant={scope === key ? 'secondary' : 'ghost'} aria-pressed={scope === key} onClick={() => update({ calendarScope: key })}>{label}</Button>)}
        </div>
        <select aria-label="Вид календаря" value={mode} onChange={e => update({ calendarMode: e.target.value })}
          className="ml-auto h-10 w-28 min-w-0 rounded-md border border-input bg-background px-3 text-base md:hidden">
          {Object.entries(MODES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <div className="relative min-w-0 basis-full md:min-w-40 md:flex-1 md:basis-auto">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
          <Input aria-label="Найти в календаре" placeholder="Поиск в выбранном периоде" maxLength={200} value={search} onChange={e => setSearch(e.target.value)} className="pl-9 text-base md:text-sm" />
        </div>
        {scope === 'mine' && (mode === 'week' || mode === 'day') && <label className="flex min-h-10 items-center gap-2 text-sm">
          <input type="checkbox" checked={showDue} onChange={e => { const value = e.target.checked; setShowDue(value); try { localStorage.setItem('calendar-hide-due', value ? '0' : '1') } catch { /* пусто */ } }} />Сроки
        </label>}
      </div>
      <p className="text-sm capitalize text-muted-foreground" aria-live="polite">{caption}</p>
    </header>

    {errors.map(({ q, label }) => <div key={label} role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 px-3 py-2 text-sm">
      <span className="flex-1">Не удалось {q.data ? 'обновить' : 'загрузить'} {label}.{q.data ? ' Показаны ранее полученные данные.' : ''}</span>
      <Button variant="outline" size="sm" onClick={() => void q.refetch()}>Повторить</Button>
    </div>)}
    {(eventsQ.isLoading || (scope === 'mine' && tasksQ.isLoading)) && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Загружаются встречи и сроки…</p>}
    {(eventsQ.data?.truncated || (scope === 'mine' && (tasksQ.data?.total ?? 0) > (tasksQ.data?.tasks.length ?? 0))) && <p role="status" className="text-sm text-muted-foreground">В периоде слишком много записей. Выберите неделю или день, чтобы увидеть все.</p>}
    {eventId && eventQ.isPending && <p role="status" className="text-sm">Открывается встреча…</p>}
    {eventId && eventQ.isError && <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 p-3 text-sm">
      <span className="flex-1">Не удалось открыть встречу. Возможно, её нет или у вас нет доступа.</span>
      <Button variant="outline" size="sm" onClick={() => void eventQ.refetch()}>Повторить</Button>
      <Button variant="ghost" size="sm" onClick={() => update({ event: null })}>Закрыть</Button>
    </div>}

    {mode === 'agenda' ? <div className="flex-1 md:min-h-0 md:overflow-y-auto" aria-label="Расписание">
      {days.map(day => {
        const meetings = events.filter(e => eventDaySegment(e, day))
        const due = tasks.filter(t => t.due_at && isSameDay(new Date(t.due_at), day))
        const planned = plan[format(day, 'yyyy-MM-dd')] ?? 0
        if (!meetings.length && !due.length && !planned) return null
        return <section key={day.toISOString()} className="mb-5" aria-label={format(day, 'd MMMM', { locale: ru })}>
          <div className="mb-1 flex items-center gap-2 border-b border-border pb-1">
            <button className={cn('min-h-10 flex-1 text-left text-sm font-semibold capitalize hover:underline', isToday(day) && 'text-primary')} onClick={() => openDay(day)}>{format(day, 'EEEE, d MMMM', { locale: ru })}</button>
            <Button variant="ghost" size="icon" aria-label={`Добавить встречу ${format(day, 'd MMMM', { locale: ru })}`} onClick={() => createAt(day)}><Plus className="h-4 w-4" /></Button>
          </div>
          {meetings.map(event => <button key={event.id} onClick={() => open(event)} className="flex min-h-14 w-full items-start gap-3 border-b border-border/60 px-1 py-3 text-left hover:bg-accent">
            <span className="w-16 shrink-0 text-sm tabular-nums text-muted-foreground">{event.all_day ? 'Весь день' : <>{format(eventDaySegment(event, day)!.start, 'HH:mm')}<span className="block">{eventDaySegment(event, day)!.endMinute === 1440 ? '24:00' : format(eventDaySegment(event, day)!.end, 'HH:mm')}</span></>}</span>
            <span className="min-w-0 flex-1">
              <span className={cn('block break-words text-sm font-medium', (event.status === 'cancelled' || event.my_response === 'declined') && 'text-muted-foreground line-through')}>{event.title}</span>
              <span className="mt-1 block break-words text-sm text-muted-foreground">{event.status === 'cancelled' ? `Отменена${event.cancel_reason ? ': ' + event.cancel_reason : ''}` : event.my_response === 'pending' ? 'Ждёт вашего ответа' : event.my_response === 'declined' ? 'Вы отказались' : event.location || (event.conference_url ? 'Видеовстреча' : eventDaySegment(event, day)?.continues ? 'Продолжение встречи' : '')}</span>
            </span>
            {event.conference_url && <Video className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />}
          </button>)}
          {due.map(task => <Link key={task.id} to={workService.refHref('task:' + task.id)!} className="flex min-h-12 items-center gap-3 border-b border-border/60 px-1 py-2 text-sm hover:bg-accent">
            <span className={cn('w-16 shrink-0', task.overdue ? 'text-destructive' : 'text-muted-foreground')}>{task.visibility === 'personal' ? 'Мне' : 'Срок'}</span>
            <span className="min-w-0 break-words">{task.title}</span>
          </Link>)}
          {planned > 0 && <p className="flex min-h-10 items-center text-sm text-muted-foreground">Намечено на день: {planned}</p>}
        </section>
      })}
      {!eventsQ.isLoading && !tasksQ.isLoading && !errors.length && !events.length && !tasks.length && !Object.values(plan).some(Boolean) && <div className="py-8 text-center">
        <p className="font-medium">{query ? 'В этом периоде ничего не найдено' : 'В ближайшие семь дней записей нет'}</p>
        <p className="mt-2 text-sm text-muted-foreground">{query ? 'Измените запрос или выберите другой период.' : 'Назначьте встречу или выберите другую дату.'}</p>
        <Button className="mt-4" variant="outline" onClick={() => query ? setSearch('') : createAt(anchor)}>{query ? 'Сбросить поиск' : 'Назначить встречу'}</Button>
      </div>}
    </div> : mode !== 'month' ? <div className="flex min-h-96 flex-1 overflow-x-auto md:min-h-0">
      <TimeGrid days={days} events={events} tasks={showDue ? tasks : []} onEvent={open} onAdd={setNewAt} onDay={day => openDay(day, 'agenda')} />
    </div> : <div className="flex-1 overflow-auto rounded-lg border border-border md:min-h-0">
      <div className="grid grid-cols-7 border-b border-border bg-muted/40">{days.slice(0, 7).map(day => <div key={day.toISOString()} className="py-2 text-center text-xs text-muted-foreground">{format(day, 'EEEEEE', { locale: ru })}</div>)}</div>
      <div className="grid grid-cols-7">{days.map(day => {
        const meetings = events.filter(e => eventDaySegment(e, day))
        const due = tasks.filter(t => t.due_at && isSameDay(new Date(t.due_at), day))
        const planned = plan[format(day, 'yyyy-MM-dd')] ?? 0
        return <div key={day.toISOString()} className={cn('min-w-0 min-h-28 border-b border-r border-border p-1', !isSameMonth(day, anchor) && 'bg-muted/30')}>
          <div className="flex items-center justify-between">
            <button aria-label={`Открыть ${format(day, 'd MMMM', { locale: ru })}`} onClick={() => openDay(day)} className={cn('min-h-8 min-w-7 rounded text-sm hover:bg-accent', isToday(day) && 'bg-primary font-semibold text-primary-foreground')}>{format(day, 'd')}</button>
            <button className="hidden h-8 w-8 items-center justify-center rounded hover:bg-accent md:flex" aria-label={`Добавить встречу ${format(day, 'd MMMM', { locale: ru })}`} onClick={() => createAt(day)}><Plus className="h-3.5 w-3.5" /></button>
          </div>
          {meetings.slice(0, 2).map(event => <button key={event.id} onClick={() => open(event)} title={event.title} className={cn('mb-1 block w-full truncate rounded bg-primary/10 px-1 py-1 text-left text-xs hover:bg-primary/20', (event.status === 'cancelled' || event.my_response === 'declined') && 'text-muted-foreground line-through')}>
            {!event.all_day && <span className="mr-1 tabular-nums">{format(new Date(event.starts_at), 'HH:mm')}</span>}{event.title}
          </button>)}
          {meetings.length > 2 && <button onClick={() => openDay(day)} className="min-h-8 text-left text-xs text-primary hover:underline">Ещё {meetings.length - 2}</button>}
          {due.some(task => task.visibility !== 'personal') && <button onClick={() => openDay(day, 'agenda')} className={cn('block min-h-8 text-left text-xs hover:underline', due.some(t => t.visibility !== 'personal' && t.overdue) ? 'text-destructive' : 'text-muted-foreground')}>{due.filter(task => task.visibility !== 'personal').length} {срок(due.filter(task => task.visibility !== 'personal').length)}</button>}
          {due.some(task => task.visibility === 'personal') && <button onClick={() => openDay(day, 'agenda')} className="block min-h-8 text-left text-xs text-muted-foreground hover:underline">Мне: {due.filter(task => task.visibility === 'personal').length}</button>}
          {planned > 0 && <button onClick={() => openDay(day, 'agenda')} className="block min-h-8 text-left text-xs text-muted-foreground hover:underline">Намечено {planned}</button>}
        </div>
      })}</div>
    </div>}
    {(newAt || (eventId && eventQ.data && !eventQ.isError)) && <EventDialog key={eventId || newAt?.toISOString()} companyId={companyId} event={newAt ? null : eventQ.data!} startAt={newAt}
      onClose={() => { setNewAt(null); if (eventId) update({ event: null }) }} onChanged={changed} />}
  </div>
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
    onError: (error: Error) => toast.error(error.message || 'Не удалось сменить ключ подписки'),
  })

  return (
    <Popover open={открыт} onOpenChange={setОткрыт}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost" aria-label="Подписка на календарь" className="h-10 w-10 shrink-0 px-0 text-xs md:w-auto md:px-2.5"
          title="Показывать этот календарь в телефоне или Outlook">
          <Rss className="h-4 w-4 md:mr-1" /><span className="hidden md:inline">Подписка</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 max-w-[calc(100vw-2rem)] space-y-2">
        <p className="text-xs font-medium">Ваш календарь во внешнем клиенте</p>
        <p className="text-xs text-muted-foreground">
          Вставьте адрес в Google Календарь, Apple Календарь или Outlook как
          подписку по ссылке. Встречи будут видны только для чтения.
        </p>
        {q.isLoading && <p className="text-xs text-muted-foreground">Собираю адрес…</p>}
        {q.isError && <p role="alert" className="text-sm">Не удалось получить адрес. <button className="underline" onClick={() => void q.refetch()}>Повторить</button></p>}
        {q.data && (
          <>
            <input aria-label="Адрес подписки на календарь" readOnly value={q.data.url} onFocus={(e) => e.target.select()}
              className="w-full rounded border border-input bg-muted/40 px-2 py-1 font-mono text-xs" />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                onClick={async () => {
                  try { await navigator.clipboard.writeText(q.data.url); toast.success('Адрес скопирован') }
                  catch { toast.error('Не удалось скопировать адрес. Выделите и скопируйте его из поля.') }
                }}>Скопировать</Button>
              <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                disabled={сменить.isPending}
                title="Прежняя ссылка перестанет работать"
                onClick={() => сменить.mutate()}>Сменить ключ</Button>
            </div>
            {q.data.note && (
              <p className="text-xs text-muted-foreground">{q.data.note}</p>
            )}
            <p className="text-xs text-muted-foreground">
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
