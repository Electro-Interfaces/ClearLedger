/**
 * «Карта» — интерактивная карта сети ЭЗС (Leaflet + тайлы CARTO, тема light/dark).
 * Станции из справочника (service_locations, /api/locations): координаты и паспорт
 * в metadata. Плюс метрики сессий по станции (/charge-sessions/station-metrics,
 * джойн по location_id) → раскраска/размер точек по выручке/сессиям/загрузке.
 * Слои раскраски, размер, фильтры, адаптивная легенда, размер точек растёт с зумом.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Loader2, Search, MapPin, Zap, Plug, Hash, Gauge, Wallet, type LucideIcon } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { loadLocations } from '@/services/locationService'
import type { ServiceLocation } from '@/types/location'
import { getStationMetrics, type StationMetric } from '@/services/overviewService'
import { fmtMoneyShort } from '@/services/analyticsService'

const ALL = '__all__'
const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const SINGLE = '#3b82f6'

// ── справочники раскраски (из нормализованного паспорта станции) ──
const OP: Record<string, { label: string; color: string }> = {
  working: { label: 'Работает', color: '#10b981' },
  not_working: { label: 'Не работает', color: '#ef4444' },
  on_repair: { label: 'На ремонте', color: '#f59e0b' },
  maintenance: { label: 'Обслуживание', color: '#3b82f6' },
  unknown: { label: 'Неизвестно', color: '#94a3b8' },
}
const opMeta = (s: string) => OP[s] ?? OP.unknown

const LINK: Record<string, { label: string; color: string }> = {
  ok: { label: 'С сессиями', color: '#10b981' },
  no_match: { label: 'Без сессий (сирота)', color: '#94a3b8' },
  conflict: { label: 'Конфликт связи', color: '#f59e0b' },
  review: { label: 'На проверке', color: '#3b82f6' },
  unknown: { label: 'Нет данных', color: '#64748b' },
}
const linkMeta = (s: string) => LINK[s] ?? LINK.unknown

const POWER_BUCKETS = [
  { key: 'p0', label: '< 50 кВт', color: '#93c5fd', test: (p: number) => p < 50 },
  { key: 'p1', label: '50–99 кВт', color: '#60a5fa', test: (p: number) => p < 100 },
  { key: 'p2', label: '100–149 кВт', color: '#3b82f6', test: (p: number) => p < 150 },
  { key: 'p3', label: '≥ 150 кВт', color: '#1d4ed8', test: () => true },
]
const POWER_NA = { key: 'pna', label: 'Мощн. не указана', color: '#64748b' }
function powerMeta(power: number | null): { key: string; label: string; color: string } {
  if (power == null) return POWER_NA
  return POWER_BUCKETS.find((b) => b.test(power)) ?? POWER_BUCKETS[POWER_BUCKETS.length - 1]
}

// ── метрики сессий по станции (раскраска/размер) ──
type Metric = 'revenue' | 'sessions' | 'utilization'
const METRICS: Record<Metric, { label: string; get: (m: StationMetric) => number; fmt: (v: number) => string }> = {
  revenue: { label: 'Выручка', get: (m) => m.amount, fmt: (v) => fmtMoneyShort(v) + ' ₽' },
  sessions: { label: 'Сессии', get: (m) => m.sessions, fmt: (v) => nf0.format(v) },
  utilization: { label: 'Загрузка', get: (m) => m.utilization_pct, fmt: (v) => v.toFixed(1) + '%' },
}
const RAMP = ['#60a5fa', '#34d399', '#fbbf24', '#fb923c', '#ef4444'] // низкая → высокая
const NODATA = '#4b5563'
const isMetric = (c: string): c is Metric => c === 'revenue' || c === 'sessions' || c === 'utilization'

/** Пороги-квантили (4 разделителя → 5 корзин) по возрастанию положительных значений. */
function quantiles(values: number[]): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b)
  if (v.length < 5) return []
  return [0.2, 0.4, 0.6, 0.8].map((q) => v[Math.floor(q * (v.length - 1))])
}
function rampColor(value: number, th: number[]): string {
  if (th.length === 0) return RAMP[2]
  let i = 0
  while (i < th.length && value > th[i]) i++
  return RAMP[i]
}

