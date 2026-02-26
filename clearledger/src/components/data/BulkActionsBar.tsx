import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { X, ChevronDown, Send, Trash2, Download } from 'lucide-react'
import type { EntryStatus } from '@/config/statuses'
import { statuses } from '@/config/statuses'

interface BulkActionsBarProps {
  selectedCount: number
  onClearSelection: () => void
  onChangeStatus: (status: EntryStatus) => void
  onTransfer: () => void
  onDelete?: () => void
  onExportCsv?: () => void
}

export function BulkActionsBar({
  selectedCount,
  onClearSelection,
  onChangeStatus,
  onTransfer,
  onDelete,
  onExportCsv,
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
          Передать
        </Button>

        {onExportCsv && (
          <Button variant="outline" size="sm" onClick={onExportCsv}>
            <Download />
            CSV
          </Button>
        )}

        {onDelete && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="text-destructive">
                <Trash2 />
                Удалить
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Удалить {selectedCount} записей?</AlertDialogTitle>
                <AlertDialogDescription>
                  Выбранные записи будут удалены. Это действие нельзя отменить.
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

        <Button variant="ghost" size="sm" onClick={onClearSelection} className="ml-auto">
          <X />
          Снять
        </Button>
      </div>
    </div>
  )
}
