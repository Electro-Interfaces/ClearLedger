import { useEntries } from '@/hooks/useEntries'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

const STATUS_CONFIG = [
  { key: 'new', label: 'Новые', color: 'hsl(217 91% 60%)' },
  { key: 'recognized', label: 'Распознаны', color: 'hsl(45 100% 55%)' },
  { key: 'verified', label: 'Проверены', color: 'hsl(120 100% 40%)' },
  { key: 'transferred', label: 'Переданы', color: 'hsl(280 65% 60%)' },
  { key: 'error', label: 'Ошибки', color: 'hsl(0 84% 60%)' },
] as const

export function StatusFunnel() {
  const { data: entries = [] } = useEntries()
  const navigate = useNavigate()

  const counts = useMemo(() => {
    const map: Record<string, number> = {}
    for (const e of entries) {
      map[e.status] = (map[e.status] || 0) + 1
    }
    return map
  }, [entries])

  const total = entries.length
  if (total === 0) return null

  const maxCount = Math.max(...STATUS_CONFIG.map((s) => counts[s.key] || 0), 1)

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle>Воронка статусов</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {STATUS_CONFIG.map((s) => {
          const count = counts[s.key] || 0
          const pct = Math.round((count / total) * 100)
          const barWidth = Math.max((count / maxCount) * 100, 2)
          return (
            <div
              key={s.key}
              className="cursor-pointer group"
              onClick={() => {
                if (s.key === 'new' || s.key === 'recognized') navigate('/inbox')
                else navigate(`/search?q=`)
              }}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium group-hover:text-foreground transition-colors">
                  {s.label}
                </span>
                <span className="text-sm text-muted-foreground">
                  {count} ({pct}%)
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-muted/50 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${barWidth}%`, backgroundColor: s.color }}
                />
              </div>
            </div>
          )
        })}
        <div className="text-xs text-muted-foreground pt-1 text-right">
          Всего: {total}
        </div>
      </CardContent>
    </Card>
  )
}
