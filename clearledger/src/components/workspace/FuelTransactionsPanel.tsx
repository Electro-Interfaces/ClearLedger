/**
 * Раздел «Операции» — реестр наливов + KPI-карточки (по видам топлива и способам
 * оплаты, кликабельные фильтры) + «Итого» + модалка деталей операции.
 * Перенос функционала «Операции» из TradeFrame («Монитор») на данные Ledger
 * (fuel_transactions). Серверная пагинация/фильтры/сортировка (сотни тысяч строк).
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery, keepPreviousData, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, ArrowUp, ArrowDown, ArrowUpDown, Download, Search, X,
  ChevronLeft, ChevronRight, RefreshCw, Activity,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { FuelBadge } from '@/components/common/FuelBadge'
import { fmtMoney, fmtLiters } from '@/services/analyticsService'
import {
  getFuelTxRows, getFuelTxFilters, getFuelTxOverview, syncFuelTransactions, getFuelTxSyncStatus,
  type FuelTxRow,
} from '@/services/fuel/fuelMappingService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const ALL = '__all__'
const PAGE = 100

function fmtDt(s: string | null): string {
  if (!s) return '—'
  return new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}
const cleanCard = (c: string | null) => (c ? c.replace(/^0+/, '') || c : '—')

type SortKey = 'dt' | 'station' | 'fuel' | 'pay_type' | 'liters' | 'price' | 'amount'

function SortHead({ label, k, sort, order, onSort, right }: {
  label: string; k: SortKey; sort: SortKey; order: 'asc' | 'desc'; onSort: (k: SortKey) => void; right?: boolean
}) {
  const active = sort === k
  const Icon = !active ? ArrowUpDown : order === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={`p-2 font-medium ${right ? 'text-right' : 'text-left'}`}>
      <button type="button" onClick={() => onSort(k)}
        className={`group inline-flex items-center gap-1 ${right ? 'flex-row-reverse' : ''} ${active ? 'text-primary' : 'hover:text-foreground'}`}>
        <Icon className={`h-3 w-3 ${active ? 'text-primary' : 'opacity-30 group-hover:opacity-70'}`} />{label}
      </button>
    </th>
  )
}

/** Кликабельная KPI-плитка (вид топлива / способ оплаты) — фильтрует список. */
function KpiTile({ title, badge, count, volume, amount, selected, onClick }: {
  title?: string; badge?: ReactNode; count: number; volume: number; amount: number; selected: boolean; onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick}
      className={`rounded-lg border p-2.5 text-left transition-all ${selected ? 'border-primary border-2 bg-primary/5 shadow-sm' : 'border-border bg-card hover:bg-muted/40'}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {badge ?? <span className="block truncate text-xs font-medium text-foreground">{title}</span>}
          <div className="mt-1 flex items-center gap-1"><Activity className="h-3 w-3 text-muted-foreground" /><span className="text-xs tabular-nums text-foreground/80">{nf0.format(count)}</span></div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[11px] font-semibold tabular-nums">{fmtLiters(volume)}</div>
          <div className="text-[11px] font-semibold tabular-nums">{fmtMoney(amount)} ₽</div>
        </div>
      </div>
    </button>
  )
}

export function FuelTransactionsPanel({ dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const qc = useQueryClient()
  const [station, setStation] = useState<string>(ALL)
  const [fuelCodes, setFuelCodes] = useState<Set<number>>(new Set())
  const [payTypes, setPayTypes] = useState<Set<string>>(new Set())
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('dt')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [detail, setDetail] = useState<FuelTxRow | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => clearTimeout(t)
  }, [searchInput])
  useEffect(() => { setPage(0) }, [station, fuelCodes, payTypes, search, sort, order, dateFrom, dateTo])

  // статус фоновой загрузки наливов
  const syncStatus = useQuery({
    queryKey: ['fuel-tx-sync-status'], queryFn: getFuelTxSyncStatus,
    enabled: syncing, refetchInterval: syncing ? 2500 : false,
  })
  useEffect(() => {
    if (syncing && syncStatus.data && !syncStatus.data.running) {
      setSyncing(false)
      qc.invalidateQueries({ queryKey: ['fuel-tx-rows'] })
      qc.invalidateQueries({ queryKey: ['fuel-tx-overview'] })
      qc.invalidateQueries({ queryKey: ['fuel-tx-filters'] })
      qc.invalidateQueries({ queryKey: ['fuel-overview'] })
      qc.invalidateQueries({ queryKey: ['fuel-map'] })
    }
  }, [syncing, syncStatus.data, qc])
  async function loadTx() {
    await syncFuelTransactions({ date_from: dateFrom, date_to: dateTo })
    setSyncing(true)
  }

  const filtersQ = useQuery({
    queryKey: ['fuel-tx-filters', dateFrom, dateTo],
    queryFn: () => getFuelTxFilters(dateFrom, dateTo),
  })
  const stationCode = station === ALL ? undefined : Number(station)
  const overviewQ = useQuery({
    queryKey: ['fuel-tx-overview', dateFrom, dateTo, station],
    queryFn: () => getFuelTxOverview(dateFrom, dateTo, stationCode),
  })

  const params = useMemo(() => ({
    dateFrom, dateTo, stationCode,
    fuelCodes: fuelCodes.size ? [...fuelCodes] : undefined,
    payTypes: payTypes.size ? [...payTypes] : undefined,
    search: search || undefined, sort, order,
  }), [dateFrom, dateTo, stationCode, fuelCodes, payTypes, search, sort, order])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['fuel-tx-rows', params, page],
    queryFn: () => getFuelTxRows({ ...params, limit: PAGE, offset: page * PAGE }),
    placeholderData: keepPreviousData,
  })

  const onSort = (k: SortKey) => {
    if (k === sort) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else { setSort(k); setOrder('desc') }
  }
  const toggleFuel = (c: number) => setFuelCodes((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n })
  const togglePay = (p: string) => setPayTypes((s) => { const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p); return n })
  const resetKpi = () => { setFuelCodes(new Set()); setPayTypes(new Set()) }
  const resetAll = () => { setStation(ALL); resetKpi(); setSearchInput(''); setSearch('') }
  const hasFilters = station !== ALL || fuelCodes.size > 0 || payTypes.size > 0 || !!search

  const ov = overviewQ.data
  const total = data?.total ?? 0
  const totals = data?.totals
  const rows = data?.rows ?? []
  const pages = Math.max(1, Math.ceil(total / PAGE))
  const from = total === 0 ? 0 : page * PAGE + 1
  const to = Math.min(total, (page + 1) * PAGE)

  async function exportXlsx() {
    setExporting(true)
    try {
      const CAP = 50000
      const res = await getFuelTxRows({ ...params, limit: 1000, offset: 0 })
      const all: FuelTxRow[] = [...res.rows]
      while (all.length < Math.min(res.total, CAP)) {
        const chunk = await getFuelTxRows({ ...params, limit: 1000, offset: all.length })
        if (chunk.rows.length === 0) break
        all.push(...chunk.rows)
      }
      const XLSX = await import('xlsx')
      const sheet = all.map((r) => ({
        'Дата/время': fmtDt(r.dt), 'АЗС': r.station_name, 'Смена': r.shift_number ?? '',
        'ТРК': r.pos ?? '', 'Пистолет': r.nozzle ?? '', 'Топливо': r.fuel_name ?? '',
        'Оплата': r.pay_type_name ?? '', 'Карта': r.card ?? '',
        'Литры': r.liters, 'Цена, ₽/л': r.price ?? '', 'Сумма, ₽': r.amount,
      }))
      const ws = XLSX.utils.json_to_sheet(sheet)
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, ws, 'Операции')
      XLSX.writeFile(wb, `operacii_${dateFrom}_${dateTo}.xlsx`)
    } finally { setExporting(false) }
  }

  return (
    <div className="space-y-3 p-4">
      {/* шапка */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">Операции</h2>
          {syncing && syncStatus.data && (
            <span className="text-xs text-muted-foreground">{syncStatus.data.message} · {nf0.format(syncStatus.data.loaded)}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8" onClick={loadTx} disabled={syncing} title="Загрузить наливы из STS за период раздела">
            {syncing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}Загрузить наливы
          </Button>
          <Button variant="outline" size="sm" className="h-8" onClick={exportXlsx} disabled={exporting || total === 0}>
            {exporting ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1.5 h-3.5 w-3.5" />}Экспорт{total > 50000 ? ' (до 50к)' : ''}
          </Button>
        </div>
      </div>

      {/* фильтры: АЗС + поиск карты + сброс */}
      <div className="flex flex-wrap items-center gap-2">
        <Select value={station} onValueChange={setStation}>
          <SelectTrigger className="h-8 w-[160px] text-xs"><SelectValue placeholder="АЗС" /></SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Все АЗС</SelectItem>
            {(filtersQ.data?.stations ?? []).map((s) => <SelectItem key={s.code} value={String(s.code)}>{s.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Номер карты…" className="h-8 w-[170px] pl-7 text-xs" />
        </div>
        {hasFilters && <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={resetAll}><X className="mr-1 h-3.5 w-3.5" />Сбросить</Button>}
        <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">{isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin" />}</div>
      </div>

      {/* KPI по видам топлива */}
      {ov && ov.by_fuel.length > 0 && (
        <div className="space-y-1.5">
          <div className="px-1 text-xs font-medium text-foreground/80">Виды топлива <span className="text-muted-foreground">— клик фильтрует список</span></div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {ov.by_fuel.map((f) => (
              <KpiTile key={f.fuel_code ?? f.fuel_name} badge={<FuelBadge fuel={f.fuel_name} />}
                count={f.count} volume={f.liters} amount={f.amount}
                selected={f.fuel_code != null && fuelCodes.has(f.fuel_code)}
                onClick={() => f.fuel_code != null && toggleFuel(f.fuel_code)} />
            ))}
          </div>
        </div>
      )}

      {/* KPI по способам оплаты */}
      {ov && ov.by_payment.length > 0 && (
        <div className="space-y-1.5">
          <div className="px-1 text-xs font-medium text-foreground/80">Способы оплаты <span className="text-muted-foreground">— клик фильтрует список</span></div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {ov.by_payment.map((p) => (
              <KpiTile key={p.name} title={p.name} count={p.count} volume={p.liters} amount={p.amount}
                selected={payTypes.has(p.name)} onClick={() => togglePay(p.name)} />
            ))}
          </div>
        </div>
      )}

      {/* Итого */}
      {ov && (
        <Card className={`${(fuelCodes.size || payTypes.size) ? 'cursor-pointer border-primary/50' : ''}`} onClick={(fuelCodes.size || payTypes.size) ? resetKpi : undefined}>
          <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-2 py-3">
            <div className="flex items-center gap-2"><span className="text-sm font-semibold">Итого за период</span>
              {(fuelCodes.size || payTypes.size) ? <span className="text-[11px] text-primary">(сброс фильтра)</span> : null}</div>
            <div className="flex items-center gap-1.5 text-sm"><Activity className="h-3.5 w-3.5 text-muted-foreground" /><span className="text-muted-foreground">Наливов</span><b className="tabular-nums">{nf0.format(ov.kpi.count)}</b></div>
            <div className="text-sm"><span className="text-muted-foreground">Объём </span><b className="tabular-nums">{fmtLiters(ov.kpi.liters)}</b></div>
            <div className="text-sm"><span className="text-muted-foreground">Выручка </span><b className="tabular-nums">{fmtMoney(ov.kpi.amount)} ₽</b></div>
            {totals && (fuelCodes.size || payTypes.size || search || station !== ALL) ? (
              <div className="ml-auto text-xs text-muted-foreground">по фильтру: {nf0.format(totals.count)} · {fmtLiters(totals.liters)} · {fmtMoney(totals.amount)} ₽</div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {/* таблица */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : total === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">Нет операций по фильтру за период</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/40 text-muted-foreground">
                    <SortHead label="Дата/время" k="dt" sort={sort} order={order} onSort={onSort} />
                    <SortHead label="АЗС" k="station" sort={sort} order={order} onSort={onSort} />
                    <SortHead label="Топливо" k="fuel" sort={sort} order={order} onSort={onSort} />
                    <SortHead label="Оплата" k="pay_type" sort={sort} order={order} onSort={onSort} />
                    <th className="p-2 text-left font-medium">Карта</th>
                    <SortHead label="Литры" k="liters" sort={sort} order={order} onSort={onSort} right />
                    <SortHead label="₽/л" k="price" sort={sort} order={order} onSort={onSort} right />
                    <SortHead label="Сумма" k="amount" sort={sort} order={order} onSort={onSort} right />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="cursor-pointer border-b border-border/30 hover:bg-muted/30" onClick={() => setDetail(r)}>
                      <td className="whitespace-nowrap p-2 font-mono text-muted-foreground">{fmtDt(r.dt)}</td>
                      <td className="max-w-[160px] truncate p-2">{r.station_name}</td>
                      <td className="p-2">{r.fuel_name ? <FuelBadge fuel={r.fuel_name} /> : '—'}</td>
                      <td className="max-w-[140px] truncate p-2">{r.pay_type_name ?? '—'}</td>
                      <td className="p-2 font-mono text-muted-foreground">{cleanCard(r.card)}</td>
                      <td className="p-2 text-right font-mono">{nf2.format(r.liters)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{r.price != null ? nf2.format(r.price) : '—'}</td>
                      <td className="p-2 text-right font-mono">{fmtMoney(r.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* пагинация */}
      {total > 0 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{nf0.format(from)}–{nf0.format(to)} из {nf0.format(total)}</span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}><ChevronLeft className="h-4 w-4" /></Button>
            <span className="px-2 tabular-nums">{page + 1} / {nf0.format(pages)}</span>
            <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}

      {/* модалка деталей операции */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Операция (налив)</DialogTitle>
            <DialogDescription>{detail?.station_name}{detail?.dt ? ` · ${fmtDt(detail.dt)}` : ''}</DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="grid grid-cols-1 gap-0 text-sm">
              {([
                ['Вид топлива', detail.fuel_name ?? '—'],
                ['Количество', `${nf2.format(detail.liters)} л`],
                ['Цена за литр', detail.price != null ? `${nf2.format(detail.price)} ₽/л` : '—'],
                ['Сумма', `${fmtMoney(detail.amount)} ₽`],
                ['Способ оплаты', detail.pay_type_name ?? '—'],
                ['Карта', detail.card ?? '—'],
                ['АЗС', detail.station_name],
                ['Смена', detail.shift_number ?? '—'],
                ['ТРК (POS)', detail.pos ?? '—'],
                ['Пистолет', detail.nozzle ?? '—'],
                ['Резервуар', detail.tank ?? '—'],
                ['ID операции (STS)', detail.id],
              ] as [string, ReactNode][]).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-b border-border/60 py-1.5">
                  <span className="text-muted-foreground">{k}:</span>
                  <span className="text-right font-mono">{v}</span>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
