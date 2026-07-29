/**
 * «Корпоратив» — корпоративный сегмент продаж топлива (fuel, ГИГ):
 * каналы «Топливные карты» (cards) + «Ведомости» (ledger), ≈18,5% выручки.
 * Табы: Обзор · Контрагенты · Карты · Динамика.
 * Данные — /api/fuel/corporate/* + /api/fuel/analytics/fills/timeseries (segment=corp).
 *
 * Особенность сегмента: федеральные процессоры топливных карт (БАЛТОП, VIAcard,
 * Инфорком, Газпромнефть, Мосресурс, Монополия) идут БЕЗ номеров карт —
 * контрагент = вид оплаты; номера есть только у локальных карт «КР» (1000xxx).
 * НСИ «карта → организация» пока нет (org: null) — колонка «Организация»
 * выведена как точка расширения.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Loader2, ArrowUp, ArrowDown, ChevronsUpDown, ChevronLeft, ChevronRight, Search, X,
} from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { KpiCard } from './analytics/AnalyticsPeriodPicker'
import { ChargeChart, ChartControls, useChartView } from './analytics/ChargeChart'
import { CHART_SERIES } from './analytics/palette'
import { type Period } from './analytics/periodPresets'
import { useTabParams } from '@/hooks/useTabParams'
import { useResetOnScopeChange, useScopeSubtitle } from '@/hooks/useScopeReset'
import { ExportButton } from './analytics/ExportButton'
import { PanelViewTabs } from './PanelViewTabs'
import { ViewParamsBar } from './ViewParamsBar'
import { HorizonControl } from './HorizonControl'
import {
  getFuelCorporateOverview, getFuelCorporateCounterparties, getFuelCorporateCards, getFuelTimeseries,
  FUEL_METRIC_LABELS, fmtFuelMetricCompact, fmtFuelMetricShort, fuelChartFormat, fmtRub0,
  type FuelMetric, type FuelBucket, type FuelGroupBy, type FuelCardsSort,
  type FuelCounterpartyRow, type FuelTimeseriesResponse,
} from '@/services/fuelSalesService'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface TabProps { companyId: string; dateFrom: string; dateTo: string }

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет корпоративных реализаций за период' }: { text?: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

/** Атрибуты на <table> с сырыми ЧИСЛАМИ для выгрузки в Excel. */
function exportRows(name: string, columns: string[], rows: (string | number | null)[][]) {
  return { 'data-export-name': name, 'data-export-rows': JSON.stringify({ columns, rows }) }
}
function ExportOnlyTable({ name, columns, rows }: { name: string; columns: string[]; rows: (string | number | null)[][] }) {
  return <table hidden aria-hidden {...exportRows(name, columns, rows)} />
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

/** Строка-рейтинг с полосой доли (как ShareCard в ЭЗС-обзоре). */
function BarRow({ label, value, frac, sub }: { label: string; value: string; frac: number; sub?: string }) {
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between gap-2 text-xs">
        <span className="truncate">{label}</span>
        <span className="whitespace-nowrap tabular-nums text-muted-foreground">{value}{sub ? ` · ${sub}` : ''}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(2, Math.min(100, frac * 100))}%` }} /></div>
    </div>
  )
}
function Widget({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{title}</div>
      <Card className="h-full"><CardContent className="space-y-1.5 p-3">{children}</CardContent></Card>
    </div>
  )
}

/** Каналы корп-сегмента: ключ канала → русская подпись. */
const CHANNEL_LABELS: Record<string, string> = { cards: 'Топливные карты', ledger: 'Ведомости' }
const chanLabel = (s: string): string => CHANNEL_LABELS[s] ?? s

const fmtDshort = (s: string | null): string => {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
const fmtMonth = (m: string): string => (m.length >= 7 ? `${m.slice(5, 7)}.${m.slice(2, 4)}` : m)

/* ────────────────────────── Обзор ────────────────────────── */

function CorpOverview({ companyId, dateFrom, dateTo }: TabProps) {
  const fk = useFuelKindFilter()
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-corp-overview', companyId, period.from, period.to, fk.key],
    queryFn: () => getFuelCorporateOverview({ companyId, dateFrom: period.from, dateTo: period.to, fuelCodes: fk.fuelCodes }),
  })
  if (isLoading) return <Loading />
  if (!data || data.kpi.fills === 0) return <Empty />
  const k = data.kpi
  const maxStation = Math.max(1, ...data.by_station.map((s) => s.amount))
  const topStations = data.by_station.slice(0, 8)
  const maxFuelShare = Math.max(0.01, ...data.by_fuel.map((f) => f.share_pct))
  return (
    <div className="p-4 space-y-4">
      {/* KPI-сетка сегмента */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Выручка" value={fmtRub0(k.amount)} accent="success" />
        <KpiCard label="Объём" value={nf0.format(k.liters) + ' л'} accent="info" />
        <KpiCard label="Реализаций" value={nf0.format(k.fills)} />
        <KpiCard label="Доля от всех продаж" value={nf1.format(k.share_of_total_pct) + '%'} hint="выручка сегмента / вся выручка" />
        <KpiCard label="Активных карт" value={nf0.format(k.active_cards)} hint="уникальных за период" />
        <KpiCard label="Ср. реализация" value={nf1.format(k.avg_fill) + ' л'} hint="крупные баки корп-парка" />
        <KpiCard label="Ср. цена" value={nf2.format(k.avg_price) + ' ₽/л'} />
        <KpiCard label="Станций" value={nf0.format(k.stations)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Разбивка cards vs ledger */}
        <Widget title="Каналы сегмента: карты vs ведомости">
          {data.by_channel.map((c) => (
            <BarRow key={c.label} label={chanLabel(c.label)} value={fmtRub0(c.amount)}
              frac={c.share_pct / 100} sub={`${nf1.format(c.share_pct)}% · ${nf0.format(c.fills)} реализаций`} />
          ))}
          <p className="border-t border-border/40 pt-1.5 text-[11px] text-muted-foreground">
            Федеральные процессоры идут без номеров карт — контрагент определяется видом оплаты.
          </p>
          <ExportOnlyTable name="Каналы сегмента" columns={['Канал', 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %']}
            rows={data.by_channel.map((c) => [chanLabel(c.label), c.fills, c.liters, c.amount, c.share_pct])} />
        </Widget>

        {/* Выручка по месяцам */}
        <Widget title="Выручка по месяцам">
          {data.monthly.length === 0 ? <Empty text="Нет данных за период" /> : (
            <div data-chart>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={data.monthly} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                    stroke="hsl(var(--muted-foreground))" tickFormatter={fmtMonth} />
                  <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                    width={52} tickFormatter={(v: number) => fmtFuelMetricShort('amount', v)} />
                  <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} labelFormatter={(m) => String(m)}
                    formatter={(v) => [fmtRub0(Number(v)), 'Выручка']} />
                  <Bar dataKey="amount" fill={CHART_SERIES[0]} fillOpacity={0.75} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <ExportOnlyTable name="Выручка по месяцам" columns={['Месяц', 'Реализаций', 'Литры', 'Выручка, ₽', 'Карт']}
            rows={data.monthly.map((m) => [m.month, m.fills, m.liters, m.amount, m.cards])} />
        </Widget>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Структура по видам топлива */}
        <div className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Структура по видам топлива</div>
          <Card>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-xs" {...exportRows('По видам топлива', ['Топливо', 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %'],
                data.by_fuel.map((f) => [f.label, f.fills, f.liters, f.amount, f.share_pct]))}>
                <thead>
                  <tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Топливо</th>
                    <th className="p-2 text-right font-medium">Реализаций</th>
                    <th className="p-2 text-right font-medium">Литры</th>
                    <th className="p-2 text-right font-medium">Выручка</th>
                    <th className="p-2 text-right font-medium">Доля</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_fuel.map((f) => (
                    <tr key={f.label} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-medium truncate max-w-[160px]">{f.label}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(f.fills)}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(f.liters)}</td>
                      <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', f.amount)}</td>
                      <td className="p-2 text-right font-mono">
                        <div className="relative">
                          <div className="absolute inset-y-0 right-0 bg-primary/15 rounded-sm" style={{ width: `${Math.min(100, f.share_pct / maxFuelShare * 100)}%` }} />
                          <span className="relative">{f.share_pct.toFixed(1)}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>

        {/* Топ станций */}
        <Widget title="Станции сегмента (топ по выручке)">
          {topStations.length === 0 ? <Empty text="Нет данных" />
            : topStations.map((s) => (
              <BarRow key={s.label} label={s.label} value={fmtRub0(s.amount)} frac={s.amount / maxStation}
                sub={`${nf1.format(s.share_pct)}% · ${nf0.format(s.fills)} нал.`} />
            ))}
          <ExportOnlyTable name="По станциям" columns={['Станция', 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %']}
            rows={data.by_station.map((s) => [s.label, s.fills, s.liters, s.amount, s.share_pct])} />
        </Widget>
      </div>
    </div>
  )
}

/* ──────────────────────── Контрагенты ────────────────────── */

/** Сортировка процессоров: числовые поля + строки (имя/канал). */
type CpSortKey = keyof Pick<FuelCounterpartyRow,
  'name' | 'channel' | 'fills' | 'liters' | 'amount' | 'share_pct' | 'avg_fill' | 'avg_price' | 'stations' | 'cards'>

function CorpCounterparties({ companyId, dateFrom, dateTo }: TabProps) {
  const fk = useFuelKindFilter()
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-corp-counterparties', companyId, period.from, period.to, fk.key],
    queryFn: () => getFuelCorporateCounterparties({ companyId, dateFrom: period.from, dateTo: period.to, fuelCodes: fk.fuelCodes }),
  })
  const [sort, setSort] = useState<{ key: CpSortKey; dir: 'asc' | 'desc' }>({ key: 'amount', dir: 'desc' })
  const rows = useMemo(() => {
    const src = data?.rows ?? []
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...src].sort((a, b) => {
      const va = a[sort.key], vb = b[sort.key]
      if (typeof va === 'string' || typeof vb === 'string') return dir * String(va).localeCompare(String(vb), 'ru')
      return dir * ((va as number) - (vb as number))
    })
  }, [data, sort])
  if (isLoading) return <Loading />
  if (!data || data.rows.length === 0) return <Empty />
  const t = data.totals
  const toggle = (key: CpSortKey) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }))
  const H = ({ k, children, left }: { k: CpSortKey; children: ReactNode; left?: boolean }) => {
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
  const maxShare = Math.max(0.01, ...data.rows.map((r) => r.share_pct))
  const exCols = ['Контрагент', 'Канал', 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %', 'Ср. реализация, л', 'Ср. цена, ₽/л', 'Станций', 'Карт']
  const exData: (string | number | null)[][] = [
    ...rows.map((r) => [r.name, chanLabel(r.channel), r.fills, r.liters, r.amount, r.share_pct, r.avg_fill, r.avg_price, r.stations, r.cards]),
    ['Итого', '', t.fills, t.liters, t.amount, 100, null, null, null, null],
  ]
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Контрагентов" value={nf0.format(data.rows.length)} hint="процессоры + ведомости" />
        <KpiCard label="Выручка сегмента" value={fmtRub0(t.amount)} accent="success" />
        <KpiCard label="Объём" value={nf0.format(t.liters) + ' л'} accent="info" />
        <KpiCard label="Реализаций" value={nf0.format(t.fills)} />
      </div>
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Контрагенты', exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <H k="name" left>Контрагент</H>
                <H k="channel" left>Канал</H>
                <H k="fills">Реализаций</H>
                <H k="liters">Литры</H>
                <H k="amount">Выручка</H>
                <H k="share_pct">Доля</H>
                <H k="avg_fill">Ср. реализация</H>
                <H k="avg_price">₽/л</H>
                <H k="stations">Станций</H>
                <H k="cards">Карт</H>
                <th className="p-2 font-medium text-right whitespace-nowrap">Тренд ₽</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium truncate max-w-[220px]">{r.name}</td>
                  <td className="p-2 text-muted-foreground whitespace-nowrap">{chanLabel(r.channel)}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(r.fills)}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(r.liters)}</td>
                  <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', r.amount)}</td>
                  <td className="p-2 text-right font-mono">
                    <div className="relative">
                      <div className="absolute inset-y-0 right-0 bg-primary/15 rounded-sm" style={{ width: `${Math.min(100, r.share_pct / maxShare * 100)}%` }} />
                      <span className="relative">{r.share_pct.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.avg_fill)}</td>
                  <td className="p-2 text-right font-mono">{r.avg_price.toFixed(2)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.stations)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{r.cards ? nf0.format(r.cards) : '—'}</td>
                  <td className="p-2 text-right"><Sparkline values={r.trend} /></td>
                </tr>
              ))}
              <tr className="bg-muted/60 font-medium">
                <td className="p-2">Итого</td>
                <td className="p-2" />
                <td className="p-2 text-right font-mono">{nf0.format(t.fills)}</td>
                <td className="p-2 text-right font-mono">{nf0.format(t.liters)}</td>
                <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', t.amount)}</td>
                <td className="p-2 text-right font-mono">100%</td>
                <td className="p-2" colSpan={5} />
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[11px] text-muted-foreground/70">
        Контрагент = вид оплаты процессора (федеральные топливные карты идут без номеров) либо ведомость.
        Тренд — выручка по месяцам периода. НСИ «карта → организация» появится позже.
      </p>
    </div>
  )
}

/* ─────────────────────────── Карты ───────────────────────── */

const CARDS_PAGE = 50

function CardsSortHead({ label, k, sort, order, onSort }: {
  label: string; k: FuelCardsSort; sort: FuelCardsSort; order: 'asc' | 'desc'; onSort: (k: FuelCardsSort) => void
}) {
  const active = sort === k
  const Ico = active ? (order === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
  return (
    <th aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'} className="p-2 font-medium text-right">
      <button onClick={() => onSort(k)} title="Сортировать по столбцу (на сервере)"
        className={`group inline-flex items-center gap-1 flex-row-reverse cursor-pointer transition-colors hover:text-foreground ${active ? 'text-foreground' : ''}`}>
        <span className="whitespace-nowrap">{label}</span>
        <Ico className={`h-3 w-3 shrink-0 ${active ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
      </button>
    </th>
  )
}

