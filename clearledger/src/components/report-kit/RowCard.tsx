import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { showCell, type Cell } from './format'

export function RowCard({
  report,
  head,
  row,
  title,
  extra,
  at,
  of,
  onStep,
  onClose,
}: {
  report: string
  head: string[]
  row: Cell[] | null
  title?: string
  extra?: ReactNode
  at: number
  of: number
  onStep: (d: 1 | -1) => void
  onClose: () => void
}) {
  useEffect(() => {
    if (!row) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea, select')) return
      if (e.key === 'ArrowDown' && at < of - 1) onStep(1)
      if (e.key === 'ArrowUp' && at > 0) onStep(-1)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [row, at, of, onStep])
  const facts = row ? head.map((h, i) => [h, row[i]] as const).filter(([, v]) => v !== '') : []
  return (
    <Sheet open={!!row} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
        <SheetHeader className="border-b border-border/60">
          <SheetTitle>{title || 'Строка таблицы'}</SheetTitle>
          <SheetDescription>
            {report}, строка {at + 1} из {of} · ↑ ↓ листают
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {extra}
          <dl className="divide-y divide-border/50 rounded-lg border border-border/60">
            {facts.map(([h, v]) => (
              <div key={h} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3 px-3 py-2 text-sm">
                <dt className="text-muted-foreground">{h}</dt>
                <dd className={typeof v === 'number' ? 'text-right tabular-nums text-foreground' : 'text-foreground'}>{showCell(v, h)}</dd>
              </div>
            ))}
          </dl>
        </div>
        <SheetFooter className="flex-row justify-between border-t border-border/60">
          <Button variant="outline" disabled={at === 0} onClick={() => onStep(-1)}>
            <ChevronLeft className="size-4" aria-hidden /> Предыдущая
          </Button>
          <Button variant="outline" disabled={at >= of - 1} onClick={() => onStep(1)}>
            Следующая <ChevronRight className="size-4" aria-hidden />
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
