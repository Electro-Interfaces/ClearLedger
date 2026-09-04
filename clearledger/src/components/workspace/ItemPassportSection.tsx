/**
 * Секция «Сеть и станции» в карточке товара.
 *
 * Карточка отвечала на вопросы одной АЗС: паспорт, цена, остаток, движение.
 * С двумя станциями появились вопросы сети, которых там не было: какие коды у
 * позиции сетевые, а какие принадлежат одной точке; на каких условиях она живёт
 * на каждой АЗС; чья рецептура по ней действует; откуда она взялась и что в неё
 * слито. Ответы собраны здесь, рядом с карточкой, а не в отдельном экране —
 * иначе товаровед сверяет две вкладки глазами.
 */
import { useQuery } from '@tanstack/react-query'
import { Network, Barcode, ChefHat, GitMerge, Store } from 'lucide-react'
import { getItemPassport, type ItemPassport } from '@/services/storeService'

function деньги(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : v.toFixed(2)
}

function дата(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString('ru-RU') : '—'
}

function Блок({ icon: Icon, title, children }: {
  icon: typeof Network; title: string; children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border bg-card p-3">
      <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase
                     tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </h4>
      {children}
    </section>
  )
}

export function ItemPassportSection({ guid }: { guid: string }) {
  const { data, isLoading } = useQuery<ItemPassport>({
    queryKey: ['store', 'item-passport', guid],
    queryFn: () => getItemPassport(guid),
  })

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">Загрузка разреза по станциям…</div>
  }
  if (!data) return null

  const карты = data.recipes.active
  const слияния = data.origin.merged
  const заявка = data.origin.draft

  return (
    <div className="grid gap-3.5 md:grid-cols-2">
      <Блок icon={Store} title="Условия станций">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="pb-1 text-left font-medium">АЗС</th>
              <th className="pb-1 text-right font-medium">Цена</th>
              <th className="pb-1 text-left font-medium">Ведёт</th>
              <th className="pb-1 text-left font-medium">Касса</th>
              <th className="pb-1 text-right font-medium">Остаток</th>
            </tr>
          </thead>
          <tbody>
            {data.conditions.map((c) => (
              <tr key={c.station_id} className="border-t border-border/40">
                <td className="py-1.5">
                  {c.station_id}
                  {!c.assortment && (
                    <span className="ml-1 text-xs text-amber-700 dark:text-amber-400">
                      закрыта
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-right tabular-nums">{деньги(c.price)}</td>
                <td className="py-1.5 text-xs text-muted-foreground">
                  {c.price_owner === 'station' ? 'станция' : 'сеть'}
                </td>
                <td className="py-1.5 font-mono text-xs">
                  {c.ns_codes.length
                    ? c.ns_codes.map((n) => n.code).join(', ')
                    : <span className="font-sans text-muted-foreground">нет кода</span>}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {c.stock === null || c.stock === undefined ? '—' : c.stock}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted-foreground">
          Позиция уедет в кассу той АЗС, где есть цена, код кассы и матрица её не
          закрыла.
        </p>
      </Блок>

      <Блок icon={Barcode} title="Штрихкоды и ярусы">
        <ul className="space-y-1 text-sm">
          {data.barcodes.map((b) => (
            <li key={b.code} className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono">{b.code}</span>
              <span className="text-xs text-muted-foreground">
                {b.station_id === null
                  ? 'сетевой код'
                  : `внутренний код АЗС ${b.station_id}`}
                {' · '}
                {b.status === 'active' ? 'действует'
                  : b.status === 'historical' ? 'снят' : 'конфликт'}
                {b.кассы && b.кассы.length > 0 && ` · в кассе ${b.кассы.join(', ')}`}
              </span>
            </li>
          ))}
          {data.barcodes.length === 0 && (
            <li className="text-sm text-muted-foreground">
              Кодов нет: такая карточка не пробивается на кассе.
            </li>
          )}
        </ul>
      </Блок>

      {карты.length > 0 && (
        <Блок icon={ChefHat} title="Рецептура по ярусам">
          <ul className="space-y-1 text-sm">
            {Object.entries(data.recipes.effective).map(([st, e]) => (
              <li key={st}>
                АЗС {st}: {e.ярус
                  ? <>действует карта яруса <b>{e.ярус}</b>, версия {e.version},
                      строк {e.строк}</>
                  : <span className="text-amber-700 dark:text-amber-400">
                      карты нет — сырьё под блюдо не спишется
                    </span>}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            Карта станции перебивает сетевую норму; сетевая действует там, где своей
            нет.
          </p>
        </Блок>
      )}

      <Блок icon={GitMerge} title="Происхождение">
        <dl className="space-y-1.5 text-sm">
          <div className="flex gap-2">
            <dt className="w-32 shrink-0 text-xs text-muted-foreground">Источник</dt>
            <dd>{data.item.source === 'station' ? 'заведена на станции'
              : data.item.source === 'import' ? 'импорт справочника'
              : data.item.source}</dd>
          </div>
          {заявка && (
            <div className="flex gap-2">
              <dt className="w-32 shrink-0 text-xs text-muted-foreground">Заявка</dt>
              <dd>
                АЗС {заявка.station_id}
                {заявка.author && `, ${заявка.author}`}
                {', заведена '}{дата(заявка.created_at)}
                {заявка.resolved_at
                  ? `, признана ${дата(заявка.resolved_at)}`
                  : ' — ещё не признана'}
              </dd>
            </div>
          )}
          {слияния.length > 0 && (
            <div className="flex gap-2">
              <dt className="w-32 shrink-0 text-xs text-muted-foreground">Слито в неё</dt>
              <dd>
                {слияния.map((м, i) => (
                  <div key={i}>
                    «{м.name ?? 'карточка удалена'}»
                    {м.sku && <span className="ml-1 font-mono text-xs">{м.sku}</span>}
                    <div className="text-xs text-muted-foreground">{м.reason}</div>
                  </div>
                ))}
              </dd>
            </div>
          )}
          {data.origin.aliases.length > 0 && (
            <div className="flex gap-2">
              <dt className="w-32 shrink-0 text-xs text-muted-foreground">Прежние коды</dt>
              <dd className="font-mono text-xs">
                {data.origin.aliases.map((a) => `${a.code} (${a.kind})`).join(', ')}
              </dd>
            </div>
          )}
        </dl>
      </Блок>

      {data.matrix_rules.length > 0 && (
        <Блок icon={Network} title="Правила матрицы по этой позиции">
          <ul className="space-y-1 text-sm">
            {data.matrix_rules.map((r, i) => (
              <li key={i}>
                <b>{r.subject === 'price' ? 'Цена' : 'Применение'}</b>
                {' · '}
                {r.station_id === null ? 'вся сеть' : `АЗС ${r.station_id}`}
                {' · '}
                <span className={r.allow ? '' : 'text-amber-700 dark:text-amber-400'}>
                  {r.allow ? 'разрешено' : 'запрещено'}
                </span>
                {r.reason && (
                  <div className="text-xs text-muted-foreground">{r.reason}</div>
                )}
              </li>
            ))}
          </ul>
        </Блок>
      )}
    </div>
  )
}
