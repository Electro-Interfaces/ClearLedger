import { memo, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export const TrendSpark = memo(function TrendSpark({
  values,
  tone = 'direction',
  full = false,
  className,
  placeholder = null,
}: {
  values: (number | null)[] | undefined
  tone?: 'direction' | 'muted' | 'brand'
  full?: boolean
  className?: string
  placeholder?: ReactNode
}) {
  const samples = (values ?? [])
    .map((value, index) => value == null ? null : { value, index })
    .filter((sample): sample is { value: number; index: number } => sample !== null)

  if (samples.length < 2) return <>{placeholder}</>

  let min = samples[0].value
  let max = samples[0].value
  for (const sample of samples) {
    min = Math.min(min, sample.value)
    max = Math.max(max, sample.value)
  }
  const range = max - min
  const lastIndex = Math.max((values?.length ?? 1) - 1, 1)
  const points = samples.map(({ value, index }) => {
    const x = index / lastIndex * 62 + 1
    const y = range === 0 ? 8 : 15 - (value - min) / range * 14
    return `${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
  const rising = samples[samples.length - 1].value >= samples[0].value
  const color = tone === 'direction'
    ? rising ? 'text-emerald-500' : 'text-red-500'
    : tone === 'brand' ? 'text-primary' : 'text-muted-foreground/60'

  return (
    <svg viewBox="0 0 64 16" preserveAspectRatio="none" aria-hidden="true" focusable="false"
      className={cn(full ? 'h-7 w-full' : 'inline-block h-4 w-16 align-middle', color, className)}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.75"
        vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
})
