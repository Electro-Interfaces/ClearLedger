/**
 * «Реализация» — управленческий анализ реализаций топлива (fuel, ГИГ).
 * Табы: Разрезы · Время и загрузка · Динамика (тренд) · Сравнение периодов
 * (+ блок когорт «Новые карты»). Данные — /api/fuel/analytics/fills*.
 *
 * Зеркало ЭЗС-«Сессий» (ChargeSessionsPanel) в топливных единицах: литры,
 * ₽/л, виды оплаты STS. Общий тумблер сегмента (Все/Розница/Корпоратив/Онлайн)
 * прокидывается контекстом во все запросы панели.
 */

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Loader2, ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-react'
import { KpiCard } from './analytics/AnalyticsPeriodPicker'
import { MultiPeriodPicker } from './analytics/PeriodRangePicker'
import { ChargeChart, ChartControls, useChartView } from './analytics/ChargeChart'
import { type Period, buildMoM, isoLocal } from './analytics/periodPresets'
import { useTabParams } from '@/hooks/useTabParams'
import { useFilters } from '@/contexts/FilterContext'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import { getFuelTxPivot } from '@/services/fuel/fuelMappingService'
import { PivotView } from './PivotView'
import { ExportButton } from './analytics/ExportButton'
import { useScopeSubtitle } from '@/hooks/useScopeReset'
import { useLocations } from '@/hooks/useLocations'
import { scopeStationCodes } from '@/services/locationService'
import { PanelViewTabs } from './PanelViewTabs'
import { ViewParamsBar } from './ViewParamsBar'
import { HorizonControl } from './HorizonControl'
import { FuelDrillDialog, exportFuelPivot } from './FuelDrillDialog'
import {
  getFuelFills, getFuelTimeseries, getFuelSlice, getFuelCompareMulti, getFuelHeatmap,
  getFuelNewCards, getFuelNewCardsList,
  FUEL_METRIC_LABELS, fmtFuelMetric, fmtFuelMetricCompact, fuelChartFormat, isFuelRatio, fmtRub0,
  type FuelGroupBy, type FuelMetric, type FuelBucket, type FuelSegment, type FuelNarrow,
  type FuelFillsLine, type FuelTimeseriesResponse, type FuelNewCardsInterval,
} from '@/services/fuelSalesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет реализаций за период' }: { text?: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

/** Атрибуты на <table> с сырыми ЧИСЛАМИ для выгрузки в Excel. */
function exportRows(name: string, columns: string[], rows: (string | number | null)[][]) {
  return { 'data-export-name': name, 'data-export-rows': JSON.stringify({ columns, rows }) }
}
function ExportOnlyTable({ name, columns, rows }: { name: string; columns: string[]; rows: (string | number | null)[][] }) {
  return <table hidden aria-hidden {...exportRows(name, columns, rows)} />
}

// ── сегмент бизнеса: общий тумблер панели ──
type SegmentSel = 'all' | 'retail' | 'corp' | 'online'
const FuelSegmentCtx = createContext<SegmentSel>('all')
const SEGMENT_VAL: Record<SegmentSel, FuelSegment | undefined> = {
  all: undefined, retail: 'retail', corp: 'corp', online: 'online',
}

function SegmentToggle({ value, onChange }: { value: SegmentSel; onChange: (v: SegmentSel) => void }) {
  const opts: { v: SegmentSel; label: string }[] = [
    { v: 'all', label: 'Все' }, { v: 'retail', label: 'Розница' },
    { v: 'corp', label: 'Корпоратив' }, { v: 'online', label: 'Онлайн' },
  ]
  return (
    <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5" title="Фильтр по сегменту продаж">
      {opts.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${value === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/**
 * Сужение всех запросов панели: сегмент (тумблер) + КОНТУР рабочей области.
 *
 * Контур для профиля fuel — это выбранные точки и регионы («Область учёта»),
 * их резолвим в коды станций STS. Источник STS (`stationCode`) — отдельное
 * измерение: если он задан вместе с областью, берём пересечение, иначе тот из
 * двух, что задан. Раньше читался только `stationCode`, поэтому выбор точек и
 * регионов на «Реализации» не влиял вообще.
 */
function useFuelNarrow(): FuelNarrow & { key: string } {
  const { stationCode, locationIds, regionIds, fuelCodes } = useFilters()
  const locations = useLocations()
  const seg = useContext(FuelSegmentCtx)
  const segment = SEGMENT_VAL[seg]

  const scopeCodes = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds),
    [locations, locationIds, regionIds],
  )

  const codeNum = stationCode && stationCode !== 'all' ? Number(stationCode) : NaN
  const srcCode = Number.isFinite(codeNum) ? codeNum : null

  const stationCodes = srcCode != null
    ? (scopeCodes.length === 0 || scopeCodes.includes(srcCode) ? [srcCode] : [])
    : (scopeCodes.length > 0 ? scopeCodes : undefined)

  // Вид топлива — измерение общего фильтра, а не экрана: сузили в шапке — сузилось
  // всё, включая разрезы, динамику, сравнение периодов и когорты карт.
  const fuels = fuelCodes.map(Number).filter(Number.isFinite)

  return {
    stationCodes, segment,
    fuelCodes: fuels.length ? fuels : undefined,
    key: `${stationCode ?? ''}|${scopeCodes.join(',')}|${seg}|${fuels.join(',')}`,
  }
}
type Narrow = ReturnType<typeof useFuelNarrow>

// ── управляющие селекторы ──
const METRIC_OPTS: FuelMetric[] = ['amount', 'liters', 'fills', 'avg_check', 'avg_fill', 'avg_price']
const GROUP_OPTS: { value: FuelGroupBy; label: string }[] = [
  { value: 'station', label: 'Станция' },
  { value: 'fuel', label: 'Вид топлива' },
  { value: 'channel', label: 'Канал оплаты' },
  { value: 'pay_type', label: 'Вид оплаты (STS)' },
  { value: 'segment', label: 'Сегмент' },
  { value: 'hour', label: 'Час суток' },
  { value: 'weekday', label: 'День недели' },
  { value: 'shift', label: 'Смена' },
  { value: 'card', label: 'Карта' },
]
const SERIES_OPTS: { value: string; label: string }[] = [
  { value: '__net__', label: 'Вся сеть' },
  { value: 'station', label: 'По станциям' },
  { value: 'fuel', label: 'По топливу' },
  { value: 'channel', label: 'По каналам' },
  { value: 'pay_type', label: 'По видам оплаты' },
  { value: 'segment', label: 'По сегментам' },
]
const BUCKET_OPTS: { value: FuelBucket; label: string }[] = [
  { value: 'day', label: 'День' }, { value: 'week', label: 'Неделя' },
  { value: 'decade', label: 'Декада' }, { value: 'month', label: 'Месяц' },
  { value: 'quarter', label: 'Квартал' },
]
const GROUP_LABELS: Record<string, string> = Object.fromEntries(GROUP_OPTS.map((o) => [o.value, o.label]))
const ROWS_OPTS: { value: number; label: string }[] = [
  { value: 10, label: 'Топ-10' }, { value: 25, label: 'Топ-25' },
  { value: 50, label: 'Топ-50' }, { value: 1000, label: 'Все' },
]

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}
function MetricSelect({ value, onChange }: { value: FuelMetric; onChange: (m: FuelMetric) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as FuelMetric)}>
      <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{METRIC_OPTS.map((m) => <SelectItem key={m} value={m} className="text-xs">{FUEL_METRIC_LABELS[m]}</SelectItem>)}</SelectContent>
    </Select>
  )
}
function GroupSelect({ value, onChange }: { value: FuelGroupBy; onChange: (v: FuelGroupBy) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as FuelGroupBy)}>
      <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{GROUP_OPTS.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
    </Select>
  )
}
function SeriesSelect({ value, onChange, withNet }: { value: string; onChange: (v: string) => void; withNet?: boolean }) {
  const opts = withNet ? SERIES_OPTS : SERIES_OPTS.filter((o) => o.value !== '__net__')
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{opts.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
    </Select>
  )
}
function BucketSelect({ value, onChange }: { value: FuelBucket; onChange: (v: FuelBucket) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as FuelBucket)}>
      <SelectTrigger className="h-7 w-[120px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{BUCKET_OPTS.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
    </Select>
  )
}

