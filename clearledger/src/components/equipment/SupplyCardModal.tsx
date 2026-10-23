/**
 * Карточка документа поставки/возврата оборудования + приёмка строки.
 *
 * Документ — слой оснований поверх движений: спецификация хранит ПЛАН, приёмка
 * порождает штатные движения (receipt единиц/ЗИП, to_vendor при возврате),
 * привязанные к строке. Факт (принято) приходит с сервера как производное.
 * Шапку можно править, пока документ не закрыт и не отменён; спецификацию — до
 * приёмки (в черновике и проведённом). Диалог приёмки — в этом же файле.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Package, Pencil, Plus, Search, Trash2, Undo2 } from 'lucide-react'
import { ApiError } from '@/services/apiClient'
import { loadLocations } from '@/services/locationService'
import { getContracts } from '@/services/referenceService'
import {
  getSupply, setSupplyStatus, deleteSupply, receiveSupplyLine, listUnits, listSpareParts, getAccountingMeta,
  updateSupply, addSupplyLine, updateSupplyLine, deleteSupplyLine,
  SUPPLY_STATUS_META, SUPPLY_TYPE_META,
  type SupplyDoc, type SupplyLine, type SupplyLinePayload, type ReceiveUnit, type SparePart,
} from '@/services/equipmentService'
import { CounterpartyContractPicker } from './CounterpartyContractPicker'
import { LoadError } from './equipmentShared'
import { invalidateEquipment } from './useEquipmentScope'
import { supplyLinesValid, supplyLinePayload as linePayload, type DraftLine } from './supplyValidation'

const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : String(e)
}

function lineTitle(ln: Pick<SupplyLine, 'lineKind' | 'name' | 'vendor' | 'model'>): string {
  if (ln.lineKind === 'spare') return ln.name || 'ЗИП'
  return [ln.vendor, ln.model].filter(Boolean).join(' ') || ln.name || 'Станция'
}

function useWarehouses(companyId: string) {
  const q = useQuery({ queryKey: ['equipment', 'locations', companyId], queryFn: () => loadLocations(companyId), staleTime: 60_000 })
  return (q.data ?? []).filter((l) => l.type === 'warehouse' && l.status !== 'closed')
}

// ─── строка спецификации в форме (создание и правка документа) ──────────────

/** `id` — строка уже есть на сервере; `locked` — по ней была приёмка, править нельзя. */
export type { DraftLine } from './supplyValidation'

export function LField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      {children}
    </div>
  )
}

/** Строка спецификации — как табличная часть «Поступления» 1С: номенклатура (у станции —
 *  её модель, тогда единица сразу получает счёт учёта), количество, цена без НДС, ставка НДС. */
