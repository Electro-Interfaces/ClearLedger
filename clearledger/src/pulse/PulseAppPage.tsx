/**
 * «Пульс» → «Экран дня» (ecosystem-deploy/docs/PULSE.md, волна В1).
 *
 * Два горизонта чтения: статус за 5 секунд (пилюля «N требуют внимания»), весь
 * экран за 60 без прокрутки. Каждая цифра — вход в разрез (лестница §2), каждая
 * карточка — к действию. Пусто — так и сказано: вмешательства не требуется.
 *
 * Подача — канон пространства: `Card`, `Badge`, альфа-шкала статусных цветов,
 * общая плитка показателя (`parts.tsx`). Своих примитивов «Пульс» не заводит.
 */
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, ArrowUpRight, CalendarClock, CheckCheck, ClipboardList, Database,
  Eye, MessageCircle, MoreHorizontal, ShieldCheck, SlidersHorizontal,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import {
  ackCard, getPulseAccepted, getPulseDay, type PulseCard, type PulseKpi,
} from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtDate, fmtNum, plural } from './parts'
import { SourcesView } from './SourcesView'
import { VisibilityView } from './VisibilityView'
import { TargetsView } from './TargetsView'
import { usePulseView } from './PulseLayout'

/** Дата данных словами: под цифрами видно, чему можно верить (правило №0). */
function asOfLabel(asOf: string | null, staleDays: number | null): string {
  if (!asOf) return 'данных о сессиях ещё нет'
  const d = new Date(asOf).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  if (staleDays != null && staleDays <= 1) return `данные сети на ${d}`
  return `данные сети на ${d} (${staleDays} дн назад)`
}

import { ViewsView } from './ViewsView'
import { ShowcaseView } from './ShowcaseView'

export function PulseAppPage() {
  const view = usePulseView('/pulse')
  if (view === 'accepted') return <AcceptedView />
  if (view === 'sources') return <SourcesPage />
  if (view === 'targets') return <TargetsPage />
  if (view === 'visibility') return <VisibilityPage />
  if (view === 'views') return <ViewsPage />
  if (view === 'showcase') return <ShowcasePage />
  return <TodayView />
}

/** Витрины: что показываем наружу. Собирает администратор компании. */
function ViewsPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <Eye className="h-5 w-5 text-primary" />Витрины
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          «Пульс», повёрнутый наружу: заказчику, владельцу и куратору со стороны нужна
          картина по своей теме без погружения в приложения. Витрина собирается из тех же
          блоков, что считает «Пульс», — второго набора цифр не заводим.
        </p>
      </div>
      <ViewsView />
    </div>
  )
}

/** Моя витрина — то, что собрали для меня. */
function ShowcasePage() {
  return <ShowcaseView />
}

/** Кто что видит — отбор картины для роли (в первую очередь для куратора). */
function VisibilityPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <Eye className="h-5 w-5 text-primary" />Кто что видит
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Что из картины открыто куратору и другим ролям пространства
        </p>
      </div>
      <VisibilityView />
    </div>
  )
}

/** Источники — вопрос, который стоит перед всеми остальными разделами. */
function SourcesPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <Database className="h-5 w-5 text-primary" />Источники
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Чему сегодня можно верить: когда какие данные приходили в последний раз
        </p>
      </div>
      <SourcesView />
    </div>
  )
}

/** Пороги эскалаций — заголовок экрана равен имени пункта (канон SPACE.md §4). */
function TargetsPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <SlidersHorizontal className="h-5 w-5 text-primary" />Пороги
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          С какого места считать, что пора вмешаться
        </p>
      </div>
      <TargetsView />
    </div>
  )
}

/* ── Пункт «Экран дня» ────────────────────────────────────────────────── */

