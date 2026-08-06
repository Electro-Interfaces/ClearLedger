/**
 * «Пульс» → «Бизнес» → «Проекты»: что компания строит, глазами руководителя.
 *
 * Витрина приложения «Проекты» отвечает тому, кто ведёт дела («какие карточки у
 * меня в работе»). Здесь три других вопроса: движется ли портфель вообще, где
 * он застрял и у кого это на руках. Долгожители — поимённо: «46 проектов стоят»
 * задачей не становится, а «Магадан, Пролетарская 66, 175 дней в проработке,
 * ведущего нет» — становится.
 *
 * Движением портфеля считаются переходы стадий, гейты и документы. Правки полей
 * карточки — нет: на пилоте их 1156 за неделю против 5 реальных переходов, и
 * лента «активности» показывала бы кипучую работу на стоящем портфеле.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, CheckCircle2, FileText, Flag, UserRound } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseProjects } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum, fmtDate } from './parts'

const MOVE_ICON = { stage: Flag, gate: CheckCircle2, doc: FileText } as const

export function ProjectsView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-projects', company.id],
    queryFn: () => getPulseProjects(company.id),
    refetchInterval: 10 * 60_000,
  })
  const d = q.data

  if (q.isLoading) return <PulseLoading what="портфеля" />
  if (q.isError) return <PulseError what="портфель проектов" onRetry={() => q.refetch()} />
  if (d && !d.available) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Проектов в работе нет — портфель пуст или всё уведено в архив.
        </CardContent>
      </Card>
    )
  }
  if (!d) return null

  const maxStage = Math.max(1, ...d.stages.map((s) => s.count))
  const maxOwner = Math.max(1, ...d.owners.map((o) => o.count))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Где стоит портфель
        </h2>
        {/* Не воронка: воронка отвечает «сколько дойдёт», а руководителю на этом
            экране нужно «сколько времени тут проводят и сколько зависло». */}
        <Card className="py-0">
          <CardContent className="divide-y divide-border/40 p-0">
            {d.stages.map((s) => (
              <div key={s.stage} className="flex items-center gap-3 px-3 py-2 text-xs">
                <span className="min-w-0 flex-1 truncate sm:w-36 sm:flex-none">{s.label}</span>
                <div className="hidden h-1.5 flex-1 rounded bg-muted sm:block">
                  <div className="h-1.5 rounded bg-primary/60"
                    style={{ width: `${(s.count / maxStage) * 100}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right font-semibold tabular-nums">
                  {s.count}
                </span>
                <span className="hidden w-28 shrink-0 text-right text-muted-foreground sm:block">
                  {s.avg_days != null ? `в среднем ${s.avg_days} дн` : '—'}
                </span>
                <span className="w-24 shrink-0 text-right">
                  {s.stuck ? (
                    <span className="text-amber-600 dark:text-amber-400 tabular-nums">
                      застряло {s.stuck}
                    </span>
                  ) : <span className="text-muted-foreground">—</span>}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      {d.longest.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Дольше всех без движения
          </h2>
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.longest.map((p, i) => (
                <div key={`${p.title}-${i}`} className="flex items-start gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px]" title={p.title}>{p.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                      <span>{p.stage}</span>
                      {p.region && p.region !== '—' && <span>· {p.region}</span>}
                      {/* Ответственный — первое, что спросит руководитель: без
                          него застрявший проект даже обсудить не с кем. */}
                      <span className={cn(!p.owner && 'text-amber-600 dark:text-amber-400')}>
                        · {p.owner || 'ведущий не назначен'}
                      </span>
                      {p.next_action && <span className="min-w-0 truncate">· дальше: {p.next_action}</span>}
                    </div>
                  </div>
                  <Badge variant="outline"
                    className={cn('shrink-0 tabular-nums font-normal',
                      p.days > 90 && 'border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400')}>
                    {fmtNum(p.days)} дн
                  </Badge>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      )}

      <div className="grid min-w-0 gap-2 md:grid-cols-2">
        <section className="min-w-0 space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Что сдвинулось за неделю
          </h2>
          <Card className="py-0">
            <CardContent className="space-y-1.5 p-3">
              {d.moves.length ? d.moves.map((m, i) => {
                const Icon = MOVE_ICON[m.kind as keyof typeof MOVE_ICON] ?? Flag
                return (
                  <div key={i} className="flex min-w-0 gap-2 text-xs">
                    <Icon className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {fmtDate(m.at)}
                    </span>
                    <span className="min-w-0 truncate" title={m.text}>{m.text}</span>
                  </div>
                )
              }) : (
                <div className="text-xs text-muted-foreground">
                  Ни одного перехода, гейта или документа за семь дней.
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        <section className="min-w-0 space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Кто ведёт
          </h2>
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.owners.map((o) => {
                const nobody = o.name.startsWith('(')
                return (
                  <div key={o.name} className="flex items-center gap-3 px-3 py-2 text-xs">
                    <UserRound className={cn('h-3.5 w-3.5 shrink-0',
                      nobody ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')} />
                    <span className={cn('min-w-0 flex-1 truncate',
                      nobody && 'text-amber-600 dark:text-amber-400')}>{o.name}</span>
                    <div className="hidden h-1.5 w-20 shrink-0 rounded bg-muted sm:block">
                      <div className={cn('h-1.5 rounded', nobody ? 'bg-amber-500/60' : 'bg-primary/60')}
                        style={{ width: `${(o.count / maxOwner) * 100}%` }} />
                    </div>
                    <span className="w-10 shrink-0 text-right font-semibold tabular-nums">
                      {o.count}
                    </span>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        </section>
      </div>

      {/* Лестница погружения: дальше — реестр проектов с карточками и гейтами. */}
      <a href="/projects" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
        Открыть приложение «Проекты»<ArrowUpRight className="h-3.5 w-3.5" />
      </a>
    </div>
  )
}
