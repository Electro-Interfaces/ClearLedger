/**
 * Станции договора: общий по компании, конкретные станции или не распределён.
 *
 * Одно поле и в окне «Охват договора», и в форме договора: договор аренды — к одной
 * станции, энергоснабжение — к нескольким, эквайринг — на всю компанию. Станции
 * ищутся по названию, номеру и адресу, сужаются регионом; найденные отмечаются
 * разом, отметки сохраняются при смене поиска. По умолчанию — только ЭЗС: склады и
 * офисы включаются флажком, договоры бывают и на них.
 */
import { useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { useLocations } from '@/hooks/useLocations'
import { locationRegion } from '@/services/locationService'
import type { ContractScopeType } from '@/types'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'

export interface ContractStationsValue { scopeType: ContractScopeType; locationIds: string[] }

export function ContractStationsField({ value, onChange }: { value: ContractStationsValue; onChange: (v: ContractStationsValue) => void }) {
  const all = useLocations()
  const [q, setQ] = useState('')
  const [region, setRegion] = useState('')
  const [allTypes, setAllTypes] = useState(false)
  const pool = useMemo(() => all.filter((l) => allTypes || l.type === 'ev_charging'), [all, allTypes])
  const regions = useMemo(() => [...new Set(pool.map((l) => locationRegion(l)).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru')), [pool])
  const found = useMemo(() => {
    const n = q.trim().toLocaleLowerCase('ru')
    return pool.filter((l) => (!region || locationRegion(l) === region)
      && (!n || `${l.name} ${l.code} ${l.address ?? ''}`.toLocaleLowerCase('ru').includes(n)))
  }, [pool, q, region])
  const picked = new Set(value.locationIds)
  const set = (ids: Set<string>) => onChange({ ...value, locationIds: [...ids] })
  const byId = new Map(all.map((l) => [l.id, l]))
  const outside = value.locationIds.filter((id) => !found.some((l) => l.id === id)).length

  return <div className="space-y-2">
    <select aria-label="Охват договора" className={selectClass} value={value.scopeType}
      onChange={(e) => onChange({ ...value, scopeType: e.target.value as ContractScopeType })}>
      <option value="locations">Конкретные станции</option>
      <option value="company">Общий по компании — все станции, включая будущие</option>
      <option value="unassigned">Не распределён</option>
    </select>
    {value.scopeType === 'company' && <p className="text-xs text-muted-foreground">Договор действует на все станции компании: эквайринг, ОФД, корпоративные условия.</p>}
    {value.scopeType === 'unassigned' && <p className="text-xs text-amber-700 dark:text-amber-400">Станции не указаны — договор попадёт в разбор качества как требующий распределения.</p>}
    {value.scopeType === 'locations' && <div className="space-y-2 rounded-md border p-2">
      <div className="grid gap-2 sm:grid-cols-[1fr_200px]">
        <Input aria-label="Поиск станции" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, название, адрес" className="h-9" />
        <select aria-label="Регион" className={selectClass} value={region} onChange={(e) => setRegion(e.target.value)}>
          <option value="">Все регионы</option>{regions.map((r) => <option key={r} value={r}>{r}</option>)}</select>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span>Найдено: {found.length}</span><span className="font-medium">Выбрано: {value.locationIds.length}{outside ? ` (вне поиска ${outside})` : ''}</span>
        <button type="button" className="underline min-h-8" onClick={() => set(new Set([...picked, ...found.map((l) => l.id)]))}>отметить найденные</button>
        <button type="button" className="underline min-h-8" onClick={() => { const n = new Set(picked); found.forEach((l) => n.delete(l.id)); set(n) }}>снять найденные</button>
        <label className="flex items-center gap-1 ml-auto"><input type="checkbox" checked={allTypes} onChange={(e) => setAllTypes(e.target.checked)} />не только ЭЗС</label>
      </div>
      <div className="max-h-60 overflow-y-auto space-y-0.5">
        {found.slice(0, 400).map((l) => <label key={l.id} className="flex items-center gap-2 text-sm py-1 px-1 rounded hover:bg-muted cursor-pointer">
          <input type="checkbox" checked={picked.has(l.id)} onChange={(e) => { const n = new Set(picked); e.target.checked ? n.add(l.id) : n.delete(l.id); set(n) }} />
          <span className="font-mono text-xs text-muted-foreground w-12 shrink-0">{l.code}</span>
          <span className="flex-1 min-w-0 truncate">{l.name}</span>
          <span className="hidden sm:inline text-xs text-muted-foreground truncate max-w-[40%]">{locationRegion(l)}</span>
        </label>)}
        {found.length > 400 && <p className="text-xs text-muted-foreground p-1">Показаны первые 400 — уточните поиск или регион.</p>}
      </div>
      {value.locationIds.length > 0 && <div className="flex flex-wrap gap-1">{value.locationIds.slice(0, 12).map((id) => <span key={id} className="text-xs rounded border px-1.5 py-0.5">{byId.get(id)?.name ?? id}</span>)}
        {value.locationIds.length > 12 && <span className="text-xs text-muted-foreground">и ещё {value.locationIds.length - 12}</span>}</div>}
    </div>}
  </div>
}

/** Срок договора: действует, истекает в течение 30 дней, истёк, закрыт, бессрочный. */
export function contractStatus(c: { validUntil?: string | null; isClosed?: boolean }): { label: string; cls: string } {
  if (c.isClosed) return { label: 'закрыт', cls: 'text-muted-foreground' }
  if (!c.validUntil) return { label: 'бессрочный', cls: 'text-muted-foreground' }
  const today = new Date().toISOString().slice(0, 10)
  const soon = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10)
  const v = c.validUntil.slice(0, 10)
  if (v < today) return { label: `истёк ${v}`, cls: 'text-red-600 dark:text-red-400' }
  if (v <= soon) return { label: `истекает ${v}`, cls: 'text-amber-700 dark:text-amber-400' }
  return { label: `до ${v}`, cls: 'text-emerald-700 dark:text-emerald-400' }
}
