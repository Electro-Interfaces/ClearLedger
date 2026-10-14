/**
 * «Поставки и возвраты» — реестр документов складского контура оборудования.
 *
 * Документ поставки/возврата — слой оснований поверх движений: спецификация =
 * план (что заказано/возвращается), приёмка порождает штатные движения железа.
 * Реестр показывает план/факт и статус; карточка (SupplyCardModal) ведёт приёмку.
 * Создание документа со спецификацией — CreateSupplyDialog в этом же файле.
 */

import { useMemo, useState } from 'react'
import { SortTh } from '@/components/workspace/SortableTh'
import { useTableSort } from '@/hooks/useTableSort'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Loader2, Plus, Search } from 'lucide-react'
import { ApiError } from '@/services/apiClient'
import { CounterpartyContractPicker } from './CounterpartyContractPicker'
import { loadLocations } from '@/services/locationService'
import {
  listSupplies, createSupply, listSuppliers, listSpareParts,
  SUPPLY_STATUS_META, SUPPLY_TYPE_META,
  type SupplyDocType, type SupplyStatus, type SupplyLinePayload, type SparePart,
} from '@/services/equipmentService'
import { SupplyCardModal, SupplyLineFields, type DraftLine } from './SupplyCardModal'
import { ExportXlsxButton, LoadError, Pager } from './equipmentShared'
import { allPages, invalidateEquipment } from './useEquipmentScope'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : String(e)
}
function todayISO(): string { return new Date().toISOString().slice(0, 10) }

const PAGE_SIZE = 100
const STATUS_OPTS = Object.entries(SUPPLY_STATUS_META) as [SupplyStatus, { label: string; cls: string }][]

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

