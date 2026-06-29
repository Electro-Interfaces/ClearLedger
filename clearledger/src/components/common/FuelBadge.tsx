import { cn } from '@/lib/utils'
import { getFuelColor } from '@/utils/fuelColors'

interface FuelBadgeProps {
  fuel: string
  showName?: boolean
  className?: string
}

/** Цветной бейдж вида топлива (код + название). Перенос из TradeFrame. */
export function FuelBadge({ fuel, showName = true, className = '' }: FuelBadgeProps) {
  const color = getFuelColor(fuel)
  return (
    <div className={cn('flex items-center gap-2 min-w-0', className)}>
      <span className={cn('inline-flex items-center justify-center min-w-8 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase text-white', color.bg)}>
        {color.label}
      </span>
      {showName && <span className="text-foreground/80 truncate">{fuel}</span>}
    </div>
  )
}
