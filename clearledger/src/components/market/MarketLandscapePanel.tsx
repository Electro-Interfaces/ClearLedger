/**
 * «Расклад сил» — раздел «Рынок» перестаёт быть списком точек.
 *
 * Здесь два слоя, которых в открытых источниках нет: чья ИТ-платформа обслуживает
 * сеть и участвует ли сеть в роуминге. Первое говорит, с кем на самом деле идёт
 * разговор о технологии — рынок держится на нескольких платформах, и большинство
 * сетей на них клиенты. Второе отвечает на вопрос водителя «где я смогу зарядиться
 * одним приложением».
 *
 * Отсутствие роуминга — факт о технологии, а не о качестве: так и написано, «работает
 * только в своём приложении». А вот оценка приложения — прямой отзыв водителя о
 * сервисе, и её мы показываем рядом со своей.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Swords } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { SortTh } from '@/components/workspace/SortableTh'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { useTableSort } from '@/hooks/useTableSort'
import { useCompany } from '@/contexts/CompanyContext'
import { MarketCompaniesPanel } from './MarketCompaniesPanel'
import {
  getMarketLandscape, type MarketNetworkRow, type MarketOwnerRow,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const ВИДЫ = [
  { k: 'power', label: 'Расклад сил' },
  // Владелец и эксплуатант — разные компании чаще, чем кажется: ZEVS владеет,
  // «Пункт Е» эксплуатирует. Разговор об интеграции идёт с первым, о тарифе —
  // со вторым (замечание РусГидро 14.09.2026).
  { k: 'owners', label: 'Владельцы ЭЗС' },
  { k: 'platforms', label: 'Платформы' },
  { k: 'roaming', label: 'Роуминг' },
  { k: 'service', label: 'Качество сервиса' },
  { k: 'legal', label: 'Реквизиты' },
] as const

function Num({ v, unit, digits = 0 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  return <span className="tabular-nums">
    {digits ? nf1.format(v) : nf.format(v)}{unit ? ` ${unit}` : ''}
  </span>
}

/** Строка нашей сети подсвечена: сравнение с рынком идёт от неё. */
function rowClass(r: MarketNetworkRow): string {
  return r.isOurs ? 'border-t border-border bg-primary/5 font-medium' : 'border-t border-border/50'
}

