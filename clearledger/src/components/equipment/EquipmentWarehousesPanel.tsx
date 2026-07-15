/**
 * «Склады и остатки» — сводка складского учёта оборудования ЭЗС.
 *
 * KPI (склады · единицы · внешние держатели · ЗИП) + таблица складов с
 * разбивкой единиц по состояниям + карточка внешних держателей (подрядчики,
 * производитель). Создание склада — через справочник точек обслуживания
 * (createLocation, type='warehouse'); свежесозданный склад показывается
 * сразу (merge локального справочника с бэкенд-сводкой).
 */

import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Plus, Warehouse } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Kpi } from '@/components/workspace/analytics/Kpi'
import { getWarehousesSummary, type UnitState, type WarehouseSummaryRow } from '@/services/equipmentService'
import { createLocation, loadLocations } from '@/services/locationService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

/** Колонки-состояния таблицы складов (порядок фиксирован). */
const STATE_COLS: { state: UnitState; label: string }[] = [
  { state: 'in_stock_new', label: 'Новые' },
  { state: 'in_stock_used', label: 'Б/у' },
  { state: 'reserved', label: 'Резерв' },
  { state: 'in_repair', label: 'В ремонте' },
]

function Num({ v, dim }: { v: number; dim?: boolean }) {
  if (!v) return <span className="text-muted-foreground/40">—</span>
  return <span className={dim ? 'text-muted-foreground' : undefined}>{nf0.format(v)}</span>
}

/** Следующий свободный код склада вида SKL-N (по существующим кодам). */
function nextWarehouseCode(existing: string[]): string {
  let max = 0
  for (const c of existing) {
    const m = /^SKL-(\d+)$/i.exec(c.trim())
    if (m) max = Math.max(max, Number(m[1]))
  }
  return `SKL-${max + 1}`
}

