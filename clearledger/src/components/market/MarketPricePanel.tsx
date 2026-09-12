/**
 * «Цена и позиция» (docs/MARKET-ROADMAP.md §9, этап 4) — три экрана одного вопроса:
 * почём рынок, что с нами сделал сосед и что делает с нами собственная цена.
 *
 * Все три заканчиваются фразой, которую менеджер может сказать вслух, и рядом —
 * оговорка о том, чего в расчёте нет. Показатель с непроговорённым допущением
 * опаснее отсутствия показателя: по нему принимают решение, не зная поправки.
 */
import { useQuery } from '@tanstack/react-query'
import { Banknote, Swords, TrendingDown } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getMarketElasticity, getMarketPressure, getMarketPriceLandscape,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function Num({ v, unit, digits = 1 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  const f = digits === 0 ? nf : digits === 2 ? nf2 : nf1
  return <span className="tabular-nums">{f.format(v)}{unit ? ` ${unit}` : ''}</span>
}

function Skeleton() {
  return (
    <div className="space-y-2 p-4" aria-busy="true">
      <span className="sr-only">Считаем цену рынка</span>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg border border-border bg-muted/40" />
      ))}
    </div>
  )
}

/** Ценовой ландшафт: почём рынок по классам мощности и где в нём мы. */
export function MarketPriceLandscapePanel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['market-price-landscape', companyId],
    queryFn: () => getMarketPriceLandscape(companyId, { days: 90 }),
    enabled: !!companyId,
  })
  if (q.isLoading) return <Skeleton />
  const d = q.data
  const gap = d?.gapPct
  const verdict = !d?.marketMedianPerKwh
    ? 'Цен рынка пока не наблюдали — сравнивать не с чем.'
    : gap == null
      ? `Медиана рынка ${nf1.format(d.marketMedianPerKwh)} ₽/кВт·ч; нашей цены за период нет.`
      : gap > 5
        ? `Мы дороже рынка на ${nf1.format(gap)} % (${nf1.format(d.ourPricePerKwh ?? 0)} против ${nf1.format(d.marketMedianPerKwh)} ₽/кВт·ч).`
        : gap < -5
          ? `Мы дешевле рынка на ${nf1.format(Math.abs(gap))} % (${nf1.format(d.ourPricePerKwh ?? 0)} против ${nf1.format(d.marketMedianPerKwh)} ₽/кВт·ч).`
          : 'Наша цена держится на уровне рынка.'

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Banknote className="size-4 text-primary" aria-hidden />{verdict}
          </span>
          <span className="text-xs text-muted-foreground">
            цена известна у {nf.format(d?.pricedSites ?? 0)} чужих точек
            {d?.unknownPower ? `, из них без мощности ${nf.format(d.unknownPower)}` : ''}
          </span>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="mb-2 font-headline text-sm font-semibold">По классам мощности</div>
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-medium">Класс</th>
                <th className="py-1 text-right font-medium">Точек с ценой</th>
                <th className="py-1 text-right font-medium">Нижняя четверть</th>
                <th className="py-1 text-right font-medium">Медиана</th>
                <th className="py-1 text-right font-medium">Верхняя четверть</th>
              </tr>
            </thead>
            <tbody>
              {(d?.buckets ?? []).map((b) => (
                <tr key={b.bucket} className="border-t border-border/40">
                  <td className="py-1">{b.bucket}</td>
                  <td className="py-1 text-right"><Num v={b.sites} digits={0} /></td>
                  <td className="py-1 text-right"><Num v={b.low} /></td>
                  <td className="py-1 text-right font-medium"><Num v={b.median} /></td>
                  <td className="py-1 text-right"><Num v={b.high} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">
            Медленная зарядка у торгового центра и быстрая на трассе — разный товар.
            Общая медиана по ним обеим не значит ничего, поэтому цена разложена по
            классам, а мощность есть не у всех точек: строки с пустой мощностью в
            классы не попадают.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

/** Давление конкурента: кто открылся рядом и что стало с нашими сессиями. */
export function MarketPressurePanel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['market-pressure', companyId],
    queryFn: () => getMarketPressure(companyId, { months: 24 }),
    enabled: !!companyId,
  })
  if (q.isLoading) return <Skeleton />
  const rows = q.data?.rows ?? []
  const dropped = rows.filter((r) => (r.changePct ?? 0) < -10)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Swords className="size-4 text-primary" aria-hidden />
            {rows.length === 0
              ? 'Рядом с нашими объектами новых соседей за два года не появилось — или мы их ещё не наблюдали.'
              : `У ${rows.length} наших объектов рядом появился сосед; у ${dropped.length} из них сессии просели больше чем на 10 %.`}
          </span>
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Наш объект</th>
              <th className="p-2 text-left font-medium">Кто появился</th>
              <th className="p-2 text-right font-medium">Дистанция</th>
              <th className="p-2 text-left font-medium">Когда</th>
              <th className="p-2 text-right font-medium">Сессий до</th>
              <th className="p-2 text-right font-medium">После</th>
              <th className="p-2 text-right font-medium">Изменение</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.locationId} className="border-t border-border/60">
                <td className="p-2 font-medium">{r.name}
                  {r.city && <span className="text-muted-foreground"> · {r.city}</span>}
                </td>
                <td className="p-2">{r.rivalName}
                  {r.rivalOperator && <span className="text-muted-foreground"> · {r.rivalOperator}</span>}
                </td>
                <td className="p-2 text-right"><Num v={r.distanceKm} unit="км" /></td>
                <td className="p-2 tabular-nums text-muted-foreground">{r.appearedOn}</td>
                <td className="p-2 text-right"><Num v={r.sessionsBefore} digits={0} /></td>
                <td className="p-2 text-right"><Num v={r.sessionsAfter} digits={0} /></td>
                <td className="p-2 text-right">
                  {r.changePct == null ? <span className="text-muted-foreground">—</span> : (
                    <span className={`tabular-nums ${r.changePct < -10 ? 'text-warning'
                      : r.changePct > 10 ? 'text-success' : ''}`}>
                      {r.changePct > 0 ? '+' : ''}{nf1.format(r.changePct)} %
                      <span className="ml-1 font-normal text-muted-foreground">
                        {r.changePct < -10 ? 'просели' : r.changePct > 10 ? 'выросли' : 'без перемен'}
                      </span>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{q.data?.note}</p>
    </div>
  )
}

