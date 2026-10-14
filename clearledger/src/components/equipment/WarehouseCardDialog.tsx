/**
 * Карточка склада: остатки на дату и реквизиты.
 *
 * «Остатки» — номенклатура склада в количестве и сумме со счётом учёта (как ОСВ по
 * счёту в 1С с субконто «Склады»); строка станции раскрывается в серийные номера.
 * «Реквизиты» — вид владения, контрагент и договор (аренда, ответственное хранение),
 * МОЛ из участников пространства, код и ссылка склада в 1С.
 *
 * Здесь же склад закрывают (пустой — уходит из выбора в документах, история
 * остаётся) и удаляют (заведённый по ошибке, без единиц и истории).
 */
import { Fragment, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, Loader2, Lock, LockOpen, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError } from '@/services/apiClient'
import {
  deleteWarehouse, getBalanceReport, getWarehouseCard, listEquipmentPeople, setWarehouseClosed, updateWarehouse,
  type BalanceWarehouse, type WarehouseCard,
} from '@/services/equipmentService'
import { CounterpartyContractPicker } from './CounterpartyContractPicker'
import { invalidateEquipment } from './useEquipmentScope'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const OWNERSHIP = { own: 'Собственный', rent: 'Арендованный', custody: 'Ответственное хранение у контрагента' }
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const today = () => new Date().toISOString().slice(0, 10)
const errText = (e: unknown) => e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)

export const CONTRACT_STATUS: Record<string, [string, string]> = {
  active: ['договор действует', 'text-emerald-700 dark:text-emerald-400'],
  expired: ['договор истёк', 'text-red-600 dark:text-red-400'],
  closed: ['договор закрыт', 'text-red-600 dark:text-red-400'],
  missing: ['нет договора', 'text-amber-700 dark:text-amber-400'],
}

