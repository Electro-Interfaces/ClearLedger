/**
 * Сетевые экраны «Топлива»: оборудование, актив, клиенты, визиты.
 *
 * Обычные разрезы отвечают, СКОЛЬКО сеть продала. Эти четыре — где она не
 * работает и где на самом деле лежат деньги (перенос приёмов ЭЗС-контура:
 * port-efficiency, silent-stations, ABC-XYZ, когорты клиентов, визиты).
 *
 * Четыре панели в одном файле намеренно: у них общий скоуп, общая вёрстка
 * таблиц и одна судьба — их правят вместе, разносить по файлам значит четыре
 * раза повторить один и тот же каркас.
 */
import { Fragment, useMemo, useRef, useState, type ReactNode } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CircleCheckBig, Gauge, Info, Loader2, TrendingUp } from 'lucide-react'
import { PumpUnitModal, type PumpUnitRef } from './PumpUnitModal'
import { BarList } from '@/components/ui/bar-list'
import { SparkLineChart } from '@/components/ui/spark-chart'
import { Tracker } from '@/components/ui/tracker'
import { formatBucket, formatDate } from '@/lib/formatDate'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useWorkspace, type CoreMode } from '@/contexts/WorkspaceContext'
import { workspaceModeForKey } from '@/config/workspaceMenus'
import { useLocations } from '@/hooks/useLocations'
import { scopeStationCodes } from '@/services/locationService'
import { cn } from '@/lib/utils'
import { fmtLiters, fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import { ExportButton } from './analytics/ExportButton'
import {
  getFuelAbcXyz, getFuelClients, getFuelPumps, getFuelSilent, getFuelVisits,
  type AbcDimension, type PumpLevel,
} from '@/services/fuelNetworkService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const pct = (v: number | null | undefined) => (v == null ? '—' : `${nf1.format(v)} %`)

/**
 * Область работы экрана из общего фильтра: точки и регионы → коды станций STS,
 * плюс выбранные виды нефтепродуктов.
 *
 * Вид топлива приходит отсюда, а не из локального селектора экрана: он выбран в
 * шапке рабочей области и обязан действовать одинаково на загрузку ТРК, ABC-XYZ,
 * когорты и визиты — иначе четыре экрана про одну сеть ответят по-разному.
 */
function useFuelScope(): { stationCodes?: number[]; fuelCodes?: number[]; key: string } {
  const { stationCode, locationIds, regionIds, fuelCodes } = useFilters()
  const locations = useLocations()
  const scope = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds),
    [locations, locationIds, regionIds],
  )
  const one = stationCode && stationCode !== 'all' ? Number(stationCode) : NaN
  const codes = Number.isFinite(one)
    ? (scope.length === 0 || scope.includes(one) ? [one] : [-1])
    : (scope.length ? scope : undefined)
  const fuels = fuelCodes.map(Number).filter(Number.isFinite)
  return {
    stationCodes: codes,
    fuelCodes: fuels.length ? fuels : undefined,
    key: `${stationCode ?? ''}|${scope.join(',')}|${fuels.join(',')}`,
  }
}

function Loading() {
  return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет данных за период' }: { text?: string }) {
  return <div className="p-8 text-center text-sm text-muted-foreground">{text}</div>
}
/**
 * Сорванный запрос — не то же самое, что пустой период.
 *
 * Раньше оба случая давали «Нет данных за период», и упавший запрос выглядел как
 * честно пустая сеть: экран когорт показывал пустоту при 20 тысячах карт в базе.
 * Причину приходилось искать в логах сервера вместо того, чтобы прочитать на экране.
 */
function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const msg = error instanceof Error ? error.message : 'неизвестная ошибка'
  return (
    <div className="p-8 text-center text-sm">
      <div className="text-red-400/90">Данные не загрузились</div>
      <div className="mt-1 text-xs text-muted-foreground">{msg}</div>
      <button onClick={onRetry}
        className="mt-3 rounded-md border border-border/60 px-3 py-1.5 text-xs hover:bg-accent/20">
        Повторить
      </button>
    </div>
  )
}

function Metric({ label, value, hint, tone, spark }: {
  label: string; value: string; hint?: string; tone?: 'danger' | 'success' | 'info'
  /** Ряд по дням периода: цифра говорит «сколько», ряд — «куда идёт». */
  spark?: (number | null)[]
}) {
  const data = spark && spark.length >= 3 ? spark.map((v, i) => ({ i, v })) : null
  return (
    <div className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn('mt-1 truncate text-lg font-semibold tabular-nums',
        tone === 'danger' && 'text-rose-400',
        tone === 'success' && 'text-emerald-400',
        tone === 'info' && 'text-blue-400')}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint}</div> : null}
      {data && (
        <SparkLineChart className="mt-1.5 h-7 w-full" data={data} index="i" categories={['v']}
          colors={[tone === 'danger' ? 'error' : 'brand']} connectNulls autoMinValue
          aria-label={`Динамика по дням: ${label}`} />
      )}
    </div>
  )
}

function Head({ title, hint, children, exportEl }: {
  title: string; hint: string; children?: ReactNode
  exportEl?: () => HTMLElement | null
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      <div className="flex items-center gap-2">
        {children}
        {exportEl && <ExportButton title={title} getEl={exportEl} />}
      </div>
    </div>
  )
}

