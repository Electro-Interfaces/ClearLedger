/**
 * Раздел «Операции» — реестр наливов по данным Ledger (`fuel_transactions`).
 *
 * Форма раздела повторяет «Операции» «Монитора» (TradeFrame,
 * `src/pages/OperationsTransactionsPageSimple.tsx`) — решение МАГа 29.07.2026:
 * это рабочее место оператора, к которому привыкли, и оно должно выглядеть и
 * работать одинаково в обоих продуктах. Отсюда KPI-карточки вместо таблиц-разрезов,
 * перекрёстный пересчёт, умный поиск и одинаковая карточка операции.
 *
 * Своё (не из «Монитора»): период и вид топлива берутся из общего фильтра рабочей
 * области, а не из полей раздела; сортировка по колонкам; серверная пагинация.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery, keepPreviousData, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, ArrowUp, ArrowDown, ArrowUpDown, Download, Search, X,
  ChevronLeft, ChevronRight, RefreshCw, Activity, Filter, FileSpreadsheet, FileText,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { FuelBadge } from '@/components/common/FuelBadge'
import { cn } from '@/lib/utils'
import { fmtMoney, fmtLiters } from '@/services/analyticsService'
import { useResetOnScopeChange } from '@/hooks/useScopeReset'
import {
  getFuelTxRows, getFuelTxFilters, getFuelTxOverview, getFuelTxCoupon,
  syncFuelTransactions, getFuelTxSyncStatus,
  type FuelTxRow, type FuelTxRowsParams,
} from '@/services/fuel/fuelMappingService'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import { parseOperationsSearch, parsedInt } from '@/utils/operationsSearchParser'
import { KpiFuelCard, KpiPaymentCard, KpiPaymentChip } from './operations/OperationsKpiCards'
import { exportOperationsToExcel, exportOperationsToPdf } from '@/services/fuel/operationsExport'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const ALL = '__all__'
const PAGE = 100
/** Потолок строк выгрузки — дальше файл становится неподъёмным для Excel. */
const EXPORT_CAP = 50000

/** Основные способы оплаты — всегда первым рядом крупными карточками, даже если за
 * период их не было (виден сам факт «купонов не было», и раскладка не прыгает). */
const PRIMARY_PAYMENTS = ['Банковские', 'Наличные', 'Онлайн', 'Корп. карты', 'Купон']

const STATUS_LABEL: Record<string, string> = {
  completed: 'Завершено', in_progress: 'Выполняется',
  failed: 'Ошибка', pending: 'Ожидание', cancelled: 'Отменено',
}

function statusBadge(status: string) {
  if (status === 'failed') {
    return <Badge className="border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300">Ошибка</Badge>
  }
  if (status === 'pending') {
    return <Badge className="border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">Ожидание</Badge>
  }
  return <Badge className="bg-secondary text-foreground">{STATUS_LABEL[status] ?? status}</Badge>
}

function fmtDt(s: string | null): string {
  if (!s) return '—'
  return new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}
const cleanCard = (c: string | null) => (c ? c.replace(/^0+/, '') || c : '—')

type SortKey = 'dt' | 'station' | 'fuel' | 'pay_type' | 'liters' | 'price' | 'amount'

function SortHead({ label, k, sort, order, onSort, right, center }: {
  label: string; k: SortKey; sort: SortKey; order: 'asc' | 'desc'; onSort: (k: SortKey) => void
  right?: boolean; center?: boolean
}) {
  const active = sort === k
  const Icon = !active ? ArrowUpDown : order === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={cn('px-3 py-2.5 font-medium', right ? 'text-right' : center ? 'text-center' : 'text-left')}>
      <button type="button" onClick={() => onSort(k)}
        className={cn('group inline-flex items-center gap-1', right && 'flex-row-reverse',
          active ? 'text-primary' : 'hover:text-foreground')}>
        <Icon className={cn('h-3 w-3', active ? 'text-primary' : 'opacity-30 group-hover:opacity-70')} />{label}
      </button>
    </th>
  )
}

