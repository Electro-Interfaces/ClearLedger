/**
 * «Карта» — интерактивная карта сети АЗС ГИГ (Leaflet + тайлы CARTO, тема light/dark).
 * Координаты станций — из STS /v1/points (гео-паспорт FuelStation). Метрики за период
 * (реализации/объём/выручка из транзакций) → раскраска/размер точек. Аналог ЭЗС «Карта».
 */

import { Fragment, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MapContainer, CircleMarker, Marker, Popup, Tooltip, useMap, useMapEvents, AttributionControl } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Loader2, MapPin, Fuel, Wallet, Gauge, RefreshCw } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { fmtMoneyShort, fmtLiters } from '@/services/analyticsService'
import { getFuelStationsMap, syncFuelStationsGeo, type FuelMapStation } from '@/services/fuel/fuelMappingService'
import { getFuelPriceSpread } from '@/services/fuelSalesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

/**
 * Величина кодируется ОДНОЙ hue от тусклого к яркому, а не радугой.
 *
 * Было viridis (фиолетовый → синий → бирюзовый → зелёный → жёлтый): формально
 * перцептивно-равномерная шкала, но пять разных цветов на карте читаются как
 * пять КАТЕГОРИЙ — «жёлтая станция» и «синяя станция» выглядят разными видами
 * объектов, а не большой и малой выручкой.
 */
/**
 * Ступени величины — одна hue, ordinal-рампа из пяти шагов. Для каждой темы СВОЙ
 * набор, а не автоматический флип: «мало» обязано быть ближе к фону карты, и на
 * тёмной это тёмно-синий, на светлой — светлый.
 *
 * Значения выверены валидатором палитр (skill dataviz, `--ordinal`) против фона
 * карты: монотонность светлоты, шаг между соседями ΔL ≥ 0.06 и контраст крайнего
 * шага к фону ≥ 2:1. Прежняя рампа проверку проходила, но занимала лишь треть
 * доступной светлоты (42→72 %), поэтому пять ступеней читались как один синий.
 */
const RAMP_DARK = ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#b7d3f6']   // фон #0b1220
const RAMP_LIGHT = ['#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']  // фон #e5e7eb
const NODATA_DARK = 'hsl(215 14% 34%)'
const NODATA_LIGHT = 'hsl(215 12% 62%)'

/**
 * Что показывает карта. Раньше выбор был из трёх величин одного смысла —
 * выручка, реализации, объём: все три меряют «насколько станция большая» и рисуют
 * одну и ту же картинку, отличающуюся округлением. Полезный выбор — это разные
 * ВОПРОСЫ к сети:
 *
 *   размер бизнеса   — выручка, объём (сколько прошло денег и литров);
 *   интенсивность    — реализаций в сутки (сравнивает станции при любом периоде);
 *   качество клиента — средний чек (сколько оставляет один заезд);
 *   позиционирование — средняя цена ₽/л (дорогая точка или дешёвая);
 *   динамика         — рост к прошлому периоду (кто набирает, кто теряет);
 *   структура спроса — ведущий вид топлива (дизельная трасса против города).
 *
 * `kind` задаёт ТИП шкалы, а не оформление: величина — одна hue светлое→яркое,
 * рост-падение — расходящаяся (два полюса и нейтральная середина), вид топлива —
 * категориальная. Смешивать нельзя: диверг-шкала на выручке врала бы о «норме»
 * посередине, а последовательная на росте прятала бы знак.
 */
type Metric = 'amount' | 'liters' | 'fills_per_day' | 'avg_check' | 'avg_price' | 'growth' | 'top_fuel'
type ScaleKind = 'sequential' | 'diverging' | 'categorical'

/**
 * Вид карты — три разных вопроса, а не оформление одного:
 *   value  — «где деньги сети»: размер и цвет по выбранному показателю, близкие АЗС в группах;
 *   dots   — «где вообще стоят наши АЗС»: одинаковые точки, без групп и шкалы;
 *   prices — «по какой цене торгует каждая»: у точки выноска с действующими ценами.
 */
type MapView = 'value' | 'dots' | 'prices'

/** Действующая цена станции по виду топлива (из раздела «Цены»). */
interface StationPrice { fuel: string; price: number; stale: boolean }

interface MetricDef {
  label: string
  hint: string
  kind: ScaleKind
  /** null — величины нет (станция без продаж, нет базы сравнения). */
  get: (s: FuelMapStation) => number | null
  fmt: (v: number) => string
  /** Размер маркера: у цены и чека он не по самой метрике — иначе дорогая
   *  мелкая станция выглядела бы крупнее большой дешёвой. */
  size?: (s: FuelMapStation) => number
}

