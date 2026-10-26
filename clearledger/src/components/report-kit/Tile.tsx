import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Плитка показателя над таблицей. С `onClick` она же — отбор списка: человек
 * смотрит на число «13 просрочено» и хочет увидеть эти тринадцать, а не искать
 * их селектами. Активная подсвечена рамкой, повторное нажатие снимает отбор.
 */
export function Tile({ icon: Icon, label, value, hint, tone, onClick, active, disabled }: {
  icon: LucideIcon; label: string; value: string; hint?: ReactNode; tone?: string
  onClick?: () => void; active?: boolean; disabled?: boolean
}) {
  const inner = (
    <>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" />{label}
      </div>
      <div className={cn('mt-0.5 text-lg font-semibold tabular-nums', tone)}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </>
  )
  const look = cn('rounded-lg border bg-card px-3 py-2 text-left',
    active ? 'border-primary ring-1 ring-primary/40' : 'border-border/60')
  if (!onClick) return <div data-kpi className={look}>{inner}</div>
  return (
    <button type="button" data-kpi onClick={onClick} aria-pressed={!!active} disabled={disabled}
      className={cn(look, 'transition-colors enabled:hover:border-primary/60 disabled:cursor-not-allowed')}>
      {inner}
    </button>
  )
}

/** Ряд плиток: две в строку на телефоне, дальше — сколько влезет по 200 px. */
export const TILE_ROW = 'grid grid-cols-2 gap-2 sm:grid-cols-[repeat(auto-fit,minmax(200px,1fr))]'
