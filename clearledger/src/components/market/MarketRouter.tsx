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
import { MapContainer, CircleMarker, Popup, AttributionControl } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import 'leaflet/dist/leaflet.css'
import { Loader2, MapPin, Plus } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import {
  listMarketSites, listMarketObservations,
  SITE_KIND_LABEL, CHANNEL_LABEL, type MarketSite, type MarketSiteKind,
} from '@/services/marketService'
import { MarketPositionPanel } from './MarketPositionPanel'
import { MarketImportDialog } from './MarketImportDialog'
import { MarketOcmButton } from './MarketOcmButton'
import { MarketSiteDialog } from './MarketSiteDialog'
import { MarketObservationDialog } from './MarketObservationDialog'
import { MarketSourcesPanel } from './MarketSourcesPanel'
import { MarketCompaniesPanel } from './MarketCompaniesPanel'
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

/** Цвет точки на карте: наши — фирменный, конкуренты — красный, притяжение — серый. */
function siteColor(s: MarketSite): string {
  if (s.isOurs) return '#3b82f6'
  if (s.kind === 'ezs') return '#ef4444'
  return '#94a3b8'
}

/** Возраст факта словами: «сегодня» важнее даты — по нему видно, можно ли доверять. */
function ageLabel(iso: string | null | undefined): { text: string; stale: boolean } {
  if (!iso) return { text: 'не проверялось', stale: true }
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return { text: 'сегодня', stale: false }
  if (days === 1) return { text: 'вчера', stale: false }
  return { text: `${days} дн назад`, stale: days > 30 }
}

function useMarketData(kind: string) {
  const { companyId } = useCompany()
  const sites = useQuery({
    queryKey: ['market-sites', companyId, kind],
    queryFn: () => listMarketSites(companyId, kind === 'all' ? undefined : { kind }),
    enabled: !!companyId,
  })
  // Наши объекты — из реестра пространства: он и есть источник истины по нашей сети,
  // копировать её в рынок нельзя (docs/MARKET.md §3).
  const ours = useQuery({
    queryKey: ['market-our-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    enabled: !!companyId,
  })
  return { sites, ours }
}

/** Карта рынка: наши объекты и чужие точки на одном полотне. */
function MarketMap() {
  const dark = useIsDark()
  const [kind, setKind] = useState('all')
  const { sites, ours } = useMarketData(kind)

  const market = (sites.data?.sites ?? []).filter((s) => s.lat != null && s.lon != null)
  // Полная выгрузка — 12 240 точек: страница может не вместить всё, и молчать об
  // этом нельзя (ревизия 12.09.2026, К10).
  const cut = (sites.data?.total ?? 0) > (sites.data?.returned ?? 0)
  const ourPoints = useMemo(() => (ours.data ?? [])
    .filter((l) => l.latitude != null && l.longitude != null)
    .map((l) => ({ id: l.id, name: l.name, lat: Number(l.latitude), lon: Number(l.longitude) })),
  [ours.data])

  const mapLayers = useMapLayers()

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все точки рынка</SelectItem>
            {Object.entries(SITE_KIND_LABEL).map(([k, label]) => (
              <SelectItem key={k} value={k}>{label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          наших объектов: {ourPoints.length} · точек рынка: {market.length}
          {cut && (
            <span className="text-warning">
              {' · '}показана часть: всего {sites.data?.total} — приблизьте карту
            </span>
          )}
        </span>
        <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><i className="size-2 rounded-full bg-[#3b82f6]" /> наши</span>
          <span className="flex items-center gap-1"><i className="size-2 rounded-full bg-[#ef4444]" /> чужие ЭЗС</span>
          <span className="flex items-center gap-1"><i className="size-2 rounded-full bg-[#94a3b8]" /> притяжение</span>
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
          {ourPoints.map((p) => (
            <CircleMarker key={`our-${p.id}`} center={[p.lat, p.lon]} radius={5}
              pathOptions={{ color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.85, weight: 1 }}>
              <Popup><b>{p.name}</b><br />наш объект</Popup>
            </CircleMarker>
          ))}
          {market.map((s) => {
            const age = ageLabel(s.price?.observedOn ?? s.lastSeenAt)
            return (
              <CircleMarker key={s.id} center={[s.lat as number, s.lon as number]} radius={5}
                pathOptions={{ color: siteColor(s), fillColor: siteColor(s), fillOpacity: 0.8, weight: 1 }}>
                <Popup>
                  <b>{s.name}</b><br />
                  {SITE_KIND_LABEL[s.kind]}{s.operatorName ? ` · ${s.operatorName}` : ''}<br />
                  {s.price?.value
                    ? <>цена {s.price.value} ₽{s.price.unit === 'kwh' ? '/кВтч' : ''} · {age.text}</>
                    : <>цена не наблюдалась</>}
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
      </div>
    </div>
  )
}

/** Реестр точек рынка: что известно и насколько это свежо. */
function MarketSites() {
  const [kind, setKind] = useState('all')
  const [q, setQ] = useState('')
  const { sites } = useMarketData(kind)
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
    case 'mk_operators': return <MarketCompaniesPanel />
    case 'mk_observations': return <MarketObservations />
    case 'mk_sources': return <MarketSourcesPanel />
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
