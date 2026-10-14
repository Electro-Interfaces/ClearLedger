/**
 * Реестр документов движения оборудования: накладные и акты с номером, датой,
 * контрагентом, договором и ответственными; карточка документа, повторная печать
 * и отмена. Отменённый документ из реестра не исчезает: видно, кто, когда и почему.
 * Черновик проводится или удаляется из своей карточки.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Ban, CheckCircle2, FileText, Loader2, Printer, Trash2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import { ApiError } from '@/services/apiClient'
import { loadLocations } from '@/services/locationService'
import { getContracts, getCounterparties } from '@/services/referenceService'
import {
  UNIT_OP_META, cancelEquipmentDocument, deleteEquipmentDraft, getEquipmentDocument, listEquipmentDocuments,
  postEquipmentDraft, type EquipmentDocument, type UnitOp,
} from '@/services/equipmentService'
import { eqName, printEquipmentDocument } from './equipmentDocPrint'
import { ExportXlsxButton, LoadError, Pager } from './equipmentShared'
import { allPages, invalidateEquipment } from './useEquipmentScope'

const ru = (iso?: string | null) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '—')
const rub = (v: number) => `${v.toLocaleString('ru-RU')} ₽`
const OPS: UnitOp[] = ['receipt', 'transfer', 'to_installation', 'commissioning', 'dismantle', 'to_repair', 'from_repair', 'to_vendor', 'write_off', 'reserve', 'unreserve', 'correction']
const PAGE = 50
const selectClass = 'h-8 max-w-[200px] rounded-md border bg-background px-2 text-xs'
const cancelledBadge = <Badge variant="outline" className="border-zinc-600 text-zinc-500 font-normal">Отменён</Badge>
const draftBadge = <Badge variant="outline" className="border-amber-500/60 text-amber-700 dark:text-amber-400 font-normal">Черновик</Badge>
const STATUS_LABEL = { posted: 'Проведён', cancelled: 'Отменён', draft: 'Черновик' } as const
const errText = (e: unknown) => e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)

function F({ k, children }: { k: string; children: React.ReactNode }) {
  return <div><span className="text-muted-foreground">{k}: </span>{children}</div>
}

export function EquipmentDocCard({ companyId, id, onClose }: { companyId: string; id: string; onClose: () => void }) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['equipment', 'document', companyId, id], queryFn: () => getEquipmentDocument(companyId, id) })
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')
  const cancel = useMutation({
    mutationFn: () => cancelEquipmentDocument(companyId, id, reason.trim()),
    onSuccess: (doc) => { toast.success(`Документ № ${doc.number} отменён`); setCancelling(false); void invalidateEquipment(qc) },
    onError: (e) => toast.error('Документ не отменён', { description: errText(e) }),
  })
  const postDraft = useMutation({
    mutationFn: () => postEquipmentDraft(companyId, id),
    onSuccess: (doc) => {
      toast.success(`${doc.title} № ${doc.number} проведён: ${doc.units} ед.`)
      for (const w of doc.warnings ?? []) toast.warning(w)
      void invalidateEquipment(qc)
    },
    onError: (e) => toast.error('Черновик не проведён', { description: errText(e) }),
  })
  const [deleting, setDeleting] = useState(false)
  const delDraft = useMutation({
    mutationFn: () => deleteEquipmentDraft(companyId, id),
    onSuccess: (r) => { toast.success(`Черновик № ${r.number} удалён`); void invalidateEquipment(qc); onClose() },
    onError: (e) => toast.error('Черновик не удалён', { description: errText(e) }),
  })
  const d = q.data
  const cancelled = d?.status === 'cancelled'
  const draft = d?.status === 'draft'
  const r = d?.details
  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle className="flex flex-wrap items-center gap-2">{d ? `${d.title} № ${d.number}` : 'Документ'}{cancelled && cancelledBadge}{draft && draftBadge}</DialogTitle></DialogHeader>
      {q.isError ? <LoadError what="документ" error={q.error} onRetry={() => void q.refetch()} />
        : !d ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /> : <div className="space-y-3 text-sm">
          {cancelled && <p role="status" className="rounded-md border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs">
            Документ отменён {ru(d.cancelledAt)}{d.cancelledBy ? ` · ${d.cancelledBy}` : ''}. Причина: {d.cancelReason || 'не указана'}.
            Движения по нему сняты, единицы возвращены в прежнее состояние.</p>}
          {draft && <p role="status" className="rounded-md border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs">
            Черновик: номер занят, единицы ещё не двигались. Проведение проверит состояние каждой единицы на сегодня —
            строки ниже показывают, где они сейчас.</p>}
          <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 text-xs">
            <F k="Дата">{ru(d.docDate)}</F>
            <F k="Операция">{d.opLabel}</F>
            <F k="Откуда">{d.fromLocation ?? '—'}</F>
            <F k="Куда">{d.toLocation ?? '—'}</F>
            <F k="Контрагент">{d.counterpartyName ?? '—'}</F>
            <F k="Договор">{d.contractId && d.contractLabel
              ? <Link to={`/contractors?sub=contracts&contract=${d.contractId}`} className="text-primary hover:underline" title="Открыть карточку договора">{d.contractLabel}</Link>
              : d.contractLabel ?? '—'}</F>
            <F k="Сдал">{d.responsibleFrom ?? '—'}</F>
            <F k="Принял">{d.responsibleTo ?? '—'}</F>
            {(d.primaryNumber || d.primaryDate) && <F k="Первичный документ">№ {d.primaryNumber ?? '—'} от {ru(d.primaryDate)}</F>}
            {!draft && <F k="1С:Бухгалтерия">{d.bpExportedAt ? `выгружен ${ru(d.bpExportedAt)}` : 'не выгружен'}</F>}
            {r?.ticketRef && <F k="Заявка Поддержки">№ {r.ticketRef}</F>}
            {r?.repairKind && <F k="Вид ремонта">{r.repairKind === 'warranty' ? 'гарантийный' : 'платный'}</F>}
            {r?.plannedReturn && <F k="Плановый возврат">{ru(r.plannedReturn)}</F>}
            {r?.costEstimate != null && <F k="Оценка стоимости">{rub(r.costEstimate)}</F>}
            {r?.costActual != null && <F k="Стоимость ремонта">{rub(r.costActual)}</F>}
            {r?.costAccount && <F k="Счёт списания">{r.costAccount}{r.costItem ? ` · ${r.costItem}` : ''}</F>}
            {r?.result && <F k="Результат">{r.result === 'repaired' ? 'отремонтировано' : 'ремонту не подлежит'}</F>}
            {d.basis && <div className="sm:col-span-2"><F k="Основание">{d.basis}</F></div>}
            {d.comment && <div className="sm:col-span-2"><F k="Комментарий">{d.comment}</F></div>}
            <div className="sm:col-span-2 text-muted-foreground">Оформил {d.createdBy ?? '—'} · {ru(d.createdAt)}</div>
          </div>
          <div className="overflow-x-auto"><table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground text-left">
              <th className="p-2 font-medium">Серийный №</th><th className="p-2 font-medium">Инв. №</th><th className="p-2 font-medium">Оборудование</th>
              <th className="p-2 font-medium">Откуда</th><th className="p-2 font-medium">Куда</th><th className="p-2 font-medium">Состояние до → после</th>
              <th className="p-2 font-medium">Счёт</th><th className="p-2 text-right font-medium">Сумма, ₽</th></tr></thead>
            <tbody>{(d.lines ?? []).map((l) => <tr key={l.unitId} className="border-b border-border/30">
              <td className="p-2 font-mono">{l.serialNumber ?? '—'}</td><td className="p-2 font-mono">{l.inventoryNumber ?? '—'}</td>
              <td className="p-2">{eqName(l.vendor, l.model) || '—'}</td>
              <td className="p-2">{l.from ?? '—'}</td><td className="p-2">{l.to ?? '—'}</td>
              <td className="p-2">{l.fromState ?? '—'} → {l.toState ?? '—'}</td>
              <td className="p-2 font-mono whitespace-nowrap">{l.accountFrom || l.accountTo ? `${l.accountFrom ?? '—'} → ${l.accountTo ?? '—'}` : '—'}</td>
              <td className="p-2 text-right font-mono tabular-nums">{l.amount != null ? l.amount.toLocaleString('ru-RU', { minimumFractionDigits: 2 }) : '—'}</td></tr>)}</tbody>
          </table></div>
          {cancelling && <div className="space-y-2 rounded-md border border-dashed p-3">
            <p className="text-xs">Отмена документа № {d.number}: движения по {d.lines?.length ?? d.units ?? 0} ед. будут сняты, единицы вернутся в прежнее состояние и место.
              Документ останется в реестре с пометкой «Отменён». Если по единицам уже есть более поздние движения, отмена не пройдёт — сначала отмените их.</p>
            <Textarea aria-label="Причина отмены" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина отмены (обязательно)" />
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setCancelling(false)}>Не отменять</Button>
              <Button variant="destructive" size="sm" disabled={!reason.trim() || cancel.isPending} onClick={() => cancel.mutate()}>
                {cancel.isPending && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Подтвердить отмену</Button>
            </div>
          </div>}
          {deleting && <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 p-3 text-xs">
            <span className="min-w-0 flex-1">Удалить черновик № {d.number}? Номер освободится, единицы не затронуты.</span>
            <Button variant="outline" size="sm" onClick={() => setDeleting(false)}>Не удалять</Button>
            <Button variant="destructive" size="sm" disabled={delDraft.isPending} onClick={() => delDraft.mutate()}>Удалить черновик</Button>
          </div>}
          <div className="flex flex-wrap justify-end gap-2">
            {draft && !deleting && <Button variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => setDeleting(true)}>
              <Trash2 className="h-3.5 w-3.5 mr-1" />Удалить черновик</Button>}
            {!cancelled && !draft && !cancelling && <Button variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => setCancelling(true)}>
              <Ban className="h-3.5 w-3.5 mr-1" />Отменить документ</Button>}
            {!draft && <Button variant="outline" onClick={() => { try { printEquipmentDocument(d, company?.name || 'Пространство') } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) } }}>
              <Printer className="h-3.5 w-3.5 mr-1" />Печать</Button>}
            {draft && <Button disabled={postDraft.isPending} onClick={() => postDraft.mutate()}>
              {postDraft.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5 mr-1" />}Провести</Button>}
          </div>
        </div>}
    </DialogContent>
  </Dialog>
}

const DEFAULTS = { op: '', status: '', dateFrom: '', dateTo: '', locationId: '', counterpartyId: '', contractId: '', q: '', page: 1 }

export function EquipmentDocumentsSection({ companyId }: { companyId: string }) {
  const [f, setF] = useState(DEFAULTS)
  // Смена любого отбора возвращает на первую страницу.
  const patch = (p: Partial<typeof f>) => setF((s) => ({ ...s, page: 1, ...p }))
  const [open, setOpen] = useState<string | null>(null)
  const { page, ...filters } = f
  const docs = useQuery({
    queryKey: ['equipment', 'documents', companyId, f],
    queryFn: () => listEquipmentDocuments({ companyId, ...filters, limit: PAGE, offset: (page - 1) * PAGE }),
    placeholderData: keepPreviousData,
  })
  const locs = useQuery({ queryKey: ['equipment', 'locations', companyId], queryFn: () => loadLocations(companyId), staleTime: 60_000 })
  const cps = useQuery({ queryKey: ['counterparties', companyId], queryFn: () => getCounterparties(companyId), staleTime: 60_000 })
  const contracts = useQuery({ queryKey: ['contracts', companyId], queryFn: () => getContracts(companyId), staleTime: 60_000 })
  const warehouses = (locs.data ?? []).filter((l) => l.type === 'warehouse')
  const ownContracts = (contracts.data ?? []).filter((c) => !f.counterpartyId || c.counterpartyId === f.counterpartyId)
  const filtered = Object.values(filters).some((v) => v !== '')
  const total = docs.data?.total ?? 0

  const exportAll = async () => {
    const all = await allPages<EquipmentDocument>((p) => listEquipmentDocuments({ companyId, ...filters, limit: 500, offset: (p - 1) * 500 }))
    return [{
      name: 'Документы движения',
      columns: ['Номер', 'Дата', 'Документ', 'Операция', 'Статус', 'Единиц', 'Откуда', 'Куда', 'Контрагент', 'Договор', 'Первичный №', 'Первичный от',
        'Сдал', 'Принял', 'Основание', 'Комментарий', 'Оформил', 'Причина отмены', 'Выгружен в 1С'],
      rows: all.map((d) => [d.number, d.docDate, d.title, d.opLabel, STATUS_LABEL[d.status ?? 'posted'], d.units, d.fromLocation, d.toLocation,
        d.counterpartyName, d.contractLabel, d.primaryNumber, d.primaryDate, d.responsibleFrom, d.responsibleTo, d.basis, d.comment, d.createdBy,
        d.cancelReason, d.bpExportedAt?.slice(0, 10) ?? '']),
    }]
  }

  return <Card><CardContent className="p-0">
    <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-2">
      <FileText className="h-3.5 w-3.5 text-muted-foreground" /><span className="text-sm font-semibold">Документы движения</span>
      <span className="text-xs text-muted-foreground">{docs.data ? total : ''}</span>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <Input aria-label="Документы с даты" type="date" value={f.dateFrom} onChange={(e) => patch({ dateFrom: e.target.value })} className="h-8 w-[135px] text-xs" />
        <span className="text-xs text-muted-foreground">—</span>
        <Input aria-label="Документы по дату" type="date" value={f.dateTo} onChange={(e) => patch({ dateTo: e.target.value })} className="h-8 w-[135px] text-xs" />
        <select aria-label="Операция документа" className={selectClass} value={f.op} onChange={(e) => patch({ op: e.target.value })}>
          <option value="">Все операции</option>{OPS.map((o) => <option key={o} value={o}>{UNIT_OP_META[o].label}</option>)}</select>
        <select aria-label="Статус документа" className={selectClass} value={f.status} onChange={(e) => patch({ status: e.target.value })}>
          <option value="">Все статусы</option><option value="posted">Проведённые</option><option value="draft">Черновики</option><option value="cancelled">Отменённые</option></select>
        <select aria-label="Склад документа" className={selectClass} value={f.locationId} onChange={(e) => patch({ locationId: e.target.value })}>
          <option value="">Все склады</option>{warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>
        <select aria-label="Контрагент документа" className={selectClass} value={f.counterpartyId} onChange={(e) => patch({ counterpartyId: e.target.value, contractId: '' })}>
          <option value="">Все контрагенты</option>{(cps.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.shortName || c.name}</option>)}</select>
        <select aria-label="Договор документа" className={selectClass} value={f.contractId} onChange={(e) => patch({ contractId: e.target.value })}>
          <option value="">Все договоры</option>{ownContracts.map((c) => <option key={c.id} value={c.id}>№ {c.number} от {c.date}</option>)}</select>
        <Input aria-label="Поиск документа" value={f.q} onChange={(e) => patch({ q: e.target.value })} placeholder="Номер, контрагент, договор, МОЛ" className="h-8 w-52 text-xs" />
        <ExportXlsxButton title="Документы движения оборудования" load={exportAll} />
      </div>
    </div>
    {docs.isLoading ? <div className="p-4"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
      : docs.isError ? <div className="p-3"><LoadError what="документы" error={docs.error} onRetry={() => void docs.refetch()} /></div>
      : !docs.data?.items.length ? <p className="p-4 text-xs text-muted-foreground">{filtered ? 'По заданному отбору документов нет.'
        : 'Документов пока нет. Движение оформляется в «Парке оборудования»: отметьте единицы и нажмите «Оформить документ» или откройте единицу и выберите операцию.'}</p>
      : <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead><tr className="border-b text-muted-foreground text-left">
          <th className="p-2 font-medium">Документ</th><th className="p-2 font-medium">Дата</th><th className="p-2 font-medium">Ед.</th>
          <th className="p-2 font-medium">Откуда → куда</th><th className="p-2 font-medium">Контрагент / договор</th><th className="p-2 font-medium">Сдал / принял</th></tr></thead>
        <tbody>{docs.data.items.map((d) => <tr key={d.id} className={`cursor-pointer border-b border-border/30 hover:bg-muted/30 ${d.status === 'cancelled' ? 'text-muted-foreground' : ''}`} onClick={() => setOpen(d.id)}>
          <td className="p-2"><div className="flex items-center gap-2 font-mono font-medium"><span className={d.status === 'cancelled' ? 'line-through' : ''}>{d.number}</span>{d.status === 'cancelled' && cancelledBadge}{d.status === 'draft' && draftBadge}</div>
            <div className="text-muted-foreground">{d.opLabel}{d.status === 'cancelled' && d.cancelReason ? ` · ${d.cancelReason}` : ''}</div></td>
          <td className="p-2 whitespace-nowrap">{ru(d.docDate)}</td><td className="p-2 text-right font-mono">{d.units}</td>
          <td className="p-2">{d.fromLocation ?? '—'} → {d.toLocation ?? '—'}</td>
          <td className="p-2">{d.counterpartyName ?? '—'}{d.contractLabel ? <div className="text-muted-foreground">{d.contractLabel}</div> : null}</td>
          <td className="p-2">{d.responsibleFrom ?? '—'} / {d.responsibleTo ?? '—'}</td></tr>)}</tbody>
      </table></div>}
    <div className="py-2 empty:hidden"><Pager page={page} pages={Math.ceil(total / PAGE)} onPage={(p) => setF((s) => ({ ...s, page: p }))} /></div>
    {open && <EquipmentDocCard companyId={companyId} id={open} onClose={() => setOpen(null)} />}
  </CardContent></Card>
}
