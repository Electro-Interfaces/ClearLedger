/**
 * «Магазин» → Каталог → Товар и станции.
 *
 * Три вопроса, ради которых раньше приходилось обходить рабочие места АЗС:
 * где позиция продаётся и на чьих условиях, что станции делают со справочником
 * сами, и не завелась ли вторая карточка там, где хватило бы правила.
 *
 * Отраслевой аналог первого вида — item/location в Oracle Retail: у карточки
 * есть сетевая часть (имя, артикул, штрихкоды, группа) и часть, своя у каждой
 * площадки — цена, право на цену, применение, код кассы. Пока станция была
 * одна, разрез был не нужен; со второй он становится главным экраном каталога.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Boxes, Search, Store, Info, Copy } from 'lucide-react'
import {
  getStoreItemLocations, getStoreItemLocationsSummary, getStationPulse, getCatalogTwins,
  type ItemLocationsAnswer, type ItemLocationsSummary,
  type StationPulse, type CatalogTwins,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useLocations } from '@/hooks/useLocations'
import { scopeStationCodes } from '@/services/locationService'
import { PanelViewTabs, type ViewTab } from './PanelViewTabs'
import { NomenclatureCardModal } from './NomenclatureCardModal'
import { rowDrill } from './rowDrill'
import { Button } from '@/components/ui/button'

type Охват = 'all' | 'shared' | 'single' | 'none'

const ВИДЫ: readonly ViewTab[] = [
  { k: 'matrix', label: 'Товар и станции' },
  { k: 'stations', label: 'Работа станций' },
  { k: 'twins', label: 'Тёзки' },
]

// Одинаковое имя бывает трёх сортов, и лечатся они по-разному. Пока список шёл
// одной кучей, 66 строк наследия прятали четыре настоящих дубля сети.
const ВИДЫ_ТЁЗОК: { k: string; label: string; hint: string }[] = [
  { k: '', label: 'Все', hint: '' },
  {
    k: 'дубль сети',
    label: 'Дубль сети',
    hint: 'Один товар заведён карточкой на каждой станции. Артикул сети обязан быть один — иначе сетевой отчёт разложит продажи по двум строкам.',
  },
  {
    k: 'ассортимент',
    label: 'Ассортимент',
    hint: 'Несколько живых карточек, у каждой свой штрихкод: вкусы под общим именем. Не дубль — лечится именем, а не слиянием: сольёшь, и вкус, который кассир пробивает отдельным кодом, пропадёт.',
  },
  {
    k: 'наследие',
    label: 'Наследие',
    hint: 'Карточка со штрихкодом одна, рядом пустышка с ценой из справочника 1С. Товара за ней нет, торговле не мешает.',
  },
]

const ОХВАТ: { key: Охват; label: string; hint: string }[] = [
  { key: 'all', label: 'Все', hint: 'весь сетевой каталог' },
  { key: 'shared', label: 'Есть на нескольких', hint: 'позиции больше чем одной станции' },
  // «Только одна станция» читалось как выбор станции: человек нажимал и ждал,
  // что таблица сузится до одной АЗС, а сужается она областью учёта в шапке.
  // Здесь же речь про ОХВАТ позиции — на скольких площадках она живёт.
  { key: 'single', label: 'Есть только на одной', hint: 'позиция уникальна для своей площадки' },
  { key: 'none', label: 'Ничьи', hint: 'ни одна станция не применяет — кандидаты в архив' },
]

const КЛАССЫ = ['', 'Сопутка', 'Блюдо', 'Сырьё']

function деньги(v: number | null): string {
  return v === null || v === undefined ? '—' : v.toFixed(2)
}

function когда(iso: string | null | undefined): string {
  if (!iso) return 'сверки не было'
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

/** Показатель станции. Ноль — тоже ответ, поэтому строка не прячется. */
function Показатель({ label, value, hint, тревога }: {
  label: string; value: number | string; hint: string; тревога?: boolean
}) {
  return (
    <div className="rounded-lg border bg-card p-3" title={hint}>
      <div className={`text-2xl font-semibold ${тревога ? 'text-amber-600 dark:text-amber-400' : ''}`}>
        {value}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
    </div>
  )
}

