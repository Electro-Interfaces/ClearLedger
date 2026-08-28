/**
 * «Динамика» — что изменилось по сети и за счёт чего.
 *
 * Остальные экраны раздела отвечают на «как сейчас». Этот отвечает на «что
 * изменилось», и это другой вопрос: «маржа упала на двести тысяч» — не вывод,
 * пока не сказано, упала она от цен, от спроса, от подорожавшей закупки, от
 * простоя станции или оттого, что перестали возить половину ассортимента.
 *
 * Раскладка — мост price-volume-mix, ровно тот же, что считает станция в своём
 * рабочем месте (agent/internal/store/compare.go). Центр и АЗС обязаны
 * объяснять одну разницу одинаково: иначе разбор месяца превращается в спор
 * двух отчётов, а не в разговор о торговле.
 *
 * Данные: /api/store/dynamics · /api/store/price-log.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Kpi } from './analytics/Kpi'
import { getStoreDynamics, getStorePriceLog, getStorePriceResponse, type DynamicsRow } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const знак = (n: number) => (n > 0 ? '+' : '')
const деньги = (n: number) => `${знак(n)}${fmtMoney(n)}`

/** Причины изменения маржи — подписи и объяснения на языке торговли. */
const ПРИЧИНЫ: { key: 'price' | 'cost' | 'volume' | 'new' | 'gone'; label: string; about: string }[] = [
  { key: 'price', label: 'Цена', about: 'продали столько же, но по другой цене' },
  { key: 'cost', label: 'Себестоимость', about: 'закупка подешевела или подорожала' },
  { key: 'volume', label: 'Объём', about: 'спрос: продали больше или меньше штук' },
  { key: 'new', label: 'Новинки', about: 'позиции, которых в прошлом периоде не продавали' },
  { key: 'gone', label: 'Выбывшие', about: 'перестали продавать — маржа ушла целиком' },
]

function Полоса({ доля, вниз }: { доля: number; вниз: boolean }) {
  return (
    <div className="h-2 w-full rounded-full bg-muted/40">
      <div
        className={`h-2 rounded-full ${вниз ? 'bg-amber-500/60' : 'bg-emerald-500/60'}`}
        style={{ width: `${Math.max(2, Math.min(100, доля))}%` }}
      />
    </div>
  )
}

