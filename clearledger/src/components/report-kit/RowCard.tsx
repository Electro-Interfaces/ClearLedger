import { ChevronLeft, ChevronRight, FileText } from 'lucide-react'
import { useRef, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { showCell, type Cell } from './format'

/**
 * Карточка строки — окно по центру на две колонки, как в эталоне КП СДО:
 * слева все поля строки (и скрытые), справа связанные отчёты и действия.
 * Боковая шторка закрывала таблицу наполовину и не вмещала второй колонки
 * (МАГ, 15.10.2026).
 */
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
  /** Правая колонка: связанные отчёты (`RelatedLink`) и действия по строке. */
  extra?: ReactNode
  at: number
  of: number
  onStep: (d: 1 | -1) => void
  onClose: () => void
}) {
  const opener = useRef<HTMLElement | null>(null)
  const facts = row ? head.map((h, i) => [h, row[i]] as const).filter(([, v]) => v !== '') : []
  const подпись = 'mb-2 text-xs font-semibold text-muted-foreground'
  return (
    <Dialog open={!!row} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[90vh] w-[calc(100vw-2rem)] max-w-[1400px] flex-col gap-0 p-0 sm:max-w-[1400px]"
        onOpenAutoFocus={() => { opener.current = document.activeElement as HTMLElement | null }}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          if (opener.current?.isConnected) opener.current.focus({ preventScroll: true })
        }}
        onKeyDown={(e) => {
          const target = e.target as HTMLElement
          if (e.defaultPrevented || target.closest('[role="dialog"]') !== e.currentTarget
            || target.closest('input, textarea, select, [role="combobox"], [contenteditable="true"]')) return
          if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
          e.preventDefault()
          e.stopPropagation()
          if (e.key === 'ArrowDown' && at < of - 1) onStep(1)
          if (e.key === 'ArrowUp' && at > 0) onStep(-1)
        }}>
        <DialogHeader className="border-b border-border/60 px-6 py-4">
          <DialogTitle>{title || 'Строка таблицы'}</DialogTitle>
          <DialogDescription>
            {report}, строка {at + 1} из {of} · ↑ ↓ листают
          </DialogDescription>
        </DialogHeader>
        <div className={`grid min-h-0 flex-1 gap-6 overflow-y-auto px-6 py-4 ${extra ? 'md:grid-cols-2' : ''}`}>
          <section>
            <div className={подпись}>В таблице</div>
            <dl className="divide-y divide-border/50 rounded-lg border border-border/60">
              {facts.map(([h, v]) => (
                <div key={h} className="flex flex-col gap-1 px-4 py-2.5 text-sm sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                  <dt className="text-muted-foreground">{h}</dt>
                  <dd className="min-w-0 break-words text-foreground tabular-nums sm:text-right">{showCell(v, h)}</dd>
                </div>
              ))}
            </dl>
          </section>
          {extra && (
            <section>
              <div className={подпись}>Связанные отчёты</div>
              {extra}
            </section>
          )}
        </div>
        <DialogFooter className="flex-row justify-start gap-2 border-t border-border/60 px-6 py-3 sm:justify-start">
          <Button variant="outline" disabled={at === 0} onClick={() => onStep(-1)}>
            <ChevronLeft className="size-4" aria-hidden /> Предыдущая
          </Button>
          <Button variant="outline" disabled={at >= of - 1} onClick={() => onStep(1)}>
            Следующая <ChevronRight className="size-4" aria-hidden />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Строка списка связанных отчётов в карточке: значок, название, стрелка. */
export function RelatedLink({ label, hint, icon, onClick }: {
  label: string
  hint?: string
  icon?: ReactNode
  onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick}
      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-accent/40">
      <span className="text-muted-foreground">{icon ?? <FileText className="size-4" aria-hidden />}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-foreground">{label}</span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
      <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
    </button>
  )
}
