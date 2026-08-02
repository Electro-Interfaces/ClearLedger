import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BadgeRussianRuble,
  CircleCheck,
  DatabaseZap,
  Fuel,
  Gauge,
  Loader2,
  TrendingUp,
} from 'lucide-react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  getMarginDecisionDashboard,
  type CostingMargin,
  type CostingMarginLine,
} from '@/services/fuel/fuelMappingService'
import { CostingWorkspace } from '@/components/fuel/CostingWorkspace'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const price = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const percent = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const compact = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })

function delta(current: number, previous: number) {
  return previous > 0 ? ((current - previous) / previous) * 100 : null
}

function Delta({ value }: { value: number | null }) {
  if (value == null || Math.abs(value) < 0.05) return <span className="text-muted-foreground">без сравнения</span>
  const positive = value > 0
  const Icon = positive ? ArrowUpRight : ArrowDownRight
  return (
    <span className={positive ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>
      <Icon className="mr-0.5 inline h-3 w-3" />{positive ? '+' : ''}{percent.format(value)}% к прошлому периоду
    </span>
  )
}

function Metric({ label, value, hint, deltaValue }: {
  label: string
  value: string
  hint?: string
  deltaValue?: number | null
}) {
  return (
    <div className="min-w-0 px-4 py-3 first:pl-0 lg:border-r lg:last:border-r-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-xl font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="mt-1 min-h-4 text-[11px]">
        {deltaValue !== undefined ? <Delta value={deltaValue} /> : <span className="text-muted-foreground">{hint}</span>}
      </div>
    </div>
  )
}

function rowSignal(line: CostingMarginLine, networkMargin: number) {
  if (line.coverage_pct < 99.9) return { label: 'нет стоимости', className: 'border-amber-500/40 text-amber-700 dark:text-amber-300' }
  if (line.margin < 0) return { label: 'убыток', className: 'border-rose-500/40 text-rose-700 dark:text-rose-300' }
  if (networkMargin > 0 && line.margin_per_liter < networkMargin * 0.7) {
    return { label: 'ниже сети', className: 'border-amber-500/40 text-amber-700 dark:text-amber-300' }
  }
  return { label: 'в норме', className: 'border-emerald-500/30 text-emerald-700 dark:text-emerald-300' }
}

function MarginTable({ data, title }: { data: CostingMargin; title: string }) {
  const total = data.totals
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-2.5">
        <div>
          <div className="text-sm font-medium">{title}</div>
          <div className="text-[11px] text-muted-foreground">Маржа рассчитана только по литрам с заданной себестоимостью</div>
        </div>
        <Badge variant="outline" className="font-normal tabular-nums">
          {data.lines.length} строк · {percent.format(total.coverage_pct)}% покрытия
        </Badge>
      </div>
      <Table data-export-name={`Маржа — ${title}`}>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-48">Разрез</TableHead>
            <TableHead className="text-right">Объём</TableHead>
            <TableHead className="text-right">Цена продажи</TableHead>
            <TableHead className="text-right">Себестоимость FIFO</TableHead>
            <TableHead className="text-right">Маржа ₽/л</TableHead>
            <TableHead className="text-right">Маржа</TableHead>
            <TableHead className="text-right">Покрытие</TableHead>
            <TableHead className="text-right">Сигнал</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.lines.map((line) => {
            const signal = rowSignal(line, total.margin_per_liter)
            return (
              <TableRow key={line.label}>
                <TableCell className="font-medium">{line.label}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {number.format(line.liters)} л
                  <div className="text-[10px] text-muted-foreground">
                    {total.liters ? percent.format((line.liters / total.liters) * 100) : '0,0'}% объёма
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">{price.format(line.avg_sale_price)} ₽/л</TableCell>
                <TableCell className="text-right tabular-nums">
                  {line.liters_costed > 0 ? `${price.format(line.avg_cost_per_liter)} ₽/л` : '—'}
                </TableCell>
                <TableCell className={`text-right tabular-nums ${line.margin < 0 ? 'text-rose-600 dark:text-rose-400' : ''}`}>
                  {line.liters_costed > 0 ? `${price.format(line.margin_per_liter)} ₽` : '—'}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {line.liters_costed > 0 ? `${compact.format(line.margin)} ₽` : '—'}
                  {line.liters_costed > 0 && <div className="text-[10px] text-muted-foreground">{percent.format(line.margin_pct)}%</div>}
                </TableCell>
                <TableCell className="text-right tabular-nums">{percent.format(line.coverage_pct)}%</TableCell>
                <TableCell className="text-right">
                  <Badge variant="outline" className={signal.className}>{signal.label}</Badge>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function MarginTrend({ data }: { data: CostingMargin }) {
  const hasCost = data.totals.liters_costed > 0
  return (
    <div className="rounded-lg border p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium">Динамика цены и маржи</div>
          <div className="text-[11px] text-muted-foreground">Средневзвешенные значения по месяцам выбранного периода</div>
        </div>
        <div className="flex gap-3 text-[11px] text-muted-foreground">
          <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-500" />Цена продажи</span>
          {hasCost && <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-500" />Себестоимость</span>}
        </div>
      </div>
      <div className="h-72 min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={[...data.lines].reverse()} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
            <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} tickFormatter={(v) => `${v} ₽`} width={52} />
            <Tooltip
              contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
              formatter={(value, name) => [`${price.format(Number(value))} ₽/л`, name === 'avg_sale_price' ? 'Цена продажи' : name === 'avg_cost_per_liter' ? 'Себестоимость' : 'Маржа']}
            />
            {hasCost && <Bar dataKey="margin_per_liter" fill="hsl(var(--chart-2) / 0.22)" radius={[3, 3, 0, 0]} isAnimationActive={false} />}
            <Line dataKey="avg_sale_price" stroke="hsl(var(--chart-1))" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            {hasCost && <Line dataKey="avg_cost_per_liter" stroke="hsl(var(--warning))" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export function MarginDecisionPanel({ companyId, dateFrom, dateTo }: {
  companyId: string
  dateFrom: string
  dateTo: string
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [priceStep, setPriceStep] = useState(0.5)
  const requestedTab = searchParams.get('marginTab')
  const activeTab = requestedTab && ['fuel', 'station', 'station-fuel', 'trend', 'costing'].includes(requestedTab)
    ? requestedTab
    : 'fuel'
  // Вид нефтепродукта из общего фильтра: маржа АИ-95 и маржа ДТ — разные истории.
  const fk = useFuelKindFilter()
  const query = useQuery({
    queryKey: ['margin-decision-dashboard', companyId, dateFrom, dateTo, fk.key],
    queryFn: () => getMarginDecisionDashboard(companyId, dateFrom, dateTo, fk.fuelCodes),
  })

  const setActiveTab = (value: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('marginTab', value)
      return next
    }, { replace: true })
  }

  const focus = useMemo(() => {
    if (!query.data) return []
    const total = query.data.fuel.totals
    const readiness = query.data.readiness
    const out: { level: 'warning' | 'danger' | 'ok'; title: string; detail: string }[] = []
    if (total.coverage_pct < 99.9) {
      out.push({
        level: 'warning',
        title: readiness.uncosted_receipts > 0 ? 'Расчёт маржи неполный' : 'Не хватает входящего FIFO-остатка',
        detail: readiness.uncosted_receipts > 0
          ? `${number.format(readiness.uncosted_receipts)} ТТН без стоимости; ${number.format(total.liters_uncosted)} л исключено из расчёта.`
          : `Все положительные ТТН оценены, но ${number.format(total.liters_uncosted)} л продаж не обеспечены партиями в загруженной истории.`,
      })
    }
    const losses = query.data.station_fuel.lines.filter((line) => line.liters_costed > 0 && line.margin < 0)
    if (losses.length) {
      out.push({
        level: 'danger',
        title: `${losses.length} позиций с отрицательной маржой`,
        detail: `Совокупный убыток ${money.format(Math.abs(losses.reduce((sum, line) => sum + line.margin, 0)))} ₽.`,
      })
    }
    if (total.liters_costed > 0) {
      const effect = total.liters_costed * priceStep / 1.22
      out.push({
        level: 'ok',
        title: `Сценарий +${price.format(priceStep)} ₽/л`,
        detail: `Оценка прироста валовой маржи: +${money.format(effect)} ₽ без изменения объёма.`,
      })
    }
    return out
  }, [priceStep, query.data])

  if (query.isLoading) {
    return <div className="flex h-64 items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />Считаем FIFO по партиям…</div>
  }
  if (query.error || !query.data) {
    return (
      <div className="m-4 rounded-lg border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-700 dark:text-rose-300">
        Не удалось рассчитать маржу: {query.error instanceof Error ? query.error.message : 'нет данных'}
      </div>
    )
  }

  const data = query.data
  const total = data.fuel.totals
  const prev = data.previous.totals
  const hasCost = total.liters_costed > 0
  const hasMissingCosts = data.readiness.uncosted_receipts > 0
  const hasComparableMargin = hasCost && prev.liters_costed > 0
  const periodLabel = `${new Date(`${dateFrom}T00:00:00`).toLocaleDateString('ru-RU')} — ${new Date(`${dateTo}T00:00:00`).toLocaleDateString('ru-RU')}`

  return (
    <div className="space-y-4 p-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight">Маржа и цены</h2>
            <Badge variant="outline" className="font-normal">FIFO по партиям</Badge>
            {data.readiness.opening_balances > 0 && (
              <Badge variant="secondary" className="font-normal">
                Входящий остаток {compact.format(data.readiness.opening_balance_liters)} л
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Цена продажи, входная себестоимость и точки потери маржи · {periodLabel}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setActiveTab(activeTab === 'costing' ? 'fuel' : 'costing')}>
          {activeTab === 'costing'
            ? <><TrendingUp className="mr-1.5 h-4 w-4" />К анализу маржи</>
            : <><DatabaseZap className="mr-1.5 h-4 w-4" />Себестоимость партий</>}
        </Button>
      </header>

      <section className="grid border-y sm:grid-cols-2 lg:grid-cols-6">
        <Metric label="Выручка с НДС" value={`${compact.format(total.revenue)} ₽`} deltaValue={delta(total.revenue, prev.revenue)} />
        <Metric label="Продано" value={`${compact.format(total.liters)} л`} deltaValue={delta(total.liters, prev.liters)} />
        <Metric label="Средняя цена" value={`${price.format(total.avg_sale_price)} ₽/л`} deltaValue={delta(total.avg_sale_price, prev.avg_sale_price)} />
        <Metric label="Маржа FIFO" value={hasCost ? `${compact.format(total.margin)} ₽` : '—'} deltaValue={hasComparableMargin ? delta(total.margin, prev.margin) : undefined} hint="нужна себестоимость" />
        <Metric label="Маржа на литр" value={hasCost ? `${price.format(total.margin_per_liter)} ₽` : '—'} hint={hasCost ? `${percent.format(total.margin_pct)}% от выручки без НДС` : 'пока не рассчитана'} />
        <Metric
          label="Покрытие стоимости"
          value={`${percent.format(total.coverage_pct)}%`}
          hint={`${number.format(total.liters_costed)} л рассчитано · ${data.readiness.opening_balances} нач. позиций`}
        />
      </section>

      {total.coverage_pct < 99.9 && (
        <section className="rounded-lg border border-amber-500/35 bg-amber-500/[0.06] p-4">
          <div className="flex flex-wrap items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="min-w-60 flex-1">
              <div className="font-medium">
                {hasMissingCosts
                  ? (total.coverage_pct === 0 ? 'Себестоимость партий не заведена' : 'Себестоимость заведена не для всех ТТН')
                  : 'Не хватает входящего остатка для полного FIFO'}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {hasMissingCosts
                  ? <>Маржа не подменяется нулём: из расчёта исключено {number.format(total.liters_uncosted)} л. Заполните стоимость ещё для {number.format(data.readiness.uncosted_receipts)} ТТН — FIFO пересчитает экран автоматически.</>
                  : <>Стоимость задана для всех {number.format(data.readiness.costed_receipts)} положительных ТТН. Для {number.format(total.liters_uncosted)} л продаж в загруженной истории нет входящих партий — нужен начальный остаток или более ранние поступления.</>}
              </p>
              <Progress value={total.coverage_pct} className="mt-3 h-1.5 [&>div]:bg-amber-500" />
            </div>
            {hasMissingCosts && activeTab !== 'costing' && <Button size="sm" onClick={() => setActiveTab('costing')}>Заполнить стоимость<ArrowRight className="ml-1.5 h-4 w-4" /></Button>}
          </div>
        </section>
      )}

      <div className={activeTab === 'costing' ? '' : 'grid gap-4 2xl:grid-cols-[minmax(0,1fr)_300px]'}>
        <Tabs value={activeTab} onValueChange={setActiveTab} className="min-w-0">
          <TabsList className="mb-3 h-auto flex-wrap justify-start">
            <TabsTrigger value="fuel"><Fuel className="mr-1.5 h-3.5 w-3.5" />Топливо</TabsTrigger>
            <TabsTrigger value="station">АЗС</TabsTrigger>
            <TabsTrigger value="station-fuel">АЗС × топливо</TabsTrigger>
            <TabsTrigger value="trend"><TrendingUp className="mr-1.5 h-3.5 w-3.5" />Динамика</TabsTrigger>
            <TabsTrigger value="costing"><DatabaseZap className="mr-1.5 h-3.5 w-3.5" />Себестоимость</TabsTrigger>
          </TabsList>
          <TabsContent value="fuel"><MarginTable data={data.fuel} title="По видам топлива" /></TabsContent>
          <TabsContent value="station"><MarginTable data={data.station} title="По станциям" /></TabsContent>
          <TabsContent value="station-fuel"><MarginTable data={data.station_fuel} title="По станции и виду топлива" /></TabsContent>
          <TabsContent value="trend"><MarginTrend data={data.month} /></TabsContent>
          <TabsContent value="costing"><CostingWorkspace /></TabsContent>
        </Tabs>

        {activeTab !== 'costing' && <aside className="self-start rounded-lg border">
          <div className="border-b px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium"><Gauge className="h-4 w-4 text-muted-foreground" />Фокус менеджера</div>
            <p className="mt-1 text-[11px] text-muted-foreground">Приоритеты по текущему периоду</p>
          </div>
          <div className="divide-y">
            {focus.map((item) => {
              const Icon = item.level === 'danger' ? AlertTriangle : item.level === 'warning' ? DatabaseZap : CircleCheck
              const color = item.level === 'danger' ? 'text-rose-500' : item.level === 'warning' ? 'text-amber-500' : 'text-emerald-500'
              return (
                <div key={item.title} className="flex gap-2.5 p-4">
                  <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${color}`} />
                  <div><div className="text-sm font-medium">{item.title}</div><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.detail}</p></div>
                </div>
              )
            })}
            {focus.length === 0 && (
              <div className="flex gap-2.5 p-4"><CircleCheck className="mt-0.5 h-4 w-4 text-emerald-500" /><div><div className="text-sm font-medium">Критических сигналов нет</div><p className="mt-1 text-xs text-muted-foreground">Покрытие полное, отрицательная маржа не обнаружена.</p></div></div>
            )}
          </div>
          {hasCost && (
            <div className="border-t p-4">
              <div className="flex items-center gap-1.5 text-xs font-medium"><BadgeRussianRuble className="h-3.5 w-3.5" />Проверить изменение цены</div>
              <div className="mt-2 flex gap-1">
                {[0.1, 0.5, 1].map((step) => (
                  <Button key={step} size="sm" variant={priceStep === step ? 'secondary' : 'ghost'} className="h-7 flex-1 px-1 text-xs" onClick={() => setPriceStep(step)}>+{price.format(step)}</Button>
                ))}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">Оценка без эластичности спроса; изменение цены переведено в выручку без НДС.</p>
            </div>
          )}
        </aside>}
      </div>
    </div>
  )
}
