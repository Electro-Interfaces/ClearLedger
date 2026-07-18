/**
 * «Частные лица» — розничный сегмент продаж топлива (fuel, ГИГ).
 * Табы: Обзор · Лояльность · Чеки · Время · Динамика.
 * Данные — /api/fuel/retail/* + /api/fuel/analytics/fills* (segment=retail).
 *
 * Розница = наличные + банковские карты. Банковская карта несёт ТОКЕН из STS —
 * отсюда полноценная аналитика лояльности (повторные визиты, частота, топ карт);
 * наличные анонимны и в лояльности не участвуют.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2 } from 'lucide-react'
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip as RTooltip,
  BarChart, Bar, ComposedChart, Line, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts'
import { KpiCard } from './analytics/AnalyticsPeriodPicker'
import { ChargeChart, ChartControls, useChartView } from './analytics/ChargeChart'
import { type Period } from './analytics/periodPresets'
import { seriesColor, CHART_SERIES } from './analytics/palette'
import { useTabParams } from '@/hooks/useTabParams'
import { ExportButton } from './analytics/ExportButton'
import { useScopeSubtitle } from '@/hooks/useScopeReset'
import { PanelViewTabs } from './PanelViewTabs'
import { ViewParamsBar } from './ViewParamsBar'
import { HorizonControl } from './HorizonControl'
import {
  getFuelRetailOverview, getFuelRetailLoyalty, getFuelHeatmap, getFuelTimeseries,
  FUEL_METRIC_LABELS, fmtFuelMetric, fmtFuelMetricCompact, fmtFuelMetricShort, fuelChartFormat, fmtRub0,
  type FuelMetric, type FuelBucket, type FuelBreakdownRow, type FuelTimeseriesResponse,
} from '@/services/fuelSalesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const pct1 = (v: number) => nf1.format(v) + '%'

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет розничных продаж за период' }: { text?: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

/** Атрибуты на <table> с сырыми ЧИСЛАМИ для выгрузки в Excel. */
function exportRows(name: string, columns: string[], rows: (string | number | null)[][]) {
  return { 'data-export-name': name, 'data-export-rows': JSON.stringify({ columns, rows }) }
}
function ExportOnlyTable({ name, columns, rows }: { name: string; columns: string[]; rows: (string | number | null)[][] }) {
  return <table hidden aria-hidden {...exportRows(name, columns, rows)} />
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

interface TabProps { companyId: string; dateFrom: string; dateTo: string }

function useRetailOverview(companyId: string, dateFrom: string, dateTo: string) {
  return useQuery({
    queryKey: ['fuel-retail-overview', companyId, dateFrom, dateTo],
    queryFn: () => getFuelRetailOverview({ companyId, dateFrom, dateTo }),
  })
}

/* ─────────────────────────── Обзор ─────────────────────────── */

/** Донат «Наличные vs Банковские карты»: компактный, легенда + сумма в центре. */
function PayDonut({ rows }: { rows: (FuelBreakdownRow & { channel: string })[] }) {
  const total = rows.reduce((s, r) => s + r.amount, 0)
  const data = rows.map((r) => ({ name: r.label, value: Math.max(0, r.amount) }))
  const n = rows.length
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Наличные vs банковские карты</div>
        <div className="flex items-center gap-4">
          <div className="relative shrink-0" style={{ width: 132, height: 132 }} data-chart>
            <ResponsiveContainer width={132} height={132}>
              <PieChart>
                <Pie data={data} dataKey="value" nameKey="name" innerRadius={44} outerRadius={62} paddingAngle={1.5} stroke="none" isAnimationActive={false}>
                  {data.map((_, i) => <Cell key={i} fill={seriesColor(i, n)} />)}
                </Pie>
                <RTooltip formatter={(value) => fmtRub0(Number(value))} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <div className="text-sm font-semibold tabular-nums">{fmtFuelMetricShort('amount', total)}</div>
              <div className="text-[9px] text-muted-foreground">₽ выручка</div>
            </div>
          </div>
          <div className="min-w-0 flex-1 space-y-1.5 text-xs"
            {...exportRows('Каналы оплаты', ['Канал', 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %'],
              rows.map((r) => [r.label, r.fills, r.liters, r.amount, r.share_pct]))}>
            {rows.map((r, i) => (
              <div key={r.channel} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: seriesColor(i, n) }} />
                <span className="flex-1 truncate">{r.label}</span>
                <span className="font-mono tabular-nums text-muted-foreground">
                  {fmtFuelMetricShort('amount', r.amount)} ₽ · {r.share_pct.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">Банковская карта несёт токен клиента; наличные — анонимны.</div>
      </CardContent>
    </Card>
  )
}

/** Таблица структуры с полосами долей (топливо / станции). */
function BreakdownTable({ title, labelCol, rows, showAvgCheck, exportName }: {
  title: string; labelCol: string; rows: FuelBreakdownRow[]; showAvgCheck?: boolean; exportName: string
}) {
  const maxShare = Math.max(...rows.map((r) => r.share_pct), 0.01)
  const exCols = [labelCol, 'Реализаций', 'Литры', 'Выручка, ₽', 'Доля, %', ...(showAvgCheck ? ['Ср. чек, ₽'] : [])]
  const exData = rows.map((r) => [r.label, r.fills, r.liters, r.amount, r.share_pct, ...(showAvgCheck ? [r.avg_check ?? null] : [])] as (string | number | null)[])
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">{title}</div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" {...exportRows(exportName, exCols, exData)}>
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="p-2 text-left font-medium">{labelCol}</th>
                <th className="p-2 text-right font-medium">Реализаций</th>
                <th className="p-2 text-right font-medium">Литры</th>
                <th className="p-2 text-right font-medium">Выручка</th>
                <th className="p-2 text-right font-medium">Доля</th>
                {showAvgCheck && <th className="p-2 text-right font-medium">Ср. чек</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium truncate max-w-[240px]">{r.label}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(r.fills)}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(r.liters)}</td>
                  <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', r.amount)}</td>
                  <td className="p-2 text-right font-mono">
                    <div className="relative">
                      <div className="absolute inset-y-0 right-0 bg-primary/15 rounded-sm" style={{ width: `${Math.min(100, r.share_pct / maxShare * 100)}%` }} />
                      <span className="relative">{r.share_pct.toFixed(1)}%</span>
                    </div>
                  </td>
                  {showAvgCheck && <td className="p-2 text-right font-mono text-muted-foreground">{r.avg_check != null ? fmtFuelMetricCompact('avg_check', r.avg_check) : '—'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function WeeklyTooltip({ active, payload, label }: {
  active?: boolean
  payload?: readonly { payload?: unknown }[]
  label?: string | number
}) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as { week: string; fills: number; amount: number; avg_check: number }
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      <div className="font-medium">{String(label ?? d.week)}</div>
      <div className="text-muted-foreground">Выручка: <span className="font-mono">{fmtRub0(d.amount)}</span></div>
      <div className="text-muted-foreground">Реализаций: <span className="font-mono">{nf0.format(d.fills)}</span></div>
      <div className="text-muted-foreground">Ср. чек: <span className="font-mono">{fmtFuelMetric('avg_check', d.avg_check)}</span></div>
    </div>
  )
}

function Overview({ companyId, dateFrom, dateTo }: TabProps) {
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useRetailOverview(companyId, period.from, period.to)
  if (isLoading) return <Loading />
  if (!data || data.kpi.fills === 0) return <Empty />
  const k = data.kpi
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Выручка" value={fmtFuelMetricCompact('amount', k.amount) + ' ₽'} accent="success" />
        <KpiCard label="Объём" value={nf0.format(k.liters) + ' л'} accent="info" />
        <KpiCard label="Реализаций" value={nf0.format(k.fills)} />
        <KpiCard label="Средний чек" value={fmtFuelMetric('avg_check', k.avg_check)} />
        <KpiCard label="Ср. реализация" value={fmtFuelMetric('avg_fill', k.avg_fill)} />
        <KpiCard label="Доля безнала" value={pct1(k.cashless_pct)} hint="банковские карты в выручке розницы" />
        <KpiCard label="Доля от всех продаж" value={pct1(k.share_of_total_pct)} hint="розница в общей выручке" />
        <KpiCard label="Медиана чека" value={fmtRub0(k.check_median)} hint={`p90: ${fmtRub0(k.check_p90)}`} />
      </div>
      <ExportOnlyTable name="KPI розницы" columns={['Показатель', 'Значение']} rows={[
        ['Выручка, ₽', k.amount], ['Литры', k.liters], ['Реализаций', k.fills],
        ['Средний чек, ₽', k.avg_check], ['Ср. реализация, л', k.avg_fill],
        ['Доля безнала, %', k.cashless_pct], ['Доля от всех продаж, %', k.share_of_total_pct],
        ['Медиана чека, ₽', k.check_median], ['P90 чека, ₽', k.check_p90],
      ]} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <PayDonut rows={data.by_pay} />
        <BreakdownTable title="По видам топлива" labelCol="Топливо" rows={data.by_fuel} exportName="По топливу" />
      </div>
      <BreakdownTable title="Топ станций по выручке розницы" labelCol="Станция"
        rows={data.by_station.slice(0, 10)} showAvgCheck exportName="Топ станций" />
      {data.weekly.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Выручка и средний чек по неделям</div>
            <div data-chart>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={data.weekly} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="week" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
                  <YAxis yAxisId="amt" tick={{ fontSize: 10 }} width={46} stroke="hsl(var(--muted-foreground))"
                    tickFormatter={(v) => fmtFuelMetricShort('amount', Number(v))} />
                  <YAxis yAxisId="chk" orientation="right" tick={{ fontSize: 10 }} width={40} stroke="hsl(var(--muted-foreground))"
                    tickFormatter={(v) => nf0.format(Number(v))} />
                  <RTooltip content={<WeeklyTooltip />} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="amt" dataKey="amount" name="Выручка, ₽" fill={CHART_SERIES[0]} fillOpacity={0.55}
                    radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  <Line yAxisId="chk" dataKey="avg_check" name="Ср. чек, ₽" stroke={CHART_SERIES[2]} strokeOpacity={0.85}
                    strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <ExportOnlyTable name="По неделям" columns={['Неделя', 'Реализаций', 'Выручка, ₽', 'Ср. чек, ₽']}
              rows={data.weekly.map((w) => [w.week, w.fills, w.amount, w.avg_check])} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ───────────────────────── Лояльность ───────────────────────── */

type FreqMetric = 'cards' | 'amount'
const FREQ_META: Record<FreqMetric, { label: string; color: string; fmtAxis: (v: number) => string }> = {
  cards: { label: 'Карты', color: CHART_SERIES[0], fmtAxis: (v) => nf0.format(v) },
  amount: { label: 'Выручка', color: CHART_SERIES[1], fmtAxis: (v) => fmtFuelMetricShort('amount', v) },
}

function FreqTooltip({ active, payload }: { active?: boolean; payload?: readonly { payload?: unknown }[] }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as { label: string; cards: number; fills: number; amount: number }
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      <div className="font-medium">{d.label}</div>
      <div className="text-muted-foreground">Карт: <span className="font-mono">{nf0.format(d.cards)}</span></div>
      <div className="text-muted-foreground">Реализаций: <span className="font-mono">{nf0.format(d.fills)}</span></div>
      <div className="text-muted-foreground">Выручка: <span className="font-mono">{fmtRub0(d.amount)}</span></div>
    </div>
  )
}

function Loyalty({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_retail/loyalty', { fm: 'cards' as FreqMetric })
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-retail-loyalty', companyId, period.from, period.to],
    queryFn: () => getFuelRetailLoyalty({ companyId, dateFrom: period.from, dateTo: period.to }),
  })
  if (isLoading) return <Loading />
  if (!data || data.kpi.cards === 0) return <Empty text="Нет карточных реализаций за период" />
  const k = data.kpi
  const meta = FREQ_META[p.fm]
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Карт" value={nf0.format(k.cards)} accent="info" hint="уникальных за период" />
        <KpiCard label="Повторных" value={pct1(k.repeat_share_pct)} accent="success" hint={`${nf0.format(k.repeat_cards)} карт с 2+ визитами`} />
        <KpiCard label="Выручка повторных" value={pct1(k.repeat_revenue_pct)} accent="success" hint="от карточной выручки" />
        <KpiCard label="Реализаций / карту" value={nf1.format(k.avg_fills_per_card)} hint="в среднем" />
        <KpiCard label="Покрытие: реализации" value={pct1(k.card_coverage_fills_pct)} hint="реализаций розницы по картам" />
        <KpiCard label="Покрытие: выручка" value={pct1(k.card_coverage_amount_pct)} hint="выручки розницы по картам" />
      </div>
      <ExportOnlyTable name="KPI лояльности" columns={['Показатель', 'Значение']} rows={[
        ['Карт', k.cards], ['Повторных карт', k.repeat_cards], ['Доля повторных, %', k.repeat_share_pct],
        ['Выручка повторных, %', k.repeat_revenue_pct], ['Ср. реализаций на карту', k.avg_fills_per_card],
        ['Покрытие реализаций картами, %', k.card_coverage_fills_pct], ['Покрытие выручки картами, %', k.card_coverage_amount_pct],
      ]} />
      {data.freq_histogram.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Частота визитов за период</div>
              <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5" data-export-ignore>
                {(Object.keys(FREQ_META) as FreqMetric[]).map((m) => (
                  <button key={m} type="button" onClick={() => patch({ fm: m })}
                    className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${p.fm === m ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                    {FREQ_META[m].label}
                  </button>
                ))}
              </div>
            </div>
            <div data-chart>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={data.freq_histogram} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} stroke="hsl(var(--muted-foreground))" />
                  <YAxis tick={{ fontSize: 10 }} width={50} stroke="hsl(var(--muted-foreground))"
                    tickFormatter={(v) => meta.fmtAxis(Number(v))} />
                  <RTooltip content={<FreqTooltip />} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                  <Bar dataKey={p.fm} name={meta.label} fill={meta.color} fillOpacity={0.55}
                    radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ExportOnlyTable name="Частота визитов" columns={['Частота', 'Карт', 'Реализаций', 'Выручка, ₽']}
              rows={data.freq_histogram.map((r) => [r.label, r.cards, r.fills, r.amount])} />
            <div className="mt-2 text-[10px] text-muted-foreground">
              «1 визит» — случайные клиенты; хвост «21+» — ядро лояльной базы.
            </div>
          </CardContent>
        </Card>
      )}
      {data.top_cards.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">Топ-20 карт по выручке</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs" {...exportRows('Топ карт', ['Карта', 'Реализаций', 'Литры', 'Сумма, ₽', 'Ср. чек, ₽'],
                data.top_cards.map((c) => [c.card, c.fills, c.liters, c.amount, c.fills ? c.amount / c.fills : null]))}>
                <thead>
                  <tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">#</th>
                    <th className="p-2 text-left font-medium">Карта</th>
                    <th className="p-2 text-right font-medium">Реализаций</th>
                    <th className="p-2 text-right font-medium">Литры</th>
                    <th className="p-2 text-right font-medium">Сумма</th>
                    <th className="p-2 text-right font-medium">Ср. чек</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_cards.map((c, i) => (
                    <tr key={c.card} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 text-muted-foreground">{i + 1}</td>
                      <td className="p-2 font-mono">{c.card}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(c.fills)}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(c.liters)}</td>
                      <td className="p-2 text-right font-mono">{fmtRub0(c.amount)}</td>
                      <td className="p-2 text-right font-mono text-muted-foreground">{c.fills ? fmtFuelMetricCompact('avg_check', c.amount / c.fills) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
      <p className="text-[11px] text-muted-foreground/70">
        Карта = токен банковской карты из STS; наличные анонимны и в лояльности не участвуют.
      </p>
    </div>
  )
}

/* ─────────────────────────── Чеки ───────────────────────────── */

function CheckTooltip({ active, payload }: { active?: boolean; payload?: readonly { payload?: unknown }[] }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as { label: string; count: number; amount: number }
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      <div className="font-medium">{d.label}</div>
      <div className="text-muted-foreground">Чеков: <span className="font-mono">{nf0.format(d.count)}</span></div>
      <div className="text-muted-foreground">Выручка: <span className="font-mono">{fmtRub0(d.amount)}</span></div>
    </div>
  )
}

function Checks({ companyId, dateFrom, dateTo }: TabProps) {
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const { data, isLoading } = useRetailOverview(companyId, period.from, period.to)
  if (isLoading) return <Loading />
  if (!data || data.check_histogram.length === 0) return <Empty />
  const k = data.kpi
  const hist = data.check_histogram
  const totalCount = hist.reduce((s, b) => s + b.count, 0) || 1
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Чеков" value={nf0.format(k.fills)} />
        <KpiCard label="Медиана чека" value={fmtRub0(k.check_median)} accent="info" hint="половина чеков ниже" />
        <KpiCard label="P90 чека" value={fmtRub0(k.check_p90)} hint="90% чеков ниже" />
        <KpiCard label="Средний чек" value={fmtFuelMetric('avg_check', k.avg_check)} />
      </div>
      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Распределение суммы чека, ₽</div>
          <div data-chart>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={hist} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} stroke="hsl(var(--muted-foreground))" />
                <YAxis tick={{ fontSize: 10 }} width={50} stroke="hsl(var(--muted-foreground))"
                  tickFormatter={(v) => nf0.format(Number(v))} />
                <RTooltip content={<CheckTooltip />} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                <Bar dataKey="count" name="Чеков" fill={CHART_SERIES[0]} fillOpacity={0.55}
                  radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 text-[10px] text-muted-foreground">
            Средний чек выше медианы — распределение вытянуто вправо крупными заправками.
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs" {...exportRows('Чеки по диапазонам', ['Диапазон, ₽', 'Чеков', 'Доля, %', 'Выручка, ₽'],
              hist.map((b) => [b.label, b.count, b.count / totalCount * 100, b.amount]))}>
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-2 text-left font-medium">Диапазон, ₽</th>
                  <th className="p-2 text-right font-medium">Чеков</th>
                  <th className="p-2 text-right font-medium">Доля</th>
                  <th className="p-2 text-right font-medium">Выручка</th>
                </tr>
              </thead>
              <tbody>
                {hist.map((b) => {
                  const share = b.count / totalCount * 100
                  return (
                    <tr key={b.label} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-medium whitespace-nowrap">{b.label}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(b.count)}</td>
                      <td className="p-2 text-right font-mono">
                        <div className="relative">
                          <div className="absolute inset-y-0 right-0 bg-primary/15 rounded-sm" style={{ width: `${Math.min(100, share)}%` }} />
                          <span className="relative">{share.toFixed(1)}%</span>
                        </div>
                      </td>
                      <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', b.amount)}</td>
                    </tr>
                  )
                })}
                <tr className="bg-muted/60 font-medium">
                  <td className="p-2">Итого</td>
                  <td className="p-2 text-right font-mono">{nf0.format(totalCount)}</td>
                  <td className="p-2 text-right font-mono">100%</td>
                  <td className="p-2 text-right font-mono">{fmtFuelMetricCompact('amount', hist.reduce((s, b) => s + b.amount, 0))}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ─────────────────────────── Время ──────────────────────────── */

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']  // isodow 1..7
const HEAT_METRICS: FuelMetric[] = ['fills', 'amount', 'avg_check']

function RetailHeatmap({ companyId, dateFrom, dateTo, metric }: TabProps & { metric: FuelMetric }) {
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-retail-heatmap', companyId, dateFrom, dateTo, metric],
    queryFn: () => getFuelHeatmap({ companyId, dateFrom, dateTo, metric, segment: 'retail' }),
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
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Розница: час × день недели ({FUEL_METRIC_LABELS[metric]})</div>
        <div className="overflow-x-auto" data-chart>
          <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: '28px repeat(7, minmax(30px, 1fr))' }}>
            {items}
          </div>
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground">Темнее — интенсивнее. Пики частников — утренний и вечерний трафик будней.</div>
        <ExportOnlyTable name="Час × день" columns={['День', 'Час', FUEL_METRIC_LABELS[metric]]}
          rows={data.cells.map((c) => [WEEKDAYS[c.weekday - 1] ?? String(c.weekday), c.hour, c.value])} />
      </CardContent>
    </Card>
  )
}

