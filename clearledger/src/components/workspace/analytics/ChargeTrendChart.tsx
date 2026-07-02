/**
 * График тренда метрики зарядных сессий по бакетам времени (recharts LineChart).
 * Multi-series: одна линия на серию (топ-N станций/коннекторов + «Прочие»).
 * Тема — из CSS-переменных приложения (как dashboard/CategoryChart).
 */

import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts'
import {
  fmtMetric, fmtMetricShort, CHARGE_METRIC_LABELS, type ChargeMetric,
} from '@/services/analyticsService'

// Палитра серий — значения выровнены под chart-токены темы (--chart-1..5).
// Литералы, т.к. recharts кладёт stroke в SVG-атрибут, где var() не резолвится.
const COLORS = [
  'hsl(217, 91%, 60%)',   // --chart-1
  'hsl(152, 69%, 45%)',   // --chart-2
  'hsl(25, 100%, 55%)',   // --chart-3
  'hsl(280, 65%, 65%)',   // --chart-4
  'hsl(340, 75%, 55%)',   // --chart-5
  'hsl(280, 100%, 70%)',  // --accent-purple
]

export function ChargeTrendChart({ data, series, metric }: {
  data: Array<Record<string, string | number | null>>
  series: string[]
  metric: ChargeMetric
}) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis
          dataKey="bucket"
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
          tickLine={false}
          axisLine={{ stroke: 'hsl(var(--border))' }}
        />
        <YAxis
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(v) => fmtMetricShort(metric, v as number)}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'hsl(var(--popover))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '8px',
            color: 'hsl(var(--popover-foreground))',
            fontSize: 12,
          }}
          labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
          formatter={(value, name) => [fmtMetric(metric, value as number | null), name as string]}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => (
          <Line
            key={s}
            type="monotone"
            dataKey={s}
            name={s === 'value' ? CHARGE_METRIC_LABELS[metric] : s}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={false}
            connectNulls
            activeDot={{ r: 4 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/**
 * Столбчатая диаграмма для сравнения дискретных интервалов — нагляднее сглаженной
 * линии: каждый интервал = столбец, пики видны сразу. Пик/минимум выделены цветом.
 */
export function ChargeBarChart({ data, series, metric }: {
  data: Array<Record<string, string | number | null>>
  series: string[]
  metric: ChargeMetric
}) {
  const single = series.length === 1
  const key = series[0]
  const nums = single ? data.map((d) => d[key]).filter((v): v is number => typeof v === 'number') : []
  const max = single && nums.length ? Math.max(...nums) : null
  const min = single && nums.length ? Math.min(...nums) : null
  const barColor = (v: string | number | null) =>
    v === max ? 'hsl(217, 91%, 60%)' : v === min ? 'hsl(25, 100%, 55%)' : 'hsl(217, 91%, 60%)'
  const barOpacity = (v: string | number | null) => (v === max ? 1 : v === min ? 0.85 : 0.45)
  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }} barCategoryGap={data.length > 16 ? '8%' : '20%'}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis
          dataKey="bucket"
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: 'hsl(var(--border))' }}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(v) => fmtMetricShort(metric, v as number)}
        />
        <Tooltip
          cursor={{ fill: 'hsl(var(--muted) / 0.4)' }}
          contentStyle={{
            backgroundColor: 'hsl(var(--popover))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '8px',
            color: 'hsl(var(--popover-foreground))',
            fontSize: 12,
          }}
          labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
          formatter={(value, name) => [fmtMetric(metric, value as number | null), name as string]}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => (
          <Bar
            key={s}
            dataKey={s}
            name={s === 'value' ? CHARGE_METRIC_LABELS[metric] : s}
            fill={COLORS[i % COLORS.length]}
            radius={[2, 2, 0, 0]}
            maxBarSize={44}
          >
            {single && data.map((d, j) => (
              <Cell key={j} fill={barColor(d[key])} fillOpacity={barOpacity(d[key])} />
            ))}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
