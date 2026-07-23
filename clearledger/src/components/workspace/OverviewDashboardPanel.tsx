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
import { ExportButton } from './analytics/ExportButton'
import { CHART_SERIES as SERIES, seriesColor } from './analytics/palette'
import { MetricHint, HINTS } from './analytics/MetricHint'
import { TzToggle, type Tz } from './analytics/TzToggle'
import {
  getChargeSessions, getStationsLinkage, getChargeTimeseries, fmtMoney, fmtMoneyShort,
} from '@/services/analyticsService'
import {
  getChargeOverview, getSilentStations, getOwnersBreakdown, getOwnerStations,
  getSpeedBreakdown, getSpeedStations,
  type OwnerBreakdownRow, type OwnerStationsResponse, type OverviewKpi,
  type ShareRow, type StationRow, type Accent, type OverviewCorporate,
  type HourPoint, type OverviewWeekday, type OverviewNetwork,
} from '@/services/overviewService'
import { formatPeriod } from '@/lib/formatDate'
import { useFilters } from '@/contexts/FilterContext'

/** Сужение по сети из контура (регион/станции) для запросов обзора. */
type ScopeArg = { stations?: string[]; regions?: string[]; key: string }
function useScope(): ScopeArg {
  const { stationCodes, regionIds } = useFilters()
  return {
    stations: stationCodes.length ? stationCodes.map(String) : undefined,
    regions: regionIds.length ? regionIds : undefined,
    key: `${stationCodes.join(',')}|${regionIds.join(',')}`,
  }
}

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

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
  sessions: 'сессий CPO, включая попытки',
  energy_kwh: 'отпущено за период',
  price_per_kwh: 'средняя за период',
  // Визит = приезд клиента: смежные попытки на одной станции склеены. Успех
  // считается по нему, поэтому визит стоит рядом с сессией — иначе доля
  // «Зарядились» не с чем соотнести.
  visits: 'приездов клиентов',
  visit_success_pct: 'доля клиентов, зарядившихся',
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

/** Карточка простаивающих ЭЗС + раскрытие списка.
 *
 * Счётчик «активных ЭЗС» говорит, сколько станций работало, и умалчивает,
 * сколько простаивало. На сети РусГидро это четверть парка — самая крупная
 * потеря, которую обзор до сих пор не показывал. Клик даёт список: простой —
 * это не справка, а перечень работ. */
/** Разрез парка по признаку станции (владелец, скорость…). Карточки-классы с
 *  метриками простоя/надёжности; клик по классу — список его станций. Обобщён,
 *  чтобы «Парк по владельцу» и «Парк по скорости» не дублировали разметку. */
type BreakdownConfig = {
  title: string; hint: string; queryKey: string; stationsHint: string
  dot: Record<string, string>; hover: Record<string, string>
  fetchRows: (a: { companyId: string; dateFrom: string; dateTo: string; stations?: string[]; regions?: string[] }) => Promise<OwnerBreakdownRow[]>
  fetchStations: (a: { companyId: string; dateFrom: string; dateTo: string; cls: string }) => Promise<OwnerStationsResponse>
}

