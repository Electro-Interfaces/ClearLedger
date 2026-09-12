/**
 * Общие части «Конференций»: строка конференции, окно созыва, пустое состояние.
 *
 * Строка одна на все разделы намеренно. Конференция в «Конференцияах» и он же в
 * «Истории» — одна и та же вещь в разных фазах, и человек, научившийся читать
 * её сегодня, читает её же через месяц.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  CheckCircle2, Circle, Copy, FileText, Link2, Loader2, UserPlus, Video,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import * as conf from '@/services/confService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'
import { длительность, когда, копировать, предмет } from './format'

/** Строка конференции: название, мета под ним, действие справа. */
export function TalkRow({ meeting, companyId, onChanged }: {
  meeting: conf.ConfMeeting
  companyId: string
  onChanged: () => void
}) {
  const [итог, setИтог] = useState(meeting.session?.note ?? '')
  const прошла = new Date(meeting.ends_at) < new Date()
  const сессия = meeting.session
  const пред = предмет(meeting.subject_ref)

  const войти = useMutation({
    mutationFn: () => conf.joinMeeting(companyId, meeting.id),
    onSuccess: (m) => {
      копировать(m.guest_url)
      onChanged()
    },
    onError: (e: Error) => toast.error(/503|не настроен/i.test(e.message || '')
      ? 'Конференции не настроены' : 'Не удалось войти в конференцию'),
  })
  const ответ = useMutation({
    mutationFn: (что: 'accepted' | 'declined') => conf.respond(companyId, meeting.id, что),
    onSuccess: (_д, что) => {
      toast.success(что === 'accepted' ? 'Записал: будете' : 'Записал: не сможете')
      onChanged()
    },
    onError: () => toast.error('Не удалось ответить на приглашение'),
  })
  const заметка = useMutation({
    mutationFn: () => conf.saveNote(companyId, сессия!.id, итог),
    onSuccess: () => { toast.success('Записано'); onChanged() },
    onError: () => toast.error('Не удалось сохранить итог'),
  })

  const пришли = сессия?.came.length ?? 0
  const ответили = meeting.attendees.filter(у => у.response === 'accepted').length
  const отказались = meeting.attendees.filter(у => у.response === 'declined').length
  // Позвали и ответа ещё нет. Организатору своё же приглашение не показываем.
  // Идущая конференция — тоже приглашение: подтвердить участие человек должен
  // и когда разговор уже начался (CONF-06).
  const зовут = meeting.my_response === 'pending' && !meeting.organizer_is_me
    && meeting.status !== 'cancelled' && (!прошла || meeting.live)
  const звано = meeting.attendees.length + meeting.guests.length

  return (
    <div className="border-b border-border/60 py-3 last:border-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {meeting.live && (
          <span className="flex items-center gap-1.5 text-xs font-medium text-success">
            <Circle className="h-2.5 w-2.5 fill-current" />идёт
          </span>
        )}
        <span className="font-medium">{meeting.title}</span>
        {meeting.status === 'cancelled' && (
          <span className="text-xs text-destructive">отменена</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {meeting.guest_url && (
            <Button variant="ghost" size="sm" className="h-8 px-2"
              title="Скопировать ссылку для участников"
              aria-label="Скопировать ссылку для участников"
              onClick={() => копировать(meeting.guest_url!)}>
              <Copy className="h-4 w-4" />
            </Button>
          )}
          {/* У прошедшей конференции входа нет: разговор состоялся, а комната
              «на всякий случай» — это постоянная комната, а не вчерашняя
              встреча (решение МАГа 10.09.2026). */}
          {meeting.status !== 'cancelled' && !прошла && (
            <Button size="sm" disabled={войти.isPending} onClick={() => войти.mutate()}>
              {войти.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                : <Video className="mr-2 h-4 w-4" />}
              {meeting.live ? 'Присоединиться'
                : meeting.organizer_is_me ? 'Войти ведущим' : 'Присоединиться'}
            </Button>
          )}
        </div>
      </div>

      {зовут && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1.5">
          <UserPlus className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs">Вас позвали. Придёте?</span>
          <div className="ml-auto flex gap-1.5">
            <Button size="sm" variant="outline" className="h-8"
              disabled={ответ.isPending} onClick={() => ответ.mutate('accepted')}>Буду</Button>
            <Button size="sm" variant="ghost" className="h-8"
              disabled={ответ.isPending} onClick={() => ответ.mutate('declined')}>Не смогу</Button>
          </div>
        </div>
      )}

      <p className="mt-1 text-xs text-muted-foreground">
        {когда(meeting.starts_at)}
        {' · '}{meeting.organizer || 'организатор неизвестен'}
        {/* Не просто «звано 5», а сколько из них ответили: организатор
            планирует разговор по фактическим согласиям (CONF-05). */}
        {звано > 1 && ` · звано ${звано}`}
        {звано > 1 && ответили > 0 && `, будут ${ответили}`}
        {звано > 1 && отказались > 0 && `, не смогут ${отказались}`}
        {сессия?.seconds ? ` · шёл ${длительность(сессия.seconds)}` : ''}
        {пред && ' · '}
        {пред && (пред.адрес
          ? <Link to={пред.адрес} className="text-primary underline-offset-2 hover:underline">
              <Link2 className="mr-0.5 inline h-3 w-3" />{пред.имя}
            </Link>
          : пред.имя)}
      </p>

      {сессия && пришли > 0 && (
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
          <span className="text-muted-foreground">пришли:</span>
          {сессия.came.map(ч => ч.name).join(', ')}
        </p>
      )}
      {сессия?.recording && (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          <FileText className="h-3.5 w-3.5" />
          Запись
          {сессия.recording_seconds ? ` · ${длительность(сессия.recording_seconds)}` : ''}
          {' · '}
          <Link to="/conf/records" className="text-primary underline-offset-2 hover:underline">
            в разделе «Записи»
          </Link>
        </p>
      )}

      {сессия && прошла && (
        <div className="mt-2 flex gap-2">
          <Input value={итог} onChange={e => setИтог(e.target.value)}
            placeholder="О чём договорились" aria-label="Итог конференции"
            className="h-9 max-w-xl text-base sm:text-sm" />
          <Button size="sm" variant="outline" className="h-9 shrink-0"
            disabled={заметка.isPending || итог === (сессия.note ?? '')}
            onClick={() => заметка.mutate()}>Сохранить</Button>
        </div>
      )}
    </div>
  )
}

