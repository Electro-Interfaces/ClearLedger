import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { DocumentStats, StatsBreakdown } from './raw-panel-types'

interface Props {
  stats: DocumentStats
}

function KpiCard({ value, label }: { value: number; label: string }) {
  return (
    <Card>
      <CardContent className="p-3 text-center">
        <div className="text-2xl font-bold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  )
}

function BreakdownSection({ title, items }: { title: string; items: StatsBreakdown[] }) {
  const [open, setOpen] = useState(true)

  if (items.length === 0) return null

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-2 w-full py-1.5 text-sm font-medium hover:text-foreground transition-colors">
        <ChevronDown className={`h-4 w-4 transition-transform ${open ? '' : '-rotate-90'}`} />
        {title}
        <span className="ml-auto text-xs text-muted-foreground">{items.length}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-2.5 pl-6 pb-2">
          {items.map((item) => (
            <div key={item.label} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span className="truncate">{item.label}</span>
                <span className="text-muted-foreground text-xs tabular-nums shrink-0 ml-2">
                  {item.count} док. {item.percent > 0 && <span className="text-muted-foreground/60">({item.percent}%)</span>}
                </span>
              </div>
              <Progress value={item.percent} className="h-1.5" />
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function RawPanelStatsTab({ stats }: Props) {
  // Derive status KPIs
  const closed = stats.byStatus.find((s) => s.label === 'Закрыта')?.count ?? 0
  const open = stats.byStatus.find((s) => s.label === 'Открыта')?.count ?? 0
  const draft = stats.byStatus.find((s) => s.label === 'Черновик')?.count ?? 0

  return (
    <div className="space-y-5">
      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-2">
        <KpiCard value={stats.total} label="Всего" />
        <KpiCard value={closed} label="Закрыто" />
        <KpiCard value={open} label="Открыто" />
        <KpiCard value={draft || stats.total - closed - open} label="Прочие" />
      </div>

      {/* Breakdowns */}
      <BreakdownSection title="По категориям" items={stats.byCategory} />
      <BreakdownSection title="По объектам" items={stats.byObject} />
      <BreakdownSection title="По месяцам" items={stats.byMonth} />
      <BreakdownSection title="По источникам" items={stats.bySource} />
    </div>
  )
}
