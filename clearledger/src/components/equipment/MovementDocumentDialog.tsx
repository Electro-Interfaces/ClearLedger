/**
 * Документ движения оборудования: одна или несколько единиц одной операцией.
 *
 * Операция проводится документом с номером, датой, контрагентом и договором из
 * справочников пространства и ответственными «сдал / принял» — как в складском
 * учёте. Переходы состояния проверяет сервер, по каждой единице.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import {
  UNIT_OP_META, UNIT_STATE_META, getEquipmentDocsMeta, opAllowedFor, postEquipmentDocument,
  type EquipmentUnit, type UnitOp, type UnitState,
} from '@/services/equipmentService'
import type { ServiceLocation } from '@/types/location'
import { CounterpartyContractPicker } from './CounterpartyContractPicker'
import { eqName, printEquipmentDocument } from './equipmentDocPrint'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const DOC_OPS: UnitOp[] = ['transfer', 'to_installation', 'commissioning', 'dismantle', 'to_repair', 'from_repair', 'to_vendor', 'write_off', 'reserve', 'unreserve']
const NEEDS_WAREHOUSE: UnitOp[] = ['transfer', 'dismantle', 'from_repair']

function LocSelect({ items, value, onChange, label }: { items: ServiceLocation[]; value: string; onChange: (v: string) => void; label: string }) {
  const [f, setF] = useState('')
  const shown = useMemo(() => {
    const n = f.trim().toLocaleLowerCase('ru')
    const list = items.filter((l) => !n || `${l.name} ${l.code} ${l.address ?? ''}`.toLocaleLowerCase('ru').includes(n)).slice(0, 300)
    const sel = items.find((l) => l.id === value)
    return sel && !list.includes(sel) ? [sel, ...list] : list
  }, [items, f, value])
  return <label className="block text-xs">{label}
    {items.length > 20 && <Input aria-label={`${label}: поиск`} value={f} onChange={(e) => setF(e.target.value)} placeholder="Поиск…" className="h-9 mb-1" />}
    <select aria-label={label} className={selectClass} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Не выбрано</option>
      {shown.map((l) => <option key={l.id} value={l.id}>{l.name}{l.address ? ` · ${l.address}` : ''}</option>)}
    </select>
  </label>
}

export function MovementDocumentDialog({ companyId, units, op: fixedOp, warehouses, sites, onClose, onDone }: {
  companyId: string
  units: Pick<EquipmentUnit, 'id' | 'serialNumber' | 'model' | 'vendor' | 'state' | 'location'>[]
  op?: UnitOp | null
  warehouses: ServiceLocation[]
  sites: ServiceLocation[]
  onClose: () => void
  onDone?: () => void
}) {
  const qc = useQueryClient()
  const { company } = useCompany()
  const meta = useQuery({ queryKey: ['eq-docs-meta'], queryFn: getEquipmentDocsMeta, staleTime: 3_600_000 })
  const available = DOC_OPS.filter((o) => units.every((u) => opAllowedFor(o, u.state as UnitState)))
  const [op, setOp] = useState<UnitOp | ''>(fixedOp ?? (available.length === 1 ? available[0] : ''))
  const [docDate, setDocDate] = useState(new Date().toISOString().slice(0, 10))
  const [number, setNumber] = useState('')
  const [toLocationId, setToLocationId] = useState('')
  const [party, setParty] = useState({ counterpartyId: '', contractId: '' })
  const [responsibleFrom, setResponsibleFrom] = useState('')
  const [responsibleTo, setResponsibleTo] = useState('')
  const [basis, setBasis] = useState('')
  const [comment, setComment] = useState('')
  const [custodian, setCustodian] = useState<'contractor' | 'vendor'>('contractor')
  const [syncPassport, setSyncPassport] = useState(false)
  const needsCp = !!op && (meta.data?.counterpartyRequired ?? ['to_repair', 'from_repair', 'to_vendor']).includes(op)

  const mut = useMutation({
    mutationFn: () => postEquipmentDocument(companyId, {
      op: op as UnitOp, unitIds: units.map((u) => u.id), docDate, number: number.trim() || undefined,
      toLocationId: toLocationId || undefined, counterpartyId: party.counterpartyId || undefined,
      contractId: party.contractId || undefined, responsibleFrom: responsibleFrom.trim() || undefined,
      responsibleTo: responsibleTo.trim() || undefined, basis: basis.trim() || undefined, comment: comment.trim() || undefined,
      custodian: op === 'to_repair' ? custodian : undefined, syncPassport: op === 'commissioning' ? syncPassport : undefined,
    }),
    onSuccess: (doc) => {
      toast.success(`${doc.title} № ${doc.number} проведён: ${doc.units} ед.`)
      for (const w of doc.warnings ?? []) toast.warning(w)
      for (const k of ['eq-units', 'eq-unit', 'eq-overview', 'eq-movements', 'eq-warehouses', 'equipment-warehouses', 'eq-documents']) void qc.invalidateQueries({ queryKey: [k] })
      try { printEquipmentDocument(doc, company?.name || 'Пространство') } catch (e) { toast.info(e instanceof Error ? e.message : String(e)) }
      onDone?.(); onClose()
    },
    onError: (e) => toast.error('Документ не проведён', { description: e instanceof Error ? e.message : String(e) }),
  })
  const problem = !op ? 'Выберите операцию'
    : NEEDS_WAREHOUSE.includes(op) && !toLocationId ? 'Выберите склад-получатель'
    : op === 'to_installation' && !toLocationId ? 'Выберите площадку ЭЗС'
    : needsCp && !party.counterpartyId ? 'Выберите контрагента: оборудование уходит из наших рук'
    : !docDate ? 'Укажите дату документа' : null

  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>{op && meta.data ? meta.data.kinds[op]?.title : 'Документ движения оборудования'}</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div className="rounded-md border p-2 text-xs max-h-32 overflow-y-auto">
          <div className="font-medium mb-1">Единиц: {units.length}</div>
          {units.map((u) => <div key={u.id} className="flex flex-wrap gap-x-2"><span className="font-mono">{u.serialNumber ?? '—'}</span>
            <span>{eqName(u.vendor, u.model)}</span><span className="text-muted-foreground">· {UNIT_STATE_META[u.state as UnitState]?.label ?? u.state}{u.location ? ` · ${u.location.name}` : ''}</span></div>)}
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="text-xs">Операция
            <select aria-label="Операция" className={selectClass} value={op} disabled={!!fixedOp} onChange={(e) => { setOp(e.target.value as UnitOp); setToLocationId('') }}>
              <option value="">{available.length ? 'Выберите' : 'Нет общей операции для выбранных'}</option>
              {(fixedOp ? [fixedOp] : available).map((o) => <option key={o} value={o}>{UNIT_OP_META[o].label}</option>)}
            </select></label>
          <label className="text-xs">Дата документа<Input aria-label="Дата документа" type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className="h-9" /></label>
          <label className="text-xs">Номер<Input aria-label="Номер документа" value={number} onChange={(e) => setNumber(e.target.value)} placeholder={op && meta.data ? `${meta.data.kinds[op]?.prefix}-${docDate.slice(0, 4)}-… автоматически` : 'автоматически'} className="h-9" /></label>
        </div>
        {op && NEEDS_WAREHOUSE.includes(op) && <LocSelect label="Склад-получатель" items={warehouses.filter((w) => !(op === 'transfer' && units.every((u) => u.location?.id === w.id)))} value={toLocationId} onChange={setToLocationId} />}
        {op === 'to_installation' && <LocSelect label="Площадка ЭЗС" items={sites} value={toLocationId} onChange={setToLocationId} />}
        {op === 'to_repair' && <label className="text-xs block">Кому передаётся
          <select aria-label="Кому передаётся" className={selectClass} value={custodian} onChange={(e) => setCustodian(e.target.value as 'contractor' | 'vendor')}>
            <option value="contractor">Подрядчику (ремонт)</option><option value="vendor">Производителю (гарантия)</option></select></label>}
        {op === 'commissioning' && <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={syncPassport} onChange={(e) => setSyncPassport(e.target.checked)} />Обновить паспорт площадки из карточки</label>}
        {op && <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty} required={needsCp}
          preferredTypes={meta.data?.contractTypes[op] ?? []} label={op === 'to_vendor' ? 'Поставщик' : op === 'transfer' ? 'Контрагент (если склад чужой)' : 'Контрагент'} />}
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">Сдал (должность, ФИО)<Input aria-label="Сдал" value={responsibleFrom} onChange={(e) => setResponsibleFrom(e.target.value)} className="h-9" /></label>
          <label className="text-xs">Принял (должность, ФИО)<Input aria-label="Принял" value={responsibleTo} onChange={(e) => setResponsibleTo(e.target.value)} className="h-9" /></label>
        </div>
        <label className="text-xs block">Основание<Input aria-label="Основание" value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="заявка, письмо, распоряжение…" className="h-9" /></label>
        <label className="text-xs block">Комментарий<Textarea aria-label="Комментарий" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
        {problem && <p className="text-xs text-muted-foreground">{problem}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button disabled={!!problem || mut.isPending} onClick={() => mut.mutate()}>
            {mut.isPending && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Провести и распечатать</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
}
