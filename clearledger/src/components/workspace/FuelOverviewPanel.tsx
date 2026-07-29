/**
 * Executive-дашборд «Обзор» продаж топлива сети АЗС (fuel, ГИГ) — стратегическая
 * витрина по образцу ЭЗС `OverviewDashboardPanel`, но на топливной семантике
 * (литры, ₽/л, виды топлива, каналы оплаты, сливы ТТН, FIFO-маржа, готовность к 1С).
 *
 * Первый срез паритета ГИГ↔ЭЗС: собирается на ТЕКУЩИХ агрегатах, без нового
 * транзакционного слоя. Данные:
 *   /api/fuel/shift-dashboard?compare=true  — продажи/оплаты/сливы ТТН/по дням/по АЗС/тренды
 *   /api/fuel/readiness                     — готовность к 1С (для алертов и полосы обработки)
 *   /api/fuel/costing/margin                — FIFO-маржа (KPI + мини-блок)
 */

import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useFilters } from '@/contexts/FilterContext'
import { useLocations } from '@/hooks/useLocations'
import { scopeStationCodes } from '@/services/locationService'
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, LineChart, Line, ReferenceLine, ComposedChart, Cell,
} from 'recharts'
import {
  Loader2, AlertTriangle, Info, Fuel, TrendingUp, Droplet, FileCheck2, CreditCard, Clock,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { ExportButton } from './analytics/ExportButton'
import { FuelInsightsBar } from './FuelNetworkPanels'
import { CHART_SERIES as SERIES, seriesColor } from './analytics/palette'
import { fmtMoney, fmtMoneyShort, fmtLiters } from '@/services/analyticsService'
import { formatPeriod } from '@/lib/formatDate'
import {
  getShiftDashboard, getFuelReadiness, getCostingMargin,
  type ShiftDashboardData, type DashTrend, type DashStation, type DashOnboarding,
  type DashActivity, type DashCard,
} from '@/services/fuel/fuelMappingService'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'

// Цвет маркеров подключения станций (спокойный emerald, тема-независимый).
const ONBOARD_COLOR = 'hsl(160 60% 45%)'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

// Ключи дневной раскладки оплат (в charts.daily топл.карты сведены в corporate).
const PAY_DAILY: { key: keyof ShiftDashboardData['charts']['daily'][number]; label: string }[] = [
  { key: 'cash', label: 'Наличные' },
  { key: 'card', label: 'Банк. карты' },
  { key: 'online', label: 'Онлайн' },
  { key: 'corporate', label: 'Ведомости / топл. карты' },
  { key: 'coupon', label: 'Талоны / купоны' },
]

function Loading() {
  return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет продаж за период' }: { text?: string }) {
  return <div className="p-8 text-sm text-muted-foreground text-center">{text}</div>
}

// ─── дневная ось: '2026-06-04' → '04.06' ─────────────────────────────
const dayTick = (b: string) => (b.length === 10 ? `${b.slice(8, 10)}.${b.slice(5, 7)}` : b)
const chartAxis = { fontSize: 10, fill: 'hsl(var(--muted-foreground))' } as const

// ─── KPI-модель ──────────────────────────────────────────────────────
type KpiFmt = 'money' | 'liters' | 'price' | 'int'
interface Kpi {
  label: string; value: number; fmt: KpiFmt; unit?: string
  delta_pct: number | null; spark?: (number | null)[]; hint?: string
}

function kpiText(k: Kpi): string {
  const v =
    k.fmt === 'money' ? fmtMoneyShort(k.value)
    : k.fmt === 'liters' ? fmtLiters(k.value)
    : k.fmt === 'price' ? fmtMoney(k.value)
    : nf0.format(k.value)
  return k.unit ? `${v} ${k.unit}` : v
}

/** Δ% из тренда бэка; null — если базы нет (прошлый период пуст → фиктивные +100%). */
function trendDelta(t?: DashTrend): number | null {
  if (!t || !(t.previous > 0)) return null
  return t.percent
}

/** Мини-спарклайн (inline SVG). Пустые бакеты (null) — разрыв линии. */
function Sparkline({ data }: { data: (number | null)[] }) {
  const vals = data.filter((v): v is number => v != null)
  if (vals.length < 2) return null
  const min = Math.min(...vals), max = Math.max(...vals), rng = max - min || 1
  const n = data.length
  const pts = data
    .map((v, i) => (v == null ? null : `${((i / (n - 1)) * 100).toFixed(1)},${(100 - ((v - min) / rng) * 100).toFixed(1)}`))
    .filter(Boolean).join(' ')
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="mt-2 h-7 w-full text-muted-foreground/60" aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={3} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** Простая счётная плитка (label · value · hint). Порядок детей — контракт экспорта. */
function CountCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div data-kpi className="rounded-xl border bg-card/50 p-3.5 shadow-sm">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums leading-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

/** KPI-плитка с Δ% к прошлому периоду + спарклайн (контракт data-kpi: первые 3 ребёнка). */
function KpiCard({ k, baseline }: { k: Kpi; baseline?: string }) {
  const showDelta = k.delta_pct != null && Math.abs(k.delta_pct) <= 500
  const up = (k.delta_pct ?? 0) >= 0
  return (
    <div data-kpi className="relative rounded-xl border bg-card/50 p-3.5 shadow-sm">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{k.label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums leading-tight">{kpiText(k)}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{k.hint ?? ''}</div>
      {showDelta && (
        // База сравнения — на самом проценте: она относится только к нему, а не
        // ко всей строке карточек (у части KPI своего Δ нет вовсе).
        <span title={baseline && `Изменение к предыдущему периоду: ${baseline}`}
          className={`absolute right-3 top-3 text-[11px] font-medium tabular-nums ${up ? 'text-emerald-600/90 dark:text-emerald-400/90' : 'text-red-600/90 dark:text-red-400/90'}`}>
          {up ? '▲' : '▼'}{Math.abs(k.delta_pct!).toFixed(1)}%
        </span>
      )}
      {k.spark && <Sparkline data={k.spark} />}
    </div>
  )
}

interface BreakRow { name: string; revenue: number; volume: number; count?: number }

/** Полная таблица разреза продаж (виды топлива / способы оплаты) — как в эталоне:
 *  все строки, Выручка · Объём · Доля · Реализации + Итого. Реализации (count) — из
 *  пооперационных транзакций; при их отсутствии колонка скрыта. */
function BreakdownTable({ title, nameCol, icon, rows }: {
  title: string; nameCol: string; icon: ReactNode; rows: BreakRow[]
}) {
  const totRev = rows.reduce((s, r) => s + r.revenue, 0)
  const totVol = rows.reduce((s, r) => s + r.volume, 0)
  const hasCount = rows.some((r) => r.count != null)
  const totCnt = rows.reduce((s, r) => s + (r.count ?? 0), 0)
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex items-center gap-1.5 border-b bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground">{icon}{title} ({rows.length})</div>
        {rows.length === 0 ? <div className="p-4 text-xs text-muted-foreground">Нет данных за период</div> : (
          <table className="w-full text-xs" data-export-name={title}
            data-export-rows={JSON.stringify({
              columns: [nameCol, 'Выручка, ₽', 'Объём, л', 'Доля, %', ...(hasCount ? ['Реализации'] : [])],
              rows: rows.map((r) => [r.name, r.revenue, r.volume, totRev ? (r.revenue / totRev) * 100 : 0, ...(hasCount ? [r.count ?? 0] : [])]),
            })}>
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="p-2 text-left font-medium">{nameCol}</th>
                <th className="p-2 text-right font-medium">Выручка</th>
                <th className="p-2 text-right font-medium">Объём, л</th>
                <th className="p-2 text-right font-medium">Доля</th>
                {hasCount && <th className="p-2 text-right font-medium">Реализации</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="max-w-[160px] truncate p-2 font-medium">{r.name}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(r.revenue)} ₽</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtLiters(r.volume)}</td>
                  <td className="p-2 text-right font-mono tabular-nums">{totRev ? ((r.revenue / totRev) * 100).toFixed(1) : '0.0'}%</td>
                  {hasCount && <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{r.count != null ? nf0.format(r.count) : '—'}</td>}
                </tr>
              ))}
              <tr className="bg-muted/60 font-medium">
                <td className="p-2">Итого</td>
                <td className="p-2 text-right font-mono">{fmtMoney(totRev)} ₽</td>
                <td className="p-2 text-right font-mono">{fmtLiters(totVol)}</td>
                <td className="p-2 text-right font-mono">100%</td>
                {hasCount && <td className="p-2 text-right font-mono">{nf0.format(totCnt)}</td>}
              </tr>
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}

/** Компактный сегмент-переключатель. */
function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { v: T; label: string }[]
}) {
  return (
    <div className="inline-flex gap-0.5 rounded-md border border-border p-0.5" data-export-ignore>
      {options.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`rounded-[5px] px-2.5 py-0.5 text-xs transition-colors ${value === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

type RevMode = 'all' | 'payment'
const REV_MODES: { v: RevMode; label: string }[] = [
  { v: 'all', label: 'Все' }, { v: 'payment', label: 'По оплате' },
]

const codeOf = (o: DashOnboarding) => (o.code != null ? `№${o.code}` : o.name)
const dayMs = (s: string) => Date.parse(s + 'T00:00:00Z')

/** Реализация (выручка) по дням — «Все» (одна серия) или разбивка по каналам оплаты.
 *  Подключение сети: ступенчатая линия «Активных АЗС» (правая ось) + вертикальные
 *  маркеры первой смены станций (близкие сгруппированы, чтобы подписи не наезжали). */
function DailyRevenueBar({ daily, onboarding }: {
  daily: ShiftDashboardData['charts']['daily']; onboarding: DashOnboarding[]
}) {
  const [mode, setMode] = useState<RevMode>('all')
  const [showMarks, setShowMarks] = useState(true)
  const barColor = (i: number) => (mode === 'all' ? SERIES[0] : seriesColor(i, PAY_DAILY.length))

  // Маркеры в видимом диапазоне (дата первой смены — абсолютная).
  const marks = useMemo(() => {
    if (!daily.length || !onboarding.length) return []
    const first = daily[0].date, last = daily[daily.length - 1].date
    return onboarding.filter((o) => o.date >= first && o.date <= last).sort((a, b) => (a.date < b.date ? -1 : 1))
  }, [daily, onboarding])

  // Кумулятивное число подключённых АЗС на каждый день (ступенька «по мере подключения»).
  const chartData = useMemo(() => {
    const dates = onboarding.map((o) => o.date).sort()
    return daily.map((d) => ({ ...d, active: dates.filter((dt) => dt <= d.date).length }))
  }, [daily, onboarding])
  const maxActive = Math.max(1, onboarding.length)

  // Группировка близких маркеров (порог ~3% диапазона) — одна подпись на кластер.
  const markGroups = useMemo(() => {
    if (!marks.length) return []
    const span = dayMs(daily[daily.length - 1].date) - dayMs(daily[0].date) || 1
    const thr = span * 0.03
    const groups: { date: string; last: string; items: DashOnboarding[] }[] = []
    for (const o of marks) {
      const g = groups[groups.length - 1]
      if (g && dayMs(o.date) - dayMs(g.last) <= thr) { g.items.push(o); g.last = o.date }
      else groups.push({ date: o.date, last: o.date, items: [o] })
    }
    return groups
  }, [marks, daily])

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <span className="text-emerald-600 dark:text-emerald-400">₽</span>Реализация по дням ({daily.length} дн.)
          </div>
          <div className="flex items-center gap-2">
            {marks.length > 0 && (
              <button type="button" onClick={() => setShowMarks((v) => !v)} data-export-ignore
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs transition-colors ${showMarks ? 'text-foreground' : 'text-muted-foreground'}`}
                title="Показать/скрыть подключение АЗС (ступень + маркеры)">
                <span className="inline-block h-3 border-l-2 border-dashed" style={{ borderColor: ONBOARD_COLOR }} />
                Подключения АЗС ({marks.length})
              </button>
            )}
            <Segmented value={mode} onChange={setMode} options={REV_MODES} />
          </div>
        </div>
        {mode === 'payment' && (
          <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {PAY_DAILY.map((p, i) => (
              <span key={p.key} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: barColor(i) }} />
                <span className="text-muted-foreground">{p.label}</span>
              </span>
            ))}
          </div>
        )}
        {daily.length === 0 ? <Empty /> : (
          <div data-chart>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={chartData} margin={{ top: 16, right: 12, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="date" tick={chartAxis} tickFormatter={dayTick} minTickGap={16} stroke="hsl(var(--muted-foreground))" />
                <YAxis yAxisId="left" tick={chartAxis} tickFormatter={(v: number) => fmtMoneyShort(v)} width={56} stroke="hsl(var(--muted-foreground))" />
                <YAxis yAxisId="right" orientation="right" tick={chartAxis} width={26} allowDecimals={false}
                  domain={[0, maxActive]} stroke={ONBOARD_COLOR} hide={!showMarks} />
                <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} labelFormatter={(label) => dayTick(String(label))}
                  formatter={(value, name) => name === 'Активных АЗС'
                    ? [`${value}`, 'Активных АЗС']
                    : [`${fmtMoney(Number(value))} ₽`, name === 'revenue' ? 'Выручка' : String(name)]} />
                {mode === 'all'
                  ? <Bar yAxisId="left" dataKey="revenue" fill={SERIES[0]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  : PAY_DAILY.map((p, i) => (
                    <Bar key={p.key} yAxisId="left" dataKey={p.key} name={p.label} stackId="rev" fill={barColor(i)}
                      radius={i === PAY_DAILY.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} isAnimationActive={false} />
                  ))}
                {showMarks && (
                  <Line yAxisId="right" type="stepAfter" dataKey="active" name="Активных АЗС"
                    stroke={ONBOARD_COLOR} strokeWidth={1.6} dot={false} isAnimationActive={false} />
                )}
                {showMarks && markGroups.map((g, gi) => {
                  const codes = g.items.map(codeOf)
                  const label = codes.length <= 3 ? codes.join('·') : `${codes[0]} +${codes.length - 1}`
                  return (
                    <ReferenceLine key={g.date} yAxisId="left" x={g.date} stroke={ONBOARD_COLOR}
                      strokeDasharray="3 3" strokeOpacity={0.65}
                      label={{ value: label, position: 'top', fontSize: 9, fill: ONBOARD_COLOR, dy: gi % 2 ? 11 : 0 }} />
                  )
                })}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
        {showMarks && marks.length > 0 && (
          <div className="mt-1.5 text-[11px] text-muted-foreground">
            <span className="inline-block h-2 border-l-2 border-dashed align-middle" style={{ borderColor: ONBOARD_COLOR }} />{' '}
            Ступень «Активных АЗС» (правая ось) + пунктир — дата первой смены: {marks.map((o) => codeOf(o) + ' ' + dayTick(o.date)).join(' · ')}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** Тултип средней цены: «ДД.ММ: X ₽/л». */
function PriceTip({ active, payload, label }: {
  active?: boolean; payload?: Array<{ dataKey?: string | number; value?: number | null }>; label?: string | number
}) {
  if (!active || !payload?.length) return null
  const v = payload.find((p) => p.dataKey === 'value')?.value
  if (v == null) return null
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md whitespace-nowrap">
      <span className="text-muted-foreground">{dayTick(String(label))}: </span>
      <span className="font-mono font-medium">{fmtMoney(Number(v))} ₽/л</span>
    </div>
  )
}

/** Средняя цена ₽/л по дням (выручка÷объём) + трендовая линия (регрессия) + бейдж. */
function AvgPriceLine({ daily, bigValue }: { daily: ShiftDashboardData['charts']['daily']; bigValue: number }) {
  const { rows, growth } = useMemo(() => {
    const base = daily.map((d) => ({ bucket: d.date, value: d.volume > 0 ? d.revenue / d.volume : null as number | null }))
    const valid = base.map((r, i) => ({ i, v: r.value })).filter((p) => p.v != null) as { i: number; v: number }[]
    const n = valid.length
    if (n < 2) return { rows: base.map((r) => ({ ...r, trend: null as number | null })), growth: null as number | null }
    const sx = valid.reduce((s, p) => s + p.i, 0), sy = valid.reduce((s, p) => s + p.v, 0)
    const sxx = valid.reduce((s, p) => s + p.i * p.i, 0), sxy = valid.reduce((s, p) => s + p.i * p.v, 0)
    const b = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1)
    const a = (sy - b * sx) / n
    const rows = base.map((r, i) => ({ ...r, trend: a + b * i }))
    const y0 = a, y1 = a + b * (base.length - 1)
    return { rows, growth: y0 ? ((y1 - y0) / y0) * 100 : null }
  }, [daily])
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium"><Droplet className="h-4 w-4 text-blue-600 dark:text-blue-400" />Средняя цена реализации</div>
            <div className="text-[11px] text-muted-foreground">выручка ÷ объём по дням</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{fmtMoney(bigValue)} ₽/л</div>
          </div>
          {growth != null && (
            <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${growth >= 0 ? 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300' : 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300'}`}>
              {growth >= 0 ? 'Рост' : 'Снижение'} {growth >= 0 ? '+' : ''}{nf1.format(growth)}%
            </span>
          )}
        </div>
        {rows.length === 0 ? <Empty /> : (
          <div data-chart>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={rows} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="bucket" tick={chartAxis} tickFormatter={dayTick} minTickGap={16} stroke="hsl(var(--muted-foreground))" />
                <YAxis tick={chartAxis} tickFormatter={(v: number) => nf1.format(v)} width={48} stroke="hsl(var(--muted-foreground))" domain={['auto', 'auto']} />
                <Tooltip content={<PriceTip />} />
                <Line type="monotone" dataKey="trend" stroke="hsl(var(--muted-foreground))" strokeDasharray="5 4" strokeWidth={1.2} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="value" stroke={SERIES[0]} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── станции: лидеры / аутсайдеры по выручке ─────────────────────────
function StationList({ title, rows, empty }: { title: string; rows: DashStation[]; empty: string }) {
  const max = Math.max(...rows.map((r) => r.revenue), 0.01)
  return (
    <Card>
      <CardContent className="p-0">
        <div className="border-b bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground">{title}</div>
        {rows.length === 0 ? <div className="p-4 text-xs text-muted-foreground">{empty}</div> : (
          <table className="w-full text-xs" data-export-name={title}
            data-export-rows={JSON.stringify({
              columns: ['АЗС', 'Смен', 'Объём, л', 'Выручка, ₽', 'Ср. цена, ₽/л'],
              rows: rows.map((r) => [r.station_name, r.shifts, r.volume, r.revenue, r.avg_price]),
            })}>
            <tbody>
              {rows.map((r) => (
                <tr key={r.station_id} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="max-w-[220px] truncate p-2 font-medium">{r.station_name}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.shifts)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtLiters(r.volume)}</td>
                  <td className="p-2 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <div className="h-1.5 w-14 overflow-hidden rounded bg-muted">
                        <div className="h-full bg-primary/70" style={{ width: `${Math.min(100, (r.revenue / max) * 100)}%` }} />
                      </div>
                      <span className="w-16 text-right font-mono tabular-nums">{fmtMoneyShort(r.revenue)} ₽</span>
                    </div>
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums">{nf2.format(r.avg_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}

// ─── сливы ТТН (поступления топлива): документ / факт / отклонение ────
function ReceiptsBlock({ receipts }: { receipts: ShiftDashboardData['receipts'] }) {
  const totalDoc = receipts.total_doc
  const devPct = totalDoc ? (receipts.total_diff / totalDoc) * 100 : 0
  const devAccent = Math.abs(devPct) <= 0.2 ? 'text-muted-foreground' : Math.abs(devPct) <= 0.5 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b bg-muted/40 px-3 py-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground"><Fuel className="h-3.5 w-3.5" />Сливы ТТН (приёмка топлива)</div>
          <span className="text-xs text-muted-foreground">ТТН: <b className="text-foreground">{nf0.format(receipts.ttn_count)}</b></span>
          <span className="text-xs text-muted-foreground">Документ: <b className="text-foreground">{fmtLiters(totalDoc)}</b></span>
          <span className="text-xs text-muted-foreground">Факт: <b className="text-foreground">{fmtLiters(receipts.total_fact)}</b></span>
          <span className={`text-xs ${devAccent}`}>Отклонение: <b>{receipts.total_diff >= 0 ? '+' : ''}{nf1.format(receipts.total_diff)} л ({devPct >= 0 ? '+' : ''}{nf2.format(devPct)}%)</b></span>
        </div>
        {receipts.by_fuel.length === 0 ? <div className="p-4 text-xs text-muted-foreground">Нет поступлений за период</div> : (
          <table className="w-full text-xs" data-export-name="Сливы ТТН по видам топлива"
            data-export-rows={JSON.stringify({
              columns: ['Топливо', 'Документ, л', 'Факт, л', 'Отклонение, л', 'ТТН, шт'],
              rows: receipts.by_fuel.map((r) => [r.fuel_name, r.doc_volume, r.fact_volume, r.diff, r.ttn_count]),
            })}>
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="p-2 text-left font-medium">Топливо</th>
                <th className="p-2 text-right font-medium">Документ, л</th>
                <th className="p-2 text-right font-medium">Факт, л</th>
                <th className="p-2 text-right font-medium">Отклонение, л</th>
                <th className="p-2 text-right font-medium">ТТН</th>
              </tr>
            </thead>
            <tbody>
              {receipts.by_fuel.map((r) => {
                const d = r.doc_volume ? (r.diff / r.doc_volume) * 100 : 0
                return (
                  <tr key={r.fuel_code} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-medium">{r.fuel_name}</td>
                    <td className="p-2 text-right font-mono">{fmtLiters(r.doc_volume)}</td>
                    <td className="p-2 text-right font-mono">{fmtLiters(r.fact_volume)}</td>
                    <td className={`p-2 text-right font-mono ${Math.abs(d) <= 0.5 ? '' : 'text-amber-600 dark:text-amber-400'}`}>{r.diff >= 0 ? '+' : ''}{nf1.format(r.diff)}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground">{r.ttn_count}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}

// ─── FIFO-маржа (mini) ───────────────────────────────────────────────
function MarginMini({ companyId, from, to }: { companyId: string; from: string; to: string }) {
  const fk = useFuelKindFilter()
  const { data } = useQuery({
    // companyId обязателен в ключе: запрос скоупится заголовком X-Company-Id,
    // без него при смене компании отдаётся кеш предыдущей.
    queryKey: ['fuel-overview-margin', companyId, from, to, fk.key],
    queryFn: () => getCostingMargin(from, to, 'fuel', fk.fuelCodes),
  })
  if (!data) return null
  const t = data.totals
  const perLiter = t.liters_costed ? t.margin / t.liters_costed : 0
  const stat = (label: string, value: string, accent?: string) => (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${accent ?? ''}`}>{value}</div>
    </div>
  )
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3 pt-4">
        {stat('Маржа (FIFO)', fmtMoneyShort(t.margin) + ' ₽', t.margin >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}
        {stat('Маржа на литр', nf2.format(perLiter) + ' ₽/л')}
        {stat('Себестоимость', fmtMoneyShort(t.cogs) + ' ₽')}
        {stat('Выручка без НДС', fmtMoneyShort(t.revenue_net) + ' ₽')}
        {stat('С себестоимостью', fmtLiters(t.liters_costed), t.liters_uncosted > 0 ? undefined : 'text-emerald-600 dark:text-emerald-400')}
        {t.liters_uncosted > 0 && stat('Без себестоимости', fmtLiters(t.liters_uncosted), 'text-amber-600 dark:text-amber-400')}
        <span className="ml-auto text-[11px] text-muted-foreground">Детали — в пункте «Маржа и цены»</span>
      </CardContent>
    </Card>
  )
}

// ─── готовность к 1С / обработка смен (mini-полоса) ──────────────────
function ReadinessStrip({ companyId, from, to }: { companyId: string; from: string; to: string }) {
  const { data } = useQuery({
    queryKey: ['fuel-overview-readiness', companyId, from, to],
    queryFn: () => getFuelReadiness(from, to),
  })
  if (!data) return null
  const chip = (label: string, value: number, accent?: string) => (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <b className={`tabular-nums ${accent ?? 'text-foreground'}`}>{nf0.format(value)}</b>
    </span>
  )
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 pt-4">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground"><FileCheck2 className="h-3.5 w-3.5" />Готовность к 1С</div>
        {chip('Смен', data.shifts.total)}
        {chip('· с правками', data.shifts.corrected, data.shifts.corrected > 0 ? 'text-amber-600 dark:text-amber-400' : undefined)}
        {chip('ТТН на проверке', data.receipts.pending, data.receipts.pending > 0 ? 'text-amber-600 dark:text-amber-400' : undefined)}
        {chip('· принято', data.receipts.confirmed)}
        {chip('· отклонено', data.receipts.rejected, data.receipts.rejected > 0 ? 'text-red-600 dark:text-red-400' : undefined)}
        {chip('Пакеты к выгрузке', data.packets.draft, data.packets.draft > 0 ? 'text-amber-600 dark:text-amber-400' : undefined)}
        {chip('· выгружено', data.packets.acked, 'text-emerald-600 dark:text-emerald-400')}
        <span className="ml-auto text-[11px] text-muted-foreground">Обработка — в разделе «Бухгалтерский»</span>
      </CardContent>
    </Card>
  )
}

// ─── профиль активности (по транзакциям) + топ карт ──────────────────
const WD_FULL: Record<number, string> = { 1: 'Понедельник', 2: 'Вторник', 3: 'Среда', 4: 'Четверг', 5: 'Пятница', 6: 'Суббота', 7: 'Воскресенье' }

function HourlyActivity({ a }: { a: DashActivity }) {
  return (
    <Card><CardContent className="pt-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium"><Clock className="h-4 w-4 text-blue-600 dark:text-blue-400" />Реализации по часам суток{a.peak_hour != null ? ` · пик ${String(a.peak_hour).padStart(2, '0')}:00` : ''}</div>
      <div data-chart>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={a.hourly} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={chartAxis} interval={1} stroke="hsl(var(--muted-foreground))" />
            <YAxis tick={chartAxis} tickFormatter={(v: number) => nf0.format(v)} width={44} stroke="hsl(var(--muted-foreground))" />
            <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} labelFormatter={(l) => `${l}:00`} formatter={(v) => [`${nf0.format(Number(v))} реализаций`, 'Реализации']} />
            <Bar dataKey="count" fill={SERIES[0]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </CardContent></Card>
  )
}

function WeekdayActivity({ a }: { a: DashActivity }) {
  const best = a.best_weekday
  return (
    <Card><CardContent className="pt-4">
      <div className="mb-2">
        <div className="text-sm font-medium">Выручка по дням недели</div>
        {best != null && <div className="text-[11px] text-muted-foreground">Лучший день: {WD_FULL[best]}</div>}
      </div>
      <div data-chart>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={a.weekday} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={chartAxis} stroke="hsl(var(--muted-foreground))" />
            <YAxis tick={chartAxis} tickFormatter={(v: number) => fmtMoneyShort(v)} width={56} stroke="hsl(var(--muted-foreground))" />
            <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} formatter={(v) => `${fmtMoney(Number(v))} ₽`} />
            <Bar dataKey="amount" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {a.weekday.map((d) => <Cell key={d.weekday} fill={d.weekday === best ? 'hsl(152, 69%, 45%)' : SERIES[0]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </CardContent></Card>
  )
}

function TopCards({ cards }: { cards: DashCard[] }) {
  return (
    <Card><CardContent className="p-0">
      <div className="flex items-center gap-1.5 border-b bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground"><CreditCard className="h-3.5 w-3.5" />Топ карт по обороту ({cards.length})</div>
      <table className="w-full text-xs" data-export-name="Топ карт"
        data-export-rows={JSON.stringify({ columns: ['Карта', 'Реализации', 'Объём, л', 'Сумма, ₽'], rows: cards.map((c) => [c.card, c.count, c.liters, c.amount]) })}>
        <thead>
          <tr className="border-b text-muted-foreground">
            <th className="p-2 text-left font-medium">Карта</th>
            <th className="p-2 text-right font-medium">Реализации</th>
            <th className="p-2 text-right font-medium">Объём, л</th>
            <th className="p-2 text-right font-medium">Сумма</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((c) => (
            <tr key={c.card} className="border-b border-border/30 hover:bg-muted/30">
              <td className="max-w-[220px] truncate p-2 font-mono">{c.card}</td>
              <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(c.count)}</td>
              <td className="p-2 text-right font-mono text-muted-foreground">{fmtLiters(c.liters)}</td>
              <td className="p-2 text-right font-mono">{fmtMoney(c.amount)} ₽</td>
            </tr>
          ))}
        </tbody>
      </table>
    </CardContent></Card>
  )
}

function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline gap-2 pt-1">
      <h3 className="text-sm font-semibold">{children}</h3>
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
    </div>
  )
}

// ─── главная витрина ─────────────────────────────────────────────────
export function FuelOverviewPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }

  /**
   * Область учёта обязана доходить до цифр.
   *
   * Панель читала из контура только период: выбор станции применялся в шапке
   * (чип, ограничение с ✕, счётчик «Фильтры 1»), а дашборд считал по всей сети —
   * «АЗС: 13» и та же выручка. Для учётных цифр это хуже отсутствия фильтра:
   * на экране заявлена одна станция, а числа сетевые.
   *
   * Отдаём КОДЫ станций — тем же scopeStationCodes, что и «Реализации»
   * (FuelFillsPanel). Роутер их резолвит в station_id по fuel_stations.code;
   * до правки он принимал только UUID и на «208» молча подставлял None, то
   * есть тихо возвращал всю сеть.
   */
  const { locationIds, regionIds } = useFilters()
  const locations = useLocations()
  const scopeCodes = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds),
    [locations, locationIds, regionIds],
  )
  const scopeKey = scopeCodes.join(',')
  // Вид нефтепродукта из общего фильтра: обзор обязан считать по нему так же,
  // как разрезы и цены, иначе шапка спорит с экранами под ней.
  const fk = useFuelKindFilter()

  const { data, isLoading, error } = useQuery({
    queryKey: ['fuel-overview', companyId, period.from, period.to, scopeKey, fk.key],
    queryFn: () => getShiftDashboard(period.from, period.to, {
      compare: true,
      stations: scopeCodes.length ? scopeCodes.map(String) : undefined,
      fuelCodes: fk.fuelCodes,
    }),
  })
  const margin = useQuery({
    queryKey: ['fuel-overview-margin-kpi', companyId, period.from, period.to, fk.key],
    queryFn: () => getCostingMargin(period.from, period.to, 'fuel', fk.fuelCodes),
  })
  // Готовность к 1С — тот же контур, иначе алерты в шапке считались бы по всей
  // сети при выбранной одной АЗС.
  const readiness = useQuery({
    queryKey: ['fuel-overview-readiness-alerts', companyId, period.from, period.to, scopeKey],
    queryFn: () => getFuelReadiness(period.from, period.to, {
      stations: scopeCodes.length ? scopeCodes.map(String) : undefined,
    }),
  })

  // Смены-пробелы: источник не отдал детализацию продаж (см. FuelShift.sales_missing).
  // Мешать их с рабочими сменами нельзя — «выручка на смену» просядет без причины.
  const missingSales = data?.operational.shifts_missing_sales ?? 0

  const kpis: Kpi[] = useMemo(() => {
    if (!data) return []
    const daily = data.charts.daily
    const sparkRev = daily.map((d) => d.revenue)
    const sparkVol = daily.map((d) => d.volume)
    const sparkPrice = daily.map((d) => (d.volume > 0 ? d.revenue / d.volume : null))
    const avgPrice = data.financial.avg_price ?? (data.volume.total ? data.financial.total_revenue / data.volume.total : 0)
    // Δ ср.цены — из прошлых тоталов (revenue/volume) тренда.
    const prevRev = data.trends?.revenue.previous ?? 0
    const prevVol = data.trends?.volume.previous ?? 0
    const prevPrice = prevVol > 0 ? prevRev / prevVol : 0
    const priceDelta = prevPrice > 0 ? ((avgPrice - prevPrice) / prevPrice) * 100 : null
    const marginTot = margin.data?.totals.margin ?? 0
    const marginPerL = margin.data && margin.data.totals.liters_costed ? marginTot / margin.data.totals.liters_costed : 0
    return [
      { label: 'Выручка', value: data.financial.total_revenue, fmt: 'money', unit: '₽', delta_pct: trendDelta(data.trends?.revenue), spark: sparkRev, hint: 'продажи топлива' },
      { label: 'Объём', value: data.volume.total, fmt: 'liters', unit: 'л', delta_pct: trendDelta(data.trends?.volume), spark: sparkVol, hint: 'реализовано' },
      { label: 'Средняя цена', value: avgPrice, fmt: 'price', unit: '₽/л', delta_pct: priceDelta, spark: sparkPrice, hint: 'выручка ÷ объём' },
      { label: 'Смен', value: missingSales > 0 ? (data.operational.shifts_with_sales ?? data.operational.shifts_count) : data.operational.shifts_count, fmt: 'int', delta_pct: trendDelta(data.trends?.shifts), hint: missingSales > 0 ? `с продажами; ещё ${nf0.format(missingSales)} без данных` : 'закрыто за период' },
      { label: 'Маржа (FIFO)', value: marginTot, fmt: 'money', unit: '₽', delta_pct: null, hint: marginPerL ? `${nf2.format(marginPerL)} ₽/л` : 'задайте себестоимость' },
    ]
  }, [data, margin.data, missingSales])

  const alerts = useMemo(() => {
    const out: { level: 'info' | 'warn'; message: string }[] = []
    if (missingSales > 0) out.push({
      level: 'warn',
      message: `Источник не отдал продажи по ${nf0.format(missingSales)} сменам — они не в цифрах периода`,
    })
    const r = readiness.data
    if (r) {
      if (r.receipts.pending > 0) out.push({ level: 'warn', message: `Непроверенных ТТН: ${r.receipts.pending}` })
      if (r.receipts.rejected > 0) out.push({ level: 'warn', message: `Отклонённых ТТН: ${r.receipts.rejected}` })
      if (r.packets.draft > 0) out.push({ level: 'info', message: `Пакетов к выгрузке в 1С: ${r.packets.draft}` })
    }
    if (data && data.receipts.total_doc > 0) {
      const devPct = (data.receipts.total_diff / data.receipts.total_doc) * 100
      if (Math.abs(devPct) > 0.5) out.push({ level: 'warn', message: `Отклонение слива ТТН: ${data.receipts.total_diff >= 0 ? '+' : ''}${nf1.format(data.receipts.total_diff)} л (${nf2.format(devPct)}%)` })
    }
    const mt = margin.data?.totals
    if (mt) {
      if (mt.liters_uncosted > 0) out.push({ level: 'info', message: `Без себестоимости: ${fmtLiters(mt.liters_uncosted)} — не учтены в марже` })
      if (mt.margin < 0) out.push({ level: 'warn', message: 'Отрицательная FIFO-маржа за период' })
    }
    return out
  }, [readiness.data, data, margin.data, missingSales])

  const stations = data?.by_station ?? []
  const topStations = stations.slice(0, 5)
  const bottomStations = stations.length > 5 ? stations.filter((s) => s.revenue > 0).slice(-5).reverse() : []

  // Период, с которым сравниваются Δ% на карточках — в подсказку самих Δ.
  const baseline = data?.prev_period
    ? formatPeriod(data.prev_period.from, data.prev_period.to)
    : undefined

  return (
    <div className="p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3" data-export-ignore>
        {/* Счётчики (АЗС, смены, дни) не дублируем: они ниже карточками.
            База сравнения переехала к строке KPI — там, где живут её Δ%. */}
        <h2 className="flex items-center gap-2 text-base font-semibold"><Fuel className="h-4 w-4 text-blue-600 dark:text-blue-400" />Обзор продаж топлива</h2>
        <ExportButton title="Обзор продаж топлива" subtitle={`Период: ${period.from} — ${period.to}`} getEl={() => ref.current} />
      </div>

      {isLoading ? <Loading />
        : error || !data ? <Empty text="Не удалось загрузить обзор" />
        : data.operational.shifts_count === 0 ? <Empty />
        : (
          <div ref={ref} className="space-y-5">
            {/* Полоса выводов: KPI ниже отвечают «сколько заработали», а это —
                «что в данных требует решения». Клик уводит на экран, где цифра
                разбирается подробно. */}
            <FuelInsightsBar companyId={companyId} dateFrom={period.from} dateTo={period.to} />
            {alerts.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {alerts.map((a, i) => (
                  <span key={i} className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${a.level === 'info'
                    ? 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300'
                    : 'border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300'}`}>
                    {a.level === 'info' ? <Info className="h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="h-3.5 w-3.5 shrink-0" />}{a.message}
                  </span>
                ))}
              </div>
            )}

            {/* счётчики размерностей */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <CountCard label="АЗС (с продажами)" value={nf0.format(data.operational.stations_count ?? stations.length)} hint="в периоде" />
              <CountCard label="Смен закрыто" value={nf0.format(data.operational.shifts_count)} hint={missingSales > 0 ? `из них ${nf0.format(missingSales)} без продаж в источнике` : 'сменных отчётов'} />
              <CountCard label="Видов топлива" value={nf0.format(data.operational.fuel_types_count ?? data.volume.by_fuel.length)} hint="в реализации" />
              <CountCard label="Дней в периоде" value={nf0.format(data.period.days)} hint="календарных" />
              <CountCard label="ТТН принято" value={nf0.format(data.receipts.ttn_count)} hint="сливов топлива" />
            </div>

            {/* ключевые KPI с Δ% + спарклайн. База сравнения — в подсказке
                самого Δ (см. KpiCard). */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {kpis.map((k) => <KpiCard key={k.label} k={k} baseline={baseline} />)}
            </div>

            {/* средние показатели АЗС (по реализациям) */}
            {data.averages && data.averages.tx_count > 0 && (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <CountCard label="Средний чек" value={`${fmtMoney(data.averages.avg_check)} ₽`} hint="на реализацию" />
                <CountCard label="Средняя заправка" value={`${nf1.format(data.averages.avg_fill_liters)} л`} hint="объём на реализацию" />
                <CountCard label="Операций в день" value={nf1.format(data.averages.ops_per_day)} hint="в среднем" />
                <CountCard label="Реализаций всего" value={nf0.format(data.averages.tx_count)} hint="за период" />
              </div>
            )}

            {/* реализация по дням + маркеры подключения АЗС */}
            <DailyRevenueBar daily={data.charts.daily} onboarding={data.onboarding ?? []} />

            {/* средняя цена — полная ширина */}
            <AvgPriceLine daily={data.charts.daily} bigValue={data.financial.avg_price ?? (data.volume.total ? data.financial.total_revenue / data.volume.total : 0)} />

            {/* структура продаж: виды топлива + способы оплаты — ПОЛНЫЙ разрез из STS */}
            <SectionTitle hint="полный разрез из отчётов STS — учтены все виды оплаты">Структура продаж</SectionTitle>
            <div className="grid gap-3 md:grid-cols-2">
              <BreakdownTable title="Виды топлива" nameCol="Топливо" icon={<Fuel className="h-3.5 w-3.5" />}
                rows={(data.fuel_types_raw ?? []).map((f) => ({ name: f.name, revenue: f.revenue, volume: f.volume, count: f.count }))} />
              <BreakdownTable title="Способы оплаты" nameCol="Вид" icon={<CreditCard className="h-3.5 w-3.5" />}
                rows={data.payment_methods ?? []} />
            </div>
            <div className="text-[11px] text-muted-foreground">
              Разрез — по пооперационным транзакциям (реализациям): каждый вид оплаты как есть (все методы) + счётчик реализаций. При отсутствии транзакций за период — фолбэк на сырые отчёты смен (без счётчика).
            </div>

            {/* профиль активности (по транзакциям) */}
            {data.activity && data.activity.hourly.some((h) => h.count > 0) && (
              <>
                <SectionTitle hint="по пооперационным реализациям">Профиль активности</SectionTitle>
                <div className="grid gap-3 lg:grid-cols-2">
                  <HourlyActivity a={data.activity} />
                  <WeekdayActivity a={data.activity} />
                </div>
              </>
            )}

            {/* топ карт */}
            {data.top_cards && data.top_cards.length > 0 && (
              <>
                <SectionTitle hint="корпоратив / лояльность (без наличных)">Топ карт по обороту</SectionTitle>
                <TopCards cards={data.top_cards} />
              </>
            )}

            {/* сливы ТТН */}
            <SectionTitle hint="приёмка топлива за период">Поступления топлива (сливы ТТН)</SectionTitle>
            <ReceiptsBlock receipts={data.receipts} />

            {/* станции топ/дно */}
            <SectionTitle hint="по выручке за период">Станции: лидеры и аутсайдеры</SectionTitle>
            <div className="grid gap-3 md:grid-cols-2">
              <StationList title="Топ по выручке" rows={topStations} empty="Недостаточно данных" />
              <StationList title="Аутсайдеры по выручке" rows={bottomStations} empty="Недостаточно данных" />
            </div>

            {/* FIFO-маржа + готовность к 1С */}
            <SectionTitle hint="управленческая себестоимость и подготовка к 1С"><span className="inline-flex items-center gap-1.5"><TrendingUp className="h-3.5 w-3.5" />Маржинальность и обработка</span></SectionTitle>
            <MarginMini companyId={companyId} from={period.from} to={period.to} />
            <ReadinessStrip companyId={companyId} from={period.from} to={period.to} />
          </div>
        )}
    </div>
  )
}
