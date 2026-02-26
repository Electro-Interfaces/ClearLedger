/**
 * ProcessingQueue — визуализация pipeline в реальном времени.
 */

import type { IntakeItem } from '@/types'
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
} from 'lucide-react'

interface ProcessingQueueProps {
  items: IntakeItem[]
}

const STAGE_INFO: Record<string, { label: string; icon: typeof FileText }> = {
  detect: { label: 'Определение', icon: Search },
  extract: { label: 'Извлечение', icon: FileText },
  classify: { label: 'Классификация', icon: Brain },
  dedup: { label: 'Дедупликация', icon: Fingerprint },
  save: { label: 'Сохранение', icon: Save },
}

export function ProcessingQueue({ items }: ProcessingQueueProps) {
  if (items.length === 0) return null

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">
        Обработка ({items.filter((i) => i.status === 'processing').length} активных)
      </h3>

      <div className="space-y-2">
        {items.map((item) => (
          <ProcessingItem key={item.id} item={item} />
        ))}
      </div>
    </div>
  )
}

function ProcessingItem({ item }: { item: IntakeItem }) {
  const stageInfo = STAGE_INFO[item.stage] ?? STAGE_INFO.detect
  const StageIcon = stageInfo.icon

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card p-3">
      <StatusIcon status={item.status} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium truncate">{item.fileName}</p>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {formatSize(item.size)}
          </span>
        </div>

        {item.status === 'processing' && (
          <div className="flex items-center gap-2 mt-1">
            <Progress value={item.progress} className="h-1.5 flex-1" />
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap">
              <StageIcon className="size-3" />
              {stageInfo.label}
            </span>
          </div>
        )}

        {item.status === 'done' && item.classification && (
          <p className="text-xs text-muted-foreground mt-1">
            {item.classification.title} — {item.classification.confidence}%
          </p>
        )}

        {item.status === 'duplicate' && item.duplicateOf && (
          <p className="text-xs text-amber-500 mt-1">
            Дубль записи #{item.duplicateOf.id}: {item.duplicateOf.title}
          </p>
        )}

        {item.status === 'error' && (
          <p className="text-xs text-destructive mt-1">{item.error}</p>
        )}
      </div>
    </div>
  )
}

function StatusIcon({ status }: { status: IntakeItem['status'] }) {
  switch (status) {
    case 'processing':
      return <Loader2 className="size-5 text-primary animate-spin shrink-0" />
    case 'done':
      return <CheckCircle2 className="size-5 text-green-500 shrink-0" />
    case 'duplicate':
      return <Copy className="size-5 text-amber-500 shrink-0" />
    case 'error':
      return <AlertCircle className="size-5 text-destructive shrink-0" />
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}
