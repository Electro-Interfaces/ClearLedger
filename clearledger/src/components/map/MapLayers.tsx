/**
 * Слои карты: схема, спутник, гибрид и пробки.
 *
 * Подложка отвечала на один вопрос — «где это на карте». Инженеру и коммерсанту
 * нужны ещё два: «что там на местности» (спутник показывает парковку, въезд,
 * соседние здания — то, чего схема не рисует) и «как туда ехать сейчас» (пробки).
 * Оба слоя есть у растрового Яндекса и не требуют ни ключа, ни смены движка.
 *
 * Выбор слоя — личная настройка рабочего места, а не свойство данных: он живёт в
 * браузере и переживает перезаход, но никому больше не виден.
 *
 * Пробки живут своей жизнью: у них отдельный кэш и своя метка времени, поэтому
 * слой перерисовывается каждые три минуты — иначе человек смотрел бы на затор,
 * которого нет уже полчаса.
 */
import { useEffect, useState } from 'react'
import { GeoJSON, TileLayer } from 'react-leaflet'
import type { FeatureCollection } from 'geojson'
import { Layers, Satellite, Map as MapIcon, TrafficCone, LandPlot } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MAP_ATTRIBUTION, MAP_MAX_ZOOM, YANDEX_LAYERS, isYandexBase } from '@/lib/mapTiles'

export type MapBase = 'map' | 'sat' | 'hybrid'

const STORE_KEY = 'map-layer'
const STORE_TRAFFIC = 'map-traffic'
const STORE_REGIONS = 'map-regions'

/** Выбор слоя и пробок с памятью на рабочем месте. */
export function useMapLayers() {
  const [base, setBase] = useState<MapBase>(() =>
    (localStorage.getItem(STORE_KEY) as MapBase) || 'map')
  const [traffic, setTraffic] = useState(() => localStorage.getItem(STORE_TRAFFIC) === '1')
  const [regions, setRegions] = useState(() => localStorage.getItem(STORE_REGIONS) === '1')
  useEffect(() => { localStorage.setItem(STORE_KEY, base) }, [base])
  useEffect(() => { localStorage.setItem(STORE_TRAFFIC, traffic ? '1' : '0') }, [traffic])
  useEffect(() => { localStorage.setItem(STORE_REGIONS, regions ? '1' : '0') }, [regions])
  return { base, setBase, traffic, setTraffic, regions, setRegions }
}

/**
 * Границы субъектов РФ.
 *
 * Файл лежит в поставке и грузится ТОЛЬКО когда слой включили: полмегабайта
 * геометрии в каждом открытии карты — это полсекунды на пустом месте у тех, кому
 * границы не нужны.
 *
 * Источник — Natural Earth (общественное достояние), упрощённый до точности
 * обзорной карты. Это навигационный слой, а не кадастровый: по нему видно, в каком
 * субъекте стоит станция, но межевать по нему нельзя.
 *
 * Цвет — фиолетовый, и это не вкус: на карте Яндекса дороги жёлтые и белые, лес
 * зелёный, вода синяя, застройка серая. Серая линия среди них теряется, а
 * фиолетового на подложке нет — граница читается сразу. На спутнике и в тёмной
 * теме тот же тёмный тон исчезает, поэтому там берётся светлый: `pale`.
 */
function RegionsLayer({ pale }: { pale: boolean }) {
  const [data, setData] = useState<FeatureCollection | null>(null)
  useEffect(() => {
    let alive = true
    fetch(`${import.meta.env.BASE_URL}ru-regions.geojson`)
      .then((r) => r.json())
      .then((d) => { if (alive) setData(d) })
      .catch(() => {})
    return () => { alive = false }
  }, [])
  if (!data) return null
  const line = pale ? '#c4b5fd' : '#6d28d9'
  const rest = { color: line, weight: 2, opacity: 0.9, fillColor: line, fillOpacity: pale ? 0.07 : 0.05 }
  const over = { ...rest, weight: 3.5, fillOpacity: pale ? 0.2 : 0.16 }
  return (
    <GeoJSON key={pale ? 'pale' : 'ink'} data={data} style={rest}
      onEachFeature={(feature, layer) => {
        // Подсветка под курсором: без неё на стыке двух областей непонятно, какая
        // из них подписана.
        layer.on('mouseover', () => (layer as any).setStyle?.(over))
        layer.on('mouseout', () => (layer as any).setStyle?.(rest))
        const name = (feature.properties as { name?: string } | null)?.name
        if (name) layer.bindTooltip(name, { sticky: true, direction: 'top' })
      }} />
  )
}

