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
import { Check, Trash2, Send } from 'lucide-react'
import type { DataEntry } from '@/types'

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface MetadataPanelProps {
  entry: DataEntry
  onVerify?: () => void
  onTransfer?: () => void
  onDelete?: () => void
}

export function MetadataPanel({ entry, onVerify, onTransfer, onDelete }: MetadataPanelProps) {
  const metadataEntries = Object.entries(entry.metadata).filter(([k]) => k !== 'rejectReason')
  const rejectReason = entry.metadata.rejectReason

  return (
    <Card>
      <CardHeader className="border-b pb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <CardTitle className="text-base flex-1">{entry.title}</CardTitle>
          <StatusBadge status={entry.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Reject reason */}
        {rejectReason && (
          <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/5 text-sm">
            <span className="text-red-400 font-medium">Причина отклонения:</span>{' '}
            <span>{rejectReason}</span>
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
