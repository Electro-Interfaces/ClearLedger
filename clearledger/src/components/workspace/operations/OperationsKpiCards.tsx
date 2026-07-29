/**
 * KPI-карточки раздела «Операции» — разрезы периода по видам топлива и способам
 * оплаты, каждая карточка одновременно фильтр реестра.
 *
 * Перенос из «Монитора» (TradeFrame, `components/operations/KPIFuelCard.tsx` и
 * `KPIPaymentCard.tsx`). Смысл формы: разрез виден целиком одним взглядом —
 * сколько наливов, литров и рублей у каждого вида — и им же отбирают строки.
 * Список карточек всегда полный: невыбранное показывает нули, а не исчезает,
 * иначе фильтр нечем снять.
 */
import { memo, useCallback } from 'react'
import { Activity } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { FuelBadge } from '@/components/common/FuelBadge'
import { cn } from '@/lib/utils'

const exact = (v: number) =>
  v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Выбранная карточка помечена полосой снизу — читается и без цвета фона. */
const cardClass = (selected: boolean) =>
  cn('cursor-pointer transition-all duration-300 hover:shadow-lg',
     selected
       ? 'border-2 border-primary/45 bg-primary/5 shadow-[inset_0_-4px_0_0_hsl(var(--primary))]'
       : 'border-border bg-card hover:bg-secondary')

function Figures({ volume, cost, count }: { volume: number; cost: number; count: number }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="mt-1 flex items-center gap-1">
        <Activity className="h-3 w-3 text-muted-foreground" />
        <span className="text-sm tabular-nums text-foreground/80">{count}</span>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-sm font-semibold tabular-nums text-foreground">{exact(volume)} л</div>
        <div className="text-sm font-semibold tabular-nums text-foreground">{exact(cost)} ₽</div>
      </div>
    </div>
  )
}

export const KpiFuelCard = memo(function KpiFuelCard({
  fuel, selected, volume, cost, count, onClick,
}: {
  fuel: string; selected: boolean; volume: number; cost: number; count: number
  onClick: (fuel: string) => void
}) {
  const handle = useCallback(() => onClick(fuel), [onClick, fuel])
  return (
    <Card className={cardClass(selected)} onClick={handle} aria-pressed={selected}>
      <CardContent className="p-4">
        <FuelBadge fuel={fuel} />
        <Figures volume={volume} cost={cost} count={count} />
      </CardContent>
    </Card>
  )
})

export const KpiPaymentCard = memo(function KpiPaymentCard({
  payment, selected, volume, cost, count, onClick,
}: {
  payment: string; selected: boolean; volume: number; cost: number; count: number
  onClick: (payment: string) => void
}) {
  const handle = useCallback(() => onClick(payment), [onClick, payment])
  return (
    <Card className={cardClass(selected)} onClick={handle} aria-pressed={selected}>
      <CardContent className="p-3">
        <p className="truncate text-sm font-semibold text-foreground" title={payment}>{payment}</p>
        <Figures volume={volume} cost={cost} count={count} />
      </CardContent>
    </Card>
  )
})

/** Редкий способ оплаты — чипом; цифры раскрываются при выборе. */
export const KpiPaymentChip = memo(function KpiPaymentChip({
  payment, selected, volume, cost, count, onClick,
}: {
  payment: string; selected: boolean; volume: number; cost: number; count: number
  onClick: (payment: string) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onClick(payment)}
      className={cn(
        'rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-200',
        selected
          ? 'border border-primary/45 bg-primary/10 text-primary shadow-md'
          : 'bg-secondary text-foreground/80 hover:bg-secondary/70',
      )}
    >
      {payment}
      {selected && (
        <span className="ml-1.5 tabular-nums opacity-90">
          {count} · {exact(volume)} л · {exact(cost)} ₽
        </span>
      )}
    </button>
  )
})
