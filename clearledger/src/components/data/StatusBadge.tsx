import { Badge } from '@/components/ui/badge'
import { statuses, type EntryStatus } from '@/config/statuses'

export function StatusBadge({ status }: { status: EntryStatus }) {
  const config = statuses[status]
  return (
    <Badge variant={config.variant} className={config.className}>
      {config.label}
    </Badge>
  )
}
