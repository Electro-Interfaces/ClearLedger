/**
 * «Позиция» — главный экран пилота (docs/MARKET.md §5).
 *
 * Одна строка = один наш объект, и в ней сразу два мира: слева наши продажи и наша
 * цена, справа — кто стоит рядом и почём заряжает. Порознь они бесполезны: «выручка
 * упала» без соседей ничего не объясняет, а «рядом открылся конкурент» без нашей
 * выручки не говорит, важно ли это.
 *
 * Разворот строки показывает само окружение — с расстоянием, ценой и её датой.
 */
import { Fragment, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { StationLink } from '@/components/common/StationLink'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { SortTh } from '@/components/workspace/SortableTh'
import { useTableSort } from '@/hooks/useTableSort'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import { MarketSelfPanel } from './MarketSelfPanel'
import { getMarketPosition, SITE_KIND_LABEL, type MarketPositionRow } from '@/services/marketService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function money(v: number): string {
  if (v >= 1_000_000) return `${nf1.format(v / 1_000_000)} млн ₽`
  if (v >= 1_000) return `${nf0.format(v / 1_000)} тыс ₽`
  return `${nf0.format(v)} ₽`
}

/** Разрыв с рынком: плюс — мы дороже. Цвет помогает, но смысл несёт слово: цвет
 *  как единственный признак состояния не проходит ни в одной теме. Токены
 *  семантические (`warning`/`success`), а не палитра Tailwind — иначе контраст в
 *  тёмной теме никем не проверяется. */
function GapCell({ gap }: { gap: number | null }) {
  if (gap == null) return <span className="text-muted-foreground">нет сравнения</span>
  const dearer = gap > 5
  const cheaper = gap < -5
  const cls = dearer ? 'text-warning' : cheaper ? 'text-success' : 'text-foreground'
  return (
    <span className={`font-medium tabular-nums ${cls}`}>
      {gap > 0 ? '+' : ''}{nf1.format(gap)} %
      <span className="ml-1 font-normal text-muted-foreground">
        {dearer ? 'дороже' : cheaper ? 'дешевле' : 'на уровне'}
      </span>
    </span>
  )
}

