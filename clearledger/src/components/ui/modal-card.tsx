/**
 * Карточка поверх экрана: шапка, тело со скроллом, необязательный подвал.
 *
 * До неё каждый экран рисовал свой слой `fixed inset-0 z-[1200]`: такие слои не
 * закрывались по Esc, не держали фокус внутри себя и жили в собственной системе
 * z-слоёв — поэтому окно пункта («Магазин», `?win=`) уезжало под них. Здесь один
 * каркас поверх Radix: Esc, клик вне, ловушка фокуса, возврат фокуса и портал в
 * body достаются от него, а не пишутся заново на каждом экране.
 *
 * Портал важен и для вёрстки: карточка, открытая из панели внутри окна пункта,
 * рисуется в body, а не внутри окна, — и не ложится по его краю.
 */
import type { ReactNode } from 'react'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

export function ModalCard({
  title,
  subtitle,
  actions,
  footer,
  className,
  bodyClassName,
  onClose,
  children,
}: {
  /** Заголовок: строка или своя разметка с бейджами. */
  title: ReactNode
  /** Вторая строка шапки — реквизиты предмета, а не пояснение к действию. */
  subtitle?: ReactNode
  /** Кнопки в правой части шапки (крестик рисует сам каркас). */
  actions?: ReactNode
  footer?: ReactNode
  /** Ширина и высота: `max-w-5xl`, `max-h-[80vh]` и т.п. */
  className?: string
  /** Отступы тела: у таблиц во всю ширину их быть не должно. */
  bodyClassName?: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        className={cn(
          'w-full max-w-4xl max-h-[90vh] gap-0 p-0',
          footer ? 'grid-rows-[auto_1fr_auto]' : 'grid-rows-[auto_1fr]',
          'max-sm:w-screen max-sm:max-w-none max-sm:h-[100dvh] max-sm:max-h-none max-sm:rounded-none',
          className,
        )}
        aria-describedby={undefined}
      >
        <DialogHeader className="flex-row items-start justify-between gap-3 space-y-0 border-b border-border/50 px-5 py-3.5">
          {/* pr-6 — место под крестик каркаса, иначе длинный заголовок уходит под него */}
          <div className="min-w-0 pr-6">
            <DialogTitle className="truncate text-base">{title}</DialogTitle>
            {subtitle ? (
              <DialogDescription className="mt-0.5 text-xs">{subtitle}</DialogDescription>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2 pr-6">{actions}</div> : null}
        </DialogHeader>

        <div className={cn('min-h-0 overflow-auto', bodyClassName ?? 'p-5')}>{children}</div>

        {footer ? <div className="border-t border-border/50 px-5 py-3">{footer}</div> : null}
      </DialogContent>
    </Dialog>
  )
}
