/**
 * «Карта проектов» — банк ЗУ поверх действующей сети.
 *
 * Главный вопрос карты: новая проект добавляет покрытие или делит трафик с
 * нашей же станцией? Поэтому станции сети показаны фоном, а вокруг проектов,
 * которые стоят к ним ближе порога, рисуется круг каннибализации.
 */
import { Fragment, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, TileLayer, CircleMarker, Circle, Popup } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2 } from 'lucide-react'
import { loadLocations } from '@/services/locationService'
import {
  getSitesMapPoints, QUADRANT_META, STAGE_META, FUNNEL_STAGES,
  type Quadrant, type SiteStage,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'

const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const CENTER: [number, number] = [58, 60]
type ColorBy = 'stage' | 'quadrant'

// Тайлы CARTO — те же, что на карте сети, чтобы разделы не выглядели чужими.
const TILE = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
const STAGE_COLOR: Record<string, string> = {
  lead: '#94a3b8', screening: '#0ea5e9', negotiation: '#3b82f6', dd: '#f59e0b',
  decision: '#f97316', contracting: '#8b5cf6', construction: '#14b8a6', live: '#10b981',
  on_hold: '#a1a1aa', archive: '#71717a',
}
const QUADRANT_COLOR: Record<Quadrant, string> = {
  do_now: '#10b981', unblock: '#f59e0b', option: '#0ea5e9', drop: '#ef4444', need_data: '#a1a1aa',
}

export function SitesMapPanel({ companyId }: { companyId: string }) {
  const [colorBy, setColorBy] = useState<ColorBy>('stage')
  const [showNetwork, setShowNetwork] = useState(true)
  const [stage, setStage] = useState<'' | SiteStage>('')
  const [detailId, setDetailId] = useState<string | null>(null)

  const pts = useQuery({ queryKey: ['sites-map', companyId], queryFn: () => getSitesMapPoints(companyId) })
  const net = useQuery({
    queryKey: ['locations', companyId, 'ev'],
    queryFn: () => loadLocations(companyId),
    enabled: showNetwork,
  })

  const points = useMemo(
    () => (pts.data?.points ?? []).filter((p) => !stage || p.stage === stage),
    [pts.data, stage],
  )
  // Координаты станции лежат в metadata (как на карте сети), а не колонками.
  const stations = useMemo(() => (net.data ?? []).flatMap((l) => {
    if (l.type !== 'ev_charging') return []
    const m = (l.metadata ?? {}) as Record<string, unknown>
    const lat = typeof m.latitude === 'number' ? m.latitude : null
    const lon = typeof m.longitude === 'number' ? m.longitude : null
    return lat != null && lon != null ? [{ id: l.id, name: l.name || l.code, lat, lon }] : []
  }), [net.data])
  const cannibalKm = pts.data?.thresholds.cannibalKm ?? 0.5

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
          {([['stage', 'По стадии'], ['quadrant', 'По решению']] as const).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setColorBy(k)}
              className={`px-2.5 py-1 text-sm rounded-[5px] transition-colors ${colorBy === k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
              {label}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => setShowNetwork((v) => !v)}
          className={`px-2.5 py-1 text-sm rounded-md border transition-colors ${showNetwork ? 'bg-primary text-primary-foreground border-transparent' : 'border-border text-muted-foreground hover:text-foreground'}`}>
          Станции сети{stations.length ? ` (${stations.length})` : ''}
        </button>
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5 flex-wrap">
          <button type="button" onClick={() => setStage('')}
            className={`px-2 py-1 text-sm rounded-[5px] ${stage === '' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>Все</button>
          {FUNNEL_STAGES.filter((s) => (pts.data?.points ?? []).some((p) => p.stage === s)).map((s) => (
            <button key={s} type="button" onClick={() => setStage(s)}
              className={`px-2 py-1 text-sm rounded-[5px] ${stage === s ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
              {STAGE_META[s].label}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground ml-auto">
          {pts.isLoading ? '…' : `${points.length} проектов с координатами`}
        </span>
      </div>

      <Card>
        <CardContent className="p-0">
          {pts.isLoading ? (
            <div className="flex justify-center py-24"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (
            <div className="h-[calc(100vh-260px)] min-h-[420px] w-full overflow-hidden rounded-lg">
              <MapContainer center={CENTER} zoom={4} style={{ height: '100%', width: '100%' }} preferCanvas>
                <TileLayer url={TILE} attribution="&copy; OpenStreetMap, &copy; CARTO" />

                {showNetwork && stations.map((l) => (
                  <CircleMarker key={`n-${l.id}`} center={[l.lat, l.lon]}
                    radius={3} pathOptions={{ color: '#64748b', fillColor: '#64748b', fillOpacity: 0.5, weight: 1 }}>
                    <Popup>
                      <div className="text-sm">
                        <div className="font-medium">{l.name}</div>
                        <div className="text-muted-foreground">действующая станция сети</div>
                      </div>
                    </Popup>
                  </CircleMarker>
                ))}

                {points.map((p) => {
                  const color = colorBy === 'stage'
                    ? (STAGE_COLOR[p.stage] ?? '#94a3b8')
                    : QUADRANT_COLOR[p.quadrant]
                  return (
                    <Fragment key={p.id}>
                      {/* Круг делёжа трафика — подсказка, а не объект: клики он пропускает
                          насквозь. Иначе заливка радиуса накрывала соседние станции сети, и
                          нажать на них, чтобы прочитать карточку, было нельзя (замечание
                          отдела развития от 06.08.2026). */}
                      {p.cannibalization && (
                        <Circle center={[p.lat, p.lon]} radius={cannibalKm * 1000} interactive={false}
                          pathOptions={{ color: '#f59e0b', weight: 1, fillOpacity: 0.06 }} />
                      )}
                      <CircleMarker center={[p.lat, p.lon]} radius={6}
                        pathOptions={{ color, fillColor: color, fillOpacity: 0.85, weight: 1 }}
                        eventHandlers={{ dblclick: () => setDetailId(p.id) }}>
                        <Popup>
                          <div className="text-sm space-y-1 min-w-[210px]">
                            <div className="font-medium">{p.address ?? p.city ?? 'Проект'}</div>
                            <div className="text-muted-foreground">{p.region ?? ''}{p.city ? ` · ${p.city}` : ''}</div>
                            <div>Стадия: <b>{p.stageLabel}</b></div>
                            <div>Решение: <b>{QUADRANT_META[p.quadrant].label}</b> (уверенность {p.confidence}%)</div>
                            {p.nearestStationKm != null && (
                              <div className={p.cannibalization ? 'text-amber-600' : ''}>
                                До ближайшей нашей станции: {nf1.format(p.nearestStationKm)} км
                                {p.cannibalization ? ' — делёж трафика' : ''}
                              </div>
                            )}
                            <button type="button" className="text-primary hover:underline"
                              onClick={() => setDetailId(p.id)}>Открыть карточку</button>
                          </div>
                        </Popup>
                      </CircleMarker>
                    </Fragment>
                  )
                })}
              </MapContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {colorBy === 'stage'
          ? FUNNEL_STAGES.map((s) => (
            <span key={s} className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: STAGE_COLOR[s] }} />{STAGE_META[s].label}
            </span>
          ))
          : (Object.keys(QUADRANT_COLOR) as Quadrant[]).map((k) => (
            <span key={k} className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: QUADRANT_COLOR[k] }} />{QUADRANT_META[k].label}
            </span>
          ))}
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-slate-500/60" />станция сети
        </span>
        <span>Круг — радиус {cannibalKm * 1000} м вокруг проекты, которая стоит вплотную к нашей станции.</span>
      </div>

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}
