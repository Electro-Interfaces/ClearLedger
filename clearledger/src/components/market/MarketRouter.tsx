/**
 * Продукт «Маркетинг» — рынок вокруг сети (docs/MARKET.md).
 *
 * Волна 0: карта «наши против чужих», реестр точек рынка и лента наблюдений. Наши
 * объекты берутся из реестра пространства, чужие — из `/api/market/*`; копий не
 * заводим, поэтому одна и та же станция не может разъехаться в двух местах.
 *
 * Порядок пунктов подчинён вопросу менеджера: сначала «что вокруг» (карта), потом
 * «кто это» (точки, конкуренты), и только потом «откуда мы это знаем» (наблюдения).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, CircleMarker, Popup, AttributionControl, useMap,
  useMapEvents } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import { clusterPoints, clusterRadiusForZoom } from '@/components/map/clusterPoints'
import { MapResize } from '@/components/map/MapResize'
import 'leaflet/dist/leaflet.css'
import { Loader2, Maximize2, Minimize2, MapPin, Plus } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { SortTh } from '@/components/workspace/SortableTh'
import { useTableSort } from '@/hooks/useTableSort'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { MarketSiteCard } from './MarketSiteCard'
import { useFullscreenPanel } from '@/hooks/useFullscreenPanel'
import { useCompany } from '@/contexts/CompanyContext'
import {
  listMarketSites, listMarketObservations, listMarketOperators, getOurMapPoints,
  getSitesBreakdown,
  SITE_KIND_LABEL, CHANNEL_LABEL, type MarketObservation, type MarketSite,
  type MarketSiteKind, type OurMapPoint,
} from '@/services/marketService'
import {
  EMPTY_MARKET_FILTERS, EMPTY_OUR_FILTERS, MarketMapFilters,
  type MarketFilters, type OurFilters,
} from './MarketMapFilters'
import { MarketPositionPanel } from './MarketPositionPanel'
import { MarketImportDialog } from './MarketImportDialog'
import { MarketOcmButton } from './MarketOcmButton'
import { MarketSiteDialog } from './MarketSiteDialog'
import { MarketObservationDialog } from './MarketObservationDialog'
import { MarketSourcesPanel } from './MarketSourcesPanel'
import { MarketLandscapePanel } from './MarketLandscapePanel'
import { MarketPlayersPanel } from './MarketPlayersPanel'
import { MarketCoveragePanel } from './MarketCoveragePanel'
import { MarketTerritoriesPanel, MarketWhitespotsPanel } from './MarketTerritoriesPanel'
import { MarketSiteScorePanel } from './MarketSiteScorePanel'
import { MarketElasticityPanel, MarketPressurePanel, MarketPriceLandscapePanel } from './MarketPricePanel'
import { MarketScenariosPanel } from './MarketScenariosPanel'
import { MarketPartnersPanel } from './MarketPartnersPanel'
import { MarketGrowthPanel } from './MarketGrowthPanel'
import { MarketLeadsPanel } from './MarketLeadsPanel'

/** Тёмная тема приложения (класс `dark` на <html>) — как в карте продаж. */
function useIsDark() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const el = document.documentElement
    const obs = new MutationObserver(() => setDark(el.classList.contains('dark')))
    obs.observe(el, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return dark
}

/**
 * Фирменный синий: им залита КАЖДАЯ наша станция, в любом состоянии и при любом
 * разрезе. Принадлежность важнее показателя: выключенный объект, закрашенный серым
 * «по состоянию», на общем полотне читался как чужая точка, и человек не мог
 * ответить на первый вопрос к карте — где тут мы (решение МАГа 13.09.2026).
 */
const НАШ_ЦВЕТ = '#3b82f6'

/**
 * Размер точки на карте постоянный и не зависит от того, сколько станций стоит
 * рядом. Маркер, растущий по числу соседей, превращает карту в диаграмму пузырей:
 * круги наезжают друг на друга, и вместо сети человек видит скопления. Густота
 * читается количеством точек — их становится больше при приближении.
 */
const ТОЧКА_РЫНКА = 3.5
const ТОЧКА_НАША = 4.5

/** Разрез нашей станции — кольцом вокруг синей заливки: состояние, загрузка,
 *  срывы, деньги. Один слой отвечает на разные вопросы, не превращаясь в четыре
 *  карты и не теряя принадлежности. */
function ourColor(p: OurMapPoint, by: OurFilters['colorBy']): string {
  if (by === 'status') {
    if (p.status === 'working') return '#3b82f6'
    if (p.status === 'no_link') return '#f59e0b'
    if (p.status === 'decommissioned' || p.status === 'disabled') return '#64748b'
    if (p.status === 'not_working') return '#ef4444'
    return '#3b82f6'
  }
  if (by === 'load') {
    const v = p.sessionsPerPortDay
    if (v == null) return '#64748b'
    return v >= 2 ? '#0ea5e9' : v >= 1 ? '#3b82f6' : v >= 0.3 ? '#a5b4fc' : '#cbd5e1'
  }
  if (by === 'errors') {
    const v = p.errorPct
    if (v == null) return '#64748b'
    return v >= 30 ? '#ef4444' : v >= 10 ? '#f59e0b' : '#22c55e'
  }
  const v = p.revenue
  return v >= 1_000_000 ? '#1d4ed8' : v >= 200_000 ? '#3b82f6' : v > 0 ? '#93c5fd' : '#cbd5e1'
}

/** Цвет точки на карте: наши — фирменный, конкуренты — красный, притяжение — серый. */
function siteColor(s: MarketSite): string {
  if (s.isOurs) return НАШ_ЦВЕТ
  if (s.kind !== 'ezs') return '#94a3b8'
  // Независимая точка — не сеть: другой цвет, чтобы плотность рынка не выглядела
  // плотностью сетей (полная выгрузка 13.09.2026).
  if (s.siteClass === 'independent') return '#f59e0b'
  if (s.siteClass === 'home') return '#a78bfa'
  return '#ef4444'
}