function BreakdownCard({ companyId, period, scope, cfg }: {
  companyId: string; period: { from: string; to: string }; scope: ScopeArg; cfg: BreakdownConfig
}) {
  const [open, setOpen] = useState<OwnerBreakdownRow | null>(null)
  const { data } = useQuery({
    queryKey: [cfg.queryKey, companyId, period.from, period.to, scope.key],
    queryFn: () => cfg.fetchRows({ companyId, dateFrom: period.from, dateTo: period.to,
      stations: scope.stations, regions: scope.regions }),
  })
  const rows = (data ?? []).filter((o) => o.stations > 0 || o.sessions > 0)
  if (rows.length < 2) return null   // один класс — сравнивать не с чем

  const dotFb = 'bg-zinc-500'
  const hoverFb = 'border-border hover:border-zinc-400/50 hover:bg-muted/40'
  const succCls = (v: number) => (v >= 85 ? 'text-emerald-600 dark:text-emerald-400'
    : v >= 70 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')
  const silentCls = (v: number) => (v <= 15 ? 'text-emerald-600 dark:text-emerald-400'
    : v <= 35 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          {cfg.title}
          <MetricHint text={cfg.hint} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((o) => (
            <button key={o.cls} type="button" onClick={() => setOpen(o)}
              title={cfg.stationsHint}
              className={`rounded-xl border ${cfg.hover[o.cls] ?? hoverFb} bg-card/50 p-3.5 text-left shadow-sm transition-colors`}>
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <span className={`h-2 w-2 rounded-full ${cfg.dot[o.cls] ?? dotFb}`} />{o.label}
                <ArrowUpRight className="ml-auto h-3.5 w-3.5 text-muted-foreground/60" />
              </div>
              <div className="mt-1.5 flex items-baseline gap-1.5">
                <span className="text-2xl font-semibold tabular-nums leading-none">{nf0.format(o.stations)}</span>
                <span className="text-xs text-muted-foreground">станций · работают {nf0.format(o.working)}</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                <Stat label="Простой" value={`${nf0.format(o.silent)} (${o.silent_pct.toFixed(0)}%)`} cls={silentCls(o.silent_pct)} />
                <Stat label="Активны" value={nf0.format(o.active)} />
                <Stat label="Надёжность" value={`${o.success_pct.toFixed(0)}%`} cls={succCls(o.success_pct)} />
                <Stat label="Сессии" value={nf0.format(o.sessions)} />
              </div>
            </button>
          ))}
        </div>
      </CardContent>
      {open && (
        <BreakdownStationsDialog companyId={companyId} period={period} row={open}
          queryKey={cfg.queryKey} fetchStations={cfg.fetchStations} onClose={() => setOpen(null)} />
      )}
    </Card>
  )
}

/** Список станций одного класса разреза — по клику с карточки. Простаивающие
 *  (0 сессий за период) идут вперёд: список читают, чтобы найти, с чем разбираться. */
