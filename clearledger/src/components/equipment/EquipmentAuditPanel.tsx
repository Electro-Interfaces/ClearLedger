/**
 * «Разбор данных» складского учёта оборудования.
 *
 * Учёт пришёл разовым импортом 21.08.2026 и с тех пор не вёлся: склад не указан,
 * списанное без актов, работающие единицы на закрытых станциях, хранитель текстом.
 * Экран показывает каждую проблему списком, и закрывается она документом — с
 * номером, датой, автором и основанием, — а не тихой правкой базы.
 */
import { Fragment, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { loadLocations } from '@/services/locationService'
import { getEquipmentAudit, type AuditSection, type AuditUnit, type UnitOp } from '@/services/equipmentService'
import { MovementDocumentDialog } from './MovementDocumentDialog'
import { eqName } from './equipmentDocPrint'

type Action = { op: UnitOp; correctionMode?: 'place' | 'doc'; label: string; basis?: string }
const ACTIONS: Record<string, Action[]> = {
  stock_no_place: [{ op: 'correction', correctionMode: 'place', label: 'Указать склад', basis: 'Разбор данных: склад не был указан' }],
  terminal_no_doc: [{ op: 'correction', correctionMode: 'doc', label: 'Оформить акт задним числом', basis: 'Разбор данных: состояние было без документа' }],
  keeper_text: [{ op: 'transfer', label: 'Переместить на склад' }],
  repair_overdue: [{ op: 'from_repair', label: 'Принять из ремонта' }],
}

function UnitRows({ items, picked, setPicked, grouped }: { items: AuditUnit[]; picked: Set<string>; setPicked: (s: Set<string>) => void; grouped?: boolean }) {
  const groups = useMemo(() => {
    if (!grouped) return [['', items]] as [string, AuditUnit[]][]
    const m = new Map<string, AuditUnit[]>()
    for (const u of items) m.set(u.group || '—', [...(m.get(u.group || '—') ?? []), u])
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [items, grouped])
  const toggle = (ids: string[], on: boolean) => { const n = new Set(picked); for (const id of ids) on ? n.add(id) : n.delete(id); setPicked(n) }
  return <div className="overflow-x-auto"><table className="w-full text-xs">
    <thead><tr className="border-b text-muted-foreground text-left">
      <th className="w-8 p-2"><input type="checkbox" aria-label="Отметить все" checked={items.length > 0 && items.every((u) => picked.has(u.id))} onChange={(e) => toggle(items.map((u) => u.id), e.target.checked)} /></th>
      <th className="p-2 font-medium">Серийный №</th><th className="p-2 font-medium">Оборудование</th><th className="p-2 font-medium">Состояние</th>
      <th className="p-2 font-medium">Где</th><th className="p-2 font-medium">Хранитель / примечание</th></tr></thead>
    <tbody>{groups.map(([g, list]) => <Fragment key={g || 'all'}>
      {grouped && <tr key={`g-${g}`} className="bg-muted/30"><td className="p-2"><input type="checkbox" aria-label={`Отметить группу ${g}`} checked={list.every((u) => picked.has(u.id))} onChange={(e) => toggle(list.map((u) => u.id), e.target.checked)} /></td>
        <td colSpan={5} className="p-2 font-medium">{g} · {list.length}</td></tr>}
      {list.map((u) => <tr key={u.id} className="border-b border-border/30">
        <td className="p-2"><input type="checkbox" aria-label={`Отметить ${u.serialNumber ?? u.model ?? 'единицу'}`} checked={picked.has(u.id)} onChange={(e) => toggle([u.id], e.target.checked)} /></td>
        <td className="p-2 font-mono">{u.serialNumber ?? '—'}</td><td className="p-2">{eqName(u.vendor, u.model) || '—'}</td>
        <td className="p-2 whitespace-nowrap">{u.stateLabel}</td><td className="p-2">{u.location?.name ?? '—'}</td>
        <td className="p-2 text-muted-foreground">{u.due ? `срок ${u.due} · ${u.document}` : u.reason ?? u.keeper ?? ''}</td></tr>)}
    </Fragment>)}</tbody></table></div>
}

function Section({ companyId, s, warehouses, sites }: { companyId: string; s: AuditSection; warehouses: never[]; sites: never[] }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [action, setAction] = useState<Action | null>(null)
  const units = s.items as AuditUnit[]
  return <Card><CardContent className="p-0">
    <button type="button" className="flex w-full items-start gap-2 px-3 py-2 text-left min-h-11" onClick={() => setOpen(!open)} aria-expanded={open}>
      {open ? <ChevronDown className="h-4 w-4 mt-0.5 shrink-0" /> : <ChevronRight className="h-4 w-4 mt-0.5 shrink-0" />}
      <span className="flex-1"><span className="text-sm font-semibold">{s.title}</span><span className="block text-xs text-muted-foreground">{s.hint}</span></span>
      <span className={`font-mono text-sm ${s.count ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400'}`}>{s.count}</span>
    </button>
    {open && s.count > 0 && <div className="border-t p-3 space-y-2">
        <UnitRows items={units} picked={picked} setPicked={setPicked} grouped={s.key === 'keeper_text'} />
        {ACTIONS[s.key] && <div className="flex flex-wrap gap-2">{ACTIONS[s.key].map((a) =>
          <Button key={a.label} size="sm" variant={a === ACTIONS[s.key][0] ? 'default' : 'outline'} disabled={!picked.size} onClick={() => setAction(a)}>{a.label} ({picked.size})</Button>)}</div>}
        {!ACTIONS[s.key] && s.key === 'unconfirmed' && <p className="text-xs text-muted-foreground">Уточните данные у поставщика и поправьте карточку единицы в «Парке оборудования».</p>}
    </div>}
    {action && <MovementDocumentDialog companyId={companyId} units={units.filter((u) => picked.has(u.id)) as never} op={action.op}
      correctionMode={action.correctionMode} presetBasis={action.basis} warehouses={warehouses} sites={sites}
      onClose={() => setAction(null)} onDone={() => setPicked(new Set())} />}
  </CardContent></Card>
}

export function EquipmentAuditPanel({ companyId }: { companyId: string }) {
  const q = useQuery({ queryKey: ['equipment', 'audit', companyId], queryFn: () => getEquipmentAudit(companyId) })
  const locs = useQuery({ queryKey: ['equipment', 'locations', companyId], queryFn: () => loadLocations(companyId), staleTime: 60_000 })
  const warehouses = (locs.data ?? []).filter((l) => l.type === 'warehouse') as never[]
  const sites = (locs.data ?? []).filter((l) => l.type === 'ev_charging') as never[]
  if (!q.data) return <div className="p-4">{q.isError ? <p role="alert">Разбор не загрузился: {q.error instanceof Error ? q.error.message : ''}</p> : <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}</div>
  const total = q.data.sections.reduce((n, s) => n + s.count, 0)
  return <div className="p-4 space-y-3">
    <div>
      <h2 className="text-base font-semibold">Разбор данных</h2>
      <p className="text-sm text-muted-foreground">Единиц в учёте: {q.data.units}. Требует разбора: {total}. Без стоимости: {q.data.noCost} — стоимость приходит из документов поставки.
        Каждое исправление оформляется документом и попадает в «Движения».</p>
    </div>
    {q.data.sections.map((s) => <Section key={s.key} companyId={companyId} s={s} warehouses={warehouses} sites={sites} />)}
  </div>
}
