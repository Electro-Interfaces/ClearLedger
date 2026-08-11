/**
 * Управленческий анализ зарядных сессий ЭЗС (energy, РусГидро).
 * Разрезы: обзор · станции · коннекторы · время/загрузка · клиенты/тарифы ·
 * динамика (тренд) · сравнение периодов. Данные — /api/analytics/charge-sessions(/timeseries|/compare).
 */

import { createContext, Fragment, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2, AlertTriangle, ArrowUp, ArrowDown, ChevronsUpDown, ChevronRight, ChevronDown, Search, X } from 'lucide-react'
import { KpiCard } from './analytics/AnalyticsPeriodPicker'
import { BarList } from '@/components/ui/bar-list'
import { HINTS, MetricHint } from './analytics/MetricHint'
import { TzToggle, type Tz } from './analytics/TzToggle'
import { seriesColor } from './analytics/palette'
import { MultiPeriodPicker } from './analytics/PeriodRangePicker'
import { ChargeTrendChart, ChargeBarChart } from './analytics/ChargeTrendChart'
import { ChargeChart, ChartControls, useChartView } from './analytics/ChargeChart'
import { type Period, buildMoM, isoLocal } from './analytics/periodPresets'
import { getPortEfficiency } from '@/services/overviewService'
import { useTabParams } from '@/hooks/useTabParams'
import { useFilters } from '@/contexts/FilterContext'
import { ExportButton } from './analytics/ExportButton'
import { useScopeSubtitle } from '@/hooks/useScopeReset'
import { PanelViewTabs } from './PanelViewTabs'
import { ViewParamsBar } from './ViewParamsBar'
import { HorizonControl } from './HorizonControl'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip as RTooltip } from 'recharts'
import { getReconciliationBy, type ReconByRow } from '@/services/chargePaymentsService'
import {
  getChargeSessions, getChargeTimeseries, getChargeCompareMulti, getChargeSlice, getChargeHeatmap,
  getChargeNewClients, getChargeNewClientsList, getChargeVisits, getChargeUnpaid, getChargeUnpaidStation,
  getChargeBrandReliability,
  fmtMoney, fmtMoneyShort, fmtMetric, fmtMetricCompact, CHARGE_METRIC_LABELS,
  type ChargeGroupBy, type ChargeSessionLine, type ChargeMetric, type ChargeBucket, type ChargeTotalsSeries,
  type ChargeSeriesBy, type ChargeTimeseriesResponse, type ChargeSliceResponse, type ChargeSessionsResponse,
  type ChargeNewClientsInterval, type StationReliabilityRow,
} from '@/services/analyticsService'
import { TrendSpark } from '@/components/ui/trend-spark'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const kwh = (v: number) => nf0.format(v) + ' кВтч'

// Палитра донат-диаграмм долей — как в analytics/ChargeChart.tsx (приглушённая, без неона);
// последний сегмент («Прочие») — нейтральный серый.

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет сессий за период' }: { text?: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

