/**
 * «Пульс» — экран дня руководителя (ecosystem-deploy/docs/PULSE.md, волна В1).
 *
 * Mobile-first: телефон — родная подача (одна колонка, крупные плитки), десктоп —
 * та же вёрстка шире. Два горизонта чтения: статус за 5 секунд (есть ли карточки),
 * весь экран за 60 без прокрутки. Каждая карточка ведёт к действию: обсудить,
 * заявка, открыть разрез, «принято». Пусто — так и сказано: вмешательства не
 * требуется, это нормальное состояние экрана.
 */
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, ArrowDownRight, ArrowUpRight, CheckCheck, ClipboardList,
  Loader2, MessageCircle, ShieldCheck,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { ackCard, getPulseDay, type PulseCard, type PulseKpi } from './pulseService'

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

function fmtValue(k: PulseKpi): string {
  if (k.value == null) return '—'
  const v = nf.format(k.value)
  return k.unit ? `${v} ${k.unit}` : v
}

/** Дата данных словами: под каждой цифрой видно, чему можно верить (правило №0). */
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
    // Обновление раз в 1–2 минуты — realtime «Пульсу» не нужен (PULSE.md §6).
    refetchInterval: 90_000,
  })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Activity className="h-5 w-5 text-primary" />Пульс
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {q.data ? asOfLabel(q.data.as_of, q.data.stale_days) : 'Экран дня руководителя'}
          </p>
        </div>
      </div>

      {q.isLoading && (
        <div className="flex justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {q.data && (
        <>
          <CardsBlock cards={q.data.cards} companyId={company.id} />
          <KpiGrid kpi={q.data.kpi} />
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
  })

  if (!cards.length) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-dashed p-4">
        <ShieldCheck className="h-6 w-6 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <div>
          <div className="text-sm font-medium">Вмешательства не требуется</div>
          <div className="text-xs text-muted-foreground">
            Ни одно правило не сработало — это нормальное состояние экрана.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {cards.map((c) => (
        <div
          key={c.key}
          className={cn(
            'rounded-lg border p-4',
            c.level === 'alert'
              ? 'border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40'
              : 'border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40',
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="text-sm font-semibold">{c.title}</div>
            {c.count != null && <div className="text-lg font-bold tabular-nums">{nf.format(c.count)}</div>}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{c.insight}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {c.link && (
              <Button size="sm" variant="outline" className="h-8" onClick={() => navigate(c.link!)}>
                <ArrowUpRight className="mr-1 h-3.5 w-3.5" />Открыть
              </Button>
            )}
            <Button size="sm" variant="outline" className="h-8" onClick={() => navigate('/messages')}>
              <MessageCircle className="mr-1 h-3.5 w-3.5" />Обсудить
            </Button>
            <Button size="sm" variant="outline" className="h-8" onClick={() => navigate('/tickets')}>
              <ClipboardList className="mr-1 h-3.5 w-3.5" />Заявка
            </Button>
            <Button
              size="sm" variant="ghost" className="h-8"
              disabled={ack.isPending}
              onClick={() => ack.mutate(c.key)}
            >
              <CheckCheck className="mr-1 h-3.5 w-3.5" />Принято
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Строка KPI по направлениям: сегодня против прошлой недели ────────── */

function KpiGrid({ kpi }: { kpi: PulseKpi[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
      {kpi.map((k) => (
        <div
          key={k.key}
          className={cn(
            'rounded-lg border p-3',
            k.state === 'warn' && 'border-amber-300 dark:border-amber-800',
            // «Стухшие» данные видно раньше, чем прочитана дата (PULSE.md §6).
            k.state === 'stale' && 'opacity-60',
          )}
        >
          <div className="text-[11px] text-muted-foreground">{k.title}</div>
          <div className="mt-0.5 flex items-baseline gap-1.5">
            <span className="text-xl font-bold tabular-nums">{fmtValue(k)}</span>
            {k.delta_pct != null && (
              <span className={cn(
                'flex items-center text-[11px] font-medium tabular-nums',
                k.delta_pct >= 0
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : 'text-red-600 dark:text-red-400',
              )}>
                {k.delta_pct >= 0
                  ? <ArrowUpRight className="h-3 w-3" />
                  : <ArrowDownRight className="h-3 w-3" />}
                {Math.abs(k.delta_pct)}%
              </span>
            )}
          </div>
          {k.note && <div className="mt-0.5 text-[11px] text-muted-foreground">{k.note}</div>}
        </div>
      ))}
    </div>
  )
}
