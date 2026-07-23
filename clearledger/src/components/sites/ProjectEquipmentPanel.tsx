/**
 * «Оборудование проектов» — что каким площадкам нужно и на каком этапе закупка.
 *
 * Это не склад: склад отвечает «что у нас есть и где лежит», а здесь —
 * потребность проекта. Пока железо не приехало, единицы склада ещё не
 * существует, но срок поставки уже двигает ввод станции.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, AlertTriangle } from 'lucide-react'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'
import { getEquipmentReport, STAGE_META, type SiteStage } from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'
import { useOpenProject } from './useOpenProject'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export function ProjectEquipmentPanel({ companyId }: { companyId: string }) {
  const [status, setStatus] = useState('')
  const [onlyOverdue, setOnlyOverdue] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  // Клик по строке открывает рабочий экран проекта; Alt+клик — быстрый просмотр.
  const openProject = useOpenProject()

  const q = useQuery({ queryKey: ['pr-equipment', companyId], queryFn: () => getEquipmentReport(companyId) })
  const d = q.data
  const rows = useMemo(() => (d?.items ?? []).filter(
    (e) => (!status || e.status === status) && (!onlyOverdue || e.overdue)), [d, status, onlyOverdue])

  if (q.isLoading || !d) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-base font-semibold">Оборудование проектов</h2>
        <p className="text-xs text-muted-foreground">
          Потребность → заказ → поставка → монтаж. Позиции ведутся в карточке проекта,
          вкладка «Оборудование»; сюда они собираются по всему портфелю.
        </p>
      </div>

      {d.total === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Потребность в оборудовании ещё не заводилась.
        </CardContent></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Позиций" value={nf0.format(d.total)} hint={`единиц ${nf0.format(d.qty)}`} />
            <KpiCard label="Поставлено"
              value={nf0.format(d.byStatus.find((s) => s.key === 'supplied')?.count ?? 0)} />
            <KpiCard label="Смонтировано"
              value={nf0.format(d.byStatus.find((s) => s.key === 'installed')?.count ?? 0)} />
            <KpiCard label="Просрочена поставка" value={nf0.format(d.overdue)}
              accent={d.overdue ? 'warning' : undefined} />
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
            <span className="text-[11px] text-muted-foreground ml-auto">
              Сумма позиций: {nf0.format(d.priceTotal)} ₽
            </span>
          </div>

          <Card>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/20 text-muted-foreground">
                    <th className="text-left p-2 font-medium">Проект</th>
                    <th className="text-left p-2 font-medium">Объект</th>
                    <th className="text-left p-2 font-medium">Оборудование</th>
                    <th className="text-right p-2 font-medium">кВт</th>
                    <th className="text-right p-2 font-medium">Кол-во</th>
                    <th className="text-left p-2 font-medium">Поставщик</th>
                    <th className="text-left p-2 font-medium">Статус</th>
                    <th className="text-left p-2 font-medium">Поставка</th>
                    <th className="text-right p-2 font-medium">Стоимость</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                      onClick={(ev) => (ev.altKey ? setDetailId(e.siteId) : openProject(e.siteId))}>
                      <td className="p-2 whitespace-nowrap font-mono">{e.projectNo ?? '—'}</td>
                      <td className="p-2 max-w-[220px] truncate" title={e.address ?? ''}>
                        {e.address ?? e.city ?? '—'}
                        {e.stage && (
                          <span className={`ml-1 text-[10px] rounded border px-1 py-0.5 ${STAGE_META[e.stage as SiteStage]?.cls ?? ''}`}>
                            {e.stageLabel}
                          </span>
                        )}
                      </td>
                      <td className="p-2 max-w-[200px] truncate">
                        {e.title ?? '—'}
                        {e.manufacturer && <span className="text-muted-foreground"> · {e.manufacturer}</span>}
                      </td>
                      <td className="p-2 text-right font-mono">{e.powerKwt ?? '—'}</td>
                      <td className="p-2 text-right font-mono">{e.qty}</td>
                      <td className="p-2 max-w-[150px] truncate text-muted-foreground">{e.supplier ?? '—'}</td>
                      <td className="p-2 whitespace-nowrap">{e.statusLabel}</td>
                      <td className={`p-2 whitespace-nowrap font-mono ${e.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {e.suppliedDate ? `✓ ${e.suppliedDate}` : (e.dueDate ?? '—')}
                        {e.overdue && <AlertTriangle className="inline h-3 w-3 ml-1" />}
                      </td>
                      <td className="p-2 text-right font-mono">{e.price != null ? nf0.format(e.price) : '—'}</td>
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