function BreakdownStationsDialog({ companyId, period, row, queryKey, fetchStations, onClose }: {
  companyId: string; period: { from: string; to: string }; row: OwnerBreakdownRow
  queryKey: string
  fetchStations: (a: { companyId: string; dateFrom: string; dateTo: string; cls: string }) => Promise<OwnerStationsResponse>
  onClose: () => void
}) {
  const q = useQuery({
    queryKey: [`${queryKey}-stations`, companyId, period.from, period.to, row.cls],
    queryFn: () => fetchStations({ companyId, dateFrom: period.from, dateTo: period.to, cls: row.cls }),
  })
  const succCls = (v: number | null) => (v == null ? 'text-muted-foreground'
    : v >= 85 ? 'text-emerald-600 dark:text-emerald-400'
    : v >= 70 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')
  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="max-h-[85dvh] w-full max-w-4xl overflow-hidden rounded-xl border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-baseline justify-between gap-3 border-b px-4 py-3">
          <div>
            <div className="text-sm font-semibold">{row.label} — {nf0.format(row.stations)} станций</div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              активны {nf0.format(q.data?.active ?? row.active)} · простой {nf0.format(q.data?.silent ?? row.silent)}
              {' · '}за период {formatPeriod(period.from, period.to)}
            </div>
          </div>
          <button type="button" onClick={onClose}
            className="shrink-0 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted">Закрыть</button>
        </div>
        <div className="max-h-[70dvh] overflow-auto">
          {q.isLoading ? <Loading /> : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b text-muted-foreground">
                  <th className="p-2 text-left font-medium">Станция</th>
                  <th className="p-2 text-left font-medium">Город</th>
                  <th className="p-2 text-left font-medium">Статус</th>
                  <th className="p-2 text-right font-medium">Сессии</th>
                  <th className="p-2 text-right font-medium">Энергия, кВтч</th>
                  <th className="p-2 text-right font-medium">Надёжность</th>
                  <th className="p-2 text-left font-medium">Последняя сессия</th>
                </tr>
              </thead>
              <tbody>
                {(q.data?.stations ?? []).map((s) => (
                  <tr key={s.id} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-medium">{s.name} <span className="text-muted-foreground">({s.code})</span></td>
                    <td className="p-2 text-muted-foreground">{s.city ?? '—'}</td>
                    <td className="p-2 text-muted-foreground">{s.operational_status ?? '—'}</td>
                    <td className={`p-2 text-right font-mono tabular-nums ${s.sessions === 0 ? 'text-amber-600 dark:text-amber-400' : ''}`}>
                      {nf0.format(s.sessions)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{nf0.format(s.energy_kwh)}</td>
                    <td className={`p-2 text-right font-mono tabular-nums ${succCls(s.success_pct)}`}>
                      {s.success_pct == null ? '—' : `${s.success_pct.toFixed(0)}%`}
                    </td>
                    <td className="p-2 font-mono text-muted-foreground">
                      {s.last_at ? s.last_at.slice(0, 10) : <span className="text-amber-600 dark:text-amber-400">никогда</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`font-mono tabular-nums ${cls ?? ''}`}>{value}</div>
    </div>
  )
}

// Разрез парка по владельцу — свои (РусГидро) vs партнёрские (СНК).
const OWNERS_CFG: BreakdownConfig = {
  title: 'Парк по владельцу',
  hint: 'Собственные — станции РусГидро (включая бренд «Доступная энергия»). Партнёрские — станции СНК. Простой и надёжность считаются отдельно: партнёрские отрабатывают иначе, и в общей цифре сети это тонет. Клик по владельцу — список его станций.',
  queryKey: 'owners-breakdown', stationsHint: 'Показать станции этого владельца',
  dot: { own: 'bg-blue-500', partner: 'bg-violet-500', unknown: 'bg-zinc-500' },
  hover: {
    own: 'border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5',
    partner: 'border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5',
    unknown: 'border-border hover:border-zinc-400/50 hover:bg-muted/40',
  },
  fetchRows: (a) => getOwnersBreakdown(a).then((r) => r.owners),
  fetchStations: getOwnerStations,
}

// Разрез парка по скорости — медленные (AC) vs быстрые (DC).
const SPEED_CFG: BreakdownConfig = {
  title: 'Парк по скорости',
  hint: 'Медленные — AC-станции (до 50 кВт), быстрые — DC (от 50 кВт). Скорость берётся из паспорта (speed_class), где пусто — по номинальной мощности. Простой и надёжность отдельно: у быстрых DC простой стоит дороже, а износ иной, чем у AC. Клик — список станций.',
  queryKey: 'speed-breakdown', stationsHint: 'Показать станции этой скорости',
  dot: { fast: 'bg-amber-500', slow: 'bg-cyan-500', unknown: 'bg-zinc-500' },
  hover: {
    fast: 'border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5',
    slow: 'border-cyan-500/30 hover:border-cyan-500/60 hover:bg-cyan-500/5',
    unknown: 'border-border hover:border-zinc-400/50 hover:bg-muted/40',
  },
  fetchRows: (a) => getSpeedBreakdown(a).then((r) => r.speed),
  fetchStations: getSpeedStations,
}

function SilentCard({ companyId, period, silent }: {
  companyId: string; period: { from: string; to: string }
  silent: OverviewNetwork['silent']
}) {
  const [open, setOpen] = useState(false)
  const sc = useScope()
  const q = useQuery({
    queryKey: ['silent-stations', companyId, period.from, period.to, sc.key],
    queryFn: () => getSilentStations({ companyId, dateFrom: period.from, dateTo: period.to, stations: sc.stations, regions: sc.regions }),
    enabled: open,
  })
  if (!silent.silent) {
    return <CountCard label="Молчат ЭЗС" value="0" hint="весь парк работал" />
  }
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        className="rounded-xl border border-amber-400/40 bg-card/50 p-3.5 text-left shadow-sm transition-colors hover:bg-amber-400/5"
        title="Показать станции без сессий за период">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Молчат ЭЗС</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums leading-tight text-amber-600 dark:text-amber-400">
          {nf0.format(silent.silent)}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {silent.silent_pct.toFixed(0)}% парка · без сессий
        </div>
      </button>

      {open && (
        <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
          onClick={() => setOpen(false)}>
          <div className="max-h-[85dvh] w-full max-w-3xl overflow-hidden rounded-xl border bg-card shadow-xl"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-baseline justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="text-sm font-semibold">Молчащие ЭЗС — {nf0.format(silent.silent)} из {nf0.format(silent.total)}</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {silent.never_worked > 0 && `${silent.never_worked} не работали никогда (вопрос запуска)`}
                  {silent.never_worked > 0 && silent.went_quiet > 0 && ' · '}
                  {silent.went_quiet > 0 && `${silent.went_quiet} замолчали (поломка или демонтаж)`}
                </div>
              </div>
              <button type="button" onClick={() => setOpen(false)}
                className="shrink-0 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted">Закрыть</button>
            </div>
            <div className="max-h-[70dvh] overflow-auto">
              {q.isLoading ? <Loading /> : (
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b text-muted-foreground">
                      <th className="p-2 text-left font-medium">Станция</th>
                      <th className="p-2 text-left font-medium">Город</th>
                      <th className="p-2 text-left font-medium">Статус</th>
                      <th className="p-2 text-left font-medium">Последняя сессия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(q.data?.stations ?? []).map((s) => (
                      <tr key={s.id} className="border-b border-border/30 hover:bg-muted/30">
                        <td className="p-2 font-medium">{s.name} <span className="text-muted-foreground">({s.code})</span></td>
                        <td className="p-2 text-muted-foreground">{s.city ?? '—'}</td>
                        <td className="p-2 text-muted-foreground">{s.operational_status ?? '—'}</td>
                        <td className="p-2 font-mono text-muted-foreground">
                          {s.last_at ? s.last_at.slice(0, 10) : <span className="text-amber-600 dark:text-amber-400">никогда</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/** Состояние сети: концентрация выручки, ядро клиентов, регионы, деньги в пути.
 * Отвечает на вопрос «что с активом», которого в KPI выручки нет. */
function NetworkHealth({ net }: { net: OverviewNetwork }) {
  const maxQ = Math.max(...net.concentration.map((c) => c.revenue), 1)
  const seg = net.segments
  const recon = net.energy_recon
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      {/* 1. Концентрация: средняя загрузка по сети смешивает станции с выручкой
             188 тыс. и 247 ₽ — полюса видны только в разбивке. */}
      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
            Где сеть зарабатывает<MetricHint text={HINTS.concentration} />
          </div>
          <div className="mt-1 mb-3 text-[11px] text-muted-foreground">станции по выручке, пятая часть парка в группе</div>
          <div className="space-y-1.5">
            {net.concentration.map((c) => (
              <div key={c.bucket} className="flex items-center gap-2 text-xs">
                <span className="w-20 shrink-0 text-muted-foreground">{c.label}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-muted">
                  <div className={`h-full ${c.bucket === 1 ? 'bg-emerald-500/70' : c.bucket >= 4 ? 'bg-red-500/60' : 'bg-primary/60'}`}
                    style={{ width: `${Math.max(1, (c.revenue / maxQ) * 100)}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right font-mono tabular-nums">{c.share_pct}%</span>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[11px] text-muted-foreground">
            Нижние {net.concentration.at(-1)?.stations ?? 0} станций дали{' '}
            {fmtMoney(net.concentration.at(-1)?.avg_per_station ?? 0)} ₽ каждая за период.
          </div>
        </CardContent>
      </Card>

      {/* 2. Ядро клиентов: приоритет «удерживать или привлекать». */}
      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Кто приносит выручку</div>
          <div className="mt-1 mb-3 text-[11px] text-muted-foreground">розница по числу визитов за период</div>
          <div className="space-y-1.5">
            {seg.tiers.map((t) => (
              <div key={t.tier} className="flex items-center gap-2 text-xs">
                <span className="w-28 shrink-0 truncate text-muted-foreground" title={t.label}>{t.label}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-muted">
                  <div className={`h-full ${t.tier === 5 ? 'bg-emerald-500/70' : t.tier === 1 ? 'bg-muted-foreground/40' : 'bg-primary/60'}`}
                    style={{ width: `${Math.max(1, t.rev_share)}%` }} />
                </div>
                <span className="w-11 shrink-0 text-right font-mono tabular-nums">{t.rev_share}%</span>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[11px] text-muted-foreground">
            Ядро — {nf0.format(seg.core_clients)} человек ({(seg.core_clients / (seg.clients || 1) * 100).toFixed(1)}% базы)
            даёт {seg.core_rev_share}% выручки. Разовых {nf0.format(seg.once_clients)} — {seg.once_rev_share}%.
          </div>
        </CardContent>
      </Card>

      {/* 3. Деньги между отпуском и счётом + прогноз темпа. */}
      <Card>
        <CardContent className="pt-4">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Деньги в пути</div>
          <div className="mt-1 mb-3 text-[11px] text-muted-foreground">отпущено, но ещё не получено</div>
          <div className="space-y-3">
            <div>
              <div className="text-lg font-semibold tabular-nums text-amber-600 dark:text-amber-400">
                {fmtMoney(net.receivable.amount)} ₽
              </div>
              <div className="text-[11px] text-muted-foreground">
                дебиторка ЮЛ · {nf0.format(net.receivable.sessions)} сессий · {nf0.format(net.receivable.kwh)} кВтч
              </div>
            </div>
            {net.receivable.retail_debt > 0 && (
              <div>
                <div className="text-sm font-semibold tabular-nums text-red-600 dark:text-red-400">
                  {fmtMoney(net.receivable.retail_debt)} ₽
                </div>
                <div className="text-[11px] text-muted-foreground">
                  долг розницы · {nf0.format(net.receivable.retail_debt_sessions)} случаев — энергия ушла без оплаты
                </div>
              </div>
            )}
            {net.run_rate && (
              <div className="border-t pt-2">
                <div className="text-sm font-semibold tabular-nums">
                  ≈ {fmtMoneyShort(net.run_rate.projected_revenue)} ₽
                </div>
                <div className="text-[11px] text-muted-foreground">
                  прогноз месяца при текущем темпе ({net.run_rate.days_done} из {net.run_rate.days_in_month} дн.)
                </div>
              </div>
            )}
            {recon && (
              <div className="border-t pt-2">
                {/* Недогруженный месяц — не расхождение витрин, а дыра в данных.
                    Смешивать их в один процент нельзя: реестр за июнь на 3%
                    заполнения дал бы «расхождение +3193%». */}
                {recon.compared_months > 0 ? (
                  <>
                    <div className={`text-sm font-semibold tabular-nums ${Math.abs(recon.diff_pct ?? 0) > 10 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                      {recon.diff_pct != null ? `${recon.diff_pct > 0 ? '+' : ''}${recon.diff_pct}%` : '—'}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      сессии против реестра за {recon.compared_months} мес.
                      ({nf0.format(recon.session_kwh)} против {nf0.format(recon.registry_kwh)} кВтч)
                    </div>
                  </>
                ) : (
                  <div className="text-[11px] text-muted-foreground">Реестр за период не догружен — сверять не с чем.</div>
                )}
                {recon.incomplete_months.length > 0 && (
                  <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">
                    Реестр не догружен: {recon.incomplete_months.join(', ')} — эти месяцы в сверку не взяты.
                  </div>
                )}
                {recon.has_anomaly && (
                  <div className="mt-1 rounded bg-red-500/10 px-1.5 py-1 text-[11px] font-semibold text-red-600 dark:text-red-400">
                    ⚠ Аномалия: продажа энергии больше закупки — {recon.anomaly_months.join(', ')}.
                    Отпуск не может превышать вход по счётчикам (потери всегда ≥ 0) — проверить данные реестра/сессий.
                  </div>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/** Регионы: где выручка и где хуже всего заряжаются. 42 региона в сети — на
 * обзоре нужны полюса, полный список живёт в разрезах. */
function RegionExtremes({ regions }: { regions: OverviewNetwork['regions'] }) {
  if (!regions.top_revenue.length) return null
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Card>
        <CardContent className="p-0">
          <div className="border-b bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground">
            Регионы по выручке
          </div>
          <table className="w-full text-xs">
            <tbody>
              {regions.top_revenue.map((r) => (
                <tr key={r.label} className="border-b border-border/30">
                  <td className="p-2 font-medium">{r.label}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.visits)} виз.</td>
                  <td className="p-2 text-right font-mono">{fmtMoneyShort(r.revenue)} ₽</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          <div className="border-b bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground">
            Регионы, где хуже заряжаются
          </div>
          <table className="w-full text-xs">
            <tbody>
              {regions.worst_success.map((r) => (
                <tr key={r.label} className="border-b border-border/30">
                  <td className="p-2 font-medium">{r.label}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{nf0.format(r.visits)} виз.</td>
                  <td className={`p-2 text-right font-mono ${r.success_pct >= 85 ? 'text-emerald-600 dark:text-emerald-400' : r.success_pct >= 80 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'}`}>
                    {r.success_pct}%
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

/** Мини-спарклайн (inline SVG, без recharts). Цвет — нейтральный currentColor,
 * семантику роста несёт Δ-бейдж. Пустые бакеты (null) — разрыв линии. */
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

/** KPI-плитка с Δ% к прошлому периоду (абс. в углу) + мини-спарклайн.
 * Контракт экспорта сохранён: первые три ребёнка — label/value/hint;
 * Δ-бейдж и спарклайн идут ПОСЛЕ (экспорт читает детей по индексу 0..2). */
function KpiCard({ k, hint, baseline }: { k: OverviewKpi; hint?: string; baseline?: string }) {
  const showDelta = k.delta_pct != null && Math.abs(k.delta_pct) <= 500  // абсурдные % (пустая база) прячем
  const up = (k.delta_pct ?? 0) >= 0
  return (
    <div data-kpi className="relative rounded-xl border bg-card/50 p-3.5 shadow-sm">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{k.label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums leading-tight">{kpiDisplay(k)}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{hint ?? ''}</div>
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
function DailyRevenueBar({ companyId, dateFrom, dateTo, scope }: {
  companyId: string; dateFrom: string; dateTo: string; scope: ScopeArg
}) {
  const [mode, setMode] = useState<RevMode>('all')
  const { data, isLoading } = useQuery({
    // Сеть входит в ключ (scope.key) и в запрос (stations/regions) — иначе график
    // остаётся по всей сети, пока KPI уже сужены на выбранную ЭЗС.
    queryKey: ['overview-daily-rev', companyId, dateFrom, dateTo, mode, scope.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'day', metric: 'amount',
      stations: scope.stations, regions: scope.regions,
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
            <span className="text-emerald-600 dark:text-emerald-400">₽</span>Реализация по дням{data ? ` (${data.data.length} дн.)` : ''}
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
function AvgCheckLine({ companyId, dateFrom, dateTo, bigValue, scope }: {
  companyId: string; dateFrom: string; dateTo: string; bigValue: number; scope: ScopeArg
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['overview-avgcheck-fl', companyId, dateFrom, dateTo, scope.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'day', metric: 'avg_check',
      dim: 'user_type', dimVal: 'ФЛ', stations: scope.stations, regions: scope.regions }),
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
            <div className="flex items-center gap-2 text-sm font-medium"><span className="text-blue-600 dark:text-blue-400">₽</span>Средний чек (частные)</div>
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
        <div className="mb-2 flex items-center gap-2 text-sm font-medium"><Zap className="h-4 w-4 text-blue-600 dark:text-blue-400" />Суточная активность по часам</div>
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
              columns: ['Станция', 'Сессий', 'Выручка, ₽', 'Загрузка, %', 'Успех сессий, %'],
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
                  {/* Здесь именно СЕССИИ (доля Complete), а не визиты — иначе цифра
                      не сойдётся с KPI «Зарядились» наверху, и это надо подсказать. */}
                  <td className="p-2 text-right font-mono tabular-nums"
                    title="Доля успешных сессий станции. KPI «Зарядились» наверху считает визиты — там смежные попытки одного клиента склеены.">
                    {r.success_pct.toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}


function SectionTitle({ children, hint, info }: { children: ReactNode; hint?: string; info?: string }) {
  return (
    <div className="flex items-baseline gap-2 pt-1">
      <h3 className="text-sm font-semibold flex items-center gap-1">{children}{info && <MetricHint text={info} />}</h3>
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
    </div>
  )
}

// ─── главная витрина ─────────────────────────────────────────────────
export function OverviewDashboardPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  // Вид-срез: период — только из контура рабочей области.
  const period = { from: dateFrom, to: dateTo }
  const sc = useScope()
  // Часовой пояс профиля активности (часы/дни недели): МСК по умолчанию.
  const [tz, setTz] = useState<Tz>('msk')

  const { data, isLoading, error } = useQuery({
    queryKey: ['charge-overview', companyId, period.from, period.to, sc.key, tz],
    queryFn: () => getChargeOverview({ companyId, dateFrom: period.from, dateTo: period.to, stations: sc.stations, regions: sc.regions, tz }),
  })
  // «Всего ЭЗС в сети» = объекты справочника станций (Нормализация → service_locations),
  // а не выведенное из сессий. Регионы/коннекторы за период — из разрезов.
  const linkage = useQuery({ queryKey: ['stations-linkage', companyId], queryFn: () => getStationsLinkage(companyId) })
  const connQ = useQuery({
    queryKey: ['overview-dim', 'connector', companyId, period.from, period.to, sc.key],
    queryFn: () => getChargeSessions({ companyId, dateFrom: period.from, dateTo: period.to, groupBy: 'connector', stations: sc.stations, regions: sc.regions }),
  })
  const regQ = useQuery({
    queryKey: ['overview-dim', 'region', companyId, period.from, period.to, sc.key],
    queryFn: () => getChargeSessions({ companyId, dateFrom: period.from, dateTo: period.to, groupBy: 'region', stations: sc.stations, regions: sc.regions }),
  })

  // Период, с которым сравниваются Δ% на карточках — в подсказку самих Δ.
  const baseline = data?.has_baseline
    ? formatPeriod(data.prev_period.from, data.prev_period.to)
    : undefined

  return (
    <div className="p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3" data-export-ignore>
        {/* Счётчики сети (ЭЗС, порты, сессии) не дублируем: они ниже карточками.
            База сравнения — в подсказке Δ% на карточках KPI. */}
        <h2 className="flex items-center gap-2 text-base font-semibold"><Zap className="h-4 w-4 text-blue-600 dark:text-blue-400" />Обзор сети ЭЗС</h2>
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

            {/* статистика по объектам сети. «Молчат» — кликабельная: простой
                парка это не справочная цифра, а список работ. */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              <CountCard label="ЭЗС (всего в сети)" value={nf0.format(linkage.data?.objects || data.meta.active_stations)} hint="боевых (без тест/выведенных)" />
              <CountCard label="Активных ЭЗС" value={nf0.format(data.meta.active_stations)} hint="с сессиями за период" />
              <SilentCard companyId={companyId} period={period} silent={data.network.silent} />
              <CountCard label="Регионов" value={nf0.format(regQ.data?.lines.length ?? 0)} hint="за период" />
              <CountCard label="Коннекторов (типов)" value={nf0.format(connQ.data?.lines.length ?? 0)} hint="за период" />
              <CountCard label="Коннекторов в сети" value={nf0.format(data.meta.ports)} hint="физических портов" />
            </div>

            <BreakdownCard companyId={companyId} period={period} scope={sc} cfg={OWNERS_CFG} />
            <BreakdownCard companyId={companyId} period={period} scope={sc} cfg={SPEED_CFG} />

            <NetworkHealth net={data.network} />
            <RegionExtremes regions={data.network.regions} />

            {/* ключевые KPI с Δ% к прошлому периоду + спарклайн — под статистикой.
                База сравнения — в подсказке самого Δ (см. KpiCard). */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              {(['revenue', 'visits', 'sessions', 'energy_kwh', 'price_per_kwh', 'visit_success_pct'] as const).map((key) => {
                const k = data.kpis.find((x) => x.key === key)
                return k ? <KpiCard key={key} k={k} hint={KPI_HINTS[key]} baseline={baseline} /> : null
              })}
            </div>

            {/* реализация по дням */}
            <DailyRevenueBar companyId={companyId} dateFrom={period.from} dateTo={period.to} scope={sc} />

            {/* одна строка: средний чек (3/4) + два доната долей стопкой (1/4), выровнены по высоте */}
            <div className="grid items-stretch gap-3 lg:grid-cols-4">
              <div className="lg:col-span-3 [&>div]:h-full">
                <AvgCheckLine companyId={companyId} dateFrom={period.from} dateTo={period.to} scope={sc}
                  bigValue={(() => { const fl = data.shares.by_segment.find((r) => r.label === 'Розница (ФЛ)'); return fl && fl.sessions ? fl.amount / fl.sessions : 0 })()} />
              </div>
              <div className="flex flex-col gap-3 lg:col-span-1">
                <div className="min-h-0 flex-1 [&>div]:h-full"><DonutCard title="По коннекторам" rows={data.shares.connector} /></div>
                <div className="min-h-0 flex-1 [&>div]:h-full"><DonutCard title="По сегменту" rows={data.shares.by_segment} /></div>
              </div>
            </div>

            {/* профиль активности: часы + дни недели (в одну строку) */}
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <SectionTitle hint={tz === 'local' ? 'по местному времени станций' : 'по московскому времени'}>Профиль активности</SectionTitle>
              <TzToggle value={tz} onChange={setTz} />
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <HourlyBar hourly={data.hourly} />
              <WeekdayBar weekday={data.weekday} />
            </div>

            {/* станции топ/дно */}
            <SectionTitle hint={`порт-нормировано · ≥ ${data.stations.min_sessions} сессий`} info={HINTS.throughputPort}>Станции: лидеры и аутсайдеры по загрузке</SectionTitle>
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
        {stat('Скидка ЮЛ', `${c.discount_pct > 0 ? '+' : ''}${nf1.format(c.discount_pct)}%`, c.discount < 0 ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400')}
        {stat('Активных ЮЛ', nf0.format(c.active_clients) + ` из ${nf0.format(c.clients)}`)}
        {stat('Доля ЮЛ в выручке', nf1.format(c.corp_share_pct) + '%')}
        <span className="ml-auto text-[11px] text-muted-foreground">Детали — в пункте «Корпоратив»</span>
      </CardContent>
    </Card>
  )
}

