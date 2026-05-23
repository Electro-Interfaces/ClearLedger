/**
 * 4 KPI-карточки сверки: сопоставлено / без оригинала / без проводки / расхождения.
 */

import { Card, CardContent } from '@/components/ui/card'
import { CheckCircle, FileQuestion, FileMinus, AlertTriangle } from 'lucide-react'
import type { ReconciliationSummary as SummaryType } from '@/types'

interface Props {
  summary: SummaryType
}

export function ReconciliationSummaryCards({ summary }: Props) {
  const cards = [
    {
      label: 'Сопоставлено',
      value: summary.matched,
      icon: CheckCircle,
      color: 'text-green-600',
      bg: 'bg-green-50',
    },
    {
      label: 'Без оригинала',
      value: summary.unmatchedAcc,
      icon: FileQuestion,
      color: 'text-orange-600',
      bg: 'bg-orange-50',
    },
    {
      label: 'Без проводки',
      value: summary.unmatchedEntry,
      icon: FileMinus,
      color: 'text-blue-600',
      bg: 'bg-blue-50',
    },
    {
      label: 'Расхождения',
      value: summary.discrepancy,
      icon: AlertTriangle,
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="pt-4 pb-3 px-4">
            <div className="flex items-center gap-3">
              <div className={`rounded-lg p-2 ${card.bg}`}>
                <card.icon className={`size-5 ${card.color}`} />
              </div>
              <div>
                <p className="text-2xl font-bold">{card.value}</p>
                <p className="text-xs text-muted-foreground">{card.label}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
