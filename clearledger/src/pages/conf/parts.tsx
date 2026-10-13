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
  CheckCircle2, ChevronRight, Circle, Copy, FileText, Link2, Loader2, Paperclip, UserPlus, Video,
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
import * as workService from '@/services/workService'
import { EventDialog } from '@/components/calendar/EventDialog'
import { cn } from '@/lib/utils'
import { длительность, когда, копировать, предмет } from './format'

/**
 * Назначенные конференции, сложенные по сериям: у серии комната одна, по ней и
 * складываем. Еженедельная планёрка на два месяца вперёд давала девять
 * одинаковых строк с одним и тем же вопросом «Придёте?» и занимала весь экран
 * (РусГидро, серия «Интеграция», 14.10.2026). Список приходит по времени,
 * поэтому первая в группе — ближайшая.
 */
export function посериям(список: conf.ConfMeeting[]): conf.ConfMeeting[][] {
  const группы = new Map<string, conf.ConfMeeting[]>()
  for (const в of список) {
    const ключ = в.room ?? в.id
    const группа = группы.get(ключ)
    if (группа) группа.push(в)
    else группы.set(ключ, [в])
  }
  return [...группы.values()]
}

/** Серия одной строкой: ближайшая встреча, остальные — по нажатию. */
export function SeriesRow({ meetings, companyId, onChanged }: {
  meetings: conf.ConfMeeting[]
  companyId: string
  onChanged: () => void
}) {
  const [раскрыта, setРаскрыта] = useState(false)
  const [первая, ...остальные] = meetings
  if (!остальные.length) {
    return <TalkRow meeting={первая} companyId={companyId} onChanged={onChanged} />
  }
  return (
    <>
      <TalkRow meeting={первая} companyId={companyId} onChanged={onChanged}
        rest={остальные} expanded={раскрыта} onToggle={() => setРаскрыта(р => !р)} />
      {раскрыта && остальные.map(в => (
        <TalkRow key={в.id} meeting={в} companyId={companyId} onChanged={onChanged} />
      ))}
    </>
  )
}

