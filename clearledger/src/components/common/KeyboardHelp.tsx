import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Keyboard } from 'lucide-react'

interface ShortcutGroup {
  title: string
  shortcuts: Array<{ keys: string[]; description: string }>
}

const GROUPS: ShortcutGroup[] = [
  {
    title: 'Навигация',
    shortcuts: [
      { keys: ['Ctrl', 'K'], description: 'Глобальный поиск' },
      { keys: ['?'], description: 'Справка по горячим клавишам' },
    ],
  },
  {
    title: 'Входящие',
    shortcuts: [
      { keys: ['J'], description: 'Следующая запись' },
      { keys: ['K'], description: 'Предыдущая запись' },
      { keys: ['S'], description: 'Пропустить' },
      { keys: ['Ctrl', 'Enter'], description: 'Верифицировать' },
    ],
  },
]

interface KeyboardHelpProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function KeyboardHelp({ open, onOpenChange }: KeyboardHelpProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Keyboard className="size-5" />
            Горячие клавиши
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-5">
          {GROUPS.map((group) => (
            <div key={group.title}>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">{group.title}</h3>
              <div className="space-y-1.5">
                {group.shortcuts.map((s) => (
                  <div key={s.description} className="flex items-center justify-between">
                    <span className="text-sm">{s.description}</span>
                    <div className="flex items-center gap-1">
                      {s.keys.map((key) => (
                        <kbd
                          key={key}
                          className="inline-flex h-6 min-w-6 items-center justify-center rounded border bg-muted px-1.5 text-xs font-medium"
                        >
                          {key}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
