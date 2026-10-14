/**
 * «Склады и остатки» — сводка складского учёта оборудования ЭЗС.
 *
 * KPI (склады · единицы · сумма · внешние держатели · ЗИП) + таблица складов с
 * разбивкой единиц по складским состояниям и суммой остатка + единицы вне складов
 * (у подрядчика, у производителя). Название склада и кнопка «Карточка» открывают
 * карточку: остатки на дату по номенклатуре, реквизиты, закрытие и удаление.
 * Любое число раскрывается в список единиц, строка списка — в карточку единицы.
 */

import { useMemo, useState } from 'react'
import { SortTh } from '@/components/workspace/SortableTh'
import { useTableSort } from '@/hooks/useTableSort'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { FileText, Loader2, Plus, Warehouse } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Kpi } from '@/components/workspace/analytics/Kpi'
import { ApiError } from '@/services/apiClient'
import {
  createWarehouse, getWarehousesSummary, listUnits, UNIT_STATE_META,
  type UnitState, type WarehouseSummaryRow,
} from '@/services/equipmentService'
import { loadLocations } from '@/services/locationService'
import { UnitDetailsDialog } from './EquipmentFleetPanel'
import { eqName } from './equipmentDocPrint'
import { ExportXlsxButton, LoadError } from './equipmentShared'
import { invalidateEquipment } from './useEquipmentScope'
import { CONTRACT_STATUS, WarehouseCardDialog } from './WarehouseCardDialog'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const rub = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Колонки-состояния таблицы складов (порядок фиксирован) — только складские. */
const STATE_COLS: { state: UnitState; label: string }[] = [
  { state: 'in_stock_new', label: 'Новые' },
  { state: 'in_stock_used', label: 'Б/у' },
  { state: 'reserved', label: 'Резерв' },
  { state: 'in_repair', label: 'В ремонте' },
]
/** Единица ещё у держателя: не списана и не возвращена поставщику. */
const HELD_STATES = (Object.keys(UNIT_STATE_META) as UnitState[])
  .filter((s) => s !== 'written_off' && s !== 'returned_to_vendor').join(',')
const LIST_LIMIT = 200

type Drill = { title: string; locationId?: string; state?: string; custodian?: string }

/** Число, которое раскрывается в список единиц. */
function Num({ v, dim, onOpen }: { v: number; dim?: boolean; onOpen?: () => void }) {
  if (!v) return <span className="text-muted-foreground/40">—</span>
  if (!onOpen) return <span className={dim ? 'text-muted-foreground' : undefined}>{nf0.format(v)}</span>
  return (
    <button type="button" title="Показать единицы" onClick={onOpen}
      className="underline decoration-dotted underline-offset-2 hover:text-primary">
      {nf0.format(v)}
    </button>
  )
}

