/**
 * «Оценка площадки» — главный экран для стройки (docs/MARKET-ROADMAP.md §9, этап 3).
 *
 * Место на карте → паспорт: кто рядом и жив ли он, что мы там съедим у себя же, чего
 * стоит вход и сколько зарабатывают НАШИ объекты с таким же окружением. Последнее и
 * есть прогноз: метод аналогов, а не регрессия — его можно оспорить на совещании,
 * потому что видно, из каких именно объектов он собран.
 *
 * Устройство экрана продиктовано тем, как им пользуются. Место выбирают не один раз:
 * сравнивают два перекрёстка, меняют радиус, возвращаются к первому варианту. Поэтому:
 *
 * 1. Условия отделены от результата. Прежде вердикт, два селектора и координаты жили в
 *    одной строке, и было не видно, где ввод, а где ответ.
 * 2. Расчёт идёт по команде, а не по клику. Клик по карте выбирает место, условия
 *    меняются свободно, считает кнопка. Прежде каждое движение запускало пересчёт, а
 *    вернуться к прежним условиям было нельзя.
 * 3. Оценённые места остаются на экране: к любому можно вернуться и сравнить — ради
 *    этого экран и открывают (замечание МАГа 13.09.2026).
 * 4. Радиус нарисован на карте: круг показывает, что именно попало в оценку.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { MapContainer, Circle, Marker, Popup, AttributionControl,
  useMap, useMapEvents } from 'react-leaflet'
import { MAP_ATTRIBUTION_PREFIX, MAP_CRS } from '@/lib/mapTiles'
import { MapLayerSwitch, MapTiles, useMapLayers } from '@/components/map/MapLayers'
import { MapResize } from '@/components/map/MapResize'
import 'leaflet/dist/leaflet.css'
import { Crosshair, Loader2, Maximize2, Minimize2, RotateCcw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useFullscreenPanel } from '@/hooks/useFullscreenPanel'
import { useCompany } from '@/contexts/CompanyContext'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
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

type Точка = { lat: number; lon: number }

/** Условия расчёта: по ним видно, не устарел ли показанный результат. */
type Условия = { point: Точка; radius: string; place: string }

/** Оценка, сохранённая на время работы: к ней можно вернуться и сравнить. */
type Оценка = { id: string; условия: Условия; score: MarketSiteScore }

const РАДИУСЫ = [
  { v: '3', label: '3 км — город' },
  { v: '5', label: '5 км' },
  { v: '15', label: '15 км — трасса' },
]

const МЕСТА = [
  { v: 'auto', label: 'определить по окружению' },
  { v: 'city', label: 'город' },
  { v: 'highway', label: 'трасса' },
]

/** Клик по карте выбирает место — но не запускает расчёт: это делает кнопка. */
function Picker({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) })
  return null
}

/** Перевести карту к месту, заданному не кликом, а полем ввода. */
function FlyTo({ point }: { point: Точка | null }) {
  const map = useMap()
  useEffect(() => {
    if (point) map.setView([point.lat, point.lon], Math.max(map.getZoom(), 12))
  }, [point, map])
  return null
}

const вГранице = (lat: number, lon: number) =>
  Number.isFinite(lat) && Number.isFinite(lon)
  && Math.abs(lat) <= 90 && Math.abs(lon) <= 180

/**
 * Место из того, что человек вставил. Он почти никогда не набирает пару чисел
 * руками: он копирует ссылку из Яндекс.Карт, 2ГИС или Google — и там ещё и разный
 * порядок координат. Поэтому разбираем четыре вида ввода:
 *
 *   55.75, 37.62                     широта и долгота, точка или запятая
 *   55°45'0"N 37°37'12"E             градусы, минуты, секунды
 *   yandex.ru/maps/?ll=37.62,55.75   ссылка Яндекса — там ДОЛГОТА первой
 *   google.com/maps/@55.75,37.62     ссылка Google — широта первой
 *
 * Перепутанный порядок — самая дорогая ошибка здесь: 37,62 северной широты это
 * Средиземное море, и оценка площадки посчитается честно, но не про то место.
 */
