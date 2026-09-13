import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import L from 'leaflet'
import { Marker, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { clusterPoints, clusterRadiusForZoom, type ClusterOf } from '@/components/map/clusterPoints'
import { SITE_KIND_LABEL, type MarketSite, type OurMapPoint } from '@/services/marketService'
import type { OurFilters } from './MarketMapFilters'
import { ageLabel, ourColor, siteColor } from './marketMapPresentation'
import './market-map.css'

type MapPoint =
  | { key: string; lat: number; lon: number; type: 'ours'; data: OurMapPoint }
  | { key: string; lat: number; lon: number; type: 'market'; data: MarketSite }

const isOur = (point: MapPoint) => point.type === 'ours' || !!point.data.isOurs
const pointLabel = (point: MapPoint) => point.type === 'ours' ? 'наш объект'
  : point.data.isOurs ? 'наш объект'
  : point.data.kind !== 'ezs' ? SITE_KIND_LABEL[point.data.kind]
    : point.data.siteClass === 'home' ? 'домашняя точка'
      : point.data.siteClass === 'independent' ? 'независимая точка' : 'сеть рынка'

function PointDetails({ point }: { point: MapPoint }) {
  if (point.type === 'ours') {
    const p = point.data
    return <div className="market-point-details" tabIndex={-1}>
      <strong>{p.name}</strong>
      <div>Наш объект · {p.code}</div>
      <div>{[p.city, p.brand].filter(Boolean).join(' · ')}</div>
      <div>{p.powerKwt != null && `${p.powerKwt} кВт`}{p.ports != null && ` · ${p.ports} портов`}</div>
      <dl>
        <dt>Сессий за 90 дней</dt><dd>{p.sessions.toLocaleString('ru-RU')}</dd>
        <dt>На порт в сутки</dt><dd>{p.sessionsPerPortDay ?? 'нет данных'}</dd>
        <dt>Срывы сессий</dt><dd>{p.errorPct != null ? `${p.errorPct} %` : 'нет данных'}</dd>
      </dl>
      {p.status && <div>Состояние: {p.status}</div>}
    </div>
  }
  const p = point.data
  const age = ageLabel(p.price?.observedOn ?? p.lastSeenAt)
  return <div className="market-point-details" tabIndex={-1}>
    <strong>{p.name}</strong>
    <div>{pointLabel(point)}{p.operatorName && ` · ${p.operatorName}`}</div>
    <div>{p.address || p.city}</div>
    {p.maxPowerKw != null && <div>{p.maxPowerKw} кВт{p.ports != null && ` · ${p.ports} портов`}</div>}
    <div>{p.price?.value != null
      ? `Цена ${p.price.value} ₽${p.price.unit === 'kwh' ? '/кВтч' : ''} · ${age.text}`
      : 'Цена не наблюдалась'}</div>
  </div>
}

function PointList({ cluster, colorBy }: { cluster: ClusterOf<MapPoint>; colorBy: OurFilters['colorBy'] }) {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(25)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const selected = cluster.items.find((p) => p.key === selectedKey)
  const own = cluster.items.filter(isOur).length
  const filtered = useMemo(() => {
    const q = query.trim().toLocaleLowerCase('ru-RU')
    return cluster.items.filter((p) => [p.data.name, p.data.city,
      p.type === 'ours' ? p.data.code : p.data.operatorName,
      p.type === 'market' ? p.data.address : p.data.brand,
    ].filter(Boolean).join(' ').toLocaleLowerCase('ru-RU').includes(q))
      .sort((a, b) => Number(isOur(b)) - Number(isOur(a)) || a.data.name.localeCompare(b.data.name, 'ru'))
  }, [cluster.items, query])
  if (cluster.items.length === 1) return <PointDetails point={cluster.items[0]} />
  if (selected) return <div>
    <button type="button" className="market-map-action" onClick={(e) => { e.stopPropagation(); setSelectedKey(null) }}>Назад к списку ({cluster.items.length})</button>
    <PointDetails point={selected} />
  </div>
  return <div className="market-point-list">
    <strong>{cluster.items.length.toLocaleString('ru-RU')} точек рядом</strong>
    <div className="market-point-meta">Наших: {own} · рынка: {cluster.items.length - own}</div>
    <input aria-label="Поиск точки в группе" placeholder="Название, адрес или оператор"
      value={query} onChange={(e) => { setQuery(e.target.value); setLimit(25) }} />
    <div className="market-point-rows">
      {filtered.slice(0, limit).map((point) => <button key={point.key} type="button"
        className="market-point-row" onClick={(e) => { e.stopPropagation(); setSelectedKey(point.key) }}>
        <span className={`market-point-symbol ${isOur(point) ? 'market-point-symbol-ours' : ''}`}
          style={{ background: point.type === 'ours' ? ourColor(point.data, colorBy) : siteColor(point.data) }} />
        <span><span className="market-point-name">{point.data.name}</span>
          <span className="market-point-meta">{pointLabel(point)}{point.type === 'market' && point.data.operatorName && ` · ${point.data.operatorName}`}</span>
        </span>
      </button>)}
      {!filtered.length && <p role="status">Точек по этому запросу нет. Измените поиск.</p>}
    </div>
    {filtered.length > limit && <button type="button" className="market-map-action"
      onClick={(e) => { e.stopPropagation(); setLimit((n) => n + 25) }}>Показать ещё ({filtered.length - limit})</button>}
  </div>
}

function PointMarker({ cluster, colorBy, onSelect }: {
  cluster: ClusterOf<MapPoint>
  colorBy: OurFilters['colorBy']
  onSelect: (key: string, marker: L.Marker) => void
}) {
  const map = useMap()
  const markerRef = useRef<L.Marker | null>(null)
  const own = cluster.items.filter(isOur).length
  const one = cluster.items.length === 1 ? cluster.items[0] : null
  const samePlace = cluster.items.every((p) => p.lat === cluster.lat && p.lon === cluster.lon)
  const showList = !!one || samePlace || map.getZoom() >= map.getMaxZoom()
  const label = one ? `${one.data.name} · ${pointLabel(one)}`
    : `${cluster.items.length} точек · наших: ${own} · рынка: ${cluster.items.length - own}`
  const action = showList ? (one ? 'Открыть карточку' : 'Открыть список точек') : 'Приблизить группу'
  useEffect(() => {
    const element = markerRef.current?.getElement()
    element?.setAttribute('aria-label', `${label}. ${action}`)
    element?.setAttribute('title', `${label}. ${action}`)
  }, [label, action])
  const icon = useMemo(() => {
    const element = document.createElement('span')
    element.className = one ? `market-point-symbol ${own ? 'market-point-symbol-ours' : ''}`
      : `market-cluster-count ${own === cluster.items.length ? 'market-cluster-ours' : ''}`
    if (one) {
      element.style.background = one.type === 'ours' ? ourColor(one.data, colorBy) : siteColor(one.data)
    } else {
      element.textContent = cluster.items.length.toLocaleString('ru-RU')
      if (own > 0 && own < cluster.items.length) {
        const badge = document.createElement('span')
        badge.className = 'market-cluster-own-count'
        badge.textContent = String(own)
        element.append(badge)
      }
    }
    return L.divIcon({ className: 'market-map-marker', html: element, iconSize: [44, 44], iconAnchor: [22, 22] })
  }, [cluster.items, one, own, colorBy])
  const activate = (event: L.LeafletEvent) => {
    if (showList) {
      onSelect(cluster.key, event.target)
      return
    }
    const bounds = L.latLngBounds(cluster.items.map((p) => [p.lat, p.lon]))
    const zoom = Math.min(map.getMaxZoom(), Math.max(map.getZoom() + 1,
      Math.floor(map.getBoundsZoom(bounds, false, L.point(100, 100)))))
    map.setView(bounds.getCenter(), zoom, {
      animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    })
  }
  return <Marker ref={markerRef} position={[cluster.lat, cluster.lon]} icon={icon} title={`${label}. ${action}`}
    alt={`${label}. ${action}`} zIndexOffset={own ? 100 : 0} autoPanOnFocus={false}
    eventHandlers={{ click: activate, keydown: (e) => {
      if (e.originalEvent.key === ' ' || e.originalEvent.key === 'Enter') { e.originalEvent.preventDefault(); activate(e) }
    } }}>
    <Tooltip direction="top" offset={[0, -20]} className="cl-map-tip market-map-tip">
      <strong>{label}</strong><div>{action}</div>
    </Tooltip>
  </Marker>
}

export function MarketMapPoints({ market, ourPoints, zoom, colorBy }: {
  market: MarketSite[]
  ourPoints: OurMapPoint[]
  zoom: number
  colorBy: OurFilters['colorBy']
}) {
  const map = useMap()
  const selectedMarker = useRef<L.Marker | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const visibleBounds = () => L.latLngBounds(map.containerPointToLatLng([-100, -100]),
    map.containerPointToLatLng(map.getSize().add([100, 100])))
  const [viewport, setViewport] = useState(visibleBounds)
  useMapEvents({
    moveend: () => { const next = visibleBounds(); setViewport((previous) => previous.equals(next) ? previous : next) },
    zoomstart: () => { map.closePopup(); setSelectedKey(null) },
  })
  const clusters = useMemo(() => {
    const points: MapPoint[] = [
      ...ourPoints.map((data): MapPoint => ({ key: `our:${data.id}`, lat: data.lat, lon: data.lon, type: 'ours', data })),
      ...market.filter((p) => p.lat != null && p.lon != null).map((data): MapPoint => ({
        key: `market:${data.id}`, lat: data.lat!, lon: data.lon!, type: 'market', data,
      })),
    ]
    return clusterPoints(map, points, clusterRadiusForZoom(zoom),
      (p) => [p.lat, p.lon], (p) => p.key, zoom)
  }, [map, market, ourPoints, zoom])
  const selected = clusters.find((c) => c.key === selectedKey)
  const popupLat = selected?.lat
  const popupLon = selected?.lon
  const popupPosition = useMemo(() => popupLat != null && popupLon != null
    ? L.latLng(popupLat, popupLon) : undefined, [popupLat, popupLon])
  return <>
    {clusters.filter((c) => viewport.contains([c.lat, c.lon])).map((cluster) =>
      <PointMarker key={cluster.key} cluster={cluster} colorBy={colorBy}
        onSelect={(key, marker) => { selectedMarker.current = marker; setSelectedKey(key) }} />)}
    {selected && <Popup key={selected.key} position={popupPosition}
      className="cl-map-popup market-map-popup" maxWidth={Math.min(320, map.getSize().x - 56)}
      minWidth={Math.min(260, map.getSize().x - 56)} autoPanPadding={[24, 24]}
      eventHandlers={{
        add: (e) => { setTimeout(() => {
          const element: HTMLElement | undefined = e.target.getElement()
          if (!element?.isConnected) return
          element.querySelector('.leaflet-popup-close-button')?.setAttribute('aria-label', 'Закрыть карточку')
          element.querySelector<HTMLElement>('input, button, [tabindex="-1"]')?.focus()
        }, 0) },
        remove: () => {
          setSelectedKey(null)
          selectedMarker.current?.getElement()?.focus({ preventScroll: true })
        },
      }}>
      <div style={{ '--market-map-height': `${map.getSize().y}px` } as CSSProperties} onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Escape') { e.preventDefault(); map.closePopup(); setSelectedKey(null) }
      }}>
        <PointList cluster={selected} colorBy={colorBy} />
      </div>
    </Popup>}
  </>
}
