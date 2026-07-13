/**
 * Модалка «Детали поступления» — как в TradePoint (display-only).
 * Основная информация + Документ/Факт/Разница + отклонения %.
 */
import { useEffect, useState } from 'react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw, Coins, Pencil } from 'lucide-react'
import { toast } from 'sonner'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { useFuelName } from '@/hooks/useFuelName'
import { ReceiptFifoSales } from '@/components/fuel/ReceiptFifoSales'
import {
  patchReceipt, resetReceiptOverride, setReceiptCost, deleteReceiptCost,
  getReceiptCosting, type LoadedReceipt,
} from '@/services/fuel/fuelMappingService'

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
  const qc = useQueryClient()
  const [vol, setVol] = useState('')
  const [mass, setMass] = useState('')
  const [dens, setDens] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    setVol(receipt ? String(receipt.doc_volume_liters ?? '') : '')
    setMass(receipt ? String(receipt.doc_mass_kg ?? '') : '')
    setDens(receipt?.density != null ? String(receipt.density) : '')
    setNote(receipt?.note ?? '')
  }, [receipt?.id, receipt?.doc_volume_liters, receipt?.doc_mass_kg, receipt?.density, receipt?.note])

  const numOrNull = (v: string): number | null => (v.trim() === '' ? null : Number(v))
  const saveEdit = async () => {
    if (!receipt) return
    setSaving(true)
    try {
      await patchReceipt(receipt.id, {
        doc_volume_liters: numOrNull(vol), doc_mass_kg: numOrNull(mass), density: numOrNull(dens),
        note: note.trim() || null,
      })
      await qc.invalidateQueries({ queryKey: ['fuel-receipts-journal'] })
      await qc.invalidateQueries({ queryKey: ['fuel-receipts-by-station'] })
      toast.success('Корректировка ТТН сохранена (L2)', {
        description: 'Пересоберите пакеты выгрузки для обновления документов 1С.',
      })
      onClose()
    } catch {
      toast.error('Не удалось сохранить', { description: 'ТТН может быть в закрытом периоде.' })
    } finally { setSaving(false) }
  }
  const resetEdit = async () => {
    if (!receipt) return
    setSaving(true)
    try {
      await resetReceiptOverride(receipt.id)
      await qc.invalidateQueries({ queryKey: ['fuel-receipts-journal'] })
      await qc.invalidateQueries({ queryKey: ['fuel-receipts-by-station'] })
      toast.success('Корректировка ТТН сброшена к данным STS')
      onClose()
    } catch {
      toast.error('Не удалось сбросить корректировку')
    } finally { setSaving(false) }
  }

  // ── Себестоимость партии (FIFO-маржа) ──
  const [costUnit, setCostUnit] = useState<'liter' | 'kg'>('liter')
  const [costPrice, setCostPrice] = useState('')
  const [costDens, setCostDens] = useState('')
  useEffect(() => {
    setCostUnit((receipt?.cost_unit as 'liter' | 'kg') || 'liter')
    setCostPrice(receipt?.has_cost && receipt.cost_unit_price != null ? String(receipt.cost_unit_price) : '')
    setCostDens(receipt?.density != null ? String(receipt.density) : '')
  }, [receipt?.id, receipt?.has_cost, receipt?.cost_unit, receipt?.cost_unit_price, receipt?.density])

  const costing = useQuery({
    queryKey: ['receipt-costing', receipt?.id],
    queryFn: () => getReceiptCosting(receipt!.id),
    enabled: !!receipt?.id && open && !!receipt?.has_cost,
  })

  const invalidateCost = async () => {
    await qc.invalidateQueries({ queryKey: ['fuel-receipts-journal'] })
    await qc.invalidateQueries({ queryKey: ['fuel-receipts-by-station'] })
    await qc.invalidateQueries({ queryKey: ['receipt-costing', receipt?.id] })
    await qc.invalidateQueries({ queryKey: ['costing-margin'] })
    await qc.invalidateQueries({ queryKey: ['margin-decision-dashboard'] })
  }
  const saveCost = async () => {
    if (!receipt || costPrice.trim() === '') return
    setSaving(true)
    try {
      await setReceiptCost(receipt.id, {
        unit: costUnit, unit_cost: Number(costPrice),
        density: costDens.trim() === '' ? null : Number(costDens),
      })
      await invalidateCost()
      toast.success('Себестоимость партии сохранена', {
        description: 'Учтётся в управленческой марже (FIFO).',
      })
    } catch (e: unknown) {
      toast.error('Не удалось сохранить себестоимость', {
        description: (e as Error)?.message || 'Проверьте плотность для ₽/кг.',
      })
    } finally { setSaving(false) }
  }
  const removeCost = async () => {
    if (!receipt) return
    setSaving(true)
    try {
      await deleteReceiptCost(receipt.id)
      await invalidateCost()
      toast.success('Себестоимость партии убрана')
    } catch {
      toast.error('Не удалось убрать себестоимость')
    } finally { setSaving(false) }
  }

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

  // Реально изменённые поля документа (для подсветки и «было») — устойчиво к ложным override.
  const volChanged = receipt.src_volume != null && Math.abs(receipt.src_volume - docVol) > 0.005
  const massChanged = receipt.src_mass != null && Math.abs(receipt.src_mass - docMass) > 0.005
  const densChanged = receipt.src_density != null && docDens != null && Math.abs(receipt.src_density - docDens) > 0.005
  const editInp = (changed: boolean) =>
    `h-7 text-right text-xs ${changed ? 'border-amber-400 ring-1 ring-amber-400/40 bg-amber-50 font-semibold text-amber-700 dark:bg-amber-400/10 dark:text-amber-200' : ''}`

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-[calc(100%-2rem)] sm:max-w-6xl max-h-[90vh] overflow-y-auto bg-card border-border">
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

          {/* Слева — Данные/Отклонения · Справа — Корректировка/Себестоимость (чтобы влезало по высоте) */}
          <div className="grid items-start gap-3 lg:grid-cols-2">
          <div className="space-y-3">
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
          </div>{/* /левая колонка (данные + отклонения) */}

          <div className="space-y-3">
          {/* Корректировка значений документа для 1С (L2 CLEAN) */}
          <div className="bg-background rounded-lg p-3 border border-amber-400/30">
            <h3 className="text-xs font-semibold text-foreground/80 mb-1 flex items-center gap-1.5">
              <Pencil className="h-3.5 w-3.5 text-amber-500" /> Корректировка для 1С
              {receipt.has_corrections && <Badge className="border-transparent bg-amber-100 text-[10px] font-medium text-amber-700 dark:bg-amber-400/15 dark:text-amber-300">правка</Badge>}
            </h3>
            <p className="text-[11px] text-muted-foreground mb-2">
              Значения документа, которые пойдут в 1С (Перемещение тонн + Комплектация). Правка хранится
              в L2, переживает перезагрузку из STS. После — пересоберите пакеты выгрузки.
            </p>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <Label className="text-[11px]">Объём док, л</Label>
                <Input className={editInp(volChanged)} inputMode="decimal" value={vol} onChange={(e) => setVol(e.target.value)} />
                {volChanged && <div className="text-right text-[10px] font-medium text-amber-600 dark:text-amber-400">было: {receipt.src_volume}</div>}
              </div>
              <div className="space-y-1">
                <Label className="text-[11px]">Масса док, кг</Label>
                <Input className={editInp(massChanged)} inputMode="decimal" value={mass} onChange={(e) => setMass(e.target.value)} />
                {massChanged && <div className="text-right text-[10px] font-medium text-amber-600 dark:text-amber-400">было: {receipt.src_mass}</div>}
              </div>
              <div className="space-y-1">
                <Label className="text-[11px]">Плотность</Label>
                <Input className={editInp(densChanged)} inputMode="decimal" value={dens} onChange={(e) => setDens(e.target.value)} />
                {densChanged && <div className="text-right text-[10px] font-medium text-amber-600 dark:text-amber-400">было: {receipt.src_density}</div>}
              </div>
            </div>
            {/* Комментарий менеджера — в целом по документу (ТТН) */}
            <div className="mt-2 space-y-1">
              <Label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Pencil className="h-3 w-3 text-amber-500" /> Комментарий менеджера по корректировке
              </Label>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={500}
                placeholder="Причина и суть правки по этой ТТН (сохраняется в L2 вместе с корректировкой)…"
                className="w-full resize-y rounded-md border border-input bg-transparent px-2 py-1.5 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
            </div>
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" onClick={saveEdit} disabled={saving} className="gap-1">
                <Save className="h-3.5 w-3.5" /> Сохранить
              </Button>
              <Button size="sm" variant="outline" onClick={resetEdit} disabled={saving || !receipt.is_manual} className="gap-1">
                <RotateCcw className="h-3.5 w-3.5" /> Сбросить к STS
              </Button>
            </div>
          </div>

          {/* Себестоимость партии (FIFO-маржа) */}
          <div className="bg-background rounded-lg p-3 border border-emerald-400/30">
            <h3 className="text-xs font-semibold text-foreground/80 mb-1 flex items-center gap-1.5">
              <Coins className="h-3.5 w-3.5 text-emerald-500" /> Себестоимость партии
              {receipt.has_cost && <Badge variant="outline" className="text-[10px] border-emerald-400/50 text-emerald-300/80">задана</Badge>}
            </h3>
            <p className="text-[11px] text-muted-foreground mb-2">
              Себестоимость закупки этой партии (ТТН). Списывается на продажи по ФИФО → управленческая маржа.
            </p>
            <div className="grid grid-cols-3 gap-2 items-end">
              <div className="space-y-1">
                <Label className="text-[11px]">Единица</Label>
                <select
                  className="h-7 w-full rounded border border-border bg-background text-xs px-1"
                  value={costUnit}
                  onChange={(e) => setCostUnit(e.target.value as 'liter' | 'kg')}
                >
                  <option value="liter">₽/литр</option>
                  <option value="kg">₽/кг</option>
                </select>
              </div>
              <div className="space-y-1">
                <Label className="text-[11px]">Цена, {costUnit === 'kg' ? '₽/кг' : '₽/л'}</Label>
                <Input className="h-7 text-right text-xs" inputMode="decimal" value={costPrice} onChange={(e) => setCostPrice(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label className="text-[11px]">Плотность{costUnit === 'kg' ? ' *' : ''}</Label>
                <Input className="h-7 text-right text-xs" inputMode="decimal" value={costDens} onChange={(e) => setCostDens(e.target.value)} />
              </div>
            </div>
            {receipt.has_cost && receipt.cost_per_liter != null && (
              <p className="mt-1.5 text-[10px] text-muted-foreground">
                = {receipt.cost_per_liter.toFixed(4)} ₽/л (нормализовано для FIFO-маржи)
              </p>
            )}
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" onClick={saveCost} disabled={saving || costPrice.trim() === ''} className="gap-1">
                <Save className="h-3.5 w-3.5" /> Сохранить
              </Button>
              <Button size="sm" variant="outline" onClick={removeCost} disabled={saving || !receipt.has_cost} className="gap-1">
                <RotateCcw className="h-3.5 w-3.5" /> Убрать
              </Button>
            </div>
          </div>
          </div>{/* /правая колонка (корректировка + себестоимость) */}
          </div>{/* /grid 2 колонки */}
          {receipt.has_cost && <ReceiptFifoSales key={receipt.id} costing={costing.data} loading={costing.isLoading} />}
        </div>
      </DialogContent>
    </Dialog>
  )
}
