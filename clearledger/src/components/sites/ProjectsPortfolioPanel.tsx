/**
 * «Обзор портфеля» — сколько проектов на каком этапе, что с бюджетом,
 * присоединениями и главным результатом: сколько дошло до работающей станции.
 *
 * Этапы идут слева направо в порядке движения проекта. Реализация — это не
 * один шаг: внутри параллельно идут присоединение, закупка и монтаж, поэтому
 * рядом с этапом показывается состояние ТП отдельным блоком.
 */
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, Info, Download } from 'lucide-react'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import {
  getPortfolio, getSitesOverview, getPhaseDurations, exportPortfolioXlsx,
  PHASE_META, STAGE_META,
} from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const money = (v: number) => `${nf0.format(Math.round(v))} ₽`

export function ProjectsPortfolioPanel({ companyId }: { companyId: string }) {
  const q = useQuery({ queryKey: ['pr-portfolio', companyId], queryFn: () => getPortfolio(companyId) })
  const ov = useQuery({ queryKey: ['sites-overview', companyId], queryFn: () => getSitesOverview(companyId) })
  const dur = useQuery({ queryKey: ['pr-durations', companyId], queryFn: () => getPhaseDurations(companyId) })
  const d = q.data

  if (q.isLoading || !d) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const maxPhase = Math.max(...d.phases.map((p) => p.count), 1)
  const work = ov.data?.work

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Портфель проектов</h2>
          <p className="text-xs text-muted-foreground">
            Жизненный цикл ЭЗС: подбор участка → оформление земли → присоединение, оборудование и
            монтаж → ввод в эксплуатацию.
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8 text-xs"
          onClick={() => exportPortfolioXlsx(companyId).catch((e) =>
            toast.error(e instanceof Error ? e.message : 'Выгрузка не удалась'))}>
          <Download className="h-3.5 w-3.5 mr-1" />Выгрузить портфель
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Проектов в работе" value={nf0.format(d.active)} accent="info"
          hint={`всего в банке ${nf0.format(d.total)}`} />
        <KpiCard label="Введено в сеть" value={nf0.format(d.realized)}
          hint="дошли до работающей станции" />
        <KpiCard label="Бюджет: план" value={money(d.budget.plan)}
          hint={`факт ${money(d.budget.fact)}`} />
        <KpiCard label="Присоединения" value={nf0.format(d.techConnections.total)}
          accent={d.techConnections.overdue > 0 ? 'warning' : undefined}
          hint={`исполнено ${d.techConnections.done} · просрочено ${d.techConnections.overdue}`} />
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
            Этапы проектов
          </div>
          <div className="p-3 space-y-3">
            {d.phases.map((p) => (
              <div key={p.key}>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 text-xs w-32 shrink-0">
                    <span className={`h-2 w-2 rounded-full ${PHASE_META[p.key]?.dot ?? 'bg-zinc-400'}`} />
                    {p.label}
                  </span>
                  <span className="text-[10px] text-muted-foreground w-56 shrink-0 truncate hidden md:block">{p.hint}</span>
                  <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                    <div className={`h-full ${PHASE_META[p.key]?.dot ?? 'bg-zinc-400'}`}
                      style={{ width: `${(p.count / maxPhase) * 100}%` }} />
                  </div>
                  <span className="font-mono text-xs text-muted-foreground w-14 text-right">{nf0.format(p.count)}</span>
                </div>
                {p.stages.length > 1 && (
                  <div className="flex flex-wrap gap-1.5 mt-1 ml-32 pl-2">
                    {p.stages.map((s) => (
                      <span key={s.stage} className={`text-[10px] rounded border px-1.5 py-0.5 ${STAGE_META[s.stage]?.cls ?? ''}`}>
                        {s.label}: {nf0.format(s.count)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {work && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Управляемость: {nf0.format(ov.data?.active ?? 0)} проектов в работе
            </div>
            <div className="p-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <Cell label="Без ответственного" value={work.noOwner} total={ov.data?.active ?? 0} />
              <Cell label="Без следующего шага" value={work.noNextAction} total={ov.data?.active ?? 0} />
              <Cell label="Срок просрочен" value={work.overdue} total={ov.data?.active ?? 0} />
              <Cell label={`Без касания > ${work.staleDays} дн`} value={work.stale} total={ov.data?.active ?? 0} />
            </div>
          </CardContent>
        </Card>
      )}

      {(dur.data?.stages ?? []).some((s) => s.count > 0) && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Сколько проекты стоят на стадиях
            </div>
            <div className="p-3 space-y-1.5">
              {(dur.data?.stages ?? []).filter((s) => s.count > 0).map((s) => (
                <div key={s.stage} className="flex items-center gap-2 text-xs">
                  <span className="w-36 shrink-0">{s.label}</span>
                  <span className="font-mono text-muted-foreground w-24">{s.medianDays} дн</span>
                  <span className="text-[11px] text-muted-foreground">
                    переходов {s.count}{s.open ? ` · сейчас в стадии ${s.open}` : ''}
                  </span>
                </div>
              ))}
              <div className="text-[10px] text-muted-foreground pt-1">{dur.data?.note}</div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span>
          Документов в проектах: {nf0.format(d.docs)}. Срок проекта определяется не стройкой, а
          присоединением — состояние заявок и ТУ смотрите в пункте «Присоединение».
        </span>
      </div>
    </div>
  )
}

function Cell({ label, value, total }: { label: string; value: number; total: number }) {
  const share = total ? value / total : 0
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">{nf0.format(value)}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full ${share >= 0.5 ? 'bg-red-400/60' : share >= 0.2 ? 'bg-amber-500/70' : 'bg-emerald-500/70'}`}
          style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  )
}
