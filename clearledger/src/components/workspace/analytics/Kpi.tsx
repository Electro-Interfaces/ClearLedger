import { MetricTile } from '@/components/ui/metric-tile'

/**
 * Плитка «Продаж»: label · value (+опц. Δ% к прошлому периоду) · sub.
 *
 * Сама вёрстка живёт в `components/ui/metric-tile.tsx` — одна на пространство.
 * Здесь остался только привычный вызовам порядок пропов: панелей на этом API
 * одиннадцать, и переписывать их ради переезда смысла не было.
 *
 * cls   — доп. класс значения (напр. пороговая цветная раскраска);
 * delta — Δ% к прошлому периоду (абсурдные значения при пустой базе прячутся).
 */
export function Kpi({ label, value, sub, cls, delta }: {
  label: string; value: string; sub?: string; cls?: string; delta?: number | null
}) {
  return <MetricTile label={label} value={value} hint={sub} valueClass={cls} delta={delta} />
}
