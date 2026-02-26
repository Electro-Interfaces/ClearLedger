/**
 * IntakeQueue — единая очередь обработки документов.
 * Показывает все элементы: обработка, принят, дубль, ошибка.
 * Заменяет ProcessingQueue + DuplicateWarning + ClassificationPreview.
 */

import type { IntakeItem } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  CheckCircle2,
  AlertCircle,
  Copy,
  Loader2,
  FileText,
  Search,
  Brain,
  Fingerprint,
  Save,
  ExternalLink,
  X,
  Trash2,
  Inbox,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

interface IntakeQueueProps {
  items: IntakeItem[]
  onForceSave: (item: IntakeItem) => void
  onDismiss: (itemId: string) => void
  onClear: () => void
}

const STAGE_INFO: Record<string, { label: string; icon: typeof FileText }> = {
  detect: { label: 'Определение типа', icon: Search },
  extract: { label: 'Извлечение данных', icon: FileText },
  classify: { label: 'Классификация', icon: Brain },
  dedup: { label: 'Проверка дубликатов', icon: Fingerprint },
  save: { label: 'Сохранение', icon: Save },
}

export function IntakeQueue({ items, onForceSave, onDismiss, onClear }: IntakeQueueProps) {
  const navigate = useNavigate()

  if (items.length === 0) return null

  const processing = items.filter((i) => i.status === 'processing').length
  const accepted = items.filter((i) => i.status === 'done').length
  const rejected = items.filter((i) => i.status === 'error' || i.status === 'duplicate').length
  const finished = items.filter((i) => i.status !== 'processing').length

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold">Очередь обработки</h3>
          <div className="flex items-center gap-2">
            {processing > 0 && (
              <Badge variant="secondary" className="gap-1">
                <Loader2 className="size-3 animate-spin" />
                {processing}
              </Badge>
            )}
            {accepted > 0 && (
              <Badge variant="outline" className="gap-1 border-green-500 text-green-600">
                <CheckCircle2 className="size-3" />
                {accepted}
              </Badge>
            )}
            {rejected > 0 && (
              <Badge variant="outline" className="gap-1 border-red-500 text-red-500">
                <AlertCircle className="size-3" />
                {rejected}
              </Badge>
            )}
          </div>
        </div>

        {finished > 0 && (
          <div className="flex gap-2">
            {accepted > 0 && (
              <Button size="sm" variant="outline" onClick={() => navigate('/inbox')}>
                <Inbox className="size-3.5 mr-1.5" />
                Входящие
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onClear}>
              <Trash2 className="size-3.5 mr-1.5" />
              Очистить
            </Button>
          </div>
        )}
      </div>

      {/* Queue items */}
      <div className="space-y-2">
        {items.map((item) => (
          <QueueItem
            key={item.id}
            item={item}
            onForceSave={onForceSave}
            onDismiss={onDismiss}
            onOpen={(entryId) => navigate(`/inbox/${entryId}`)}
          />
        ))}
      </div>
    </div>
  )
}

interface QueueItemProps {
  item: IntakeItem
  onForceSave: (item: IntakeItem) => void
  onDismiss: (itemId: string) => void
  onOpen: (entryId: string) => void
}

function QueueItem({ item, onForceSave, onDismiss, onOpen }: QueueItemProps) {
  const stageInfo = STAGE_INFO[item.stage] ?? STAGE_INFO.detect
  const StageIcon = stageInfo.icon

  const borderClass =
    item.status === 'done' ? 'border-green-500/30 bg-green-500/5' :
    item.status === 'error' ? 'border-red-500/30 bg-red-500/5' :
    item.status === 'duplicate' ? 'border-amber-500/30 bg-amber-500/5' :
    ''

  return (
    <div className={`flex items-start gap-3 rounded-lg border bg-card p-3 ${borderClass}`}>
      <StatusIcon status={item.status} />

      <div className="flex-1 min-w-0">
        {/* Имя файла + размер */}
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium truncate">{item.fileName}</p>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {formatSize(item.size)}
          </span>
        </div>

        {/* Processing: прогресс + этап */}
        {item.status === 'processing' && (
          <div className="flex items-center gap-2 mt-1.5">
            <Progress value={item.progress} className="h-1.5 flex-1" />
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap">
              <StageIcon className="size-3" />
              {stageInfo.label}
            </span>
          </div>
        )}

        {/* Done: классификация + confidence */}
        {item.status === 'done' && item.classification && (
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <StatusLabel status="accepted" />
            <span className="text-xs text-muted-foreground">
              {item.classification.title}
            </span>
            <ConfidenceBadge confidence={item.classification.confidence} />
            <span className="text-xs text-muted-foreground">
              {item.classification.categoryId}/{item.classification.subcategoryId}
            </span>
          </div>
        )}

        {/* Duplicate: причина */}
        {item.status === 'duplicate' && (
          <div className="mt-1.5 space-y-1">
            <div className="flex items-center gap-2">
              <StatusLabel status="rejected" />
              <span className="text-xs text-muted-foreground">Дубликат</span>
            </div>
            {item.duplicateOf && (
              <p className="text-xs text-amber-600">
                Совпадает с записью #{item.duplicateOf.id}: {item.duplicateOf.title}
              </p>
            )}
          </div>
        )}

        {/* Error: причина */}
        {item.status === 'error' && (
          <div className="mt-1.5 space-y-1">
            <div className="flex items-center gap-2">
              <StatusLabel status="rejected" />
              <span className="text-xs text-muted-foreground">Ошибка обработки</span>
            </div>
            {item.error && (
              <p className="text-xs text-red-500">{item.error}</p>
            )}
          </div>
        )}
      </div>

      {/* Действия */}
      <div className="flex gap-1 shrink-0">
        {item.status === 'done' && item.entryId && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onOpen(item.entryId!)}
            title="Открыть"
          >
            <ExternalLink className="size-3.5" />
          </Button>
        )}

        {item.status === 'duplicate' && (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onForceSave(item)}
              title="Сохранить всё равно"
            >
              <Save className="size-3.5 mr-1" />
              Сохранить
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onDismiss(item.id)}
              title="Пропустить"
            >
              <X className="size-3.5" />
            </Button>
          </>
        )}

        {item.status === 'error' && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onDismiss(item.id)}
            title="Убрать"
          >
            <X className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  )
}

function StatusIcon({ status }: { status: IntakeItem['status'] }) {
  switch (status) {
    case 'processing':
      return <Loader2 className="size-5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'done':
      return <CheckCircle2 className="size-5 text-green-500 shrink-0 mt-0.5" />
    case 'duplicate':
      return <Copy className="size-5 text-amber-500 shrink-0 mt-0.5" />
    case 'error':
      return <AlertCircle className="size-5 text-red-500 shrink-0 mt-0.5" />
  }
}

function StatusLabel({ status }: { status: 'accepted' | 'rejected' }) {
  if (status === 'accepted') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-green-600 bg-green-500/10 px-1.5 py-0.5 rounded">
        Принят
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-red-500 bg-red-500/10 px-1.5 py-0.5 rounded">
      Отклонён
    </span>
  )
}

function ConfidenceBadge({ confidence }: { confidence: number }) {
  let className = 'border-green-500 text-green-500'
  if (confidence < 70) className = 'border-red-500 text-red-500'
  else if (confidence < 85) className = 'border-amber-500 text-amber-500'

  return (
    <Badge variant="outline" className={`text-[10px] ${className}`}>
      {confidence}%
    </Badge>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}