const METRICS: Record<Metric, MetricDef> = {
  amount: {
    label: 'Выручка', hint: 'сколько денег прошло через станцию', kind: 'sequential',
    get: (s) => s.amount, fmt: (v) => fmtMoneyShort(v) + ' ₽',
  },
  liters: {
    label: 'Объём', hint: 'сколько литров отпущено', kind: 'sequential',
    get: (s) => s.liters, fmt: (v) => fmtLiters(v),
  },
  fills_per_day: {
    label: 'Реализаций в сутки', hint: 'интенсивность работы, не зависит от длины периода',
    kind: 'sequential', get: (s) => s.fills_per_day ?? null, fmt: (v) => `${nf1.format(v)}/сут`,
  },
  avg_check: {
    label: 'Средний чек', hint: 'сколько оставляет один заезд', kind: 'sequential',
    get: (s) => (s.avg_check ? s.avg_check : null), fmt: (v) => `${nf0.format(v)} ₽`,
    size: (s) => s.amount,
  },
  avg_price: {
    label: 'Средняя цена', hint: 'дорогая точка или дешёвая, ₽/л', kind: 'sequential',
    get: (s) => (s.avg_price ? s.avg_price : null), fmt: (v) => `${nf2.format(v)} ₽/л`,
    size: (s) => s.amount,
  },
  growth: {
    label: 'Динамика', hint: 'рост или падение выручки к прошлому периоду',
    kind: 'diverging', get: (s) => s.growth_pct ?? null,
    fmt: (v) => `${v > 0 ? '+' : ''}${nf0.format(v)} %`,
    size: (s) => s.amount,
  },
  top_fuel: {
    label: 'Ведущее топливо', hint: 'какой продукт даёт станции больше всего выручки',
    kind: 'categorical', get: () => null, fmt: () => '',
    size: (s) => s.amount,
  },
}

/** Категориальная палитра видов топлива — фиксированный порядок, не по рангу. */
const FUEL_COLORS: Record<string, string> = {
  'АИ-92': 'hsl(217 91% 62%)',
  'АИ-95': 'hsl(152 62% 48%)',
  'АИ-98': 'hsl(280 60% 66%)',
  'ДТ': 'hsl(25 92% 58%)',
  'ГАЗ': 'hsl(190 70% 52%)',
}
const FUEL_FALLBACK = 'hsl(215 16% 55%)'
const fuelColor = (name: string | null | undefined) =>
  (name && FUEL_COLORS[name]) || FUEL_FALLBACK

/** Расходящаяся шкала: падение — тёплый полюс, рост — холодный, ноль — нейтраль. */
const DIVERGING = {
  down2: 'hsl(0 72% 55%)', down1: 'hsl(14 78% 60%)',
  mid: 'hsl(215 14% 48%)',
  up1: 'hsl(152 52% 45%)', up2: 'hsl(152 68% 42%)',
}
function divergingColor(v: number): string {
  if (v <= -25) return DIVERGING.down2
  if (v < -5) return DIVERGING.down1
  if (v <= 5) return DIVERGING.mid
  if (v < 25) return DIVERGING.up1
  return DIVERGING.up2
}

function quantiles(values: number[]): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b)
  if (v.length < 5) return []
  return [0.2, 0.4, 0.6, 0.8].map((q) => v[Math.floor(q * (v.length - 1))])
}
function rampColor(value: number, th: number[], dark: boolean): string {
  const ramp = dark ? RAMP_DARK : RAMP_LIGHT
  if (value <= 0) return dark ? NODATA_DARK : NODATA_LIGHT
  if (th.length === 0) return ramp[2]
  let i = 0
  while (i < th.length && value > th[i]) i++
  return ramp[i]
}

/** Цвет по величине активной метрики и типу её шкалы (общий для станции и группы). */
function valueColor(v: number | null, kind: ScaleKind, th: number[], dark: boolean): string {
  if (v == null) return dark ? NODATA_DARK : NODATA_LIGHT
  return kind === 'diverging' ? divergingColor(v) : rampColor(v, th, dark)
}

/** Цвет станции по активной метрике и её типу шкалы. */
function markerColor(st: FuelMapStation, metric: Metric, th: number[], dark: boolean): string {
  const def = METRICS[metric]
  if (def.kind === 'categorical') return fuelColor(st.top_fuel)
  return valueColor(def.get(st), def.kind, th, dark)
}

/**
 * Величина метрики для ГРУППЫ станций.
 *
 * Без неё группа красилась одним цветом на все метрики — и переключение показателя
 * на обзорном плане не меняло ничего, потому что почти все станции сети собраны в
 * группы (МАГ 30.07.2026: «по некоторым переключениям вообще ничего не меняется»).
 *
 * Как складывать — зависит от смысла метрики, а не от типа шкалы:
 *   деньги, литры, интенсивность — сумма (группа продаёт столько же, сколько её АЗС);
 *   чек, цена, динамика — средневзвешенное ПО ВЫРУЧКЕ (среднее из средних врёт:
 *     станция с двумя заправками в день утянула бы цену группы наравне с крупной).
 */
