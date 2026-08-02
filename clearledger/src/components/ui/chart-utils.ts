/* eslint-disable @typescript-eslint/no-explicit-any */
// Основа чартов Tremor Raw (Apache-2.0), адаптированная под токены пространства.
// Палитра завязана на --chart-1..5 и статусные токены из src/index.css: чарт
// меняет цвета вместе с темой, отдельного «цвета графиков» в проекте нет.
import * as React from "react"

export type ColorUtility = "bg" | "stroke" | "fill" | "text"

export const chartColors = {
  brand: {
    bg: "bg-chart-1",
    stroke: "stroke-chart-1",
    fill: "fill-chart-1",
    text: "text-chart-1",
  },
  green: {
    bg: "bg-chart-2",
    stroke: "stroke-chart-2",
    fill: "fill-chart-2",
    text: "text-chart-2",
  },
  orange: {
    bg: "bg-chart-3",
    stroke: "stroke-chart-3",
    fill: "fill-chart-3",
    text: "text-chart-3",
  },
  purple: {
    bg: "bg-chart-4",
    stroke: "stroke-chart-4",
    fill: "fill-chart-4",
    text: "text-chart-4",
  },
  pink: {
    bg: "bg-chart-5",
    stroke: "stroke-chart-5",
    fill: "fill-chart-5",
    text: "text-chart-5",
  },
  neutral: {
    bg: "bg-muted-foreground",
    stroke: "stroke-muted-foreground",
    fill: "fill-muted-foreground",
    text: "text-muted-foreground",
  },
  // Статусные — брать явно, когда цвет несёт смысл (норма / внимание / отклонение).
  success: {
    bg: "bg-success",
    stroke: "stroke-success",
    fill: "fill-success",
    text: "text-success",
  },
  warning: {
    bg: "bg-warning",
    stroke: "stroke-warning",
    fill: "fill-warning",
    text: "text-warning",
  },
  error: {
    bg: "bg-error",
    stroke: "stroke-error",
    fill: "fill-error",
    text: "text-error",
  },
} as const satisfies {
  [color: string]: { [key in ColorUtility]: string }
}

export type AvailableChartColorsKeys = keyof typeof chartColors

/** Порядок цветов по умолчанию: сначала пять чартовых токенов, потом нейтральный.
 *  Статусные в автопорядок не входят — красный «шестой серией» врёт о смысле. */
export const AvailableChartColors: AvailableChartColorsKeys[] = [
  "brand",
  "green",
  "orange",
  "purple",
  "pink",
  "neutral",
]

export const constructCategoryColors = (
  categories: string[],
  colors: AvailableChartColorsKeys[],
): Map<string, AvailableChartColorsKeys> => {
  const categoryColors = new Map<string, AvailableChartColorsKeys>()
  categories.forEach((category, index) => {
    categoryColors.set(category, colors[index % colors.length])
  })
  return categoryColors
}

export const getColorClassName = (
  color: AvailableChartColorsKeys,
  type: ColorUtility,
): string => chartColors[color]?.[type] ?? chartColors.neutral[type]

export const getYAxisDomain = (
  autoMinValue: boolean,
  minValue: number | undefined,
  maxValue: number | undefined,
) => {
  const minDomain = autoMinValue ? "auto" : (minValue ?? 0)
  const maxDomain = maxValue ?? "auto"
  return [minDomain, maxDomain]
}

export function hasOnlyOneValueForKey(array: any[], keyToCheck: string): boolean {
  const val: any[] = []
  for (const obj of array) {
    if (Object.prototype.hasOwnProperty.call(obj, keyToCheck)) {
      val.push(obj[keyToCheck])
      if (val.length > 1) return false
    }
  }
  return true
}

/** Оформление подсказки recharts для графиков, собранных вручную.
 *  Без него подсказка рисуется дефолтной белой плашкой — на тёмной теме это
 *  светящийся прямоугольник поверх данных. Ставить первым, чтобы собственные
 *  props графика (cursor, formatter) перекрывали умолчания:
 *  `<Tooltip {...rechartsTooltipTheme} formatter={…} />`.
 *  Компонентам из этого каталога он не нужен — у них своя разметка подсказки. */
export const rechartsTooltipTheme = {
  contentStyle: {
    backgroundColor: "hsl(var(--popover))",
    border: "1px solid hsl(var(--border))",
    borderRadius: "8px",
    color: "hsl(var(--popover-foreground))",
    fontSize: 12,
    boxShadow: "var(--shadow-medium)",
  },
  labelStyle: { color: "hsl(var(--muted-foreground))", marginBottom: 2 },
  itemStyle: { color: "hsl(var(--popover-foreground))" },
  cursor: { fill: "hsl(var(--muted) / 0.35)" },
} as const

export const focusRing = [
  "outline outline-offset-2 outline-0 focus-visible:outline-2",
  "outline-ring",
]

export const useOnWindowResize = (handler: () => void) => {
  React.useEffect(() => {
    const handleResize = () => handler()
    handleResize()
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [handler])
}
