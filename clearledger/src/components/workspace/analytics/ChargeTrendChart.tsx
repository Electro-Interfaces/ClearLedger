/**
 * График тренда метрики зарядных сессий по бакетам времени.
 * Multi-series: одна линия на серию (топ-N станций/коннекторов + «Прочие»).
 * Линия — на общей чартовой базе (ui/line-chart), цвета серий приходят
 * классами chart-1..5 и следуют теме сами.
 */

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts'
import { LineChart, ChartTooltip } from '@/components/ui/line-chart'
import {
  fmtMetric, fmtMetricShort, CHARGE_METRIC_LABELS, type ChargeMetric,
} from '@/services/analyticsService'
import { formatBucket } from '@/lib/formatDate'

// Палитра столбцов — токенами, а не значениями цвета: var() в SVG-атрибуте
// браузер резолвит (проверено), поэтому переключение темы график переживает.
const COLORS = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-5))',
  'hsl(var(--accent-purple))',
]

export function ChargeTrendChart({ data, series, metric }: {
  data: Array<Record<string, string | number | null>>
  series: string[]
  metric: ChargeMetric
}) {
  // Единственная серия приходит безымянным ключом `value` — подписываем её
  // названием метрики: в легенде и подсказке должно стоять «Отпущено кВт·ч»,
  // а не служебное слово.
  const label = CHARGE_METRIC_LABELS[metric]
  const renamed = series.includes('value')
  const categories = series.map((s) => (s === 'value' ? label : s))
  const rows = data.map((d) => {
    const { value, bucket, ...rest } = d
    return {
      ...rest,
      bucket: formatBucket(String(bucket)),
      ...(renamed ? { [label]: value } : { value }),
    }
  })

  return (
    <LineChart
      className="h-80"
      data={rows}
      index="bucket"
      categories={categories}
      // Ось — короткий формат (12,4 тыс), подсказка — полный: на оси важен масштаб,
      // в подсказке цифра, которую переписывают в отчёт.
      valueFormatter={(v) => fmtMetricShort(metric, v)}
      customTooltip={(props) => (
        <ChartTooltip {...props} valueFormatter={(v) => fmtMetric(metric, v)} />
      )}
      showLegend={series.length > 1}
      // Ось от нуля прижимает кривую к верху: успешность гуляет в пределах 65–70 %,
      // а на шкале 0–100 это плоская черта. Домен считает recharts по данным.
      autoMinValue
      // Подпись у каждого бакета, а не через один: восемь месяцев подписаны — восемь.
      intervalType="preserveStartEnd"
      connectNulls
      yAxisWidth={56}
    />
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
    v === max ? 'hsl(var(--chart-1))' : v === min ? 'hsl(var(--chart-3))' : 'hsl(var(--chart-1))'
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
          tickFormatter={(v) => formatBucket(String(v))}
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
