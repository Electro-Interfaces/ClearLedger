import { Clock3 } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Входящие и просрочка различаются подписью, формой и цветом. */
export function TaskAssignmentBadges({ incoming, overdue, inline = false }: {
  incoming: number; overdue: number; inline?: boolean
}) {
  if (incoming <= 0 && overdue <= 0) return null
  return (
    <span className={cn('pointer-events-none inline-flex items-center gap-1',
      !inline && 'absolute -right-1 -top-2')}>
      {incoming > 0 && <span title={`Новые назначения: ${incoming}`}
        aria-label={`Новые назначения: ${incoming}`}
        className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
        {incoming}
      </span>}
      {overdue > 0 && <span title={`Просрочено: ${overdue}`}
        aria-label={`Просрочено: ${overdue}`}
        className="inline-flex h-[18px] items-center gap-0.5 rounded border border-destructive bg-background px-1 text-[10px] font-bold text-destructive">
        <Clock3 className="size-3" aria-hidden />{overdue}
      </span>}
    </span>
  )
}
