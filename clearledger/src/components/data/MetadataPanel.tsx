import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { StatusBadge } from './StatusBadge'
import { SourceBadge } from './SourceBadge'
import { formatDateTime } from '@/lib/formatDate'
import { Check, Trash2, Send, Archive, ArchiveRestore, EyeOff, Eye, ChevronDown, ChevronUp, History } from 'lucide-react'
import { useEntryAudit } from '@/hooks/useAudit'
import type { DataEntry, AuditAction } from '@/types'
import type { ValidationResult } from '@/services/validationService'

const auditActionLabels: Record<AuditAction, string> = {
  created: 'Создан',
  verified: 'Верифицирован',
  rejected: 'Отклонён',
  transferred: 'Передан',
  archived: 'Архивирован',
  restored: 'Восстановлен',
  excluded: 'Исключён',
  included: 'Возвращён',
  updated: 'Обновлён',
  version_created: 'Новая версия',
  exported: 'Экспортирован',
  bulk_archived: 'Массовая архивация',
  bulk_excluded: 'Массовое исключение',
  connector_synced: 'Синхронизация',
}

interface MetadataPanelProps {
  entry: DataEntry
  onVerify?: () => void
  onTransfer?: () => void
  onDelete?: () => void
  onArchive?: () => void
  onRestore?: () => void
  onExclude?: () => void
  onInclude?: () => void
  validation?: ValidationResult
}

export function MetadataPanel({
  entry, onVerify, onTransfer, onDelete,
  onArchive, onRestore, onExclude, onInclude,
  validation,
}: MetadataPanelProps) {
  const metadataEntries = Object.entries(entry.metadata).filter(([k]) => k !== 'rejectReason' && !k.startsWith('_'))
  const { data: auditEvents = [] } = useEntryAudit(entry.id)
  const [auditOpen, setAuditOpen] = useState(false)
  const recentAudit = auditEvents.slice(-5).reverse()
  const rejectReason = entry.metadata.rejectReason
  const isExcluded = entry.metadata._excluded === 'true'

  return (
    <Card>
      <CardHeader className="border-b pb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <CardTitle className="text-base flex-1">{entry.title}</CardTitle>
          <StatusBadge status={entry.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Excluded banner */}
        {isExcluded && (
          <div className="p-3 rounded-lg border border-yellow-500/30 bg-yellow-500/5 text-sm">
            <span className="text-yellow-400 font-medium">Исключён из анализа</span>
          </div>
        )}

        {/* Reject reason */}
        {rejectReason && (
          <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/5 text-sm">
            <span className="text-red-400 font-medium">Причина отклонения:</span>{' '}
            <span>{rejectReason}</span>
          </div>
        )}

        {/* Validation badge */}
        {validation && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">Валидация</span>
              {validation.issues.length === 0 ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 text-green-400 border border-green-500/30">Корректен</span>
              ) : validation.issues.some((i) => i.severity === 'error') ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/30">Ошибки ({validation.issues.filter((i) => i.severity === 'error').length})</span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400 border border-yellow-500/30">Предупреждения ({validation.issues.length})</span>
              )}
              <span className="text-xs text-muted-foreground ml-auto">{validation.completeness}%</span>
            </div>
            {validation.issues.length > 0 && (
              <div className="space-y-1 text-xs">
                {validation.issues.map((issue, idx) => (
                  <div key={idx} className={`flex gap-1 ${issue.severity === 'error' ? 'text-red-400' : 'text-yellow-400'}`}>
                    <span>{issue.severity === 'error' ? '✗' : '⚠'}</span>
                    <span>{issue.label}: {issue.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Metadata fields */}
        {metadataEntries.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">Метаданные</h4>
            <div className="space-y-1.5">
              {metadataEntries.map(([key, value]) => (
                <div key={key} className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground capitalize">{key}</span>
                  <span className="font-medium text-right max-w-[60%] truncate">{value}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <Separator />

        {/* Info */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Информация</h4>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Источник</span>
              <SourceBadge source={entry.source} />
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Создан</span>
              <span className="font-medium">{formatDateTime(entry.createdAt)}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Обновлён</span>
              <span className="font-medium">{formatDateTime(entry.updatedAt)}</span>
            </div>
          </div>
        </div>

        {/* Audit journal */}
        {recentAudit.length > 0 && (
          <>
            <Separator />
            <div className="space-y-2">
              <button
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground w-full hover:text-foreground transition-colors"
                onClick={() => setAuditOpen(!auditOpen)}
              >
                <History className="size-4" />
                <span className="flex-1 text-left">Журнал изменений</span>
                {auditOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
              </button>
              {auditOpen && (
                <div className="space-y-1.5 text-xs">
                  {recentAudit.map((ev) => (
                    <div key={ev.id} className="flex items-start justify-between gap-2">
                      <div>
                        <span className="font-medium">{auditActionLabels[ev.action] ?? ev.action}</span>
                        {ev.details && <span className="text-muted-foreground ml-1">({ev.details})</span>}
                      </div>
                      <span className="text-muted-foreground whitespace-nowrap">{formatDateTime(ev.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        <Separator />

        {/* Actions */}
        <div className="flex flex-col gap-2">
          {onVerify && (
            <Button variant="outline" size="sm" className="w-full justify-start" onClick={onVerify}>
              <Check />
              Верифицировать
            </Button>
          )}
          {onTransfer && (
            <Button variant="outline" size="sm" className="w-full justify-start" onClick={onTransfer}>
              <Send />
              Передать на Слой 2
            </Button>
          )}

          {/* Exclude / Include toggle */}
          {onExclude && !isExcluded && (
            <Button variant="outline" size="sm" className="w-full justify-start text-yellow-500 hover:text-yellow-400" onClick={onExclude}>
              <EyeOff />
              Исключить из анализа
            </Button>
          )}
          {onInclude && isExcluded && (
            <Button variant="outline" size="sm" className="w-full justify-start text-yellow-500 hover:text-yellow-400" onClick={onInclude}>
              <Eye />
              Вернуть в анализ
            </Button>
          )}

          {/* Archive (replaces hard-delete as primary action) */}
          {onArchive && entry.status !== 'archived' && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm" className="w-full justify-start">
                  <Archive />
                  В архив
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Архивировать запись?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Запись &laquo;{entry.title}&raquo; будет перемещена в архив. Её можно восстановить позже.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Отмена</AlertDialogCancel>
                  <AlertDialogAction onClick={onArchive}>В архив</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {/* Restore from archive */}
          {onRestore && entry.status === 'archived' && (
            <Button variant="outline" size="sm" className="w-full justify-start" onClick={onRestore}>
              <ArchiveRestore />
              Восстановить из архива
            </Button>
          )}

          {onDelete && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full justify-start text-destructive hover:text-destructive"
                >
                  <Trash2 />
                  Удалить
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Удалить запись?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Запись &laquo;{entry.title}&raquo; будет удалена. Это действие нельзя отменить.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Отмена</AlertDialogCancel>
                  <AlertDialogAction onClick={onDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Удалить
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
