/**
 * Передачи товара между АЗС — двусторонняя операция, а не запись в журнале.
 *
 * Перемещение внутри станции (склад ↔ торговый зал) делает один человек, и
 * спрашивать за него не с кого. Передача между станциями меняет материально
 * ответственного: один сдал, другой принял, и до подтверждения товар в пути —
 * то есть физически нигде. Механика двусторонняя с самого начала: агент
 * отправителя ставит получателю заготовку приёмки, тот отвечает подтверждением
 * с фактическим количеством. Здесь видно, что из этого не сошлось.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, TriangleAlert } from 'lucide-react'
import { getStoreTransfersBetween } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

const nf = (n: number | null | undefined, d = 3) =>
  n == null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function впути(часов: number | null): string {
  if (часов == null) return '—'
  if (часов < 24) return `${часов} ч`
  return `${Math.round(часов / 24)} сут`
}

const СОСТОЯНИЕ: Record<string, string> = {
  'в пути': 'text-amber-300/90',
  'принято': 'text-emerald-400/90',
  'расхождение': 'text-red-400/90',
}

export function TransfersBetweenBlock({ dateFrom, dateTo }: {
  dateFrom?: string; dateTo?: string
}) {
  const { company } = useCompany()
  const { data, isLoading } = useQuery({
    queryKey: ['store-transfers-between', company.id, dateFrom, dateTo],
    queryFn: () => getStoreTransfersBetween({ dateFrom, dateTo }),
  })

  const передачи = data?.transfers ?? []
  const свод = data?.by_state

  return (
    <div className="rounded-lg border border-border/50">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/40 px-3 py-2">
        <ArrowLeftRight className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">Передачи между АЗС</span>
        <span className="text-[11px] text-muted-foreground">
          смена материально ответственного: сдал один, принял другой
        </span>
        {свод && (
          <span className="ml-auto flex items-center gap-3 text-[11px]">
            <span className="text-amber-300/90">в пути {свод['в пути']}</span>
            <span className="text-emerald-400/90">принято {свод['принято']}</span>
            <span className={свод['расхождение'] > 0 ? 'text-red-400/90' : 'text-muted-foreground'}>
              расхождений {свод['расхождение']}
            </span>
          </span>
        )}
      </div>

      {(data?.stuck.length ?? 0) > 0 && (
        <div className="flex items-start gap-2 border-b border-border/40 bg-amber-400/5 px-3 py-2 text-xs">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300/90" />
          <span className="text-muted-foreground">
            {data!.stuck.length} передач{data!.stuck.length === 1 ? 'а висит' : ' висят'} в пути
            дольше суток. Столько занимает доставка между соседними АЗС, а не приём товара с
            машины: либо получатель не подтвердил, либо его агент молчит.
          </span>
        </div>
      )}

      {isLoading ? (
        <div className="px-3 py-4 text-xs text-muted-foreground">Сводим отправки и приёмы…</div>
      ) : передачи.length === 0 ? (
        <div className="px-3 py-4 text-xs text-muted-foreground">
          Передач между станциями не было. Пока в сети одна АЗС, это норма: передавать некому.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Дата</th>
                <th className="px-3 py-2 text-left font-medium">Откуда → куда</th>
                <th className="px-3 py-2 text-left font-medium">Номер</th>
                <th className="px-3 py-2 text-right font-medium">Позиций</th>
                <th className="px-3 py-2 text-right font-medium">Отправлено</th>
                <th className="px-3 py-2 text-right font-medium">Принято</th>
                <th className="px-3 py-2 text-right font-medium">Разница</th>
                <th className="px-3 py-2 text-left font-medium">Состояние</th>
                <th className="px-3 py-2 text-left font-medium">Заготовка у получателя</th>
              </tr>
            </thead>
            <tbody>
              {передачи.map((t, i) => (
                <tr key={`${t.doc_id}-${i}`} className="border-t border-border/30">
                  <td className="whitespace-nowrap px-3 py-1.5">{когда(t.doc_date)}</td>
                  <td className="px-3 py-1.5 tabular-nums">
                    АЗС {t.from_station} → АЗС {t.to_station}
                    {t.from_place && (
                      <span className="ml-1 text-[10px] text-muted-foreground">{t.from_place}</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{t.number || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{t.positions}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{nf(t.qty_sent)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{nf(t.qty_accepted)}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${
                    t.difference ? 'text-red-400/90' : 'text-muted-foreground'}`}>
                    {t.difference ? `${t.difference > 0 ? '+' : ''}${nf(t.difference)}` : '—'}
                  </td>
                  <td className={`px-3 py-1.5 ${СОСТОЯНИЕ[t.state] ?? ''}`}>
                    {t.state}
                    {t.state === 'в пути' && (
                      <span className="ml-1 text-[10px] text-muted-foreground">
                        {впути(t.hours_in_transit)}
                      </span>
                    )}
                    {t.state !== 'в пути' && t.accepted_at && (
                      <span className="ml-1 text-[10px] text-muted-foreground">{когда(t.accepted_at)}</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {t.task_acked ? 'применена'
                      : t.task_delivered ? 'доставлена, не подтверждена'
                      : 'ждёт станцию'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="px-3 py-2 text-[10px] leading-relaxed text-muted-foreground/70">
        Расхождение — это не ошибка системы, а факт: приняли меньше или больше, чем отправили.
        Разбирается он между двумя станциями и закрывается документом, а не правкой цифры.
      </p>
    </div>
  )
}
