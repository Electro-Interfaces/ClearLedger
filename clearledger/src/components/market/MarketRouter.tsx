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
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, CircleMarker, Popup, AttributionControl, useMap,
  useMapEvents } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import { clusterPoints, clusterRadiusForZoom } from '@/components/map/clusterPoints'
import 'leaflet/dist/leaflet.css'
import { Loader2, MapPin, Plus } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  listMarketSites, listMarketObservations, listMarketOperators, getOurMapPoints,
  SITE_KIND_LABEL, CHANNEL_LABEL, type MarketSite, type MarketSiteKind,
  type OurMapPoint,
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

/** Цвет нашей станции — по выбранному показателю: состояние, загрузка, срывы, деньги.
 *  Один слой отвечает на разные вопросы, не превращаясь в четыре карты. */
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
  if (s.isOurs) return '#3b82f6'
  if (s.kind !== 'ezs') return '#94a3b8'
  // Независимая точка — не сеть: другой цвет, чтобы плотность рынка не выглядела
  // плотностью сетей (полная выгрузка 13.09.2026).
  if (s.siteClass === 'independent') return '#f59e0b'
  if (s.siteClass === 'home') return '#a78bfa'
  return '#ef4444'
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
    [map, ourPoints, radius])  // eslint-disable-line react-hooks/exhaustive-deps
  const marketClusters = useMemo(
    () => clusterPoints(map, market, radius,
      (p) => [p.lat as number, p.lon as number], (p) => p.id),
    [map, market, radius])

  return (
    <>
      {ourClusters.map((c) => {
        const one = c.items.length === 1 ? c.items[0] : null
        const color = one ? ourColor(one, colorBy) : '#3b82f6'
        return (
          <CircleMarker key={c.key} center={[c.lat, c.lon]}
            radius={one ? 6 : Math.min(16, 6 + Math.log2(c.items.length) * 2.5)}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.9, weight: 1.5 }}>
            <Popup>
              {one ? (
                <>
                  <b>{one.name}</b> · наш объект<br />
                  {one.city ?? ''}{one.brand ? ` · ${one.brand}` : ''}
                  {one.powerKwt ? ` · ${one.powerKwt} кВт` : ''}
                  {one.ports ? ` · ${one.ports} портов` : ''}<br />
                  сессий за 90 дней: {one.sessions}
                  {one.sessionsPerPortDay != null && ` · ${one.sessionsPerPortDay} на порт в сутки`}<br />
                  {one.errorPct != null ? `срывов ${one.errorPct} %` : 'срывы не считаны'}
                  {one.status ? ` · ${one.status}` : ''}
                </>
              ) : (
                <><b>{c.items.length} наших объектов</b><br />приблизьте, чтобы разделить</>
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
            radius={one ? 5 : Math.min(18, 6 + Math.log2(c.items.length) * 2.5)}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.8, weight: 1 }}>
            <Popup>
              {one ? (
                <>
                  <b>{one.name}</b><br />
                  {SITE_KIND_LABEL[one.kind]}{one.operatorName ? ` · ${one.operatorName}` : ''}<br />
                  {one.price?.value != null
                    ? <>цена {one.price.value} ₽{one.price.unit === 'kwh' ? '/кВтч' : ''} · {age?.text}</>
                    : <>цена не наблюдалась</>}
                </>
              ) : (
                <><b>{c.items.length} точек рынка</b><br />приблизьте, чтобы разделить</>
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <MarketMapFilters
        filters={filters} onFilters={setFilters}
        our={our} onOur={setOur}
        operators={operators.data?.operators ?? []}
        brands={ours.data?.brands ?? []}
        statuses={ours.data?.statuses ?? []}
        counts={{
          ours: ourPoints.length,
          rivals: allMarket.filter((s) => s.kind === 'ezs' && s.siteClass === 'network').length,
          independent: allMarket.filter((s) => s.siteClass === 'independent').length,
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
          <AttributionControl position="bottomright" prefix={MAP_ATTRIBUTION_PREFIX} />
          <ViewportWatch onChange={(bbox, zoom) => setView({ bbox, zoom })} />
          <MarketPoints market={market} ourPoints={ourPoints} zoom={view.zoom}
            colorBy={our.colorBy} />
        </MapContainer>
      </div>
    </div>
  )
}

/** Реестр точек рынка: что известно и насколько это свежо. */
function MarketSites() {
  const [kind, setKind] = useState('all')
  const [q, setQ] = useState('')
  const { sites } = useMarketData({ ...EMPTY_MARKET_FILTERS, kind })
  const rows = (sites.data?.sites ?? []).filter((s) =>
    !q || s.name.toLowerCase().includes(q.toLowerCase())
    || (s.city ?? '').toLowerCase().includes(q.toLowerCase()))

  if (sites.isLoading) {
    return <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> Загрузка…
    </div>
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
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
        <span className="text-xs text-muted-foreground">{rows.length} точек</span>
        <div className="ml-auto flex items-center gap-2">
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

      {rows.length === 0 ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          Точек рынка пока нет. Добавьте первую — чужую станцию рядом с нашей, торговый
          центр или парковку: карта «наши против чужих» начинается с одной записи.
        </CardContent></Card>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="p-2 text-left font-medium">Точка</th>
                <th className="p-2 text-left font-medium">Вид</th>
                <th className="p-2 text-left font-medium">Оператор</th>
                <th className="p-2 text-left font-medium">Город</th>
                <th className="p-2 text-right font-medium">Порты</th>
                <th className="p-2 text-right font-medium">Цена</th>
                <th className="p-2 text-left font-medium">Проверено</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const age = ageLabel(s.price?.observedOn ?? s.lastSeenAt)
                return (
                  <tr key={s.id} className="border-t border-border/60 hover:bg-accent/30">
                    <td className="p-2">
                      <span className="font-medium text-foreground">{s.name}</span>
                      {s.isOurs && <span className="ml-2 rounded border border-primary/40 px-1 text-xs text-primary">наш</span>}
                      {s.address && <div className="text-xs text-muted-foreground">{s.address}</div>}
                    </td>
                    <td className="p-2 text-muted-foreground">{SITE_KIND_LABEL[s.kind as MarketSiteKind]}</td>
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
        </div>
      )}
    </div>
  )
}

/** Лента наблюдений — откуда мы знаем то, что показываем. */
function MarketObservations() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['market-observations', companyId],
    queryFn: () => listMarketObservations(companyId),
    enabled: !!companyId,
  })
  const rows = q.data?.observations ?? []
  return (
    <div className="h-full overflow-auto p-4">
      {rows.length === 0 ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          Наблюдений пока нет. Наблюдение — это факт с датой и автором: заезд сервиса,
          снимок ценника, ответ партнёра. Без него цифра на карте не значит ничего.
        </CardContent></Card>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/60 text-muted-foreground">
              <tr>
                <th className="p-2 text-left font-medium">Дата</th>
                <th className="p-2 text-left font-medium">Точка</th>
                <th className="p-2 text-left font-medium">Что наблюдали</th>
                <th className="p-2 text-right font-medium">Цена</th>
                <th className="p-2 text-left font-medium">Канал</th>
                <th className="p-2 text-left font-medium">Автор</th>
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
