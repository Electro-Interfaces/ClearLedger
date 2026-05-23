import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime } from '@/lib/formatDate'
import type { DataEntry, AuditEvent } from '@/types'
import type { EntryStatus } from '@/config/statuses'

const statusOrder: EntryStatus[] = ['new', 'recognized', 'verified', 'transferred']
const statusLabels: Record<EntryStatus, string> = {
  new: 'Создан',
  recognized: 'Распознан',
  verified: 'Проверен',
  transferred: 'Передан',
  error: 'Ошибка',
  archived: 'В архиве',
}

const auditActionToStatus: Record<string, EntryStatus> = {
  created: 'new',
  verified: 'verified',
  transferred: 'transferred',
  rejected: 'error',
  archived: 'archived',
}

interface TimelineEvent {
  status: EntryStatus
  label: string
  date: string
  active: boolean
}

function buildTimeline(entry: DataEntry, auditEvents?: AuditEvent[]): TimelineEvent[] {
  // If we have audit events, use real timestamps
  if (auditEvents && auditEvents.length > 0) {
    const events: TimelineEvent[] = []
    const seen = new Set<string>()

    for (const ev of auditEvents) {
      const status = auditActionToStatus[ev.action]
      if (!status || seen.has(status)) continue
      seen.add(status)
      events.push({
        status,
        label: statusLabels[status] ?? ev.action,
        date: ev.timestamp,
        active: true,
      })
    }

    // Ensure at least 'new' event exists
    if (!seen.has('new')) {
      events.unshift({
        status: 'new',
        label: statusLabels.new,
        date: entry.createdAt,
        active: true,
      })
    }

    return events
  }

  // Fallback: approximate timeline from entry status
  const events: TimelineEvent[] = []
  const currentIndex = statusOrder.indexOf(entry.status)

  events.push({
    status: 'new',
    label: statusLabels.new,
    date: entry.createdAt,
    active: true,
  })

  if (entry.status === 'error') {
    events.push({
      status: 'error',
      label: statusLabels.error,
      date: entry.updatedAt,
      active: true,
    })
    return events
  }

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
  auditEvents?: AuditEvent[]
}

export function HistoryTimeline({ entry, auditEvents }: HistoryTimelineProps) {
  const events = buildTimeline(entry, auditEvents)

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