/** Окно созыва: тема, время, кого зовём, чем зовём. */
export function NewTalkDialog({ companyId, onClose, onCreated }: {
  companyId: string
  onClose: () => void
  onCreated: () => void
}) {
  const [тема, setТема] = useState('')
  const [сейчас, setСейчас] = useState(true)
  const [начало, setНачало] = useState(() => {
    const d = new Date(Date.now() + 30 * 60_000)
    d.setSeconds(0, 0)
    return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
  })
  const [минут, setМинут] = useState(60)
  const [кого, setКого] = useState<string[]>([])
  const [внешние, setВнешние] = useState('')
  const [поиск, setПоиск] = useState('')
  // Выбор канала запоминается: в одной компании планёрку зовут чатом, в другой
  // без письма на встречу не приходят. Спрашивать это каждый раз заново значит
  // заставлять человека принимать одно и то же решение по десять раз в неделю.
  const [всем, setВсем] = useState(false)
  const [почтой, setПочтой] = useState(() => {
    try { return localStorage.getItem('conf-email-copy') === '1' } catch { return false }
  })

  const люди = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const видимые = useMemo(() => (люди.data?.people ?? []).filter(п =>
    !поиск.trim() || п.name.toLocaleLowerCase('ru').includes(поиск.trim().toLocaleLowerCase('ru'))),
    [люди.data, поиск])

  const созвать = useMutation({
    mutationFn: () => conf.createMeeting(companyId, {
      title: тема,
      startsAt: сейчас ? undefined : new Date(начало).toISOString(),
      minutes: минут,
      attendeeIds: кого,
      guestEmails: внешние.split(/[\s,;]+/).filter(a => a.includes('@')),
      emailCopy: почтой,
      openToSpace: всем,
    }),
    onSuccess: async (m) => {
      try { localStorage.setItem('conf-email-copy', почтой ? '1' : '0') } catch { /* приватный режим */ }
      const д = m.delivery
      const позвали = [
        д.chatted && `в чат ${д.chatted}`,
        д.mailed && `письмом ${д.mailed}`,
        д.guests && `внешним ${д.guests}`,
      ].filter(Boolean).join(', ')
      toast.success(сейчас ? 'Конференция началась' : 'Конференция назначена',
        { description: позвали ? `Позвали: ${позвали}` : 'Ссылка в карточке конференции' })
      if (сейчас) {
        try {
          const вход = await conf.joinMeeting(companyId, m.id)
          копировать(вход.guest_url)
        } catch { /* войдёт из списка */ }
      }
      onCreated()
    },
    onError: (e: Error) => toast.error(/503|не настроен/i.test(e.message || '')
      ? 'Конференции не настроены' : 'Не удалось создать конференцию'),
  })

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent aria-describedby="conf-help"
        className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogHeader className="shrink-0 border-b border-border px-6 py-4">
          <DialogTitle>{сейчас ? 'Начать конференцию' : 'Назначить конференцию'}</DialogTitle>
          <DialogDescription id="conf-help">
            Конференция встаёт в календарь пространства, участников зовём в чат, а
            при желании и письмом.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-4">
          <div className="space-y-1.5">
            <Label htmlFor="conf-title">О чём</Label>
            <Input id="conf-title" value={тема} onChange={e => setТема(e.target.value)}
              placeholder="Разбор смены, приёмка работ, планёрка"
              className="text-base sm:text-sm" />
            <p className="text-xs text-muted-foreground">
              Тема встаёт в заголовок конференции, в приглашение и в историю. Без неё
              через месяц в списке будет строка с одной вашей фамилией.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => setСейчас(true)}
                className={cn('min-h-9 rounded-md border px-3 text-sm transition-colors',
                  сейчас ? 'border-primary bg-primary/10 font-medium text-primary'
                    : 'border-input hover:bg-accent/50')}>
                Прямо сейчас
              </button>
              <button type="button" onClick={() => setСейчас(false)}
                className={cn('min-h-9 rounded-md border px-3 text-sm transition-colors',
                  !сейчас ? 'border-primary bg-primary/10 font-medium text-primary'
                    : 'border-input hover:bg-accent/50')}>
                На время
              </button>
              {!сейчас && (
                <Input type="datetime-local" value={начало} aria-label="Когда"
                  onChange={e => setНачало(e.target.value)}
                  className="h-9 w-auto text-base sm:text-sm" />
              )}
              <div className="flex items-center gap-1.5">
                <Input type="number" min={5} max={600} step={5} value={минут}
                  aria-label="Сколько минут" onChange={e => setМинут(Number(e.target.value) || 60)}
                  className="h-9 w-20 text-base sm:text-sm" />
                <span className="text-sm text-muted-foreground">мин</span>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Конференция встаёт в календарь пространства и занимает это время у всех,
              кого позвали.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <Label htmlFor="conf-people">Кого зовём</Label>
              {кого.length > 0 && (
                <span className="text-xs text-muted-foreground">выбрано {кого.length}</span>
              )}
            </div>
            <Input id="conf-people" value={поиск} onChange={e => setПоиск(e.target.value)}
              placeholder="Имя сотрудника" className="text-base sm:text-sm" />
            <div className="max-h-44 overflow-y-auto rounded-md border border-border px-2">
              {люди.isLoading && <p role="status" className="py-2 text-sm">Загружаются сотрудники…</p>}
              {!люди.isLoading && !видимые.length && (
                <p className="py-2 text-sm text-muted-foreground">Никого не нашли</p>
              )}
              {видимые.map(п => (
                <label key={п.id}
                  className="flex min-h-10 items-center gap-2 border-b border-border/60 py-1 text-sm last:border-0">
                  <input type="checkbox" checked={кого.includes(п.id)}
                    onChange={e => setКого(с => e.target.checked
                      ? [...с, п.id] : с.filter(id => id !== п.id))} />
                  <span className="break-words">{п.name}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="conf-guests">Внешние участники</Label>
            <Textarea id="conf-guests" value={внешние} onChange={e => setВнешние(e.target.value)}
              placeholder="почта через запятую" rows={2} className="text-base sm:text-sm" />
            <p className="text-xs text-muted-foreground">
              Им уходит письмо со ссылкой и конференцией для их календаря. Учётной
              записи в пространстве гость не получает.
            </p>
          </div>

          <div className="space-y-1.5 rounded-md border border-border p-3">
            <p className="text-sm font-medium">Кто увидит</p>
            <p className="text-xs text-muted-foreground">
              По умолчанию конференцию видят только те, кого позвали. Открытую
              видит всё пространство, и войти в неё может любой сотрудник.
            </p>
            <label className="flex min-h-9 items-center gap-2 text-sm">
              <input type="checkbox" checked={всем}
                onChange={e => setВсем(e.target.checked)} />
              Открыть всему пространству
            </label>
          </div>

          <div className="space-y-1.5 rounded-md border border-border p-3">
            <p className="text-sm font-medium">Чем зовём</p>
            <p className="text-xs text-muted-foreground">
              Сообщение в чат пространства уходит всегда — оно приходит туда, где
              человек работает.
            </p>
            <label className="flex min-h-9 items-center gap-2 text-sm">
              <input type="checkbox" checked={почтой}
                onChange={e => setПочтой(e.target.checked)} />
              Продублировать письмом со встречей для календаря
            </label>
          </div>
        </div>

        <DialogFooter className="shrink-0 flex-col gap-2 border-t border-border px-6 py-4 sm:flex-row">
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button disabled={созвать.isPending} onClick={() => созвать.mutate()}>
            {созвать.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {сейчас ? 'Начать и позвать' : 'Назначить и позвать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
