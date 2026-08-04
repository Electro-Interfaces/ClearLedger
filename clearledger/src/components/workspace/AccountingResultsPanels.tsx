/**
 * «Итоги» — то, что видно после закрытия, а не во время него.
 *
 * Два экрана. «Динамика по месяцам» отвечает на вопрос, который не задаёт ни одна
 * цифра за один месяц: нормально ли то, что мы видим. «Маржа потоков» ставит рядом
 * три источника прибыли станции, потому что по-отдельности они лежат в трёх разных
 * разделах и никогда не сравнивались.
 */
import { useQuery } from '@tanstack/react-query'
import { Fuel, ShoppingCart, ChefHat, Loader2 } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { get } from '@/services/apiClient'
import { getStorePricing, getStoreCateringMenu } from '@/services/storeService'
import { getCostingMargin } from '@/services/fuel/fuelMappingService'
import { fmtMoney, fmtPct } from '@/services/analyticsService'

const H3 = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
const fmtN = (v: number) => (v ?? 0).toLocaleString('ru-RU')
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

interface TrendMonth {
  year: number; month: number
  fuelShifts: number; fuelAmount: number; fuelLiters: number
  storeShifts: number; soputka: number; obshepit: number
  docs1c: number; unposted: number
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  ДИНАМИКА ПО МЕСЯЦАМ                                                       */
/* ══════════════════════════════════════════════════════════════════════════ */

export function AccountingTrendPanel() {
  const { companyId } = useCompany()
  const trend = useQuery({
    queryKey: ['periods-trend', companyId],
    queryFn: () => get<TrendMonth[]>('/api/periods/trend', { company_id: companyId, months: '8' }),
  })

  const rows = trend.data ?? []
  const maxFuel = Math.max(1, ...rows.map((r) => r.fuelAmount))
  const maxStore = Math.max(1, ...rows.map((r) => r.soputka + r.obshepit))

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Динамика по месяцам</h2>
        <span className="text-xs text-muted-foreground">
          восемь месяцев по трём потокам — провал виден без арифметики
        </span>
      </div>

      {trend.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Собираем ряд…
        </div>
      ) : rows.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">Данных за последние месяцы нет.</p>
      ) : (
        <>
          <Card>
            <CardContent className="pt-4">
              <div className="mb-3 flex items-center gap-2">
                <Fuel className="h-4 w-4 text-primary" />
                <h3 className={H3}>Выручка по месяцам</h3>
              </div>
              {/* Столбики — доли одной величины, а не украшение: топливо и товарный
                  контур масштабируются каждый к своему максимуму, иначе магазин на
                  фоне топлива превращается в невидимую полоску. */}
              <div className="flex items-end gap-2 overflow-x-auto pb-1">
                {rows.map((r) => (
                  <div key={`${r.year}-${r.month}`} className="flex min-w-[52px] flex-1 flex-col items-center gap-1">
                    <div className="flex h-28 w-full items-end justify-center gap-1">
                      <div className="w-1/2 rounded-t bg-primary/70"
                        style={{ height: `${Math.max(2, (r.fuelAmount / maxFuel) * 100)}%` }}
                        title={`Топливо: ${fmtMoney(r.fuelAmount)}`} />
                      <div className="w-1/2 rounded-t bg-emerald-500/60"
                        style={{ height: `${Math.max(2, ((r.soputka + r.obshepit) / maxStore) * 100)}%` }}
                        title={`Магазин и общепит: ${fmtMoney(r.soputka + r.obshepit)}`} />
                    </div>
                    <span className="text-[10px] text-muted-foreground">
                      {MONTHS_SHORT[r.month - 1]}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-2 flex gap-4 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-primary/70" />топливо
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500/60" />магазин и общепит
                </span>
                <span>масштаб у каждого свой</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-4">
              <div className="mb-3 flex items-center gap-2">
                <ShoppingCart className="h-4 w-4 text-primary" />
                <h3 className={H3}>Месяц за месяцем</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-[11px] text-muted-foreground">
                      <th className="py-1.5 text-left font-medium">Месяц</th>
                      <th className="py-1.5 text-right font-medium">Смен топлива</th>
                      <th className="py-1.5 text-right font-medium">Выручка топлива</th>
                      <th className="py-1.5 text-right font-medium">Литры</th>
                      <th className="py-1.5 text-right font-medium">Смен магазина</th>
                      <th className="py-1.5 text-right font-medium">Сопутка</th>
                      <th className="py-1.5 text-right font-medium">Общепит</th>
                      <th className="py-1.5 text-right font-medium">Док. 1С</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => {
                      const prev = rows[i - 1]
                      // Падение больше трети от прошлого месяца — либо станция встала,
                      // либо данные не доехали. Оба ответа требуют действий, поэтому
                      // такая строка обязана бросаться в глаза.
                      const drop = !!prev && prev.fuelShifts > 0
                        && r.fuelShifts < prev.fuelShifts * 0.66
                      return (
                        <tr key={`${r.year}-${r.month}`} className="border-b border-border/30">
                          <td className="py-1.5 font-medium">
                            {MONTHS_SHORT[r.month - 1]} {r.year}
                          </td>
                          <td className={cn('py-1.5 text-right tabular-nums',
                            drop && 'font-semibold text-amber-600 dark:text-amber-400')}>
                            {fmtN(r.fuelShifts)}
                            {drop && <span className="ml-1 text-[10px]">спад</span>}
                          </td>
                          <td className="py-1.5 text-right tabular-nums">{fmtMoney(r.fuelAmount)}</td>
                          <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                            {fmtN(Math.round(r.fuelLiters))}
                          </td>
                          <td className="py-1.5 text-right tabular-nums">{fmtN(r.storeShifts)}</td>
                          <td className="py-1.5 text-right tabular-nums">{fmtMoney(r.soputka)}</td>
                          <td className="py-1.5 text-right tabular-nums">{fmtMoney(r.obshepit)}</td>
                          <td className="py-1.5 text-right tabular-nums">
                            {fmtN(r.docs1c)}
                            {r.unposted > 0 && (
                              <span className="ml-1 text-[10px] text-amber-600 dark:text-amber-400">
                                +{fmtN(r.unposted)} не пров.
                              </span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  МАРЖА ТРЁХ ПОТОКОВ                                                        */
/* ══════════════════════════════════════════════════════════════════════════ */

/**
 * Три источника прибыли станции рядом.
 *
 * Порознь они лежат в трёх разделах и считаются по-разному: топливо — FIFO по
 * партиям, сопутка — закупочная себестоимость карточки, общепит — разворот
 * техкарты. Сравнивать проценты в лоб нельзя, и подпись об этом говорит; но
 * увидеть, где на самом деле зарабатывает станция, можно только так.
 */
export function StreamMarginSummary() {
  const { companyId } = useCompany()
  const { period } = useFilters()

  const fuel = useQuery({
    queryKey: ['costing-margin', companyId, period.from, period.to, 'fuel'],
    queryFn: () => getCostingMargin(period.from, period.to, 'fuel'),
  })
  const pricing = useQuery({
    queryKey: ['store-pricing', companyId, period.from, period.to, 'soputka'],
    queryFn: () => getStorePricing(period.from, period.to, 'soputka'),
  })
  const catering = useQuery({
    queryKey: ['store-catering', companyId, period.from, period.to],
    queryFn: () => getStoreCateringMenu(period.from, period.to),
  })

  const fuelTotals = fuel.data?.totals
  const sop = pricing.data?.summary
  const cat = catering.data?.summary

  const streams = [
    {
      icon: Fuel, title: 'Нефтепродукты',
      // Покрытие себестоимостью у топлива своё: литры без закупочной партии в
      // марже не участвуют, и молчать об этом нельзя — процент был бы завышен.
      basis: fuelTotals && fuelTotals.coverage_pct < 99
        ? `FIFO по партиям · себестоимость известна для ${Math.round(fuelTotals.coverage_pct)}% литров`
        : 'FIFO по закупочным партиям',
      revenue: fuelTotals?.revenue ?? 0, margin: fuelTotals?.margin ?? null,
      pct: fuelTotals?.margin_pct ?? null,
      loading: fuel.isLoading,
    },
    {
      icon: ShoppingCart, title: 'Сопутка', basis: 'себестоимость карточки',
      revenue: sop?.revenue ?? 0, margin: sop?.margin ?? null,
      pct: sop?.margin_pct ?? null,
      loading: pricing.isLoading,
    },
    {
      icon: ChefHat, title: 'Общепит', basis: 'разворот техкарты',
      revenue: cat?.revenue ?? 0, margin: cat?.margin ?? null,
      pct: cat?.margin_pct ?? null,
      loading: catering.isLoading,
    },
  ]

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-3 flex items-center gap-2">
          <ShoppingCart className="h-4 w-4 text-primary" />
          <h3 className={H3}>Маржа трёх потоков</h3>
          <span className="ml-auto text-[11px] text-muted-foreground">
            {period.from} — {period.to}
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {streams.map((s) => (
            <div key={s.title} className="rounded-lg border border-border bg-background p-3">
              <div className="flex items-center gap-2">
                <s.icon className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">{s.title}</span>
              </div>
              {s.loading ? (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> считаем…
                </div>
              ) : (
                <>
                  <div className="mt-1.5 text-xl font-bold tabular-nums">
                    {s.pct === null ? '—' : fmtPct(s.pct)}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    выручка {fmtMoney(s.revenue)}
                    {s.margin !== null && ` · маржа ${fmtMoney(s.margin)}`}
                  </div>
                </>
              )}
              <div className="mt-1.5 text-[10px] text-muted-foreground/70">{s.basis}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
          Проценты считаются по-разному и в лоб не сравниваются: у топлива себестоимость берётся из
          партий поставки, у сопутки — из карточки товара, у общепита — сборкой по техкарте, и там,
          где техкарта неполна, маржа завышена. Смысл в другом: видно, какой контур приносит
          деньги, а какой их только оборачивает.
        </p>
      </CardContent>
    </Card>
  )
}