function Requisites({ companyId, card, onClose }: { companyId: string; card: WarehouseCard; onClose: () => void }) {
  const qc = useQueryClient()
  const people = useQuery({ queryKey: ['equipment', 'people', companyId], queryFn: () => listEquipmentPeople(companyId), staleTime: 300_000 })
  const [f, setF] = useState({
    name: card.name, address: card.address ?? '', ownership: card.ownership ?? 'own',
    responsible: card.responsible ?? '', responsibleUserId: card.responsibleUserId ?? '',
    phone: card.phone ?? '', note: card.note ?? '', bpCode: card.bpCode ?? '', bpRef: card.bpRef ?? '',
  })
  const [party, setParty] = useState({ counterpartyId: card.counterpartyId ?? '', contractId: card.contractId ?? '' })
  const [busy, setBusy] = useState(false)
  const foreign = f.ownership !== 'own'
  const save = async () => {
    setBusy(true)
    try {
      await updateWarehouse(companyId, card.id, {
        ...f, responsibleUserId: f.responsibleUserId || null,
        counterpartyId: foreign ? party.counterpartyId || null : null, contractId: foreign ? party.contractId || null : null,
      })
      await invalidateEquipment(qc)
      toast.success('Карточка склада сохранена'); onClose()
    } catch (e) { toast.error('Склад не сохранён', { description: errText(e) }) }
    finally { setBusy(false) }
  }
  return <div className="space-y-3">
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="text-xs">Название<Input aria-label="Название склада" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="h-9" /></label>
      <label className="text-xs">Вид владения
        <select aria-label="Вид владения" className={selectClass} value={f.ownership} onChange={(e) => setF({ ...f, ownership: e.target.value as typeof f.ownership })}>
          {Object.entries(OWNERSHIP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="text-xs sm:col-span-2">Адрес<Input aria-label="Адрес склада" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className="h-9" /></label>
      <label className="text-xs">Ответственный (МОЛ)
        <select aria-label="Материально ответственное лицо" className={selectClass} value={f.responsibleUserId}
          onChange={(e) => setF({ ...f, responsibleUserId: e.target.value })}>
          <option value="">{f.responsible && !f.responsibleUserId ? `Записан текстом: ${f.responsible}` : 'Не назначен'}</option>
          {(people.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
      <label className="text-xs">Телефон<Input aria-label="Телефон склада" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} className="h-9" /></label>
      {!f.responsibleUserId && <label className="text-xs sm:col-span-2">МОЛ не из участников пространства
        <Input aria-label="МОЛ текстом" value={f.responsible} onChange={(e) => setF({ ...f, responsible: e.target.value })}
          placeholder="должность, ФИО — подставляется в «сдал» и «принял» документов" className="h-9" /></label>}
    </div>
    {foreign && <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty} required
      label={f.ownership === 'rent' ? 'Арендодатель' : 'Хранитель'} preferredTypes={f.ownership === 'rent' ? ['Аренда'] : ['Ответственное хранение', 'Хранение']}
      preferredTypeCodes={f.ownership === 'rent' ? ['rent'] : ['storage']} />}
    <fieldset className="grid gap-2 rounded-lg border p-3 sm:grid-cols-2">
      <legend className="px-1 text-xs text-muted-foreground">Связь с 1С:Бухгалтерией</legend>
      <label className="text-xs">Код склада в 1С<Input aria-label="Код склада в 1С" value={f.bpCode} onChange={(e) => setF({ ...f, bpCode: e.target.value })} className="h-9 font-mono" /></label>
      <label className="text-xs">Ссылка (GUID) в 1С<Input aria-label="Ссылка склада в 1С" value={f.bpRef} onChange={(e) => setF({ ...f, bpRef: e.target.value })}
        placeholder="заполняется выгрузкой" className="h-9 font-mono" /></label>
    </fieldset>
    <label className="text-xs block">Примечание<Textarea aria-label="Примечание к складу" rows={2} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
    <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Отмена</Button>
      <Button disabled={busy || !f.name.trim() || (foreign && !party.counterpartyId)} onClick={() => void save()}>
        {busy && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Сохранить</Button></div>
  </div>
}

/** Остатки склада на дату: номенклатура, счёт, количество, сумма; станции раскрываются в серийники. */
export function WarehouseBalance({ companyId, warehouseId }: { companyId: string; warehouseId: string }) {
  const [day, setDay] = useState(today())
  const [open, setOpen] = useState<Set<string>>(new Set())
  const q = useQuery({
    queryKey: ['equipment', 'balance', companyId, warehouseId, day],
    queryFn: () => getBalanceReport({ companyId, date: day || today(), locationId: warehouseId }),
  })
  const w: BalanceWarehouse | undefined = q.data?.warehouses[0]
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })
  return <div className="space-y-2">
    <div className="flex flex-wrap items-end justify-between gap-2">
      <label className="text-xs">Остаток на дату
        <Input type="date" aria-label="Дата остатка" value={day} onChange={(e) => setDay(e.target.value)} className="h-9 w-40" /></label>
      {w && <div className="text-sm">Итого: <span className="font-mono font-semibold tabular-nums">{money.format(w.amount)} ₽</span>
        <span className="ml-2 text-xs text-muted-foreground">без НДС · {w.positions} поз.</span></div>}
    </div>
    {q.isLoading ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      : q.isError ? <p role="alert" className="text-sm">Остатки не загрузились: {errText(q.error)}</p>
      : !w || w.items.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">На эту дату на складе ничего не числится.</p>
      : <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead><tr className="border-b bg-muted/40 text-left text-muted-foreground">
            <th className="p-2 font-medium">Номенклатура</th><th className="p-2 font-medium">Счёт</th>
            <th className="p-2 text-right font-medium">Количество</th><th className="p-2 text-right font-medium">Сумма, ₽</th>
          </tr></thead>
          <tbody>
            {w.items.map((i) => {
              const has = i.units.length > 0
              const isOpen = open.has(i.key)
              return <Fragment key={i.key}>
                <tr className="border-b border-border/30">
                  <td className="p-2">
                    {has ? <button type="button" className="inline-flex min-h-6 items-center gap-1 text-left hover:text-primary"
                      aria-expanded={isOpen} onClick={() => toggle(i.key)}>
                      {isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                      {i.name}</button> : i.name}
                    {i.key.startsWith('text:') && <span className="ml-2 text-amber-700 dark:text-amber-400">без номенклатуры</span>}
                  </td>
                  <td className="p-2 font-mono">{i.account}</td>
                  <td className="p-2 text-right font-mono tabular-nums">{nf.format(i.qty)} {i.unitLabel}</td>
                  <td className="p-2 text-right font-mono tabular-nums">{money.format(i.amount)}</td>
                </tr>
                {isOpen && i.units.map((u) => <tr key={u.id} className="border-b border-border/20 bg-muted/20 text-muted-foreground">
                  <td className="py-1 pl-8 pr-2 font-mono" colSpan={2}>{u.serialNumber ?? 'без серийного номера'}
                    {u.inventoryNumber && <span className="ml-2">инв. {u.inventoryNumber}</span>}
                    <span className="ml-2 font-sans">{u.stateLabel}{u.since ? ` с ${u.since}` : ''}</span></td>
                  <td className="py-1 px-2 text-right font-mono">1 шт</td>
                  <td className="py-1 px-2 text-right font-mono tabular-nums">{u.amount == null
                    ? <span className="text-amber-700 dark:text-amber-400">нет стоимости</span> : money.format(u.amount)}</td>
                </tr>)}
              </Fragment>
            })}
          </tbody>
        </table>
      </div>}
    {!!w?.noCost && <p className="text-xs text-amber-700 dark:text-amber-400">
      У {w.noCost} ед. не указана стоимость — в сумме они идут нулём, сверка с бухгалтерией по сумме не сойдётся.</p>}
  </div>
}

/** Закрыть / открыть / удалить склад — с подтверждением, без браузерных окон. */
function WarehouseActions({ companyId, card, onClose }: { companyId: string; card: WarehouseCard; onClose: () => void }) {
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState<null | 'close' | 'delete'>(null)
  const [busy, setBusy] = useState(false)
  const closed = card.status === 'closed'
  const run = async (fn: () => Promise<unknown>, ok: string, done: boolean) => {
    setBusy(true)
    try { await fn(); await invalidateEquipment(qc); toast.success(ok); setConfirm(null); if (done) onClose() }
    catch (e) { toast.error('Не выполнено', { description: errText(e) }) }
    finally { setBusy(false) }
  }
  if (confirm) {
    return <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/40 p-3 text-sm">
      <span className="min-w-0 flex-1">{confirm === 'delete'
        ? `Удалить склад «${card.name}» насовсем? Удаляется только склад без единиц, остатков и истории движений.`
        : `Закрыть склад «${card.name}»? Он пропадёт из выбора в документах, история и отчёты останутся. Закрывается только пустой склад.`}</span>
      <Button size="sm" variant="outline" onClick={() => setConfirm(null)}>Отмена</Button>
      <Button size="sm" variant="destructive" disabled={busy} onClick={() => void (confirm === 'delete'
        ? run(() => deleteWarehouse(companyId, card.id), `Склад «${card.name}» удалён`, true)
        : run(() => setWarehouseClosed(companyId, card.id, true), `Склад «${card.name}» закрыт`, false))}>
        {busy && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}{confirm === 'delete' ? 'Удалить склад' : 'Закрыть склад'}</Button>
    </div>
  }
  return <div className="flex flex-wrap gap-2 border-t pt-3">
    {closed
      ? <Button size="sm" variant="outline" disabled={busy}
        onClick={() => void run(() => setWarehouseClosed(companyId, card.id, false), `Склад «${card.name}» снова открыт`, false)}>
        <LockOpen className="mr-1.5 h-4 w-4" />Открыть склад</Button>
      : <Button size="sm" variant="outline" onClick={() => setConfirm('close')}><Lock className="mr-1.5 h-4 w-4" />Закрыть склад</Button>}
    <Button size="sm" variant="outline" className="text-destructive" onClick={() => setConfirm('delete')}>
      <Trash2 className="mr-1.5 h-4 w-4" />Удалить склад</Button>
  </div>
}

export function WarehouseCardDialog({ companyId, warehouseId, onClose, initialTab = 'stock' }: {
  companyId: string; warehouseId: string; onClose: () => void; initialTab?: 'stock' | 'card'
}) {
  const [tab, setTab] = useState<'stock' | 'card'>(initialTab)
  const q = useQuery({ queryKey: ['equipment', 'warehouse-card', companyId, warehouseId], queryFn: () => getWarehouseCard(companyId, warehouseId) })
  const card = q.data
  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle className="flex flex-wrap items-center gap-2">{card?.name ?? 'Склад'}
          {card?.status === 'closed' && <Badge variant="outline" className="font-normal text-muted-foreground">закрыт</Badge>}</DialogTitle>
        {card && <p className="text-xs text-muted-foreground">
          {[card.ownershipLabel, card.counterpartyName, card.responsible && `МОЛ: ${card.responsible}`, card.address].filter(Boolean).join(' · ') || 'Реквизиты не заполнены'}</p>}
      </DialogHeader>
      <div role="tablist" aria-label="Разделы карточки склада" className="flex gap-1">
        {([['stock', 'Остатки'], ['card', 'Реквизиты']] as const).map(([k, l]) => (
          <button key={k} role="tab" type="button" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`min-h-8 rounded-md px-3 text-xs ${tab === k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}>{l}</button>
        ))}
      </div>
      {q.isError ? <p role="alert" className="text-sm">Карточка не загрузилась: {errText(q.error)}</p>
        : !card ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        : tab === 'stock' ? <WarehouseBalance companyId={companyId} warehouseId={warehouseId} />
        : <Requisites key={card.id} companyId={companyId} card={card} onClose={onClose} />}
      {card && <WarehouseActions companyId={companyId} card={card} onClose={onClose} />}
    </DialogContent>
  </Dialog>
}
