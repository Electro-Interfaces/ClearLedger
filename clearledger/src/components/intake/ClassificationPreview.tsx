/**
 * ClassificationPreview — превью результатов классификации перед сохранением.
 * Показывает все завершённые элементы с возможностью редактирования.
 */

import type { IntakeItem } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  CheckCircle2,
  ExternalLink,
  Trash2,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

interface ClassificationPreviewProps {
  items: IntakeItem[]
  onClear: () => void
}

export function ClassificationPreview({ items, onClear }: ClassificationPreviewProps) {
  const navigate = useNavigate()
  const doneItems = items.filter((i) => i.status === 'done')

  if (doneItems.length === 0) return null

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">
          Создано записей: {doneItems.length}
        </h3>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => navigate('/inbox')}>
            <ExternalLink className="size-3.5 mr-1" />
            Открыть Входящие
          </Button>
          <Button size="sm" variant="ghost" onClick={onClear}>
            <Trash2 className="size-3.5 mr-1" />
            Очистить
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        {doneItems.map((item) => (
          <div
            key={item.id}
            className="flex items-center gap-3 rounded-lg border bg-card p-3"
          >
            <CheckCircle2 className="size-5 text-green-500 shrink-0" />

            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">
                {item.classification?.title ?? item.fileName}
              </p>
              <div className="flex items-center gap-2 mt-1">
                {item.classification && (
                  <>
                    <ConfidenceBadge confidence={item.classification.confidence} />
                    <span className="text-xs text-muted-foreground">
                      {item.classification.categoryId}/{item.classification.subcategoryId}
                    </span>
                  </>
                )}
              </div>
            </div>

            {item.entryId && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate(`/inbox/${item.entryId}`)}
              >
                <ExternalLink className="size-3.5" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
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
