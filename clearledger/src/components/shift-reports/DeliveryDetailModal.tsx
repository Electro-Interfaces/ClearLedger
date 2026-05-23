/**
 * Просмотрщик ТТН (товарно-транспортная накладная / слив бензовоза).
 */

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Truck } from 'lucide-react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import type { DeliveryRecord } from '@/services/receiptExtractService'

interface Props {
  delivery: DeliveryRecord | null
  onClose: () => void
}

function fmtDT(d: string) { return format(new Date(d), 'dd.MM.yyyy HH:mm', { locale: ru }) }
function fmtNum(v: number, digits = 3) {
  return v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function DeliveryDetailModal({ delivery, onClose }: Props) {
  if (!delivery) return null

  const hasDiff = Math.abs(delivery.diffVolumeLiters) > 0.01 || Math.abs(delivery.diffMassKg) > 0.01

  return (
    <Dialog open={!!delivery} onOpenChange={onClose}>
      <DialogContent className="!max-w-none !w-[100vw] !h-[100vh] !rounded-none !border-none !p-4 flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-3">
            <Truck className="h-5 w-5" />
            ТТН {delivery.ttn} — {delivery.fuelName}
          </DialogTitle>
          <p className="text-sm text-muted-foreground">
            {delivery.stationName} · Смена №{delivery.shiftNumber} · {fmtDT(delivery.deliveredAt)}
          </p>
        </DialogHeader>

        <div className="space-y-6 flex-1 overflow-y-auto">
          {/* Основная информация */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-secondary/50 rounded-lg p-3">
              <div className="text-xs text-muted-foreground mb-1">Поставщик</div>
              <div className="text-sm font-semibold">{delivery.supplierName}</div>
            </div>
            <div className="bg-secondary/50 rounded-lg p-3">
              <div className="text-xs text-muted-foreground mb-1">Вид топлива</div>
              <div className="text-sm font-semibold">{delivery.fuelName} (код {delivery.fuelCode})</div>
            </div>
            <div className="bg-secondary/50 rounded-lg p-3">
              <div className="text-xs text-muted-foreground mb-1">Резервуар</div>
              <div className="text-sm font-semibold">№{delivery.tankNumber}</div>
            </div>
            <div className="bg-secondary/50 rounded-lg p-3">
              <div className="text-xs text-muted-foreground mb-1">Дата слива</div>
              <div className="text-sm font-semibold">{fmtDT(delivery.deliveredAt)}</div>
            </div>
          </div>

          {/* Таблица документ vs факт */}
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-secondary/80">
                <tr className="border-b-2 border-border">
                  <th className="px-4 py-3 text-left font-medium"></th>
                  <th className="px-4 py-3 text-right font-medium">Объём, л</th>
                  <th className="px-4 py-3 text-right font-medium">Масса, кг</th>
                  <th className="px-4 py-3 text-right font-medium">Плотность, г/см³</th>
                  <th className="px-4 py-3 text-right font-medium">Температура, °C</th>
                </tr>
              </thead>
              <tbody className="bg-card">
                <tr className="border-b border-border">
                  <td className="px-4 py-3 font-medium">По документу</td>
                  <td className="px-4 py-3 text-right">{fmtNum(delivery.docVolumeLiters)}</td>
                  <td className="px-4 py-3 text-right">{fmtNum(delivery.docMassKg)}</td>
                  <td className="px-4 py-3 text-right">{delivery.docDensity.toFixed(4)}</td>
                  <td className="px-4 py-3 text-right">{delivery.docTemp.toFixed(1)}</td>
                </tr>
                <tr className="border-b border-border">
                  <td className="px-4 py-3 font-medium">Фактически</td>
                  <td className="px-4 py-3 text-right">{fmtNum(delivery.factVolumeLiters)}</td>
                  <td className="px-4 py-3 text-right">{fmtNum(delivery.factMassKg)}</td>
                  <td className="px-4 py-3 text-right">{delivery.factDensity.toFixed(4)}</td>
                  <td className="px-4 py-3 text-right">{delivery.factTemp.toFixed(1)}</td>
                </tr>
                <tr className="bg-secondary/50 font-bold">
                  <td className="px-4 py-3">
                    Расхождение
                    {hasDiff && <Badge variant="destructive" className="ml-2 text-[10px]">!</Badge>}
                  </td>
                  <td className={`px-4 py-3 text-right ${Math.abs(delivery.diffVolumeLiters) > 0.01 ? 'text-destructive' : ''}`}>
                    {delivery.diffVolumeLiters > 0 ? '+' : ''}{fmtNum(delivery.diffVolumeLiters)}
                  </td>
                  <td className={`px-4 py-3 text-right ${Math.abs(delivery.diffMassKg) > 0.01 ? 'text-destructive' : ''}`}>
                    {delivery.diffMassKg > 0 ? '+' : ''}{fmtNum(delivery.diffMassKg)}
                  </td>
                  <td className="px-4 py-3 text-right text-muted-foreground">
                    {(delivery.factDensity - delivery.docDensity).toFixed(4)}
                  </td>
                  <td className="px-4 py-3 text-right text-muted-foreground">
                    {(delivery.factTemp - delivery.docTemp).toFixed(1)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