function Neighbours({ row }: { row: MarketPositionRow }) {
  // Соседи сортируются своим порядком: вопрос к ним не «кто ближе», а «кто дешевле»
  // и «кто ещё жив», и ответ меняется от объекта к объекту.
  const карта = useMemo(() => ({
    name: (n: MarketPositionRow['neighbours'][number]) => n.name,
    distance: (n: MarketPositionRow['neighbours'][number]) => n.distanceKm,
    ports: (n: MarketPositionRow['neighbours'][number]) => n.ports,
    price: (n: MarketPositionRow['neighbours'][number]) => n.pricePerKwh,
    observed: (n: MarketPositionRow['neighbours'][number]) => n.observedOn,
  }), [])
  const { rows: соседи, sort, toggle } = useTableSort(
    row.neighbours, карта, { key: 'distance', dir: 'asc' })
  if (!row.neighbours.length) {
    return (
      <div className="px-4 py-3 text-xs text-muted-foreground">
        В радиусе никого не заведено. Это не значит, что рядом пусто — значит, рынок
        здесь ещё не наблюдали.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto px-4 py-2">
      <p className="mb-2 text-sm">Все соседи: {row.neighbours.length}. В медиане: {row.priceCoverage ?? 0}. Наша сеть показана для ориентира и в медиану не входит.</p>
      <table className="w-full text-xs"
        {...exportRows(`Соседи · ${row.name}`.slice(0, 28), [
          'Кто рядом', 'Оператор', 'Вид', 'Спрос', 'Расстояние, км', 'Портов',
          'Цена ₽/кВт·ч', 'Наблюдалась',
        ], row.neighbours.map((n) => [
          n.name, n.operatorName ?? null,
          n.siteClass === 'home' ? 'домашняя розетка'
            : n.siteClass === 'independent' ? 'независимая точка' : SITE_KIND_LABEL[n.kind],
          n.lastSessionAt ? (n.alive ? 'заряжали недавно' : 'молчит больше 90 дней') : 'нет данных',
          n.distanceKm, n.ports, n.pricePerKwh, n.observedOn,
        ]))}>
        <thead className="text-muted-foreground">
          <tr>
            <SortTh sortKey="name" sort={sort} onSort={toggle}>Кто рядом</SortTh>
            <th className="py-1 text-left font-medium">Вид</th>
            <th className="py-1 text-left font-medium">Спрос</th>
            <SortTh sortKey="distance" sort={sort} onSort={toggle} align="right">Расст.</SortTh>
            <SortTh sortKey="ports" sort={sort} onSort={toggle} align="right">Портов</SortTh>
            <SortTh sortKey="price" sort={sort} onSort={toggle} align="right">Цена ₽/кВтч</SortTh>
            <SortTh sortKey="observed" sort={sort} onSort={toggle}>Наблюдалась</SortTh>
          </tr>
        </thead>
        <tbody>
          {соседи.map((n) => (
            <tr key={n.id} className="border-t border-border/40">
              <td className="py-1">
                {n.name}
                {n.operatorName && (
                  <span className="text-muted-foreground"> · {n.operatorName}</span>
                )}
              </td>
              <td className="py-1 text-muted-foreground">
                {n.siteClass === 'home' ? 'домашняя розетка'
                  : n.siteClass === 'independent' ? 'независимая точка'
                  : SITE_KIND_LABEL[n.kind]}
              </td>
              <td className="py-1 text-muted-foreground">
                {n.lastSessionAt
                  ? (n.alive ? 'заряжали недавно' : 'молчит больше 90 дней')
                  : 'нет данных'}
              </td>
              <td className="py-1 text-right tabular-nums">{nf1.format(n.distanceKm)} км</td>
              <td className="py-1 text-right tabular-nums">{n.ports ?? '—'}</td>
              <td className="py-1 text-right tabular-nums">
                {n.pricePerKwh != null ? nf1.format(n.pricePerKwh) : '—'}
              </td>
              <td className="py-1 text-muted-foreground">{n.observedOn ?? 'не наблюдалась'}
                <div>{n.priceStale ? 'Цена устарела' : n.includedInPrice ? 'Входит в медиану' : 'В медиану не входит'}</div>
                <div>{n.currentType ?? 'Тип тока неизвестен'} · {n.maxPowerKw ?? '—'} кВт · {n.priceBasis ?? 'Основание неизвестно'}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Два взгляда на одно: наш объект против соседей и наш профиль глазами клиента. */
const ВИДЫ = [
  { k: 'objects', label: 'Наши объекты' },
  { k: 'pivot', label: 'Сводная' },
  { k: 'self', label: 'Мы глазами рынка' },
] as const

export function MarketPositionPanel() {
  const [вид, setВид] = useState<string>('objects')
  if (вид === 'pivot') {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="px-4 pt-4">
          <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />
        </div>
        <div className="min-h-0 flex-1 overflow-auto"><MarketPositionPivot /></div>
      </div>
    )
  }
  if (вид === 'self') {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="px-4 pt-4">
          <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />
        </div>
        <div className="min-h-0 flex-1"><MarketSelfPanel /></div>
      </div>
    )
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-4 pt-4">
        <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />
      </div>
      <div className="min-h-0 flex-1"><MarketPositionTable /></div>
    </div>
  )
}

function MarketPositionTable() {
  const { companyId } = useCompany()
  const { period, regionIds } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  const [radius, setRadius] = useState('5')
  const [currentType, setCurrentType] = useState('all')
  const [minPower, setMinPower] = useState('0')
  const [q, setQ] = useState('')
  const [onlyRivals, setOnlyRivals] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const pos = useQuery({
    queryKey: ['market-position', companyId, radius, period.from, period.to, regionIds, currentType, minPower],
    queryFn: () => getMarketPosition(companyId, { radius_km: Number(radius), date_from: period.from, date_to: period.to, ...(currentType === 'all' ? {} : { current_type: currentType }), min_power: Number(minPower) }),
    enabled: !!companyId,
  })

  // Ради чего экран и открывают: отобрать объекты, где мы дороже или дешевле рынка.
  // Глазами по шести сотням строк такой отбор не делается (замечание РусГидро
  // 14.09.2026). Карта до ранних возвратов: порядок хуков обязан совпадать на
  // каждой отрисовке.
  const сортировка = useMemo(() => ({
    name: (r: MarketPositionRow) => r.name,
    city: (r: MarketPositionRow) => r.city,
    sessions: (r: MarketPositionRow) => r.sessions,
    energy: (r: MarketPositionRow) => r.energyKwh,
    revenue: (r: MarketPositionRow) => r.revenue,
    ourPrice: (r: MarketPositionRow) => r.ourPricePerKwh,
    marketPrice: (r: MarketPositionRow) => r.marketPricePerKwh,
    gap: (r: MarketPositionRow) => r.priceGapPct,
    rivals: (r: MarketPositionRow) => r.rivals,
    rivalsAlive: (r: MarketPositionRow) => r.rivalsAlive,
  }), [])

  // Отбор и сортировка — до скелетона: во время загрузки это пустой список, но
  // порядок хуков обязан совпадать на каждой отрисовке.
  const отобранные = (pos.data?.objects ?? []).filter((r) =>
    (!onlyRivals || r.rivals > 0)
    && (!q || r.name.toLowerCase().includes(q.toLowerCase())
        || (r.city ?? '').toLowerCase().includes(q.toLowerCase())))
  const { rows, sort, toggle } = useTableSort(отобранные, сортировка)

  if (pos.isLoading) {
    // Скелетон, а не спиннер по центру: экран грузится в свою же раскладку, и человек
    // видит, ЧТО именно сейчас появится.
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        {/* Скелетон молчит, и на долгом счёте это читается как «зависло». Поэтому
            рядом сказано, что именно считается: экран сводит наши продажи с
            окружением каждого объекта, и это работа, а не ожидание сети. */}
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Считаем окружение каждого объекта: кто стоит рядом и почём заряжает.
        </div>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const all = pos.data?.objects ?? []

  const stalePrices = all.reduce((n, r) => n + (r.stalePrices ?? 0), 0)
  const withRivals = all.filter((r) => r.rivals > 0).length
  const comparable = all.filter((r) => r.priceGapPct != null)
  const pricier = comparable.filter((r) => (r.priceGapPct ?? 0) > 5).length
  const cheaper = comparable.filter((r) => (r.priceGapPct ?? 0) < -5).length
  // Вывод экрана словами. Без покрытия он был бы враньём: «дороже рынка на четырёх
  // объектах» из шестисот — это про четыре объекта, а не про сеть.
  const verdict = comparable.length === 0
    ? 'Нет сравнения: нужны наша цена за период и свежие сопоставимые цены рынка.'
    : pricier > cheaper
      ? `Мы дороже рынка на ${pricier} объектах и дешевле на ${cheaper}.`
      : cheaper > 0
        ? `Мы дешевле рынка на ${cheaper} объектах и дороже на ${pricier}.`
        : 'Наша цена держится на уровне рынка везде, где есть с чем сравнить.'
  const rivalsAlive = all.reduce((acc, r) => acc + (r.rivalsAlive ?? 0), 0)
  const rivalsAll = all.reduce((acc, r) => acc + r.rivals, 0)

  return (
    <div ref={экран} className="h-full space-y-3 overflow-auto p-3 pb-20 sm:flex sm:min-h-0 sm:flex-col sm:gap-3 sm:space-y-0 sm:overflow-hidden sm:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Объект или город"
          className="h-8 w-[220px] text-xs" />
        <Select value={radius} onValueChange={setRadius}>
          <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="2">Радиус 2 км</SelectItem>
            <SelectItem value="5">Радиус 5 км</SelectItem>
            <SelectItem value="10">Радиус 10 км</SelectItem>
            <SelectItem value="25">Радиус 25 км</SelectItem>
          </SelectContent>
        </Select>
        <Select value={currentType} onValueChange={setCurrentType}>
          <SelectTrigger className="h-9 w-[150px] text-xs" aria-label="Тип зарядки рынка"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Рынок: AC и DC</SelectItem><SelectItem value="AC">Рынок: AC</SelectItem><SelectItem value="DC">Рынок: DC</SelectItem></SelectContent>
        </Select>
        <Select value={minPower} onValueChange={setMinPower}>
          <SelectTrigger className="h-9 w-[150px] text-xs" aria-label="Мощность рынка"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="0">Любая мощность</SelectItem><SelectItem value="50">От 50 кВт</SelectItem><SelectItem value="150">От 150 кВт</SelectItem></SelectContent>
        </Select>
        <button type="button" onClick={() => setOnlyRivals((v) => !v)}
          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors
            ${onlyRivals ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent'}`}>
          Только с соседями
        </button>
        <span className="ml-auto text-xs text-muted-foreground">
          {rows.length} объектов · с соседями {withRivals} · {comparable.length ? `дороже рынка ${pricier}` : 'нет свежего сравнения'}
        </span>
        <span data-export-ignore>
          <ExportButton title="Позиция"
            subtitle={`радиус ${radius} км · продажи ${period.from} — ${period.to} · ${rows.length} объектов`}
            getEl={() => экран.current} />
        </span>
      </div>

      <div className="space-y-1 text-sm" role="note">
        <p>Наши объекты — эксплуатационный реестр, включая объекты без координат. Продажи: {pos.data?.salesFrom} — {pos.data?.salesTo}.</p>
        <details className="text-muted-foreground"><summary className="cursor-pointer py-1">Как сопоставляем цены</summary><p>{pos.data?.comparisonNote}</p></details>
        {stalePrices > 0 && <p className="font-medium text-foreground">Цены старше {pos.data?.priceMaxAgeDays} дней исключены; прошлые значения доступны в расшифровке.</p>}
      </div>
      {/* Сначала вывод, потом данные, из которых он собран. */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="text-sm font-medium">{verdict}</span>
          <span className="text-xs text-muted-foreground">
            посчитано по {comparable.length} из {all.length} объектов
          </span>
          {rivalsAll > 0 && (
            <span className="text-xs text-muted-foreground">
              соседей рядом {rivalsAll}, из них заряжали за 90 дней {rivalsAlive}
            </span>
          )}
        </CardContent>
      </Card>


      <div className="overflow-auto rounded-lg border border-border sm:min-h-0 sm:flex-1">
        <table className="w-full min-w-[800px] text-xs"
          {...exportRows('Позиция', [
            'Наш объект', 'Город', 'Сессий', 'кВт·ч', 'Выручка, ₽', 'Наша ₽/кВт·ч',
            'Рынок ₽/кВт·ч', 'Разрыв, %', 'Соседей ЭЗС', 'Из них живых', 'Точек притяжения',
          ], rows.map((r) => [
            r.name, r.city, r.sessions, r.energyKwh, r.revenue, r.ourPricePerKwh,
            r.marketPricePerKwh, r.priceGapPct, r.rivals, r.rivalsAlive, r.attractors,
          ]))}>
          <thead className="sticky top-0 z-10 bg-muted text-muted-foreground">
            <tr>
              <SortTh sortKey="name" sort={sort} onSort={toggle}>Наш объект</SortTh>
              <SortTh sortKey="sessions" sort={sort} onSort={toggle} align="right">Сессий</SortTh>
              <SortTh sortKey="energy" sort={sort} onSort={toggle} align="right">кВтч</SortTh>
              <SortTh sortKey="revenue" sort={sort} onSort={toggle} align="right">Выручка</SortTh>
              <SortTh sortKey="ourPrice" sort={sort} onSort={toggle} align="right">Наша ₽/кВтч</SortTh>
              <SortTh sortKey="marketPrice" sort={sort} onSort={toggle} align="right">Рынок ₽/кВтч</SortTh>
              <SortTh sortKey="gap" sort={sort} onSort={toggle} align="right">Разрыв</SortTh>
              <SortTh sortKey="rivals" sort={sort} onSort={toggle} align="right">Соседи (живых)</SortTh>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const expanded = open === r.locationId
              return (
                <Fragment key={r.locationId}>
                  <tr
                    onClick={() => setOpen(expanded ? null : r.locationId)}
                    className="cursor-pointer border-t border-border/60 hover:bg-accent/30">
                    <td className="p-2">
                      <span className="flex items-center gap-1.5">
                        <button type="button" className="flex size-9 shrink-0 items-center justify-center rounded hover:bg-accent"
                          aria-label={`${expanded ? 'Скрыть' : 'Показать'} соседей: ${r.name}`} aria-expanded={expanded}
                          onClick={e => { e.stopPropagation(); setOpen(expanded ? null : r.locationId) }}>
                          {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                        </button>
                        <span className="font-medium text-foreground">
                          <StationLink station={r.locationId}>{r.name}</StationLink>
                        </span>
                      </span>
                      <div className="pl-5 text-xs text-muted-foreground">
                        {r.city ?? '—'}{!r.hasGeo && ' · без координат'}
                      </div>
                    </td>
                    <td className="p-2 text-right tabular-nums">{nf0.format(r.sessions)}</td>
                    <td className="p-2 text-right tabular-nums">{nf0.format(r.energyKwh)}</td>
                    <td className="p-2 text-right tabular-nums">{money(r.revenue)}</td>
                    <td className="p-2 text-right tabular-nums">
                      {r.ourPricePerKwh != null ? nf1.format(r.ourPricePerKwh) : '—'}
                    </td>
                    <td className="p-2 text-right tabular-nums">
                      {r.marketPricePerKwh != null ? nf1.format(r.marketPricePerKwh) : '—'}
                      <div className="text-xs text-muted-foreground">{r.priceCoverage ?? 0} цен{r.marketObservedFrom ? ` · ${r.marketObservedFrom} — ${r.marketObservedTo}` : ' · нет свежих'}</div>
                    </td>
                    <td className="p-2 text-right"><GapCell gap={r.priceGapPct} /></td>
                    <td className="p-2 text-right tabular-nums">
                      {r.rivals > 0 ? `${r.rivals} ЭЗС (${r.rivalsAlive ?? 0})` : '—'}
                      {r.attractors > 0 && (
                        <span className="text-muted-foreground"> · {r.attractors} точек</span>
                      )}
                    </td>
                  </tr>
                  {expanded && (
                    <tr key={`${r.locationId}-n`} className="bg-muted/20">
                      <td colSpan={8}><Neighbours row={r} /></td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}


/**
 * Сводная «Позиции»: те же объекты, свёрнутые по городу и положению к рынку.
 *
 * Вопрос, ради которого экран открывают, звучит не «что с объектом N», а «где мы
 * дороже рынка» — и ответ на него даёт не список из шестисот строк, а два уровня
 * группировки (замечание РусГидро 14.09.2026).
 *
 * Цена не мера: сводная складывает, а сумма цен по городу не значит ничего.
 * Поэтому цена входит разрезом — «дороже рынка», «на уровне», «дешевле».
 */
function MarketPositionPivot() {
  const { companyId } = useCompany()
  const { period, regionIds } = useFilters()
  const [radius, setRadius] = useState('5')
  const [currentType, setCurrentType] = useState('all')
  const [minPower, setMinPower] = useState('0')
  const pos = useQuery({
    queryKey: ['market-position', companyId, radius, period.from, period.to, regionIds, currentType, minPower],
    queryFn: () => getMarketPosition(companyId, { radius_km: Number(radius), date_from: period.from, date_to: period.to, ...(currentType === 'all' ? {} : { current_type: currentType }), min_power: Number(minPower) }),
    enabled: !!companyId,
  })

  const строки = useMemo(() => (pos.data?.objects ?? []).map((r) => ({
    city: r.city ?? '— город не указан —',
    position: r.priceGapPct == null ? 'нет сравнения'
      : r.priceGapPct > 5 ? 'дороже рынка'
      : r.priceGapPct < -5 ? 'дешевле рынка' : 'на уровне рынка',
    rivals: r.rivals > 0 ? 'соседи есть' : 'соседей нет',
    alive: (r.rivalsAlive ?? 0) > 0 ? 'соседи живые' : 'живых соседей нет',
    geo: r.hasGeo ? 'с координатами' : 'без координат',
    objects: 1,
    sessions: r.sessions,
    energy: Math.round(r.energyKwh),
    revenue: Math.round(r.revenue),
    rivalsCount: r.rivals,
  })), [pos.data])

  if (pos.isLoading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Считаем окружение каждого объекта.
      </div>
    )
  }

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={radius} onValueChange={setRadius}>
          <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="2">Радиус 2 км</SelectItem>
            <SelectItem value="5">Радиус 5 км</SelectItem>
            <SelectItem value="10">Радиус 10 км</SelectItem>
            <SelectItem value="25">Радиус 25 км</SelectItem>
          </SelectContent>
        </Select>
        <Select value={currentType} onValueChange={setCurrentType}>
          <SelectTrigger className="h-9 w-[150px] text-xs" aria-label="Тип зарядки рынка"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Рынок: AC и DC</SelectItem><SelectItem value="AC">Рынок: AC</SelectItem><SelectItem value="DC">Рынок: DC</SelectItem></SelectContent>
        </Select>
        <Select value={minPower} onValueChange={setMinPower}>
          <SelectTrigger className="h-9 w-[150px] text-xs" aria-label="Мощность рынка"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="0">Любая мощность</SelectItem><SelectItem value="50">От 50 кВт</SelectItem><SelectItem value="150">От 150 кВт</SelectItem></SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {строки.length} объектов · цена входит разрезом, а не мерой: сумма цен по
          городу не значит ничего
        </span>
      </div>
      <ReportPivot
        fields={['city', 'position', 'rivals', 'alive', 'geo',
                 'objects', 'sessions', 'energy', 'revenue', 'rivalsCount']}
        columns={['Город', 'Положение к рынку', 'Соседи', 'Живые соседи', 'Координаты',
                  'Объектов', 'Сессий', 'кВт·ч', 'Выручка, ₽', 'Соседей рядом']}
        rows={строки}
      />
    </div>
  )
}
