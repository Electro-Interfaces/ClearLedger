/**
 * «Движения» — журнал операций жизненного цикла единиц оборудования ЭЗС.
 *
 * Фильтры: период · операция · склад или станция · единица. Таблица: дата,
 * операция, единица, документ, откуда → куда (для внешних — контрагент), смена
 * состояния, основание, комментарий, автор. Строка открывает карточку единицы,
 * номер документа — сам документ. Выгрузка в Excel — весь отбор, не страница.
 */

import { useMemo, useState } from 'react'
import { SortTh } from '@/components/workspace/SortableTh'
import { useTableSort } from '@/hooks/useTableSort'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  listMovements, listUnits, UNIT_OP_META, type EquipmentMovement, type UnitOp,
} from '@/services/equipmentService'
import { loadLocations } from '@/services/locationService'
import { formatDate } from '@/lib/formatDate'
import { EquipmentDocCard, EquipmentDocumentsSection } from './EquipmentDocumentsSection'
import { UnitDetailsDialog } from './EquipmentFleetPanel'
import { ExportXlsxButton, LoadError, Pager } from './equipmentShared'
import { allPages } from './useEquipmentScope'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE_SIZE = 200

const OP_OPTS = Object.entries(UNIT_OP_META) as [UnitOp, { label: string }][]

/** Класс badge операции: нейтральный zinc; списание/возврат производителю — приглушённые red/amber. */
function opCls(op: UnitOp): string {
  if (op === 'write_off') return 'border-red-400/40 text-red-600/70 dark:text-red-400/70'
  if (op === 'to_vendor') return 'border-amber-400/40 text-amber-600/70 dark:text-amber-300/70'
  return 'border-zinc-600 text-zinc-500 dark:text-zinc-400'
}

/** Откуда/куда: сторона без склада и станции подставляет контрагента (поставщик/подрядчик). */
function moveEnds(m: EquipmentMovement): { from: string; to: string } {
  const to = m.toLocation?.name ?? m.counterparty ?? '—'
  const from = m.fromLocation?.name ?? (m.toLocation ? m.counterparty : null) ?? '—'
  return { from, to }
}

