/**
 * Реестр сессий в разрезе: таблица групп с итогами + раскрытие строки до
 * первички. Считает БД (см. services/charge_grouping.py) — 117 тыс. строк
 * реестра браузеру не свернуть.
 *
 * Строка итога отвечает «где просело», раскрытие — «что именно там произошло»:
 * визит со 189 попытками на 0 ₽ разбирается только построчно.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ChevronRight, ChevronDown, AlertTriangle, ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-react'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DualScrollX } from '@/components/common/DualScrollX'
import {
  getChargeGrouped, getChargeGroupDetail, fmtMoney,
  type ChargeGroupFilters, type ChargeGroupRow,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

const CHANNEL_RU: Record<string, string> = { USER: 'Приложение', RFID: 'Карта RFID', AUTO: 'Автостарт', ADMIN: 'ADMIN' }
const fmtDT = (s: string | null) => (s ? new Date(s).toLocaleString('ru-RU', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
}) : '—')

type SortKey = 'label' | 'sessions' | 'energy_kwh' | 'revenue' | 'avg_tariff' | 'avg_check' | 'avg_duration' | 'charged_pct'

export function ChargeGroupedView({ companyId, dateFrom, dateTo, groupBy, filters }: {
  companyId: string; dateFrom: string; dateTo: string; groupBy: string; filters: ChargeGroupFilters
}) {
  // Сортировка не задана → разрез сам выбирает осмысленную (время —
  // хронологически, визиты — от самых многопопыточных), см. DEFAULT_SORT.
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' } | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['charge-grouped', companyId, dateFrom, dateTo, groupBy, sort?.key, sort?.dir,
      filters.userType, filters.region, filters.connector, filters.result, filters.paid, filters.search],
    queryFn: () => getChargeGrouped({
      companyId, dateFrom, dateTo, groupBy,
      sort: sort?.key, sortDir: sort?.dir, ...filters,
    }),
  })

  const toggleSort = (k: SortKey) => setSort((s) =>
    s?.key === k ? { key: k, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: 'desc' })

  const Th = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => {
    const on = sort?.key === k
    const Ico = on ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    return (
      <TableHead className={right ? 'text-right' : ''}>
        <button onClick={() => toggleSort(k)}
          className={`group inline-flex items-center gap-1 hover:text-foreground ${right ? 'flex-row-reverse' : ''} ${on ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{label}</span>
          <Ico className={`h-3 w-3 shrink-0 ${on ? 'text-primary' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </TableHead>
    )
  }

  if (isLoading) return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (error || !data) return <div className="p-8 text-center text-sm text-muted-foreground">Не удалось построить разрез</div>
  if (data.groups.length === 0) return <div className="p-8 text-center text-sm text-muted-foreground">За период нет сессий</div>

  const t = data.totals
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground" data-export-ignore>
        <span>Разрез «{data.label}»: <b className="text-foreground">{nf0.format(t.groups)}</b> групп
          {' '}· <b className="text-foreground">{nf0.format(t.sessions)}</b> сессий</span>
        <span className="text-muted-foreground/70">строка раскрывается до сессий</span>
        {data.truncated && (
          <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            Показаны первые {nf0.format(data.shown)} групп из {nf0.format(t.groups)} — итог внизу полный
          </span>
        )}
      </div>

      <DualScrollX>
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <Th k="label" label={data.label} />
              <Th k="sessions" label="Сессий" right />
              <Th k="energy_kwh" label="Энергия, кВтч" right />
              <Th k="revenue" label="Выручка, ₽" right />
              <Th k="avg_tariff" label="₽/кВтч" right />
              <Th k="avg_check" label="Ср. чек, ₽" right />
              <Th k="avg_duration" label="Ср. длит., мин" right />
              <Th k="charged_pct" label="Зарядились" right />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.groups.map((g) => (
              <GroupRow key={g.key || '∅'} g={g} groupBy={groupBy}
                open={open === g.key} onToggle={() => setOpen(open === g.key ? null : g.key)}
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} filters={filters} />
            ))}
          </TableBody>
          <TableFooter>
            {/* Итог — по всей выборке, а не сумма показанных групп: при
                усечении списка сумма строк не сошлась бы с реестром. */}
            <TableRow>
              <TableCell className="font-medium">Итого{data.truncated ? ' (вся выборка)' : ''}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{nf0.format(t.sessions)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{nf0.format(t.energy_kwh)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{fmtMoney(t.revenue)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{nf2.format(t.avg_tariff)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{fmtMoney(t.avg_check)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">—</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">—</TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </DualScrollX>
    </div>
  )
}

function GroupRow({ g, groupBy, open, onToggle, companyId, dateFrom, dateTo, filters }: {
  g: ChargeGroupRow; groupBy: string; open: boolean; onToggle: () => void
  companyId: string; dateFrom: string; dateTo: string; filters: ChargeGroupFilters
}) {
  const detail = useQuery({
    queryKey: ['charge-group-detail', companyId, dateFrom, dateTo, groupBy, g.key,
      filters.userType, filters.region, filters.connector, filters.result, filters.paid, filters.search],
    queryFn: () => getChargeGroupDetail({ companyId, dateFrom, dateTo, groupBy, key: g.key, ...filters }),
    enabled: open,
  })

  return (
    <>
      <TableRow className="cursor-pointer hover:bg-muted/30" onClick={onToggle}>
        <TableCell className="font-medium">
          <span className="inline-flex items-center gap-1.5">
            {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
            <span className="truncate max-w-[320px]">{g.label}</span>
            {/* Для сети полезно знать охват: одна станция или сорок. */}
            {(groupBy === 'region' || groupBy === 'client' || groupBy === 'user') && g.stations > 1 && (
              <span className="text-[10px] text-muted-foreground">· {g.stations} ст.</span>
            )}
          </span>
        </TableCell>
        <TableCell className="text-right tabular-nums">{nf0.format(g.sessions)}</TableCell>
        <TableCell className="text-right tabular-nums text-muted-foreground">{nf1.format(g.energy_kwh)}</TableCell>
        <TableCell className="text-right tabular-nums">{fmtMoney(g.revenue)}</TableCell>
        <TableCell className="text-right tabular-nums text-muted-foreground">{nf2.format(g.avg_tariff)}</TableCell>
        <TableCell className="text-right tabular-nums text-muted-foreground">{fmtMoney(g.avg_check)}</TableCell>
        <TableCell className="text-right tabular-nums text-muted-foreground">{nf0.format(g.avg_duration)}</TableCell>
        <TableCell className={`text-right tabular-nums ${g.charged_pct < 50 ? 'text-amber-600/90 dark:text-amber-400/90' : 'text-muted-foreground'}`}>
          {nf1.format(g.charged_pct)}%
        </TableCell>
      </TableRow>

      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={8} className="bg-muted/20 p-0">
            {detail.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
            ) : !detail.data?.rows.length ? (
              <div className="py-4 text-center text-xs text-muted-foreground">Нет сессий</div>
            ) : (
              <div className="p-2">
                <table className="w-full text-[11px]">
                  <thead className="text-muted-foreground">
                    <tr className="border-b border-border/40">
                      <th className="p-1.5 text-left font-medium">Начало</th>
                      <th className="p-1.5 text-left font-medium">Станция</th>
                      <th className="p-1.5 text-left font-medium">Клиент / карта</th>
                      <th className="p-1.5 text-left font-medium">Канал</th>
                      <th className="p-1.5 text-right font-medium">кВтч</th>
                      <th className="p-1.5 text-right font-medium">Мин</th>
                      <th className="p-1.5 text-right font-medium">₽</th>
                      <th className="p-1.5 text-left font-medium">Исход</th>
                      <th className="p-1.5 text-center font-medium">Оплата</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.data.rows.map((r) => (
                      <tr key={r.session_ext_id} className="border-b border-border/20 last:border-0">
                        <td className="p-1.5 font-mono">
                          {fmtDT(r.started_at)}
                          {/* Попытка N из M — видно, что это повтор внутри визита. */}
                          {r.visit_size != null && r.visit_size > 1 && (
                            <span className="ml-1 text-muted-foreground">· попытка {r.visit_seq}/{r.visit_size}</span>
                          )}
                        </td>
                        <td className="p-1.5">{r.station_name || r.station_code || '—'}</td>
                        <td className="p-1.5 text-muted-foreground">{r.client_name || r.user_id || '—'}</td>
                        <td className="p-1.5 text-muted-foreground">{r.charge_type ? (CHANNEL_RU[r.charge_type] ?? r.charge_type) : '—'}</td>
                        <td className="p-1.5 text-right tabular-nums">{nf1.format(r.energy_kwh)}</td>
                        <td className="p-1.5 text-right tabular-nums text-muted-foreground">{r.duration_min ?? '—'}</td>
                        <td className="p-1.5 text-right tabular-nums">{fmtMoney(r.revenue)}</td>
                        <td className={`p-1.5 ${r.result === 'Complete' ? 'text-muted-foreground' : 'text-amber-600/90 dark:text-amber-400/90'}`}>{r.result || '—'}</td>
                        <td className="p-1.5 text-center">{r.paid_at ? '✓' : '✗'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.data.rows.length >= 100 && (
                  <p className="px-1.5 pt-1.5 text-[10px] text-muted-foreground">Показаны первые 100 сессий группы</p>
                )}
              </div>
            )}
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
