/**
 * SLA по заявкам за период (из timesheet): % в срок, время реакции/выполнения,
 * перцентили; разрез по критичности / подрядчику / виду заявки.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Gauge, CheckCircle2, Timer, Wrench } from 'lucide-react'
import { getSla, type NetFilters } from '@/services/netServiceService'

const BREAKDOWNS = [
  { v: 'criticality', label: 'По критичности' },
  { v: 'contractor', label: 'По подрядчику' },
  { v: 'task_type', label: 'По виду заявки' },
]

function fmtDur(sec: number | null): string {
  if (sec == null) return '—'
  const h = Math.floor(sec / 3600)
  const m = Math.round((sec % 3600) / 60)
  if (h >= 24) { const d = Math.floor(h / 24); return `${d}д ${h % 24}ч` }
  if (h > 0) return `${h}ч ${m}м`
  return `${m}м`
}

function slaColor(pct: number | null): string {
  if (pct == null) return '#9ca3af'
  if (pct >= 90) return '#10b981'
  if (pct >= 70) return '#f59e0b'
  return '#ef4444'
}

function Kpi({ icon: Icon, label, value, tone }: {
  icon: React.ComponentType<{ className?: string }>; label: string; value: string; tone?: string
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={`flex h-11 w-11 items-center justify-center rounded-full ${tone ?? 'bg-muted'}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-2xl font-bold tabular-nums">{value}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export function SlaDashboard({ companyId, filters }: { companyId: string; filters: NetFilters }) {
  const [breakdown, setBreakdown] = useState('criticality')
  const { data, isLoading } = useQuery({
    queryKey: ['netservice', 'sla', companyId, filters, breakdown],
    queryFn: () => getSla(companyId, filters, breakdown),
    enabled: !!companyId,
  })

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  if (!data) return <div className="p-6 text-sm text-muted-foreground">Нет данных. Запустите синхронизацию.</div>

  const t = data.totals
  const chart = data.rows.filter((r) => r.slaPct != null).slice(0, 12)

  return (
    <div className="p-5 space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi icon={Gauge} label="Соблюдение SLA" value={t.slaPct != null ? `${t.slaPct}%` : '—'}
          tone="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" />
        <Kpi icon={CheckCircle2} label="Завершено заявок" value={t.completed.toLocaleString('ru-RU')} />
        <Kpi icon={Timer} label="Ср. время реакции" value={fmtDur(t.avgReactionSec)} />
        <Kpi icon={Wrench} label="Ср. время выполнения" value={fmtDur(t.avgWorkSec)} />
      </div>

      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Разрез:</span>
        <Select value={breakdown} onValueChange={setBreakdown}>
          <SelectTrigger className="h-8 w-[190px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {BREAKDOWNS.map((b) => <SelectItem key={b.v} value={b.v}>{b.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Соблюдение SLA, %</CardTitle></CardHeader>
        <CardContent>
          {chart.length === 0 ? <p className="text-sm text-muted-foreground py-6 text-center">Нет завершённых заявок за период.</p> : (
            <ResponsiveContainer width="100%" height={Math.max(180, chart.length * 32)}>
              <BarChart data={chart} layout="vertical" margin={{ left: 8, right: 24 }}>
                <XAxis type="number" domain={[0, 100]} hide />
                <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => [`${v}%`, 'SLA']} />
                <Bar dataKey="slaPct" radius={[0, 6, 6, 0]} barSize={18}>
                  {chart.map((r, i) => <Cell key={i} fill={slaColor(r.slaPct)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Детализация</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{BREAKDOWNS.find((b) => b.v === breakdown)?.label.replace('По ', '') ?? ''}</TableHead>
                <TableHead className="text-right">Всего</TableHead>
                <TableHead className="text-right">Заверш.</TableHead>
                <TableHead className="text-right">SLA</TableHead>
                <TableHead className="text-right hidden sm:table-cell">Медиана</TableHead>
                <TableHead className="text-right hidden md:table-cell">p90</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow key={r.name}>
                  <TableCell className="max-w-[260px] truncate">{r.name}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.total.toLocaleString('ru-RU')}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.completed.toLocaleString('ru-RU')}</TableCell>
                  <TableCell className="text-right tabular-nums font-medium" style={{ color: slaColor(r.slaPct) }}>
                    {r.slaPct != null ? `${r.slaPct}%` : '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums hidden sm:table-cell">{fmtDur(r.p50WorkSec)}</TableCell>
                  <TableCell className="text-right tabular-nums hidden md:table-cell">{fmtDur(r.p90WorkSec)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
