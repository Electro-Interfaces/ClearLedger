/**
 * Карточка документа поставки/возврата оборудования + приёмка строки.
 *
 * Документ — слой оснований поверх движений: спецификация хранит ПЛАН, приёмка
 * порождает штатные движения (receipt единиц/ЗИП, to_vendor при возврате),
 * привязанные к строке. Факт (принято) приходит с сервера как производное.
 * Диалог приёмки — в этом же файле (паттерн EquipmentFleetPanel).
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Package, Plus, Trash2, Undo2 } from 'lucide-react'
import { ApiError } from '@/services/apiClient'
import { loadLocations } from '@/services/locationService'
import {
  getSupply, setSupplyStatus, deleteSupply, receiveSupplyLine, listUnits,
  SUPPLY_STATUS_META, SUPPLY_TYPE_META,
  type SupplyDoc, type SupplyLine, type ReceiveUnit, type EquipmentUnit,
} from '@/services/equipmentService'

const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : String(e)
}

/** Ключи витрин, которые меняет приёмка/смена статуса. */
const AFFECTED = ['eq-supplies', 'eq-supply', 'eq-units', 'eq-unit', 'eq-overview',
  'eq-movements', 'eq-warehouses', 'equipment-warehouses', 'equipment-movements'] as const

function lineTitle(ln: SupplyLine): string {
  if (ln.lineKind === 'spare') return ln.name || 'ЗИП'
  return [ln.vendor, ln.model].filter(Boolean).join(' ') || ln.name || 'Станция'
}

