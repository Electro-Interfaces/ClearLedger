import { Fragment } from 'react'
import { ArrowUp, Folder, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  currentPath: string[]
  onNavigate: (path: string[]) => void
  onGoUp: () => void
  viewMode: 'tree' | 'list'
  collapseButton?: React.ReactNode
}

export function RawPanelAddressBar({ currentPath, onNavigate, onGoUp, viewMode, collapseButton }: Props) {
  const segments = [
    { name: 'Хранилище', path: [] as string[] },
    ...currentPath.map((seg, i) => ({
      name: seg,
      path: currentPath.slice(0, i + 1),
    })),
  ]

  return (
    <div className="flex items-center gap-1 px-2 py-1 bg-muted/30 border-b border-border/40 min-h-[28px]">
      {collapseButton}

      {currentPath.length > 0 && (
        <Button variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={onGoUp} title="Вверх (Backspace)">
          <ArrowUp className="h-3 w-3" />
        </Button>
      )}

      <div className="flex items-center gap-0.5 flex-1 overflow-hidden">
        {viewMode === 'tree' ? (
          segments.map((seg, i) => (
            <Fragment key={i}>
              {i === 0 && <Folder className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
              {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground/40 shrink-0" />}
              <button
                onClick={() => onNavigate(seg.path)}
                className={`text-sm px-1 py-0.5 rounded hover:bg-accent/50 transition-colors truncate shrink-0 ${
                  i === segments.length - 1 ? 'font-semibold text-foreground' : 'text-muted-foreground'
                }`}
              >
                {seg.name}
              </button>
            </Fragment>
          ))
        ) : (
          <span className="text-sm font-semibold text-foreground px-1 flex items-center gap-1.5">
            <Folder className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            Все документы
          </span>
        )}
      </div>
    </div>
  )
}
