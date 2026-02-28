/**
 * Страница отчётов: KPI за период, контрагенты, источники, ошибки.
 */

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { useEntries } from '@/hooks/useEntries'
import { generatePeriodReport, getCounterpartyStats, getSourceStats, getErrorAnalysis } from '@/services/reportService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { ExportModal } from '@/components/common/ExportModal'
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Download, FileText, CheckCircle2, AlertTriangle, Send, Clock } from 'lucide-react'

type PeriodPreset = 'today' | 'week' | 'month' | 'quarter' | 'custom'

function getPeriodDates(preset: PeriodPreset, customFrom: string, customTo: string): { from: string; to: string } {
  const now = new Date()
  const today = now.toISOString().slice(0, 10)

  if (preset === 'custom') return { from: customFrom || today, to: customTo || today }
  if (preset === 'today') return { from: today, to: today }

  const d = new Date(now)
  if (preset === 'week') d.setDate(d.getDate() - 7)
  else if (preset === 'month') d.setMonth(d.getMonth() - 1)
  else d.setMonth(d.getMonth() - 3)

  return { from: d.toISOString().slice(0, 10), to: today }
}

const COLORS = ['hsl(217, 91%, 60%)', 'hsl(120, 100%, 40%)', 'hsl(45, 100%, 55%)', 'hsl(0, 84%, 60%)', 'hsl(280, 65%, 60%)', 'hsl(180, 70%, 45%)']

export function ReportsPage() {
  const { companyId } = useCompany()
  const [preset, setPreset] = useState<PeriodPreset>('month')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [exportOpen, setExportOpen] = useState(false)
  const { data: allEntries = [] } = useEntries()

  const { from, to } = useMemo(() => getPeriodDates(preset, customFrom, customTo), [preset, customFrom, customTo])

  const { data: report } = useQuery({
    queryKey: ['report-period', companyId, from, to],
    queryFn: () => generatePeriodReport(companyId, from, to),
  })

  const { data: cpStats = [] } = useQuery({
    queryKey: ['report-cp', companyId, from, to],
    queryFn: () => getCounterpartyStats(companyId, from, to),
  })

  const { data: sourceStats = [] } = useQuery({
    queryKey: ['report-source', companyId, from, to],
    queryFn: () => getSourceStats(companyId, from, to),
  })

  const { data: errorStats = [] } = useQuery({
    queryKey: ['report-errors', companyId, from, to],
    queryFn: () => getErrorAnalysis(companyId, from, to),
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <h1 className="text-2xl font-bold tracking-tight">Отчёты</h1>
        <Button variant="outline" onClick={() => setExportOpen(true)}>
          <Download className="size-4" />
          Экспорт
        </Button>
      </div>

      {/* Period selector */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={preset} onValueChange={(v) => setPreset(v as PeriodPreset)}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="today">Сегодня</SelectItem>
            <SelectItem value="week">Неделя</SelectItem>
            <SelectItem value="month">Месяц</SelectItem>
            <SelectItem value="quarter">Квартал</SelectItem>
            <SelectItem value="custom">Произвольный</SelectItem>
          </SelectContent>
        </Select>
        {preset === 'custom' && (
          <>
            <Input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} className="w-40" />
            <span className="text-muted-foreground">—</span>
            <Input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} className="w-40" />
          </>
        )}
      </div>

      {/* KPI cards */}
      {report && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <KpiCard icon={FileText} label="Загружено" value={report.uploaded} color="text-blue-500" bg="hsl(217 91% 60% / 0.15)" />
          <KpiCard icon={CheckCircle2} label="Проверено" value={report.verified} color="text-green-500" bg="hsl(120 100% 40% / 0.15)" />
          <KpiCard icon={AlertTriangle} label="Отклонено" value={report.rejected} color="text-red-500" bg="hsl(0 84% 60% / 0.15)" />
          <KpiCard icon={Send} label="Передано" value={report.transferred} color="text-purple-500" bg="hsl(280 65% 60% / 0.15)" />
          <KpiCard
            icon={Clock}
            label="Ср. верификация"
            value={report.avgVerificationTimeMs ? formatDuration(report.avgVerificationTimeMs) : '—'}
            color="text-yellow-500"
            bg="hsl(45 100% 55% / 0.15)"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top counterparties */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Топ контрагентов</CardTitle>
          </CardHeader>
          <CardContent>
            {cpStats.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет данных за период</p>
            ) : (
              <div className="space-y-2">
                {cpStats.slice(0, 10).map((cp) => (
                  <div key={cp.counterparty} className="flex items-center justify-between text-sm">
                    <span className="truncate max-w-[60%]">{cp.counterparty}</span>
                    <div className="flex gap-3">
                      <span className="text-muted-foreground">{cp.count}</span>
                      <span className="text-green-500">{cp.verified}</span>
                      <span className="text-red-500">{cp.rejected}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Sources pie chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">По источникам</CardTitle>
          </CardHeader>
          <CardContent>
            {sourceStats.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет данных за период</p>
            ) : (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width={160} height={160}>
                  <PieChart>
                    <Pie data={sourceStats} dataKey="count" nameKey="label" cx="50%" cy="50%" outerRadius={70}>
                      {sourceStats.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--popover))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '8px',
                        color: 'hsl(var(--popover-foreground))',
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="space-y-1 text-sm">
                  {sourceStats.map((s, i) => (
                    <div key={s.source} className="flex items-center gap-2">
                      <div className="size-3 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                      <span>{s.label}: {s.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Error analysis */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Анализ ошибок</CardTitle>
          </CardHeader>
          <CardContent>
            {errorStats.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет ошибок за период</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={errorStats.slice(0, 8)} layout="vertical">
                  <XAxis type="number" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <YAxis type="category" dataKey="reason" width={150} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <Tooltip
                    cursor={{ fill: 'hsl(var(--muted) / 0.3)' }}
                    contentStyle={{
                      backgroundColor: 'hsl(var(--popover))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '8px',
                      color: 'hsl(var(--popover-foreground))',
                    }}
                  />
                  <Bar dataKey="count" fill="hsl(var(--error))" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <ExportModal open={exportOpen} onOpenChange={setExportOpen} entries={allEntries} companyId={companyId} />
    </div>
  )
}

// ---- Helpers ----

function KpiCard({ icon: Icon, label, value, color, bg }: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string | number
  color: string
  bg: string
}) {
  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardContent className="flex items-center gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full" style={{ background: bg }}>
          <Icon className={`h-6 w-6 ${color}`} />
        </div>
        <div>
          <p className="text-2xl font-bold tracking-tight">{typeof value === 'number' ? value.toLocaleString('ru-RU') : value}</p>
          <p className="text-sm text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function formatDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}с`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}мин`
  return `${(ms / 3_600_000).toFixed(1)}ч`
}
