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
      iconBg: 'hsl(217 91% 60% / 0.15)',
      iconColor: 'text-blue-500',
    },
    {
      label: 'Валидация',
      value: `${summary.validPercent}%`,
      icon: CheckCircle,
      iconBg: 'hsl(120 100% 40% / 0.15)',
      iconColor: 'text-green-500',
    },
    {
      label: 'Обогащение',
      value: `${summary.enrichedPercent}%`,
      icon: Sparkles,
      iconBg: 'hsl(280 100% 65% / 0.15)',
      iconColor: 'text-purple-500',
    },
    {
      label: 'Находки',
      value: summary.complianceFindings,
      icon: AlertTriangle,
      iconBg: summary.criticalFindings > 0 ? 'hsl(0 84% 60% / 0.15)' : 'hsl(45 100% 55% / 0.15)',
      iconColor: summary.criticalFindings > 0 ? 'text-red-500' : 'text-yellow-500',
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