/** Мини-график тренда в строке таблицы (SVG-полилиния). */
function Sparkline({ values }: { values: (number | null)[] }) {
  const w = 60, h = 16
  const vals = values.map((v) => v ?? 0)
  if (vals.length < 2) return <span className="text-muted-foreground/40">—</span>
  const max = Math.max(...vals), min = Math.min(...vals)
  const range = max - min || 1
  const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`).join(' ')
  const up = vals[vals.length - 1] >= vals[0]
  return (
    <svg width={w} height={h} className="inline-block align-middle overflow-visible">
      <polyline points={pts} fill="none" stroke={up ? 'hsl(152, 69%, 45%)' : 'hsl(0, 84%, 60%)'} strokeWidth="1" />
    </svg>
  )
}

function FillKpis({ t }: { t: FuelFillsLine }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <KpiCard label="Выручка" value={fmtFuelMetricCompact('amount', t.amount) + ' ₽'} accent="success" />
      <KpiCard label="Объём" value={nf0.format(t.liters) + ' л'} accent="info" />
      <KpiCard label="Реализаций" value={nf0.format(t.fills)} />
      <KpiCard label="Ср. цена" value={fmtFuelMetric('avg_price', t.avg_price)} />
      <KpiCard label="Средний чек" value={fmtFuelMetric('avg_check', t.avg_check)} />
      <KpiCard label="Ср. заправка" value={fmtFuelMetric('avg_fill', t.avg_fill)} />
      <KpiCard label="Станций" value={nf0.format(t.stations)} />
      <KpiCard label="Карт" value={nf0.format(t.cards)} hint="уникальных за период" />
    </div>
  )
}

function useFills(companyId: string, dateFrom: string, dateTo: string, groupBy: FuelGroupBy) {
  const n = useFuelNarrow()
  return useQuery({
    queryKey: ['fuel-fills', groupBy, companyId, dateFrom, dateTo, n.key],
    queryFn: () => getFuelFills({ companyId, dateFrom, dateTo, groupBy, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
  })
}

/* ────────────────────────── Разрезы ────────────────────────── */

/** Разрезы со спарклайнами (для содержательных групп — не времени/карт). */
const SPARK_GROUPS: FuelGroupBy[] = ['station', 'fuel', 'channel', 'pay_type', 'segment']

function FillsBreakdown({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('fuel_fills/breakdown', {
    group: 'station' as FuelGroupBy, rows: 1000,
  })
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useFills(companyId, period.from, period.to, p.group)
  const n = useFuelNarrow()
  const withSpark = SPARK_GROUPS.includes(p.group)
  const spark = useQuery({
    queryKey: ['fuel-slice-spark', companyId, period.from, period.to, p.group, n.key],
    queryFn: () => getFuelSlice({ companyId, dateFrom: period.from, dateTo: period.to, bucket: 'month', groupBy: p.group, metric: 'amount', topN: 1000, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
    enabled: withSpark,
  })
  const sparkMap = useMemo(() => {
    const m: Record<string, (number | null)[]> = {}
    spark.data?.lines.forEach((l) => { m[l.label] = l.values })
    return m
  }, [spark.data])
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'amount', dir: 'desc' })
  // Строка разреза больше не тупик: клик раскрывает её встречными разрезами.
  const [drill, setDrill] = useState<{ key: string; label: string } | null>(null)
  const lines = useMemo(() => {
    const src = data?.lines ?? []
    const dir = sort.dir === 'asc' ? 1 : -1
    const sorted = [...src].sort((a, b) => (sort.key === 'label'
      ? dir * a.label.localeCompare(b.label, 'ru')
      : dir * (((a as unknown as Record<string, number>)[sort.key] ?? 0) - ((b as unknown as Record<string, number>)[sort.key] ?? 0))))
    return p.rows > 0 ? sorted.slice(0, p.rows) : sorted
  }, [data, sort, p.rows])
  if (isLoading) return <Loading />
  if (!data || data.lines.length === 0) return <Empty />
  const t = data.totals
  const col = GROUP_LABELS[p.group] ?? 'Разрез'
  const showCards = ['channel', 'pay_type', 'segment', 'station'].includes(p.group)
  const exCols = [col, 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %', 'Ср. чек, ₽', 'Ср. заправка, л', 'Цена, ₽/л', ...(showCards ? ['Карт'] : [])]
  const exData: (string | number)[][] = [
    ...lines.map((l) => [l.label, l.fills, l.liters, l.amount, l.share_pct, l.avg_check, l.avg_fill, l.avg_price, ...(showCards ? [l.cards] : [])]),
    ['Итого', t.fills, t.liters, t.amount, 100, t.avg_check, t.avg_fill, t.avg_price, ...(showCards ? [t.cards] : [])],
  ]
  const toggle = (key: string) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }))
  const H = ({ k, children, left }: { k: string; children: ReactNode; left?: boolean }) => {
    const active = sort.key === k
    const Ico = active ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    return (
      <th aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} className={`p-2 font-medium ${left ? 'text-left' : 'text-right'}`}>
        <button onClick={() => toggle(k)} title="Сортировать по столбцу"
          className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${left ? '' : 'flex-row-reverse'} ${active ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{children}</span>
          <Ico className={`h-3 w-3 shrink-0 ${active ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </th>
    )
  }
  const maxShare = Math.max(...data.lines.map((l) => l.share_pct), 0.01)
  return (
    <div className="p-4 space-y-4">
      <ViewParamsBar>
        <Field label="Разрез"><GroupSelect value={p.group} onChange={(g) => patch({ group: g })} /></Field>
        <Field label="Строк">
          <Select value={String(p.rows)} onValueChange={(v) => patch({ rows: Number(v) })}>
            <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{ROWS_OPTS.map((o) => <SelectItem key={o.value} value={String(o.value)} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        {/* Сводная — матрица «разрез × месяцы»: экспорт видимой таблицы отдаёт
            только выбранный период, а управленцу нужна динамика по строкам. */}
        <Field label="Выгрузка">
          <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
            onClick={() => exportFuelPivot({
              companyId, dateFrom: period.from, dateTo: period.to, groupBy: p.group,
              narrow: { stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment },
              title: `Реализация_${col}`,
            })}>
            Сводная × месяцы
          </Button>
        </Field>
      </ViewParamsBar>
      {drill && (
        <FuelDrillDialog open onClose={() => setDrill(null)}
          companyId={companyId} dateFrom={period.from} dateTo={period.to}
          dim={p.group} dimVal={drill.key} label={`${col}: ${drill.label}`}
          narrow={{ stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }} />
      )}
      <FillKpis t={t} />
      {data.truncated > 0 && (
        <div className="text-[11px] text-muted-foreground">Показан топ по обороту; ещё {nf0.format(data.truncated)} строк не выведено (сузьте период или фильтры).</div>
      )}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs" {...exportRows(col, exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <H k="label" left>{col}</H>
                <H k="fills">Реализаций</H>
                <H k="liters">Литры</H>
                <H k="amount">Выручка</H>
                <H k="share_pct">Доля</H>
                <H k="avg_check">Ср. чек</H>
                <H k="avg_fill">Ср. заправка</H>
                <H k="avg_price">₽/л</H>
                {showCards && <H k="cards">Карт</H>}
                {withSpark && <th className="p-2 font-medium text-right whitespace-nowrap">Тренд ₽</th>}
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.key} className="cursor-pointer border-b border-border/30 hover:bg-muted/30"
                  onClick={() => setDrill({ key: l.key, label: l.label })}
                  title="Открыть строку по другим разрезам">
                  <td className="p-2 font-medium truncate max-w-[240px]">{l.label}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(l.fills)}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(l.liters)}</td>
                  <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', l.amount)}</td>
                  <td className="p-2 text-right font-mono">
                    <div className="relative">
                      <div className="absolute inset-y-0 right-0 bg-primary/15 rounded-sm" style={{ width: `${Math.min(100, l.share_pct / maxShare * 100)}%` }} />
                      <span className="relative">{l.share_pct.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtFuelMetricCompact('avg_check', l.avg_check)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(l.avg_fill)}</td>
                  <td className="p-2 text-right font-mono">{l.avg_price.toFixed(2)}</td>
                  {showCards && <td className="p-2 text-right font-mono text-muted-foreground">{l.cards ? nf0.format(l.cards) : '—'}</td>}
                  {withSpark && <td className="p-2 text-right"><Sparkline values={sparkMap[l.label] ?? []} /></td>}
                </tr>
              ))}
              <tr className="bg-muted/60 font-medium">
                <td className="p-2">Итого</td>
                <td className="p-2 text-right font-mono">{nf0.format(t.fills)}</td>
                <td className="p-2 text-right font-mono">{nf0.format(t.liters)}</td>
                <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', t.amount)}</td>
                <td className="p-2 text-right font-mono">100%</td>
                <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('avg_check', t.avg_check)}</td>
                <td className="p-2 text-right font-mono">{nf1.format(t.avg_fill)}</td>
                <td className="p-2 text-right font-mono">{t.avg_price.toFixed(2)}</td>
                {showCards && <td className="p-2 text-right font-mono">{t.cards ? nf0.format(t.cards) : '—'}</td>}
                {withSpark && <td className="p-2" />}
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────── Время и загрузка ────────────────────── */

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']  // isodow 1..7
const HEAT_METRICS: FuelMetric[] = ['fills', 'liters', 'amount', 'avg_check']