/**
 * Стоят ли все точки группы в одной координате.
 *
 * У 22 наших мест несколько объектов с одинаковыми координатами: в Фокино рядом
 * «Клубная, 15» и выведенный из эксплуатации «ТЦ Меридиан», в Красноярске на
 * Перенсона — двенадцать записей. Приближение их не разведёт никогда, и совет
 * «приблизьте, чтобы увидеть каждый» отправлял человека делать бесполезное.
 */
function вОднойТочке(points: { lat: number; lon: number }[]): boolean {
  const [first] = points
  return points.every((p) => Math.abs(p.lat - first.lat) < 1e-5
    && Math.abs(p.lon - first.lon) < 1e-5)
}

/** Список объектов группы: когда их не развести, надо просто показать, кто это. */
function СписокОбъектов({ items }: { items: { name: string; note?: string | null }[] }) {
  return (
    <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
      {items.slice(0, 8).map((it, i) => (
        <li key={`${it.name}-${i}`}>
          {it.name}
          {it.note && <span style={{ opacity: 0.7 }}> · {it.note}</span>}
        </li>
      ))}
      {items.length > 8 && <li style={{ opacity: 0.7 }}>и ещё {items.length - 8}</li>}
    </ul>
  )
}

/**
 * Подсказка нашего объекта.
 *
 * Подписываем именем компании, а не словом «наш объект»: на одной карте рядом
 * стоят наши станции из своего реестра и они же из выгрузки рынка, где оператор
 * назван «РусГидро». Две разные подписи об одном и том же читались как две разные
 * сети (замечание МАГа 13.09.2026).
 */
function OurPopupBody({ p }: { p: OurMapPoint }) {
  const { company } = useCompany()
  const мы = company.shortName || company.name || 'наш объект'
  return (
    <>
      <b>{p.name}</b> · {мы}<br />
      {p.city ?? ''}{p.brand ? ` · ${p.brand}` : ''}
      {p.powerKwt ? ` · ${p.powerKwt} кВт` : ''}
      {p.ports ? ` · ${p.ports} портов` : ''}<br />
      сессий за 90 дней: {p.sessions}
      {p.sessionsPerPortDay != null && ` · ${p.sessionsPerPortDay} на порт в сутки`}<br />
      {p.errorPct != null ? `срывов ${p.errorPct} %` : 'срывы не считаны'}
      {p.status ? ` · ${p.status}` : ''}
    </>
  )
}

/** Возраст факта словами: «сегодня» важнее даты — по нему видно, можно ли доверять. */
function ageLabel(iso: string | null | undefined): { text: string; stale: boolean } {
  if (!iso) return { text: 'не проверялось', stale: true }
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return { text: 'сегодня', stale: false }
  if (days === 1) return { text: 'вчера', stale: false }
  return { text: `${days} дн назад`, stale: days > 30 }
}

function useMarketData(filters: MarketFilters, bbox?: string) {
  const { companyId } = useCompany()
  const sites = useQuery({
    // Точки грузятся по ВИДИМОЙ ОБЛАСТИ и отобранные на сервере: всей страной их
    // девять тысяч, и одна страница выдачи их не вмещает (ревизия 12.09.2026, К10).
    queryKey: ['market-sites', companyId, bbox ?? 'all', filters.kind,
               filters.operatorId, filters.currentType, filters.minPower, filters.alive],
    queryFn: () => listMarketSites(companyId, {
      ...(filters.kind === 'all' ? {} : { kind: filters.kind }),
      ...(filters.operatorId === 'all' ? {} : { operator_id: filters.operatorId }),
      ...(filters.currentType === 'all' ? {} : { current_type: filters.currentType }),
      ...(filters.minPower === 'all' ? {} : { min_power: Number(filters.minPower) }),
      ...(filters.alive === 'all' ? {} : { alive: filters.alive }),
      ...(bbox ? { bbox } : {}),
      limit: 5000,
    }),
    enabled: !!companyId,
    placeholderData: (prev) => prev,
  })
  // Наши объекты — из реестра пространства, но с НАШИМИ показателями: слой своих
  // станций фильтруют по работе, а не по названию (решение МАГа 13.09.2026).
  const ours = useQuery({
    queryKey: ['market-our-map', companyId],
    queryFn: () => getOurMapPoints(companyId, { days: 90 }),
    enabled: !!companyId,
  })
  return { sites, ours }
}