function CorpCards({ companyId, dateFrom, dateTo }: TabProps) {
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const [sort, setSort] = useState<FuelCardsSort>('amount')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  // Смена контура делает поиск и страницу бессмысленными (CLAUDE.md, правило 5).
  useResetOnScopeChange(() => { setSearchInput(''); setSearch(''); setPage(0) })

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['fuel-corp-cards', companyId, period.from, period.to, sort, order, page, search],
    queryFn: () => getFuelCorporateCards({
      companyId, dateFrom: period.from, dateTo: period.to,
      sort, order, limit: CARDS_PAGE, offset: page * CARDS_PAGE,
      search: search || undefined, segment: 'corp',
    }),
    placeholderData: keepPreviousData,
  })

  const onSort = (k: FuelCardsSort) => {
    if (k === sort) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else { setSort(k); setOrder('desc') }
    setPage(0)
  }
  const applySearch = () => { setSearch(searchInput.trim()); setPage(0) }
  const clearSearch = () => { setSearchInput(''); setSearch(''); setPage(0) }

  if (isLoading) return <Loading />
  if (!data) return <Empty />
  const t = data.totals
  const total = data.total
  const pages = Math.max(1, Math.ceil(total / CARDS_PAGE))
  const from = total === 0 ? 0 : page * CARDS_PAGE + 1
  const to = Math.min(total, (page + 1) * CARDS_PAGE)
  const exCols = ['Карта', 'Организация', 'Вид оплаты', 'Реализаций', 'Литры', 'Сумма, ₽', 'Ср. реализация, л', 'Станций', 'Топлив', 'Первая реализация', 'Последняя реализация']
  const exData = data.rows.map((r) => [
    r.card, r.org ?? '—', r.pay_type ?? '—', r.fills, r.liters, r.amount, r.avg_fill, r.stations, r.fuels, r.first_dt, r.last_dt,
  ] as (string | number | null)[])
  const orgTitle = 'НСИ «карта → организация» появится позже'
  return (
    <div className="p-4 space-y-4">
      <ViewParamsBar>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') applySearch() }}
            placeholder="Номер карты" className="h-7 w-[170px] pl-7 text-xs" />
        </div>
        <Button variant="outline" size="sm" className="h-7 text-xs px-2" onClick={applySearch}>Найти</Button>
        {search && (
          <Button variant="ghost" size="sm" className="h-7 text-xs px-2" onClick={clearSearch}>
            <X className="mr-1 h-3.5 w-3.5" />Сбросить поиск
          </Button>
        )}
        {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
      </ViewParamsBar>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Карт всего" value={nf0.format(t.cards)} hint={search ? `по поиску «${search}»` : 'в корп-сегменте за период'} />
        <KpiCard label="Реализаций" value={nf0.format(t.fills)} />
        <KpiCard label="Объём" value={nf0.format(t.liters) + ' л'} accent="info" />
        <KpiCard label="Сумма" value={fmtRub0(t.amount)} accent="success" />
      </div>

      {total === 0 ? <Empty text="Нет карт по текущему отбору" /> : (
        <>
          <Card>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full min-w-[980px] text-xs" {...exportRows('Карты (страница)', exCols, exData)}>
                <thead>
                  <tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Карта</th>
                    <th className="p-2 text-left font-medium" title={orgTitle}>Организация</th>
                    <th className="p-2 text-left font-medium">Вид оплаты</th>
                    <CardsSortHead label="Реализаций" k="fills" sort={sort} order={order} onSort={onSort} />
                    <CardsSortHead label="Литры" k="liters" sort={sort} order={order} onSort={onSort} />
                    <CardsSortHead label="Сумма" k="amount" sort={sort} order={order} onSort={onSort} />
                    <CardsSortHead label="Ср. реализация" k="avg_fill" sort={sort} order={order} onSort={onSort} />
                    <th className="p-2 text-right font-medium">Станций</th>
                    <th className="p-2 text-right font-medium">Топлив</th>
                    <CardsSortHead label="Первый" k="first_dt" sort={sort} order={order} onSort={onSort} />
                    <CardsSortHead label="Последний" k="last_dt" sort={sort} order={order} onSort={onSort} />
                    <th className="p-2 text-right font-medium whitespace-nowrap">Тренд ₽</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.card} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-mono font-medium whitespace-nowrap">{r.card}</td>
                      <td className="p-2 text-muted-foreground/60" title={orgTitle}>{r.org ?? '—'}</td>
                      <td className="p-2 text-muted-foreground truncate max-w-[180px]">{r.pay_type ?? '—'}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(r.fills)}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(r.liters)}</td>
                      <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', r.amount)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{nf1.format(r.avg_fill)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.stations)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.fuels)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground whitespace-nowrap">{fmtDshort(r.first_dt)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground whitespace-nowrap">{fmtDshort(r.last_dt)}</td>
                      <td className="p-2 text-right"><Sparkline values={r.trend} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          {/* серверная пагинация */}
          <div className="flex items-center justify-between text-xs text-muted-foreground" data-export-ignore>
            <span>{nf0.format(from)}–{nf0.format(to)} из {nf0.format(total)} карт</span>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page === 0}
                onClick={() => setPage((x) => Math.max(0, x - 1))}><ChevronLeft className="h-4 w-4" /></Button>
              <span className="px-2 tabular-nums">страница {page + 1} из {nf0.format(pages)}</span>
              <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page + 1 >= pages}
                onClick={() => setPage((x) => x + 1)}><ChevronRight className="h-4 w-4" /></Button>
            </div>
          </div>
        </>
      )}
      <p className="text-[11px] text-muted-foreground/70">
        Номера есть только у локальных карт «КР» (1000xxx); федеральные процессоры представлены агрегатом по виду оплаты.
        Сортировка и поиск выполняются на сервере.
      </p>
    </div>
  )
}

