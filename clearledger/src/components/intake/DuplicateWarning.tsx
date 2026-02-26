/**
 * DuplicateWarning — предупреждение о найденных дубликатах.
 */

import type { IntakeItem } from '@/types'
import { Button } from '@/components/ui/button'
import { Copy, Save, X } from 'lucide-react'

interface DuplicateWarningProps {
  items: IntakeItem[]
  onForceSave: (item: IntakeItem) => void
  onDismiss: (itemId: string) => void
}

export function DuplicateWarning({ items, onForceSave, onDismiss }: DuplicateWarningProps) {
  const duplicates = items.filter((i) => i.status === 'duplicate')

  if (duplicates.length === 0) return null

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-amber-500">
        Найдены дубликаты: {duplicates.length}
      </h3>

      <div className="space-y-2">
        {duplicates.map((item) => (
          <div
            key={item.id}
            className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3"
          >
            <Copy className="size-5 text-amber-500 shrink-0" />

            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{item.fileName}</p>
              {item.duplicateOf && (
                <p className="text-xs text-amber-500 mt-0.5">
                  Совпадает с записью #{item.duplicateOf.id}: {item.duplicateOf.title}
                </p>
              )}
            </div>

            <div className="flex gap-1 shrink-0">
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
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