const SUMMED: Metric[] = ['amount', 'liters', 'fills_per_day']

function clusterValue(items: FuelMapStation[], metric: Metric): number | null {
  const def = METRICS[metric]
  if (def.kind === 'categorical') return null
  const vals = items.map((s) => ({ v: def.get(s), w: s.amount || 0 })).filter((x) => x.v != null)
  if (vals.length === 0) return null
  if (SUMMED.includes(metric)) return vals.reduce((s, x) => s + (x.v as number), 0)
  const wsum = vals.reduce((s, x) => s + x.w, 0)
  if (wsum <= 0) return vals.reduce((s, x) => s + (x.v as number), 0) / vals.length
  return vals.reduce((s, x) => s + (x.v as number) * x.w, 0) / wsum
}

/** Ведущее топливо группы — по сумме выручки, а не по числу станций. */
function clusterTopFuel(items: FuelMapStation[]): string | null {
  const by = new Map<string, number>()
  items.forEach((s) => s.by_fuel.forEach((f) => by.set(f.fuel_name, (by.get(f.fuel_name) ?? 0) + f.amount)))
  let best: string | null = null
  let max = -1
  by.forEach((amount, name) => { if (amount > max) { max = amount; best = name } })
  return best
}

/** Тёмная тема приложения (класс `dark` на <html>) — реактивно. */
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

function FitBounds({ pts }: { pts: FuelMapStation[] }) {
  const map = useMap()
  useEffect(() => {
    const sane = pts.filter((p) => p.latitude != null && p.longitude != null)
    if (sane.length) {
      map.fitBounds(L.latLngBounds(sane.map((p) => [p.latitude!, p.longitude!] as [number, number])), { padding: [40, 40] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, pts.length])
  return null
}

function MapInvalidate() {
  const map = useMap()
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 120)
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(map.getContainer())
    return () => { clearTimeout(t); ro.disconnect() }
  }, [map])
  return null
}

