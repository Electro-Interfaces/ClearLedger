/**
 * «Пульс» → «Бизнес» → «Эксплуатация»: хозяйство вокруг сети.
 *
 * Приложение «Эксплуатация» показывает хозяйство до последней строки — договоры,
 * условия, счётчики, начисления по каждой точке. Руководителю нужен другой
 * разрез: во сколько обходится незакрытый период, чем он подтверждён, кому мы
 * должны и что тянется с прошлых месяцев.
 *
 * Всё построено вокруг одного различия: ОЖИДАНИЕ (сколько должны по договору) и
 * ФАКТ (документ от контрагента) — разные вещи. Пока акта нет, это не расход, а
 * обещание, и закрывать месяц по ожиданиям нельзя.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Building2, FileWarning } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseOperations } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtDate, fmtNum } from './parts'

/** Типы договоров — словами: `energy_supply` руководителю ничего не говорит. */
const CONTRACT_TYPE: Record<string, string> = {
  rent: 'аренда', energy_supply: 'энергоснабжение', works: 'работы',
  supply: 'поставка', maintenance: 'обслуживание',
  charging_service: 'зарядный сервис', services: 'услуги',
}

/** «2026-07-01» → «июль 2026»: период читает человек, а не парсер. */
const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const periodLabel = (p: string) => {
  const [y, m] = p.split('-')
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`
}

export function OperationsView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-operations', company.id],
    queryFn: () => getPulseOperations(company.id),
    refetchInterval: 15 * 60_000,
  })
  const d = q.data

  if (q.isLoading) return <PulseLoading what="хозяйства" />
  if (q.isError) return <PulseError what="картину хозяйства" onRetry={() => q.refetch()} />
  if (d && !d.available) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Начислений по договорам пока нет — хозяйство ведётся в «Эксплуатации»,
          там же заводятся условия и контрагенты.
        </CardContent>
      </Card>
    )
  }
  if (!d) return null

  const maxItem = Math.max(1, ...d.items.map((i) => i.expected))
  const maxCp = Math.max(1, ...d.counterparties.map((c) => c.expected))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <div className="grid min-w-0 gap-2 md:grid-cols-2">
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Из чего складывается · {periodLabel(d.period)}
          </h2>
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.items.map((i) => {
                const delta = i.expected - i.previous
                return (
                  <div key={i.code} className="flex items-center gap-3 px-3 py-2 text-xs">
                    <span className="w-28 shrink-0 truncate">{i.label}</span>
                    <div className="hidden h-1.5 flex-1 rounded bg-muted sm:block">
                      <div className="h-1.5 rounded bg-primary/60"
                        style={{ width: `${(i.expected / maxItem) * 100}%` }} />
                    </div>
                    <span className="w-12 shrink-0 text-right text-muted-foreground tabular-nums">
                      {i.count}
                    </span>
                    <span className="w-28 shrink-0 text-right font-medium tabular-nums">
                      {fmtNum(i.expected, '₽')}
                    </span>
                    {/* Рост расхода красным: у затрат полярность обратная выручке. */}
                    <span className={cn('w-24 shrink-0 text-right tabular-nums',
                      !Math.round(delta) ? 'text-muted-foreground'
                        : delta > 0 ? 'text-red-600 dark:text-red-400'
                          : 'text-emerald-600 dark:text-emerald-400')}>
                      {Math.round(delta) ? `${delta > 0 ? '+' : '−'}${fmtNum(Math.abs(delta), '₽')}` : '—'}
                    </span>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        </section>

        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Кому платим · {periodLabel(d.period)}
          </h2>
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.counterparties.map((c) => (
                <div key={c.name} className="flex items-center gap-3 px-3 py-2 text-xs">
                  <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate" title={c.name}>{c.name}</span>
                  <div className="hidden h-1.5 w-16 shrink-0 rounded bg-muted md:block">
                    <div className="h-1.5 rounded bg-primary/60"
                      style={{ width: `${(c.expected / maxCp) * 100}%` }} />
                  </div>
                  <span className="w-10 shrink-0 text-right text-muted-foreground tabular-nums">
                    {c.count}
                  </span>
                  <span className="w-28 shrink-0 text-right font-medium tabular-nums">
                    {fmtNum(c.expected, '₽')}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Периоды · ждали ↔ чем подтверждено
          </h2>
          {!!d.open_periods && (
            <span className="text-[11px] text-amber-600 dark:text-amber-400">
              не закрыто периодов: {d.open_periods}
            </span>
          )}
        </div>
        {/* Проблемы прошлых месяцев — одной таблицей: сколько ждали, сколько
            подтверждено документами и сколько уже просрочено. Закрытый месяц
            не переписывается, открытый — ещё может измениться. */}
        <Card className="py-0">
          {/* Скролл внутри карточки: шесть колонок на телефон не помещаются, а
              резать данные нельзя — реестр периодов и есть ответ про хвосты. */}
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full min-w-[560px] text-xs">
              <thead className="text-[11px] uppercase tracking-wider text-muted-foreground/60">
                <tr className="border-b border-border/40">
                  <th className="px-3 py-1.5 text-left font-medium">Период</th>
                  <th className="px-3 py-1.5 text-right font-medium">Начислений</th>
                  <th className="px-3 py-1.5 text-right font-medium">Ожидание</th>
                  <th className="px-3 py-1.5 text-right font-medium">Подтверждено</th>
                  <th className="px-3 py-1.5 text-right font-medium">Просрочено</th>
                  <th className="px-3 py-1.5 text-right font-medium">Статус</th>
                </tr>
              </thead>
              <tbody>
                {d.periods.map((p) => (
                  <tr key={p.period} className="border-b border-border/40 last:border-0">
                    <td className="px-3 py-2">{periodLabel(p.period)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.charges}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmtNum(p.expected, '₽')}</td>
                    <td className={cn('px-3 py-2 text-right tabular-nums',
                      !p.with_doc && 'text-muted-foreground')}>
                      {p.with_doc ? `${p.with_doc} из ${p.charges}` : 'нет документов'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {p.overdue ? (
                        <span className="text-amber-600 dark:text-amber-400">{p.overdue}</span>
                      ) : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Badge variant="outline" className={cn('font-normal',
                        p.status !== 'closed' && 'border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400')}>
                        {p.status === 'closed' ? 'закрыт' : 'открыт'}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </section>

      {d.contracts.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Основания расходов · договоры на сроке
          </h2>
          {/* Договор — основание платежа: истёкший срок означает, что платим по
              бумаге, которой формально уже нет. Имя контрагента важнее номера —
              с ним идут разговаривать. */}
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.contracts.map((c, i) => (
                <div key={`${c.number}-${i}`} className="flex items-center gap-3 px-3 py-2 text-xs">
                  <FileWarning className={cn('h-3.5 w-3.5 shrink-0',
                    c.expired ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')} />
                  <span className="min-w-0 flex-1 truncate" title={c.counterparty}>
                    {c.counterparty}
                  </span>
                  <span className="hidden w-32 shrink-0 truncate text-right text-muted-foreground sm:block">
                    {CONTRACT_TYPE[c.type] ?? c.type}
                  </span>
                  <span className="hidden w-24 shrink-0 text-right text-muted-foreground sm:block">
                    №&nbsp;{c.number || '—'}
                  </span>
                  <span className={cn('w-28 shrink-0 text-right tabular-nums',
                    c.expired && 'text-amber-600 dark:text-amber-400')}>
                    {c.expired ? 'истёк ' : 'до '}{fmtDate(c.valid_until)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      )}

      {!!d.docs_overdue_amount && (
        <Card className="border-amber-500/40 bg-amber-500/5 py-0">
          <CardContent className="flex items-start gap-2 p-3 text-xs">
            <FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <span>
              На <span className="font-semibold tabular-nums">{fmtNum(d.docs_overdue_amount, '₽')}</span>
              {' '}расходов срок подачи документов уже прошёл. Пока акта нет, сумма остаётся
              обещанием: закрыть период и передать её в учёт нельзя.
            </span>
          </CardContent>
        </Card>
      )}

      {/* Лестница погружения: дальше — договоры, условия, счётчики и начисления
          по каждой точке. */}
      <a href="/operations" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
        Открыть приложение «Эксплуатация»<ArrowUpRight className="h-3.5 w-3.5" />
      </a>
    </div>
  )
}
