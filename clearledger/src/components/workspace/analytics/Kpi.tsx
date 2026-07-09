import { Card, CardContent } from '@/components/ui/card'

/**
 * Компактная KPI-карточка раздела «Продажи» ЭЗС: label · value (+опц. Δ% к
 * прошлому периоду) · sub. Единый канон для панелей Тарифы/Корпоратив/Частные
 * лица (раньше — три идентичных локальных копии `Kpi`).
 *
 * cls   — доп. класс значения (напр. пороговая цветная раскраска);
 * delta — Δ% к прошлому периоду (абсурдные значения при пустой базе прячутся).
 */
export function Kpi({ label, value, sub, cls, delta }: {
  label: string; value: string; sub?: string; cls?: string; delta?: number | null
}) {
  const showDelta = delta != null && Math.abs(delta) <= 500   // абсурдные % (пустой прошлый период) прячем
  return (
    <Card className="py-0">
      <CardContent className="p-3">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="flex items-baseline gap-1.5">
          <div className={`text-lg font-semibold tabular-nums ${cls ?? ''}`}>{value}</div>
          {showDelta && (
            <span className={`text-[11px] font-medium tabular-nums ${delta! >= 0 ? 'text-emerald-400/90' : 'text-red-400/90'}`}>
              {delta! >= 0 ? '▲' : '▼'}{Math.abs(delta!).toFixed(1)}%
            </span>
          )}
        </div>
        {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  )
}