function ТаблицаВкладов({ rows, empty }: { rows: DynamicsRow[]; empty: string }) {
  if (!rows.length) return <div className="text-xs text-muted-foreground py-3">{empty}</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr className="border-b border-border/50">
            <th className="text-left py-1.5 pr-3 font-medium">Позиция</th>
            <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
            <th className="text-right py-1.5 pr-3 font-medium">Продано</th>
            <th className="text-right py-1.5 pr-3 font-medium">Цена</th>
            <th className="text-right py-1.5 pr-3 font-medium">Маржа</th>
            <th className="text-right py-1.5 pr-3 font-medium">Изменение</th>
            <th className="text-left py-1.5 font-medium">Судьба</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.station_id}-${r.item_uuid}-${i}`}
                className="border-b border-border/30 hover:bg-accent/30">
              <td className="py-1.5 pr-3">{r.name}</td>
              <td className="py-1.5 pr-3 text-muted-foreground">{r.station_id}</td>
              <td className="py-1.5 pr-3 text-right">{nf(r.qty_prev, 1)} → {nf(r.qty, 1)}</td>
              <td className="py-1.5 pr-3 text-right text-muted-foreground">
                {fmtMoney(r.price_prev)} → {fmtMoney(r.price)}
              </td>
              <td className="py-1.5 pr-3 text-right">
                {fmtMoney(r.margin_prev)} → <b>{fmtMoney(r.margin)}</b>
              </td>
              <td className={`py-1.5 pr-3 text-right font-medium ${r.delta_margin < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                {деньги(r.delta_margin)}
              </td>
              <td className="py-1.5 text-muted-foreground">{r.fate || 'была и осталась'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function StoreDynamicsPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const [pricePage, setPricePage] = useState({ scope: '', offset: 0 })
  const pageSize = 100
  const scopeKey = stations?.join(',') || ''
  const priceScope = [companyId, dateFrom, dateTo, scopeKey].join('|')
  const priceOffset = pricePage.scope === priceScope ? pricePage.offset : 0

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-dynamics', companyId, dateFrom, dateTo, scopeKey],
    queryFn: () => getStoreDynamics(dateFrom, dateTo, stations),
  })
  // Отклик на цену живёт своим горизонтом: он привязан не к периоду экрана, а к
  // дате самого изменения — окно наблюдения отсчитывается от неё.
  const { data: отклики } = useQuery({
    queryKey: ['store-price-response', companyId, scopeKey],
    queryFn: () => getStorePriceResponse(14, stations),
  })
  const { data: журнал, error: ошибкаЖурнала, refetch: повторитьЖурнал } = useQuery({
    queryKey: ['store-price-log', companyId, dateFrom, dateTo, scopeKey, priceOffset],
    queryFn: () => getStorePriceLog(dateFrom, dateTo, stations, priceOffset, pageSize),
  })

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Считаем изменения…</div>
  }
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400/90">
        Не удалось рассчитать динамику.{' '}
        <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
      </div>
    )
  }
  const t = data.total
  const макс = Math.max(...ПРИЧИНЫ.map((п) => Math.abs(data.factors[п.key])), 1)

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Динамика</h2>
        <p className="text-sm text-muted-foreground max-w-4xl mt-1">
          Что изменилось по сравнению с прошлым таким же периодом и <b>за счёт чего именно</b>.
          Сравниваем {data.period.from} — {data.period.to} с {data.period_prev.from} — {data.period_prev.to}.
        </p>
      </div>

      {!data.has_prev && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          В предыдущем периоде продаж нет — сравнивать не с чем. Возьмите период короче
          или подождите, пока накопится история.
        </div>
      )}

      {Math.abs(t.cost_known_pct - t.cost_known_pct_prev) > 5 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          Себестоимость известна по {nf(t.cost_known_pct, 1)} % выручки сейчас и по{' '}
          {nf(t.cost_known_pct_prev, 1)} % в прошлом периоде. Там, где закупочной цены нет,
          маржа считается равной выручке — поэтому период с худшим покрытием выглядит
          прибыльнее, чем был. Разница долей маржи ниже частично объясняется этим, а не торговлей.
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Выручка" value={fmtMoney(t.revenue)}
             sub={`было ${fmtMoney(t.revenue_prev)} · ${деньги(t.delta_revenue)}`} />
        <Kpi label="Маржа" value={fmtMoney(t.margin)}
             sub={`было ${fmtMoney(t.margin_prev)} · ${деньги(t.delta_margin)}`} />
        <Kpi label="Доля маржи" value={`${nf(t.margin_pct, 1)} %`}
             sub={`было ${nf(t.margin_pct_prev, 1)} % · ${знак(t.margin_pct - t.margin_pct_prev)}${nf(t.margin_pct - t.margin_pct_prev, 1)} пунктов`} />
        <Kpi label="Себестоимость известна" value={`${nf(t.cost_known_pct, 1)} %`}
             sub={`выручки · в прошлом периоде ${nf(t.cost_known_pct_prev, 1)} %`} />
      </div>

      <section className="rounded-lg border border-border/50 p-4">
        <h3 className="text-sm font-semibold">За счёт чего изменилась маржа</h3>
        <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
          Пять причин, и вместе они дают ровно ту разницу, что в карточке выше — {деньги(t.delta_margin)}.
          Сходимость и делает раскладку проверяемой: считается по позициям, а не прикидкой.
        </p>
        <table className="w-full text-xs mt-3">
          <tbody>
            {ПРИЧИНЫ.map((п) => {
              const v = data.factors[п.key]
              return (
                <tr key={п.key} className="border-b border-border/30">
                  <td className="py-2 pr-3 w-32">{п.label}</td>
                  <td className={`py-2 pr-3 text-right w-32 font-medium ${v < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                    {деньги(v)}
                  </td>
                  <td className="py-2 pr-3 w-1/3"><Полоса доля={(Math.abs(v) / макс) * 100} вниз={v < 0} /></td>
                  <td className="py-2 text-muted-foreground">{п.about}</td>
                </tr>
              )
            })}
            <tr>
              <td className="py-2 pr-3 font-semibold">Итого</td>
              <td className="py-2 pr-3 text-right font-semibold">{деньги(data.factors_sum)}</td>
              <td />
              <td className="py-2 text-muted-foreground">совпадает с изменением маржи</td>
            </tr>
          </tbody>
        </table>
      </section>

      {data.by_station.length > 1 && (
        <section className="rounded-lg border border-border/50 p-4">
          <h3 className="text-sm font-semibold">По станциям</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Сеть одной цифрой прячет провал отдельной точки — поэтому разрез стоит рядом с итогом.
          </p>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border/50">
                  <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Выручка</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Δ выручки</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Маржа</th>
                  <th className="text-right py-1.5 font-medium">Δ маржи</th>
                </tr>
              </thead>
              <tbody>
                {data.by_station.map((с) => (
                  <tr key={с.station_id} className="border-b border-border/30">
                    <td className="py-1.5 pr-3">{с.station_id}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtMoney(с.revenue)}</td>
                    <td className={`py-1.5 pr-3 text-right ${с.delta_revenue < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                      {деньги(с.delta_revenue)}
                    </td>
                    <td className="py-1.5 pr-3 text-right">{fmtMoney(с.margin)}</td>
                    <td className={`py-1.5 text-right font-medium ${с.delta_margin < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                      {деньги(с.delta_margin)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="rounded-lg border border-border/50 p-4">
        <h3 className="text-sm font-semibold">Что вытянуло период</h3>
        {data.up_total > data.up.length && (
          <p className="text-xs text-muted-foreground mt-1">Показаны 20 наибольших вкладов из {nf(data.up_total)}.</p>
        )}
        <ТаблицаВкладов rows={data.up} empty="Прироста маржи нет ни по одной позиции." />
      </section>

      <section className="rounded-lg border border-border/50 p-4">
        <h3 className="text-sm font-semibold">Что утянуло вниз</h3>
        <p className="text-xs text-muted-foreground mt-1">
          «Выбыла» значит, что позицию перестали продавать совсем — чаще всего это не решение,
          а кончившийся товар.
        </p>
        {data.down_total > data.down.length && (
          <p className="text-xs text-muted-foreground mt-1">Показаны 20 наибольших потерь из {nf(data.down_total)}.</p>
        )}
        <ТаблицаВкладов rows={data.down} empty="Потерь маржи нет." />
      </section>

      {ошибкаЖурнала && (
        <section className="rounded-lg border border-red-500/30 p-4 text-sm text-red-400/90">
          Не удалось загрузить журнал цен.{' '}
          <button type="button" className="underline" onClick={() => повторитьЖурнал()}>Повторить</button>
        </section>
      )}

      {!!отклики?.rows.length && (
        <section className="rounded-lg border border-border/50 p-4">
          <h3 className="text-sm font-semibold">Как спрос ответил на цену</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
            Подняли — и что стало. Это <b>наблюдение</b>, а не закон: контрольной группы и
            очищенного от сезонности ряда у розницы АЗС нет, поэтому рядом с каждой строкой
            стоит число дней, на которых она построена. Окно — {отклики.window} дней до и после.
            Эластичность −1 значит «процент цены съел процент спроса»; около нуля — покупателю
            всё равно, цена ниже возможной.
          </p>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border/50">
                  <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
                  <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Цена</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Спрос в день</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Маржа в день</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Чувствительность</th>
                  <th className="text-left py-1.5 font-medium">Вывод</th>
                </tr>
              </thead>
              <tbody>
                {отклики.rows.map((о, i) => (
                  <tr key={`${о.station_id}-${о.item_uuid}-${i}`}
                      className="border-b border-border/30 hover:bg-accent/30">
                    <td className="py-1.5 pr-3">
                      {о.name}
                      <div className="text-[11px] text-muted-foreground">
                        {о.at ? new Date(о.at).toLocaleDateString('ru-RU') : '—'} · {о.author || 'без автора'}
                        {' · '}{о.days_prev} и {о.days} дн.
                      </div>
                    </td>
                    <td className="py-1.5 pr-3 text-muted-foreground">{о.station_id}</td>
                    <td className="py-1.5 pr-3 text-right">
                      {fmtMoney(о.price_prev)} → {fmtMoney(о.price)}
                      <div className="text-[11px] text-muted-foreground">
                        {знак(о.price_pct)}{nf(о.price_pct, 1)} %
                      </div>
                    </td>
                    <td className="py-1.5 pr-3 text-right">
                      {nf(о.qty_day_prev, 2)} → {nf(о.qty_day, 2)}
                      <div className={`text-[11px] ${о.qty_pct < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                        {знак(о.qty_pct)}{nf(о.qty_pct, 1)} %
                      </div>
                    </td>
                    <td className="py-1.5 pr-3 text-right">
                      {fmtMoney(о.margin_day_prev)} → <b>{fmtMoney(о.margin_day)}</b>
                      <div className={`text-[11px] ${о.margin_pct < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                        {знак(о.margin_pct)}{nf(о.margin_pct, 1)} %
                      </div>
                    </td>
                    <td className="py-1.5 pr-3 text-right">
                      {о.elasticity == null ? '—' : nf(о.elasticity, 2)}
                    </td>
                    <td className="py-1.5 text-muted-foreground">{о.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {!ошибкаЖурнала && !!журнал?.rows.length && (
        <section className="rounded-lg border border-border/50 p-4">
          <h3 className="text-sm font-semibold">Журнал цен сети</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Кто и когда двигал цену. Без журнала любой разговор о цене упирается в память.
          </p>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border/50">
                  <th className="text-left py-1.5 pr-3 font-medium">Когда</th>
                  <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Было</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Стало</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Δ</th>
                  <th className="text-left py-1.5 font-medium">Автор</th>
                </tr>
              </thead>
              <tbody>
                {журнал.rows.map((r, i) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-accent/30">
                    <td className="py-1.5 pr-3 text-muted-foreground">
                      {r.at ? new Date(r.at).toLocaleDateString('ru-RU') : '—'}
                    </td>
                    <td className="py-1.5 pr-3 text-muted-foreground">{r.station_id}</td>
                    <td className="py-1.5 pr-3">{r.name}</td>
                    <td className="py-1.5 pr-3 text-right text-muted-foreground">
                      {r.price_prev != null ? fmtMoney(r.price_prev) : '—'}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-medium">{fmtMoney(r.price)}</td>
                    <td className={`py-1.5 pr-3 text-right ${(r.delta ?? 0) < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                      {r.delta != null ? деньги(r.delta) : '—'}
                    </td>
                    <td className="py-1.5 text-muted-foreground">{r.author || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>
              {nf(журнал.offset + 1)}–{nf(журнал.offset + журнал.rows.length)} из {nf(журнал.total)} изменений
            </span>
            <div className="flex gap-2">
              <button type="button" disabled={журнал.offset === 0}
                className="rounded border border-border px-2 py-1 disabled:opacity-40"
                onClick={() => setPricePage({ scope: priceScope, offset: Math.max(0, журнал.offset - журнал.limit) })}>
                Назад
              </button>
              <button type="button" disabled={!журнал.truncated}
                className="rounded border border-border px-2 py-1 disabled:opacity-40"
                onClick={() => setPricePage({ scope: priceScope, offset: журнал.offset + журнал.limit })}>
                Дальше
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