export function MarketLandscapePanel() {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const [вид, setВид] = useState<string>('power')
  // Расклад отвечает «кто сильнее», карточка — «что он делает». Второй вопрос
  // возникает сразу после первого, поэтому строка сети ведёт в карточку, а не
  // заставляет искать компанию в другом разделе.
  const [карточка, setКарточка] = useState<string | null>(null)
  // Сортировка по столбцу: менеджеру нужен то верх по числу точек, то по цене, то
  // по доле живых — перебирать это глазами в таблице на сотню строк нельзя.
  const сортировка = useMemo(() => ({
    name: (r: MarketNetworkRow) => r.name,
    sites: (r: MarketNetworkRow) => r.sites,
    share: (r: MarketNetworkRow) => r.sharePct,
    cities: (r: MarketNetworkRow) => r.citiesCount,
    districts: (r: MarketNetworkRow) => r.districts,
    power: (r: MarketNetworkRow) => r.avgPowerKw,
    price: (r: MarketNetworkRow) => r.medianPricePerKwh,
    model: (r: MarketNetworkRow) => r.class,
    base: (r: MarketNetworkRow) => r.baseCity,
  }), [])
  const [q, setQ] = useState('')
  // У каждого вида свои столбцы, а значит и своя карта сортировки: в роуминге
  // сравнивают долю открытых точек, в качестве — успешность, в реквизитах — ИНН.
  const сорт_роуминга = useMemo(() => ({
    name: (r: MarketNetworkRow) => r.name,
    sites: (r: MarketNetworkRow) => r.sites,
    access: (r: MarketNetworkRow) => (r.roaming === null ? null : r.roaming ? 1 : 0),
    pct: (r: MarketNetworkRow) => r.roamingPct,
    platform: (r: MarketNetworkRow) => r.platformOwner,
  }), [])
  const сорт_сервиса = useMemo(() => ({
    name: (r: MarketNetworkRow) => r.name,
    sites: (r: MarketNetworkRow) => r.sites,
    quality: (r: MarketNetworkRow) => r.quality,
    success: (r: MarketNetworkRow) => r.success,
    silent: (r: MarketNetworkRow) => r.silentHalfYear,
    rating: (r: MarketNetworkRow) => r.appRating,
    reviews: (r: MarketNetworkRow) => r.appReviews,
    app: (r: MarketNetworkRow) => r.appName,
  }), [])
  const сорт_реквизитов = useMemo(() => ({
    name: (r: MarketNetworkRow) => r.name,
    legal: (r: MarketNetworkRow) => r.legalName,
    inn: (r: MarketNetworkRow) => r.inn,
    ogrn: (r: MarketNetworkRow) => r.ogrn,
    director: (r: MarketNetworkRow) => r.director,
    trust: (r: MarketNetworkRow) => r.legalConfidence,
  }), [])
  const сорт_владельцев = useMemo(() => ({
    name: (r: MarketOwnerRow) => r.name,
    sites: (r: MarketOwnerRow) => r.sites,
    share: (r: MarketOwnerRow) => r.sharePct,
    alive: (r: MarketOwnerRow) => r.alive,
    self: (r: MarketOwnerRow) => r.operatedSelf,
    others: (r: MarketOwnerRow) => r.operatedByOthers,
  }), [])

  const data = useQuery({
    queryKey: ['market-landscape', companyId],
    queryFn: () => getMarketLandscape(companyId),
    enabled: !!companyId,
  })

  // Списки и сортировка — до ранних возвратов: порядок хуков обязан совпадать на
  // каждой отрисовке, иначе React путает их между собой.
  const t = data.data?.totals
  const all = data.data?.networks ?? []
  const отобранные = all.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()))
  const { rows, sort, toggle } = useTableSort(отобранные, сортировка)
  const роуминг = useTableSort(отобранные, сорт_роуминга)
  const сервис = useTableSort(отобранные, сорт_сервиса)
  const реквизиты = useTableSort(
    отобранные.filter((r) => r.legalName || r.inn), сорт_реквизитов)
  const владельцы = useTableSort(
    (data.data?.owners ?? []).filter(
      (r) => !q || r.name.toLowerCase().includes(q.toLowerCase())),
    сорт_владельцев)

  if (data.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем расклад сил</span>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const ours = all.find((r) => r.isOurs)
  const platforms = data.data?.platforms ?? []
  const owners = владельцы.rows

  if (карточка) {
    return <MarketCompaniesPanel initialOpen={карточка} onBack={() => setКарточка(null)} />
  }

  return (
    <div ref={экран} className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Swords className="size-4 text-primary" aria-hidden />
            {ours
              ? `Мы ${ours.sharePct} % рынка: ${nf.format(ours.sites)} точек в ${nf.format(ours.citiesCount ?? 0)} городах.`
              : `На рынке ${t?.networks ?? 0} сетей.`}
          </span>
          <span className="text-xs text-muted-foreground">
            {nf.format(t?.networks ?? 0)} сетей · {nf.format(t?.networkSites ?? 0)} точек ·
            своя платформа у {t?.ownPlatform ?? 0} · в роуминге {t?.roamingNetworks ?? 0}
          </span>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Сеть"
            className="h-8 w-[180px] text-xs" />
          {/* Выгружается открытый вид: в книге ровно то, что человек видит на экране,
              иначе в файле оказываются столбцы, о которых он не просил. */}
          <span data-export-ignore>
            <ExportButton title={`Расклад сил · ${ВИДЫ.find((v) => v.k === вид)?.label}`}
              subtitle={`${rows.length} сетей${q ? ` · отбор «${q}»` : ''}`}
              getEl={() => экран.current} />
          </span>
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      {вид === 'power' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Расклад сил', [
              'Сеть', 'Мы', 'Точек', 'Доля, %', 'Городов', 'Округов', 'Модель', 'База',
              'Средняя мощность, кВт', 'Медиана цены, ₽/кВт·ч',
            ], rows.map((r) => [
              r.name, r.isOurs ? 'мы' : null, r.sites, r.sharePct, r.citiesCount, r.districts,
              r.class ?? 'не определена', r.baseCity, r.avgPowerKw, r.medianPricePerKwh,
            ]))}>
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <SortTh sortKey="name" sort={sort} onSort={toggle}>Сеть</SortTh>
                <SortTh sortKey="sites" sort={sort} onSort={toggle} align="right">Точек</SortTh>
                <SortTh sortKey="share" sort={sort} onSort={toggle} align="right">Доля</SortTh>
                <SortTh sortKey="cities" sort={sort} onSort={toggle} align="right">Городов</SortTh>
                <SortTh sortKey="districts" sort={sort} onSort={toggle} align="right">Округов</SortTh>
                <SortTh sortKey="model" sort={sort} onSort={toggle}>Модель</SortTh>
                <SortTh sortKey="base" sort={sort} onSort={toggle}>База</SortTh>
                <SortTh sortKey="power" sort={sort} onSort={toggle} align="right">Средняя мощность</SortTh>
                <SortTh sortKey="price" sort={sort} onSort={toggle} align="right">Медиана цены</SortTh>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={`${rowClass(r)} cursor-pointer hover:bg-muted/40`}
                  onClick={() => setКарточка(r.id)} tabIndex={0} role="button"
                  onKeyDown={(e) => e.key === 'Enter' && setКарточка(r.id)}>
                  <td className="p-2 underline decoration-dotted underline-offset-2">
                    {r.name}{r.isOurs && ' · мы'}
                  </td>
                  <td className="p-2 text-right"><Num v={r.sites} /></td>
                  <td className="p-2 text-right"><Num v={r.sharePct} unit="%" digits={1} /></td>
                  <td className="p-2 text-right"><Num v={r.citiesCount} /></td>
                  <td className="p-2 text-right"><Num v={r.districts} /></td>
                  <td className="p-2 text-muted-foreground">
                    {r.class ?? 'не определена'}
                    {r.class && !r.classChecked && (
                      <span className="ml-1 text-xs">· не проверено</span>
                    )}
                  </td>
                  <td className="p-2 text-muted-foreground">{r.baseCity ?? '—'}</td>
                  <td className="p-2 text-right"><Num v={r.avgPowerKw} unit="кВт" digits={1} /></td>
                  <td className="p-2 text-right"><Num v={r.medianPricePerKwh} digits={1} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">{data.data?.note}</p>
        </div>
      )}

      {вид === 'owners' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Владелец — чей актив стоит на земле; эксплуатант — под чьим именем точка
            приходит в выгрузке. Совпадают они не всегда: сеть отдают в эксплуатацию
            другой компании, а в публичном реестре она числится за поставщиком
            платформы. Колонка «под чужим именем» и показывает такие точки: с их
            владельцами и говорят об интеграции.
            {(t?.ownerUnclear ?? 0) > 0 && (
              <span className="ml-1 text-warning">
                У {nf.format(t!.ownerUnclear)} точек владелец пока унаследован от
                платформы и не подтверждён — разбор в «Источниках и свежести».
              </span>
            )}
          </CardContent></Card>
          <div className="rounded-lg border border-border">
            <table className="w-full text-xs"
              {...exportRows('Владельцы ЭЗС', [
                'Владелец', 'Мы', 'Точек', 'Доля, %', 'Живых', 'Портов',
                'Обслуживает сам', 'Под чужим именем', 'Роли', 'Юрлицо', 'ИНН',
              ], owners.map((r) => [
                r.name, r.isOurs ? 'мы' : null, r.sites, r.sharePct, r.alive, r.ports,
                r.operatedSelf, r.operatedByOthers,
                [r.isOwner && 'владелец', r.isOperator && 'оператор', r.isPlatform && 'платформа']
                  .filter(Boolean).join(', '),
                r.legalTrusted ? r.legalName : null, r.legalTrusted ? r.inn : null,
              ]))}>
              <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
                <tr>
                  <SortTh sortKey="name" sort={владельцы.sort} onSort={владельцы.toggle}>Владелец</SortTh>
                  <SortTh sortKey="sites" sort={владельцы.sort} onSort={владельцы.toggle} align="right">Точек</SortTh>
                  <SortTh sortKey="share" sort={владельцы.sort} onSort={владельцы.toggle} align="right">Доля</SortTh>
                  <SortTh sortKey="alive" sort={владельцы.sort} onSort={владельцы.toggle} align="right">Живых</SortTh>
                  <SortTh sortKey="self" sort={владельцы.sort} onSort={владельцы.toggle} align="right">Обслуживает сам</SortTh>
                  <SortTh sortKey="others" sort={владельцы.sort} onSort={владельцы.toggle} align="right">Под чужим именем</SortTh>
                  <th className="p-2 text-left font-medium">Роли</th>
                </tr>
              </thead>
              <tbody>
                {owners.map((r) => (
                  <tr key={r.id} className={r.isOurs
                    ? 'border-t border-border bg-primary/5 font-medium'
                    : 'border-t border-border/50'}>
                    <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                    <td className="p-2 text-right"><Num v={r.sites} /></td>
                    <td className="p-2 text-right"><Num v={r.sharePct} unit="%" digits={1} /></td>
                    <td className="p-2 text-right"><Num v={r.alive} /></td>
                    <td className="p-2 text-right"><Num v={r.operatedSelf} /></td>
                    <td className="p-2 text-right">
                      {r.operatedByOthers > 0 ? (
                        <span className="tabular-nums text-warning">
                          {nf.format(r.operatedByOthers)}
                        </span>
                      ) : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="p-2 text-muted-foreground">
                      {[r.isOwner && 'владелец', r.isOperator && 'оператор',
                        r.isPlatform && 'платформа'].filter(Boolean).join(' · ')}
                      {!r.rolesChecked && (
                        <span className="ml-1 text-xs">· не проверено</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {owners.length === 0 && (
              <p className="p-6 text-center text-xs text-muted-foreground">
                Владельцы пока не разобраны: точки числятся за теми, под чьим именем
                пришли.
              </p>
            )}
          </div>
        </div>
      )}

      {вид === 'platforms' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Платформа — это чья система обслуживает станции. Сеть на чужой платформе
            технологически зависит от её владельца, и разговор с ней о протоколах,
            роуминге и интеграции идёт через него. Из {t?.networks ?? 0} сетей своя
            платформа у {t?.ownPlatform ?? 0}.
          </CardContent></Card>
          {platforms.map((p) => (
            <Card key={p.owner}>
              <CardContent className="p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-headline text-sm font-semibold">{p.owner}</span>
                  <span className="text-xs text-muted-foreground">
                    своих точек {nf.format(p.ownSites)} · чужих {nf.format(p.clientSites)}
                    {p.clients.length > 0 && ` в ${p.clients.length} сетях`}
                  </span>
                </div>
                {p.clients.length > 0 ? (
                  <ul className="mt-1 space-y-0.5">
                    {p.clients.map((c) => (
                      <li key={c.name} className="flex items-baseline justify-between gap-2 text-xs">
                        <span className="text-muted-foreground">{c.name}</span>
                        <span className="tabular-nums">{nf.format(c.sites)} точек</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Обслуживает только свою сеть.
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
          {/* Платформы показаны карточками, а выгрузка работает с таблицами: эта
              таблица не рисуется, а существует только затем, чтобы связка
              «платформа — её клиент» уехала в книгу строками. */}
          <table hidden {...exportRows('Платформы', [
            'Платформа', 'Своих точек', 'Чужих точек', 'Сетей-клиентов', 'Клиент', 'Точек у клиента',
          ], platforms.flatMap((p) => (p.clients.length
            ? p.clients.map((c) => [p.owner, p.ownSites, p.clientSites, p.clients.length, c.name, c.sites])
            : [[p.owner, p.ownSites, p.clientSites, 0, null, null]])))} />
        </div>
      )}

      {вид === 'roaming' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Роуминг означает, что на станции можно зарядиться через приложение другого
            оператора. В роуминге {t?.roamingNetworks ?? 0} сетей
            ({nf.format(t?.roamingSites ?? 0)} точек), только в своём приложении
            работают {t?.closedNetworks ?? 0} ({nf.format(t?.closedSites ?? 0)} точек).
            Это факт о технологии, а не о качестве сети.
          </CardContent></Card>
          <div className="rounded-lg border border-border">
            <table className="w-full text-xs"
              {...exportRows('Роуминг', [
                'Сеть', 'Мы', 'Точек', 'Доступ', 'Доля точек в роуминге, %', 'Платформа',
              ], роуминг.rows.map((r) => [
                r.name, r.isOurs ? 'мы' : null, r.sites,
                r.roaming ? 'роуминг с другими сетями'
                  : r.roaming === false ? 'только своё приложение' : 'нет данных',
                r.roamingPct, r.platformOwner,
              ]))}>
              <thead className="bg-muted/60 text-muted-foreground">
                <tr>
                  <SortTh sortKey="name" sort={роуминг.sort} onSort={роуминг.toggle}>Сеть</SortTh>
                  <SortTh sortKey="sites" sort={роуминг.sort} onSort={роуминг.toggle} align="right">Точек</SortTh>
                  <SortTh sortKey="access" sort={роуминг.sort} onSort={роуминг.toggle}>Доступ</SortTh>
                  <SortTh sortKey="pct" sort={роуминг.sort} onSort={роуминг.toggle} align="right">Доля точек в роуминге</SortTh>
                  <SortTh sortKey="platform" sort={роуминг.sort} onSort={роуминг.toggle}>Платформа</SortTh>
                </tr>
              </thead>
              <tbody>
                {роуминг.rows.map((r) => (
                  <tr key={r.id} className={rowClass(r)}>
                    <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                    <td className="p-2 text-right"><Num v={r.sites} /></td>
                    <td className="p-2">
                      {r.roaming
                        ? <span className="text-success">роуминг с другими сетями</span>
                        : r.roaming === false
                          ? <span className="text-muted-foreground">только своё приложение</span>
                          : <span className="text-muted-foreground">нет данных</span>}
                    </td>
                    <td className="p-2 text-right"><Num v={r.roamingPct} unit="%" digits={0} /></td>
                    <td className="p-2 text-muted-foreground">{r.platformOwner ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {вид === 'service' && (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Качество сервиса', [
              'Сеть', 'Мы', 'Точек', 'Связь, %', 'Успешных зарядок, %', 'Молчат больше полугода',
              'Доля молчащих, %', 'Оценка приложения', 'Отзывов', 'Приложение',
            ], сервис.rows.map((r) => [
              r.name, r.isOurs ? 'мы' : null, r.sites, r.quality, r.success, r.silentHalfYear,
              r.sites > 0 ? (r.silentHalfYear / r.sites) * 100 : null,
              r.appRating, r.appReviews, r.appName,
            ]))}>
            <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
              <tr>
                <SortTh sortKey="name" sort={сервис.sort} onSort={сервис.toggle}>Сеть</SortTh>
                <SortTh sortKey="sites" sort={сервис.sort} onSort={сервис.toggle} align="right">Точек</SortTh>
                <SortTh sortKey="quality" sort={сервис.sort} onSort={сервис.toggle} align="right">Связь</SortTh>
                <SortTh sortKey="success" sort={сервис.sort} onSort={сервис.toggle} align="right">Успешных зарядок</SortTh>
                <SortTh sortKey="silent" sort={сервис.sort} onSort={сервис.toggle} align="right">Молчат больше полугода</SortTh>
                <SortTh sortKey="rating" sort={сервис.sort} onSort={сервис.toggle} align="right">Оценка приложения</SortTh>
                <SortTh sortKey="reviews" sort={сервис.sort} onSort={сервис.toggle} align="right">Отзывов</SortTh>
                <SortTh sortKey="app" sort={сервис.sort} onSort={сервис.toggle}>Приложение</SortTh>
              </tr>
            </thead>
            <tbody>
              {сервис.rows.map((r) => (
                <tr key={r.id} className={rowClass(r)}>
                  <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                  <td className="p-2 text-right"><Num v={r.sites} /></td>
                  <td className="p-2 text-right"><Num v={r.quality} unit="%" digits={1} /></td>
                  <td className="p-2 text-right"><Num v={r.success} unit="%" digits={1} /></td>
                  <td className="p-2 text-right">
                    <Num v={r.silentHalfYear} />
                    {r.sites > 0 && r.silentHalfYear > 0 && (
                      <span className="ml-1 text-muted-foreground">
                        {nf1.format((r.silentHalfYear / r.sites) * 100)} %
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right">
                    {r.appRating == null ? <span className="text-muted-foreground">нет данных</span> : (
                      <span className={`tabular-nums ${r.appRating >= 4 ? 'text-success'
                        : r.appRating < 2.5 ? 'text-warning' : ''}`}>
                        {nf1.format(r.appRating)}
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right"><Num v={r.appReviews} /></td>
                  <td className="p-2 text-muted-foreground">{r.appName ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-2 text-xs text-muted-foreground">
            Четыре независимых среза одной темы: связь и успешность зарядок — техника,
            доля молчащих — спрос, оценка приложения — то, что об этом думает водитель.
            Пустая клетка означает, что источник этого показателя по сети не даёт.
          </p>
        </div>
      )}

      {вид === 'legal' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card><CardContent className="p-3 text-xs text-muted-foreground">
            Реквизиты подтверждены у {t?.legalTrusted ?? 0} сетей. Ссылаться можно
            только на подтверждённые: бренд и юрлицо часто не совпадают, и ошибка здесь
            дороже молчания.
          </CardContent></Card>
          <div className="rounded-lg border border-border">
            <table className="w-full text-xs"
              {...exportRows('Реквизиты', [
                'Сеть', 'Мы', 'Юридическое лицо', 'ИНН', 'ОГРН', 'Руководитель',
                'Достоверность', 'Ссылаться можно',
              ], реквизиты.rows.map((r) => [
                r.name, r.isOurs ? 'мы' : null, r.legalName, r.inn, r.ogrn, r.director,
                r.legalConfidence ?? 'не проверено', r.legalTrusted ? 'да' : 'нет',
              ]))}>
              <thead className="bg-muted/60 text-muted-foreground">
                <tr>
                  <SortTh sortKey="name" sort={реквизиты.sort} onSort={реквизиты.toggle}>Сеть</SortTh>
                  <SortTh sortKey="legal" sort={реквизиты.sort} onSort={реквизиты.toggle}>Юридическое лицо</SortTh>
                  <SortTh sortKey="inn" sort={реквизиты.sort} onSort={реквизиты.toggle}>ИНН</SortTh>
                  <SortTh sortKey="ogrn" sort={реквизиты.sort} onSort={реквизиты.toggle}>ОГРН</SortTh>
                  <SortTh sortKey="director" sort={реквизиты.sort} onSort={реквизиты.toggle}>Руководитель</SortTh>
                  <SortTh sortKey="trust" sort={реквизиты.sort} onSort={реквизиты.toggle}>Достоверность</SortTh>
                </tr>
              </thead>
              <tbody>
                {реквизиты.rows.map((r) => (
                  <tr key={r.id} className={rowClass(r)}>
                    <td className="p-2">{r.name}{r.isOurs && ' · мы'}</td>
                    <td className="p-2">{r.legalName ?? '—'}</td>
                    <td className="p-2 font-mono">{r.inn ?? '—'}</td>
                    <td className="p-2 font-mono">{r.ogrn ?? '—'}</td>
                    <td className="p-2 text-muted-foreground">{r.director ?? '—'}</td>
                    <td className="p-2">
                      <span className={r.legalTrusted ? 'text-success' : 'text-warning'}>
                        {r.legalConfidence ?? 'не проверено'}
                      </span>
                      {!r.legalTrusted && (
                        <span className="ml-1 text-muted-foreground">— ссылаться нельзя</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
