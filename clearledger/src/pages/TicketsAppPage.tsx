/**
 * Приложение «Заявки» — трекер пространства (docs/TICKETS.md ecosystem-deploy).
 *
 * Три раздела: «Заявки» (работа), «Регламент» (периодические задачи движка
 * Поддержки), «Аналитика» (срез руководителя: сколько и где стоит работа,
 * «у кого мяч»). Движок один — контур Поддержки; здесь витрина пространства.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpRight, CalendarClock, ClipboardList, BarChart3, Loader2, MessageCircle,
  Plus, RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import * as ticketsService from '@/services/ticketsService'
import type { SpaceTicket, TicketScope } from '@/services/ticketsService'
import { ensureTicketRoom } from '@/services/chatService'
import { listSpaceObjects } from '@/services/spaceObjectsService'

const nf = new Intl.NumberFormat('ru-RU')
const dt = (s: string | null) => (s ? new Date(s).toLocaleDateString('ru-RU') : '—')
const dtT = (s: string | null) => (s ? new Date(s).toLocaleString('ru-RU',
  { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—')

/** «У кого мяч» — главный индикатор строки: где работа стоит прямо сейчас. */
const RESP_LABEL: Record<string, string> = {
  internal: 'у нас', vendor: 'у внешних', external: 'у внешних',
  customer: 'у заявителя', client: 'у заявителя',
}
const STATUS_LABEL: Record<string, string> = {
  new: 'новая', in_progress: 'в работе', waiting_customer: 'ждёт заявителя',
  resolved: 'решена', closed: 'закрыта', cancelled: 'отменена',
}
const PRIORITY_TONE: Record<string, string> = {
  critical: 'text-red-600 dark:text-red-400',
  high: 'text-amber-600 dark:text-amber-400',
}

type Section = 'work' | 'schedule' | 'analytics'

export function TicketsAppPage() {
  const { company } = useCompany()
  const [section, setSection] = useState<Section>('work')

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Заявки</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Работа пространства: от постановки до закрытия по маршруту. Исполняют —
            в Поддержке, здесь ставят, следят и видят картину целиком.
          </p>
        </div>
        <Tabs value={section} onValueChange={(v) => setSection(v as Section)}>
          <TabsList variant="line" className="h-9">
            <TabsTrigger value="work"><ClipboardList className="mr-1.5 h-3.5 w-3.5" />Заявки</TabsTrigger>
            <TabsTrigger value="schedule"><CalendarClock className="mr-1.5 h-3.5 w-3.5" />Регламент</TabsTrigger>
            <TabsTrigger value="analytics"><BarChart3 className="mr-1.5 h-3.5 w-3.5" />Аналитика</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {section === 'work' && <WorkSection companyId={company.id} />}
      {section === 'schedule' && <ScheduleSection companyId={company.id} />}
      {section === 'analytics' && <AnalyticsSection companyId={company.id} />}
    </div>
  )
}

/* ── Раздел «Заявки»: список + создание ──────────────────────────────── */

