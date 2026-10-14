/**
 * Документы договора: подписанный экземпляр, доп. соглашения, спецификации, акты, счета.
 *
 * Хранятся в «Треке» — со своим номером, версиями файла и правами, как любой документ
 * пространства, — и привязаны к договору связью `annex_of → contract:<id>` (предмет
 * карточки «Трека» уникален, а бумаг у договора много). Поэтому тот же документ виден
 * в «Треке», в карточке договора и в «Документах» пространства (папка договора).
 *
 * Доп. соглашение может менять срок и сумму — как в 1С, где оно живёт табличной частью
 * договора: изменение применяется к договору, а в документе остаётся, что именно поменяли.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Paperclip } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { get, post } from '@/services/apiClient'
import { createDoc, getDoc, listDocs, registerDoc, uploadVersion, type DocKind } from '@/services/docsService'
import { updateContract } from '@/services/referenceService'
import { openAuthAttachment } from '@/lib/authFiles'
import type { Contract } from '@/types'

const field = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const STATUS: Record<string, string> = { draft: 'черновик', registered: 'зарегистрирован', in_force: 'действует', executed: 'исполнен', archived: 'в архиве', cancelled: 'отменён' }

export function ContractDocumentsBlock({ contract: c }: { contract: Contract }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const ref = `contract:${c.id}`
  const docs = useQuery({ queryKey: ['contract-docs', c.id], queryFn: () => listDocs(companyId, { ref } as never) })
  const [adding, setAdding] = useState(false)
  const kinds = useQuery({
    queryKey: ['contract-doc-kinds', companyId], enabled: adding, staleTime: 600_000,
    queryFn: async () => (await get<{ kinds: DocKind[] }>('/api/docs/contract-kinds', { company_id: companyId })).kinds,
  })
  const [f, setF] = useState({ kindId: '', number: '', date: '', title: '', validUntil: '', amount: '' })
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const kind = kinds.data?.find((k) => k.id === f.kindId)
  const supplement = kind?.code === 'contract_supplement'

  const open = async (id: string) => {
    try {
      const d = await getDoc(companyId, id)
      const v = d.versions.find((x) => x.is_current) ?? d.versions[0]
      if (!v) { toast.info('Файл к документу не приложен'); return }
      await openAuthAttachment(`/api/files/${v.file_id}`)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось открыть файл') }
  }

  const save = async () => {
    if (!kind || !file) return
    setBusy(true)
    try {
      const changes: Record<string, unknown> = {}
      if (supplement && f.validUntil) changes.validUntil = f.validUntil
      if (supplement && f.amount) changes.amountLimit = Number(f.amount)
      const doc = await createDoc(companyId, {
        kind_id: kind.id, title: f.title.trim() || `${kind.name} к договору № ${c.number}`,
        counterparty_id: c.counterpartyId, external_number: f.number.trim() || null, external_date: f.date || null,
        attrs: { contract_id: c.id, ...(Object.keys(changes).length ? { contract_changes: changes } : {}) },
      })
      await post(`/api/docs/${doc.id}/relations`, { company_id: companyId, kind: 'annex_of', target_ref: ref })
      await uploadVersion(companyId, doc.id, file, 'body')
      await registerDoc(companyId, doc.id)
      if (Object.keys(changes).length) {
        await updateContract(companyId, c.id, changes as Partial<Contract>)
        qc.invalidateQueries({ queryKey: ['references', companyId] })
      }
      qc.invalidateQueries({ queryKey: ['contract-docs', c.id] })
      qc.invalidateQueries({ queryKey: ['raw-docs-space', companyId] })
      toast.success(Object.keys(changes).length ? 'Доп. соглашение добавлено, условия договора обновлены' : 'Документ добавлен к договору')
      setAdding(false); setFile(null); setF({ kindId: '', number: '', date: '', title: '', validUntil: '', amount: '' })
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось добавить документ') }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-2 border-t border-border/50 pt-3">
      <div className="flex items-center gap-2">
        <p className="flex-1 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">Документы договора</p>
        <Button size="sm" variant="outline" onClick={() => setAdding((v) => !v)}>Добавить документ</Button>
      </div>
      {adding && <div className="space-y-2 rounded-md border p-2">
        <div className="grid gap-2 sm:grid-cols-[1fr_120px_150px]">
          <select aria-label="Вид документа" className={field} value={f.kindId} onChange={(e) => setF((s) => ({ ...s, kindId: e.target.value }))}>
            <option value="">{kinds.isLoading ? 'Загрузка видов…' : 'Вид документа'}</option>
            {kinds.data?.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
          <Input aria-label="Номер документа" className="h-9" placeholder="Номер" value={f.number} onChange={(e) => setF((s) => ({ ...s, number: e.target.value }))} />
          <Input aria-label="Дата документа" className="h-9" type="date" value={f.date} onChange={(e) => setF((s) => ({ ...s, date: e.target.value }))} />
        </div>
        <Input aria-label="Описание документа" className="h-9" placeholder="Описание (необязательно): о чём документ" value={f.title} onChange={(e) => setF((s) => ({ ...s, title: e.target.value }))} />
        {supplement && <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs space-y-1"><span className="text-muted-foreground">Новый срок действия (если меняется)</span>
            <Input aria-label="Новый срок действия" className="h-9" type="date" value={f.validUntil} onChange={(e) => setF((s) => ({ ...s, validUntil: e.target.value }))} /></label>
          <label className="text-xs space-y-1"><span className="text-muted-foreground">Новая сумма (если меняется)</span>
            <Input aria-label="Новая сумма" className="h-9" inputMode="decimal" value={f.amount} onChange={(e) => setF((s) => ({ ...s, amount: e.target.value.replace(/[^\d.]/g, '') }))} /></label>
        </div>}
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Paperclip className="size-4" /><span className="truncate">{file ? file.name : 'Выбрать файл (PDF, скан, DOCX, до 25 МБ)'}</span>
          <input aria-label="Файл документа" type="file" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <Button size="sm" disabled={!kind || !file || busy} onClick={() => void save()}>
          {busy && <Loader2 className="size-4 mr-1 animate-spin" />}Сохранить документ</Button>
      </div>}
      {docs.isLoading ? <p className="text-xs text-muted-foreground">Загрузка…</p>
        : !docs.data?.docs?.length ? <p className="text-xs text-muted-foreground">Документов нет. Подписанный экземпляр, доп. соглашения и акты прикладываются здесь.</p>
        : <ul className="divide-y text-sm">{docs.data.docs.map((d) => <li key={d.id} className="flex items-center gap-2 py-1.5">
            <div className="flex-1 min-w-0">
              <div className="truncate">{d.kind_name}{d.external_number ? ` № ${d.external_number}` : ''}{d.external_date ? ` от ${d.external_date}` : ''}</div>
              <div className="text-xs text-muted-foreground truncate">{d.title} · {d.reg_number ?? 'без номера'} · {STATUS[d.status] ?? d.status}</div>
            </div>
            {d.has_files && <Button size="sm" variant="ghost" onClick={() => void open(d.id)}>открыть</Button>}
          </li>)}</ul>}
    </div>
  )
}