export function EquipmentSuppliesPanel({ companyId }: { companyId: string }) {
  const [f, setF] = useState({ docType: 'all', status: 'all', counterpartyId: 'all', dateFrom: '', dateTo: '', q: '', page: 1 })
  const patch = (p: Partial<typeof f>) => setF((s) => ({ ...s, page: 1, ...p }))
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const suppliersQ = useQuery({ queryKey: ['equipment', 'suppliers', companyId], queryFn: () => listSuppliers(companyId) })

  const params = {
    companyId,
    docType: f.docType === 'all' ? undefined : (f.docType as SupplyDocType),
    status: f.status === 'all' ? undefined : (f.status as SupplyStatus),
    counterpartyId: f.counterpartyId === 'all' ? undefined : f.counterpartyId,
    dateFrom: f.dateFrom || undefined,
    dateTo: f.dateTo || undefined,
    q: f.q || undefined,
  }
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['equipment', 'supplies', companyId, f.docType, f.status, f.counterpartyId, f.dateFrom, f.dateTo, f.q, f.page],
    queryFn: () => listSupplies({ ...params, page: f.page, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  const все = data?.items ?? []
  // Поставки ведут по дате и по сумме, а разбирают — по статусу: что не принято.
  const сортировка = useMemo(() => ({
    no: (d: typeof все[number]) => d.number,
    date: (d: typeof все[number]) => d.docDate,
    kind: (d: typeof все[number]) => d.docType,
    supplier: (d: typeof все[number]) => d.counterpartyName,
    status: (d: typeof все[number]) => d.status,
    lines: (d: typeof все[number]) => d.linesCount,
    qty: (d: typeof все[number]) => d.qtyPlanned,
    sum: (d: typeof все[number]) => d.amountTotal,
  }), [])
  const { rows: items, sort, toggle } = useTableSort(все, сортировка, { key: 'date', dir: 'desc' })
  const total = data?.total ?? 0
  const suppliers = suppliersQ.data?.items ?? []

  // Выгрузка — весь отбор, а не загруженная страница.
  const exportAll = async () => {
    const all = await allPages((page) => listSupplies({ ...params, page, pageSize: 500 }))
    return [{
      name: 'Поставки',
      columns: ['№', 'Дата', 'Тип', 'Поставщик', 'Статус', 'Позиций', 'План', 'Принято', 'Сумма', 'Валюта', 'Автор', 'Примечание'],
      rows: all.map((d) => [
        d.number, d.docDate, SUPPLY_TYPE_META[d.docType].label, d.counterpartyName,
        SUPPLY_STATUS_META[d.status].label, d.linesCount, d.qtyPlanned, d.qtyReceived,
        d.amountTotal, d.currency, d.createdByName, d.note,
      ]),
    }]
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3" data-export-ignore>
        <Field label="Тип">
          <Select value={f.docType} onValueChange={(v) => patch({ docType: v })}>
            <SelectTrigger className="h-8 w-[130px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все</SelectItem>
              <SelectItem value="supply" className="text-xs">Поставки</SelectItem>
              <SelectItem value="return" className="text-xs">Возвраты</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Статус">
          <Select value={f.status} onValueChange={(v) => patch({ status: v })}>
            <SelectTrigger className="h-8 w-[160px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все статусы</SelectItem>
              {STATUS_OPTS.map(([s, meta]) => (
                <SelectItem key={s} value={s} className="text-xs">{meta.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Поставщик">
          <Select value={f.counterpartyId} onValueChange={(v) => patch({ counterpartyId: v })}>
            <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все поставщики</SelectItem>
              {suppliers.map((s) => (
                <SelectItem key={s.id} value={s.id} className="text-xs">{s.shortName || s.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Период">
          <Input type="date" value={f.dateFrom} onChange={(e) => patch({ dateFrom: e.target.value })} className="h-8 w-[140px] text-xs" />
        </Field>
        <span className="text-xs text-muted-foreground">—</span>
        <Input type="date" value={f.dateTo} onChange={(e) => patch({ dateTo: e.target.value })} className="h-8 w-[140px] text-xs" />
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={f.q} onChange={(e) => patch({ q: e.target.value })} placeholder="№ документа"
            className="h-8 w-[150px] pl-7 text-xs" />
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <ExportXlsxButton title="Поставки и возвраты оборудования" load={exportAll} />
          <Button size="sm" className="h-8 text-xs" onClick={() => setCreating(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Новый документ
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : isError ? (
        <LoadError what="поставки" error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Документов нет. Создайте поставку кнопкой «Новый документ».
        </CardContent></Card>
      ) : (
        <Card><CardContent className="overflow-x-auto p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <SortTh sortKey="no" sort={sort} onSort={toggle}>№</SortTh>
                <SortTh sortKey="date" sort={sort} onSort={toggle}>Дата</SortTh>
                <SortTh sortKey="kind" sort={sort} onSort={toggle}>Тип</SortTh>
                <SortTh sortKey="supplier" sort={sort} onSort={toggle}>Поставщик</SortTh>
                <SortTh sortKey="status" sort={sort} onSort={toggle}>Статус</SortTh>
                <SortTh sortKey="lines" sort={sort} onSort={toggle} align="right">Позиций</SortTh>
                <SortTh sortKey="qty" sort={sort} onSort={toggle} align="right">План / принято</SortTh>
                <SortTh sortKey="sum" sort={sort} onSort={toggle} align="right">Сумма</SortTh>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id} className="cursor-pointer border-b border-border/30 hover:bg-muted/30"
                  onClick={() => setOpenId(d.id)}>
                  <td className="p-2 font-medium">{d.number}</td>
                  <td className="p-2 font-mono whitespace-nowrap">{d.docDate}</td>
                  <td className="p-2">
                    <Badge variant="outline" className={`text-[10px] font-normal ${SUPPLY_TYPE_META[d.docType].cls}`}>
                      {SUPPLY_TYPE_META[d.docType].label}
                    </Badge>
                  </td>
                  <td className="p-2 max-w-[200px] truncate" title={d.counterpartyName ?? undefined}>
                    {d.counterpartyName ?? '—'}
                  </td>
                  <td className="p-2">
                    <Badge variant="outline" className={`text-[10px] font-normal ${SUPPLY_STATUS_META[d.status].cls}`}>
                      {SUPPLY_STATUS_META[d.status].label}
                    </Badge>
                  </td>
                  <td className="p-2 text-right tabular-nums">{d.linesCount}</td>
                  <td className="p-2 text-right tabular-nums">
                    {nf0.format(d.qtyPlanned)} / {nf0.format(d.qtyReceived)}
                  </td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">
                    {d.amountTotal != null ? `${nf2.format(d.amountTotal)} ${d.currency}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}

      {total > 0 && (
        <div className="text-right text-xs text-muted-foreground tabular-nums">всего документов: {nf0.format(total)}</div>
      )}

      <Pager page={f.page} pages={Math.ceil(total / PAGE_SIZE)} onPage={(page) => setF((s) => ({ ...s, page }))} />

      {openId && <SupplyCardModal companyId={companyId} supplyId={openId} onClose={() => setOpenId(null)} />}
      {creating && <CreateSupplyDialog companyId={companyId} onClose={() => setCreating(false)}
        onCreated={(id) => { setCreating(false); setOpenId(id) }} />}
    </div>
  )
}

// ─── создание документа со спецификацией ────────────────────────────────────

function CreateSupplyDialog({ companyId, onClose, onCreated }: {
  companyId: string
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const qc = useQueryClient()
  const [docType, setDocType] = useState<SupplyDocType>('supply')
  const [number, setNumber] = useState('')
  const [docDate, setDocDate] = useState(todayISO())
  // Поставщик и договор поставки — из справочников пространства (договор раньше не выбирался).
  const [party, setParty] = useState({ counterpartyId: '', contractId: '' })
  const counterpartyId = party.counterpartyId
  const [warehouseId, setWarehouseId] = useState('')
  const [note, setNote] = useState('')
  const [lines, setLines] = useState<DraftLine[]>([])
  const keyRef = useState(() => ({ n: 0 }))[0]

  const suppliersQ = useQuery({ queryKey: ['equipment', 'suppliers', companyId], queryFn: () => listSuppliers(companyId) })
  const locsQ = useQuery({ queryKey: ['equipment', 'locations', companyId], queryFn: () => loadLocations(companyId), staleTime: 60_000 })
  const partsQ = useQuery({ queryKey: ['equipment', 'spares', companyId], queryFn: () => listSpareParts({ companyId }) })
  const warehouses = useMemo(() => (locsQ.data ?? []).filter((l) => l.type === 'warehouse'), [locsQ.data])
  const parts: SparePart[] = partsQ.data ?? []

  const addLine = (kind: 'station' | 'spare') =>
    setLines((s) => [...s, { _key: keyRef.n++, lineKind: kind, qtyPlanned: 1 }])
  const upd = (key: number, p: Partial<SupplyLinePayload>) =>
    setLines((s) => s.map((l) => l._key === key ? { ...l, ...p } : l))
  const rm = (key: number) => setLines((s) => s.filter((l) => l._key !== key))

  const mut = useMutation({
    mutationFn: () => createSupply(companyId, {
      docType, number: number.trim(), docDate,
      counterpartyId: counterpartyId || null,
      counterpartyName: suppliersQ.data?.items.find((x) => x.id === counterpartyId)?.name ?? null,
      contractId: party.contractId || null,
      warehouseId: warehouseId || null, note: note || null,
      lines: lines.map(({ _key, ...l }) => l),
    }),
    onSuccess: (doc) => {
      void invalidateEquipment(qc)
      toast.success('Документ создан')
      onCreated(doc.id)
    },
    onError: (e) => toast.error(errMsg(e)),
  })

  const canSave = number.trim().length > 0 && lines.length > 0 &&
    lines.every((l) => (l.qtyPlanned ?? 0) > 0 && (l.lineKind === 'spare' ? !!l.partId : true))

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader><DialogTitle>Новый документ</DialogTitle></DialogHeader>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <Label className="text-xs">Тип</Label>
            <Select value={docType} onValueChange={(v) => setDocType(v as SupplyDocType)}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="supply">Поставка</SelectItem>
                <SelectItem value="return">Возврат поставщику</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Номер</Label>
            <Input value={number} onChange={(e) => setNumber(e.target.value)} className="h-9" placeholder="№" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Дата</Label>
            <Input type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className="h-9" />
          </div>
          <div className="col-span-2 sm:col-span-3">
            <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty}
              label={docType === 'return' ? 'Кому возвращаем' : 'Поставщик'} preferredTypes={['Поставка ЭЗС', 'Поставка']} preferredTypeCodes={['supply']} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Склад по умолчанию</Label>
            <Select value={warehouseId} onValueChange={setWarehouseId}>
              <SelectTrigger className="h-9"><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {warehouses.map((w) => (<SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Спецификация */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label className="text-xs">Спецификация</Label>
            <Button variant="outline" size="sm" className="ml-auto h-7 px-2 text-xs" onClick={() => addLine('station')}>
              <Plus className="mr-1 h-3.5 w-3.5" /> Станция
            </Button>
            <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => addLine('spare')}>
              <Plus className="mr-1 h-3.5 w-3.5" /> ЗИП
            </Button>
          </div>
          {lines.length === 0 && (
            <div className="rounded-md border border-dashed py-4 text-center text-xs text-muted-foreground">
              Добавьте позиции: станции или ЗИП
            </div>
          )}
          {lines.map((l) => (
            <SupplyLineFields key={l._key} line={l} parts={parts}
              onChange={(p) => upd(l._key, p)} onRemove={() => rm(l._key)} />
          ))}
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Примечание</Label>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="text-xs" />
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" onClick={() => mut.mutate()} disabled={!canSave || mut.isPending}>
            {mut.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
            Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
