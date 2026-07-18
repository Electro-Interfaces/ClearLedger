/**
 * Закупочные партии (Шаг 2): менеджер заводит крупную закупку топлива у поставщика
 * (объём + себестоимость), выбирает целевые АЗС; кнопка «Распределить» раскидывает
 * объём на ТТН этих АЗС по ФИФО (по дате поступления) → себестоимость на ТТН →
 * управленческая FIFO-маржа.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Boxes, Trash2, Split, Plus } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  getPurchaseBatches, createPurchaseBatch, deletePurchaseBatch, allocatePurchaseBatch,
  getFuelStations, getFuelTypes, type PurchaseBatch,
} from '@/services/fuel/fuelMappingService'

const fmt = (v: number, d = 0) => (v ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d })
const todayStr = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function PurchaseBatchesPanel({ embedded = false }: { embedded?: boolean }) {
  const qc = useQueryClient()
  const { companyId } = useCompany()
  const { data: batches } = useQuery({ queryKey: ['purchase-batches', companyId], queryFn: getPurchaseBatches })
  const { data: stations } = useQuery({ queryKey: ['fuel-stations-ref', companyId], queryFn: getFuelStations })
  const { data: fuelTypes } = useQuery({ queryKey: ['fuel-types-ref', companyId], queryFn: getFuelTypes })

  const [supplier, setSupplier] = useState('')
  const [fuelCode, setFuelCode] = useState<number | ''>('')
  const [liters, setLiters] = useState('')
  const [unit, setUnit] = useState<'liter' | 'kg'>('liter')
  const [unitCost, setUnitCost] = useState('')
  const [density, setDensity] = useState('')
  const [date, setDate] = useState(todayStr())
  const [stationIds, setStationIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const invalidate = async () => {
    await qc.invalidateQueries({ queryKey: ['purchase-batches'] })
    await qc.invalidateQueries({ queryKey: ['fuel-receipts-journal'] })
    await qc.invalidateQueries({ queryKey: ['fuel-receipts-by-station'] })
    await qc.invalidateQueries({ queryKey: ['costing-margin'] })
    await qc.invalidateQueries({ queryKey: ['margin-decision-dashboard'] })
  }

  const toggleStation = (id: string) =>
    setStationIds((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  const create = async () => {
    if (fuelCode === '' || liters.trim() === '' || unitCost.trim() === '' || stationIds.length === 0) {
      toast.error('Заполните топливо, объём, цену и выберите хотя бы одну АЗС')
      return
    }
    setBusy(true)
    try {
      const fm = fuelTypes?.find((f) => f.service_code === fuelCode)
      await createPurchaseBatch({
        supplier: supplier || null,
        fuel_code: Number(fuelCode),
        fuel_name: fm?.fuel_name ?? null,
        total_liters: Number(liters),
        unit,
        unit_cost: Number(unitCost),
        density: density.trim() === '' ? null : Number(density),
        purchase_date: date,
        target_station_ids: stationIds,
      })
      await invalidate()
      toast.success('Закупочная партия создана', { description: 'Нажмите «Распределить» для разнесения по ТТН.' })
      setSupplier(''); setLiters(''); setUnitCost(''); setDensity(''); setStationIds([])
    } catch (e: unknown) {
      toast.error('Не удалось создать партию', { description: (e as Error)?.message || 'Проверьте плотность для ₽/кг.' })
    } finally { setBusy(false) }
  }

  const allocate = async (b: PurchaseBatch) => {
    setBusy(true)
    try {
      const r = await allocatePurchaseBatch(b.id)
      await invalidate()
      toast.success('Распределено по ФИФО', {
        description: `Покрыто ТТН: ${r.receipts_covered}, распределено ${fmt(r.allocated_liters)} л, остаток партии ${fmt(r.remaining_liters)} л.`,
      })
    } catch (e: unknown) {
      toast.error('Не удалось распределить', { description: (e as Error)?.message || '' })
    } finally { setBusy(false) }
  }

  const remove = async (b: PurchaseBatch) => {
    setBusy(true)
    try {
      await deletePurchaseBatch(b.id)
      await invalidate()
      toast.success('Партия удалена', { description: 'Себестоимость, созданная ею, снята с ТТН.' })
    } catch {
      toast.error('Не удалось удалить партию')
    } finally { setBusy(false) }
  }

  return (
    <div className={embedded ? 'space-y-4 pt-1' : 'p-4 space-y-4'}>
      {/* Форма создания */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium">
            <Boxes className="h-4 w-4 text-muted-foreground" /> Новая закупочная партия
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="space-y-1">
              <Label className="text-[11px]">Поставщик</Label>
              <Input className="h-8 text-xs" value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Нефтебаза" />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Топливо</Label>
              <select className="h-8 w-full rounded border border-border bg-background text-xs px-1"
                value={fuelCode} onChange={(e) => setFuelCode(e.target.value === '' ? '' : Number(e.target.value))}>
                <option value="">— выбрать —</option>
                {fuelTypes?.map((f) => (
                  <option key={f.service_code} value={f.service_code}>{f.fuel_name} (код {f.service_code})</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Объём, л</Label>
              <Input className="h-8 text-right text-xs" inputMode="decimal" value={liters} onChange={(e) => setLiters(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Дата закупки</Label>
              <Input type="date" className="h-8 text-xs" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Единица</Label>
              <select className="h-8 w-full rounded border border-border bg-background text-xs px-1"
                value={unit} onChange={(e) => setUnit(e.target.value as 'liter' | 'kg')}>
                <option value="liter">₽/литр</option>
                <option value="kg">₽/кг</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Цена, {unit === 'kg' ? '₽/кг' : '₽/л'}</Label>
              <Input className="h-8 text-right text-xs" inputMode="decimal" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Плотность{unit === 'kg' ? ' *' : ''}</Label>
              <Input className="h-8 text-right text-xs" inputMode="decimal" value={density} onChange={(e) => setDensity(e.target.value)} placeholder="0.745" />
            </div>
          </div>

          <div className="mt-3">
            <Label className="text-[11px]">Целевые АЗС (распределение по ФИФО)</Label>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {stations?.length ? stations.map((st) => (
                <button key={st.id} onClick={() => toggleStation(st.id)}
                  className={`rounded border px-2 py-1 text-xs transition-colors ${stationIds.includes(st.id) ? 'border-primary bg-primary/15 text-primary' : 'border-border text-muted-foreground hover:bg-accent/40'}`}>
                  {st.name || `АЗС №${st.code}`}
                </button>
              )) : <span className="text-xs text-muted-foreground">Нет станций</span>}
            </div>
          </div>

          <div className="mt-3">
            <Button size="sm" onClick={create} disabled={busy} className="gap-1">
              <Plus className="h-3.5 w-3.5" /> Создать партию
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Список партий */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 text-sm font-medium">Закупочные партии</div>
          {!batches?.length ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Нет закупочных партий.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-xs text-muted-foreground">
                    <th className="py-2 pr-3 text-left font-medium">Поставщик</th>
                    <th className="px-3 text-left font-medium">Топливо</th>
                    <th className="px-3 text-right font-medium">Объём, л</th>
                    <th className="px-3 text-right font-medium">₽/л</th>
                    <th className="px-3 text-right font-medium">Распределено</th>
                    <th className="px-3 text-left font-medium">Статус</th>
                    <th className="pl-3 text-right font-medium">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {batches.map((b) => (
                    <tr key={b.id} className="border-b border-border/30">
                      <td className="py-2 pr-3">{b.supplier || '—'}</td>
                      <td className="px-3">{b.fuel_name || `код ${b.fuel_code}`}</td>
                      <td className="px-3 text-right tabular-nums">{fmt(b.total_liters)}</td>
                      <td className="px-3 text-right tabular-nums">{b.cost_per_liter.toFixed(2)}</td>
                      <td className="px-3 text-right tabular-nums">{fmt(b.allocated_liters)}</td>
                      <td className="px-3">
                        <Badge variant="outline" className={b.status === 'allocated' ? 'border-emerald-400/50 text-emerald-700 dark:text-emerald-300/80' : b.status === 'partial' ? 'border-amber-400/50 text-amber-700 dark:text-amber-300/80' : 'border-zinc-600 text-zinc-500'}>
                          {b.status === 'allocated' ? 'распределена' : b.status === 'partial' ? 'частично' : 'черновик'}
                        </Badge>
                      </td>
                      <td className="pl-3 text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" disabled={busy} onClick={() => allocate(b)}>
                            <Split className="h-3 w-3" /> Распределить
                          </Button>
                          <Button size="sm" variant="ghost" className="h-7 px-2 text-red-400" disabled={busy} onClick={() => remove(b)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
