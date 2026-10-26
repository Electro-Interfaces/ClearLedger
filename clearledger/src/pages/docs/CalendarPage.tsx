import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import {
  addDays, addMonths, addWeeks, addYears, eachDayOfInterval, endOfMonth, endOfWeek, format,
  isSameDay, isSameMonth, isValid, parseISO, startOfDay, startOfMonth, startOfWeek, startOfYear,
} from 'date-fns'
import { ru } from 'date-fns/locale'
import {
  Bell, Building2, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, ListChecks, Loader2,
  PanelLeft, Plus, RefreshCw, Repeat, Rss, Search, Video, X,
} from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import * as workService from '@/services/workService'
import type { CalendarEvent } from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { eventDaySegment, recurrenceTimes } from '@/lib/calendarLayout'
import { видимаВКалендаре } from '@/lib/calendarVisibility'
import {
  calendarDayKey, companyDateKey, companyDateTimeToDate, companyDayStart, companyDayTime, companyTime,
  companyTodayDate, isCompanyDay, isCompanyToday, COMPANY_TIME_ZONE,
} from '@/lib/companyTime'
import { EventDialog } from '@/components/calendar/EventDialog'
import { TimeGrid } from '@/components/calendar/TimeGrid'

/** Порядок видов — от короткого периода к длинному, «Список» отдельно в конце:
 *  так их ставят настольные календари, и рука ищет «Неделю» рядом с «Днём». */
const MODES = { day: 'День', week: 'Неделя', month: 'Месяц', year: 'Год', agenda: 'Список' }
const REPEAT_WORD: Record<string, string> = {
  daily: 'каждый день', weekly: 'каждую неделю', monthly: 'каждый месяц',
}
type Mode = keyof typeof MODES
/** Как повторяется дело: разово или расписанием «Трека». */
type DeedRepeat = 'none' | 'daily' | 'weekly' | 'monthly'

/**
 * Что показано в сетке — слоями, как календари в Outlook и VK: свой календарь,
 * общий календарь компании и три «жителя», которые встречами не являются.
 * Раньше был переключатель «Мой / Компании / Вместе» и отдельная галочка
 * «Сроки» только для недели; теперь любой слой включается сам по себе, и оба
 * календаря можно смотреть одной сеткой (решение МАГа 26.10.2026).
 */
type Слои = { mine: boolean; company: boolean; due: boolean; reminders: boolean; repeats: boolean }
const СЛОИ_ПО_УМОЛЧАНИЮ: Слои = { mine: true, company: false, due: true, reminders: true, repeats: true }
const СЛОИ_КЛЮЧ = 'calendar-layers'

function начальныеСлои(scope: string | null): Слои {
  let слои = СЛОИ_ПО_УМОЛЧАНИЮ
  try {
    const сохранено = JSON.parse(localStorage.getItem(СЛОИ_КЛЮЧ) ?? 'null') as Partial<Слои> | null
    if (сохранено && typeof сохранено === 'object') слои = { ...слои, ...сохранено }
    // Прежняя галочка «Сроки» недели — тот же вопрос, что слой сроков.
    else if (localStorage.getItem('calendar-hide-due') === '1') слои = { ...слои, due: false }
  } catch { /* хранилище недоступно — по умолчанию */ }
  // Ссылки со старым параметром ведут туда же, куда вели.
  if (scope === 'mine') слои = { ...слои, mine: true, company: false }
  if (scope === 'company') слои = { ...слои, mine: false, company: true }
  if (scope === 'all') слои = { ...слои, mine: true, company: true }
  return слои
}

const СЛОИ_ПОДПИСИ: { key: keyof Слои; label: string; mark: ReactNode }[] = [
  { key: 'mine', label: 'Мой календарь', mark: <span className="size-3 rounded-[4px] border border-primary/50 bg-primary/20" /> },
  { key: 'company', label: 'Календарь компании', mark: <span className="size-3 rounded-[4px] border border-foreground/40 bg-background" /> },
  { key: 'due', label: 'Сроки поручений', mark: <ListChecks className="h-3.5 w-3.5 text-muted-foreground" /> },
  { key: 'reminders', label: 'Напоминания', mark: <Bell className="h-3.5 w-3.5 text-muted-foreground" /> },
  { key: 'repeats', label: 'Повторяющиеся дела', mark: <Repeat className="h-3.5 w-3.5 text-muted-foreground" /> },
]