function WorkSection({ companyId }: { companyId: string }) {
  const [scope, setScope] = useState<TicketScope>('open')
  // Фильтр по объекту живёт в URL: карточка объекта и «Офис» ссылаются на
  // /tickets?object=<id> — список открывается уже суженным.
  const [params, setParams] = useSearchParams()
  const objectId = params.get('object') ?? ''
  const setObjectId = (v: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    if (v) n.set('object', v); else n.delete('object')
    return n
  }, { replace: true })
  const objectsQ = useQuery({
    queryKey: ['space-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const q = useQuery({
    queryKey: ['space-tickets', companyId, scope, objectId],
    queryFn: () => ticketsService.listTickets(companyId, scope, objectId || undefined),
    placeholderData: keepPreviousData,
  })
  const tickets = q.data?.tickets ?? []
  const [openTicket, setOpenTicket] = useState<SpaceTicket | null>(null)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={scope} onValueChange={(v) => setScope(v as TicketScope)}>
          <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="open">Активные</SelectItem>
            <SelectItem value="mine">Мои</SelectItem>
            <SelectItem value="closed">Завершённые</SelectItem>
            <SelectItem value="all">Все</SelectItem>
          </SelectContent>
        </Select>
        <Select value={objectId || 'all'} onValueChange={(v) => setObjectId(v === 'all' ? '' : v)}>
          <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue placeholder="Объект" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все объекты</SelectItem>
            {(objectsQ.data ?? []).map((o) => (
              <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-[11px] text-muted-foreground">заявок: {nf.format(tickets.length)}</span>
        <span className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', q.isFetching && 'animate-spin')} />Обновить
          </Button>
          <CreateTicketDialog companyId={companyId} onCreated={() => q.refetch()} />
        </span>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка заявок…
        </div>
      ) : q.isError ? (
        <div className="rounded-lg border p-6 text-center text-sm">
          <p className="text-destructive">Не удалось загрузить заявки</p>
          <Button variant="outline" size="sm" className="mt-2 h-8" onClick={() => q.refetch()}>Повторить</Button>
        </div>
      ) : tickets.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          {scope === 'open'
            ? 'Активных заявок нет. Поставьте первую — кнопка «Создать заявку».'
            : 'Под этот фильтр заявок нет.'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[1000px] text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <Th>№</Th><Th>Заявка</Th><Th>Объект</Th><Th>Стадия</Th>
                <Th>Исполнитель</Th><Th>У кого мяч</Th><Th>Срок SLA</Th><Th>Обновлена</Th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => <TicketRow key={t.id} t={t} onOpen={() => setOpenTicket(t)} />)}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">
        Строка открывает карточку заявки — там обсуждение и точка эскалации.
        Зеркальные заявки внешних систем (HubEx и др.) показываются наравне со своими —
        помечены значком системы. Их ведёт внешняя система, здесь виден ход.
      </p>

      <Sheet open={!!openTicket} onOpenChange={(v) => { if (!v) setOpenTicket(null) }}>
        <SheetContent side="right" className="w-full p-0 sm:max-w-lg">
          <SheetTitle className="sr-only">Карточка заявки</SheetTitle>
          <SheetDescription className="sr-only">Детали, обсуждение и эскалация</SheetDescription>
          {openTicket && <TicketCard id={openTicket.id} companyId={companyId} />}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function TicketRow({ t, onOpen }: { t: SpaceTicket; onOpen: () => void }) {
  return (
    <tr
      tabIndex={0}
      aria-haspopup="dialog"
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
      className="cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
      <Td className="whitespace-nowrap font-medium">{t.number ?? '—'}</Td>
      <Td>
        <div className="font-medium text-foreground">{t.title}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span>{STATUS_LABEL[t.status] ?? t.status}</span>
          {t.priority && (t.priority === 'high' || t.priority === 'critical') && (
            <span className={PRIORITY_TONE[t.priority]}>
              {t.priority === 'critical' ? 'критично' : 'срочно'}
            </span>
          )}
          {t.category && <span>· {t.category}</span>}
          {t.external_system && (
            <Badge variant="outline" className="h-4 px-1 text-[10px] uppercase">{t.external_system}</Badge>
          )}
        </div>
      </Td>
      <Td>{t.object ?? '—'}</Td>
      <Td>
        {t.stage ? (
          <span className="whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px]"
                style={t.stage_color ? { borderColor: t.stage_color, color: t.stage_color } : undefined}>
            {t.stage}
          </span>
        ) : <span className="text-muted-foreground">—</span>}
      </Td>
      <Td>{t.assignee ?? <span className="text-muted-foreground">не назначен</span>}</Td>
      <Td>
        {t.responsibility
          ? <span>{RESP_LABEL[t.responsibility] ?? t.responsibility}</span>
          : <span className="text-muted-foreground">—</span>}
      </Td>
      <Td className={cn('whitespace-nowrap', t.sla_breached && 'font-medium text-red-600 dark:text-red-400')}>
        {t.sla_breached ? `просрочен · ${dt(t.sla_deadline)}` : dt(t.sla_deadline)}
      </Td>
      <Td className="whitespace-nowrap text-muted-foreground">{dtT(t.updated_at)}</Td>
    </tr>
  )
}

/** Карточка заявки: детали + «Обсудить» (скрытый чат заявки) + «Из обсуждения». */
function TicketCard({ id, companyId }: { id: string; companyId: string }) {
  const { openInteraction } = useSupportContext()
  const q = useQuery({
    queryKey: ['space-ticket', id, companyId],
    queryFn: () => ticketsService.ticketDetails(id, companyId),
  })
  // Чат заявки создаётся при первом «Обсудить» и дальше просто открывается.
  // В общем списке чатов его нет — вход только отсюда (решение МАГа).
  const discuss = useMutation({
    mutationFn: () => ensureTicketRoom(id),
    onSuccess: (room) => openInteraction('chat', `room:${room.id}`),
    onError: (e) => toast.error(`Не удалось открыть чат заявки: ${(e as Error).message}`),
  })
  const t = q.data

  if (q.isLoading) {
    return <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Загрузка заявки…</div>
  }
  if (!t) {
    return <div className="p-6 text-sm text-destructive">Не удалось загрузить заявку</div>
  }
  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold">{t.number ?? 'Заявка'}</span>
          {t.stage && (
            <span className="rounded-md border px-1.5 py-0.5 text-[11px]"
              style={t.stage_color ? { borderColor: t.stage_color, color: t.stage_color } : undefined}>
              {t.stage}
            </span>
          )}
          {t.external_system && (
            <Badge variant="outline" className="h-4 px-1 text-[10px] uppercase">{t.external_system}</Badge>
          )}
        </div>
        <div className="mt-1 text-sm">{t.title}</div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4 text-sm">
        {/* Обсуждение — первым: заявка живёт разговором. */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" className="h-8" disabled={discuss.isPending}
            onClick={() => discuss.mutate()}>
            {discuss.isPending
              ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              : <MessageCircle className="mr-1.5 h-3.5 w-3.5" />}
            Обсудить
          </Button>
          {t.origin_room && (
            <button type="button"
              onClick={() => openInteraction('chat', `room:${t.origin_room!.room_id}`)}
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
              <ArrowUpRight className="h-3 w-3" />
              Создана из обсуждения «{t.origin_room.room_name}»
            </button>
          )}
        </div>

        {t.description && (
          <p className="whitespace-pre-wrap text-sm text-foreground/90">{t.description}</p>
        )}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <Fact label="Статус" value={STATUS_LABEL[t.status] ?? t.status} />
          <Fact label="Срочность"
            value={({ low: 'низкая', medium: 'обычная', high: 'срочная', critical: 'критичная' } as Record<string, string>)[t.priority] ?? t.priority}
            tone={PRIORITY_TONE[t.priority]} />
          <Fact label="Объект" value={t.object ?? '—'} />
          <Fact label="Категория" value={t.category ?? '—'} />
          <Fact label="Исполнитель" value={t.assignee ?? 'не назначен'} />
          <Fact label="У кого мяч" value={t.responsibility ? (RESP_LABEL[t.responsibility] ?? t.responsibility) : '—'} />
          <Fact label="Автор" value={t.author ?? '—'} />
          <Fact label="Срок SLA"
            value={t.sla_breached ? `просрочен · ${dt(t.sla_deadline)}` : dt(t.sla_deadline)}
            tone={t.sla_breached ? 'text-red-600 dark:text-red-400' : undefined} />
          <Fact label="Создана" value={dtT(t.created_at)} />
          <Fact label="Обновлена" value={dtT(t.updated_at)} />
        </dl>

        {/* Эскалация по штатной структуре: кому поднимать, если работа стоит —
            сначала начальнику подразделения исполнителя, не сразу директору. */}
        {t.escalation && (
          <p className="rounded-lg border border-border/70 bg-card/60 px-3 py-2 text-xs text-muted-foreground">
            Эскалация: <span className="text-foreground">{t.escalation.to}</span>
            {t.escalation.department ? ` — руководитель «${t.escalation.department}»` : ''}
          </p>
        )}
      </div>
    </div>
  )
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('mt-0.5 text-foreground', tone)}>{value}</dd>
    </div>
  )
}

