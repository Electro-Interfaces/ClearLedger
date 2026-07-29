import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  Activity, BookOpen, CircleCheckBig, Database, Download, Fuel, Loader2, MapPin, RefreshCw,
  TriangleAlert, Warehouse, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MultiSelectFilter } from '@/components/locations/fleet/MultiSelectFilter'
import { TankLedgerTabs } from '@/components/workspace/TankLedgerTabs'
import { ReceiptAnalysisPanel } from '@/components/workspace/ReceiptAnalysisPanel'
import { VarianceCausesPanel } from '@/components/workspace/VarianceCausesPanel'
import { InventoryPanel } from '@/components/workspace/InventoryPanel'
import { GoodsRouteBar, type GoodsStep } from '@/components/workspace/GoodsRouteBar'
import { useFilters } from '@/contexts/FilterContext'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import { useLocations } from '@/hooks/useLocations'
import { cn } from '@/lib/utils'
import {
  fmtLiters, fmtPct, getFuelBalance,
  type FuelBalanceLine,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

function locationStationCodes(locations: ReturnType<typeof useLocations>, selectedIds: string[]): number[] {
  if (selectedIds.length === 0) return []
  const selected = new Set(selectedIds)
  const codes = new Set<number>()
  for (const location of locations) {
    if (!selected.has(location.id)) continue
    let bound = false
    for (const binding of location.sourceBindings) {
      const code = Number(binding.config.station ?? binding.config.code ?? location.code)
      if (Number.isFinite(code) && code > 0) {
        codes.add(code)
        bound = true
      }
    }
    if (!bound) {
      const code = Number(location.code)
      if (Number.isFinite(code) && code > 0) codes.add(code)
    }
  }
  return [...codes].sort((a, b) => a - b)
}

function Metric({ label, value, hint, tone = 'default' }: {
  label: string
  value: string
  hint?: string
  tone?: 'default' | 'info' | 'danger' | 'surplus'
}) {
  return (
    <div className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn(
        'mt-1 truncate text-lg font-semibold tabular-nums',
        tone === 'info' && 'text-blue-400',
        tone === 'danger' && 'text-rose-400',
        tone === 'surplus' && 'text-sky-400',
      )}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

function varianceTone(value: number) {
  if (Math.abs(value) <= 1) return 'text-muted-foreground'
  return value > 0 ? 'text-rose-400' : 'text-sky-400'
}

/** Имя невязки КНИГИ (приход-расход по документам), а не расхождения с замером.
 *  Карточка звалась «Недостача»/«Излишек» — теми же словами, что расхождение книги с
 *  уровнемером на соседней вкладке, хотя величина другая: здесь не сошлись документы
 *  между собой, там документ не сошёлся с прибором. Менеджер читал арифметику
 *  сменных отчётов как потерю топлива и шёл искать утечку. */
function varianceName(value: number) {
  if (Math.abs(value) <= 1) return 'Книга сходится'
  return 'Невязка книги'
}

function SummaryTable({ rows, totals }: { rows: FuelBalanceLine[]; totals: FuelBalanceLine }) {
  if (rows.length === 0) return <Empty text="Нет данных по выбранному срезу" />
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-xs" aria-label="Баланс по АЗС и видам топлива">
        <thead>
          <tr className="border-b bg-muted/35 text-muted-foreground">
            <th className="p-2.5 text-left font-medium">АЗС · топливо</th>
            <th className="p-2.5 text-right font-medium">Начальный остаток</th>
            <th className="p-2.5 text-right font-medium">Поступления</th>
            <th className="p-2.5 text-right font-medium">Реализация</th>
            <th className="p-2.5 text-right font-medium">Конечный остаток</th>
            <th className="p-2.5 text-right font-medium">Отклонение</th>
            <th className="p-2.5 text-right font-medium">От реализации</th>
            <th className="p-2.5 text-right font-medium">Резервуары</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.station_code}:${row.fuel_code}:${row.label}`} className="border-b border-border/50 hover:bg-muted/25">
              <td className="p-2.5 font-medium">{row.label}</td>
              <td className="p-2.5 text-right tabular-nums text-muted-foreground">{fmtLiters(row.balance_start_liters)}</td>
              <td className="p-2.5 text-right tabular-nums text-blue-400">{fmtLiters(row.receipts_liters)}</td>
              <td className="p-2.5 text-right tabular-nums">{fmtLiters(row.sales_liters)}</td>
              <td className="p-2.5 text-right tabular-nums text-muted-foreground">{fmtLiters(row.balance_end_liters)}</td>
              <td className={cn('p-2.5 text-right font-medium tabular-nums', varianceTone(row.variance_liters))}>
                {fmtLiters(row.variance_liters)}
              </td>
              <td className={cn('p-2.5 text-right tabular-nums', varianceTone(row.variance_liters))}>{fmtPct(row.variance_pct)}</td>
              <td className="p-2.5 text-right tabular-nums">
                {row.tanks_count}
                {row.continuity_breaks > 0 ? <span className="ml-1 text-amber-400">· {row.continuity_breaks} разр.</span> : null}
              </td>
            </tr>
          ))}
          <tr className="bg-muted/45 font-semibold">
            <td className="p-2.5">Итого</td>
            <td className="p-2.5 text-right tabular-nums">{fmtLiters(totals.balance_start_liters)}</td>
            <td className="p-2.5 text-right tabular-nums">{fmtLiters(totals.receipts_liters)}</td>
            <td className="p-2.5 text-right tabular-nums">{fmtLiters(totals.sales_liters)}</td>
            <td className="p-2.5 text-right tabular-nums">{fmtLiters(totals.balance_end_liters)}</td>
            <td className={cn('p-2.5 text-right tabular-nums', varianceTone(totals.variance_liters))}>{fmtLiters(totals.variance_liters)}</td>
            <td className={cn('p-2.5 text-right tabular-nums', varianceTone(totals.variance_liters))}>{fmtPct(totals.variance_pct)}</td>
            <td className="p-2.5 text-right tabular-nums">{totals.tanks_count}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="p-10 text-center text-sm text-muted-foreground">{text}</div>
}

/**
 * Виды панели = пункты «Товародвижения», которые раньше были её табами.
 *
 * Предмет у них разный (претензия поставщику · поиск причины · ведомость бухгалтеру),
 * поэтому в меню они стоят отдельными пунктами. Панель осталась одна: фильтр станций
 * и топлива, расчёт баланса и шапка с итогами нужны всем четырём одинаково — иначе
 * пришлось бы четырежды повторить фильтр и четырежды считать одно и то же.
 */
export type FuelBalanceView = 'balance' | 'intake' | 'variances' | 'inventory'

const VIEW_TABS: Record<FuelBalanceView, string[]> = {
  balance: ['journal', 'book_tanks', 'summary'],
  intake: ['receipts'],
  variances: ['book_issues', 'causes'],
  inventory: ['inventory'],
}

const VIEW_HEAD: Record<FuelBalanceView, { title: string; hint: string }> = {
  balance: {
    title: 'Контроль топливного баланса',
    hint: 'Первый остаток + поступления − реализация − последний остаток · расчёт по каждому резервуару',
  },
  intake: {
    title: 'Приёмка и сливы',
    hint: 'Ошибки слива бензовозов по каждой ТТН · считается по массе, а не по объёму накладной',
  },
  variances: {
    title: 'Расхождения книги и факта',
    hint: 'Замечания по стыку смен и поведение расхождения во времени: дрейф, скачок, шум',
  },
  inventory: {
    title: 'Инвентаризация резервуаров',
    hint: 'Ведомость корректировок книги на фактический замер: излишки к оприходованию, недостачи к списанию',
  },
}

export function FuelBalancePanel({ companyId, dateFrom, dateTo, view = 'balance' }: {
  companyId: string
  dateFrom: string
  dateTo: string
  view?: FuelBalanceView
}) {
  const { stationCode, locationIds } = useFilters()
  const fk = useFuelKindFilter()
  const locations = useLocations()
  const [stations, setStations] = useState<string[]>([])
  const [fuels, setFuels] = useState<string[]>([])
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
  const scopeMismatch = workspaceStations.includes(-1)

  useEffect(() => setStations([]), [workspaceKey])
  useEffect(() => setFuels([]), [dateFrom, dateTo])

  const effectiveStations = stations.length > 0 ? stations.map(Number) : workspaceStations
  // Вид топлива: фильтр экрана сужает ВНУТРИ выбора из шапки рабочей области.
  const effectiveFuels = fuels.length > 0
    ? fuels.map(Number).filter(Number.isFinite)
    : (fk.fuelCodes ?? [])
  const query = useQuery({
    queryKey: ['analytics-fuelbalance-v2', companyId, dateFrom, dateTo, effectiveStations, effectiveFuels],
    queryFn: () => getFuelBalance({
      companyId,
      dateFrom,
      dateTo,
      groupBy: 'station_fuel',
      stationCodes: effectiveStations.length ? effectiveStations : undefined,
      fuelCodes: effectiveFuels.length ? effectiveFuels : undefined,
    }),
    placeholderData: keepPreviousData,
  })

  const data = query.data
  const stationOptions = useMemo(() => {
    if (scopeMismatch) return []
    const scope = new Set(workspaceStations.filter((code) => code > 0))
    return (data?.dimensions.stations ?? [])
      .filter((station) => scope.size === 0 || scope.has(station.code))
      .map((station) => ({ value: String(station.code), label: station.name }))
  }, [data?.dimensions.stations, scopeMismatch, workspaceStations])
  const fuelOptions = (data?.dimensions.fuels ?? []).map((fuel) => ({ value: String(fuel.code), label: fuel.name }))
  const hasFilters = stations.length > 0 || fuels.length > 0
  const reset = () => { setStations([]); setFuels([]) }

  async function exportXlsx() {
    if (!data) return
    setExporting(true)
    try {
      const XLSX = await import('xlsx')
      const workbook = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(data.lines.map((row) => ({
        'АЗС · топливо': row.label,
        'Начальный остаток, л': row.balance_start_liters,
        'Поступления, л': row.receipts_liters,
        'Реализация, л': row.sales_liters,
        'Конечный остаток, л': row.balance_end_liters,
        'Отклонение, л': row.variance_liters,
        'Отклонение, %': row.variance_pct,
        'Резервуары': row.tanks_count,
      }))), 'Свод')
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(data.tanks.map((row) => ({
        'АЗС': row.station_name,
        'Резервуар': row.tank_number,
        'Топливо': row.fuel_name,
        'Первая смена': row.first_shift,
        'Последняя смена': row.last_shift,
        'Начальный остаток, л': row.balance_start_liters,
        'Поступления, л': row.receipts_liters,
        'Реализация, л': row.sales_liters,
        'Конечный остаток, л': row.balance_end_liters,
        'Отклонение, л': row.variance_liters,
        'Разрывы': row.continuity_breaks,
      }))), 'Резервуары')
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(data.issues.map((row) => ({
        'Тип': row.type === 'fuel_change' ? 'Смена топлива' : 'Разрыв остатков',
        'АЗС': row.station_name,
        'Резервуар': row.tank_number,
        'Топливо': row.fuel_name,
        'Предыдущая смена': row.previous_shift,
        'Текущая смена': row.current_shift,
        'Предыдущий конец, л': row.previous_end_liters,
        'Текущее начало, л': row.current_start_liters,
        'Разрыв, л': row.gap_liters,
      }))), 'Контроль разрывов')
      XLSX.writeFile(workbook, `toplivnyj_balans_${dateFrom}_${dateTo}.xlsx`)
    } finally {
      setExporting(false)
    }
  }

  if (query.isLoading) {
    return <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Расчёт топливного баланса…</div>
  }
  if (query.error) return <div className="p-6 text-sm text-destructive">Не удалось рассчитать баланс: {String(query.error)}</div>
  if (!data) return null

  const variance = data.totals.variance_liters
  const issues = data.integrity.issues_total
  // Шаг маршрута: у панели один вид на пункт, кроме `balance` — он и есть «Контроль».
  const step: GoodsStep = view === 'balance' ? 'tanks' : view
  return (
    <div className="space-y-4 p-4">
      {/* Порядок работы разделa: пять пунктов — это один сценарий, а не пять экранов. */}
      <GoodsRouteBar
        current={step}
        counters={{
          tanks: issues > 0 ? { value: issues, unit: 'замеч.', alarm: true } : null,
          variances: data.integrity.continuity_breaks > 0
            ? { value: data.integrity.continuity_breaks, unit: 'разр.', alarm: true } : null,
          inventory: data.integrity.unique_tanks
            ? { value: data.integrity.unique_tanks, unit: 'рез.' } : null,
        }}
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold">{VIEW_HEAD[view].title}</h2>
            {query.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label="Обновление данных" /> : null}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{VIEW_HEAD[view].hint}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', query.isFetching && 'animate-spin')} />Обновить
          </Button>
          {/* Выгрузка — книга остатков (свод · резервуары · разрывы): она про баланс,
              на «Приёмке» и «Инвентаризации» отдала бы не то, что человек видит. */}
          {view === 'balance' && (
            <Button variant="outline" size="sm" className="h-8" onClick={exportXlsx} disabled={exporting || data.tanks.length === 0}>
              {exporting ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1.5 h-3.5 w-3.5" />}Экспорт
            </Button>
          )}
        </div>
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
        <MultiSelectFilter label="Топливо" icon={Fuel} options={fuelOptions} selected={fuels} onChange={setFuels} />
        {hasFilters ? <Button variant="ghost" size="sm" className="h-9 px-2 text-xs" onClick={reset}><X className="mr-1 h-3.5 w-3.5" />Сбросить</Button> : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {scopeMismatch ? 'Источник STS не входит в выбранную область учёта' : workspaceStations.length > 0 ? `Рабочий контур: ${workspaceStations.length} АЗС` : 'Рабочий контур: вся сеть'}
        </span>
      </div>

      {/* Пустые резервуары глушат только то, что из них считается. «Приёмка» живёт на
          накладных, «Инвентаризация» на замерах — им пустой баланс не мешает, а раньше
          оба экрана показывали «нет данных по резервуарам» и выглядели сломанными. */}
      {data.tanks.length === 0 && (view === 'balance' || view === 'variances')
        ? <Card><Empty text="Нет данных по резервуарам за выбранный период и фильтры" /></Card> : (
        <>
          <Card className="gap-0 py-0">
            <CardContent className="grid grid-cols-2 p-0 md:grid-cols-4 xl:grid-cols-7">
              <Metric label="Начальный остаток" value={fmtLiters(data.totals.balance_start_liters)} hint="Первая смена периода" />
              <Metric label="Поступления" value={fmtLiters(data.totals.receipts_liters)} hint="Сливы по сменам" tone="info" />
              <Metric label="Реализация" value={fmtLiters(data.totals.sales_liters)} hint={`${data.shifts_count} смен`} />
              <Metric label="Конечный остаток" value={fmtLiters(data.totals.balance_end_liters)} hint="Последняя смена периода" />
              <Metric label={varianceName(variance)} value={fmtLiters(variance)} hint="приход − расход по документам, не замер" tone={Math.abs(variance) <= 1 ? 'default' : variance > 0 ? 'danger' : 'surplus'} />
              <Metric label="Резервуары" value={nf0.format(data.integrity.unique_tanks)} hint={`${nf0.format(data.integrity.records_count)} сменных записей`} />
              <Metric label="Контроль смен" value={nf0.format(data.integrity.continuity_checks)} hint={`${issues} замечаний`} />
            </CardContent>
          </Card>

          {/* Плашка целостности — про стык смен: она объясняет цифры баланса и
              расхождений. На «Приёмке» и «Инвентаризации» это чужой сюжет. */}
          {(view === 'balance' || view === 'variances') && (
            <div className={cn(
              'flex items-start gap-3 rounded-lg border px-4 py-3 text-sm',
              issues === 0 ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-amber-500/35 bg-amber-500/5',
            )}>
              {issues === 0 ? <CircleCheckBig className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" /> : <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />}
              <div className="min-w-0">
                <div className="font-medium">{issues === 0 ? 'Последовательность остатков подтверждена' : `Найдены замечания: ${issues}`}</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Проверено переходов между сменами: {nf0.format(data.integrity.continuity_checks)}. Допуск: ±{nf1.format(data.method.continuity_tolerance_liters)} л.
                  {issues > 0 ? ` Суммарный разрыв: ${fmtLiters(data.integrity.continuity_gap_liters)}; смен топлива: ${data.integrity.fuel_changes}.` : ''}
                </div>
              </div>
            </div>
          )}

          {/* Виды раздела. Табами остались только разрезы ОДНОЙ книги остатков:
              журнал по сменам (стык смен, книга ↔ факт), тот же журнал по резервуарам
              и обзорный свод «АЗС × топливо». Приёмка, причины и инвентаризация ушли
              в свои пункты меню — у них другой предмет и другой адресат.
              Единственный вид ряда вкладок не рисует: заголовок уже сказал, где мы. */}
          <Tabs defaultValue={VIEW_TABS[view][0]}>
            {VIEW_TABS[view].length > 1 && (
              <TabsList variant="line" className="h-9">
                {VIEW_TABS[view].includes('journal') && <TabsTrigger value="journal"><BookOpen className="mr-1.5 h-3.5 w-3.5" />Журнал по сменам</TabsTrigger>}
                {VIEW_TABS[view].includes('book_tanks') && <TabsTrigger value="book_tanks"><Warehouse className="mr-1.5 h-3.5 w-3.5" />По резервуарам <span className="ml-1 text-muted-foreground">{data.tanks.length}</span></TabsTrigger>}
                {VIEW_TABS[view].includes('book_issues') && <TabsTrigger value="book_issues"><TriangleAlert className="mr-1.5 h-3.5 w-3.5" />Замечания</TabsTrigger>}
                {VIEW_TABS[view].includes('causes') && <TabsTrigger value="causes"><Activity className="mr-1.5 h-3.5 w-3.5" />Причины</TabsTrigger>}
                {VIEW_TABS[view].includes('summary') && <TabsTrigger value="summary"><Database className="mr-1.5 h-3.5 w-3.5" />АЗС × топливо <span className="ml-1 text-muted-foreground">{data.lines.length}</span></TabsTrigger>}
              </TabsList>
            )}
            <TabsContent value="journal" className="mt-3">
              <TankLedgerTabs view="journal"
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                stationCodes={effectiveStations}
                fuelCodes={effectiveFuels}
              />
            </TabsContent>
            <TabsContent value="book_tanks" className="mt-3">
              <TankLedgerTabs view="tanks"
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                stationCodes={effectiveStations}
                fuelCodes={effectiveFuels}
              />
            </TabsContent>
            <TabsContent value="book_issues" className="mt-3">
              <TankLedgerTabs view="issues"
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                stationCodes={effectiveStations}
                fuelCodes={effectiveFuels}
              />
            </TabsContent>
            <TabsContent value="receipts" className="mt-3">
              <ReceiptAnalysisPanel
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                stationCodes={effectiveStations}
                fuelCodes={effectiveFuels}
              />
            </TabsContent>
            <TabsContent value="causes" className="mt-3">
              <VarianceCausesPanel
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                stationCodes={effectiveStations}
                fuelCodes={effectiveFuels}
              />
            </TabsContent>
            <TabsContent value="inventory" className="mt-3">
              <InventoryPanel
                companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                stationCodes={effectiveStations}
                fuelCodes={effectiveFuels}
              />
            </TabsContent>
            <TabsContent value="summary" className="mt-3"><Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0"><SummaryTable rows={data.lines} totals={data.totals} /></CardContent></Card></TabsContent>
          </Tabs>

          {(view === 'balance' || view === 'variances') && (
            <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
              В расчёте используются первый и последний остатки каждого физического резервуара за период. Положительное отклонение — недостача, отрицательное — излишек. Нормы естественной убыли и ручные корректировки пока не применяются.
            </div>
          )}
        </>
      )}
    </div>
  )
}
