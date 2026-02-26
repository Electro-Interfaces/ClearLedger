/**
 * ActivityChart — график активности за последние 14 дней.
 * Показывает количество загруженных и верифицированных записей по дням.
 */

import { useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useEntries } from '@/hooks/useEntries'

const DAYS = 14

function formatDay(date: Date): string {
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

function dateKey(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function ActivityChart() {
  const { data: entries = [] } = useEntries()

  const { days, maxValue } = useMemo(() => {
    const now = new Date()
    const buckets: Array<{ label: string; uploaded: number; verified: number }> = []

    for (let i = DAYS - 1; i >= 0; i--) {
      const d = new Date(now)
      d.setDate(d.getDate() - i)
      const key = dateKey(d)
      const uploaded = entries.filter((e) => e.createdAt.startsWith(key)).length
      const verified = entries.filter(
        (e) => (e.status === 'verified' || e.status === 'transferred') && e.updatedAt.startsWith(key),
      ).length
      buckets.push({ label: formatDay(d), uploaded, verified })
    }

    const max = Math.max(1, ...buckets.map((b) => Math.max(b.uploaded, b.verified)))
    return { days: buckets, maxValue: max }
  }, [entries])

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Активность за 14 дней</span>
          <div className="flex items-center gap-4 text-xs font-normal text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-blue-500" />
              Загружено
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-green-500" />
              Проверено
            </span>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-1 h-32">
          {days.map((day, i) => (
            <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
              <div className="w-full flex gap-px justify-center" style={{ height: '100px' }}>
                <div
                  className="w-[40%] bg-blue-500/80 rounded-t-sm transition-all"
                  style={{ height: `${(day.uploaded / maxValue) * 100}%`, minHeight: day.uploaded > 0 ? '2px' : 0 }}
                  title={`Загружено: ${day.uploaded}`}
                />
                <div
                  className="w-[40%] bg-green-500/80 rounded-t-sm transition-all"
                  style={{ height: `${(day.verified / maxValue) * 100}%`, minHeight: day.verified > 0 ? '2px' : 0 }}
                  title={`Проверено: ${day.verified}`}
                />
              </div>
              {i % 2 === 0 && (
                <span className="text-[9px] text-muted-foreground whitespace-nowrap">{day.label}</span>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
