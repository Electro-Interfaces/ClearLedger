/**
 * Реестр документов ЗИП: приходные ордера, требования-накладные, накладные на
 * перемещение, акты на списание, инвентаризационные описи. Карточка документа,
 * повторная печать и отмена: проведённый документ не правится — ошибку исправляет
 * отмена (остаток возвращается) и новый документ. Черновик проводится или удаляется
 * из своей карточки.
 */
import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Ban, CheckCircle2, FileText, Loader2, Printer, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import {
  SPARE_DOC_META, cancelSpareDocument, deleteSpareDraft, getSpareDocument, listSpareDocuments, postSpareDraft,
  type SpareDocOp, type SpareDocument,
} from '@/services/equipmentService'
import { ApiError } from '@/services/apiClient'
import { printSpareDocument, ruDate, signed, spareSigners, spareTarget } from './spareDocPrint'

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const errText = (e: unknown) => (e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e))
const selectClass = 'h-8 rounded-md border bg-background px-2 text-xs'
const rub = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const Cancelled = () => <Badge variant="outline" className="ml-1.5 text-xs border-destructive/50 text-destructive">отменён</Badge>
const Draft = () => <Badge variant="outline" className="ml-1.5 text-xs border-amber-500/60 text-amber-700 dark:text-amber-400">черновик</Badge>
const SPARE_KEYS = ['equipment', 'eq-spares', 'eq-spare-movements', 'eq-warehouses', 'equipment-warehouses']
/** Куда и откуда — одной строкой для реестра. */
const route = (d: SpareDocument) => d.op === 'issue' ? `${d.fromLocation ?? '—'} → ${spareTarget(d) || '—'}`
  : d.op === 'transfer' ? `${d.fromLocation ?? '—'} → ${d.toLocation ?? '—'}` : d.fromLocation ?? d.toLocation ?? '—'

const F = ({ k, v, wide }: { k: string; v?: string | null; wide?: boolean }) =>
  <div className={wide ? 'sm:col-span-2' : ''}><span className="text-muted-foreground">{k}: </span>{v || '—'}</div>