/** Следит за областью карты: что видно, то и грузим. */
function ViewportWatch({ onChange }: { onChange: (bbox: string, zoom: number) => void }) {
  const map = useMap()
  const report = () => {
    const b = map.getBounds()
    onChange(
      [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()]
        .map((v) => v.toFixed(4)).join(','),
      map.getZoom(),
    )
  }
  useMapEvents({ moveend: report, zoomend: report })
  useEffect(report, [])  // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

/** Слой точек: склеивает соседние в один маркер, пока масштаб не позволит развести. */
function MarketPoints({ market, ourPoints, zoom, colorBy }: {
  market: MarketSite[]
  ourPoints: OurMapPoint[]
  zoom: number
  colorBy: OurFilters['colorBy']
}) {
  const map = useMap()
  const radius = clusterRadiusForZoom(zoom)
  const ourClusters = useMemo(
    () => clusterPoints(map, ourPoints, radius, (p) => [p.lat, p.lon], (p) => `our-${p.id}`),
    [map, ourPoints, radius])   
  const marketClusters = useMemo(
    () => clusterPoints(map, market, radius,
      (p) => [p.lat as number, p.lon as number], (p) => p.id),
    [map, market, radius])

  return (
    <>
      {ourClusters.map((c) => {
        const one = c.items.length === 1 ? c.items[0] : null
        // Заливка — принадлежность, кольцо — выбранный разрез. Цвет при этом не
        // единственный носитель: то же состояние написано словами в подсказке.
        const ring = one ? ourColor(one, colorBy) : НАШ_ЦВЕТ
        // Точка, а не значок-капля: на крупном приближении станции стоят вплотную,
        // и значки перекрывают карту и друг друга — в городе от них не видно ни
        // улиц, ни чужих точек (замечание МАГа 13.09.2026).
        return (
          <CircleMarker key={c.key} center={[c.lat, c.lon]}
            radius={ТОЧКА_НАША}
            pathOptions={{ color: ring, fillColor: НАШ_ЦВЕТ, fillOpacity: 0.95,
                           weight: ring === НАШ_ЦВЕТ ? 1 : 2 }}>
            <Popup>
              {one ? (
                <OurPopupBody p={one} />
              ) : вОднойТочке(c.items) ? (
                <>
                  <b>{c.items.length} объектов по одному адресу</b> — приближение их
                  не разведёт:
                  <СписокОбъектов items={c.items.map((p) => ({
                    name: p.name,
                    note: p.status && p.status !== 'working' ? p.status : null,
                  }))} />
                </>
              ) : (
                <>
                  <b>{c.items.length} объектов</b> рядом — приблизьте, чтобы
                  увидеть каждый:
                  <СписокОбъектов items={c.items.map((p) => ({
                    name: p.name,
                    note: p.status && p.status !== 'working' ? p.status : null,
                  }))} />
                </>
              )}
            </Popup>
          </CircleMarker>
        )
      })}
      {marketClusters.map((c) => {
        const one = c.items.length === 1 ? c.items[0] : null
        const color = one ? siteColor(one) : '#ef4444'
        const age = one ? ageLabel(one.price?.observedOn ?? one.lastSeenAt) : null
        return (
          <CircleMarker key={c.key} center={[c.lat, c.lon]}
            radius={ТОЧКА_РЫНКА}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.85, weight: 0.5 }}>
            <Popup>
              {one ? (
                <>
                  <b>{one.name}</b>
                  {/* Наша же станция, увиденная снаружи. Без этой строки человек
                      видит на карте точку с адресом своего объекта и не понимает,
                      чья она: две записи об одном объекте выглядят как две
                      станции. */}
                  {one.isOurs && <> · <span style={{ color: НАШ_ЦВЕТ }}>наша станция, так её видит рынок</span></>}
                  <br />
                  {SITE_KIND_LABEL[one.kind]}{one.operatorName ? ` · ${one.operatorName}` : ''}<br />
                  {one.price?.value != null
                    ? <>цена {one.price.value} ₽{one.price.unit === 'kwh' ? '/кВтч' : ''} · {age?.text}</>
                    : <>цена не наблюдалась</>}
                </>
              ) : вОднойТочке(c.items as { lat: number; lon: number }[]) ? (
                <>
                  <b>{c.items.length} точек по одному адресу</b> — приближение их
                  не разведёт:
                  <СписокОбъектов items={c.items.map((p) => ({
                    name: p.name, note: p.operatorName,
                  }))} />
                </>
              ) : (
                <>
                  <b>{c.items.length} точек рынка</b> рядом — приблизьте, чтобы
                  увидеть каждую:
                  <СписокОбъектов items={c.items.map((p) => ({
                    name: p.name, note: p.operatorName,
                  }))} />
                </>
              )}
            </Popup>
          </CircleMarker>
        )
      })}
    </>
  )
}

