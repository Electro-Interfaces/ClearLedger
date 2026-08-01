/**
 * Оси графиков под ширину экрана.
 *
 * На десктопе ось может позволить себе «800.0 тыс» и подпись каждого второго часа.
 * На телефоне те же настройки съедают график: колонка чисел занимала 56 px из 390
 * (седьмую часть ширины) и переносилась в две строки, а подписи часов слипались в
 * «00:0002:0004:00» — нечитаемую ленту.
 *
 * Здесь одно правило на все графики: числа короче, колонка уже, подписи по оси X
 * прореживает сам recharts по свободному месту (`preserveStartEnd` + `minTickGap`),
 * а не жёсткий `interval`, подобранный под широкий экран.
 */
import { useMaxWidth } from '@/hooks/use-mobile'

/** Компактное число для узкой оси: 800к, 1,4м — без десятых и слов. */
export function fmtAxisShort(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace('.', ',') + 'млрд'
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace('.', ',') + 'м'
  if (a >= 1e3) return Math.round(n / 1e3) + 'к'
  return String(Math.round(n))
}

export interface ChartAxisPreset {
  /** Стиль подписи оси (в `tick`). */
  tick: { fontSize: number; fill: string }
  /** Дополнительные свойства XAxis: прореживание под ширину. */
  x: { interval?: 'preserveStartEnd'; minTickGap?: number }
  /** Ширина колонки подписей YAxis. */
  yWidth: number
  /** Формат числа для YAxis: на узком экране короткий. */
  fmt: (n: number) => string
  /** Узкий экран — можно решить и что-то ещё (скрыть легенду, убрать сетку). */
  narrow: boolean
}

/**
 * Настройки осей под текущую ширину. `wideFmt` — формат для десктопа (у денег свой,
 * у литров и штук свой), на узком экране он заменяется компактным.
 */
export function useChartAxis(wideFmt?: (n: number) => string): ChartAxisPreset {
  const narrow = useMaxWidth(640)
  return {
    tick: { fontSize: narrow ? 9 : 10, fill: 'hsl(var(--muted-foreground))' },
    // Жёсткий `interval` подобран под широкий экран и на телефоне даёт слипшиеся
    // подписи. `preserveStartEnd` оставляет края и убирает лишнее в середине.
    x: narrow ? { interval: 'preserveStartEnd', minTickGap: 16 } : {},
    yWidth: narrow ? 34 : 48,
    fmt: narrow ? fmtAxisShort : (wideFmt ?? ((n: number) => String(n))),
    narrow,
  }
}
