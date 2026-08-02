/**
 * 4 KPI-карточки нормализации: ожидают / валидация / обогащение / находки.
 * Паттерн: hsl() с opacity для фона иконок, text-{color}-500 для цвета — работает в dark mode.
 */

import { Card, CardContent } from '@/components/ui/card'
import { FileSearch, CheckCircle, Sparkles, AlertTriangle } from 'lucide-react'
import type { NormalizationSummary } from '@/types'

interface Props {
  summary: NormalizationSummary
}

export function NormalizationKpiCards({ summary }: Props) {
  const cards = [
    {
      label: 'Ожидают проверки',
      value: summary.pendingCount,
      icon: FileSearch,
      iconBg: 'hsl(var(--chart-1) / 0.12)',
      iconColor: 'text-blue-400/80',
    },
    {
      label: 'Валидация',
      value: `${summary.validPercent}%`,
      icon: CheckCircle,
      iconBg: 'hsl(var(--success) / 0.12)',
      iconColor: 'text-emerald-400/80',
    },
    {
      label: 'Обогащение',
      value: `${summary.enrichedPercent}%`,
      icon: Sparkles,
      iconBg: 'hsl(var(--accent-purple) / 0.12)',
      iconColor: 'text-purple-400/80',
    },
    {
      label: 'Находки',
      value: summary.complianceFindings,
      icon: AlertTriangle,
      iconBg: summary.criticalFindings > 0 ? 'hsl(var(--error) / 0.12)' : 'hsl(var(--warning) / 0.12)',
      iconColor: summary.criticalFindings > 0 ? 'text-red-400/80' : 'text-amber-400/80',
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <Card key={card.label} style={{ boxShadow: 'var(--shadow-soft)' }}>
            <CardContent className="flex items-center gap-4">
              <div
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full"
                style={{ background: card.iconBg }}
              >
                <Icon className={`h-6 w-6 ${card.iconColor}`} />
              </div>
              <div>
                <p className="text-2xl font-bold tracking-tight">{card.value}</p>
                <p className="text-sm text-muted-foreground">{card.label}</p>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
