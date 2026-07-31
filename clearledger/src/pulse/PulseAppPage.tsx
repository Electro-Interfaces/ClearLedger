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
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, ArrowUpRight, CheckCheck, ClipboardList,
  MessageCircle, MoreHorizontal, ShieldCheck,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { ackCard, getPulseDay, type PulseCard, type PulseKpi } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum, plural } from './parts'

/** Дата данных словами: под цифрами видно, чему можно верить (правило №0). */
function asOfLabel(asOf: string | null, staleDays: number | null): string {
  if (!asOf) return 'данных о сессиях ещё нет'
  const d = new Date(asOf).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  if (staleDays != null && staleDays <= 1) return `данные сети на ${d}`
  return `данные сети на ${d} (${staleDays} дн назад)`
}

export function PulseAppPage() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-day', company.id],
    queryFn: () => getPulseDay(company.id),
    // Обновление раз в полторы минуты — realtime «Пульсу» не нужен (PULSE.md §6).
    refetchInterval: 90_000,
  })

  return (
    <div className="space-y-5">
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
  const ack = useMutation({
    mutationFn: (key: string) => ackCard(companyId, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pulse-day', companyId] })
      toast.success('Принято — карточка снята до конца дня')
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
                  disabled={ack.isPending} onClick={() => ack.mutate(c.key)}>
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
