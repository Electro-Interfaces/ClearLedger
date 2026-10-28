/**
 * Встреча: собрать, изменить, ответить.
 *
 * Один диалог на все три случая — потому что человек видит один и тот же
 * предмет и должен видеть одни и те же поля. Разводить «создание» и «карточку»
 * значит завести два места, которые обязаны одинаково считать участников и
 * одинаково объяснять, что перенос обнуляет согласия.
 *
 * Что кому доступно, решает не диалог, а роль в этой встрече: организатор
 * правит и отменяет, приглашённый отвечает. Поля показываются всем — скрывать
 * от участника время и место значит прятать от него смысл приглашения.
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { addDays, parseISO } from 'date-fns'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useHref } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { EventReminder } from './EventReminder'
import {
  AlignLeft, Bell, BookmarkPlus, CalendarSearch, ChevronDown, Clock, Copy, Eye, LayoutTemplate,
  ListPlus, Loader2, MapPin, Paperclip, Repeat, Tag, Users, Video, X,
} from 'lucide-react'
import { TagPicker } from '@/components/tags/PersonalTags'
import * as tagsService from '@/services/tagsService'
import { findSlots } from '@/lib/slots'
import { GuestPanel } from '@/components/calendar/GuestPanel'
import { PollPanel } from '@/components/calendar/PollPanel'
import { PapersPanel } from '@/components/calendar/PapersPanel'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DateField, TimeField } from '@/components/ui/date-time-field'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import * as workService from '@/services/workService'
import { startEventMeeting } from '@/services/conferenceService'
import type {
  CalendarEvent, EventResponse, EventVisibility, Recurrence,
} from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { calendarDayKey, companyDateKey, companyDateTimeInput, companyDateTimeToDate, companyDateTimeToISO, companyDayStart, COMPANY_TIME_ZONE } from '@/lib/companyTime'

const local = companyDateTimeInput
const началоДня = (d: Date | null) => companyDateTimeToDate(`${companyDateKey(d ?? new Date())}T00:00`)

const ОТВЕТЫ: { key: Exclude<EventResponse, 'pending'>; label: string }[] = [
  { key: 'accepted', label: 'Буду' },
  { key: 'tentative', label: 'Может быть' },
  { key: 'declined', label: 'Не буду' },
]

const ОТВЕТ_СЛОВОМ: Record<EventResponse, string> = {
  pending: 'не ответил', accepted: 'будет', declined: 'не будет', tentative: 'может быть',
}

/** Повторения, которые люди действительно заводят. Полного RRULE тут нет и не
 *  нужно: «каждый второй вторник месяца» в делопроизводстве не встречается, а
 *  редактор такого правила стоит дороже самой серии. */
type КлючПовтора = 'none' | 'daily' | 'weekly' | 'biweekly' | 'monthly'

/** Круги встречи — тот же словарь, что у поручения: человеку незачем помнить
 *  два набора слов для одного вопроса. */
const КРУГИ: { key: EventVisibility; label: string; hint: string }[] = [
  { key: 'company', label: 'Вся компания',
    hint: 'Встреча видна в общем календаре компании' },
  { key: 'private', label: 'Только участники',
    hint: 'Остальные видят лишь «занят» — ни темы, ни места' },
  { key: 'personal', label: 'Только я',
    hint: 'Личное время: не видит никто, включая администратора' },
]

const когда = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'short', day: 'numeric', month: 'short',
  hour: '2-digit', minute: '2-digit',
  timeZone: COMPANY_TIME_ZONE,
})

const ПОВТОРЫ: { key: КлючПовтора; label: string; rule: Recurrence | null }[] = [
  { key: 'none', label: 'Не повторяется', rule: null },
  { key: 'daily', label: 'Каждый день', rule: { mode: 'daily' } },
  { key: 'weekly', label: 'Каждую неделю', rule: { mode: 'weekly' } },
  { key: 'biweekly', label: 'Раз в две недели', rule: { mode: 'weekly', interval: 2 } },
  { key: 'monthly', label: 'Каждый месяц', rule: { mode: 'monthly' } },
]

function ключПовтора(r: Recurrence | null): КлючПовтора {
  if (!r) return 'none'
  if (r.mode === 'weekly' && (r.interval ?? 1) === 2) return 'biweekly'
  return r.mode
}

/**
 * Строка карточки: значок поля слева, само поле справа — как в настольных
 * календарях. Значок заменяет подпись глазу, поэтому у группы есть имя для
 * чтения с экрана, а у каждого поля — своё.
 */
function Строка({ icon: Icon, label, children, className, id }: {
  icon: LucideIcon; label: string; children: ReactNode; className?: string; id?: string
}) {
  return (
    <div role="group" aria-label={label} id={id}
      className={cn('grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-x-3', className)}>
      <Icon aria-hidden className="mt-2.5 h-4 w-4 text-muted-foreground" />
      <div className="min-w-0 space-y-1.5">{children}</div>
    </div>
  )
}

