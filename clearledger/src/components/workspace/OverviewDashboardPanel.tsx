/**
 * Executive-дашборд «Обзор» сети ЭЗС (energy, РусГидро) — стратегическая витрина
 * поверх операционных пунктов (Сессии / Тарифы / Корпоратив).
 *
 * Одна прокручиваемая premium-витрина: KPI-плитки с Δ% к прошлому периоду +
 * спарклайны, радиальные гейджи-кольца, тренд-area с градиентом и оверлеем,
 * донат-диаграммы долей, топ/дно станций, heatmap час×день, корп/розница и
 * ПОЛНЫЙ блок количественных показателей по всем разрезам (DimTable).
 *
 * Данные: /api/analytics/charge-sessions/overview (сводка+дельты, изолированный
 * OverviewService) + /charge-sessions?group_by=X (разрезы, готовый эндпоинт).
 */

import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
  BarChart, Bar, LineChart, Line,
} from 'recharts'
import { Loader2, AlertTriangle, Info, ArrowUpRight, ArrowDownRight, Zap } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useTabParams } from '@/hooks/useTabParams'
import { ExportButton } from './analytics/ExportButton'
import { PeriodRangePicker } from './analytics/PeriodRangePicker'
import { type Period } from './analytics/periodPresets'
import {
  getChargeSessions, getStationsLinkage, getChargeTimeseries, fmtMoney, fmtMoneyShort,
} from '@/services/analyticsService'
import {
  getChargeOverview, type OverviewKpi,
  type ShareRow, type StationRow, type Accent, type OverviewCorporate,
  type HourPoint, type OverviewWeekday,
} from '@/services/overviewService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

// Палитра серий — как в analytics/ChargeChart.tsx (приглушённая, богатая, без неона).
const SERIES = [
  'hsl(217, 91%, 60%)', 'hsl(152, 69%, 45%)', 'hsl(25, 100%, 55%)',
  'hsl(280, 65%, 65%)', 'hsl(340, 75%, 55%)', 'hsl(190, 70%, 50%)',
]
const OTHER_COLOR = 'hsl(215, 16%, 55%)'
const seriesColor = (i: number, n: number) => (i === n - 1 ? OTHER_COLOR : SERIES[i % SERIES.length])
const ACCENT_HSL: Record<Accent, string> = {
  success: 'hsl(152, 69%, 45%)', warning: 'hsl(38, 92%, 50%)',
  danger: 'hsl(0, 84%, 60%)', info: 'hsl(217, 91%, 60%)',
}

function Loading() {
  return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет сессий за период' }: { text?: string }) {
  return <div className="p-8 text-sm text-muted-foreground text-center">{text}</div>
}

// ─── форматирование значения KPI ─────────────────────────────────────
function kpiNum(fmt: string, v: number): string {
  switch (fmt) {
    case 'moneyShort': return fmtMoneyShort(v)
    case 'money': return fmtMoney(v)
    case 'int': return nf0.format(v)
    case 'kwh': return fmtMoneyShort(v)
    case 'pct': return nf1.format(v) + '%'
    case 'price': return fmtMoney(v)
    default: return String(v)
  }
}
function kpiDisplay(k: OverviewKpi): string {
  const n = kpiNum(k.fmt, k.value)
  if (k.fmt === 'pct') return n
  return k.unit ? `${n} ${k.unit}` : n
}
// Описательные подписи ключевых KPI (в стиле счётных карт, без дельт).
const KPI_HINTS: Record<string, string> = {
  revenue: 'выручка сети за период',
  sessions: 'зарядных сессий',
  energy_kwh: 'отпущено за период',
  price_per_kwh: 'средняя за период',
  success_pct: 'доля успешных сессий',
}

/** Простая плитка (label · value · hint) — счётчики сети и ключевые KPI.
 * Порядок детей label/value/hint — контракт экспорта (data-kpi). */
function CountCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div data-kpi className="rounded-xl border bg-card/50 p-3.5 shadow-sm">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums leading-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