/** Слои подложки: основа плюс пробки и границы поверх, если включены. */
export function MapTiles({ base, traffic, regions, dark }: {
  base: MapBase; traffic: boolean; regions?: boolean; dark: boolean
}) {
  // Метка времени пробок: перерисовываем слой раз в три минуты.
  const [stamp, setStamp] = useState(() => Date.now())
  useEffect(() => {
    if (!traffic) return
    const id = setInterval(() => setStamp(Date.now()), 180_000)
    return () => clearInterval(id)
  }, [traffic])

  const layer = YANDEX_LAYERS[base]
  return (
    <>
      <TileLayer key={`${base}-${dark ? 'd' : 'l'}`} url={layer.url}
        attribution={MAP_ATTRIBUTION} maxZoom={MAP_MAX_ZOOM}
        // Спутник затемнять незачем: он и так тёмный, а фильтр съедает детали.
        className={dark && base === 'map' ? 'brightness-[.72] saturate-[.85] contrast-[1.05]' : ''} />
      {base === 'hybrid' && (
        <TileLayer key="labels" url={YANDEX_LAYERS.labels.url} maxZoom={MAP_MAX_ZOOM} />
      )}
      {traffic && (
        <TileLayer key={`traffic-${stamp}`} url={YANDEX_LAYERS.traffic.url(stamp)}
          maxZoom={MAP_MAX_ZOOM} opacity={0.85} />
      )}
      {regions && <RegionsLayer pale={dark || base !== 'map'} />}
    </>
  )
}

/** Переключатель в углу карты. */
export function MapLayerSwitch({ base, setBase, traffic, setTraffic, regions, setRegions, className }: {
  base: MapBase
  setBase: (v: MapBase) => void
  traffic: boolean
  setTraffic: (v: boolean) => void
  regions?: boolean
  setRegions?: (v: boolean) => void
  className?: string
}) {
  if (!isYandexBase) return null
  const item = (value: MapBase, label: string, Icon: typeof MapIcon) => (
    <button key={value} type="button" onClick={() => setBase(value)}
      title={label} aria-pressed={base === value}
      className={cn('inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors',
        base === value ? 'bg-primary text-primary-foreground' : 'text-foreground hover:bg-accent')}>
      <Icon className="size-3.5" />{label}
    </button>
  )
  return (
    <div className={cn(
      'absolute right-2 top-2 z-[1000] flex items-center gap-0.5 rounded-lg border border-border bg-background/95 p-1 shadow-md backdrop-blur',
      className)}>
      {item('map', 'Схема', MapIcon)}
      {item('sat', 'Спутник', Satellite)}
      {item('hybrid', 'Гибрид', Layers)}
      <span className="mx-0.5 h-5 w-px bg-border" />
      <button type="button" onClick={() => setTraffic(!traffic)}
        title="Пробки сейчас" aria-pressed={traffic}
        className={cn('inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors',
          traffic ? 'bg-amber-500 text-white' : 'text-foreground hover:bg-accent')}>
        <TrafficCone className="size-3.5" />Пробки
      </button>
      {setRegions && (
        <button type="button" onClick={() => setRegions(!regions)}
          title="Границы субъектов России" aria-pressed={!!regions}
          className={cn('inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors',
            regions ? 'bg-primary text-primary-foreground' : 'text-foreground hover:bg-accent')}>
          <LandPlot className="size-3.5" />Регионы
        </button>
      )}
    </div>
  )
}
