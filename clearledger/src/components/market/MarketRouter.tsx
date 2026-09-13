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
import { MapContainer, AttributionControl, useMap,
  useMapEvents } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import { MarketMapPoints } from './MarketMapPoints'
import { ageLabel } from './marketMapPresentation'
import 'leaflet/dist/leaflet.css'
import { MapPin, Plus } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  listMarketSites, listMarketObservations, listMarketOperators, getOurMapPoints,
  SITE_KIND_LABEL, CHANNEL_LABEL, type MarketSiteKind,
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

async function loadMapSites(companyId: string, params: Parameters<typeof listMarketSites>[1], signal: AbortSignal) {
  const first = await listMarketSites(companyId, params)
  signal.throwIfAborted()
  const points = new Map(first.sites.map((site) => [site.id, site]))
  let offset = first.sites.length
  while (offset < first.total) {
    signal.throwIfAborted()
    const page = await listMarketSites(companyId, { ...params, offset })
    signal.throwIfAborted()
    if (!page.sites.length) break
    const previous = points.size
    for (const site of page.sites) points.set(site.id, site)
    offset += page.sites.length
    if (points.size === previous) break
  }
  return { ...first, sites: [...points.values()], returned: points.size }
}

function useMarketData(filters: MarketFilters, bbox?: string) {
  const { companyId } = useCompany()
  const sites = useQuery({
    // Точки грузятся по ВИДИМОЙ ОБЛАСТИ и отобранные на сервере: всей страной их
    // девять тысяч, и одна страница выдачи их не вмещает (ревизия 12.09.2026, К10).
    queryKey: ['market-sites', companyId, bbox ?? 'all', filters.kind,
               filters.operatorId, filters.currentType, filters.minPower, filters.alive],
    queryFn: ({ signal }) => loadMapSites(companyId, {
      ...(filters.kind === 'all' ? {} : { kind: filters.kind }),
      ...(filters.operatorId === 'all' ? {} : { operator_id: filters.operatorId }),
      ...(filters.currentType === 'all' ? {} : { current_type: filters.currentType }),
      ...(filters.minPower === 'all' ? {} : { min_power: Number(filters.minPower) }),
      ...(filters.alive === 'all' ? {} : { alive: filters.alive }),
      ...(bbox ? { bbox } : {}),
      limit: 5000,
    }, signal),
    enabled: !!companyId && !!bbox,
    placeholderData: (prev, query) => query?.queryKey[1] === companyId ? prev : undefined,
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
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map])
  return null
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

  const allMarket = useMemo(() => (sites.data?.sites ?? []).filter((s) => s.lat != null && s.lon != null), [sites.data])
  // Слои включаются флажками, а вид точки уже отобран на сервере: здесь остаётся
  // только скрыть выключенные слои.
  const market = useMemo(() => allMarket.filter((s) => {
    if (s.kind !== 'ezs') return filters.showAttractors
    if (s.siteClass === 'home') return filters.showHome
    if (s.siteClass === 'independent') return filters.showIndependent
    return filters.showRivals
  }), [allMarket, filters.showAttractors, filters.showHome, filters.showIndependent, filters.showRivals])
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
    <div className="market-map-surface flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-4">
      <details className="market-map-filters">
        <summary>Слои и фильтры карты
          <span className="text-muted-foreground"> · слоёв: {[filters.showOurs, filters.showRivals,
            filters.showIndependent, filters.showHome, filters.showAttractors].filter(Boolean).length}
            {' · '}отборов: {[filters.kind, filters.operatorId, filters.currentType, filters.minPower,
              filters.alive, our.status, our.speedClass, our.brand, our.load, our.errors].filter((v) => v !== 'all').length}</span>
        </summary>
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
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">
          наших объектов в сети: {ourPoints.length} · точек рынка в кадре: {market.length}
          <span className="inline-block min-w-[100px]" aria-live="polite">{(sites.isFetching || ours.isFetching) ? ' · обновляем…' : ' '}</span>
          {cut && (
            <span className="text-warning">
              {' · '}в кадре {sites.data?.total}, показано {sites.data?.returned} —
              приблизьте карту
            </span>
          )}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {our.colorBy === 'status' ? 'цвет наших точек: состояние'
            : our.colorBy === 'load' ? 'цвет наших точек: загрузка порта'
            : our.colorBy === 'errors' ? 'цвет наших точек: доля срывов'
            : 'цвет наших точек: выручка'}
        </span>
        <MarketSiteDialog trigger={
          <button type="button" className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
            <Plus className="size-3.5" /> Точка рынка
          </button>
        } />
      </div>

      <div className="market-map-legend" aria-label="Обозначения карты">
        <span><i className="market-point-symbol market-point-symbol-ours" aria-hidden="true" /> Наш объект</span>
        <span><i className="market-point-symbol" aria-hidden="true" /> Точка рынка</span>
        <span>Число — точек в группе; синий счётчик — наших</span>
      </div>
      <MapLayerSwitch {...mapLayers} className="market-map-layer-switch" />
      <div className="market-map-canvas relative isolate flex-1 overflow-hidden rounded-lg border border-border">
        <MapContainer crs={MAP_CRS} attributionControl={false} center={[55.75, 37.6]} zoom={5} scrollWheelZoom preferCanvas
          style={{ height: '100%', width: '100%', background: 'hsl(var(--muted))' }}>
          <MapTiles base={mapLayers.base} traffic={mapLayers.traffic} regions={mapLayers.regions} dark={dark} />
          <AttributionControl position="bottomright" prefix={MAP_ATTRIBUTION_PREFIX} />
          <ViewportWatch onChange={(bbox, zoom) => setView((previous) => previous.bbox === bbox && previous.zoom === zoom ? previous : { bbox, zoom })} />
          <MarketMapPoints key={companyId} market={market} ourPoints={ourPoints} zoom={view.zoom}
            colorBy={our.colorBy} />
        </MapContainer>
      {(sites.isError || ours.isError) && <div role="alert" className="market-map-message flex flex-wrap items-center gap-2 text-destructive">
        {sites.isError ? 'Не удалось загрузить точки рынка. ' : ''}
        {ours.isError ? 'Не удалось загрузить наши объекты. ' : ''}
        <button type="button" className="market-map-action" onClick={() => { void sites.refetch(); void ours.refetch() }}>Повторить загрузку</button>
      </div>}
      {!sites.isPending && !ours.isPending && !sites.isError && !ours.isError && !market.length && !ourPoints.length &&
        <p role="status" className="market-map-message text-muted-foreground">По выбранным фильтрам точек нет. Измените фильтры или область карты.</p>}
      </div>
    </div>
  )
}

/** Реестр точек рынка: что известно и насколько это свежо. */
function MarketSites() {
  const { companyId } = useCompany()
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
  useEffect(() => { setСтраниц(1) }, [запрос, kind])

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
  const rows = sites.data?.sites ?? []
  const всего = sites.data?.total ?? 0
  const ещё = Math.max(0, всего - rows.length)

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
        <span className="text-xs text-muted-foreground">
          {rows.length === всего
            ? `${всего.toLocaleString('ru-RU')} точек`
            : `${rows.length.toLocaleString('ru-RU')} из ${всего.toLocaleString('ru-RU')}`}
          {запрос && ` по запросу «${запрос}»`}
        </span>
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
