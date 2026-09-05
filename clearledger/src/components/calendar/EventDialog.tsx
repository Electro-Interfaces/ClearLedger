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
import { useEffect, useId, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useHref } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { EventReminder } from './EventReminder'
import { BookmarkPlus, ListPlus, Loader2, Repeat, Video, X } from 'lucide-react'
import { findSlots } from '@/lib/slots'
import { GuestPanel } from '@/components/calendar/GuestPanel'
import { PollPanel } from '@/components/calendar/PollPanel'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import * as workService from '@/services/workService'
import type {
  CalendarEvent, EventResponse, EventVisibility, Recurrence,
} from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'

/** Date → значение datetime-local в местном поясе браузера. */
const local = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)

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

export function EventDialog({ companyId, event: initialEvent, startAt, subjectRef, initialTitle,
  onClose, onChanged }: {
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
  const [allDay, setAllDay] = useState(event?.all_day ?? false)
  const [peopleSearch, setPeopleSearch] = useState('')
  const [cancelConfirm, setCancelConfirm] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
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

  const [title, setTitle] = useState(event?.title ?? initialTitle ?? '')
  const [description, setDescription] = useState(event?.description ?? '')
  const [starts, setStarts] = useState(() => local(
    event ? new Date(event.starts_at) : (startAt ?? new Date())))
  const [ends, setEnds] = useState(() => local(
    event ? new Date(event.ends_at)
      : new Date((startAt ?? new Date()).getTime() + 60 * 60_000)))
  const [location, setLocation] = useState(event?.location ?? '')
  const [conference, setConference] = useState(event?.conference_url ?? '')
  const [attendees, setAttendees] = useState<string[]>(
    () => (event?.attendees ?? []).map((a) => a.user_id))
  // Кто позван «для сведения». Его занятость не блокирует подбор времени:
  // иначе приглашённый руководитель закрывает все слоты, хотя встреча может
  // пройти без него.
  const [optional, setOptional] = useState<string[]>(
    () => (event?.attendees ?? []).filter((a) => a.role === 'optional')
      .map((a) => a.user_id))
  // Круг встречи — тот же словарь, что у поручения. Без выбора всё уходило в
  // `company`, и встреча, которую человек считал разговором пятерых,
  // публиковалась всей компании.
  const [visibility, setVisibility] = useState<EventVisibility>(
    () => event?.visibility ?? 'company')

  // Смена встречи в родителе (открыли другую) — перезаполняем поля.
  useEffect(() => {
    if (!event) return
    setTitle(event.title)
    setDescription(event.description ?? '')
    setStarts(local(new Date(event.starts_at)))
    setEnds(local(new Date(event.ends_at)))
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
        (new Date(ends).getTime() - new Date(starts).getTime()) / 60_000)),
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
      proposeStartsAt: new Date(starts).toISOString(),
      proposeEndsAt: new Date(ends).toISOString(),
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
    const requested = new Date(searchDate + 'T00:00')
    const from = new Date(Math.max(Number.isFinite(requested.getTime()) ? requested.getTime() : 0, Date.now()))
    const to = new Date(from)
    to.setDate(to.getDate() + 14)
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
    mutationFn: () => {
      const начало = new Date(starts).toISOString()
      const конец = new Date(ends).toISOString()
      if (новая) {
        return workService.createEvent(companyId, {
          title: title.trim(), startsAt: начало, endsAt: конец,
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
        })
      }
      return workService.eventAction(companyId, event!.id, {
        title: title.trim(), startsAt: начало, endsAt: конец,
        description: description.trim(), location: location.trim(),
        conferenceUrl: conference.trim(), attendeeIds: attendees,
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

  const отменить = useMutation({
    mutationFn: (reason: string) =>
      workService.eventAction(companyId, event!.id, { cancel: true, cancelReason: reason }),
    onSuccess: () => { toast.success('Встреча отменена'); notifyChanged(); onClose() },
    onError: (e: Error) => toast.error(e.message || 'Не отменилась'),
  })

  const люди = (peopleQ.data?.people ?? []).filter(person => person.id !== (event?.organizer_id ?? user?.id)
    && (!peopleSearch.trim() || person.name.toLocaleLowerCase('ru').includes(peopleSearch.trim().toLocaleLowerCase('ru'))))
  const startMs = new Date(starts).getTime()
  const endMs = new Date(ends).getTime()
  let formError = !Number.isFinite(startMs) || !Number.isFinite(endMs) ? 'Укажите начало и конец встречи.'
    : endMs <= startMs ? 'Конец встречи должен быть позже начала.'
      : повтор !== 'none' && until && until < starts.slice(0, 10) ? 'Повторение не может закончиться раньше первой встречи.' : ''
  if (!formError && conference.trim()) {
    try { const url = new URL(conference.trim()); if (!['https:', 'http:'].includes(url.protocol)) formError = 'Укажите ссылку с https:// или http://.' }
    catch { formError = 'Укажите полную ссылку на видеовстречу, начиная с https://.' }
  }
  const changeStart = (value: string) => {
    const next = allDay && value ? value + 'T00:00' : value
    const delta = new Date(next).getTime() - startMs
    setStarts(next)
    if (Number.isFinite(delta) && Number.isFinite(endMs)) setEnds(local(new Date(endMs + delta)))
  }
  const toggleAllDay = (checked: boolean) => {
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return
    const start = new Date(startMs)
    const end = new Date(endMs)
    setAllDay(checked)
    if (checked) {
      start.setHours(0, 0, 0, 0)
      const endsAtMidnight = end.getHours() === 0 && end.getMinutes() === 0
      end.setHours(0, 0, 0, 0)
      if (!endsAtMidnight) end.setDate(end.getDate() + 1)
    } else {
      start.setHours(10, 0, 0, 0)
      end.setTime(start.getTime() + 60 * 60_000)
    }
    setStarts(local(start)); setEnds(local(end))
  }
  const endDate = Number.isFinite(endMs) ? (() => { const date = new Date(endMs); date.setDate(date.getDate() - 1); return local(date).slice(0, 10) })() : ''
  const subjectHref = event?.subject_ref ? workService.refHref(event.subject_ref) : null
  const время_поехало = !новая && (
    local(new Date(event!.starts_at)) !== starts || local(new Date(event!.ends_at)) !== ends)

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-h-[90dvh] w-[94vw] max-w-2xl overflow-y-auto p-4 sm:max-w-2xl sm:p-6">
        <DialogHeader>
          <DialogTitle>{новая ? 'Новая встреча' : мой ? 'Встреча' : title}</DialogTitle>
        </DialogHeader>

        {event?.status === 'cancelled' && (
          <p className="rounded border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
            Встреча отменена{event.cancel_reason ? `: ${event.cancel_reason}` : ''}
          </p>
        )}

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor={fieldId + "-title"}>О чём</Label>
            <Input id={fieldId + "-title"} maxLength={300} className="text-base sm:text-sm" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!мой}
              placeholder="Тема рабочей встречи" />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-start"}>Начало</Label>
              <Input id={fieldId + "-start"} type={allDay ? 'date' : 'datetime-local'} value={allDay ? starts.slice(0, 10) : starts} disabled={!мой}
                className="min-w-0 text-base sm:text-sm" onChange={(e) => changeStart(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-end"}>{allDay ? "Последний день" : "Конец"}</Label>
              <Input id={fieldId + "-end"} type={allDay ? 'date' : 'datetime-local'} value={allDay ? endDate : ends} disabled={!мой}
                className="min-w-0 text-base sm:text-sm" onChange={(e) => {
                  if (!allDay || !e.target.value) { setEnds(e.target.value); return }
                  const end = new Date(e.target.value + 'T00:00'); end.setDate(end.getDate() + 1); setEnds(local(end))
                }} />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={allDay} disabled={!мой} onChange={e => toggleAllDay(e.target.checked)} />Весь день</label>
            {!allDay && мой && [30, 60, 90].map(minutes => <Button key={minutes} variant="outline" size="sm" disabled={!Number.isFinite(startMs)} onClick={() => setEnds(local(new Date(startMs + minutes * 60_000)))}>{minutes} мин</Button>)}
          </div>
          <p className="text-sm text-muted-foreground">Время показано в часовом поясе устройства: {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>
          {formError && <p role="alert" className="text-sm text-destructive">{formError}</p>}

          {время_поехало && event!.attendees.length > 1 && (
            <p className="rounded border border-amber-500/40 bg-amber-500/5 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400">
              Время меняется — согласия участников сбросятся: «буду в 10» не значит «буду в 18».
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-location"}>Где</Label>
              <Input id={fieldId + "-location"} className="text-base sm:text-sm" value={location} onChange={(e) => setLocation(e.target.value)}
                disabled={!мой} placeholder="Переговорная, адрес" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-conference"} className="flex items-center gap-1.5">
                <Video className="h-3.5 w-3.5" />Ссылка на видеовстречу
              </Label>
              <Input id={fieldId + "-conference"} className="text-base sm:text-sm" value={conference} onChange={(e) => setConference(e.target.value)}
                disabled={!мой} placeholder="https://…" />
            </div>
          </div>

          {/* Заготовка — просто набор полей, который надоело набирать заново.
              Повторение здесь тоже поле: «планёрка по понедельникам» заводится
              одним нажатием вместе со своей серией. */}
          {новая && (шаблоны.data?.templates.length ?? 0) > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Заготовка:</span>
              {(шаблоны.data?.templates ?? []).map((t) => (
                <Button key={t.id} type="button" size="sm" variant="outline"
                  className="h-7 px-2 text-xs"
                  onClick={() => {
                    setTitle(t.title)
                    setDescription(t.description ?? '')
                    setLocation(t.location ?? '')
                    setAttendees(t.attendee_ids)
                    setДлительность(t.duration_minutes)
                    setПовтор(ключПовтора(t.recurrence))
                    const н = new Date(starts)
                    setEnds(local(new Date(н.getTime() + t.duration_minutes * 60_000)))
                  }}>
                  {t.name}
                </Button>
              ))}
            </div>
          )}

          {мой && attendees.length > 0 && (
            <div className="space-y-1.5 rounded-md border border-border p-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">Найти время</span>
                <select value={длительность}
                  onChange={(e) => setДлительность(Number(e.target.value))}
                  className="h-7 rounded border border-input bg-background px-1.5 text-xs">
                  {[30, 60, 90, 120].map((m) => (
                    <option key={m} value={m}>{m} мин</option>
                  ))}
                </select>
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                  disabled={busyQ.isFetching}
                  onClick={() => { setИщем(true); void busyQ.refetch() }}>
                  {busyQ.isFetching
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : 'Подобрать'}
                </Button>
              </div>
              {ищем && !busyQ.isFetching && (
                busyQ.isError ? <p role="alert" className="text-sm text-destructive">Не удалось проверить занятость. Повторите подбор.</p>
                : busyQ.data?.truncated ? <p role="alert" className="text-sm text-muted-foreground">Данных о занятости слишком много. Сократите состав: свободное время пока не подтверждено.</p>
                : кандидаты.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Общего окна на две недели вперёд нет. Уберите кого-то из
                    состава или соберите короче.
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
                        title={c.busyOptional.length
                          ? `Заняты: ${c.busyOptional.join(', ')}`
                          : 'Все свободны'}
                        className={cn('rounded border px-2 py-0.5 text-xs hover:bg-accent',
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
          )}

          {/* Повторение задаётся на голове серии. Порождённая встреча его не
              показывает: у неё оно пусто, и предлагать «повторять» тому, что уже
              есть повторение, значит завести серию внутри серии. */}
          {мой && !event?.series_id && (
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1.5">
                <Label htmlFor={fieldId + "-repeat"}>Повторять</Label>
                <select id={fieldId + "-repeat"} value={повтор}
                  onChange={(e) => setПовтор(e.target.value as КлючПовтора)}
                  className="h-9 w-[200px] rounded-md border border-input bg-background px-3 text-sm">
                  {ПОВТОРЫ.map((r) => (
                    <option key={r.key} value={r.key}>{r.label}</option>
                  ))}
                </select>
              </div>
              {повтор !== 'none' && (
                <div className="space-y-1.5">
                  <Label htmlFor={fieldId + "-until"}>Повторять до</Label>
                  <Input id={fieldId + "-until"} type="date" value={until} className="w-[170px]"
                    onChange={(e) => setUntil(e.target.value)} />
                  <p className="text-[12px] text-muted-foreground">
                    Пусто — пока не выключите
                  </p>
                </div>
              )}
            </div>
          )}
          {event?.series_id && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Repeat className="h-3.5 w-3.5" />
              Встреча из серии. Правки и отмена коснутся только её.
            </p>
          )}
          {event?.recurrence && <p className="text-sm text-muted-foreground">Уже назначенные повторы редактируются отдельно. Изменение правила действует на новые повторения.</p>}

          <div className="space-y-1.5">
            <Label htmlFor={fieldId + "-description"}>Описание</Label>
            <Textarea id={fieldId + "-description"} className="text-base sm:text-sm" value={description} rows={3} disabled={!мой}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Что обсуждаем, что принести" />
          </div>

          <div className="space-y-1.5">
            <Label>Кто видит встречу</Label>
            <div className="flex flex-wrap gap-1.5">
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
            <p className="text-[12px] text-muted-foreground">
              {КРУГИ.find((к) => к.key === visibility)?.hint}
            </p>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Кого зовём</p>
            {мой && visibility === 'personal' ? <p className="text-sm text-muted-foreground">После сохранения останется только организатор. Приглашённые участники будут убраны.</p>
              : мой ? <>
                <Input aria-label="Найти участника" placeholder="Имя сотрудника" value={peopleSearch} onChange={e => setPeopleSearch(e.target.value)} className="text-base sm:text-sm" />
                <p className="text-sm text-muted-foreground">Организатор участвует обязательно. Остальных можно позвать для сведения.</p>
                {peopleQ.isError && <p role="alert" className="text-sm text-destructive">Не удалось загрузить сотрудников. <button className="underline" onClick={() => void peopleQ.refetch()}>Повторить</button></p>}
                <div className="max-h-48 overflow-y-auto rounded-md border border-border px-2">
                  {peopleQ.isLoading && <p role="status" className="py-2 text-sm">Загружаются сотрудники…</p>}
                  {!peopleQ.isLoading && !peopleQ.isError && !люди.length && <p className="py-2 text-sm text-muted-foreground">Сотрудники не найдены</p>}
                  {люди.map(person => <div key={person.id} className="flex min-h-11 items-center gap-2 border-b border-border/60 py-1 last:border-0">
                    <label className="flex min-h-10 min-w-0 flex-1 items-center gap-2 text-sm">
                      <input type="checkbox" checked={attendees.includes(person.id)} onChange={e => {
                        setAttendees(current => e.target.checked ? [...current, person.id] : current.filter(id => id !== person.id))
                        if (!e.target.checked) setOptional(current => current.filter(id => id !== person.id))
                      }} /><span className="break-words">{person.name}</span>
                    </label>
                    {attendees.includes(person.id) && <select aria-label={`Участие: ${person.name}`} value={optional.includes(person.id) ? 'optional' : 'required'}
                      onChange={e => setOptional(current => e.target.value === 'optional' ? [...current.filter(id => id !== person.id), person.id] : current.filter(id => id !== person.id))}
                      className="h-10 max-w-36 rounded-md border border-input bg-background px-2 text-base sm:text-sm">
                      <option value="required">Обязательно</option><option value="optional">Для сведения</option>
                    </select>}
                  </div>)}
                </div>
              </> : <div className="space-y-1 text-sm text-muted-foreground">{event!.attendees.map(attendee => <p key={attendee.user_id}>{attendee.name || 'Участник'} · {ОТВЕТ_СЛОВОМ[attendee.response]}{attendee.role === 'optional' ? ' · для сведения' : ''}</p>)}</div>}
          </div>

          {!новая && мой && event!.attendees.length > 1 && (
            <p className="text-xs text-muted-foreground">
              {event!.attendees.map((a) => `${a.name || 'участник'} — ${ОТВЕТ_СЛОВОМ[a.response]}`)
                .join(' · ')}
            </p>
          )}
        </div>

        {!новая && (мой || canRespond) && event!.status !== 'cancelled' && (
          <div className="mt-3">
            <PollPanel companyId={companyId} eventId={event!.id}
              isOrganizer={мой} durationMinutes={длительность}
              onChanged={() => void refreshEvent()} />
          </div>
        )}

        {!новая && мой && event!.status !== 'cancelled' && (
          <div className="mt-3">
            <GuestPanel companyId={companyId} eventId={event!.id} title={title} />
          </div>
        )}

        {/* Организатор видит встречные предложения и принимает их одним
            нажатием. Само предложение время не двигало: перенос остаётся его
            решением, иначе любой приглашённый переставлял бы чужие календари. */}
        {!новая && мой && предложения.length > 0 && (
          <div className="mt-3 space-y-1.5 rounded-md border border-amber-500/40 bg-amber-500/[0.05] p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
              Предложили другое время
            </p>
            {предложения.map((a) => (
              <div key={a.user_id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="min-w-[8rem] flex-1">{a.name || 'участник'}</span>
                <span className="tabular-nums">
                  {когда.format(new Date(a.proposed_starts_at!))}
                </span>
                {a.comment && <span className="text-muted-foreground">{a.comment}</span>}
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                  onClick={() => {
                    setStarts(local(new Date(a.proposed_starts_at!)))
                    setEnds(local(new Date(a.proposed_ends_at!)))
                    toast.info('Время подставлено — сохраните встречу, чтобы перенести')
                  }}>
                  Перенести на это
                </Button>
              </div>
            ))}
            <p className="text-[12px] text-muted-foreground">
              Перенос обнулит согласия: «буду в 10» не равно «буду в 18».
            </p>
          </div>
        )}

        {/* По итогам встречи — поручение. Исполнителя здесь не спрашиваем: на
            совещании решают ЧТО, а кто — часто позже. Работа без исполнителя не
            теряется, она попадает в «Разбор», где её берут, отдают или
            закрывают с причиной. Ссылка на встречу остаётся в предмете
            поручения: через месяц видно, где это решили. */}
        {!новая && event!.status !== 'cancelled' && (
          <div className="mt-3 space-y-1.5 border-t pt-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              По итогам
            </p>
            <div className="flex items-center gap-1.5">
              <Input value={итог} onChange={(e) => setИтог(e.target.value)}
                placeholder="Что решили сделать…" className="h-8 text-sm"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && итог.trim() && !поручить.isPending) поручить.mutate()
                }} />
              <Button size="sm" variant="outline" className="h-8 shrink-0 px-2 text-xs"
                disabled={!итог.trim() || поручить.isPending}
                onClick={() => поручить.mutate()}>
                <ListPlus className="mr-1 h-3.5 w-3.5" />Поручение
              </Button>
            </div>
          </div>
        )}

        {!новая && <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Button variant="outline" onClick={async () => {
            try { await navigator.clipboard.writeText(new URL(eventHref, window.location.origin).href); toast.success('Ссылка на встречу скопирована') }
            catch { toast.error('Не удалось скопировать ссылку. Проверьте разрешение браузера.') }
          }}>Ссылка на встречу</Button>
          {event!.conference_url && /^https?:\/\//i.test(event!.conference_url) && event!.status !== 'cancelled' && <Button variant="outline" asChild><a href={event!.conference_url} target="_blank" rel="noopener noreferrer"><Video className="mr-2 h-4 w-4" />Открыть видеовстречу</a></Button>}
          {subjectHref && <Button variant="ghost" asChild><Link to={subjectHref} onClick={onClose}>Предмет встречи</Link></Button>}
        </div>}
        {!новая && event!.status !== 'cancelled' && <EventReminder companyId={companyId} event={event!} />}
<div className="flex flex-wrap items-center gap-2">
          {!новая && мой && event!.status !== 'cancelled' && (
            <Button size="sm" variant="ghost" className="mr-auto text-destructive"
              disabled={отменить.isPending}
              onClick={() => setCancelConfirm(true)}>
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
        {cancelConfirm && мой && <section aria-label="Отмена встречи" className="space-y-2 rounded-md border border-destructive/40 p-3">
          <p className="text-sm font-medium">{event?.recurrence ? 'Отменить эту встречу и будущие встречи серии?' : 'Отменить встречу?'}</p>
          <p className="text-sm text-muted-foreground">Отмена останется видна в календаре участников. Личные напоминания о встрече будут сняты.</p>
          <Input aria-label="Причина отмены" placeholder="Причина отмены — необязательно" value={cancelReason} onChange={e => setCancelReason(e.target.value)} className="text-base sm:text-sm" />
          <div className="flex flex-wrap gap-2"><Button variant="destructive" disabled={отменить.isPending} onClick={() => отменить.mutate(cancelReason.trim())}>Подтвердить отмену</Button><Button variant="ghost" disabled={отменить.isPending} onClick={() => setCancelConfirm(false)}>Не отменять</Button></div>
        </section>}
        <DialogFooter className="sticky -bottom-4 -mx-4 flex-row flex-wrap gap-2 border-t border-border bg-background px-4 py-3 sm:-bottom-6 sm:-mx-6 sm:px-6">
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
              <Button size="sm" variant="ghost"
                onClick={() => setПредлагаю(false)}>Отмена</Button>
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
              {/* Отказ без встречного предложения оставляет организатора гадать,
                  когда человеку удобно, и переписка уходит в чат. */}
              <Button size="sm" variant="ghost" onClick={() => setПредлагаю(true)}>
                Другое время
              </Button>
            </div>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>Закрыть</Button>
          {мой && (
            <Button size="sm" disabled={!title.trim() || !!formError || сохранить.isPending || отменить.isPending}
              onClick={() => сохранить.mutate()}>
              {сохранить.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              {новая ? 'Собрать' : 'Сохранить'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
