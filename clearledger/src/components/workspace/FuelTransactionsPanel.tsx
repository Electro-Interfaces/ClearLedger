/**
 * Раздел «Операции» — реестр реализаций + KPI-карточки (по видам топлива и способам
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
import { cn } from '@/lib/utils'
import { fmtMoney, fmtLiters } from '@/services/analyticsService'
import { useResetOnScopeChange } from '@/hooks/useScopeReset'
import {
  getFuelTxRows, getFuelTxFilters, getFuelTxOverview, syncFuelTransactions, getFuelTxSyncStatus,
  type FuelTxRow,
} from '@/services/fuel/fuelMappingService'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'

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
    <th className={`px-3 py-2.5 font-medium ${right ? 'text-right' : 'text-left'}`}>
      <button type="button" onClick={() => onSort(k)}
        className={`group inline-flex items-center gap-1 ${right ? 'flex-row-reverse' : ''} ${active ? 'text-primary' : 'hover:text-foreground'}`}>
        <Icon className={`h-3 w-3 ${active ? 'text-primary' : 'opacity-30 group-hover:opacity-70'}`} />{label}
      </button>
    </th>
  )
}

type BreakdownRow = {
  key: string
  label: ReactNode
  count: number
  liters: number
  amount: number
  selected: boolean
  selectable: boolean
  onSelect: () => void
}

function BreakdownTable({ title, nameColumn, rows }: {
  title: string
  nameColumn: string
  rows: BreakdownRow[]
}) {
  const selectedCount = rows.filter((row) => row.selected).length

  return (
    <section className="min-w-0 basis-[520px] flex-1 bg-card" aria-label={title}>
      <div className="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Нажмите строку, чтобы отфильтровать реестр</p>
        </div>
        <span className={cn(
          'shrink-0 rounded-md border px-2 py-1 text-xs tabular-nums',
          selectedCount ? 'border-primary/45 bg-primary/10 font-medium text-primary' : 'border-border bg-muted/35 text-muted-foreground',
        )}>
          {selectedCount ? `Выбрано: ${selectedCount}` : `${rows.length} поз.`}
        </span>
      </div>
      <div className="max-h-[330px] overflow-auto">
        <table className="w-full min-w-[470px] text-[13px]">
          <caption className="sr-only">{title}: количество реализаций, объём и выручка</caption>
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b bg-muted/35 text-xs text-muted-foreground">
              <th className="px-4 py-2.5 text-left font-medium">{nameColumn}</th>
              <th className="px-3 py-2.5 text-right font-medium">Реализации</th>
              <th className="px-3 py-2.5 text-right font-medium">Объём</th>
              <th className="px-4 py-2.5 text-right font-medium">Выручка</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                tabIndex={row.selectable ? 0 : undefined}
                aria-selected={row.selected}
                onClick={row.selectable ? row.onSelect : undefined}
                onKeyDown={(event) => {
                  if (!row.selectable || (event.key !== 'Enter' && event.key !== ' ')) return
                  event.preventDefault()
                  row.onSelect()
                }}
                className={cn(
                  'border-b border-border/45 transition-colors',
                  row.selectable && 'cursor-pointer hover:bg-muted/45',
                  row.selected && 'bg-primary/10 hover:bg-primary/15',
                )}
              >
                <td className="max-w-[220px] truncate px-4 py-2.5 font-medium">{row.label}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{nf0.format(row.count)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{fmtLiters(row.liters)}</td>
                <td className="px-4 py-2.5 text-right font-medium tabular-nums">{fmtMoney(row.amount)} ₽</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function SummaryMetric({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className={cn('min-w-[160px] flex-1 px-4 py-3.5', className)}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-base font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  )
}

export function FuelTransactionsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const qc = useQueryClient()
  const [station, setStation] = useState<string>(ALL)
  // Стартовый набор — из общего фильтра: реестр открывается уже суженным по виду
  // топлива, как и все соседние экраны. Дальше пользователь правит его локально.
  const fk = useFuelKindFilter()
  const [fuelCodes, setFuelCodes] = useState<Set<number>>(() => new Set(fk.fuelCodes ?? []))
  const fkKey = fk.key
  useEffect(() => { setFuelCodes(new Set(fk.fuelCodes ?? [])) }, [fkKey])
  const [payTypes, setPayTypes] = useState<Set<string>>(new Set())
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  // Смена контура делает поиск и страницу бессмысленными (CLAUDE.md, правило 5).
  useResetOnScopeChange(() => { setSearchInput(''); setSearch(''); setPage(0) })
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

  // статус фоновой загрузки реализаций
  const syncStatus = useQuery({
    queryKey: ['fuel-tx-sync-status', companyId], queryFn: getFuelTxSyncStatus,
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
    // companyId в ключе обязателен: запрос скоупится заголовком X-Company-Id,
    // без него смена компании отдаёт кеш предыдущей (чужой реестр операций).
    queryKey: ['fuel-tx-filters', companyId, dateFrom, dateTo],
    queryFn: () => getFuelTxFilters(dateFrom, dateTo),
  })
  const stationCode = station === ALL ? undefined : Number(station)
  const overviewQ = useQuery({
    queryKey: ['fuel-tx-overview', companyId, dateFrom, dateTo, station],
    queryFn: () => getFuelTxOverview(dateFrom, dateTo, stationCode),
  })

  const params = useMemo(() => ({
    dateFrom, dateTo, stationCode,
    fuelCodes: fuelCodes.size ? [...fuelCodes] : undefined,
    payTypes: payTypes.size ? [...payTypes] : undefined,
    search: search || undefined, sort, order,
  }), [dateFrom, dateTo, stationCode, fuelCodes, payTypes, search, sort, order])

  const { data, isLoading, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['fuel-tx-rows', companyId, params, page],
    queryFn: () => getFuelTxRows({ ...params, limit: PAGE, offset: page * PAGE }),
    placeholderData: keepPreviousData,
  })

  const onSort = (k: SortKey) => {
    if (k === sort) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else { setSort(k); setOrder('desc') }
  }
  const toggleFuel = (c: number) => setFuelCodes((s) => {
    const n = new Set(s)
    if (n.has(c)) n.delete(c)
    else n.add(c)
    return n
  })
  const togglePay = (p: string) => setPayTypes((s) => {
    const n = new Set(s)
    if (n.has(p)) n.delete(p)
    else n.add(p)
    return n
  })
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
  const activeFilterCount = (station !== ALL ? 1 : 0) + fuelCodes.size + payTypes.size + (search ? 1 : 0)
  const hasFreshFilterTotals = hasFilters && !!totals && !isPlaceholderData
  const summary = hasFreshFilterTotals ? totals : ov?.kpi

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
    <div className="space-y-4 p-4 lg:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">Операции</h2>
          <p className="mt-1 text-sm text-muted-foreground">Реестр реализаций STS: отберите нужный разрез и откройте операцию для деталей.</p>
          {syncing && syncStatus.data && (
            <p className="mt-1 text-xs text-primary">{syncStatus.data.message} · загружено {nf0.format(syncStatus.data.loaded)}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" className="h-9" onClick={loadTx} disabled={syncing} title="Загрузить реализации из STS за период раздела">
            {syncing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}Загрузить реализации
          </Button>
          <Button variant="outline" size="sm" className="h-9" onClick={exportXlsx} disabled={exporting || total === 0}>
            {exporting ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1.5 h-3.5 w-3.5" />}Экспорт{total > 50000 ? ' (до 50к)' : ''}
          </Button>
        </div>
      </header>

      <Card className="overflow-hidden border-border/80 bg-card/80">
        <CardContent className="flex flex-wrap items-center gap-2 p-3">
          <div className="mr-1 flex items-center gap-2 text-sm font-medium text-foreground">
            <span>Фильтры</span>
            <span className={cn(
              'rounded-md px-2 py-0.5 text-xs font-normal',
              activeFilterCount ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
            )}>
              {activeFilterCount ? `Активно: ${activeFilterCount}` : 'Все операции'}
            </span>
          </div>
          <Select value={station} onValueChange={setStation}>
            <SelectTrigger className="h-9 w-[180px] text-sm"><SelectValue placeholder="АЗС" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Все АЗС</SelectItem>
              {(filtersQ.data?.stations ?? []).map((s) => <SelectItem key={s.code} value={String(s.code)}>{s.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Номер карты" className="h-9 w-[190px] pl-8 text-sm" />
          </div>
          {hasFilters && <Button variant="ghost" size="sm" className="h-9 px-2.5 text-sm" onClick={resetAll}><X className="mr-1.5 h-4 w-4" />Сбросить</Button>}
          <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
            {isFetching && <><Loader2 className="h-3.5 w-3.5 animate-spin" />Обновление</>}
          </div>
        </CardContent>
      </Card>

      {summary && (
        <Card className="overflow-hidden">
          <CardContent className="flex flex-wrap p-0">
            <div className="basis-[230px] grow border-b border-border/70 px-4 py-3.5">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground"><Activity className="h-4 w-4 text-primary" />{hasFreshFilterTotals ? 'Текущая выборка' : hasFilters ? 'Обновляем выборку' : 'За выбранный период'}</div>
              <p className="mt-1 text-xs text-muted-foreground">
                {hasFreshFilterTotals ? 'Показатели пересчитаны по активным фильтрам.' : hasFilters ? 'Загружаем показатели по новому отбору.' : 'Все операции в границах периода и рабочей области.'}
              </p>
            </div>
            <SummaryMetric label="Реализации" value={nf0.format(summary.count)} className="border-b border-border/70" />
            <SummaryMetric label="Объём" value={fmtLiters(summary.liters)} className="border-b border-border/70" />
            <SummaryMetric label="Выручка" value={`${fmtMoney(summary.amount)} ₽`} />
          </CardContent>
        </Card>
      )}

      {ov && (ov.by_fuel.length > 0 || ov.by_payment.length > 0) && (
        <section aria-labelledby="operation-breakdown-heading">
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 id="operation-breakdown-heading" className="text-sm font-semibold text-foreground">Структура операций</h3>
              <p className="mt-0.5 text-xs text-muted-foreground">Сравнивайте показатели по колонкам; выбранные строки добавляют фильтр к реестру.</p>
            </div>
            {(fuelCodes.size || payTypes.size) > 0 && (
              <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={resetKpi}><X className="mr-1.5 h-3.5 w-3.5" />Снять фильтры разрезов</Button>
            )}
          </div>
          <Card className="overflow-hidden">
            <CardContent className="flex flex-wrap gap-px bg-border p-0">
              {ov.by_fuel.length > 0 && (
                <BreakdownTable
                  title="Виды топлива"
                  nameColumn="Топливо"
                  rows={ov.by_fuel.map((f) => ({
                    key: `fuel-${f.fuel_code ?? f.fuel_name}`,
                    label: <FuelBadge fuel={f.fuel_name} />,
                    count: f.count,
                    liters: f.liters,
                    amount: f.amount,
                    selected: f.fuel_code != null && fuelCodes.has(f.fuel_code),
                    selectable: f.fuel_code != null,
                    onSelect: () => f.fuel_code != null && toggleFuel(f.fuel_code),
                  }))}
                />
              )}
              {ov.by_payment.length > 0 && (
                <BreakdownTable
                  title="Способы оплаты"
                  nameColumn="Способ оплаты"
                  rows={ov.by_payment.map((p) => ({
                    key: `payment-${p.name}`,
                    label: p.name,
                    count: p.count,
                    liters: p.liters,
                    amount: p.amount,
                    selected: payTypes.has(p.name),
                    selectable: true,
                    onSelect: () => togglePay(p.name),
                  }))}
                />
              )}
            </CardContent>
          </Card>
        </section>
      )}

      <section aria-labelledby="operation-list-heading">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 id="operation-list-heading" className="text-sm font-semibold text-foreground">Реестр операций</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {total === 0 ? 'Нет строк по текущему отбору.' : `Показано ${nf0.format(from)}–${nf0.format(to)} из ${nf0.format(total)} операций.`}
            </p>
          </div>
        </div>
        <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : total === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">Нет операций по фильтру за период</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-[13px]">
                <thead>
                  <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
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
                    <tr key={r.id} className="cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/35" onClick={() => setDetail(r)}>
                      <td className="whitespace-nowrap px-3 py-2.5 font-mono text-muted-foreground">{fmtDt(r.dt)}</td>
                      <td className="max-w-[180px] truncate px-3 py-2.5 font-medium">{r.station_name}</td>
                      <td className="px-3 py-2.5">{r.fuel_name ? <FuelBadge fuel={r.fuel_name} /> : '—'}</td>
                      <td className="max-w-[160px] truncate px-3 py-2.5">{r.pay_type_name ?? '—'}</td>
                      <td className="px-3 py-2.5 font-mono text-muted-foreground">{cleanCard(r.card)}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{nf2.format(r.liters)}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">{r.price != null ? nf2.format(r.price) : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono font-medium tabular-nums">{fmtMoney(r.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
        </Card>
      </section>

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
            <DialogTitle>Операция (реализация)</DialogTitle>
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