/** Сегмент-переключатель — тот же вид, что у «Реализации». */
function Toggle<T extends string>({ value, onChange, opts, title }: {
  value: T; onChange: (v: T) => void; opts: { v: T; label: string }[]; title?: string
}) {
  return (
    <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5" title={title}>
      {opts.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${
            value === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return <th className={cn('p-2.5 font-medium', right ? 'text-right' : 'text-left')}>{children}</th>
}
function Td({ children, right, className }: { children: ReactNode; right?: boolean; className?: string }) {
  return <td className={cn('p-2.5', right && 'text-right tabular-nums', className)}>{children}</td>
}

// ═══════════════════════════════════════════════════════════════════════
// 1. Оборудование: ТРК и пистолеты
// ═══════════════════════════════════════════════════════════════════════

/**
 * Загрузка оборудования. Ключевая колонка — не выручка, а реализаций в сутки:
 * абсолютные цифры зависят от размера АЗС, и без нормировки крупная станция
 * всегда выглядит эффективнее маленькой.
 */
export function FuelPumpsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [level, setLevel] = useState<PumpLevel>('nozzle')
  const [unit, setUnit] = useState<PumpUnitRef | null>(null)
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-pumps', companyId, dateFrom, dateTo, level, scope.key],
    queryFn: () => getFuelPumps({ companyId, dateFrom, dateTo, level, stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })
  const silentQ = useQuery({
    queryKey: ['fuel-silent', companyId, dateFrom, dateTo],
    queryFn: () => getFuelSilent({ companyId, dateFrom, dateTo }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  if (q.isError) return <Failed error={q.error} onRetry={() => void q.refetch()} />
  const data = q.data
  if (!data) return null
  const t = data.totals
  const active = data.lines.filter((l) => !l.silent)
  // Подпись строки — словами, а не кодом `210·1/1`: по такому коду читатель не
  // скажет ни станции, ни топлива. Название АЗС + номер ТРК + рукав + вид топлива.
  const chart = active.slice(0, 20).map((l) => ({
    name: [
      l.station,
      l.pos != null ? `ТРК ${l.pos}` : null,
      level === 'nozzle' && l.nozzle != null ? `рукав ${l.nozzle}` : null,
      l.fuel_name,
    ].filter(Boolean).join(' · '),
    value: l.fills_per_day,
    ref: {
      stationCode: l.station_code, station: l.station, pos: l.pos,
      nozzle: level === 'nozzle' ? l.nozzle : null, fuelName: l.fuel_name,
    } satisfies PumpUnitRef,
  }))

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Загрузка ТРК и пистолетов"
        hint="Реализаций в сутки на единицу оборудования · простой · молчащие рукава"
        exportEl={() => ref.current}>
        <Toggle value={level} onChange={setLevel} title="Уровень детализации"
          opts={[{ v: 'nozzle', label: 'Пистолеты' }, { v: 'pos', label: 'ТРК' }]} />
      </Head>

      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
          <Metric label={level === 'nozzle' ? 'Пистолетов' : 'ТРК'} value={nf0.format(t.units)}
            hint={`${t.stations} АЗС · ${data.days} дней`} />
          <Metric label="Работали" value={nf0.format(t.active)} tone="success"
            hint={`${pct(t.units ? t.active / t.units * 100 : 0)} парка`}
            spark={data.series?.units} />
          <Metric label="Молчали" value={nf0.format(t.silent)} tone={t.silent ? 'danger' : undefined}
            hint="ни одной реализации за период" />
          <Metric label="Медиана" value={`${nf2.format(t.median_fills_per_day)}/сут`}
            hint="реализаций в сутки на единицу" spark={data.series?.fills_per_unit} />
          <Metric label="Максимум" value={`${nf2.format(t.top_fills_per_day)}/сут`} tone="info"
            hint={t.median_fills_per_day
              ? `разброс ${nf1.format(t.top_fills_per_day / t.median_fills_per_day)}×` : undefined} />
          <Metric label="Выручка" value={`${fmtMoneyShort(t.amount)} ₽`}
            hint={`${fmtLiters(t.liters)} · ${nf0.format(t.fills)} реализаций`}
            spark={data.series?.amount} />
        </CardContent>
      </Card>

      {/* Парк по дням: «219 из 337 работали» — это итог за период, из него не
          видно, был ли провал одним днём или сеть просела на неделю. */}
      {data.series && data.series.axis.length >= 3 && (
        <Card>
          <CardContent className="pt-4">
            <div className="mb-0.5 text-sm font-medium">Парк по дням</div>
            <div className="mb-3 text-xs text-muted-foreground">
              Доля {level === 'nozzle' ? 'рукавов' : 'ТРК'} с реализациями · всего в парке {nf0.format(t.units)}
            </div>
            <Tracker
              className="h-9"
              hoverEffect
              data={data.series.axis.map((day, i) => {
                const active = data.series!.units[i] ?? 0
                const share = t.units ? active / t.units * 100 : 0
                return {
                  key: day,
                  // Пороги те же, что у тона плиток: не заводим отдельную шкалу
                  // «хорошо/плохо» там, где рядом уже есть своя.
                  color: active === 0 ? 'bg-muted-foreground/30'
                    : share >= 90 ? 'bg-success'
                    : share >= 70 ? 'bg-warning'
                    : 'bg-error',
                  tooltip: `${formatBucket(day)} · ${nf0.format(active)} из ${nf0.format(t.units)} (${pct(share)})`,
                }
              })}
            />
            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1"><i className="size-2 rounded-[2px] bg-success" />от 90 %</span>
              <span className="flex items-center gap-1"><i className="size-2 rounded-[2px] bg-warning" />70–90 %</span>
              <span className="flex items-center gap-1"><i className="size-2 rounded-[2px] bg-error" />ниже 70 %</span>
              <span className="flex items-center gap-1"><i className="size-2 rounded-[2px] bg-muted-foreground/30" />нет данных</span>
            </div>
          </CardContent>
        </Card>
      )}

      {chart.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <div className="mb-0.5 text-sm font-medium">
              Топ-20 {level === 'nozzle' ? 'рукавов' : 'ТРК'} по загрузке
            </div>
            {/* Цифра без опоры не читается: 104,91 — это много или мало? Медиана рядом
                отвечает на вопрос сразу, поэтому она в подзаголовке, а не только в KPI. */}
            <div className="mb-3 text-xs text-muted-foreground">
              Реализаций в сутки на единицу · медиана по сети {nf2.format(t.median_fills_per_day)}
            </div>
            {/* Рейтинг, а не динамика: подписи двадцати столбцов вставали под 45° и не
                читались, да и длины строк сравниваются глазом легче, чем высоты. */}
            <BarList
              className="max-h-80 overflow-y-auto pr-1"
              data={chart}
              sortOrder="none"
              valueFormatter={(v) => `${nf2.format(v)} реализ./сут`}
              onValueChange={(item) => setUnit(item.ref)}
            />
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="all">
        <TabsList variant="line" className="h-9">
          <TabsTrigger value="all"><Gauge className="mr-1.5 h-3.5 w-3.5" />Все единицы</TabsTrigger>
          <TabsTrigger value="silent">
            <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />Молчащие
            {silentQ.data ? <span className="ml-1 text-muted-foreground">{silentQ.data.counts.nozzles}</span> : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="all" className="mt-3">
          <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-xs">
                <thead>
                  <tr className="border-b bg-muted/35 text-muted-foreground">
                    <Th>АЗС</Th><Th>ТРК</Th>{level === 'nozzle' && <Th>Пистолет</Th>}<Th>Топливо</Th>
                    <Th right>Реализаций/сут</Th><Th right>Реализации</Th><Th right>Литры</Th>
                    <Th right>Выручка</Th><Th right>Ср. заправка</Th>
                    <Th right>Дней без работы</Th><Th right>Доля АЗС</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((l, i) => (
                    /* Клик по строке — расшифровка единицы: из чего сложились её цифры
                       и откуда они взяты. Строка это физический рукав, а не агрегат
                       разных сущностей, поэтому окно, а не смена фильтра. */
                    <tr key={`${l.station_code}-${l.pos}-${l.nozzle}-${i}`}
                      onClick={() => setUnit({
                        stationCode: l.station_code, station: l.station, pos: l.pos,
                        nozzle: level === 'nozzle' ? l.nozzle : null, fuelName: l.fuel_name,
                      })}
                      title="Открыть расшифровку строки"
                      className={cn('cursor-pointer border-b border-border/50 hover:bg-muted/25', l.silent && 'opacity-60')}>
                      <Td>{l.station}</Td>
                      <Td>{l.pos ?? '—'}</Td>
                      {level === 'nozzle' && <Td>{l.nozzle ?? '—'}</Td>}
                      <Td className="text-muted-foreground">{l.fuel_name ?? (l.fuels > 1 ? `${l.fuels} вида` : '—')}</Td>
                      <Td right className={l.silent ? 'text-rose-400' : 'font-medium'}>{nf2.format(l.fills_per_day)}</Td>
                      <Td right>{nf0.format(l.fills)}</Td>
                      <Td right>{fmtLiters(l.liters)}</Td>
                      <Td right>{fmtMoney(l.amount)}</Td>
                      <Td right>{nf1.format(l.avg_fill)} л</Td>
                      <Td right className={l.idle_days > data.days / 2 ? 'text-amber-400' : ''}>{l.idle_days}</Td>
                      <Td right className="text-muted-foreground">{pct(l.station_share_pct)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="silent" className="mt-3">
          {silentQ.data && (silentQ.data.counts.stations + silentQ.data.counts.pumps + silentQ.data.counts.nozzles) === 0 ? (
            <Card><CardContent className="flex items-center gap-3 py-6 text-sm">
              <CircleCheckBig className="h-4 w-4 text-emerald-400" />
              Всё оборудование сети отпускало топливо в этом периоде.
            </CardContent></Card>
          ) : (
            <>
            {/* Кто стоит дольше всех — первый вопрос к этому списку, а в таблице
                на сотню строк он тонет: сортировка есть, глазомера нет. */}
            {(() => {
              const idle = [
                ...(silentQ.data?.stations ?? []).map((r) => ({ ...r, kind: 'АЗС' })),
                ...(silentQ.data?.pumps ?? []).map((r) => ({ ...r, kind: 'ТРК' })),
                ...(silentQ.data?.nozzles ?? []).map((r) => ({ ...r, kind: 'рукав' })),
              ].filter((r) => (r.days_idle ?? 0) > 0)
                .sort((a, b) => (b.days_idle ?? 0) - (a.days_idle ?? 0))
                .slice(0, 10)
              if (idle.length < 3) return null
              return (
                <Card className="mb-3">
                  <CardContent className="pt-4">
                    <div className="mb-0.5 text-sm font-medium">Дольше всех без реализаций</div>
                    <div className="mb-3 text-xs text-muted-foreground">
                      Дней с последней операции · показаны десять первых из {nf0.format(
                        (silentQ.data?.counts.stations ?? 0) + (silentQ.data?.counts.pumps ?? 0)
                        + (silentQ.data?.counts.nozzles ?? 0))}
                    </div>
                    <BarList
                      sortOrder="none"
                      valueFormatter={(v) => `${nf0.format(v)} дн.`}
                      data={idle.map((r) => ({
                        name: [r.station, r.pos != null ? `ТРК ${r.pos}` : null,
                          r.nozzle != null ? `рукав ${r.nozzle}` : null].filter(Boolean).join(' · ')
                          + ` — ${r.kind}`,
                        value: r.days_idle ?? 0,
                      }))}
                    />
                  </CardContent>
                </Card>
              )
            })()}
            <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-xs">
                  <thead>
                    <tr className="border-b bg-muted/35 text-muted-foreground">
                      <Th>Уровень</Th><Th>АЗС</Th><Th>ТРК</Th><Th>Пистолет</Th>
                      <Th right>Последняя заправка</Th><Th right>Дней простоя</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ...(silentQ.data?.stations ?? []).map((r) => ({ ...r, kind: 'Станция' })),
                      ...(silentQ.data?.pumps ?? []).map((r) => ({ ...r, kind: 'ТРК' })),
                      ...(silentQ.data?.nozzles ?? []).map((r) => ({ ...r, kind: 'Пистолет' })),
                    ].map((r, i) => (
                      <tr key={i} className="border-b border-border/50 hover:bg-muted/25">
                        <Td className="text-muted-foreground">{r.kind}</Td>
                        <Td>{r.station}</Td><Td>{r.pos ?? '—'}</Td><Td>{r.nozzle ?? '—'}</Td>
                        <Td right>{r.last_at ? formatDate(r.last_at) : 'никогда'}</Td>
                        <Td right className="text-amber-400">{r.days_idle ?? '—'}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent></Card>
            </>
          )}
        </TabsContent>
      </Tabs>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        «Реализаций в сутки» считается на все сутки периода, включая простой: делить на
        рабочие дни значило бы спрятать сам простой. Молчащие единицы — те, что
        отпускали топливо раньше, но за период не сделали ни одной операции.
        Клик по строке открывает расшифровку: динамика по суткам, интервалы простоя,
        профиль часов и источник цифр.
      </div>

      <PumpUnitModal unit={unit} companyId={companyId} dateFrom={dateFrom} dateTo={dateTo}
        onClose={() => setUnit(null)} />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 2. ABC-XYZ и концентрация
// ═══════════════════════════════════════════════════════════════════════

/**
 * Класс позиции читается ЦВЕТОМ ЗАЛИВКИ по доле выручки — это магнитуда, а
 * магнитуда кодируется одной hue от светлого к тёмному, не радугой классов.
 * Сам класс несут буквы и положение в сетке, поэтому цвет свободен под деньги:
 * взгляд сразу находит клетку, где лежит оборот, а не ту, где больше позиций.
 */
function cellFill(sharePct: number, maxShare: number): { bg: string; ink: string } {
  if (!sharePct) return { bg: 'transparent', ink: 'text-muted-foreground/60' }
  const t = Math.min(1, sharePct / (maxShare || 1))
  // Четыре ступени вместо непрерывной шкалы: глаз всё равно не различает
  // больше, а ступени дают предсказуемый контраст текста.
  const step = t > 0.66 ? 3 : t > 0.33 ? 2 : t > 0.1 ? 1 : 0
  return {
    bg: ['hsl(var(--chart-1) / 0.08)', 'hsl(var(--chart-1) / 0.18)',
      'hsl(var(--chart-1) / 0.30)', 'hsl(var(--chart-1) / 0.45)'][step],
    ink: step >= 2 ? 'text-foreground' : 'text-foreground/90',
  }
}

const ABC_ROW = [
  { k: 'A', title: 'A — лидеры', sub: 'до 80 % выручки' },
  { k: 'B', title: 'B — середина', sub: '80–95 %' },
  { k: 'C', title: 'C — хвост', sub: 'последние 5 %' },
]
const XYZ_COL = [
  { k: 'X', title: 'X — ровный', sub: 'разброс ≤ 25 %' },
  { k: 'Y', title: 'Y — переменный', sub: '25–50 %' },
  { k: 'Z', title: 'Z — рваный', sub: '> 50 %' },
]

/** Подписи групп концентрации — одни на карточку и на заголовок таблицы. */
const QUINTILE_LABELS = ['Верхние 20 %', 'Следующие 20 %', 'Средние 20 %',
  'Предпоследние 20 %', 'Нижние 20 %']

const TREND_VIEW: Record<string, { sign: string; cls: string; label: string }> = {
  up: { sign: '↗', cls: 'text-emerald-400', label: 'растёт' },
  down: { sign: '↘', cls: 'text-rose-400', label: 'падает' },
  flat: { sign: '→', cls: 'text-muted-foreground', label: 'ровно' },
}

/** Деньги в таблице — компактно: «44,4 млн ₽» читается, «44 406 941,32» — нет. */
const money = (v: number): string => (
  v >= 1e6 ? `${nf1.format(v / 1e6)} млн` : v >= 1e3 ? `${nf0.format(v / 1e3)} тыс` : nf0.format(v)
)

export function FuelAbcXyzPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [dim, setDim] = useState<AbcDimension>('station_fuel')
  const [bucket, setBucket] = useState<'week' | 'month'>('week')
  /**
   * Что оставлено в таблице. Фильтруют ОБА среза — и клетка матрицы, и группа
   * концентрации: две карточки рядом про одни и те же позиции, и если кликается
   * только одна, вторая читается как сломанная. Выбор один за раз — пересечение
   * «класс AY ∩ верхние 20 %» человек не заказывал, а объяснять пустой результат
   * пришлось бы отдельно.
   */
  const [sel, setSel] = useState<{ kind: 'cell'; key: string } | { kind: 'quintile'; n: number } | null>(null)
  const cell = sel?.kind === 'cell' ? sel.key : null
  const quintile = sel?.kind === 'quintile' ? sel.n : null
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-abcxyz', companyId, dateFrom, dateTo, dim, bucket, scope.key],
    queryFn: () => getFuelAbcXyz({ companyId, dateFrom, dateTo, dimension: dim, bucket, stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  if (q.isError) return <Failed error={q.error} onRetry={() => void q.refetch()} />
  const data = q.data
  if (!data) return <Empty />

  const byCell = new Map(data.matrix.map((m) => [m.cell, m]))
  const maxShare = Math.max(...data.matrix.map((m) => m.share_pct), 0.01)
  const rows = cell ? data.items.filter((i) => i.abc + i.xyz === cell)
    : quintile ? data.items.filter((i) => i.quintile === quintile)
    : data.items
  const unclassified = data.items.filter((i) => i.xyz === '—')
  const tail = data.items.filter((i) => i.abc === 'C')
  const tailShare = tail.reduce((s, i) => s + i.share_pct, 0)
  const leaders = data.items.filter((i) => i.abc === 'A')
  const risky = data.items.filter((i) => i.abc === 'A' && i.xyz === 'Z')
  const bucketWord = bucket === 'week' ? 'недель' : 'месяцев'
  const cutShort = data.period_buckets && data.buckets < data.period_buckets

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Классы позиций: вклад × предсказуемость"
        hint={`${data.totals.count} позиций · сетка по ${bucket === 'week' ? 'неделям' : 'месяцам'}`
          + ` · в расчёте ${data.buckets} полных ${bucketWord}`
          + (data.data_through ? ` · данные по ${data.data_through.slice(8, 10)}.${data.data_through.slice(5, 7)}` : '')}
        exportEl={() => ref.current}>
        <Toggle value={dim} onChange={(v) => { setDim(v); setSel(null) }} title="Единица классификации"
          opts={[{ v: 'station_fuel', label: 'АЗС × топливо' }, { v: 'station', label: 'АЗС' }, { v: 'fuel', label: 'Топливо' }]} />
        <Toggle value={bucket} onChange={(v) => { setBucket(v); setSel(null) }} title="Шаг сетки для расчёта разброса"
          opts={[{ v: 'week', label: 'Недели' }, { v: 'month', label: 'Месяцы' }]} />
      </Head>

      {/* Период шире загруженных данных — сказать прямо. Раньше пустой хвост
          молча превращал ровные позиции в «рваные»: это стоило целой матрицы. */}
      {cutShort && (
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/35 bg-amber-500/5 px-3 py-2 text-xs">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
          <span>
            Период шире загруженных данных: последние операции — {data.data_through}.
            Пустые {bucketWord} на конце в расчёт разброса не берутся, иначе задержка
            загрузки выглядела бы падением спроса.
          </span>
        </div>
      )}

      {/* Ответ раньше подробностей: три числа, ради которых экран открывают. */}
      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-4">
          <Metric label="Лидеры (A)" value={`${leaders.length} поз.`} tone="success"
            hint={`дают ${pct(leaders.reduce((s, i) => s + i.share_pct, 0))} выручки`} />
          <Metric label="Крупные и рваные" value={`${risky.length} поз.`}
            tone={risky.length ? 'danger' : undefined}
            hint={risky.length ? 'спрос скачет — разобрать причину' : 'таких нет'} />
          <Metric label="Хвост (C)" value={`${tail.length} поз.`}
            hint={`${pct(tailShare)} выручки — кандидаты на пересмотр`} />
          <Metric label="Мало данных" value={`${unclassified.length} поз.`}
            hint={unclassified.length ? `меньше 6 ${bucketWord} истории` : 'история достаточна у всех'} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_1fr]">
        <Card><CardContent className="pt-4">
          <div className="mb-3 flex items-baseline justify-between">
            <span className="text-sm font-medium">Матрица классов</span>
            {sel && (
              <button onClick={() => setSel(null)}
                className="text-xs text-primary hover:underline">Показать все</button>
            )}
          </div>

          {/* Заголовки осей — на самих осях, а не в сноске под картинкой. */}
          <div className="grid grid-cols-[auto_repeat(3,1fr)] gap-1.5 text-center">
            <div />
            {XYZ_COL.map((c) => (
              <div key={c.k} className="pb-1">
                <div className="text-xs font-semibold">{c.title}</div>
                <div className="text-[10px] text-muted-foreground">{c.sub}</div>
              </div>
            ))}
            {ABC_ROW.map((r) => (
              <Fragment key={r.k}>
                <div className="flex flex-col justify-center pr-2 text-right">
                  <div className="text-xs font-semibold">{r.title}</div>
                  <div className="text-[10px] text-muted-foreground">{r.sub}</div>
                </div>
                {XYZ_COL.map((c) => {
                  const key = r.k + c.k
                  const m = byCell.get(key)
                  const count = m?.count ?? 0
                  const fill = cellFill(m?.share_pct ?? 0, maxShare)
                  const active = cell === key
                  return (
                    <button key={key} type="button" disabled={!count}
                      onClick={() => setSel(active ? null : { kind: 'cell', key })}
                      title={m?.hint || 'Позиций этого класса нет'}
                      aria-pressed={active}
                      className={cn(
                        'rounded-md border px-2 py-2.5 text-center transition-colors',
                        count ? 'cursor-pointer hover:border-primary/60' : 'cursor-default',
                        active ? 'border-primary ring-1 ring-primary/40' : 'border-border/60',
                      )}
                      style={{ background: fill.bg }}>
                      <div className={cn('text-lg font-semibold tabular-nums', fill.ink)}>{count}</div>
                      <div className="text-[10px] text-muted-foreground">{nf1.format(m?.share_pct ?? 0)} % ₽</div>
                    </button>
                  )
                })}
              </Fragment>
            ))}
          </div>

          {/* Совет принадлежит КЛАССУ, а не строке таблицы: в таблице он
              повторялся восемнадцать раз подряд и съедал четверть ширины. */}
          <div className="mt-3 min-h-[3rem] rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
            {cell
              ? <><span className="font-medium text-foreground">{cell}:</span> {byCell.get(cell)?.hint}</>
              : 'Заливка — доля выручки класса. Нажмите клетку, чтобы оставить в таблице только её позиции.'}
          </div>
          {unclassified.length > 0 && (
            <div className="mt-2 text-[11px] text-muted-foreground">
              Ещё {unclassified.length} позиций без класса: история короче
              6 {bucketWord} — разброс на таком отрезке показывает случайность, а не спрос.
            </div>
          )}
        </CardContent></Card>

        <Card><CardContent className="pt-4">
          <div className="mb-1 text-sm font-medium">Где лежат деньги</div>
          <p className="mb-3 text-xs text-muted-foreground">
            Позиции по убыванию выручки, разбитые на пять равных групп.
          </p>
          <div className="space-y-1.5">
            {data.quintiles.map((qq, idx) => {
              const label = QUINTILE_LABELS[idx] ?? `${qq.quintile}-я группа`
              const active = quintile === qq.quintile
              return (
                <button key={qq.quintile} type="button" aria-pressed={active}
                  onClick={() => setSel(active ? null : { kind: 'quintile', n: qq.quintile })}
                  title={`Оставить в таблице только эти позиции (${qq.count})`}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs transition-colors',
                    active ? 'bg-primary/10 ring-1 ring-primary/40' : 'hover:bg-muted/40',
                  )}>
                  <span className={cn('w-36 shrink-0', active ? 'font-medium text-primary' : 'text-muted-foreground')}>{label}</span>
                  <div className="h-5 flex-1 overflow-hidden rounded bg-muted/40">
                    <div className={cn('h-full rounded-r-[3px]', active ? 'bg-primary' : 'bg-blue-500/70')}
                      style={{ width: `${Math.max(1.5, Math.min(100, qq.share_pct))}%` }} />
                  </div>
                  <span className="w-14 shrink-0 text-right font-medium tabular-nums">{nf1.format(qq.share_pct)} %</span>
                  <span className="w-16 shrink-0 text-right text-muted-foreground">{qq.count} поз.</span>
                </button>
              )
            })}
          </div>
          {data.quintiles.length >= 5 && (
            <p className="mt-3 text-xs text-muted-foreground">
              Верхняя пятая часть даёт {nf1.format(data.quintiles[0].share_pct)} % выручки,
              нижняя — {nf1.format(data.quintiles[4].share_pct)} %. Средняя по сети такие
              полюса смешивает: решения принимаются по верхушке и по хвосту.
              Нажмите группу, чтобы оставить её позиции в таблице.
            </p>
          )}
        </CardContent></Card>
      </div>

      <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
        <div className="flex items-center justify-between border-b px-4 py-2.5">
          <span className="text-sm font-medium">
            {cell ? `Класс ${cell}`
              : quintile ? QUINTILE_LABELS[quintile - 1] ?? `Группа ${quintile}`
              : 'Все позиции'}
            <span className="ml-2 text-xs font-normal text-muted-foreground">{rows.length}</span>
          </span>
          {sel && (
            <button onClick={() => setSel(null)} className="text-xs text-primary hover:underline">
              Снять фильтр
            </button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                {dim !== 'fuel' && <Th>АЗС</Th>}
                {dim !== 'station' && <Th>Топливо</Th>}
                {/* Столбец класса не нужен, когда таблица УЖЕ отфильтрована по
                    классу: шестнадцать одинаковых бейджей ничего не сообщают,
                    а класс назван в заголовке карточки. */}
                {!cell && <Th>Класс</Th>}
                <Th right>Выручка, ₽</Th>
                <Th right>Доля</Th><Th right>Накопл.</Th><Th right>Литры</Th>
                <Th right>Реализации</Th><Th right>Карт</Th>
                <Th right>Разброс</Th><Th right>Тренд</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => {
                const tr = TREND_VIEW[i.trend ?? 'flat'] ?? TREND_VIEW.flat
                return (
                  <tr key={i.key} className="border-b border-border/50 hover:bg-muted/25">
                    {dim !== 'fuel' && <Td>{i.station_label ?? '—'}</Td>}
                    {dim !== 'station' && (
                      <Td className="text-muted-foreground">{i.fuel_name ?? '—'}</Td>
                    )}
                    {!cell && (
                      <Td>
                        <span title={i.hint}
                          className={cn('rounded px-1.5 py-0.5 font-semibold',
                            i.xyz === '—' ? 'bg-muted/60 text-muted-foreground' : 'bg-primary/10 text-primary')}>
                          {i.xyz === '—' ? `${i.abc}·—` : i.abc + i.xyz}
                        </span>
                      </Td>
                    )}
                    <Td right className="font-medium">{money(i.amount)}</Td>
                    <Td right>
                      {/* Бар внутри ячейки — доля читается взглядом, а не сравнением цифр. */}
                      <div className="relative">
                        <div className="absolute inset-y-0 right-0 rounded-sm bg-primary/15"
                          style={{ width: `${Math.min(100, i.share_pct / (data.items[0]?.share_pct || 1) * 100)}%` }} />
                        <span className="relative">{nf1.format(i.share_pct)} %</span>
                      </div>
                    </Td>
                    <Td right className="text-muted-foreground">{nf1.format(i.cum_share_pct)} %</Td>
                    <Td right>{fmtLiters(i.liters)}</Td>
                    <Td right>{nf0.format(i.fills)}</Td>
                    <Td right>{nf0.format(i.cards)}</Td>
                    <Td right className={cn(i.cv != null && i.cv > 0.5 && 'text-amber-400')}>
                      {i.cv != null ? `${nf0.format(i.cv * 100)} %` : '—'}
                    </Td>
                    <Td right>
                      <span className={cn('tabular-nums', tr.cls)}
                        title={`${tr.label}: ${i.trend_pct != null ? nf0.format(i.trend_pct) : '—'} % за период`}>
                        {tr.sign} {i.trend_pct != null ? `${nf0.format(i.trend_pct)} %` : '—'}
                      </span>
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent></Card>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        <span className="font-medium text-foreground/80">Как читается разброс.</span>{' '}
        Это отклонение от собственного тренда позиции за последние
        12 {bucket === 'week' ? 'недель' : 'месяцев'}, а не за весь период: сеть растёт,
        и без поправки на рост любая позиция выглядела бы рваной. Куда идёт спрос,
        показывает колонка «Тренд». Нули до подключения станции в расчёт не входят —
        отсчёт ведётся от первой продажи позиции.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 3. Клиенты: когорты и движение базы
// ═══════════════════════════════════════════════════════════════════════

export function FuelClientsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-clients', companyId, dateFrom, dateTo, scope.key],
    queryFn: () => getFuelClients({ companyId, dateFrom, dateTo, stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  if (q.isError) return <Failed error={q.error} onRetry={() => void q.refetch()} />
  const data = q.data
  if (!data) return <Empty />
  const m = data.movement
  const c = data.concentration

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Клиенты: когорты и удержание"
        hint="По картам за период · наличные без карты в клиентские метрики не входят"
        exportEl={() => ref.current} />

      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
          <Metric label="Активных карт" value={nf0.format(m.active)}
            hint={`${fmtMoneyShort(data.totals.amount)} ₽ · ${nf0.format(data.totals.fills)} покупок`} />
          <Metric label="Новые" value={nf0.format(m.new)} tone="success"
            hint={`${fmtMoneyShort(m.new_amount)} ₽ · первая покупка в периоде`} />
          <Metric label="Вернулись" value={nf0.format(m.returning)}
            hint={`${fmtMoneyShort(m.returning_amount)} ₽`} />
          <Metric label="Не вернулись" value={nf0.format(m.churned)} tone={m.churned ? 'danger' : undefined}
            hint={`были в ${m.prev_period.from.slice(5)}–${m.prev_period.to.slice(5)}`} />
          <Metric label="Удержание" value={pct(m.retention_pct)}
            tone={(m.retention_pct ?? 100) < 60 ? 'danger' : 'success'}
            hint={`из ${nf0.format(m.prev_active)} прошлого периода`} />
          <Metric label="Топ-10 % карт" value={pct(c.top10_pct)} tone="info"
            hint={`${nf0.format(c.cards_top10)} карт · верхний 1 % → ${pct(c.top1_pct)}`} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Когорты по частоте покупок</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Когорта</Th><Th right>Карт</Th><Th right>Доля карт</Th>
                <Th right>Выручка</Th><Th right>Доля выручки</Th><Th right>На карту</Th>
              </tr>
            </thead>
            <tbody>
              {data.cohorts.map((co) => (
                <tr key={co.code} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{co.label}</Td>
                  <Td right>{nf0.format(co.cards)}</Td>
                  <Td right className="text-muted-foreground">{pct(co.cards_pct)}</Td>
                  <Td right>{fmtMoney(co.amount)}</Td>
                  <Td right className="font-medium">{pct(co.amount_pct)}</Td>
                  <Td right>{fmtMoney(co.avg_card)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Что берут: виды топлива</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Топливо</Th><Th right>Карт</Th><Th right>Покупок</Th>
                <Th right>Выручка</Th><Th right>Доля</Th><Th right>Ср. чек</Th>
              </tr>
            </thead>
            <tbody>
              {data.by_fuel.map((f) => (
                <tr key={f.fuel_name} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{f.fuel_name}</Td>
                  <Td right>{nf0.format(f.cards)}</Td>
                  <Td right>{nf0.format(f.fills)}</Td>
                  <Td right>{fmtMoney(f.amount)}</Td>
                  <Td right className="font-medium">{pct(f.amount_pct)}</Td>
                  <Td right>{fmtMoney(f.avg_check)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Топ карт по обороту</div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b bg-muted/35 text-muted-foreground">
                  <Th>Карта</Th><Th right>Покупок</Th><Th right>Выручка</Th>
                  <Th right>Ср. чек</Th><Th right>АЗС</Th><Th right>Последняя</Th>
                </tr>
              </thead>
              <tbody>
                {data.top_cards.map((k) => (
                  <tr key={k.card} className="border-b border-border/50 hover:bg-muted/25">
                    <Td className="font-mono text-[11px]">
                      {k.card}{k.is_new && <span className="ml-1.5 text-[10px] text-emerald-400">новая</span>}
                    </Td>
                    <Td right>{nf0.format(k.fills)}</Td>
                    <Td right>{fmtMoney(k.amount)}</Td>
                    <Td right>{fmtMoney(k.avg_check)}</Td>
                    <Td right>{k.stations}</Td>
                    <Td right className="text-muted-foreground">{k.last_at ? formatDate(k.last_at) : '—'}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent></Card>
      </div>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        «Новая» — карта, у которой ПЕРВАЯ в истории покупка попала в период; иначе
        новичком выглядел бы любой, кто просто не заезжал полгода. Границы когорт
        привязаны к длине периода, поэтому концентрация (верхние 10 % по обороту)
        показана отдельно — она от границ не зависит.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 4. Визиты (визиты)
// ═══════════════════════════════════════════════════════════════════════

export function FuelVisitsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [gap, setGap] = useState<'5' | '10' | '20'>('10')
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-visits', companyId, dateFrom, dateTo, gap, scope.key],
    queryFn: () => getFuelVisits({ companyId, dateFrom, dateTo, gapMin: Number(gap), stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  if (q.isError) return <Failed error={q.error} onRetry={() => void q.refetch()} />
  const data = q.data
  if (!data) return <Empty />
  const t = data.totals
  const lift = t.avg_fill_check ? (t.avg_visit_check / t.avg_fill_check - 1) * 100 : 0

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Визиты (визиты)"
        hint="Соседние реализации одной карты на одной АЗС — это один визит, а не несколько покупок"
        exportEl={() => ref.current}>
        <Toggle value={gap} onChange={setGap} title="Порог склейки реализаций в один визит"
          opts={[{ v: '5', label: '5 мин' }, { v: '10', label: '10 мин' }, { v: '20', label: '20 мин' }]} />
      </Head>

      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
          <Metric label="Визитов" value={nf0.format(t.visits)}
            hint={`из ${nf0.format(t.fills)} реализаций`} />
          <Metric label="Реализаций на визит" value={nf2.format(t.fills_per_visit)}
            hint={`составных визитов ${pct(t.multi_pct)}`} />
          <Metric label="Чек визита" value={fmtMoney(t.avg_visit_check)} tone="info"
            hint={`по реализациям ${fmtMoney(t.avg_fill_check)}`} />
          <Metric label="Разница" value={`+${nf1.format(lift)} %`} tone="success"
            hint="насколько занижен чек по реализациям" />
          <Metric label="Объём визита" value={`${nf1.format(t.avg_visit_liters)} л`}
            hint={fmtLiters(t.liters)} />
          <Metric label="Разных видов в визите" value={nf0.format(t.multi_fuel_visits)}
            hint={`${pct(t.multi_fuel_pct)} визитов · бак + канистра`} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Сколько реализаций в визите</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Реализаций</Th><Th right>Визитов</Th><Th right>Доля</Th><Th right>Выручка</Th>
              </tr>
            </thead>
            <tbody>
              {data.distribution.map((d) => (
                <tr key={d.fills} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{d.fills}</Td>
                  <Td right>{nf0.format(d.visits)}</Td>
                  <Td right className="text-muted-foreground">{pct(d.share_pct)}</Td>
                  <Td right>{fmtMoney(d.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Чек визита по видам топлива</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Топливо</Th><Th right>Визитов</Th><Th right>Чек визита</Th>
                <Th right>Литров за визит</Th><Th right>Выручка</Th>
              </tr>
            </thead>
            <tbody>
              {data.by_fuel.map((f) => (
                <tr key={f.fuel_name} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{f.fuel_name}</Td>
                  <Td right>{nf0.format(f.visits)}</Td>
                  <Td right className="font-medium">{fmtMoney(f.avg_visit_check)}</Td>
                  <Td right>{nf1.format(f.avg_visit_liters)} л</Td>
                  <Td right>{fmtMoney(f.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">
            Только визиты с одним видом топлива: смешанные ({pct(t.multi_fuel_pct)}) в разрез
            не входят — их чек принадлежит сразу двум продуктам.
          </div>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">По станциям</div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b bg-muted/35 text-muted-foreground">
                  <Th>АЗС</Th><Th right>Визитов</Th><Th right>Составных</Th>
                  <Th right>Чек визита</Th><Th right>Выручка</Th>
                </tr>
              </thead>
              <tbody>
                {data.by_station.map((s) => (
                  <tr key={s.station_code} className="border-b border-border/50 hover:bg-muted/25">
                    <Td>{s.station}</Td>
                    <Td right>{nf0.format(s.visits)}</Td>
                    <Td right className="text-muted-foreground">{pct(s.multi_pct)}</Td>
                    <Td right>{fmtMoney(s.avg_visit_check)}</Td>
                    <Td right>{fmtMoney(s.amount)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent></Card>
      </div>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        Склейка идёт по карте и станции: наличные без карты остаются отдельными реализациями —
        связать их с одним автомобилем нечем. Порог по умолчанию 10 минут: дольше на
        колонке не стоят, это уже следующий заезд.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 5. Инсайты для шапки «Обзора»
// ═══════════════════════════════════════════════════════════════════════

const TONE_STYLE = {
  warning: { border: 'border-amber-500/35 bg-amber-500/5', icon: AlertTriangle, color: 'text-amber-400' },
  success: { border: 'border-emerald-500/30 bg-emerald-500/5', icon: TrendingUp, color: 'text-emerald-400' },
  info: { border: 'border-blue-500/30 bg-blue-500/5', icon: Info, color: 'text-blue-400' },
} as const

/**
 * Полоса выводов над обзором: не «сколько заработали» (это KPI ниже), а что в
 * данных видно и требует решения. Каждый вывод ведёт на экран, где эта цифра
 * разбирается подробно.
 */
export function FuelInsightsBar({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const { company } = useCompany()
  const { setCoreMode } = useWorkspace()
  // Вывод ведёт на пункт в ЕГО разделе: «Загрузка ТРК» живёт в «Сети», «Визиты» —
  // в «Аналитике», и без смены раздела ссылка открыла бы пустой экран.
  const open = (sub: string) => {
    const mode = workspaceModeForKey(sub)
    if (mode) setCoreMode(mode as CoreMode, sub)
  }
  const q = useQuery({
    queryKey: ['fuel-insights', companyId, dateFrom, dateTo],
    queryFn: () => getFuelInsightsSafe({ companyId, dateFrom, dateTo }),
    enabled: company.profileId === 'fuel',
    staleTime: 5 * 60_000,
  })
  const items = q.data?.insights ?? []
  if (!items.length) return null
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {items.map((i) => {
        const s = TONE_STYLE[i.tone] ?? TONE_STYLE.info
        const Icon = s.icon
        const clickable = !!i.link?.sub
        return (
          <div key={i.key}
            onClick={clickable ? () => open(i.link!.sub!) : undefined}
            className={cn('flex items-start gap-2.5 rounded-lg border px-3 py-2.5', s.border,
              clickable && 'cursor-pointer transition-colors hover:bg-muted/30')}>
            <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', s.color)} />
            <div className="min-w-0">
              <div className="text-sm font-medium">{i.title}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{i.text}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Инсайты не должны ронять обзор: пустой список честнее пустого экрана. */
async function getFuelInsightsSafe(p: { companyId: string; dateFrom: string; dateTo: string }) {
  const { getFuelInsights } = await import('@/services/fuelNetworkService')
  try {
    return await getFuelInsights(p)
  } catch {
    return { period: { from: p.dateFrom, to: p.dateTo }, insights: [] }
  }
}