/* ────────────────────────── Динамика ─────────────────────── */

const DYN_METRICS: FuelMetric[] = ['amount', 'liters', 'fills', 'avg_fill']
const DYN_SERIES: { value: string; label: string }[] = [
  { value: '__net__', label: 'Все вместе' },
  { value: 'channel', label: 'По каналам' },
  { value: 'fuel', label: 'По топливу' },
]
const DYN_BUCKETS: { value: FuelBucket; label: string }[] = [
  { value: 'week', label: 'Неделя' }, { value: 'month', label: 'Месяц' },
]
const DYN_DEFAULTS = { metric: 'amount' as FuelMetric, seriesSel: '__net__', bucket: 'week' as FuelBucket }

function DynTrendTable({ data, metric }: { data: FuelTimeseriesResponse; metric: FuelMetric }) {
  const name = (s: string) => (s === 'value' ? FUEL_METRIC_LABELS[metric] : chanLabel(s))
  const exCols = ['Период', ...data.series.map(name)]
  const exData = data.data.map((row) => [String(row.bucket), ...data.series.map((s) => (row[s] ?? null) as string | number | null)])
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs" {...exportRows('Динамика сегмента', exCols, exData)}>
          <thead>
            <tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="text-left p-2 font-medium">Период</th>
              {data.series.map((s) => <th key={s} className="text-right p-2 font-medium">{name(s)}</th>)}
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

function CorpDynamics({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_corp/dynamics', DYN_DEFAULTS)
  const [view, setView] = useChartView({ type: 'line' })
  // Горизонт анализа: не персистится и сбрасывается при смене периода наверху.
  const [horizon, setHorizon] = useState<Period | null>(null)
  useEffect(() => { setHorizon(null) }, [dateFrom, dateTo])
  const period = horizon ?? { from: dateFrom, to: dateTo }
  const seriesBy = p.seriesSel === '__net__' ? undefined : (p.seriesSel as FuelGroupBy)
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-corp-timeseries', companyId, period.from, period.to, p.bucket, p.metric, p.seriesSel],
    queryFn: () => getFuelTimeseries({
      companyId, dateFrom: period.from, dateTo: period.to,
      bucket: p.bucket, metric: p.metric, seriesBy, segment: 'corp',
    }),
  })
  const hasData = !!data && data.data.length > 0
  const format = fuelChartFormat(p.metric)
  return (
    <div className="p-4 space-y-4">
      <ViewParamsBar>
        <HorizonControl horizon={horizon} scopeFrom={dateFrom} scopeTo={dateTo} onChange={setHorizon} />
        <Field label="Метрика">
          <Select value={p.metric} onValueChange={(v) => patch({ metric: v as FuelMetric })}>
            <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{DYN_METRICS.map((m) => <SelectItem key={m} value={m} className="text-xs">{FUEL_METRIC_LABELS[m]}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Разрез">
          <Select value={p.seriesSel} onValueChange={(v) => patch({ seriesSel: v })}>
            <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{DYN_SERIES.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Шаг">
          <Select value={p.bucket} onValueChange={(v) => patch({ bucket: v as FuelBucket })}>
            <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{DYN_BUCKETS.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </ViewParamsBar>
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {FUEL_METRIC_LABELS[p.metric]} · корпоративный сегмент
            </div>
            {hasData && !isLoading && <ChartControls view={view} onChange={setView} single={data!.series.length === 1} ratio={format.ratio} />}
          </div>
          {isLoading ? <Loading /> : !hasData ? <Empty text="Нет данных за период" />
            : <ChargeChart data={data!.data} series={data!.series} view={view} format={format} />}
        </CardContent>
      </Card>
      {hasData && <DynTrendTable data={data!} metric={p.metric} />}
    </div>
  )
}

/* ─────────────────────── Контейнер табов ────────────────────── */

const SUB_TABS: { k: string; label: string }[] = [
  { k: 'overview', label: 'Обзор' },
  { k: 'counterparties', label: 'Контрагенты' },
  { k: 'cards', label: 'Карты' },
  { k: 'dynamics', label: 'Динамика' },
]

function subView(sub: string, p: TabProps): { title: string; node: ReactNode } {
  switch (sub) {
    case 'counterparties': return { title: 'Контрагенты', node: <CorpCounterparties {...p} /> }
    case 'cards': return { title: 'Карты', node: <CorpCards {...p} /> }
    case 'dynamics': return { title: 'Динамика', node: <CorpDynamics {...p} /> }
    default: return { title: 'Обзор', node: <CorpOverview {...p} /> }
  }
}

/** Пункт «Корпоратив» — контейнер с внутренними табами (сегмент cards + ledger). */
export function FuelCorporatePanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [st, patch] = useTabParams('fuel_corp', { sub: 'overview' })
  const v = subView(st.sub, { companyId, dateFrom, dateTo })
  const ref = useRef<HTMLDivElement>(null)
  const scopeSub = useScopeSubtitle({ scopeApplied: false })  // панель не сужает по сети: API не принимает станции
  return (
    <div>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="my-2 shrink-0 rounded-md border border-primary/40 px-2 py-0.5 text-[11px] text-primary/80">Карты + ведомости</span>
          <PanelViewTabs tabs={SUB_TABS} value={st.sub} onChange={(k) => patch({ sub: k })} label={null} ariaLabel="Виды раздела «Корпоратив»" />
        </div>
        <ExportButton title={`Корпоратив · ${v.title}`} subtitle={scopeSub} getEl={() => ref.current} />
      </div>
      {/* key={st.sub} — ремаунт под-вида при смене таба (чистое локальное состояние). */}
      <div ref={ref} key={st.sub}>{v.node}</div>
    </div>
  )
}
