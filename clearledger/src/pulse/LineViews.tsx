/**
 * «Пульс» → «Бизнес» → «Моя линия» и «Смена»: контакт-центр вблизи.
 *
 * «Обращения» отвечают руководителю компании и меряют неделю. Людям на линии
 * нужен другой горизонт — текущая минута, и разные вопросы:
 *
 * - оператору: что на мне сейчас, что уже просрочено, успеваю ли по норме;
 * - руководителю смены: кто вышел, у кого очередь упёрлась, сколько ждут.
 *
 * Оба экрана — витрина на чтение: работа ведётся в рабочем месте Поддержки, и
 * ссылка туда стоит внизу. Второго набора метрик контакт-центра здесь нет —
 * цифры считаются по тем же таблицам, что и «Обращения» (PULSE.md §6).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpRight, CalendarClock, Clock, Coffee, Headphones, Inbox, LogIn, LogOut,
  MessageCircle, Phone, PhoneMissed, Play,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import { createRoom } from '@/services/chatService'
import { getPulseMyLine, getPulseShift, pulseLineAction } from './pulseService'
import type { LineAction, PulseShiftAgent } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum, plural } from './parts'

/** Состояния оператора называются так же, как в самой Поддержке. */
const STATE: Record<string, { label: string; dot: string }> = {
  available: { label: 'Готов', dot: 'bg-emerald-500' },
  busy: { label: 'В разговоре', dot: 'bg-blue-500' },
  acw: { label: 'Разбор', dot: 'bg-amber-500' },
  not_ready: { label: 'Перерыв', dot: 'bg-amber-500' },
  offline: { label: 'Не в сети', dot: 'bg-muted-foreground/40' },
}

const state = (key: string) => ({ key, ...(STATE[key] ?? STATE.offline) })

/** «14:35» — время ответа читают глазами, а не считают в уме. */
const at = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'

