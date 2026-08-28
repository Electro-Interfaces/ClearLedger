/**
 * «Цены по марке» — приём цены, продиктованной пачкой.
 *
 * У маркированного табака цену задаёт не справочник, а сама марка: МРЦ
 * напечатана на пачке, касса читает её из кода и пробивает по ней. Партия с
 * новой МРЦ приезжает без предупреждения, наша цена отстаёт — торговле это не
 * мешает, но выручка и себестоимость по таким позициям считаются по старой
 * цене, то есть занижаются.
 *
 * Экран тот же, что на станции (agent/internal/web/price_mrc.go), но по сети:
 * подорожание приходит ко всем точкам одной волной, и разбирать его по одной
 * АЗС — делать одну работу пять раз.
 *
 * Промежуточного черновика нет намеренно: цена уже действует на полке, мы её не
 * назначаем, а догоняем учётом. Принять можно только строки, объяснённые маркой;
 * остальные расхождения разбираются по позиции — за ними может стоять что
 * угодно, от ошибки кассира до чужого штрихкода.
 *
 * Данные: /api/store/price-mrc · POST /api/store/price-mrc/accept.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Kpi } from './analytics/Kpi'
import { Button } from '@/components/ui/button'
import { StoreCommercialPolicyNotice } from './StoreCommercialPolicyNotice'
import { useCentralCommercialWrite } from './useStoreCommercialPolicy'
import { acceptStorePriceMrc, getStorePriceMrc, type MrcPriceRow } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const ключ = (r: MrcPriceRow) => `${r.station_id}:${r.item_uuid}`

function Таблица({ rows, выбор, переключить, приём }: {
  rows: MrcPriceRow[]
  выбор?: Set<string>
  переключить?: (k: string) => void
  приём: boolean
}) {
  if (!rows.length) return null
  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr className="border-b border-border/50">
            {приём && <th className="w-8 py-1.5" />}
            <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
            <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
            <th className="text-right py-1.5 pr-3 font-medium">Наша цена</th>
            <th className="text-right py-1.5 pr-3 font-medium">Касса пробила</th>
            <th className="text-right py-1.5 pr-3 font-medium">МРЦ</th>
            <th className="text-right py-1.5 pr-3 font-medium">Продано</th>
            <th className="text-right py-1.5 font-medium">Недоучёт</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={ключ(r)} className="border-b border-border/30 hover:bg-accent/30">
              {приём && (
                <td className="py-1.5">
                  <input type="checkbox" checked={выбор?.has(ключ(r)) ?? false}
                         onChange={() => переключить?.(ключ(r))} />
                </td>
              )}
              <td className="py-1.5 pr-3">
                {r.name}
                {r.barcode ? <span className="ml-2 text-muted-foreground/70">{r.barcode}</span> : null}
              </td>
              <td className="py-1.5 pr-3 text-muted-foreground">{r.station_id}</td>
              <td className="py-1.5 pr-3 text-right">{fmtMoney(r.price)}</td>
              <td className="py-1.5 pr-3 text-right font-medium">{fmtMoney(r.cash_price)}</td>
              <td className="py-1.5 pr-3 text-right text-muted-foreground">
                {r.mrc ? fmtMoney(r.mrc) : '—'}
              </td>
              <td className="py-1.5 pr-3 text-right">{nf(r.qty, 2)}</td>
              <td className="py-1.5 text-right text-amber-500">{fmtMoney(r.loss)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function StorePriceMrcPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const centralWrite = useCentralCommercialWrite()
  const [выбор, setВыбор] = useState<Set<string>>(new Set())
  const [итог, setИтог] = useState<string | null>(null)
  const scopeKey = stations?.join(',') || ''

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-price-mrc', companyId, dateFrom, dateTo, scopeKey],
    queryFn: () => getStorePriceMrc(dateFrom, dateTo, stations),
  })

  const приём = useMutation({
    mutationFn: () => acceptStorePriceMrc(dateFrom, dateTo, stations,
                                          выбор.size ? [...выбор] : undefined),
    onSuccess: (r) => {
      setИтог(`${r.note}. Принято цен: ${r.accepted}, станций: ${r.stations}.`)
      setВыбор(new Set())
      refetch()
    },
    onError: (e: unknown) => setИтог(e instanceof Error ? e.message : 'Не удалось принять цены'),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Сверяем цены с маркой…</div>
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400/90">
        Не удалось сверить цены с маркой.{' '}
        <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
      </div>
    )
  }

  const поМарке = data.rows.filter((r) => r.by_mark)
  const прочие = data.rows.filter((r) => !r.by_mark)
  const переключить = (k: string) => setВыбор((prev) => {
    const next = new Set(prev)
    if (next.has(k)) next.delete(k)
    else next.add(k)
    return next
  })

  return (
    <div className="p-4 md:p-6 space-y-6">
      <StoreCommercialPolicyNotice />
      <div>
        <h2 className="text-lg font-semibold">Цены по марке</h2>
        <p className="text-sm text-muted-foreground max-w-4xl mt-1">
          У маркированного табака цену диктует пачка: касса читает МРЦ из кода и пробивает по
          ней. Здесь видно, где наша цена отстала и сколько выручки на этом посчитано мимо.
          Период {data.period.from} — {data.period.to}
          {stations?.length ? ` · АЗС ${stations.join(', ')}` : ' · вся сеть'}.
        </p>
      </div>

      {data.note && (
        <div className="rounded-md border border-amber-400/30 bg-amber-500/[0.06] px-3 py-2 text-sm">
          {data.note}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Объяснено маркой" value={nf(поМарке.length)}
             sub={`недоучёт ${fmtMoney(data.loss_mark)}`} />
        <Kpi label="Прочие расхождения" value={nf(прочие.length)}
             sub={`недоучёт ${fmtMoney(data.loss_other)}`} />
        <Kpi label="Станций затронуто" value={nf(data.by_station.length)}
             sub="подорожание приходит волной по всей сети" />
        <Kpi label="Всего мимо учёта" value={fmtMoney(data.loss_mark + data.loss_other)}
             sub="разница цены × проданное количество" />
      </div>

      {итог && (
        <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm">{итог}</div>
      )}

      <section className="rounded-lg border border-border/50 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Догнать марку</h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-3xl">
              Касса пробила ровно по МРЦ — цену принимаем как факт, а не как решение. Ничего не
              выбрано — принимаются все строки этого списка; галочками можно взять часть.
              Новая цена уйдёт на станцию обычным заданием и заодно ляжет в историю центра.
            </p>
          </div>
          <Button size="sm" disabled={!поМарке.length || !centralWrite || приём.isPending}
                  onClick={() => приём.mutate()}>
            {приём.isPending ? 'Принимаем…'
              : `Принять цену${выбор.size ? ` (${выбор.size})` : поМарке.length ? ' (все)' : ''}`}
          </Button>
        </div>
        {!centralWrite && поМарке.length > 0 && (
          <p className="text-xs text-amber-200/70 mt-2">
            В режиме «станция» цену принимает администратор АЗС у себя в агенте — здесь список
            остаётся справкой.
          </p>
        )}
        {поМарке.length === 0 ? (
          <div className="text-xs text-muted-foreground py-3">
            Расхождений, объяснённых маркой, нет: наши цены совпадают с тем, по чему пробивает касса.
          </div>
        ) : (
          <Таблица rows={поМарке} выбор={выбор} переключить={переключить} приём />
        )}
      </section>

      {прочие.length > 0 && (
        <section className="rounded-lg border border-border/50 p-4">
          <h3 className="text-sm font-semibold">Расхождения без объяснения маркой</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-3xl">
            Касса пробила дороже нашей цены, но МРЦ этого не объясняет. Такое принимать вслепую
            нельзя: за строкой может стоять ошибка кассира, чужой штрихкод или незамеченная
            переоценка на станции. Разбирается по позиции.
          </p>
          <Таблица rows={прочие} приём={false} />
        </section>
      )}

      {data.by_station.length > 1 && (
        <section className="rounded-lg border border-border/50 p-4">
          <h3 className="text-sm font-semibold">По станциям</h3>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border/50">
                  <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Позиций</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Из них по марке</th>
                  <th className="text-right py-1.5 font-medium">Недоучёт</th>
                </tr>
              </thead>
              <tbody>
                {data.by_station.map((с) => (
                  <tr key={с.station_id} className="border-b border-border/30">
                    <td className="py-1.5 pr-3">{с.station_id}</td>
                    <td className="py-1.5 pr-3 text-right">{nf(с.rows)}</td>
                    <td className="py-1.5 pr-3 text-right">{nf(с.by_mark)}</td>
                    <td className="py-1.5 text-right text-amber-500">{fmtMoney(с.loss)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
