import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  BarChart3, Download, Fuel, Loader2, MapPin, RefreshCw, WalletCards, X,
} from 'lucide-react'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MultiSelectFilter } from '@/components/locations/fleet/MultiSelectFilter'
import { useFilters } from '@/contexts/FilterContext'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import { useLocations } from '@/hooks/useLocations'
import { cn } from '@/lib/utils'
import { fmtLiters, fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import {
  getFuelTxFilters, getFuelTxPivot, getSalesChannelsAnalytics,
  type SalesChannelMetrics, type SalesChannelsAnalytics,
} from '@/services/fuel/fuelMappingService'
import { PivotView } from './PivotView'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const metricMeta = {
  amount: { label: 'Выручка', short: '₽', format: (value: number) => `${fmtMoneyShort(value)} ₽` },
  liters: { label: 'Объём', short: 'л', format: (value: number) => fmtLiters(value) },
  count: { label: 'Реализации', short: 'шт.', format: (value: number) => nf0.format(value) },
} as const
type TrendMetric = keyof typeof metricMeta

function locationStationCodes(locations: ReturnType<typeof useLocations>, selectedIds: string[]): number[] {
  if (selectedIds.length === 0) return []
  const selected = new Set(selectedIds)
  const codes = new Set<number>()
  for (const location of locations) {
    if (!selected.has(location.id)) continue
    let added = false
    for (const binding of location.sourceBindings) {
      const code = Number(binding.config.station ?? binding.config.code ?? location.code)
      if (Number.isFinite(code) && code > 0) {
        codes.add(code)
        added = true
      }
    }
    if (!added) {
      const code = Number(location.code)
      if (Number.isFinite(code) && code > 0) codes.add(code)
    }
  }
  return [...codes].sort((a, b) => a - b)
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div data-metric={label} className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-lg font-semibold tabular-nums">{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

interface BreakdownRow extends SalesChannelMetrics {
  key: string
  label: string
  selectable?: boolean
}

function BreakdownTable({ rows, selected, onSelect, empty }: {
  rows: BreakdownRow[]
  selected: string[]
  onSelect: (key: string) => void
  empty: string
}) {
  if (rows.length === 0) return <div className="p-8 text-center text-sm text-muted-foreground">{empty}</div>
  const selectedSet = new Set(selected)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-xs">
        <thead>
          <tr className="border-b bg-muted/35 text-muted-foreground">
            <th className="p-2.5 text-left font-medium">Разрез</th>
            <th className="p-2.5 text-right font-medium">Реализации</th>
            <th className="p-2.5 text-right font-medium">Объём</th>
            <th className="p-2.5 text-right font-medium">Выручка</th>
            <th className="p-2.5 text-right font-medium">Доля</th>
            <th className="p-2.5 text-right font-medium">Средний чек</th>
            <th className="p-2.5 text-right font-medium">Ср. заправка</th>
            <th className="p-2.5 text-right font-medium">₽/л</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isSelected = selectedSet.has(row.key)
            const selectable = row.selectable !== false
            return (
              <tr
                key={row.key}
                tabIndex={selectable ? 0 : undefined}
                aria-selected={isSelected}
                onClick={selectable ? () => onSelect(row.key) : undefined}
                onKeyDown={(event) => {
                  if (!selectable) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelect(row.key)
                  }
                }}
                className={cn(
                  'border-b border-border/40 transition-colors',
                  selectable && 'cursor-pointer hover:bg-muted/35',
                  isSelected && 'bg-primary/10 hover:bg-primary/15',
                )}
              >
                <td className="max-w-[250px] truncate p-2.5 font-medium">{row.label}</td>
                <td className="p-2.5 text-right tabular-nums">{nf0.format(row.count)}</td>
                <td className="p-2.5 text-right tabular-nums">{fmtLiters(row.liters)}</td>
                <td className="p-2.5 text-right font-medium tabular-nums">{fmtMoney(row.amount)} ₽</td>
                <td className="p-2.5 text-right tabular-nums">{nf1.format(row.share)}%</td>
                <td className="p-2.5 text-right tabular-nums">{fmtMoney(row.avg_check)} ₽</td>
                <td className="p-2.5 text-right tabular-nums">{nf1.format(row.avg_fill)} л</td>
                <td className="p-2.5 text-right tabular-nums text-muted-foreground">{fmtMoney(row.avg_price)} ₽</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function PaymentTable({ data, selected, onSelect }: {
  data: SalesChannelsAnalytics['by_payment']
  selected: string[]
  onSelect: (value: string) => void
}) {
  const max = Math.max(...data.map((row) => row.amount), 1)
  const selectedSet = new Set(selected)
  return (
    <div className="max-h-[330px] overflow-auto">
      <table className="w-full min-w-[500px] text-xs">
        <thead className="sticky top-0 z-10 bg-card">
          <tr className="border-b text-muted-foreground">
            <th className="p-2.5 text-left font-medium">Способ оплаты</th>
            <th className="p-2.5 text-right font-medium">Реализации</th>
            <th className="p-2.5 text-right font-medium">Объём</th>
            <th className="p-2.5 text-right font-medium">Выручка</th>
            <th className="p-2.5 text-right font-medium">Доля</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => {
            const active = selectedSet.has(row.name)
            return (
              <tr
                key={row.name}
                tabIndex={0}
                aria-selected={active}
                onClick={() => onSelect(row.name)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelect(row.name)
                  }
                }}
                className={cn('cursor-pointer border-b border-border/40 hover:bg-muted/35', active && 'bg-primary/10')}
              >
                <td className="relative max-w-[190px] overflow-hidden p-2.5 font-medium">
                  <span className="relative z-[1] block truncate">{row.name}</span>
                  <span className="absolute inset-y-1 left-1 rounded-sm bg-primary/8" style={{ width: `${Math.max(2, 100 * row.amount / max)}%` }} />
                </td>
                <td className="p-2.5 text-right tabular-nums">{nf0.format(row.count)}</td>
                <td className="p-2.5 text-right tabular-nums">{fmtLiters(row.liters)}</td>
                <td className="p-2.5 text-right font-medium tabular-nums">{fmtMoney(row.amount)} ₽</td>
                <td className="p-2.5 text-right tabular-nums">{nf1.format(row.share)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function StationPaymentTable({ rows }: { rows: SalesChannelsAnalytics['station_payment'] }) {
  if (rows.length === 0) return <div className="p-8 text-center text-sm text-muted-foreground">Нет данных по связке АЗС и оплаты</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-xs">
        <thead>
          <tr className="border-b bg-muted/35 text-muted-foreground">
            <th className="p-2.5 text-left font-medium">АЗС</th>
            <th className="p-2.5 text-left font-medium">Способ оплаты</th>
            <th className="p-2.5 text-right font-medium">Реализации</th>
            <th className="p-2.5 text-right font-medium">Объём</th>
            <th className="p-2.5 text-right font-medium">Выручка</th>
            <th className="p-2.5 text-right font-medium">Доля в АЗС</th>
            <th className="p-2.5 text-right font-medium">Средний чек</th>
            <th className="p-2.5 text-right font-medium">₽/л</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const firstForStation = index === 0 || rows[index - 1].station_code !== row.station_code
            return (
              <tr key={`${row.station_code}-${row.payment}`} className={cn('border-b border-border/40 hover:bg-muted/30', firstForStation && index > 0 && 'border-t-2')}>
                <td className="p-2.5 font-medium">{firstForStation ? row.station_name : ''}</td>
                <td className="p-2.5">{row.payment}</td>
                <td className="p-2.5 text-right tabular-nums">{nf0.format(row.count)}</td>
                <td className="p-2.5 text-right tabular-nums">{fmtLiters(row.liters)}</td>
                <td className="p-2.5 text-right font-medium tabular-nums">{fmtMoney(row.amount)} ₽</td>
                <td className="p-2.5 text-right tabular-nums">{nf1.format(row.share)}%</td>
                <td className="p-2.5 text-right tabular-nums">{fmtMoney(row.avg_check)} ₽</td>
                <td className="p-2.5 text-right tabular-nums text-muted-foreground">{fmtMoney(row.avg_price)} ₽</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function SalesChannelsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string
  dateFrom: string
  dateTo: string
}) {
  const { stationCode, locationIds } = useFilters()
  const fk = useFuelKindFilter()
  const locations = useLocations()
  const [stations, setStations] = useState<string[]>([])
  const [fuels, setFuels] = useState<string[]>([])
  const [payments, setPayments] = useState<string[]>([])
  const [trendMetric, setTrendMetric] = useState<TrendMetric>('amount')
  const [exporting, setExporting] = useState(false)

  const workspaceStations = useMemo(() => {
    const locationCodes = locationStationCodes(locations, locationIds)
    if (stationCode === 'all') return locationCodes
    const sourceCode = Number(stationCode)
    if (!Number.isFinite(sourceCode)) return locationCodes
    if (locationCodes.length === 0) return [sourceCode]
    return locationCodes.includes(sourceCode) ? [sourceCode] : [-1]
  }, [locationIds, locations, stationCode])
  const workspaceKey = workspaceStations.join(',')
  // Сводная умеет одну станцию (как реестр). Несколько выбранных областью - берём
  // всю сеть, иначе разрез молча покажет часть данных и разойдётся с карточками.
  const pivotStation = workspaceStations.length === 1 && workspaceStations[0] > 0
    ? workspaceStations[0] : undefined
  const scopeMismatch = workspaceStations.includes(-1)

  useEffect(() => {
    setStations([])
  }, [workspaceKey])
  useEffect(() => {
    setFuels([])
    setPayments([])
  }, [dateFrom, dateTo])

  const filtersQuery = useQuery({
    queryKey: ['fuel-tx-filters', companyId, dateFrom, dateTo],
    queryFn: () => getFuelTxFilters(dateFrom, dateTo),
    staleTime: 60_000,
  })
  const effectiveStations = useMemo(() => {
    if (stations.length > 0) return stations.map(Number)
    return workspaceStations
  }, [stations, workspaceStations])
  // Вид топлива: локальный селектор экрана сужает ВНУТРИ выбора из шапки —
  // выбрали в общем фильтре ДТ, экран не может показать бензин.
  const effectiveFuels = useMemo(() => (
    fuels.length ? fuels.map(Number) : (fk.fuelCodes ?? [])
  ), [fuels, fk.fuelCodes])
  const params = useMemo(() => ({
    dateFrom,
    dateTo,
    stationCodes: effectiveStations.length ? effectiveStations : undefined,
    fuelCodes: effectiveFuels.length ? effectiveFuels : undefined,
    payTypes: payments.length ? payments : undefined,
  }), [dateFrom, dateTo, effectiveStations, effectiveFuels, payments])
  const analyticsQuery = useQuery({
    queryKey: ['fuel-sales-channels', companyId, params],
    queryFn: () => getSalesChannelsAnalytics(params),
    placeholderData: keepPreviousData,
  })

  const stationOptions = useMemo(() => {
    if (scopeMismatch) return []
    const scope = new Set(workspaceStations.filter((code) => code > 0))
    return (filtersQuery.data?.stations ?? [])
      .filter((station) => scope.size === 0 || scope.has(station.code))
      .map((station) => ({ value: String(station.code), label: station.name }))
  }, [filtersQuery.data?.stations, scopeMismatch, workspaceStations])
  const fuelOptions = (filtersQuery.data?.fuels ?? []).map((fuel) => ({ value: String(fuel.code), label: fuel.name }))
  const paymentOptions = (filtersQuery.data?.pay_types ?? []).map((payment) => ({ value: payment, label: payment }))
  const data = analyticsQuery.data
  const hasLocalFilters = stations.length > 0 || fuels.length > 0 || payments.length > 0

  const toggle = (list: string[], value: string, setter: (next: string[]) => void) =>
    setter(list.includes(value) ? list.filter((item) => item !== value) : [...list, value])
  const reset = () => {
    setStations([])
    setFuels([])
    setPayments([])
  }

  const stationRows: BreakdownRow[] = (data?.by_station ?? []).map((row) => ({ ...row, key: String(row.code), label: row.name }))
  const fuelRows: BreakdownRow[] = (data?.by_fuel ?? []).map((row) => ({
    ...row,
    key: row.code == null ? `unknown:${row.name}` : String(row.code),
    label: row.name,
    selectable: row.code != null,
  }))
  const trend = (data?.daily ?? []).map((row) => ({ ...row, label: row.date.slice(5).split('-').reverse().join('.') }))
  const trendInfo = metricMeta[trendMetric]

  async function exportXlsx() {
    if (!data) return
    setExporting(true)
    try {
      const XLSX = await import('xlsx')
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.by_payment.map((row) => ({
        'Способ оплаты': row.name, 'Реализации': row.count, 'Объём, л': row.liters,
        'Выручка, ₽': row.amount, 'Доля, %': row.share, 'Средний чек, ₽': row.avg_check,
        'Ср. заправка, л': row.avg_fill, 'Цена, ₽/л': row.avg_price,
      }))), 'Способы оплаты')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.by_station.map((row) => ({
        'АЗС': row.name, 'Код': row.code, 'Реализации': row.count, 'Объём, л': row.liters,
        'Выручка, ₽': row.amount, 'Доля, %': row.share, 'Средний чек, ₽': row.avg_check,
      }))), 'АЗС')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.station_payment.map((row) => ({
        'АЗС': row.station_name, 'Способ оплаты': row.payment, 'Реализации': row.count,
        'Объём, л': row.liters, 'Выручка, ₽': row.amount, 'Доля в АЗС, %': row.share,
      }))), 'АЗС × оплата')
      XLSX.writeFile(wb, `kanaly_prodazh_${dateFrom}_${dateTo}.xlsx`)
    } finally {
      setExporting(false)
    }
  }

  if (analyticsQuery.isLoading) {
    return <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Загрузка каналов продаж…</div>
  }
  if (analyticsQuery.error) {
    return <div className="p-6 text-sm text-destructive">Не удалось загрузить аналитику: {String(analyticsQuery.error)}</div>
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold">Каналы продаж</h2>
            {analyticsQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label="Обновление данных" /> : null}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">Пооперационные данные STS · все фильтры пересчитывают разрезы совместно</p>
        </div>
        <Button variant="outline" size="sm" className="h-8" onClick={exportXlsx} disabled={exporting || !data?.totals.count}>
          {exporting ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1.5 h-3.5 w-3.5" />}
          Экспорт
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2.5">
        <span className="mr-1 text-xs font-medium text-muted-foreground">Фильтры раздела</span>
        <MultiSelectFilter
          label={workspaceStations.length > 0 ? 'АЗС в контуре' : 'АЗС'}
          icon={MapPin}
          options={stationOptions}
          selected={stations}
          onChange={setStations}
          width="w-[260px]"
        />
        <MultiSelectFilter label="Способ оплаты" icon={WalletCards} options={paymentOptions} selected={payments} onChange={setPayments} width="w-[280px]" />
        <MultiSelectFilter label="Топливо" icon={Fuel} options={fuelOptions} selected={fuels} onChange={setFuels} />
        {hasLocalFilters ? (
          <Button variant="ghost" size="sm" className="h-9 px-2 text-xs" onClick={reset}><X className="mr-1 h-3.5 w-3.5" />Сбросить</Button>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {scopeMismatch
            ? 'Источник STS не входит в выбранную область учёта'
            : workspaceStations.length > 0
              ? `Рабочий контур: ${workspaceStations.length} АЗС`
              : 'Рабочий контур: вся сеть'}
        </span>
      </div>

      {data && data.totals.count > 0 ? (
        <>
          <Card>
            <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
              <Metric label="Выручка" value={`${fmtMoneyShort(data.totals.amount)} ₽`} hint={`${nf1.format(data.totals.share)}% выборки`} />
              <Metric label="Объём" value={fmtLiters(data.totals.liters)} hint={`${data.totals.stations} АЗС`} />
              <Metric label="Реализации" value={nf0.format(data.totals.count)} hint={`${data.by_payment.length} видов оплаты`} />
              <Metric label="Средний чек" value={`${fmtMoney(data.totals.avg_check)} ₽`} />
              <Metric label="Ср. заправка" value={`${nf1.format(data.totals.avg_fill)} л`} />
              <Metric label="Средняя цена" value={`${fmtMoney(data.totals.avg_price)} ₽/л`} />
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(520px,1.15fr)]">
            <Card>
              <CardContent className="p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-1.5 text-sm font-semibold"><BarChart3 className="h-4 w-4 text-primary" />Динамика</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">по дням выбранного периода</div>
                  </div>
                  <Select value={trendMetric} onValueChange={(value) => setTrendMetric(value as TrendMetric)}>
                    <SelectTrigger className="h-8 w-[130px] text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(metricMeta).map(([key, meta]) => <SelectItem key={key} value={key}>{meta.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <ResponsiveContainer width="100%" height={285}>
                  <LineChart data={trend} margin={{ top: 8, right: 12, left: 6, bottom: 2 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" minTickGap={18} />
                    <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={54} tickFormatter={(value) => trendInfo.format(Number(value)).replace(` ${trendInfo.short}`, '')} />
                    <Tooltip {...rechartsTooltipTheme}
                      formatter={(value) => [trendInfo.format(Number(value)), trendInfo.label]}
                      labelFormatter={(_, payload) => payload?.[0]?.payload?.date ? new Date(`${payload[0].payload.date}T00:00:00`).toLocaleDateString('ru-RU') : ''}
                      contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    />
                    <Line type="monotone" dataKey={trendMetric} stroke="hsl(var(--primary))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-0">
                <div className="border-b px-4 py-3">
                  <div className="text-sm font-semibold">Структура способов оплаты</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">Нажмите строку, чтобы применить или снять фильтр</div>
                </div>
                <PaymentTable data={data.by_payment} selected={payments} onSelect={(value) => toggle(payments, value, setPayments)} />
              </CardContent>
            </Card>
          </div>

          <Tabs defaultValue="stations">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <TabsList variant="line" className="h-9">
                <TabsTrigger value="stations">По АЗС <span className="text-[10px] text-muted-foreground">{data.by_station.length}</span></TabsTrigger>
                <TabsTrigger value="fuel">По топливу <span className="text-[10px] text-muted-foreground">{data.by_fuel.length}</span></TabsTrigger>
                <TabsTrigger value="matrix">Оплата × АЗС <span className="text-[10px] text-muted-foreground">{data.station_payment.length}</span></TabsTrigger>
                <TabsTrigger value="pivot">Сводная</TabsTrigger>
              </TabsList>
              <span className="text-[11px] text-muted-foreground">Строки в первых двух разрезах интерактивны</span>
            </div>
            <TabsContent value="stations">
              <Card><CardContent className="p-0"><BreakdownTable rows={stationRows} selected={stations} onSelect={(value) => toggle(stations, value, setStations)} empty="Нет продаж по АЗС" /></CardContent></Card>
            </TabsContent>
            <TabsContent value="fuel">
              <Card><CardContent className="p-0"><BreakdownTable rows={fuelRows} selected={fuels} onSelect={(value) => toggle(fuels, value, setFuels)} empty="Нет продаж по видам топлива" /></CardContent></Card>
            </TabsContent>
            <TabsContent value="matrix">
              <Card><CardContent className="p-0"><StationPaymentTable rows={data.station_payment} /></CardContent></Card>
            </TabsContent>
            {/* Готовые разрезы выше отвечают на частые вопросы, сводная - на остальные:
                канал → топливо → час, оплата → смена и любые другие комбинации. */}
            <TabsContent value="pivot">
              <PivotView
                source="transactions" storageKey="fuel-channels-pivot"
                defaultDims={['payment', 'station', 'fuel']}
                queryKey={{ dateFrom, dateTo, station: pivotStation, fuels: fk.fuelCodes }}
                fetchLeaves={(dims) => getFuelTxPivot({
                  dateFrom, dateTo, dims,
                  stationCode: pivotStation,
                  fuelCodes: fk.fuelCodes?.length ? fk.fuelCodes : undefined,
                })}
                dateFrom={dateFrom} dateTo={dateTo}
                scopeLabel={pivotStation ? `АЗС ${pivotStation}` : 'все АЗС'}
                hint="разрез по каналам оплаты: перетащите уровни или добавьте свои" />
            </TabsContent>
          </Tabs>

          <div className="flex items-start gap-2 rounded-md border border-border/70 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
            <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>Источник — нормализованные пооперационные реализации STS. Технические способы оплаты не скрываются; доля в матрице считается внутри каждой АЗС.</span>
          </div>
        </>
      ) : (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <div className="text-sm font-medium">Нет продаж по выбранному сочетанию фильтров</div>
          <div className="mt-1 text-xs text-muted-foreground">Снимите часть ограничений или проверьте наличие операций STS за период.</div>
          {hasLocalFilters ? <Button variant="outline" size="sm" className="mt-4" onClick={reset}>Сбросить фильтры раздела</Button> : null}
        </div>
      )}
    </div>
  )
}