function TimeTab({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_retail/time', { metric: 'fills' as FuelMetric })
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
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
      <RetailHeatmap companyId={companyId} dateFrom={period.from} dateTo={period.to} metric={p.metric} />
    </div>
  )
}

/* ────────────────────────── Динамика ────────────────────────── */

const DYN_METRICS: FuelMetric[] = ['amount', 'fills', 'avg_check']
const DYN_BUCKETS: { value: FuelBucket; label: string }[] = [
  { value: 'day', label: 'День' }, { value: 'week', label: 'Неделя' }, { value: 'month', label: 'Месяц' },
]
const DYN_DEFAULTS = { metric: 'amount' as FuelMetric, bucket: 'week' as FuelBucket }

function Dynamics({ companyId, dateFrom, dateTo }: TabProps) {
  const [p, patch] = useTabParams('fuel_retail/dynamics', DYN_DEFAULTS)
  const [view, setView] = useChartView({ type: 'line' })
  // Горизонт анализа: не персистится и сбрасывается при смене периода наверху.
  const [horizon, setHorizon] = useState<Period | null>(null)
  useEffect(() => { setHorizon(null) }, [dateFrom, dateTo])
  const period = horizon ?? { from: dateFrom, to: dateTo }
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-retail-timeseries', companyId, period.from, period.to, p.bucket, p.metric],
    queryFn: () => getFuelTimeseries({
      companyId, dateFrom: period.from, dateTo: period.to,
      bucket: p.bucket, metric: p.metric, seriesBy: 'channel', segment: 'retail',
    }),
  })
  const hasData = data && data.data.length > 0
  const format = fuelChartFormat(p.metric)
  return (
    <div className="p-4 space-y-4">
      <ViewParamsBar>
        <HorizonControl horizon={horizon} scopeFrom={dateFrom} scopeTo={dateTo} onChange={setHorizon} />
        <Field label="Метрика">
          <Select value={p.metric} onValueChange={(v) => patch({ metric: v as FuelMetric })}>
            <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{DYN_METRICS.map((m) => <SelectItem key={m} value={m} className="text-xs">{FUEL_METRIC_LABELS[m]}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Шаг">
          <Select value={p.bucket} onValueChange={(v) => patch({ bucket: v as FuelBucket })}>
            <SelectTrigger className="h-7 w-[120px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{DYN_BUCKETS.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </ViewParamsBar>
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {FUEL_METRIC_LABELS[p.metric]} · серии: Наличные / Банковские карты
            </div>
            {hasData && !isLoading && <ChartControls view={view} onChange={setView} single={data!.series.length === 1} ratio={format.ratio} />}
          </div>
          {isLoading ? <Loading /> : !hasData ? <Empty text="Нет данных за период" />
            : <ChargeChart data={data!.data} series={data!.series} view={view} format={format} />}
        </CardContent>
      </Card>
      {hasData && <ChannelTrendTable data={data!} metric={p.metric} />}
    </div>
  )
}

function ChannelTrendTable({ data, metric }: { data: FuelTimeseriesResponse; metric: FuelMetric }) {
  const exCols = ['Период', ...data.series.map((s) => (s === 'value' ? FUEL_METRIC_LABELS[metric] : s))]
  const exData = data.data.map((row) => [String(row.bucket), ...data.series.map((s) => (row[s] ?? null) as string | number | null)])
  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Динамика розницы', exCols, exData)}>
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
        </div>
      </CardContent>
    </Card>
  )
}

