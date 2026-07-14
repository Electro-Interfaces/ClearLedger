/**
 * «Тарифы» — ценовая политика сети АЗС (fuel, ГИГ).
 * Табы: Прайс-лист (станция × топливо) · Средние цены · Отклонения цен · Динамика цен.
 * Данные — /api/fuel/tariffs/* (сетка, отклонения, динамика) + /api/fuel/analytics/fills.
 *
 * Семантика: `price` в наливах = номинальная цена стеллы ₽/л; факт-цена =
 * Σвыручка/Σлитры (realized); скидки на грейне налива ≈ 0 — реальные скидки
 * живут в сменных отчётах и приходят готовым блоком discounts_by_channel.
 */

import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Loader2, ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-react'
import { Kpi } from './analytics/Kpi'
import { ExportButton } from './analytics/ExportButton'
import { ChargeChart, ChartControls, useChartView } from './analytics/ChargeChart'
import { PeriodRangePicker } from './analytics/PeriodRangePicker'
import { type Period } from './analytics/periodPresets'
import { useTabParams } from '@/hooks/useTabParams'
import {
  getFuelTariffGrid, getFuelFills, getFuelPriceDeviations, getFuelPriceTimeseries,
  fmtFuelMetricCompact, fuelChartFormat,
  type FuelGroupBy, type FuelTariffCell, type FuelFillsLine, type FuelPriceDeviationLine,
} from '@/services/fuelSalesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет данных за период' }: { text?: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

/** Атрибуты на <table> с сырыми ЧИСЛАМИ для выгрузки в Excel. */
function exportRows(name: string, columns: string[], rows: (string | number | null)[][]) {
  return { 'data-export-name': name, 'data-export-rows': JSON.stringify({ columns, rows }) }
}
function ExportOnlyTable({ name, columns, rows }: { name: string; columns: string[]; rows: (string | number | null)[][] }) {
  return <table hidden aria-hidden {...exportRows(name, columns, rows)} />
}

/** Период пункта: по умолчанию — период раздела; «Свой период» — локальный override. */
function PeriodOverride({ override, sectionFrom, sectionTo, onChange }: {
  override: Period | null
  sectionFrom: string
  sectionTo: string
  onChange: (p: Period | null) => void
}) {
  if (override) {
    return (
      <div className="flex flex-wrap items-center gap-2" data-export-ignore>
        <span className="text-[11px] uppercase tracking-wider text-amber-600/70 dark:text-amber-400/70">Свой период</span>
        <PeriodRangePicker period={override} onChange={(p) => onChange(p)} />
        <Button variant="ghost" size="sm" className="h-7 text-xs px-2" onClick={() => onChange(null)}>← период раздела</Button>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-export-ignore>
      <span className="text-xs text-muted-foreground">Период раздела: <span className="font-mono">{sectionFrom} — {sectionTo}</span></span>
      <Button variant="outline" size="sm" className="h-7 text-xs px-2" onClick={() => onChange({ from: sectionFrom, to: sectionTo })}>Свой период</Button>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

const deltaCls = (v: number) => (v > 0 ? 'text-emerald-600 dark:text-emerald-400' : v < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')

interface TabProps { companyId: string; dateFrom: string; dateTo: string }

// ── Локальная сортируемая таблица (канон TariffsPanel ЭЗС) ──
interface Col<T> { key: string; label: string; left?: boolean; get: (r: T) => number | string; cell: (r: T) => ReactNode }

function SortTable<T>({ rows, cols, initial, rowKey, exp }: {
  rows: T[]; cols: Col<T>[]; initial: string; rowKey: (r: T, i: number) => string
  exp?: { name: string; columns: string[]; rows: (string | number | null)[][] }
}) {
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: initial, dir: 'desc' })
  const col = useMemo(() => cols.find((c) => c.key === sort.key) ?? cols[0], [cols, sort.key])
  const sorted = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = col.get(a), vb = col.get(b)
      if (typeof va === 'string' || typeof vb === 'string') return dir * String(va).localeCompare(String(vb), 'ru')
      return dir * (va - vb)
    })
  }, [rows, col, sort.dir])
  const toggle = (k: string) => setSort((s) => (s.key === k ? { key: k, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: 'desc' }))
  return (
    <Card><CardContent className="p-0 overflow-x-auto">
      <table className="w-full text-xs" {...(exp ? exportRows(exp.name, exp.columns, exp.rows) : {})}>
        <thead><tr className="border-b bg-muted/40 text-muted-foreground">
          {cols.map((c) => {
            const on = sort.key === c.key
            const Ico = on ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
            const ariaSort: 'ascending' | 'descending' | 'none' = on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
            return (
              <th key={c.key} aria-sort={ariaSort} className={`p-2 font-medium ${c.left ? 'text-left' : 'text-right'}`}>
                <button onClick={() => toggle(c.key)} title="Сортировать"
                  className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${c.left ? '' : 'flex-row-reverse'} ${on ? 'text-foreground' : ''}`}>
                  <span className="whitespace-nowrap">{c.label}</span>
                  <Ico className={`h-3 w-3 shrink-0 ${on ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
                </button>
              </th>
            )
          })}
        </tr></thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={rowKey(r, i)} className="border-b border-border/30 hover:bg-muted/30">
              {cols.map((c, j) => (
                <td key={c.key} className={`p-2 ${c.left ? 'text-left font-medium truncate max-w-[260px]' : 'text-right tabular-nums font-mono'} ${j === 0 ? '' : 'text-muted-foreground'}`}>{c.cell(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </CardContent></Card>
  )
}

/* ────────────────────── Таб: Прайс-лист (сетка) ────────────────────── */

function PriceGridTab({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_tariffs/grid', { override: null as Period | null })
  const period = p.override ?? { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-tariff-grid', companyId, period.from, period.to],
    queryFn: () => getFuelTariffGrid({ companyId, dateFrom: period.from, dateTo: period.to }),
  })
  const cellMap = useMemo(() => {
    const m = new Map<string, FuelTariffCell>()
    data?.cells.forEach((c) => m.set(`${c.station_code}|${c.fuel_code}`, c))
    return m
  }, [data])
  /** Средняя цена сети по топливу — средневзвешенно по литрам (номинал стеллы). */
  const netAvg = useMemo(() => (data?.fuels ?? []).map((f) => {
    let liters = 0, sum = 0
    data?.cells.forEach((c) => {
      if (c.fuel_code === f.code && c.price_avg != null && c.liters > 0) { liters += c.liters; sum += c.price_avg * c.liters }
    })
    return { code: f.code, name: f.name, price: liters > 0 ? sum / liters : null }
  }), [data])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3" data-export-ignore>
        <PeriodOverride override={p.override} sectionFrom={dateFrom} sectionTo={dateTo} onChange={(o) => patch({ override: o })} />
      </div>
      <div className="text-xs text-muted-foreground">
        Номинальная цена стеллы ₽/л по наливам за период. «~» — цена в периоде менялась (диапазон и факт-цена — в подсказке ячейки).
      </div>
      {isLoading ? <Loading /> : !data || data.cells.length === 0 ? <Empty text="Нет наливов за период" /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
            {netAvg.map((f) => (
              <Kpi key={f.code} label={f.name} value={f.price != null ? `${nf2.format(f.price)} ₽/л` : '—'} sub="средняя по сети" />
            ))}
          </div>
          <Card><CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium sticky left-0 bg-muted/40">АЗС</th>
                {data.fuels.map((f) => <th key={f.code} className="text-right p-2 font-medium whitespace-nowrap">{f.name}</th>)}
              </tr></thead>
              <tbody>
                {data.stations.map((s) => (
                  <tr key={s.code} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="text-left p-2 sticky left-0 bg-background">
                      <span className="font-medium">{s.name}</span>
                      <span className="ml-1.5 text-[10px] text-muted-foreground font-mono">#{s.code}</span>
                    </td>
                    {data.fuels.map((f) => {
                      const c = cellMap.get(`${s.code}|${f.code}`)
                      if (!c || c.price_avg == null) {
                        return <td key={f.code} className="text-right p-2 tabular-nums"><span className="text-muted-foreground/30">—</span></td>
                      }
                      const title = `${nf0.format(c.fills)} наливов · ${nf0.format(c.liters)} л`
                        + (c.varies ? ` · диапазон ${nf2.format(c.price_min)}–${nf2.format(c.price_max)} ₽/л` : '')
                        + (c.realized != null ? ` · факт ${nf2.format(c.realized)} ₽/л` : '')
                      return (
                        <td key={f.code} className="text-right p-2 tabular-nums" title={title}>
                          <span className={c.varies ? 'text-amber-600/90 dark:text-amber-300/80' : ''}>
                            {c.varies ? '~' : ''}{nf2.format(c.price_avg)}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
          <ExportOnlyTable name="Прайс-лист"
            columns={['Станция', 'Код', ...data.fuels.map((f) => `${f.name}, ₽/л`)]}
            rows={data.stations.map((s) => [
              s.name, s.code,
              ...data.fuels.map((f) => cellMap.get(`${s.code}|${f.code}`)?.price_avg ?? null),
            ])} />
        </>
      )}
    </div>
  )
}

/* ────────────────────── Таб: Средние цены ────────────────────── */

const AVG_CUTS: { v: FuelGroupBy; label: string }[] = [
  { v: 'station', label: 'Станция' },
  { v: 'fuel', label: 'Вид топлива' },
  { v: 'channel', label: 'Канал' },
  { v: 'pay_type', label: 'Вид оплаты' },
]

function AvgPricesTab({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_tariffs/avg', { override: null as Period | null, cut: 'station' as FuelGroupBy })
  const period = p.override ?? { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-tariff-avg', companyId, period.from, period.to, p.cut],
    queryFn: () => getFuelFills({ companyId, dateFrom: period.from, dateTo: period.to, groupBy: p.cut }),
  })
  const cutLabel = AVG_CUTS.find((c) => c.v === p.cut)?.label ?? 'Разрез'
  const priced = useMemo(() => (data?.lines ?? []).filter((l) => l.avg_price > 0), [data])
  const minL = useMemo(() => (priced.length ? priced.reduce((m, l) => (l.avg_price < m.avg_price ? l : m), priced[0]) : null), [priced])
  const maxL = useMemo(() => (priced.length ? priced.reduce((m, l) => (l.avg_price > m.avg_price ? l : m), priced[0]) : null), [priced])

  const cols: Col<FuelFillsLine>[] = [
    { key: 'label', label: cutLabel, left: true, get: (r) => r.label, cell: (r) => r.label },
    { key: 'fills', label: 'Наливов', get: (r) => r.fills, cell: (r) => nf0.format(r.fills) },
    { key: 'liters', label: 'Литры', get: (r) => r.liters, cell: (r) => nf0.format(r.liters) },
    { key: 'amount', label: 'Выручка', get: (r) => r.amount, cell: (r) => fmtFuelMetricCompact('amount', r.amount) },
    { key: 'avg_price', label: 'Ср. цена ₽/л', get: (r) => r.avg_price, cell: (r) => <span className="font-medium text-foreground">{nf2.format(r.avg_price)}</span> },
    { key: 'avg_check', label: 'Ср. чек', get: (r) => r.avg_check, cell: (r) => fmtFuelMetricCompact('avg_check', r.avg_check) },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3" data-export-ignore>
        <PeriodOverride override={p.override} sectionFrom={dateFrom} sectionTo={dateTo} onChange={(o) => patch({ override: o })} />
        <Field label="Разрез">
          <Select value={p.cut} onValueChange={(v) => patch({ cut: v as FuelGroupBy })}>
            <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{AVG_CUTS.map((o) => <SelectItem key={o.v} value={o.v} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </div>
      <div className="text-xs text-muted-foreground">Факт-цена = Σвыручка / Σлитры за период — где дорого/дёшево продаётся литр.</div>
      {isLoading ? <Loading /> : !data || data.lines.length === 0 ? <Empty text="Нет наливов за период" /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            <Kpi label="Ср. цена сети" value={`${nf2.format(data.totals.avg_price)} ₽/л`} sub="средневзвешенно" />
            <Kpi label="Минимум" value={minL ? `${nf2.format(minL.avg_price)} ₽/л` : '—'} sub={minL?.label} />
            <Kpi label="Максимум" value={maxL ? `${nf2.format(maxL.avg_price)} ₽/л` : '—'} sub={maxL?.label} />
          </div>
          <SortTable rows={data.lines} cols={cols} initial="liters" rowKey={(r) => r.key}
            exp={{
              name: 'Средние цены',
              columns: [cutLabel, 'Наливов', 'Литры', 'Выручка, ₽', 'Ср. цена, ₽/л', 'Ср. чек, ₽'],
              rows: [
                ...data.lines.map((l) => [l.label, l.fills, l.liters, l.amount, l.avg_price, l.avg_check] as (string | number | null)[]),
                ['Итого', data.totals.fills, data.totals.liters, data.totals.amount, data.totals.avg_price, data.totals.avg_check],
              ],
            }} />
        </>
      )}
    </div>
  )
}

/* ────────────────────── Таб: Отклонения цен ────────────────────── */

function DeviationsTab({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_tariffs/dev', { override: null as Period | null, fuel: 'all' })
  const period = p.override ?? { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-tariff-dev', companyId, period.from, period.to],
    queryFn: () => getFuelPriceDeviations({ companyId, dateFrom: period.from, dateTo: period.to }),
  })
  const fuels = useMemo(() => Array.from(new Set((data?.lines ?? []).map((l) => l.fuel))), [data])
  const lines = useMemo(
    () => (p.fuel === 'all' ? data?.lines ?? [] : (data?.lines ?? []).filter((l) => l.fuel === p.fuel)),
    [data, p.fuel],
  )
  const discounts = data?.discounts_by_channel ?? []
  const discTotal = discounts.reduce((a, r) => a + Math.abs(r.discount), 0)
  const amountTotal = discounts.reduce((a, r) => a + r.amount, 0)
  const discNegligible = discounts.length === 0 || discTotal < Math.max(1, amountTotal * 0.001)

  const cols: Col<FuelPriceDeviationLine>[] = [
    { key: 'station', label: 'Станция', left: true, get: (r) => r.station, cell: (r) => r.station },
    { key: 'fuel', label: 'Топливо', left: true, get: (r) => r.fuel, cell: (r) => r.fuel },
    { key: 'fills', label: 'Наливов', get: (r) => r.fills, cell: (r) => nf0.format(r.fills) },
    { key: 'liters', label: 'Литры', get: (r) => r.liters, cell: (r) => nf0.format(r.liters) },
    { key: 'price', label: 'Цена станции', get: (r) => r.price, cell: (r) => <span className="font-medium text-foreground">{nf2.format(r.price)}</span> },
    { key: 'net_avg', label: 'Средняя сети', get: (r) => r.net_avg, cell: (r) => nf2.format(r.net_avg) },
    { key: 'delta', label: 'Δ ₽/л', get: (r) => r.delta, cell: (r) => <span className={deltaCls(r.delta)}>{r.delta > 0 ? '+' : ''}{nf2.format(r.delta)}</span> },
    { key: 'delta_pct', label: 'Δ %', get: (r) => r.delta_pct, cell: (r) => <span className={deltaCls(r.delta)}>{r.delta_pct > 0 ? '+' : ''}{nf1.format(r.delta_pct)}%</span> },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3" data-export-ignore>
        <PeriodOverride override={p.override} sectionFrom={dateFrom} sectionTo={dateTo} onChange={(o) => patch({ override: o })} />
        <Field label="Топливо">
          <Select value={p.fuel} onValueChange={(v) => patch({ fuel: v })}>
            <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все топлива</SelectItem>
              {fuels.map((f) => <SelectItem key={f} value={f} className="text-xs">{f}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <div className="text-xs text-muted-foreground">
        Цена станции vs средняя по сети (по тому же топливу): Δ &gt; 0 — станция дороже сети, Δ &lt; 0 — дешевле.
      </div>
      {isLoading ? <Loading /> : !data || data.lines.length === 0 ? <Empty text="Нет наливов за период" /> : (
        <>
          <SortTable rows={lines} cols={cols} initial="delta_pct" rowKey={(r) => `${r.station_code}|${r.fuel_code}`}
            exp={{
              name: 'Отклонения цен',
              columns: ['Станция', 'Топливо', 'Наливов', 'Литры', 'Цена станции, ₽/л', 'Средняя сети, ₽/л', 'Δ, ₽/л', 'Δ, %'],
              rows: lines.map((l) => [l.station, l.fuel, l.fills, l.liters, l.price, l.net_avg, l.delta, l.delta_pct] as (string | number | null)[]),
            }} />
          <Card><CardContent className="p-0">
            <div className="px-3 py-1.5 border-b bg-muted/20 text-[11px] font-medium">Скидки по каналам (из сменных отчётов)</div>
            {discounts.length === 0 ? (
              <div className="px-3 py-2 text-[11px] text-muted-foreground">Нет данных о скидках за период.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs" {...exportRows('Скидки по каналам', ['Канал', 'Выручка, ₽', 'Скидка, ₽'],
                  discounts.map((r) => [r.label, r.amount, r.discount]))}>
                  <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Канал</th>
                    <th className="p-2 text-right font-medium">Выручка</th>
                    <th className="p-2 text-right font-medium">Скидка</th>
                  </tr></thead>
                  <tbody>
                    {discounts.map((r) => (
                      <tr key={r.channel} className="border-b border-border/30 hover:bg-muted/30">
                        <td className="p-2 font-medium">{r.label}</td>
                        <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', r.amount)}</td>
                        <td className={`p-2 text-right font-mono ${r.discount > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                          {fmtFuelMetricCompact('amount', r.discount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {discNegligible && discounts.length > 0 && (
              <div className="px-3 py-2 border-t text-[11px] text-muted-foreground">Скидки по данным сменных отчётов минимальны.</div>
            )}
          </CardContent></Card>
        </>
      )}
    </div>
  )
}

/* ────────────────────── Таб: Динамика цен ────────────────────── */

const DYN_BUCKETS: { v: 'week' | 'month'; label: string }[] = [
  { v: 'week', label: 'Неделя' },
  { v: 'month', label: 'Месяц' },
]

function PriceDynamicsTab({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_tariffs/dyn', { override: null as Period | null, bucket: 'week' as 'week' | 'month' })
  const [view, setView] = useChartView({ type: 'line' })
  const period = p.override ?? { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-tariff-dyn', companyId, period.from, period.to, p.bucket],
    queryFn: () => getFuelPriceTimeseries({ companyId, dateFrom: period.from, dateTo: period.to, bucket: p.bucket }),
  })
  const hasData = !!data && data.data.length > 0 && data.series.length > 0
  const format = fuelChartFormat('avg_price')
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3" data-export-ignore>
        <PeriodOverride override={p.override} sectionFrom={dateFrom} sectionTo={dateTo} onChange={(o) => patch({ override: o })} />
        <Field label="Шаг">
          <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
            {DYN_BUCKETS.map((o) => (
              <button key={o.v} type="button" onClick={() => patch({ bucket: o.v })}
                className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${p.bucket === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                {o.label}
              </button>
            ))}
          </div>
        </Field>
      </div>
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Цена ₽/л по видам топлива</div>
            {hasData && !isLoading && <ChartControls view={view} onChange={setView} single={data!.series.length === 1} ratio={format.ratio} />}
          </div>
          {isLoading ? <Loading /> : !hasData ? <Empty text="Нет данных за период" />
            : <ChargeChart data={data!.data} series={data!.series} view={view} format={format} />}
        </CardContent>
      </Card>
      {hasData && (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Динамика цен',
            ['Период', ...data!.series.map((s) => `${s}, ₽/л`)],
            data!.data.map((row) => [String(row.bucket), ...data!.series.map((s) => (typeof row[s] === 'number' ? (row[s] as number) : null))]))}>
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Период</th>
              {data!.series.map((s) => <th key={s} className="p-2 text-right font-medium whitespace-nowrap">{s}</th>)}
            </tr></thead>
            <tbody>
              {data!.data.map((row) => (
                <tr key={String(row.bucket)} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium whitespace-nowrap">{String(row.bucket)}</td>
                  {data!.series.map((s) => {
                    const v = row[s]
                    return <td key={s} className="p-2 text-right font-mono tabular-nums">{typeof v === 'number' ? v.toFixed(2) : '—'}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}
    </div>
  )
}

/* ─────────────────────── Контейнер табов ────────────────────── */

const FUEL_TARIFF_TABS: { k: string; label: string }[] = [
  { k: 'grid', label: 'Прайс-лист' },
  { k: 'avg', label: 'Средние цены' },
  { k: 'dev', label: 'Отклонения цен' },
  { k: 'dyn', label: 'Динамика цен' },
]

/** Пункт «Тарифы» топливной сети — контейнер с внутренними табами. */
export function FuelTariffsPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [t, patch] = useTabParams('fuel_tariffs', { sub: 'grid' })
  const p: TabProps = { companyId, dateFrom, dateTo }
  const ref = useRef<HTMLDivElement>(null)
  const curLabel = FUEL_TARIFF_TABS.find((x) => x.k === t.sub)?.label ?? 'Тарифы'
  return (
    <div>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <div className="flex items-stretch gap-0.5 overflow-x-auto">
          {FUEL_TARIFF_TABS.map((x) => {
            const on = t.sub === x.k
            return (
              <button key={x.k} type="button" onClick={() => patch({ sub: x.k })}
                className={`whitespace-nowrap border-b-2 -mb-px px-3 py-2.5 text-[13px] transition-colors ${on ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}`}>
                {x.label}
              </button>
            )
          })}
        </div>
        <ExportButton title={`Тарифы АЗС · ${curLabel}`} subtitle={`Период: ${dateFrom} — ${dateTo}`} getEl={() => ref.current} />
      </div>
      {/* key={t.sub} — ремаунт под-вида при смене таба (чистое локальное состояние). */}
      <div ref={ref} className="p-4" key={t.sub}>
        {t.sub === 'grid' && <PriceGridTab {...p} />}
        {t.sub === 'avg' && <AvgPricesTab {...p} />}
        {t.sub === 'dev' && <DeviationsTab {...p} />}
        {t.sub === 'dyn' && <PriceDynamicsTab {...p} />}
      </div>
    </div>
  )
}
