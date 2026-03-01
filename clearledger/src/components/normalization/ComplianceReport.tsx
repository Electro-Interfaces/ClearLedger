/**
 * Список compliance-находок — dark-safe цвета через HSL и semantic badge.
 */

import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { AlertOctagon, AlertTriangle, Info } from 'lucide-react'
import type { ComplianceFinding } from '@/types'

interface Props {
  findings: ComplianceFinding[]
}

const severityOrder: Record<string, number> = { critical: 0, warning: 1, info: 2 }

const severityConfig = {
  critical: {
    icon: AlertOctagon,
    iconBg: 'hsl(0 84% 60% / 0.15)',
    iconColor: 'text-red-500',
    badgeClass: 'border-red-500 text-red-400',
    label: 'Критично',
  },
  warning: {
    icon: AlertTriangle,
    iconBg: 'hsl(45 100% 55% / 0.15)',
    iconColor: 'text-yellow-500',
    badgeClass: 'border-yellow-500 text-yellow-400',
    label: 'Внимание',
  },
  info: {
    icon: Info,
    iconBg: 'hsl(217 91% 60% / 0.15)',
    iconColor: 'text-blue-500',
    badgeClass: 'border-blue-500 text-blue-400',
    label: 'Информация',
  },
} as const

const categoryLabels: Record<string, string> = {
  bundle_inconsistency: 'Бандлы',
  amount_duplicate: 'Дубли сумм',
  numbering_gap: 'Нумерация',
}

export function ComplianceReport({ findings }: Props) {
  const [filterCategory, setFilterCategory] = useState<string | null>(null)

  const categories = useMemo(() => {
    const cats = new Map<string, number>()
    for (const f of findings) {
      cats.set(f.category, (cats.get(f.category) || 0) + 1)
    }
    return cats
  }, [findings])

  const sorted = useMemo(() => {
    let items = findings
    if (filterCategory) {
      items = items.filter((f) => f.category === filterCategory)
    }
    return [...items].sort(
      (a, b) => (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9),
    )
  }, [findings, filterCategory])

  if (findings.length === 0) {
    return (
      <div className="text-center text-muted-foreground py-12">
        Нет находок — запустите нормализацию
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge
          variant={filterCategory === null ? 'default' : 'outline'}
          className="cursor-pointer"
          onClick={() => setFilterCategory(null)}
        >
          Все ({findings.length})
        </Badge>
        {[...categories.entries()].map(([cat, count]) => (
          <Badge
            key={cat}
            variant={filterCategory === cat ? 'default' : 'outline'}
            className="cursor-pointer"
            onClick={() => setFilterCategory(filterCategory === cat ? null : cat)}
          >
            {categoryLabels[cat] || cat} ({count})
          </Badge>
        ))}
      </div>

      <div className="space-y-3">
        {sorted.map((f) => {
          const cfg = severityConfig[f.severity] || severityConfig.info
          const Icon = cfg.icon
          return (
            <Card key={f.id}>
              <CardContent className="flex items-start gap-3">
                <div
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                  style={{ background: cfg.iconBg }}
                >
                  <Icon className={`size-4 ${cfg.iconColor}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-sm text-foreground">{f.title}</p>
                    <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${cfg.badgeClass}`}>
                      {cfg.label}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mt-0.5">{f.description}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Затронуто записей: {f.affectedEntryIds.length}
                  </p>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <p className="text-xs text-muted-foreground">Показано {sorted.length} из {findings.length}</p>
    </div>
  )
}
