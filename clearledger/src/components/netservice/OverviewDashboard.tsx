/**
 * Обзор сети — состояние сервиса: KPI, карта заявок, разбивки по региону/
 * критичности, воронка стадий, топ проблемных объектов (drill-down в станцию).
 */
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Loader2, ClipboardList, AlertTriangle, Clock, UserX } from 'lucide-react'
import {
  getNetworkHealth, getAssetReliability, type NetFilters,
} from '@/services/netServiceService'
import { NetworkMap } from './NetworkMap'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16']

function Kpi({ icon: Icon, label, value, tone }: {
  icon: React.ComponentType<{ className?: string }>; label: string; value: number; tone?: string
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={`flex h-11 w-11 items-center justify-center rounded-full ${tone ?? 'bg-muted'}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-2xl font-bold tabular-nums">{value.toLocaleString('ru-RU')}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export function OverviewDashboard({ companyId, filters, onOpenStation }: {
  companyId: string
  filters: NetFilters
  onOpenStation: (locationId: string | null) => void
}) {
  const healthQ = useQuery({
    queryKey: ['netservice', 'health', companyId, filters],
    queryFn: () => getNetworkHealth(companyId, filters),
    enabled: !!companyId,
  })
  const relQ = useQuery({
    queryKey: ['netservice', 'reliability', companyId, filters, 8],
    queryFn: () => getAssetReliability(companyId, filters, 8),
    enabled: !!companyId,
  })

  if (healthQ.isLoading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  const h = healthQ.data
  if (!h) return <div className="p-6 text-sm text-muted-foreground">Нет данных. Запустите синхронизацию.</div>

  const region = h.byRegion.slice(0, 10)
  const top = relQ.data?.topProblematic ?? []

  return (
    <div className="p-5 space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi icon={ClipboardList} label="Открытых заявок" value={h.kpi.open} tone="bg-blue-500/15 text-blue-600 dark:text-blue-400" />
        <Kpi icon={AlertTriangle} label="Просрочено по SLA" value={h.kpi.overdue} tone="bg-red-500/15 text-red-600 dark:text-red-400" />
        <Kpi icon={UserX} label="Без исполнителя" value={h.kpi.unassigned} tone="bg-amber-500/15 text-amber-600 dark:text-amber-400" />
        <Kpi icon={Clock} label="Всего заявок" value={h.kpi.total} />
      </div>

      <NetworkMap points={h.points} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Открытые по регионам</CardTitle></CardHeader>
          <CardContent>
            {region.length === 0 ? <p className="text-sm text-muted-foreground py-6 text-center">Нет данных.</p> : (
              <ResponsiveContainer width="100%" height={Math.max(180, region.length * 30)}>
                <BarChart data={region} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    formatter={(v) => [Number(v).toLocaleString('ru-RU'), 'Заявок']} />
                  <Bar dataKey="n" radius={[0, 6, 6, 0]} barSize={18}>
                    {region.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Открытые по критичности</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {h.byCriticality.length === 0 ? <p className="text-sm text-muted-foreground py-6 text-center">Нет данных.</p> :
              h.byCriticality.map((c) => (
                <div key={c.name} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: c.color ? `#${c.color}` : 'hsl(var(--muted-foreground))' }} />
                    {c.name}
                  </span>
                  <span className="font-medium tabular-nums">{c.n.toLocaleString('ru-RU')}</span>
                </div>
              ))}
            <div className="border-t border-border/40 pt-2 mt-2 text-xs font-medium text-muted-foreground">Воронка стадий</div>
            {h.funnel.slice(0, 6).map((s) => (
              <div key={s.stage} className="flex items-center justify-between text-sm">
                <span className="truncate text-muted-foreground">{s.stage}</span>
                <span className="font-medium tabular-nums ml-2">{s.n.toLocaleString('ru-RU')}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Топ проблемных объектов за период</CardTitle></CardHeader>
        <CardContent className="space-y-1">
          {top.length === 0 ? <p className="text-sm text-muted-foreground py-6 text-center">Нет данных.</p> :
            top.map((a) => (
              <button key={a.asset_id}
                onClick={() => onOpenStation(a.location_id)}
                className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm hover:bg-secondary/50 transition-colors">
                <span className="truncate">{a.asset_name || `Объект ${a.asset_id}`}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {a.total} заявок{a.incidents > 0 && ` · ав. ${a.incidents}`}
                </span>
              </button>
            ))}
        </CardContent>
      </Card>
    </div>
  )
}