export function SupplyCardModal({ companyId, supplyId, onClose }: {
  companyId: string
  supplyId: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const invalidate = () => {
    for (const k of AFFECTED) void qc.invalidateQueries({ queryKey: [k] })
  }
  const { data: doc, isLoading } = useQuery({
    queryKey: ['eq-supply', companyId, supplyId],
    queryFn: () => getSupply(companyId, supplyId),
  })
  const [receiveLine, setReceiveLine] = useState<SupplyLine | null>(null)

  const statusMut = useMutation({
    mutationFn: (action: 'confirm' | 'close' | 'cancel') => setSupplyStatus(companyId, supplyId, action),
    onSuccess: () => { invalidate() },
    onError: (e) => toast.error(errMsg(e)),
  })
  const delMut = useMutation({
    mutationFn: () => deleteSupply(companyId, supplyId),
    onSuccess: () => { invalidate(); toast.success('Документ удалён'); onClose() },
    onError: (e) => toast.error(errMsg(e)),
  })

  const isReturn = doc?.docType === 'return'
  const canEditStatus = doc && !['cancelled'].includes(doc.status)
  const canReceive = doc && ['ordered', 'partially_received', 'received'].includes(doc.status)

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        {isLoading || !doc ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {isReturn ? <Undo2 className="h-4 w-4" /> : <Package className="h-4 w-4" />}
                {SUPPLY_TYPE_META[doc.docType].label} № {doc.number}
                <Badge variant="outline" className={`ml-1 text-[11px] font-normal ${SUPPLY_STATUS_META[doc.status].cls}`}>
                  {SUPPLY_STATUS_META[doc.status].label}
                </Badge>
              </DialogTitle>
            </DialogHeader>

            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
              <KV label="Дата" value={doc.docDate} />
              <KV label="Поставщик" value={doc.counterpartyName} />
              <KV label="Валюта" value={doc.currency} />
              <KV label="Сумма" value={doc.amountTotal != null ? `${nf2.format(doc.amountTotal)} ${doc.currency}` : '—'} />
              <KV label="План / принято" value={`${nf0.format(doc.qtyPlanned)} / ${nf0.format(doc.qtyReceived)}`} />
              {doc.note && <KV label="Примечание" value={doc.note} />}
            </div>

            {/* Спецификация */}
            <div className="rounded-md border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Позиция</th>
                    <th className="p-2 text-left font-medium">Тип</th>
                    <th className="p-2 text-right font-medium">Кол-во</th>
                    <th className="p-2 text-right font-medium">Принято</th>
                    <th className="p-2 text-right font-medium">Цена</th>
                    <th className="p-2" />
                  </tr>
                </thead>
                <tbody>
                  {doc.lines.map((ln) => {
                    const full = ln.qtyReceived >= ln.qtyPlanned
                    return (
                      <tr key={ln.id} className="border-b border-border/30">
                        <td className="p-2">
                          <div>{lineTitle(ln)}</div>
                          {ln.lineKind === 'station' && (ln.powerKwt || ln.connectorTypes) && (
                            <div className="text-[11px] text-muted-foreground">
                              {[ln.powerKwt ? `${ln.powerKwt} кВт` : '', ln.connectorTypes].filter(Boolean).join(' · ')}
                            </div>
                          )}
                        </td>
                        <td className="p-2 text-muted-foreground">{ln.lineKind === 'spare' ? 'ЗИП' : 'Станция'}</td>
                        <td className="p-2 text-right tabular-nums">{nf0.format(ln.qtyPlanned)}</td>
                        <td className={`p-2 text-right tabular-nums ${full ? 'text-emerald-600 dark:text-emerald-400' : ''}`}>
                          {nf0.format(ln.qtyReceived)}
                        </td>
                        <td className="p-2 text-right tabular-nums text-muted-foreground">
                          {ln.unitPrice != null ? nf2.format(ln.unitPrice) : '—'}
                        </td>
                        <td className="p-2 text-right">
                          {canReceive && !full && (
                            <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
                              onClick={() => setReceiveLine(ln)}>
                              {isReturn ? 'Вернуть' : 'Принять'}
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                  {doc.lines.length === 0 && (
                    <tr><td colSpan={6} className="p-4 text-center text-muted-foreground">Спецификация пуста</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <DialogFooter className="flex-wrap gap-2 sm:justify-between">
              <div className="flex flex-wrap gap-2">
                {doc.status === 'draft' && (
                  <Button size="sm" onClick={() => statusMut.mutate('confirm')} disabled={statusMut.isPending}>
                    Провести
                  </Button>
                )}
                {['ordered', 'partially_received', 'received'].includes(doc.status) && (
                  <Button variant="outline" size="sm" onClick={() => statusMut.mutate('close')} disabled={statusMut.isPending}>
                    Закрыть
                  </Button>
                )}
                {canEditStatus && doc.status !== 'closed' && (
                  <Button variant="ghost" size="sm" className="text-muted-foreground"
                    onClick={() => statusMut.mutate('cancel')} disabled={statusMut.isPending}>
                    Отменить документ
                  </Button>
                )}
                {doc.status === 'draft' && (
                  <Button variant="ghost" size="sm" className="text-destructive"
                    onClick={() => delMut.mutate()} disabled={delMut.isPending}>
                    <Trash2 className="mr-1 h-3.5 w-3.5" /> Удалить
                  </Button>
                )}
              </div>
              <Button variant="outline" size="sm" onClick={onClose}>Закрыть окно</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>

      {receiveLine && doc && (
        <ReceiveLineDialog companyId={companyId} doc={doc} line={receiveLine}
          onClose={() => setReceiveLine(null)}
          onDone={() => { invalidate(); setReceiveLine(null) }} />
      )}
    </Dialog>
  )
}

function KV({ label, value }: { label: string; value?: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      <div className="text-sm break-words">{value ?? '—'}</div>
    </div>
  )
}

// ─── приёмка / возврат строки ───────────────────────────────────────────────

function ReceiveLineDialog({ companyId, doc, line, onClose, onDone }: {
  companyId: string
  doc: SupplyDoc
  line: SupplyLine
  onClose: () => void
  onDone: () => void
}) {
  const isReturn = doc.docType === 'return'
  const isStation = line.lineKind === 'station'
  const remaining = Math.max(0, line.qtyPlanned - line.qtyReceived)

  const locsQ = useQuery({ queryKey: ['equipment-locations', companyId], queryFn: () => loadLocations(companyId) })
  const warehouses = useMemo(
    () => (locsQ.data ?? []).filter((l) => l.type === 'warehouse'),
    [locsQ.data])

  const [wh, setWh] = useState(doc.warehouseId ?? '')
  const [occurredOn, setOccurredOn] = useState(doc.docDate)
  const [comment, setComment] = useState('')
  const [qty, setQty] = useState(remaining ? String(remaining) : '')
  const [units, setUnits] = useState<ReceiveUnit[]>([{}])
  const [pickedIds, setPickedIds] = useState<string[]>([])

  // единицы-кандидаты на возврат станции (у которых доступен to_vendor)
  const returnPickQ = useQuery({
    queryKey: ['eq-units-return', companyId, line.vendor],
    queryFn: () => listUnits({ companyId, pageSize: 500 }),
    enabled: isReturn && isStation,
  })
  const candidates = useMemo(() => {
    const all: EquipmentUnit[] = returnPickQ.data?.items ?? []
    return all.filter((u) => u.allowedOps.includes('to_vendor'))
  }, [returnPickQ.data])

  const mut = useMutation({
    mutationFn: () => {
      const base = {
        warehouseId: wh || null, occurredOn: occurredOn || null, comment: comment || null,
      }
      if (isReturn && isStation) {
        return receiveSupplyLine(companyId, doc.id, line.id, { ...base, unitIds: pickedIds })
      }
      if (isStation) {
        const filled = units.map((u) => ({
          serial: (u.serial || '').trim() || null,
          inventoryNumber: (u.inventoryNumber || '').trim() || null,
          warrantyUntil: (u.warrantyUntil || '').trim() || null,
        }))
        const hasSerials = filled.some((u) => u.serial)
        return receiveSupplyLine(companyId, doc.id, line.id,
          hasSerials ? { ...base, units: filled } : { ...base, qty: Number(qty) })
      }
      return receiveSupplyLine(companyId, doc.id, line.id, { ...base, qty: Number(qty) })
    },
    onSuccess: () => { toast.success(isReturn ? 'Возврат оформлен' : 'Приёмка выполнена'); onDone() },
    onError: (e) => toast.error(errMsg(e)),
  })

  const needWh = !isReturn || !isStation  // возврат станций склад не требует
  const canSave = (!needWh || !!wh) && (
    isReturn && isStation ? pickedIds.length > 0
      : isStation ? (units.some((u) => (u.serial || '').trim()) || Number(qty) > 0)
        : Number(qty) > 0)

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isReturn ? 'Возврат' : 'Приёмка'}: {lineTitle(line)}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">
            План {nf0.format(line.qtyPlanned)} · принято {nf0.format(line.qtyReceived)} · осталось {nf0.format(remaining)}
          </div>

          {needWh && (
            <div className="space-y-1">
              <Label className="text-xs">Склад {isReturn ? 'списания' : 'получатель'}</Label>
              <Select value={wh} onValueChange={setWh}>
                <SelectTrigger className="h-9"><SelectValue placeholder="Выберите склад" /></SelectTrigger>
                <SelectContent>
                  {warehouses.map((w) => (
                    <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Дата</Label>
              <Input type="date" value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} className="h-9" />
            </div>
          </div>

          {/* Станция + поставка: серийные единицы либо количество безсерийных */}
          {isStation && !isReturn && (
            <div className="space-y-2">
              <Label className="text-xs">Единицы (серийные номера)</Label>
              {units.map((u, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input placeholder="Серийный №" value={u.serial ?? ''} className="h-8 text-xs"
                    onChange={(e) => setUnits((s) => s.map((x, j) => j === i ? { ...x, serial: e.target.value } : x))} />
                  <Input placeholder="Инв. №" value={u.inventoryNumber ?? ''} className="h-8 w-24 text-xs"
                    onChange={(e) => setUnits((s) => s.map((x, j) => j === i ? { ...x, inventoryNumber: e.target.value } : x))} />
                  {units.length > 1 && (
                    <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0"
                      onClick={() => setUnits((s) => s.filter((_, j) => j !== i))}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
                  onClick={() => setUnits((s) => [...s, {}])}>
                  <Plus className="mr-1 h-3.5 w-3.5" /> Ещё единица
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  или без серийников — количество:
                </span>
                <Input type="number" min={0} value={qty} onChange={(e) => setQty(e.target.value)}
                  className="h-7 w-20 text-xs" />
              </div>
            </div>
          )}

          {/* ЗИП (поставка/возврат): количество */}
          {!isStation && (
            <div className="space-y-1">
              <Label className="text-xs">Количество</Label>
              <Input type="number" min={0} value={qty} onChange={(e) => setQty(e.target.value)} className="h-9" />
            </div>
          )}

          {/* Возврат станций: выбор единиц */}
          {isReturn && isStation && (
            <div className="space-y-1">
              <Label className="text-xs">Единицы к возврату</Label>
              <div className="max-h-52 overflow-y-auto rounded-md border">
                {returnPickQ.isLoading ? (
                  <div className="flex justify-center py-6"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
                ) : candidates.length === 0 ? (
                  <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                    Нет единиц, доступных к возврату производителю
                  </div>
                ) : candidates.map((u) => {
                  const on = pickedIds.includes(u.id)
                  return (
                    <button key={u.id} type="button"
                      onClick={() => setPickedIds((s) => on ? s.filter((x) => x !== u.id) : [...s, u.id])}
                      className={`flex w-full items-center gap-2 border-b border-border/30 px-3 py-1.5 text-left text-xs hover:bg-muted/40 ${on ? 'bg-primary/10' : ''}`}>
                      <input type="checkbox" checked={on} readOnly className="pointer-events-none" />
                      <span className="font-mono">{u.serialNumber ?? '—'}</span>
                      <span className="text-muted-foreground">{[u.vendor, u.model].filter(Boolean).join(' ')}</span>
                      <span className="ml-auto text-muted-foreground">{u.stateLabel}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          <div className="space-y-1">
            <Label className="text-xs">Комментарий</Label>
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} className="text-xs" />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" onClick={() => mut.mutate()} disabled={!canSave || mut.isPending}>
            {mut.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
            {isReturn ? 'Оформить возврат' : 'Принять'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