export function CalendarPage() {
  const { company } = useCompany()
  const companyId = company?.id ?? ''
  const qc = useQueryClient()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [defaultMode] = useState<Mode>(() => window.matchMedia('(max-width: 767px)').matches ? 'agenda' : 'month')
  const requestedMode = params.get('calendarMode')
  const mode = requestedMode && Object.hasOwn(MODES, requestedMode) ? requestedMode as Mode : defaultMode
  const requestedDate = params.get('date') ?? ''
  const anchor = /^\d{4}-\d{2}-\d{2}$/.test(requestedDate) && isValid(parseISO(requestedDate))
    ? startOfDay(parseISO(requestedDate)) : companyTodayDate()
  const [слои, setСлои] = useState<Слои>(() => начальныеСлои(params.get('calendarScope')))
  const personal = слои.mine
  const eventId = params.get('event')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  // Телефон: своя шапка в одну строку; поле поиска раскрывается по кнопке.
  const phone = useIsMobile()
  const [searchOpen, setSearchOpen] = useState(false)
  // Левая колонка на узком окне (планшет) уходит за кнопку, на широком стоит всегда.
  const [колонкаОткрыта, setКолонкаОткрыта] = useState(false)
  /** Черновик дела: что, когда, на весь день или к часу, напоминание, повторение. */
  const [deed, setDeed] = useState<{
    title: string; date: string; time: string; allDay: boolean
    remindBefore: number | null; repeat: DeedRepeat
  } | null>(null)
  const [newAt, setNewAt] = useState<Date | null>(null)
  const [companyDay, setCompanyDay] = useState(false)
  /** Встреча, которую собирают в панели: сетка рисует её на месте. */
  const [draft, setDraft] = useState<{ start: Date; end: Date; title: string } | null>(null)
  // Скрываются ПРОШЕДШИЕ отменённые: именно они накапливались в сетке и мешали
  // назначать новую встречу на то же время (РусГидро, 14.10.2026). Отменённая
  // встреча, день которой ещё не прошёл, видна всегда и без этой галочки:
  // пропав молча, она отправляет человека в пустую переговорную (docs/TRACK.md,
  // «Календарь»). Слот она при этом не занимает — занятость считают только по
  // запланированным.
  const [showCancelled, setShowCancelled] = useState(() => {
    try { return localStorage.getItem('calendar-show-cancelled') === '1' } catch { return false }
  })
  const переключитьОтменённые = (value: boolean) => {
    setShowCancelled(value)
    try { localStorage.setItem('calendar-show-cancelled', value ? '1' : '0') } catch { /* пусто */ }
  }
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
  const переключитьСлой = (key: keyof Слои, value: boolean) => {
    setСлои(было => {
      const стало = { ...было, [key]: value }
      try { localStorage.setItem(СЛОИ_КЛЮЧ, JSON.stringify(стало)) } catch { /* пусто */ }
      return стало
    })
    // Параметр ссылки отработал при открытии; дальше выбор человека главнее.
    if (params.has('calendarScope')) update({ calendarScope: null })
  }
  const dateKey = format(anchor, 'yyyy-MM-dd')
  const { from, to, days } = useMemo(() => {
    const at = parseISO(dateKey)
    const from = mode === 'month' ? startOfWeek(startOfMonth(at), { weekStartsOn: 1 })
      : mode === 'year' ? startOfYear(at)
        : mode === 'week' ? startOfWeek(at, { weekStartsOn: 1 }) : at
    const to = mode === 'month' ? addDays(startOfDay(endOfWeek(endOfMonth(at), { weekStartsOn: 1 })), 1)
      : mode === 'year' ? addYears(from, 1)
        : addDays(from, mode === 'day' ? 1 : 7)
    return { from, to, days: eachDayOfInterval({ start: from, end: addDays(to, -1) }) }
  }, [dateKey, mode])
  const rangeFrom = companyDayStart(from)
  const rangeTo = companyDayStart(to)

  const eventsQ = useQuery({
    queryKey: ['calendar', companyId, слои.mine, слои.company, rangeFrom.toISOString(), rangeTo.toISOString(), query],
    queryFn: async () => {
      const load = (s: 'mine' | 'company') => workService.listEvents(
        companyId, rangeFrom.toISOString(), rangeTo.toISOString(), { scope: s, q: query || undefined })
      const [mine, company] = await Promise.all([
        слои.mine ? load('mine') : null,
        слои.company ? load('company') : null,
      ])
      const own = new Set((mine?.events ?? []).map(e => e.id))
      const rest = (company?.events ?? []).filter(e => !own.has(e.id))
      return {
        events: [...(mine?.events ?? []), ...rest],
        truncated: !!(mine?.truncated || company?.truncated),
        // Чужие встречи общего календаря рамкой — только рядом со своими:
        // одни они рисуются обычно, отличать их не от чего.
        foreign: mine ? rest.map(e => e.id) : [],
      }
    },
    enabled: !!companyId && (слои.mine || слои.company), staleTime: 30_000, refetchOnWindowFocus: true,
  })
  const tasksQ = useQuery({
    queryKey: ['calendar-tasks', companyId, rangeFrom.toISOString(), rangeTo.toISOString()],
    queryFn: () => tasksService.listTasks(companyId, 'my_due', { dueFrom: rangeFrom.toISOString(), dueTo: rangeTo.toISOString(), limit: 200 }),
    enabled: !!companyId && слои.due, refetchOnWindowFocus: true,
  })
  const planQ = useQuery({
    queryKey: ['calendar-plan', companyId, calendarDayKey(from), calendarDayKey(addDays(to, -1))],
    queryFn: () => workService.planDays(companyId, workService.todayKey(from), workService.todayKey(addDays(to, -1))),
    enabled: !!companyId && personal && mode !== 'year', refetchOnWindowFocus: true,
  })
  /**
   * Личные напоминания — третий житель календаря рядом со встречами и сроками
   * (замечание МАГа 07.09.2026: «календарь — это не только встречи»). Список
   * приходит целиком (их единицы), период отбираем на месте: своя ручка периода
   * ради десятка строк — лишний контракт.
   */
  const remindersQ = useQuery({
    queryKey: ['calendar-reminders', companyId],
    queryFn: () => workService.listReminders(companyId),
    enabled: !!companyId && слои.reminders, refetchOnWindowFocus: true,
  })
  /** Расписания дел: без них повторяющееся дело видно только в день, когда оно
   *  уже поставлено, и планировать вперёд по календарю нельзя. */
  const recurQ = useQuery({
    queryKey: ['task-recurrences', companyId],
    queryFn: () => tasksService.listTaskRecurrences(companyId),
    enabled: !!companyId && слои.repeats,
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
  /**
   * Записать дело. Время — это и срок, и момент напоминания: человек ставит «в 15:00
   * позвонить», и ему в 15:00 об этом говорят. «Весь день» — дело без часа, срок на
   * конец дня, напоминания нет: напоминать «когда-нибудь сегодня» бессмысленно.
   */
  const записатьДело = useMutation({
    mutationFn: async () => {
      const d = deed!
      const at = companyDateTimeToDate(`${d.date}T${d.allDay ? '18:00' : (d.time || '18:00')}`)
      if (d.repeat !== 'none') {
        // Повторяющееся дело — это шаблон плюс расписание: дальше «Трек» ставит
        // задачу сам, в назначенное время и по своему часовому поясу.
        const tpl = await tasksService.createTaskTemplate({
          companyId, name: d.title.trim().slice(0, 160), title: d.title.trim(),
          assigneeId: user?.id || undefined, checklist: [],
        })
        const время = d.allDay ? '09:00' : (d.time || '09:00')
        const rule: Record<string, unknown> = {
          mode: d.repeat, at: время,
          tz: COMPANY_TIME_ZONE,
        }
        if (d.repeat === 'weekly') rule.weekday = (at.getDay() + 6) % 7   // пн = 0
        if (d.repeat === 'monthly') rule.day = at.getDate()
        await tasksService.createTaskRecurrence({ companyId, templateId: tpl.id, rule })
        return null
      }
      const task = await tasksService.createTask({
        companyId, title: d.title.trim(),
        // Исполнитель явный: без него задача ничья и в «Моей очереди» не появится.
        assigneeId: user?.id || undefined,
        dueAt: at.toISOString(),
      })
      if (!d.allDay && d.remindBefore !== null) {
        // «За сколько до» — то же, что у встречи: срок один, а сказать о нём можно
        // заранее (вопрос МАГа 07.09.2026).
        const remindAt = new Date(at.getTime() - d.remindBefore * 60_000)
        if (remindAt > new Date()) {
          await workService.createReminder(companyId, {
            targetRef: `task:${task.id}`, remindAt: remindAt.toISOString(), note: d.title.trim(),
          }).catch(() => { /* дело записано; о неудаче напоминания скажет само окно */ })
        }
      }
      return task
    },
    onSuccess: () => {
      const d = deed!
      setDeed(null)
      changed()
      void qc.invalidateQueries({ queryKey: ['calendar-reminders', companyId] })
      void qc.invalidateQueries({ queryKey: ['task-recurrences', companyId] })
      toast.success(d.repeat === 'none'
        ? `Записано на ${format(parseISO(d.date), 'd MMMM', { locale: ru })}`
        : `Дело будет ставиться ${REPEAT_WORD[d.repeat]} — расписание в «Треке»`)
    },
    onError: (e: Error) => toast.error(e.message || 'Не записалось'),
  })
  const open = (event: CalendarEvent) => {
    qc.setQueryData(['calendar-event', companyId, event.id], event)
    setNewAt(null); setDeed(null)
    update({ event: event.id })
  }
  const openDay = (day: Date, nextMode: Mode = 'day') => update({ date: format(day, 'yyyy-MM-dd'), calendarMode: nextMode })
  /** Новая встреча на это время. Одна панель за раз: открытая встреча или дело
   *  уступают место новой, иначе две панели легли бы друг на друга. */
  const startMeeting = (at: Date, forCompany = false) => {
    setCompanyDay(forCompany)
    setDeed(null)
    if (eventId) update({ event: null })
    setNewAt(at)
  }
  const createAt = (day: Date, forCompany = false) => {
    let at = companyDayTime(day, 10)
    const сейчас = new Date()
    if (isCompanyDay(сейчас, day) && at < сейчас) at = new Date(Math.ceil(сейчас.getTime() / 1_800_000) * 1_800_000)
    startMeeting(at, forCompany)
  }
  const move = (step: number) => {
    const at = mode === 'month' ? addMonths(anchor, step) : mode === 'year' ? addYears(anchor, step)
      : mode === 'day' ? addDays(anchor, step) : addWeeks(anchor, step)
    update({ date: format(at, 'yyyy-MM-dd') })
  }
  if (!companyId) return null

  const events = (eventsQ.data?.events ?? []).filter(e => видимаВКалендаре(e,
    { сейчас: new Date(), показыватьПрошедшие: showCancelled, открытая: eventId }))
  const tasks = слои.due ? (tasksQ.data?.tasks ?? []).filter(t => !query || t.title.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru'))) : []
  const plan = personal && !query && mode !== 'year' ? (planQ.data ?? {}) : {}
  const reminders = (слои.reminders ? remindersQ.data?.items ?? [] : [])
    .filter(r => {
      const at = new Date(r.remind_at)
      return at >= rangeFrom && at < rangeTo
        && (!query || (r.note ?? '').toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')))
    })
  const foreign = new Set(eventsQ.data?.foreign ?? [])
  const now = new Date()
  const repeats = (слои.repeats ? recurQ.data?.recurrences ?? [] : [])
    .filter(r => r.mine && r.enabled
      && (!query || r.template.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru'))))
    .flatMap(r => recurrenceTimes(r.rule, days, now).map(at => ({ id: r.id + at.getTime(), title: r.template, at })))
  const newDeed = () => {
    setNewAt(null)
    if (eventId) update({ event: null })
    setDeed({
      title: '', date: format(anchor, 'yyyy-MM-dd'), time: '18:00', allDay: false,
      remindBefore: 0, repeat: 'none',
    })
  }
  /** Что можно записать в календарь. Одно меню на телефон и на стол: раньше со
   *  стола ставилась только встреча, а дело себе — только с телефона. */
  const createItems = <>
    <DropdownMenuItem onSelect={() => createAt(anchor)}>
      <CalendarDays className="mr-2 h-4 w-4" />Встреча
    </DropdownMenuItem>
    <DropdownMenuItem onSelect={newDeed}>
      <ListChecks className="mr-2 h-4 w-4" />Дело себе
    </DropdownMenuItem>
    <DropdownMenuItem onSelect={() => createAt(anchor, true)}>
      <Building2 className="mr-2 h-4 w-4" />Событие компании
    </DropdownMenuItem>
  </>
  const chip = (event: CalendarEvent) => cn(
    'mb-0.5 block w-full truncate rounded-md px-1.5 py-1 text-left text-xs',
    foreign.has(event.id) ? 'border border-border bg-background hover:bg-accent' : 'bg-primary/15 hover:bg-primary/25',
    (event.status === 'cancelled' || event.my_response === 'declined') && 'text-muted-foreground line-through')
  const busy = eventsQ.isFetching || tasksQ.isFetching || planQ.isFetching
  const errors = [
    ...(слои.mine || слои.company ? [{ q: eventsQ, label: 'встречи' }] : []),
    ...(слои.due ? [{ q: tasksQ, label: 'сроки поручений' }] : []),
    ...(personal ? [{ q: planQ, label: 'личный план' }] : []),
  ].filter(row => row.q.isError)
  const caption = mode === 'month' ? format(anchor, 'LLLL yyyy', { locale: ru })
    : mode === 'year' ? format(anchor, 'yyyy')
      : mode === 'day' ? format(anchor, 'EEEEEE, d MMMM yyyy', { locale: ru })
        : `${format(from, 'd MMM', { locale: ru })} — ${format(addDays(to, -1), 'd MMM yyyy', { locale: ru })}`
  /** Дни, где что-то стоит: точки в годе. */
  const занятыеДни = new Set([
    ...events.flatMap(e => {
      const end = new Date(e.ends_at)
      const ключи: string[] = []
      for (let d = parseISO(companyDateKey(e.starts_at)); companyDayStart(d) < end && ключи.length < 62; d = addDays(d, 1)) ключи.push(calendarDayKey(d))
      return ключи
    }),
    ...tasks.filter(t => t.due_at).map(t => companyDateKey(t.due_at!)),
    ...reminders.map(r => companyDateKey(r.remind_at)),
  ])
  const meetingOpen = !!(newAt || (eventId && eventQ.data && !eventQ.isError))
  const ничегоНеВключено = !Object.values(слои).some(Boolean)

  /**
   * Шапка календаря на телефоне — ОДНА строка (решение МАГа 07.09.2026).
   *
   * Как в телефонном календаре: строка с периодом и стрелками, всё остальное —
   * за одним меню у вида (вид, какие календари показаны, «сегодня»), а «＋» —
   * плавающая кнопка над нижней панелью, где её и ищут большим пальцем.
   * Нажатие на сам период открывает выбор даты.
   */
  const activeMode = MODES[mode as Mode] ?? 'Список'
  const mobileHeader = (
    <header className="flex items-center gap-1">
      <Button size="icon" variant="ghost" className="size-9 shrink-0" aria-label="Предыдущий период"
        onClick={() => move(-1)}><ChevronLeft className="h-5 w-5" /></Button>

      <label className="relative min-w-0 flex-1">
        <span className="block truncate text-center text-base font-semibold capitalize">{caption}</span>
        <input type="date" aria-label="Перейти к дате" value={dateKey}
          onChange={e => { if (e.target.value) update({ date: e.target.value }) }}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
      </label>

      <Button size="icon" variant="ghost" className="size-9 shrink-0" aria-label="Следующий период"
        onClick={() => move(1)}><ChevronRight className="h-5 w-5" /></Button>

      <Button size="icon" variant={searchOpen || query ? 'secondary' : 'ghost'}
        className="size-9 shrink-0" aria-label="Поиск в периоде"
        onClick={() => { setSearchOpen(v => !v); if (searchOpen) setSearch('') }}>
        <Search className="h-4 w-4" />
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="h-9 shrink-0 gap-1 px-2 text-xs">
            {activeMode}<ChevronDown className="h-3.5 w-3.5 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuLabel>Вид</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={mode} onValueChange={value => update({ calendarMode: value })}>
            {(Object.entries(MODES) as [Mode, string][]).map(([key, label]) => (
              <DropdownMenuRadioItem key={key} value={key}>{label}</DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Календари</DropdownMenuLabel>
          {СЛОИ_ПОДПИСИ.map(({ key, label }) => (
            <DropdownMenuCheckboxItem key={key} checked={слои[key]}
              onSelect={e => e.preventDefault()}
              onCheckedChange={value => переключитьСлой(key, !!value)}>
              {label}
            </DropdownMenuCheckboxItem>
          ))}
          <DropdownMenuCheckboxItem checked={showCancelled} onSelect={e => e.preventDefault()}
            onCheckedChange={value => переключитьОтменённые(!!value)}>
            Прошедшие отменённые
          </DropdownMenuCheckboxItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => update({ date: format(companyTodayDate(), 'yyyy-MM-dd') })}>
            Сегодня
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  )

  /**
   * Левая колонка — как у настольных календарей: «создать», мини-месяц для
   * перехода по датам и список того, что показано в сетке. Период и вид живут
   * в строке над сеткой, а не здесь: колонка отвечает на «что», строка — на «когда».
   */
  const колонка = (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-3">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button className="w-full justify-center shadow-sm shadow-primary/20">
            <Plus className="mr-1.5 h-4 w-4" />Новое событие<ChevronDown className="ml-1 h-3.5 w-3.5 opacity-70" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">{createItems}</DropdownMenuContent>
      </DropdownMenu>

      <MiniMonth value={anchor} mode={mode} onPick={day => { update({ date: format(day, 'yyyy-MM-dd') }); setКолонкаОткрыта(false) }} />

      <section aria-labelledby="calendar-layers-title" className="space-y-0.5">
        <h3 id="calendar-layers-title" className="px-1 pb-1 text-xs font-medium text-muted-foreground">Календари</h3>
        {СЛОИ_ПОДПИСИ.map(({ key, label, mark }) => (
          <label key={key} className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-md px-1 text-sm hover:bg-accent/60">
            <Checkbox checked={слои[key]} onCheckedChange={value => переключитьСлой(key, value === true)} />
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <span aria-hidden className="grid w-4 place-items-center">{mark}</span>
          </label>
        ))}
        <label className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-md px-1 text-sm hover:bg-accent/60">
          <Checkbox checked={showCancelled} onCheckedChange={value => переключитьОтменённые(value === true)} />
          <span className="min-w-0 flex-1 truncate">Прошедшие отменённые</span>
        </label>
      </section>

      <div className="mt-auto flex items-center gap-1 border-t border-border pt-3">
        <FeedLink wide />
        <Button variant="ghost" size="icon" className="ml-auto size-9" aria-label="Обновить календарь" disabled={busy} onClick={changed}>
          <RefreshCw className={cn('h-4 w-4', busy && 'animate-spin')} />
        </Button>
      </div>
    </div>
  )

  /** Строка над сеткой: «Сегодня ‹ › период» слева, поиск и виды справа. */
  const toolbar = (
    <header className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="icon" className="size-10 lg:hidden" aria-label="Календари и мини-месяц"
        aria-expanded={колонкаОткрыта} onClick={() => setКолонкаОткрыта(v => !v)}>
        <PanelLeft className="h-4 w-4" />
      </Button>
      <Button variant="secondary" className="h-10 px-4" onClick={() => update({ date: format(companyTodayDate(), 'yyyy-MM-dd') })}>Сегодня</Button>
      <div className="flex items-center">
        <Button size="icon" variant="ghost" className="size-10" aria-label="Предыдущий период" onClick={() => move(-1)}><ChevronLeft className="h-5 w-5" /></Button>
        <Button size="icon" variant="ghost" className="size-10" aria-label="Следующий период" onClick={() => move(1)}><ChevronRight className="h-5 w-5" /></Button>
      </div>
      <h2 className="min-w-0 truncate font-headline text-lg font-semibold first-letter:uppercase" aria-live="polite">{caption}</h2>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label="Найти в календаре" placeholder="Поиск в периоде" maxLength={200} value={search}
            onChange={e => setSearch(e.target.value)} className="h-10 w-52 pl-9 pr-8 text-sm" />
          {search && <button type="button" aria-label="Сбросить поиск" onClick={() => setSearch('')}
            className="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-muted-foreground hover:bg-accent">
            <X className="h-3.5 w-3.5" />
          </button>}
        </div>
        <div role="group" aria-label="Вид календаря" className="flex items-center rounded-lg border border-border bg-muted/40 p-0.5">
          {(Object.entries(MODES) as [Mode, string][]).map(([key, label]) => (
            <button key={key} type="button" aria-pressed={mode === key} onClick={() => update({ calendarMode: key })}
              className={cn('h-9 rounded-md px-3 text-sm transition-colors',
                mode === key ? 'bg-primary font-medium text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
              {label}
            </button>
          ))}
        </div>
      </div>
    </header>
  )

  /* Дело — вторая половина календаря рядом со встречей (разбор с МАГом 07.09.2026).
     Встреча — «с кем-то и в такое-то время». Дело — то, что человек делает сам:
     на день целиком или на время, и тогда оно же напоминание «скажи мне в 15:00». */
  const делоПоля = <>
    <Input autoFocus maxLength={300} value={deed?.title ?? ''} placeholder="Что нужно сделать" aria-label="Что нужно сделать"
      onChange={e => setDeed(d => d && { ...d, title: e.target.value })}
      onKeyDown={e => { if (e.key === 'Enter' && (deed?.title ?? '').trim().length >= 3) записатьДело.mutate() }}
      className="h-11 font-headline text-lg font-semibold md:text-lg" />

    <div className="grid grid-cols-2 gap-2">
      <label className="space-y-1 text-xs text-muted-foreground">
        Когда
        <Input type="date" value={deed?.date ?? ''} className="h-10 text-base md:text-sm"
          onChange={e => setDeed(d => d && { ...d, date: e.target.value })} />
      </label>
      <label className="space-y-1 text-xs text-muted-foreground">
        Время
        <Input type="time" value={deed?.time ?? ''} disabled={deed?.allDay}
          className="h-10 text-base md:text-sm"
          onChange={e => setDeed(d => d && { ...d, time: e.target.value })} />
      </label>
    </div>

    <label className="flex min-h-9 items-center gap-2 text-sm">
      <Checkbox checked={deed?.allDay ?? false}
        onCheckedChange={value => setDeed(d => d && { ...d, allDay: value === true })} />
      Весь день
    </label>

    {!deed?.allDay && (
      <label className="flex flex-wrap items-center gap-2 text-sm">
        <span className="flex items-center gap-1.5"><Bell className="h-3.5 w-3.5 text-muted-foreground" />Напомнить</span>
        <select value={deed?.remindBefore ?? ''}
          onChange={e => setDeed(d => d && {
            ...d, remindBefore: e.target.value === '' ? null : Number(e.target.value),
          })}
          className="h-9 rounded-md border border-input bg-card px-2 text-sm">
          <option value="">не напоминать</option>
          <option value="0">в это время</option>
          <option value="5">за 5 минут</option>
          <option value="15">за 15 минут</option>
          <option value="30">за 30 минут</option>
          <option value="60">за час</option>
          <option value="1440">за день</option>
        </select>
      </label>
    )}

    {/* Повторение — как у встречи, только заводится расписанием «Трека»
        (решение МАГа 08.09.2026): шаблон плюс правило, дальше дело ставится само. */}
    <label className="flex flex-wrap items-center gap-2 text-sm">
      <span className="flex items-center gap-1.5"><Repeat className="h-3.5 w-3.5 text-muted-foreground" />Повторять</span>
      <select value={deed?.repeat ?? 'none'}
        onChange={e => setDeed(d => d && { ...d, repeat: e.target.value as DeedRepeat })}
        className="h-9 rounded-md border border-input bg-card px-2 text-sm">
        <option value="none">не повторяется</option>
        <option value="daily">каждый день</option>
        <option value="weekly">каждую неделю</option>
        <option value="monthly">каждый месяц</option>
      </select>
    </label>
  </>
  const делоЗаписать = (
    <Button className="h-10 w-full"
      disabled={(deed?.title ?? '').trim().length < 3 || !deed?.date || записатьДело.isPending}
      onClick={() => записатьДело.mutate()}>
      {записатьДело.isPending ? 'Записываем…' : 'Записать'}
    </Button>
  )

  const сетка = mode === 'agenda' ? <div className="min-h-0 flex-1 overflow-y-auto" aria-label="Расписание">
    {days.map(day => {
      const meetings = events.filter(e => eventDaySegment(e, day))
      const due = tasks.filter(t => t.due_at && isCompanyDay(t.due_at, day))
      const planned = plan[format(day, 'yyyy-MM-dd')] ?? 0
      const dayReminders = reminders.filter(r => isCompanyDay(r.remind_at, day))
      const dayRepeats = repeats.filter(r => isCompanyDay(r.at, day))
      if (!meetings.length && !due.length && !planned && !dayReminders.length && !dayRepeats.length) return null
      return <section key={day.toISOString()} className="mb-5" aria-label={format(day, 'd MMMM', { locale: ru })}>
        {/* Заголовок дня — разделитель списка. Плюс у каждого дня убран с телефона
            (замечание МАГа 07.09.2026): три одинаковые кнопки читались как винегрет. */}
        <div className="mb-1 flex items-center gap-2 border-b border-border pb-1">
          <button className={cn('min-h-10 flex-1 text-left text-sm font-semibold capitalize hover:underline', isCompanyToday(day) && 'text-primary')} onClick={() => openDay(day)}>{format(day, 'EEEE, d MMMM', { locale: ru })}</button>
          {!phone && <Button variant="ghost" size="icon" aria-label={`Добавить встречу ${format(day, 'd MMMM', { locale: ru })}`} onClick={() => createAt(day)}><Plus className="h-4 w-4" /></Button>}
        </div>
        {meetings.map(event => <button key={event.id} onClick={() => open(event)} className="flex min-h-14 w-full items-start gap-3 border-b border-border/60 px-1 py-3 text-left hover:bg-accent">
          <span className="w-16 shrink-0 text-sm tabular-nums text-muted-foreground">{event.all_day ? 'Весь день' : <>{companyTime(eventDaySegment(event, day)!.start)}<span className="block">{eventDaySegment(event, day)!.endMinute === 1440 ? '24:00' : companyTime(eventDaySegment(event, day)!.end)}</span></>}</span>
          <span className="min-w-0 flex-1">
            <span className={cn('block break-words text-sm font-medium', (event.status === 'cancelled' || event.my_response === 'declined') && 'text-muted-foreground line-through')}>{event.title}</span>
            <span className="mt-1 block break-words text-sm text-muted-foreground">{event.status === 'cancelled' ? `Отменена${event.cancel_reason ? ': ' + event.cancel_reason : ''}` : event.my_response === 'pending' ? 'Ждёт вашего ответа' : event.my_response === 'declined' ? 'Вы отказались' : event.location || (event.conference_url ? 'Видеовстреча' : eventDaySegment(event, day)?.continues ? 'Продолжение встречи' : foreign.has(event.id) ? 'Календарь компании' : '')}</span>
          </span>
          {event.conference_url && <Video className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />}
        </button>)}
        {/* Напоминание — тоже запись дня: стоит рядом со встречей, а не живёт
            отдельным списком в другом окне. */}
        {dayReminders.map(r => {
          const href = workService.refHref(r.target_ref)
          const row = <>
            <span className="w-16 shrink-0 text-sm tabular-nums text-muted-foreground">{companyTime(r.remind_at)}</span>
            <span className="flex min-w-0 flex-1 items-center gap-2">
              <Bell className={cn('h-4 w-4 shrink-0', r.fired_at ? 'text-primary' : 'text-muted-foreground')} />
              <span className="min-w-0 break-words">{r.note || 'Напоминание'}</span>
            </span>
          </>
          return href
            ? <Link key={r.id} to={href} className="flex min-h-12 items-center gap-3 border-b border-border/60 px-1 py-2 text-sm hover:bg-accent">{row}</Link>
            : <div key={r.id} className="flex min-h-12 items-center gap-3 border-b border-border/60 px-1 py-2 text-sm">{row}</div>
        })}
        {due.map(task => <Link key={task.id} to={workService.refHref('task:' + task.id)!} className="flex min-h-12 items-center gap-3 border-b border-border/60 px-1 py-2 text-sm hover:bg-accent">
          <span className={cn('w-16 shrink-0', task.overdue ? 'text-destructive' : 'text-muted-foreground')}>{task.visibility === 'personal' ? 'Мне' : 'Срок'}</span>
          <span className="min-w-0 break-words">{task.title}</span>
        </Link>)}
        {dayRepeats.map(r => <div key={r.id} title="Повторяющееся дело: «Трек» поставит его в это время" className="flex min-h-12 items-center gap-3 border-b border-border/60 px-1 py-2 text-sm text-muted-foreground">
          <span className="w-16 shrink-0 tabular-nums">{companyTime(r.at)}</span>
          <span className="flex min-w-0 flex-1 items-center gap-2"><Repeat className="h-4 w-4 shrink-0" /><span className="min-w-0 break-words">{r.title}</span></span>
        </div>)}
        {planned > 0 && <p className="flex min-h-10 items-center text-sm text-muted-foreground">Намечено на день: {planned}</p>}
      </section>
    })}
    {!eventsQ.isLoading && !tasksQ.isLoading && !errors.length && !events.length && !tasks.length && !repeats.length && !reminders.length && !Object.values(plan).some(Boolean) && <div className="py-8 text-center">
      <p className="font-medium">{query ? 'В этом периоде ничего не найдено' : 'В ближайшие семь дней записей нет'}</p>
      <p className="mt-2 text-sm text-muted-foreground">{query ? 'Измените запрос или выберите другой период.' : 'Назначьте встречу или выберите другую дату.'}</p>
      <Button className="mt-4" variant="outline" onClick={() => query ? setSearch('') : createAt(anchor)}>{query ? 'Сбросить поиск' : 'Назначить встречу'}</Button>
    </div>}
  </div> : mode === 'year' ? <YearView anchor={anchor} busyDays={занятыеДни}
    onDay={day => openDay(day, 'day')} onMonth={day => openDay(day, 'month')} />
    : mode !== 'month' ? <div className="flex min-h-0 flex-1 overflow-x-auto">
      <TimeGrid days={days} events={events} tasks={tasks} foreign={foreign} repeats={repeats} draft={newAt ? draft : null}
        onEvent={open} onAdd={at => startMeeting(at)} onDay={day => openDay(day, mode === 'week' ? 'day' : 'agenda')} />
    </div> : <div className="flex min-h-0 flex-1 flex-col overflow-auto rounded-xl border border-border bg-card">
      <div className="grid grid-cols-7 border-b border-border">{days.slice(0, 7).map(day => <div key={day.toISOString()} className={cn('px-2 py-2 text-sm font-medium', day.getDay() % 6 === 0 ? 'text-muted-foreground/80' : 'text-muted-foreground')}>{format(day, 'EEEEEE', { locale: ru })}</div>)}</div>
      <div className="grid flex-1 grid-cols-7 [grid-auto-rows:minmax(5.5rem,1fr)]">{days.map(day => {
        const meetings = events.filter(e => eventDaySegment(e, day))
        const due = tasks.filter(t => t.due_at && isCompanyDay(t.due_at, day))
        const planned = plan[format(day, 'yyyy-MM-dd')] ?? 0
        const dayRepeats = repeats.filter(r => isCompanyDay(r.at, day))
        const dayReminders = reminders.filter(r => isCompanyDay(r.remind_at, day))
        /* Строки дня названиями, а не счётчиком «2 срока»: в месяце смотрят, ЧТО
           стоит на числе, и ради этого не должны открывать день. */
        const rows = [
          ...meetings.map(event => <button key={event.id} onClick={() => open(event)} title={event.title} className={chip(event)}>
            {!event.all_day && <span className="mr-1 tabular-nums text-muted-foreground">{companyTime(event.starts_at)}</span>}{event.title}
          </button>),
          ...due.map(task => <Link key={task.id} to={workService.refHref('task:' + task.id)!} title={task.title}
            className={cn('mb-0.5 flex items-center gap-1 rounded-md px-1.5 py-1 text-xs hover:bg-accent', task.overdue && 'text-destructive')}>
            <ListChecks className="h-3 w-3 shrink-0" /><span className="truncate">{task.title}</span>
          </Link>),
          ...dayRepeats.map(r => <span key={r.id} title={`Повторяющееся дело: поставится в ${companyTime(r.at)}`}
            className="mb-0.5 flex items-center gap-1 px-1.5 py-1 text-xs text-muted-foreground">
            <Repeat className="h-3 w-3 shrink-0" /><span className="truncate">{r.title}</span>
          </span>),
        ]
        const total = rows.length + dayReminders.length + planned
        const чужойМесяц = !isSameMonth(day, anchor)
        return <div key={day.toISOString()} className={cn('group min-w-0 border-b border-r border-border p-1 [&:nth-child(7n)]:border-r-0',
          чужойМесяц ? 'bg-muted/25' : day.getDay() % 6 === 0 && 'bg-muted/15')}>
          <div className="flex items-center justify-between">
            <button aria-label={`Открыть ${format(day, 'd MMMM', { locale: ru })}`} onClick={() => openDay(day)}
              className={cn('grid size-8 place-items-center rounded-full text-sm tabular-nums hover:bg-accent',
                isCompanyToday(day) ? 'bg-primary font-semibold text-primary-foreground hover:bg-primary/90'
                  : чужойМесяц ? 'text-muted-foreground' : 'font-medium')}>{format(day, 'd')}</button>
            {/* Плюс дня проступает при наведении и с клавиатуры: на каждой из 35
                клеток постоянно он читался рябью, а число в клетке — главное. */}
            <button className="hidden size-8 items-center justify-center rounded-md text-muted-foreground opacity-0 hover:bg-accent focus-visible:opacity-100 group-hover:opacity-100 md:flex" aria-label={`Добавить встречу ${format(day, 'd MMMM', { locale: ru })}`} onClick={() => createAt(day)}><Plus className="h-4 w-4" /></button>
          </div>
          {phone
            /* Телефон: в клетку шириной в палец название не влезает — «12:3…» хуже
               точки. Точки говорят, что день занят, нажатие открывает его списком. */
            ? total > 0 && <button onClick={() => openDay(day, 'agenda')} aria-label={`${format(day, 'd MMMM', { locale: ru })}: ${total} ${запись(total)}`}
              className="flex min-h-8 w-full flex-wrap content-start items-center gap-1 px-0.5 py-1">
              {meetings.slice(0, 3).map(e => <span key={e.id} className={cn('size-1.5 rounded-full', foreign.has(e.id) ? 'border border-foreground/60' : 'bg-primary')} />)}
              {due.slice(0, 3).map(t => <span key={t.id} className={cn('size-1.5 rounded-[1px]', t.overdue ? 'bg-destructive' : 'bg-foreground/50')} />)}
              {total > 3 && <span className="text-xs leading-none tabular-nums text-muted-foreground">{total}</span>}
            </button>
            : <>
              {rows.slice(0, 3)}
              {rows.length > 3 && <button onClick={() => openDay(day, 'agenda')} className="block px-1.5 text-left text-xs text-primary hover:underline">Ещё {rows.length - 3}</button>}
              {(planned > 0 || dayReminders.length > 0) && <button onClick={() => openDay(day, 'agenda')} className="flex items-center gap-2 px-1.5 py-0.5 text-left text-xs text-muted-foreground hover:underline">
                {planned > 0 && <span>Намечено {planned}</span>}
                {dayReminders.length > 0 && <span className="flex items-center gap-1"><Bell className="h-3 w-3" />{dayReminders.length}</span>}
              </button>}
            </>}
        </div>
      })}</div>
    </div>

  const сообщения = <>
    {errors.map(({ q, label }) => <div key={label} role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 px-3 py-2 text-sm">
      <span className="flex-1">Не удалось {q.data ? 'обновить' : 'загрузить'} {label}.{q.data ? ' Показаны ранее полученные данные.' : ''}</span>
      <Button variant="outline" size="sm" onClick={() => void q.refetch()}>Повторить</Button>
    </div>)}
    {ничегоНеВключено && <p role="status" className="rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">Ни один календарь не выбран. Отметьте «Мой календарь» или другой слой {phone ? 'в меню вида' : 'слева'}.</p>}
    {(eventsQ.isLoading || tasksQ.isLoading) && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Загружаются встречи и сроки…</p>}
    {(eventsQ.data?.truncated || (tasksQ.data?.total ?? 0) > (tasksQ.data?.tasks.length ?? 0)) && <p role="status" className="text-sm text-muted-foreground">В периоде слишком много записей. Выберите неделю или день, чтобы увидеть все.</p>}
    {eventId && eventQ.isPending && <p role="status" className="text-sm">Открывается встреча…</p>}
    {eventId && eventQ.isError && <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 p-3 text-sm">
      <span className="flex-1">Не удалось открыть встречу. Возможно, её нет или у вас нет доступа.</span>
      <Button variant="outline" size="sm" onClick={() => void eventQ.refetch()}>Повторить</Button>
      <Button variant="ghost" size="sm" onClick={() => update({ event: null })}>Закрыть</Button>
    </div>}
  </>

  const встреча = meetingOpen && <EventDialog key={eventId || `${newAt?.toISOString()}-${companyDay}`} companyId={companyId}
    event={newAt ? null : eventQ.data!} startAt={newAt} companyDay={!!newAt && companyDay} panel onDraft={setDraft}
    onClose={() => { setNewAt(null); if (eventId) update({ event: null }) }} onChanged={changed} />

  // Нижний отступ на высоту плашки установки: иначе на столе она ложится на
  // последнюю строку месяца, и записи этих дней не видно и не нажать.
  const отступПлашки = { paddingBottom: 'calc(0.75rem + var(--pwa-install-height, 0px) + var(--pwa-install-gap, 0px))' }

  if (phone) return <div className="flex h-full min-h-0 min-w-0 flex-col gap-3 p-3" style={отступПлашки}>
    {(searchOpen || query) && (
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input autoFocus aria-label="Найти в календаре" placeholder="Поиск в выбранном периоде"
          maxLength={200} value={search} onChange={e => setSearch(e.target.value)}
          className="h-9 pl-9 text-base" />
      </div>
    )}
    {mobileHeader}
    {сообщения}
    {сетка}
    {/* «Новое событие» — одна кнопка, два вида записи (решение МАГа 07.09.2026).
        Над плашкой «поставьте приложением», а не под ней: нажатие попадало в её
        «Позже» (проверка календаря 25.10.2026). */}
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button aria-label="Новое событие"
          className="fixed right-4 z-40 size-14 rounded-full p-0 shadow-lg"
          style={{ bottom: 'calc(4.5rem + env(safe-area-inset-bottom) + var(--pwa-install-height, 0px) + var(--pwa-install-gap, 0px))' }}>
          <Plus className="h-6 w-6" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="top" sideOffset={12} className="w-56">
        <DropdownMenuLabel>Новое событие</DropdownMenuLabel>
        {createItems}
      </DropdownMenuContent>
    </DropdownMenu>
    <Dialog open={deed !== null} onOpenChange={(o) => { if (!o) setDeed(null) }}>
      <DialogContent className="max-w-xs gap-3 sm:max-w-sm">
        <DialogHeader><DialogTitle className="text-sm">Дело</DialogTitle></DialogHeader>
        {делоПоля}
        {делоЗаписать}
      </DialogContent>
    </Dialog>
    {встреча}
  </div>

  return <div className="relative flex h-full min-h-0 min-w-0" style={отступПлашки}>
    {/* Колонка на широком окне стоит всегда; на узком — выезжает поверх сетки. */}
    <aside aria-label="Календари" className={cn('w-64 shrink-0 border-r border-border bg-muted/20',
      колонкаОткрыта ? 'absolute inset-y-0 left-0 z-40 block bg-card lg:static lg:bg-muted/20' : 'hidden lg:block')}
      style={колонкаОткрыта ? { boxShadow: 'var(--shadow-large)' } : undefined}>
      {колонка}
    </aside>
    {колонкаОткрыта && <button type="button" aria-label="Скрыть колонку календарей" className="absolute inset-0 z-30 bg-foreground/10 lg:hidden" onClick={() => setКолонкаОткрыта(false)} />}

    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-3 md:p-4">
      {toolbar}
      {сообщения}
      <div className="relative flex min-h-0 flex-1 flex-col">
        {сетка}
        {встреча}
        {deed && (
          <aside role="dialog" aria-label="Дело себе"
            onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setDeed(null) } }}
            className="absolute bottom-2 right-2 top-2 z-30 flex w-[min(400px,calc(100%-1rem))] flex-col overflow-hidden rounded-xl border border-border bg-card"
            style={{ boxShadow: 'var(--shadow-large)' }}>
            <div className="flex items-center gap-2 px-4 pt-4">
              <h2 className="flex-1 text-sm font-medium text-muted-foreground">Дело себе</h2>
              <Button variant="ghost" size="icon" className="size-9" aria-label="Закрыть" onClick={() => setDeed(null)}><X className="h-4 w-4" /></Button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-4 pt-1">{делоПоля}</div>
            <div className="border-t border-border px-4 py-3">{делоЗаписать}</div>
          </aside>
        )}
      </div>
    </div>
  </div>
}

/**
 * Мини-месяц в левой колонке: переход по датам одним нажатием. Листается сам по
 * себе, не трогая сетку, — человек ищет «следующий вторник через месяц», а
 * сетка остаётся на той неделе, где он работал, пока он не выберет число.
 */
function MiniMonth({ value, mode, onPick }: { value: Date; mode: Mode; onPick: (day: Date) => void }) {
  const [месяц, setМесяц] = useState(() => startOfMonth(value))
  const ключ = format(value, 'yyyy-MM')
  useEffect(() => { setМесяц(startOfMonth(parseISO(ключ + '-01'))) }, [ключ])
  const начало = startOfWeek(месяц, { weekStartsOn: 1 })
  const дни = eachDayOfInterval({ start: начало, end: addDays(начало, 41) })
  const выбранныйПериод = (d: Date) => mode === 'week'
    ? startOfWeek(d, { weekStartsOn: 1 }).getTime() === startOfWeek(value, { weekStartsOn: 1 }).getTime()
    : isSameDay(d, value)
  return (
    <section aria-label="Мини-календарь" className="select-none">
      <div className="mb-1 flex items-center">
        <Button variant="ghost" size="icon" className="size-8" aria-label="Предыдущий месяц" onClick={() => setМесяц(m => addMonths(m, -1))}><ChevronLeft className="h-4 w-4" /></Button>
        <span className="flex-1 text-center text-sm font-medium capitalize">{format(месяц, 'LLLL yyyy', { locale: ru })}</span>
        <Button variant="ghost" size="icon" className="size-8" aria-label="Следующий месяц" onClick={() => setМесяц(m => addMonths(m, 1))}><ChevronRight className="h-4 w-4" /></Button>
      </div>
      <div className="grid grid-cols-7 text-center text-xs text-muted-foreground">
        {дни.slice(0, 7).map(d => <span key={d.toISOString()} className="py-1">{format(d, 'EEEEEE', { locale: ru })}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-y-0.5 text-center">
        {дни.map(d => (
          <button key={d.toISOString()} type="button" onClick={() => onPick(d)}
            aria-label={format(d, 'd MMMM yyyy', { locale: ru })} aria-current={isSameDay(d, value) ? 'date' : undefined}
            className={cn('mx-auto grid size-8 place-items-center rounded-full text-xs tabular-nums hover:bg-accent',
              isCompanyToday(d) ? 'bg-primary font-semibold text-primary-foreground hover:bg-primary/90'
                : выбранныйПериод(d) ? 'bg-primary/15 font-medium text-foreground'
                  : !isSameMonth(d, месяц) ? 'text-muted-foreground/70' : 'text-foreground')}>
            {format(d, 'd')}
          </button>
        ))}
      </div>
    </section>
  )
}

/**
 * Год — двенадцать месяцев на одном экране: где отпуск, где плотная неделя,
 * где пусто. Точка под числом значит «в этот день что-то стоит»; что именно —
 * нажатием, в дне.
 */
function YearView({ anchor, busyDays, onDay, onMonth }: {
  anchor: Date; busyDays: Set<string>; onDay: (day: Date) => void; onMonth: (day: Date) => void
}) {
  const год = startOfYear(anchor)
  return (
    <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-border bg-card p-4">
      <div className="grid gap-x-8 gap-y-6 [grid-template-columns:repeat(auto-fill,minmax(15rem,1fr))]">
        {Array.from({ length: 12 }, (_, i) => addMonths(год, i)).map(месяц => {
          const начало = startOfWeek(месяц, { weekStartsOn: 1 })
          const дни = eachDayOfInterval({ start: начало, end: addDays(startOfDay(endOfWeek(endOfMonth(месяц), { weekStartsOn: 1 })), 0) })
          return (
            <section key={месяц.toISOString()} aria-label={format(месяц, 'LLLL yyyy', { locale: ru })}>
              <button type="button" onClick={() => onMonth(месяц)}
                className="mb-1 rounded px-1 font-headline text-base font-semibold capitalize hover:text-primary">
                {format(месяц, 'LLLL', { locale: ru })}
              </button>
              <div className="grid grid-cols-7 text-center text-xs text-muted-foreground">
                {дни.slice(0, 7).map(d => <span key={d.toISOString()} className="py-0.5">{format(d, 'EEEEEE', { locale: ru })}</span>)}
              </div>
              <div className="grid grid-cols-7 text-center">
                {дни.map(d => {
                  if (!isSameMonth(d, месяц)) return <span key={d.toISOString()} />
                  const занят = busyDays.has(format(d, 'yyyy-MM-dd'))
                  return (
                    <button key={d.toISOString()} type="button" onClick={() => onDay(d)}
                      aria-label={`${format(d, 'd MMMM', { locale: ru })}${занят ? ', есть записи' : ''}`}
                      className={cn('relative mx-auto grid size-8 place-items-center rounded-full text-xs tabular-nums hover:bg-accent',
                        isCompanyToday(d) ? 'bg-primary font-semibold text-primary-foreground hover:bg-primary/90'
                          : d.getDay() % 6 === 0 ? 'text-muted-foreground' : 'text-foreground',
                        занят && !isCompanyToday(d) && 'font-semibold')}>
                      {format(d, 'd')}
                      {занят && <span aria-hidden className={cn('absolute bottom-1 size-1 rounded-full', isCompanyToday(d) ? 'bg-primary-foreground' : 'bg-primary')} />}
                    </button>
                  )
                })}
              </div>
            </section>
          )
        })}
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
function FeedLink({ wide = false }: { wide?: boolean }) {
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
        <Button size="sm" variant="ghost" aria-label="Подписка на календарь"
          className={wide ? 'h-9 px-2 text-sm' : 'h-10 w-10 shrink-0 px-0 text-xs md:w-auto md:px-2.5'}
          title="Показывать этот календарь в телефоне или Outlook">
          <Rss className={wide ? 'mr-1.5 h-4 w-4' : 'h-4 w-4 md:mr-1'} /><span className={wide ? '' : 'hidden md:inline'}>Подписка</span>
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

/** «1 запись», «2 записи», «5 записей» — иначе счётчик читается как ошибка. */
const запись = (n: number) => {
  const две = n % 100
  if (две > 4 && две < 21) return 'записей'
  const одна = n % 10
  if (одна === 1) return 'запись'
  if (одна > 1 && одна < 5) return 'записи'
  return 'записей'
}

export default CalendarPage
