/**
 * «Движения» — журнал операций жизненного цикла единиц оборудования ЭЗС.
 *
 * Фильтры: период · операция · склад/локация. Таблица: дата, операция,
 * единица, откуда → куда (для внешних — контрагент), смена состояния,
 * основание, комментарий, автор. Пагинация по 200 строк + скрытая
 * экспорт-таблица с сырыми данными (паттерн exportRows из FuelFillsPanel).
 */

import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  listMovements, UNIT_OP_META, type EquipmentMovement, type UnitOp,
} from '@/services/equipmentService'
import { loadLocations } from '@/services/locationService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const PAGE_SIZE = 200

const OP_OPTS = Object.entries(UNIT_OP_META) as [UnitOp, { label: string }][]

/** Класс badge операции: нейтральный zinc; списание/возврат производителю — приглушённые red/amber. */
function opCls(op: UnitOp): string {
  if (op === 'write_off') return 'border-red-400/40 text-red-600/70 dark:text-red-400/70'
  if (op === 'to_vendor') return 'border-amber-400/40 text-amber-600/70 dark:text-amber-300/70'
  return 'border-zinc-600 text-zinc-500 dark:text-zinc-400'
}

/** Откуда/куда: сторона без локации подставляет контрагента (поставщик/подрядчик). */
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

const FILTER_DEFAULTS = { op: 'all', locationId: 'all', dateFrom: '', dateTo: '', page: 1 }

export function EquipmentMovementsPanel({ companyId }: { companyId: string }) {
  const [f, setF] = useState(FILTER_DEFAULTS)
  // Смена любого фильтра сбрасывает на первую страницу (page в p — переопределит).
  const patch = (p: Partial<typeof f>) => setF((s) => ({ ...s, page: 1, ...p }))

  const locationsQ = useQuery({
    queryKey: ['equipment-locations', companyId],
    queryFn: () => loadLocations(companyId),
  })
  const locOpts = useMemo(() => {
    const typeLabel: Record<string, string> = { warehouse: 'склад', ev_charging: 'ЭЗС' }
    return (locationsQ.data ?? [])
      .filter((l) => l.type === 'warehouse' || l.type === 'ev_charging')
      .sort((a, b) => (a.type === b.type
        ? a.name.localeCompare(b.name, 'ru')
        : a.type === 'warehouse' ? -1 : 1))
      .map((l) => ({ id: l.id, label: `${l.name} · ${typeLabel[l.type]}` }))
  }, [locationsQ.data])

  const { data, isLoading } = useQuery({
    queryKey: ['equipment-movements', companyId, f.op, f.locationId, f.dateFrom, f.dateTo, f.page],
    queryFn: () => listMovements({
      companyId,
      op: f.op === 'all' ? undefined : f.op,
      locationId: f.locationId === 'all' ? undefined : f.locationId,
      dateFrom: f.dateFrom || undefined,
      dateTo: f.dateTo || undefined,
      page: f.page,
      pageSize: PAGE_SIZE,
    }),
    placeholderData: keepPreviousData,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  // Сырые данные для выгрузки в Excel (скрытая таблица — паттерн exportRows).
  const exCols = ['Дата', 'Операция', 'Серийный №', 'Вендор', 'Модель', 'Инв. №',
    'Откуда', 'Куда', 'Контрагент', 'Из состояния', 'В состояние', 'Основание', 'Комментарий', 'Кто']
  const exRows: (string | number | null)[][] = items.map((m) => [
    m.occurredOn, m.opLabel, m.unit?.serialNumber ?? null, m.unit?.vendor ?? null,
    m.unit?.model ?? null, m.unit?.inventoryNumber ?? null,
    m.fromLocation?.name ?? null, m.toLocation?.name ?? null, m.counterparty,
    m.fromStateLabel, m.toStateLabel, m.basis, m.comment, m.createdBy,
  ])

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3" data-export-ignore>
        <Field label="Период">
          <Input type="date" value={f.dateFrom} onChange={(e) => patch({ dateFrom: e.target.value })}
            className="h-8 w-[140px] text-xs" />
        </Field>
        <span className="text-xs text-muted-foreground">—</span>
        <Input type="date" value={f.dateTo} onChange={(e) => patch({ dateTo: e.target.value })}
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
        <Field label="Локация">
          <Select value={f.locationId} onValueChange={(v) => patch({ locationId: v })}>
            <SelectTrigger className="h-8 w-[230px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все локации</SelectItem>
              {locOpts.map((l) => (
                <SelectItem key={l.id} value={l.id} className="text-xs">{l.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {total > 0 && (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            всего движений: {nf0.format(total)}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Движений за период нет.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-2 text-left font-medium whitespace-nowrap">Дата</th>
                  <th className="p-2 text-left font-medium">Операция</th>
                  <th className="p-2 text-left font-medium">Единица</th>
                  <th className="p-2 text-left font-medium">Откуда → Куда</th>
                  <th className="p-2 text-left font-medium">Состояние</th>
                  <th className="p-2 text-left font-medium">Основание</th>
                  <th className="p-2 text-left font-medium">Комментарий</th>
                  <th className="p-2 text-left font-medium">Кто</th>
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
                    <tr key={m.id} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-mono whitespace-nowrap">{m.occurredOn?.slice(0, 10)}</td>
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

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2" data-export-ignore>
          <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
            disabled={f.page <= 1}
            onClick={() => setF((s) => ({ ...s, page: s.page - 1 }))}>
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="text-xs text-muted-foreground tabular-nums">
            страница {f.page} из {totalPages}
          </span>
          <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
            disabled={f.page >= totalPages}
            onClick={() => setF((s) => ({ ...s, page: s.page + 1 }))}>
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {/* Скрытая таблица с сырыми данными — подхватывается экспортом в Excel. */}
      <table hidden aria-hidden
        data-export-name="Движения"
        data-export-rows={JSON.stringify({ columns: exCols, rows: exRows })} />
    </div>
  )
}
