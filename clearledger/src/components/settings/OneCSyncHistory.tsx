/**
 * История синхронизаций 1С — таблица с раскрытием деталей.
 */

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronRight, Clock, ArrowDownToLine, ArrowUpFromLine } from 'lucide-react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { useSyncHistory } from '@/hooks/useOneCSync'
import type { OneCSyncLog } from '@/types'

interface Props {
  connectionId: string
}

export function OneCSyncHistory({ connectionId }: Props) {
  const { data: logs, isLoading } = useSyncHistory(connectionId)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (isLoading || !logs?.length) return null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
            <Clock className="size-5 text-violet-500" />
          </div>
          <div>
            <CardTitle>История синхронизаций</CardTitle>
            <CardDescription>Последние {logs.length} операций</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-1">
          {logs.map((log) => (
            <LogRow
              key={log.id}
              log={log}
              isExpanded={expandedId === log.id}
              onToggle={() => setExpandedId(expandedId === log.id ? null : log.id)}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function LogRow({
  log,
  isExpanded,
  onToggle,
}: {
  log: OneCSyncLog
  isExpanded: boolean
  onToggle: () => void
}) {
  const statusVariants: Record<string, 'default' | 'secondary' | 'destructive'> = {
    success: 'default',
    running: 'secondary',
    error: 'destructive',
  }

  const typeLabels: Record<string, string> = {
    catalogs: 'Справочники',
    documents: 'Документы',
    full: 'Полная',
    export: 'Экспорт',
  }

  return (
    <div className="border rounded-lg">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-muted/50 transition-colors"
      >
        {isExpanded ? (
          <ChevronDown className="size-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="size-4 text-muted-foreground shrink-0" />
        )}

        {log.direction === 'inbound' ? (
          <ArrowDownToLine className="size-4 text-blue-500 shrink-0" />
        ) : (
          <ArrowUpFromLine className="size-4 text-orange-500 shrink-0" />
        )}

        <span className="text-sm text-muted-foreground shrink-0 w-36">
          {format(new Date(log.startedAt), 'dd MMM yyyy HH:mm', { locale: ru })}
        </span>

        <span className="text-sm font-medium shrink-0">
          {typeLabels[log.syncType] ?? log.syncType}
        </span>

        <div className="flex-1" />

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {log.itemsCreated > 0 && <span className="text-green-500">+{log.itemsCreated}</span>}
          {log.itemsUpdated > 0 && <span className="text-blue-500">~{log.itemsUpdated}</span>}
          {log.itemsErrors > 0 && <span className="text-red-500">!{log.itemsErrors}</span>}
        </div>

        <Badge variant={statusVariants[log.status] ?? 'secondary'} className="shrink-0">
          {log.status === 'success' ? 'OK' : log.status === 'running' ? '...' : 'Ошибка'}
        </Badge>
      </button>

      {isExpanded && (
        <div className="px-3 pb-3 pt-0 border-t">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Обработано</p>
              <p className="font-medium">{log.itemsProcessed}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Создано</p>
              <p className="font-medium text-green-600">{log.itemsCreated}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Обновлено</p>
              <p className="font-medium text-blue-600">{log.itemsUpdated}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Ошибок</p>
              <p className={`font-medium ${log.itemsErrors > 0 ? 'text-red-600' : ''}`}>{log.itemsErrors}</p>
            </div>
          </div>

          {log.finishedAt && (
            <p className="text-xs text-muted-foreground mt-2">
              Завершено: {format(new Date(log.finishedAt), 'dd.MM.yyyy HH:mm:ss', { locale: ru })}
              {' '}({Math.round((new Date(log.finishedAt).getTime() - new Date(log.startedAt).getTime()) / 1000)}с)
            </p>
          )}

          {log.details && Object.keys(log.details).length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
                Подробности
              </summary>
              <pre className="mt-1 text-xs bg-muted rounded p-2 overflow-auto max-h-48">
                {JSON.stringify(log.details, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