function Stat({ icon: Icon, label, value }: { icon: typeof Wallet; label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/60 px-2 py-1.5">
      <div className="flex items-center gap-1 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="h-2.5 w-2.5" />{label}
      </div>
      <div className="mt-0.5 text-[13px] font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  )
}

/**
 * Группа станций, попавших в один экранный «пятачок» на текущем масштабе.
 *
 * Три АЗС под Выборгом стоят в паре километров: на обзорном плане их круги
 * физически не могут не пересечься — сколько ни уменьшай маркер, разводить
 * нечего. Поэтому на дальних масштабах они складываются в ОДИН маркер с числом
 * точек, а при приближении расходятся сами. Это честнее, чем рисовать три круга
 * друг на друге и надеяться, что человек попадёт мышью в нужный.
 */
interface Cluster {
  key: string
  lat: number
  lng: number
  items: FuelMapStation[]
}

/** Сборка кластеров по расстоянию В ПИКСЕЛЯХ — то есть по тому, что видит глаз. */
function clusterize(map: L.Map, pts: FuelMapStation[], radiusPx: number): Cluster[] {
  const out: Cluster[] = []
  const used = new Set<number>()
  // От крупных к мелким: центром группы становится значимая станция, а не
  // случайная первая в списке.
  const ordered = [...pts].sort((a, b) => b.amount - a.amount)
  for (const p of ordered) {
    if (used.has(p.code)) continue
    used.add(p.code)
    const base = map.latLngToLayerPoint([p.latitude!, p.longitude!])
    const group = [p]
    for (const q of ordered) {
      if (used.has(q.code)) continue
      const pt = map.latLngToLayerPoint([q.latitude!, q.longitude!])
      if (base.distanceTo(pt) <= radiusPx) {
        used.add(q.code)
        group.push(q)
      }
    }
    const lat = group.reduce((sum, g) => sum + g.latitude!, 0) / group.length
    const lng = group.reduce((sum, g) => sum + g.longitude!, 0) / group.length
    out.push({ key: `c${p.code}`, lat, lng, items: group })
  }
  return out
}

function StationMarkers({ pts, metric, th: thPts, dark, total, view, prices, onScale }: {
  pts: FuelMapStation[]; metric: Metric; th: number[]; dark: boolean; total: number
  view: MapView
  /** Действующие цены станции по видам топлива — для вида «Цены». */
  prices: Map<number, StationPrice[]>
  /** Фактическая шкала текущего кадра — для легенды (см. ниже, почему не по станциям). */
  onScale: (th: number[], max: number) => void
}) {
  // «Точки» и «Цены» — оба вида без склейки и без раскраски величиной.
  const dots = view !== 'value'
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  const [, setMoved] = useState(0)
  useMapEvents({
    zoomend: () => setZoom(map.getZoom()),
    // Кластеры считаются в экранных координатах, поэтому пересобираются и при
    // сдвиге карты — иначе после панорамирования группы «съезжают».
    moveend: () => setMoved((n) => n + 1),
  })
  const halo = dark ? '#0b1220' : '#ffffff'
  const def = METRICS[metric]
  const sizeOf = def.size ?? ((st: FuelMapStation) => def.get(st) ?? 0)

  /**
   * Радиус — по КОРНЮ величины: глаз сравнивает площадь, линейный радиус
   * преувеличил бы разницу вчетверо. На мелком масштабе круги ужимаются: сеть
   * должна читаться как сеть, а не как гроздь пятен.
   */
  const zoomK = Math.max(0.55, Math.min(1.35, 0.55 + (zoom - 6) * 0.1))
  const maxSize = useMemo(
    () => pts.reduce((m, p) => Math.max(m, sizeOf(p) || 0), 0),
    [pts, metric], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const radiusOf = (st: FuelMapStation) => {
    // Вид «точки»: размер ничего не значит — все станции одного калибра.
    if (dots) return Math.max(3.5, 5 * zoomK)
    const v = sizeOf(st)
    if (!(v > 0) || maxSize <= 0) return 5 * zoomK
    return (6 + 14 * Math.sqrt(v / maxSize)) * zoomK
  }

  // Радиус склейки — от масштаба: чем дальше, тем крупнее «пятачок». Ниже 34 px
  // не опускаемся: столько занимает сам маркер с обводкой.
  // В виде «точки» склейки нет вовсе: точка занимает единицы пикселей, наложение
  // терпимо, а группа скрыла бы ровно то, зачем этот вид включают — где стоят ВСЕ
  // станции сети.
  const clusterPx = Math.max(34, 74 - (zoom - 6) * 8)
  const clusters = useMemo(
    () => clusterize(map, pts, dots || zoom >= 12 ? 0 : clusterPx),
    [map, pts, zoom, clusterPx, dots], // eslint-disable-line react-hooks/exhaustive-deps
  )

  /**
   * Пороги ступеней считаются по ТОМУ, ЧТО НАРИСОВАНО в текущем кадре — по группам
   * и одиночным станциям, — а не по всем станциям сети.
   *
   * Иначе на обзорном плане каждая группа суммой перебивает максимум одиночной АЗС,
   * все группы попадают в верхнюю ступень и карта снова выходит одноцветной: ровно
   * та беда, из-за которой «переключения ничего не меняют». Пороги по кадру дают
   * различие между группами; при приближении, когда группы распадаются, шкала сама
   * возвращается к масштабу станций.
   */
  const shown = useMemo(
    () => clusters.map((c) => (c.items.length > 1 ? clusterValue(c.items, metric) : def.get(c.items[0])))
      .filter((v): v is number => v != null),
    [clusters, metric], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const th = useMemo(() => (shown.length >= 5 ? quantiles(shown) : thPts), [shown, thPts])
  const shownMax = useMemo(() => shown.reduce((m, v) => Math.max(m, v), 0), [shown])
  useEffect(() => { onScale(th, shownMax) }, [th, shownMax]) // eslint-disable-line react-hooks/exhaustive-deps

  const ranks = useMemo(() => {
    const m = new Map<number, number>()
    ;[...pts].sort((a, b) => (def.get(b) ?? -Infinity) - (def.get(a) ?? -Infinity))
      .forEach((p, i) => m.set(p.code, i + 1))
    return m
  }, [pts, metric]) // eslint-disable-line react-hooks/exhaustive-deps
  const withLabels = zoom >= 9

  return (
    <>
      {clusters.map((c) => {
        // ── Группа: один маркер вместо стопки, клик приближает к её станциям ──
        if (c.items.length > 1) {
          const sum = c.items.reduce((s2, st) => s2 + (sizeOf(st) || 0), 0)
          const amount = c.items.reduce((s2, st) => s2 + st.amount, 0)
          const r = Math.min(26, (12 + 3 * c.items.length) * Math.max(0.8, zoomK))
          /**
           * Группа — иконка С ЧИСЛОМ станций внутри, а не круг с постоянным
           * тултипом. Так делают все: Leaflet.markercluster (`iconCreateFunction` +
           * `getChildCount()`), Яндекс и Google — число объектов внутри кружка.
           *
           * Причина замены техническая: у слоя Leaflet может быть ТОЛЬКО ОДИН
           * tooltip — `bindTooltip` затирает предыдущий. Постоянный со счётчиком и
           * подсказка при наведении висели на одном маркере, вторая перебивала
           * первую, и группа выходила безымянным синим пятном: сколько станций
           * внутри, карта не говорила вовсе.
           */
          const d = Math.round(r * 2)
          // Цвет группы — по ЕЁ величине той же шкалой, что у одиночных станций:
          // иначе переключение показателя не меняет карту, где почти всё в группах.
          const cv = clusterValue(c.items, metric)
          const fill = def.kind === 'categorical'
            ? fuelColor(clusterTopFuel(c.items))
            : valueColor(cv, def.kind, th, dark)
          const icon = L.divIcon({
            className: 'cl-map-cluster',
            html: `<span style="width:${d}px;height:${d}px;border-color:${halo};background:${fill}">${c.items.length}</span>`,
            iconSize: [d, d],
            iconAnchor: [d / 2, d / 2],
          })
          return (
            <Marker key={c.key} position={[c.lat, c.lng]} icon={icon}
              eventHandlers={{
                click: () => map.fitBounds(
                  L.latLngBounds(c.items.map((st) => [st.latitude!, st.longitude!] as [number, number])),
                  { padding: [70, 70], maxZoom: 13 },
                ),
              }}>
              <Tooltip direction="top" offset={[0, -r - 2]} opacity={1} className="cl-map-tip">
                <div className="min-w-[200px]">
                  <div className="text-[12px] font-semibold">{c.items.length} АЗС рядом</div>
                  <div className="mt-0.5 text-[10px] opacity-70">Нажмите, чтобы приблизить</div>
                  <div className="mt-1.5 space-y-0.5 text-[11px]">
                    {c.items.slice(0, 6).map((st) => (
                      <div key={st.code} className="flex justify-between gap-3">
                        <span className="truncate">{st.name}</span>
                        <span className="tabular-nums opacity-80">{fmtMoneyShort(st.amount)} ₽</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-1.5 border-t border-border/60 pt-1 text-[11px]">
                    <span className="opacity-70">Вместе: </span>
                    <span className="font-medium tabular-nums">{fmtMoneyShort(amount)} ₽</span>
                    {def.kind === 'sequential' && sum > 0 && (
                      <span className="opacity-70"> · {def.label.toLowerCase()} {def.fmt(sum)}</span>
                    )}
                  </div>
                </div>
              </Tooltip>
            </Marker>
          )
        }

        // ── Одиночная станция ──
        const p = c.items[0]
        const value = def.get(p)
        const radius = radiusOf(p)
        const share = total > 0 ? ((METRICS.amount.get(p) ?? 0) / total) * 100 : 0
        const short = p.name.replace(/^АЗС\s*/i, '')
        const growth = p.growth_pct
        const fill = dots ? 'hsl(217 60% 58%)' : markerColor(p, metric, th, dark)
        return (
          <Fragment key={p.code}>
          {/*
            Подпись — ОТДЕЛЬНЫЙ неинтерактивный маркер, а не второй tooltip слоя.
            Раньше номер станции висел на том же круге постоянным tooltip'ом рядом с
            подсказкой при наведении, а `bindTooltip` держит только один: с зума 9
            подпись затирала подсказку, и карточка станции не показывалась вовсе.
            В виде «Цены» тем же маркером выводятся действующие цены по видам топлива.
          */}
          <PointLabel p={p} radius={radius} short={short} fill={fill}
            mode={view === 'prices' ? 'prices' : withLabels ? 'name' : 'none'}
            prices={prices.get(p.code) ?? []} />
          <CircleMarker center={[p.latitude!, p.longitude!]} radius={radius}
            pathOptions={{
              color: halo, weight: dots ? 1 : 2,
              // В виде «точки» цвет тоже не несёт величины — иначе это была бы та же
              // аналитическая карта, только мельче.
              fillColor: fill,
              fillOpacity: 0.92,
            }}
            eventHandlers={{
              mouseover: (e) => {
                e.target.bringToFront()
                e.target.setStyle({ color: 'hsl(205 96% 72%)', weight: 3 })
              },
              mouseout: (e) => e.target.setStyle({ color: halo, weight: 2 }),
            }}>
            <Tooltip direction="top" offset={[0, -radius - 2]} opacity={1} className="cl-map-tip">
              <div className="min-w-[210px]">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[12px] font-semibold leading-tight">{p.name}</span>
                  <span className="text-[10px] opacity-70">{ranks.get(p.code)} из {pts.length}</span>
                </div>
                {p.address && <div className="mt-0.5 text-[10px] opacity-70">{p.address}</div>}

                {/* Активная метрика — первой строкой и крупно: карта отвечает
                    именно на неё, остальное идёт справкой. */}
                <div className="mt-1.5 rounded-md bg-muted/40 px-2 py-1.5">
                  <div className="text-[10px] uppercase tracking-wide opacity-70">{def.label}</div>
                  <div className="text-[15px] font-semibold tabular-nums">
                    {metric === 'top_fuel'
                      ? `${p.top_fuel ?? '—'}${p.top_fuel_pct != null ? ` · ${nf0.format(p.top_fuel_pct)} %` : ''}`
                      : value != null ? def.fmt(value) : '—'}
                  </div>
                </div>

                <div className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
                  <span className="opacity-70">Выручка</span>
                  <span className="text-right font-medium tabular-nums">{fmtMoneyShort(p.amount)} ₽</span>
                  <span className="opacity-70">Объём</span>
                  <span className="text-right tabular-nums">{fmtLiters(p.liters)}</span>
                  <span className="opacity-70">Реализации</span>
                  <span className="text-right tabular-nums">{nf0.format(p.transactions)} · {nf1.format(p.fills_per_day)}/сут</span>
                  <span className="opacity-70">Средний чек</span>
                  <span className="text-right tabular-nums">{nf0.format(p.avg_check)} ₽</span>
                  <span className="opacity-70">Средняя цена</span>
                  <span className="text-right tabular-nums">{p.avg_price ? `${nf2.format(p.avg_price)} ₽/л` : '—'}</span>
                  <span className="opacity-70">Карт</span>
                  <span className="text-right tabular-nums">{nf0.format(p.cards)}</span>
                  <span className="opacity-70">Доля сети</span>
                  <span className="text-right tabular-nums">{nf1.format(share)} %</span>
                  <span className="opacity-70">К прошлому периоду</span>
                  <span className="text-right tabular-nums">
                    {growth == null ? 'нет базы' : `${growth > 0 ? '+' : ''}${nf0.format(growth)} %`}
                  </span>
                </div>

                {p.by_fuel.length > 0 && (
                  <div className="mt-1.5 border-t border-border/60 pt-1">
                    <div className="text-[10px] uppercase tracking-wide opacity-70">Состав продаж</div>
                    <div className="mt-1 flex h-2 overflow-hidden rounded-sm">
                      {p.by_fuel.slice(0, 5).map((f) => (
                        <span key={f.fuel_name} title={`${f.fuel_name}: ${fmtMoneyShort(f.amount)} ₽`}
                          style={{
                            width: `${(f.amount / (p.amount || 1)) * 100}%`,
                            background: fuelColor(f.fuel_name),
                          }} />
                      ))}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px]">
                      {p.by_fuel.slice(0, 4).map((f) => (
                        <span key={f.fuel_name} className="flex items-center gap-1">
                          <span className="inline-block size-1.5 rounded-full"
                            style={{ background: fuelColor(f.fuel_name) }} />
                          {f.fuel_name} {nf0.format((f.amount / (p.amount || 1)) * 100)} %
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Tooltip>
            <Popup className="cl-map-popup">
              <div className="w-[230px]">
                <div className="px-3 pb-2 pr-6 pt-2.5">
                  <div className="truncate text-[13px] font-semibold leading-tight text-foreground">{p.name}</div>
                  {p.address && (
                    <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                      <MapPin className="h-3 w-3 shrink-0 opacity-70" /><span className="truncate">{p.address}</span>
                    </div>
                  )}
                </div>
                <div className="border-t border-border/60 bg-muted/20 px-3 py-2">
                  <div className="grid grid-cols-2 gap-1.5">
                    <Stat icon={Wallet} label="Выручка" value={`${fmtMoneyShort(p.amount)} ₽`} />
                    <Stat icon={Gauge} label="Реализации" value={nf0.format(p.transactions)} />
                    <Stat icon={Fuel} label="Объём" value={fmtLiters(p.liters)} />
                    <Stat icon={Wallet} label="Ср. цена" value={p.avg_price ? `${nf2.format(p.avg_price)} ₽/л` : '—'} />
                  </div>
                </div>
              </div>
            </Popup>
          </CircleMarker>
          </Fragment>
        )
      })}
    </>
  )
}

/**
 * Подпись у точки: номер станции либо действующие цены по видам топлива.
 *
 * Отдельный маркер, а не tooltip круга: у слоя Leaflet только один tooltip, и
 * постоянная подпись затирала подсказку при наведении. `interactive: false` —
 * подпись не должна перехватывать наведение и клик у самой станции.
 */
function PointLabel({ p, radius, short, fill, mode, prices }: {
  p: FuelMapStation; radius: number; short: string; fill: string
  mode: 'none' | 'name' | 'prices'; prices: StationPrice[]
}) {
  if (mode === 'none') return null
  if (mode === 'prices' && prices.length === 0) return null
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string))
  const html = mode === 'prices'
    ? `<i class="cl-dot" style="background:${fill}"></i><span class="cl-plate">${
        prices.map((x) => `<b>${esc(x.fuel)}</b><span class="cl-num${x.stale ? ' cl-stale' : ''}">${
          nf2.format(x.price)}</span>`).join('')}</span>`
    : `<span class="cl-name">${esc(short)}</span>`
  const icon = L.divIcon({
    className: mode === 'prices' ? 'cl-map-priced' : 'cl-map-name',
    html,
    iconSize: [0, 0],
    iconAnchor: [mode === 'prices' ? -radius : -(radius + 3), 0],
  })
  return <Marker position={[p.latitude!, p.longitude!]} icon={icon} interactive={false} />
}

/** Легенда: у каждого типа шкалы свой вид — иначе цвет читается наугад. */
function MapLegend({ metric, th, maxVal, pts, dark }: {
  metric: Metric; th: number[]; maxVal: number; pts: FuelMapStation[]; dark: boolean
}) {
  const def = METRICS[metric]
  const fuels = useMemo(() => {
    const set = new Map<string, number>()
    pts.forEach((p) => p.top_fuel && set.set(p.top_fuel, (set.get(p.top_fuel) ?? 0) + 1))
    return [...set.entries()].sort((a, b) => b[1] - a[1])
  }, [pts])

  return (
    <div className="pointer-events-none absolute bottom-6 left-4 z-[1000] max-w-[260px] rounded-lg border border-border/70 bg-card/95 px-3 py-2 shadow-lg">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {def.label}
      </div>
      <div className="mb-1.5 text-[10px] leading-snug text-muted-foreground/80">{def.hint}</div>

      {def.kind === 'sequential' && (
        <>
          <div className="flex items-center gap-1">
            {(dark ? RAMP_DARK : RAMP_LIGHT).map((c: string) => <span key={c} className="h-3 w-7 rounded-sm" style={{ background: c }} />)}
          </div>
          <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
            <span>{th.length ? def.fmt(th[0]) : 'меньше'}</span>
            <span>{maxVal ? def.fmt(maxVal) : '—'}</span>
          </div>
        </>
      )}

      {def.kind === 'diverging' && (
        <>
          <div className="flex items-center gap-1">
            {[DIVERGING.down2, DIVERGING.down1, DIVERGING.mid, DIVERGING.up1, DIVERGING.up2].map((c) => (
              <span key={c} className="h-3 w-7 rounded-sm" style={{ background: c }} />
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
            <span>−25 % и ниже</span><span>0</span><span>+25 % и выше</span>
          </div>
        </>
      )}

      {def.kind === 'categorical' && (
        <div className="flex flex-col gap-0.5">
          {fuels.map(([name, n]) => (
            <span key={name} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <span className="inline-block size-2.5 rounded-full" style={{ background: fuelColor(name) }} />
              {name}<span className="opacity-60">· {n} АЗС</span>
            </span>
          ))}
        </div>
      )}

      <div className="mt-1.5 flex items-center gap-1.5 border-t border-border/60 pt-1.5 text-[10px] text-muted-foreground">
        <span className="inline-block size-2 rounded-full bg-blue-400/80" />
        <span className="inline-block size-3.5 rounded-full bg-blue-400/80" />
        <span>{def.size ? 'размер — выручка' : 'размер — та же величина'}</span>
      </div>
      <div className="mt-1 text-[10px] text-muted-foreground/80">
        Близкие АЗС собраны в группу с числом точек — приблизьте, чтобы разделить.
      </div>
    </div>
  )
}

export function FuelMapPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const dark = useIsDark()
  const qc = useQueryClient()
  const [metric, setMetric] = useState<Metric>('amount')
  const [view, setView] = useState<MapView>('value')
  // Шкала того, что видно в кадре: маркеры считают её по группам текущего зума и
  // сообщают наверх — легенда обязана подписывать те же ступени, что нарисованы.
  const [shownScale, setShownScale] = useState<{ th: number[]; max: number }>({ th: [], max: 0 })
  const [syncing, setSyncing] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['fuel-map', companyId, dateFrom, dateTo],
    queryFn: () => getFuelStationsMap(dateFrom, dateTo),
  })

  /**
   * Цены для выносок — из того же источника, что раздел «Цены» → «Разброс по сети»
   * (`/api/fuel/pricing/spread`): действующая цена станции это последняя, по которой
   * была продажа. Своего расчёта у карты нет намеренно — иначе на карте и в
   * прайс-листе оказались бы два разных числа. Запрос идёт только в виде «Цены».
   */
  const { data: spread } = useQuery({
    queryKey: ['fuel-map-prices', companyId, dateFrom, dateTo],
    queryFn: () => getFuelPriceSpread({ companyId, dateFrom, dateTo }),
    enabled: view === 'prices',
  })
  const prices = useMemo(() => {
    const m = new Map<number, StationPrice[]>()
    // Порог «залежавшейся» цены — тот же, что в «Разбросе»: втрое дольше типичного
    // шага сети по этому топливу. Иначе янтарём горело бы пол-карты.
    const staleAfter = new Map<number, number>()
    ;(spread?.fuels ?? []).forEach((f) => staleAfter.set(f.fuel_code, Math.max(14, Math.round(f.age_max * 0.75))))
    ;(spread?.lines ?? []).forEach((l) => {
      const arr = m.get(l.station_code) ?? []
      arr.push({ fuel: l.fuel_name, price: l.price, stale: l.age_days > (staleAfter.get(l.fuel_code) ?? 999) })
      m.set(l.station_code, arr)
    })
    // Порядок топлив внутри выноски — по цене вниз: глаз ищет «сколько стоит 95-й»,
    // а не строку номер три.
    m.forEach((arr) => arr.sort((a, b) => b.price - a.price))
    return m
  }, [spread])
  const pts = useMemo(() => (data?.stations ?? []).filter((s) => s.latitude != null && s.longitude != null), [data])
  const values = useMemo(
    () => pts.map((p) => METRICS[metric].get(p)).filter((v): v is number => v != null),
    [pts, metric],
  )
  const th = useMemo(() => quantiles(values), [values])
  const maxVal = useMemo(() => values.reduce((m, v) => Math.max(m, v), 0), [values])
  // Доля сети в подсказке всегда считается по ВЫРУЧКЕ: это единственная
  // величина, у которой доля осмысленна (доля от средней цены — бессмыслица).
  const totalVal = useMemo(() => pts.reduce((sum, p) => sum + p.amount, 0), [pts])

  async function refreshGeo() {
    setSyncing(true)
    try {
      await syncFuelStationsGeo()
      await qc.invalidateQueries({ queryKey: ['fuel-map'] })
    } finally { setSyncing(false) }
  }

  const mapLayers = useMapLayers()

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h2 className="flex items-center gap-2 text-base font-semibold"><MapPin className="h-4 w-4 text-blue-600 dark:text-blue-400" />Карта АЗС</h2>
          {data && <span className="text-xs text-muted-foreground">{data.with_coords} из {data.total} с координатами</span>}
        </div>
        <div className="flex items-center gap-2">
          {/* Вид карты. «Величина» отвечает на вопрос «где деньги сети», «точки» — на
              «где вообще стоят наши АЗС». Второй вопрос задают не реже первого, а
              раскрашенные круги разного калибра на него отвечают плохо: крупная
              станция перекрывает соседнюю, мелкая теряется. */}
          <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
            {([
              { v: 'value', l: 'Величина', t: 'Размер и цвет по выбранному показателю' },
              { v: 'dots', l: 'Точки', t: 'Все станции одинаковыми точками' },
              { v: 'prices', l: 'Цены', t: 'Действующие цены по видам топлива у каждой станции' },
            ] as { v: MapView; l: string; t: string }[]).map((o) => (
              <button key={o.v} type="button" onClick={() => setView(o.v)} title={o.t}
                aria-pressed={view === o.v}
                className={`px-2.5 py-1 text-xs rounded-[5px] transition-colors ${
                  view === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                {o.l}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">{view === 'value' ? 'Раскраска:' : 'Показатель:'}</span>
          <Select value={metric} onValueChange={(v) => setMetric(v as Metric)}>
            <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent className="z-[1200]">
              {(Object.keys(METRICS) as Metric[]).map((k) => <SelectItem key={k} value={k} className="text-xs">{METRICS[k].label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" className="h-8" onClick={refreshGeo} disabled={syncing}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${syncing ? 'animate-spin' : ''}`} />Координаты
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : pts.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-muted-foreground">
          Нет АЗС с координатами. Нажмите «Координаты», чтобы подтянуть из STS.
        </div>
      ) : (
        <div className="relative isolate min-h-[520px] flex-1">
          <MapLayerSwitch {...mapLayers} />
        <MapContainer crs={MAP_CRS} attributionControl={false} center={[60.7, 28.8]} zoom={9} scrollWheelZoom style={{ height: '100%', width: '100%', background: dark ? '#0b1220' : '#e5e7eb' }} preferCanvas>
            <MapTiles base={mapLayers.base} traffic={mapLayers.traffic} regions={mapLayers.regions} dark={dark} />
          <AttributionControl position="bottomright" prefix={MAP_ATTRIBUTION_PREFIX} />
            <MapInvalidate />
            <FitBounds pts={pts} />
            <StationMarkers pts={pts} metric={metric} th={th} dark={dark} total={totalVal}
              view={view} prices={prices}
              onScale={(t2, m2) => setShownScale((s) => (s.max === m2 && s.th.join() === t2.join() ? s : { th: t2, max: m2 }))} />
          </MapContainer>
          {/* Легенда — про раскраску и размер; в видах «точки» и «цены» ни того, ни
              другого нет, и шкала врала бы, что цвет что-то значит. */}
          {view === 'value' && (
            <MapLegend metric={metric} dark={dark} pts={pts}
              th={shownScale.th.length ? shownScale.th : th}
              maxVal={shownScale.max || maxVal} />
          )}
        </div>
      )}
    </div>
  )
}
