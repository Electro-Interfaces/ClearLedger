/**
 * Единый управляемый график аналитики ЭЗС (recharts ComposedChart).
 * Тип: столбцы / линия / область. Режим: обычные / накопительно / индекс к 100.
 * Тумблеры: лог. шкала, линия среднего. Multi-series: стек / 100% (доли).
 * Тема — из CSS-переменных приложения.
 */

import { useState, type ReactNode } from 'react'
import {
  ComposedChart, Bar, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'
import { Button } from '@/components/ui/button'
import {
  fmtMetric, fmtMetricShort, CHARGE_METRIC_LABELS, type ChargeMetric,
} from '@/services/analyticsService'

const COLORS = [
  'hsl(217, 91%, 60%)', 'hsl(152, 69%, 45%)', 'hsl(25, 100%, 55%)',
  'hsl(280, 65%, 65%)', 'hsl(340, 75%, 55%)', 'hsl(280, 100%, 70%)',
]

export type ChartType = 'bar' | 'line' | 'area'
export type ChartMode = 'plain' | 'cumulative' | 'index'
export interface ChartView {
  type: ChartType
  mode: ChartMode
  log: boolean
  avg: boolean
  stack: 'none' | 'stack' | 'percent'
}
export const DEFAULT_VIEW: ChartView = { type: 'bar', mode: 'plain', log: false, avg: false, stack: 'none' }

const RATIO_METRICS: ChargeMetric[] = ['avg_check', 'avg_energy', 'avg_duration_min', 'success_pct', 'price_per_kwh']
const isRatio = (m: ChargeMetric) => RATIO_METRICS.includes(m)

export function useChartView(initial: Partial<ChartView> = {}) {
  return useState<ChartView>({ ...DEFAULT_VIEW, ...initial })
}

type Row = Record<string, string | number | null>

/** Применить режим (накопительно/индекс) к данным по каждой серии. */
function applyMode(data: Row[], series: string[], view: ChartView, metric: ChargeMetric): Row[] {
  if (view.mode === 'cumulative' && !isRatio(metric)) {
    const acc: Record<string, number> = {}
    return data.map((row) => {
      const r: Row = { ...row }
      series.forEach((s) => { if (typeof r[s] === 'number') { acc[s] = (acc[s] ?? 0) + (r[s] as number); r[s] = acc[s] } })
      return r
    })
  }
  if (view.mode === 'index') {
    const base: Record<string, number> = {}
    series.forEach((s) => { const first = data.find((row) => typeof row[s] === 'number'); base[s] = first ? (first[s] as number) : 0 })
    return data.map((row) => {
      const r: Row = { ...row }
      series.forEach((s) => { if (typeof r[s] === 'number' && base[s]) r[s] = Math.round(((r[s] as number) / base[s]) * 1000) / 10 })
      return r
    })
  }
  return data
}

export function ChargeChart({ data, series, metric, view, height = 320 }: {
  data: Row[]; series: string[]; metric: ChargeMetric; view: ChartView; height?: number
}) {
  const single = series.length === 1
  const d = applyMode(data, series, view, metric)
  const canStack = !single && view.type !== 'line' && view.stack !== 'none'
  const stackId = canStack ? 'a' : undefined
  const percent = canStack && view.stack === 'percent'
  const isIndex = view.mode === 'index'

  // Форматтеры значений с учётом режима
  const fmtVal = (v: number | null) => isIndex ? `${v ?? 0}` : fmtMetric(metric, v)
  const fmtAxis = (v: number) => percent ? `${Math.round(v * 100)}%` : isIndex ? `${v}` : fmtMetricShort(metric, v)

  // Пик/минимум для подсветки одиночных столбцов (только обычный режим)
  const nums = single ? d.map((r) => r[series[0]]).filter((v): v is number => typeof v === 'number') : []
  const max = nums.length ? Math.max(...nums) : null
  const min = nums.length ? Math.min(...nums) : null
  const mean = nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
  const highlightBars = single && view.type === 'bar' && view.mode === 'plain' && !view.log

  const renderSeries = (s: string, i: number) => {
    const color = COLORS[i % COLORS.length]
    const name = s === 'value' ? CHARGE_METRIC_LABELS[metric] : s
    if (view.type === 'line') {
      return <Line key={s} type="monotone" dataKey={s} name={name} stroke={color} strokeWidth={2} dot={false} connectNulls activeDot={{ r: 4 }} />
    }
    if (view.type === 'area') {
      return <Area key={s} type="monotone" dataKey={s} name={name} stroke={color} fill={color} fillOpacity={0.2} strokeWidth={2} connectNulls stackId={stackId} />
    }
    return (
      <Bar key={s} dataKey={s} name={name} fill={color} radius={[2, 2, 0, 0]} maxBarSize={44} stackId={stackId}>
        {highlightBars && d.map((row, j) => {
          const v = row[series[0]]
          const op = v === max ? 1 : v === min ? 0.85 : 0.45
          const c = v === min ? 'hsl(25, 100%, 55%)' : color
          return <Cell key={j} fill={c} fillOpacity={op} />
        })}
      </Bar>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={d} margin={{ top: 8, right: 16, left: 4, bottom: 4 }} stackOffset={percent ? 'expand' : undefined}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis dataKey="bucket" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} tickLine={false}
          axisLine={{ stroke: 'hsl(var(--border))' }} interval="preserveStartEnd" />
        <YAxis tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} tickLine={false} axisLine={false} width={56}
          scale={view.log ? 'log' : 'auto'}
          domain={view.log ? [0.1, 'auto'] : percent ? [0, 1] : ['auto', 'auto']}
          allowDataOverflow={view.log}
          tickFormatter={(v) => fmtAxis(v as number)} />
        <Tooltip
          cursor={view.type === 'bar' ? { fill: 'hsl(var(--muted) / 0.4)' } : undefined}
          contentStyle={{ backgroundColor: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: '8px', color: 'hsl(var(--popover-foreground))', fontSize: 12 }}
          labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
          formatter={(value, name) => [fmtVal(value as number | null), name as string]} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {view.avg && single && mean != null && !isIndex && view.stack === 'none' && (
          <ReferenceLine y={mean} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4"
            label={{ value: `среднее ${fmtMetricShort(metric, mean)}`, position: 'right', fill: 'hsl(var(--muted-foreground))', fontSize: 10 }} />
        )}
        {series.map(renderSeries)}
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Тулбар переключателей вида графика. */
export function ChartControls({ view, onChange, single, metric }: {
  view: ChartView; onChange: (v: ChartView) => void; single: boolean; metric: ChargeMetric
}) {
  const set = (patch: Partial<ChartView>) => onChange({ ...view, ...patch })
  const Seg = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) => (
    <Button variant={active ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-2" onClick={onClick}>{children}</Button>
  )
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2" data-export-ignore>
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-muted-foreground mr-1">Тип:</span>
        <Seg active={view.type === 'bar'} onClick={() => set({ type: 'bar' })}>Столбцы</Seg>
        <Seg active={view.type === 'line'} onClick={() => set({ type: 'line' })}>Линия</Seg>
        <Seg active={view.type === 'area'} onClick={() => set({ type: 'area' })}>Область</Seg>
      </div>
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-muted-foreground mr-1">Режим:</span>
        <Seg active={view.mode === 'plain'} onClick={() => set({ mode: 'plain' })}>Обычные</Seg>
        {!isRatio(metric) && <Seg active={view.mode === 'cumulative'} onClick={() => set({ mode: 'cumulative' })}>Накопительно</Seg>}
        <Seg active={view.mode === 'index'} onClick={() => set({ mode: 'index' })}>Индекс 100</Seg>
      </div>
      <div className="flex items-center gap-1">
        <Seg active={view.log} onClick={() => set({ log: !view.log })}>Лог</Seg>
        {single && <Seg active={view.avg} onClick={() => set({ avg: !view.avg })}>Среднее</Seg>}
      </div>
      {!single && (
        <div className="flex items-center gap-1">
          <span className="text-[11px] text-muted-foreground mr-1">Ряды:</span>
          <Seg active={view.stack === 'none'} onClick={() => set({ stack: 'none' })}>Рядом</Seg>
          <Seg active={view.stack === 'stack'} onClick={() => set({ stack: 'stack' })}>Стек</Seg>
          <Seg active={view.stack === 'percent'} onClick={() => set({ stack: 'percent' })}>100%</Seg>
        </div>
      )}
    </div>
  )
}