function TodayView() {
  const { company } = useCompany()
  // Режим просмотра живёт в URL: ссылку на «как видит куратор» можно передать,
  // а обновление страницы из режима не выбрасывает.
  const [params, setParams] = useSearchParams()
  const asRole = params.get('as')
  const q = useQuery({
    queryKey: ['pulse-day', company.id, asRole],
    queryFn: () => getPulseDay(company.id, asRole),
    // Обновление раз в полторы минуты — realtime «Пульсу» не нужен (PULSE.md §6).
    refetchInterval: 90_000,
  })

  return (
    <div className="space-y-5">
      {/* Полоса режима с явным выходом: без неё легко забыть, что смотришь
          чужими глазами, и решить, что часть карточек пропала. */}
      {asRole && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2">
          <span className="flex items-center gap-2 text-xs">
            <Eye className="h-4 w-4 shrink-0 text-primary" />
            Смотрю глазами роли — видно только то, что ей открыто
          </span>
          <Button size="sm" variant="outline" className="h-9 shrink-0 sm:h-8"
            onClick={() => setParams((p) => {
              const n = new URLSearchParams(p)
              n.delete('as')
              return n
            }, { replace: true })}>
            Вернуться к своей картине
          </Button>
        </div>
      )}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Activity className="h-5 w-5 text-primary" />Экран дня
          </h1>
          {/* Экран объясняет себя сам: руководитель заходит раз в день и не должен
              вспоминать, что это за цифры и откуда. */}
          <p className="mt-0.5 text-xs text-muted-foreground">
            Что требует вмешательства сегодня и как идут дела
          </p>
        </div>
        {q.data && (
          <Badge variant="outline" className={cn('shrink-0',
            q.data.cards.length
              ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400'
              : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400')}>
            {q.data.cards.length
              ? `${q.data.cards.length} ${plural(q.data.cards.length, 'требует', 'требуют', 'требуют')} внимания`
              : 'всё спокойно'}
          </Badge>
        )}
      </div>

      {q.isLoading && <PulseLoading what="пульса" />}
      {q.isError && <PulseError what="пульс" onRetry={() => q.refetch()} />}

      {q.data && (
        <>
          <section className="space-y-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              Требуют вмешательства
            </h2>
            <CardsBlock cards={q.data.cards} companyId={company.id} />
          </section>

          <section className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                Как идут дела
              </h2>
              {/* Дата данных — рядом с цифрами, а не в шапке: она относится к ним. */}
              <span className="text-[11px] text-muted-foreground">
                {asOfLabel(q.data.as_of, q.data.stale_days)}
              </span>
            </div>
            <KpiRow kpi={q.data.kpi} />
          </section>
        </>
      )}
    </div>
  )
}

/* ── Эскалации: верх экрана. Пусто = «вмешательства не требуется» ─────── */

function CardsBlock({ cards, companyId }: { cards: PulseCard[]; companyId: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  // «Принято» — это «я видел сегодня». «Отложить» — обязательство вернуться:
  // карточка уходит с экрана на срок, но остаётся в «Принятом» с датой возврата,
  // и по её наступлении живое условие вернёт её само, если ничего не изменилось.
  const ack = useMutation({
    mutationFn: ({ key, days }: { key: string; days?: number }) =>
      ackCard(companyId, key, days),
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: ['pulse-day', companyId] })
      qc.invalidateQueries({ queryKey: ['pulse-accepted', companyId] })
      toast.success(v.days
        ? `Отложено — вернём через ${v.days} ${plural(v.days, 'день', 'дня', 'дней')}`
        : 'Принято — карточка снята до конца дня')
    },
    onError: () => toast.error('Не удалось снять карточку — попробуйте ещё раз'),
  })

  if (!cards.length) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="flex items-center gap-3 p-4">
          <ShieldCheck className="h-6 w-6 shrink-0 text-emerald-600 dark:text-emerald-400" />
          <div>
            <div className="text-sm font-medium">Вмешательства не требуется</div>
            <div className="text-xs text-muted-foreground">
              Ни одно правило не сработало — это нормальное состояние экрана.
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-2">
      {cards.map((c) => {
        const alert = c.level === 'alert'
        return (
          <Card key={c.key} className={cn('py-0 border-l-2',
            // Альфа-шкала пространства: один класс работает в обеих темах.
            alert
              ? 'border-red-500/40 border-l-red-500 bg-red-500/5'
              : 'border-amber-500/40 border-l-amber-500 bg-amber-500/5')}>
            <CardContent className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2">
                  {/* Уровень несёт не только цвет: иконка обязательна (PRODUCT.md). */}
                  <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0',
                    alert ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400')} />
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">{c.title}</div>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      {c.insight}
                    </p>
                  </div>
                </div>
                {c.count != null && (
                  <div className="shrink-0 text-base font-semibold tabular-nums">
                    {fmtNum(c.count)}
                  </div>
                )}
              </div>

              {/* Одно первичное действие, «Принято» рядом, остальное — под «⋯»:
                  до семи карточек × четыре кнопки давали 28 контролов в первом экране. */}
              <div className="mt-2.5 flex items-center gap-1.5">
                {c.link && (
                  <Button size="sm" className="h-9 sm:h-8" onClick={() => navigate(c.link!)}>
                    <ArrowUpRight className="mr-1 h-3.5 w-3.5" />Открыть
                  </Button>
                )}
                {/* На телефоне цели крупнее: 32 px против 28 — промах по «Принято»
                    стоит дорого, карточка уходит с экрана до конца дня. */}
                <Button size="sm" variant="outline" className="h-9 sm:h-8"
                  disabled={ack.isPending} onClick={() => ack.mutate({ key: c.key })}>
                  <CheckCheck className="mr-1 h-3.5 w-3.5" />Принято
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="ghost" className="ml-auto h-9 w-9 p-0 sm:h-8 sm:w-8"
                      aria-label="Ещё действия">
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => ack.mutate({ key: c.key, days: 3 })}>
                      <CalendarClock className="mr-2 h-3.5 w-3.5" />Вернуться через 3 дня
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => ack.mutate({ key: c.key, days: 7 })}>
                      <CalendarClock className="mr-2 h-3.5 w-3.5" />Вернуться через неделю
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => navigate('/messages')}>
                      <MessageCircle className="mr-2 h-3.5 w-3.5" />Обсудить в чате
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => navigate('/tickets')}>
                      <ClipboardList className="mr-2 h-3.5 w-3.5" />Поставить заявку
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