/** Эластичность: что было с сессиями после изменения нашей цены. */
export function MarketElasticityPanel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['market-elasticity', companyId],
    queryFn: () => getMarketElasticity(companyId, { weeks: 52 }),
    enabled: !!companyId,
  })
  if (q.isLoading) return <Skeleton />
  const cases = q.data?.cases ?? []
  const median = q.data?.medianElasticity

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <TrendingDown className="size-4 text-primary" aria-hidden />
            {cases.length === 0
              ? 'Заметных изменений цены за год не было — отклик мерить не на чем.'
              : median == null
                ? `Найдено ${q.data?.total} изменений цены, но отклик посчитать не удалось.`
                : `Найдено ${q.data?.total} изменений цены. Медианный отклик: на каждый процент цены спрос меняется на ${nf2.format(Math.abs(median))} %` }
          </span>
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Объект</th>
              <th className="p-2 text-left font-medium">Неделя</th>
              <th className="p-2 text-right font-medium">Цена была</th>
              <th className="p-2 text-right font-medium">Стала</th>
              <th className="p-2 text-right font-medium">Цена, %</th>
              <th className="p-2 text-right font-medium">Сессии, %</th>
              <th className="p-2 text-right font-medium">Отклик</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c, i) => (
              <tr key={`${c.locationId}-${c.week}-${i}`} className="border-t border-border/60">
                <td className="p-2 font-medium">{c.name}</td>
                <td className="p-2 tabular-nums text-muted-foreground">{c.week}</td>
                <td className="p-2 text-right"><Num v={c.priceWas} digits={2} /></td>
                <td className="p-2 text-right"><Num v={c.priceNow} digits={2} /></td>
                <td className="p-2 text-right tabular-nums">
                  {c.pricePct > 0 ? '+' : ''}{nf1.format(c.pricePct)}
                </td>
                <td className="p-2 text-right tabular-nums">
                  {c.sessionsPct > 0 ? '+' : ''}{nf1.format(c.sessionsPct)}
                </td>
                <td className="p-2 text-right"><Num v={c.elasticity} digits={2} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        {q.data?.note} Отрицательный отклик — обычное поведение: дороже, значит меньше.
        Положительный чаще означает, что в ту же неделю случилось что-то ещё.
      </p>
    </div>
  )
}
