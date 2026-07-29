/**
 * «Карта» — интерактивная карта сети АЗС ГИГ (Leaflet + тайлы CARTO, тема light/dark).
 * Координаты станций — из STS /v1/points (гео-паспорт FuelStation). Метрики за период
 * (реализации/объём/выручка из транзакций) → раскраска/размер точек. Аналог ЭЗС «Карта».
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Loader2, MapPin, Fuel, Wallet, Gauge, RefreshCw } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { fmtMoneyShort, fmtLiters } from '@/services/analyticsService'
import { getFuelStationsMap, syncFuelStationsGeo, type FuelMapStation } from '@/services/fuel/fuelMappingService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

type Metric = 'amount' | 'transactions' | 'liters'
const METRICS: Record<Metric, { label: string; get: (s: FuelMapStation) => number; fmt: (v: number) => string }> = {
  amount: { label: 'Выручка', get: (s) => s.amount, fmt: (v) => fmtMoneyShort(v) + ' ₽' },
  transactions: { label: 'Реализации', get: (s) => s.transactions, fmt: (v) => nf0.format(v) },
  liters: { label: 'Объём', get: (s) => s.liters, fmt: (v) => fmtLiters(v) },
}
/**
 * Величина кодируется ОДНОЙ hue от тусклого к яркому, а не радугой.
 *
 * Было viridis (фиолетовый → синий → бирюзовый → зелёный → жёлтый): формально
 * перцептивно-равномерная шкала, но пять разных цветов на карте читаются как
 * пять КАТЕГОРИЙ — «жёлтая станция» и «синяя станция» выглядят разными видами
 * объектов, а не большой и малой выручкой. Жёлтый и бирюзовый вдобавок спорят с
 * тёмной подложкой сильнее, чем несут смысла.
 *
 * Одна hue (синяя, акцент продукта) со ступенями по светлоте читается как шкала
 * сразу: тусклое — мало, яркое — много. Размер маркера несёт ту же величину
 * вторым каналом, поэтому порядок виден и в ч/б, и дальтонику.
 */
const RAMP = [
  'hsl(217 35% 42%)', 'hsl(217 50% 50%)', 'hsl(217 68% 57%)',
  'hsl(213 85% 64%)', 'hsl(205 96% 72%)',
]
const NODATA = 'hsl(215 14% 38%)'

