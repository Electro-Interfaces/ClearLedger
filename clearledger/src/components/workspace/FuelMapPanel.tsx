/**
 * «Карта» — интерактивная карта сети АЗС ГИГ (Leaflet + тайлы CARTO, тема light/dark).
 * Координаты станций — из STS /v1/points (гео-паспорт FuelStation). Метрики за период
 * (реализации/объём/выручка из транзакций) → раскраска/размер точек. Аналог ЭЗС «Карта».
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Loader2, MapPin, Fuel, Wallet, Gauge, RefreshCw } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { fmtMoneyShort, fmtLiters } from '@/services/analyticsService'
import { getFuelStationsMap, syncFuelStationsGeo, type FuelMapStation } from '@/services/fuel/fuelMappingService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

type Metric = 'amount' | 'transactions' | 'liters'
const METRICS: Record<Metric, { label: string; get: (s: FuelMapStation) => number; fmt: (v: number) => string }> = {
  amount: { label: 'Выручка', get: (s) => s.amount, fmt: (v) => fmtMoneyShort(v) + ' ₽' },
  transactions: { label: 'Реализации', get: (s) => s.transactions, fmt: (v) => nf0.format(v) },
  liters: { label: 'Объём', get: (s) => s.liters, fmt: (v) => fmtLiters(v) },
}
// viridis — перцептивно-равномерная, colorblind-safe (низкая → высокая величина).
const RAMP = ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725']
const NODATA = '#4b5563'

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

function StationMarkers({ pts, metric, th, dark, maxVal }: {
  pts: FuelMapStation[]; metric: Metric; th: number[]; dark: boolean; maxVal: number
}) {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const base = Math.max(4, Math.min(14, (zoom - 3) * 1.6 + 4))
  const halo = dark ? '#0b1220' : '#ffffff'
  const get = METRICS[metric].get
  const sizeFn = (s: FuelMapStation) => (maxVal > 0 ? 0.4 + Math.sqrt(get(s) / maxVal) : 0.6)
  const ordered = useMemo(() => [...pts].sort((a, b) => sizeFn(b) - sizeFn(a)), [pts, metric]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {ordered.map((p) => {
        const radius = Math.min(28, base * sizeFn(p))
        const avg = p.liters ? p.amount / p.liters : 0
        return (
          <CircleMarker key={p.code} center={[p.latitude!, p.longitude!]} radius={radius}
            pathOptions={{ color: halo, weight: 1.4, fillColor: rampColor(get(p), th), fillOpacity: 0.82 }}>
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

export function FuelMapPanel({ dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const dark = useIsDark()
  const qc = useQueryClient()
  const [metric, setMetric] = useState<Metric>('amount')
  const [syncing, setSyncing] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['fuel-map', dateFrom, dateTo],
    queryFn: () => getFuelStationsMap(dateFrom, dateTo),
  })
  const pts = useMemo(() => (data?.stations ?? []).filter((s) => s.latitude != null && s.longitude != null), [data])
  const th = useMemo(() => quantiles(pts.map((p) => METRICS[metric].get(p))), [pts, metric])
  const maxVal = useMemo(() => pts.reduce((m, p) => Math.max(m, METRICS[metric].get(p)), 0), [pts, metric])

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
        <div className="isolate min-h-[520px] flex-1">
          <MapContainer center={[60.7, 28.8]} zoom={9} scrollWheelZoom style={{ height: '100%', width: '100%', background: dark ? '#0b1220' : '#e5e7eb' }} preferCanvas>
            <TileLayer url={tiles} attribution='&copy; OpenStreetMap, &copy; CARTO' subdomains="abcd" maxZoom={20} />
            <MapInvalidate />
            <FitBounds pts={pts} />
            <StationMarkers pts={pts} metric={metric} th={th} dark={dark} maxVal={maxVal} />
          </MapContainer>
        </div>
      )}
    </div>
  )
}
