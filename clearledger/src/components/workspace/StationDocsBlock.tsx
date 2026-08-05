/**
 * Документы, заведённые НА СТАНЦИИ, — рядом с реестром 1С на том же экране.
 *
 * Реестры склада исторически читают документы ЦБ: их полтора десятка тысяч, и
 * они кончаются датой, когда 1С перестанет вести станцию. Работа агента живёт
 * в пакетах, и без этого блока её в разделе не видно вовсе — а именно она и
 * останется, когда 1С уйдёт.
 *
 * Поэтому блок не прячется, даже когда пуст: пустой список здесь — не «нет
 * данных», а «станция таких документов ещё не присылала», и это разные вещи.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RadioTower } from 'lucide-react'
import { getStoreStationDocs } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { useCompany } from '@/contexts/CompanyContext'
import { StationDocModal } from './StationDocModal'

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU',
    { day: '2-digit', month: '2-digit', year: '2-digit' })
}

export function StationDocsBlock({ kind, dateFrom, dateTo, title }: {
  kind: string; dateFrom?: string; dateTo?: string; title: string
}) {
  const { company } = useCompany()
  const { data, isLoading } = useQuery({
    queryKey: ['store-station-docs', company.id, kind, dateFrom, dateTo],
    queryFn: () => getStoreStationDocs({ kind, dateFrom, dateTo }),
  })

  const [открыт, открыть] = useState<{ packet: string; index: number } | null>(null)
  const docs = data?.docs ?? []
  const станции = data?.by_station ?? []

  return (
    <div className="rounded-lg border border-border/50">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/40 px-3 py-2">
        <RadioTower className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">{title}</span>
        <span className="text-[11px] text-muted-foreground">заведено на АЗС, пришло агентом</span>
        {станции.length > 0 && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {станции.map((s) => `АЗС ${s.station_id} — ${s.docs}`).join(' · ')}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="px-3 py-4 text-xs text-muted-foreground">Загрузка документов станции…</div>
      ) : docs.length === 0 ? (
        <div className="px-3 py-4 text-xs text-muted-foreground">
          Станция таких документов ещё не присылала. Это не пустой отчёт: реестр выше —
          история 1С, а здесь появится то, что заведут на самой АЗС.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Дата</th>
                <th className="px-3 py-2 text-left font-medium">АЗС</th>
                <th className="px-3 py-2 text-left font-medium">Номер</th>
                <th className="px-3 py-2 text-left font-medium">Место</th>
                <th className="px-3 py-2 text-right font-medium">Позиций</th>
                <th className="px-3 py-2 text-right font-medium">Сумма</th>
                <th className="px-3 py-2 text-left font-medium">Кто и почему</th>
                <th className="px-3 py-2 text-left font-medium">Смена</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d, i) => (
                <tr key={`${d.packet_uuid}-${d.number}-${i}`}
                    onClick={() => открыть({ packet: d.packet_uuid, index: d.doc_index })}
                    title="Открыть документ: строки, стороны, образы"
                    className="cursor-pointer border-t border-border/30 hover:bg-accent/20">
                  <td className="whitespace-nowrap px-3 py-1.5">{когда(d.doc_date)}</td>
                  <td className="px-3 py-1.5 tabular-nums">{d.station_id}</td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{d.number || '—'}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {d.place_from || '—'}{d.place_to ? ` → ${d.place_to}` : ''}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{d.positions}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {d.amount ? fmtMoney(d.amount) : '—'}
                  </td>
                  <td className="max-w-[280px] truncate px-3 py-1.5 text-muted-foreground"
                      title={`${d.author ?? ''} ${d.note ?? ''}`.trim()}>
                    {[d.author, d.note].filter(Boolean).join(' · ') || '—'}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{d.shift_number ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {открыт && (
        <StationDocModal packetUuid={открыт.packet} index={открыт.index}
                         onClose={() => открыть(null)} />
      )}
    </div>
  )
}
