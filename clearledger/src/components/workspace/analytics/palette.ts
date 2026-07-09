/**
 * Единая палитра серий графиков раздела «Продажи» ЭЗС (приглушённая, богатая,
 * без неона). Раньше дублировалась в трёх местах (SERIES в OverviewDashboardPanel,
 * COLORS в ChargeChart, DONUT_COLORS в ChargeSessionsPanel), причём 6-й цвет
 * расходился (тёплый teal против неонового фиолета). Один источник — одинаковые
 * цвета во всех графиках раздела.
 */
export const CHART_SERIES = [
  'hsl(217, 91%, 60%)', 'hsl(152, 69%, 45%)', 'hsl(25, 100%, 55%)',
  'hsl(280, 65%, 65%)', 'hsl(340, 75%, 55%)', 'hsl(190, 70%, 50%)',
]

/** Нейтральный цвет последнего сегмента «Прочие». */
export const OTHER_COLOR = 'hsl(215, 16%, 55%)'

/** Цвет серии i из n: последний сегмент (при n>1) — нейтральный «Прочие». */
export const seriesColor = (i: number, n: number): string =>
  (i === n - 1 && n > 1 ? OTHER_COLOR : CHART_SERIES[i % CHART_SERIES.length])