/** Донат долей + легенда со значениями и %. */
function DonutCard({ title, rows }: { title: string; rows: ShareRow[] }) {
  const total = rows.reduce((s, r) => s + r.amount, 0)
  const data = rows.map((r) => ({ name: r.label, value: Math.max(0, r.amount) }))
  const n = rows.length
  return (
    <Card>
      <CardContent className="flex h-full flex-col pt-4">
        <div className="mb-2 shrink-0 text-xs uppercase tracking-wider text-muted-foreground">{title}</div>
        <div className="flex flex-1 items-center gap-3">
          <div className="relative shrink-0" style={{ width: 128, height: 128 }}>
            <ResponsiveContainer width={128} height={128}>
              <PieChart>
                <Pie data={data} dataKey="value" nameKey="name" innerRadius={42} outerRadius={60} paddingAngle={1.5} stroke="none" isAnimationActive={false}>
                  {data.map((_, i) => <Cell key={i} fill={seriesColor(i, n)} />)}
                </Pie>
                <Tooltip formatter={(value) => `${fmtMoney(Number(value))} ₽`} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <div className="text-sm font-semibold tabular-nums">{fmtMoneyShort(total)}</div>
              <div className="text-[9px] text-muted-foreground">₽ итого</div>
            </div>
          </div>
          <div className="min-w-0 flex-1 space-y-1 text-xs">
            {rows.map((r, i) => (
              <div key={r.label} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: seriesColor(i, n) }} />
                <span className="flex-1 truncate">{r.label}</span>
                <span className="font-mono tabular-nums text-muted-foreground">{r.share_pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── дневная ось: '2026-06-04' → '04.06' ─────────────────────────────
const dayTick = (b: string) => (b.length === 10 ? `${b.slice(8, 10)}.${b.slice(5, 7)}` : b)
const WD_FULL: Record<number, string> = { 1: 'Понедельник', 2: 'Вторник', 3: 'Среда', 4: 'Четверг', 5: 'Пятница', 6: 'Суббота', 7: 'Воскресенье' }
const chartAxis = { fontSize: 10, fill: 'hsl(var(--muted-foreground))' } as const

/** Компактный сегмент-переключатель (Все / Коннекторы / ФЛ·ЮЛ и т.п.). */
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

type RevMode = 'all' | 'connector' | 'user_type'
const REV_MODES: { v: RevMode; label: string }[] = [
  { v: 'all', label: 'Все' }, { v: 'connector', label: 'Коннекторы' }, { v: 'user_type', label: 'ФЛ · ЮЛ' },
]
const seriesLabel = (s: string) => (s === 'value' ? 'Выручка' : s)

/** Реализация (выручка) по дням за период — stacked-бары; разрез: все/коннекторы/ФЛ·ЮЛ + легенда.
 *  По умолчанию — «Все» (одна серия, синяя заливка). */
function DailyRevenueBar({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [mode, setMode] = useState<RevMode>('all')
  const { data, isLoading } = useQuery({
    queryKey: ['overview-daily-rev', companyId, dateFrom, dateTo, mode],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'day', metric: 'amount',
      ...(mode === 'all' ? {} : { seriesBy: mode }), topN: 6 }),
  })
  const series = data?.series ?? []
  // Одиночная серия («Все») — синяя (SERIES[0]); разбивка — палитра серий.
  const barColor = (i: number) => (series.length === 1 ? SERIES[0] : seriesColor(i, series.length))
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <span className="text-emerald-400">₽</span>Реализация по дням{data ? ` (${data.data.length} дн.)` : ''}
          </div>
          <Segmented value={mode} onChange={setMode} options={REV_MODES} />
        </div>
        {/* легенда-аннотация серий */}
        {series.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {series.map((s, i) => (
              <span key={s} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: barColor(i) }} />
                <span className="text-muted-foreground">{seriesLabel(s)}</span>
              </span>
            ))}
          </div>
        )}
        {isLoading ? <Loading /> : !data || data.data.length === 0 ? <Empty /> : (
          <div data-chart>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data.data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="bucket" tick={chartAxis} tickFormatter={dayTick} minTickGap={16} stroke="hsl(var(--muted-foreground))" />
                <YAxis tick={chartAxis} tickFormatter={(v: number) => fmtMoneyShort(v)} width={56} stroke="hsl(var(--muted-foreground))" />
                <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} labelFormatter={(label) => dayTick(String(label))} formatter={(value, name) => [`${fmtMoney(Number(value))} ₽`, seriesLabel(String(name))]} />
                {series.map((s, i) => (
                  <Bar key={s} dataKey={s} stackId="rev" fill={barColor(i)} radius={i === series.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** Однострочный тултип среднего чека: «ДД.ММ: X ₽» (без служебной линии тренда). */
function AvgCheckTip({ active, payload, label }: {
  active?: boolean; payload?: Array<{ dataKey?: string | number; value?: number | null }>; label?: string | number
}) {
  if (!active || !payload?.length) return null
  const v = payload.find((p) => p.dataKey === 'value')?.value
  if (v == null) return null
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md whitespace-nowrap">
      <span className="text-muted-foreground">{dayTick(String(label))}: </span>
      <span className="font-mono font-medium">{fmtMoney(Number(v))} ₽</span>
    </div>
  )
}

/** Средний чек ФЛ (частные) по дням + трендовая линия (линейная регрессия) + бейдж роста. */
function AvgCheckLine({ companyId, dateFrom, dateTo, bigValue }: { companyId: string; dateFrom: string; dateTo: string; bigValue: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['overview-avgcheck-fl', companyId, dateFrom, dateTo],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'day', metric: 'avg_check', dim: 'user_type', dimVal: 'ФЛ' }),
  })
  const { rows, growth } = useMemo(() => {
    const pts = (data?.data ?? []).map((d, i) => ({ i, v: typeof d.value === 'number' ? d.value : null }))
    const valid = pts.filter((p) => p.v != null) as { i: number; v: number }[]
    const n = valid.length
    if (n < 2) return { rows: (data?.data ?? []).map((d) => ({ bucket: String(d.bucket), value: d.value as number | null, trend: null as number | null })), growth: null as number | null }
    const sx = valid.reduce((s, p) => s + p.i, 0), sy = valid.reduce((s, p) => s + p.v, 0)
    const sxx = valid.reduce((s, p) => s + p.i * p.i, 0), sxy = valid.reduce((s, p) => s + p.i * p.v, 0)
    const b = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1)
    const a = (sy - b * sx) / n
    const rows = (data?.data ?? []).map((d, i) => ({ bucket: String(d.bucket), value: d.value as number | null, trend: a + b * i }))
    const y0 = a, y1 = a + b * (pts.length - 1)
    return { rows, growth: y0 ? ((y1 - y0) / y0) * 100 : null }
  }, [data])
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium"><span className="text-blue-400">₽</span>Средний чек (частные)</div>
            <div className="text-[11px] text-muted-foreground">без корп. карт, талонов, купонов</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{fmtMoney(bigValue)} ₽</div>
          </div>
          {growth != null && (
            <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${growth >= 0 ? 'border-blue-500/30 bg-blue-500/10 text-blue-300' : 'border-red-500/30 bg-red-500/10 text-red-300'}`}>
              {growth >= 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
              {growth >= 0 ? 'Рост' : 'Спад'} {growth >= 0 ? '+' : ''}{nf1.format(growth)}%
            </span>
          )}
        </div>
        {isLoading ? <Loading /> : rows.length === 0 ? <Empty /> : (
          <div data-chart>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={rows} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="bucket" tick={chartAxis} tickFormatter={dayTick} minTickGap={16} stroke="hsl(var(--muted-foreground))" />
                <YAxis tick={chartAxis} tickFormatter={(v: number) => fmtMoneyShort(v)} width={56} stroke="hsl(var(--muted-foreground))" />
                <Tooltip content={<AvgCheckTip />} />
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

/** Суточная активность по часам (0–23) — число сессий. */
function HourlyBar({ hourly }: { hourly: HourPoint[] }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium"><Zap className="h-4 w-4 text-blue-400" />Суточная активность по часам</div>
        <div data-chart>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={hourly} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
              <XAxis dataKey="label" tick={chartAxis} interval={1} stroke="hsl(var(--muted-foreground))" />
              <YAxis tick={chartAxis} tickFormatter={(v: number) => nf0.format(v)} width={48} stroke="hsl(var(--muted-foreground))" />
              <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} formatter={(value) => [`${nf0.format(Number(value))} сессий`, 'Сессий']} />
              <Bar dataKey="sessions" fill={SERIES[0]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

/** Паттерн по дням недели — выручка; лучший день зелёный, худший красный. */
function WeekdayBar({ weekday }: { weekday: OverviewWeekday }) {
  const bestName = weekday.best ? WD_FULL[weekday.best] : '—'
  const worstName = weekday.worst ? WD_FULL[weekday.worst] : '—'
  const colorOf = (w: number) => (w === weekday.best ? ACCENT_HSL.success : w === weekday.worst ? ACCENT_HSL.danger : SERIES[0])
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2">
          <div className="text-sm font-medium">Паттерн по дням недели</div>
          <div className="text-[11px] text-muted-foreground">Лучший: {bestName}, Худший: {worstName}</div>
        </div>
        <div data-chart>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={weekday.days} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
              <XAxis dataKey="label" tick={chartAxis} stroke="hsl(var(--muted-foreground))" />
              <YAxis tick={chartAxis} tickFormatter={(v: number) => fmtMoneyShort(v)} width={56} stroke="hsl(var(--muted-foreground))" />
              <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} formatter={(value) => `${fmtMoney(Number(value))} ₽`} />
              <Bar dataKey="amount" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                {weekday.days.map((d) => <Cell key={d.weekday} fill={colorOf(d.weekday)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── топ/дно станций по загрузке ─────────────────────────────────────
function StationList({ title, rows, empty }: { title: string; rows: StationRow[]; empty: string }) {
  const max = Math.max(...rows.map((r) => r.utilization_pct), 0.01)
  return (
    <Card>
      <CardContent className="p-0">
        <div className="border-b bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground">{title}</div>
        {rows.length === 0 ? <div className="p-4 text-xs text-muted-foreground">{empty}</div> : (
          <table className="w-full text-xs" data-export-name={title}
            data-export-rows={JSON.stringify({
              columns: ['Станция', 'Сессий', 'Выручка, ₽', 'Загрузка, %', 'Успех, %'],
              rows: rows.map((r) => [r.label, r.sessions, r.amount, r.utilization_pct, r.success_pct]),
            })}>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="max-w-[220px] truncate p-2 font-medium">{r.label}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.sessions)}</td>
                  <td className="p-2 text-right font-mono">{fmtMoneyShort(r.amount)} ₽</td>
                  <td className="p-2 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <div className="h-1.5 w-14 overflow-hidden rounded bg-muted">
                        <div className="h-full bg-primary/70" style={{ width: `${Math.min(100, (r.utilization_pct / max) * 100)}%` }} />
                      </div>
                      <span className="w-10 font-mono tabular-nums">{r.utilization_pct.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums">{r.success_pct.toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}


// ─── период пункта (свой период / период раздела) ────────────────────
function PeriodOverride({ override, sectionFrom, sectionTo, onChange }: {
  override: Period | null; sectionFrom: string; sectionTo: string; onChange: (p: Period | null) => void
}) {
  if (override) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-wider text-amber-400/70">Свой период</span>
        <PeriodRangePicker period={override} onChange={onChange} />
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => onChange(null)}>← период раздела</Button>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted-foreground">Период раздела: <span className="font-mono">{sectionFrom} — {sectionTo}</span></span>
      <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => onChange({ from: sectionFrom, to: sectionTo })}>Свой период</Button>
    </div>
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
export function OverviewDashboardPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [ov, setOv] = useTabParams('cs_dashboard', { override: null as Period | null })
  const period = ov.override ?? { from: dateFrom, to: dateTo }

  const { data, isLoading, error } = useQuery({
    queryKey: ['charge-overview', companyId, period.from, period.to],
    queryFn: () => getChargeOverview({ companyId, dateFrom: period.from, dateTo: period.to }),
  })
  // «Всего ЭЗС в сети» = объекты справочника станций (Нормализация → service_locations),
  // а не выведенное из сессий. Регионы/коннекторы за период — из разрезов.
  const linkage = useQuery({ queryKey: ['stations-linkage', companyId], queryFn: () => getStationsLinkage(companyId) })
  const connQ = useQuery({
    queryKey: ['overview-dim', 'connector', companyId, period.from, period.to],
    queryFn: () => getChargeSessions({ companyId, dateFrom: period.from, dateTo: period.to, groupBy: 'connector' }),
  })
  const regQ = useQuery({
    queryKey: ['overview-dim', 'region', companyId, period.from, period.to],
    queryFn: () => getChargeSessions({ companyId, dateFrom: period.from, dateTo: period.to, groupBy: 'region' }),
  })

  return (
    <div className="p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3" data-export-ignore>
        <div className="space-y-1.5">
          <h2 className="flex items-center gap-2 text-base font-semibold"><Zap className="h-4 w-4 text-blue-400" />Обзор сети ЭЗС</h2>
          <PeriodOverride override={ov.override} sectionFrom={dateFrom} sectionTo={dateTo} onChange={(o) => setOv({ override: o })} />
          {data && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
              <span>Активных ЭЗС: <b className="text-foreground">{nf0.format(data.meta.active_stations)}</b></span>
              <span>Портов: <b className="text-foreground">{nf0.format(data.meta.ports)}</b></span>
              <span>Сессий: <b className="text-foreground">{nf0.format(data.meta.sessions)}</b></span>
              <span className="text-muted-foreground/70">{data.has_baseline
                ? `сравнение с ${data.prev_period.from} — ${data.prev_period.to}`
                : 'нет данных за прошлый период — Δ не рассчитывается'}</span>
            </div>
          )}
        </div>
        <ExportButton title="Обзор сети ЭЗС" subtitle={`Период: ${period.from} — ${period.to}`} getEl={() => ref.current} />
      </div>

      {isLoading ? <Loading />
        : error || !data ? <Empty text="Не удалось загрузить обзор" />
        : data.meta.sessions === 0 ? <Empty />
        : (
          <div ref={ref} className="space-y-5">
            {/* алерты */}
            {data.alerts.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {data.alerts.map((a, i) => (
                  <span key={i} className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${a.level === 'info'
                    ? 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300'
                    : 'border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300'}`}>
                    {a.level === 'info' ? <Info className="h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="h-3.5 w-3.5 shrink-0" />}{a.message}
                  </span>
                ))}
              </div>
            )}

            {/* статистика по объектам сети */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <CountCard label="ЭЗС (всего в сети)" value={nf0.format(linkage.data?.objects || data.meta.active_stations)} hint="станций в справочнике" />
              <CountCard label="Активных ЭЗС" value={nf0.format(data.meta.active_stations)} hint="с сессиями за период" />
              <CountCard label="Регионов" value={nf0.format(regQ.data?.lines.length ?? 0)} hint="за период" />
              <CountCard label="Коннекторов (типов)" value={nf0.format(connQ.data?.lines.length ?? 0)} hint="за период" />
              <CountCard label="Коннекторов в сети" value={nf0.format(data.meta.ports)} hint="физических портов" />
            </div>

            {/* ключевые KPI (тот же чистый дизайн) — под статистикой */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {(['revenue', 'sessions', 'energy_kwh', 'price_per_kwh', 'success_pct'] as const).map((key) => {
                const k = data.kpis.find((x) => x.key === key)
                return k ? <CountCard key={key} label={k.label} value={kpiDisplay(k)} hint={KPI_HINTS[key]} /> : null
              })}
            </div>

            {/* реализация по дням */}
            <DailyRevenueBar companyId={companyId} dateFrom={period.from} dateTo={period.to} />

            {/* одна строка: средний чек (3/4) + два доната долей стопкой (1/4), выровнены по высоте */}
            <div className="grid items-stretch gap-3 lg:grid-cols-4">
              <div className="lg:col-span-3 [&>div]:h-full">
                <AvgCheckLine companyId={companyId} dateFrom={period.from} dateTo={period.to}
                  bigValue={(() => { const fl = data.shares.user_type.find((r) => r.label === 'ФЛ'); return fl && fl.sessions ? fl.amount / fl.sessions : 0 })()} />
              </div>
              <div className="flex flex-col gap-3 lg:col-span-1">
                <div className="min-h-0 flex-1 [&>div]:h-full"><DonutCard title="По коннекторам" rows={data.shares.connector} /></div>
                <div className="min-h-0 flex-1 [&>div]:h-full"><DonutCard title="По типу клиента" rows={data.shares.user_type} /></div>
              </div>
            </div>

            {/* профиль активности: часы + дни недели (в одну строку) */}
            <SectionTitle hint="за выбранный период">Профиль активности</SectionTitle>
            <div className="grid gap-3 lg:grid-cols-2">
              <HourlyBar hourly={data.hourly} />
              <WeekdayBar weekday={data.weekday} />
            </div>

            {/* станции топ/дно */}
            <SectionTitle hint={`порт-нормировано · ≥ ${data.stations.min_sessions} сессий`}>Станции: лидеры и аутсайдеры по загрузке</SectionTitle>
            <div className="grid gap-3 md:grid-cols-2">
              <StationList title="Топ по загрузке" rows={data.stations.top} empty="Недостаточно данных" />
              <StationList title="Аутсайдеры по загрузке" rows={data.stations.bottom} empty="Недостаточно данных" />
            </div>

            {/* корп vs розница mini */}
            <CorpMini c={data.corporate} />
          </div>
        )}
    </div>
  )
}

// ─── корп/розница mini ───────────────────────────────────────────────
function CorpMini({ c }: { c: OverviewCorporate }) {
  const stat = (label: string, value: string, accent?: string) => (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${accent ?? ''}`}>{value}</div>
    </div>
  )
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3 pt-4">
        {stat('Корп. выручка (ЮЛ)', fmtMoneyShort(c.corp_revenue) + ' ₽')}
        {stat('Розница-эквивалент', fmtMoneyShort(c.retail_revenue) + ' ₽')}
        {stat('Скидка ЮЛ', `${c.discount_pct > 0 ? '+' : ''}${nf1.format(c.discount_pct)}%`, c.discount < 0 ? 'text-amber-400' : 'text-emerald-400')}
        {stat('Активных ЮЛ', nf0.format(c.active_clients) + ` из ${nf0.format(c.clients)}`)}
        {stat('Доля ЮЛ в выручке', nf1.format(c.corp_share_pct) + '%')}
        <span className="ml-auto text-[11px] text-muted-foreground">Детали — в пункте «Корпоратив»</span>
      </CardContent>
    </Card>
  )
}