function NewWarehouseDialog({ companyId, onCreated }: { companyId: string; onCreated: (id: string) => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const mut = useMutation({
    mutationFn: () => createWarehouse(companyId, { name: name.trim(), address: address.trim() || null }),
    onSuccess: (w) => {
      toast.success(`Создан склад «${w.name}»`)
      setName('')
      setAddress('')
      setOpen(false)
      void invalidateEquipment(qc)
      onCreated(w.id)
    },
    onError: (e) => toast.error('Склад не создан', { description: e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e) }),
  })

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
          <p className="text-xs text-muted-foreground">
            После создания откроется карточка склада: там указываются вид владения, договор, МОЛ и код склада в 1С.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={() => mut.mutate()} disabled={!name.trim() || mut.isPending}>
            {mut.isPending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Содержимое склада или внешнего держателя: список единиц, строка открывает карточку. */
function UnitsListDialog({ companyId, drill, onOpenUnit, onClose }: {
  companyId: string; drill: Drill; onOpenUnit: (id: string) => void; onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['equipment', 'units', companyId, 'drill', drill.locationId, drill.state, drill.custodian],
    queryFn: () => listUnits({
      companyId, locationId: drill.locationId, state: drill.state, custodian: drill.custodian,
      sort: 'serialNumber', dir: 'asc', pageSize: LIST_LIMIT,
    }),
  })
  const items = q.data?.items ?? []
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[90dvh] overflow-y-auto">
        <DialogHeader><DialogTitle>{drill.title}</DialogTitle></DialogHeader>
        {q.isLoading ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          : q.isError ? <LoadError what="список единиц" error={q.error} onRetry={() => void q.refetch()} />
          : items.length === 0 ? <p className="text-sm text-muted-foreground">Единиц нет.</p>
          : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/40 text-left text-muted-foreground">
                    <th className="p-2 font-medium">Серийный №</th>
                    <th className="p-2 font-medium">Инв. №</th>
                    <th className="p-2 font-medium">Оборудование</th>
                    <th className="p-2 font-medium">Состояние</th>
                    <th className="p-2 font-medium">{drill.custodian ? 'У кого' : 'Резерв под станцию'}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((u) => (
                    <tr key={u.id} className="cursor-pointer border-b border-border/30 hover:bg-muted/30"
                      title="Открыть карточку единицы" onClick={() => onOpenUnit(u.id)}>
                      <td className="p-2 font-mono">{u.serialNumber ?? '—'}</td>
                      <td className="p-2 font-mono">{u.inventoryNumber ?? '—'}</td>
                      <td className="p-2">{eqName(u.vendor ?? u.vendorRaw, u.model) || '—'}</td>
                      <td className="p-2 whitespace-nowrap">{u.stateLabel}</td>
                      <td className="p-2">{(drill.custodian ? u.custodianName : u.reservedFor?.name) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(q.data?.total ?? 0) > items.length && (
                <p className="p-2 text-xs text-muted-foreground">
                  Показаны первые {items.length} из {nf0.format(q.data?.total ?? 0)} — полный список в «Парке оборудования» с отбором по складу.
                </p>
              )}
            </div>
          )}
      </DialogContent>
    </Dialog>
  )
}

export function EquipmentWarehousesPanel({ companyId }: { companyId: string }) {
  const [card, setCard] = useState<{ id: string; tab: 'stock' | 'card' } | null>(null)
  const [showClosed, setShowClosed] = useState(false)
  const [drill, setDrill] = useState<Drill | null>(null)
  const [unitId, setUnitId] = useState<string | null>(null)
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['equipment', 'warehouses', companyId],
    queryFn: () => getWarehousesSummary(companyId),
  })
  // Склады и станции нужны карточке единицы (операции из неё).
  const locationsQ = useQuery({
    queryKey: ['equipment', 'locations', companyId],
    queryFn: () => loadLocations(companyId),
    staleTime: 60_000,
  })
  const warehouses = useMemo(() => (locationsQ.data ?? []).filter((l) => l.type === 'warehouse' && l.status !== 'closed'), [locationsQ.data])
  const sites = useMemo(() => (locationsQ.data ?? []).filter((l) => l.type === 'ev_charging'), [locationsQ.data])

  const allRows = useMemo(() => data?.warehouses ?? [], [data])
  const closedCount = allRows.filter((w) => w.status === 'closed').length
  const rows = useMemo(() => allRows.filter((w) => showClosed || w.status !== 'closed'), [allRows, showClosed])

  // Склады сравнивают по загруженности: где скопились единицы, где пусто.
  const сортировка = useMemo(() => ({
    name: (w: WarehouseSummaryRow) => w.location.name,
    units: (w: WarehouseSummaryRow) => w.unitsTotal,
    spareLines: (w: WarehouseSummaryRow) => w.sparePositions,
    spareQty: (w: WarehouseSummaryRow) => w.spareQty,
    amount: (w: WarehouseSummaryRow) => w.amount ?? 0,
  }), [])
  const склады = useTableSort(rows, сортировка)

  const external = useMemo(() => data?.external ?? [], [data])

  const kpi = useMemo(() => ({
    warehouses: rows.length,
    units: rows.reduce((a, w) => a + w.unitsTotal, 0),
    contractor: external.find((e) => e.custodian === 'contractor')?.unitsTotal ?? 0,
    vendor: external.find((e) => e.custodian === 'vendor')?.unitsTotal ?? 0,
    sparePositions: rows.reduce((a, w) => a + w.sparePositions, 0),
    amount: rows.reduce((a, w) => a + (w.amount ?? 0), 0),
  }), [rows, external])

  const totals = useMemo(() => ({
    byState: STATE_COLS.map((c) => rows.reduce((a, w) => a + (w.unitsByState[c.state] ?? 0), 0)),
    unitsTotal: rows.reduce((a, w) => a + w.unitsTotal, 0),
    sparePositions: rows.reduce((a, w) => a + w.sparePositions, 0),
    amount: rows.reduce((a, w) => a + (w.amount ?? 0), 0),
  }), [rows])

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }
  // Сбой — не «складов нет» и не нули в плитках.
  if (isError) {
    return <div className="p-4"><LoadError what="склады и остатки" error={error} onRetry={() => void refetch()} /></div>
  }

  const exportAll = async () => [
    {
      name: 'Склады и остатки',
      columns: ['Склад', 'Состояние', 'Адрес', 'Вид владения', 'Контрагент', 'Договор', 'Ответственный', 'Код в 1С',
        ...STATE_COLS.map((c) => c.label), 'Всего единиц', 'Позиций ЗИП', 'Сумма остатка, ₽'],
      rows: allRows.map((w) => [w.location.name, w.status === 'closed' ? 'закрыт' : 'действует', w.location.address,
        w.card?.ownershipLabel, w.card?.counterpartyName, w.card?.contractLabel, w.card?.responsible, w.card?.bpCode,
        ...STATE_COLS.map((c) => w.unitsByState[c.state] ?? 0), w.unitsTotal, w.sparePositions, w.amount ?? 0]),
    },
    {
      name: 'Вне складов',
      columns: ['Держатель', 'Единиц', 'Кто именно'],
      rows: external.map((e) => [e.custodianLabel, e.unitsTotal, e.names.join(', ')]),
    },
  ]

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold">Склады и остатки</h2>
          {closedCount > 0 && <label className="flex min-h-8 items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            Показать закрытые ({closedCount})</label>}
        </div>
        <div className="flex flex-wrap gap-2">
          <ExportXlsxButton title="Склады и остатки оборудования" load={exportAll} />
          <NewWarehouseDialog companyId={companyId} onCreated={(id) => setCard({ id, tab: 'card' })} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Складов" value={nf0.format(kpi.warehouses)} />
        <Kpi label="Единиц на складах" value={nf0.format(kpi.units)} />
        <Kpi label="Сумма остатка, ₽" value={rub.format(kpi.amount)} />
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
                  <SortTh sortKey="name" sort={склады.sort} onSort={склады.toggle}>Склад</SortTh>
                  {STATE_COLS.map((c) => (
                    <th key={c.state} className="p-2 text-right font-medium whitespace-nowrap">{c.label}</th>
                  ))}
                  <SortTh sortKey="units" sort={склады.sort} onSort={склады.toggle} align="right">Всего единиц</SortTh>
                  <SortTh sortKey="spareLines" sort={склады.sort} onSort={склады.toggle} align="right">Позиций ЗИП</SortTh>
                  <SortTh sortKey="amount" sort={склады.sort} onSort={склады.toggle} align="right">Сумма, ₽</SortTh>
                  <th className="p-2"><span className="sr-only">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {склады.rows.map((w) => (
                  <tr key={w.location.id} className={`border-b border-border/30 hover:bg-muted/30 ${w.status === 'closed' ? 'text-muted-foreground' : ''}`}>
                    <td className="p-2">
                      <div className="flex items-center gap-1.5 font-medium">
                        <Warehouse className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                        <button type="button" className="min-h-6 text-left hover:text-primary hover:underline"
                          title="Остатки и реквизиты склада" onClick={() => setCard({ id: w.location.id, tab: 'stock' })}>
                          {w.location.name}</button>
                        {w.status === 'closed' && <Badge variant="outline" className="font-normal text-muted-foreground">закрыт</Badge>}
                      </div>
                      {w.location.address && (
                        <div className="mt-0.5 max-w-[320px] truncate text-[11px] text-muted-foreground" title={w.location.address}>
                          {w.location.address}
                        </div>
                      )}
                      {/* Реквизиты склада: чей он, по какому договору и кто отвечает. */}
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
                        {w.card?.ownershipLabel && <span>{w.card.ownershipLabel}</span>}
                        {w.card?.counterpartyName && <span>· {w.card.counterpartyName}</span>}
                        {w.card?.contractLabel && <span>· {w.card.contractLabel}</span>}
                        {w.card?.contractStatus && <span className={CONTRACT_STATUS[w.card.contractStatus][1]}>· {CONTRACT_STATUS[w.card.contractStatus][0]}</span>}
                        {w.card?.responsible && <span>· МОЛ: {w.card.responsible}</span>}
                        {!w.card?.ownership && <span className="text-amber-700 dark:text-amber-400">· реквизиты не заполнены</span>}
                      </div>
                    </td>
                    {STATE_COLS.map((c) => (
                      <td key={c.state} className="p-2 text-right font-mono">
                        <Num v={w.unitsByState[c.state] ?? 0} onOpen={() => setDrill({
                          title: `${w.location.name} · ${c.label}`, locationId: w.location.id, state: c.state })} />
                      </td>
                    ))}
                    <td className="p-2 text-right font-mono font-semibold">
                      <Num v={w.unitsTotal} onOpen={() => setDrill({ title: w.location.name, locationId: w.location.id })} />
                    </td>
                    <td className="p-2 text-right font-mono"><Num v={w.sparePositions} dim /></td>
                    <td className="p-2 text-right font-mono tabular-nums">{w.amount ? rub.format(w.amount) : <span className="text-muted-foreground/40">—</span>}</td>
                    <td className="p-2 text-right">
                      <Button size="sm" variant="outline" className="h-8" onClick={() => setCard({ id: w.location.id, tab: 'stock' })}>
                        <FileText className="mr-1.5 h-3.5 w-3.5" />Карточка</Button>
                    </td>
                  </tr>
                ))}
                <tr className="bg-muted/60 font-medium">
                  <td className="p-2">Итого</td>
                  {totals.byState.map((v, i) => (
                    <td key={STATE_COLS[i].state} className="p-2 text-right font-mono"><Num v={v} /></td>
                  ))}
                  <td className="p-2 text-right font-mono"><Num v={totals.unitsTotal} /></td>
                  <td className="p-2 text-right font-mono"><Num v={totals.sparePositions} /></td>
                  <td className="p-2 text-right font-mono tabular-nums">{rub.format(totals.amount)}</td>
                  <td />
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {external.length > 0 && (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <div className="border-b bg-muted/20 px-3 py-1.5 text-[11px] font-medium">
              Вне складов
              <span className="ml-2 font-normal text-muted-foreground">единицы у подрядчика и у производителя</span>
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
                    <td className="p-2 text-right font-mono">
                      <Num v={e.unitsTotal} onOpen={() => setDrill({
                        title: `Вне складов · ${e.custodianLabel}`, custodian: e.custodian, state: HELD_STATES })} />
                    </td>
                    <td className="p-2 text-muted-foreground">{e.names.length > 0 ? e.names.join(', ') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
      {card && <WarehouseCardDialog key={card.id} companyId={companyId} warehouseId={card.id} initialTab={card.tab}
        onClose={() => setCard(null)} />}
      {drill && <UnitsListDialog companyId={companyId} drill={drill} onOpenUnit={setUnitId} onClose={() => setDrill(null)} />}
      {unitId && (
        <UnitDetailsDialog companyId={companyId} unitId={unitId}
          warehouses={warehouses} sites={sites} onClose={() => setUnitId(null)} />
      )}
    </div>
  )
}
