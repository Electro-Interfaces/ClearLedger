/**
 * «Ждёт учёта» — мост между стройкой и бухгалтерией.
 *
 * Показывает разрывы: проект ушёл вперёд, а в учёте записи нет. Договор
 * подписан — а в реестре договоров его не завели; станция введена — а объекта
 * в сети нет; идёт стройка — а документов поставки не существует.
 *
 * Список именно показывает, а не создаёт записи сам: бухгалтерский контур не
 * должен наполняться побочным эффектом смены статуса проекта.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, FileWarning, MapPinOff, PackageX } from 'lucide-react'
import { getAwaitingAccounting, STAGE_META, type SiteStage } from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export function AwaitingAccountingPanel({ companyId }: { companyId: string }) {
  const [detailId, setDetailId] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['pr-awaiting', companyId], queryFn: () => getAwaitingAccounting(companyId) })
  const d = q.data

  if (q.isLoading || !d) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  const groups = [
    {
      key: 'contract', icon: FileWarning, title: 'Договор подписан, а в учёте его нет',
      hint: 'В карточке проекта, вкладка «Учёт» — привязать договор из реестра.',
      items: d.contractMissing,
    },
    {
      key: 'location', icon: MapPinOff, title: 'Проект введён, а объекта в сети нет',
      hint: 'Пока объект не связан, станция не попадёт в аналитику и отчётность.',
      items: d.locationMissing,
    },
    {
      key: 'supply', icon: PackageX, title: 'Идёт стройка, а документов поставки нет',
      hint: 'Оборудование должно приходить документом поставки — иначе парк не сойдётся.',
      items: d.supplyMissing.map((s) => ({ ...s, title: null, region: null, stage: 'construction',
                                           stageLabel: 'Реализация' })),
    },
  ]
  const totalIssues = groups.reduce((a, g) => a + g.items.length, 0)

  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-base font-semibold">Ждёт учёта</h2>
        <p className="text-xs text-muted-foreground">
          Где проект ушёл вперёд, а бухгалтерия об этом ещё не знает. Всего расхождений: {nf0.format(totalIssues)}.
        </p>
      </div>

      {totalIssues === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Расхождений нет — учёт идёт вровень с проектами.
        </CardContent></Card>
      ) : groups.filter((g) => g.items.length > 0).map((g) => (
        <Card key={g.key}>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
              <g.icon className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
              <span className="text-xs font-semibold">{g.title}</span>
              <span className="font-mono text-xs text-muted-foreground ml-auto">{nf0.format(g.items.length)}</span>
            </div>
            <div className="px-3 py-1.5 text-[11px] text-muted-foreground border-b">{g.hint}</div>
            <table className="w-full text-xs">
              <tbody>
                {g.items.slice(0, 100).map((s) => (
                  <tr key={s.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                    onClick={() => setDetailId(s.id)}>
                    <td className="p-2 whitespace-nowrap font-mono w-36">{s.projectNo ?? '—'}</td>
                    <td className="p-2 max-w-[380px] truncate">
                      {s.address ?? '—'}<span className="text-muted-foreground"> · {s.city ?? ''}</span>
                    </td>
                    <td className="p-2 w-40">
                      <span className={`text-[11px] rounded border px-1.5 py-0.5 ${STAGE_META[s.stage as SiteStage]?.cls ?? ''}`}>
                        {s.stageLabel}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {g.items.length > 100 && (
              <div className="px-3 py-2 text-[11px] text-muted-foreground border-t">
                Показаны первые 100 из {nf0.format(g.items.length)}.
              </div>
            )}
          </CardContent>
        </Card>
      ))}

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}