function FuelHeatmap({ companyId, dateFrom, dateTo, metric }: {
  companyId: string; dateFrom: string; dateTo: string; metric: FuelMetric
}) {
  const n = useFuelNarrow()
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-heatmap', companyId, dateFrom, dateTo, metric, n.key],
    queryFn: () => getFuelHeatmap({ companyId, dateFrom, dateTo, metric, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
  })
  if (isLoading) return <Loading />
  if (!data || data.cells.length === 0) return <Empty />
  const grid: Record<string, number> = {}
  let max = 0
  data.cells.forEach((c) => { grid[`${c.hour}-${c.weekday}`] = c.value; if (c.value > max) max = c.value })
  const color = (v: number) => (v ? `hsl(var(--chart-1) / ${0.1 + 0.9 * (v / max)})` : 'hsl(var(--muted) / 0.3)')

  const items: ReactNode[] = [<div key="corner" />]
  WEEKDAYS.forEach((w, i) => items.push(<div key={`wd${i}`} className="text-[10px] text-center text-muted-foreground pb-1">{w}</div>))
  for (let h = 0; h < 24; h++) {
    items.push(<div key={`hr${h}`} className="text-[10px] text-right pr-1 text-muted-foreground tabular-nums leading-4">{String(h).padStart(2, '0')}</div>)
    for (let wd = 1; wd <= 7; wd++) {
      const v = grid[`${h}-${wd}`] ?? 0
      items.push(<div key={`${h}-${wd}`} title={`${WEEKDAYS[wd - 1]} ${String(h).padStart(2, '0')}:00 — ${fmtFuelMetric(metric, v)}`}
        className="h-4 rounded-sm" style={{ background: color(v) }} />)
    }
  }
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Загрузка: час × день недели ({FUEL_METRIC_LABELS[metric]})</div>
        <div className="overflow-x-auto" data-chart>
          <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: '28px repeat(7, minmax(30px, 1fr))' }}>
            {items}
          </div>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">Темнее — интенсивнее. Пики — усиление персонала смен; «мёртвые» окна — регламентные работы.</div>
      </CardContent>
    </Card>
  )
}