/* ── Строка KPI: каждая плитка — вход в свой разрез ───────────────────── */

function KpiRow({ kpi }: { kpi: PulseKpi[] }) {
  const navigate = useNavigate()
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
      {kpi.map((k) => (
        <KpiTile key={k.key} k={k}
          onOpen={k.link ? () => navigate(k.link!) : undefined} />
      ))}
    </div>
  )
}

/* ── Пункт «Принятое сегодня» ─────────────────────────────────────────── */

/**
 * Снятая карточка не должна выглядеть пропавшей: здесь видно, что уже посмотрели
 * сегодня и кто именно — в том числе секретарь, разобравший экран до директора.
 */
function AcceptedView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-accepted', company.id],
    queryFn: () => getPulseAccepted(company.id),
  })
  const items = q.data?.items ?? []
  const today = items.filter((i) => i.today)
  const before = items.filter((i) => !i.today)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <CheckCheck className="h-5 w-5 text-primary" />Принятое сегодня
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Что уже сняли с экрана дня — и кто. Завтра правило проверится заново.
        </p>
      </div>

      {q.isLoading && <PulseLoading what="принятого" />}
      {q.isError && <PulseError what="принятые карточки" onRetry={() => q.refetch()} />}

      {q.data && !items.length && (
        <Card className="border-dashed py-0">
          <CardContent className="p-4 text-xs text-muted-foreground">
            За последнюю неделю карточки не снимали.
          </CardContent>
        </Card>
      )}

      {[{ label: 'Сегодня', rows: today }, { label: 'Раньше', rows: before }]
        .filter((g) => g.rows.length)
        .map((g) => (
          <section key={g.label} className="space-y-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              {g.label}
            </h2>
            <Card className="py-0">
              <CardContent className="divide-y p-0">
                {g.rows.map((i, idx) => (
                  <div key={`${i.card_key}-${idx}`}
                    className="flex items-center justify-between gap-3 px-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13px]">{i.title}</div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {i.who ?? 'кто-то из руководства'}
                        {i.at && ` · ${new Date(i.at).toLocaleString('ru-RU',
                          { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`}
                        {/* Отложенное — не «снято», а «обещали вернуться»:
                            дата возврата видна прямо в строке. */}
                        {i.snooze_until && (
                          <span className="text-amber-600 dark:text-amber-400">
                            {' · '}вернуть {fmtDate(i.snooze_until)}
                          </span>
                        )}
                      </div>
                    </div>
                    {i.snooze_until
                      ? <CalendarClock className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                      : <CheckCheck className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />}
                  </div>
                ))}
              </CardContent>
            </Card>
          </section>
        ))}
    </div>
  )
}
