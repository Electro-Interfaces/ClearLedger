/**
 * Захват строки: цепляют его, а не всю строку.
 *
 * Когда перетаскивается вся строка, теряются обычные вещи — выделить текст,
 * начать движение мышью и передумать, кликнуть по названию. Ручка отделяет
 * «взял и понёс» от «читаю и нажимаю», и человек видит, за что браться.
 *
 * Показывается всегда, а не по наведению: элемент, о существовании которого
 * узнают случайно, для половины людей не существует.
 */
import { GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'

export function DragHandle({ targetRef, label, title, className }: {
  /** Предмет словарём пространства: `task:<uuid>`, `doc:<uuid>`. */
  targetRef: string
  /** Как предмет называется вслух: «№11 Пример задачи». Уносится вместе со
   *  ссылкой, чтобы агент открылся с готовым вопросом, а не с номером. */
  label?: string
  title?: string
  className?: string
}) {
  return (
    <span
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', targetRef)
        if (label) e.dataTransfer.setData('text/x-elsy-label', label)
        e.dataTransfer.effectAllowed = 'move'
        e.stopPropagation()
      }}
      onClick={(e) => e.stopPropagation()}
      role="application"
      aria-label="Перетащить в календарь"
      title={title ?? 'Перетащите в календарь справа: на день — срок, на человека — поручить'}
      className={cn('inline-flex shrink-0 cursor-grab items-center text-muted-foreground/50 transition-colors hover:text-foreground active:cursor-grabbing',
        className)}>
      <GripVertical className="h-3.5 w-3.5" />
    </span>
  )
}

export default DragHandle
