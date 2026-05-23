/**
 * Компонент журнала аудита для конкретной записи.
 * Используется в InboxDetailPage и DataDetailPage.
 */

import { useEntryAudit } from '@/hooks/useAudit'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { History } from 'lucide-react'
import { formatDateTime } from '@/lib/formatDate'
import type { AuditAction } from '@/types'

interface AuditJournalProps {
  entryId: string
}

const ACTION_LABELS: Record<AuditAction, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  created: { label: 'Создано', variant: 'secondary' },
  verified: { label: 'Верифицировано', variant: 'default' },
  rejected: { label: 'Отклонено', variant: 'destructive' },
  transferred: { label: 'Передано', variant: 'default' },
  archived: { label: 'Архивировано', variant: 'outline' },
  restored: { label: 'Восстановлено', variant: 'secondary' },
  excluded: { label: 'Исключено', variant: 'outline' },
  included: { label: 'Включено', variant: 'secondary' },
  updated: { label: 'Обновлено', variant: 'secondary' },
  version_created: { label: 'Новая версия', variant: 'secondary' },
  exported: { label: 'Экспорт', variant: 'outline' },
  bulk_archived: { label: 'Массовый архив', variant: 'outline' },
  bulk_excluded: { label: 'Массовое исключ.', variant: 'outline' },
  connector_synced: { label: 'Синхронизация', variant: 'secondary' },
}

export function AuditJournal({ entryId }: AuditJournalProps) {
  const { data: events = [], isLoading } = useEntryAudit(entryId)

  // Сортируем от новых к старым
  const sorted = [...events].sort((a, b) => b.timestamp.localeCompare(a.timestamp))

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4" />
          Журнал аудита
          {sorted.length > 0 && (
            <Badge variant="secondary" className="ml-auto text-xs">
              {sorted.length}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="text-sm text-muted-foreground">Загрузка...</div>
        ) : sorted.length === 0 ? (
          <div className="text-sm text-muted-foreground">Нет событий</div>
        ) : (
          <ScrollArea className="max-h-64">
            <div className="space-y-3">
              {sorted.map((event) => {
                const actionConfig = ACTION_LABELS[event.action] ?? { label: event.action, variant: 'outline' as const }
                return (
                  <div key={event.id} className="flex items-start gap-3 text-sm">
                    <div className="shrink-0 pt-0.5">
                      <Badge variant={actionConfig.variant} className="text-[10px] px-1.5 py-0">
                        {actionConfig.label}
                      </Badge>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-xs">{event.userName}</span>
                        <span className="text-xs text-muted-foreground">
                          {formatDateTime(event.timestamp)}
                        </span>
                      </div>
                      {event.details && (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">
                          {event.details}
                        </p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
}