function TimeLoad({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('fuel_fills/time', { metric: 'fills' as FuelMetric })
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useFills(companyId, period.from, period.to, 'hour')
  if (isLoading) return <Loading />
  if (!data || data.lines.length === 0) return <Empty />
  const max = Math.max(...data.lines.map((l) => l.fills), 1)
  return (
    <div className="p-4 space-y-4">
      <ViewParamsBar>
        <Field label="Метрика">
          <Select value={p.metric} onValueChange={(v) => patch({ metric: v as FuelMetric })}>
            <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{HEAT_METRICS.map((m) => <SelectItem key={m} value={m} className="text-xs">{FUEL_METRIC_LABELS[m]}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </ViewParamsBar>
      <FillKpis t={data.totals} />
      <FuelHeatmap companyId={companyId} dateFrom={period.from} dateTo={period.to} metric={p.metric} />
      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Профиль по часам суток (реализации · литры)</div>
          <div className="space-y-1" {...exportRows('Профиль по часам', ['Час', 'Реализаций', 'Литры', 'Выручка, ₽'],
            data.lines.map((l) => [l.label, l.fills, l.liters, l.amount]))}>
            {data.lines.map((l) => (
              <div key={l.key} className="flex items-center gap-2 text-xs">
                <span className="w-10 tabular-nums text-muted-foreground">{l.label}</span>
                <div className="flex-1 h-4 bg-muted/40 rounded overflow-hidden">
                  <div className="h-full bg-primary/70 rounded" style={{ width: `${l.fills / max * 100}%` }} />
                </div>
                <span className="w-32 text-right font-mono tabular-nums">{nf0.format(l.fills)} · {nf0.format(l.liters)} л</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────────── Динамика ────────────────────────── */

const DYN_DEFAULTS = { metric: 'amount' as FuelMetric, seriesSel: '__net__', bucket: 'week' as FuelBucket, yoy: false }
const shiftYearISO = (iso: string, delta: number): string => {
  const d = new Date(iso); d.setFullYear(d.getFullYear() + delta); return isoLocal(d)
}

/** 6 KPI сводки временного ряда (сумма/среднее/пик/мин/тренд/стабильность). */
function PeriodSummaryKpis({ points, metric, unit }: { points: { label: string; v: number }[]; metric: FuelMetric; unit: string }) {
  if (points.length === 0) return null
  const nums = points.map((x) => x.v)
  const ratio = isFuelRatio(metric)
  const total = nums.reduce((a, b) => a + b, 0)
  const mean = total / nums.length
  const peak = points.reduce((m, x) => (x.v > m.v ? x : m), points[0])
  const low = points.reduce((m, x) => (x.v < m.v ? x : m), points[0])
  const trend = nums[0] ? (nums[nums.length - 1] - nums[0]) / nums[0] * 100 : 0
  const cv = mean ? Math.sqrt(nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length) / Math.abs(mean) * 100 : 0
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <KpiCard label="За период" value={fmtFuelMetric(metric, ratio ? mean : total)} accent="success" hint={ratio ? 'среднее' : 'сумма'} />
      <KpiCard label={`Среднее / ${unit}`} value={fmtFuelMetric(metric, mean)} />
      <KpiCard label="Пик" value={fmtFuelMetric(metric, peak.v)} accent="info" hint={peak.label} />
      <KpiCard label="Минимум" value={fmtFuelMetric(metric, low.v)} hint={low.label} />
      <KpiCard label="Тренд" value={`${trend >= 0 ? '+' : ''}${trend.toFixed(0)}%`} accent={trend >= 0 ? 'success' : 'danger'} hint="последний vs первый" />
      <KpiCard label="Стабильность" value={`${cv.toFixed(0)}%`} accent={cv <= 30 ? 'success' : cv <= 70 ? 'warning' : 'danger'} hint="разброс (CV)" />
    </div>
  )
}

const BUCKET_UNIT: Record<string, string> = { day: 'день', week: 'неделя', decade: 'декада', month: 'месяц', quarter: 'квартал' }

function Dynamics({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('fuel_fills/dynamics', DYN_DEFAULTS)
  const [view, setView] = useChartView({ type: 'line' })
  // Горизонт анализа: не персистится и сбрасывается при смене периода наверху.
  const [horizon, setHorizon] = useState<Period | null>(null)
  useEffect(() => { setHorizon(null) }, [dateFrom, dateTo])
  const period = horizon ?? { from: dateFrom, to: dateTo }
  const seriesBy = p.seriesSel === '__net__' ? undefined : (p.seriesSel as FuelGroupBy)
  const n = useFuelNarrow()

  const { data, isLoading } = useQuery({
    queryKey: ['fuel-timeseries', companyId, period.from, period.to, p.bucket, p.metric, p.seriesSel, n.key],
    queryFn: () => getFuelTimeseries({ companyId, dateFrom: period.from, dateTo: period.to, bucket: p.bucket, metric: p.metric, seriesBy, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
  })
  const yoyOn = p.yoy && p.seriesSel === '__net__'
  const prevFrom = shiftYearISO(period.from, -1), prevTo = shiftYearISO(period.to, -1)
  const prev = useQuery({
    queryKey: ['fuel-timeseries-yoy', companyId, prevFrom, prevTo, p.bucket, p.metric, n.key],
    queryFn: () => getFuelTimeseries({ companyId, dateFrom: prevFrom, dateTo: prevTo, bucket: p.bucket, metric: p.metric, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
    enabled: yoyOn,
  })
  const hasData = data && data.data.length > 0
  const chartData = yoyOn && prev.data
    ? (data?.data ?? []).map((row, i) => ({ bucket: row.bucket, 'Текущий': row.value, 'Год назад': prev.data!.data[i]?.value ?? null }))
    : (data?.data ?? [])
  const chartSeries = yoyOn && prev.data ? ['Текущий', 'Год назад'] : (data?.series ?? [])
  const format = fuelChartFormat(p.metric)

  return (
    <div className="p-4 space-y-4">
      <ViewParamsBar>
        <HorizonControl horizon={horizon} scopeFrom={dateFrom} scopeTo={dateTo} onChange={setHorizon} />
        <Field label="Метрика"><MetricSelect value={p.metric} onChange={(m) => patch({ metric: m })} /></Field>
        <Field label="Разрез"><SeriesSelect value={p.seriesSel} onChange={(v) => patch({ seriesSel: v })} withNet /></Field>
        <Field label="Шаг"><BucketSelect value={p.bucket} onChange={(b) => patch({ bucket: b })} /></Field>
        {p.seriesSel === '__net__' && (
          <Button variant={p.yoy ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-2" onClick={() => patch({ yoy: !p.yoy })}>
            Год к году
          </Button>
        )}
      </ViewParamsBar>
      {hasData && !isLoading && (
        <PeriodSummaryKpis
          points={data!.data.map((row) => ({
            label: String(row.bucket),
            v: data!.series.reduce((a, s) => a + (typeof row[s] === 'number' ? (row[s] as number) : 0), 0),
          }))}
          metric={p.metric}
          unit={BUCKET_UNIT[p.bucket] ?? 'интервал'} />
      )}
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {FUEL_METRIC_LABELS[p.metric]}{yoyOn && <span className="normal-case text-muted-foreground/60"> · оверлей: {prevFrom.slice(0, 4)} vs {period.from.slice(0, 4)}</span>}
            </div>
            {hasData && !isLoading && <ChartControls view={view} onChange={setView} single={chartSeries.length === 1} ratio={format.ratio} />}
          </div>
          {isLoading ? <Loading /> : !hasData ? <Empty text="Нет данных за период" />
            : <ChargeChart data={chartData} series={chartSeries} view={view} format={format} />}
        </CardContent>
      </Card>
      {hasData && <TrendTable data={data!} metric={p.metric} />}
    </div>
  )
}

function TrendTable({ data, metric }: { data: FuelTimeseriesResponse; metric: FuelMetric }) {
  const exCols = ['Период', ...data.series.map((s) => (s === 'value' ? FUEL_METRIC_LABELS[metric] : s))]
  const exData = data.data.map((row) => [String(row.bucket), ...data.series.map((s) => (row[s] ?? null) as string | number | null)])
  return (
    <Card>
      <CardContent className="p-0">
        <table className="w-full text-xs" {...exportRows('Динамика', exCols, exData)}>
          <thead>
            <tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="text-left p-2 font-medium">Период</th>
              {data.series.map((s) => (
                <th key={s} className="text-right p-2 font-medium">{s === 'value' ? FUEL_METRIC_LABELS[metric] : s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.data.map((row) => (
              <tr key={String(row.bucket)} className="border-b border-border/30 hover:bg-muted/30">
                <td className="p-2 font-medium">{String(row.bucket)}</td>
                {data.series.map((s) => (
                  <td key={s} className="p-2 text-right font-mono">{fmtFuelMetricCompact(metric, row[s] as number | null)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

/* ──────────────────── Сравнение периодов ────────────────────── */

function Compare({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('fuel_fills/compare', { mode: 'slice' as 'slice' | 'manual' })
  return (
    <div className="p-4 space-y-4">
      <div className="flex gap-1" data-export-ignore>
        <Button variant={p.mode === 'slice' ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-3" onClick={() => patch({ mode: 'slice' })}>
          Нарезка периода
        </Button>
        <Button variant={p.mode === 'manual' ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-3" onClick={() => patch({ mode: 'manual' })}>
          Произвольные периоды
        </Button>
      </div>
      {p.mode === 'slice'
        ? <SliceCompare companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
        : <ManualCompare companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />}
    </div>
  )
}

const SLICE_DEFAULTS = { bucket: 'month' as FuelBucket, metric: 'amount' as FuelMetric, seriesSel: '__net__', topN: 8 }
const SLICE_CHART_MAX = 12

function SliceCompare({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('fuel_fills/compare_slice', SLICE_DEFAULTS)
  // Горизонт анализа: не персистится и сбрасывается при смене периода наверху.
  const [horizon, setHorizon] = useState<Period | null>(null)
  useEffect(() => { setHorizon(null) }, [dateFrom, dateTo])
  const period = horizon ?? { from: dateFrom, to: dateTo }
  const groupBy = p.seriesSel === '__net__' ? undefined : (p.seriesSel as FuelGroupBy)
  const n = useFuelNarrow()
  const [view, setView] = useChartView()

  const { data, isLoading } = useQuery({
    queryKey: ['fuel-slice', companyId, period.from, period.to, p.bucket, p.metric, p.seriesSel, p.topN, n.key],
    queryFn: () => getFuelSlice({ companyId, dateFrom: period.from, dateTo: period.to, bucket: p.bucket, metric: p.metric, groupBy, topN: p.topN, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
  })
  const hasData = data && data.intervals.length > 0
  const format = fuelChartFormat(p.metric)

  return (
    <div className="space-y-4">
      <ViewParamsBar>
        <HorizonControl horizon={horizon} scopeFrom={dateFrom} scopeTo={dateTo} onChange={setHorizon} />
        <Field label="Нарезка"><BucketSelect value={p.bucket} onChange={(b) => patch({ bucket: b })} /></Field>
        <Field label="Метрика"><MetricSelect value={p.metric} onChange={(m) => patch({ metric: m })} /></Field>
        <Field label="Разрез"><SeriesSelect value={p.seriesSel} onChange={(v) => patch({ seriesSel: v })} withNet /></Field>
      </ViewParamsBar>
      {isLoading ? <Loading /> : !hasData ? <Empty text="Нет данных за период" /> : (
        <>
          <PeriodSummaryKpis
            points={data!.intervals.map((iv, i) => ({ label: iv.label, v: data!.totals.values[i] ?? 0 })).filter((_, i) => !data!.intervals[i].partial)}
            metric={p.metric} unit="интервал" />
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs uppercase tracking-wider text-muted-foreground">
                  {FUEL_METRIC_LABELS[p.metric]} по интервалам
                  {data!.lines.length > SLICE_CHART_MAX && <span className="normal-case text-muted-foreground/60"> · на графике топ-{SLICE_CHART_MAX}</span>}
                </div>
                <ChartControls view={view} onChange={setView} single={data!.lines.length === 1} ratio={format.ratio} />
              </div>
              <ChargeChart
                data={data!.intervals.map((iv, i) => {
                  const row: Record<string, string | number | null> = { bucket: iv.label }
                  data!.lines.slice(0, SLICE_CHART_MAX).forEach((l) => { row[l.label] = l.values[i] })
                  return row
                })}
                series={data!.lines.slice(0, SLICE_CHART_MAX).map((l) => l.label)}
                view={view} format={format} />
            </CardContent>
          </Card>
          <ComparisonTable
            columns={data!.intervals.map((iv) => ({ label: iv.label, hint: `${iv.from.slice(5)}–${iv.to.slice(5)}`, partial: iv.partial }))}
            lines={data!.lines}
            totalsValues={data!.group_by !== '__net__' && data!.lines.length > 1 ? data!.totals.values : undefined}
            metric={p.metric} firstCol={GROUP_LABELS[data!.group_by] ?? 'Разрез'} />
          <NewCardsBlock companyId={companyId} dateFrom={period.from} dateTo={period.to} bucket={p.bucket} narrow={n} />
        </>
      )}
    </div>
  )
}

const MANUAL_DEFAULTS = { metric: 'amount' as FuelMetric, groupBy: 'station' as FuelGroupBy, periods: null as Period[] | null }

function ManualCompare({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const anchor: Period = { from: dateFrom, to: dateTo }
  const [p, patch] = useTabParams('fuel_fills/compare_manual', MANUAL_DEFAULTS)
  const periods = p.periods ?? buildMoM(anchor, 3)
  const n = useFuelNarrow()

  const ready = periods.length >= 2 && periods.every((x) => x.from && x.to)
  const { data, isLoading, error } = useQuery({
    queryKey: ['fuel-compare-multi', companyId, JSON.stringify(periods), p.metric, p.groupBy, n.key],
    queryFn: () => getFuelCompareMulti({ companyId, periods, metric: p.metric, groupBy: p.groupBy, stationCodes: n.stationCodes, fuelCodes: n.fuelCodes, segment: n.segment }),
    enabled: ready,
  })

  return (
    <div className="space-y-4">
      <MultiPeriodPicker periods={periods} onChange={(np) => patch({ periods: np })} anchor={anchor} />
      <ViewParamsBar>
        <Field label="Метрика"><MetricSelect value={p.metric} onChange={(m) => patch({ metric: m })} /></Field>
        <Field label="Разрез"><SeriesSelect value={p.groupBy} onChange={(v) => patch({ groupBy: v as FuelGroupBy })} /></Field>
      </ViewParamsBar>
      {!ready ? <Empty text="Задайте минимум 2 периода" />
        : isLoading ? <Loading />
        : (error || !data) ? <Empty text="Нет данных для сравнения" />
        : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {data.periods.map((per, i) => (
                <KpiCard key={i} label={`Период ${i + 1}`} value={fmtFuelMetric(p.metric, data.totals.values[i] ?? null)}
                  hint={`${per.from} — ${per.to}`} accent={i === data.periods.length - 1 ? 'success' : undefined} />
              ))}
            </div>
            <ComparisonTable
              columns={data.periods.map((per, i) => ({ label: `П${i + 1}`, hint: `${per.from.slice(5)}—${per.to.slice(5)}` }))}
              lines={data.lines} metric={p.metric} firstCol={GROUP_LABELS[data.group_by] ?? 'Разрез'} />
            <NewCardsManualBlock companyId={companyId} periods={periods} narrow={n} />
          </div>
        )}
    </div>
  )
}

/** Таблица сравнения: строки = разрез, колонки = интервалы/периоды + дельты. */
function ComparisonTable({ columns, lines, totalsValues, metric, firstCol }: {
  columns: { label: string; hint?: string; partial?: boolean }[]
  lines: { label: string; values: (number | null)[]; delta_prev: number; delta_pct_prev: number }[]
  totalsValues?: (number | null)[]
  metric: FuelMetric
  firstCol: string
}) {
  const deltaCls = (v: number) => (v > 0 ? 'text-emerald-600 dark:text-emerald-400' : v < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')
  const cellDim = (i: number) => (columns[i]?.partial ? 'text-muted-foreground/40' : '')
  const hasPartial = columns.some((c) => c.partial)
  const exCols = [firstCol, ...columns.map((c) => c.label), 'Δ посл.', 'Δ %']
  const exData: (string | number | null)[][] = lines.map((l) => [l.label, ...l.values, l.delta_prev, l.delta_pct_prev])
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-1.5 text-[11px] text-muted-foreground border-b bg-muted/20">
          Значения: {FUEL_METRIC_LABELS[metric]}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" {...exportRows(firstCol, exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium sticky left-0 bg-muted/40 z-10">{firstCol}</th>
                {columns.map((c, i) => (
                  <th key={i} className={`text-right p-2 font-medium whitespace-nowrap ${c.partial ? 'text-muted-foreground/50' : ''}`}>
                    {c.label}{c.partial && <span className="text-amber-600/70 dark:text-amber-400/70"> *</span>}
                    {c.hint && <div className="text-[10px] font-normal text-muted-foreground/70">{c.hint}{c.partial ? ' · неполн.' : ''}</div>}
                  </th>
                ))}
                <th className="text-right p-2 font-medium whitespace-nowrap">Δ посл.</th>
                <th className="text-right p-2 font-medium">Δ %</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium truncate max-w-[200px] sticky left-0 bg-background z-10">{l.label}</td>
                  {l.values.map((v, i) => (
                    <td key={i} className={`p-2 text-right font-mono whitespace-nowrap ${cellDim(i)}`}>{fmtFuelMetricCompact(metric, v)}</td>
                  ))}
                  <td className={`p-2 text-right font-mono whitespace-nowrap ${deltaCls(l.delta_prev)}`}>
                    {l.delta_prev > 0 ? '+' : ''}{fmtFuelMetricCompact(metric, l.delta_prev)}
                  </td>
                  <td className={`p-2 text-right font-mono ${deltaCls(l.delta_pct_prev)}`}>
                    {l.delta_pct_prev > 0 ? '+' : ''}{l.delta_pct_prev.toFixed(0)}%
                  </td>
                </tr>
              ))}
              {totalsValues && (
                <tr className="bg-muted/60 font-medium">
                  <td className="p-2 sticky left-0 bg-muted/60 z-10">Итого (сеть)</td>
                  {totalsValues.map((v, i) => (
                    <td key={i} className={`p-2 text-right font-mono whitespace-nowrap ${cellDim(i)}`}>{fmtFuelMetricCompact(metric, v)}</td>
                  ))}
                  <td colSpan={2} />
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {hasPartial && (
          <div className="px-3 py-2 text-[11px] text-muted-foreground border-t">
            <span className="text-amber-600/70 dark:text-amber-400/70">*</span> неполный интервал (частично вне периода) — не участвует в расчёте Δ
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ─────────────────── Когорты «новые карты» ──────────────────── */

function NewCardsBlock({ companyId, dateFrom, dateTo, bucket, narrow }: {
  companyId: string; dateFrom: string; dateTo: string; bucket: FuelBucket; narrow: Narrow
}) {
  const [sel, setSel] = useState<{ from: string; to: string; label: string } | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-new-cards', companyId, dateFrom, dateTo, bucket, narrow.key],
    queryFn: () => getFuelNewCards({ companyId, dateFrom, dateTo, bucket, stationCodes: narrow.stationCodes, segment: narrow.segment }),
  })
  if (isLoading || !data || data.intervals.length === 0) return null
  const iv = data.intervals
  const histNote = data.historyFrom && data.historyFrom >= dateFrom
  const exCols = ['Интервал', 'Активных карт', 'Новых', 'Доля новых, %', 'Вернувшихся', 'Реализаций новых', 'Литры новых', 'Выручка новых, ₽', 'Доля выручки новых, %']
  const exData = iv.map((r) => [r.label, r.activeCards, r.newCards, r.newSharePct, r.returningCards, r.newFills, r.newLiters, r.newRevenue, r.newRevenueSharePct] as (string | number | null)[])
  const dim = (r: FuelNewCardsInterval) => (r.partial ? 'text-muted-foreground/40' : '')
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b bg-muted/20 px-3 py-1.5">
          <span className="text-[11px] font-medium">Новые карты по интервалам</span>
          <span className="text-[11px] text-muted-foreground">
            впервые за всю историю наблюдений · клик по строке — конкретные карты
          </span>
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            за период: новых {nf0.format(data.totals.newCards)} · выручка новых {fmtRub0(data.totals.newRevenue)}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Новые карты', exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="p-2 text-left font-medium">Интервал</th>
                <th className="p-2 text-right font-medium">Активных</th>
                <th className="p-2 text-right font-medium">Новых</th>
                <th className="p-2 text-right font-medium">Доля новых</th>
                <th className="p-2 text-right font-medium">Вернувшихся</th>
                <th className="p-2 text-right font-medium">Реализаций новых</th>
                <th className="p-2 text-right font-medium">Литры новых</th>
                <th className="p-2 text-right font-medium">Выручка новых</th>
                <th className="p-2 text-right font-medium">Доля выручки</th>
              </tr>
            </thead>
            <tbody>
              {iv.map((r) => (
                <tr key={r.key} className="cursor-pointer border-b border-border/30 hover:bg-muted/30"
                  onClick={() => setSel({ from: r.from, to: r.to, label: r.label })}>
                  <td className={`p-2 font-medium whitespace-nowrap ${dim(r)}`}>{r.label}{r.partial ? ' *' : ''}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf0.format(r.activeCards)}</td>
                  <td className={`p-2 text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400 ${r.partial ? 'opacity-40' : ''}`}>{nf0.format(r.newCards)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{r.newSharePct != null ? `${r.newSharePct}%` : '—'}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf0.format(r.returningCards)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf0.format(r.newFills)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf1.format(r.newLiters)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{fmtRub0(r.newRevenue)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{r.newRevenueSharePct != null ? `${r.newRevenueSharePct}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="px-3 py-1.5 text-[11px] text-muted-foreground/70">
          * — неполный интервал (выходит за границы периода).
          {histNote && <> История наблюдений начинается {data.historyFrom} — в первом интервале «новыми» выглядят и давние карты.</>}
          {' '}Карта = идентификатор из STS (банковская — розница, топливная — корпоратив); наличные без карты в когортах не участвуют.
          Учитываются фильтры панели (сегмент/станция).
        </p>
      </CardContent>
      <NewCardsListModal companyId={companyId} interval={sel} narrow={narrow} onClose={() => setSel(null)} />
    </Card>
  )
}

function NewCardsManualBlock({ companyId, periods, narrow }: {
  companyId: string; periods: Period[]; narrow: Narrow
}) {
  const [sel, setSel] = useState<{ from: string; to: string; label: string } | null>(null)
  const results = useQueries({
    queries: periods.map((per) => ({
      queryKey: ['fuel-new-cards-list', companyId, per.from, per.to, narrow.key, 'count'],
      queryFn: () => getFuelNewCardsList({ companyId, dateFrom: per.from, dateTo: per.to, limit: 1, stationCodes: narrow.stationCodes, segment: narrow.segment }),
      enabled: !!per.from && !!per.to,
    })),
  })
  const exData = periods.map((per, i) => [
    `Период ${i + 1}`, per.from, per.to, results[i]?.data?.count ?? null,
  ] as (string | number | null)[])
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex items-center gap-2 border-b bg-muted/20 px-3 py-1.5">
          <span className="text-[11px] font-medium">Новые карты по периодам</span>
          <span className="text-[11px] text-muted-foreground">впервые за всю историю · клик — конкретные карты</span>
        </div>
        <div className="grid grid-cols-2 gap-3 p-3 md:grid-cols-4">
          {periods.map((per, i) => (
            <button key={`${per.from}-${per.to}`} type="button"
              onClick={() => setSel({ from: per.from, to: per.to, label: `${per.from} — ${per.to}` })}
              className="rounded-lg border bg-muted/20 p-3 text-left transition-colors hover:bg-muted/40">
              <div className="text-[11px] text-muted-foreground">Период {i + 1} · {per.from.slice(5)}—{per.to.slice(5)}</div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                {results[i]?.isLoading ? '…' : nf0.format(results[i]?.data?.count ?? 0)}
              </div>
              <div className="text-[11px] text-muted-foreground">новых карт</div>
            </button>
          ))}
        </div>
        <ExportOnlyTable name="Новые карты" columns={['Период', 'С', 'По', 'Новых карт']} rows={exData} />
      </CardContent>
      <NewCardsListModal companyId={companyId} interval={sel} narrow={narrow} onClose={() => setSel(null)} />
    </Card>
  )
}

function NewCardsListModal({ companyId, interval, narrow, onClose }: {
  companyId: string
  interval: { from: string; to: string; label: string } | null
  narrow: Narrow
  onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-new-cards-list', companyId, interval?.from, interval?.to, narrow.key, 500],
    queryFn: () => getFuelNewCardsList({ companyId, dateFrom: interval!.from, dateTo: interval!.to, limit: 500, stationCodes: narrow.stationCodes, segment: narrow.segment }),
    enabled: !!interval,
  })
  return (
    <Dialog open={!!interval} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Новые карты · {interval?.label}
            {data && <span className="ml-2 font-normal text-muted-foreground">{nf0.format(data.count)} шт.{data.count > 500 ? ' · показаны первые 500' : ''}</span>}
          </DialogTitle>
        </DialogHeader>
        <div className="overflow-y-auto -mx-1 px-1">
          {isLoading ? <Loading /> : !data || data.cards.length === 0 ? <Empty text="Нет новых карт в интервале" /> : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-background">
                <tr className="border-b text-muted-foreground">
                  <th className="p-2 text-left font-medium">Карта</th>
                  <th className="p-2 text-left font-medium">Канал</th>
                  <th className="p-2 text-left font-medium">Первая заправка</th>
                  <th className="p-2 text-right font-medium">Реализаций</th>
                  <th className="p-2 text-right font-medium">Литры</th>
                  <th className="p-2 text-right font-medium">Выручка</th>
                  <th className="p-2 text-right font-medium">Станций</th>
                </tr>
              </thead>
              <tbody>
                {data.cards.map((c) => (
                  <tr key={c.card} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-mono">{c.card}</td>
                    <td className="p-2 text-muted-foreground">{c.channel}</td>
                    <td className="p-2 font-mono text-muted-foreground">{c.firstAt ?? '—'}</td>
                    <td className="p-2 text-right font-mono">{nf0.format(c.fills)}</td>
                    <td className="p-2 text-right font-mono">{nf0.format(c.liters)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub0(c.revenue)}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{c.stations}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/* ─────────────────────── Контейнер табов ────────────────────── */

const SUB_TABS: { k: string; label: string }[] = [
  { k: 'breakdown', label: 'Разрезы' },
  { k: 'time', label: 'Время и загрузка' },
  { k: 'dynamics', label: 'Динамика (тренд)' },
  { k: 'compare', label: 'Сравнение периодов' },
  // Готовые разрезы отвечают на частые вопросы, сводная - на все остальные.
  { k: 'pivot', label: 'Сводная' },
]

function subView(sub: string, p: { companyId: string; dateFrom: string; dateTo: string }): { title: string; node: ReactNode } {
  const { companyId, dateFrom, dateTo } = p
  switch (sub) {
    case 'time': return { title: 'Время и загрузка', node: <TimeLoad companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    case 'dynamics': return { title: 'Динамика', node: <Dynamics companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    case 'compare': return { title: 'Сравнение периодов', node: <Compare companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    case 'pivot': return { title: 'Сводная', node: <FillsPivot dateFrom={dateFrom} dateTo={dateTo} /> }
    default: return { title: 'Разрезы', node: <FillsBreakdown companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
  }
}

/**
 * Сводная «Реализации»: тот же источник, что у реестра операций, и те же фильтры
 * рабочей области. Сегмент (розница/корпоратив) сюда НЕ прокидывается: сводная
 * умеет разрез по способу оплаты, а два разных сужения одних данных в одном экране
 * читаются как ошибка в цифрах.
 */
function FillsPivot({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { stationCode } = useFilters()
  const fk = useFuelKindFilter()
  const station = stationCode !== 'all' && Number.isFinite(Number(stationCode))
    ? Number(stationCode) : undefined
  return (
    <div className="px-4 pb-4">
      <PivotView
        source="transactions" storageKey="fuel-fills-pivot"
        defaultDims={['fuel', 'station', 'payment']}
        queryKey={{ dateFrom, dateTo, station, fuels: fk.fuelCodes }}
        fetchLeaves={(dims) => getFuelTxPivot({
          dateFrom, dateTo, dims, stationCode: station,
          fuelCodes: fk.fuelCodes?.length ? fk.fuelCodes : undefined,
        })}
        dateFrom={dateFrom} dateTo={dateTo}
        scopeLabel={station ? `АЗС ${station}` : 'все АЗС'} />
    </div>
  )
}

/** Пункт «Реализация» — контейнер с внутренними табами + общий тумблер сегмента. */
export function FuelFillsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [st, patch] = useTabParams('fuel_fills', { sub: 'breakdown' })
  const [segment, setSegment] = useState<SegmentSel>('all')
  const v = subView(st.sub, { companyId, dateFrom, dateTo })
  const ref = useRef<HTMLDivElement>(null)
  const scopeSub = useScopeSubtitle()
  return (
    <FuelSegmentCtx.Provider value={segment}>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <PanelViewTabs tabs={SUB_TABS} value={st.sub} onChange={(k) => patch({ sub: k })} ariaLabel="Виды пункта «Реализация»" />
        <div className="flex items-center gap-2 shrink-0">
          <SegmentToggle value={segment} onChange={setSegment} />
          <ExportButton title={`Реализация · ${v.title}`} subtitle={scopeSub} getEl={() => ref.current} />
        </div>
      </div>
      {/* key={st.sub} — ремаунт под-вида при смене таба (чистое локальное состояние). */}
      <div ref={ref} className="pt-3" key={st.sub}>{v.node}</div>
    </FuelSegmentCtx.Provider>
  )
}
