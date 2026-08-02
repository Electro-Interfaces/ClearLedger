/**
 * «Динамика 2024–2026» (cs_trend) — длинный горизонт отпуска сети ЭЗС на склейке
 * двух L2-рядов нормализации: сводная выработка контрагента (station_dispense_periods,
 * слот obshaya — 2024–2025) и транзакционные зарядные сессии (с 2026). Точку склейки
 * выбирает бэкенд (первый месяц полных сессий) — на графике отмечена линией.
 * Разрезы: тип коннектора (канонизированный) / Быстрая–Медленная / город–трасса.
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExportButton } from './analytics/ExportButton'
import {
  ResponsiveContainer, ComposedChart, Bar, XAxis, YAxis, Tooltip,
  CartesianGrid, ReferenceLine,
} from 'recharts'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getChargeLongTrend } from '@/services/analyticsService'
import { useNetScope } from '@/hooks/useScopeReset'
import { seriesColor } from './analytics/palette'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

const GROUPS = [
  { key: 'none', label: 'Вся сеть' },
  { key: 'connector', label: 'По коннекторам' },
  { key: 'speed', label: 'Быстрые / медленные' },
  { key: 'location_class', label: 'Город / трасса' },
] as const
type GroupKey = typeof GROUPS[number]['key']

const DIM_LABEL: Record<string, string> = {
  fast: 'Быстрые', slow: 'Медленные',
  city: 'Город', highway: 'Трасса',
  '—': 'Не размечено',
}

export function ChargeTrendPanel({ companyId }: {
  companyId: string; dateFrom?: string; dateTo?: string
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [groupBy, setGroupBy] = useState<GroupKey>('none')
  const sc = useNetScope()
  const { data, isLoading } = useQuery({
    queryKey: ['charge-long-trend', companyId, groupBy, sc.key],
    queryFn: () => getChargeLongTrend(companyId, groupBy, { stations: sc.stations, regions: sc.regions }),
    enabled: !!companyId,
    staleTime: 5 * 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка динамики…</div>
  if (!data || data.months.length === 0) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Нет данных длинного горизонта — загрузите «Сводную выработку 2024–2026» в канале
        «Энергоснабжение и аренда ЭЗС».
      </div>
    )
  }

  const months = data.months
  const dimKeys = data.dimKeys.slice(0, 8)
  const chart = months.map((m) => ({
    period: m.period.slice(0, 7),
    kwh: m.kwh,
    source: m.source,
    ...(m.dims ?? {}),
  }))
  const cutoffLabel = data.cutoff ? data.cutoff.slice(0, 7) : null

  // KPI: сумма горизонта; YoY — по последнему ПОЛНОМУ месяцу (текущий
  // календарный месяц не закрыт — сравнивать его с прошлым годом нечестно).
  const totalKwh = months.reduce((a, m) => a + m.kwh, 0)
  const nowYm = new Date().toISOString().slice(0, 7)
  const closed = months.filter((m) => m.period.slice(0, 7) < nowYm)
  const last = closed[closed.length - 1] ?? months[months.length - 1]
  const prevYear = months.find((m) => m.period === `${Number(last.period.slice(0, 4)) - 1}${last.period.slice(4)}`)
  const yoy = prevYear && prevYear.kwh > 0 ? (last.kwh - prevYear.kwh) / prevYear.kwh * 100 : null
  const fileMonths = months.filter((m) => m.source === 'file').length

  return (
    <div ref={rootRef} className="space-y-4 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">Динамика отпуска · длинный горизонт</h2>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        <ExportButton title="Динамика отпуска 2024+" getEl={() => rootRef.current} />
        <span className="text-xs text-muted-foreground">
          {months[0].period.slice(0, 7)} — {last.period.slice(0, 7)} · до {cutoffLabel ?? '—'} — сводная контрагента, далее — сессии
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card><CardContent className="pt-4">
          <div className="text-xs text-muted-foreground">Σ отпуск за горизонт</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">{nf(totalKwh / 1e6, 2)} млн кВт·ч</div>
          <div className="text-[11px] text-muted-foreground/70">{months.length} месяцев</div>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <div className="text-xs text-muted-foreground">Последний полный месяц</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">{nf(last.kwh)} кВт·ч</div>
          <div className="text-[11px] text-muted-foreground/70">{last.period.slice(0, 7)}</div>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <div className="text-xs text-muted-foreground">Год к году (YoY)</div>
          <div className={`mt-1 text-lg font-semibold tabular-nums ${yoy == null ? '' : yoy >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500/90'}`}>
            {yoy == null ? '—' : `${yoy > 0 ? '+' : ''}${nf(yoy, 1)}%`}
          </div>
          <div className="text-[11px] text-muted-foreground/70">{prevYear ? `к ${prevYear.period.slice(0, 7)}` : 'нет базы сравнения'}</div>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <div className="text-xs text-muted-foreground">Источники ряда</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">{fileMonths} + {months.length - fileMonths}</div>
          <div className="text-[11px] text-muted-foreground/70">мес. сводной + мес. сессий</div>
        </CardContent></Card>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {GROUPS.map((g) => (
          <button key={g.key} onClick={() => setGroupBy(g.key)}
            className={`px-2.5 py-1 rounded-md text-xs border transition-colors ${groupBy === g.key
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border/50 text-muted-foreground hover:bg-accent/30'}`}>
            {g.label}
          </button>
        ))}
      </div>

      <Card><CardContent className="pt-5">
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={chart} margin={{ top: 8, right: 12, left: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.08} />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={2} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => nf(v / 1000) + 'к'} width={44} />
            <Tooltip {...rechartsTooltipTheme}
              formatter={(v, name) => [`${nf(Number(v))} кВт·ч`, DIM_LABEL[String(name)] ?? String(name)]}
              labelFormatter={(l) => {
                const key = String(l)
                const m = months.find((x) => x.period.slice(0, 7) === key)
                return `${key} · ${m?.source === 'file' ? 'сводная контрагента' : 'зарядные сессии'}`
              }}
              contentStyle={{ fontSize: 12 }}
            />
            {groupBy === 'none'
              ? <Bar dataKey="kwh" name="Отпуск" fill={seriesColor(0, 1)} radius={[3, 3, 0, 0]} />
              : dimKeys.map((k, i) => (
                <Bar key={k} dataKey={k} name={k} stackId="dims"
                  fill={seriesColor(i, dimKeys.length)} />
              ))}
            {cutoffLabel && (
              <ReferenceLine x={cutoffLabel} stroke="currentColor" strokeDasharray="4 4" opacity={0.45}
                label={{ value: '→ сессии', fontSize: 10, position: 'insideTopLeft', opacity: 0.7 }} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
        {groupBy !== 'none' && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {dimKeys.map((k, i) => (
              <span key={k} className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: seriesColor(i, dimKeys.length) }} />
                {DIM_LABEL[k] ?? k}
              </span>
            ))}
          </div>
        )}
      </CardContent></Card>

      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          Помесячная таблица ({months.length})
        </summary>
        <div className="mt-2 max-h-[380px] overflow-auto rounded-lg border border-border/50">
          <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
            <TableHead>Месяц</TableHead>
            <TableHead>Источник</TableHead>
            <TableHead className="text-right">Отпуск, кВт·ч</TableHead>
            <TableHead className="text-right">Выручка, ₽</TableHead>
            {dimKeys.map((k) => (
              <TableHead key={k} className="text-right">{DIM_LABEL[k] ?? k}</TableHead>
            ))}
          </TableRow></TableHeader><TableBody>
            {[...months].reverse().map((m) => (
              <TableRow key={m.period}>
                <TableCell className="font-medium tabular-nums">{m.period.slice(0, 7)}</TableCell>
                <TableCell>
                  <Badge variant="secondary" className={`text-[9px] uppercase tracking-wide ${m.source === 'sessions'
                    ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                    : 'bg-blue-500/10 text-blue-600 dark:text-blue-400'}`}>
                    {m.source === 'sessions' ? 'сессии' : 'сводная'}
                  </Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums">{nf(m.kwh)}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{m.rub != null ? nf(m.rub) : '—'}</TableCell>
                {dimKeys.map((k) => (
                  <TableCell key={k} className="text-right tabular-nums text-muted-foreground">
                    {m.dims?.[k] != null ? nf(m.dims[k]) : '—'}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody></Table>
        </div>
      </details>
    </div>
  )
}
