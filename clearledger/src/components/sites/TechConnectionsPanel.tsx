/**
 * «Присоединение» — реестр техприсоединений по проектам.
 *
 * Отдельный экран, потому что срок проекта задаёт именно ТП: от заявки до
 * исполнения проходит от двух месяцев до полутора лет, и просрочка сетевой
 * организации двигает весь план ввода станций.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, AlertTriangle } from 'lucide-react'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'
import { getTechConnections, STAGE_META, type SiteStage } from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export function TechConnectionsPanel({ companyId }: { companyId: string }) {
  const [status, setStatus] = useState('')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)

  const q = useQuery({ queryKey: ['pr-tc', companyId], queryFn: () => getTechConnections(companyId) })
  const d = q.data

  const rows = useMemo(() => (d?.items ?? []).filter(
    (t) => (!status || t.status === status) && (!onlyOverdue || t.overdue)), [d, status, onlyOverdue])

  if (q.isLoading || !d) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-base font-semibold">Технологическое присоединение</h2>
        <p className="text-xs text-muted-foreground">
          Заявка → ТУ → договор → мероприятия сетевой. Именно этот срок определяет,
          когда станция выйдет в сеть.
        </p>
      </div>

      {d.total === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Присоединения ещё не заводились. Открывается в карточке проекта, вкладка «Присоединение».
        </CardContent></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Всего присоединений" value={nf0.format(d.total)} />
            <KpiCard label="Исполнено" value={nf0.format(d.byStatus.find((s) => s.key === 'done')?.count ?? 0)} />
            <KpiCard label="Просрочено" value={nf0.format(d.overdue)}
              accent={d.overdue ? 'warning' : undefined} hint="срок мероприятий прошёл" />
            <KpiCard label="Стоимость подключений" value={`${nf0.format(d.costSum)} ₽`} hint="по заполненным" />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5 flex-wrap">
              <button type="button" onClick={() => setStatus('')}
                className={`px-2 py-1 text-xs rounded-[5px] ${status === '' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                Все
              </button>
              {d.byStatus.filter((s) => s.count > 0).map((s) => (
                <button key={s.key} type="button" onClick={() => setStatus(s.key)}
                  className={`px-2 py-1 text-xs rounded-[5px] ${status === s.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {s.label} ({s.count})
                </button>
              ))}
            </div>
            <button type="button" onClick={() => setOnlyOverdue((v) => !v)}
              className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${onlyOverdue ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
              Только просроченные
            </button>
          </div>

          <Card>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/20 text-muted-foreground">
                    <th className="text-left p-2 font-medium">Проект</th>
                    <th className="text-left p-2 font-medium">Объект</th>
                    <th className="text-left p-2 font-medium">Сетевая</th>
                    <th className="text-left p-2 font-medium">Статус ТП</th>
                    <th className="text-left p-2 font-medium">Заявка</th>
                    <th className="text-left p-2 font-medium">ТУ</th>
                    <th className="text-right p-2 font-medium">кВт</th>
                    <th className="text-right p-2 font-medium">Стоимость</th>
                    <th className="text-left p-2 font-medium">Срок</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                      onClick={() => setDetailId(t.siteId)}>
                      <td className="p-2 whitespace-nowrap font-mono">{t.projectNo ?? '—'}</td>
                      <td className="p-2 max-w-[240px] truncate" title={t.address ?? ''}>
                        {t.address ?? t.city ?? '—'}
                        {t.stage && (
                          <span className={`ml-1 text-[10px] rounded border px-1 py-0.5 ${STAGE_META[t.stage as SiteStage]?.cls ?? ''}`}>
                            {t.stageLabel}
                          </span>
                        )}
                      </td>
                      <td className="p-2 max-w-[160px] truncate text-muted-foreground">{t.gridOperator ?? '—'}</td>
                      <td className="p-2 whitespace-nowrap">{t.statusLabel}</td>
                      <td className="p-2 whitespace-nowrap text-muted-foreground">
                        {t.applicationNo ?? '—'}{t.applicationDate ? ` · ${t.applicationDate}` : ''}
                      </td>
                      <td className="p-2 whitespace-nowrap text-muted-foreground">
                        {t.specsNo ?? '—'}{t.specsDate ? ` · ${t.specsDate}` : ''}
                      </td>
                      <td className="p-2 text-right font-mono">{t.powerKwt ?? '—'}</td>
                      <td className="p-2 text-right font-mono">{t.cost != null ? nf0.format(t.cost) : '—'}</td>
                      <td className={`p-2 whitespace-nowrap font-mono ${t.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {t.doneDate ? `✓ ${t.doneDate}` : (t.dueDate ?? '—')}
                        {t.overdue && <AlertTriangle className="inline h-3 w-3 ml-1" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}
