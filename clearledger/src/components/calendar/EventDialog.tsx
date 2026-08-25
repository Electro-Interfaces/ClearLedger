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
import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2, Video, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import * as workService from '@/services/workService'
import type { CalendarEvent, EventResponse } from '@/services/workService'
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

export function EventDialog({ companyId, event, startAt, onClose, onChanged }: {
  companyId: string
  /** Существующая встреча — правим её; иначе собираем новую. */
  event: CalendarEvent | null
  /** С какого времени предложить новую встречу (клик по дню). */
  startAt: Date | null
  onClose: () => void
  onChanged: () => void
}) {
  const новая = !event
  const мой = event?.is_organizer ?? true

  const [title, setTitle] = useState(event?.title ?? '')
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
  }, [event])

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
        })
      }
      return workService.eventAction(companyId, event!.id, {
        title: title.trim(), startsAt: начало, endsAt: конец,
        description: description.trim(), location: location.trim(),
        conferenceUrl: conference.trim(), attendeeIds: attendees,
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