function разобрать(text: string): Точка | null {
  const t = text.trim()
  if (!t) return null

  // Ссылка Яндекс.Карт и 2ГИС: параметр `ll`/`m` идёт как «долгота,широта».
  const ll = t.match(/[?&](?:ll|m)=(-?\d+(?:\.\d+)?)(?:%2C|,)(-?\d+(?:\.\d+)?)/i)
  if (ll) {
    const lon = Number(ll[1])
    const lat = Number(ll[2])
    if (вГранице(lat, lon)) return { lat, lon }
  }
  // Ссылка Google Maps: «@широта,долгота» либо «q=широта,долгота».
  const g = t.match(/[@=](-?\d+\.\d+),(-?\d+\.\d+)/)
  if (g && /google|maps\.app|goo\.gl/i.test(t)) {
    const lat = Number(g[1])
    const lon = Number(g[2])
    if (вГранице(lat, lon)) return { lat, lon }
  }

  // Градусы, минуты, секунды: 55°45'0"N 37°37'12"E.
  const dms = [...t.matchAll(
    /(\d+)\s*[°º]\s*(\d+)?\s*['′]?\s*(\d+(?:[.,]\d+)?)?\s*["″]?\s*([NSEWСЮВЗ])?/gi)]
  if (dms.length >= 2) {
    const вГрадусы = (m: RegExpMatchArray) => {
      const value = Number(m[1]) + Number(m[2] ?? 0) / 60
        + Number((m[3] ?? '0').replace(',', '.')) / 3600
      const знак = /[SWЮЗ]/i.test(m[4] ?? '') ? -1 : 1
      return value * знак
    }
    const first = вГрадусы(dms[0])
    const second = вГрадусы(dms[1])
    // Буква важнее порядка: «37°E 55°N» тоже про Москву.
    const широтаВторой = /[NSСЮ]/i.test(dms[1][4] ?? '')
    const lat = широтаВторой ? second : first
    const lon = широтаВторой ? first : second
    if (вГранице(lat, lon)) return { lat, lon }
  }

  // Просто два числа: широта, долгота.
  const nums = t.match(/-?\d+(?:[.,]\d+)?/g)
  if (!nums || nums.length < 2) return null
  const [lat, lon] = nums.slice(0, 2).map((n) => Number(n.replace(',', '.')))
  return вГранице(lat, lon) ? { lat, lon } : null
}

const одинаковы = (a: Условия | null, b: Условия | null) =>
  !!a && !!b && a.radius === b.radius && a.place === b.place
  && Math.abs(a.point.lat - b.point.lat) < 1e-6
  && Math.abs(a.point.lon - b.point.lon) < 1e-6

export function MarketSiteScorePanel() {
  const { companyId } = useCompany()
  const [radius, setRadius] = useState('5')
  const [place, setPlace] = useState('auto')
  const [point, setPoint] = useState<Точка | null>(null)
  const [coords, setCoords] = useState('')
  const [ошибкаВвода, setОшибкаВвода] = useState<string | null>(null)
  // Результат хранится вместе с условиями, при которых получен: иначе на экране
  // оказывается новое место со старым расчётом.
  const [показан, setПоказан] = useState<Оценка | null>(null)
  const [сохранённые, setСохранённые] = useState<Оценка[]>([])
  // Разбор места — работа на весь стол: карта, окружение, территория и прогноз
  // смотрятся вместе. Режим общий с картой рынка, выход по Escape.
  const полный = useFullscreenPanel()
  // Четыре разреза оценки лежали друг под другом, и до прогноза приходилось
  // прокручивать мимо трёх карточек. Теперь это табы одной области: перебор
  // быстрый, а на ярлыке стоит число — видно, где смотреть (МАГ, 13.09.2026).
  const [вид, setВид] = useState<string>('area')
  const оценка = useRef<HTMLDivElement>(null)
  const mapLayers = useMapLayers()
  const isDark = useIsDark()

  const условия: Условия | null = point ? { point, radius, place } : null
  const устарел = !!показан && !одинаковы(показан.условия, условия)

  const ask = useMutation({
    mutationFn: (u: Условия) => getMarketSiteScore(companyId, {
      lat: u.point.lat, lon: u.point.lon, radius_km: Number(u.radius), place: u.place,
    }),
    onSuccess: (data, u) => {
      const оценка: Оценка = {
        id: `${u.point.lat},${u.point.lon},${u.radius},${u.place}`,
        условия: u, score: data,
      }
      setПоказан(оценка)
      // Повторная оценка тех же условий не плодит запись в сравнении.
      setСохранённые((prev) => [оценка, ...prev.filter((o) => o.id !== оценка.id)].slice(0, 6))
    },
  })

  const выбрать = (lat: number, lon: number) => {
    setPoint({ lat, lon })
    setCoords(`${lat.toFixed(5)}, ${lon.toFixed(5)}`)
    setОшибкаВвода(null)
  }

  const применитьКоординаты = () => {
    const p = разобрать(coords)
    if (!p) {
      setОшибкаВвода('Не похоже на координаты. Нужны широта и долгота: 55.75, 37.62')
      return
    }
    setPoint(p)
    setОшибкаВвода(null)
  }

  const сбросить = () => {
    setPoint(null)
    setCoords('')
    setПоказан(null)
    setОшибкаВвода(null)
  }

  const вернуться = (о: Оценка) => {
    setPoint(о.условия.point)
    setCoords(`${о.условия.point.lat.toFixed(5)}, ${о.условия.point.lon.toFixed(5)}`)
    setRadius(о.условия.radius)
    setPlace(о.условия.place)
    setПоказан(о)
    setОшибкаВвода(null)
  }

  const score = показан?.score ?? null
  const f = score?.forecast
  const центр = useMemo<[number, number]>(
    () => (point ? [point.lat, point.lon] : [55.75, 37.62]), [point])

  // Число на ярлыке отвечает на «есть ли там что смотреть» до переключения.
  const виды = score ? [
    { k: 'area', label: 'Территория' },
    { k: 'rivals', label: `Кто рядом · ${score.rivals.total}` },
    { k: 'cannibal', label: `Что съедим · ${score.cannibalization.ourNearby}` },
    { k: 'entry', label: `Чего стоит вход · ${score.entry.projectsNearby}` },
    { k: 'forecast', label: `Из чего прогноз · ${f?.analogues ?? 0}` },
  ] : []

  const вердикт = !score
    ? null
    : f && f.analogues === 0
      ? 'Похожих наших объектов не нашлось — прогноз строить не на чем, но окружение видно ниже.'
      : `Рядом ${score.rivals.total} чужих точек, из них живых ${score.rivals.alive}. `
        + `Похожие наши объекты дают ${nf.format(f?.sessionsPerPeriod ?? 0)} сессий `
        + `и ${money(f?.revenuePerPeriod ?? null)} за ${f?.days ?? 90} дней `
        + `(половина из них — от ${nf.format(f?.sessionsLow ?? 0)} до ${nf.format(f?.sessionsHigh ?? 0)} сессий).`

  return (
    <div className={полный.className}>
      {/* ── Условия: что и как оцениваем ───────────────────────────────── */}
      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
            <div>
              <label htmlFor="score-coords" className="mb-1 block text-xs text-muted-foreground">
                Место — ткните в карту или вставьте координаты
              </label>
              <div className="flex gap-2">
                <Input id="score-coords" value={coords} placeholder="55.75000, 37.62000"
                  onChange={(e) => setCoords(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && применитьКоординаты()}
                  className="h-8 w-[190px] text-xs tabular-nums" />
                <Button size="sm" variant="outline" className="h-8"
                  onClick={применитьКоординаты} disabled={!coords.trim()}>
                  Показать
                </Button>
              </div>
            </div>

            <div>
              <label id="score-radius-label"
                className="mb-1 block text-xs text-muted-foreground">
                Радиус оценки
              </label>
              <Select value={radius} onValueChange={setRadius}>
                <SelectTrigger aria-labelledby="score-radius-label"
                  className="h-8 w-[170px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {РАДИУСЫ.map((r) => (
                    <SelectItem key={r.v} value={r.v}>{r.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label id="score-place-label"
                className="mb-1 block text-xs text-muted-foreground">
                Тип места
              </label>
              <Select value={place} onValueChange={setPlace}>
                <SelectTrigger aria-labelledby="score-place-label"
                  className="h-8 w-[210px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {МЕСТА.map((m) => (
                    <SelectItem key={m.v} value={m.v}>{m.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2">
              {/* Кнопка называет, что произойдёт, и активна только когда есть что
                  считать. Автозапуск убран: условия должны меняться свободно. */}
              <Button size="sm" className="h-8" disabled={!point || ask.isPending}
                onClick={() => условия && ask.mutate(условия)}>
                {ask.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />}
                {показан ? 'Пересчитать' : 'Оценить место'}
              </Button>
              {(point || показан) && (
                <Button size="sm" variant="outline" className="h-8" onClick={сбросить}>
                  <RotateCcw className="mr-1.5 size-3.5" aria-hidden /> Другое место
                </Button>
              )}
              <Button size="sm" variant="outline" className="h-8"
                onClick={полный.toggle}
                title={полный.on ? 'Вернуть в рабочую область (Escape)' : 'Развернуть на весь экран'}>
                {полный.on
                  ? <><Minimize2 className="mr-1.5 size-3.5" aria-hidden /> Свернуть</>
                  : <><Maximize2 className="mr-1.5 size-3.5" aria-hidden /> Во весь экран</>}
              </Button>
            </div>
          </div>

          {ошибкаВвода && <p className="text-xs text-destructive">{ошибкаВвода}</p>}

          {!point && !показан && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Crosshair className="size-3.5" aria-hidden />
              Ткните в карту там, где думаете поставить станцию. Расчёт запустится по
              кнопке — условия до этого можно менять сколько угодно.
            </p>
          )}

          {/* Результат помечен условиями, при которых получен: изменил радиус —
              видно, что на экране ещё прежний ответ. */}
          {устарел && (
            <p className="text-xs text-warning">
              Условия изменились — на экране расчёт для прежних: {показан!.условия.radius} км,
              {' '}{МЕСТА.find((m) => m.v === показан!.условия.place)?.label}. Нажмите
              «Пересчитать».
            </p>
          )}

          {ask.isError && (
            <p className="text-xs text-destructive">
              Не удалось посчитать. Проверьте связь и нажмите «Пересчитать» ещё раз.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Оценённые места: вернуться и сравнить ──────────────────────── */}
      {/* Компактной строкой, а не полосой во всю ширину: это навигация между
          вариантами, а не раздел. */}
      {сохранённые.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-1">
          <span className="text-xs text-muted-foreground">Оценено:</span>
            {сохранённые.map((о) => {
              const активна = показан?.id === о.id
              const сессии = о.score.forecast?.sessionsPerPeriod
              return (
                <span key={о.id}
                  className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs ${
                    активна ? 'border-primary bg-primary/10' : 'border-border'}`}>
                  <button type="button" onClick={() => вернуться(о)}
                    className="tabular-nums hover:underline">
                    {о.условия.point.lat.toFixed(3)}, {о.условия.point.lon.toFixed(3)}
                    <span className="text-muted-foreground"> · {о.условия.radius} км</span>
                    {сессии != null && (
                      <span className="ml-1">→ {nf.format(сессии)} сессий</span>
                    )}
                  </button>
                  <button type="button" aria-label="Убрать из сравнения"
                    onClick={() => {
                      setСохранённые((prev) => prev.filter((x) => x.id !== о.id))
                      if (активна) setПоказан(null)
                    }}
                    className="text-muted-foreground hover:text-foreground">
                    <X className="size-3" aria-hidden />
                  </button>
                </span>
              )
            })}
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[3fr_2fr]">
        <Card className="min-h-[320px] overflow-hidden">
          <CardContent className="h-full p-0">
            <MapContainer center={центр} zoom={9} crs={MAP_CRS}
              attributionControl={false}
              style={{ height: '100%', minHeight: 320, width: '100%' }}>
              <MapTiles base={mapLayers.base} traffic={mapLayers.traffic}
                regions={mapLayers.regions} dark={isDark} />
              <AttributionControl position="bottomright" prefix={MAP_ATTRIBUTION_PREFIX} />
              <MapResize trigger={полный.on} />
              <Picker onPick={выбрать} />
              <FlyTo point={point} />
              {point && (
                <>
                  {/* Круг радиуса: без него не видно, что именно попало в оценку. */}
                  <Circle center={[point.lat, point.lon]} radius={Number(radius) * 1000}
                    pathOptions={{ color: '#3b82f6', weight: 1.5, fillOpacity: 0.06 }} />
                  <Marker position={[point.lat, point.lon]}>
                    <Popup>Место, которое оцениваем<br />радиус {radius} км</Popup>
                  </Marker>
                </>
              )}
            </MapContainer>
            <MapLayerSwitch {...mapLayers} />
          </CardContent>
        </Card>

        <div ref={оценка} className="min-h-0 space-y-3 overflow-auto">
          {!score ? (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                {point
                  ? 'Место выбрано. Нажмите «Оценить место»: посчитаем окружение, '
                    + 'каннибализацию, стоимость входа и прогноз по похожим объектам.'
                  : 'Пока место не выбрано, считать нечего. Ткните в карту или вставьте '
                    + 'координаты в поле выше.'}
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardContent className="space-y-1 p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-headline text-sm font-semibold">Что получилось</span>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {показан!.условия.point.lat.toFixed(5)},{' '}
                      {показан!.условия.point.lon.toFixed(5)} · {показан!.условия.radius} км
                      {' · '}{score.placeClass === 'city' ? 'город' : 'трасса'}
                      {score.placeGuessed ? ' (определено)' : ''}
                    </span>
                    <span data-export-ignore>
                      <ExportButton title="Оценка площадки"
                        subtitle={`${показан!.условия.point.lat.toFixed(5)}, ${показан!.условия.point.lon.toFixed(5)}`
                          + ` · радиус ${показан!.условия.radius} км`}
                        getEl={() => оценка.current} />
                    </span>
                  </div>
                  <p className="text-sm">{вердикт}</p>
                </CardContent>
              </Card>

              {/* Книга собирается по ВСЕМ разрезам, а не по открытому: оценку площадки
                  выгружают как обоснование к решению, и в нём должны быть и окружение,
                  и каннибализация, и стоимость входа, и выборка, на которой стоит
                  прогноз. Переключать вкладки ради полного файла человек не обязан. */}
              <table hidden {...exportRows('Оценка площадки', ['Показатель', 'Значение'], [
                ['Широта', показан!.условия.point.lat],
                ['Долгота', показан!.условия.point.lon],
                ['Радиус, км', показан!.условия.radius],
                ['Тип места', score.placeClass === 'city' ? 'город' : 'трасса'],
                ['Тип места определён автоматически', score.placeGuessed ? 'да' : 'нет'],
                ['Вывод', вердикт],
                ['Город', score.area.city],
                ['Регион', score.area.region],
                ['Электромобилей в регионе', score.area.evCars],
                ['Зарядок в регионе', score.area.marketSites],
                ['Из них живых', score.area.marketAlive],
                ['Машин на живую зарядку', score.area.carsPerAlive],
                ['Наших объектов в регионе', score.area.ourSites],
                ['Площадок в работе', score.area.projectsInWork],
                ['Номера площадок', (score.area.projectNumbers ?? []).join(', ')],
                ['Источник парка машин', score.area.evSource],
                ['Чужих точек в радиусе', score.rivals.total],
                ['Из них живых', score.rivals.alive],
                ['Портов у чужих', score.rivals.ports],
                ['Цена рынка, ₽/кВт·ч', score.rivals.marketPricePerKwh],
                ['Наших объектов в радиусе', score.cannibalization.ourNearby],
                ['Присоединение, ₽ (медиана)', score.entry.tpCostMedian],
                ['Срок присоединения, мес', score.entry.tpTermMonthsMedian],
                ['Свободная мощность, кВт', score.entry.freePowerKwtMedian],
                ['Аренда в месяц, ₽', score.entry.rentMonthMedian],
                ['Оценка входа, ₽', score.entry.capexEstimate],
                ['Окупаемость, периодов выручки', score.entry.paybackPeriods],
                ['Основание стоимости входа', score.entry.basis],
                ['Метод прогноза', f?.method],
                ['Аналогов в выборке', f?.analogues],
                ['Из них заряжают', f?.working],
                ['Не заряжают вовсе', f?.zeroDemand],
                [`Прогноз сессий за ${f?.days ?? 90} дней`, f?.sessionsPerPeriod],
                ['Половина случаев, от', f?.sessionsLow],
                ['Половина случаев, до', f?.sessionsHigh],
                ['Медиана с учётом незаряжающих', f?.sessionsAllMedian],
                ['Прогноз выручки, ₽', f?.revenuePerPeriod],
              ])} />
              <table hidden {...exportRows('Кто рядом', [
                'Точка', 'Оператор', 'Расстояние, км', 'Цена, ₽/кВт·ч', 'Спрос',
              ], score.rivals.list.map((r) => [
                r.name, r.operatorName, r.distanceKm, r.pricePerKwh,
                r.alive ? 'заряжали недавно' : 'молчит',
              ]))} />
              <table hidden {...exportRows('Что съедим', [
                'Наш объект', 'Город', 'Расстояние, км', 'Сессий',
              ], score.cannibalization.list.map((o) => [
                o.name, o.city, o.distanceKm, o.sessions,
              ]))} />
              <table hidden {...exportRows('Из чего прогноз', [
                'Объект', 'Город', 'Соседей', 'Сессий', 'Выручка, ₽',
              ], (f?.sample ?? []).map((a) => [
                a.name, a.city, a.rivals, a.sessions, a.revenue,
              ]))} />

              <PanelViewTabs tabs={виды} value={вид} onChange={setВид} label={null}
                ariaLabel="Разрезы оценки площадки" />

              {вид === 'area' && (
              <Card>
                <CardContent className="space-y-3 p-4">
                  {/* Соседние станции отвечают на «кто рядом», территория — на «что
                      это за место вообще»: сколько там машин, насколько плотен рынок
                      и не строим ли мы уже тут. Без второго решение принимают,
                      глядя в радиус пяти километров. */}
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">
                      {score.area.city ?? 'город не определён'}
                      {score.area.region && (
                        <span className="text-muted-foreground"> · {score.area.region}</span>
                      )}
                    </span>
                    {score.area.byPointName && (
                      <span className="text-xs text-muted-foreground">
                        определено по точке «{score.area.byPointName.slice(0, 28)}»
                        {score.area.byPointKm != null && ` в ${nf1.format(score.area.byPointKm)} км`}
                      </span>
                    )}
                  </div>

                  <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
                    <div>
                      <div className="text-xs text-muted-foreground">электромобилей в регионе</div>
                      <div className="text-sm">
                        {score.area.evCars != null
                          ? <span className="tabular-nums">{nf.format(score.area.evCars)}</span>
                          : <span className="text-muted-foreground">не публикуется</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">зарядок в регионе</div>
                      <div className="text-sm tabular-nums">
                        {nf.format(score.area.marketSites ?? 0)}
                        <span className="text-muted-foreground">
                          {' '}· живых {nf.format(score.area.marketAlive ?? 0)}
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">машин на живую зарядку</div>
                      <div className="text-sm">
                        {score.area.carsPerAlive != null
                          ? <span className="tabular-nums">{nf1.format(score.area.carsPerAlive)}</span>
                          : <span className="text-muted-foreground">парк неизвестен</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">наших объектов в регионе</div>
                      <div className="text-sm tabular-nums">{nf.format(score.area.ourSites ?? 0)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">площадок в работе</div>
                      <div className="text-sm tabular-nums">
                        {nf.format(score.area.projectsInWork ?? 0)}
                      </div>
                    </div>
                  </div>

                  {(score.area.projectsInWork ?? 0) > 0 && (
                    <p className="text-xs text-muted-foreground">
                      В этом регионе уже идут наши площадки
                      {score.area.projectNumbers?.length
                        ? `: ${score.area.projectNumbers.slice(0, 4).join(', ')}`
                        : ''}. Прежде чем считать место новым, стоит посмотреть, не
                      про него ли они.
                    </p>
                  )}

                  {score.area.evSource && (
                    <p className="text-xs text-muted-foreground">
                      парк машин: {score.area.evSource}
                      {score.area.evAsOf && `, данные на ${score.area.evAsOf}`}
                    </p>
                  )}
                </CardContent>
              </Card>
              )}

              {вид === 'rivals' && (
              <Card>
                <CardContent className="p-4">
                  {score.rivals.total === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      В радиусе чужих сетевых точек нет. Это либо свободное место, либо
                      место, где рынок ещё не наблюдали.
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
              )}

              {вид === 'cannibal' && (
              <Card>
                <CardContent className="p-4">
                  {score.cannibalization.ourNearby === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      Наших объектов в этом радиусе нет — перетекать сессиям неоткуда.
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
              )}

              {вид === 'entry' && (
              <Card>
                <CardContent className="p-4">
                  {score.entry.projectsNearby === 0 ? (
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
              )}

              {вид === 'forecast' && (
              <Card>
                <CardContent className="p-4">
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
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
