/**
 * «Поставки и возвраты» — реестр документов складского контура оборудования.
 *
 * Документ поставки/возврата — слой оснований поверх движений: спецификация =
 * план (что заказано/возвращается), приёмка порождает штатные движения железа.
 * Реестр показывает план/факт и статус; карточка (SupplyCardModal) ведёт приёмку.
 * Создание документа со спецификацией — CreateSupplyDialog в этом же файле.
 */

import { useMemo, useState } from 'react'
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
import { Loader2, Plus, Search, Trash2 } from 'lucide-react'
import { ApiError } from '@/services/apiClient'
import { loadLocations } from '@/services/locationService'
import {
  listSupplies, createSupply, listSuppliers, listSpareParts,
  SUPPLY_STATUS_META, SUPPLY_TYPE_META,
  type SupplyDocType, type SupplyStatus, type SupplyLinePayload, type SparePart,
} from '@/services/equipmentService'
import { SupplyCardModal } from './SupplyCardModal'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : String(e)
}
function todayISO(): string { return new Date().toISOString().slice(0, 10) }

const STATUS_OPTS = Object.entries(SUPPLY_STATUS_META) as [SupplyStatus, { label: string; cls: string }][]

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

export function EquipmentSuppliesPanel({ companyId }: { companyId: string }) {
  const [f, setF] = useState({ docType: 'all', status: 'all', counterpartyId: 'all', dateFrom: '', dateTo: '', q: '', page: 1 })
  const patch = (p: Partial<typeof f>) => setF((s) => ({ ...s, page: 1, ...p }))
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const suppliersQ = useQuery({ queryKey: ['eq-suppliers', companyId], queryFn: () => listSuppliers(companyId) })

  const { data, isLoading } = useQuery({
    queryKey: ['eq-supplies', companyId, f.docType, f.status, f.counterpartyId, f.dateFrom, f.dateTo, f.q, f.page],
    queryFn: () => listSupplies({
      companyId,
      docType: f.docType === 'all' ? undefined : (f.docType as SupplyDocType),
      status: f.status === 'all' ? undefined : (f.status as SupplyStatus),
      counterpartyId: f.counterpartyId === 'all' ? undefined : f.counterpartyId,
      dateFrom: f.dateFrom || undefined,
      dateTo: f.dateTo || undefined,
      q: f.q || undefined,
      page: f.page, pageSize: 100,
    }),
    placeholderData: keepPreviousData,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const suppliers = suppliersQ.data?.items ?? []

  const exCols = ['№', 'Дата', 'Тип', 'Поставщик', 'Статус', 'Позиций', 'План', 'Принято', 'Сумма']
  const exRows = items.map((d) => [
    d.number, d.docDate, SUPPLY_TYPE_META[d.docType].label, d.counterpartyName,
    SUPPLY_STATUS_META[d.status].label, d.linesCount, d.qtyPlanned, d.qtyReceived,
    d.amountTotal,
  ])

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
        <Button size="sm" className="ml-auto h-8 text-xs" onClick={() => setCreating(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" /> Новый документ
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : items.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Документов нет. Создайте поставку кнопкой «Новый документ».
        </CardContent></Card>
      ) : (
        <Card><CardContent className="overflow-x-auto p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="p-2 text-left font-medium">№</th>
                <th className="p-2 text-left font-medium">Дата</th>
                <th className="p-2 text-left font-medium">Тип</th>
                <th className="p-2 text-left font-medium">Поставщик</th>
                <th className="p-2 text-left font-medium">Статус</th>
                <th className="p-2 text-right font-medium">Позиций</th>
                <th className="p-2 text-right font-medium">План / принято</th>
                <th className="p-2 text-right font-medium">Сумма</th>
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

      <table hidden aria-hidden data-export-name="Поставки"
        data-export-rows={JSON.stringify({ columns: exCols, rows: exRows })} />

      {openId && <SupplyCardModal companyId={companyId} supplyId={openId} onClose={() => setOpenId(null)} />}
      {creating && <CreateSupplyDialog companyId={companyId} onClose={() => setCreating(false)}
        onCreated={(id) => { setCreating(false); setOpenId(id) }} />}
    </div>
  )
}

// ─── создание документа со спецификацией ────────────────────────────────────

type DraftLine = SupplyLinePayload & { _key: number }

function CreateSupplyDialog({ companyId, onClose, onCreated }: {
  companyId: string
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const qc = useQueryClient()
  const [docType, setDocType] = useState<SupplyDocType>('supply')
  const [number, setNumber] = useState('')
  const [docDate, setDocDate] = useState(todayISO())
  const [counterpartyId, setCounterpartyId] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [note, setNote] = useState('')
  const [lines, setLines] = useState<DraftLine[]>([])
  const keyRef = useState(() => ({ n: 0 }))[0]

  const suppliersQ = useQuery({ queryKey: ['eq-suppliers', companyId], queryFn: () => listSuppliers(companyId) })
  const locsQ = useQuery({ queryKey: ['equipment-locations', companyId], queryFn: () => loadLocations(companyId) })
  const partsQ = useQuery({ queryKey: ['eq-spares', companyId], queryFn: () => listSpareParts({ companyId }) })
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
      warehouseId: warehouseId || null, note: note || null,
      lines: lines.map(({ _key, ...l }) => l),
    }),
    onSuccess: (doc) => {
      void qc.invalidateQueries({ queryKey: ['eq-supplies'] })
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
          <div className="space-y-1">
            <Label className="text-xs">Поставщик</Label>
            <Select value={counterpartyId} onValueChange={setCounterpartyId}>
              <SelectTrigger className="h-9"><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {(suppliersQ.data?.items ?? []).map((s) => (
                  <SelectItem key={s.id} value={s.id}>{s.shortName || s.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
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
            <div key={l._key} className="flex flex-wrap items-end gap-2 rounded-md border p-2">
              {l.lineKind === 'station' ? (
                <>
                  <LField label="Вендор"><Input value={l.vendor ?? ''} className="h-8 w-28 text-xs"
                    onChange={(e) => upd(l._key, { vendor: e.target.value })} /></LField>
                  <LField label="Модель"><Input value={l.model ?? ''} className="h-8 w-32 text-xs"
                    onChange={(e) => upd(l._key, { model: e.target.value })} /></LField>
                  <LField label="кВт"><Input type="number" value={l.powerKwt ?? ''} className="h-8 w-16 text-xs"
                    onChange={(e) => upd(l._key, { powerKwt: e.target.value ? Number(e.target.value) : null })} /></LField>
                </>
              ) : (
                <LField label="Номенклатура">
                  <Select value={l.partId ?? ''} onValueChange={(v) => upd(l._key, { partId: v, name: parts.find((p) => p.id === v)?.name })}>
                    <SelectTrigger className="h-8 w-52 text-xs"><SelectValue placeholder="Выберите ЗИП" /></SelectTrigger>
                    <SelectContent>
                      {parts.map((p) => (<SelectItem key={p.id} value={p.id} className="text-xs">{p.name}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </LField>
              )}
              <LField label="Кол-во"><Input type="number" min={1} value={l.qtyPlanned} className="h-8 w-16 text-xs"
                onChange={(e) => upd(l._key, { qtyPlanned: Number(e.target.value) })} /></LField>
              <LField label="Цена"><Input type="number" value={l.unitPrice ?? ''} className="h-8 w-24 text-xs"
                onChange={(e) => upd(l._key, { unitPrice: e.target.value ? Number(e.target.value) : null })} /></LField>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => rm(l._key)}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
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

function LField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      {children}
    </div>
  )
}
