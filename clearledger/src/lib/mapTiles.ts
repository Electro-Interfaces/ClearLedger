/**
 * Подложка карт пространства — одна на все карты продукта.
 *
 * Карт в продукте четыре: рынок, площадки проектов, зарядные сессии и АЗС. Пока
 * подложка задавалась в каждой по месту, «сменить провайдера» означало четыре
 * правки и один забытый экран, где карта осталась чужой. Теперь провайдер живёт
 * здесь, а карты спрашивают его.
 *
 * ПРОВАЙДЕР МЕНЯЕТСЯ ОДНОЙ СТРОКОЙ — `ACTIVE`. Проекция и подпись едут за ним:
 * у Яндекса эллиптическая Меркатор (EPSG:3395), у остальных сферическая
 * (EPSG:3857). Разница не косметическая — на широте Москвы точка уезжает примерно
 * на двадцать километров, и станция оказывается в соседнем районе.
 *
 * Про лицензии, чтобы выбор был осознанным:
 *
 * - `yandex` — тайлы берутся у растрового рендерера напрямую. Работает и выглядит
 *   привычно для российского пользователя, но условиями Яндекса такое применение
 *   не предусмотрено: для поставки заказчику нужен их JS API с ключом.
 * - `osm` — свободные тайлы OpenStreetMap: единственный вариант без договора и
 *   ключа. Города РФ покрыты хорошо, детализация зданий скромнее.
 * - `carto` — та же OSM, но приятнее нарисованная, с тёмной темой. Бесплатна для
 *   небольшого трафика, дальше — тариф.
 *
 * 2ГИС и Сбер сюда не добавить строкой: у них нет растровых тайлов для Leaflet,
 * их карта — WebGL-SDK (MapGL) с ключом и своим API, то есть замена движка карты,
 * а не подложки. Это отдельная работа, и начинать её имеет смысл, когда куплен
 * ключ, — см. отчёт по картам.
 */
import { CRS } from 'leaflet'

type Provider = {
  url: string
  attribution: string
  maxZoom: number
  /** Тайлы в эллиптической проекции Яндекса (EPSG:3395), а не сферической. */
  elliptical?: boolean
  subdomains?: string
  /** Есть ли у провайдера отдельная тёмная подложка. */
  darkUrl?: string
}

const PROVIDERS = {
  yandex: {
    url: 'https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}&scale=1&lang=ru_RU',
    attribution: '&copy; <a href="https://yandex.ru/maps">Яндекс</a>',
    maxZoom: 21,
    elliptical: true,
  },
  osm: {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  },
  carto: {
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    darkUrl: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution: '&copy; OpenStreetMap, &copy; CARTO',
    maxZoom: 19,
    subdomains: 'abcd',
  },
} satisfies Record<string, Provider>

/** Действующий провайдер подложки (решение МАГа 21.08.2026 — Яндекс). */
const ACTIVE: keyof typeof PROVIDERS = 'yandex'

const current: Provider = PROVIDERS[ACTIVE]

/** Проекция подложки. Передаётся в MapContainer как `crs`. */
export const MAP_CRS = current.elliptical ? CRS.EPSG3395 : CRS.EPSG3857

export const MAP_ATTRIBUTION = current.attribution

export const MAP_MAX_ZOOM = current.maxZoom

export const MAP_TILE_URL = current.url

/**
 * Класс слоя под тему. Своей тёмной подложки у растрового Яндекса нет, поэтому
 * ночью карту гасим фильтром: инверсия сделала бы воду розовой, а лес
 * фиолетовым — читать такую карту нельзя.
 */
export function mapTileClass(dark: boolean): string {
  return dark && !current.darkUrl ? 'brightness-[.72] saturate-[.85] contrast-[1.05]' : ''
}

/** Всё, что нужно `<TileLayer>`, одним объектом. */
export function mapTileProps(dark: boolean) {
  return {
    url: dark && current.darkUrl ? current.darkUrl : current.url,
    attribution: current.attribution,
    maxZoom: current.maxZoom,
    ...(current.subdomains ? { subdomains: current.subdomains } : {}),
    className: mapTileClass(dark),
  }
}

/**
 * Подпись под картой: только источник данных.
 *
 * Leaflet по умолчанию ставит рядом свой значок с флагом Украины. Продукт про
 * зарядную сеть, а не про чью-либо позицию, и политический символ в углу рабочего
 * экрана — это заявление, которого никто не делал. Библиотеку не прячем: ссылка на
 * неё остаётся в исходниках и в лицензии, а на экране остаётся то, что требует
 * поставщик подложки.
 *
 * Использовать так: у карты `attributionControl={false}`, а внутри —
 * `<AttributionControl prefix={MAP_ATTRIBUTION_PREFIX} />`.
 */
export const MAP_ATTRIBUTION_PREFIX = false as const

/**
 * Слои растрового Яндекса, доступные без ключа и без смены движка.
 *
 * `map` — схема, `sat` — спутник, `hybrid` — спутник плюс отдельный слой подписей
 * (`skl`), который кладётся сверху: в одном тайле их не отдают. `traffic` — пробки;
 * у них свой кэш и обязательная метка времени, иначе браузер покажет затор
 * получасовой давности из своего кэша.
 */
export const YANDEX_LAYERS = {
  map: { url: 'https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}&scale=1&lang=ru_RU' },
  sat: { url: 'https://core-sat.maps.yandex.net/tiles?l=sat&x={x}&y={y}&z={z}&scale=1&lang=ru_RU' },
  hybrid: { url: 'https://core-sat.maps.yandex.net/tiles?l=sat&x={x}&y={y}&z={z}&scale=1&lang=ru_RU' },
  labels: { url: 'https://core-renderer-tiles.maps.yandex.net/tiles?l=skl&x={x}&y={y}&z={z}&scale=1&lang=ru_RU' },
  traffic: {
    url: (stamp: number) =>
      `https://core-jams-rdr-cache.maps.yandex.net/1.1/tiles?l=trf,trfe&x={x}&y={y}&z={z}&scale=1&tm=${Math.floor(stamp / 1000)}`,
  },
} as const

/** Слои есть только у Яндекса: на OSM переключателю показывать нечего. */
export const isYandexBase = ACTIVE === 'yandex'