type ColorBy = 'single' | 'status' | 'link' | 'power' | Metric
const COLOR_BY: { v: ColorBy; label: string }[] = [
  { v: 'single', label: 'Единый цвет' }, { v: 'status', label: 'Статус' },
  { v: 'link', label: 'Связь с сессиями' }, { v: 'power', label: 'Мощность' },
  { v: 'revenue', label: 'Выручка (метрика)' }, { v: 'sessions', label: 'Сессии (метрика)' },
  { v: 'utilization', label: 'Загрузка (метрика)' },
]
type SizeBy = 'fixed' | Metric
const SIZE_BY: { v: SizeBy; label: string }[] = [
  { v: 'fixed', label: 'Одинаковый' }, { v: 'revenue', label: 'по выручке' },
  { v: 'sessions', label: 'по сессиям' }, { v: 'utilization', label: 'по загрузке' },
]
function catColor(p: Pt, by: 'single' | 'status' | 'link' | 'power'): string {
  if (by === 'status') return opMeta(p.opStatus).color
  if (by === 'link') return linkMeta(p.linkStatus).color
  if (by === 'power') return powerMeta(p.power).color
  return SINGLE
}

interface Pt {
  id: string; name: string; number: string
  lat: number; lon: number
  region: string; city: string; address: string
  power: number | null; connectors: number | null
  opStatus: string; linkStatus: string
  manufacturer: string; stage: string; owner: string
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v))

function toPoint(l: ServiceLocation): Pt | null {
  const m = (l.metadata ?? {}) as Record<string, unknown>
  const lat = num(m.latitude), lon = num(m.longitude)
  if (lat === null || lon === null) return null
  const city = str(m.cityName)
  const addr = [city, str(m.street), str(m.houseNumber)].filter(Boolean).join(', ') || str(l.address)
  return {
    id: l.id, name: l.name || str(m.number) || l.code, number: str(m.number) || l.code,
    lat, lon, region: str(m.federalSubject) || '—', city, address: addr,
    power: num(m.maxPowerKw), connectors: num(m.connectorCount),
    opStatus: l.operationalStatus || 'unknown', linkStatus: str(m.linkStatus) || 'unknown',
    manufacturer: str(m.manufacturer) || '—', stage: str(m.stage) || '—', owner: str(m.ownerTitle) || '—',
  }
}

/** Тёмная тема приложения (класс `dark` на <html>) — реактивно через MutationObserver. */
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

