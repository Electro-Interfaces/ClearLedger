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
import { Bell, BookmarkPlus, ChevronDown, Copy, ListPlus, Loader2, Repeat, Video, X } from 'lucide-react'
import { findSlots } from '@/lib/slots'
import { GuestPanel } from '@/components/calendar/GuestPanel'
import { PollPanel } from '@/components/calendar/PollPanel'
import { PapersPanel } from '@/components/calendar/PapersPanel'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DateField, TimeField } from '@/components/ui/date-time-field'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import * as workService from '@/services/workService'
import { startEventMeeting } from '@/services/conferenceService'
import type {
  CalendarEvent, EventResponse, EventVisibility, Recurrence, StoredEventVisibility,
} from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'

/** Date → значение datetime-local в местном поясе браузера. */
const local = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
const началоДня = (d: Date | null) => {
  const day = new Date(d ?? new Date())
  day.setHours(0, 0, 0, 0)
  return day
}

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

const видимостьФормы = (value: StoredEventVisibility | null | undefined): EventVisibility =>
  value === 'company' ? 'company' : 'private'

/** Два понятных режима встречи: по приглашению или для всей компании. */
const КРУГИ: { key: EventVisibility; label: string; hint: string }[] = [
  { key: 'private', label: 'Закрытая',
    hint: 'Видна организатору и приглашённым' },
  { key: 'company', label: 'Открытая',
    hint: 'Видна и доступна всем сотрудникам; приглашение получат отмеченные участники' },
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
  companyDay, onClose, onChanged }: {
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
  const [allDay, setAllDay] = useState(event?.all_day ?? !!companyDay)
  const [peopleSearch, setPeopleSearch] = useState('')
  const [cancelConfirm, setCancelConfirm] = useState(false)
  // Телефон открывает встречу простой: тема, время, место. Остальное — за
  // «Подробнее» (решение МАГа 07.09.2026).
  const phone = useIsMobile()
  const [more, setMore] = useState(false)
  /** За сколько минут до начала напомнить себе; null — не напоминать. */
  const [напомнитьЗа, setНапомнитьЗа] = useState<number | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  // «Создать видеоконференцию»: ссылка появлялась только после «Начать
  // видеовстречу» в уже собранной встрече и в приглашение не попадала
  // (РусГидро, 15.10.2026). Новой встрече номер выдаём заранее — комната
  // считается от него, и ссылка видна сразу.
  const [заранееId, setЗаранееId] = useState<string | null>(null)
  const [своя, setСвоя] = useState(false)
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
    event ? new Date(event.starts_at) : companyDay ? началоДня(startAt) : (startAt ?? new Date())))
  const [ends, setEnds] = useState(() => local(
    event ? new Date(event.ends_at)
      : companyDay ? new Date(началоДня(startAt).getTime() + 24 * 60 * 60_000)
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
    () => видимостьФормы(event?.visibility ?? (companyDay ? 'company' : 'private')))

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
    setVisibility(видимостьФормы(event.visibility))
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
    mutationFn: async () => {
      const начало = new Date(starts).toISOString()
      const конец = new Date(ends).toISOString()
      if (новая) {
        const created = await workService.createEvent(companyId, {
          title: title.trim(), startsAt: начало, endsAt: конец,
          description: description.trim() || undefined,
          location: location.trim() || undefined,
          conferenceUrl: conference.trim() || undefined,
          attendeeIds: attendees,
          optionalIds: optional,
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
        return created
      }
      return workService.eventAction(companyId, event!.id, {
        title: title.trim(), startsAt: начало, endsAt: конец,
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
  const причинаОбязательна = (event?.attendees ?? [])
    .some((a) => a.user_id !== event?.organizer_id)

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
      <DialogContent className="max-h-[90dvh] w-[94vw] max-w-2xl overflow-y-auto p-4 sm:max-w-2xl sm:p-6 lg:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{новая ? (companyDay ? 'Событие компании' : 'Новая встреча') : мой ? 'Встреча' : title}</DialogTitle>
        </DialogHeader>

        {event?.status === 'cancelled' && (
          <p className="rounded border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
            Встреча отменена{event.cancel_reason ? `: ${event.cancel_reason}` : ''}
          </p>
        )}

        {/* На широком экране карточка в две колонки: слева — что и когда, справа —
            с чем и кто (материалы, круг, участники, опрос, гости). Одной колонкой
            она уходила в три экрана прокрутки, и до участников не долистывали.
            На телефоне порядок прежний — правая колонка встаёт под левую. */}
        <div className="lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-8">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor={fieldId + "-title"}>О чём</Label>
            <Input id={fieldId + "-title"} maxLength={300} className="text-base sm:text-sm" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!мой}
              placeholder="Тема рабочей встречи" />
          </div>

          {/* 🔴 Дата и время — РАЗДЕЛЬНО и с ручным вводом.
              Было одно поле `datetime-local`: на телефоне это нативные барабаны, где
              значение только прокручивают. Человек, который знает ответ («семнадцатого,
              в девять тридцать»), крутил к нему колесо — и не мог просто напечатать
              цифры (претензия МАГа 16.09.2026). Теперь в каждом поле печатают ИЛИ
              выбирают: дату — сеткой месяца, время — списком получаса. */}
          {/* В колонке широкого экрана начало и конец стоят друг под другом: рядом
              поле даты сжималось до «14.10.20». */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-start"}>Начало</Label>
              <div className="flex gap-2">
                <DateField id={fieldId + "-start"} className="min-w-0 flex-1" disabled={!мой}
                  value={starts.slice(0, 10)}
                  onChange={(d) => changeStart(allDay ? d : d + 'T' + starts.slice(11, 16))} />
                {!allDay && (
                  <TimeField className="w-28 shrink-0" disabled={!мой} aria-label="Время начала"
                    value={starts.slice(11, 16)}
                    onChange={(t) => changeStart(starts.slice(0, 10) + 'T' + t)} />
                )}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={fieldId + "-end"}>{allDay ? "Последний день" : "Конец"}</Label>
              <div className="flex gap-2">
                <DateField id={fieldId + "-end"} className="min-w-0 flex-1" disabled={!мой}
                  value={allDay ? endDate : ends.slice(0, 10)}
                  onChange={(d) => {
                    if (!allDay) { setEnds(d + 'T' + ends.slice(11, 16)); return }
                    // «Весь день» хранит конец следующим днём: человек называет последний
                    // день встречи, а система держит границу интервала.
                    const end = new Date(d + 'T00:00'); end.setDate(end.getDate() + 1); setEnds(local(end))
                  }} />
                {!allDay && (
                  <TimeField className="w-28 shrink-0" disabled={!мой} aria-label="Время окончания"
                    value={ends.slice(11, 16)}
                    onChange={(t) => setEnds(ends.slice(0, 10) + 'T' + t)} />
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={allDay} disabled={!мой} onChange={e => toggleAllDay(e.target.checked)} />Весь день</label>
            {/* Длительность раньше пряталась на телефоне под «ещё» — а это самый быстрый
                способ задать конец: одно нажатие против набора четырёх цифр. */}
            {!allDay && мой && [30, 60, 90].map(minutes => <Button key={minutes} variant="outline" size="sm" disabled={!Number.isFinite(startMs)} onClick={() => setEnds(local(new Date(startMs + minutes * 60_000)))}>{minutes} мин</Button>)}
          </div>
          {(!phone || more) && <p className="text-sm text-muted-foreground">Время показано в часовом поясе устройства: {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>}
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
            {/* Видеовстреча — не «подробность»: на телефоне её тоже собирают
                сразу, а за «Подробнее» кнопку не находили (15.10.2026). */}
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor={fieldId + "-conference"} className="flex items-center gap-1.5">
                <Video className="h-3.5 w-3.5" />Ссылка на видеовстречу
              </Label>
              {мой && !conference.trim() && !своя ? (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <Button type="button" variant="outline" className="w-full whitespace-normal" disabled={видеоИдёт} onClick={создатьВидео}>
                    {видеоИдёт ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Video className="mr-2 h-4 w-4" />}
                    Создать видеоконференцию
                  </Button>
                  <button type="button" className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                    onClick={() => setСвоя(true)}>или своя ссылка (Zoom, Teams)</button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Input id={fieldId + "-conference"} className="min-w-0 flex-1 text-base sm:text-sm" value={conference}
                    onChange={(e) => setConference(e.target.value)} disabled={!мой} placeholder="https://…" />
                  {conference.trim() && (
                    <Button type="button" variant="outline" size="icon" className="shrink-0"
                      title="Копировать ссылку" aria-label="Копировать ссылку на видеовстречу" onClick={копироватьВидео}>
                      <Copy className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>


          {/* Телефон открывает встречу в простом виде: о чём, когда, где — этого
              хватает, чтобы записать или прочитать (решение МАГа 07.09.2026).
              Заготовки, подбор времени, повторение, описание, участники и
              напоминание живут за «Подробнее»: каждый день они не нужны, а
              высоту занимали всю. На компьютере показываем всё сразу. */}
          {phone && (
            <Button type="button" variant="outline" size="sm" className="w-full"
              aria-expanded={more} onClick={() => setMore(v => !v)}>
              {more ? 'Свернуть подробности' : 'Подробнее'}
              <ChevronDown className={cn('ml-1.5 h-4 w-4 transition-transform', more && 'rotate-180')} />
            </Button>
          )}
          {(!phone || more) && <>
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

          {/* За сколько напомнить — здесь же, при сборе встречи (вопрос МАГа 07.09.2026:
              «почему нет напоминания с выбором, за сколько времени»). У созданной
              встречи тем же занимается блок «Напомнить мне» ниже. */}
          {новая && мой && (
            <label className="flex flex-wrap items-center gap-2 text-sm">
              <span className="flex items-center gap-1.5"><Bell className="h-3.5 w-3.5" />Напомнить</span>
              <select value={напомнитьЗа ?? ''}
                onChange={(e) => setНапомнитьЗа(e.target.value === '' ? null : Number(e.target.value))}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm">
                <option value="">не напоминать</option>
                <option value="0">в момент начала</option>
                <option value="5">за 5 минут</option>
                <option value="15">за 15 минут</option>
                <option value="30">за 30 минут</option>
                <option value="60">за час</option>
                <option value="1440">за день</option>
              </select>
            </label>
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

          {/* Материалы — сразу под описанием: это та же повестка, только
              бумагами. Ниже, под списком людей и опросом времени, участник до
              них не долистывал. Видит каждый, кто открыл карточку, а не только
              организатор; право приложить проверяет сервер. */}
          {!новая && (
            <PapersPanel companyId={companyId} eventId={event!.id}
              readOnly={event!.status === 'cancelled'} />
          )}
          </>}

          {/* Опрос времени — в левой колонке: он про «когда», а не про «кто». */}
        {!новая && (мой || canRespond) && event!.status !== 'cancelled' && (
          <div>
            <PollPanel companyId={companyId} eventId={event!.id}
              isOrganizer={мой} durationMinutes={длительность}
              onChanged={() => void refreshEvent()} />
          </div>
        )}
        </div>

        <div className="mt-3 space-y-3 lg:mt-0">
          {(!phone || more) && <>
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
            {мой ? <>
                <Input aria-label="Найти участника" placeholder="Имя сотрудника" value={peopleSearch} onChange={e => setPeopleSearch(e.target.value)} className="text-base sm:text-sm" />
                <p className="text-sm text-muted-foreground">Организатор участвует обязательно. Остальных можно позвать для сведения.</p>
                {/* Организатора в списке не было вовсе (его добавляет сервер), и
                    человек не видел ни себя, ни того, что он ведущий (МАГ,
                    15.10.2026). Теперь он первой строкой, с именем. */}
                {conference.trim() && (
                  <p className="text-xs text-muted-foreground">Ведущий видеоконференции — по умолчанию организатор. Чтобы передать роль, отметьте участника и поставьте у него «ведущий». Ведущего ждут, он впускает гостей; если через 5 минут после начала его нет, первый вошедший откроет комнату сам.</p>
                )}
                {conference.trim() && !hosts.some(id => id === организаторId || attendees.includes(id)) && (
                  <p className="text-xs text-amber-700 dark:text-amber-400">Ведущий не выбран — им будет организатор.</p>
                )}
                {peopleQ.isError && <p role="alert" className="text-sm text-destructive">Не удалось загрузить сотрудников. <button className="underline" onClick={() => void peopleQ.refetch()}>Повторить</button></p>}
                <div className="max-h-48 overflow-y-auto rounded-md border border-border px-2 lg:max-h-64">
                  {peopleQ.isLoading && <p role="status" className="py-2 text-sm">Загружаются сотрудники…</p>}
                  {!peopleQ.isLoading && !peopleQ.isError && !люди.length && <p className="py-2 text-sm text-muted-foreground">Сотрудники не найдены</p>}
                  <div className="flex min-h-11 items-center gap-2 border-b border-border/60 py-1">
                    <label className="flex min-h-10 min-w-0 flex-1 items-center gap-2 text-sm">
                      <input type="checkbox" checked disabled aria-label="Организатор участвует всегда" />
                      <span className="break-words">{организаторИмя}<span className="text-muted-foreground"> · организатор</span></span>
                    </label>
                    {conference.trim() && (
                      <label className="flex shrink-0 items-center gap-1 text-xs" title="Ведущий видеоконференции: его ждут, он впускает гостей">
                        <input type="checkbox" checked={ведущий(организаторId)} onChange={e => отметитьВедущего(организаторId, e.target.checked)} />
                        ведущий
                      </label>
                    )}
                  </div>
                  {люди.map(person => <div key={person.id} className="flex min-h-11 items-center gap-2 border-b border-border/60 py-1 last:border-0">
                    <label className="flex min-h-10 min-w-0 flex-1 items-center gap-2 text-sm">
                      <input type="checkbox" checked={attendees.includes(person.id)} onChange={e => {
                        setAttendees(current => e.target.checked ? [...current, person.id] : current.filter(id => id !== person.id))
                        if (!e.target.checked) setOptional(current => current.filter(id => id !== person.id))
                        if (!e.target.checked) отметитьВедущего(person.id, false)
                      }} /><span className="break-words">{person.name}</span>
                    </label>
                    {attendees.includes(person.id) && <select aria-label={`Участие: ${person.name}`} value={optional.includes(person.id) ? 'optional' : 'required'}
                      onChange={e => setOptional(current => e.target.value === 'optional' ? [...current.filter(id => id !== person.id), person.id] : current.filter(id => id !== person.id))}
                      className="h-10 max-w-36 rounded-md border border-input bg-background px-2 text-base sm:text-sm">
                      <option value="required">Обязательно</option><option value="optional">Для сведения</option>
                    </select>}
                    {attendees.includes(person.id) && person.id !== организаторId && conference.trim() && (
                      <label className="flex shrink-0 items-center gap-1 text-xs" title="Ведущий видеоконференции: его ждут, он впускает гостей">
                        <input type="checkbox" checked={ведущий(person.id)} onChange={e => отметитьВедущего(person.id, e.target.checked)} />
                        ведущий
                      </label>
                    )}
                  </div>)}
                </div>
              </> : <div className="space-y-1 text-sm text-muted-foreground">{event!.attendees.map(attendee => <p key={attendee.user_id}>{attendee.name || 'Участник'} · {ОТВЕТ_СЛОВОМ[attendee.response]}{attendee.role === 'optional' ? ' · для сведения' : ''}{event!.conference_url && ведущий(attendee.user_id) ? ' · ведущий' : ''}</p>)}</div>}
          </div>

          {!новая && мой && event!.attendees.length > 1 && (
            <p className="text-xs text-muted-foreground">
              {event!.attendees.map((a) => `${a.name || 'участник'} — ${ОТВЕТ_СЛОВОМ[a.response]}`)
                .join(' · ')}
            </p>
          )}
          </>}

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
        </div>
        </div>

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
          }}>Ссылка на карточку</Button>
          {/* «Ссылка на встречу» копировала адрес карточки календаря, а не комнаты
              (РусГидро, 14.10.2026). Ссылка на видеовстречу копируется значком в
              своей строке, здесь — только адрес карточки. */}
          {/* Своя комната — своя кнопка: сервер подписывает вход ведущим, иначе
              Jitsi держит всех на «ждём организатора». Чужую ссылку (Zoom,
              Teams) открываем как есть — ведущего там назначаем не мы. */}
          {event!.status !== 'cancelled' && (
            event!.conference_url && !/\/ledger-[0-9a-f]+/i.test(event!.conference_url)
              ? (/^https?:\/\//i.test(event!.conference_url) && <Button variant="outline" asChild><a href={event!.conference_url} target="_blank" rel="noopener noreferrer"><Video className="mr-2 h-4 w-4" />Открыть видеовстречу</a></Button>)
              : <Button variant="outline" disabled={confBusy} onClick={войтиВВидеовстречу}>
                  <Video className="mr-2 h-4 w-4" />{event!.conference_url ? 'Войти в видеовстречу' : 'Начать видеовстречу'}
                </Button>
          )}
          {subjectHref && <Button variant="ghost" asChild><Link to={subjectHref} onClick={onClose}>Предмет встречи</Link></Button>}
        </div>}
        {!новая && event!.status !== 'cancelled' && (!phone || more) && <EventReminder companyId={companyId} event={event!} />}
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
          <p className="text-sm text-muted-foreground">
            Участники получат сообщение и письмо об отмене; до конца дня встреча останется у них
            зачёркнутой с этой причиной, потом скроется. Личные напоминания будут сняты.
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
          <div className="flex flex-wrap gap-2"><Button variant="destructive" disabled={отменить.isPending || (причинаОбязательна && !cancelReason.trim())} onClick={() => отменить.mutate(cancelReason.trim())}>Подтвердить отмену</Button><Button variant="ghost" disabled={отменить.isPending} onClick={() => setCancelConfirm(false)}>Не отменять</Button></div>
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
