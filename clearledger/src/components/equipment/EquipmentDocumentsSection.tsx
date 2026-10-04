/**
 * Реестр документов движения оборудования: накладные и акты с номером, датой,
 * контрагентом, договором и ответственными; карточка документа и повторная печать.
 */
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { FileText, Loader2, Printer } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import { UNIT_OP_META, getEquipmentDocument, listEquipmentDocuments, type UnitOp } from '@/services/equipmentService'
import { eqName, printEquipmentDocument } from './equipmentDocPrint'

const ru = (iso?: string | null) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '—')
const OPS: UnitOp[] = ['transfer', 'to_installation', 'commissioning', 'dismantle', 'to_repair', 'from_repair', 'to_vendor', 'write_off', 'reserve', 'unreserve', 'correction']

function DocCard({ companyId, id, onClose }: { companyId: string; id: string; onClose: () => void }) {
  const { company } = useCompany()
  const q = useQuery({ queryKey: ['eq-document', companyId, id], queryFn: () => getEquipmentDocument(companyId, id) })
  const d = q.data
  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>{d ? `${d.title} № ${d.number}` : 'Документ'}</DialogTitle></DialogHeader>
      {!d ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /> : <div className="space-y-3 text-sm">
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 text-xs">
          <div><span className="text-muted-foreground">Дата: </span>{ru(d.docDate)}</div>
          <div><span className="text-muted-foreground">Операция: </span>{d.opLabel}</div>
          <div><span className="text-muted-foreground">Откуда: </span>{d.fromLocation ?? '—'}</div>
          <div><span className="text-muted-foreground">Куда: </span>{d.toLocation ?? '—'}</div>
          <div><span className="text-muted-foreground">Контрагент: </span>{d.counterpartyName ?? '—'}</div>
          <div><span className="text-muted-foreground">Договор: </span>{d.contractLabel ?? '—'}</div>
          <div><span className="text-muted-foreground">Сдал: </span>{d.responsibleFrom ?? '—'}</div>
          <div><span className="text-muted-foreground">Принял: </span>{d.responsibleTo ?? '—'}</div>
          {d.basis && <div className="sm:col-span-2"><span className="text-muted-foreground">Основание: </span>{d.basis}</div>}
          {d.comment && <div className="sm:col-span-2"><span className="text-muted-foreground">Комментарий: </span>{d.comment}</div>}
          <div className="sm:col-span-2 text-muted-foreground">Оформил {d.createdBy ?? '—'} · {ru(d.createdAt)}</div>
        </div>
        <div className="overflow-x-auto"><table className="w-full text-xs">
          <thead><tr className="border-b bg-muted/40 text-muted-foreground text-left">
            <th className="p-2 font-medium">Серийный №</th><th className="p-2 font-medium">Оборудование</th><th className="p-2 font-medium">Откуда</th>
            <th className="p-2 font-medium">Куда</th><th className="p-2 font-medium">Состояние после</th></tr></thead>
          <tbody>{(d.lines ?? []).map((l) => <tr key={l.unitId} className="border-b border-border/30">
            <td className="p-2 font-mono">{l.serialNumber ?? '—'}</td><td className="p-2">{eqName(l.vendor, l.model)}</td>
            <td className="p-2">{l.from ?? '—'}</td><td className="p-2">{l.to ?? '—'}</td><td className="p-2">{l.toState ?? '—'}</td></tr>)}</tbody>
        </table></div>
        <div className="flex justify-end"><Button variant="outline" onClick={() => { try { printEquipmentDocument(d, company?.name || 'Пространство') } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) } }}>
          <Printer className="h-3.5 w-3.5 mr-1" />Печать</Button></div>
      </div>}
    </DialogContent>
  </Dialog>
}

export function EquipmentDocumentsSection({ companyId }: { companyId: string }) {
  const [op, setOp] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const docs = useQuery({ queryKey: ['eq-documents', companyId, op, q], queryFn: () => listEquipmentDocuments({ companyId, op, q, limit: 100 }), placeholderData: keepPreviousData })
  return <Card><CardContent className="p-0">
    <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-2">
      <FileText className="h-3.5 w-3.5 text-muted-foreground" /><span className="text-sm font-semibold">Документы движения</span>
      <span className="text-xs text-muted-foreground">{docs.data ? `${docs.data.total}` : ''}</span>
      <div className="ml-auto flex flex-wrap gap-2">
        <select aria-label="Операция документа" className="h-8 rounded-md border bg-background px-2 text-xs" value={op} onChange={(e) => setOp(e.target.value)}>
          <option value="">Все операции</option>{OPS.map((o) => <option key={o} value={o}>{UNIT_OP_META[o].label}</option>)}</select>
        <Input aria-label="Поиск документа" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, контрагент, договор, МОЛ" className="h-8 w-56" />
      </div>
    </div>
    {docs.isLoading ? <div className="p-4"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
      : !docs.data?.items.length ? <p className="p-4 text-xs text-muted-foreground">Документов пока нет. Движение оформляется в «Парке оборудования»: отметьте единицы и нажмите «Оформить документ» или откройте единицу и выберите операцию.</p>
      : <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead><tr className="border-b text-muted-foreground text-left">
          <th className="p-2 font-medium">Документ</th><th className="p-2 font-medium">Дата</th><th className="p-2 font-medium">Ед.</th>
          <th className="p-2 font-medium">Откуда → куда</th><th className="p-2 font-medium">Контрагент / договор</th><th className="p-2 font-medium">Сдал / принял</th></tr></thead>
        <tbody>{docs.data.items.map((d) => <tr key={d.id} className="cursor-pointer border-b border-border/30 hover:bg-muted/30" onClick={() => setOpen(d.id)}>
          <td className="p-2"><div className="font-mono font-medium">{d.number}</div><div className="text-muted-foreground">{d.opLabel}</div></td>
          <td className="p-2 whitespace-nowrap">{ru(d.docDate)}</td><td className="p-2 text-right font-mono">{d.units}</td>
          <td className="p-2">{d.fromLocation ?? '—'} → {d.toLocation ?? '—'}</td>
          <td className="p-2">{d.counterpartyName ?? '—'}{d.contractLabel ? <div className="text-muted-foreground">{d.contractLabel}</div> : null}</td>
          <td className="p-2">{d.responsibleFrom ?? '—'} / {d.responsibleTo ?? '—'}</td></tr>)}</tbody>
      </table></div>}
    {open && <DocCard companyId={companyId} id={open} onClose={() => setOpen(null)} />}
  </CardContent></Card>
}