/** Сегмент-переключатель типа клиента (Все / ФЛ / ЮЛ) — общий для пунктов сессий. */
function ClientTypeToggle({ value, onChange }: { value: ClientType; onChange: (v: ClientType) => void }) {
  const opts: { v: ClientType; label: string }[] = [
    { v: 'all', label: 'Все' }, { v: 'fl', label: 'ФЛ' }, { v: 'ul', label: 'ЮЛ' },
  ]
  return (
    <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5" title="Фильтр по типу клиента">
      {opts.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors max-sm:inline-flex max-sm:min-h-9 max-sm:min-w-11 max-sm:items-center max-sm:justify-center max-sm:px-3.5 max-sm:text-sm ${value === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Атрибуты на <table> с сырыми ЧИСЛАМИ для выгрузки в Excel (формулы/сортировка). */
function exportRows(name: string, columns: string[], rows: (string | number | null)[][]) {
  return { 'data-export-name': name, 'data-export-rows': JSON.stringify({ columns, rows }) }
}

/** Невидимая таблица только для выгрузки — даёт отдельный лист Excel, не влияя на UI. */
function ExportOnlyTable({ name, columns, rows }: { name: string; columns: string[]; rows: (string | number | null)[][] }) {
  return <table hidden aria-hidden {...exportRows(name, columns, rows)} />
}

// ── управляющие селекторы (метрика/разрез/гранулярность) ──
const METRIC_OPTS: ChargeMetric[] = ['amount', 'energy_kwh', 'sessions', 'avg_check', 'success_pct', 'price_per_kwh', 'avg_energy', 'avg_duration_min']
const SERIES_OPTS: { value: string; label: string }[] = [
  { value: '__net__', label: 'Вся сеть' },
  { value: 'station', label: 'По станциям' },
  { value: 'connector', label: 'По коннекторам' },
  { value: 'user_type', label: 'По клиентам (ФЛ/ЮЛ)' },
  { value: 'client', label: 'По организациям (ЮЛ)' },
  { value: 'charge_type', label: 'По каналу запуска' },
  { value: 'region', label: 'По регионам' },
  { value: 'tariff', label: 'По тарифам' },
  { value: 'result', label: 'По исходу' },
]
const BUCKET_OPTS: { value: ChargeBucket; label: string }[] = [
  { value: 'day', label: 'День' }, { value: 'week', label: 'Неделя' },
  { value: 'decade', label: 'Декада' },
  { value: 'month', label: 'Месяц' }, { value: 'quarter', label: 'Квартал' },
]
const GROUP_LABELS: Record<string, string> = {
  station: 'Станция', connector: 'Коннектор', user_type: 'Тип клиента',
  charge_type: 'Канал запуска', region: 'Регион', tariff: 'Тариф', result: 'Исход',
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}
function MetricSelect({ value, onChange }: { value: ChargeMetric; onChange: (m: ChargeMetric) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as ChargeMetric)}>
      <SelectTrigger className="h-7 w-[190px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{METRIC_OPTS.map((m) => <SelectItem key={m} value={m} className="text-xs">{CHARGE_METRIC_LABELS[m]}</SelectItem>)}</SelectContent>
    </Select>
  )
}
function SeriesSelect({ value, onChange, withNet }: { value: string; onChange: (v: string) => void; withNet?: boolean }) {
  const opts = withNet ? SERIES_OPTS : SERIES_OPTS.filter((o) => o.value !== '__net__')
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-7 w-[190px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{opts.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
    </Select>
  )
}
function BucketSelect({ value, onChange, only }: { value: ChargeBucket; onChange: (v: ChargeBucket) => void; only?: ChargeBucket[] }) {
  const opts = only ? BUCKET_OPTS.filter((o) => only.includes(o.value)) : BUCKET_OPTS
  return (
    <Select value={value} onValueChange={(v) => onChange(v as ChargeBucket)}>
      <SelectTrigger className="h-7 w-[120px] text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>{opts.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
    </Select>
  )
}

// Цветовые пороги (индустрия CPO): загрузка <10% убыточна / 15% безубыток / 25%+ сильно;
// успех <70 плохо / 85 норма (у сети ~69% — сигнал проблемы).
type KpiAccent = 'success' | 'danger' | 'warning' | 'info'
const utilAccent = (v: number): KpiAccent => (v >= 15 ? 'success' : v >= 10 ? 'warning' : 'danger')
const succAccent = (v: number): KpiAccent => (v >= 85 ? 'success' : v >= 70 ? 'warning' : 'danger')
const utilTxt = (v: number) => (v >= 15 ? 'text-emerald-600 dark:text-emerald-400' : v >= 10 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')
const succTxt = (v: number) => (v >= 85 ? 'text-emerald-600 dark:text-emerald-400' : v >= 70 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')
/** Физический разрез — порт-нормированные метрики (загрузка) имеют смысл. */
const PHYSICAL_GROUPS = ['station', 'connector', 'region']

/** Ряд под цифрой даём только тем плиткам, чья метрика в нём есть: у загрузки,
 *  цены и throughput своего ряда нет — рисовать под ними чужой было бы враньём. */
function SessionKpis({ t, series }: { t: ChargeSessionLine; series?: ChargeTotalsSeries }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <KpiCard label="Выручка" value={fmtMoneyShort(t.amount) + ' ₽'} accent="success" spark={series?.amount} sparkLabel="Выручка по периодам" />
      <KpiCard label="Загрузка (util)" value={t.utilization_pct.toFixed(1) + '%'} accent={utilAccent(t.utilization_pct)} hint={`${nf0.format(t.ports)} портов`} info={HINTS.utilization} />
      {/* Успех — доля ВИЗИТОВ, закончившихся зарядкой: человек, у которого разъём
          схватился со второй попытки, зарядился. Та же цифра, что на «Обзоре». */}
      <KpiCard label="Зарядились" value={t.success_pct.toFixed(1) + '%'} accent={succAccent(t.success_pct)} info={HINTS.sessionSuccess} spark={series?.success_pct} sparkLabel="Успешность по периодам" />
      <KpiCard label="Сессий" value={nf0.format(t.sessions)}
        hint={t.charged ? `${nf0.format(t.charged)} с отпуском` : undefined}
        spark={series?.sessions} sparkLabel="Сессии по периодам" />
      <KpiCard label="Энергия" value={kwh(t.energy_kwh)} accent="info" spark={series?.energy} sparkLabel="Энергия по периодам" />
      <KpiCard label="Цена ₽/кВтч" value={fmtMoney(t.price_per_kwh)} />
      {/* Средняя заправка — на состоявшуюся зарядку, а не на попытку подключения. */}
      <KpiCard label="Средняя заправка" value={fmtMoney(t.avg_check) + ' ₽'} spark={series?.avg_check} sparkLabel="Средний чек по периодам" />
      <KpiCard label="кВтч/день/порт" value={nf1.format(t.throughput_port)} hint="throughput" />
    </div>
  )
}

/** Сужение из фильтра раздела (energy): выбранные ЭЗС-станции и регионы. */
// Фильтр типа клиента (ФЛ/ЮЛ) — общий для всех пунктов сессий. Прокидывается
// через контекст в useNarrow → в dim/dimVal каждого запроса (WHERE user_type).
// Компонуется с group_by (разрезом). Пункт «Корпоратив» жёстко ставит 'ul'.
export type ClientType = 'all' | 'fl' | 'ul'
const ChargeClientCtx = createContext<ClientType>('all')
const CLIENT_DIMVAL: Record<ClientType, string | undefined> = { all: undefined, fl: 'ФЛ', ul: 'ЮЛ' }

function useNarrow() {
  const { stationCodes, regionIds } = useFilters()
  const clientType = useContext(ChargeClientCtx)
  const dimVal = CLIENT_DIMVAL[clientType]
  return {
    stations: stationCodes.length ? stationCodes : undefined,
    regions: regionIds.length ? regionIds : undefined,
    dim: dimVal ? 'user_type' : undefined,   // фильтр ФЛ/ЮЛ как точечный dim (не мешает group_by)
    dimVal,
    key: `${stationCodes.join(',')}|${regionIds.join(',')}|${clientType}`,  // для queryKey
  }
}
type Narrow = ReturnType<typeof useNarrow>

/** withSeries — просить ряд тоталов для спарклайнов плиток. Это лишний скан
 *  периода, поэтому включают только экраны, где плитки действительно рисуются. */
function useCS(companyId: string, dateFrom: string, dateTo: string, groupBy: ChargeGroupBy, tz?: Tz, withSeries?: boolean) {
  const n = useNarrow()
  return useQuery({
    // withSeries в ключе: без него переход между экранами с плитками и без них
    // отдавал бы кеш без ряда, и спарклайны пропадали через раз.
    queryKey: ['charge-sessions', groupBy, companyId, dateFrom, dateTo, n.key, tz ?? 'msk', withSeries ? 'series' : ''],
    queryFn: () => getChargeSessions({ companyId, dateFrom, dateTo, groupBy, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal, tz, withSeries }),
  })
}

/** Универсальная таблица разреза сессий — сортируемая, с data-bars загрузки. */
function BreakdownTable({ companyId, dateFrom, dateTo, groupBy, firstCol, withKpis = false, controls = false, tabKey = 'cs_bd' }: {
  companyId: string; dateFrom: string; dateTo: string; groupBy: ChargeGroupBy; firstCol: string
  withKpis?: boolean; controls?: boolean; tabKey?: string
}) {
  // Только представление (метрика распределения + топ-N). Период — из контура
  // рабочей области: вид-срез не имеет своего периода (см. CLAUDE.md, ур. 2/4).
  const [p, patch] = useTabParams(tabKey, { metric: 'amount' as ChargeMetric, rows: 0 })
  // Разрез — ЛОКАЛЬНО (не в useTabParams): всегда стартует от groupBy таба. Иначе при
  // переиспользовании экземпляра между табами (станции↔коннекторы) разрез залипал.
  const [group, setGroup] = useState<ChargeGroupBy>(groupBy)
  const gb = (controls ? group : groupBy) as ChargeGroupBy
  const period = { from: dateFrom, to: dateTo }
  const distMetric = controls ? p.metric : 'amount'
  const col = controls ? (GROUP_LABELS[gb] ?? firstCol) : firstCol
  const { data, isLoading, error } = useCS(companyId, period.from, period.to, gb, undefined, withKpis)
  const n = useNarrow()
  const physical = PHYSICAL_GROUPS.includes(gb)
  const showStations = physical && gb !== 'station'   // число станций в группе; для разреза «станция» = 1, скрываем
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'amount', dir: 'desc' })
  const lines = data?.lines ?? []
  const sortedLines = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    const get = (l: Record<string, unknown>) => l[sort.key]
    return [...lines].sort((a, b) => (sort.key === 'label'
      ? dir * a.label.localeCompare(b.label, 'ru')
      : dir * (((get(a as unknown as Record<string, unknown>) as number) ?? 0) - ((get(b as unknown as Record<string, unknown>) as number) ?? 0))))
  }, [lines, sort])
  const shownLines = controls && p.rows > 0 ? sortedLines.slice(0, p.rows) : sortedLines
  // Батч-тренд по месяцам для sparkline в строке (только физические разрезы).
  const spark = useQuery({
    queryKey: ['charge-slice-spark', companyId, period.from, period.to, gb, n.key],
    queryFn: () => getChargeSlice({ companyId, dateFrom: period.from, dateTo: period.to, bucket: 'month', groupBy: gb as ChargeSeriesBy, metric: 'amount', topN: 1000, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
    enabled: physical,
  })
  const sparkMap = useMemo(() => {
    const m: Record<string, (number | null)[]> = {}
    spark.data?.lines.forEach((l) => { m[l.label] = l.values })
    return m
  }, [spark.data])
  if (isLoading) return <Loading />
  if (error || !data) return <Empty text="Нет данных" />
  if (data.lines.length === 0) return <Empty />
  const t = data.totals
  const maxUtil = Math.max(...data.lines.map((l) => l.utilization_pct), 0.01)
  const exCols = [col, ...(physical ? ['Портов'] : []), ...(showStations ? ['Станций'] : []), 'Сессий', 'Энергия, кВтч', 'Выручка, ₽', 'Доля, %',
    ...(physical ? ['Загрузка, %', 'кВтч/д·порт'] : []), 'Ср. чек, ₽', '₽/кВтч', 'Успех, %']
  const exData: (string | number)[][] = [
    ...sortedLines.map((l) => [l.label, ...(physical ? [l.ports] : []), ...(showStations ? [l.stations] : []), l.sessions, l.energy_kwh, l.amount, l.share_pct,
      ...(physical ? [l.utilization_pct, l.throughput_port] : []), l.avg_check, l.price_per_kwh, l.success_pct]),
    ['Итого', ...(physical ? [t.ports] : []), ...(showStations ? [t.stations] : []), t.sessions, t.energy_kwh, t.amount, 100,
      ...(physical ? [t.utilization_pct, t.throughput_port] : []), t.avg_check, t.price_per_kwh, t.success_pct],
  ]
  const toggle = (key: string) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }))
  // Каждый столбец сортируемый: бледная ↕ всегда видна (ярче на hover), активный —
  // цветная стрелка направления. Так понятно, что кликается любой заголовок.
  const H = ({ k, children, left }: { k: string; children: ReactNode; left?: boolean }) => {
    const active = sort.key === k
    const Ico = active ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    const ariaSort: 'ascending' | 'descending' | 'none' = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
    return (
      <th aria-sort={ariaSort} className={`p-2 font-medium ${left ? 'text-left' : 'text-right'}`}>
        <button onClick={() => toggle(k)} title="Сортировать по столбцу"
          className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${left ? '' : 'flex-row-reverse'} ${active ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{children}</span>
          <Ico className={`h-3 w-3 shrink-0 ${active ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </th>
    )
  }
  return (
    <div className="p-4 space-y-4">
      {controls && (
        <ViewParamsBar>
          <Field label="Разрез"><SeriesSelect value={group} onChange={(v) => setGroup(v as ChargeGroupBy)} /></Field>
          <Field label="Метрика"><MetricSelect value={p.metric} onChange={(m) => patch({ metric: m })} /></Field>
          <Field label="Строк">
            <Select value={String(p.rows)} onValueChange={(v) => patch({ rows: Number(v) })}>
              <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{ROWS_OPTS.map((o) => <SelectItem key={o.value} value={String(o.value)} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
        </ViewParamsBar>
      )}
      {withKpis && <SessionKpis t={t} series={data.series} />}
      {data.lines.length >= 3 && (
        <div className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Распределение по разрезу: {CHARGE_METRIC_LABELS[distMetric]}</div>
          <DistributionKpis lines={data.lines} metric={distMetric} dimGen={DIM_GEN[gb] ?? 'разрез'} />
        </div>
      )}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs" {...exportRows(col, exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <H k="label" left>{col}</H>
                {physical && <H k="ports">Портов</H>}
                {showStations && <H k="stations">Станций</H>}
                <H k="sessions">Сессий</H>
                <H k="energy_kwh">Энергия, кВтч</H>
                <H k="amount">Выручка</H>
                <H k="share_pct">Доля</H>
                {physical && <H k="utilization_pct">Загрузка</H>}
                {physical && <H k="throughput_port">кВтч/д·порт</H>}
                <H k="avg_check">Ср. чек</H>
                <H k="price_per_kwh">₽/кВтч</H>
                <H k="success_pct">Успех</H>
                {physical && <th className="p-2 font-medium text-right whitespace-nowrap">Тренд ₽</th>}
              </tr>
            </thead>
            <tbody>
              {shownLines.map((l) => (
                <tr key={l.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium truncate max-w-[240px]">{l.label}</td>
                  {physical && <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.ports)}</td>}
                  {showStations && <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.stations)}</td>}
                  <td className="p-2 text-right font-mono">{nf0.format(l.sessions)}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(l.energy_kwh)}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(l.amount)}</td>
                  <td className="p-2 text-right font-mono">{l.share_pct.toFixed(1)}%</td>
                  {physical && (
                    <td className="p-2 text-right font-mono">
                      <div className="relative">
                        <div className="absolute inset-y-0 right-0 bg-primary/15 rounded-sm" style={{ width: `${Math.min(100, l.utilization_pct / maxUtil * 100)}%` }} />
                        <span className={`relative ${utilTxt(l.utilization_pct)}`}>{l.utilization_pct.toFixed(1)}%</span>
                      </div>
                    </td>
                  )}
                  {physical && <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.throughput_port)}</td>}
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtMoney(l.avg_check)}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(l.price_per_kwh)}</td>
                  <td className={`p-2 text-right font-mono ${succTxt(l.success_pct)}`}>{l.success_pct.toFixed(0)}%</td>
                  {physical && <td className="p-2 text-right"><TrendSpark values={sparkMap[l.label] ?? []} placeholder={<span className="text-muted-foreground/40">—</span>} /></td>}
                </tr>
              ))}
              <tr className="bg-muted/60 font-medium">
                <td className="p-2">Итого</td>
                {physical && <td className="p-2 text-right font-mono">{nf0.format(t.ports)}</td>}
                {showStations && <td className="p-2 text-right font-mono">{nf0.format(t.stations)}</td>}
                <td className="p-2 text-right font-mono">{nf0.format(t.sessions)}</td>
                <td className="p-2 text-right font-mono">{nf0.format(t.energy_kwh)}</td>
                <td className="p-2 text-right font-mono">{fmtMoney(t.amount)}</td>
                <td className="p-2 text-right font-mono">100%</td>
                {physical && <td className={`p-2 text-right font-mono ${utilTxt(t.utilization_pct)}`}>{t.utilization_pct.toFixed(1)}%</td>}
                {physical && <td className="p-2 text-right font-mono">{nf0.format(t.throughput_port)}</td>}
                <td className="p-2 text-right font-mono">{fmtMoney(t.avg_check)}</td>
                <td className="p-2 text-right font-mono">{fmtMoney(t.price_per_kwh)}</td>
                <td className="p-2 text-right font-mono">{t.success_pct.toFixed(0)}%</td>
                {physical && <td className="p-2" />}
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

/** Обзор: KPI + доли коннекторов и клиентов. */
function Overview({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const st = useCS(companyId, period.from, period.to, 'station')
  const conn = useCS(companyId, period.from, period.to, 'connector')
  const usr = useCS(companyId, period.from, period.to, 'user_type')
  if (st.isLoading) return <Loading />
  if (!st.data || st.data.lines.length === 0) return <Empty />
  const t = st.data.totals
  const bar = (rows: ChargeSessionLine[] | undefined) => (rows ?? []).slice(0, 6)
  const alerts: string[] = []
  if (t.success_pct < 85) alerts.push(`Зарядились ${t.success_pct.toFixed(1)}% визитов — ${(100 - t.success_pct).toFixed(1)}% уехали без зарядки`)
  if (t.utilization_pct < 15) alerts.push(`Загрузка сети ${t.utilization_pct.toFixed(1)}% — ниже порога безубыточности (15%)`)
  // Тревога только по настоящему долгу: ток отпущен, оплаты нет. Раньше сюда
  // попадали сорвавшиеся попытки, и панель горела при нулевой задолженности.
  if (t.unpaid_pct > 3 && (t.unpaid_sessions ?? 0) > 0) {
    alerts.push(`Без оплаты ${nf0.format(t.unpaid_sessions ?? 0)} заправок (${t.unpaid_pct.toFixed(1)}%)`)
  }
  return (
    <div className="p-4 space-y-4">
      <SessionKpis t={t} />
      {alerts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {alerts.map((a, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-amber-500/10 text-amber-800 dark:text-amber-300 border border-amber-500/30">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />{a}
            </span>
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <ShareCard title="По коннекторам" rows={bar(conn.data?.lines)} />
        <ShareDonut title="По типу клиента" rows={bar(usr.data?.lines)} />
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Топ станций по выручке</div>
          <table className="w-full text-xs" {...exportRows('Топ станций', ['Станция', 'Сессий', 'Энергия, кВтч', 'Выручка, ₽', 'Доля, %'],
            st.data.lines.slice(0, 10).map((l) => [l.label, l.sessions, l.energy_kwh, l.amount, l.share_pct]))}>
            <tbody>
              {st.data.lines.slice(0, 10).map((l) => (
                <tr key={l.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium truncate max-w-[280px]">{l.label}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.sessions)} сес.</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.energy_kwh)} кВтч</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(l.amount)} ₽</td>
                  <td className="p-2 text-right font-mono">{l.share_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

/** Доли горизонтальными полосами-рейтингом (для разрезов с многими категориями). */
function ShareCard({ title, rows }: { title: string; rows: ChargeSessionLine[] }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">{title}</div>
        {/* Рейтинг общим компонентом: длина полосы пропорциональна выручке, доля —
            в подписи. Раньше ширина считалась вручную от share_pct. */}
        <BarList
          sortOrder="none"
          valueFormatter={(v) => `${fmtMoneyShort(v)} ₽`}
          data={rows.map((r) => ({
            key: r.label,
            name: `${r.label} · ${r.share_pct.toFixed(1)} %`,
            value: r.amount,
          }))}
        />
      </CardContent>
    </Card>
  )
}

/** Доли донат-диаграммой + легенда (для разрезов с малым числом категорий). */
function ShareDonut({ title, rows }: { title: string; rows: ChargeSessionLine[] }) {
  const total = rows.reduce((s, r) => s + r.amount, 0)
  const data = rows.map((r) => ({ name: r.label, value: Math.max(0, r.amount) }))
  const n = rows.length
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">{title}</div>
        <div className="flex items-center gap-4">
          <div className="relative shrink-0" style={{ width: 132, height: 132 }} data-chart>
            <ResponsiveContainer width={132} height={132}>
              <PieChart>
                <Pie data={data} dataKey="value" nameKey="name" innerRadius={44} outerRadius={62} paddingAngle={1.5} stroke="none" isAnimationActive={false}>
                  {data.map((_, i) => <Cell key={i} fill={seriesColor(i, n)} />)}
                </Pie>
                <RTooltip formatter={(value) => `${fmtMoney(Number(value))} ₽`} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <div className="text-sm font-semibold tabular-nums">{fmtMoneyShort(total)}</div>
              <div className="text-[9px] text-muted-foreground">₽ итого</div>
            </div>
          </div>
          <div className="min-w-0 flex-1 space-y-1.5 text-xs">
            {rows.map((r, i) => (
              <div key={r.label} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: seriesColor(i, n) }} />
                <span className="flex-1 truncate">{r.label}</span>
                <span className="font-mono tabular-nums text-muted-foreground">{fmtMoneyShort(r.amount)} ₽ · {r.share_pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']  // isodow 1..7

/** Heatmap загрузки: час × день недели (цвет = интенсивность). */
function ChargeHeatmap({ companyId, dateFrom, dateTo, tz }: { companyId: string; dateFrom: string; dateTo: string; tz?: Tz }) {
  const n = useNarrow()
  const { data, isLoading } = useQuery({
    queryKey: ['charge-heatmap', companyId, dateFrom, dateTo, n.key, tz ?? 'msk'],
    queryFn: () => getChargeHeatmap({ companyId, dateFrom, dateTo, metric: 'sessions', stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal, tz }),
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
      items.push(<div key={`${h}-${wd}`} title={`${WEEKDAYS[wd - 1]} ${String(h).padStart(2, '0')}:00 — ${nf0.format(v)} сессий`}
        className="h-4 rounded-sm" style={{ background: color(v) }} />)
    }
  }
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Загрузка: час × день недели (число сессий)</div>
        <div className="overflow-x-auto" data-chart>
          <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: '28px repeat(7, minmax(30px, 1fr))' }}>
            {items}
          </div>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">Темнее — выше загрузка. Пики → ToU-тарифы; «мёртвые» окна → ТО/скидки.</div>
      </CardContent>
    </Card>
  )
}

/** Время и загрузка — heatmap час×день + профиль по часам суток. */
function TimeLoad({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  // Часовой пояс анализа: по умолчанию МСК; «Местное» сдвигает час/день на пояс
  // региона станции (сеть от Калининграда до Камчатки — до +9 ч от МСК).
  const [tz, setTz] = useState<Tz>('msk')
  const { data, isLoading } = useCS(companyId, period.from, period.to, 'hour', tz)
  const tzNote = tz === 'local'
    ? 'Час — по местному времени станции (сдвиг на часовой пояс региона).'
    : 'Час — по московскому времени (как хранятся сессии).'
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-[11px] text-muted-foreground">{tzNote}</div>
        <TzToggle value={tz} onChange={setTz} />
      </div>
      {isLoading || !data || data.lines.length === 0 ? (isLoading ? <Loading /> : <Empty />) : (() => {
      const max = Math.max(...data.lines.map((l) => l.sessions), 1)
      return (
      <div className="space-y-4">
      <SessionKpis t={data.totals} />
      {data.lines.length >= 3 && (
        <div className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Распределение сессий по часам суток</div>
          <DistributionKpis lines={data.lines} metric="sessions" dimGen="час" topLabel="Пиковый час" bottomLabel="Тихий час" />
        </div>
      )}
      <ChargeHeatmap companyId={companyId} dateFrom={period.from} dateTo={period.to} tz={tz} />
      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Профиль по часам суток (число сессий)</div>
          <div className="space-y-1">
            {data.lines.map((l) => (
              <div key={l.label} className="flex items-center gap-2 text-xs">
                <span className="w-10 tabular-nums text-muted-foreground">{l.label}</span>
                <div className="flex-1 h-4 bg-muted/40 rounded overflow-hidden">
                  <div className="h-full bg-primary/70 rounded" style={{ width: `${l.sessions / max * 100}%` }} />
                </div>
                <span className="w-24 text-right font-mono tabular-nums">{nf0.format(l.sessions)} · {nf0.format(l.energy_kwh)}кВтч</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      </div>
      )
      })()}
    </div>
  )
}

const DYN_DEFAULTS = { metric: 'amount' as ChargeMetric, seriesSel: '__net__', bucket: 'month' as ChargeBucket, yoy: false }
const shiftYearISO = (iso: string, delta: number): string => {
  const d = new Date(iso); d.setFullYear(d.getFullYear() + delta); return isoLocal(d)
}

/** Динамика (тренд) метрики по бакетам времени + таблица детализации. */
function Dynamics({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('cs_dynamics', DYN_DEFAULTS)
  const [view, setView] = useChartView({ type: 'line' })
  // Горизонт анализа: не персистится и сбрасывается при смене периода наверху.
  const [horizon, setHorizon] = useState<Period | null>(null)
  useEffect(() => { setHorizon(null) }, [dateFrom, dateTo])
  const period = horizon ?? { from: dateFrom, to: dateTo }
  const seriesBy = p.seriesSel === '__net__' ? undefined : (p.seriesSel as ChargeSeriesBy)
  const n = useNarrow()

  const { data, isLoading, error } = useQuery({
    queryKey: ['charge-timeseries', companyId, period.from, period.to, p.bucket, p.metric, p.seriesSel, n.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom: period.from, dateTo: period.to, bucket: p.bucket, metric: p.metric, seriesBy, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
    enabled: !!period.from && !!period.to,
  })
  // YoY-оверлей — только для «Вся сеть» (одна линия): тот же интервал год назад.
  const yoyOn = p.yoy && p.seriesSel === '__net__'
  const prevFrom = shiftYearISO(period.from, -1), prevTo = shiftYearISO(period.to, -1)
  const prev = useQuery({
    queryKey: ['charge-timeseries-yoy', companyId, prevFrom, prevTo, p.bucket, p.metric, n.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom: prevFrom, dateTo: prevTo, bucket: p.bucket, metric: p.metric, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
    enabled: yoyOn,
  })
  const hasData = data && data.data.length > 0

  // Данные графика: обычные или совмещённые YoY (выравнивание по позиции бакета).
  const chartData = yoyOn && prev.data
    ? (data?.data ?? []).map((row, i) => ({ bucket: row.bucket, 'Текущий': row.value, 'Год назад': prev.data!.data[i]?.value ?? null }))
    : (data?.data ?? [])
  const chartSeries = yoyOn && prev.data ? ['Текущий', 'Год назад'] : (data?.series ?? [])

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
              {CHARGE_METRIC_LABELS[p.metric]}{yoyOn && <span className="normal-case text-muted-foreground/60"> · оверлей: {prevFrom.slice(0, 4)} vs {period.from.slice(0, 4)}</span>}
            </div>
            {hasData && !isLoading && <ChartControls view={view} onChange={setView} single={chartSeries.length === 1} metric={p.metric} />}
          </div>
          {isLoading ? <Loading /> : !hasData ? <Empty text="Нет данных за период" />
            : <ChargeChart data={chartData} series={chartSeries} metric={p.metric} view={view} />}
        </CardContent>
      </Card>
      {hasData && !error && <TrendTable data={data} metric={p.metric} />}
    </div>
  )
}

function TrendTable({ data, metric }: { data: ChargeTimeseriesResponse; metric: ChargeMetric }) {
  const exCols = ['Период', ...data.series.map((s) => (s === 'value' ? CHARGE_METRIC_LABELS[metric] : s))]
  const exData = data.data.map((row) => [String(row.bucket), ...data.series.map((s) => (row[s] ?? null) as string | number | null)])
  return (
    <Card>
      <CardContent className="p-0">
        <table className="w-full text-xs" {...exportRows('Динамика', exCols, exData)}>
          <thead>
            <tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="text-left p-2 font-medium">Период</th>
              {data.series.map((s) => (
                <th key={s} className="text-right p-2 font-medium">{s === 'value' ? CHARGE_METRIC_LABELS[metric] : s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.data.map((row) => (
              <tr key={String(row.bucket)} className="border-b border-border/30 hover:bg-muted/30">
                <td className="p-2 font-medium">{String(row.bucket)}</td>
                {data.series.map((s) => (
                  <td key={s} className="p-2 text-right font-mono">{fmtMetricCompact(metric, row[s] as number | null)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

/** Сравнение: два режима — нарезка одного периода и произвольные периоды. */
function Compare({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('cs_compare', { mode: 'slice' as 'slice' | 'manual' })
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

const SLICE_DEFAULTS = { bucket: 'month' as ChargeBucket, metric: 'amount' as ChargeMetric, seriesSel: '__net__', topN: 1000 }
const ROWS_OPTS: { value: number; label: string }[] = [
  { value: 10, label: 'Топ-10' }, { value: 25, label: 'Топ-25' },
  { value: 50, label: 'Топ-50' }, { value: 1000, label: 'Все' },
]

/** Нарезка одного периода на интервалы (неделя/декада/месяц/квартал) → сравнение. */
function SliceCompare({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [p, patch] = useTabParams('cs_compare/slice', SLICE_DEFAULTS)
  // Горизонт анализа: не персистится и сбрасывается при смене периода наверху.
  const [horizon, setHorizon] = useState<Period | null>(null)
  useEffect(() => { setHorizon(null) }, [dateFrom, dateTo])
  const period = horizon ?? { from: dateFrom, to: dateTo }
  const groupBy = p.seriesSel === '__net__' ? undefined : (p.seriesSel as ChargeSeriesBy)
  const n = useNarrow()

  const { data, isLoading, error } = useQuery({
    queryKey: ['charge-slice', companyId, period.from, period.to, p.bucket, p.metric, p.seriesSel, p.topN, n.key],
    queryFn: () => getChargeSlice({ companyId, dateFrom: period.from, dateTo: period.to, bucket: p.bucket, metric: p.metric, groupBy, topN: p.topN, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
    enabled: !!period.from && !!period.to,
  })
  const hasData = data && data.intervals.length > 0

  return (
    <div className="space-y-4">
      <ViewParamsBar>
        <HorizonControl horizon={horizon} scopeFrom={dateFrom} scopeTo={dateTo} onChange={setHorizon} />
        <Field label="Нарезка"><BucketSelect value={p.bucket} onChange={(b) => patch({ bucket: b })} only={['day', 'week', 'decade', 'month', 'quarter']} /></Field>
        <Field label="Метрика"><MetricSelect value={p.metric} onChange={(m) => patch({ metric: m })} /></Field>
        <Field label="Разрез"><SeriesSelect value={p.seriesSel} onChange={(v) => patch({ seriesSel: v })} withNet /></Field>
        {p.seriesSel !== '__net__' && (
          <Field label="Строк">
            <Select value={String(p.topN)} onValueChange={(v) => patch({ topN: Number(v) })}>
              <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{ROWS_OPTS.map((o) => <SelectItem key={o.value} value={String(o.value)} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
        )}
      </ViewParamsBar>
      {isLoading ? <Loading /> : !hasData || error ? <Empty text="Нет данных за период" />
        : <SliceView data={data} metric={p.metric} companyId={companyId} dateFrom={period.from} dateTo={period.to} bucket={p.bucket} narrow={n} />}
      {hasData && !error && (
        <NewClientsBlock companyId={companyId} dateFrom={period.from} dateTo={period.to} bucket={p.bucket} narrow={n} />
      )}
    </div>
  )
}

const SLICE_CHART_MAX = 12  // на графике — топ-N линий для читаемости; таблица показывает все
const RATIO_METRICS: ChargeMetric[] = ['avg_check', 'avg_energy', 'avg_duration_min', 'success_pct', 'price_per_kwh']
const BUCKET_UNIT: Record<string, string> = { day: 'день', week: 'неделя', decade: 'декада', month: 'месяц', quarter: 'квартал' }
const DIM_GEN: Record<string, string> = { station: 'станцию', connector: 'коннектор', user_type: 'клиента', charge_type: 'канал', region: 'регион', tariff: 'тариф', result: 'исход' }

/** Выделить ключ разреза из подписи строки для drill-down (станция: «Имя (код)» → код). */
function rowDimVal(groupBy: string, label: string): string {
  if (groupBy === 'station') { const m = label.match(/\(([^)]+)\)\s*$/); return m ? m[1] : label }
  if (groupBy === 'tariff') { const m = label.match(/^([\d.,]+)/); return m ? m[1] : label }
  return label
}

/** Значение метрики из строки-разреза (для распределения по разрезу). */
function lineMetricValue(metric: ChargeMetric, l: ChargeSessionLine): number {
  switch (metric) {
    case 'sessions': return l.sessions
    case 'energy_kwh': return l.energy_kwh
    case 'avg_check': return l.avg_check
    case 'avg_energy': return l.avg_energy
    case 'avg_duration_min': return l.avg_duration_min
    case 'success_pct': return l.success_pct
    case 'price_per_kwh': return l.price_per_kwh
    default: return l.amount
  }
}

/** 6 KPI сводки ВРЕМЕННОГО РЯДА: за период / среднее / пик(когда) / мин(когда) / тренд / стабильность. */
function PeriodSummaryKpis({ points, metric, unit }: { points: { label: string; v: number }[]; metric: ChargeMetric; unit: string }) {
  if (points.length === 0) return null
  const nums = points.map((x) => x.v)
  const isRatio = RATIO_METRICS.includes(metric)
  const total = nums.reduce((a, b) => a + b, 0)
  const mean = total / nums.length
  const peak = points.reduce((m, x) => (x.v > m.v ? x : m), points[0])
  const low = points.reduce((m, x) => (x.v < m.v ? x : m), points[0])
  const first = nums[0], last = nums[nums.length - 1]
  const trend = first ? (last - first) / first * 100 : 0
  const cv = mean ? Math.sqrt(nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length) / Math.abs(mean) * 100 : 0
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {/* Ряд у плиток уже на руках — показываем его там, где цифра о нём и говорит:
          итог, направление и разброс. «Пик» и «Минимум» точечные, им ряд не нужен. */}
      <KpiCard label="За период" value={fmtMetric(metric, isRatio ? mean : total)} accent="success" hint={isRatio ? 'среднее' : 'сумма'}
        spark={nums} sparkLabel={`Динамика по ${unit}`} />
      <KpiCard label={`Среднее / ${unit}`} value={fmtMetric(metric, mean)} />
      <KpiCard label="Пик" value={fmtMetric(metric, peak.v)} accent="info" hint={peak.label} />
      <KpiCard label="Минимум" value={fmtMetric(metric, low.v)} hint={low.label} />
      <KpiCard label="Тренд" value={`${trend >= 0 ? '+' : ''}${trend.toFixed(0)}%`} accent={trend >= 0 ? 'success' : 'danger'} hint="последний vs первый"
        spark={nums} sparkLabel="Как шёл ряд" />
      <KpiCard label="Стабильность" value={`${cv.toFixed(0)}%`} accent={cv <= 30 ? 'success' : cv <= 70 ? 'warning' : 'danger'} hint="разброс (CV)"
        spark={nums} sparkLabel="Колебания ряда" />
    </div>
  )
}

/** KPI РАСПРЕДЕЛЕНИЯ по разрезу. Суммовые метрики: итого/среднее/лидер/аутсайдер/концентрация.
 * Ratio-метрики (%, ₽/кВтч): среднее/лидер/аутсайдер/разброс (сумма процентов бессмысленна). */
function DistributionKpis({ lines, metric, dimGen, topLabel = 'Лидер', bottomLabel = 'Аутсайдер' }: {
  lines: ChargeSessionLine[]; metric: ChargeMetric; dimGen: string; topLabel?: string; bottomLabel?: string
}) {
  const pts = lines.filter((l) => l.label !== 'Прочие').map((l) => ({ label: l.label, v: lineMetricValue(metric, l) }))
    .filter((p) => Number.isFinite(p.v))
  if (pts.length === 0) return null
  const isRatio = RATIO_METRICS.includes(metric)
  const nums = pts.map((p) => p.v)
  const total = nums.reduce((a, b) => a + b, 0)
  const mean = total / nums.length
  const top = pts.reduce((m, x) => (x.v > m.v ? x : m), pts[0])
  const bottom = pts.reduce((m, x) => (x.v < m.v ? x : m), pts[0])
  const cv = mean ? Math.sqrt(nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length) / Math.abs(mean) * 100 : 0
  if (isRatio) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Среднее" value={fmtMetric(metric, mean)} accent="success" hint={`${pts.length} ${dimGen}`} />
        <KpiCard label={topLabel} value={fmtMetric(metric, top.v)} accent="info" hint={top.label} />
        <KpiCard label={bottomLabel} value={fmtMetric(metric, bottom.v)} accent="danger" hint={bottom.label} />
        <KpiCard label="Разброс" value={`${cv.toFixed(0)}%`} hint="разброс (CV)" />
      </div>
    )
  }
  const top3 = [...nums].sort((a, b) => b - a).slice(0, 3).reduce((a, b) => a + b, 0)
  const conc = total ? top3 / total * 100 : 0
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      <KpiCard label="Итого" value={fmtMetric(metric, total)} accent="success" hint={`${pts.length} ${dimGen}`} />
      <KpiCard label={`Среднее / ${dimGen}`} value={fmtMetric(metric, mean)} />
      <KpiCard label={topLabel} value={fmtMetric(metric, top.v)} accent="info" hint={top.label} />
      <KpiCard label={bottomLabel} value={fmtMetric(metric, bottom.v)} hint={bottom.label} />
      <KpiCard label="Концентрация" value={`${conc.toFixed(0)}%`} hint="доля топ-3" />
    </div>
  )
}

/** Сводка нарезки (полные интервалы) — обёртка PeriodSummaryKpis. */
function SliceKpis({ data, metric }: { data: ChargeSliceResponse; metric: ChargeMetric }) {
  const pts = data.intervals
    .map((iv, i) => ({ label: iv.label, v: data.totals.values[i], partial: iv.partial }))
    .filter((x) => !x.partial && x.v != null)
    .map((x) => ({ label: x.label, v: x.v as number }))
  return <PeriodSummaryKpis points={pts} metric={metric} unit="интервал" />
}

function SliceView({ data, metric, companyId, dateFrom, dateTo, bucket, narrow }: {
  data: ChargeSliceResponse; metric: ChargeMetric
  companyId: string; dateFrom: string; dateTo: string; bucket: ChargeBucket; narrow: Narrow
}) {
  const [compact, setCompact] = useState(true)
  const [view, setView] = useChartView()
  const [drill, setDrill] = useState<{ label: string; dimVal: string } | null>(null)
  const chartLines = data.lines.slice(0, SLICE_CHART_MAX)
  const series = chartLines.map((l) => l.label)
  const chartData = data.intervals.map((iv, i) => {
    const row: Record<string, string | number | null> = { bucket: iv.label }
    chartLines.forEach((l) => { row[l.label] = l.values[i] })
    return row
  })
  const truncated = data.lines.length > SLICE_CHART_MAX
  const columns = data.intervals.map((iv) => ({ label: iv.label, hint: `${iv.from.slice(5)}–${iv.to.slice(5)}`, partial: iv.partial }))
  const showTotals = data.group_by !== '__net__' && data.lines.length > 1
  const openRow = (label: string) => setDrill({ label, dimVal: data.group_by === '__net__' ? '' : rowDimVal(data.group_by, label) })
  const manyIntervals = data.intervals.length > 6

  // Сводка по каждой строке (без интервалов) — отдельный лист «Сводка» в Excel.
  const isRatioS = RATIO_METRICS.includes(metric)
  const summaryCols = [GROUP_LABELS[data.group_by] ?? 'Разрез', isRatioS ? 'Среднее' : 'Итого', 'Мин', 'Макс', 'Δ посл.', 'Δ %']
  const summaryRows: (string | number | null)[][] = data.lines.map((l) => {
    const nums = l.values.filter((v): v is number => v != null)
    const total = nums.reduce((a, b) => a + b, 0)
    return [l.label, isRatioS ? (nums.length ? total / nums.length : 0) : total, nums.length ? Math.min(...nums) : 0, nums.length ? Math.max(...nums) : 0, l.delta_prev, l.delta_pct_prev]
  })

  return (
    <div className="space-y-4">
      <ExportOnlyTable name="Сводка" columns={summaryCols} rows={summaryRows} />
      <SliceKpis data={data} metric={metric} />
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {CHARGE_METRIC_LABELS[metric]} по интервалам
              {truncated && <span className="normal-case text-muted-foreground/60"> · на графике топ-{SLICE_CHART_MAX} из {data.lines.length}</span>}
            </div>
            <ChartControls view={view} onChange={setView} single={series.length === 1} metric={metric} />
          </div>
          <ChargeChart data={chartData} series={series} metric={metric} view={view} />
        </CardContent>
      </Card>

      {manyIntervals && (
        <div className="flex items-center gap-1 justify-end" data-export-ignore>
          <span className="text-[11px] text-muted-foreground mr-1">Вид:</span>
          <Button variant={compact ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-2" onClick={() => setCompact(true)}>Компактно</Button>
          <Button variant={!compact ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-2" onClick={() => setCompact(false)}>Все интервалы</Button>
        </div>
      )}

      {compact && manyIntervals
        ? <SliceCompactTable data={data} metric={metric} onRow={openRow} drillable />
        : <ComparisonTable columns={columns} lines={data.lines} totalsValues={showTotals ? data.totals.values : undefined}
            metric={metric} firstCol={GROUP_LABELS[data.group_by] ?? 'Разрез'} onRow={openRow} />}

      {drill && (
        <RowDetailModal
          open={!!drill} onClose={() => setDrill(null)}
          companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} bucket={bucket} metric={metric}
          dim={data.group_by} dimVal={drill.dimVal} label={drill.label} narrow={narrow}
        />
      )}
    </div>
  )
}

/** Компактная таблица нарезки: строка + sparkline-тренд + сводка. Клик — детали. */
function SliceCompactTable({ data, metric, onRow, drillable }: {
  data: ChargeSliceResponse; metric: ChargeMetric; onRow: (label: string) => void; drillable: boolean
}) {
  const isRatio = RATIO_METRICS.includes(metric)
  const rows = data.lines.map((l) => {
    const nums = l.values.filter((v): v is number => v != null)
    const total = nums.reduce((a, b) => a + b, 0)
    return { l, agg: isRatio ? (nums.length ? total / nums.length : 0) : total, mn: nums.length ? Math.min(...nums) : 0, mx: nums.length ? Math.max(...nums) : 0 }
  })
  const firstCol = GROUP_LABELS[data.group_by] ?? 'Разрез'
  // Выгрузка компактного вида = ПОЛНАЯ матрица: все интервалы + сводка (не только сводка на экране).
  const exCols = [firstCol, ...data.intervals.map((iv) => iv.label), isRatio ? 'Среднее' : 'Итого', 'Мин', 'Макс', 'Δ посл.', 'Δ %']
  const exData: (string | number | null)[][] = rows.map((r) => [r.l.label, ...r.l.values, r.agg, r.mn, r.mx, r.l.delta_prev, r.l.delta_pct_prev])
  const deltaCls = (v: number) => (v > 0 ? 'text-emerald-600 dark:text-emerald-400' : v < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-1.5 text-[11px] text-muted-foreground border-b bg-muted/20">
          Значения: {CHARGE_METRIC_LABELS[metric]} · {data.intervals.length} интервалов{drillable && ' · клик по строке — детали'}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" {...exportRows(firstCol, exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium">{firstCol}</th>
                <th className="text-center p-2 font-medium">Тренд</th>
                <th className="text-right p-2 font-medium">{isRatio ? 'Среднее' : 'Итого'}</th>
                <th className="text-right p-2 font-medium">Мин</th>
                <th className="text-right p-2 font-medium">Макс</th>
                <th className="text-right p-2 font-medium whitespace-nowrap">Δ посл.</th>
                <th className="text-right p-2 font-medium">Δ %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.l.label} onClick={() => onRow(r.l.label)}
                  className={`border-b border-border/30 hover:bg-muted/30 ${drillable ? 'cursor-pointer' : ''}`}>
                  <td className="p-2 font-medium truncate max-w-[220px]">{r.l.label}</td>
                  <td className="p-2 text-center"><TrendSpark values={r.l.values} placeholder={<span className="text-muted-foreground/40">—</span>} /></td>
                  <td className="p-2 text-right font-mono">{fmtMetricCompact(metric, r.agg)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtMetricCompact(metric, r.mn)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtMetricCompact(metric, r.mx)}</td>
                  <td className={`p-2 text-right font-mono ${deltaCls(r.l.delta_prev)}`}>{r.l.delta_prev > 0 ? '+' : ''}{fmtMetricCompact(metric, r.l.delta_prev)}</td>
                  <td className={`p-2 text-right font-mono ${deltaCls(r.l.delta_pct_prev)}`}>{r.l.delta_pct_prev > 0 ? '+' : ''}{r.l.delta_pct_prev.toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

/** Мини-таблица под-разбивки в модалке (по коннекторам/клиентам). */
function MiniBreak({ title, data }: { title: string; data: ChargeSessionsResponse }) {
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">{title}</div>
        <table className="w-full text-xs">
          <tbody>
            {data.lines.map((l) => (
              <tr key={l.label} className="border-b border-border/30">
                <td className="p-2 font-medium truncate max-w-[160px]">{l.label}</td>
                <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.sessions)} сес.</td>
                <td className="p-2 text-right font-mono">{fmtMoney(l.amount)} ₽</td>
                <td className="p-2 text-right font-mono text-muted-foreground">{l.share_pct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

/** Модалка деталей строки: кросс-метрики + тренд по интервалам + под-разбивки. */
function RowDetailModal({ open, onClose, companyId, dateFrom, dateTo, bucket, metric, dim, dimVal, label, narrow }: {
  open: boolean; onClose: () => void
  companyId: string; dateFrom: string; dateTo: string; bucket: ChargeBucket; metric: ChargeMetric
  dim: string; dimVal: string; label: string; narrow: Narrow
}) {
  const isNet = dim === '__net__'
  const fdim = isNet ? undefined : dim
  const base = { companyId, dateFrom, dateTo, dim: fdim, dimVal: fdim ? dimVal : undefined, stations: narrow.stations, regions: narrow.regions }
  const k = `${companyId}|${dateFrom}|${dateTo}|${dim}|${dimVal}|${narrow.key}`
  const totalsQ = useQuery({ queryKey: ['drill-tot', k], queryFn: () => getChargeSessions({ ...base, groupBy: 'result' }) })
  const sliceQ = useQuery({ queryKey: ['drill-slice', k, bucket, metric], queryFn: () => getChargeSlice({ ...base, bucket, metric }) })
  const connQ = useQuery({ queryKey: ['drill-conn', k], queryFn: () => getChargeSessions({ ...base, groupBy: 'connector' }), enabled: dim !== 'connector' })
  const usrQ = useQuery({ queryKey: ['drill-usr', k], queryFn: () => getChargeSessions({ ...base, groupBy: 'user_type' }), enabled: dim !== 'user_type' })

  const t = totalsQ.data?.totals
  const line = sliceQ.data?.lines[0]
  const chartData = sliceQ.data ? sliceQ.data.intervals.map((iv, i) => ({ bucket: iv.label, value: line?.values[i] ?? null })) : []

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-6xl w-[94vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base">{isNet ? 'Вся сеть' : `${GROUP_LABELS[dim] ?? 'Разрез'}: ${label}`}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {t ? <SessionKpis t={t} /> : <Loading />}
          <div className="grid lg:grid-cols-[1.55fr_1fr] gap-4 items-start">
            <div className="space-y-4">
              <Card>
                <CardContent className="pt-4">
                  <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">{CHARGE_METRIC_LABELS[metric]} по интервалам</div>
                  {sliceQ.data && chartData.length ? <ChargeBarChart data={chartData} series={['value']} metric={metric} /> : <Loading />}
                </CardContent>
              </Card>
              {(connQ.data || usrQ.data) && (
                <div className="grid sm:grid-cols-2 gap-3">
                  {dim !== 'connector' && connQ.data && <MiniBreak title="По коннекторам" data={connQ.data} />}
                  {dim !== 'user_type' && usrQ.data && <MiniBreak title="По клиентам (ФЛ/ЮЛ)" data={usrQ.data} />}
                </div>
              )}
            </div>
            {line && sliceQ.data && (
              <Card>
                <CardContent className="p-0">
                  <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">По интервалам</div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b bg-muted/40 text-muted-foreground">
                          <th className="text-left p-2 font-medium">Интервал</th>
                          <th className="text-right p-2 font-medium">{CHARGE_METRIC_LABELS[metric]}</th>
                          <th className="text-right p-2 font-medium">Δ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sliceQ.data.intervals.map((iv, i) => {
                          const v = line.values[i]; const prev = i > 0 ? line.values[i - 1] : null
                          const d = v != null && prev != null ? v - prev : null
                          return (
                            <tr key={iv.label} className={`border-b border-border/30 ${iv.partial ? 'text-muted-foreground/50' : ''}`}>
                              <td className="p-2">{iv.label}{iv.partial && <span className="text-amber-600/70 dark:text-amber-400/70"> *</span>}</td>
                              <td className="p-2 text-right font-mono">{fmtMetricCompact(metric, v)}</td>
                              <td className={`p-2 text-right font-mono ${d == null ? '' : d > 0 ? 'text-emerald-600 dark:text-emerald-400' : d < 0 ? 'text-red-600 dark:text-red-400' : ''}`}>
                                {d == null ? '—' : (d > 0 ? '+' : '') + fmtMetricCompact(metric, d)}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/* ── Когорты: НОВЫЕ клиенты (впервые за всю историю наблюдений) ─────────────── */

const fmtRub0 = (v: number) => nf0.format(Math.round(v)) + ' ₽'

/** Маркер ленивого листа Excel: экспортёр дотянет СПИСОК новых клиентов периода
 * с сервера и добавит лист «Новые {label}» (см. chargeExport: data-export-newclients). */
function NewClientsExportMarker({ companyId, from, to, label, narrow }: {
  companyId: string; from: string; to: string; label: string; narrow: Narrow
}) {
  return (
    <span hidden aria-hidden data-export-newclients={JSON.stringify({
      companyId, from, to, label,
      stations: narrow.stations, regions: narrow.regions, dim: narrow.dim, dimVal: narrow.dimVal,
    })} />
  )
}

/** Модалка: конкретные новые клиенты интервала (кто, когда впервые, вклад). */
function NewClientsListModal({ companyId, interval, narrow, onClose }: {
  companyId: string
  interval: { from: string; to: string; label: string } | null
  narrow: Narrow
  onClose: () => void
}) {
  const [q, setQ] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['charge-new-clients-list', companyId, interval?.from, interval?.to, narrow.key],
    queryFn: () => getChargeNewClientsList({
      companyId, dateFrom: interval!.from, dateTo: interval!.to, limit: 1000,
      stations: narrow.stations, regions: narrow.regions, dim: narrow.dim, dimVal: narrow.dimVal,
    }),
    enabled: !!interval,
  })
  const rows = useMemo(() => {
    const all = data?.clients ?? []
    const t = q.trim().toLowerCase()
    if (!t) return all
    return all.filter((c) =>
      (c.clientName || '').toLowerCase().includes(t) || (c.userId || '').toLowerCase().includes(t))
  }, [data, q])
  const exCols = ['Клиент', 'Тип', 'Первая сессия', 'Сессий', 'кВт·ч', 'Выручка, ₽', 'ЭЗС']
  const exData = rows.map((c) => [c.clientName || c.userId || c.key, c.userType, c.firstAt, c.sessions, c.kwh, c.revenue, c.stations] as (string | number | null)[])
  return (
    <Dialog open={!!interval} onOpenChange={(v) => { if (!v) { setQ(''); onClose() } }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="pr-6">Новые клиенты · {interval?.label}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          Клиенты, впервые зарядившиеся в этом интервале (не встречались за всю историю наблюдений ранее).
          {data && <> Всего <b className="text-foreground">{nf0.format(data.count)}</b>{data.count > (data.clients?.length ?? 0) && <> · показаны первые {data.clients.length} по выручке</>}.</>}
        </p>
        <div className="flex items-center gap-2">
          <input
            value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: организация или телефон"
            className="h-8 w-[260px] rounded-md border border-input bg-transparent px-2 text-xs outline-none focus:ring-1 focus:ring-ring"
          />
          <Button variant="outline" size="sm" className="h-8 text-xs" disabled={!data?.clients?.length}
            onClick={() => data && import('@/services/chargeExport').then((m) =>
              m.exportNewClientsXlsx(interval?.label ?? '', data.count, rows))}>
            Скачать xlsx{q.trim() ? ' (найденные)' : ''}
          </Button>
        </div>
        {isLoading ? <Loading /> : (
          <div className="max-h-[52vh] overflow-auto rounded-md border border-border/40">
            <table className="w-full text-xs" {...exportRows(`Новые клиенты ${interval?.label ?? ''}`, exCols, exData)}>
              <thead className="sticky top-0 bg-card">
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-2 text-left font-medium">Клиент</th>
                  <th className="p-2 text-left font-medium">Тип</th>
                  <th className="p-2 text-left font-medium">Первая сессия</th>
                  <th className="p-2 text-right font-medium">Сессий</th>
                  <th className="p-2 text-right font-medium">кВт·ч</th>
                  <th className="p-2 text-right font-medium">Выручка</th>
                  <th className="p-2 text-right font-medium">ЭЗС</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.key} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-medium">{c.clientName || c.userId || c.key}</td>
                    <td className="p-2 text-muted-foreground">{c.userType || '—'}</td>
                    <td className="p-2 font-mono text-muted-foreground">{c.firstAt || '—'}</td>
                    <td className="p-2 text-right font-mono">{nf0.format(c.sessions)}</td>
                    <td className="p-2 text-right font-mono">{nf1.format(c.kwh)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub0(c.revenue)}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{c.stations}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** Блок «Новые клиенты по интервалам» (нарезка периода). Клик по строке — список. */
function NewClientsBlock({ companyId, dateFrom, dateTo, bucket, narrow }: {
  companyId: string; dateFrom: string; dateTo: string; bucket: ChargeBucket; narrow: Narrow
}) {
  const [sel, setSel] = useState<{ from: string; to: string; label: string } | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['charge-new-clients', companyId, dateFrom, dateTo, bucket, narrow.key],
    queryFn: () => getChargeNewClients({
      companyId, dateFrom, dateTo, bucket,
      stations: narrow.stations, regions: narrow.regions, dim: narrow.dim, dimVal: narrow.dimVal,
    }),
    enabled: !!dateFrom && !!dateTo,
  })
  if (isLoading || !data || data.intervals.length === 0) return null
  const iv = data.intervals
  const histNote = data.historyFrom && data.historyFrom >= dateFrom
  const exCols = ['Интервал', 'Активных клиентов', 'Новых', 'Доля новых, %', 'Вернувшихся', 'Сессии новых', 'кВт·ч новых', 'Выручка новых, ₽', 'Доля выручки новых, %']
  const exData = iv.map((r) => [r.label, r.activeClients, r.newClients, r.newSharePct, r.returningClients, r.newSessions, r.newKwh, r.newRevenue, r.newRevenueSharePct] as (string | number | null)[])
  const dim = (r: ChargeNewClientsInterval) => (r.partial ? 'text-muted-foreground/40' : '')
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b bg-muted/20 px-3 py-1.5">
          <span className="text-[11px] font-medium">Новые клиенты по интервалам</span>
          <span className="text-[11px] text-muted-foreground">
            впервые за всю историю наблюдений · клик по строке — конкретные клиенты
          </span>
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            за период: новых {nf0.format(data.totals.newClients)} · выручка новых {fmtRub0(data.totals.newRevenue)}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Новые клиенты', exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="p-2 text-left font-medium">Интервал</th>
                <th className="p-2 text-right font-medium">Активных</th>
                <th className="p-2 text-right font-medium">Новых</th>
                <th className="p-2 text-right font-medium">Доля новых</th>
                <th className="p-2 text-right font-medium">Вернувшихся</th>
                <th className="p-2 text-right font-medium">Сессии новых</th>
                <th className="p-2 text-right font-medium">кВт·ч новых</th>
                <th className="p-2 text-right font-medium">Выручка новых</th>
                <th className="p-2 text-right font-medium">Доля выручки</th>
              </tr>
            </thead>
            <tbody>
              {iv.map((r) => (
                <tr key={r.key} className="cursor-pointer border-b border-border/30 hover:bg-muted/30"
                  onClick={() => setSel({ from: r.from, to: r.to, label: r.label })}>
                  <td className={`p-2 font-medium whitespace-nowrap ${dim(r)}`}>{r.label}{r.partial ? ' *' : ''}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf0.format(r.activeClients)}</td>
                  <td className={`p-2 text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400 ${r.partial ? 'opacity-40' : ''}`}>{nf0.format(r.newClients)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{r.newSharePct != null ? `${r.newSharePct}%` : '—'}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf0.format(r.returningClients)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf0.format(r.newSessions)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{nf1.format(r.newKwh)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{fmtRub0(r.newRevenue)}</td>
                  <td className={`p-2 text-right font-mono ${dim(r)}`}>{r.newRevenueSharePct != null ? `${r.newRevenueSharePct}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="px-3 py-1.5 text-[11px] text-muted-foreground/70">
          * — неполный интервал (выходит за границы периода).
          {histNote && <> История наблюдений начинается {data.historyFrom} — в первом интервале «новыми» выглядят и давние клиенты.</>}
          {' '}Клиент = организация (ЮЛ) или телефон (ФЛ); учитываются выбранные фильтры (станции/регион/тип клиента).
          {' '}В Excel-экспорт попадают и списки конкретных клиентов (лист на интервал).
        </p>
        {/* ленивые листы Excel: списки клиентов по завершённым интервалам (cap 12, чтобы day-нарезка не плодила сотни листов) */}
        {iv.filter((r) => !r.partial && r.newClients > 0).slice(-12).map((r) => (
          <NewClientsExportMarker key={`ex-${r.key}`} companyId={companyId}
            from={r.from} to={r.to} label={r.label} narrow={narrow} />
        ))}
      </CardContent>
      <NewClientsListModal companyId={companyId} interval={sel} narrow={narrow} onClose={() => setSel(null)} />
    </Card>
  )
}

/** Новые клиенты для произвольных периодов сравнения: карточка на период.
 * Счётчики также уходят в Excel-экспорт (скрытая таблица «Новые клиенты»). */
function NewClientsManualBlock({ companyId, periods, narrow }: {
  companyId: string; periods: Period[]; narrow: Narrow
}) {
  const [sel, setSel] = useState<{ from: string; to: string; label: string } | null>(null)
  const results = useQueries({
    queries: periods.map((per) => ({
      queryKey: ['charge-new-clients-list', companyId, per.from, per.to, narrow.key, 'card'],
      queryFn: () => getChargeNewClientsList({
        companyId, dateFrom: per.from, dateTo: per.to, limit: 1,
        stations: narrow.stations, regions: narrow.regions, dim: narrow.dim, dimVal: narrow.dimVal,
      }),
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
          <span className="text-[11px] font-medium">Новые клиенты по периодам</span>
          <span className="text-[11px] text-muted-foreground">впервые за всю историю · клик — конкретные клиенты</span>
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
              <div className="text-[11px] text-muted-foreground">новых клиентов</div>
            </button>
          ))}
        </div>
        <ExportOnlyTable name="Новые клиенты"
          columns={['Период', 'С', 'По', 'Новых клиентов']} rows={exData} />
        {/* ленивые листы Excel: список клиентов на каждый сравниваемый период */}
        {periods.map((per, i) => (
          <NewClientsExportMarker key={`ex-${per.from}-${per.to}`} companyId={companyId}
            from={per.from} to={per.to} label={`П${i + 1} ${per.from.slice(5)}—${per.to.slice(5)}`} narrow={narrow} />
        ))}
      </CardContent>
      <NewClientsListModal companyId={companyId} interval={sel} narrow={narrow} onClose={() => setSel(null)} />
    </Card>
  )
}

const MANUAL_DEFAULTS = { metric: 'amount' as ChargeMetric, groupBy: 'station' as ChargeSeriesBy, periods: null as Period[] | null }

/** Произвольные периоды (2–4) по выбранному разрезу и метрике. */
function ManualCompare({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const anchor: Period = { from: dateFrom, to: dateTo }
  const [p, patch] = useTabParams('cs_compare/manual', MANUAL_DEFAULTS)
  const periods = p.periods ?? buildMoM(anchor, 3)  // до первого изменения — 3 месяца от периода раздела
  const n = useNarrow()

  const ready = periods.length >= 2 && periods.every((x) => x.from && x.to)
  const { data, isLoading, error } = useQuery({
    queryKey: ['charge-compare-multi', companyId, JSON.stringify(periods), p.metric, p.groupBy, n.key],
    queryFn: () => getChargeCompareMulti({ companyId, periods, metric: p.metric, groupBy: p.groupBy, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
    enabled: ready,
  })

  return (
    <div className="space-y-4">
      <MultiPeriodPicker periods={periods} onChange={(np) => patch({ periods: np })} anchor={anchor} />
      <ViewParamsBar>
        <Field label="Метрика"><MetricSelect value={p.metric} onChange={(m) => patch({ metric: m })} /></Field>
        <Field label="Разрез"><SeriesSelect value={p.groupBy} onChange={(v) => patch({ groupBy: v as ChargeSeriesBy })} /></Field>
      </ViewParamsBar>
      {!ready ? <Empty text="Задайте минимум 2 периода" />
        : isLoading ? <Loading />
        : (error || !data) ? <Empty text="Нет данных для сравнения" />
        : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {data.periods.map((per, i) => (
                <KpiCard key={i} label={`Период ${i + 1}`} value={fmtMetric(p.metric, data.totals.values[i])}
                  hint={`${per.from} — ${per.to}`} accent={i === data.periods.length - 1 ? 'success' : undefined} />
              ))}
            </div>
            <ComparisonTable
              columns={data.periods.map((per, i) => ({ label: `П${i + 1}`, hint: `${per.from.slice(5)}—${per.to.slice(5)}` }))}
              lines={data.lines} metric={p.metric} firstCol={GROUP_LABELS[data.group_by] ?? 'Разрез'} />
            <NewClientsManualBlock companyId={companyId} periods={periods} narrow={n} />
          </div>
        )}
    </div>
  )
}

/** Общая таблица сравнения: строки = разрез, колонки = интервалы/периоды + дельты.
 * Неполные интервалы (частично вне периода) приглушены и не идут в расчёт Δ. */
type SortKey = 'label' | 'delta_prev' | 'delta_pct' | number

function ComparisonTable({ columns, lines, totalsValues, metric, firstCol, onRow }: {
  columns: { label: string; hint?: string; partial?: boolean }[]
  lines: { label: string; values: (number | null)[]; delta_prev: number; delta_pct_prev: number }[]
  totalsValues?: number[]
  metric: ChargeMetric
  firstCol: string
  onRow?: (label: string) => void
}) {
  const deltaCls = (v: number) => (v > 0 ? 'text-emerald-600 dark:text-emerald-400' : v < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')
  const cellDim = (i: number) => (columns[i]?.partial ? 'text-muted-foreground/40' : '')
  const hasPartial = columns.some((c) => c.partial)

  // Сортировка по клику на заголовок: desc → asc → сброс. «Прочие» всегда внизу.
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' } | null>(null)
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s && s.key === key ? (s.dir === 'desc' ? { key, dir: 'asc' } : null) : { key, dir: 'desc' }))

  const sortedLines = useMemo(() => {
    if (!sort) return lines
    const others = lines.filter((l) => l.label === 'Прочие')
    const rest = lines.filter((l) => l.label !== 'Прочие')
    const dir = sort.dir === 'asc' ? 1 : -1
    const val = (l: typeof lines[number]) =>
      sort.key === 'delta_prev' ? l.delta_prev : sort.key === 'delta_pct' ? l.delta_pct_prev : l.values[sort.key as number]
    const norm = (v: number | null | undefined) => (v == null ? (sort.dir === 'asc' ? Infinity : -Infinity) : v)  // null всегда внизу
    rest.sort((a, b) =>
      sort.key === 'label' ? dir * a.label.localeCompare(b.label, 'ru') : dir * (norm(val(a)) - norm(val(b))))
    return [...rest, ...others]
  }, [lines, sort])

  const HdBtn = ({ k, children, left }: { k: SortKey; children: ReactNode; left?: boolean }) => {
    const dir = sort && sort.key === k ? sort.dir : null
    const Ico = dir === 'asc' ? ArrowUp : dir === 'desc' ? ArrowDown : ChevronsUpDown
    return (
      <button onClick={() => toggleSort(k)} title="Сортировать по столбцу"
        className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${left ? '' : 'flex-row-reverse'} ${dir ? 'text-foreground' : ''}`}>
        <span className="whitespace-nowrap">{children}</span>
        <Ico className={`h-3 w-3 shrink-0 ${dir ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
      </button>
    )
  }

  // Выгрузка полного вида = интервалы + сводка (Итого/Среднее·Мин·Макс) + Δ — как в компактном.
  const isRatioC = RATIO_METRICS.includes(metric)
  const aggOf = (vals: (number | null)[]) => {
    const nums = vals.filter((v): v is number => v != null)
    const total = nums.reduce((a, b) => a + b, 0)
    return { a: isRatioC ? (nums.length ? total / nums.length : 0) : total, mn: nums.length ? Math.min(...nums) : 0, mx: nums.length ? Math.max(...nums) : 0 }
  }
  const exCols = [firstCol, ...columns.map((c) => c.label), isRatioC ? 'Среднее' : 'Итого', 'Мин', 'Макс', 'Δ посл.', 'Δ %']
  const exData: (string | number | null)[][] = [
    ...sortedLines.map((l) => { const s = aggOf(l.values); return [l.label, ...l.values, s.a, s.mn, s.mx, l.delta_prev, l.delta_pct_prev] }),
    ...(totalsValues ? [(() => { const s = aggOf(totalsValues); return ['Итого (сеть)', ...totalsValues, s.a, s.mn, s.mx, '', ''] as (string | number | null)[] })()] : []),
  ]

  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-1.5 text-[11px] text-muted-foreground border-b bg-muted/20">
          Значения: {CHARGE_METRIC_LABELS[metric]}
        </div>
        <div className="overflow-x-auto">
        <table className="w-full text-xs" {...exportRows(firstCol, exCols, exData)}>
          <thead>
            <tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="text-left p-2 font-medium sticky left-0 bg-muted/40 z-10"><HdBtn k="label" left>{firstCol}</HdBtn></th>
              {columns.map((c, i) => (
                <th key={i} className={`text-right p-2 font-medium whitespace-nowrap ${c.partial ? 'text-muted-foreground/50' : ''}`}>
                  <HdBtn k={i}>{c.label}{c.partial && <span className="text-amber-600/70 dark:text-amber-400/70"> *</span>}</HdBtn>
                  {c.hint && <div className="text-[10px] font-normal text-muted-foreground/70">{c.hint}{c.partial ? ' · неполн.' : ''}</div>}
                </th>
              ))}
              <th className="text-right p-2 font-medium whitespace-nowrap"><HdBtn k="delta_prev">Δ посл.</HdBtn></th>
              <th className="text-right p-2 font-medium"><HdBtn k="delta_pct">Δ %</HdBtn></th>
            </tr>
          </thead>
          <tbody>
            {sortedLines.map((l) => (
              <tr key={l.label} onClick={() => onRow?.(l.label)}
                className={`border-b border-border/30 hover:bg-muted/30 ${onRow ? 'cursor-pointer' : ''}`}>
                <td className="p-2 font-medium truncate max-w-[200px] sticky left-0 bg-background z-10">{l.label}</td>
                {l.values.map((v, i) => (
                  <td key={i} className={`p-2 text-right font-mono whitespace-nowrap ${cellDim(i)}`}>{fmtMetricCompact(metric, v)}</td>
                ))}
                <td className={`p-2 text-right font-mono whitespace-nowrap ${deltaCls(l.delta_prev)}`}>
                  {l.delta_prev > 0 ? '+' : ''}{fmtMetricCompact(metric, l.delta_prev)}
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
                  <td key={i} className={`p-2 text-right font-mono whitespace-nowrap ${cellDim(i)}`}>{fmtMetricCompact(metric, v)}</td>
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

/** Повторные попытки: разбор составных визитов.
 *
 * CPO пишет каждое касание разъёма отдельной сессией, поэтому «31% сессий с
 * ошибкой» смешивает два разных факта: человек не смог зарядиться (потеря) и
 * человек зарядился с третьего раза (проблема качества, но не потеря). Здесь
 * они разведены: успех считается по визиту, а повторные попытки показаны как
 * самостоятельный показатель — с адресами, где именно они происходят. */
function RetryAnalysis({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const n = useNarrow()
  const q = useQuery({
    queryKey: ['charge-visits', companyId, dateFrom, dateTo, n.key],
    queryFn: () => getChargeVisits({
      companyId, dateFrom, dateTo, stations: n.stations, regions: n.regions, top: 15,
    }),
  })
  if (q.isLoading) return <Loading />
  if (!q.data || q.data.totals.visits === 0) return <Empty text="Нет визитов за период" />
  const { totals: t, distribution, stations, connectors, clients, worst, gap_min } = q.data

  const dimTable = (title: string, rows: typeof stations, dimLabel: string, note?: string) => (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40 flex items-baseline justify-between gap-2">
          <span>{title}</span>
          {note ? <span className="text-[10px] font-normal normal-case">{note}</span> : null}
        </div>
        {rows.length === 0
          ? <div className="p-3 text-xs text-muted-foreground">Недостаточно данных за период</div>
          : (
            <table className="w-full text-xs" {...exportRows(title, [dimLabel, 'Визитов', 'Зарядились', 'С повторами', 'Доля повторов, %', 'Ср. попыток', 'Впустую сессий'],
              rows.map((r) => [r.label, r.visits, r.charged, r.retried,
                +(r.retried / r.visits * 100).toFixed(1), r.avg_attempts, r.wasted]))}>
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">{dimLabel}</th>
                  <th className="text-right p-2 font-medium">Визитов</th>
                  <th className="text-right p-2 font-medium" title="Визиты, где зарядка получилась не с первой попытки">С повторами</th>
                  <th className="text-right p-2 font-medium">Ср. попыток</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const share = r.retried / r.visits * 100
                  return (
                    <tr key={r.label} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-medium truncate max-w-[220px]" title={r.label}>{r.label}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.visits)}</td>
                      <td className={`p-2 text-right font-mono ${share >= 40 ? 'text-red-600 dark:text-red-400' : share >= 25 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                        {nf0.format(r.retried)} <span className="opacity-60">({share.toFixed(0)}%)</span>
                      </td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.avg_attempts)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
      </CardContent>
    </Card>
  )

  const maxDist = Math.max(...distribution.map((d) => d.visits), 1)

  return (
    <div className="p-4 space-y-4">
      {/* Метод склейки — не прячем: от порога зависят все цифры ниже. */}
      <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
        <span className="font-semibold text-foreground">Визит</span> — попытки одного клиента на одной станции
        с разрывом до <span className="font-mono">{gap_min}</span> мин. Успех визита = отпущена энергия
        (а не флаг <span className="font-mono">Complete</span> от CPO).
        {' '}Сырых сессий за период: <span className="font-mono">{nf0.format(t.sessions)}</span> → визитов: <span className="font-mono">{nf0.format(t.visits)}</span>.
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label="Визитов" value={nf0.format(t.visits)} hint={`из ${nf0.format(t.sessions)} сессий`} />
        <KpiCard label="Зарядились" value={t.success_pct.toFixed(1) + '%'} accent={succAccent(t.success_pct)}
          hint={`${nf0.format(t.charged)} визитов`} info={HINTS.visitSuccess} />
        <KpiCard label="С повторами" value={nf0.format(t.retried)} accent={t.retried_pct >= 25 ? 'warning' : 'info'}
          hint={`${t.retried_pct.toFixed(1)}% успешных — зарядились не сразу`} />
        <KpiCard label="Не зарядились" value={nf0.format(t.failed)} accent="danger"
          hint={`${(100 - t.success_pct).toFixed(1)}% визитов брошено`} />
        <KpiCard label="Впустую" value={nf0.format(t.wasted_sessions)} accent="warning"
          hint="сессий без отпуска энергии" />
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Сколько попыток потребовалось
            </div>
            <table className="w-full text-xs" {...exportRows('Попытки в визите', ['Попыток', 'Визитов', 'Зарядились', 'Доля успеха, %'],
              distribution.map((d) => [d.attempts >= 6 ? '6+' : d.attempts, d.visits, d.charged,
                +(d.charged / d.visits * 100).toFixed(1)]))}>
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Попыток</th>
                  <th className="text-right p-2 font-medium">Визитов</th>
                  <th className="text-right p-2 font-medium">Зарядились</th>
                </tr>
              </thead>
              <tbody>
                {distribution.map((d) => (
                  <tr key={d.attempts} className="border-b border-border/30">
                    <td className="p-2 font-medium">
                      {d.attempts === 1 ? 'с первой' : d.attempts >= 6 ? '6 и более' : `${d.attempts}`}
                    </td>
                    <td className="p-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {/* Полоса — чтобы хвост «борьбы с разъёмом» читался глазом, а не вычислялся. */}
                        <div className="h-1.5 rounded-full bg-primary/60" style={{ width: `${Math.max(2, d.visits / maxDist * 90)}px` }} />
                        <span className="font-mono text-muted-foreground">{nf0.format(d.visits)}</span>
                      </div>
                    </td>
                    <td className={`p-2 text-right font-mono ${succTxt(d.charged / d.visits * 100)}`}>
                      {(d.charged / d.visits * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {dimTable('Коннекторы', connectors, 'Коннектор')}
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        {dimTable('Станции с повторными попытками', stations, 'Станция', 'топ по доле, ≥10 визитов')}
        {dimTable('Клиенты, которым тяжелее всех', clients, 'Клиент', 'топ по доле, ≥10 визитов')}
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
            Самые тяжёлые визиты — конкретные случаи для разбора
          </div>
          <table className="w-full text-xs" {...exportRows('Тяжёлые визиты', ['Дата', 'Станция', 'Регион', 'Коннектор', 'Клиент', 'Попыток', 'Впустую', 'кВтч', 'Итог'],
            worst.map((r) => [r.first_at.slice(0, 16).replace('T', ' '), r.station, r.region, r.connector_type,
              r.client, r.attempts, r.wasted, r.kwh, r.charged ? 'зарядился' : 'не зарядился']))}>
            <thead>
              <tr className="border-b bg-muted/20 text-muted-foreground">
                <th className="text-left p-2 font-medium">Дата</th>
                <th className="text-left p-2 font-medium">Станция</th>
                <th className="text-left p-2 font-medium">Коннектор</th>
                <th className="text-right p-2 font-medium">Попыток</th>
                <th className="text-right p-2 font-medium">кВтч</th>
                <th className="text-left p-2 font-medium">Итог</th>
              </tr>
            </thead>
            <tbody>
              {worst.map((r) => (
                <tr key={r.visit_key} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-mono text-muted-foreground whitespace-nowrap">{r.first_at.slice(0, 16).replace('T', ' ')}</td>
                  <td className="p-2 font-medium truncate max-w-[200px]" title={`${r.station} · ${r.region ?? ''}`}>{r.station}</td>
                  <td className="p-2 text-muted-foreground">{r.connector_type ?? '—'}</td>
                  <td className="p-2 text-right font-mono text-red-600 dark:text-red-400">{r.attempts}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.kwh)}</td>
                  <td className="p-2">
                    {r.charged
                      ? <span className="text-[11px] rounded border border-emerald-400/50 px-1.5 py-0.5 text-emerald-600 dark:text-emerald-300/80">зарядился</span>
                      : <span className="text-[11px] rounded border border-red-400/50 px-1.5 py-0.5 text-red-600 dark:text-red-300/80">не зарядился</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {t.unpaid > 0 && (
        <div className="rounded-lg border border-amber-400/40 bg-amber-400/5 px-3 py-2 text-[11px] text-muted-foreground">
          <span className="font-semibold text-amber-600 dark:text-amber-400">Без оплаты:</span>{' '}
          {nf0.format(t.unpaid)} визитов с отпуском энергии не имеют отметки оплаты
          ({(t.unpaid / t.charged * 100).toFixed(1)}% успешных). Это отдельный контур —
          энергия отпущена, деньги не подтверждены.
        </div>
      )}
    </div>
  )
}

/** Без оплаты: отпуск энергии, за который не пришли деньги.
 *
 * «Сессия без отметки оплаты» — один ярлык на три разных факта, и общий счётчик
 * их путает. Долг розницы — настоящая дыра. Постоплата ЮЛ — ожидаемое состояние
 * (счёт за период), это дебиторка, а не убыток. Пробы без энергии — ноль в
 * деньгах, но именно они раздувают долю «неоплаченных» и пугают зря. */
/** Раскрытая станция: кто именно уехал не заплатив и какие ЮЛ ждут счёта.
 * Сводная цифра без имён не подсказывает, что делать дальше. */
function UnpaidStationDetailRow({ companyId, dateFrom, dateTo, code, colSpan }: {
  companyId: string; dateFrom: string; dateTo: string; code: string; colSpan: number
}) {
  const q = useQuery({
    queryKey: ['charge-unpaid-station', companyId, dateFrom, dateTo, code],
    queryFn: () => getChargeUnpaidStation({ companyId, dateFrom, dateTo, code }),
  })
  return (
    <tr className="bg-muted/20">
      <td colSpan={colSpan} className="p-3">
        {q.isLoading ? <div className="text-[11px] text-muted-foreground">Загрузка…</div> : !q.data ? null : (
          <div className="space-y-3">
            {q.data.retail.length > 0 && (
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-red-600 dark:text-red-400">
                  Уехали не заплатив ({q.data.retail.length})
                </div>
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-muted-foreground">
                      <th className="text-left py-1 font-medium">Дата</th>
                      <th className="text-left py-1 font-medium">Аккаунт</th>
                      <th className="text-left py-1 font-medium">Коннектор</th>
                      <th className="text-right py-1 font-medium">кВтч</th>
                      <th className="text-right py-1 font-medium">Сумма</th>
                      <th className="text-left py-1 font-medium">Исход</th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.retail.map((r) => (
                      <tr key={r.session_ext_id} className="border-t border-border/30">
                        <td className="py-1 font-mono text-muted-foreground whitespace-nowrap">{r.started_at.slice(0, 16).replace('T', ' ')}</td>
                        <td className="py-1 font-mono">{r.client}</td>
                        <td className="py-1 text-muted-foreground">{r.connector_type ?? '—'}</td>
                        <td className="py-1 text-right font-mono">{nf1.format(r.energy_kwh)}</td>
                        <td className="py-1 text-right font-mono text-red-600 dark:text-red-400">{fmtMoney(r.amount)} ₽</td>
                        <td className="py-1 text-muted-foreground">{r.result ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {q.data.corp.length > 0 && (
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                  Ждут счёта (ЮЛ)
                </div>
                <table className="w-full text-[11px]">
                  <tbody>
                    {q.data.corp.map((c) => (
                      <tr key={c.label} className="border-t border-border/30">
                        <td className="py-1 font-medium">{c.label}</td>
                        <td className="py-1 text-right font-mono text-muted-foreground">{nf0.format(c.sessions)} сес.</td>
                        <td className="py-1 text-right font-mono text-muted-foreground">{nf0.format(c.kwh)} кВтч</td>
                        <td className="py-1 text-right font-mono">{fmtMoney(c.amount)} ₽</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {q.data.retail.length === 0 && q.data.corp.length === 0 && (
              <div className="text-[11px] text-muted-foreground">
                На станции только пробы без отпуска энергии ({nf0.format(q.data.probes)}) — платить не за что.
              </div>
            )}
          </div>
        )}
      </td>
    </tr>
  )
}

function UnpaidAnalysis({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const n = useNarrow()
  const [openStation, setOpenStation] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['charge-unpaid', companyId, dateFrom, dateTo, n.key],
    queryFn: () => getChargeUnpaid({ companyId, dateFrom, dateTo, stations: n.stations, regions: n.regions, top: 15 }),
  })
  if (q.isLoading) return <Loading />
  if (!q.data) return <Empty text="Нет данных за период" />
  const { totals: t, stations, clients, trend, cases, accounts } = q.data
  const nothing = t.debt.sessions === 0 && t.postpaid.sessions === 0
  if (nothing) return <Empty text="За период весь отпуск энергии оплачен" />
  const maxTrend = Math.max(...trend.map((r) => r.corp_kwh), 1)
  // Повторяющиеся аккаунты отделяют сбой оплаты от поведения клиента.
  const repeaters = accounts.filter((a) => a.cases > 1).length

  return (
    <div className="p-4 space-y-4">
      <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
        Сессия без отметки оплаты — <span className="font-semibold text-foreground">не одно и то же</span> в
        рознице и у корпоратива. У ЮЛ <span className="font-mono">paid_at</span> пуст штатно: они платят
        по счёту за период. Поэтому суммы ниже разведены и не складываются.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Card className="border-red-400/40">
          <CardContent className="pt-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Долг розницы</div>
            <div className="mt-1 text-2xl font-semibold text-red-600 dark:text-red-400">{fmtMoney(t.debt.amount)} ₽</div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {nf0.format(t.debt.sessions)} сессий · {nf1.format(t.debt.kwh)} кВтч отпущено
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">Энергия ушла, оплаты нет и не будет — это потеря.</div>
          </CardContent>
        </Card>
        <Card className="border-amber-400/40">
          <CardContent className="pt-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Постоплата ЮЛ</div>
            <div className="mt-1 text-2xl font-semibold text-amber-600 dark:text-amber-400">{fmtMoney(t.postpaid.amount)} ₽</div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {nf0.format(t.postpaid.sessions)} сессий · {nf1.format(t.postpaid.kwh)} кВтч отпущено
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              Дебиторка: должно превратиться в счёт.{t.postpaid.estimated ? ' Сумма оценена по прайсу — тарифная модель не отработала.' : ''}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Пробы без энергии</div>
            <div className="mt-1 text-2xl font-semibold text-muted-foreground">{nf0.format(t.probes.sessions)}</div>
            <div className="mt-1 text-[11px] text-muted-foreground">сессий без оплаты и без отпуска</div>
            <div className="mt-2 text-[11px] text-muted-foreground">В деньгах ноль — платить не за что. Разбор в «Повторных попытках».</div>
          </CardContent>
        </Card>
      </div>

      {cases.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Розничный долг поимённо — энергия отпущена, оплата не прошла
            </div>
            <table className="w-full text-xs" {...exportRows('Розничный долг', ['ID сессии', 'Дата', 'Станция', 'Регион', 'Коннектор', 'Клиент', 'кВтч', 'Тариф', 'Сумма, ₽', 'Результат'],
              cases.map((r) => [r.session_ext_id, r.started_at.slice(0, 16).replace('T', ' '),
                r.station_name, r.region, r.connector_type, r.client, r.energy_kwh, r.tariff, r.amount, r.result]))}>
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Дата</th>
                  <th className="text-left p-2 font-medium">Станция</th>
                  <th className="text-left p-2 font-medium">Клиент</th>
                  <th className="text-right p-2 font-medium">кВтч</th>
                  <th className="text-right p-2 font-medium">Сумма</th>
                  <th className="text-left p-2 font-medium">Исход</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((r) => (
                  <tr key={r.session_ext_id} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-mono text-muted-foreground whitespace-nowrap">{r.started_at.slice(0, 16).replace('T', ' ')}</td>
                    <td className="p-2 font-medium truncate max-w-[200px]" title={`${r.station_name ?? ''} · ${r.region ?? ''}`}>
                      {r.station_name ?? r.station_code}
                    </td>
                    <td className="p-2 font-mono text-muted-foreground whitespace-nowrap">{r.client}</td>
                    <td className="p-2 text-right font-mono">{nf1.format(r.energy_kwh)}</td>
                    <td className="p-2 text-right font-mono text-red-600 dark:text-red-400">{fmtMoney(r.amount)} ₽</td>
                    <td className="p-2 text-muted-foreground">{r.result ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {accounts.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40 flex items-baseline justify-between gap-2">
              <span>Аккаунты, заряжающиеся без оплаты</span>
              <span className="text-[10px] font-normal normal-case">
                {repeaters > 0
                  ? `${repeaters} с повторными случаями — это уже не сбой оплаты`
                  : 'все случаи разовые — похоже на сбой оплаты, а не на клиентов'}
              </span>
            </div>
            <table className="w-full text-xs" {...exportRows('Аккаунты без оплаты', ['Аккаунт', 'Случаев', 'кВтч', 'Сумма, ₽', 'Станций', 'Первый', 'Последний'],
              accounts.map((r) => [r.account, r.cases, r.kwh, r.amount, r.stations,
                r.first_at.slice(0, 10), r.last_at.slice(0, 10)]))}>
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Аккаунт</th>
                  <th className="text-right p-2 font-medium" title="Сколько раз уехал без оплаты">Случаев</th>
                  <th className="text-right p-2 font-medium">кВтч</th>
                  <th className="text-right p-2 font-medium">Сумма</th>
                  <th className="text-right p-2 font-medium" title="На скольких разных станциях">Станций</th>
                  <th className="text-left p-2 font-medium">Последний раз</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((r) => (
                  <tr key={r.account} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-mono font-medium whitespace-nowrap">{r.account}</td>
                    {/* Повтор — другой разговор: разовый случай списывают на сбой,
                        системный требует решения по клиенту. */}
                    <td className={`p-2 text-right font-mono ${r.cases > 1 ? 'text-red-600 dark:text-red-400 font-semibold' : 'text-muted-foreground'}`}>
                      {r.cases}
                    </td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.kwh)}</td>
                    <td className="p-2 text-right font-mono">{fmtMoney(r.amount)} ₽</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{r.stations}</td>
                    <td className="p-2 font-mono text-muted-foreground whitespace-nowrap">{r.last_at.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Корпоративная дебиторка по клиентам
            </div>
            {clients.length === 0
              ? <div className="p-3 text-xs text-muted-foreground">Нет корпоративного отпуска без оплаты</div>
              : (
                <table className="w-full text-xs" {...exportRows('Дебиторка ЮЛ', ['Клиент', 'Сессий', 'кВтч', 'К выставлению, ₽'],
                  clients.map((r) => [r.label, r.sessions, r.kwh, r.amount]))}>
                  <thead>
                    <tr className="border-b bg-muted/20 text-muted-foreground">
                      <th className="text-left p-2 font-medium">Клиент</th>
                      <th className="text-right p-2 font-medium">Сессий</th>
                      <th className="text-right p-2 font-medium">кВтч</th>
                      <th className="text-right p-2 font-medium">К выставлению</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clients.map((r) => (
                      <tr key={r.label} className="border-b border-border/30 hover:bg-muted/30">
                        <td className="p-2 font-medium truncate max-w-[200px]" title={r.label}>{r.label}</td>
                        <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.sessions)}</td>
                        <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.kwh)}</td>
                        <td className="p-2 text-right font-mono">{fmtMoney(r.amount)} ₽</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Станции — где отпускают без оплаты
            </div>
            <table className="w-full text-xs" {...exportRows('Станции без оплаты', ['Станция', 'Долг розницы, сессий', 'Долг, ₽', 'Корп. сессий', 'Корп. кВтч', 'Проб'],
              stations.map((r) => [r.label, r.debt_sessions, r.debt_amount, r.corp_sessions, r.corp_kwh, r.probe_sessions]))}>
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Станция</th>
                  <th className="text-right p-2 font-medium">Долг</th>
                  <th className="text-right p-2 font-medium">Корп. кВтч</th>
                </tr>
              </thead>
              <tbody>
                {stations.map((r) => {
                  const open = openStation === r.station_code
                  return (
                    <Fragment key={r.station_code}>
                      <tr className="border-b border-border/30 hover:bg-muted/30 cursor-pointer"
                        onClick={() => setOpenStation(open ? null : r.station_code)}
                        title="Показать, кто заряжался без оплаты на этой станции">
                        <td className="p-2 font-medium truncate max-w-[200px]">
                          <span className="mr-1 inline-block w-3 text-muted-foreground">{open ? '▾' : '▸'}</span>
                          {r.label}
                        </td>
                        <td className={`p-2 text-right font-mono ${r.debt_amount > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                          {r.debt_amount > 0 ? `${fmtMoney(r.debt_amount)} ₽` : '—'}
                        </td>
                        <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.corp_kwh)}</td>
                      </tr>
                      {open && (
                        <UnpaidStationDetailRow companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
                          code={r.station_code} colSpan={3} />
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
            Динамика по месяцам — разовый сбой или постоянная протечка
          </div>
          <table className="w-full text-xs" {...exportRows('Динамика без оплаты', ['Месяц', 'Долг розницы, сессий', 'Долг, ₽', 'Корп. сессий', 'Корп. кВтч'],
            trend.map((r) => [r.month, r.debt_sessions, r.debt_amount, r.corp_sessions, r.corp_kwh]))}>
            <thead>
              <tr className="border-b bg-muted/20 text-muted-foreground">
                <th className="text-left p-2 font-medium">Месяц</th>
                <th className="text-right p-2 font-medium">Долг розницы</th>
                <th className="text-right p-2 font-medium">Постоплата ЮЛ, кВтч</th>
              </tr>
            </thead>
            <tbody>
              {trend.map((r) => (
                <tr key={r.month} className="border-b border-border/30">
                  <td className="p-2 font-medium">{r.month}</td>
                  <td className={`p-2 text-right font-mono ${r.debt_amount > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                    {r.debt_sessions > 0 ? `${nf0.format(r.debt_sessions)} сес · ${fmtMoney(r.debt_amount)} ₽` : '—'}
                  </td>
                  <td className="p-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="h-1.5 rounded-full bg-amber-400/60" style={{ width: `${Math.max(2, r.corp_kwh / maxTrend * 80)}px` }} />
                      <span className="font-mono text-muted-foreground w-16 text-right">{nf0.format(r.corp_kwh)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

/** Использование портов: занятость ≠ работа.
 *
 * «Загрузка» отвечает, сколько времени порт был занят, и не отличает работу от
 * простоя. Отраслевые дашборды CPO считают это отдельно (idle time share): порт,
 * занятый три часа под 2 кВт, — это не медленная зарядка, а недоступный порт.
 * Метрика применяется только к быстрым (DC) портам: на Schuko и Type 1 три
 * киловатта — паспортная скорость, и общий порог показал бы им «простой 97%». */
function PortEfficiency({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const n = useNarrow()
  const q = useQuery({
    queryKey: ['port-efficiency', companyId, dateFrom, dateTo, n.key],
    queryFn: () => getPortEfficiency({ companyId, dateFrom, dateTo, stations: n.stations, regions: n.regions }),
  })
  if (q.isLoading) return <Loading />
  if (!q.data || !q.data.totals.sessions) return <Empty text="Нет сессий с отпуском энергии за период" />
  const { totals: t, connectors, stations, bands, thresholds } = q.data
  const maxBand = Math.max(...bands.map((b) => b.port_hours), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
        <span className="font-semibold text-foreground">Простой</span> — порт занят, но не заряжает:
        сессия дольше <span className="font-mono">{thresholds.idle_min}</span> мин при мощности ниже{' '}
        <span className="font-mono">{thresholds.idle_kw}</span> кВт. Считается только для быстрых портов
        ({thresholds.dc_connectors.join(', ')}): на медленных AC такая мощность — паспортная норма.
        Мощность — по медиане: короткая сессия даёт арифметический выброс в сотни кВт.
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Порт-часов" value={nf0.format(t.port_hours)} hint={`из них DC — ${nf0.format(t.dc_port_hours)}`} />
        <KpiCard label="Простой DC" value={t.idle_time_pct.toFixed(1) + '%'}
          accent={t.idle_time_pct >= 15 ? 'danger' : t.idle_time_pct >= 8 ? 'warning' : 'success'}
          hint={`${nf0.format(t.idle_hours)} ч занято без зарядки`} info={HINTS.idleDc} />
        <KpiCard label="Сессий простоя" value={nf0.format(t.idle_sessions)} hint="долго стоят, мало берут" />
        <KpiCard label="Медиана сессии" value={nf1.format(t.median_min) + ' мин'} hint="dwell time" />
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Коннекторы: фактическая мощность и простой
            </div>
            <table className="w-full text-xs" {...exportRows('Мощность коннекторов', ['Коннектор', 'Тип', 'Сессий', 'Медиана, кВт', 'p90, кВт', 'Dwell, мин', 'Простой, %'],
              connectors.map((r) => [r.label, r.is_dc ? 'DC' : 'AC', r.sessions,
                r.median_kw ?? 0, r.p90_kw ?? 0, r.median_min, r.idle_time_pct ?? '']))}>
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground">
                  <th className="text-left p-2 font-medium">Коннектор</th>
                  <th className="text-right p-2 font-medium" title="Медианная фактическая мощность">кВт</th>
                  <th className="text-right p-2 font-medium" title="Медианная длительность сессии">Dwell</th>
                  <th className="text-right p-2 font-medium">Простой</th>
                </tr>
              </thead>
              <tbody>
                {connectors.map((r) => (
                  <tr key={r.label} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-medium">
                      {r.label}
                      <span className="ml-1.5 text-[10px] text-muted-foreground">{r.is_dc ? 'DC' : 'AC'}</span>
                    </td>
                    <td className="p-2 text-right font-mono">
                      {nf1.format(r.median_kw ?? 0)}
                      <span className="ml-1 text-[10px] text-muted-foreground">p90 {nf0.format(r.p90_kw ?? 0)}</span>
                    </td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.median_min)} м</td>
                    {/* null ≠ 0: для AC простой не измеряется, а не «отсутствует». */}
                    <td className={`p-2 text-right font-mono ${r.idle_time_pct == null ? 'text-muted-foreground/50'
                      : r.idle_time_pct >= 15 ? 'text-red-600 dark:text-red-400'
                      : r.idle_time_pct >= 8 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                      {r.idle_time_pct == null ? '—' : `${r.idle_time_pct}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
              Распределение по фактической мощности
            </div>
            <table className="w-full text-xs" {...exportRows('Мощность сессий', ['Диапазон', 'Сессий', 'Порт-часов', 'кВтч'],
              bands.map((b) => [b.label, b.sessions, b.port_hours, b.kwh]))}>
              <tbody>
                {bands.map((b) => (
                  <tr key={b.band} className="border-b border-border/30">
                    <td className="p-2 font-medium">{b.label}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(b.sessions)} сес.</td>
                    <td className="p-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className={`h-1.5 rounded-full ${b.band <= 2 ? 'bg-amber-400/70' : 'bg-primary/60'}`}
                          style={{ width: `${Math.max(2, b.port_hours / maxBand * 80)}px` }} />
                        <span className="w-14 text-right font-mono text-muted-foreground">{nf0.format(b.port_hours)} ч</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40 flex items-baseline justify-between gap-2">
            <span>Станции, где быстрые порты простаивают занятыми</span>
            <span className="text-[10px] font-normal normal-case">кандидаты на разметку, тариф за простой или информирование</span>
          </div>
          {stations.length === 0
            ? <div className="p-3 text-xs text-muted-foreground">Простоя быстрых портов за период не зафиксировано</div>
            : (
              <table className="w-full text-xs" {...exportRows('Простой портов по станциям', ['Станция', 'Сессий простоя', 'Часов простоя', 'DC порт-часов', 'Доля, %', 'Медиана, кВт'],
                stations.map((r) => [r.label, r.idle_sessions, r.idle_hours, r.dc_port_hours, r.idle_time_pct, r.median_kw ?? 0]))}>
                <thead>
                  <tr className="border-b bg-muted/20 text-muted-foreground">
                    <th className="text-left p-2 font-medium">Станция</th>
                    <th className="text-right p-2 font-medium">Часов впустую</th>
                    <th className="text-right p-2 font-medium">Доля времени DC</th>
                    <th className="text-right p-2 font-medium">Медиана</th>
                  </tr>
                </thead>
                <tbody>
                  {stations.map((r) => (
                    <tr key={r.station_code} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-medium truncate max-w-[240px]" title={r.label}>{r.label}</td>
                      <td className="p-2 text-right font-mono text-red-600 dark:text-red-400">{nf0.format(r.idle_hours)} ч</td>
                      <td className={`p-2 text-right font-mono ${r.idle_time_pct >= 30 ? 'text-red-600 dark:text-red-400' : r.idle_time_pct >= 15 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                        {r.idle_time_pct}%
                      </td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.median_kw ?? 0)} кВт</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </CardContent>
      </Card>
    </div>
  )
}

/** Надёжность: успех сессий, исходы, худшие станции (кандидаты на ТО), тренд. */
function Reliability({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const outcomes = useCS(companyId, period.from, period.to, 'result')
  const byConn = useCS(companyId, period.from, period.to, 'connector')
  const byStation = useCS(companyId, period.from, period.to, 'station')
  const n = useNarrow()
  const recon = useQuery<ReconByRow[]>({
    queryKey: ['reliability-recon', companyId, period.from, period.to],
    queryFn: () => getReconciliationBy({ companyId, dateFrom: period.from, dateTo: period.to, by: 'station', limit: 200 }),
    enabled: !!companyId,
  })
  const trend = useQuery({
    queryKey: ['charge-timeseries', companyId, period.from, period.to, 'month', 'success_pct', '__net__', n.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom: period.from, dateTo: period.to, bucket: 'month', metric: 'success_pct', stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
  })
  // Успех берём из визитов — из ТОГО ЖЕ источника, что вкладка «Повторные попытки».
  // Раньше он приходил из разреза по result, где визит с ошибкой и повтором попадает
  // в обе строки: на «Обзоре» выходило 95.6 %, на соседней вкладке 94.9 % — при одном
  // и том же смысле («клиент уехал заряженным»). Замечание Л. Чурилова 10.08.2026.
  const visits = useQuery({
    queryKey: ['charge-visits-kpi', companyId, period.from, period.to, n.key],
    queryFn: () => getChargeVisits({
      companyId, dateFrom: period.from, dateTo: period.to,
      stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal, top: 1,
    }),
  })
  if (outcomes.isLoading) return <Loading />
  if (!outcomes.data || outcomes.data.lines.length === 0) return <Empty />
  const t = outcomes.data.totals
  const vt = visits.data?.totals
  const complete = outcomes.data.lines.find((l) => l.label === 'Complete')?.sessions ?? 0
  const errors = t.sessions - complete
  const stations = byStation.data?.lines ?? []
  const risk = stations.filter((l) => l.sessions >= 30 && l.success_pct < 70)
  // Вторая причина вызывать сервис — не «люди уезжают незаряженными», а «счётчик
  // врёт»: станция может показывать отличный успех и при этом писать 10 000 кВт·ч
  // за 11 секунд. Оба признака должны стоять в одном списке кандидатов на ТО.
  const byCode = new Map(
    (recon.data ?? []).filter((r) => r.code).map((r) => [String(r.code), r]))
  const codeOf = (label: string) => label.match(/\(([^)]+)\)\s*$/)?.[1] ?? ''
  const dataIssue = (l: { label: string }): ReconByRow | undefined => byCode.get(codeOf(l.label))
  const worstBase = [...stations].filter((l) => l.sessions >= 30)
    .sort((a, b) => a.success_pct - b.success_pct).slice(0, 15)
  // Хронику по данным добавляем, даже если по успеху станция не худшая.
  const chronicExtra = stations.filter((l) => {
    const d = dataIssue(l)
    return d?.chronic && !worstBase.some((w) => w.label === l.label)
  }).slice(0, 5)
  const worst = [...worstBase, ...chronicExtra]
  // Ряд для плитки берём из того же запроса, что кормит график ниже: динамика под
  // цифрой не стоит экрану ни одного лишнего обращения.
  const netSpark = trend.data?.data.map((d) => {
    const v = d[trend.data!.series[0]]
    return typeof v === 'number' ? v : null
  })

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Значение и подпись — из одного знаменателя. Раньше стояло «95.6 %» от
            визитов с подписью «694 из 1 027» (это Complete-сессии, то есть 67.6 %):
            цифра и её же расшифровка говорили разное. */}
        <KpiCard label="Клиенты зарядились" value={vt ? vt.success_pct.toFixed(1) + '%' : '—'}
          accent={succAccent(vt?.success_pct ?? 0)}
          hint={vt ? `${nf0.format(vt.charged)} из ${nf0.format(vt.visits)} визитов` : 'считаем визиты'}
          info={HINTS.visitSuccess} spark={netSpark} sparkLabel="Успешность по месяцам" />
        <KpiCard label="Сессий с ошибкой" value={nf0.format(errors)} accent="danger"
          hint={`${(errors / t.sessions * 100).toFixed(1)}% из ${nf0.format(t.sessions)} сессий`} />
        <KpiCard label="Станций риска" value={nf0.format(risk.length)} accent={risk.length ? 'warning' : 'success'} hint="success < 70% (≥30 сессий)" />
        <KpiCard label="Без оплаты" value={t.unpaid_pct.toFixed(1) + '%'} accent={t.unpaid_pct >= 10 ? 'danger' : t.unpaid_pct >= 3 ? 'warning' : 'success'} hint="сессий без отметки оплаты" />
      </div>

      {stations.filter((l) => l.sessions >= 30).length >= 3 && (
        <div className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Распределение успеха по станциям (≥30 сессий)</div>
          <DistributionKpis lines={stations.filter((l) => l.sessions >= 30)} metric="success_pct" dimGen="станцию"
            topLabel="Лучшая станция" bottomLabel="Худшая станция" />
        </div>
      )}

      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Успешность по месяцам</div>
          {trend.data && trend.data.data.length > 0
            ? <ChargeTrendChart data={trend.data.data} series={trend.data.series} metric="success_pct" />
            : <Loading />}
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Исходы сессий</div>
            {/* Доля — от СЕССИЙ: колонка стоит рядом со счётчиком сессий, а показывала
                долю денег (у станции 353: 92.1 % денег против 67.6 % сессий) — читалось
                как доля сессий. Деньги остались отдельной колонкой, со своей долей. */}
            <table className="w-full text-xs" {...exportRows('Исходы', ['Исход', 'Сессий', 'Доля сессий, %', 'Выручка, ₽', 'Доля выручки, %'],
              outcomes.data.lines.map((l) => [l.label, l.sessions,
                +(l.sessions / t.sessions * 100).toFixed(1), l.amount, l.share_pct]))}>
              <thead>
                <tr className="border-b border-border/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="p-2 text-left font-medium">Исход</th>
                  <th className="p-2 text-right font-medium">Сессий</th>
                  <th className="p-2 text-right font-medium">Доля сессий</th>
                  <th className="p-2 text-right font-medium">Выручка</th>
                  <th className="p-2 text-right font-medium">Доля ₽</th>
                </tr>
              </thead>
              <tbody>
                {outcomes.data.lines.map((l) => (
                  <tr key={l.label} className="border-b border-border/30">
                    <td className="p-2 font-medium">{l.label}</td>
                    <td className="p-2 text-right font-mono">{nf0.format(l.sessions)}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">
                      {(l.sessions / t.sessions * 100).toFixed(1)}%
                    </td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{fmtMoney(l.amount)} ₽</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{l.share_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Успех по коннекторам</div>
            <table className="w-full text-xs" {...exportRows('Успех коннекторов', ['Коннектор', 'Сессий', 'Успех, %'],
              [...(byConn.data?.lines ?? [])].sort((a, b) => a.success_pct - b.success_pct).map((l) => [l.label, l.sessions, l.success_pct]))}>
              <tbody>
                {[...(byConn.data?.lines ?? [])].sort((a, b) => a.success_pct - b.success_pct).map((l) => (
                  <tr key={l.label} className="border-b border-border/30">
                    <td className="p-2 font-medium">{l.label}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.sessions)} сес.</td>
                    <td className={`p-2 text-right font-mono ${succTxt(l.success_pct)}`}>{l.success_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">
            Кандидаты на ТО: люди уезжают незаряженными или врут данные счётчика
          </div>
          <table className="w-full text-xs" {...exportRows('Кандидаты на ТО',
            ['Станция', 'Сессий', 'Успех, %', 'Загрузка, %', 'Выручка, ₽', 'Битых сессий', 'Разрыв, ₽', 'Месяцев с расхождением'],
            worst.map((l) => {
              const d = dataIssue(l)
              return [l.label, l.sessions, l.success_pct, l.utilization_pct, l.amount,
                d?.impossible ?? 0, d?.gap ?? 0, d?.badMonths ?? 0]
            }))}>
            <thead>
              <tr className="border-b bg-muted/20 text-muted-foreground">
                <th className="text-left p-2 font-medium">Станция</th>
                <th className="text-right p-2 font-medium">Сессий</th>
                <th className="text-right p-2 font-medium">Успех</th>
                <th className="text-right p-2 font-medium">Загрузка</th>
                <th className="text-right p-2 font-medium">Выручка</th>
                {/* Данные счётчика: сессии, противоречащие физике, и разрыв с
                    эквайрингом. Их источник — сверка «сессия ↔ платёж». */}
                <th className="text-right p-2 font-medium">Битых</th>
                <th className="text-right p-2 font-medium">Разрыв</th>
                <th className="text-left p-2 font-medium">Данные</th>
              </tr>
            </thead>
            <tbody>
              {worst.map((l) => (
                <tr key={l.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium truncate max-w-[240px]">{l.label}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(l.sessions)}</td>
                  <td className={`p-2 text-right font-mono ${succTxt(l.success_pct)}`}>{l.success_pct.toFixed(1)}%</td>
                  <td className={`p-2 text-right font-mono ${utilTxt(l.utilization_pct)}`}>{l.utilization_pct.toFixed(1)}%</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtMoney(l.amount)} ₽</td>
                  {(() => {
                    const d = dataIssue(l)
                    return (
                      <>
                        <td className={`p-2 text-right font-mono ${
                          d?.impossible ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground/60'}`}>
                          {d?.impossible || '—'}
                        </td>
                        <td className={`p-2 text-right font-mono ${
                          Math.abs(d?.gap ?? 0) > 1 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground/60'}`}>
                          {d && Math.abs(d.gap) > 1 ? `${fmtMoney(d.gap)} ₽` : '—'}
                        </td>
                        <td className="p-2 whitespace-nowrap text-muted-foreground">
                          {d?.chronic ? (
                            <span className="text-amber-600 dark:text-amber-400">
                              хроника · {d.badMonths} из {d.months} мес
                            </span>
                          ) : d?.badMonths ? `${d.badMonths} из ${d.months} мес` : '—'}
                        </td>
                      </>
                    )
                  })()}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

// ── Надёжность по производителям (модель визитов) ──
// Успех визита: сеть ~89%, поэтому <80 — красное, 80–90 — внимание, ≥90 — норма.
const visitSuccTxt = (v: number) => (v >= 90 ? 'text-emerald-600 dark:text-emerald-400' : v >= 80 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')
const visitSuccAccent = (v: number): KpiAccent => (v >= 90 ? 'success' : v >= 80 ? 'warning' : 'danger')

type RelSortKey = 'label' | 'brand' | 'visits' | 'visit_success_pct' | 'repeat_sessions' | 'wasted_sessions' | 'avg_attempts' | 'energy_kwh'
const REL_ASC_DEFAULT: RelSortKey[] = ['label', 'brand']
type RelSort = { key: RelSortKey; dir: 'asc' | 'desc' }

/** Универсальный компаратор строк: строки — по алфавиту (ru), числа — по величине. */
function relCmp(av: unknown, bv: unknown, dir: number): number {
  if (typeof av === 'string' || typeof bv === 'string') return dir * String(av ?? '').localeCompare(String(bv ?? ''), 'ru')
  return dir * (((av as number) ?? 0) - ((bv as number) ?? 0))
}
const relPick = (o: object, k: string): unknown => (o as Record<string, unknown>)[k]

/** Итог по бренду: сырые счётчики суммируем, проценты пересчитываем (не усредняем). */
interface BrandAgg {
  brand: string; stations: number; visits: number; visit_success_pct: number
  repeat_sessions: number; wasted_sessions: number; avg_attempts: number
  energy_kwh: number; risk_stations: number; rows: StationReliabilityRow[]
}
function aggregateByBrand(stations: StationReliabilityRow[]): BrandAgg[] {
  const m = new Map<string, StationReliabilityRow[]>()
  for (const s of stations) { const a = m.get(s.brand); if (a) a.push(s); else m.set(s.brand, [s]) }
  const out: BrandAgg[] = []
  for (const [brand, rows] of m) {
    const sum = (f: (r: StationReliabilityRow) => number) => rows.reduce((t, r) => t + f(r), 0)
    const visits = sum((r) => r.visits); const sessions = sum((r) => r.sessions)
    out.push({
      brand, stations: rows.length, visits,
      visit_success_pct: visits ? +(sum((r) => r.charged_visits) / visits * 100).toFixed(1) : 0,
      repeat_sessions: sum((r) => r.repeat_sessions), wasted_sessions: sum((r) => r.wasted_sessions),
      avg_attempts: visits ? +(sessions / visits).toFixed(2) : 0,
      energy_kwh: +sum((r) => r.energy_kwh).toFixed(1), risk_stations: rows.filter((r) => r.risk).length, rows,
    })
  }
  return out
}

/** Сортируемый заголовок столбца: клик — сорт по нему, повторный — смена направления. */
function SortTh({ label, k, sort, onSort, align = 'right', info }: {
  label: ReactNode; k: RelSortKey; sort: RelSort; onSort: (k: RelSortKey) => void
  align?: 'left' | 'right'; info?: string
}) {
  const active = sort.key === k
  return (
    <th className={`p-2 font-medium cursor-pointer select-none whitespace-nowrap ${align === 'left' ? 'text-left' : 'text-right'} ${active ? 'text-foreground' : ''}`}
      onClick={() => onSort(k)} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} title="Сортировать по столбцу">
      <span className={`inline-flex items-center gap-1 ${align === 'right' ? 'flex-row-reverse' : ''}`}>
        <span>{label}</span>
        {info && <MetricHint text={info} />}
        {active ? (sort.dir === 'desc' ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />) : <ChevronsUpDown className="h-3 w-3 opacity-25" />}
      </span>
    </th>
  )
}

/** Числовые ячейки надёжности — общие для строки станции и итога бренда. */
function RelNumCells({ r }: { r: { visits: number; visit_success_pct: number; repeat_sessions: number; wasted_sessions: number; avg_attempts: number; energy_kwh: number } }) {
  return (
    <>
      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.visits)}</td>
      <td className={`p-2 text-right font-mono ${visitSuccTxt(r.visit_success_pct)}`}>{nf1.format(r.visit_success_pct)}%</td>
      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.repeat_sessions)}</td>
      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.wasted_sessions)}</td>
      <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.avg_attempts)}</td>
      <td className="p-2 text-right font-mono text-muted-foreground">{kwh(r.energy_kwh)}</td>
    </>
  )
}

/** Надёжность станций в разрезе производителя оборудования — на модели визитов
 *  (совпадает с «Повторными попытками»). Два разреза (по вендору / по станциям),
 *  поиск, порог визитов, сортировка по любому столбцу, клик по станции → детали. */
function BrandReliability({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const n = useNarrow()
  const q = useQuery({
    queryKey: ['charge-brand-reliability', companyId, dateFrom, dateTo, n.key],
    queryFn: () => getChargeBrandReliability({ companyId, dateFrom, dateTo, stations: n.stations, regions: n.regions, dim: n.dim, dimVal: n.dimVal }),
  })
  // Представление (разрез + порог) персистим по (компания × пункт); поиск,
  // сортировка, раскрытие — навигация, не персистятся (CLAUDE.md, слой 3).
  const [view, setView] = useTabParams('cs_rel_brands', { mode: 'brand' as 'brand' | 'flat', minVisits: 0 })
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<RelSort>({ key: 'visits', dir: 'desc' })
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [detail, setDetail] = useState<StationReliabilityRow | null>(null)
  const onSort = (k: RelSortKey) => setSort((s) => s.key === k
    ? { key: k, dir: s.dir === 'desc' ? 'asc' : 'desc' }
    : { key: k, dir: REL_ASC_DEFAULT.includes(k) ? 'asc' : 'desc' })

  const all = q.data?.stations ?? []
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return all.filter((s) => s.visits >= view.minVisits
      && (!term || s.label.toLowerCase().includes(term) || s.brand.toLowerCase().includes(term) || (s.code ?? '').toLowerCase().includes(term)))
  }, [all, search, view.minVisits])
  const dir = sort.dir === 'asc' ? 1 : -1
  const sortedStations = useMemo(() => [...filtered].sort((a, b) => relCmp(relPick(a, sort.key), relPick(b, sort.key), dir)),
    [filtered, sort, dir])
  const brandAggs = useMemo(() => {
    const bk = sort.key === 'label' ? 'brand' : sort.key   // «имя» в разрезе брендов = имя бренда
    return aggregateByBrand(filtered).sort((a, b) => relCmp(relPick(a, bk), relPick(b, bk), dir))
  }, [filtered, sort, dir])

  if (q.isLoading) return <Loading />
  if (!q.data) return <Empty />
  const { totals: t, risk } = q.data
  const searching = search.trim().length > 0

  const nameHead = view.mode === 'flat'
    ? <SortTh label="Станция" k="label" sort={sort} onSort={onSort} align="left" />
    : <SortTh label="Производитель" k="label" sort={sort} onSort={onSort} align="left" />
  const numHead = (
    <>
      <SortTh label="Визитов" k="visits" sort={sort} onSort={onSort} info={HINTS.visitDef} />
      <SortTh label="Успех визита" k="visit_success_pct" sort={sort} onSort={onSort} info={HINTS.visitSuccess} />
      <SortTh label="Повторных" k="repeat_sessions" sort={sort} onSort={onSort} info={HINTS.repeatSessions} />
      <SortTh label="Неудачных" k="wasted_sessions" sort={sort} onSort={onSort} info={HINTS.failedSessions} />
      <SortTh label="Ср. попыток" k="avg_attempts" sort={sort} onSort={onSort} info={HINTS.avgAttempts} />
      <SortTh label="Энергия" k="energy_kwh" sort={sort} onSort={onSort} />
    </>
  )
  const exportCols = ['Производитель', 'Станция', 'Код', 'Визитов', 'Успех визита, %', 'Повторных сессий', 'Неудачных сессий', 'Ср. попыток', 'Энергия, кВтч', 'Станция риска']
  const exportData = sortedStations.map((s): (string | number | null)[] =>
    [s.brand, s.label, s.code, s.visits, s.visit_success_pct, s.repeat_sessions, s.wasted_sessions, s.avg_attempts, s.energy_kwh, s.risk ? 'риск' : ''])

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label="Визитов" value={nf0.format(t.visits)} hint={`из ${nf0.format(t.sessions)} сессий`} info={HINTS.visitDef} />
        <KpiCard label="Успех визита" value={nf1.format(t.visit_success_pct) + '%'} accent={visitSuccAccent(t.visit_success_pct)}
          hint={`${nf0.format(t.charged_visits)} зарядились`} info={HINTS.visitSuccess} />
        <KpiCard label="Повторных сессий" value={nf0.format(t.repeat_sessions)} accent="warning" hint="переподключения разъёма" info={HINTS.repeatSessions} />
        <KpiCard label="Неудачных сессий" value={nf0.format(t.wasted_sessions)} accent="warning" hint="без отпуска энергии" info={HINTS.failedSessions} />
        <KpiCard label="Станций риска" value={nf0.format(t.risk_stations)} accent={t.risk_stations ? 'danger' : 'success'}
          hint={`≥${risk.min_visits} виз. и успех <${risk.success_pct}%`} info={HINTS.riskStation} />
      </div>

      {/* Глоссарий: чтобы менеджер не гадал, что значит цифра. */}
      <details className="rounded-lg border border-border bg-muted/20 text-[11px] text-muted-foreground">
        <summary className="cursor-pointer px-3 py-2 font-medium text-foreground select-none">Как читать эти цифры</summary>
        <div className="px-3 pb-3 space-y-1 leading-relaxed">
          <p><b className="text-foreground">Визит</b> — попытки одного клиента на станции подряд (разрыв ≤ {q.data.gap_min} мин), склеенные в одно «человек приехал зарядиться». <b className="text-foreground">Сессия</b> — одна строка CPO = одно касание разъёма; в визите их может быть несколько.</p>
          <p><b className="text-foreground">Успех визита %</b> = зарядившиеся визиты ÷ все визиты. «Человек уехал заряженным» (отпущена энергия, а не флаг Complete от CPO).</p>
          <p><b className="text-foreground">Повторных сессий</b> = сессий − визитов (лишние переподключения). <b className="text-foreground">Неудачных сессий</b> = подключения без отпуска энергии (пробы, сорвы).</p>
          <p><b className="text-foreground">Ср. попыток</b> = сессий ÷ визитов (1,0 — всегда с первой). <b className="text-foreground">Станция риска</b> = ≥ {risk.min_visits} визитов за период и успех визита &lt; {risk.success_pct}% — кандидат на ТОиР.</p>
        </div>
      </details>

      {/* Управление: разрез · поиск · порог визитов. */}
      <div className="flex flex-wrap items-center gap-2" data-export-ignore>
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
          {([['brand', 'По производителям'], ['flat', 'По станциям']] as const).map(([m, l]) => (
            <button key={m} type="button" onClick={() => setView({ mode: m })}
              className={`px-2.5 py-1 text-xs rounded-[5px] transition-colors ${view.mode === m ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{l}</button>
          ))}
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Станция или производитель"
            className="h-8 w-[220px] pl-7 pr-7 text-xs" />
          {search && <button type="button" onClick={() => setSearch('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>}
        </div>
        <Select value={String(view.minVisits)} onValueChange={(v) => setView({ minVisits: Number(v) })}>
          <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {[[0, 'Все станции'], [10, '≥ 10 визитов'], [30, '≥ 30 визитов'], [100, '≥ 100 визитов']].map(([v, l]) => (
              <SelectItem key={v} value={String(v)} className="text-xs">{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-[11px] text-muted-foreground">{nf0.format(filtered.length)} из {nf0.format(all.length)} станций</span>
      </div>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Надёжность по производителям', exportCols, exportData)}>
            <thead>
              <tr className="border-b bg-muted/20 text-muted-foreground">
                {nameHead}
                {view.mode === 'flat' && <SortTh label="Производитель" k="brand" sort={sort} onSort={onSort} align="left" />}
                {numHead}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={view.mode === 'flat' ? 8 : 7} className="p-6 text-center text-muted-foreground">Ничего не найдено — смягчите поиск или порог визитов</td></tr>
              )}
              {view.mode === 'flat'
                ? sortedStations.map((s) => (
                  <tr key={s.code ?? s.label} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer" onClick={() => setDetail(s)}>
                    <td className="p-2 font-medium truncate max-w-[240px]" title={s.label}>
                      {s.risk && <AlertTriangle className="inline h-3 w-3 mr-1 text-red-500 align-[-1px]" />}{s.label}
                    </td>
                    <td className="p-2 text-muted-foreground">{s.brand}</td>
                    <RelNumCells r={s} />
                  </tr>
                ))
                : brandAggs.map((b) => {
                  const isOpen = open.has(b.brand) || searching
                  const rows = [...b.rows].sort((x, y) => relCmp(relPick(x, sort.key), relPick(y, sort.key), dir))
                  return (
                    <Fragment key={b.brand}>
                      <tr className="border-b border-border/40 hover:bg-muted/30 cursor-pointer" onClick={() => setOpen((o) => { const x = new Set(o); if (x.has(b.brand)) x.delete(b.brand); else x.add(b.brand); return x })}>
                        <td className="p-2 font-semibold">
                          <span className="inline-flex items-center gap-1">
                            {isOpen ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                            {b.brand}
                            <span className="text-[10px] font-normal text-muted-foreground">· {nf0.format(b.stations)} ст.{b.risk_stations ? <span className="text-red-500"> · {b.risk_stations} риска</span> : null}</span>
                          </span>
                        </td>
                        <RelNumCells r={b} />
                      </tr>
                      {isOpen && rows.map((s) => (
                        <tr key={b.brand + '|' + (s.code ?? s.label)} className="border-b border-border/20 bg-muted/10 hover:bg-muted/30 cursor-pointer" onClick={() => setDetail(s)}>
                          <td className="p-2 pl-7 truncate max-w-[280px]" title={s.label}>
                            {s.risk && <AlertTriangle className="inline h-3 w-3 mr-1 text-red-500 align-[-1px]" />}{s.label}
                          </td>
                          <RelNumCells r={s} />
                        </tr>
                      ))}
                    </Fragment>
                  )
                })}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[11px] text-muted-foreground">Клик по станции — детальный разбор её надёжности (визиты, попытки, коннекторы, тяжёлые случаи).</p>

      {detail && <StationReliabilityModal station={detail} companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} onClose={() => setDetail(null)} />}
    </div>
  )
}

/** Детали надёжности одной станции — раскрытие по клику. Тянет ту же склейку
 *  визитов, что и «Повторные попытки», но сужённую до станции. */
function StationReliabilityModal({ station, companyId, dateFrom, dateTo, onClose }: {
  station: StationReliabilityRow; companyId: string; dateFrom: string; dateTo: string; onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['charge-visits-station', companyId, dateFrom, dateTo, station.code],
    queryFn: () => getChargeVisits({ companyId, dateFrom, dateTo, stations: station.code ? [station.code] : undefined, top: 20 }),
    enabled: !!station.code,
  })
  const d = q.data
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-4xl w-[94vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base pr-6 flex flex-wrap items-center gap-2">
            {station.label}
            <span className="text-[11px] rounded border border-zinc-600 px-1.5 py-0.5 text-zinc-400 font-normal">{station.brand}</span>
            {station.power_kwt != null && (
              <span className="text-[11px] text-muted-foreground font-normal">паспорт {nf0.format(station.power_kwt)} кВт{station.connectors ? ` · ${station.connectors} разъёма` : ''}</span>
            )}
          </DialogTitle>
        </DialogHeader>
        {q.isLoading ? <Loading /> : !d || d.totals.visits === 0 ? <Empty text="Нет визитов за период" /> : (() => {
          const t = d.totals
          const maxDist = Math.max(...d.distribution.map((x) => x.visits), 1)
          return (
            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
                Визит — попытки одного клиента подряд (разрыв ≤ <span className="font-mono">{d.gap_min}</span> мин) склеены. Успех = отпущена энергия. По всем типам клиентов.
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <KpiCard label="Визитов" value={nf0.format(t.visits)} hint={`из ${nf0.format(t.sessions)} сессий`} />
                <KpiCard label="Успех визита" value={t.success_pct.toFixed(1) + '%'} accent={visitSuccAccent(t.success_pct)} hint={`${nf0.format(t.charged)} зарядились`} info={HINTS.visitSuccess} />
                <KpiCard label="С повторами" value={nf0.format(t.retried)} accent={t.retried_pct >= 25 ? 'warning' : 'info'} hint={`${t.retried_pct.toFixed(1)}% успешных — не сразу`} />
                <KpiCard label="Не зарядились" value={nf0.format(t.failed)} accent={t.failed ? 'danger' : 'success'} hint={`${(100 - t.success_pct).toFixed(1)}% визитов`} />
                <KpiCard label="Впустую сессий" value={nf0.format(t.wasted_sessions)} accent="warning" hint="без отпуска энергии" info={HINTS.failedSessions} />
              </div>

              <div className="grid md:grid-cols-2 gap-3">
                <Card>
                  <CardContent className="p-0">
                    <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Сколько попыток потребовалось</div>
                    <table className="w-full text-xs">
                      <thead><tr className="border-b bg-muted/20 text-muted-foreground"><th className="text-left p-2 font-medium">Попыток</th><th className="text-right p-2 font-medium">Визитов</th><th className="text-right p-2 font-medium">Зарядились</th></tr></thead>
                      <tbody>
                        {d.distribution.map((x) => (
                          <tr key={x.attempts} className="border-b border-border/30">
                            <td className="p-2 font-medium">{x.attempts === 1 ? 'с первой' : x.attempts >= 6 ? '6 и более' : `${x.attempts}`}</td>
                            <td className="p-2 text-right">
                              <div className="flex items-center justify-end gap-2">
                                <div className="h-1.5 rounded-full bg-primary/60" style={{ width: `${Math.max(2, x.visits / maxDist * 90)}px` }} />
                                <span className="font-mono text-muted-foreground">{nf0.format(x.visits)}</span>
                              </div>
                            </td>
                            <td className={`p-2 text-right font-mono ${succTxt(x.charged / x.visits * 100)}`}>{(x.charged / x.visits * 100).toFixed(0)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-0">
                    <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Коннекторы станции</div>
                    {d.connectors.length === 0 ? <div className="p-3 text-xs text-muted-foreground">Нет данных</div> : (
                      <table className="w-full text-xs">
                        <thead><tr className="border-b bg-muted/20 text-muted-foreground"><th className="text-left p-2 font-medium">Коннектор</th><th className="text-right p-2 font-medium">Визитов</th><th className="text-right p-2 font-medium" title="Успех визита по коннектору">Успех</th><th className="text-right p-2 font-medium">Ср. попыток</th></tr></thead>
                        <tbody>
                          {d.connectors.map((c) => {
                            const succ = c.visits ? c.charged / c.visits * 100 : 0
                            return (
                              <tr key={c.label} className="border-b border-border/30">
                                <td className="p-2 font-medium">{c.label}</td>
                                <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(c.visits)}</td>
                                <td className={`p-2 text-right font-mono ${visitSuccTxt(succ)}`}>{succ.toFixed(0)}%</td>
                                <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(c.avg_attempts)}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardContent className="p-0">
                  <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Самые тяжёлые визиты — конкретные случаи для разбора</div>
                  {d.worst.length === 0 ? <div className="p-3 text-xs text-muted-foreground">Повторных визитов нет</div> : (
                    <table className="w-full text-xs">
                      <thead><tr className="border-b bg-muted/20 text-muted-foreground"><th className="text-left p-2 font-medium">Дата</th><th className="text-left p-2 font-medium">Коннектор</th><th className="text-left p-2 font-medium">Клиент</th><th className="text-right p-2 font-medium">Попыток</th><th className="text-right p-2 font-medium">кВтч</th><th className="text-left p-2 font-medium">Итог</th></tr></thead>
                      <tbody>
                        {d.worst.map((r) => (
                          <tr key={r.visit_key} className="border-b border-border/30 hover:bg-muted/30">
                            <td className="p-2 font-mono text-muted-foreground whitespace-nowrap">{r.first_at.slice(0, 16).replace('T', ' ')}</td>
                            <td className="p-2 text-muted-foreground">{r.connector_type ?? '—'}</td>
                            <td className="p-2 text-muted-foreground truncate max-w-[160px]" title={r.client ?? ''}>{r.client ?? '—'}</td>
                            <td className="p-2 text-right font-mono text-red-600 dark:text-red-400">{r.attempts}</td>
                            <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.kwh)}</td>
                            <td className="p-2">{r.charged
                              ? <span className="text-[11px] rounded border border-emerald-400/50 px-1.5 py-0.5 text-emerald-600 dark:text-emerald-300/80">зарядился</span>
                              : <span className="text-[11px] rounded border border-red-400/50 px-1.5 py-0.5 text-red-600 dark:text-red-300/80">не зарядился</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </CardContent>
              </Card>
            </div>
          )
        })()}
      </DialogContent>
    </Dialog>
  )
}

// Виды сессий. «Разрезы» — единая таблица с селектором разреза (станция/коннектор/
// регион/тариф/клиент). Каждый вид приходит СВОИМ пунктом раздела «Сессии»
// (28.07.2026): раньше это были табы под одним пунктом «Сессии», и четырёх разных
// вопросов в меню не было видно.
function subView(sub: string, p: { companyId: string; dateFrom: string; dateTo: string }): { title: string; node: ReactNode } {
  const { companyId, dateFrom, dateTo } = p
  switch (sub) {
    case 'breakdown': return { title: 'Разрезы', node: <BreakdownTable companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} groupBy="station" firstCol="Станция" withKpis controls tabKey="cs_breakdown" /> }
    // legacy ?sub=stations|connectors — теперь один таб «Разрезы» с селектором разреза
    case 'stations': return { title: 'По станциям', node: <BreakdownTable companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} groupBy="station" firstCol="Станция" withKpis controls tabKey="cs_breakdown" /> }
    case 'connectors': return { title: 'По коннекторам', node: <BreakdownTable companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} groupBy="connector" firstCol="Коннектор" withKpis controls tabKey="cs_breakdown" /> }
    case 'time': return { title: 'Время и загрузка', node: <TimeLoad companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    case 'reliability': return { title: 'Надёжность', node: <Reliability companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    case 'dynamics': return { title: 'Динамика', node: <Dynamics companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    case 'compare': return { title: 'Сравнение периодов', node: <Compare companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
    default: return { title: 'Обзор', node: <Overview companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} /> }
  }
}

/** Один вид сессий + общий тумблер ФЛ/ЮЛ и экспорт (имя вида — заголовок области). */
function SessionsView({ view, companyId, dateFrom, dateTo, subtitle, clientType, setClientType }: {
  view: string; companyId: string; dateFrom: string; dateTo: string; subtitle?: string
  clientType: ClientType; setClientType: (v: ClientType) => void
}) {
  const v = subView(view, { companyId, dateFrom, dateTo })
  const ref = useRef<HTMLDivElement>(null)
  return (
    <ChargeClientCtx.Provider value={clientType}>
      <div className="flex items-center justify-end gap-2 border-b border-border px-4 py-2">
        <ClientTypeToggle value={clientType} onChange={setClientType} />
        <ExportButton title={`Сессии ЭЗС · ${v.title}`} subtitle={subtitle} getEl={() => ref.current} />
      </div>
      {/* key={view} — ремаунт при смене пункта: локальное состояние вида (напр.
          выбранный разрез) не тянется в следующий. */}
      <div ref={ref} className="pt-3" key={view}>{v.node}</div>
    </ChargeClientCtx.Provider>
  )
}

// Виды пункта «Надёжность». «Обзор» отвечает на вопрос «что со станциями»,
// «Повторные попытки» — «что с клиентским опытом»: одни и те же сессии, но
// разные единицы счёта (сессия против визита), поэтому это разные виды, а не
// один экран с переключателем метрики.
const RELIABILITY_TABS: { k: string; label: string }[] = [
  { k: 'overview', label: 'Обзор' },
  { k: 'retries', label: 'Повторные попытки' },
  { k: 'brands', label: 'По производителям' },
  { k: 'unpaid', label: 'Без оплаты' },
  { k: 'ports', label: 'Использование портов' },
]

function ReliabilitySection({ companyId, dateFrom, dateTo, subtitle, clientType, setClientType }: {
  companyId: string; dateFrom: string; dateTo: string; subtitle?: string
  clientType: ClientType; setClientType: (v: ClientType) => void
}) {
  const [st, patch] = useTabParams('cs_reliability', { sub: 'overview' })
  const title = RELIABILITY_TABS.find((t) => t.k === st.sub)?.label ?? 'Обзор'
  const ref = useRef<HTMLDivElement>(null)
  return (
    <ChargeClientCtx.Provider value={clientType}>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <PanelViewTabs tabs={RELIABILITY_TABS} value={st.sub} onChange={(k) => patch({ sub: k })}
          ariaLabel="Виды пункта «Надёжность»" />
        <div className="flex items-center gap-2 shrink-0">
          <ClientTypeToggle value={clientType} onChange={setClientType} />
          <ExportButton title={`Сессии ЭЗС · Надёжность · ${title}`} subtitle={subtitle} getEl={() => ref.current} />
        </div>
      </div>
      <div ref={ref} className="pt-3" key={st.sub}>
        {st.sub === 'retries' ? <RetryAnalysis companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
          : st.sub === 'brands' ? <BrandReliability companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
          : st.sub === 'unpaid' ? <UnpaidAnalysis companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
          : st.sub === 'ports' ? <PortEfficiency companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
          : <Reliability companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />}
      </div>
    </ChargeClientCtx.Provider>
  )
}

/**
 * Пункты, которым нужен общий стейт типа клиента (ФЛ/ЮЛ): виды сессий и «Надёжность».
 * Остальные пункты раздаёт ChargeSalesRouter.
 *
 * Ключ пункта → вид: «Разрезы»/«Время»/«Тренд»/«Сравнение» — свои пункты раздела
 * «Сессии»; `cs_sessions` — старая ссылка, ведёт на «Разрезы». «Надёжность» осталась
 * одним пунктом с табами: её пять углов — один вопрос о качестве зарядки.
 */
const SESSION_VIEWS: Record<string, string> = {
  cs_breakdown: 'breakdown', cs_time: 'time', cs_dynamics: 'dynamics',
  cs_compare: 'compare', cs_sessions: 'breakdown',
}

export function SessionsPanel({ tab, companyId, dateFrom, dateTo }: {
  tab: string; companyId: string; dateFrom: string; dateTo: string
}) {
  const sub = useScopeSubtitle()
  const [clientType, setClientType] = useState<ClientType>('all')
  // «Надёжность» — отдельный подраздел (ТОиР: приоритет РусГидро), не 3-й уровень.
  if (tab === 'cs_reliability') {
    return <ReliabilitySection companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
      subtitle={sub} clientType={clientType} setClientType={setClientType} />
  }
  return (
    <SessionsView view={SESSION_VIEWS[tab] ?? 'breakdown'}
      companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} subtitle={sub}
      clientType={clientType} setClientType={setClientType} />
  )
}
