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
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ListPlus, Loader2, Repeat, Video, X } from 'lucide-react'
import { findSlots } from '@/lib/slots'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import * as workService from '@/services/workService'
import type { CalendarEvent, EventResponse, Recurrence } from '@/services/workService'
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

export function EventDialog({ companyId, event, startAt, subjectRef, initialTitle,
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
  const новая = !event
  const мой = event?.is_organizer ?? true

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
    setПовтор(ключПовтора(event.recurrence ?? null))
    setUntil(event.recurrence_until ?? '')
  }, [event])

  const [длительность, setДлительность] = useState(60)
  const [ищем, setИщем] = useState(false)

  // Окно поиска — две недели вперёд: дальше подбирают по договорённости, а не
  // по сетке, и тащить месяц занятости ради этого незачем.
  const [окноОт, окноДо] = (() => {
    const н = new Date()
    const к = new Date(н.getTime() + 14 * 24 * 3600_000)
    return [н.toISOString(), к.toISOString()]
  })()
  const busyQ = useQuery({
    queryKey: ['calendar-busy', companyId, attendees.slice().sort().join(',')],
    queryFn: () => workService.calendarBusy(companyId, окноОт, окноДо, attendees),
    enabled: false,
  })
  const кандидаты = useMemo(() => {
    const люди = busyQ.data?.people ?? []
    if (!люди.length) return []
    return findSlots({
      people: люди, requiredIds: люди.map((p) => p.user_id),
      from: new Date(окноОт), to: new Date(окноДо), minutes: длительность,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busyQ.data, длительность])

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
      toast.success('Поручение заведено — оно в «Разборе», пока не назначен исполнитель')
      onChanged()
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
          subjectRef: subjectRef || undefined,
          recurrence: ПОВТОРЫ.find((r) => r.key === повтор)?.rule ?? null,
          recurrenceUntil: повтор === 'none' ? null : (until || null),
        })
      }
      return workService.eventAction(companyId, event!.id, {
        title: title.trim(), startsAt: начало, endsAt: конец,
        description: description.trim(), location: location.trim(),
        conferenceUrl: conference.trim(), attendeeIds: attendees,
        // Серия правится только у головы: у порождённой встречи `recurrence`
        // пуст, и слать пустой объект значило бы каждый раз снимать повторение
        // с той, у которой его и не было.
        ...(event!.series_id ? {} : {
          recurrence: ПОВТОРЫ.find((r) => r.key === повтор)?.rule ?? {},
          recurrenceUntil: повтор === 'none' ? null : (until || null),
        }),
      })
    },
    onSuccess: () => { toast.success(новая ? 'Встреча собрана' : 'Сохранено'); onChanged(); onClose() },
    onError: (e: Error) => toast.error(e.message || 'Не сохранилось'),
  })

  const ответить = useMutation({
    mutationFn: (response: Exclude<EventResponse, 'pending'>) =>
      workService.eventAction(companyId, event!.id, { response }),
    onSuccess: () => { toast.success('Ответ записан'); onChanged() },
    onError: (e: Error) => toast.error(e.message || 'Ответ не записался'),
  })

  const отменить = useMutation({
    mutationFn: (reason: string) =>
      workService.eventAction(companyId, event!.id, { cancel: true, cancelReason: reason }),
    onSuccess: () => { toast.success('Встреча отменена'); onChanged(); onClose() },
    onError: (e: Error) => toast.error(e.message || 'Не отменилась'),
  })

  const люди = peopleQ.data?.people ?? []
  const время_поехало = !новая && (
    local(new Date(event!.starts_at)) !== starts || local(new Date(event!.ends_at)) !== ends)

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
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
            <Label>О чём</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!мой}
              placeholder="Планёрка по 208" />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Начало</Label>
              <Input type="datetime-local" value={starts} disabled={!мой}
                onChange={(e) => setStarts(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Конец</Label>
              <Input type="datetime-local" value={ends} disabled={!мой}
                onChange={(e) => setEnds(e.target.value)} />
            </div>
          </div>

          {время_поехало && event!.attendees.length > 1 && (
            <p className="rounded border border-amber-500/40 bg-amber-500/5 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400">
              Время меняется — согласия участников сбросятся: «буду в 10» не значит «буду в 18».
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Где</Label>
              <Input value={location} onChange={(e) => setLocation(e.target.value)}
                disabled={!мой} placeholder="Переговорная, адрес" />
            </div>
            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5">
                <Video className="h-3.5 w-3.5" />Ссылка на видеовстречу
              </Label>
              <Input value={conference} onChange={(e) => setConference(e.target.value)}
                disabled={!мой} placeholder="https://…" />
            </div>
          </div>

          {/* «Найти время» появляется, только когда есть кого искать: подбор по
              одному себе — это просто календарь. Обязательными считаем всех
              приглашённых: деления на обязательных и необязательных в составе
              нет, а выдумывать его ради подбора значит завести понятие, которого
              в продукте не существует. Занятость приходит интервалами, окно —
              рабочими часами каждого; кто свободен, но ещё не работает, в
              кандидаты не попадёт. */}
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
                кандидаты.length === 0 ? (
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
                <Label>Повторять</Label>
                <select value={повтор}
                  onChange={(e) => setПовтор(e.target.value as КлючПовтора)}
                  className="h-9 w-[200px] rounded-md border border-input bg-background px-3 text-sm">
                  {ПОВТОРЫ.map((r) => (
                    <option key={r.key} value={r.key}>{r.label}</option>
                  ))}
                </select>
              </div>
              {повтор !== 'none' && (
                <div className="space-y-1.5">
                  <Label>До</Label>
                  <Input type="date" value={until} className="w-[170px]"
                    onChange={(e) => setUntil(e.target.value)} />
                  <p className="text-[11px] text-muted-foreground">
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

          <div className="space-y-1.5">
            <Label>Описание</Label>
            <Textarea value={description} rows={3} disabled={!мой}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Что обсуждаем, что принести" />
          </div>

          <div className="space-y-1.5">
            <Label>Кого зовём</Label>
            {мой ? (
              <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded border border-border p-2">
                {peopleQ.isLoading && (
                  <span className="text-xs text-muted-foreground">Загружаю список…</span>
                )}
                {люди.map((p) => {
                  const выбран = attendees.includes(p.id)
                  return (
                    <button key={p.id} type="button"
                      onClick={() => setAttendees((v) => (выбран
                        ? v.filter((x) => x !== p.id) : [...v, p.id]))}
                      className={cn('rounded-full border px-2 py-0.5 text-xs transition-colors',
                        выбран
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border text-muted-foreground hover:bg-accent')}>
                      {p.name}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {event!.attendees.map((a) => (
                  <span key={a.user_id}
                    className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                    {a.name || 'участник'} · {ОТВЕТ_СЛОВОМ[a.response]}
                  </span>
                ))}
              </div>
            )}
          </div>

          {!новая && мой && event!.attendees.length > 1 && (
            <p className="text-xs text-muted-foreground">
              {event!.attendees.map((a) => `${a.name || 'участник'} — ${ОТВЕТ_СЛОВОМ[a.response]}`)
                .join(' · ')}
            </p>
          )}
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
                  if (e.key === 'Enter' && итог.trim()) поручить.mutate()
                }} />
              <Button size="sm" variant="outline" className="h-8 shrink-0 px-2 text-xs"
                disabled={!итог.trim() || поручить.isPending}
                onClick={() => поручить.mutate()}>
                <ListPlus className="mr-1 h-3.5 w-3.5" />Поручение
              </Button>
            </div>
          </div>
        )}

        <DialogFooter className="flex-wrap gap-2">
          {!новая && !мой && (
            <div className="mr-auto flex items-center gap-1.5">
              {ОТВЕТЫ.map((r) => (
                <Button key={r.key} size="sm" disabled={ответить.isPending}
                  variant={event!.my_response === r.key ? 'default' : 'outline'}
                  onClick={() => ответить.mutate(r.key)}>
                  {r.label}
                </Button>
              ))}
            </div>
          )}
          {!новая && мой && event!.status !== 'cancelled' && (
            <Button size="sm" variant="ghost" className="mr-auto text-destructive"
              disabled={отменить.isPending}
              onClick={() => отменить.mutate('')}>
              <X className="mr-1 h-3.5 w-3.5" />Отменить встречу
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>Закрыть</Button>
          {мой && (
            <Button size="sm" disabled={!title.trim() || сохранить.isPending}
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
