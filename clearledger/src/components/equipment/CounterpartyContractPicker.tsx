/**
 * Контрагент и договор из справочников пространства — для документов оборудования.
 *
 * Раньше контрагент движения был свободным текстом, договор не выбирался вовсе: в
 * справочнике 79 договоров поставки ЭЗС, 99 подряда, 23 сервисных, а складской
 * учёт о них не знал. Здесь — поиск по имени и ИНН, договоры выбранного контрагента
 * с подходящими операции типами наверху, и заведение нового контрагента или
 * договора прямо из документа, без ухода в справочник.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createContract, createCounterparty, getContracts, getCounterparties, getOrganizations } from '@/services/referenceService'
import type { Contract } from '@/types'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const today = () => new Date().toISOString().slice(0, 10)

export interface CounterpartyContractValue { counterpartyId: string; contractId: string }

export function contractExpired(c?: Pick<Contract, 'validUntil'> | null) {
  return !!c?.validUntil && c.validUntil.slice(0, 10) < today()
}

export function CounterpartyContractPicker({ companyId, value, onChange, preferredTypes = [], required = false, label = 'Контрагент' }: {
  companyId: string
  value: CounterpartyContractValue
  onChange: (v: CounterpartyContractValue) => void
  /** Типы договоров, подходящие операции: показываются первыми. */
  preferredTypes?: string[]
  required?: boolean
  label?: string
}) {
  const qc = useQueryClient()
  const cps = useQuery({ queryKey: ['counterparties', companyId], queryFn: () => getCounterparties(companyId), staleTime: 60_000 })
  const contracts = useQuery({ queryKey: ['contracts', companyId], queryFn: () => getContracts(companyId), staleTime: 60_000 })
  const [q, setQ] = useState('')
  const [newCp, setNewCp] = useState<null | { name: string; inn: string }>(null)
  const [newContract, setNewContract] = useState<null | { number: string; date: string; type: string; validUntil: string }>(null)
  const [busy, setBusy] = useState(false)

  const selectedCp = cps.data?.find((c) => c.id === value.counterpartyId)
  const shown = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase('ru')
    const list = (cps.data ?? []).filter((c) => !needle || `${c.name} ${c.shortName ?? ''} ${c.inn}`.toLocaleLowerCase('ru').includes(needle))
    const top = list.slice(0, 200)
    return selectedCp && !top.some((c) => c.id === selectedCp.id) ? [selectedCp, ...top] : top
  }, [cps.data, q, selectedCp])
  const own = useMemo(() => (contracts.data ?? []).filter((c) => c.counterpartyId === value.counterpartyId && !c.isClosed)
    .sort((a, b) => Number(preferredTypes.includes(b.type)) - Number(preferredTypes.includes(a.type)) || (b.date || '').localeCompare(a.date || '')),
  [contracts.data, value.counterpartyId, preferredTypes])

  const saveCp = async () => {
    if (!newCp?.name.trim()) return toast.error('Укажите наименование')
    setBusy(true)
    try {
      const cp = await createCounterparty(companyId, { name: newCp.name.trim(), inn: newCp.inn.trim(), type: 'ЮЛ', aliases: [] } as never)
      await qc.invalidateQueries({ queryKey: ['counterparties', companyId] })
      onChange({ counterpartyId: cp.id, contractId: '' }); setNewCp(null); toast.success('Контрагент добавлен в справочник пространства')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось добавить контрагента') }
    finally { setBusy(false) }
  }
  const saveContract = async () => {
    if (!newContract?.number.trim() || !newContract.date) return toast.error('Укажите номер и дату договора')
    setBusy(true)
    try {
      const orgs = await getOrganizations(companyId)
      if (!orgs.length) throw new Error('В пространстве нет организации — договор не к кому привязать')
      const c = await createContract(companyId, {
        number: newContract.number.trim(), date: newContract.date, counterpartyId: value.counterpartyId,
        organizationId: orgs[0].id, type: newContract.type || preferredTypes[0] || 'Прочее',
        validUntil: newContract.validUntil || undefined,
      } as never)
      await qc.invalidateQueries({ queryKey: ['contracts', companyId] })
      onChange({ ...value, contractId: c.id }); setNewContract(null); toast.success('Договор добавлен в справочник пространства')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось добавить договор') }
    finally { setBusy(false) }
  }
  const chosen = own.find((c) => c.id === value.contractId)

  return <div className="space-y-2 rounded-md border p-2">
    <div className="grid gap-2 sm:grid-cols-[1fr_1fr]">
      <label className="text-xs">{label}{required ? ' *' : ''}
        <Input aria-label="Поиск контрагента" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по названию или ИНН" className="h-9 mb-1" />
        <select aria-label={label} className={selectClass} value={value.counterpartyId}
          onChange={(e) => onChange({ counterpartyId: e.target.value, contractId: '' })}>
          <option value="">{cps.isLoading ? 'Загрузка…' : 'Не выбран'}</option>
          {shown.map((c) => <option key={c.id} value={c.id}>{c.shortName || c.name}{c.inn ? ` · ИНН ${c.inn}` : ''}</option>)}
        </select>
      </label>
      <label className="text-xs">Договор
        <select aria-label="Договор" className={`${selectClass} sm:mt-10`} value={value.contractId} disabled={!value.counterpartyId}
          onChange={(e) => onChange({ ...value, contractId: e.target.value })}>
          <option value="">{value.counterpartyId ? (own.length ? 'Не выбран' : 'Договоров с контрагентом нет') : 'Сначала контрагент'}</option>
          {own.map((c) => <option key={c.id} value={c.id}>№ {c.number} от {c.date} · {c.type}{c.validUntil ? ` · до ${c.validUntil.slice(0, 10)}` : ''}{contractExpired(c) ? ' (истёк)' : ''}</option>)}
        </select>
      </label>
    </div>
    {chosen && contractExpired(chosen) && <p role="alert" className="text-xs text-amber-700 dark:text-amber-400">Срок договора истёк {chosen.validUntil?.slice(0, 10)} — документ проведётся, но договор стоит продлить</p>}
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="ghost" size="sm" onClick={() => setNewCp(newCp ? null : { name: q.trim(), inn: '' })}><Plus className="h-3.5 w-3.5 mr-1" />Новый контрагент</Button>
      <Button type="button" variant="ghost" size="sm" disabled={!value.counterpartyId} onClick={() => setNewContract(newContract ? null : { number: '', date: today(), type: preferredTypes[0] || '', validUntil: '' })}><Plus className="h-3.5 w-3.5 mr-1" />Новый договор</Button>
    </div>
    {newCp && <div className="grid gap-2 sm:grid-cols-[1fr_160px_auto] items-end rounded border border-dashed p-2">
      <label className="text-xs">Наименование<Input aria-label="Наименование нового контрагента" value={newCp.name} onChange={(e) => setNewCp({ ...newCp, name: e.target.value })} className="h-9" /></label>
      <label className="text-xs">ИНН<Input aria-label="ИНН нового контрагента" value={newCp.inn} onChange={(e) => setNewCp({ ...newCp, inn: e.target.value.replace(/\D/g, '').slice(0, 12) })} className="h-9" /></label>
      <Button type="button" size="sm" disabled={busy} onClick={() => void saveCp()}>Добавить</Button>
    </div>}
    {newContract && <div className="grid gap-2 sm:grid-cols-[1fr_140px_1fr_140px_auto] items-end rounded border border-dashed p-2">
      <label className="text-xs">Номер<Input aria-label="Номер нового договора" value={newContract.number} onChange={(e) => setNewContract({ ...newContract, number: e.target.value })} className="h-9" /></label>
      <label className="text-xs">Дата<Input aria-label="Дата нового договора" type="date" value={newContract.date} onChange={(e) => setNewContract({ ...newContract, date: e.target.value })} className="h-9" /></label>
      <label className="text-xs">Тип<Input aria-label="Тип нового договора" list="eq-contract-types" value={newContract.type} onChange={(e) => setNewContract({ ...newContract, type: e.target.value })} className="h-9" />
        <datalist id="eq-contract-types">{[...new Set([...preferredTypes, 'Поставка ЭЗС', 'Монтаж/Подряд', 'Сервисное обслуживание', 'Аренда', 'Ответственное хранение'])].map((t) => <option key={t} value={t} />)}</datalist></label>
      <label className="text-xs">Действует до<Input aria-label="Срок нового договора" type="date" value={newContract.validUntil} onChange={(e) => setNewContract({ ...newContract, validUntil: e.target.value })} className="h-9" /></label>
      <Button type="button" size="sm" disabled={busy} onClick={() => void saveContract()}>Добавить</Button>
    </div>}
  </div>
}