export function SupplyLineFields({ companyId, line: l, parts, onChange, onRemove }: {
  companyId: string; line: DraftLine; parts: SparePart[]
  onChange: (p: Partial<SupplyLinePayload>) => void; onRemove: () => void
}) {
  const modelsQ = useQuery({ queryKey: ['equipment', 'spares-serial', companyId],
    queryFn: () => listSpareParts({ companyId, kind: 'station,equipment' }), staleTime: 60_000, enabled: l.lineKind === 'station' })
  const meta = useQuery({ queryKey: ['equipment', 'accounting-meta'], queryFn: getAccountingMeta, staleTime: Infinity }).data
  if (l.locked) {
    return (
      <div className="rounded-md border border-dashed p-2 text-xs text-muted-foreground">
        {lineTitle({ lineKind: l.lineKind, name: l.name ?? null, vendor: l.vendor ?? null, model: l.model ?? null })} · {nf0.format(l.qtyPlanned)} шт.
        — по строке уже была приёмка, она не меняется
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-md border p-2">
      {l.lineKind === 'station' ? (
        <>
          <LField label="Номенклатура">
            <select aria-label="Номенклатура станции" className="h-8 w-48 rounded-md border bg-background px-2 text-xs" value={l.partId ?? ''}
              onChange={(e) => {
                const p = (modelsQ.data ?? []).find((x) => x.id === e.target.value)
                onChange(p ? { partId: p.id, vendor: p.vendor ?? l.vendor, model: p.model ?? l.model, vatRate: l.vatRate ?? p.vatRate ?? undefined } : { partId: null })
              }}>
              <option value="">Без номенклатуры</option>
              {(modelsQ.data ?? []).filter((p) => !p.isArchived || p.id === l.partId).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </LField>
          <LField label="Производитель"><Input value={l.vendor ?? ''} className="h-8 w-28 text-xs"
            onChange={(e) => onChange({ vendor: e.target.value })} /></LField>
          <LField label="Модель"><Input value={l.model ?? ''} className="h-8 w-32 text-xs"
            onChange={(e) => onChange({ model: e.target.value })} /></LField>
          <LField label="кВт"><Input type="number" value={l.powerKwt ?? ''} className="h-8 w-16 text-xs"
            onChange={(e) => onChange({ powerKwt: e.target.value ? Number(e.target.value) : null })} /></LField>
        </>
      ) : (
        <LField label="Номенклатура">
          <Select value={l.partId ?? ''} onValueChange={(v) => onChange({ partId: v, name: parts.find((p) => p.id === v)?.name })}>
            <SelectTrigger className="h-8 w-52 text-xs"><SelectValue placeholder="Выберите ЗИП" /></SelectTrigger>
            <SelectContent>
              {parts.map((p) => (<SelectItem key={p.id} value={p.id} className="text-xs">{p.name}</SelectItem>))}
            </SelectContent>
          </Select>
        </LField>
      )}
      <LField label="Кол-во"><Input type="number" aria-label="Количество по строке" min={l.lineKind === 'station' ? 1 : 0.001}
        step={l.lineKind === 'station' ? 1 : 0.001} value={l.qtyPlanned} className="h-8 w-20 text-xs"
        onChange={(e) => onChange({ qtyPlanned: Number(e.target.value) })} /></LField>
      <LField label="Цена без НДС"><Input type="number" aria-label="Цена без НДС" min={0} step={0.01} value={l.unitPrice ?? ''} className="h-8 w-24 text-xs"
        onChange={(e) => onChange({ unitPrice: e.target.value ? Number(e.target.value) : null })} /></LField>
      <LField label="НДС">
        <select aria-label="Ставка НДС" className="h-8 w-24 rounded-md border bg-background px-2 text-xs" value={l.vatRate ?? ''}
          onChange={(e) => onChange({ vatRate: e.target.value || null })}>
          <option value="">—</option>
          {(meta?.vatRates ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </LField>
      <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Убрать строку" onClick={onRemove}>
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

const toDraft = (ln: SupplyLine, i: number): DraftLine => ({
  _key: i, id: ln.id, locked: ln.qtyReceived > 0, lineKind: ln.lineKind, partId: ln.partId, name: ln.name,
  qtyPlanned: ln.qtyPlanned, unitPrice: ln.unitPrice, vatRate: ln.vatRate, note: ln.note, vendor: ln.vendor,
  model: ln.model, stationType: ln.stationType, powerKwt: ln.powerKwt, connectorsCount: ln.connectorsCount,
  connectorTypes: ln.connectorTypes,
})

// ─── правка шапки и спецификации ────────────────────────────────────────────

function SupplyEditForm({ companyId, doc, onDone }: { companyId: string; doc: SupplyDoc; onDone: () => void }) {
  const qc = useQueryClient()
  const warehouses = useWarehouses(companyId)
  const partsQ = useQuery({ queryKey: ['equipment', 'spares', companyId], queryFn: () => listSpareParts({ companyId }) })
  const linesEditable = doc.status === 'draft' || doc.status === 'ordered'
  const headEditable = doc.qtyReceived === 0
  const [number, setNumber] = useState(doc.number)
  const [docDate, setDocDate] = useState(doc.docDate)
  const [party, setParty] = useState({ counterpartyId: doc.counterpartyId ?? '', contractId: doc.contractId ?? '' })
  const [warehouseId, setWarehouseId] = useState(doc.warehouseId ?? '')
  const [note, setNote] = useState(doc.note ?? '')
  const [lines, setLines] = useState<DraftLine[]>(() => doc.lines.map(toDraft))
  const [nextKey, setNextKey] = useState(doc.lines.length)

  const save = useMutation({
    mutationFn: async () => {
      await updateSupply(companyId, doc.id, headEditable ? {
        number: number.trim(), docDate, counterpartyId: party.counterpartyId || null,
        contractId: party.contractId || null, warehouseId: warehouseId || null, note: note.trim() || null,
      } : { note: note.trim() || null })
      if (!linesEditable) return
      const before = new Map(doc.lines.map((ln, i) => [ln.id, JSON.stringify(linePayload(toDraft(ln, i)))]))
      const kept = new Set(lines.map((l) => l.id))
      for (const ln of doc.lines) if (!kept.has(ln.id)) await deleteSupplyLine(companyId, doc.id, ln.id)
      for (const l of lines) {
        if (l.locked) continue
        if (!l.id) await addSupplyLine(companyId, doc.id, linePayload(l))
        else if (before.get(l.id) !== JSON.stringify(linePayload(l))) await updateSupplyLine(companyId, doc.id, l.id, linePayload(l))
      }
    },
    onSuccess: () => { toast.success('Документ сохранён'); onDone() },
    // Часть правок могла пройти до сбоя — перечитываем документ в любом случае.
    onError: (e) => toast.error('Документ сохранён не полностью', { description: errMsg(e) }),
    onSettled: () => { void invalidateEquipment(qc) },
  })

  const add = (lineKind: 'station' | 'spare') => {
    setLines((s) => [...s, { _key: nextKey, lineKind, qtyPlanned: 1 }])
    setNextKey((n) => n + 1)
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label className="text-xs">Номер</Label>
          <Input aria-label="Номер поставки" disabled={!headEditable} value={number} onChange={(e) => setNumber(e.target.value)} className="h-9" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Дата</Label>
          <Input aria-label="Дата поставки" disabled={!headEditable} type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className="h-9" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Склад по умолчанию</Label>
          <Select disabled={!headEditable} value={warehouseId} onValueChange={setWarehouseId}>
            <SelectTrigger className="h-9"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {warehouses.map((w) => (<SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>))}
            </SelectContent>
          </Select>
        </div>
        <div className="sm:col-span-3">
          {headEditable ? <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty}
            label={doc.docType === 'return' ? 'Кому возвращаем' : 'Поставщик'}
            preferredTypes={['Поставка ЭЗС', 'Поставка']} preferredTypeCodes={['supply']} />
            : <p className="text-xs text-muted-foreground">{doc.counterpartyName} · Реквизиты после приёмки не меняются.</p>}
        </div>
      </div>

      {linesEditable ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label className="text-xs">Спецификация</Label>
            <Button variant="outline" size="sm" className="ml-auto h-7 px-2 text-xs" onClick={() => add('station')}>
              <Plus className="mr-1 h-3.5 w-3.5" /> Станция
            </Button>
            <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => add('spare')}>
              <Plus className="mr-1 h-3.5 w-3.5" /> ЗИП
            </Button>
          </div>
          {lines.map((l) => (
            <SupplyLineFields key={l._key} companyId={companyId} line={l} parts={partsQ.data ?? []}
              onChange={(p) => setLines((s) => s.map((x) => (x._key === l._key ? { ...x, ...p } : x)))}
              onRemove={() => setLines((s) => s.filter((x) => x._key !== l._key))} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">После приёмки можно изменить примечание. Реквизиты и спецификация сохраняются для сверки с первичным документом.</p>
      )}

      <div className="space-y-1">
        <Label className="text-xs">Примечание</Label>
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="text-xs" />
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onDone}>Отмена</Button>
        <Button size="sm" disabled={!number.trim() || !docDate || !supplyLinesValid(lines) || save.isPending} onClick={() => save.mutate()}>
          {save.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
          Сохранить
        </Button>
      </div>
    </div>
  )
}

// ─── карточка ───────────────────────────────────────────────────────────────

export function SupplyCardModal({ companyId, supplyId, onClose }: {
  companyId: string
  supplyId: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const invalidate = () => { void invalidateEquipment(qc) }
  const { data: doc, isError, error, refetch } = useQuery({
    queryKey: ['equipment', 'supply', companyId, supplyId],
    queryFn: () => getSupply(companyId, supplyId),
  })
  const warehouses = useWarehouses(companyId)
  const contractsQ = useQuery({ queryKey: ['contracts', companyId], queryFn: () => getContracts(companyId), staleTime: 60_000 })
  const [receiveLine, setReceiveLine] = useState<SupplyLine | null>(null)
  const [editing, setEditing] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)

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
  const canReceive = doc && ['ordered', 'partially_received', 'received'].includes(doc.status)
  const canEdit = doc && !['closed', 'cancelled'].includes(doc.status)
  // Правила сервера: отменить и удалить можно только документ без приёмки —
  // в любом статусе; с приёмкой сначала возвращают или списывают принятое.
  const noReceipts = doc?.qtyReceived === 0
  const contract = contractsQ.data?.find((c) => c.id === doc?.contractId)

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        {isError ? (
          <LoadError what="документ" error={error} onRetry={() => void refetch()} />
        ) : !doc ? (
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

            {editing ? <SupplyEditForm companyId={companyId} doc={doc} onDone={() => setEditing(false)} /> : (
              <>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
                  <KV label="Дата" value={doc.docDate} />
                  <KV label={isReturn ? 'Кому возвращаем' : 'Поставщик'} value={doc.counterpartyName} />
                  <KV label="Договор" value={doc.contractId
                    ? <Link to={`/contractors?sub=contracts&contract=${doc.contractId}`} className="text-primary hover:underline"
                      title="Открыть карточку договора">{contract ? `№ ${contract.number} от ${contract.date}` : 'открыть договор'}</Link>
                    : undefined} />
                  <KV label="Склад" value={warehouses.find((w) => w.id === doc.warehouseId)?.name} />
                  <KV label="Сумма" value={doc.amountTotal != null ? `${nf2.format(doc.amountTotal)} ${doc.currency}` : '—'} />
                  <KV label="План / принято" value={`${nf0.format(doc.qtyPlanned)} / ${nf0.format(doc.qtyReceived)}`} />
                  <KV label="Автор" value={doc.createdByName} />
                  {doc.note && <KV label="Примечание" value={doc.note} />}
                </div>

                {/* Спецификация */}
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full min-w-[520px] text-xs">
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
                    {canReceive && (
                      <Button variant="outline" size="sm" onClick={() => statusMut.mutate('close')} disabled={statusMut.isPending}>
                        Закрыть
                      </Button>
                    )}
                    {canEdit && (
                      <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                        <Pencil className="mr-1 h-3.5 w-3.5" /> Изменить
                      </Button>
                    )}
                    {noReceipts && doc.status !== 'cancelled' && (
                      <Button variant="ghost" size="sm" className="text-muted-foreground"
                        onClick={() => statusMut.mutate('cancel')} disabled={statusMut.isPending}>
                        Отменить документ
                      </Button>
                    )}
                    {noReceipts && (
                      <Button variant="ghost" size="sm" className="text-destructive"
                        onClick={() => setConfirmDel(true)} disabled={delMut.isPending}>
                        <Trash2 className="mr-1 h-3.5 w-3.5" /> Удалить
                      </Button>
                    )}
                  </div>
                  <Button variant="outline" size="sm" onClick={onClose}>Закрыть окно</Button>
                </DialogFooter>
              </>
            )}
          </>
        )}
      </DialogContent>

      {receiveLine && doc && (
        <ReceiveLineDialog companyId={companyId} doc={doc} line={receiveLine}
          onClose={() => setReceiveLine(null)}
          onDone={() => { invalidate(); setReceiveLine(null) }} />
      )}
      {doc && (
        <AlertDialog open={confirmDel} onOpenChange={setConfirmDel}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Удалить документ?</AlertDialogTitle>
              <AlertDialogDescription>
                {SUPPLY_TYPE_META[doc.docType].label} № {doc.number} от {doc.docDate} будет удалена вместе со спецификацией
                ({doc.lines.length} поз.). Приёмки по документу не было, остатки не изменятся. Вернуть удалённый документ нельзя.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Не удалять</AlertDialogCancel>
              <AlertDialogAction onClick={() => delMut.mutate()}>Удалить</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
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

/** Состояния, из которых единицу можно вернуть поставщику (правило сервера). */
const RETURNABLE = 'in_stock_new,in_stock_used,in_repair'
const RETURN_LIMIT = 100

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
  const warehouses = useWarehouses(companyId)

  const [wh, setWh] = useState(doc.warehouseId ?? '')
  const [occurredOn, setOccurredOn] = useState(doc.docDate)
  const [comment, setComment] = useState('')
  const [qty, setQty] = useState(remaining ? String(remaining) : '')
  const [units, setUnits] = useState<ReceiveUnit[]>([{}])
  const [pickedIds, setPickedIds] = useState<string[]>([])
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  // Кандидаты на возврат отбирает сервер: по состоянию и поиску, а не из первой
  // страницы парка — на большом парке нужной единицы там могло не оказаться.
  const returnPickQ = useQuery({
    queryKey: ['equipment', 'units', companyId, 'return', search],
    queryFn: () => listUnits({ companyId, state: RETURNABLE, q: search || undefined, sort: 'serialNumber', dir: 'asc', pageSize: RETURN_LIMIT }),
    enabled: isReturn && isStation,
  })
  const candidates = returnPickQ.data?.items ?? []

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
        const hasDetails = filled.some((u) => u.serial || u.inventoryNumber || u.warrantyUntil)
        return receiveSupplyLine(companyId, doc.id, line.id,
          hasDetails ? { ...base, units: filled } : { ...base, qty: Number(qty) })
      }
      return receiveSupplyLine(companyId, doc.id, line.id, { ...base, qty: Number(qty) })
    },
    onSuccess: () => { toast.success(isReturn ? 'Возврат оформлен' : 'Приёмка выполнена'); onDone() },
    onError: (e) => toast.error(errMsg(e)),
  })

  const needWh = !isReturn || !isStation  // возврат станций склад не требует
  const canSave = (!needWh || !!wh) && (
    isReturn && isStation ? pickedIds.length > 0
      : isStation ? (units.some((u) => (u.serial || '').trim() || (u.inventoryNumber || '').trim() || u.warrantyUntil)
          || (Number.isInteger(Number(qty)) && Number(qty) > 0 && Number(qty) <= 500))
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
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
                  onClick={() => setUnits((s) => [...s, {}])}>
                  <Plus className="mr-1 h-3.5 w-3.5" /> Ещё единица
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  или без серийников — количество:
                </span>
                <Input type="number" aria-label="Количество единиц без серийных номеров" min={1} max={500} step={1} value={qty} onChange={(e) => setQty(e.target.value)}
                  className="h-7 w-20 text-xs" />
              </div>
            </div>
          )}

          {/* ЗИП (поставка/возврат): количество */}
          {!isStation && (
            <div className="space-y-1">
              <Label className="text-xs">Количество</Label>
              <Input type="number" aria-label="Количество ЗИП к приёмке" min={0.001} step={0.001} value={qty} onChange={(e) => setQty(e.target.value)} className="h-9" />
            </div>
          )}

          {/* Возврат станций: выбор единиц */}
          {isReturn && isStation && (
            <div className="space-y-1">
              <Label className="text-xs">Единицы к возврату · отмечено {pickedIds.length}</Label>
              <div className="flex items-center gap-1">
                <Input value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') setSearch(searchInput.trim()) }}
                  placeholder="Серийный №, модель, производитель, склад…" className="h-8 text-xs" />
                <Button variant="outline" size="icon" className="h-8 w-8 shrink-0" title="Искать"
                  onClick={() => setSearch(searchInput.trim())}>
                  <Search className="h-4 w-4" />
                </Button>
              </div>
              <div className="max-h-52 overflow-y-auto rounded-md border">
                {returnPickQ.isLoading ? (
                  <div className="flex justify-center py-6"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
                ) : returnPickQ.isError ? (
                  <div role="alert" className="px-3 py-4 text-center text-xs text-muted-foreground">
                    Не удалось загрузить единицы: {errMsg(returnPickQ.error)}
                  </div>
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
              {(returnPickQ.data?.total ?? 0) > candidates.length && (
                <div className="text-[11px] text-muted-foreground">
                  Показаны первые {candidates.length} из {nf0.format(returnPickQ.data?.total ?? 0)} — уточните поиск.
                </div>
              )}
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