/* ─────────────────────── Контейнер табов ────────────────────── */

const SUB_TABS: { k: string; label: string }[] = [
  { k: 'overview', label: 'Обзор' },
  { k: 'loyalty', label: 'Лояльность' },
  { k: 'checks', label: 'Чеки' },
  { k: 'time', label: 'Время' },
  { k: 'dynamics', label: 'Динамика' },
]

function subView(sub: string, p: TabProps): { title: string; node: ReactNode } {
  switch (sub) {
    case 'loyalty': return { title: 'Лояльность', node: <Loyalty {...p} /> }
    case 'checks': return { title: 'Чеки', node: <Checks {...p} /> }
    case 'time': return { title: 'Время', node: <TimeTab {...p} /> }
    case 'dynamics': return { title: 'Динамика', node: <Dynamics {...p} /> }
    default: return { title: 'Обзор', node: <Overview {...p} /> }
  }
}

/** Пункт «Частные лица» — контейнер с внутренними табами. */
export function FuelRetailPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [st, patch] = useTabParams('fuel_retail', { sub: 'overview' })
  const v = subView(st.sub, { companyId, dateFrom, dateTo })
  const ref = useRef<HTMLDivElement>(null)
  const scopeSub = useScopeSubtitle()
  return (
    <>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <PanelViewTabs tabs={SUB_TABS} value={st.sub} onChange={(k) => patch({ sub: k })} ariaLabel="Виды раздела «Розница»" />
        <div className="flex items-center gap-2 shrink-0">
          <ExportButton title={`Частные лица · ${v.title}`} subtitle={scopeSub} getEl={() => ref.current} />
        </div>
      </div>
      {/* key={st.sub} — ремаунт под-вида при смене таба (чистое локальное состояние). */}
      <div ref={ref} className="pt-3" key={st.sub}>{v.node}</div>
    </>
  )
}
