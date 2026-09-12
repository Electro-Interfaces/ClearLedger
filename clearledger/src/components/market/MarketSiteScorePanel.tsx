/**
 * «Оценка площадки» — главный экран для стройки (docs/MARKET-ROADMAP.md §9, этап 3).
 *
 * Точка на карте → паспорт места: кто рядом и жив ли он, что мы там съедим у себя же,
 * и сколько зарабатывают НАШИ объекты с таким же окружением. Последнее и есть прогноз:
 * метод аналогов, а не регрессия — его можно оспорить на совещании, потому что видно,
 * из каких именно объектов он собран.
 *
 * Экран заканчивается фразой, которую менеджер может сказать вслух, и списком, из
 * которого она собрана. Без второго первое было бы гаданием с процентами.
 */
import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { MapContainer, Marker, Popup, AttributionControl, useMapEvents } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import 'leaflet/dist/leaflet.css'
import { Crosshair, Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { getMarketSiteScore, type MarketSiteScore } from '@/services/marketService'

/** Тёмная тема приложения (класс `dark` на <html>) — как в карте рынка. */
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

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function money(v: number | null): string {
  if (v == null) return 'нет данных'
  if (v >= 1_000_000) return `${nf1.format(v / 1_000_000)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

/** Клик по карте выбирает точку — это и есть ввод экрана. */
function Picker({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) })
  return null
}

export function MarketSiteScorePanel() {
  const { companyId } = useCompany()
  const [radius, setRadius] = useState('5')
  const [place, setPlace] = useState('auto')
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null)
  const [score, setScore] = useState<MarketSiteScore | null>(null)
  const mapLayers = useMapLayers()
  const isDark = useIsDark()

  const ask = useMutation({
    mutationFn: (p: { lat: number; lon: number }) =>
      getMarketSiteScore(companyId, {
        lat: p.lat, lon: p.lon, radius_km: Number(radius), place,
      }),
    onSuccess: (data) => setScore(data),
  })

  const pick = (lat: number, lon: number) => {
    setPoint({ lat, lon })
    ask.mutate({ lat, lon })
  }

  const f = score?.forecast
  const verdict = !score
    ? 'Ткните в карту там, где думаете поставить станцию.'
    : f && f.analogues === 0
      ? 'Похожих наших объектов не нашлось — прогноз строить не на чем, но окружение видно ниже.'
      : `Рядом ${score.rivals.total} чужих точек, из них живых ${score.rivals.alive}. `
        + `Похожие наши объекты дают ${nf.format(f?.sessionsPerPeriod ?? 0)} сессий `
        + `и ${money(f?.revenuePerPeriod ?? null)} за ${f?.days ?? 90} дней `
        + `(половина из них — от ${nf.format(f?.sessionsLow ?? 0)} до ${nf.format(f?.sessionsHigh ?? 0)} сессий).`

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Crosshair className="size-4 text-primary" aria-hidden />
            {verdict}
          </span>
          {ask.isPending && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
          <Select value={radius} onValueChange={(v) => {
            setRadius(v)
            if (point) ask.mutate(point)
          }}>
            <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="3">Радиус 3 км (город)</SelectItem>
              <SelectItem value="5">Радиус 5 км</SelectItem>
              <SelectItem value="15">Радиус 15 км (трасса)</SelectItem>
            </SelectContent>
          </Select>
          <Select value={place} onValueChange={(v) => {
            setPlace(v)
            if (point) ask.mutate(point)
          }}>
            <SelectTrigger className="h-8 w-[170px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Тип места: определить</SelectItem>
              <SelectItem value="city">Город</SelectItem>
              <SelectItem value="highway">Трасса</SelectItem>
            </SelectContent>
          </Select>
          {point && (
            <span className="text-xs tabular-nums text-muted-foreground">
              {nf1.format(point.lat)}, {nf1.format(point.lon)}
              {score && (
                <span className="ml-2">
                  {score.placeClass === 'city' ? 'город' : 'трасса'}
                  {score.placeGuessed ? ' (определено автоматически)' : ''}
                </span>
              )}
            </span>
          )}
        </CardContent>
      </Card>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[3fr_2fr]">
        <Card className="min-h-[320px] overflow-hidden">
          <CardContent className="h-full p-0">
            <MapContainer center={[55.75, 37.62]} zoom={9} crs={MAP_CRS}
              attributionControl={false}
              style={{ height: '100%', minHeight: 320, width: '100%' }}>
              <MapTiles base={mapLayers.base} traffic={mapLayers.traffic}
                regions={mapLayers.regions} dark={isDark} />
              <AttributionControl position="bottomright" prefix={MAP_ATTRIBUTION_PREFIX} />
              <Picker onPick={pick} />
              {point && (
                <Marker position={[point.lat, point.lon]}>
                  <Popup>Место, которое оцениваем</Popup>
                </Marker>
              )}
            </MapContainer>
            <MapLayerSwitch {...mapLayers} />
          </CardContent>
        </Card>

        <div className="min-h-0 space-y-3 overflow-auto">
          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-headline text-sm font-semibold">Кто рядом</div>
              {!score || score.rivals.total === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {score ? 'В радиусе чужих сетевых точек нет. Это либо свободное место, '
                    + 'либо место, где рынок ещё не наблюдали.' : 'Выберите точку на карте.'}
                </p>
              ) : (
                <>
                  <p className="mb-2 text-xs text-muted-foreground">
                    портов {score.rivals.ports}, цена рынка{' '}
                    {score.rivals.marketPricePerKwh != null
                      ? `${nf1.format(score.rivals.marketPricePerKwh)} ₽/кВт·ч`
                      : 'не наблюдалась'}
                  </p>
                  <ul className="space-y-1">
                    {score.rivals.list.map((r) => (
                      <li key={r.id} className="flex items-baseline justify-between gap-2 text-xs">
                        <span className="min-w-0 truncate">
                          {r.name}
                          {r.operatorName && <span className="text-muted-foreground"> · {r.operatorName}</span>}
                          <span className="text-muted-foreground">
                            {' · '}{r.alive ? 'заряжали недавно' : 'молчит'}
                          </span>
                        </span>
                        <span className="shrink-0 tabular-nums">
                          {nf1.format(r.distanceKm)} км
                          {r.pricePerKwh != null ? ` · ${nf1.format(r.pricePerKwh)} ₽` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-headline text-sm font-semibold">Что съедим у себя</div>
              {!score || score.cannibalization.ourNearby === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Наших объектов в радиусе нет — каннибализации не будет.
                </p>
              ) : (
                <ul className="space-y-1">
                  {score.cannibalization.list.map((o) => (
                    <li key={o.locationId} className="flex items-baseline justify-between gap-2 text-xs">
                      <span className="min-w-0 truncate">{o.name}
                        {o.city && <span className="text-muted-foreground"> · {o.city}</span>}
                      </span>
                      <span className="shrink-0 tabular-nums">
                        {nf1.format(o.distanceKm)} км · {nf.format(o.sessions)} сессий
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-headline text-sm font-semibold">Чего стоит вход</div>
              {!score || score.entry.projectsNearby === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Рядом нет наших площадок из «Проектов» — опереться на их опыт
                  присоединения не на что.
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <div className="text-muted-foreground">присоединение</div>
                      <div className="font-medium">{money(score.entry.tpCostMedian)}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">срок присоединения</div>
                      <div className="font-medium">
                        {score.entry.tpTermMonthsMedian != null
                          ? `${nf1.format(score.entry.tpTermMonthsMedian)} мес`
                          : 'нет данных'}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">свободная мощность</div>
                      <div className="font-medium">
                        {score.entry.freePowerKwtMedian != null
                          ? `${nf1.format(score.entry.freePowerKwtMedian)} кВт`
                          : 'нет данных'}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground">аренда в месяц</div>
                      <div className="font-medium">{money(score.entry.rentMonthMedian)}</div>
                    </div>
                  </div>
                  {score.entry.paybackPeriods != null && (
                    <p className="mt-2 text-xs">
                      Вход обойдётся примерно в {money(score.entry.capexEstimate)} — это
                      не меньше {nf1.format(score.entry.paybackPeriods)} таких периодов
                      выручки, без учёта энергии и обслуживания.
                    </p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">{score.entry.basis}</p>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-headline text-sm font-semibold">Из чего собран прогноз</div>
              {!f || f.analogues === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Аналогов нет: среди наших работающих объектов не нашлось таких же по
                  числу живых конкурентов рядом. Прогноз не выдумываем.
                </p>
              ) : (
                <>
                  <p className="mb-2 text-xs text-muted-foreground">
                    {f.method}; объектов в выборке {f.analogues}, из них заряжают{' '}
                    {f.working}. Показана медиана работающих и разброс: решение
                    принимают по диапазону, а не по одной цифре.
                  </p>
                  {f.zeroDemand > 0 && (
                    <p className="mb-2 text-xs text-warning">
                      {f.zeroDemand} похожих объектов не заряжают вовсе. С их учётом
                      медиана — {nf.format(f.sessionsAllMedian ?? 0)} сессий: столько
                      даёт место такого типа в среднем по сети, а не в удачном случае.
                    </p>
                  )}
                  <ul className="space-y-1">
                    {f.sample.map((a) => (
                      <li key={a.locationId} className="flex items-baseline justify-between gap-2 text-xs">
                        <span className="min-w-0 truncate">{a.name}
                          {a.city && <span className="text-muted-foreground"> · {a.city}</span>}
                          <span className="text-muted-foreground"> · соседей {a.rivals}</span>
                        </span>
                        <span className="shrink-0 tabular-nums">
                          {nf.format(a.sessions)} сессий · {money(a.revenue)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
