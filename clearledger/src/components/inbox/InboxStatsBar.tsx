import { useMemo } from 'react'
import { Inbox, Sparkles, Eye, CalendarDays } from 'lucide-react'
import type { DataEntry } from '@/types'

interface InboxStatsBarProps {
  entries: DataEntry[]
}

export function InboxStatsBar({ entries }: InboxStatsBarProps) {
  const stats = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    let newCount = 0
    let recognizedCount = 0
    let todayCount = 0

    for (const e of entries) {
      if (e.status === 'new') newCount++
      if (e.status === 'recognized') recognizedCount++
      if (e.createdAt.slice(0, 10) === today) todayCount++
    }

    return {
      total: entries.length,
      newCount,
      recognizedCount,
      todayCount,
    }
  }, [entries])

  const cards = [
    { icon: Inbox, value: stats.total, label: 'Всего', color: 'text-foreground' },
    { icon: Sparkles, value: stats.newCount, label: 'Новых', color: 'text-blue-500' },
    { icon: Eye, value: stats.recognizedCount, label: 'Распознано', color: 'text-yellow-500' },
    { icon: CalendarDays, value: stats.todayCount, label: 'Сегодня', color: 'text-green-500' },
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