function FitBounds({ points }: { points: Pt[] }) {
  const map = useMap()
  useEffect(() => {
    const sane = points.filter((p) => p.lat >= 40 && p.lat <= 78 && p.lon >= 19 && p.lon <= 180)
    if (sane.length) map.fitBounds(L.latLngBounds(sane.map((p) => [p.lat, p.lon] as [number, number])), { padding: [30, 30] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map])
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

// ── строительные блоки карточки станции в попапе ──
/** Нейтральный чип паспорта (номер, мощность, коннекторы, регион). */
function Chip({ icon: Icon, children }: { icon?: LucideIcon; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-[3px] text-[10px] font-medium text-muted-foreground">
      {Icon ? <Icon className="h-2.5 w-2.5 opacity-70" /> : null}{children}
    </span>
  )
}
/** Мини-тайл метрики: подпись + крупное значение. */
function Stat({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/60 px-2 py-1.5">
      <div className="flex items-center gap-1 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="h-2.5 w-2.5" />{label}
      </div>
      <div className="mt-0.5 text-[13px] font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  )
}
/** Горизонтальный прогресс-бар «параллельная графика» для процентных метрик. */
function Bar({ label, pct, color }: { label: string; pct: number; color: string }) {
  const w = Math.max(0, Math.min(100, pct))
  return (
    <div>
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums text-foreground">{pct.toFixed(pct < 10 ? 1 : 0)}%</span>
      </div>
      <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full transition-[width]" style={{ width: `${w}%`, background: color }} />
      </div>
    </div>
  )
}
/** Цвет полосы «Успех» по величине (семантика: хорошо/средне/плохо). */
const successColor = (pct: number) => (pct >= 75 ? 'hsl(var(--success))' : pct >= 50 ? 'hsl(var(--warning))' : 'hsl(var(--error))')

/** Маркеры: цвет и размер по функциям (слои), базовый радиус растёт с зумом.
 *  Против «каши» в плотных городах: halo-обводка цветом фона карты разделяет
 *  соприкасающиеся круги, полупрозрачная заливка показывает наложения, а z-order
 *  (крупные снизу, мелкие сверху) не даёт большим кругам «съедать» соседей. */
function StationMarkers({ points, colorFn, sizeFn, metricMap, dark }: {
  points: Pt[]; colorFn: (p: Pt) => string; sizeFn: (p: Pt) => number; metricMap: Map<string, StationMetric>; dark: boolean
}) {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const base = Math.max(3, Math.min(13, (zoom - 3) * 1.5 + 3))
  const halo = dark ? '#0b1220' : '#ffffff'
  // рисуем крупные первыми (внизу), мелкие последними (поверх) → мелкие не теряются
  const ordered = useMemo(() => [...points].sort((a, b) => sizeFn(b) - sizeFn(a)), [points, sizeFn])
  return (
    <>
      {ordered.map((p) => {
        const mx = metricMap.get(p.id)
        const op = opMeta(p.opStatus)
        const radius = Math.min(26, base * sizeFn(p))
        return (
          <CircleMarker key={p.id} center={[p.lat, p.lon]} radius={radius}
            pathOptions={{ color: halo, weight: 1.4, fillColor: colorFn(p), fillOpacity: 0.82 }}>
            <Popup className="cl-map-popup">
              <div className="w-[240px]">
                {/* шапка: имя + адрес + чипы паспорта (место справа сверху — под крестик) */}
                <div className="px-3 pb-2 pr-6 pt-2.5">
                  <div className="truncate text-[13px] font-semibold leading-tight text-foreground">{p.name}</div>
                  {p.address && (
                    <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                      <MapPin className="h-3 w-3 shrink-0 opacity-70" /><span className="truncate">{p.address}</span>
                    </div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-1">
                    <span className="inline-flex items-center gap-1 rounded-md px-1.5 py-[3px] text-[10px] font-medium"
                      style={{ background: `${op.color}1f`, color: op.color }}>
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: op.color }} />{op.label}
                    </span>
                    <Chip icon={Hash}>{p.number}</Chip>
                    {p.power != null && <Chip icon={Zap}>{nf0.format(p.power)} кВт</Chip>}
                    {p.connectors != null && <Chip icon={Plug}>{nf0.format(p.connectors)}</Chip>}
                    {p.region !== '—' && <Chip icon={MapPin}>{p.region}</Chip>}
                  </div>
                </div>
                {/* метрики: два тайла + параллельные полосы загрузки/успеха */}
                {mx ? (
                  <div className="border-t border-border/60 bg-muted/20 px-3 py-2">
                    <div className="grid grid-cols-2 gap-1.5">
                      <Stat icon={Wallet} label="Выручка" value={`${fmtMoneyShort(mx.amount)} ₽`} />
                      <Stat icon={Gauge} label="Сессии" value={nf0.format(mx.sessions)} />
                    </div>
                    <div className="mt-2 space-y-1.5">
                      <Bar label="Загрузка" pct={mx.utilization_pct} color="hsl(var(--primary))" />
                      <Bar label="Успех сессий" pct={mx.success_pct} color={successColor(mx.success_pct)} />
                    </div>
                  </div>
                ) : (
                  <div className="border-t border-border/60 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
                    Нет сессий за выбранный период
                  </div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        )
      })}
    </>
  )
}

/** Компактный фильтр-селект с опцией «все». */
function FSelect({ value, onChange, all, options, w }: {
  value: string; onChange: (v: string) => void; all: string; options: { v: string; label: string }[]; w: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={`h-8 ${w} text-xs`}><SelectValue /></SelectTrigger>
      <SelectContent className="z-[1200]">
        <SelectItem value={ALL} className="text-xs">{all}</SelectItem>
        {options.map((o) => <SelectItem key={o.v} value={o.v} className="text-xs">{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

export function ChargeMapPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const dark = useIsDark()
  const { data, isLoading } = useQuery({ queryKey: ['locations', companyId], queryFn: () => loadLocations(companyId) })
  const { data: metricsData } = useQuery({
    queryKey: ['station-metrics', companyId, dateFrom, dateTo],
    queryFn: () => getStationMetrics({ companyId, dateFrom, dateTo }),
  })
  const [search, setSearch] = useState('')
  const [region, setRegion] = useState(ALL)
  const [status, setStatus] = useState(ALL)
  const [link, setLink] = useState(ALL)
  const [power, setPower] = useState(ALL)
  const [manuf, setManuf] = useState(ALL)
  const [stage, setStage] = useState(ALL)
  const [owner, setOwner] = useState(ALL)
  const [colorBy, setColorBy] = useState<ColorBy>('single')
  const [sizeBy, setSizeBy] = useState<SizeBy>('fixed')

  const metricMap = useMemo(() => new Map((metricsData?.metrics ?? []).map((m) => [m.location_id, m])), [metricsData])
  const allPoints = useMemo(() => (data ?? []).map(toPoint).filter((p): p is Pt => p !== null), [data])
  const uniq = (sel: (p: Pt) => string) => [...new Set(allPoints.map(sel))].filter((x) => x !== '—').sort((a, b) => a.localeCompare(b, 'ru'))
  const regions = useMemo(() => uniq((p) => p.region), [allPoints])
  const statuses = useMemo(() => [...new Set(allPoints.map((p) => p.opStatus))], [allPoints])
  const links = useMemo(() => [...new Set(allPoints.map((p) => p.linkStatus))], [allPoints])
  const manufs = useMemo(() => uniq((p) => p.manufacturer), [allPoints])
  const stages = useMemo(() => uniq((p) => p.stage), [allPoints])
  const owners = useMemo(() => uniq((p) => p.owner), [allPoints])

  const points = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allPoints.filter((p) => {
      if (region !== ALL && p.region !== region) return false
      if (status !== ALL && p.opStatus !== status) return false
      if (link !== ALL && p.linkStatus !== link) return false
      if (power !== ALL && powerMeta(p.power).key !== power) return false
      if (manuf !== ALL && p.manufacturer !== manuf) return false
      if (stage !== ALL && p.stage !== stage) return false
      if (owner !== ALL && p.owner !== owner) return false
      if (q && !`${p.name} ${p.city} ${p.address} ${p.number}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [allPoints, search, region, status, link, power, manuf, stage, owner])

  // пороги раскраски по метрике (квантили над видимыми точками)
  const colorTh = useMemo(() => {
    if (!isMetric(colorBy)) return []
    const g = METRICS[colorBy].get
    return quantiles(points.map((p) => { const m = metricMap.get(p.id); return m ? g(m) : 0 }))
  }, [points, colorBy, metricMap])
  const colorFn = (p: Pt): string => {
    if (isMetric(colorBy)) { const m = metricMap.get(p.id); return m ? rampColor(METRICS[colorBy].get(m), colorTh) : NODATA }
    return catColor(p, colorBy)
  }

  // размер по метрике (sqrt-нормировка к максимуму)
  const sizeMax = useMemo(() => {
    if (sizeBy === 'fixed') return 0
    const g = METRICS[sizeBy].get
    return Math.max(1, ...points.map((p) => { const m = metricMap.get(p.id); return m ? g(m) : 0 }))
  }, [points, sizeBy, metricMap])
  const sizeFn = (p: Pt): number => {
    if (sizeBy === 'fixed') return 1
    const m = metricMap.get(p.id)
    if (!m) return 0.5
    return 0.6 + 1.7 * Math.sqrt(METRICS[sizeBy].get(m) / sizeMax)
  }

  // легенда: категориальная (статус/связь/мощность) или градиент (метрика)
  const catLegend = useMemo(() => {
    if (colorBy === 'single' || isMetric(colorBy)) return []
    const c = new Map<string, { label: string; color: string; count: number }>()
    for (const p of points) {
      const m = colorBy === 'status' ? { key: p.opStatus, ...opMeta(p.opStatus) }
        : colorBy === 'link' ? { key: p.linkStatus, ...linkMeta(p.linkStatus) }
        : powerMeta(p.power)
      const e = c.get(m.key) ?? { label: m.label, color: m.color, count: 0 }
      e.count++; c.set(m.key, e)
    }
    return [...c.values()]
  }, [points, colorBy])
  const noMetricCount = useMemo(() => (isMetric(colorBy) ? points.filter((p) => !metricMap.has(p.id)).length : 0), [points, colorBy, metricMap])

  if (isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (allPoints.length === 0) return <div className="p-8 text-center text-sm text-muted-foreground">Нет станций с координатами. Загрузите справочник станций ЭЗС.</div>

  const tileUrl = dark
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      {/* фильтры + слои */}
      <div className="flex flex-wrap items-center gap-2 shrink-0">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск: станция, город, адрес…" className="h-8 w-[210px] pl-8 text-xs" />
        </div>
        <FSelect value={region} onChange={setRegion} all="Все регионы" options={regions.map((r) => ({ v: r, label: r }))} w="w-[170px]" />
        <FSelect value={status} onChange={setStatus} all="Все статусы" options={statuses.map((s) => ({ v: s, label: opMeta(s).label }))} w="w-[140px]" />
        <FSelect value={link} onChange={setLink} all="Связь: все" options={links.map((s) => ({ v: s, label: linkMeta(s).label }))} w="w-[170px]" />
        <FSelect value={power} onChange={setPower} all="Мощность: все" options={[...POWER_BUCKETS, POWER_NA].map((b) => ({ v: b.key, label: b.label }))} w="w-[160px]" />
        <FSelect value={manuf} onChange={setManuf} all="Производитель: все" options={manufs.map((x) => ({ v: x, label: x }))} w="w-[170px]" />
        <FSelect value={stage} onChange={setStage} all="Этап: все" options={stages.map((x) => ({ v: x, label: x }))} w="w-[150px]" />
        <FSelect value={owner} onChange={setOwner} all="Владелец: все" options={owners.map((x) => ({ v: x, label: x }))} w="w-[170px]" />
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1"><span className="text-xs text-muted-foreground">Цвет:</span>
            <Select value={colorBy} onValueChange={(v) => setColorBy(v as ColorBy)}>
              <SelectTrigger className="h-8 w-[175px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="z-[1200]">{COLOR_BY.map((o) => <SelectItem key={o.v} value={o.v} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-1"><span className="text-xs text-muted-foreground">Размер:</span>
            <Select value={sizeBy} onValueChange={(v) => setSizeBy(v as SizeBy)}>
              <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="z-[1200]">{SIZE_BY.map((o) => <SelectItem key={o.v} value={o.v} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* счётчик + адаптивная легенда */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground shrink-0">
        <span>На карте: <b className="text-foreground">{nf0.format(points.length)}</b> из {nf0.format(allPoints.length)} станций</span>
        {catLegend.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: l.color }} />{l.label} · <b className="text-foreground">{nf0.format(l.count)}</b>
          </span>
        ))}
        {isMetric(colorBy) && (
          <>
            <span className="inline-flex items-center gap-1.5">{METRICS[colorBy].label}: меньше
              <span className="h-2.5 w-20 rounded" style={{ background: `linear-gradient(to right, ${RAMP.join(', ')})` }} /> больше
            </span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: NODATA }} />нет сессий · <b className="text-foreground">{nf0.format(noMetricCount)}</b></span>
          </>
        )}
      </div>

      {/* карта — isolate: свой stacking-контекст, чтобы z-index панелей Leaflet
          (popupPane 700 и др.) не всплывал поверх модальных диалогов приложения */}
      <div className="isolate min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        <MapContainer center={[62, 94]} zoom={3} style={{ height: '100%', width: '100%', background: 'hsl(var(--muted))' }} scrollWheelZoom preferCanvas>
          <TileLayer key={dark ? 'dark' : 'light'} url={tileUrl}
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            subdomains="abcd" maxZoom={19} />
          <FitBounds points={allPoints} />
          <MapInvalidate />
          <StationMarkers points={points} colorFn={colorFn} sizeFn={sizeFn} metricMap={metricMap} dark={dark} />
        </MapContainer>
      </div>
    </div>
  )
}
