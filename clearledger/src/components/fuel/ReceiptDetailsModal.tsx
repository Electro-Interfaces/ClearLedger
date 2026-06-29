/**
 * Модалка «Детали поступления» — как в TradePoint (display-only).
 * Основная информация + Документ/Факт/Разница + отклонения %.
 */
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useFuelName } from '@/hooks/useFuelName'
import type { LoadedReceipt } from '@/services/fuel/fuelMappingService'

function devVariant(percent: number): 'default' | 'secondary' | 'destructive' {
  const a = Math.abs(percent)
  if (a < 1) return 'default'
  if (a < 3) return 'secondary'
  return 'destructive'
}

const diffClass = (v: number) => v > 0 ? 'text-emerald-500' : v < 0 ? 'text-red-500' : 'text-muted-foreground'

export function ReceiptDetailsModal({ receipt, open, onClose }: {
  receipt: LoadedReceipt | null; open: boolean; onClose: () => void
}) {
  const fuelName = useFuelName()
  if (!receipt) return null

  const dt = receipt.received_at || receipt.created_at
  const docVol = receipt.doc_volume_liters || 0
  const factVol = receipt.fact_volume_liters || 0
  const docMass = receipt.doc_mass_kg || 0
  const factMass = receipt.fact_mass_kg || 0
  const docDens = receipt.density ?? null
  const factDens = receipt.fact_density ?? receipt.density ?? null
  const docTemp = receipt.doc_temp ?? null
  const factTemp = receipt.fact_temp ?? null
  const volDiff = receipt.diff_volume ?? (factVol - docVol)
  const massDiff = receipt.diff_mass ?? (factMass - docMass)
  const volPct = docVol > 0 ? (volDiff / docVol) * 100 : 0
  const massPct = docMass > 0 ? (massDiff / docMass) * 100 : 0

  const num = (v: number | null, d = 2) => (v == null ? '—' : v.toFixed(d))

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl bg-card border-border">
        <DialogHeader className="pb-2">
          <DialogTitle className="text-lg font-semibold">Детали поступления</DialogTitle>
          <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
            <span>ТТН: <span className="text-foreground font-mono">{receipt.ttn}</span></span>
            <span>•</span>
            <span>Смена: <span className="text-foreground">{receipt.shift_number ?? '—'}</span></span>
            <span>•</span>
            <span>ТТ: <span className="text-foreground">{receipt.station_code}</span></span>
          </div>
        </DialogHeader>

        <div className="space-y-3">
          {/* Основная информация */}
          <div className="bg-background rounded-lg p-3 border border-border">
            <h3 className="text-xs font-semibold text-foreground/80 mb-2">Основная информация</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              <div>
                <div className="text-muted-foreground mb-0.5">Дата и время</div>
                <div className="text-foreground">{format(new Date(dt), 'dd.MM.yyyy HH:mm', { locale: ru })}</div>
              </div>
              <div>
                <div className="text-muted-foreground mb-0.5">Вид топлива</div>
                <Badge variant="outline" className="bg-card text-foreground border-border text-xs">{fuelName(receipt.fuel_code, receipt.fuel_name)}</Badge>
              </div>
              <div>
                <div className="text-muted-foreground mb-0.5">Резервуар</div>
                <div className="text-foreground">{receipt.tank != null ? `Резервуар ${receipt.tank}` : '—'}</div>
              </div>
              <div>
                <div className="text-muted-foreground mb-0.5">Нефтебаза</div>
                <div className="text-foreground">{receipt.supplier || '—'}</div>
              </div>
            </div>
          </div>

          {/* Данные поступления — Документ / Факт / Разница */}
          <div className="bg-background rounded-lg p-3 border border-border">
            <h3 className="text-xs font-semibold text-foreground/80 mb-2">Данные поступления</h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-1.5 text-muted-foreground font-medium">Параметр</th>
                  <th className="text-right py-1.5 text-muted-foreground font-medium">Документ</th>
                  <th className="text-right py-1.5 text-muted-foreground font-medium">Факт</th>
                  <th className="text-right py-1.5 text-muted-foreground font-medium">Разница</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border">
                  <td className="py-1.5 text-foreground/80">Объем (л)</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{num(docVol)}</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{num(factVol)}</td>
                  <td className={cn('text-right py-1.5 font-mono', diffClass(volDiff))}>{volDiff > 0 ? '+' : ''}{volDiff.toFixed(2)}</td>
                </tr>
                <tr className="border-b border-border">
                  <td className="py-1.5 text-foreground/80">Масса (кг)</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{num(docMass)}</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{num(factMass)}</td>
                  <td className={cn('text-right py-1.5 font-mono', diffClass(massDiff))}>{massDiff > 0 ? '+' : ''}{massDiff.toFixed(2)}</td>
                </tr>
                <tr className="border-b border-border">
                  <td className="py-1.5 text-foreground/80">Плотность</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{num(docDens, 3)}</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{num(factDens, 3)}</td>
                  <td className={cn('text-right py-1.5 font-mono', docDens != null && factDens != null ? diffClass(factDens - docDens) : 'text-muted-foreground')}>
                    {docDens != null && factDens != null ? `${(factDens - docDens) > 0 ? '+' : ''}${(factDens - docDens).toFixed(3)}` : '—'}
                  </td>
                </tr>
                <tr>
                  <td className="py-1.5 text-foreground/80">Температура (°C)</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{docTemp ?? '—'}</td>
                  <td className="text-right py-1.5 font-mono text-foreground">{factTemp ?? '—'}</td>
                  <td className={cn('text-right py-1.5 font-mono', docTemp != null && factTemp != null ? diffClass(factTemp - docTemp) : 'text-muted-foreground')}>
                    {docTemp != null && factTemp != null ? `${(factTemp - docTemp) > 0 ? '+' : ''}${factTemp - docTemp}` : '—'}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Отклонения */}
          <div className="bg-background rounded-lg p-3 border border-border">
            <h3 className="text-xs font-semibold text-foreground/80 mb-2">Отклонения</h3>
            <div className="grid grid-cols-2 gap-2">
              <div className="flex items-center justify-between p-2 bg-card rounded">
                <div className="text-xs text-muted-foreground">По объему</div>
                <Badge variant={devVariant(volPct)} className="text-xs">{volPct > 0 ? '+' : ''}{volPct.toFixed(2)}%</Badge>
              </div>
              <div className="flex items-center justify-between p-2 bg-card rounded">
                <div className="text-xs text-muted-foreground">По массе</div>
                <Badge variant={devVariant(massPct)} className="text-xs">{massPct > 0 ? '+' : ''}{massPct.toFixed(2)}%</Badge>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