type Agg = { count: number; liters: number; amount: number }
const ZERO: Agg = { count: 0, liters: 0, amount: 0 }

export function FuelTransactionsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const qc = useQueryClient()
  const [station, setStation] = useState<string>(ALL)
  const [status, setStatus] = useState<string>(ALL)
  // Стартовый набор — из общего фильтра: реестр открывается уже суженным по виду
  // топлива, как и все соседние экраны. Дальше пользователь правит его локально.
  const fk = useFuelKindFilter()
  const [fuelNames, setFuelNames] = useState<Set<string>>(new Set())
  const [payments, setPayments] = useState<Set<string>>(new Set())
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
  const fkKey = fk.key
  useEffect(() => { setFuelNames(new Set()) }, [fkKey])
  useEffect(() => { setPage(0) }, [station, status, fuelNames, payments, search, sort, order, dateFrom, dateTo, fkKey])

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
  const parsed = useMemo(() => parseOperationsSearch(search), [search])
  // Станция из строки поиска («азс 6») работает, только если селектор не задан явно.
  const effStation = stationCode ?? parsedInt(parsed.station)

  const overviewQ = useQuery({
    queryKey: ['fuel-tx-overview', companyId, dateFrom, dateTo, effStation, fkKey],
    queryFn: () => getFuelTxOverview(dateFrom, dateTo, effStation, fk.fuelCodes),
  })

  const params = useMemo<FuelTxRowsParams>(() => {
    // Коды видов топлива для сервера: локальный выбор карточек (по имени вида,
    // как его показывает разрез) сужает сквозной фильтр рабочей области.
    const codesByName = new Map((overviewQ.data?.by_fuel ?? [])
      .filter((f) => f.fuel_code != null)
      .map((f) => [f.fuel_name, f.fuel_code as number]))
    const picked = [...fuelNames].map((n) => codesByName.get(n)).filter((c): c is number => c != null)
    return {
      dateFrom, dateTo, stationCode: effStation,
      fuelCodes: picked.length ? picked : fk.fuelCodes,
      payTypes: payments.size ? [...payments] : undefined,
      shift: parsedInt(parsed.shift), receipt: parsedInt(parsed.receipt), pos: parsedInt(parsed.pos),
      card: parsed.card, search: parsed.search,
      status: status === ALL ? undefined : status,
      sort, order,
    }
  }, [dateFrom, dateTo, effStation, fuelNames, payments, parsed, status, sort, order, fk.fuelCodes, overviewQ.data])

  const { data, isLoading, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['fuel-tx-rows', companyId, params, page],
    queryFn: () => getFuelTxRows({ ...params, limit: PAGE, offset: page * PAGE }),
    placeholderData: keepPreviousData,
  })

  const onSort = (k: SortKey) => {
    if (k === sort) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else { setSort(k); setOrder('desc') }
  }
  const toggle = <T,>(set: (fn: (s: Set<T>) => Set<T>) => void) => (v: T) => set((s) => {
    const n = new Set(s)
    if (n.has(v)) n.delete(v)
    else n.add(v)
    return n
  })
  const toggleFuel = toggle<string>(setFuelNames)
  const togglePayment = toggle<string>(setPayments)
  const resetKpi = () => { setFuelNames(new Set()); setPayments(new Set()) }
  const resetAll = () => { setStation(ALL); setStatus(ALL); resetKpi(); setSearchInput(''); setSearch('') }
  const hasKpiFilter = fuelNames.size > 0 || payments.size > 0
  const hasFilters = station !== ALL || status !== ALL || hasKpiFilter || !!search

  const ov = overviewQ.data
  const total = data?.total ?? 0
  const rows = data?.rows ?? []
  const pages = Math.max(1, Math.ceil(total / PAGE))
  const from = total === 0 ? 0 : page * PAGE + 1
  const to = Math.min(total, (page + 1) * PAGE)
  const activeFilterCount = (station !== ALL ? 1 : 0) + (status !== ALL ? 1 : 0)
    + fuelNames.size + payments.size + (search ? 1 : 0)

  // ─── KPI: перекрёстный пересчёт по кросс-разрезу «топливо × оплата» ───
  // Выбрали АИ-92 → карточки оплат показывают суммы только по нему, и наоборот;
  // «Итого» сужено обоими. Считается локально, клик по карточке не идёт в сеть.
  const cross = ov?.by_fuel_payment
  const sumCross = (match: (c: NonNullable<typeof cross>[number]) => boolean): Agg => {
    let count = 0, liters = 0, amount = 0
    for (const c of cross ?? []) {
      if (!match(c)) continue
      count += c.count; liters += c.liters; amount += c.amount
    }
    return { count, liters, amount }
  }

  const fuelKpis = useMemo(() => (ov?.by_fuel ?? []).map((f) => ({
    fuel: f.fuel_name,
    ...(payments.size === 0
      ? { count: f.count, liters: f.liters, amount: f.amount }
      : sumCross((c) => c.fuel_name === f.fuel_name && payments.has(c.name))),
  })), [ov, cross, payments])

  const paymentKpis = useMemo(() => {
    // Порядок — по общей выручке за период, чтобы карточки не прыгали при фильтре.
    const base = (ov?.by_payment ?? []).slice().sort((a, b) => b.amount - a.amount)
    return base.map((p) => ({
      payment: p.name,
      ...(fuelNames.size === 0
        ? { count: p.count, liters: p.liters, amount: p.amount }
        : sumCross((c) => c.name === p.name && fuelNames.has(c.fuel_name))),
    }))
  }, [ov, cross, fuelNames])

  const totalKpi = useMemo<Agg>(() => {
    if (!ov) return ZERO
    if (!hasKpiFilter) return { count: ov.kpi.count, liters: ov.kpi.liters, amount: ov.kpi.amount }
    return sumCross((c) =>
      (fuelNames.size === 0 || fuelNames.has(c.fuel_name)) &&
      (payments.size === 0 || payments.has(c.name)))
  }, [ov, cross, fuelNames, payments, hasKpiFilter])

  // Карточки показываем по НАЛИЧИЮ данных за период, а не по результату фильтра —
  // иначе пустое пересечение прячет карточки вместе с кнопкой сброса.
  const hasPeriodData = (ov?.kpi.count ?? 0) > 0
  const primaryCards = PRIMARY_PAYMENTS.map((name) =>
    paymentKpis.find((p) => p.payment === name) ?? { payment: name, ...ZERO })
  const restCards = paymentKpis.filter((p) => !PRIMARY_PAYMENTS.includes(p.payment))

  /** Все строки текущего отбора — для выгрузки (не только видимая страница). */
  async function collectAllRows(): Promise<FuelTxRow[]> {
    const res = await getFuelTxRows({ ...params, limit: 1000, offset: 0 })
    const all: FuelTxRow[] = [...res.rows]
    while (all.length < Math.min(res.total, EXPORT_CAP)) {
      const chunk = await getFuelTxRows({ ...params, limit: 1000, offset: all.length })
      if (chunk.rows.length === 0) break
      all.push(...chunk.rows)
    }
    return all
  }

  async function runExport(kind: 'xlsx' | 'pdf') {
    setExporting(true)
    try {
      const all = await collectAllRows()
      const opts = { rows: all, dateFrom, dateTo, stationName: station === ALL ? 'Все АЗС'
        : filtersQ.data?.stations.find((s) => String(s.code) === station)?.name }
      if (kind === 'xlsx') await exportOperationsToExcel(opts)
      else await exportOperationsToPdf(opts)
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="h-9" disabled={exporting || total === 0}>
                {exporting ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1.5 h-3.5 w-3.5" />}
                Экспорт{total > EXPORT_CAP ? ' (до 50к)' : ''}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem onClick={() => runExport('xlsx')} className="cursor-pointer gap-2 py-2.5">
                <FileSpreadsheet className="h-4 w-4 text-green-600 dark:text-green-400" />
                <span className="text-sm font-medium">Экспорт в Excel</span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => runExport('pdf')} className="cursor-pointer gap-2 py-2.5">
                <FileText className="h-4 w-4 text-red-600 dark:text-red-400" />
                <span className="text-sm font-medium">Экспорт в PDF</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <Card className="overflow-hidden border-border/80 bg-card/80">
        <CardContent className="p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span>Фильтры</span>
              <span className={cn('rounded-md px-2 py-0.5 text-xs font-normal',
                activeFilterCount ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground')}>
                {activeFilterCount ? `Активно: ${activeFilterCount}` : 'Все операции'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {hasFilters && (
                <Button variant="outline" size="sm" className="h-8" onClick={resetAll}>
                  <X className="mr-1.5 h-3.5 w-3.5" />Очистить фильтры
                </Button>
              )}
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
                {isFetching && <><Loader2 className="h-3.5 w-3.5 animate-spin" />Обновление</>}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="ops-station" className="text-xs text-muted-foreground">АЗС</Label>
              <Select value={station} onValueChange={setStation}>
                <SelectTrigger id="ops-station" className="h-9 w-[190px] text-sm"><SelectValue placeholder="Все АЗС" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Все АЗС</SelectItem>
                  {(filtersQ.data?.stations ?? []).map((s) => <SelectItem key={s.code} value={String(s.code)}>{s.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="ops-status" className="text-xs text-muted-foreground">Статус</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger id="ops-status" className="h-9 w-[160px] text-sm"><SelectValue placeholder="Все" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Все</SelectItem>
                  {Object.entries(STATUS_LABEL).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-[260px] flex-1 space-y-1">
              <Label htmlFor="ops-search" className="text-xs text-muted-foreground">Поиск</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input id="ops-search" value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Чек, смена, карта, АЗС — «смена 9 азс 6 чек 42»" className="h-9 pl-8 text-sm" />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {hasPeriodData && (
        <div className="space-y-4">
          <section className="space-y-2" aria-label="Виды топлива">
            <div className="flex items-center gap-2 px-1">
              <h3 className="text-base font-medium text-foreground/80">Виды топлива</h3>
              <span className="text-xs text-muted-foreground">выберите один или несколько элементов</span>
            </div>
            <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(Math.max(fuelKpis.length, 1), 6)}, minmax(0, 1fr))` }}>
              {fuelKpis.map((f) => (
                <KpiFuelCard key={f.fuel} fuel={f.fuel} selected={fuelNames.has(f.fuel)}
                  volume={f.liters} cost={f.amount} count={f.count} onClick={toggleFuel} />
              ))}
            </div>
          </section>

          <section className="space-y-2" aria-label="Способы оплаты">
            <div className="flex items-center gap-2 px-1">
              <h3 className="text-base font-medium text-foreground/80">Способы оплаты</h3>
              <span className="text-xs text-muted-foreground">выберите один или несколько элементов</span>
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              {primaryCards.map((p) => (
                <KpiPaymentCard key={p.payment} payment={p.payment} selected={payments.has(p.payment)}
                  volume={p.liters} cost={p.amount} count={p.count} onClick={togglePayment} />
              ))}
            </div>
            {restCards.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {restCards.map((p) => (
                  <KpiPaymentChip key={p.payment} payment={p.payment} selected={payments.has(p.payment)}
                    volume={p.liters} cost={p.amount} count={p.count} onClick={togglePayment} />
                ))}
              </div>
            )}
          </section>

          <section className="space-y-2" aria-label="Итого">
            <div className="flex items-center gap-3 px-1">
              <h3 className="text-base font-medium text-foreground/80">Итого</h3>
              <span className="text-sm">
                {hasKpiFilter ? (
                  <><span className="text-muted-foreground">выбрано: </span>
                    <span className="font-bold text-primary">{[...fuelNames, ...payments].join(', ')}</span></>
                ) : <span className="text-muted-foreground">не выбрано</span>}
              </span>
            </div>
            <Card
              className={cn('transition-all duration-300',
                hasKpiFilter ? 'cursor-pointer border-2 border-primary/45 bg-primary/5 hover:shadow-lg' : 'bg-card')}
              onClick={hasKpiFilter ? resetKpi : undefined}
              title={hasKpiFilter ? 'Снять фильтры разрезов' : undefined}
            >
              <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-foreground/80">{nf0.format(totalKpi.count)} операций</span>
                  {hasKpiFilter && <span className="text-xs text-primary">нажмите, чтобы снять разрезы</span>}
                </div>
                <div className="flex gap-6 text-right">
                  <div className="text-base font-semibold tabular-nums text-foreground">{fmtLiters(totalKpi.liters)}</div>
                  <div className="text-base font-semibold tabular-nums text-foreground">{fmtMoney(totalKpi.amount)} ₽</div>
                </div>
              </CardContent>
            </Card>
          </section>
        </div>
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
            <div className="p-8 text-center text-sm text-muted-foreground">Нет операций по выбранным фильтрам</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1100px] text-[13px]">
                <thead>
                  <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                    <SortHead label="Дата/время" k="dt" sort={sort} order={order} onSort={onSort} />
                    <SortHead label="АЗС" k="station" sort={sort} order={order} onSort={onSort} />
                    <SortHead label="Топливо" k="fuel" sort={sort} order={order} onSort={onSort} />
                    <SortHead label="Факт" k="liters" sort={sort} order={order} onSort={onSort} right />
                    <SortHead label="Цена" k="price" sort={sort} order={order} onSort={onSort} right />
                    <SortHead label="Сумма" k="amount" sort={sort} order={order} onSort={onSort} right />
                    <SortHead label="Оплата" k="pay_type" sort={sort} order={order} onSort={onSort} />
                    <th className="px-3 py-2.5 text-left font-medium">Карта</th>
                    <th className="px-3 py-2.5 text-center font-medium">Чек</th>
                    <th className="px-3 py-2.5 text-center font-medium">POS</th>
                    <th className="px-3 py-2.5 text-center font-medium">Смена</th>
                    <th className="px-3 py-2.5 text-center font-medium">Пистолет</th>
                    <th className="px-3 py-2.5 text-left font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/35" onClick={() => setDetail(r)}>
                      <td className="whitespace-nowrap px-3 py-2.5 font-mono text-muted-foreground">{fmtDt(r.dt)}</td>
                      <td className="max-w-[200px] px-3 py-2.5">
                        <div className="truncate font-medium">{r.station_name}</div>
                        <div className="truncate font-mono text-xs text-muted-foreground">ID: {r.ext_id}</div>
                      </td>
                      <td className="px-3 py-2.5">{r.fuel_name ? <FuelBadge fuel={r.fuel_name} /> : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{nf2.format(r.liters)} л</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">{r.price != null ? nf2.format(r.price) : '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono font-medium tabular-nums">{fmtMoney(r.amount)}</td>
                      <td className="max-w-[150px] truncate px-3 py-2.5">{r.payment_method ?? r.pay_type_name ?? '—'}</td>
                      <td className="px-3 py-2.5 font-mono text-muted-foreground">{cleanCard(r.card)}</td>
                      <td className="px-3 py-2.5 text-center tabular-nums">{r.receipt ?? '—'}</td>
                      <td className="px-3 py-2.5 text-center tabular-nums">{r.pos ?? '—'}</td>
                      <td className="px-3 py-2.5 text-center tabular-nums">{r.shift_number ?? '—'}</td>
                      <td className="px-3 py-2.5 text-center tabular-nums">{r.nozzle ?? '—'}</td>
                      <td className="px-3 py-2.5">{statusBadge(r.status)}</td>
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
          <span>{nf0.format(from)}–{nf0.format(to)} из {nf0.format(total)}{isPlaceholderData ? ' · обновляем' : ''}</span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}><ChevronLeft className="h-4 w-4" /></Button>
            <span className="px-2 tabular-nums">{page + 1} / {nf0.format(pages)}</span>
            <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}

      <OperationDetailsDialog row={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

/** Карточка операции. Состав полей — как в «Мониторе»: то, что оператор проверяет
 * по звонку клиента (чек, купон, заказ до налива, ТРК и резервуар). */
function OperationDetailsDialog({ row, onClose }: { row: FuelTxRow | null; onClose: () => void }) {
  const isCoupon = (row?.payment_method ?? '') === 'Купон'
  const number = row?.card && row.card !== '-' ? row.card : ''
  // Дату выдачи купона знает только STS — тянем точечно при открытии карточки.
  const coupon = useQuery({
    queryKey: ['fuel-tx-coupon', row?.station_code, row?.dt, number],
    queryFn: () => getFuelTxCoupon(row!.station_code, row!.dt!, number),
    enabled: !!row && isCoupon && !!number && !!row.dt,
    staleTime: 5 * 60 * 1000,
  })

  const fields: [string, ReactNode][] = row ? [
    ['Статус', statusBadge(row.status)],
    ['Время', fmtDt(row.dt)],
    ['Вид топлива', row.fuel_name ?? '—'],
    ['Количество', `${nf2.format(row.liters)} л`],
    ['Цена за литр', row.price != null ? `${nf2.format(row.price)} ₽/л` : '—'],
    ['Сумма', `${fmtMoney(row.amount)} ₽`],
    ['Способ оплаты', row.payment_method ?? row.pay_type_name ?? '—'],
    ...(isCoupon && number ? ([
      ['Номер купона', number],
      ['Купон выдан', coupon.isFetching ? '…' : coupon.data?.issued_at ? fmtDt(coupon.data.issued_at) : '—'],
      ['Купон реализован', fmtDt(row.dt)],
    ] as [string, ReactNode][]) : []),
    ...(!isCoupon && row.card ? ([['Карта', row.card]] as [string, ReactNode][]) : []),
    ['АЗС', row.station_name],
    ['Номер чека', row.receipt ?? '—'],
    ['Смена', row.shift_number ?? '—'],
    ['ТРК (POS)', row.pos ?? '—'],
    ['Пистолет', row.nozzle ?? '—'],
    ['Резервуар', row.tank ?? '—'],
    ...(row.mass != null ? ([['Масса', `${nf2.format(row.mass)} кг`]] as [string, ReactNode][]) : []),
    ...(row.density != null ? ([['Плотность', `${row.density} кг/л`]] as [string, ReactNode][]) : []),
    ...(row.order_qty ? ([['Заказ (литры)', `${nf2.format(row.order_qty)} л`]] as [string, ReactNode][]) : []),
    ...(row.order_cost ? ([['Заказ (сумма)', `${fmtMoney(row.order_cost)} ₽`]] as [string, ReactNode][]) : []),
    ['ID операции (STS)', row.ext_id],
  ] : []

  return (
    <Dialog open={!!row} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-md overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Операция{row ? ` № ${row.receipt ?? row.ext_id}` : ''}</DialogTitle>
          <DialogDescription>{row?.station_name}{row?.dt ? ` · ${fmtDt(row.dt)}` : ''}</DialogDescription>
        </DialogHeader>
        {row && (
          <div className="grid grid-cols-1 gap-0 text-sm">
            {fields.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-4 border-b border-border/60 py-1.5">
                <span className="text-muted-foreground">{k}:</span>
                <span className="text-right font-mono">{v}</span>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
