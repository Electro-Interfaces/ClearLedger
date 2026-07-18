/**
 * Сливы ТТН по станциям — контроль приёмки в разрезе АЗС.
 * Показывает объём док/факт, отклонение (л/кг и %), подсветку проблемных станций;
 * клик по станции открывает журнал ТТН с фильтром по ней.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PackageOpen, ChevronRight } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getLoadedReceipts, type LoadedReceipt } from '@/services/fuel/fuelMappingService'
import { fmtLiters } from '@/services/analyticsService'
import { useCompany } from '@/contexts/CompanyContext'

// Цвет отклонения по модулю процента: >3% — красный, >1% — амбер, иначе нейтральный.
const devCls = (pct: number) =>
  Math.abs(pct) > 3 ? 'text-red-500' : Math.abs(pct) > 1 ? 'text-amber-500' : 'text-muted-foreground'
const fmtPct = (pct: number) => `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`

export function TtnByStationView({ onStationClick }: { onStationClick?: (code: number) => void }) {
  const { companyId } = useCompany()
  const { data } = useQuery({ queryKey: ['fuel-receipts-by-station', companyId], queryFn: () => getLoadedReceipts() })
  const receipts: LoadedReceipt[] = data ?? []

  const byStation = useMemo(() => {
    const map = new Map<number, {
      code: number; name: string; count: number
      docVol: number; factVol: number; diffVol: number; diffMass: number
    }>()
    for (const r of receipts) {
      const e = map.get(r.station_code) ?? {
        code: r.station_code, name: r.station_name ?? `АЗС №${r.station_code}`,
        count: 0, docVol: 0, factVol: 0, diffVol: 0, diffMass: 0,
      }
      e.count += 1
      e.docVol += r.doc_volume_liters || 0
      e.factVol += r.fact_volume_liters || 0
      e.diffVol += r.diff_volume || 0
      e.diffMass += r.diff_mass || 0
      map.set(r.station_code, e)
    }
    // Проблемные станции (наибольшее отклонение) — сверху.
    return [...map.values()].sort((a, b) => Math.abs(b.diffVol) - Math.abs(a.diffVol))
  }, [receipts])

  const totals = useMemo(() => byStation.reduce((t, s) => ({
    count: t.count + s.count, docVol: t.docVol + s.docVol, factVol: t.factVol + s.factVol,
    diffVol: t.diffVol + s.diffVol, diffMass: t.diffMass + s.diffMass,
  }), { count: 0, docVol: 0, factVol: 0, diffVol: 0, diffMass: 0 }), [byStation])
  const totalPct = totals.docVol > 0 ? (totals.diffVol / totals.docVol) * 100 : 0

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <PackageOpen className="h-4 w-4 text-muted-foreground" />
          Сливы ТТН по станциям
          <span className="text-xs font-normal text-muted-foreground">— клик по станции открывает её ТТН</span>
        </div>
        {byStation.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Нет загруженных ТТН.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-xs text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-medium">Станция</th>
                  <th className="px-3 text-right font-medium">ТТН</th>
                  <th className="px-3 text-right font-medium">Объём док, л</th>
                  <th className="px-3 text-right font-medium">Объём факт, л</th>
                  <th className="px-3 text-right font-medium">Δ объём, л</th>
                  <th className="px-3 text-right font-medium">Δ, %</th>
                  <th className="pl-3 text-right font-medium">Δ масса, кг</th>
                  <th className="w-6" />
                </tr>
              </thead>
              <tbody>
                {byStation.map((s) => {
                  const pct = s.docVol > 0 ? (s.diffVol / s.docVol) * 100 : 0
                  return (
                    <tr key={s.code}
                      onClick={() => onStationClick?.(s.code)}
                      className={cn('group border-b border-border/30', onStationClick && 'cursor-pointer hover:bg-accent/40',
                        Math.abs(pct) > 3 && 'bg-red-500/[0.04]', Math.abs(pct) > 1 && Math.abs(pct) <= 3 && 'bg-amber-400/[0.05]')}>
                      <td className="py-2 pr-3 font-medium">{s.name}</td>
                      <td className="px-3 text-right tabular-nums text-muted-foreground">{s.count}</td>
                      <td className="px-3 text-right tabular-nums">{fmtLiters(s.docVol)}</td>
                      <td className="px-3 text-right tabular-nums">{fmtLiters(s.factVol)}</td>
                      <td className={cn('px-3 text-right tabular-nums font-medium', devCls(pct))}>
                        {s.diffVol > 0 ? '+' : ''}{fmtLiters(s.diffVol)}
                      </td>
                      <td className={cn('px-3 text-right tabular-nums', devCls(pct))}>{fmtPct(pct)}</td>
                      <td className={cn('pl-3 text-right tabular-nums', devCls(pct))}>
                        {s.diffMass > 0 ? '+' : ''}{s.diffMass.toFixed(1)}
                      </td>
                      <td className="pl-1 text-muted-foreground/40">
                        {onStationClick && <ChevronRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border font-semibold">
                  <td className="py-2 pr-3">ИТОГО</td>
                  <td className="px-3 text-right tabular-nums text-muted-foreground">{totals.count}</td>
                  <td className="px-3 text-right tabular-nums">{fmtLiters(totals.docVol)}</td>
                  <td className="px-3 text-right tabular-nums">{fmtLiters(totals.factVol)}</td>
                  <td className={cn('px-3 text-right tabular-nums', devCls(totalPct))}>
                    {totals.diffVol > 0 ? '+' : ''}{fmtLiters(totals.diffVol)}
                  </td>
                  <td className={cn('px-3 text-right tabular-nums', devCls(totalPct))}>{fmtPct(totalPct)}</td>
                  <td className={cn('pl-3 text-right tabular-nums', devCls(totalPct))}>
                    {totals.diffMass > 0 ? '+' : ''}{totals.diffMass.toFixed(1)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