/** Карта рынка: наши объекты и чужие точки на одном полотне. */
function MarketMap() {
  const dark = useIsDark()
  const { companyId } = useCompany()
  const [filters, setFilters] = useState<MarketFilters>(EMPTY_MARKET_FILTERS)
  const [our, setOur] = useState<OurFilters>(EMPTY_OUR_FILTERS)
  const [view, setView] = useState<{ bbox?: string; zoom: number }>({ zoom: 5 })
  const { sites, ours } = useMarketData(filters, view.bbox)
  const operators = useQuery({
    queryKey: ['market-operators', companyId],
    queryFn: () => listMarketOperators(companyId),
    enabled: !!companyId,
  })

  const allMarket = (sites.data?.sites ?? []).filter((s) => s.lat != null && s.lon != null)
  // Слои включаются флажками, а вид точки уже отобран на сервере: здесь остаётся
  // только скрыть выключенные слои.
  const market = allMarket.filter((s) => {
    // Наша станция, найденная во внешнем реестре, — это не рынок. Прежде она
    // попадала в слой сетей и красилась как конкурент: на карте рядом с нашим
    // объектом стояла «чужая» точка с тем же адресом, и понять, чья она, было
    // нельзя. Теперь это отдельный слой, выключенный по умолчанию.
    if (s.isOurs) return filters.showOursOnMarket
    if (s.kind !== 'ezs') return filters.showAttractors
    if (s.siteClass === 'home') return filters.showHome
    if (s.siteClass === 'independent') return filters.showIndependent
    return filters.showRivals
  })
  // Даже с отбором по области страница может не вместить всё: тогда об этом надо
  // сказать, а не молча показать половину (ревизия 12.09.2026, К10).
  const cut = (sites.data?.total ?? 0) > (sites.data?.returned ?? 0)
  // Наш слой отбирается по НАШИМ данным: состояние, скорость, производитель,
  // загрузка порта, доля срывов. Снаружи такого о станции не узнать.
  const ourPoints = useMemo(() => {
    if (!filters.showOurs) return []
    return (ours.data?.points ?? []).filter((p) => {
      if (our.status !== 'all' && p.status !== our.status) return false
      if (our.speedClass !== 'all' && p.speedClass !== our.speedClass) return false
      if (our.brand !== 'all' && p.brand !== our.brand) return false
      if (our.load !== 'all') {
        const v = p.sessionsPerPortDay
        if (v == null) return false
        if (our.load === 'idle' && v >= 0.3) return false
        if (our.load === 'low' && v >= 1) return false
        if (our.load === 'busy' && v < 2) return false
      }
      if (our.errors !== 'all') {
        const v = p.errorPct
        if (v == null) return false
        if (our.errors === 'bad' && v <= 30) return false
        if (our.errors === 'good' && v >= 10) return false
      }
      return true
    })
  }, [ours.data, filters.showOurs, our])

  const mapLayers = useMapLayers()
  // Карта страны в половине окна нечитаема: точки сливаются, а фильтры и счётчики
  // съедают вертикаль. Разворот — на всё окно, выход по Escape.
  const полный = useFullscreenPanel(undefined, { scroll: false })

  return (
    <div className={полный.className}>
      <MarketMapFilters
        filters={filters} onFilters={setFilters}
        our={our} onOur={setOur}
        operators={operators.data?.operators ?? []}
        brands={ours.data?.brands ?? []}
        statuses={ours.data?.statuses ?? []}
        counts={{
          ours: ourPoints.length,
          rivals: allMarket.filter((s) => !s.isOurs && s.kind === 'ezs'
            && s.siteClass === 'network').length,
          oursOnMarket: allMarket.filter((s) => s.isOurs).length,
          independent: allMarket.filter((s) => !s.isOurs && s.siteClass === 'independent').length,
          home: allMarket.filter((s) => s.siteClass === 'home').length,
          attractors: allMarket.filter((s) => s.kind !== 'ezs').length,
        }} />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">
          наших объектов: {ourPoints.length} · точек рынка в кадре: {market.length}
          {sites.isFetching && ' · обновляем…'}
          {cut && (
            <span className="text-warning">
              {' · '}в кадре {sites.data?.total}, показано {sites.data?.returned} —
              приблизьте карту
            </span>
          )}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {our.colorBy === 'status' ? 'наши по состоянию'
            : our.colorBy === 'load' ? 'наши по загрузке порта'
            : our.colorBy === 'errors' ? 'наши по доле срывов'
            : 'наши по выручке'}
        </span>
        <button type="button" onClick={полный.toggle}
          title={полный.on ? 'Вернуть в рабочую область (Escape)' : 'Развернуть карту на весь экран'}
          className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
          {полный.on
            ? <><Minimize2 className="size-3.5" aria-hidden /> Свернуть</>
            : <><Maximize2 className="size-3.5" aria-hidden /> Во весь экран</>}
        </button>
        <MarketSiteDialog trigger={
          <button type="button" className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
            <Plus className="size-3.5" /> Точка рынка
          </button>
        } />
      </div>

      <div className="relative isolate min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        <MapLayerSwitch {...mapLayers} />
        <MapContainer crs={MAP_CRS} attributionControl={false} center={[55.75, 37.6]} zoom={5} scrollWheelZoom preferCanvas
          style={{ height: '100%', width: '100%', background: 'hsl(var(--muted))' }}>
          <MapTiles base={mapLayers.base} traffic={mapLayers.traffic} regions={mapLayers.regions} dark={dark} />
          <MapResize trigger={полный.on} />
          <AttributionControl position="bottomright" prefix={MAP_ATTRIBUTION_PREFIX} />
          <ViewportWatch onChange={(bbox, zoom) => setView({ bbox, zoom })} />
          <MarketPoints market={market} ourPoints={ourPoints} zoom={view.zoom}
            colorBy={our.colorBy} />
        </MapContainer>
      </div>
    </div>
  )
}

/** Разрезы «Точек рынка»: список и три способа посмотреть на рынок целиком. */
const ВИДЫ_ТОЧЕК = [
  { k: 'list', label: 'Список' },
  { k: 'gear', label: 'Чем оснащены' },
  { k: 'live', label: 'Живы ли' },
  { k: 'who', label: 'Кто владеет' },
] as const

/** Строка разреза: доля считается от всех точек выборки, а не от видимой страницы. */
function РазрезСтрока({ row, total }: {
  row: { name: string; sites: number; alive: number; medianPrice: number | null
         pricedSites: number }
  total: number
}) {
  const share = total ? (row.sites / total) * 100 : 0
  return (
    <tr className="border-t border-border/50">
      <td className="p-2">{row.name}</td>
      <td className="p-2 text-right tabular-nums">{nfm.format(row.sites)}</td>
      <td className="p-2 text-right tabular-nums text-muted-foreground">
        {nf1m.format(share)} %
      </td>
      <td className="p-2 text-right tabular-nums">{nfm.format(row.alive)}</td>
      <td className="p-2 text-right">
        {row.medianPrice != null ? (
          <span className="tabular-nums">
            {nf1m.format(row.medianPrice)}
            <span className="ml-1 text-muted-foreground">по {row.pricedSites}</span>
          </span>
        ) : <span className="text-muted-foreground">нет цен</span>}
      </td>
    </tr>
  )
}

