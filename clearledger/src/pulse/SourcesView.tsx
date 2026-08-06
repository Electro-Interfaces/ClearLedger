/**
 * «Пульс» → «Экран дня» → «Источники»: чему сегодня можно верить.
 *
 * Вопрос, который стоит перед всеми остальными разделами. Реестр коннекторов
 * для ответа не годится: коннектор бывает «активным» при том, что данные не
 * приезжали неделю. Правда — в самих таблицах, поэтому каждый источник показан
 * фактом «когда последняя запись», а не своим статусом.
 */
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Database, TriangleAlert } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseSources } from './pulseService'
import { PulseError, PulseLoading, fmtDate, fmtNum } from './parts'

/** «0 дн» звучит как поломка; человеку понятнее «сегодня». */
const ago = (days: number | null) =>
  days === null ? 'данных нет' : days <= 0 ? 'сегодня' : days === 1 ? 'вчера' : `${days} дн назад`

export function SourcesView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-sources', company.id],
    queryFn: () => getPulseSources(company.id),
    refetchInterval: 5 * 60_000,
  })
  if (q.isLoading) return <PulseLoading what="источников" />
  if (q.isError) return <PulseError what="состояние источников" onRetry={() => q.refetch()} />
  const d = q.data
  if (!d) return null

  return (
    <div className="space-y-5">
      <Card className={cn('py-0', d.stale ? 'border-amber-500/40 bg-amber-500/5' : 'border-dashed')}>
        <CardContent className="flex items-center gap-3 p-4">
          {d.stale
            ? <TriangleAlert className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
            : <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-400" />}
          <div>
            <div className="text-sm font-medium">
              {d.stale
                ? `Молчат источников: ${d.stale}`
                : 'Все источники приносят данные вовремя'}
            </div>
            <div className="text-xs text-muted-foreground">
              Пока источник молчит, разделы, которые он кормит, показывают прошлый обмен.
            </div>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Приёмники данных
        </h2>
        <Card className="py-0">
          <CardContent className="divide-y divide-border/40 p-0">
            {d.items.map((i) => (
              <div key={i.key} className="flex items-center gap-3 px-3 py-2.5 text-xs">
                <Database className={cn('h-3.5 w-3.5 shrink-0',
                  i.stale ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13px]">{i.label}</div>
                  <div className="text-[11px] text-muted-foreground">кормит {i.feeds}</div>
                </div>
                <span className="hidden w-24 shrink-0 text-right text-muted-foreground tabular-nums sm:block">
                  {fmtNum(i.count)} зап.
                </span>
                <span className="w-28 shrink-0 text-right text-muted-foreground">
                  {i.last_at ? fmtDate(i.last_at) : '—'}
                </span>
                {/* Норма у каждого источника своя: телефония приходит каждый час,
                    начисления — раз в месяц, и одно окно для всех врало бы. */}
                <span className={cn('w-24 shrink-0 text-right',
                  i.stale ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
                  {ago(i.days)}
                </span>
                <span className="hidden w-20 shrink-0 text-right text-muted-foreground md:block">
                  норма ≤ {i.window} дн
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      {d.channels.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Каналы обмена
          </h2>
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.channels.map((c) => (
                <div key={c.name} className="flex items-center gap-3 px-3 py-2 text-xs">
                  <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  <span className="w-20 shrink-0 text-right text-muted-foreground">{c.status}</span>
                  <span className="w-24 shrink-0 text-right text-muted-foreground tabular-nums">
                    {fmtNum(c.docs)} док.
                  </span>
                  <span className="w-24 shrink-0 text-right text-muted-foreground">
                    {c.last_sync ? fmtDate(c.last_sync) : 'ни разу'}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  )
}