export function StoreItemLocationsPanel() {
  const { company } = useCompany()
  // Область учёта из шапки обязана доходить до цифр: пока она сюда не
  // передавалась, экран показывал всю сеть при выбранной одной АЗС — и человек
  // читал чужие колонки как свои.
  const { locationIds, regionIds } = useFilters()
  const locations = useLocations()
  const выбранныеСтанции = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds),
    [locations, locationIds, regionIds],
  )
  const однаСтанция = выбранныеСтанции.length === 1 ? выбранныеСтанции[0] : null
  const [вид, задатьВид] = useState('matrix')
  const [видТёзок, setВидТёзок] = useState('')
  const [запрос, задатьЗапрос] = useState('')
  const [строкаПоиска, задатьСтрокуПоиска] = useState('')
  const [охват, задатьОхват] = useState<Охват>('all')
  const [класс, задатьКласс] = useState('')
  const [карточка, открытьКарточку] = useState<string | null>(null)

  const сводка = useQuery<ItemLocationsSummary>({
    queryKey: ['store', 'item-locations', 'summary', company?.id],
    queryFn: getStoreItemLocationsSummary,
  })
  const данные = useQuery<ItemLocationsAnswer>({
    queryKey: ['store', 'item-locations', company?.id, запрос, охват, класс, однаСтанция],
    queryFn: () => getStoreItemLocations({
      q: запрос, scope: охват, skuClass: класс, station: однаСтанция,
    }),
    enabled: вид === 'matrix',
  })
  const пульс = useQuery<StationPulse>({
    queryKey: ['store', 'station-pulse', company?.id],
    queryFn: () => getStationPulse(7),
    enabled: вид === 'stations',
  })
  const тёзки = useQuery<CatalogTwins>({
    queryKey: ['store', 'catalog-twins', company?.id, видТёзок],
    queryFn: () => getCatalogTwins(true, видТёзок),
    enabled: вид === 'twins',
  })

  // Колонки — только те АЗС, что в области учёта. Выбрал одну станцию, а в
  // таблице по-прежнему обе — это и есть «фильтр не работает» глазами человека.
  const всеСтанции = данные.data?.stations ?? []
  const станции = выбранныеСтанции.length
    ? всеСтанции.filter((с) => выбранныеСтанции.includes(с))
    : всеСтанции

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Boxes className="h-5 w-5 text-primary" />
          <h2 className="font-headline text-lg font-semibold">Товар и станции</h2>
        </div>
        <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={задатьВид} />
      </div>

      {сводка.data && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Показатель label="карточек в сетевом каталоге"
                      value={сводка.data.итого.всего_карточек}
                      hint="Весь справочник сети, кроме помеченных удалёнными" />
          <Показатель label="продаются больше чем на одной станции"
                      value={сводка.data.итого.общих}
                      hint="Общая часть ассортимента: одна карточка, разные цены" />
          <Показатель label="только на одной станции"
                      value={сводка.data.итого.своих}
                      hint="Своё у площадки — это норма, а не ошибка" />
          <Показатель label="не применяет никто"
                      value={сводка.data.итого.без_станций}
                      hint="Архив и наследие 1С: ни одной станционной цены" />
        </div>
      )}

      {вид === 'matrix' && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded-md border bg-background px-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              <input
                className="h-9 w-64 bg-transparent text-sm outline-none"
                placeholder="имя, артикул или штрихкод"
                aria-label="Поиск позиции"
                value={строкаПоиска}
                onChange={(e) => задатьСтрокуПоиска(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') задатьЗапрос(строкаПоиска) }}
              />
              <Button size="sm" variant="ghost" onClick={() => задатьЗапрос(строкаПоиска)}>
                Найти
              </Button>
            </div>
            <div className="flex gap-1 rounded-lg border border-border bg-muted/60 p-1">
              {ОХВАТ.map((о) => (
                <button
                  key={о.key}
                  title={о.hint}
                  onClick={() => задатьОхват(о.key)}
                  className={`rounded-md px-3 py-1.5 text-sm transition ${
                    охват === о.key
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {о.label}
                </button>
              ))}
            </div>
            <select
              className="h-9 rounded-md border bg-background px-2 text-sm"
              aria-label="Класс позиции"
              value={класс}
              onChange={(e) => задатьКласс(e.target.value)}
            >
              {КЛАССЫ.map((к) => (
                <option key={к} value={к}>{к || 'любой класс'}</option>
              ))}
            </select>
            {данные.data && (
              <span className="text-sm text-muted-foreground">найдено {данные.data.total}</span>
            )}
          </div>

          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Позиция</th>
                  <th className="px-3 py-2 text-left">Артикул</th>
                  <th className="px-3 py-2 text-left">Группа</th>
                  {станции.map((s) => (
                    <th key={s} className="px-3 py-2 text-left">АЗС {s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {данные.isLoading && (
                  <tr><td colSpan={3 + станции.length}
                          className="px-3 py-6 text-center text-muted-foreground">Загрузка…</td></tr>
                )}
                {данные.data?.items.map((т) => (
                  /* Клик по всей строке открывает карточку товара: в ней разрез
                     по каждой АЗС — цена и чья она, код кассы, применение,
                     ярусы штрихкодов. Здесь видно «где позиция есть», там —
                     «что именно с ней на этой станции». */
                  <tr key={т.id}
                    {...(т.guid
                      ? rowDrill(() => открытьКарточку(т.guid!), `Карточка: ${т.name}`, 'border-t')
                      : { className: 'border-t hover:bg-muted/30' })}>
                    <td className="px-3 py-2">
                      <div className="font-medium">{т.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {т.sku_class}
                        {т.barcodes.length > 0 && ` · ${т.barcodes.slice(0, 2).join(', ')}`}
                        {т.barcodes.length > 2 && ` +${т.barcodes.length - 2}`}
                      </div>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{т.sku || '—'}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {т.group_path || '— без группы —'}
                    </td>
                    {т.stations.map((с) => (
                      <td key={с.station_id} className="px-3 py-2">
                        {с.живёт ? (
                          <div>
                            <span className="font-medium">{деньги(с.price)}</span>
                            <span className="ml-1 text-xs text-muted-foreground">
                              {с.price_owner === 'station' ? 'своя' : 'сетевая'}
                            </span>
                            {с.ns_codes > 0 && (
                              <span className="ml-1 text-xs text-emerald-700 dark:text-emerald-400">
                                · в кассе
                              </span>
                            )}
                          </div>
                        ) : с.price !== null && !с.assortment ? (
                          <span className="text-xs text-amber-700 dark:text-amber-400">
                            закрыта матрицей
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
                {данные.data?.items.length === 0 && (
                  <tr><td colSpan={3 + станции.length}
                          className="px-3 py-6 text-center text-muted-foreground">
                    Ничего не найдено
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              Позиция «живёт» на станции, когда у неё там есть цена и матрица её не
              закрыла — ровно эта пара решает, уедет ли товар в кассу. «Своя» цена
              значит, что её ведёт администратор АЗС; «сетевая» — что цену назначает
              товаровед. Пустая клетка это не ошибка: часть ассортимента своя у
              каждой площадки, и вторая карточка ради этого не нужна — нужно правило.
            </div>
          </div>
        </>
      )}

      {вид === 'stations' && (
        <>
          {пульс.isLoading && <div className="text-sm text-muted-foreground">Загрузка…</div>}
          {пульс.data?.rows.map((с) => (
            <section key={с.station_id} className="space-y-3 rounded-lg border bg-card p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Store className="h-4 w-4 text-primary" />
                <h3 className="font-headline text-base font-semibold">{с.name}</h3>
                <span className="text-xs text-muted-foreground">
                  сверка справочника: {когда(с.сверка?.момент)}
                  {с.сверка && ` · на станции ${с.сверка.на_станции}, в центре ${с.сверка.в_центре}`}
                </span>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Показатель label="позиций с ценой станции" value={с.позиций}
                            hint="Столько карточек станция вправе продавать" />
                <Показатель label="заявок ждёт признания" value={с.заявок_ждёт}
                            тревога={с.заявок_ждёт > 0}
                            hint="Карточки, заведённые на АЗС: пока не признаны, в сети их нет" />
                <Показатель label="правок цен за неделю" value={с.правок_цен}
                            hint="Сколько раз администратор станции менял розничную цену" />
                <Показатель label="закрыто матрицей" value={с.закрыто_матрицей}
                            hint="Позиции, которые товаровед запретил применять на этой АЗС" />
                <Показатель label="не уедут в кассу: нет кода" value={с.без_кода_кассы}
                            тревога={с.без_кода_кассы > 0}
                            hint="Цена есть, кода кассы нет — пробить товар на этой АЗС нельзя" />
                <Показатель label="блюд без действующей карты" value={с.блюд_без_ттк}
                            тревога={с.блюд_без_ттк > 0}
                            hint="Блюдо продаётся, а сырьё под него не списывается" />
                <Показатель label="своих карт рецептур" value={с.своих_карт}
                            hint={`Карты яруса этой АЗС; сетевых норм ${с.сетевых_карт}`} />
                <Показатель label="своих внутренних кодов" value={с.своих_кодов}
                            hint="Короткие номера кухни: у каждой станции свои, у соседней означают своё" />
              </div>

              {с.справочники && (() => {
                const пары = [
                  { ключ: 'поставщики', сост: с.справочники.partners },
                  { ключ: 'договоры', сост: с.справочники.contracts },
                ]
                const отстал = пары.some((п) => !п.сост.синхронно)
                return (
                  <div className={`rounded-md border p-3 text-xs ${
                    отстал ? 'border-amber-500/40 bg-amber-500/5' : 'border-border bg-muted/30'
                  }`}>
                    <span className="font-medium">Справочники контрагентов:</span>{' '}
                    {пары.map((п, i) => (
                      <span key={п.ключ}>
                        {i > 0 && ' · '}
                        {п.ключ} {п.сост.на_станции}/{п.сост.в_центре}
                        {п.сост.синхронно
                          ? ''
                          : п.сост.в_пути
                            ? ' (в пути)'
                            : ' — отстают'}
                      </span>
                    ))}
                    {отстал ? (
                      <span className="text-muted-foreground">
                        {' '}· свежий состав уедет ближайшим тактом связи
                      </span>
                    ) : null}
                  </div>
                )
              })()}

              {с.сверка && (с.сверка.нет_в_центре || с.сверка.нет_на_станции) ? (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs">
                  Расхождение справочника: центр не знает о{' '}
                  <b>{с.сверка.нет_в_центре}</b> карточках станции, станция не получила{' '}
                  <b>{с.сверка.нет_на_станции}</b>. Карточка, о которой центр не знает,
                  продаётся на полке и не попадает ни в один сетевой отчёт.
                </div>
              ) : null}
            </section>
          ))}
          {пульс.data?.rows.length === 0 && (
            <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
              Ни одной станции не заведено. Станция появляется здесь, как только
              её агент пришлёт первый пакет.
            </div>
          )}
        </>
      )}

      {вид === 'twins' && (
        <>
          {тёзки.isLoading && <div className="text-sm text-muted-foreground">Загрузка…</div>}
          {тёзки.data && (
            <div className="space-y-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="flex gap-2">
                <Copy className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  Карточки с одинаковым именем. Одинаковое имя само по себе не беда —
                  беда, когда за ним стоит один и тот же товар: сводный отчёт по сети
                  разойдётся по двум строкам молча. Разбор ниже отделяет одно от другого.
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {ВИДЫ_ТЁЗОК.map((в) => {
                  const счёт = в.k ? (тёзки.data?.по_видам?.[в.k] ?? 0) : тёзки.data?.пар ?? 0
                  return (
                    <button
                      key={в.k || 'все'}
                      onClick={() => setВидТёзок(в.k)}
                      className={`rounded-md border px-2 py-1 text-xs transition ${
                        видТёзок === в.k
                          ? 'border-primary bg-primary/10 font-medium text-foreground'
                          : 'bg-background hover:bg-muted'
                      }`}
                      title={в.hint}
                    >
                      {в.label} · {счёт}
                    </button>
                  )
                })}
              </div>
              {ВИДЫ_ТЁЗОК.find((в) => в.k === видТёзок)?.hint && (
                <div className="pl-6">{ВИДЫ_ТЁЗОК.find((в) => в.k === видТёзок)!.hint}</div>
              )}
            </div>
          )}
          <div className="space-y-2">
            {тёзки.data?.группы.map((г) => (
              <div key={г.ключ} className="rounded-lg border bg-card p-3">
                <div className="mb-2 flex items-baseline gap-2 text-xs">
                  <span
                    className={`rounded px-1.5 py-0.5 uppercase tracking-wide ${
                      г.вид === 'дубль сети'
                        ? 'bg-destructive/10 font-medium text-destructive'
                        : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {г.вид}
                  </span>
                  <span className="text-muted-foreground">занято карточек: {г.живых}</span>
                </div>
                <div className="space-y-1">
                  {г.карточки.map((к) => (
                    <div key={к.id} className="flex flex-wrap items-baseline gap-2 text-sm">
                      <span className={к.живая ? 'font-medium' : 'text-muted-foreground'}>
                        {к.name}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {к.sku || 'без артикула'}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {к.станции.length > 0
                          ? `АЗС ${к.станции.join(', ')}`
                          : 'ни одной станции'}
                        {' · '}
                        {к.штрихкодов > 0 ? `ШК ${к.штрихкодов}` : 'без штрихкода'}
                        {к.кодов_кассы > 0 && ` · касса ${к.кодов_кассы}`}
                        {к.остаток > 0 && ` · остаток ${к.остаток}`}
                        {' · '}
                        {к.sku_class}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {тёзки.data?.группы.length === 0 && (
              <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
                Ни одной такой пары.
              </div>
            )}
          </div>
        </>
      )}
      {карточка && (
        <NomenclatureCardModal guid={карточка} companyId={company?.id ?? ''}
          dateFrom="" dateTo="" onClose={() => открытьКарточку(null)} />
      )}
    </div>
  )
}
