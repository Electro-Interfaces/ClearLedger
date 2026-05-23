import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { List, Table2, FolderTree } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ViewMode = 'list' | 'register' | 'tree'

interface ViewSwitcherProps {
  value: ViewMode
  onChange: (mode: ViewMode) => void
}

const views: { mode: ViewMode; icon: typeof List; label: string }[] = [
  { mode: 'list', icon: List, label: 'Список' },
  { mode: 'register', icon: Table2, label: 'Реестр' },
  { mode: 'tree', icon: FolderTree, label: 'Иерархия' },
]

export function ViewSwitcher({ value, onChange }: ViewSwitcherProps) {
  return (
    <div className="flex items-center gap-0.5 rounded-lg border p-0.5">
      {views.map(({ mode, icon: Icon, label }) => (
        <Tooltip key={mode}>
          <TooltipTrigger asChild>
            <Button
              variant={value === mode ? 'secondary' : 'ghost'}
              size="sm"
              className={cn('h-7 w-7 p-0', value === mode && 'pointer-events-none')}
              onClick={() => onChange(mode)}
            >
              <Icon className="size-4" />
              <span className="sr-only">{label}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">{label}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  )
}
