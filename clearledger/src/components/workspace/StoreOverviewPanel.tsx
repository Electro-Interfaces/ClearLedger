/**
 * «Обзор» — executive-дашборд сопутки/общепита (форк FuelOverviewPanel).
 * Данные: /api/store/overview (GoodsDashboardService из DataEntry clean канала ЦБ).
 * KPI на продажах: выручка/чистая/НДС/средний чек≈/смены/позиции + структура категорий,
 * оплаты (нал/безнал), дневная динамика. Маржа/ABC — следующий блок (FIFO).
 */
import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts'
import { ExportButton } from './analytics/ExportButton'
import { Kpi } from './analytics/Kpi'
import { CHART_SERIES, seriesColor } from './analytics/palette'
import { getStoreOverview, monthOf } from '@/services/storeService'
import { fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import { StorePlanMonitor } from './StorePlanMonitor'
import { StoreExceptionsWidget } from './StoreExceptionsWidget'
import { StoreMovementSummary } from './StoreMovementSummary'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'

const nf0 = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n)

function ShareBars({ rows }: { rows: { name: string; value: number; percent?: number }[] }) {
  const total = rows.reduce((s, r) => s + r.value, 0) || 1
  return (
    <div className="space-y-2">
      {rows.map((r, i) => {
        const pct = r.percent ?? (100 * r.value) / total
        return (
          <div key={r.name}>
            <div className="flex justify-between text-xs mb-1">
              <span>{r.name}</span>
              <span className="tabular-nums text-muted-foreground">{fmtMoney(r.value)} · {pct.toFixed(1)}%</span>
            </div>
            <div className="h-2 rounded-full bg-muted/40 overflow-hidden">
              <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: seriesColor(i, rows.length) }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function StoreOverviewPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const ref = useRef<HTMLDivElement>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-overview', companyId, dateFrom, dateTo, stations],
    queryFn: () => getStoreOverview(dateFrom, dateTo, { compare: true, stations }),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка обзора…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки обзора магазина</div>
  if (!data) return null

  const { financial: f, units: u, operational: op, trends: t } = data
  const empty = op.shifts_count === 0

  return (
    <div ref={ref} className="p-6 space-y-5 max-w-6xl">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Обзор</h3>
          <p className="text-xs text-muted-foreground">
            Сопутка + общепит · {data.period.from} – {data.period.to} · {op.shifts_count} смен · {op.stations_count} АЗС
          </p>
        </div>
        <ExportButton title="Обзор" subtitle={`${data.period.from} — ${data.period.to}`} getEl={() => ref.current} />
      </div>

      {empty ? (
        <div className="rounded-lg border border-dashed border-border/50 p-6 text-sm text-muted-foreground">
          Нет продаж за выбранный период. Загрузите смены в разделе «Коннекторы» → «Сопутка (магазин)».
          <br />Локальная копия ЦБ — снимок на 29.04.2026, данные есть по апрель (поставьте период в апреле).
        </div>
      ) : (
        <>
          {/* План-факт-светофор (директорский монитор, О-1) */}
          <StorePlanMonitor companyId={companyId} period={monthOf(data.period.to)} />

          {/* Виджет-исключения «работа по исключениям» (О-6) */}
          <StoreExceptionsWidget companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} period={monthOf(data.period.to)} />

          {/* Движение и потери (учёт документов движения в разделе) */}
          <StoreMovementSummary companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />

          {/* KPI-полоса */}
          <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Выручка" value={fmtMoney(f.total_revenue)} delta={t?.revenue?.percent} sub="с НДС" />
            <Kpi label="Без НДС" value={fmtMoney(f.net_revenue)} />
            <Kpi label="НДС" value={fmtMoney(f.vat)} />
            <Kpi label="Выручка/смена" value={fmtMoney(f.avg_check_approx)} delta={t?.avg_check?.percent} sub="не средний чек (ОРП агрегирован)" />
            <Kpi label="Смен" value={nf0(op.shifts_count)} delta={t?.shifts?.percent} />
            {f.returns > 0
              ? <Kpi label="Возвраты" value={fmtMoney(f.returns)} sub="в выручке (gross)" />
              : <Kpi label="Позиций" value={nf0(u.total_positions)} sub={`${nf0(u.total_units)} ед.`} />}
          </div>

          {/* Категории + оплаты */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-border/50 bg-card/40 p-4">
              <div className="text-sm font-medium mb-3">Структура продаж</div>
              <ShareBars rows={u.by_category.map((c) => ({ name: c.category, value: c.revenue, percent: c.percent }))} />
            </div>
            <div className="rounded-lg border border-border/50 bg-card/40 p-4">
              <div className="text-sm font-medium mb-3">Способы оплаты</div>
              <ShareBars rows={(f.payments_detail?.length
                ? f.payments_detail.slice(0, 8)
                : [{ name: 'Наличные', value: f.payments.cash }, { name: 'Безналичные', value: f.payments.card }]
              ).map((p) => ({ name: p.name, value: p.value }))} />
            </div>
          </div>

          {/* Разрез по АЗС (заложен под мультиобъект) */}
          {data.by_station.length > 1 && (
            <div className="rounded-lg border border-border/50 bg-card/40 p-4">
              <div className="text-sm font-medium mb-3">По АЗС</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground"><tr>
                    <th className="text-left font-medium py-1">АЗС</th>
                    <th className="text-right font-medium">Выручка</th>
                    <th className="text-right font-medium">Позиций</th>
                    <th className="text-right font-medium">Смен</th>
                  </tr></thead>
                  <tbody>
                    {data.by_station.map((st) => (
                      <tr key={st.station} className="border-t border-border/30">
                        <td className="py-1">{st.station}</td>
                        <td className="text-right tabular-nums">{fmtMoney(st.revenue)}</td>
                        <td className="text-right tabular-nums">{nf0(st.positions)}</td>
                        <td className="text-right tabular-nums">{nf0(st.shifts)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Дневная динамика */}
          <div className="rounded-lg border border-border/50 bg-card/40 p-4">
            <div className="text-sm font-medium mb-3">Выручка по дням</div>
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={data.charts.daily} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.12} />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => fmtMoneyShort(v)} width={52} />
                <Tooltip {...rechartsTooltipTheme}
                  formatter={(value) => fmtMoney(Number(value))}
                  contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="soputka" name="Сопутка" stackId="a" fill={CHART_SERIES[0]} />
                <Bar dataKey="obshepit" name="Общепит" stackId="a" fill={CHART_SERIES[1]} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Задел под маржу */}
          <div className="rounded-lg border border-dashed border-border/40 p-3 text-xs text-muted-foreground">
            Валовая прибыль, маржа %, GMROI, ABC-анализ — следующий блок: FIFO-себестоимость
            из поступлений (поступления сопутки в периоде уже загружены).
          </div>
        </>
      )}
    </div>
  )
}