function quantiles(values: number[]): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b)
  if (v.length < 5) return []
  return [0.2, 0.4, 0.6, 0.8].map((q) => v[Math.floor(q * (v.length - 1))])
}
function rampColor(value: number, th: number[]): string {
  if (value <= 0) return NODATA
  if (th.length === 0) return RAMP[2]
  let i = 0
  while (i < th.length && value > th[i]) i++
  return RAMP[i]
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

function StationMarkers({ pts, metric, th, dark, maxVal, total }: {
  pts: FuelMapStation[]; metric: Metric; th: number[]; dark: boolean; maxVal: number; total: number
}) {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const halo = dark ? '#0b1220' : '#ffffff'
  const get = METRICS[metric].get

  /**
   * Радиус — по КОРНЮ величины: глаз сравнивает площадь круга, и линейный радиус
   * преувеличил бы разницу вчетверо. Нижняя граница — чтобы станция без продаж
   * оставалась видимой точкой, а не пикселем.
   */
  const zoomK = Math.max(0.75, Math.min(1.5, 0.75 + (zoom - 7) * 0.12))
  const radiusOf = (st: FuelMapStation) => {
    const v = get(st)
    if (!(v > 0) || maxVal <= 0) return 6 * zoomK
    return (7 + 17 * Math.sqrt(v / maxVal)) * zoomK
  }
  // Крупные рисуются первыми и уходят под мелкие: иначе большая станция накрывает
  // соседнюю целиком — у Выборга три АЗС в паре километров сливались в пятно.
  const ordered = useMemo(
    () => [...pts].sort((a, b) => get(b) - get(a)),
    [pts, metric], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const ranks = useMemo(() => {
    const m = new Map<number, number>()
    ordered.forEach((p, i) => m.set(p.code, i + 1))
    return m
  }, [ordered])
  // Номера подписываем на крупном плане: на обзорном они налезают друг на друга
  // и мешают увидеть саму сеть.
  const withLabels = zoom >= 9

  return (
    <>
      {ordered.map((p) => {
        const value = get(p)
        const radius = radiusOf(p)
        const avg = p.liters ? p.amount / p.liters : 0
        const share = total > 0 ? (value / total) * 100 : 0
        const short = p.name.replace(/^АЗС\s*/i, '')
        return (
          <CircleMarker key={p.code} center={[p.latitude!, p.longitude!]} radius={radius}
            pathOptions={{ color: halo, weight: 2, fillColor: rampColor(value, th), fillOpacity: 0.9 }}
            eventHandlers={{
              // Наведение поднимает маркер над соседями и подсвечивает контур:
              // при плотной посадке иначе не понять, какой именно круг читаешь.
              mouseover: (e) => {
                e.target.bringToFront()
                e.target.setStyle({ color: 'hsl(205 96% 72%)', weight: 3 })
              },
              mouseout: (e) => e.target.setStyle({ color: halo, weight: 2 }),
            }}>
            {/* Тултип по наведению — обязательный слой карты: клик ради того,
                чтобы узнать имя точки, это лишний шаг в каждом просмотре. */}
            <Tooltip direction="top" offset={[0, -radius - 2]} opacity={1} className="cl-map-tip">
              <div className="min-w-[190px]">
                <div className="text-[12px] font-semibold leading-tight">{p.name}</div>
                {p.address && (
                  <div className="mt-0.5 text-[10px] opacity-70">{p.address}</div>
                )}
                <div className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
                  <span className="opacity-70">Выручка</span>
                  <span className="text-right font-medium tabular-nums">{fmtMoneyShort(p.amount)} ₽</span>
                  <span className="opacity-70">Объём</span>
                  <span className="text-right tabular-nums">{fmtLiters(p.liters)}</span>
                  <span className="opacity-70">Реализации</span>
                  <span className="text-right tabular-nums">{nf0.format(p.transactions)}</span>
                  <span className="opacity-70">Средняя цена</span>
                  <span className="text-right tabular-nums">{avg ? `${nf2.format(avg)} ₽/л` : '—'}</span>
                  <span className="opacity-70">Доля сети</span>
                  <span className="text-right tabular-nums">{nf1.format(share)} %</span>
                  <span className="opacity-70">Место по величине</span>
                  <span className="text-right tabular-nums">{ranks.get(p.code)} из {pts.length}</span>
                </div>
              </div>
            </Tooltip>
            {withLabels && (
              <Tooltip permanent direction="right" offset={[radius + 2, 0]} opacity={1}
                className="cl-map-label">{short}</Tooltip>
            )}
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
                    <Stat icon={Wallet} label="Ср. цена" value={avg ? `${nf2.format(avg)} ₽/л` : '—'} />
                  </div>
                </div>
              </div>
            </Popup>
          </CircleMarker>
        )
      })}
    </>
  )
}

/** Легенда шкалы: без неё цвет и размер — украшение, а не данные. */
function MapLegend({ metric, th, maxVal }: { metric: Metric; th: number[]; maxVal: number }) {
  const fmt = METRICS[metric].fmt
  return (
    <div className="pointer-events-none absolute bottom-6 left-4 z-[1000] rounded-lg border border-border/70 bg-card/95 px-3 py-2 shadow-lg">
      <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {METRICS[metric].label} за период
      </div>
      <div className="flex items-center gap-1">
        {RAMP.map((c) => (
          <span key={c} className="h-3 w-7 rounded-sm" style={{ background: c }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
        <span>{th.length ? fmt(th[0]) : 'меньше'}</span>
        <span>{maxVal ? fmt(maxVal) : '—'}</span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <span className="inline-block size-2 rounded-full bg-blue-400/80" />
        <span className="inline-block size-3.5 rounded-full bg-blue-400/80" />
        <span>размер — та же величина</span>
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
  const [syncing, setSyncing] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['fuel-map', companyId, dateFrom, dateTo],
    queryFn: () => getFuelStationsMap(dateFrom, dateTo),
  })
  const pts = useMemo(() => (data?.stations ?? []).filter((s) => s.latitude != null && s.longitude != null), [data])
  const th = useMemo(() => quantiles(pts.map((p) => METRICS[metric].get(p))), [pts, metric])
  const maxVal = useMemo(() => pts.reduce((m, p) => Math.max(m, METRICS[metric].get(p)), 0), [pts, metric])
  const totalVal = useMemo(() => pts.reduce((sum, p) => sum + METRICS[metric].get(p), 0), [pts, metric])

  async function refreshGeo() {
    setSyncing(true)
    try {
      await syncFuelStationsGeo()
      await qc.invalidateQueries({ queryKey: ['fuel-map'] })
    } finally { setSyncing(false) }
  }

  const tiles = dark
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h2 className="flex items-center gap-2 text-base font-semibold"><MapPin className="h-4 w-4 text-blue-600 dark:text-blue-400" />Карта АЗС</h2>
          {data && <span className="text-xs text-muted-foreground">{data.with_coords} из {data.total} с координатами</span>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Раскраска:</span>
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
          <MapContainer center={[60.7, 28.8]} zoom={9} scrollWheelZoom style={{ height: '100%', width: '100%', background: dark ? '#0b1220' : '#e5e7eb' }} preferCanvas>
            <TileLayer url={tiles} attribution='&copy; OpenStreetMap, &copy; CARTO' subdomains="abcd" maxZoom={20} />
            <MapInvalidate />
            <FitBounds pts={pts} />
            <StationMarkers pts={pts} metric={metric} th={th} dark={dark} maxVal={maxVal} total={totalVal} />
          </MapContainer>
          <MapLegend metric={metric} th={th} maxVal={maxVal} />
        </div>
      )}
    </div>
  )
}
