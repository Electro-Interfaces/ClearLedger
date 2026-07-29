/**
 * Плитки разрезов «Операций» — вид топлива и способ оплаты. Каждая плитка
 * одновременно показывает разрез и включает его в фильтр реестра.
 *
 * Форма — плотная строка, а не карточка: разрезов до одиннадцати, и карточной
 * раскладкой они отжимали реестр на второй экран. В плитке две строки: кто
 * (бейдж или имя) и сколько (операции · литры · рубли), числа выровнены
 * табличными цифрами в общую колонку — соседние плитки читаются столбцом.
 *
 * Кнопка, а не `div` с обработчиком: это фильтр, до него обязана доходить
 * клавиатура, и состояние выбора должен объявлять `aria-pressed`.
 * Язык плитки — общий с «Обзором» (`FuelOverviewPanel`): рамка, `bg-card/50`,
 * метка 11px капсом, табличные цифры.
 */
import { memo, useCallback, type ReactNode } from 'react'
import { FuelBadge } from '@/components/common/FuelBadge'
import { fmtLiters } from '@/services/analyticsService'
import { cn } from '@/lib/utils'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

/** Копейки в разрезе — шум: он про порядок величин, точность живёт в реестре. */
const money = (v: number) => `${nf0.format(Math.round(v))} ₽`

function Tile({ title, selected, count, liters, amount, onClick }: {
  title: ReactNode; selected: boolean; count: number; liters: number; amount: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        'w-full rounded-xl border px-3 py-2.5 text-left shadow-sm transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected
          ? 'border-primary/60 bg-primary/10 hover:bg-primary/15'
          : 'bg-card/50 hover:bg-muted/40',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-medium text-foreground">{title}</span>
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{nf0.format(count)}</span>
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2 tabular-nums">
        <span className="text-[13px] text-muted-foreground">{fmtLiters(liters)}</span>
        <span className="text-[13px] font-semibold text-foreground">{money(amount)}</span>
      </div>
    </button>
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
    <Tile title={<FuelBadge fuel={fuel} />} selected={selected}
      count={count} liters={volume} amount={cost} onClick={handle} />
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
    <Tile title={<span title={payment}>{payment}</span>} selected={selected}
      count={count} liters={volume} amount={cost} onClick={handle} />
  )
})

/** Редкий способ оплаты — чипом: у него единицы наливов, плитка была бы пустой.
 *  Цифры раскрываются при выборе, чтобы ряд чипов не превращался в вторую сетку. */
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
        'rounded-lg border px-2.5 py-1 text-xs transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected
          ? 'border-primary/60 bg-primary/10 font-medium text-primary'
          : 'border-border bg-card/50 text-muted-foreground hover:bg-muted/40 hover:text-foreground',
      )}
    >
      {payment}
      {selected && (
        <span className="ml-1.5 tabular-nums opacity-80">
          {nf0.format(count)} · {fmtLiters(volume)} · {money(cost)}
        </span>
      )}
    </button>
  )
})