function NewWarehouseDialog({ existingCodes, onCreated }: {
  existingCodes: string[]
  onCreated: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')

  function handleCreate() {
    if (!name.trim()) {
      toast.error('Укажите название склада')
      return
    }
    createLocation({
      code: nextWarehouseCode(existingCodes),
      name: name.trim(),
      type: 'warehouse',
      status: 'active',
      address: address.trim() || undefined,
    })
    toast.success(`Создан склад «${name.trim()}»`)
    setName('')
    setAddress('')
    setOpen(false)
    onCreated()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-8">
          <Plus className="mr-1.5 h-4 w-4" />
          Новый склад
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Новый склад</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="wh-name">Название</Label>
            <Input id="wh-name" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="Склад Хабаровск" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wh-address">Адрес (необязательно)</Label>
            <Input id="wh-address" value={address} onChange={(e) => setAddress(e.target.value)}
              placeholder="г. Хабаровск, ул. Промышленная, 5" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={handleCreate}>Создать</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function EquipmentWarehousesPanel({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['equipment-warehouses', companyId],
    queryFn: () => getWarehousesSummary(companyId),
  })
  const locationsQ = useQuery({
    queryKey: ['equipment-locations', companyId],
    queryFn: () => loadLocations(companyId),
  })

  // Сводка бэкенда + локальные склады, которых в ней ещё нет (свежесозданные,
  // зеркало в бэкенд асинхронное) — нулевыми строками.
  const rows = useMemo<WarehouseSummaryRow[]>(() => {
    const summary = data?.warehouses ?? []
    const known = new Set(summary.map((w) => w.location.id))
    const extra = (locationsQ.data ?? [])
      .filter((l) => l.type === 'warehouse' && !known.has(l.id))
      .map((l): WarehouseSummaryRow => ({
        location: { id: l.id, name: l.name, type: l.type, address: l.address ?? null },
        unitsByState: {},
        unitsTotal: 0,
        sparePositions: 0,
        spareQty: 0,
      }))
      .sort((a, b) => a.location.name.localeCompare(b.location.name, 'ru'))
    return [...summary, ...extra]
  }, [data, locationsQ.data])

  const external = data?.external ?? []
  const existingCodes = useMemo(
    () => (locationsQ.data ?? []).map((l) => l.code),
    [locationsQ.data],
  )

  const refresh = () => {
    const invalidate = () => {
      void qc.invalidateQueries({ queryKey: ['equipment-warehouses', companyId] })
      void qc.invalidateQueries({ queryKey: ['equipment-locations', companyId] })
    }
    invalidate()
    // Зеркало createLocation в бэкенд — fire-and-forget: перечитываем ещё раз.
    setTimeout(invalidate, 900)
  }

  const kpi = useMemo(() => ({
    warehouses: rows.length,
    units: rows.reduce((a, w) => a + w.unitsTotal, 0),
    contractor: external.find((e) => e.custodian === 'contractor')?.unitsTotal ?? 0,
    vendor: external.find((e) => e.custodian === 'vendor')?.unitsTotal ?? 0,
    sparePositions: rows.reduce((a, w) => a + w.sparePositions, 0),
  }), [rows, external])

  const totals = useMemo(() => ({
    byState: STATE_COLS.map((c) => rows.reduce((a, w) => a + (w.unitsByState[c.state] ?? 0), 0)),
    unitsTotal: rows.reduce((a, w) => a + w.unitsTotal, 0),
    sparePositions: rows.reduce((a, w) => a + w.sparePositions, 0),
    spareQty: rows.reduce((a, w) => a + w.spareQty, 0),
  }), [rows])

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Склады и остатки оборудования</div>
        <NewWarehouseDialog existingCodes={existingCodes} onCreated={refresh} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi label="Складов" value={nf0.format(kpi.warehouses)} />
        <Kpi label="Единиц на складах" value={nf0.format(kpi.units)} />
        <Kpi label="У подрядчиков" value={nf0.format(kpi.contractor)} />
        <Kpi label="У производителя" value={nf0.format(kpi.vendor)} />
        <Kpi label="Позиций ЗИП" value={nf0.format(kpi.sparePositions)} />
      </div>

      {rows.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Складов пока нет — создайте первый.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-2 text-left font-medium">Склад</th>
                  {STATE_COLS.map((c) => (
                    <th key={c.state} className="p-2 text-right font-medium whitespace-nowrap">{c.label}</th>
                  ))}
                  <th className="p-2 text-right font-medium whitespace-nowrap">Всего единиц</th>
                  <th className="p-2 text-right font-medium whitespace-nowrap">Позиций ЗИП</th>
                  <th className="p-2 text-right font-medium whitespace-nowrap">Кол-во ЗИП</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((w) => (
                  <tr key={w.location.id} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2">
                      <div className="flex items-center gap-1.5 font-medium">
                        <Warehouse className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                        {w.location.name}
                      </div>
                      {w.location.address && (
                        <div className="mt-0.5 max-w-[320px] truncate text-[11px] text-muted-foreground" title={w.location.address}>
                          {w.location.address}
                        </div>
                      )}
                    </td>
                    {STATE_COLS.map((c) => (
                      <td key={c.state} className="p-2 text-right font-mono">
                        <Num v={w.unitsByState[c.state] ?? 0} />
                      </td>
                    ))}
                    <td className="p-2 text-right font-mono font-semibold"><Num v={w.unitsTotal} /></td>
                    <td className="p-2 text-right font-mono"><Num v={w.sparePositions} dim /></td>
                    <td className="p-2 text-right font-mono"><Num v={w.spareQty} dim /></td>
                  </tr>
                ))}
                <tr className="bg-muted/60 font-medium">
                  <td className="p-2">Итого</td>
                  {totals.byState.map((v, i) => (
                    <td key={STATE_COLS[i].state} className="p-2 text-right font-mono"><Num v={v} /></td>
                  ))}
                  <td className="p-2 text-right font-mono"><Num v={totals.unitsTotal} /></td>
                  <td className="p-2 text-right font-mono"><Num v={totals.sparePositions} /></td>
                  <td className="p-2 text-right font-mono"><Num v={totals.spareQty} /></td>
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {external.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="border-b bg-muted/20 px-3 py-1.5 text-[11px] font-medium">
              Вне наших локаций
              <span className="ml-2 font-normal text-muted-foreground">единицы у внешних держателей</span>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-2 text-left font-medium">Держатель</th>
                  <th className="p-2 text-right font-medium whitespace-nowrap">Единиц</th>
                  <th className="p-2 text-left font-medium">Кто именно</th>
                </tr>
              </thead>
              <tbody>
                {external.map((e) => (
                  <tr key={e.custodian} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-medium whitespace-nowrap">{e.custodianLabel}</td>
                    <td className="p-2 text-right font-mono">{nf0.format(e.unitsTotal)}</td>
                    <td className="p-2 text-muted-foreground">{e.names.length > 0 ? e.names.join(', ') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