function CreateTicketDialog({ companyId, onCreated }: { companyId: string; onCreated: () => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [objectId, setObjectId] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('medium')

  const objectsQ = useQuery({
    queryKey: ['space-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const objects = useMemo(
    () => (objectsQ.data ?? []).filter((o) => o.status !== 'closed'),
    [objectsQ.data])

  const reset = () => { setObjectId(''); setTitle(''); setDescription(''); setPriority('medium') }
  const create = useMutation({
    mutationFn: () => ticketsService.createTicket({
      companyId, objectId, description: description.trim(),
      title: title.trim() || undefined, priority,
    }),
    onSuccess: () => {
      toast.success('Заявка создана и пошла по маршруту')
      qc.invalidateQueries({ queryKey: ['space-tickets'] })
      setOpen(false); reset(); onCreated()
    },
    onError: (e) => toast.error(`Не удалось создать заявку: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset() }}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-8"><Plus className="mr-1.5 h-3.5 w-3.5" />Создать заявку</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Новая заявка</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Объект</Label>
            <Select value={objectId} onValueChange={setObjectId}>
              <SelectTrigger><SelectValue placeholder={
                objectsQ.isLoading ? 'Загрузка объектов…' : 'Выберите объект'} /></SelectTrigger>
              <SelectContent>
                {objects.map((o) => (
                  <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">
              Заявка привязывается к объекту пространства — по нему находят исполнителя.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Заголовок</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="Коротко: что случилось" maxLength={300} />
          </div>
          <div className="space-y-1.5">
            <Label>Описание</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="Что случилось, где, с какого момента. Чем подробнее — тем быстрее возьмут в работу."
              rows={4} maxLength={4000} />
          </div>
          <div className="space-y-1.5">
            <Label>Срочность</Label>
            <Select value={priority} onValueChange={setPriority}>
              <SelectTrigger className="w-[220px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Низкая — когда будет время</SelectItem>
                <SelectItem value="medium">Обычная</SelectItem>
                <SelectItem value="high">Срочная — мешает работе</SelectItem>
                <SelectItem value="critical">Критичная — работа стоит</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!objectId || description.trim().length < 3 || create.isPending}
            onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── Раздел «Регламент»: периодические задачи ────────────────────────── */

function ScheduleSection({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['space-ticket-schedules', companyId],
    queryFn: () => ticketsService.listSchedules(companyId),
  })
  const rows = q.data?.schedules ?? []

  const period = (days: number) =>
    days % 90 === 0 ? `раз в ${days / 90 === 1 ? '' : `${days / 90} `}квартал${days / 90 > 1 ? 'а' : ''}`
      : days % 30 === 0 ? `раз в ${days / 30 === 1 ? '' : `${days / 30} `}мес.`
        : days % 7 === 0 ? `раз в ${days / 7 === 1 ? 'неделю' : `${days / 7} нед.`}`
          : `раз в ${days} дн.`

  if (q.isLoading) {
    return <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Загрузка регламента…</div>
  }
  return (
    <div className="space-y-3">
      {rows.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Регламентных задач пока нет. Это работы по расписанию — ТО, поверки, отчёты:
          движок сам ставит заявку к сроку, исполнителю остаётся выполнить.
          Настраиваются в Поддержке (раздел «Регламент ТО»).
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <Th>Задача</Th><Th>Объект</Th><Th>Периодичность</Th>
                <Th>Следующий срок</Th><Th>Категория</Th><Th>Состояние</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className={cn('border-t', !s.is_active && 'opacity-50')}>
                  <Td>
                    <div className="font-medium text-foreground">{s.name}</div>
                    {s.description && <div className="mt-0.5 text-[11px] text-muted-foreground">{s.description}</div>}
                  </Td>
                  <Td>{s.object ?? 'все объекты'}</Td>
                  <Td>{period(s.interval_days)}</Td>
                  <Td className="whitespace-nowrap">{dt(s.next_due_date)}</Td>
                  <Td>{s.category ?? '—'}</Td>
                  <Td>{s.is_active ? 'действует' : 'выключена'}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── Раздел «Аналитика»: срез руководителя ───────────────────────────── */

/**
 * Срез руководителя по заявкам. Экспортирован, потому что тот же разбор открывает
 * «Пульс» в разделе «Бизнес → Поддержка»: показываем ЧУЖУЮ витрину как есть, а не
 * пишем её вторую копию (ecosystem-deploy/docs/PULSE.md §6, единый словарь метрик).
 */
export function AnalyticsSection({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['space-tickets-summary', companyId],
    queryFn: () => ticketsService.ticketsSummary(companyId),
  })
  if (q.isLoading) {
    return <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Считаем срез…</div>
  }
  const s = q.data
  if (!s) {
    return <div className="rounded-lg border p-6 text-center text-sm">
      <p className="text-destructive">Не удалось загрузить срез</p>
      <Button variant="outline" size="sm" className="mt-2 h-8" onClick={() => q.refetch()}>Повторить</Button>
    </div>
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="В работе" value={nf.format(s.open)} />
        <Stat label="Нарушают SLA" value={nf.format(s.sla_breached)}
          tone={s.sla_breached ? 'text-red-600 dark:text-red-400' : undefined} />
        <Stat label="За неделю" value={`+${nf.format(s.created_7d)} / −${nf.format(s.closed_7d)}`}
          hint="создано / закрыто" />
        <Stat label="За месяц" value={`+${nf.format(s.created_30d)} / −${nf.format(s.closed_30d)}`}
          hint="создано / закрыто" />
        <Stat label="Баланс месяца" value={nf.format(s.created_30d - s.closed_30d)}
          hint="создано минус закрыто"
          tone={s.created_30d > s.closed_30d ? 'text-amber-600 dark:text-amber-400' : undefined} />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Breakdown title="У кого мяч" hint="где стоит работа прямо сейчас"
          rows={(s.by.responsibility ?? []).map((r) => ({ ...r, key: RESP_LABEL[r.key] ?? r.key }))} />
        <Breakdown title="По подразделениям" hint="нагрузка по штатной структуре"
          rows={s.by.department ?? []} />
        <Breakdown title="По исполнителям" hint="активные заявки на человеке"
          rows={s.by.assignee ?? []} />
        <Breakdown title="По категориям" hint="активные, по видам работ"
          rows={s.by.category ?? []} />
      </div>
      <p className="text-[11px] text-muted-foreground">
        Срез считается по активным заявкам пространства, включая зеркала внешних систем.
        «У кого мяч» — чья сторона держит заявку: наша, внешняя компания или заявитель.
      </p>
    </div>
  )
}

function Stat({ label, value, hint, tone }: {
  label: string; value: string; hint?: string; tone?: string
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('mt-0.5 text-lg font-semibold tabular-nums', tone)}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

function Breakdown({ title, hint, rows }: {
  title: string; hint: string; rows: { key: string; count: number }[]
}) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-sm font-medium">{title}</div>
      <div className="text-[11px] text-muted-foreground">{hint}</div>
      <div className="mt-2 space-y-1.5">
        {rows.length === 0 && <div className="text-xs text-muted-foreground">Активных заявок нет</div>}
        {rows.map((r) => (
          <div key={r.key} className="flex items-center gap-2 text-xs">
            <span className="w-36 truncate" title={r.key}>{r.key}</span>
            <span className="h-2 rounded bg-primary/60" style={{ width: `${(r.count / max) * 100}%`, minWidth: 4 }} />
            <span className="tabular-nums text-muted-foreground">{nf.format(r.count)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="p-2.5 text-left font-medium">{children}</th>
}
function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('p-2.5 align-top', className)}>{children}</td>
}

export default TicketsAppPage
