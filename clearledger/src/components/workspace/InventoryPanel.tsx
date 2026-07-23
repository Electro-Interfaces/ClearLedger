/**
 * Инвентаризация резервуаров: ведомость корректировок книги на факт.
 *
 * Кнопка «Сформировать ведомость» берёт на дату по каждому резервуару книжный
 * остаток и фактический замер и считает корректировку = факт − книга (излишек к
 * оприходованию / недостача к списанию). Бухгалтер сверяет и проводит — книга
 * приводится к факту, накопленное расхождение на этот момент закрывается.
 *
 * Факт не выдумывается — берётся из уже сохранённого замера уровнемера. Строку
 * можно исключить из ведомости (не проводить по этому резервуару).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, Download, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import {
  getInventories, getInventoryDraft, saveInventory,
  type InventoryDraftRow, type InventoryGroup,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const L = (v: number | null | undefined) => (v == null ? '—' : `${nf0.format(v)} л`)

interface Props {
  companyId: string
  dateTo: string
  stationCodes: number[]
  fuelCodes: number[]
}

export function InventoryPanel({ companyId, dateTo, stationCodes, fuelCodes }: Props) {
  const qc = useQueryClient()
  const [date, setDate] = useState(dateTo)
  const [note, setNote] = useState('')
  const [draft, setDraft] = useState<InventoryDraftRow[] | null>(null)
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  const history = useQuery({
    queryKey: ['inventory-list', companyId, stationCodes.join(',')],
    queryFn: () => getInventories({ companyId, stationCodes }),
  })

  const draftMut = useMutation({
    mutationFn: () => getInventoryDraft({ date, stationCodes, fuelCodes }),
    onSuccess: (d) => { setDraft(d.rows); setExcluded(new Set()) },
    onError: () => toast.error('Не удалось сформировать ведомость'),
  })

  const saveMut = useMutation({
    mutationFn: (rows: InventoryDraftRow[]) => saveInventory({
      date,
      rows: rows.map((r) => ({
        station_id: r.station_id, tank_number: r.tank_number,
        fuel_code: r.fuel_code, fuel_name: r.fuel_name, shift_number: r.shift_number,
        book_volume: r.book_volume, fact_volume: r.fact_volume,
        book_mass: r.book_mass, fact_mass: r.fact_mass,
      })),
      note: note.trim() || undefined,
    }),
    onSuccess: (res) => {
      toast.success(`Инвентаризация проведена: ${res.saved} резервуаров, книга приведена к факту`)
      setDraft(null)
      qc.invalidateQueries({ queryKey: ['inventory-list'] })
      qc.invalidateQueries({ queryKey: ['tank-ledger'] })
      qc.invalidateQueries({ queryKey: ['variance-diagnostics'] })
    },
    onError: () => toast.error('Не удалось провести инвентаризацию'),
  })

  const key = (r: InventoryDraftRow) => `${r.station_code}:${r.tank_number}`
  const activeRows = useMemo(
    () => (draft ?? []).filter((r) => !excluded.has(key(r))),
    [draft, excluded],
  )
  const draftTotal = activeRows.reduce((s, r) => s + r.adjustment_volume, 0)

  return (
    <div className="space-y-4">
      {/* Панель формирования ведомости */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3">
        <div>
          <div className="mb-1 text-[11px] text-muted-foreground">Дата инвентаризации</div>
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                 className="h-8 w-[150px] text-xs" />
        </div>
        <Button size="sm" className="h-8" onClick={() => draftMut.mutate()} disabled={draftMut.isPending}>
          {draftMut.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <ClipboardCheck className="mr-1.5 h-3.5 w-3.5" />}
          Сформировать ведомость
        </Button>
        <p className="text-[11px] text-muted-foreground">
          По контуру ({stationCodes.length ? `${stationCodes.length} АЗС` : 'вся сеть'}) на выбранную дату.
          Корректировка = факт − книга.
        </p>
      </div>

      {/* Черновик ведомости */}
      {draft && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm font-semibold">
              Ведомость на {new Date(date).toLocaleDateString('ru-RU')}: {activeRows.length} резервуаров
              <span className={cn('ml-2 text-xs font-medium',
                draftTotal > 0.5 ? 'text-red-600 dark:text-red-400'
                  : draftTotal < -0.5 ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground')}>
                итог: {draftTotal >= 0 ? '+' : ''}{nf0.format(draftTotal)} л
                {' '}({draftTotal > 0.5 ? 'к оприходованию' : draftTotal < -0.5 ? 'к списанию' : 'сходится'})
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Input value={note} onChange={(e) => setNote(e.target.value)}
                     placeholder="Комментарий (необязательно)" className="h-8 w-[240px] text-xs" />
              <Button variant="outline" size="sm" className="h-8"
                      onClick={() => exportDraftXlsx(activeRows, date)} disabled={activeRows.length === 0}>
                <Download className="mr-1.5 h-3.5 w-3.5" />Экспорт в Excel
              </Button>
              <Button size="sm" className="h-8" onClick={() => saveMut.mutate(activeRows)}
                      disabled={saveMut.isPending || activeRows.length === 0}>
                {saveMut.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <ClipboardCheck className="mr-1.5 h-3.5 w-3.5" />}
                Провести инвентаризацию
              </Button>
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[900px] text-xs">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <Th></Th><Th>АЗС</Th><Th>Рез.</Th><Th>Топливо</Th><Th>Смена</Th>
                  <Th right>Книга, л</Th><Th right>Факт, л</Th><Th right>Корректировка</Th>
                  <Th right>Масса корр., кг</Th><Th></Th>
                </tr>
              </thead>
              <tbody>
                {draft.map((r) => {
                  const k = key(r)
                  const off = excluded.has(k)
                  return (
                    <tr key={k} className={cn('border-t', off && 'opacity-40')}>
                      <Td>
                        <Checkbox checked={!off} onCheckedChange={(v) => {
                          setExcluded((prev) => {
                            const n = new Set(prev)
                            if (v) n.delete(k); else n.add(k)
                            return n
                          })
                        }} />
                      </Td>
                      <Td>{r.station_name}</Td>
                      <Td>№{r.tank_number}</Td>
                      <Td>{r.fuel_name}</Td>
                      <Td>№{r.shift_number}</Td>
                      <Td right>{nf1.format(r.book_volume)}</Td>
                      <Td right>{nf1.format(r.fact_volume)}</Td>
                      <Td right className={cn('font-medium',
                        r.adjustment_volume > 0.05 ? 'text-red-600 dark:text-red-400'
                          : r.adjustment_volume < -0.05 ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground')}>
                        {r.adjustment_volume >= 0 ? '+' : ''}{nf1.format(r.adjustment_volume)} л
                        <span className="ml-1 text-[10px] text-muted-foreground">{r.kind}</span>
                      </Td>
                      <Td right className="text-muted-foreground">
                        {r.adjustment_mass != null ? `${r.adjustment_mass >= 0 ? '+' : ''}${nf1.format(r.adjustment_mass)}` : '—'}
                      </Td>
                      <Td>{r.already_confirmed && <span className="text-[10px] text-emerald-600 dark:text-emerald-400">уже проведена</span>}</Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Плюс — излишек (в баке больше книги, к оприходованию), минус — недостача
            (к списанию). Снимите галочку, чтобы не проводить по резервуару. После
            проведения книга приравнивается к факту — расхождение на дату закрывается.
          </p>
        </div>
      )}

      {/* История проведённых инвентаризаций */}
      <div>
        <div className="mb-2 text-sm font-semibold">Проведённые инвентаризации</div>
        {history.isLoading ? (
          <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />Загрузка…
          </div>
        ) : (history.data?.inventories.length ?? 0) === 0 ? (
          <div className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
            Инвентаризаций ещё не проводилось
          </div>
        ) : (
          <div className="space-y-2">
            {history.data!.inventories.map((g) => (
              <div key={g.inventory_date} className="rounded-lg border">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
                  <span className="text-sm font-medium">
                    {new Date(g.inventory_date).toLocaleDateString('ru-RU')}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {g.tanks} рез. · {g.surplus_tanks} излишков · {g.shortfall_tanks} недостач
                    </span>
                  </span>
                  <span className="flex items-center gap-3">
                    <span className={cn('text-xs font-medium',
                      g.adjustment_volume > 0.5 ? 'text-red-600 dark:text-red-400'
                        : g.adjustment_volume < -0.5 ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground')}>
                      итог {g.adjustment_volume >= 0 ? '+' : ''}{nf0.format(g.adjustment_volume)} л
                    </span>
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => exportGroupXlsx(g)}>
                      <Download className="mr-1 h-3.5 w-3.5" />Excel
                    </Button>
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[700px] text-xs">
                    <thead className="text-muted-foreground">
                      <tr><Th>АЗС</Th><Th>Рез.</Th><Th>Топливо</Th><Th right>Книга</Th><Th right>Факт</Th><Th right>Корректировка</Th></tr>
                    </thead>
                    <tbody>
                      {g.rows.map((r, i) => (
                        <tr key={i} className="border-t">
                          <Td>{r.station_name}</Td><Td>№{r.tank_number}</Td><Td>{r.fuel_name}</Td>
                          <Td right>{L(r.book_volume)}</Td><Td right>{L(r.fact_volume)}</Td>
                          <Td right className={cn('font-medium',
                            r.adjustment_volume > 0.05 ? 'text-red-600 dark:text-red-400'
                              : r.adjustment_volume < -0.05 ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground')}>
                            {r.adjustment_volume >= 0 ? '+' : ''}{nf1.format(r.adjustment_volume)} л
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** Выгрузка ведомости-черновика (перед проведением). */
async function exportDraftXlsx(rows: InventoryDraftRow[], date: string) {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()
  const data = rows.map((r) => ({
    'АЗС': r.station_name,
    'Резервуар': r.tank_number,
    'Топливо': r.fuel_name,
    'Смена': r.shift_number,
    'Книга, л': r.book_volume,
    'Факт, л': r.fact_volume,
    'Корректировка, л': r.adjustment_volume,
    'Вид': r.kind,
    'Книга, кг': r.book_mass ?? '',
    'Факт, кг': r.fact_mass ?? '',
    'Корректировка, кг': r.adjustment_mass ?? '',
  }))
  const ws = XLSX.utils.json_to_sheet(data)
  ws['!cols'] = [{ wch: 12 }, { wch: 9 }, { wch: 8 }, { wch: 8 }, ...Array(7).fill({ wch: 14 })]
  XLSX.utils.book_append_sheet(wb, ws, 'Ведомость инвентаризации')
  XLSX.writeFile(wb, `vedomost_inventarizacii_${date}.xlsx`)
}

/** Выгрузка проведённой инвентаризации из истории. */
async function exportGroupXlsx(g: InventoryGroup) {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()
  const data = g.rows.map((r) => ({
    'АЗС': r.station_name,
    'Резервуар': r.tank_number,
    'Топливо': r.fuel_name ?? '',
    'Книга, л': r.book_volume,
    'Факт, л': r.fact_volume,
    'Корректировка, л': r.adjustment_volume,
    'Вид': r.adjustment_volume > 0.05 ? 'излишек' : r.adjustment_volume < -0.05 ? 'недостача' : 'сходится',
    'Комментарий': r.note ?? '',
  }))
  const ws = XLSX.utils.json_to_sheet(data)
  ws['!cols'] = [{ wch: 12 }, { wch: 9 }, { wch: 8 }, { wch: 12 }, { wch: 12 }, { wch: 16 }, { wch: 11 }, { wch: 24 }]
  XLSX.utils.book_append_sheet(wb, ws, 'Инвентаризация')
  XLSX.writeFile(wb, `inventarizaciya_${g.inventory_date}.xlsx`)
}

function Th({ children, right }: { children?: React.ReactNode; right?: boolean }) {
  return <th className={cn('p-2.5 font-medium', right ? 'text-right' : 'text-left')}>{children}</th>
}

function Td({ children, right, className }: {
  children: React.ReactNode; right?: boolean; className?: string
}) {
  return <td className={cn('p-2.5', right ? 'text-right tabular-nums' : '', className)}>{children}</td>
}
