import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime } from '@/lib/formatDate'
import type { DataEntry } from '@/types'
import type { EntryStatus } from '@/config/statuses'

const statusOrder: EntryStatus[] = ['new', 'recognized', 'verified', 'transferred']
const statusLabels: Record<EntryStatus, string> = {
  new: 'Создан',
  recognized: 'Распознан',
  verified: 'Проверен',
  transferred: 'Передан',
  error: 'Ошибка',
}

interface TimelineEvent {
  status: EntryStatus
  label: string
  date: string
  active: boolean
}

function buildTimeline(entry: DataEntry): TimelineEvent[] {
  const events: TimelineEvent[] = []
  const currentIndex = statusOrder.indexOf(entry.status)

  // "new" always happened at createdAt
  events.push({
    status: 'new',
    label: statusLabels.new,
    date: entry.createdAt,
    active: true,
  })

  // For error status, show the error event
  if (entry.status === 'error') {
    events.push({
      status: 'error',
      label: statusLabels.error,
      date: entry.updatedAt,
      active: true,
    })
    return events
  }

  // For each subsequent status up to current, show as active with updatedAt
  for (let i = 1; i < statusOrder.length; i++) {
    const s = statusOrder[i]
    if (i <= currentIndex) {
      events.push({
        status: s,
        label: statusLabels[s],
        date: entry.updatedAt,
        active: true,
      })
    }
  }

  return events
}

interface HistoryTimelineProps {
  entry: DataEntry
}

export function HistoryTimeline({ entry }: HistoryTimelineProps) {
  const events = buildTimeline(entry)

  return (
    <Card>
      <CardHeader className="border-b pb-4">
        <CardTitle className="text-base">История</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="relative pl-6">
          {/* Vertical line */}
          <div className="absolute left-[9px] top-2 bottom-2 w-px bg-border" />

          <div className="space-y-4">
            {events.map((event, i) => (
              <div key={`${event.status}-${i}`} className="relative flex items-start gap-3">
                {/* Dot */}
                <div
                  className={`absolute -left-6 top-1.5 size-[9px] rounded-full ring-2 ring-background ${
                    event.status === 'error'
                      ? 'bg-destructive'
                      : event.active
                        ? 'bg-primary'
                        : 'bg-muted-foreground/30'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{event.label}</p>
                  <p className="text-xs text-muted-foreground">{formatDateTime(event.date)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