/** Плашка участника в составе встречи: имя, роль и настройки по нажатию. */
function ПлашкаУчастника({ имя, подпись, ведущий, наВедущего, дляСведения, наСведения, убрать }: {
  имя: string; подпись?: string
  /** Есть видеовстреча — можно отметить ведущего; иначе пункта нет. */
  ведущий?: boolean; наВедущего: (v: boolean) => void
  дляСведения?: boolean; наСведения?: (v: boolean) => void
  убрать?: () => void
}) {
  const подписи = [подпись, ведущий ? 'ведущий' : null].filter(Boolean).join(' · ')
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button"
          className="inline-flex min-h-8 max-w-full items-center gap-1 rounded-full border border-border bg-card pl-2.5 pr-2 text-sm hover:bg-accent"
          aria-label={`${имя}${подписи ? `, ${подписи}` : ''}: настроить участие`}>
          <span className="truncate">{имя}</span>
          {подписи && <span className="shrink-0 text-xs text-muted-foreground">· {подписи}</span>}
          <ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-1 p-2 text-sm">
        {наСведения && (
          <div role="radiogroup" aria-label="Участие" className="grid grid-cols-2 gap-1">
            {([['Обязательно', false], ['Для сведения', true]] as const).map(([слово, v]) => (
              <button key={слово} type="button" role="radio" aria-checked={!!дляСведения === v} onClick={() => наСведения(v)}
                className={cn('min-h-8 rounded-md border px-2 text-xs',
                  !!дляСведения === v ? 'border-primary bg-primary text-primary-foreground' : 'border-border hover:bg-accent')}>
                {слово}
              </button>
            ))}
          </div>
        )}
        {ведущий !== undefined && (
          <label className="flex min-h-9 items-center gap-2 px-1"
            title="Ведущего ждут, он впускает гостей; если через 5 минут после начала его нет, первый вошедший откроет комнату сам">
            <Checkbox checked={ведущий} onCheckedChange={(v) => наВедущего(v === true)} />
            Ведущий видеовстречи
          </label>
        )}
        {!наСведения && ведущий === undefined && (
          <p className="px-1 py-1 text-xs text-muted-foreground">Организатор участвует всегда.</p>
        )}
        {убрать && (
          <button type="button" onClick={убрать}
            className="flex min-h-9 w-full items-center gap-2 rounded-md px-1 text-left text-destructive hover:bg-destructive/10">
            <X aria-hidden className="h-3.5 w-3.5" />Убрать из встречи
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}

export function EventDialog({ companyId, event: initialEvent, startAt, subjectRef, initialTitle,
  companyDay, allDay: весьДеньНовой, panel: панельЗапрошена, onDraft, onClose, onChanged }: {
  companyId: string
  /** Существующая встреча — правим её; иначе собираем новую. */
  event: CalendarEvent | null
  /** С какого времени предложить новую встречу (клик по дню). */
  startAt: Date | null
  /** Предмет, ради которого собираются (`doc:<uuid>`, `task:<uuid>`). Ссылка
   *  двусторонняя: из встречи видно предмет, из предмета — назначенные по нему
   *  обсуждения. Без неё через месяц никто не вспомнит, зачем собирались. */
  subjectRef?: string
  /** Заготовка названия: обсуждение приходит с именем своего предмета. */
  initialTitle?: string
  /** Событие компании: дата на весь день для всех, без созыва — день компании,
   *  выездная проверка, отключение площадки. Та же встреча, другая заготовка. */
  companyDay?: boolean
  /** Новая встреча на весь день — клик по ряду «весь день» в сетке. Видимость
   *  обычная (только участники), в отличие от события компании. */
  allDay?: boolean
  /** Панелью справа поверх сетки, а не окном по центру: календарь остаётся
   *  виден, и время встречи сверяют с соседними. Только на компьютере —
   *  на телефоне для панели нет места, там прежнее окно. */
  panel?: boolean
  /** Новая встреча сообщает, куда она встанет: сетка рисует её черновиком. */
  onDraft?: (draft: { start: Date; end: Date; title: string } | null) => void
  onClose: () => void
  onChanged: () => void
}) {
  const [event, setEvent] = useState(initialEvent)
  const { user } = useAuth()
  const qc = useQueryClient()
  const fieldId = useId()
  const новая = !event
  const мой = (event?.is_organizer ?? true) && event?.status !== 'cancelled'
  const canRespond = !!event && !event.is_organizer && event.my_response !== null && event.status !== 'cancelled'
  const eventHref = useHref(event ? workService.refHref('event:' + event.id)! : '/')
  const наДень = !!companyDay || !!весьДеньНовой
  const [allDay, setAllDay] = useState(event?.all_day ?? наДень)
  const [peopleSearch, setPeopleSearch] = useState('')
  const [cancelConfirm, setCancelConfirm] = useState(false)
  const [запасКонца, setЗапасКонца] = useState<string | null>(null)
  // Телефон открывает встречу простой: тема, время, место. Остальное — за
  // «Подробнее» (решение МАГа 07.09.2026).
  const phone = useIsMobile()
  const [more, setMore] = useState(false)
  /** За сколько минут до начала напомнить себе; null — не напоминать. */
  const [напомнитьЗа, setНапомнитьЗа] = useState<number | null>(null)
  // Мои теги новой встречи: id ещё нет, ставим сразу после сборки.
  const [тегиНовой, setТегиНовой] = useState<string[]>([])
  const [cancelReason, setCancelReason] = useState('')
  // «Создать видеоконференцию»: ссылка появлялась только после «Начать
  // видеовстречу» в уже собранной встрече и в приглашение не попадала
  // (РусГидро, 15.10.2026). Новой встрече номер выдаём заранее — комната
  // считается от него, и ссылка видна сразу.
  const [заранееId, setЗаранееId] = useState<string | null>(null)
  // Список сотрудников раскрыт, только пока ищут: раньше под полем висел весь
  // штат с галочками и форма уходила на два экрана (МАГ, 28.10.2026, по образцу VK).
  const [ищуЛюдей, setИщуЛюдей] = useState(false)
  const [видеоИдёт, setВидеоИдёт] = useState(false)
  useEffect(() => { setEvent(initialEvent) }, [initialEvent?.id])
  const notifyChanged = () => {
    for (const key of ['calendar', 'events', 'calendar-event', 'calendar-summary', 'calendar-busy', 'pulse-my-meetings', 'reminders']) {
      void qc.invalidateQueries({ queryKey: [key] })
    }
    onChanged()
  }
  const refreshEvent = async () => {
    if (event) {
      try { setEvent(await workService.getEvent(companyId, event.id)) }
      catch { toast.error('Не удалось обновить встречу. Откройте её ещё раз.') }
    }
    notifyChanged()
  }

  // Видеовстреча этой встречи. Комнату держит сервер: имя постоянное, поэтому
  // ссылка из приглашения и вход ведущего ведут в одно место, а вернуться в
  // свою же комнату можно и после закрытой вкладки.
  const [confBusy, setConfBusy] = useState(false)
  const войтиВВидеовстречу = async () => {
    if (confBusy || !event) return
    setConfBusy(true)
    try {
      const m = await startEventMeeting(companyId, event.id)
      // Поле формы живёт своим состоянием и обновляется только при смене
      // встречи: без этой строки карточка показывала пустую ссылку, а
      // «Сохранить» отправлял пустое поле и стирал комнату (15.10.2026).
      if (!conference.trim()) setConference(m.guest_url)
      try { await navigator.clipboard.writeText(m.guest_url) } catch { /* буфер недоступен */ }
      toast.success('Вы ведущий — ссылка для участников скопирована', { description: m.guest_url })
      await refreshEvent()
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Видеоконференции не настроены'
        : 'Не удалось открыть видеовстречу')
    } finally { setConfBusy(false) }
  }

  const создатьВидео = async () => {
    if (видеоИдёт) return
    setВидеоИдёт(true)
    try {
      if (!event) {
        const id = заранееId ?? crypto.randomUUID()
        const r = await workService.videoLink(companyId, id)
        setЗаранееId(id)
        setConference(r.url)
      } else {
        const обновлена = await workService.eventAction(companyId, event.id, { video: true })
        setEvent(обновлена)
        setConference(обновлена.conference_url ?? '')
        notifyChanged()
      }
      toast.success('Видеоконференция создана — ссылку можно скопировать')
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Видеоконференции не настроены' : 'Не удалось создать видеоконференцию')
    } finally { setВидеоИдёт(false) }
  }
  const копироватьВидео = async () => {
    try { await navigator.clipboard.writeText(conference.trim()); toast.success('Ссылка на видеовстречу скопирована') }
    catch { toast.error('Не удалось скопировать ссылку. Проверьте разрешение браузера.') }
  }

  const [title, setTitle] = useState(event?.title ?? initialTitle ?? '')
  const [description, setDescription] = useState(event?.description ?? '')
  const [starts, setStarts] = useState(() => local(
    event ? event.starts_at : наДень ? началоДня(startAt) : (startAt ?? new Date())))
  const [ends, setEnds] = useState(() => local(
    event ? event.ends_at
      : наДень ? companyDayStart(addDays(parseISO(companyDateKey(началоДня(startAt))), 1))
        : new Date((startAt ?? new Date()).getTime() + 60 * 60_000)))
  const [location, setLocation] = useState(event?.location ?? '')
  const [conference, setConference] = useState(event?.conference_url ?? '')
  const [attendees, setAttendees] = useState<string[]>(
    () => (event?.attendees ?? []).map((a) => a.user_id))
  // Ведущие видеоконференции. По умолчанию — организатор; он же может
  // передать роль другому участнику, например секретарь — руководителю
  // (МАГ, 15.10.2026). Ведущими бывают только участники.
  const организаторId = event?.organizer_id ?? user?.id ?? ''
  const [hosts, setHosts] = useState<string[]>(() => {
    const отмечены = (event?.attendees ?? []).filter((a) => a.is_host).map((a) => a.user_id)
    return отмечены.length ? отмечены : (event?.organizer_id ?? user?.id ? [event?.organizer_id ?? user!.id] : [])
  })
  const организаторИмя = event?.attendees.find((a) => a.user_id === event.organizer_id)?.name
    ?? (event ? 'Организатор' : `${user?.name ?? 'Вы'} (вы)`)
  const ведущий = (id: string) => hosts.includes(id)
  const отметитьВедущего = (id: string, on: boolean) =>
    setHosts((было) => (on ? [...было.filter((x) => x !== id), id] : было.filter((x) => x !== id)))
  // Кто позван «для сведения». Его занятость не блокирует подбор времени:
  // иначе приглашённый руководитель закрывает все слоты, хотя встреча может
  // пройти без него.
  const [optional, setOptional] = useState<string[]>(
    () => (event?.attendees ?? []).filter((a) => a.role === 'optional')
      .map((a) => a.user_id))
  // Круг встречи — тот же словарь, что у поручения. Без выбора всё уходило в
  // `company`, и встреча, которую человек считал разговором пятерых,
  // публиковалась всей компании.
  // Новая встреча по умолчанию видна только участникам: «вся компания» для
  // разговора пятерых — странное начало (МАГ, 15.10.2026). Событие компании
  // («весь день компании») — для всех, ради этого его и заводят.
  const [visibility, setVisibility] = useState<EventVisibility>(
    () => event?.visibility ?? (companyDay ? 'company' : 'private'))

  // Смена встречи в родителе (открыли другую) — перезаполняем поля.
  useEffect(() => {
    if (!event) return
    setTitle(event.title)
    setDescription(event.description ?? '')
    setStarts(local(event.starts_at))
    setEnds(local(event.ends_at))
    setLocation(event.location ?? '')
    setConference(event.conference_url ?? '')
    setAttendees(event.attendees.map((a) => a.user_id))
    setOptional(event.attendees.filter((a) => a.role === 'optional')
      .map((a) => a.user_id))
    setVisibility(event.visibility ?? 'company')
    setAllDay(event.all_day)
    setПовтор(ключПовтора(event.recurrence ?? null))
    setUntil(event.recurrence_until ?? '')
  }, [event])

  const шаблоны = useQuery({
    queryKey: ['meeting-templates', companyId],
    queryFn: () => workService.meetingTemplates(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })
  const сохранитьЗаготовку = useMutation({
    mutationFn: (имя: string) => workService.saveMeetingTemplate(companyId, {
      name: имя, title: title.trim(),
      description: description.trim() || undefined,
      durationMinutes: Math.max(5, Math.round(
        (companyDateTimeToDate(ends).getTime() - companyDateTimeToDate(starts).getTime()) / 60_000)),
      location: location.trim() || undefined,
      attendeeIds: attendees,
      recurrence: ПОВТОРЫ.find((r) => r.key === повтор)?.rule ?? null,
    }),
    onSuccess: () => { toast.success('Заготовка сохранена'); void шаблоны.refetch() },
    onError: (e: Error) => toast.error(e.message || 'Не сохранилось'),
  })

  const [предлагаю, setПредлагаю] = useState(false)
  const предложения = (event?.attendees ?? []).filter((a) => a.proposed_starts_at)
  const предложить = useMutation({
    mutationFn: () => workService.eventAction(companyId, event!.id, {
      proposeStartsAt: companyDateTimeToISO(starts),
      proposeEndsAt: companyDateTimeToISO(ends),
    }),
    onSuccess: () => {
      setПредлагаю(false)
      void refreshEvent()
      toast.success('Предложение отправлено организатору')
      notifyChanged()
    },
    onError: (e: Error) => toast.error(e.message || 'Не отправилось'),
  })

  const [длительность, setДлительность] = useState(60)
  const [ищем, setИщем] = useState(false)

  // Окно поиска — две недели вперёд: дальше подбирают по договорённости, а не
  // по сетке, и тащить месяц занятости ради этого незачем.
  const searchDate = starts.slice(0, 10)
  const [окноОт, окноДо] = useMemo(() => {
    const requested = companyDateTimeToDate(searchDate + 'T00:00')
    const from = new Date(Math.max(Number.isFinite(requested.getTime()) ? requested.getTime() : 0, Date.now()))
    const to = companyDayStart(addDays(parseISO(companyDateKey(from)), 14))
    return [from.toISOString(), to.toISOString()]
  }, [searchDate])
  const attendeesKey = attendees.slice().sort().join(',')
  const busyQ = useQuery({
    queryKey: ['calendar-busy', companyId, attendeesKey, окноОт, окноДо, event?.id],
    queryFn: () => workService.calendarBusy(companyId, окноОт, окноДо, attendees, event?.id),
    enabled: false,
  })
  useEffect(() => { setИщем(false) }, [attendeesKey, searchDate])
  const кандидаты = useMemo(() => {
    const люди = busyQ.data?.people ?? []
    if (!люди.length || busyQ.isError || busyQ.data?.truncated) return []
    return findSlots({
      people: люди,
      // Необязательные в отбор не входят — иначе встречу на пятерых не собрать
      // никогда; их занятость показывается числом рядом с кандидатом.
      requiredIds: люди.map((p) => p.user_id).filter((id) => !optional.includes(id)),
      from: new Date(окноОт), to: new Date(окноДо), minutes: длительность,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busyQ.data, busyQ.isError, длительность, optional, окноОт, окноДо])

  const [повтор, setПовтор] = useState<КлючПовтора>(
    () => ключПовтора(event?.recurrence ?? null))
  const [until, setUntil] = useState(event?.recurrence_until ?? '')
  const [итог, setИтог] = useState('')
  const поручить = useMutation({
    mutationFn: () => tasksService.createTask({
      companyId, title: итог.trim().slice(0, 300),
      subjectRef: `event:${event!.id}`,
    }),
    onSuccess: () => {
      setИтог('')
      void qc.invalidateQueries({ queryKey: ['work-mine'] })
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      toast.success('Поручение заведено — оно в «Разборе», пока не назначен исполнитель')
      notifyChanged()
    },
    onError: (e: Error) => toast.error(e.message || 'Поручение не завелось'),
  })

  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })

  const сохранить = useMutation({
    mutationFn: async () => {
      const начало = companyDateTimeToISO(starts)
      const конец = companyDateTimeToISO(ends)
      if (новая) {
        const created = await workService.createEvent(companyId, {
          title: title.trim(), startsAt: начало, endsAt: конец,
          tz: COMPANY_TIME_ZONE,
          description: description.trim() || undefined,
          location: location.trim() || undefined,
          conferenceUrl: conference.trim() || undefined,
          attendeeIds: attendees,
          optionalIds: visibility === 'personal' ? [] : optional,
          allDay,
          visibility,
          subjectRef: subjectRef || undefined,
          recurrence: ПОВТОРЫ.find((r) => r.key === повтор)?.rule ?? null,
          recurrenceUntil: повтор === 'none' ? null : (until || null),
          id: заранееId ?? undefined,
          hostIds: hosts.filter(id => id === организаторId || attendees.includes(id)),
        })
        // Напоминание себе — сразу, тем же нажатием: иначе человек собирает
        // встречу, закрывает окно и открывает его заново, чтобы «напомнить».
        if (напомнитьЗа !== null) {
          const at = new Date(new Date(начало).getTime() - напомнитьЗа * 60_000)
          if (at > new Date()) {
            await workService.createReminder(companyId, {
              targetRef: `event:${created.id}`, remindAt: at.toISOString(), note: title.trim(),
            }).catch(() => toast.error('Встреча собрана, а напоминание не поставилось'))
          }
        }
        if (тегиНовой.length) {
          await tagsService.assignTags(companyId, `event:${created.id}`, тегиНовой)
            .catch(() => toast.error('Встреча собрана, а теги не поставились'))
          void qc.invalidateQueries({ queryKey: ['personal-tags', companyId] })
        }
        return created
      }
      return workService.eventAction(companyId, event!.id, {
        title: title.trim(), startsAt: начало, endsAt: конец,
        tz: COMPANY_TIME_ZONE,
        description: description.trim(), location: location.trim(),
        conferenceUrl: conference.trim(), attendeeIds: attendees,
        hostIds: hosts.filter(id => id === организаторId || attendees.includes(id)),
        optionalIds: optional, visibility, allDay,
        // Серия правится только у головы: у порождённой встречи `recurrence`
        // пуст, и слать пустой объект значило бы каждый раз снимать повторение
        // с той, у которой его и не было.
        ...(event!.series_id ? {} : {
          recurrence: ПОВТОРЫ.find((r) => r.key === повтор)?.rule ?? {},
          recurrenceUntil: повтор === 'none' ? null : (until || null),
        }),
      })
    },
    onSuccess: () => { toast.success(новая ? 'Встреча собрана' : 'Сохранено'); notifyChanged(); onClose() },
    onError: (e: Error) => toast.error(e.message || 'Не сохранилось'),
  })

  const ответить = useMutation({
    mutationFn: (response: Exclude<EventResponse, 'pending'>) =>
      workService.eventAction(companyId, event!.id, { response }),
    onSuccess: (saved) => { setEvent(saved); toast.success('Ответ записан'); notifyChanged() },
    onError: (e: Error) => toast.error(e.message || 'Ответ не записался'),
  })

  // Встречу с участниками отменяют только с причиной: она уже стоит в чужих
  // календарях, и зачёркнутая строка без объяснения оставляет вопрос «почему»
  // тому, кто спросить уже не может — правка отменённой встречи запрещена.
  // Признак считается по составу самой встречи, а не по черновику формы:
  // снятый в форме участник ещё не перестал её ждать.
  // Внешние гости тоже получают письмо об отмене — тот же запрос, что у панели
  // гостей, общий кэш (QA 27.10.2026: при госте писалось «писем никто не получит»).
  const гостиQ = useQuery({
    queryKey: ['event-guests', companyId, event?.id],
    queryFn: () => workService.eventGuests(companyId, event!.id),
    enabled: !!event?.id && cancelConfirm,
  })
  const причинаОбязательна = (event?.attendees ?? [])
    .some((a) => a.user_id !== event?.organizer_id) || (гостиQ.data?.guests ?? []).length > 0

  const отменить = useMutation({
    mutationFn: (reason: string) =>
      workService.eventAction(companyId, event!.id, { cancel: true, cancelReason: reason }),
    onSuccess: () => { toast.success('Встреча отменена'); notifyChanged(); onClose() },
    onError: (e: Error) => toast.error(e.message || 'Не отменилась'),
  })

  const люди = (peopleQ.data?.people ?? []).filter(person => person.id !== (event?.organizer_id ?? user?.id)
    && (!peopleSearch.trim() || person.name.toLocaleLowerCase('ru').includes(peopleSearch.trim().toLocaleLowerCase('ru'))))
  const имяЧеловека = (id: string) => peopleQ.data?.people.find((p) => p.id === id)?.name
    ?? event?.attendees.find((x) => x.user_id === id)?.name ?? 'Сотрудник'
  const startMs = companyDateTimeToDate(starts).getTime()
  const endMs = companyDateTimeToDate(ends).getTime()
  let formError = !Number.isFinite(startMs) || !Number.isFinite(endMs) ? 'Укажите начало и конец встречи.'
    : endMs <= startMs ? 'Конец встречи должен быть позже начала.'
      : повтор !== 'none' && until && until < starts.slice(0, 10) ? 'Повторение не может закончиться раньше первой встречи.' : ''
  if (!formError && conference.trim()) {
    try { const url = new URL(conference.trim()); if (!['https:', 'http:'].includes(url.protocol)) formError = 'Укажите ссылку с https:// или http://.' }
    catch { formError = 'Укажите полную ссылку на видеовстречу, начиная с https://.' }
  }
  /**
   * Наложение видно сразу, а не после «Подобрать»: кто из состава (и сам
   * организатор) уже занят в выбранный час. Та же проекция занятости, что у
   * подбора, — только имена, ни названий, ни мест чужих встреч (docs/TRACK.md).
   */
  const накладкаQ = useQuery({
    queryKey: ['calendar-busy', companyId, 'overlap', attendeesKey, startMs, endMs, event?.id],
    queryFn: () => workService.calendarBusy(companyId, new Date(startMs).toISOString(),
      new Date(endMs).toISOString(), attendees, event?.id),
    // Без приглашённых сервер проверяет одного организатора: встреча поверх
    // своей же — самый частый случай наложения (QA 27.10.2026).
    enabled: !!companyId && мой && !allDay && !formError
      && event?.status !== 'poll' && endMs > Date.now(),
    staleTime: 30_000,
  })
  // Событие на весь день время не занимает — та же договорённость, что у подбора (lib/slots).
  const заняты = (накладкаQ.data?.people ?? []).filter((p) => p.busy.some((b) => !b.all_day &&
    new Date(b.starts_at).getTime() < endMs && new Date(b.ends_at).getTime() > startMs))
    .map((p) => p.user_id === user?.id ? 'вы' : p.name)
  const changeStart = (value: string) => {
    const next = allDay && value ? value + 'T00:00' : value
    const delta = companyDateTimeToDate(next).getTime() - startMs
    setStarts(next)
    if (Number.isFinite(delta) && Number.isFinite(endMs)) setEnds(local(new Date(endMs + delta)))
  }
  const toggleAllDay = (checked: boolean) => {
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return
    setAllDay(checked)
    if (checked) {
      const startDate = starts.slice(0, 10)
      const endDate = ends.slice(0, 10)
      const endsAtMidnight = ends.slice(11, 16) === '00:00'
      const lastDay = endsAtMidnight ? parseISO(endDate) : addDays(parseISO(endDate), 1)
      setStarts(`${startDate}T00:00`)
      // Снял и тут же вернул «Весь день» — многодневное событие не сжимается
      // до одного дня (QA 27.10.2026).
      setEnds(запасКонца && запасКонца > `${startDate}T00:00` ? запасКонца : `${calendarDayKey(lastDay)}T00:00`)
    } else {
      setЗапасКонца(ends)
      const start = companyDateTimeToDate(`${starts.slice(0, 10)}T10:00`)
      setStarts(`${starts.slice(0, 10)}T10:00`)
      setEnds(local(new Date(start.getTime() + 60 * 60_000)))
    }
  }
  const endDate = Number.isFinite(endMs) ? (ends.slice(11, 16) === '00:00'
    ? calendarDayKey(addDays(parseISO(ends.slice(0, 10)), -1)) : ends.slice(0, 10)) : ''
  const subjectHref = event?.subject_ref ? workService.refHref(event.subject_ref) : null
  const время_поехало = !новая && (
    local(event!.starts_at) !== starts || local(event!.ends_at) !== ends)

  // Панель только на компьютере: на телефоне ей нет места рядом с сеткой.
  const panel = !!панельЗапрошена && !phone
  const полно = !phone || more
  const панельRef = useRef<HTMLElement>(null)
  // Escape без фокуса в панели: сразу после открытия из меню и после выбора окна
  // в «Подобрать» фокус оставался на странице, и клавиша ничего не делала
  // (QA 27.10.2026). Фокус во всплывающем поле даты — не наш случай, его
  // закрывает само поле.
  const закрыть = useRef(onClose)
  useEffect(() => { закрыть.current = onClose })
  useEffect(() => {
    if (!panel) return
    const onKey = (e: KeyboardEvent) => {
      // Фокус вне панели (страница или кнопка «Новое событие», куда его вернуло
      // меню), но не в другом окне, меню или всплывающем поле: те закрываются сами.
      const цель = e.target as Element | null
      if (e.key === 'Escape' && !e.defaultPrevented && !панельRef.current?.contains(цель)
        && !цель?.closest?.('[role="dialog"],[role="menu"],[role="listbox"],[data-radix-popper-content-wrapper]')) закрыть.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [panel])
  const подборId = fieldId + '-find'
  // Несколько дней — редкость: поле даты окончания показываем, когда оно нужно,
  // а не всегда (как у настольных календарей: «26 окт. 17:00 — 17:30»).
  const [доДругогоДня, setДоДругогоДня] = useState(false)
  const разныеДни = !allDay && starts.slice(0, 10) !== ends.slice(0, 10)
  const датаОкончания = allDay || разныеДни || доДругогоДня
  // День окончания человек выбрал сам (поле даты, «До другого дня», встреча уже
  // на несколько дней) — время окончания его не трогает.
  const [датаКонцаВручную, setДатаКонцаВручную] = useState(() => !новая && разныеДни)
  /**
   * Время окончания ложится на день начала, если так конец позже начала; иначе —
   * на следующий, но только для встречи через полночь не длиннее 12 часов.
   * Раньше время писалось в дату, которую сам сдвинул перенос начала: «23:00» →
   * конец 00:00 завтра, затем «23:30» давало встречу на 24,5 часа без
   * предупреждения (QA 27.10.2026).
   */
  const changeEndTime = (t: string) => {
    if (датаКонцаВручную || доДругогоДня) { setEnds(ends.slice(0, 10) + 'T' + t); return }
    const деньНачала = starts.slice(0, 10)
    const тотЖе = `${деньНачала}T${t}`
    const назавтра = `${calendarDayKey(addDays(parseISO(деньНачала), 1))}T${t}`
    const черезПолночь = companyDateTimeToDate(назавтра).getTime() - startMs
    setEnds(companyDateTimeToDate(тотЖе).getTime() > startMs || !(черезПолночь <= 12 * 3_600_000) ? тотЖе : назавтра)
  }

  // Черновик новой встречи — в сетку календаря, пока его собирают.
  useEffect(() => {
    if (!новая || !onDraft) return
    if (Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs && !allDay) {
      onDraft({ start: new Date(startMs), end: new Date(endMs), title })
    } else onDraft(null)
  }, [новая, onDraft, startMs, endMs, title, allDay])
  useEffect(() => () => onDraft?.(null), [onDraft])

  const заголовок = новая ? (companyDay ? 'Событие компании' : 'Новая встреча') : мой ? 'Встреча' : title

  const шаблоныБлок = новая && (шаблоны.data?.templates.length ?? 0) > 0 && полно && (
    /* Заготовка — набор полей, который надоело набирать заново. Повторение здесь
       тоже поле: «планёрка по понедельникам» заводится одним нажатием. */
    <Строка icon={LayoutTemplate} label="Заготовки">
      <div className="flex flex-wrap items-center gap-1.5 pt-1.5">
        {(шаблоны.data?.templates ?? []).map((t) => (
          <Button key={t.id} type="button" size="xs" variant="outline"
            onClick={() => {
              setTitle(t.title)
              setDescription(t.description ?? '')
              setLocation(t.location ?? '')
              setAttendees(t.attendee_ids)
              setДлительность(t.duration_minutes)
              setПовтор(ключПовтора(t.recurrence))
              const н = companyDateTimeToDate(starts)
              setEnds(local(new Date(н.getTime() + t.duration_minutes * 60_000)))
            }}>
            {t.name}
          </Button>
        ))}
      </div>
    </Строка>
  )

  /* 🔴 Дата и время — РАЗДЕЛЬНО и с ручным вводом (претензия МАГа 16.09.2026):
     в каждом поле печатают ИЛИ выбирают — дату сеткой месяца, время списком. */
  const времяТекстом = (() => {
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return ''
    const с = new Date(startMs), по = new Date(endMs)
    const день = new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric', timeZone: COMPANY_TIME_ZONE })
    const час = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: COMPANY_TIME_ZONE })
    if (allDay) {
      const последний = new Date(endMs - 1)
      return companyDateKey(с) === companyDateKey(последний) ? `${день.format(с)}, весь день`
        : `${день.format(с)} — ${день.format(последний)}`
    }
    return companyDateKey(с) === companyDateKey(по) ? `${день.format(с)}, ${час.format(с)} — ${час.format(по)}`
      : `${день.format(с)}, ${час.format(с)} — ${день.format(по)}, ${час.format(по)}`
  })()
  /* Участник встречу не правит: поля ему не нужны, нужен ответ «когда, где,
     о чём» текстом. Пустое у него не показывается — серая заготовка «Переговорная,
     адрес» в закрытом поле читалась как недоделка. */
  const времяБлок = !мой ? (
    <Строка icon={Clock} label="Когда">
      <p className="pt-2 text-sm first-letter:uppercase">{времяТекстом}</p>
    </Строка>
  ) : (
    <Строка icon={Clock} label="Когда">
      <div className="flex flex-wrap items-center gap-2">
        <DateField id={fieldId + '-start'} className="w-40" disabled={!мой}
          aria-label={allDay ? 'Первый день' : 'Дата начала'}
          value={starts.slice(0, 10)}
          onChange={(d) => changeStart(allDay ? d : d + 'T' + starts.slice(11, 16))} />
        {!allDay && (
          <TimeField className="w-24" disabled={!мой} aria-label="Время начала"
            value={starts.slice(11, 16)}
            onChange={(t) => changeStart(starts.slice(0, 10) + 'T' + t)} />
        )}
        <span aria-hidden className="text-muted-foreground">—</span>
        {датаОкончания && (
          <DateField id={fieldId + '-end'} className="w-40" disabled={!мой}
            aria-label={allDay ? 'Последний день' : 'Дата окончания'}
            value={allDay ? endDate : ends.slice(0, 10)}
            onChange={(d) => {
              if (!allDay) { setДатаКонцаВручную(true); setEnds(d + 'T' + ends.slice(11, 16)); return }
              // «Весь день» хранит конец следующим днём: человек называет последний
              // день встречи, а система держит границу интервала.
              setEnds(`${calendarDayKey(addDays(parseISO(d), 1))}T00:00`)
            }} />
        )}
        {!allDay && (
          /* Список конца — от начала и с длительностью («11:30 (1,5 ч)»): одно
             нажатие вместо кнопок 30/60/90 (по образцу VK, 28.10.2026). */
          <TimeField className="w-24" disabled={!мой} aria-label="Время окончания"
            value={ends.slice(11, 16)} from={датаОкончания ? undefined : starts.slice(11, 16)}
            onChange={changeEndTime} />
        )}
        <label className="flex min-h-9 items-center gap-2 text-sm">
          <Checkbox checked={allDay} disabled={!мой} onCheckedChange={(v) => toggleAllDay(v === true)} />
          Весь день
        </label>
        {!allDay && мой && !датаОкончания && (
          <button type="button" onClick={() => setДоДругогоДня(true)}
            className="text-xs text-primary underline-offset-2 hover:underline">
            До другого дня
          </button>
        )}
      </div>
      {/* Пояс называем тому, у кого он другой: москвичу строка ничего не говорит. */}
      {полно && Intl.DateTimeFormat().resolvedOptions().timeZone !== COMPANY_TIME_ZONE && <p className="text-xs text-muted-foreground">
        Время указано по Москве (часовой пояс компании).
      </p>}
      {formError && <p role="alert" className="text-sm text-destructive">{formError}</p>}
      {!formError && заняты.length > 0 && (
        <p role="status" className="rounded-md border border-amber-500/40 bg-amber-500/5 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400">
          В это время {заняты.length === 1 && заняты[0] === 'вы' ? 'у вас уже есть встреча' : `заняты: ${заняты.join(', ')}`}.
          {attendees.length > 1 && ' Свободное время подскажет «Подобрать».'}
        </p>
      )}
      {время_поехало && event!.attendees.length > 1 && (
        <p className="rounded-md border border-amber-500/40 bg-amber-500/5 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400">
          Время меняется — согласия участников сбросятся: «буду в 10» не значит «буду в 18».
        </p>
      )}
    </Строка>
  )

  /* Повторение задаётся на голове серии. Порождённая встреча его не показывает:
     предлагать «повторять» тому, что уже есть повторение, значит завести серию
     внутри серии. */
  const повторБлок = полно && (мой && !event?.series_id ? (
    <Строка icon={Repeat} label="Повторение">
      <div className="flex flex-wrap items-center gap-2">
        <select id={fieldId + '-repeat'} aria-label="Повторять" value={повтор}
          onChange={(e) => setПовтор(e.target.value as КлючПовтора)}
          className="h-9 rounded-md border border-input bg-card px-2.5 text-sm">
          {ПОВТОРЫ.map((r) => (
            <option key={r.key} value={r.key}>{r.label}</option>
          ))}
        </select>
        {повтор !== 'none' && (
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            до
            <Input id={fieldId + '-until'} type="date" value={until} className="h-9 w-[160px]"
              aria-label="Повторять до" onChange={(e) => setUntil(e.target.value)} />
          </label>
        )}
      </div>
      {повтор !== 'none' && !until && <p className="text-xs text-muted-foreground">Без даты — пока не выключите</p>}
      {event?.recurrence && <p className="text-xs text-muted-foreground">Уже назначенные повторы редактируются отдельно. Изменение правила действует на новые повторения.</p>}
    </Строка>
  ) : event?.series_id ? (
    <Строка icon={Repeat} label="Повторение">
      <p className="pt-2 text-sm text-muted-foreground">Встреча из серии. Правки и отмена коснутся только её.</p>
    </Строка>
  ) : null)

  const местоБлок = !мой ? (location.trim() ? (
    <Строка icon={MapPin} label="Место"><p className="break-words pt-2 text-sm">{location}</p></Строка>
  ) : null) : (
    <Строка icon={MapPin} label="Место">
      <Input id={fieldId + '-location'} aria-label="Место" className="text-base sm:text-sm" value={location}
        onChange={(e) => setLocation(e.target.value)} disabled={!мой} placeholder="Переговорная, адрес" />
    </Строка>
  )

  /* Видеовстреча — не «подробность»: на телефоне её тоже собирают сразу
     (15.10.2026). Своя комната создаётся кнопкой, чужая ссылка — полем. */
  const видеоБлок = !мой && !conference.trim() ? null : (
    <Строка icon={Video} label="Видеовстреча">
      {мой && !conference.trim() ? (
        /* Одна строка: своя ссылка полем, своя комната — «Создать» справа (как в VK). */
        <div className="flex items-center gap-2">
          <Input id={fieldId + '-conference'} aria-label="Ссылка на видеовстречу" className="min-w-0 flex-1 text-base sm:text-sm"
            value={conference} onChange={(e) => setConference(e.target.value)} placeholder="Ссылка на видеовстречу (Zoom, Teams…)" />
          <Button type="button" variant="ghost" size="sm" className="shrink-0 text-primary" disabled={видеоИдёт} onClick={создатьВидео}
            title="Создать видеоконференцию пространства">
            {видеоИдёт && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}Создать
          </Button>
        </div>
      ) : (
        <div className="flex gap-2">
          <Input id={fieldId + '-conference'} aria-label="Ссылка на видеовстречу" className="min-w-0 flex-1 text-base sm:text-sm" value={conference}
            onChange={(e) => setConference(e.target.value)} disabled={!мой} placeholder="https://…" />
          {conference.trim() && (
            <Button type="button" variant="outline" size="icon" className="shrink-0"
              title="Копировать ссылку" aria-label="Копировать ссылку на видеовстречу" onClick={копироватьВидео}>
              <Copy className="h-4 w-4" />
            </Button>
          )}
        </div>
      )}
    </Строка>
  )

  const описаниеБлок = полно && (!мой ? (description.trim() ? (
    <Строка icon={AlignLeft} label="Описание"><p className="whitespace-pre-wrap break-words pt-2 text-sm">{description}</p></Строка>
  ) : null) : (
    <Строка icon={AlignLeft} label="Описание">
      {/* Пустое описание — одна строка; растёт, когда пишут. */}
      <Textarea id={fieldId + '-description'} aria-label="Описание" className="min-h-9 resize-y py-1.5 text-base sm:text-sm"
        value={description} rows={description.trim() ? 3 : 1} disabled={!мой}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Описание: что обсуждаем, что принести" />
    </Строка>
  ))

  /* Материалы — сразу под описанием: это та же повестка, только бумагами. */
  const материалыБлок = полно && !новая && (
    <Строка icon={Paperclip} label="Материалы">
      <PapersPanel companyId={companyId} eventId={event!.id} readOnly={event!.status === 'cancelled'} />
    </Строка>
  )

  /* Мои теги — личная пометка встречи: цвет в календаре, поиск и отбор. Ставит
     любой, кто видит встречу, и видит только он сам (МАГ, 28.10.2026). */
  const тегиБлок = (
    <Строка icon={Tag} label="Мои теги">
      {новая
        ? <TagPicker companyId={companyId} value={тегиНовой} onChange={setТегиНовой} />
        : <TagPicker companyId={companyId} targetRef={`event:${event!.id}`} />}
    </Строка>
  )

  /* За сколько напомнить — при сборе встречи (вопрос МАГа 07.09.2026). У
     собранной встречи тем же занимается блок напоминания ниже. */
  const напоминаниеБлок = новая && мой && полно ? (
    <Строка icon={Bell} label="Напоминание">
      <select aria-label="Напомнить" value={напомнитьЗа ?? ''}
        onChange={(e) => setНапомнитьЗа(e.target.value === '' ? null : Number(e.target.value))}
        className="h-9 rounded-md border border-input bg-card px-2.5 text-sm">
        <option value="">Не напоминать</option>
        <option value="0">В момент начала</option>
        <option value="5">За 5 минут</option>
        <option value="15">За 15 минут</option>
        <option value="30">За 30 минут</option>
        <option value="60">За час</option>
        <option value="1440">За день</option>
      </select>
    </Строка>
  ) : !новая && event!.status !== 'cancelled' && полно ? (
    <Строка icon={Bell} label="Напоминание"><EventReminder companyId={companyId} event={event!} /></Строка>
  ) : null

  /* Опрос времени — про «когда», а не про «кто». */
  const опросБлок = !новая && (мой || canRespond) && event!.status !== 'cancelled' && (
    <PollPanel companyId={companyId} eventId={event!.id}
      isOrganizer={мой} durationMinutes={длительность}
      onChanged={() => void refreshEvent()} />
  )

  const подборБлок = мой && attendees.length > 0 && (
    <div id={подборId} className="space-y-1.5 rounded-lg border border-border p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium">Свободное время участников</span>
        <select aria-label="Длительность" value={длительность}
          onChange={(e) => setДлительность(Number(e.target.value))}
          className="h-8 rounded-md border border-input bg-card px-1.5 text-xs">
          {[30, 60, 90, 120].map((m) => (
            <option key={m} value={m}>{m} мин</option>
          ))}
        </select>
        <Button size="xs" variant="outline" disabled={busyQ.isFetching}
          onClick={() => { setИщем(true); void busyQ.refetch() }}>
          {busyQ.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Подобрать'}
        </Button>
      </div>
      {ищем && !busyQ.isFetching && (
        busyQ.isError ? <p role="alert" className="text-sm text-destructive">Не удалось проверить занятость. Повторите подбор.</p>
        : busyQ.data?.truncated ? <p role="alert" className="text-sm text-muted-foreground">Данных о занятости слишком много. Сократите состав: свободное время пока не подтверждено.</p>
        : кандидаты.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Общего окна на две недели вперёд нет. Уберите кого-то из состава или соберите короче.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {кандидаты.slice(0, 12).map((c) => (
              <button key={c.at} type="button"
                onClick={() => {
                  const н = new Date(c.at)
                  setStarts(local(н))
                  setEnds(local(new Date(н.getTime() + длительность * 60_000)))
                  setИщем(false)
                }}
                title={c.busyOptional.length ? `Заняты: ${c.busyOptional.join(', ')}` : 'Все свободны'}
                className={cn('rounded-md border px-2 py-1 text-xs hover:bg-accent',
                  c.busyOptional.length
                    ? 'border-amber-500/50 text-amber-700 dark:text-amber-400'
                    : 'border-border')}>
                {когда.format(new Date(c.at))}
              </button>
            ))}
          </div>
        )
      )}
    </div>
  )

  const кругБлок = полно && (!мой ? (
    <Строка icon={Eye} label="Кто видит встречу">
      <p className="pt-2 text-sm">{КРУГИ.find((к) => к.key === visibility)?.label}<span className="text-muted-foreground"> · {КРУГИ.find((к) => к.key === visibility)?.hint}</span></p>
    </Строка>
  ) : (
    <Строка icon={Eye} label="Кто видит встречу">
      <div className="flex flex-wrap gap-1.5 pt-1">
        {КРУГИ.map((к) => (
          <button key={к.key} type="button" disabled={!мой} aria-pressed={visibility === к.key}
            onClick={() => setVisibility(к.key)}
            title={к.hint}
            className={cn('rounded-full border px-2.5 py-1 text-xs transition-colors',
              visibility === к.key
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border text-muted-foreground hover:bg-accent',
              !мой && 'opacity-60')}>
            {к.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{КРУГИ.find((к) => к.key === visibility)?.hint}</p>
    </Строка>
  ))

  const участникиБлок = полно && (
    <Строка icon={Users} label="Участники">
      {мой && visibility === 'personal' ? <p className="pt-2 text-sm text-muted-foreground">После сохранения останется только организатор. Приглашённые участники будут убраны.</p>
        : мой ? <>
          {/* Состав плашками, как в VK: организатор первым, у каждого позванного
              свои настройки (обязательно или для сведения, ведущий) и «убрать». */}
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <ПлашкаУчастника имя={организаторИмя} подпись="организатор"
              ведущий={conference.trim() ? ведущий(организаторId) : undefined}
              наВедущего={(v) => отметитьВедущего(организаторId, v)} />
            {attendees.filter((id) => id !== организаторId).map((id) => (
              <ПлашкаУчастника key={id} имя={имяЧеловека(id)}
                подпись={optional.includes(id) ? 'для сведения' : undefined}
                ведущий={conference.trim() ? ведущий(id) : undefined}
                наВедущего={(v) => отметитьВедущего(id, v)}
                дляСведения={optional.includes(id)}
                наСведения={(v) => setOptional((c) => v ? [...c.filter((x) => x !== id), id] : c.filter((x) => x !== id))}
                убрать={() => {
                  setAttendees((c) => c.filter((x) => x !== id))
                  setOptional((c) => c.filter((x) => x !== id))
                  отметитьВедущего(id, false)
                }} />
            ))}
          </div>
          <div className="relative">
            <Input aria-label="Найти участника" placeholder="Добавить участников" value={peopleSearch}
              onChange={(e) => { setPeopleSearch(e.target.value); setИщуЛюдей(true) }}
              onFocus={() => setИщуЛюдей(true)}
              onBlur={() => setTimeout(() => setИщуЛюдей(false), 150)}
              onKeyDown={(e) => { if (e.key === 'Escape' && ищуЛюдей) { e.stopPropagation(); setИщуЛюдей(false) } }}
              aria-expanded={ищуЛюдей} aria-controls={fieldId + '-people'} role="combobox"
              className="text-base sm:text-sm" />
            {ищуЛюдей && (
              <div id={fieldId + '-people'} role="listbox" aria-label="Сотрудники"
                className="absolute inset-x-0 top-full z-40 mt-1 max-h-56 overflow-y-auto rounded-lg border border-border bg-popover p-1"
                style={{ boxShadow: 'var(--shadow-medium)' }}>
                {peopleQ.isLoading && <p role="status" className="px-2 py-1.5 text-sm">Загружаются сотрудники…</p>}
                {peopleQ.isError && <p role="alert" className="px-2 py-1.5 text-sm text-destructive">Не удалось загрузить сотрудников. <button type="button" className="underline" onMouseDown={(e) => e.preventDefault()} onClick={() => void peopleQ.refetch()}>Повторить</button></p>}
                {!peopleQ.isLoading && !peopleQ.isError && !люди.some((p) => !attendees.includes(p.id)) && (
                  <p className="px-2 py-1.5 text-sm text-muted-foreground">{peopleSearch.trim() ? 'Никого не нашли' : 'Все уже позваны'}</p>
                )}
                {люди.filter((p) => !attendees.includes(p.id)).slice(0, 60).map((person) => (
                  <button key={person.id} type="button" role="option" aria-selected={false}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => { setAttendees((c) => [...c, person.id]); setPeopleSearch('') }}
                    className="flex min-h-9 w-full items-center rounded-md px-2 text-left text-sm hover:bg-accent">
                    {person.name}
                  </button>
                ))}
              </div>
            )}
          </div>
          {conference.trim() && !hosts.some(id => id === организаторId || attendees.includes(id)) && (
            <p className="text-xs text-amber-700 dark:text-amber-400">Ведущий не выбран — им будет организатор.</p>
          )}
          {подборБлок}
        </> : <div className="space-y-1 pt-2 text-sm text-muted-foreground">{event!.attendees.map(attendee => <p key={attendee.user_id}>{attendee.name || 'Участник'} · {ОТВЕТ_СЛОВОМ[attendee.response]}{attendee.role === 'optional' ? ' · для сведения' : ''}{event!.conference_url && ведущий(attendee.user_id) ? ' · ведущий' : ''}</p>)}</div>}
      {!новая && мой && event!.attendees.length > 1 && (
        <p className="text-xs text-muted-foreground">
          {event!.attendees.map((a) => `${a.name || 'участник'} — ${ОТВЕТ_СЛОВОМ[a.response]}`).join(' · ')}
        </p>
      )}
    </Строка>
  )

  const гостиБлок = !новая && мой && event!.status !== 'cancelled' && (
    <GuestPanel companyId={companyId} eventId={event!.id} title={title} />
  )

  /* Организатор видит встречные предложения и принимает их одним нажатием.
     Само предложение время не двигает: перенос остаётся его решением. */
  const предложенияБлок = !новая && мой && предложения.length > 0 && (
    <div className="space-y-1.5 rounded-lg border border-amber-500/40 bg-amber-500/[0.05] p-3">
      <p className="text-xs font-medium text-amber-700 dark:text-amber-400">Предложили другое время</p>
      {предложения.map((a) => (
        <div key={a.user_id} className="flex flex-wrap items-center gap-2 text-xs">
          <span className="min-w-[8rem] flex-1">{a.name || 'участник'}</span>
          <span className="tabular-nums">{когда.format(new Date(a.proposed_starts_at!))}</span>
          {a.comment && <span className="text-muted-foreground">{a.comment}</span>}
          <Button size="xs" variant="outline"
            onClick={() => {
              setStarts(local(a.proposed_starts_at!))
              setEnds(local(a.proposed_ends_at!))
              toast.info('Время подставлено — сохраните встречу, чтобы перенести')
            }}>
            Перенести на это
          </Button>
        </div>
      ))}
      <p className="text-xs text-muted-foreground">Перенос обнулит согласия: «буду в 10» не равно «буду в 18».</p>
    </div>
  )

  /* По итогам встречи — поручение без исполнителя: на совещании решают ЧТО,
     а кто — часто позже. Оно попадает в «Разбор», ссылка на встречу остаётся. */
  const итогиБлок = !новая && event!.status !== 'cancelled' && (
    <div className="space-y-1.5 border-t border-border pt-3">
      <p className="text-xs font-medium text-muted-foreground">По итогам</p>
      <div className="flex items-center gap-1.5">
        <Input value={итог} onChange={(e) => setИтог(e.target.value)} aria-label="Что решили сделать"
          placeholder="Что решили сделать…" className="h-9 text-sm"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && итог.trim() && !поручить.isPending) поручить.mutate()
          }} />
        <Button size="sm" variant="outline" className="shrink-0"
          disabled={!итог.trim() || поручить.isPending}
          onClick={() => поручить.mutate()}>
          <ListPlus className="mr-1 h-3.5 w-3.5" />Поручение
        </Button>
      </div>
    </div>
  )

  const ссылкиБлок = !новая && (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onClick={async () => {
        try { await navigator.clipboard.writeText(new URL(eventHref, window.location.origin).href); toast.success('Ссылка на встречу скопирована') }
        catch { toast.error('Не удалось скопировать ссылку. Проверьте разрешение браузера.') }
      }}>Ссылка на карточку</Button>
      {/* Своя комната — своя кнопка: сервер подписывает вход ведущим. Чужую
          ссылку (Zoom, Teams) открываем как есть. */}
      {event!.status !== 'cancelled' && (
        event!.conference_url && !/\/ledger-[0-9a-f]+/i.test(event!.conference_url)
          ? (/^https?:\/\//i.test(event!.conference_url) && <Button variant="outline" size="sm" asChild><a href={event!.conference_url} target="_blank" rel="noopener noreferrer"><Video className="mr-1.5 h-4 w-4" />Открыть видеовстречу</a></Button>)
          : <Button variant="outline" size="sm" disabled={confBusy} onClick={войтиВВидеовстречу}>
              <Video className="mr-1.5 h-4 w-4" />{event!.conference_url ? 'Войти в видеовстречу' : 'Начать видеовстречу'}
            </Button>
      )}
      {subjectHref && <Button variant="ghost" size="sm" asChild><Link to={subjectHref} onClick={onClose}>Предмет встречи</Link></Button>}
    </div>
  )

  const служебныеБлок = ((!новая && мой && event!.status !== 'cancelled') || (мой && title.trim())) && (
    <div className="flex flex-wrap items-center gap-2">
      {!новая && мой && event!.status !== 'cancelled' && (
        <Button size="sm" variant="ghost" className="mr-auto text-destructive"
          disabled={отменить.isPending} onClick={() => setCancelConfirm(true)}>
          <X className="mr-1 h-3.5 w-3.5" />Отменить встречу
        </Button>
      )}
      {мой && title.trim() && (
        <Button size="sm" variant="ghost"
          disabled={сохранитьЗаготовку.isPending || !!formError}
          onClick={() => {
            const имя = window.prompt('Название заготовки', title.trim().slice(0, 60))
            if (имя?.trim()) сохранитьЗаготовку.mutate(имя.trim())
          }}>
          <BookmarkPlus className="mr-1 h-3.5 w-3.5" />В заготовки
        </Button>
      )}
    </div>
  )

  const отменаБлок = cancelConfirm && мой && (
    <section aria-label="Отмена встречи" className="space-y-2 rounded-lg border border-destructive/40 p-3">
      <p className="text-sm font-medium">{event?.recurrence ? 'Отменить эту встречу и будущие встречи серии?' : 'Отменить встречу?'}</p>
      <p className="text-sm text-muted-foreground">
        {причинаОбязательна
          ? 'Участники получат сообщение и письмо об отмене; до конца дня встреча останется у них зачёркнутой с этой причиной, потом скроется. Личные напоминания будут сняты.'
          : 'Приглашённых нет — писем никто не получит. До конца дня встреча останется в календаре зачёркнутой, потом скроется; напоминания будут сняты.'}
      </p>
      <Input aria-label="Причина отмены"
        placeholder={причинаОбязательна ? 'Причина отмены — её увидят участники' : 'Причина отмены — необязательно'}
        value={cancelReason} onChange={e => setCancelReason(e.target.value)}
        className="text-base sm:text-sm" />
      {/* Отказ, известный заранее, называется до нажатия, а не красной плашкой после. */}
      {причинаОбязательна && !cancelReason.trim() && (
        <p className="text-xs text-muted-foreground">
          Встречу ждут другие: без причины отменить нельзя — иначе в чужом календаре она
          пропадёт молча, и спросить будет не у кого.
        </p>
      )}
      <div className="flex flex-wrap gap-2"><Button variant="destructive" size="sm" disabled={отменить.isPending || (причинаОбязательна && !cancelReason.trim())} onClick={() => отменить.mutate(cancelReason.trim())}>Подтвердить отмену</Button><Button variant="ghost" size="sm" disabled={отменить.isPending} onClick={() => setCancelConfirm(false)}>Не отменять</Button></div>
    </section>
  )

  const названиеБлок = мой ? (
    <Input id={fieldId + '-title'} aria-label="Тема встречи" maxLength={300} autoFocus={новая}
      value={title} onChange={(e) => setTitle(e.target.value)}
      placeholder="Тема рабочей встречи"
      className="h-11 font-headline text-lg font-semibold md:text-lg" />
  ) : null

  const отменённая = event?.status === 'cancelled' && (
    <p className="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
      Встреча отменена{event.cancel_reason ? `: ${event.cancel_reason}` : ''}
    </p>
  )

  const кнопки = <>
    {canRespond && предлагаю && (
      <div className="mr-auto flex w-full flex-wrap items-end gap-2">
        <label className="space-y-1 text-xs text-muted-foreground">
          Предлагаю с
          <Input type="datetime-local" value={starts} className="w-[200px]"
            onChange={(e) => setStarts(e.target.value)} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">
          по
          <Input type="datetime-local" value={ends} className="w-[200px]"
            onChange={(e) => setEnds(e.target.value)} />
        </label>
        <Button size="sm" disabled={предложить.isPending || !!formError}
          onClick={() => предложить.mutate()}>Отправить</Button>
        <Button size="sm" variant="ghost" onClick={() => setПредлагаю(false)}>Отмена</Button>
      </div>
    )}
    {canRespond && !предлагаю && (
      <div className="mr-auto flex flex-wrap items-center gap-1.5">
        {ОТВЕТЫ.map((r) => (
          <Button key={r.key} size="sm" disabled={ответить.isPending}
            aria-pressed={event!.my_response === r.key}
            variant={event!.my_response === r.key ? 'default' : 'outline'}
            onClick={() => ответить.mutate(r.key)}>
            {r.label}
          </Button>
        ))}
        {/* Отказ без встречного предложения оставляет организатора гадать. */}
        <Button size="sm" variant="ghost" onClick={() => setПредлагаю(true)}>Другое время</Button>
      </div>
    )}
    {мой && (
      <Button size="sm" disabled={!title.trim() || !!formError || сохранить.isPending || отменить.isPending}
        onClick={() => сохранить.mutate()}>
        {сохранить.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
        {новая ? 'Собрать' : 'Сохранить'}
      </Button>
    )}
    {/* «Занятость участников» — у кнопки сохранения, как в настольных календарях:
        время подбирают последним шагом, когда состав уже собран. */}
    {мой && attendees.some((id) => id !== организаторId) && полно && visibility !== 'personal' && (
      <Button size="sm" variant="outline" disabled={busyQ.isFetching} onClick={() => {
        setИщем(true); void busyQ.refetch()
        document.getElementById(подборId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      }}>
        <CalendarSearch className="mr-1.5 h-3.5 w-3.5" />Занятость участников
      </Button>
    )}
    {!panel && <Button size="sm" variant="ghost" onClick={onClose}>Закрыть</Button>}
  </>

  // Теги — сразу под временем: ими встречу и находят в календаре (МАГ, 28.10.2026).
  const основное = [шаблоныБлок, времяБлок, тегиБлок, повторБлок]
  const подробности = [местоБлок, видеоБлок, описаниеБлок, материалыБлок, напоминаниеБлок]
  const люди_ = [кругБлок, участникиБлок]
  const после = [опросБлок, гостиБлок, предложенияБлок]
  const ключи = (блоки: ReactNode[], префикс: string) => блоки.map((б, i) => б ? <div key={префикс + i}>{б}</div> : null)

  const подвал = <>
    {итогиБлок}
    {ссылкиБлок}
    {служебныеБлок}
    {отменаБлок}
  </>

  if (panel) {
    return (
      <aside ref={панельRef} role="dialog" aria-label={заголовок}
        onKeyDown={(e) => {
          // Escape закрывает панель, но не когда его поймало всплывающее поле даты:
          // оно отрисовано вне панели и закрывается само.
          if (e.key === 'Escape' && панельRef.current?.contains(e.target as Node)) { e.stopPropagation(); onClose() }
        }}
        className="absolute bottom-2 right-2 top-2 z-30 flex w-[min(460px,calc(100%-1rem))] flex-col overflow-hidden rounded-xl border border-border bg-card"
        style={{ boxShadow: 'var(--shadow-large)' }}>
        <div className="flex items-start gap-2 px-4 pb-2 pt-4">
          <div className="min-w-0 flex-1">
            {названиеБлок ?? <h2 className="font-headline text-lg font-semibold leading-snug">{title}</h2>}
          </div>
          <Button variant="ghost" size="icon" className="size-9 shrink-0" aria-label="Закрыть" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-4 pt-1">
          {отменённая}
          {ключи([...основное, ...люди_, ...подробности, ...после], 'p')}
          {подвал}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">{кнопки}</div>
      </aside>
    )
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-h-[90dvh] w-[94vw] max-w-2xl overflow-y-auto p-4 sm:max-w-2xl sm:p-6 lg:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{заголовок}</DialogTitle>
        </DialogHeader>
        {отменённая}
        {названиеБлок}

        {/* На широком экране две колонки: слева что, когда и где, справа кто.
            Одной колонкой карточка уходила в три экрана прокрутки, и до
            участников не долистывали. На телефоне правая встаёт под левую. */}
        <div className="lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-8">
          <div className="space-y-4">
            {ключи([...основное, ...подробности], 'l')}
            {/* Телефон открывает встречу простой: о чём, когда, где (решение МАГа
                07.09.2026). Остальное — за «Подробнее». */}
            {phone && (
              <Button type="button" variant="outline" size="sm" className="w-full"
                aria-expanded={more} onClick={() => setMore(v => !v)}>
                {more ? 'Свернуть подробности' : 'Подробнее'}
                <ChevronDown className={cn('ml-1.5 h-4 w-4 transition-transform', more && 'rotate-180')} />
              </Button>
            )}
            {опросБлок}
          </div>
          <div className="mt-4 space-y-4 lg:mt-0">
            {ключи([...люди_, гостиБлок, предложенияБлок], 'r')}
          </div>
        </div>

        <div className="space-y-3">{подвал}</div>
        <DialogFooter className="sticky -bottom-4 -mx-4 flex-row flex-wrap gap-2 border-t border-border bg-background px-4 py-3 sm:-bottom-6 sm:-mx-6 sm:px-6">
          {кнопки}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