function DocCard({ companyId, id, onClose }: { companyId: string; id: string; onClose: () => void }) {
  const qc = useQueryClient()
  const { company } = useCompany()
  const q = useQuery({ queryKey: ['equipment', 'spare-document', companyId, id], queryFn: () => getSpareDocument(companyId, id) })
  const [reason, setReason] = useState<string | null>(null)
  const cancel = useMutation({
    mutationFn: () => cancelSpareDocument(companyId, id, (reason ?? '').trim()),
    onSuccess: (doc) => {
      toast.success(`Документ № ${doc.number} отменён, остаток возвращён`)
      for (const k of ['equipment', 'eq-spares', 'eq-spare-movements', 'eq-warehouses', 'equipment-warehouses']) void qc.invalidateQueries({ queryKey: [k] })
      setReason(null)
    },
    onError: (e) => toast.error('Документ не отменён', { description: errText(e) }),
  })
  const postDraft = useMutation({
    mutationFn: () => postSpareDraft(companyId, id),
    onSuccess: (doc) => {
      toast.success(`${doc.title} № ${doc.number} проведён: ${doc.positions} поз.`)
      for (const w of doc.warnings ?? []) toast.warning(w)
      for (const k of SPARE_KEYS) void qc.invalidateQueries({ queryKey: [k] })
    },
    onError: (e) => toast.error('Черновик не проведён', { description: errText(e) }),
  })
  const [deleting, setDeleting] = useState(false)
  const delDraft = useMutation({
    mutationFn: () => deleteSpareDraft(companyId, id),
    onSuccess: (r) => { toast.success(`Черновик № ${r.number} удалён`); for (const k of SPARE_KEYS) void qc.invalidateQueries({ queryKey: [k] }); onClose() },
    onError: (e) => toast.error('Черновик не удалён', { description: errText(e) }),
  })
  const d = q.data
  const inv = d?.op === 'inventory'
  const draft = d?.status === 'draft'
  const [signFrom, signTo] = spareSigners(d?.op ?? 'receipt')
  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>{d ? `${d.title} № ${d.number}` : 'Документ'}{d?.status === 'cancelled' && <Cancelled />}{draft && <Draft />}</DialogTitle></DialogHeader>
      {q.isError ? <p role="alert" className="text-sm text-destructive">Документ не загрузился: {errText(q.error)}</p>
        : !d ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /> : <div className="space-y-3 text-sm">
          {d.status === 'cancelled' && <p role="alert" className="rounded-md border border-destructive/40 p-2 text-xs text-destructive">
            Отменён {ruDate(d.cancelledAt)}{d.cancelledBy ? ` · ${d.cancelledBy}` : ''}. Причина: {d.cancelReason}</p>}
          {draft && <p role="status" className="rounded-md border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs">
            Черновик: номер занят, остатки не изменены. Количество и средняя стоимость проверятся при проведении.</p>}
          <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 text-xs">
            <F k="Дата" v={ruDate(d.docDate)} /><F k="Операция" v={d.opLabel} />
            {d.fromLocation && <F k="Склад-отправитель" v={d.fromLocation} />}
            {d.toLocation && <F k={inv ? 'Склад' : 'Склад-получатель'} v={d.toLocation} />}
            {d.op === 'issue' && <F k="Получатель" v={spareTarget(d)} wide />}
            {d.repairDocument && <F k="Акт ремонта" v={`№ ${d.repairDocument.number ?? '—'}`} />}
            {!inv && <><F k="Контрагент" v={d.counterpartyName} /><F k="Договор" v={d.contractLabel} /></>}
            <F k={signFrom} v={d.responsibleFrom} /><F k={signTo} v={d.responsibleTo} />
            {(d.primaryNumber || d.primaryDate) && <F k="Первичный документ" v={`№ ${d.primaryNumber ?? '—'} от ${ruDate(d.primaryDate)}`} />}
            {!draft && <F k="Сумма без НДС" v={`${rub.format(d.amount ?? 0)} ₽`} />}
            {!draft && <F k="1С:Бухгалтерия" v={d.bpExportedAt ? `выгружен ${ruDate(d.bpExportedAt)}` : 'не выгружен'} />}
            {d.basis && <F k="Основание" v={d.basis} wide />}
            {d.comment && <F k="Комментарий" v={d.comment} wide />}
            <div className="sm:col-span-2 text-muted-foreground">Оформил {d.createdBy ?? '—'} · {ruDate(d.createdAt)}</div>
          </div>
          <div className="overflow-x-auto"><table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground text-left">
              <th className="p-2 font-medium">Номенклатура</th><th className="p-2 font-medium">Артикул</th>
              {inv ? <><th className="p-2 font-medium text-right">По учёту</th><th className="p-2 font-medium text-right">Фактически</th><th className="p-2 font-medium text-right">Отклонение</th></>
                : <th className="p-2 font-medium text-right">Количество</th>}
              {d.op === 'receipt' && <th className="p-2 font-medium text-right">Цена, ₽</th>}
              <th className="p-2 font-medium text-right">Сумма, ₽</th></tr></thead>
            <tbody>{(d.lines ?? []).map((l) => <tr key={l.partId} className="border-b border-border/30">
              <td className="p-2">{l.name}</td><td className="p-2">{l.article ?? '—'}</td>
              {inv ? <><td className="p-2 text-right tabular-nums">{l.book == null ? 'при проведении' : nf.format(l.book)}</td><td className="p-2 text-right tabular-nums">{nf.format(l.fact ?? 0)} {l.unitLabel}</td>
                <td className={`p-2 text-right tabular-nums ${l.delta ? 'font-medium text-amber-700 dark:text-amber-400' : 'text-muted-foreground'}`}>{l.delta ? signed(l.delta) : '—'}</td></>
                : <td className="p-2 text-right tabular-nums">{nf.format(l.qty ?? 0)} {l.unitLabel}</td>}
              {d.op === 'receipt' && <td className="p-2 text-right tabular-nums">{l.price != null ? rub.format(l.price) : '—'}</td>}
              <td className="p-2 text-right tabular-nums">{l.amount != null ? rub.format(l.amount) : draft ? 'при проведении' : '—'}</td></tr>)}</tbody>
          </table></div>
          {reason !== null && <div className="space-y-2 rounded-md border border-destructive/40 p-2">
            <p className="text-xs">Отмена вернёт остаток по всем строкам документа; номер останется занят. Если часть прихода уже израсходована, сначала отмените более поздние расходы.</p>
            <Textarea aria-label="Причина отмены" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина отмены — обязательно" />
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setReason(null)}>Не отменять</Button>
              <Button variant="destructive" size="sm" disabled={!reason.trim() || cancel.isPending} onClick={() => cancel.mutate()}>
                {cancel.isPending && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Подтвердить отмену</Button>
            </div>
          </div>}
          {deleting && <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 p-3 text-xs">
            <span className="min-w-0 flex-1">Удалить черновик № {d.number}? Номер освободится, остатки не затронуты.</span>
            <Button variant="outline" size="sm" onClick={() => setDeleting(false)}>Не удалять</Button>
            <Button variant="destructive" size="sm" disabled={delDraft.isPending} onClick={() => delDraft.mutate()}>Удалить черновик</Button>
          </div>}
          <div className="flex flex-wrap justify-end gap-2">
            {draft && !deleting && <Button variant="outline" className="text-destructive" onClick={() => setDeleting(true)}><Trash2 className="h-3.5 w-3.5 mr-1" />Удалить черновик</Button>}
            {d.status === 'posted' && reason === null && <Button variant="outline" onClick={() => setReason('')}><Ban className="h-3.5 w-3.5 mr-1" />Отменить документ</Button>}
            {!draft && <Button variant="outline" onClick={() => { try { printSpareDocument(d, company?.name || 'Пространство') } catch (e) { toast.error(errText(e)) } }}>
              <Printer className="h-3.5 w-3.5 mr-1" />Печать</Button>}
            {draft && <Button disabled={postDraft.isPending} onClick={() => postDraft.mutate()}>
              {postDraft.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5 mr-1" />}Провести</Button>}
          </div>
        </div>}
    </DialogContent>
  </Dialog>
}

export function SpareDocumentsSection({ companyId }: { companyId: string }) {
  const [op, setOp] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const docs = useQuery({
    queryKey: ['equipment', 'spare-documents', companyId, op, status, q],
    queryFn: () => listSpareDocuments({ companyId, op, status, q, limit: 200 }), placeholderData: keepPreviousData,
  })
  return <Card><CardContent className="p-0">
    <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-2">
      <FileText className="h-3.5 w-3.5 text-muted-foreground" /><span className="text-sm font-semibold">Документы</span>
      <span className="text-xs text-muted-foreground">{docs.data ? `${docs.data.total}` : ''}</span>
      <div className="ml-auto flex flex-wrap gap-2">
        <select aria-label="Вид документа" className={selectClass} value={op} onChange={(e) => setOp(e.target.value)}>
          <option value="">Все виды</option>{(Object.keys(SPARE_DOC_META) as SpareDocOp[]).map((o) => <option key={o} value={o}>{SPARE_DOC_META[o].label}</option>)}</select>
        <select aria-label="Состояние документа" className={selectClass} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все состояния</option><option value="posted">Проведённые</option><option value="draft">Черновики</option><option value="cancelled">Отменённые</option></select>
        <Input aria-label="Поиск документа" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, контрагент, договор, основание" className="h-8 w-60" />
      </div>
    </div>
    {docs.isError ? <p role="alert" className="p-4 text-xs text-destructive">Документы не загрузились: {errText(docs.error)}</p>
      : docs.isLoading ? <div className="p-4"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
      : !docs.data?.items.length ? <p className="p-4 text-xs text-muted-foreground">Документов нет. Приход, отпуск, перемещение, списание и инвентаризация оформляются кнопками над таблицей остатков.</p>
      : <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead><tr className="border-b text-muted-foreground text-left">
          <th className="p-2 font-medium">Документ</th><th className="p-2 font-medium">Дата</th><th className="p-2 font-medium text-right">Строк</th>
          <th className="p-2 font-medium text-right">Сумма, ₽</th>
          <th className="p-2 font-medium">Склад и получатель</th><th className="p-2 font-medium">Контрагент / договор</th><th className="p-2 font-medium">Оформил</th></tr></thead>
        <tbody>{docs.data.items.map((d) => <tr key={d.id} className={`cursor-pointer border-b border-border/30 hover:bg-muted/30 ${d.status === 'cancelled' ? 'opacity-60' : ''}`} onClick={() => setOpen(d.id)}>
          <td className="p-2"><div className="font-mono font-medium">{d.number}{d.status === 'cancelled' && <Cancelled />}{d.status === 'draft' && <Draft />}</div><div className="text-muted-foreground">{d.opLabel}</div></td>
          <td className="p-2 whitespace-nowrap">{ruDate(d.docDate)}</td><td className="p-2 text-right font-mono">{d.positions}</td>
          <td className="p-2 text-right font-mono tabular-nums">{d.status === 'draft' ? '—' : rub.format(d.amount ?? 0)}</td>
          <td className="p-2">{route(d)}</td>
          <td className="p-2">{d.counterpartyName ?? '—'}{d.contractLabel ? <div className="text-muted-foreground">{d.contractLabel}</div> : null}</td>
          <td className="p-2">{d.createdBy ?? '—'}</td></tr>)}</tbody>
      </table></div>}
    {open && <DocCard companyId={companyId} id={open} onClose={() => setOpen(null)} />}
  </CardContent></Card>
}