/** Строка конференции: название, мета под ним, действие справа. */
export function TalkRow({ meeting, companyId, onChanged, rest = [], expanded = false, onToggle }: {
  meeting: conf.ConfMeeting
  companyId: string
  onChanged: () => void
  /** Остальные встречи той же серии, свёрнутые под эту строку. */
  rest?: conf.ConfMeeting[]
  expanded?: boolean
  onToggle?: () => void
}) {
  const [итог, setИтог] = useState(meeting.session?.note ?? '')
  // Карточка — та же, что у встречи в календаре: конференция и есть встреча
  // календаря, и второй экран с её участниками, повесткой и повтором расходился
  // бы с первым. Раньше из строки можно было только войти: кто позван, что в
  // повестке и до какого числа серия, было не узнать (вопрос МАГа 14.10.2026).
  const [карточка, setКарточка] = useState(false)
  const событие = useQuery({
    queryKey: ['calendar-event', companyId, meeting.id],
    queryFn: () => workService.getEvent(companyId, meeting.id),
    enabled: карточка, retry: false,
  })
  const сессия = meeting.session
  // Прошла — по факту, а не по часам календаря: закрытая в своё время
  // конференция окончена, даже если её час ещё идёт. Иначе в «Истории» у неё
  // стояла кнопка входа и не было поля итога (проверка 13.10.2026). Вход до
  // срока встречу не закрывает — как и на сервере.
  const прошла = new Date(meeting.ends_at) < new Date()
    || (!!сессия?.ended_at && new Date(сессия.ended_at) >= new Date(meeting.starts_at))
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
  // Свёрнутая серия отвечает разом: на планёрку по четвергам ходят или не ходят,
  // а не решают про каждый четверг отдельно. Раскрыл — отвечаешь по одной.
  const разом = expanded ? [] : rest.filter(в => в.my_response === 'pending' && !в.organizer_is_me)
  const ответ = useMutation({
    mutationFn: (что: 'accepted' | 'declined') => Promise.all(
      [meeting, ...разом].map(в => conf.respond(companyId, в.id, что))),
    onSuccess: (_д, что) => {
      toast.success(что === 'accepted' ? 'Записал: будете' : 'Записал: не сможете',
        разом.length ? { description: `На все встречи серии: ${разом.length + 1}` } : undefined)
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
    // Карточку открывает вся строка, а не слово в мета-строке: искать ссылку
    // «карточка» среди дат и фамилий неудобно (замечание МАГа 14.10.2026).
    // Кнопки, ссылки и поля внутри строки делают своё — их нажатие карточку не
    // открывает. Окно карточки рисуется порталом, но события React всплывают и
    // через него, поэтому нажатия внутри окна тоже отсекаем.
    <div onClick={(e) => {
      if ((e.target as HTMLElement).closest('button, a, input, textarea, select, label, [role="dialog"]')) return
      setКарточка(true)
    }}
      className="-mx-2 cursor-pointer rounded-md border-b border-border/60 px-2 py-3 transition-colors last:border-0 hover:bg-accent/40">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {meeting.live && (
          <span className="flex items-center gap-1.5 text-xs font-medium text-success">
            <Circle className="h-2.5 w-2.5 fill-current" />идёт
          </span>
        )}
        <button type="button" onClick={() => setКарточка(true)}
          title="Открыть карточку: участники, повестка, материалы"
          className="rounded-sm text-left font-medium underline-offset-4 hover:underline">
          {meeting.title}
        </button>
        {!!meeting.papers && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground"
            title="Материалы к встрече — в карточке">
            <Paperclip className="h-3.5 w-3.5" />материалы: {meeting.papers}
          </span>
        )}
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
          <Button variant="ghost" size="sm" className="h-8 px-1.5"
            title="Открыть карточку" aria-label={`Открыть карточку: ${meeting.title}`}
            onClick={() => setКарточка(true)}>
            {событие.isFetching ? <Loader2 className="h-4 w-4 animate-spin" />
              : <ChevronRight className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {зовут && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1.5">
          <UserPlus className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs">
            {разом.length ? `Вас позвали на серию встреч: ${разом.length + 1}. Придёте?`
              : 'Вас позвали. Придёте?'}
          </span>
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
        {rest.length > 0 && (
          <>
            {' · '}
            <button type="button" onClick={onToggle} aria-expanded={expanded}
              className="text-primary underline-offset-2 hover:underline">
              {expanded ? 'свернуть серию'
                : `и ещё ${rest.length} до ${new Date(rest[rest.length - 1].starts_at)
                  .toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}`}
            </button>
          </>
        )}
      </p>

      {карточка && событие.isError && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          Карточка не открылась — встречу могли отменить или закрыть от вас.{' '}
          <button type="button" className="underline" onClick={() => setКарточка(false)}>Понятно</button>
        </p>
      )}
      {карточка && событие.data && (
        <EventDialog companyId={companyId} event={событие.data} startAt={null}
          onClose={() => setКарточка(false)} onChanged={onChanged} />
      )}

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

// Те же правила, что у встречи календаря: повторения создаёт планировщик серий.
const ПОВТОРЫ: Record<string, conf.NewMeeting['recurrence']> = {
  none: null,
  daily: { mode: 'daily' },
  weekly: { mode: 'weekly' },
  biweekly: { mode: 'weekly', interval: 2 },
  monthly: { mode: 'monthly' },
}

/** Окно созыва: тема, время, кого зовём, чем зовём. */
export function NewTalkDialog({ companyId, plan = false, onClose, onCreated }: {
  companyId: string
  /** Открыть сразу на назначении по времени, а не на «прямо сейчас». */
  plan?: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [тема, setТема] = useState('')
  const [сейчас, setСейчас] = useState(!plan)
  const [повтор, setПовтор] = useState('none')
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
      recurrence: сейчас ? null : ПОВТОРЫ[повтор],
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
        className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg md:max-w-4xl">
        <DialogHeader className="shrink-0 border-b border-border px-6 py-4">
          <DialogTitle>{сейчас ? 'Начать конференцию' : 'Назначить конференцию'}</DialogTitle>
          <DialogDescription id="conf-help">
            Конференция встаёт в календарь пространства, участников зовём в чат, а
            при желании и письмом.
          </DialogDescription>
        </DialogHeader>

        {/* На широком экране — две колонки: слева о чём, когда и кому видно, справа
            кого зовём. Одной колонкой окно не помещалось по высоте, и кнопка «Начать»
            с настройками видимости уезжала под прокрутку. Список людей тянется на
            высоту левой колонки, а не задаёт её: basis-0, не flex-1 — у того основа 0%, и при неопределённой высоте она считается по содержимому. На телефоне порядок
            прежний: расстановка по строкам действует только с md. */}
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-4 md:grid md:grid-cols-2 md:gap-x-8 md:gap-y-5 md:space-y-0">
          <div className="space-y-1.5 md:col-start-1 md:row-start-1">
            <Label htmlFor="conf-title">О чём</Label>
            <Input id="conf-title" value={тема} onChange={e => setТема(e.target.value)}
              placeholder="Разбор смены, приёмка работ, планёрка"
              className="text-base sm:text-sm" />
            <p className="text-xs text-muted-foreground">
              Тема встаёт в заголовок конференции, в приглашение и в историю. Без неё
              через месяц в списке будет строка с одной вашей фамилией.
            </p>
          </div>

          <div className="space-y-2 md:col-start-1 md:row-start-2">
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
              {!сейчас && (
                <select value={повтор} aria-label="Повторять"
                  onChange={e => setПовтор(e.target.value)}
                  className="h-9 rounded-md border border-input bg-background px-2 text-base sm:text-sm">
                  <option value="none">Не повторять</option>
                  <option value="daily">Каждый день</option>
                  <option value="weekly">Каждую неделю</option>
                  <option value="biweekly">Раз в две недели</option>
                  <option value="monthly">Каждый месяц</option>
                </select>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Конференция встаёт в календарь пространства и занимает это время у всех,
              кого позвали.
            </p>
          </div>

          <div className="flex min-h-0 flex-col gap-2 md:col-start-2 md:row-span-3 md:row-start-1">
            <div className="flex items-baseline justify-between">
              <Label htmlFor="conf-people">Кого зовём</Label>
              {кого.length > 0 && (
                <span className="text-xs text-muted-foreground">выбрано {кого.length}</span>
              )}
            </div>
            <Input id="conf-people" value={поиск} onChange={e => setПоиск(e.target.value)}
              placeholder="Имя сотрудника" className="text-base sm:text-sm" />
            <div className="max-h-44 overflow-y-auto rounded-md border border-border px-2 md:h-0 md:max-h-none md:min-h-44 md:grow md:basis-0">
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

          <div className="space-y-1.5 md:col-start-2 md:row-start-4">
            <Label htmlFor="conf-guests">Внешние участники</Label>
            <Textarea id="conf-guests" value={внешние} onChange={e => setВнешние(e.target.value)}
              placeholder="почта через запятую" rows={2} className="text-base sm:text-sm" />
            <p className="text-xs text-muted-foreground">
              Им уходит письмо со ссылкой и конференцией для их календаря. Учётной
              записи в пространстве гость не получает.
            </p>
          </div>

          <div className="space-y-1.5 rounded-md border border-border p-3 md:col-start-1 md:row-start-3">
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

          <div className="space-y-1.5 rounded-md border border-border p-3 md:col-start-1 md:row-start-4">
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