function stateStr(m: EquipmentMovement): string {
  if (!m.fromStateLabel && !m.toStateLabel) return '—'
  if (!m.fromStateLabel) return m.toStateLabel ?? '—'
  return `${m.fromStateLabel} → ${m.toStateLabel ?? '—'}`
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

type UnitPick = { id: string; label: string }

/**
 * Отбор по единице. Журнал на сервере отбирает по самой единице, поэтому серийный
 * номер сначала ищется в парке, а в журнал уходит найденная единица.
 */
function UnitFilter({ companyId, unit, onChange }: {
  companyId: string; unit: UnitPick | null; onChange: (u: UnitPick | null) => void
}) {
  const [text, setText] = useState('')
  const [term, setTerm] = useState('')
  const found = useQuery({
    queryKey: ['equipment', 'unit-search', companyId, term],
    queryFn: () => listUnits({ companyId, q: term, pageSize: 20 }),
    enabled: !!term,
  })
  if (unit) {
    return (
      <Button variant="outline" size="sm" className="h-8 text-xs" title="Снять отбор по единице"
        onClick={() => { onChange(null); setTerm('') }}>
        {unit.label}<X className="ml-1 h-3 w-3" />
      </Button>
    )
  }
  const items = found.data?.items ?? []
  return (
    <>
      <Input value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') setTerm(text.trim()) }}
        placeholder="Серийный или инв. № — Enter" className="h-8 w-[200px] text-xs" />
      {term && (found.isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
        : found.isError ? <span role="alert">поиск не удался</span>
        : items.length === 0 ? <span>не найдено</span>
        : (
          <select aria-label="Найденные единицы" className="h-8 max-w-[240px] rounded-md border bg-background px-2 text-xs" value=""
            onChange={(e) => {
              const u = items.find((x) => x.id === e.target.value)
              if (u) onChange({ id: u.id, label: u.serialNumber ?? u.inventoryNumber ?? u.model ?? 'единица' })
            }}>
            <option value="">Найдено {found.data?.total} — выберите</option>
            {items.map((u) => (
              <option key={u.id} value={u.id}>
                {[u.serialNumber, u.inventoryNumber ? `инв. ${u.inventoryNumber}` : '', u.vendor, u.model].filter(Boolean).join(' · ')}
              </option>
            ))}
          </select>
        ))}
    </>
  )
}

const FILTER_DEFAULTS = { op: 'all', locationId: 'all', dateFrom: '', dateTo: '', unit: null as UnitPick | null, page: 1 }

export function EquipmentMovementsPanel({ companyId }: { companyId: string }) {
  const [f, setF] = useState(FILTER_DEFAULTS)
  // Смена любого фильтра сбрасывает на первую страницу (page в p — переопределит).
  const patch = (p: Partial<typeof f>) => setF((s) => ({ ...s, page: 1, ...p }))
  const [unitId, setUnitId] = useState<string | null>(null)
  const [docId, setDocId] = useState<string | null>(null)

  const locationsQ = useQuery({
    queryKey: ['equipment', 'locations', companyId],
    queryFn: () => loadLocations(companyId),
    staleTime: 60_000,
  })
  const warehouses = useMemo(() => (locationsQ.data ?? []).filter((l) => l.type === 'warehouse' && l.status !== 'closed'), [locationsQ.data])
  const sites = useMemo(() => (locationsQ.data ?? []).filter((l) => l.type === 'ev_charging'), [locationsQ.data])
  const locOpts = useMemo(() => [
    ...warehouses.map((l) => ({ id: l.id, label: `${l.name} · склад` })),
    ...sites.map((l) => ({ id: l.id, label: `${l.name} · станция` })),
  ].sort((a, b) => a.label.localeCompare(b.label, 'ru')), [warehouses, sites])

  const params = {
    companyId,
    op: f.op === 'all' ? undefined : f.op,
    locationId: f.locationId === 'all' ? undefined : f.locationId,
    unitId: f.unit?.id,
    dateFrom: f.dateFrom || undefined,
    dateTo: f.dateTo || undefined,
  }
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['equipment', 'movements', companyId, f.op, f.locationId, f.unit?.id, f.dateFrom, f.dateTo, f.page],
    queryFn: () => listMovements({ ...params, page: f.page, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  const все = data?.items ?? []
  // Журнал движений смотрят и по дате, и по единице, и по станции: «что уехало
  // последним» и «куда делась вот эта станция» — разные вопросы.
  const сортировка = useMemo(() => ({
    date: (m: typeof все[number]) => m.occurredOn,
    op: (m: typeof все[number]) => m.opLabel ?? m.op,
    unit: (m: typeof все[number]) => m.unit?.serialNumber ?? m.unit?.inventoryNumber ?? null,
    doc: (m: typeof все[number]) => m.documentNumber ?? m.supplyNumber ?? null,
    route: (m: typeof все[number]) => m.toLocation?.name ?? m.fromLocation?.name ?? null,
    state: (m: typeof все[number]) => m.toStateLabel ?? m.toState,
    basis: (m: typeof все[number]) => m.basis,
    who: (m: typeof все[number]) => m.createdBy,
  }), [])
  const { rows: items, sort, toggle } = useTableSort(все, сортировка, { key: 'date', dir: 'desc' })
  const total = data?.total ?? 0

  const exportAll = async () => {
    const all = await allPages((page) => listMovements({ ...params, page, pageSize: 1000 }))
    return [{
      name: 'Движения',
      columns: ['Дата', 'Операция', 'Документ', 'Серийный №', 'Производитель', 'Модель', 'Инв. №',
        'Откуда', 'Куда', 'Контрагент', 'Из состояния', 'В состояние', 'Основание', 'Комментарий', 'Кто'],
      rows: all.map((m) => [
        m.occurredOn, m.opLabel, m.documentNumber ?? (m.supplyNumber ? `поставка № ${m.supplyNumber}` : null),
        m.unit?.serialNumber, m.unit?.vendor, m.unit?.model, m.unit?.inventoryNumber,
        m.fromLocation?.name, m.toLocation?.name, m.counterparty,
        m.fromStateLabel, m.toStateLabel, m.basis, m.comment, m.createdBy,
      ]),
    }]
  }

  return (
    <div className="space-y-4 p-4">
      <EquipmentDocumentsSection companyId={companyId} />
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground" data-export-ignore>
        <span className="text-sm font-semibold text-foreground">Журнал движений</span>
        <Field label="Период">
          <Input type="date" value={f.dateFrom} onChange={(e) => patch({ dateFrom: e.target.value })}
            className="h-8 w-[140px] text-xs" />
        </Field>
        <span>—</span>
        <Input type="date" aria-label="Период, по дату" value={f.dateTo} onChange={(e) => patch({ dateTo: e.target.value })}
          className="h-8 w-[140px] text-xs" />
        <Field label="Операция">
          <Select value={f.op} onValueChange={(v) => patch({ op: v })}>
            <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все операции</SelectItem>
              {OP_OPTS.map(([op, meta]) => (
                <SelectItem key={op} value={op} className="text-xs">{meta.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Склад / станция">
          <Select value={f.locationId} onValueChange={(v) => patch({ locationId: v })}>
            <SelectTrigger className="h-8 w-[230px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все склады и станции</SelectItem>
              {locOpts.map((l) => (
                <SelectItem key={l.id} value={l.id} className="text-xs">{l.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <span>Единица:</span>
        <UnitFilter companyId={companyId} unit={f.unit} onChange={(unit) => patch({ unit })} />
        <div className="ml-auto flex items-center gap-3">
          {total > 0 && <span className="tabular-nums">всего движений: {nf0.format(total)}</span>}
          <ExportXlsxButton title="Журнал движений оборудования" load={exportAll} />
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <LoadError what="журнал движений" error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Движений по заданному отбору нет.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <SortTh sortKey="date" sort={sort} onSort={toggle}>Дата</SortTh>
                  <SortTh sortKey="op" sort={sort} onSort={toggle}>Операция</SortTh>
                  <SortTh sortKey="unit" sort={sort} onSort={toggle}>Единица</SortTh>
                  <SortTh sortKey="doc" sort={sort} onSort={toggle}>Документ</SortTh>
                  <SortTh sortKey="route" sort={sort} onSort={toggle}>Откуда → Куда</SortTh>
                  <SortTh sortKey="state" sort={sort} onSort={toggle}>Состояние</SortTh>
                  <SortTh sortKey="basis" sort={sort} onSort={toggle}>Основание</SortTh>
                  <th className="p-2 text-left font-medium">Комментарий</th>
                  <SortTh sortKey="who" sort={sort} onSort={toggle}>Кто</SortTh>
                </tr>
              </thead>
              <tbody>
                {items.map((m) => {
                  const ends = moveEnds(m)
                  const unitSub = [
                    [m.unit?.vendor, m.unit?.model].filter(Boolean).join(' '),
                    m.unit?.inventoryNumber ? `инв. ${m.unit.inventoryNumber}` : '',
                  ].filter(Boolean).join(' · ')
                  return (
                    <tr key={m.id} className="cursor-pointer border-b border-border/30 hover:bg-muted/30"
                      title="Открыть карточку единицы" onClick={() => setUnitId(m.unitId)}>
                      <td className="p-2 font-mono whitespace-nowrap">{m.occurredOn ? formatDate(m.occurredOn) : '—'}</td>
                      <td className="p-2 whitespace-nowrap">
                        <Badge variant="outline" className={`text-[10px] font-normal ${opCls(m.op)}`}>
                          {m.opLabel}
                        </Badge>
                      </td>
                      <td className="p-2">
                        <div className="font-mono">{m.unit?.serialNumber ?? '—'}</div>
                        {unitSub && (
                          <div className="max-w-[200px] truncate text-[11px] text-muted-foreground" title={unitSub}>
                            {unitSub}
                          </div>
                        )}
                      </td>
                      <td className="p-2 font-mono whitespace-nowrap">
                        {m.documentId ? (
                          <button type="button" title="Открыть документ"
                            className="underline decoration-dotted underline-offset-2 hover:text-primary"
                            onClick={(e) => { e.stopPropagation(); setDocId(m.documentId ?? null) }}>
                            {m.documentNumber ?? 'документ'}
                          </button>
                        ) : m.supplyNumber ? `поставка № ${m.supplyNumber}` : <span className="text-muted-foreground/40">—</span>}
                      </td>
                      <td className="p-2">
                        <span>{ends.from}</span>
                        <span className="text-muted-foreground/50"> → </span>
                        <span>{ends.to}</span>
                      </td>
                      <td className="p-2 text-muted-foreground whitespace-nowrap">{stateStr(m)}</td>
                      <td className="p-2 max-w-[160px] truncate" title={m.basis ?? undefined}>
                        {m.basis ?? <span className="text-muted-foreground/40">—</span>}
                      </td>
                      <td className="p-2 max-w-[200px] truncate text-muted-foreground" title={m.comment ?? undefined}>
                        {m.comment ?? '—'}
                      </td>
                      <td className="p-2 text-muted-foreground whitespace-nowrap">{m.createdBy ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <Pager page={f.page} pages={Math.ceil(total / PAGE_SIZE)} onPage={(page) => setF((s) => ({ ...s, page }))} />

      {unitId && (
        <UnitDetailsDialog companyId={companyId} unitId={unitId}
          warehouses={warehouses} sites={sites} onClose={() => setUnitId(null)} />
      )}
      {docId && <EquipmentDocCard companyId={companyId} id={docId} onClose={() => setDocId(null)} />}
    </div>
  )
}
