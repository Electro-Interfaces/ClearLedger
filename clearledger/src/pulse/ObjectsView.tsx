/**
 * «Пульс» → «Бизнес» → «Где болит»: точка сети сразу во всех контурах.
 *
 * Единственный экран пространства, которого нет ни в одном приложении:
 * «Продажи» видят молчание станции, «Эксплуатация» — расходы по ней, и каждый
 * считает, что у соседа порядок. Здесь они сведены по одному ключу.
 *
 * В список попадает точка, у которой сошлось НЕСКОЛЬКО независимых признаков:
 * одна просроченная бумага — работа бухгалтерии, а молчание плюс расход плюс
 * неподтверждённые документы на одной точке — уже вопрос к руководителю.
 *
 * Заявок здесь нет намеренно: они живут в реестре объектов Поддержки, общего
 * ключа с объектами Ядра у него сейчас нет, а сшивка по имени дала бы ложные
 * пары — «Гоголя 1» есть в трёх городах.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, MapPin } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseObjects } from './pulseService'
import { KpiTile, PulseError, PulseExport, PulseLoading, fmtNum, fmtDate } from './parts'

/** Признаки — словами, а не кодами: карточку читает человек. */
const FLAG_LABEL: Record<string, string> = {
  idle_cost: 'платим, не продаёт',
  revenue_drop: 'выручка провалилась',
  docs_late: 'документы просрочены',
  silent: 'молчит',
}

export function ObjectsView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-objects', company.id],
    queryFn: () => getPulseObjects(company.id),
    refetchInterval: 10 * 60_000,
  })
  const d = q.data

  if (q.isLoading) return <PulseLoading what="точек сети" />
  if (q.isError) return <PulseError what="картину по точкам" onRetry={() => q.refetch()} />
  if (d && !d.available) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          По точкам сети пока нет ни сессий, ни начислений — сводить нечего.
        </CardContent>
      </Card>
    )
  }
  if (!d) return null

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Точки, где сошлось несколько признаков
          </h2>
          <span className="text-[11px] text-muted-foreground">
            {d.pain.length} из {d.pain_count} · по цене вопроса
          </span>
        </div>

        {d.pain.length ? (
          <div className="space-y-2">
            {d.pain.map((p) => (
              <Card key={p.id}
                className={cn('py-0', p.flags.length >= 3 && 'border-amber-500/40 bg-amber-500/5')}>
                <CardContent className="p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 truncate text-sm font-medium">
                        <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        {p.name}
                        {p.code && (
                          <span className="shrink-0 text-[11px] text-muted-foreground">· {p.code}</span>
                        )}
                      </div>
                      {/* Каждый признак — отдельным бейджем: руководителю важно
                          не «плохо», а ЧТО именно сложилось на этой точке. */}
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {p.flags.map((f) => (
                          <Badge key={f} variant="outline"
                            className="border-amber-500/40 bg-amber-500/5 px-1.5 py-0 text-[10px] font-normal text-amber-600 dark:text-amber-400">
                            {FLAG_LABEL[f] ?? f}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-base font-semibold tabular-nums">
                        {fmtNum(p.at_risk, '₽')}
                      </div>
                      <div className="text-[10px] text-muted-foreground">под вопросом</div>
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-muted-foreground">
                    <span>
                      выручка недели: <span className="tabular-nums text-foreground">{fmtNum(p.revenue, '₽')}</span>
                      {p.revenue_prev > 0 && <> (было {fmtNum(p.revenue_prev, '₽')})</>}
                    </span>
                    {p.cost > 0 && (
                      <span>
                        начислено за два месяца: <span className="tabular-nums text-foreground">{fmtNum(p.cost, '₽')}</span>
                      </span>
                    )}
                    {!!p.late_docs && <span>без документа: {p.late_docs}</span>}
                    <span>
                      последняя сессия: {p.last_session ? fmtDate(p.last_session) : 'не было ни одной'}
                    </span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <Card className="border-dashed py-0">
            <CardContent className="flex items-center gap-3 p-4">
              <div>
                <div className="text-sm font-medium">Ни на одной точке признаки не сошлись</div>
                <div className="text-xs text-muted-foreground">
                  Отдельные проблемы разбираются в своих приложениях — сюда попадает
                  только то, что видно сразу в нескольких контурах.
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </section>

      <div className="flex flex-wrap items-center gap-4">
        <PulseExport view="objects" companyId={company.id} />
        <a href="/sales" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
          Выручка точек — в «Продажах»<ArrowUpRight className="h-3.5 w-3.5" />
        </a>
        <a href="/operations" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
          Расходы и документы — в «Эксплуатации»<ArrowUpRight className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  )
}