/** Сколько прошло: «12 мин», «3 ч». Ноль и будущее — прочерк. */
function ago(s: string | null | undefined): string {
  if (!s) return '—'
  const min = Math.floor((Date.now() - new Date(s).getTime()) / 60_000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин`
  const h = Math.floor(min / 60)
  return h < 24 ? `${h} ч` : `${Math.floor(h / 24)} дн`
}

function NotAvailable({ reason }: { reason?: string }) {
  return (
    <Card className="border-dashed py-0">
      <CardContent className="p-4 text-xs text-muted-foreground">
        {reason === 'not_in_support'
          ? 'Вас нет среди сотрудников контакт-центра — показывать нечего. '
            + 'Состав ведёт руководитель смены в «Поддержке».'
          : 'Контакт-центр в пространстве не подключён — показывать пока нечего.'}
      </CardContent>
    </Card>
  )
}

export function MyLineView() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['pulse-my-line', company.id],
    queryFn: () => getPulseMyLine(company.id),
    // Своя очередь меняется быстрее любой другой цифры «Пульса»: пока человек
    // смотрит на экран, ему уже могли назначить обращение.
    refetchInterval: 60_000,
  })
  const d = q.data

  /**
   * Действие линии. Правила живут в Поддержке, поэтому здесь только отправка и
   * человеческий разбор отказа: «передайте активные обращения» — не ошибка, а
   * условие, и второй нажатой кнопкой человек соглашается передать их очереди.
   */
  const act = useMutation({
    mutationFn: (body: { action: LineAction; state?: string; handover?: boolean; note?: string }) =>
      pulseLineAction(company.id, body),
    onSuccess: (res, body) => {
      if (body.action === 'next') {
        toast.success(res.taken
          ? `Взято: ${res.taken.subject || 'обращение'}`
          : 'В очереди сейчас пусто')
      } else if (body.action === 'shift_end' && res.handed) {
        toast.success(`Смена закрыта, ${res.handed} обращений передано очереди`)
      }
      qc.invalidateQueries({ queryKey: ['pulse-my-line', company.id] })
    },
    onError: (e: Error, body) => {
      const text = e.message || 'Не получилось'
      if (body.action === 'shift_end' && text.includes('передайте активные')) {
        toast.error('На вас есть незакрытые обращения', {
          description: 'Их можно вернуть в очередь — тогда их возьмёт другой оператор.',
          action: {
            label: 'Передать очереди',
            onClick: () => act.mutate({
              action: 'shift_end', handover: true, note: 'Смена закрыта из «Пульса»',
            }),
          },
        })
        return
      }
      toast.error(text)
    },
  })
  const busy = act.isPending

  if (q.isLoading) return <PulseLoading what="вашей линии" />
  if (q.isError) return <PulseError what="вашу линию" onRetry={() => q.refetch()} />
  if (!d) return null
  if (!d.available) return <NotAvailable reason={d.reason} />

  const st = state(d.shift?.state || 'offline')
  return (
    <div className="space-y-5">
      {/* Смена — первым: пока она не открыта, обращения не приходят вовсе, и
          пустые цифры ниже иначе читались бы как «сегодня тихо». */}
      <Card className={cn('py-0', !d.shift?.on_shift && 'border-amber-500/40 bg-amber-500/5')}>
        <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3 text-xs">
          <span className="flex items-center gap-1.5 font-medium text-foreground">
            <span className={cn('h-2 w-2 rounded-full', st.dot)} />{st.label}
          </span>
          <span className="text-muted-foreground">
            {d.shift?.on_shift ? `на смене с ${at(d.shift.since)}` : 'смена не открыта'}
          </span>
          {!!d.accepted_week && (
            <span className="text-muted-foreground">
              принято за неделю: <span className="font-semibold tabular-nums text-foreground">{fmtNum(d.accepted_week)}</span>
            </span>
          )}
          {/* Пульт: то, ради чего экран открывают с телефона. Разговор ведётся в
              рабочем месте, а вот выйти на линию, отойти и взять следующее нужно
              уметь отсюда — иначе человек, отошедший от компьютера, просто
              пропадает для очереди. */}
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            {d.shift?.on_shift ? (
              <>
                <Button size="sm" variant="secondary" disabled={busy}
                  onClick={() => act.mutate({ action: 'next' })}>
                  <Play className="h-3.5 w-3.5" />Взять следующее
                </Button>
                {st.key === 'not_ready' ? (
                  <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => act.mutate({ action: 'state', state: 'available' })}>
                    <Play className="h-3.5 w-3.5" />Готов
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => act.mutate({ action: 'state', state: 'not_ready' })}>
                    <Coffee className="h-3.5 w-3.5" />Перерыв
                  </Button>
                )}
                <Button size="sm" variant="ghost" disabled={busy}
                  onClick={() => act.mutate({ action: 'shift_end' })}>
                  <LogOut className="h-3.5 w-3.5" />Закончить смену
                </Button>
              </>
            ) : (
              <Button size="sm" disabled={busy}
                onClick={() => act.mutate({ action: 'shift_start' })}>
                <LogIn className="h-3.5 w-3.5" />Начать смену
              </Button>
            )}
          </span>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {(d.kpi ?? []).map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            На мне сейчас
          </h2>
          {d.queue_oldest && (
            <span className="text-[11px] text-muted-foreground">
              в очереди ждут с {at(d.queue_oldest)}
            </span>
          )}
        </div>
        {d.threads?.length ? (
          <Card className="py-0">
            <CardContent className="divide-y p-0">
              {d.threads.map((t) => {
                const late = !t.answered && t.due_at && new Date(t.due_at) < new Date()
                return (
                  <div key={t.id} className="flex items-center gap-3 px-3 py-2">
                    <Inbox className={cn('h-3.5 w-3.5 shrink-0',
                      late ? 'text-red-500' : 'text-muted-foreground')} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px]">{t.subject || t.contact || 'Без темы'}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {t.contact || '—'} · последнее сообщение {ago(t.last_at)} назад
                      </span>
                    </span>
                    {/* Срок ответа — то единственное, ради чего оператор открывает
                        этот список: он решает, за что браться первым. */}
                    <span className={cn('shrink-0 text-[11px] tabular-nums',
                      late ? 'font-semibold text-red-500' : 'text-muted-foreground')}>
                      {t.answered ? 'отвечено' : late ? 'просрочен' : `до ${at(t.due_at)}`}
                    </span>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed py-0">
            <CardContent className="p-4 text-xs text-muted-foreground">
              Ни одного обращения на вас не назначено — очередь разбирают в рабочем месте.
            </CardContent>
          </Card>
        )}
      </section>

      <a href="/support/" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
        Открыть рабочее место<ArrowUpRight className="h-3.5 w-3.5" />
      </a>
    </div>
  )
}

/** «Сегодня 09:00–18:00», «завтра 14:00» — график читают глазами. */
function when(iso: string): string {
  const d = new Date(iso)
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const day = new Date(d); day.setHours(0, 0, 0, 0)
  const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000)
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (diff === 0) return `сегодня ${time}`
  if (diff === 1) return `завтра ${time}`
  return `${d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })} ${time}`
}

const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

/** «2 мин 30 с» — длительность разговора. */
const dur = (sec: number) => (sec < 60 ? `${sec} с` : `${Math.floor(sec / 60)} мин`)

function AgentRow({ a }: { a: PulseShiftAgent }) {
  const st = state(a.state)
  const loaded = a.max > 0 && a.in_work >= a.max
  const { openInteraction } = useSupportContext()

  /** Написать человеку: личный чат пространства, а не второй мессенджер. */
  const write = useMutation({
    mutationFn: () => createRoom('direct', [a.core_user_id as string]),
    onSuccess: (room) => openInteraction('chat', `room:${room.id}`),
    onError: (e: Error) => toast.error(e.message || 'Не получилось открыть разговор'),
  })

  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <Headphones className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px]">
          {a.name}
          {a.duty === 'head' && (
            <span className="ml-1.5 text-[11px] text-muted-foreground">руководитель</span>
          )}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className={cn('h-1.5 w-1.5 rounded-full', st.dot)} />
          {st.label}
          {a.on_shift ? ` · на линии ${ago(a.since)}` : ' · смена не открыта'}
          {!a.on_shift && a.planned && ` · по графику ${when(a.planned.starts_at)}`}
        </span>
      </span>
      {/* Связаться — половина работы руководителя смены: увидел затор, написал
          или позвонил. Разговор идёт в чате пространства, звонок — с трубки. */}
      <span className="flex shrink-0 items-center gap-1">
        {a.core_user_id && (
          <button type="button" title="Написать в чат" disabled={write.isPending}
            onClick={() => write.mutate()}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
            <MessageCircle className="h-3.5 w-3.5" />
          </button>
        )}
        {a.phone && (
          <a href={`tel:${a.phone.replace(/[^+\d]/g, '')}`} title={`Позвонить: ${a.phone}`}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
            <Phone className="h-3.5 w-3.5" />
          </a>
        )}
      </span>
      {/* Нагрузка и просрочки — то, ради чего руководитель сюда смотрит:
          «у кого упёрлось» и «у кого горит», остальное можно не читать. */}
      <span className={cn('w-16 shrink-0 text-right text-sm font-semibold tabular-nums',
        loaded && 'text-amber-600 dark:text-amber-400')}>
        {a.in_work} из {a.max}
      </span>
      <span className={cn('hidden w-24 shrink-0 justify-end gap-1 text-[11px] md:flex',
        a.overdue ? 'text-red-500' : 'text-muted-foreground')}>
        <Clock className="h-3 w-3" />
        {a.overdue ? `${a.overdue} просроч.` : 'в сроке'}
      </span>
      <span className="hidden w-20 shrink-0 text-right text-[11px] text-muted-foreground lg:block">
        закрыл {a.closed_today}
      </span>
    </div>
  )
}

type ShiftTab = 'now' | 'plan' | 'calls'

const TABS: { key: ShiftTab; label: string }[] = [
  { key: 'now', label: 'Сейчас' },
  { key: 'plan', label: 'График' },
  { key: 'calls', label: 'Звонки' },
]

export function ShiftView() {
  const { company } = useCompany()
  const { openInteraction } = useSupportContext()
  // Три вопроса руководителя смены идут по очереди: что происходит сейчас, кто
  // выходит дальше, дышит ли линия. Это виды одного предмета, поэтому вкладки, а
  // не три пункта меню.
  const [tab, setTab] = useState<ShiftTab>('now')
  const q = useQuery({
    queryKey: ['pulse-shift', company.id],
    queryFn: () => getPulseShift(company.id),
    refetchInterval: 60_000,
  })
  const d = q.data

  if (q.isLoading) return <PulseLoading what="смены" />
  if (q.isError) return <PulseError what="состояние смены" onRetry={() => q.refetch()} />
  if (!d) return null
  if (!d.available) return <NotAvailable reason={d.reason} />

  const agents = d.agents ?? []
  const online = agents.filter((a) => a.on_shift)
  const offline = agents.filter((a) => !a.on_shift)
  const plan = d.plan ?? []
  const calls = d.calls ?? []
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
        {(d.kpi ?? []).map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <div className="flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)}
            className={cn('rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              tab === t.key ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
            {t.label}
            {t.key === 'plan' && plan.length > 0 && (
              <span className="ml-1.5 opacity-70">{plan.length}</span>
            )}
          </button>
        ))}
      </div>

      {tab === 'plan' && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Кто когда выходит · неделя вперёд
          </h2>
          {plan.length ? (
            <Card className="py-0"><CardContent className="divide-y p-0">
              {plan.map((p, i) => (
                <div key={`${p.user}-${p.starts_at}-${i}`} className="flex items-center gap-3 px-3 py-2">
                  <CalendarClock className={cn('h-3.5 w-3.5 shrink-0',
                    p.now ? 'text-emerald-500' : 'text-muted-foreground')} />
                  <span className="min-w-0 flex-1 truncate text-[13px]">{p.user}</span>
                  <span className="shrink-0 text-[11px] text-muted-foreground">
                    {p.duty === 'head' ? 'старший' : 'оператор'}
                  </span>
                  <span className={cn('shrink-0 text-[11px] tabular-nums',
                    p.now ? 'font-semibold text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>
                    {when(p.starts_at)}–{hhmm(p.ends_at)}
                  </span>
                </div>
              ))}
            </CardContent></Card>
          ) : (
            <Card className="border-dashed py-0">
              <CardContent className="p-4 text-xs text-muted-foreground">
                График на неделю не поставлен — смены ведутся в «Поддержке», раздел «Смены операторов».
              </CardContent>
            </Card>
          )}
        </section>
      )}

      {tab === 'calls' && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Последние звонки
          </h2>
          {calls.length ? (
            <Card className="py-0"><CardContent className="divide-y p-0">
              {calls.map((c, i) => (
                <div key={`${c.at}-${i}`} className="flex items-center gap-3 px-3 py-2">
                  {c.missed
                    ? <PhoneMissed className="h-3.5 w-3.5 shrink-0 text-red-500" />
                    : <Phone className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] tabular-nums">{c.phone || 'номер скрыт'}</span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {c.missed ? `не ответили · ждал ${dur(c.wait)}`
                        : `${c.operator || 'оператор'} · разговор ${dur(c.duration)}`}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                    {c.at ? when(c.at) : '—'}
                  </span>
                </div>
              ))}
            </CardContent></Card>
          ) : (
            <Card className="border-dashed py-0">
              <CardContent className="p-4 text-xs text-muted-foreground">
                Звонков не приходило — либо телефония ещё не подключена.
              </CardContent>
            </Card>
          )}
        </section>
      )}

      {tab === 'now' && d.queue_oldest && (
        <Card className="py-0">
          <CardContent className="p-3 text-xs text-muted-foreground">
            Самое давнее обращение в очереди ждёт с {at(d.queue_oldest)} — это {ago(d.queue_oldest)} без ответа.
          </CardContent>
        </Card>
      )}

      {tab === 'now' && (
      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          На линии · {online.length} {plural(online.length, 'человек', 'человека', 'человек')}
        </h2>
        {online.length ? (
          <Card className="py-0"><CardContent className="divide-y p-0">
            {online.map((a) => <AgentRow key={a.id} a={a} />)}
          </CardContent></Card>
        ) : (
          <Card className="border-amber-500/40 bg-amber-500/5 py-0">
            <CardContent className="p-4 text-xs">
              Смену не открыл никто. Обращения копятся в очереди, разбирать их некому.
            </CardContent>
          </Card>
        )}
      </section>
      )}

      {tab === 'now' && offline.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Сегодня не на линии
          </h2>
          <Card className="py-0"><CardContent className="divide-y p-0">
            {offline.map((a) => <AgentRow key={a.id} a={a} />)}
          </CardContent></Card>
        </section>
      )}

      {/* Общение — половина работы руководителя смены, и держать его в другом
          месте бессмысленно: чат пространства открывается панелью прямо здесь,
          «Трек» и рабочее место — соседними приложениями. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <button type="button" onClick={() => openInteraction('chat')}
          className="inline-flex min-h-9 items-center gap-1 text-primary hover:underline sm:min-h-0">
          <MessageCircle className="h-3.5 w-3.5" />Чаты смены
        </button>
        <a href="/docs/work" className="inline-flex min-h-9 items-center gap-1 text-primary hover:underline sm:min-h-0">
          Мои поручения в «Треке»<ArrowUpRight className="h-3.5 w-3.5" />
        </a>
        <a href="/support/" className="inline-flex min-h-9 items-center gap-1 text-primary hover:underline sm:min-h-0">
          Открыть смену в «Поддержке»<ArrowUpRight className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  )
}
