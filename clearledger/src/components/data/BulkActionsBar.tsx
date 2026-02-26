import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { X, ChevronDown, Send } from 'lucide-react'
import type { EntryStatus } from '@/config/statuses'
import { statuses } from '@/config/statuses'

interface BulkActionsBarProps {
  selectedCount: number
  onClearSelection: () => void
  onChangeStatus: (status: EntryStatus) => void
  onTransfer: () => void
}

export function BulkActionsBar({
  selectedCount,
  onClearSelection,
  onChangeStatus,
  onTransfer,
}: BulkActionsBarProps) {
  if (selectedCount === 0) return null

  return (
    <div className="sticky bottom-0 z-10 border-t bg-card/95 backdrop-blur-sm px-4 py-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-muted-foreground">
          Выбрано: <span className="font-medium text-foreground">{selectedCount}</span>
        </span>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              Изменить статус
              <ChevronDown />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {(Object.keys(statuses) as EntryStatus[]).map((key) => (
              <DropdownMenuItem key={key} onClick={() => onChangeStatus(key)}>
                {statuses[key].label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <Button variant="outline" size="sm" onClick={onTransfer}>
          <Send />
          Передать на Слой 2
        </Button>

        <Button variant="ghost" size="sm" onClick={onClearSelection}>
          <X />
          Снять выделение
        </Button>
      </div>
    </div>
  )
}
