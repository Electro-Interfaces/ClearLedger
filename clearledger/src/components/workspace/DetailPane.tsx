/**
 * Немодальная боковая панель разбора: открывается по строке таблицы и НЕ блокирует
 * её. Таблица слева остаётся живой — можно листать, сравнивать и открывать
 * следующую строку, не закрывая эту.
 *
 * Модальное окно для разбора не годится: расхождение смотрят подряд по нескольким
 * резервуарам и сменам, а модалка на каждый клик заставляет закрывать её, чтобы
 * просто увидеть, какая строка была следующей.
 *
 * Рецепт немодальности взят из карточки станции (`LocationCockpitModal`):
 * `modal={false}` + подавление `onInteractOutside`, иначе клик по таблице закрывал
 * бы панель, а это ровно то взаимодействие, ради которого она немодальная.
 */
import type { ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export function DetailPane({ open, title, subtitle, badges, onClose, children, className }: {
  open: boolean
  title: ReactNode
  subtitle?: ReactNode
  badges?: ReactNode
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  return (
    <DialogPrimitive.Root open={open} modal={false} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Content
          onInteractOutside={(e) => e.preventDefault()}
          aria-describedby={undefined}
          className={cn(
            'fixed inset-y-0 right-0 z-40 flex w-full max-w-[94vw] flex-col border-l border-border bg-background shadow-2xl outline-none sm:w-[44rem]',
            'data-[state=open]:animate-in data-[state=open]:slide-in-from-right-4 data-[state=open]:fade-in-0',
            'data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right-4 data-[state=closed]:fade-out-0',
            className,
          )}
        >
          <div className="flex shrink-0 items-start gap-3 border-b border-border px-4 py-3">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="truncate text-sm font-semibold">{title}</DialogPrimitive.Title>
              {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
              {badges && <div className="mt-1.5 flex flex-wrap items-center gap-1.5">{badges}</div>}
            </div>
            <DialogPrimitive.Close
              aria-label="Закрыть разбор"
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
