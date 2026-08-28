/**
 * «Анализ чеков» — как покупают в сети.
 *
 * «Продажи» отвечают на вопрос про товар, этот экран — про покупателя: что он
 * берёт за один подход, берёт ли что-то вообще, когда приходит и что с чем
 * сочетает. Действия отсюда другие: не «заказать больше», а «переложить полку»,
 * «поставить у кассы», «предложить вторую позицию».
 *
 * Тот же разбор, что делает станция у себя (agent/internal/web/baskets.go), с
 * одним добавлением, ради которого в центр и приходят, — разрез по АЗС: корзину
 * двух точек сравнить можно только отсюда.
 *
 * Топливо здесь — не предмет учёта, а измерение покупателя. На АЗС у человека
 * уже есть повод подойти к кассе, поэтому первый вопрос эффективности магазина
 * не «сколько продали», а «из заправившихся сколько дополнили заправку товаром,
 * а сколько уехали ни с чем» — и различается ли это по марке и объёму залива.
 * Дизель на сорок литров и десять литров 95-го — разные люди с разной корзиной.
 *
 * Заправки берутся из топливного контура по сменам, чеки которых уже приехали;
 * марка и литры известны там, где чек сошёлся с заправкой по номеру. Доля
 * сошедшихся показана на экране: разрез по марке — подсказка, а не бухгалтерия.
 *
 * Данные: /api/store/baskets.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Kpi } from './analytics/Kpi'
import { getStoreBaskets, getStoreBasketItem } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

function Полоса({ доля }: { доля: number }) {
  return (
    <div className="h-2 w-full rounded-full bg-muted/40">
      <div className="h-2 rounded-full bg-primary/60" style={{ width: `${Math.max(2, Math.min(100, доля))}%` }} />
    </div>
  )
}

export function StoreBasketsPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const scopeKey = stations?.join(',') || ''
  // Разбор вокруг одной позиции: пусто — экран показывает сеть целиком.
  const [товар, setТовар] = useState('')
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-baskets', companyId, dateFrom, dateTo, scopeKey],
    queryFn: () => getStoreBaskets(dateFrom, dateTo, stations),
  })
  const { data: позиция } = useQuery({
    queryKey: ['store-basket-item', companyId, dateFrom, dateTo, scopeKey, товар],
    queryFn: () => getStoreBasketItem(товар, dateFrom, dateTo, stations),
    enabled: товар.length > 0,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Разбираем чеки…</div>
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400/90">
        Не удалось разобрать чеки.{' '}
        <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
      </div>
    )
  }

  const t = data.totals

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Анализ чеков</h2>
        <p className="text-sm text-muted-foreground max-w-4xl mt-1">
          Как покупают: сколько берут за один подход, что берут вместе и в какие часы.
          Период {data.period.from} — {data.period.to}
          {stations?.length ? ` · АЗС ${stations.join(', ')}` : ' · вся сеть'}.
        </p>
      </div>

      {t.cheques === 0 ? (
        <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          За период чеков с товаром нет. Чеки приезжают со станций с версии агента 0.87 —
          за более ранние периоды разбирать нечего, смотрите «Продажи».
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Чеков с товаром" value={nf(t.cheques)}
                 sub={`${fmtMoney(t.revenue)} товарной выручки`} />
            <Kpi label="Средний чек" value={fmtMoney(t.avg_check)}
                 sub={`медиана ${fmtMoney(t.median_check)}`} />
            <Kpi label="Позиций в чеке" value={nf(t.depth, 2)}
                 sub={`одна позиция — ${nf(t.single_pct, 1)} % чеков`} />
            <Kpi label="Прицеп к топливу" value={`${nf(t.attach_pct, 1)} %`}
                 sub={`${nf(t.mixed)} из ${nf(t.fuel_ops)} заправок дополнены товаром`} />
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Уехали без покупки" value={nf(t.fuel_only)}
                 sub="заправились и ничего не взяли" />
            <Kpi label="Товара на заправку" value={fmtMoney(t.goods_per_fill)}
                 sub="включая тех, кто уехал ни с чем" />
            <Kpi label="Средний залив" value={`${nf(t.avg_fill, 2)} л`}
                 sub={`${nf(data.fuel.ops)} заправок в контуре топлива`} />
            <Kpi label="Покупки одной позицией" value={nf(t.single)}
                 sub="резерв второй позиции в чеке" />
          </div>

          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-sm">
            {data.verdict}
          </div>

          {t.returns > 0 && (
            <div className="text-xs text-muted-foreground">
              Возвраты — {nf(t.returns)} чеков на {fmtMoney(t.returns_amount)} — в корзину не
              включены: возврат не покупка и занизил бы и средний чек, и глубину.
            </div>
          )}

          <section className="rounded-lg border border-border/50 p-4">
            <h3 className="text-sm font-semibold">Размер корзины</h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
              Сколько позиций берут за подход. Вторая позиция в чеке даёт выручку без нового
              покупателя — поэтому доля одиночных покупок и есть размер резерва.
            </p>
            <table className="w-full text-xs mt-3">
              <tbody>
                {data.sizes.map((р) => (
                  <tr key={р.positions} className="border-b border-border/30">
                    <td className="py-2 pr-3 w-40">{р.label}</td>
                    <td className="py-2 pr-3 text-right w-24">{nf(р.cheques)}</td>
                    <td className="py-2 pr-3 text-right w-20 text-muted-foreground">{nf(р.share, 1)} %</td>
                    <td className="py-2 pr-3 w-1/3"><Полоса доля={р.share} /></td>
                    <td className="py-2 text-right text-muted-foreground">{fmtMoney(р.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {data.fuel.by_fuel.length > 0 && (
            <section className="rounded-lg border border-border/50 p-4">
              <h3 className="text-sm font-semibold">Кто заправляется — тот и покупает по-разному</h3>
              <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
                Дизель на АЗС — чаще коммерческий транспорт: другой человек, другое время и
                другая корзина, и одной цифрой прицепа эта разница не видна. «Товара на заправку» —
                деньги магазина с одной заправки этой маркой, включая уехавших ни с чем.
                {data.fuel.matched_pct < 95 && (
                  <> Марка известна у {nf(data.fuel.matched)} из {nf(t.mixed)} смешанных чеков
                  ({nf(data.fuel.matched_pct, 1)} %) — остальные не сошлись с заправкой по номеру.</>
                )}
              </p>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr className="border-b border-border/50">
                      <th className="text-left py-1.5 pr-3 font-medium">Марка</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Заправок</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Средний залив</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Взяли товар</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Прицеп</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Средний чек товара</th>
                      <th className="text-right py-1.5 font-medium">Товара на заправку</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.fuel.by_fuel.map((м) => (
                      <tr key={м.fuel} className="border-b border-border/30 hover:bg-accent/30">
                        <td className="py-1.5 pr-3">{м.fuel}</td>
                        <td className="py-1.5 pr-3 text-right">{nf(м.ops)}</td>
                        <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(м.avg_fill, 2)} л</td>
                        <td className="py-1.5 pr-3 text-right">{nf(м.with_goods)}</td>
                        <td className="py-1.5 pr-3 text-right font-medium">{nf(м.attach_pct, 1)} %</td>
                        <td className="py-1.5 pr-3 text-right">{fmtMoney(м.avg_goods_check)}</td>
                        <td className="py-1.5 text-right">{fmtMoney(м.goods_per_fill)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {data.fuel.by_volume.length > 0 && (
            <section className="rounded-lg border border-border/50 p-4">
              <h3 className="text-sm font-semibold">Объём заправки и готовность купить</h3>
              <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
                Кто льёт на пятьсот рублей и кто заправляет полный бак — заходят в магазин
                по-разному. Здесь видно, на каком объёме прицеп проседает и во сколько это обходится.
              </p>
              <table className="w-full text-xs mt-3">
                <tbody>
                  {data.fuel.by_volume.map((д) => (
                    <tr key={д.label} className="border-b border-border/30">
                      <td className="py-2 pr-3 w-40">{д.label}</td>
                      <td className="py-2 pr-3 text-right w-24">{nf(д.ops)}</td>
                      <td className="py-2 pr-3 text-right w-28 text-muted-foreground">
                        взяли {nf(д.with_goods)}
                      </td>
                      <td className="py-2 pr-3 w-1/3"><Полоса доля={д.attach_pct} /></td>
                      <td className="py-2 pr-3 text-right w-20 font-medium">{nf(д.attach_pct, 1)} %</td>
                      <td className="py-2 text-right text-muted-foreground">{fmtMoney(д.goods_per_fill)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="rounded-lg border border-border/50 p-4">
            <h3 className="text-sm font-semibold">Часы суток</h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
              Когда покупают и на сколько. Час — московский, как и вся отчётность сети.
            </p>
            <div className="overflow-x-auto mt-3">
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border/50">
                    <th className="text-left py-1.5 pr-3 font-medium">Час</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Чеков</th>
                    <th className="py-1.5 pr-3 font-medium w-1/3" />
                    <th className="text-right py-1.5 pr-3 font-medium">С заправкой</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Средний чек</th>
                    <th className="text-right py-1.5 font-medium">Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {data.hours.map((ч) => (
                    <tr key={ч.hour} className="border-b border-border/30">
                      <td className="py-1.5 pr-3">{String(ч.hour).padStart(2, '0')}:00</td>
                      <td className="py-1.5 pr-3 text-right">{nf(ч.cheques)}</td>
                      <td className="py-1.5 pr-3"><Полоса доля={ч.bar} /></td>
                      <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(ч.mixed)}</td>
                      <td className="py-1.5 pr-3 text-right">{fmtMoney(ч.avg_check)}</td>
                      <td className="py-1.5 text-right text-muted-foreground">{fmtMoney(ч.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {data.stations.length > 1 && (
            <section className="rounded-lg border border-border/50 p-4">
              <h3 className="text-sm font-semibold">По станциям</h3>
              <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
                Разрез, которого у самой АЗС нет: одинаковый ассортимент даёт разную корзину,
                и разница между точками — это про выкладку и кассира, а не про спрос.
              </p>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr className="border-b border-border/50">
                      <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Чеков</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Выручка</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Средний чек</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Позиций в чеке</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Одна позиция</th>
                      <th className="text-right py-1.5 font-medium">Прицеп к топливу</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.stations.map((с) => (
                      <tr key={с.station_id} className="border-b border-border/30 hover:bg-accent/30">
                        <td className="py-1.5 pr-3">{с.station_id}</td>
                        <td className="py-1.5 pr-3 text-right">{nf(с.cheques)}</td>
                        <td className="py-1.5 pr-3 text-right">{fmtMoney(с.revenue)}</td>
                        <td className="py-1.5 pr-3 text-right">{fmtMoney(с.avg_check)}</td>
                        <td className="py-1.5 pr-3 text-right">{nf(с.depth, 2)}</td>
                        <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(с.single_pct, 1)} %</td>
                        <td className="py-1.5 text-right">{nf(с.attach_pct, 1)} %</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="rounded-lg border border-border/50 p-4">
            <h3 className="text-sm font-semibold">Что берут вместе</h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
              Подъём выше 1,5 — привычка покупателя, а не совпадение популярностей: такую пару
              стоит держать рядом на полке и предлагать на кассе. Пары реже пяти чеков не
              считаем — это шум. Найдено {nf(data.pairs_total)}
              {data.pairs_total > data.pairs.length ? `, показаны первые ${nf(data.pairs.length)}` : ''}.
            </p>
            {data.pairs.length === 0 ? (
              <div className="text-xs text-muted-foreground py-3">
                Устойчивых пар за период нет: корзина слишком мелкая или чеков мало.
              </div>
            ) : (
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr className="border-b border-border/50">
                      <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
                      <th className="text-left py-1.5 pr-3 font-medium">И вместе с ним</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Чеков</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Поддержка</th>
                      <th className="text-right py-1.5 pr-3 font-medium">Уверенность</th>
                      <th className="text-right py-1.5 font-medium">Подъём</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.pairs.map((п, i) => (
                      <tr key={`${п.a}-${п.b}-${i}`} className="border-b border-border/30 hover:bg-accent/30">
                        <td className="py-1.5 pr-3">{п.a}</td>
                        <td className="py-1.5 pr-3">{п.b}</td>
                        <td className="py-1.5 pr-3 text-right">{nf(п.together)}</td>
                        <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(п.support, 2)} %</td>
                        <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(п.confidence, 1)} %</td>
                        <td className={`py-1.5 text-right font-medium ${п.lift >= 1.5 ? 'text-emerald-500' : ''}`}>
                          {nf(п.lift, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="rounded-lg border border-border/50 p-4">
            <h3 className="text-sm font-semibold">Чем платят</h3>
            <div className="overflow-x-auto mt-3">
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border/50">
                    <th className="text-left py-1.5 pr-3 font-medium">Способ</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Чеков</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Доля</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Средний чек</th>
                    <th className="text-right py-1.5 font-medium">Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {data.payments.map((о) => (
                    <tr key={о.name} className="border-b border-border/30">
                      <td className="py-1.5 pr-3">{о.name}</td>
                      <td className="py-1.5 pr-3 text-right">{nf(о.cheques)}</td>
                      <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(о.share, 1)} %</td>
                      <td className="py-1.5 pr-3 text-right">{fmtMoney(о.avg_check)}</td>
                      <td className="py-1.5 text-right text-muted-foreground">{fmtMoney(о.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {позиция && позиция.cheques > 0 && (
            <section className="rounded-lg border border-primary/30 bg-primary/[0.03] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold">С чем берут «{позиция.item}»</h3>
                  <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
                    Общая таблица связок отвечает, какие пары есть в сети; здесь — что кладут
                    в корзину именно с этой позицией и в какие часы её берут. Из первого делают
                    выкладку по сети, из второго — перестановку у кассы.
                  </p>
                </div>
                <button className="text-xs underline text-muted-foreground hover:text-foreground"
                        onClick={() => setТовар('')}>
                  показать сеть целиком
                </button>
              </div>

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-3">
                <Kpi label="Чеков с позицией" value={nf(позиция.cheques)}
                     sub={`${nf(позиция.share, 1)} % товарных чеков`} />
                <Kpi label="Продано" value={nf(позиция.qty, 2)}
                     sub={`средняя цена ${fmtMoney(позиция.avg_price)}`} />
                <Kpi label="Выручка" value={fmtMoney(позиция.revenue)} sub="за период" />
                <Kpi label="Берут при заправке" value={`${nf(позиция.with_fuel_pct, 1)} %`}
                     sub={`${nf(позиция.with_fuel)} чеков вместе с топливом`} />
              </div>

              {позиция.neighbours.length === 0 ? (
                <div className="text-xs text-muted-foreground py-3">
                  Устойчивых соседей нет: позицию берут поодиночке или чеков с ней слишком мало.
                </div>
              ) : (
                <div className="overflow-x-auto mt-3">
                  <table className="w-full text-xs">
                    <thead className="text-muted-foreground">
                      <tr className="border-b border-border/50">
                        <th className="text-left py-1.5 pr-3 font-medium">Сосед по чеку</th>
                        <th className="text-right py-1.5 pr-3 font-medium">Чеков вместе</th>
                        <th className="text-right py-1.5 pr-3 font-medium">Из чеков с позицией</th>
                        <th className="text-right py-1.5 pr-3 font-medium">Подъём</th>
                        <th className="text-right py-1.5 font-medium">Выручка соседа</th>
                      </tr>
                    </thead>
                    <tbody>
                      {позиция.neighbours.map((с) => (
                        <tr key={с.name} className="border-b border-border/30 hover:bg-accent/30">
                          <td className="py-1.5 pr-3">{с.name}</td>
                          <td className="py-1.5 pr-3 text-right">{nf(с.together)}</td>
                          <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(с.confidence, 1)} %</td>
                          <td className={`py-1.5 pr-3 text-right font-medium ${с.lift >= 1.5 ? 'text-emerald-500' : ''}`}>
                            {nf(с.lift, 2)}
                          </td>
                          <td className="py-1.5 text-right text-muted-foreground">{fmtMoney(с.revenue)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="mt-4">
                <div className="text-xs font-medium mb-2">Когда её берут</div>
                <div className="flex items-end gap-[3px] h-16">
                  {позиция.hours.map((ч) => (
                    <div key={ч.hour} className="flex-1 flex flex-col justify-end items-center gap-1"
                         title={`${String(ч.hour).padStart(2, '0')}:00 — ${nf(ч.cheques)} чеков`}>
                      <div className="w-full rounded-t bg-primary/50"
                           style={{ height: `${Math.max(2, ч.bar)}%` }} />
                      {ч.hour % 3 === 0 && (
                        <span className="text-[9px] text-muted-foreground">{ч.hour}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}

          <section className="rounded-lg border border-border/50 p-4">
            <h3 className="text-sm font-semibold">Что чаще всего в чеке</h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-4xl">
              Не по выручке, а по числу чеков: это позиции, ради которых заходят. Их место на
              полке и наличие важнее, чем у любого другого товара. Клик по строке — разбор
              вокруг этой позиции: с чем берут и в какие часы.
            </p>
            <div className="overflow-x-auto mt-3">
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border/50">
                    <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Чеков</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Доля чеков</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Продано</th>
                    <th className="text-right py-1.5 font-medium">Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top.map((т) => (
                    <tr key={т.name}
                        className="border-b border-border/30 hover:bg-accent/30 cursor-pointer"
                        onClick={() => setТовар(т.name)}
                        title={`${т.name} — с чем берут`}>
                      <td className="py-1.5 pr-3">{т.name}</td>
                      <td className="py-1.5 pr-3 text-right">{nf(т.cheques)}</td>
                      <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(т.share, 1)} %</td>
                      <td className="py-1.5 pr-3 text-right">{nf(т.qty, 2)}</td>
                      <td className="py-1.5 text-right text-muted-foreground">{fmtMoney(т.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