function BreakdownTable({ rows, total, first }: {
  rows: { name: string; sites: number; alive: number; medianPrice: number | null
          pricedSites: number }[]
  total: number
  first: string
}) {
  // Разрез читают с двух сторон: «кого больше» и «у кого дороже». Порядок с сервера
  // отвечает только на первый вопрос.
  const карта = useMemo(() => ({
    name: (r: typeof rows[number]) => r.name,
    sites: (r: typeof rows[number]) => r.sites,
    alive: (r: typeof rows[number]) => r.alive,
    price: (r: typeof rows[number]) => r.medianPrice,
    priced: (r: typeof rows[number]) => r.pricedSites,
  }), [])
  const { rows: строки, sort, toggle } = useTableSort(rows, карта)
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-xs"
        {...exportRows(first, [
          first, 'Точек', 'Доля, %', 'Живых', 'Медиана цены, ₽/кВт·ч', 'Точек с ценой',
        ], строки.map((r) => [
          r.name, r.sites, total > 0 ? (r.sites / total) * 100 : null, r.alive,
          r.medianPrice, r.pricedSites,
        ]))}>
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <SortTh sortKey="name" sort={sort} onSort={toggle}>{first}</SortTh>
            <SortTh sortKey="sites" sort={sort} onSort={toggle} align="right">Точек</SortTh>
            <th className="p-2 text-right font-medium">Доля</th>
            <SortTh sortKey="alive" sort={sort} onSort={toggle} align="right">Живых</SortTh>
            <SortTh sortKey="price" sort={sort} onSort={toggle} align="right">Медиана цены</SortTh>
          </tr>
        </thead>
        <tbody>
          {строки.map((r) => <РазрезСтрока key={r.name} row={r} total={total} />)}
        </tbody>
      </table>
    </div>
  )
}

const nfm = new Intl.NumberFormat('ru-RU')
const nf1m = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

