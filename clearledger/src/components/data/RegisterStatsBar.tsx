import { useMemo } from 'react'
import { FileText, BookOpen, Clock, Upload, CheckCircle2 } from 'lucide-react'
import type { DataEntry } from '@/types'

interface RegisterStatsBarProps {
  entries: DataEntry[]
}

export function RegisterStatsBar({ entries }: RegisterStatsBarProps) {
  const stats = useMemo(() => {
    let accounting = 0
    let pending = 0
    let exported = 0
    let confirmed = 0

    for (const e of entries) {
      if (e.docPurpose === 'accounting') accounting++
      if (e.syncStatus === 'pending') pending++
      if (e.syncStatus === 'exported') exported++
      if (e.syncStatus === 'confirmed') confirmed++
    }

    return { total: entries.length, accounting, pending, exported, confirmed }
  }, [entries])

  const cards = [
    { icon: FileText, value: stats.total, label: 'Всего', color: 'text-foreground' },
    { icon: BookOpen, value: stats.accounting, label: 'Бухгалтерских', color: 'text-blue-500' },
    { icon: Clock, value: stats.pending, label: 'Ожидают выгрузки', color: 'text-yellow-500' },
    { icon: Upload, value: stats.exported, label: 'Выгружено', color: 'text-orange-500' },
    { icon: CheckCircle2, value: stats.confirmed, label: 'Подтверждено 1С', color: 'text-green-500' },
  ]

  return (
    <div className="flex flex-wrap gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/30 border"
        >
          <card.icon className={`size-4 ${card.color}`} />
          <span className={`text-sm font-semibold ${card.color}`}>{card.value}</span>
          <span className="text-xs text-muted-foreground">{card.label}</span>
        </div>
      ))}
    </div>
  )
}
