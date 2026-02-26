import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useCategoryStats } from '@/hooks/useEntries'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'

const COLORS = [
  'hsl(217, 91%, 60%)',
  'hsl(160, 60%, 45%)',
  'hsl(30, 80%, 55%)',
  'hsl(280, 65%, 60%)',
  'hsl(340, 75%, 55%)',
  'hsl(50, 80%, 50%)',
]

export function CategoryChart() {
  const { company } = useCompany()
  const { data: stats = [] } = useCategoryStats()

  const chartData = stats.map((s) => {
    const cat = getCategoryById(company.profileId, s.categoryId)
    return {
      name: cat?.label ?? s.categoryId,
      count: s.count,
    }
  })

  if (chartData.length === 0) {
    return (
      <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
        <CardHeader>
          <CardTitle>Записи по категориям</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-muted-foreground">Нет данных</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle>Записи по категориям</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 0, right: 24, bottom: 0, left: 0 }}
          >
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={140}
              tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 13 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: 'hsl(var(--muted) / 0.3)' }}
              contentStyle={{
                backgroundColor: 'hsl(var(--popover))',
                border: '1px solid hsl(var(--border))',
                borderRadius: '8px',
                color: 'hsl(var(--popover-foreground))',
              }}
              formatter={(value) => [(value ?? 0).toLocaleString('ru-RU'), 'Записей']}
            />
            <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={28}>
              {chartData.map((_entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
