/**
 * Карточка склада: вид владения, контрагент и договор (аренда, ответственное
 * хранение), ответственный, адрес. До 04.10.2026 склад был одним названием, а
 * «договор хранения закончился» жил текстом в карточках единиц.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { getWarehouseCard, updateWarehouse, type WarehouseCard } from '@/services/equipmentService'
import { CounterpartyContractPicker } from './CounterpartyContractPicker'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const OWNERSHIP = { own: 'Собственный', rent: 'Арендованный', custody: 'Ответственное хранение у контрагента' }

export const CONTRACT_STATUS: Record<string, [string, string]> = {
  active: ['договор действует', 'text-emerald-700 dark:text-emerald-400'],
  expired: ['договор истёк', 'text-red-600 dark:text-red-400'],
  closed: ['договор закрыт', 'text-red-600 dark:text-red-400'],
  missing: ['нет договора', 'text-amber-700 dark:text-amber-400'],
}

function Form({ companyId, card, onClose }: { companyId: string; card: WarehouseCard; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({
    name: card.name, address: card.address ?? '', ownership: card.ownership ?? 'own',
    responsible: card.responsible ?? '', phone: card.phone ?? '', note: card.note ?? '',
  })
  const [party, setParty] = useState({ counterpartyId: card.counterpartyId ?? '', contractId: card.contractId ?? '' })
  const [busy, setBusy] = useState(false)
  const foreign = f.ownership !== 'own'
  const save = async () => {
    setBusy(true)
    try {
      await updateWarehouse(companyId, card.id, { ...f, counterpartyId: foreign ? party.counterpartyId || null : null, contractId: foreign ? party.contractId || null : null })
      for (const k of ['equipment-warehouses', 'eq-warehouses', 'eq-warehouse-card']) await qc.invalidateQueries({ queryKey: [k] })
      toast.success('Карточка склада сохранена'); onClose()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить склад') }
    finally { setBusy(false) }
  }
  return <div className="space-y-3">
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="text-xs">Название<Input aria-label="Название склада" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="h-9" /></label>
      <label className="text-xs">Вид владения
        <select aria-label="Вид владения" className={selectClass} value={f.ownership} onChange={(e) => setF({ ...f, ownership: e.target.value as typeof f.ownership })}>
          {Object.entries(OWNERSHIP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="text-xs sm:col-span-2">Адрес<Input aria-label="Адрес склада" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className="h-9" /></label>
      <label className="text-xs">Ответственный (МОЛ)<Input aria-label="Ответственный за склад" value={f.responsible} onChange={(e) => setF({ ...f, responsible: e.target.value })} placeholder="должность, ФИО" className="h-9" /></label>
      <label className="text-xs">Телефон<Input aria-label="Телефон склада" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} className="h-9" /></label>
    </div>
    {foreign && <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty} required
      label={f.ownership === 'rent' ? 'Арендодатель' : 'Хранитель'} preferredTypes={f.ownership === 'rent' ? ['Аренда'] : ['Ответственное хранение', 'Хранение']} />}
    <label className="text-xs block">Примечание<Textarea aria-label="Примечание к складу" rows={2} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
    <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Отмена</Button>
      <Button disabled={busy || !f.name.trim() || (foreign && !party.counterpartyId)} onClick={() => void save()}>
        {busy && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Сохранить</Button></div>
  </div>
}

export function WarehouseCardDialog({ companyId, warehouseId, onClose }: { companyId: string; warehouseId: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['eq-warehouse-card', companyId, warehouseId], queryFn: () => getWarehouseCard(companyId, warehouseId) })
  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-2xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>Карточка склада</DialogTitle></DialogHeader>
      {q.data ? <Form companyId={companyId} card={q.data} onClose={onClose} />
        : q.isError ? <p role="alert" className="text-sm">Карточка не загрузилась: {q.error instanceof Error ? q.error.message : ''}</p>
        : <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
    </DialogContent>
  </Dialog>
}
