/**
 * «Игроки» — кто ещё борется за того же водителя.
 *
 * Карта зарядок показывает владельцев железа. Но за водителя конкурируют и те, у
 * кого станций нет вовсе: агрегаторы на чужой инфраструктуре, топливный процессинг
 * с готовой базой корпоративных клиентов, мойки, банки, автопроизводители. Их видно
 * только через магазин приложений — и это отдельный слой рынка, которого нет ни на
 * одной карте.
 *
 * Осторожность здесь встроена в экран: класс проставлен автоматически, поэтому
 * непроверенные помечены; наличие приложения не означает работы на рынке зарядок,
 * поэтому смежные игроки названы смежными; рейтинги не сравниваются между классами
 * без числа отзывов рядом.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { SortTh } from '@/components/workspace/SortableTh'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { useTableSort } from '@/hooks/useTableSort'
import { useCompany } from '@/contexts/CompanyContext'
import { getMarketPlayers, type MarketPlayer } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const ВИДЫ = [
  { k: 'models', label: 'Модели бизнеса' },
  { k: 'classes', label: 'Откуда приходят' },
  { k: 'quality', label: 'Качество против размера' },
  { k: 'shops', label: 'Интернет-магазин' },
] as const

function PlayerLine({ p }: { p: MarketPlayer }) {
  return (
    <li className="flex items-baseline justify-between gap-2 text-xs">
      <span className="min-w-0 truncate">
        {p.app}
        {!p.isActive && <span className="ml-1 text-warning">· не работает</span>}
        {p.operatorName && p.operatorName !== p.app && (
          <span className="text-muted-foreground"> · {p.operatorName}</span>
        )}
        {!p.classChecked && (
          <span className="ml-1 text-muted-foreground">· класс не проверен</span>
        )}
      </span>
      <span className="shrink-0 tabular-nums text-muted-foreground">
        {(p.ownStations ?? 0) > 0 ? `${nf.format(p.ownStations ?? 0)} станций` : p.class}
        {p.rating != null && ` · ${nf1.format(p.rating)}`}
      </span>
    </li>
  )
}

export function MarketPlayersPanel() {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const [вид, setВид] = useState<string>('models')

  const q = useQuery({
    queryKey: ['market-players', companyId],
    queryFn: () => getMarketPlayers(companyId),
    enabled: !!companyId,
  })

  // Списки и сортировка — до ранних возвратов: порядок хуков обязан совпадать на
  // каждой отрисовке, иначе React путает их между собой.
  const качество = q.data?.quality ?? []
  // Рейтинг без числа отзывов обманчив, поэтому сортировать нужно и по тому, и по
  // другому — а ещё по числу станций: это разные вопросы к одной таблице.
  const сортировкаКачества = useMemo(() => ({
    app: (p: MarketPlayer) => p.app,
    class: (p: MarketPlayer) => p.class,
    stations: (p: MarketPlayer) => p.ownStations,
    rating: (p: MarketPlayer) => p.rating,
    reviews: (p: MarketPlayer) => p.reviews,
    developer: (p: MarketPlayer) => p.developer,
  }), [])
  const { rows: quality, sort: сортК, toggle: жмиК } =
    useTableSort(качество, сортировкаКачества)

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем игроков рынка</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const t = q.data?.totals
  if (!t || (q.data?.total ?? 0) === 0) {
    return (
      <Card className="m-4"><CardContent className="p-6 text-sm text-muted-foreground">
        {q.data?.message ?? 'Карта игроков не загружена.'}
      </CardContent></Card>
    )
  }

  const quadrants = q.data?.quadrants ?? []
  const classes = q.data?.classes ?? []

  return (
    <div ref={экран} className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Users className="size-4 text-primary" aria-hidden />
            За того же водителя борются {nf.format(q.data?.total ?? 0)} игроков, и у{' '}
            {nf.format(t.assetLight)} из них нет ни одной своей станции.
          </span>
          <span className="text-xs text-muted-foreground">
            смежных игроков {nf.format(t.adjacent)} · медиана оценки приложения{' '}
            {t.medianRating != null ? nf1.format(t.medianRating) : 'нет данных'}
          </span>
          <span className="ml-auto" data-export-ignore>
            <ExportButton title={`Игроки рынка · ${ВИДЫ.find((v) => v.k === вид)?.label}`}
              subtitle={`${nf.format(q.data?.total ?? 0)} игроков`}
              getEl={() => экран.current} />
          </span>
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      {вид === 'models' && (
        <div className="grid min-h-0 flex-1 gap-3 overflow-auto md:grid-cols-2">
          {quadrants.map((qd) => (
            <Card key={qd.key}>
              <CardContent className="p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-headline text-sm font-semibold">{qd.label}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {nf.format(qd.count)} приложений
                    {qd.networks ? ` · ${nf.format(qd.networks)} сетей` : ''}
                    {qd.stations > 0 && ` · ${nf.format(qd.stations)} станций`}
                  </span>
                </div>
                <p className="mb-2 mt-0.5 text-xs text-muted-foreground">{qd.hint}</p>
                <ul className="space-y-0.5">
                  {qd.players.map((p) => <PlayerLine key={p.id} p={p} />)}
                </ul>
              </CardContent>
            </Card>
          ))}
          {/* Квадранты показаны карточками, а выгрузка работает с таблицами: эта
              таблица не рисуется, её дело — уложить игроков по моделям в строки. */}
          <table hidden {...exportRows('Модели бизнеса', [
            'Модель', 'Игрок', 'Оператор', 'Класс', 'Своих станций', 'Оценка', 'Работает',
            'Класс проверен',
          ], quadrants.flatMap((qd) => qd.players.map((p) => [
            qd.label, p.app, p.operatorName, p.class, p.ownStations, p.rating,
            p.isActive ? 'да' : 'нет', p.classChecked ? 'да' : 'нет',
          ])))} />
        </div>
      )}

      {вид === 'classes' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Откуда приходят', [
              'Класс', 'Смежные', 'Игроков', 'Без своих станций', 'Станций у класса',
              'Медиана оценки', 'Оценок в основе', 'Кто это',
            ], classes.map((c) => [
              c.class, c.adjacent ? 'да' : 'нет', c.players, c.assetLight, c.stations,
              c.medianRating, c.withRating, c.examples.join(', '),
            ]))}>
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="p-2 text-left font-medium">Класс</th>
                <th className="p-2 text-right font-medium">Игроков</th>
                <th className="p-2 text-right font-medium">Без своих станций</th>
                <th className="p-2 text-right font-medium">Станций у класса</th>
                <th className="p-2 text-right font-medium">Медиана оценки</th>
                <th className="p-2 text-left font-medium">Кто это</th>
              </tr>
            </thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c.class} className="border-t border-border/50">
                  <td className="p-2 font-medium">
                    {c.class}
                    {c.adjacent && (
                      <span className="ml-1 font-normal text-muted-foreground">
                        · смежные, потенциальные входящие
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right tabular-nums">{nf.format(c.players)}</td>
                  <td className="p-2 text-right tabular-nums">{nf.format(c.assetLight)}</td>
                  <td className="p-2 text-right tabular-nums">{nf.format(c.stations)}</td>
                  <td className="p-2 text-right">
                    {c.medianRating != null ? (
                      <span className="tabular-nums">
                        {nf1.format(c.medianRating)}
                        <span className="ml-1 text-muted-foreground">
                          по {c.withRating}
                        </span>
                      </span>
                    ) : <span className="text-muted-foreground">нет данных</span>}
                  </td>
                  <td className="p-2 text-muted-foreground">{c.examples.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">
            Класс, где почти все без станций, — это конкуренция за интерфейс, а не за
            железо: там выигрывает тот, в чьём приложении водитель нажимает «зарядить».
          </p>
        </div>
      )}

      {вид === 'quality' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Качество против размера', [
              'Приложение', 'Работает', 'Класс', 'Своих станций', 'Оценка', 'Отзывов', 'Разработчик',
            ], quality.map((p) => [
              p.app, p.isActive ? 'да' : 'нет', p.class, p.ownStations, p.rating, p.reviews,
              p.developer,
            ]))}>
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <SortTh sortKey="app" sort={сортК} onSort={жмиК}>Приложение</SortTh>
                <SortTh sortKey="class" sort={сортК} onSort={жмиК}>Класс</SortTh>
                <SortTh sortKey="stations" sort={сортК} onSort={жмиК} align="right">Своих станций</SortTh>
                <SortTh sortKey="rating" sort={сортК} onSort={жмиК} align="right">Оценка</SortTh>
                <SortTh sortKey="reviews" sort={сортК} onSort={жмиК} align="right">Отзывов</SortTh>
                <SortTh sortKey="developer" sort={сортК} onSort={жмиК}>Разработчик</SortTh>
              </tr>
            </thead>
            <tbody>
              {quality.map((p) => (
                <tr key={p.id} className="border-t border-border/50">
                  <td className="p-2 font-medium">
                    {p.app}
                    {!p.isActive && (
                      <span className="ml-2 text-xs text-warning">· не работает</span>
                    )}
                  </td>
                  <td className="p-2 text-muted-foreground">{p.class}</td>
                  <td className="p-2 text-right tabular-nums">
                    {p.ownStations ? nf.format(p.ownStations) : '—'}
                  </td>
                  <td className="p-2 text-right">
                    <span className={`tabular-nums ${(p.rating ?? 0) >= 4 ? 'text-success'
                      : (p.rating ?? 5) < 2.5 ? 'text-warning' : ''}`}>
                      {p.rating != null ? nf1.format(p.rating) : '—'}
                    </span>
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {p.reviews != null ? nf.format(p.reviews) : '—'}
                  </td>
                  <td className="p-2 text-muted-foreground">{p.developer ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">
            Отсортировано по числу отзывов: у приложения с пятью оценками и с тремястами
            разная достоверность, и сравнивать их между собой напрямую нельзя.
          </p>
        </div>
      )}

      {вид === 'shops' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Интернет-магазин', [
              'Сеть', 'Магазин', 'Примечание', 'Что продают', 'Цены от, ₽', 'до, ₽',
              'Позиций с ценой', 'Адрес',
            ], (q.data?.shops ?? []).map((sh) => [
              sh.brand, sh.hasShop ? 'есть' : 'не нашли', sh.note, sh.goods, sh.priceMin,
              sh.priceMax, sh.pricesFound, sh.host,
            ]))}>
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="p-2 text-left font-medium">Сеть</th>
                <th className="p-2 text-left font-medium">Магазин</th>
                <th className="p-2 text-left font-medium">Что продают</th>
                <th className="p-2 text-right font-medium">Цены от</th>
                <th className="p-2 text-right font-medium">до</th>
                <th className="p-2 text-right font-medium">Позиций с ценой</th>
                <th className="p-2 text-left font-medium">Адрес</th>
              </tr>
            </thead>
            <tbody>
              {(q.data?.shops ?? []).map((sh) => (
                <tr key={sh.brand} className="border-t border-border/50">
                  <td className="p-2 font-medium">{sh.brand}</td>
                  <td className="p-2">
                    {sh.hasShop
                      ? <span className="text-success">есть</span>
                      : <span className="text-muted-foreground">не нашли</span>}
                    {sh.note && <span className="ml-1 text-warning">· {sh.note}</span>}
                  </td>
                  <td className="p-2 text-muted-foreground">{sh.goods ?? '—'}</td>
                  <td className="p-2 text-right tabular-nums">
                    {sh.priceMin != null ? `${nf.format(sh.priceMin)} ₽` : '—'}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {sh.priceMax != null ? `${nf.format(sh.priceMax)} ₽` : '—'}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {sh.pricesFound ? nf.format(sh.pricesFound) : '—'}
                  </td>
                  <td className="p-2 text-muted-foreground">{sh.host ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">
            Свой интернет-магазин оказался признаком модели: он есть у {t.withShop}{' '}
            из {t.shopsChecked} проверенных сетей, а у чистых агрегаторов его нет
            вовсе — они работают на чужих станциях и оборудование не продают. Цены
            сняты автоматически со страниц каталога: это диапазон для ориентира, а не
            прайс-лист, и перед публикацией цифру надо сверить с сайтом. «Не нашли»
            означает, что магазина не было на типовых адресах сайта, а не что его нет.
          </p>
        </div>
      )}

      <Card><CardContent className="p-3 text-xs text-muted-foreground">
        {q.data?.note}
        {t.unchecked > 0 && ` Не проверено вручную: ${nf.format(t.unchecked)} записей.`}
        {t.multiApp?.length > 0 && (
          <span>
            {' '}У этих сетей больше одного приложения — точка контакта с водителем
            раздвоена: {t.multiApp.join(', ')}.
          </span>
        )}
      </CardContent></Card>
    </div>
  )
}
