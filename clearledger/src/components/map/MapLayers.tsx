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
import { TileLayer } from 'react-leaflet'
import { Layers, Satellite, Map as MapIcon, TrafficCone } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MAP_ATTRIBUTION, MAP_MAX_ZOOM, YANDEX_LAYERS, isYandexBase } from '@/lib/mapTiles'

export type MapBase = 'map' | 'sat' | 'hybrid'

const STORE_KEY = 'map-layer'
const STORE_TRAFFIC = 'map-traffic'

/** Выбор слоя и пробок с памятью на рабочем месте. */
export function useMapLayers() {
  const [base, setBase] = useState<MapBase>(() =>
    (localStorage.getItem(STORE_KEY) as MapBase) || 'map')
  const [traffic, setTraffic] = useState(() => localStorage.getItem(STORE_TRAFFIC) === '1')
  useEffect(() => { localStorage.setItem(STORE_KEY, base) }, [base])
  useEffect(() => { localStorage.setItem(STORE_TRAFFIC, traffic ? '1' : '0') }, [traffic])
  return { base, setBase, traffic, setTraffic }
}

/** Слои подложки: основа плюс пробки поверх, если включены. */
export function MapTiles({ base, traffic, dark }: {
  base: MapBase; traffic: boolean; dark: boolean
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
    </>
  )
}

/** Переключатель в углу карты. */
export function MapLayerSwitch({ base, setBase, traffic, setTraffic, className }: {
  base: MapBase
  setBase: (v: MapBase) => void
  traffic: boolean
  setTraffic: (v: boolean) => void
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
    </div>
  )
}