/** Реестр точек рынка: что известно и насколько это свежо. */
function MarketSites() {
  const { companyId, company } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const [вид, setВид] = useState<string>('list')
  // Карточка станции: полсотни полей парсера в списке не помещаются, а решение
  // «сравнивать ли с этой точкой» принимается именно по ним.
  const [открыта, setОткрыта] = useState<MarketSite | null>(null)
  const мы = company.shortName || company.name || 'наш'
  const [kind, setKind] = useState('all')
  const [q, setQ] = useState('')
  // Ищет сервер, а не браузер. Прежде список брал первую страницу в 5 000 строк и
  // фильтровал её у себя: из 9 118 точек 4 118 не существовали для поиска, и на
  // запрос о реальной точке экран отвечал «ничего не найдено» (аудит А10).
  const [запрос, setЗапрос] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setЗапрос(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])
  const [страниц, setСтраниц] = useState(1)
  const PAGE = 500
  // Сброс на первую страницу при смене условий делается ПРИ ОТРИСОВКЕ, а не в
  // эффекте: эффект вызывал вторую отрисовку следом за первой, и список успевал
  // мигнуть старой выдачей.
  const условия = `${запрос}|${kind}`
  const [прежние, setПрежние] = useState(условия)
  if (условия !== прежние) {
    setПрежние(условия)
    setСтраниц(1)
  }

  const разрез = useQuery({
    queryKey: ['market-breakdown', companyId],
    queryFn: () => getSitesBreakdown(companyId),
    enabled: !!companyId && вид !== 'list',
  })

  const sites = useQuery({
    queryKey: ['market-sites-list', companyId, kind, запрос, страниц],
    queryFn: () => listMarketSites(companyId, {
      ...(kind === 'all' ? {} : { kind }),
      ...(запрос ? { search: запрос } : {}),
      limit: PAGE * страниц,
    }),
    enabled: !!companyId,
    placeholderData: (prev) => prev,
  })
  // Реестр в девять тысяч строк без сортировки читать нельзя: вопросы к нему —
  // «где дороже», «где больше портов», «что давно не проверяли» (замечание
  // РусГидро 14.09.2026).
  const сортировка = useMemo(() => ({
    name: (s: MarketSite) => s.name,
    owner: (s: MarketSite) => s.ownerName,
    operator: (s: MarketSite) => s.operatorName,
    city: (s: MarketSite) => s.city,
    ports: (s: MarketSite) => s.ports,
    price: (s: MarketSite) => s.price?.value ?? null,
    checked: (s: MarketSite) => s.price?.observedOn ?? s.lastSeenAt,
  }), [])
  const { rows, sort, toggle } = useTableSort(sites.data?.sites ?? [], сортировка)
  // Разрез по разъёмам — своя таблица со своим порядком: «каких больше» и «какие
  // мощнее» это разные вопросы.
  const карта_разъёмов = useMemo(() => ({
    name: (c: { name: string }) => c.name,
    count: (c: { count: number }) => c.count,
    power: (c: { medianPowerKw: number | null }) => c.medianPowerKw,
    withPower: (c: { withPower: number }) => c.withPower,
  }), [])
  const разъёмы = useTableSort(разрез.data?.byConnector ?? [], карта_разъёмов)
  const всего = sites.data?.total ?? 0
  const ещё = Math.max(0, всего - rows.length)

  if (открыта) {
    return <MarketSiteCard site={открыта} onBack={() => setОткрыта(null)} />
  }

  if (sites.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Загружаем точки рынка</span>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-9 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  return (
    <div ref={экран} className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2" data-export-ignore>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Название или город"
          className="h-8 w-[240px] text-xs" />
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все виды</SelectItem>
            {Object.entries(SITE_KIND_LABEL).map(([k, label]) => (
              <SelectItem key={k} value={k}>{label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {rows.length === всего
            ? `${всего.toLocaleString('ru-RU')} точек`
            : `${rows.length.toLocaleString('ru-RU')} из ${всего.toLocaleString('ru-RU')}`}
          {запрос && ` по запросу «${запрос}»`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {/* Выгружается загруженная часть списка: постранично докачанное и есть то,
              что человек видит. Сколько именно — сказано в подписи книги. */}
          <ExportButton title="Точки рынка"
            subtitle={`${вид === 'list' ? `${rows.length} из ${всего} точек` : 'разрез по всем точкам'}`
              + `${запрос ? ` · запрос «${запрос}»` : ''}`}
            getEl={() => экран.current} />
          <MarketObservationDialog sites={sites.data?.sites ?? []} trigger={
            <button type="button" className="rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
              Наблюдение
            </button>
          } />
          <MarketOcmButton />
          <MarketImportDialog trigger={
            <button type="button" className="rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
              Импорт списком
            </button>
          } />
          <MarketSiteDialog trigger={
            <button type="button" className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
              <Plus className="size-3.5" /> Точка рынка
            </button>
          } />
        </div>
      </div>

      <PanelViewTabs tabs={ВИДЫ_ТОЧЕК} value={вид} onChange={setВид} />

      {вид !== 'list' && (
        разрез.isLoading ? (
          <div className="space-y-2" aria-busy="true">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Считаем разрез по всем точкам рынка, а не по видимой странице.
            </div>
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-16 animate-pulse rounded-lg border border-border bg-muted/40" />
            ))}
          </div>
        ) : !разрез.data || разрез.data.total === 0 ? (
          <Card><CardContent className="p-6 text-sm text-muted-foreground">
            {разрез.data?.message ?? 'Разрез посчитать не на чем.'}
          </CardContent></Card>
        ) : (
          <div className="min-h-0 flex-1 space-y-3 overflow-auto">
            <Card>
              <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3 text-sm">
                <span className="font-medium">
                  {nfm.format(разрез.data.total)} точек рынка в разрезе
                </span>
                <span className="text-xs text-muted-foreground">
                  домашних розеток {nfm.format(разрез.data.homeSockets)} — в рынок не
                  входят; живых за {разрез.data.quality.aliveDays} дней{' '}
                  {nfm.format(разрез.data.quality.alive)}
                </span>
              </CardContent>
            </Card>

            {вид === 'gear' && (
              <>
                <BreakdownTable rows={разрез.data.byPower} total={разрез.data.total}
                  first="Мощность" />
                <BreakdownTable rows={разрез.data.byCurrent} total={разрез.data.total}
                  first="Тип тока" />
                <div className="overflow-hidden rounded-lg border border-border">
                  <table className="w-full text-xs"
                    {...exportRows('Разъёмы', [
                      'Разъём', 'Сколько их', 'Медиана мощности, кВт', 'Мощность известна у',
                    ], разрез.data.byConnector.map((c) => [
                      c.name, c.count, c.medianPowerKw, c.withPower,
                    ]))}>
                    <thead className="bg-muted/50 text-muted-foreground">
                      <tr>
                        <SortTh sortKey="name" sort={разъёмы.sort} onSort={разъёмы.toggle}>Разъём</SortTh>
                        <SortTh sortKey="count" sort={разъёмы.sort} onSort={разъёмы.toggle} align="right">Сколько их</SortTh>
                        <SortTh sortKey="power" sort={разъёмы.sort} onSort={разъёмы.toggle} align="right">Медиана мощности</SortTh>
                        <SortTh sortKey="withPower" sort={разъёмы.sort} onSort={разъёмы.toggle} align="right">Известна у</SortTh>
                      </tr>
                    </thead>
                    <tbody>
                      {разъёмы.rows.map((c) => (
                        <tr key={c.name} className="border-t border-border/50">
                          <td className="p-2">{c.name}</td>
                          <td className="p-2 text-right tabular-nums">{nfm.format(c.count)}</td>
                          <td className="p-2 text-right tabular-nums">
                            {c.medianPowerKw != null
                              ? `${nf1m.format(c.medianPowerKw)} кВт`
                              : <span className="text-muted-foreground">нет данных</span>}
                          </td>
                          <td className="p-2 text-right tabular-nums text-muted-foreground">
                            {nfm.format(c.withPower)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="p-2 text-xs text-muted-foreground">
                    Тип разъёма решает, подъедет ли сюда машина вообще: с CCS не
                    зарядиться от GB/T, сколько бы киловатт там ни было.
                  </p>
                </div>
              </>
            )}

            {вид === 'live' && (
              <Card>
                <CardContent className="space-y-3 p-4">
                  {/* Показатели живости нарисованы плитками; в книгу они уходят
                      строками — вместе с покрытием, без которого медиана врёт. */}
                  <table hidden {...exportRows('Живы ли', [
                    'Показатель', 'Значение', 'Посчитано по точкам',
                  ], [
                    [`заряжали за ${разрез.data.quality.aliveDays} дней`, разрез.data.quality.alive, null],
                    ['зарядок не видели ни разу', разрез.data.quality.neverSeenCharging, null],
                    ['закрытие подтверждали', разрез.data.quality.closedConfirmed, null],
                    ['владелец не назван', разрез.data.quality.withoutOperator, null],
                    ['связь за сутки, медиана %', разрез.data.quality.medianQuality,
                     разрез.data.quality.qualityCoverage],
                    ['успешных зарядок, медиана %', разрез.data.quality.medianSuccess,
                     разрез.data.quality.successCoverage],
                    ['оценка, медиана', разрез.data.quality.medianRating,
                     разрез.data.quality.ratingCoverage],
                  ])} />
                  <div className="grid gap-x-6 gap-y-3 md:grid-cols-3 xl:grid-cols-4">
                    <div>
                      <div className="text-xs text-muted-foreground">
                        заряжали за {разрез.data.quality.aliveDays} дней
                      </div>
                      <div className="font-headline text-lg tabular-nums">
                        {nfm.format(разрез.data.quality.alive)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">зарядок не видели ни разу</div>
                      <div className="font-headline text-lg tabular-nums text-warning">
                        {nfm.format(разрез.data.quality.neverSeenCharging)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">закрытие подтверждали</div>
                      <div className="font-headline text-lg tabular-nums">
                        {nfm.format(разрез.data.quality.closedConfirmed)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">владелец не назван</div>
                      <div className="font-headline text-lg tabular-nums">
                        {nfm.format(разрез.data.quality.withoutOperator)}
                      </div>
                    </div>
                  </div>
                  <div className="grid gap-x-6 gap-y-3 border-t border-border/60 pt-3 md:grid-cols-3">
                    {/* Медиана без покрытия — это медиана неизвестно чего: у трети
                        точек этих полей нет вовсе. */}
                    <div>
                      <div className="text-xs text-muted-foreground">связь за сутки, медиана</div>
                      <div className="text-sm">
                        {разрез.data.quality.medianQuality != null
                          ? <>{nf1m.format(разрез.data.quality.medianQuality)} %
                              <span className="text-muted-foreground">
                                {' '}по {nfm.format(разрез.data.quality.qualityCoverage)} точкам
                              </span></>
                          : <span className="text-muted-foreground">нет данных</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">успешных зарядок, медиана</div>
                      <div className="text-sm">
                        {разрез.data.quality.medianSuccess != null
                          ? <>{nf1m.format(разрез.data.quality.medianSuccess)} %
                              <span className="text-muted-foreground">
                                {' '}по {nfm.format(разрез.data.quality.successCoverage)} точкам
                              </span></>
                          : <span className="text-muted-foreground">нет данных</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">оценка, медиана</div>
                      <div className="text-sm">
                        {разрез.data.quality.medianRating != null
                          ? <>{nf1m.format(разрез.data.quality.medianRating)}
                              <span className="text-muted-foreground">
                                {' '}по {nfm.format(разрез.data.quality.ratingCoverage)} точкам
                              </span></>
                          : <span className="text-muted-foreground">нет данных</span>}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {вид === 'who' && (
              <>
                <BreakdownTable rows={разрез.data.byClass} total={разрез.data.total}
                  first="Класс точки" />
                <BreakdownTable rows={разрез.data.byOperator} total={разрез.data.total}
                  first="Оператор" />
                <BreakdownTable rows={разрез.data.byRegion} total={разрез.data.total}
                  first="Регион" />
              </>
            )}

            <Card><CardContent className="p-3 text-xs text-muted-foreground">
              {разрез.data.note}
            </CardContent></Card>
          </div>
        )
      )}

      {вид === 'list' && (rows.length === 0 ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          {запрос || kind !== 'all' ? (
            <>
              По этим условиям ничего не нашлось. Это ответ о запросе, а не о
              рынке: в базе точки есть — измените запрос или вид.
              <div className="mt-3">
                <button type="button" onClick={() => { setQ(''); setKind('all') }}
                  className="rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
                  Сбросить условия
                </button>
              </div>
            </>
          ) : (
            <>Точек рынка пока нет. Добавьте первую — чужую станцию рядом с нашей,
            торговый центр или парковку: карта «наши против чужих» начинается с одной
            записи.</>
          )}
        </CardContent></Card>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Точки рынка', [
              'Точка', 'Наша', 'Вид', 'Владелец', 'Эксплуатирует', 'Город', 'Адрес',
              'Портов', 'Цена, ₽', 'Основание цены', 'Проверено', 'Снимков', 'Дубль',
            ], rows.map((s) => [
              s.name, s.isOurs ? мы : null, SITE_KIND_LABEL[s.kind as MarketSiteKind],
              s.ownerName, s.operatorName, s.city, s.address, s.ports, s.price?.value ?? null,
              s.price?.basis ?? null, s.price?.observedOn ?? s.lastSeenAt ?? null,
              s.photoCount ?? 0, s.duplicateOfId ? 'та же станция заведена другой записью' : null,
            ]))}>
            <thead className="sticky top-0 bg-muted/60 text-muted-foreground">
              <tr>
                <SortTh sortKey="name" sort={sort} onSort={toggle}>Точка</SortTh>
                <th className="p-2 text-left font-medium">Вид</th>
                {/* Владелец и эксплуатант — разные компании чаще, чем кажется:
                    станции под именем платформы принадлежат не ей. */}
                <SortTh sortKey="owner" sort={sort} onSort={toggle}>Владелец</SortTh>
                <SortTh sortKey="operator" sort={sort} onSort={toggle}>Эксплуатирует</SortTh>
                <SortTh sortKey="city" sort={sort} onSort={toggle}>Город</SortTh>
                <SortTh sortKey="ports" sort={sort} onSort={toggle} align="right">Порты</SortTh>
                <SortTh sortKey="price" sort={sort} onSort={toggle} align="right">Цена</SortTh>
                <SortTh sortKey="checked" sort={sort} onSort={toggle}>Проверено</SortTh>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const age = ageLabel(s.price?.observedOn ?? s.lastSeenAt)
                return (
                  <tr key={s.id}
                    className="cursor-pointer border-t border-border/60 hover:bg-accent/30"
                    onClick={() => setОткрыта(s)} tabIndex={0} role="button"
                    onKeyDown={(e) => e.key === 'Enter' && setОткрыта(s)}>
                    <td className="p-2">
                      <span className="font-medium text-foreground underline decoration-dotted underline-offset-2">
                        {s.name}
                      </span>
                      {/* Имя компании, а не слово «наш»: в соседней колонке у той
                          же строки стоит оператор «РусГидро», и две подписи об
                          одном объекте сбивают. */}
                      {s.isOurs && (
                        <span className="ml-2 rounded border border-primary/40 px-1 text-xs text-primary">
                          {мы}
                        </span>
                      )}
                      {s.address && <div className="text-xs text-muted-foreground">{s.address}</div>}
                      {(s.photoCount ?? 0) > 0 && (
                        <div className="text-xs text-muted-foreground">
                          снимков {s.photoCount}
                        </div>
                      )}
                    </td>
                    <td className="p-2 text-muted-foreground">{SITE_KIND_LABEL[s.kind as MarketSiteKind]}</td>
                    <td className="p-2 text-muted-foreground">
                      {s.ownerName ?? '—'}
                      {/* Владелец, унаследованный от эксплуатанта, — предположение,
                          а не факт: пока его не подтвердили, так и написано. */}
                      {s.ownerName && !s.ownerChecked && (
                        <span className="ml-1 text-xs">· не подтверждён</span>
                      )}
                    </td>
                    <td className="p-2 text-muted-foreground">{s.operatorName ?? '—'}</td>
                    <td className="p-2 text-muted-foreground">{s.city ?? '—'}</td>
                    <td className="p-2 text-right tabular-nums">{s.ports ?? '—'}</td>
                    <td className="p-2 text-right tabular-nums">
                      {s.price?.value ? `${s.price.value} ₽` : '—'}
                      {s.price?.basis && <div className="text-xs text-muted-foreground">{s.price.basis}</div>}
                    </td>
                    <td className={`p-2 ${age.stale ? 'text-warning' : 'text-muted-foreground'}`}>{age.text}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {ещё > 0 && (
            <div className="border-t border-border p-2 text-center">
              <button type="button" onClick={() => setСтраниц((n) => n + 1)}
                disabled={sites.isFetching}
                className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-60">
                {sites.isFetching ? 'Загружаем…' : `Показать ещё (осталось ${ещё.toLocaleString('ru-RU')})`}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/** Лента наблюдений — откуда мы знаем то, что показываем. */
function MarketObservations() {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['market-observations', companyId],
    queryFn: () => listMarketObservations(companyId),
    enabled: !!companyId,
  })
  // Лента наблюдений читается и как журнал (что свежее), и как разрез по точке или
  // автору: «кто давно не ездил» и «где цену давно не снимали».
  const карта = useMemo(() => ({
    date: (o: MarketObservation) => o.observedOn,
    site: (o: MarketObservation) => o.siteName ?? null,
    kind: (o: MarketObservation) => o.kind,
    price: (o: MarketObservation) => o.price,
    channel: (o: MarketObservation) => o.channel,
    author: (o: MarketObservation) => o.author ?? null,
  }), [])
  const { rows, sort, toggle } = useTableSort(
    q.data?.observations ?? [], карта, { key: 'date', dir: 'desc' })
  return (
    <div ref={экран} className="h-full overflow-auto p-4">
      {rows.length > 0 && (
        <div className="mb-2 flex justify-end" data-export-ignore>
          <ExportButton title="Наблюдения" subtitle={`${rows.length} записей`}
            getEl={() => экран.current} />
        </div>
      )}
      {rows.length === 0 ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          Наблюдений пока нет. Наблюдение — это факт с датой и автором: заезд сервиса,
          снимок ценника, ответ партнёра. Без него цифра на карте не значит ничего.
        </CardContent></Card>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-xs"
            {...exportRows('Наблюдения', [
              'Дата', 'Точка', 'Что наблюдали', 'Основание', 'Цена, ₽', 'Канал', 'Автор',
            ], rows.map((o) => [
              o.observedOn, o.siteName,
              o.kind === 'price' ? 'цена' : o.kind === 'availability' ? 'доступность'
                : o.kind === 'closed' ? 'закрыта' : o.kind === 'opened' ? 'открылась' : o.kind,
              o.basis, o.price, CHANNEL_LABEL[o.channel] ?? o.channel, o.author,
            ]))}>
            <thead className="bg-muted/60 text-muted-foreground">
              <tr>
                <SortTh sortKey="date" sort={sort} onSort={toggle}>Дата</SortTh>
                <SortTh sortKey="site" sort={sort} onSort={toggle}>Точка</SortTh>
                <SortTh sortKey="kind" sort={sort} onSort={toggle}>Что наблюдали</SortTh>
                <SortTh sortKey="price" sort={sort} onSort={toggle} align="right">Цена</SortTh>
                <SortTh sortKey="channel" sort={sort} onSort={toggle}>Канал</SortTh>
                <SortTh sortKey="author" sort={sort} onSort={toggle}>Автор</SortTh>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.id} className="border-t border-border/60">
                  <td className="p-2 tabular-nums">{o.observedOn}</td>
                  <td className="p-2">{o.siteName ?? '—'}</td>
                  <td className="p-2 text-muted-foreground">
                    {o.kind === 'price' ? 'цена' : o.kind === 'availability' ? 'доступность'
                      : o.kind === 'closed' ? 'закрыта' : o.kind === 'opened' ? 'открылась' : o.kind}
                    {o.basis && <span className="ml-1 text-muted-foreground">({o.basis})</span>}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {o.price != null ? `${o.price} ₽` : '—'}
                  </td>
                  <td className="p-2 text-muted-foreground">{CHANNEL_LABEL[o.channel] ?? o.channel}</td>
                  <td className="p-2 text-muted-foreground">{o.author ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Тонкий роутер продукта: пункт меню → панель (как в «Продажах»). */
export function MarketRouter({ tab }: { tab: string }) {
  switch (tab) {
    case 'mk_position': return <MarketPositionPanel />
    case 'mk_map': return <MarketMap />
    case 'mk_sites': return <MarketSites />
    case 'mk_landscape2': return <MarketLandscapePanel />
    case 'mk_players': return <MarketPlayersPanel />
    case 'mk_observations': return <MarketObservations />
    case 'mk_sources': return <MarketSourcesPanel />
    case 'mk_coverage': return <MarketCoveragePanel />
    case 'mk_territories': return <MarketTerritoriesPanel />
    case 'mk_whitespots': return <MarketWhitespotsPanel />
    case 'mk_score': return <MarketSiteScorePanel />
    case 'mk_landscape': return <MarketPriceLandscapePanel />
    case 'mk_pressure': return <MarketPressurePanel />
    case 'mk_elasticity': return <MarketElasticityPanel />
    case 'mk_scenarios': return <MarketScenariosPanel />
    case 'mk_partners': return <MarketPartnersPanel />
    case 'mk_growth': return <MarketGrowthPanel />
    case 'mk_leads': return <MarketLeadsPanel />
    default: return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
        <MapPin className="mr-2 size-4" /> Выберите раздел рынка
      </div>
    )
  }
}
