/**
 * «Производители» — сеть глазами марки железа.
 *
 * Инженер смотрит на сеть не только станциями: если у вендора из четырнадцати
 * станций не работает ни одна, дело не в конкретной площадке, и ехать надо не
 * бригадой, а разговором о поставке. Экран отвечает, какое железо держит
 * нагрузку, а какое стоит.
 *
 * Марки сравниваются тремя мерами сразу, потому что порознь они врут:
 * живых станций (сколько реально отпускало энергию), доля приездов «ни с чем»
 * и отдача — кВт·ч на станцию в сутки. Марка с двумя станциями и марка со ста
 * тридцатью при одинаковом проценте отказов — разный разговор, поэтому объём
 * всегда рядом с процентом.
 *
 * Строка раскрывается в станции этой марки: сверху те, где приездов впустую
 * больше всего. Оттуда — клик на станцию, и открывается её карточка.
 */
import { Fragment, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { OpsSnapshotNotice } from './OpsSnapshotNotice'
import { ChevronDown, ChevronRight, Loader2, PlugZap } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import { StationLink } from '@/components/common/StationLink'
import { SortTh } from '@/components/workspace/SortableTh'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { useTableSort } from '@/hooks/useTableSort'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { cn } from '@/lib/utils'
import {
  getNetworkVendors, type VendorRow, type VendorStationRow,
} from '@/services/opsService'

const nf = new Intl.NumberFormat('ru-RU')
const ОКНА = [30, 90, 180] as const

function тишина(дней: number | null): string {
  if (дней === null) return 'ни разу'
  if (дней === 0) return 'сегодня'
  return `${дней} дн`
}

/** Станции выбранной марки — раскрытие строки. */
function VendorStations({ vendor, days, region, asOf }: {
  vendor: string; days: number; region?: string; asOf?: string
}) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['ops-vendor-stations', companyId, vendor, days, region ?? '', asOf ?? ''],
    queryFn: () => getNetworkVendors(companyId, { vendor, days, region, asOf }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  // Раскрытие — такая же таблица, как остальные: по ней выбирают, куда ехать
  // первой, и сортировка столбцов ей нужна ровно так же (20.09.2026).
  // Хук объявлен ДО ранних возвратов: порядок вызовов должен совпадать в любом
  // состоянии загрузки.
  const сорт = useMemo(() => ({
    number: (s: VendorStationRow) => s.number ?? s.code,
    name: (s: VendorStationRow) => s.name,
    region: (s: VendorStationRow) => s.region,
    model: (s: VendorStationRow) => s.model,
    visits: (s: VendorStationRow) => s.visits,
    failed: (s: VendorStationRow) => s.failedVisitsPct,
    silent: (s: VendorStationRow) => s.silentDays,
  }), [])
  const таблица = useTableSort(q.data?.stations ?? [], сорт, { key: 'failed', dir: 'desc' })

  if (q.isLoading) {
    return <div className="flex justify-center py-4">
      <Loader2 className="size-4 animate-spin text-muted-foreground" />
    </div>
  }
  const строки = таблица.rows
  if (!строки.length) {
    return <div className="py-3 text-center text-xs text-muted-foreground">
      Станций этой марки в выборке нет
    </div>
  }

  return (
    <div className="overflow-x-auto rounded border border-border/60 bg-background/50">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/60 text-muted-foreground">
            <SortTh sortKey="number" sort={таблица.sort} onSort={таблица.toggle}>№</SortTh>
            <SortTh sortKey="name" sort={таблица.sort} onSort={таблица.toggle}>Станция</SortTh>
            <SortTh sortKey="region" sort={таблица.sort} onSort={таблица.toggle}>Регион</SortTh>
            <SortTh sortKey="model" sort={таблица.sort} onSort={таблица.toggle}>Модель</SortTh>
            <SortTh sortKey="visits" sort={таблица.sort} onSort={таблица.toggle} align="right">Приездов</SortTh>
            <SortTh sortKey="failed" sort={таблица.sort} onSort={таблица.toggle} align="right">Ни с чем</SortTh>
            <SortTh sortKey="silent" sort={таблица.sort} onSort={таблица.toggle} align="right">Молчит</SortTh>
          </tr>
        </thead>
        <tbody>
          {строки.slice(0, 60).map((s) => (
            <tr key={s.locationId} className="border-b border-border/30">
              <td className="p-1.5 font-mono text-muted-foreground">
                {s.number ?? s.code ?? '—'}
              </td>
              <td className="max-w-[220px] truncate p-1.5 font-medium">
                <StationLink station={s.locationId}>{s.name}</StationLink>
              </td>
              <td className="p-1.5 text-muted-foreground">{s.region ?? '—'}</td>
              <td className="p-1.5 text-muted-foreground">{s.model ?? '—'}</td>
              <td className="p-1.5 text-right tabular-nums">{nf.format(s.visits)}</td>
              <td className={cn('p-1.5 text-right tabular-nums',
                s.failedVisitsPct >= 20 && 'font-medium text-red-600 dark:text-red-400')}>
                {s.visits ? `${s.failedVisitsPct} %` : '—'}
              </td>
              <td className="p-1.5 text-right tabular-nums text-muted-foreground">
                {тишина(s.silentDays)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {строки.length > 60 && (
        <div className="p-2 text-center text-xs text-muted-foreground">
          показаны первые 60 из {nf.format(строки.length)}
        </div>
      )}
    </div>
  )
}

export function NetworkVendorsPanel() {
  const { companyId } = useCompany()
  const { regionIds } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  const [окно, setОкно] = useState<number>(90)
  const [открыта, setОткрыта] = useState<string | null>(null)
  const [поиск, setПоиск] = useState('')
  const [регионОтбора, setРегионОтбора] = useState('all')
  const [вид, setВид] = useState('list')
  const [наДень, setНаДень] = useState('')

  // Регион с экрана сильнее области учёта из шапки: инженер смотрит марки
  // сразу по всей сети, а сужает разрез руками, когда нашёл подозрительную.
  const регион = регионОтбора !== 'all'
    ? регионОтбора
    : regionIds.length ? regionIds.join('|') : undefined
  const q = useQuery({
    queryKey: ['ops-vendors', companyId, окно, регион ?? '', наДень],
    queryFn: () => getNetworkVendors(companyId, {
      days: окно, region: регион, asOf: наДень || undefined }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  // Станции всех марок разом — только для сводной, поэтому запрашиваются
  // лениво: на списке марок эта выборка не нужна.
  const qВсе = useQuery({
    queryKey: ['ops-vendor-stations-all', companyId, окно, регион ?? '', наДень],
    queryFn: () => getNetworkVendors(companyId, {
      vendor: '*', days: окно, region: регион, asOf: наДень || undefined }),
    enabled: !!companyId && вид === 'pivot',
    staleTime: 60_000,
  })

  const сортировка = useMemo(() => ({
    vendor: (r: VendorRow) => r.vendor,
    stations: (r: VendorRow) => r.stations,
    live: (r: VendorRow) => r.livePct,
    silent: (r: VendorRow) => r.silentWeek,
    visits: (r: VendorRow) => r.visits,
    failed: (r: VendorRow) => r.failedVisitsPct,
    attempts: (r: VendorRow) => r.attemptsPerVisit,
    bad: (r: VendorRow) => r.badStations,
    output: (r: VendorRow) => r.kwhPerStationDay,
  }), [])

  const строки = useMemo(() => {
    const все = q.data?.vendors ?? []
    const текст = поиск.trim().toLowerCase()
    if (!текст) return все
    return все.filter((r) => [r.vendor, ...r.models]
      .some((v) => (v ?? '').toLowerCase().includes(текст)))
  }, [q.data, поиск])

  const таблица = useTableSort(строки, сортировка)

  if (q.isLoading) {
    return <div className="flex justify-center py-12">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.error || !q.data) {
    return <div className="p-8 text-center text-sm text-muted-foreground">
      Не удалось собрать разрез по производителям
    </div>
  }

  const d = q.data
  const t = d.totals

  return (
    <div ref={экран} className="space-y-3 p-3">
      <OpsSnapshotNotice data={d} />
      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">Производители</div>
              <div className="text-xs text-muted-foreground">
                {nf.format(t.vendors)} марок · {nf.format(t.stations)} станций ·
                окно {d.days} дней по {d.asOf.slice(0, 10).split('-').reverse().join('.')}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {ОКНА.map((о) => (
                <Button key={о} size="sm" variant={окно === о ? 'default' : 'outline'}
                  className="h-7 px-2 text-xs" onClick={() => setОкно(о)}>
                  {о} дн
                </Button>
              ))}
              <label className="text-xs text-muted-foreground" htmlFor="ven-asof">
                на день
              </label>
              <Input id="ven-asof" type="date" value={наДень}
                max={d.dataThrough?.slice(0, 10)}
                onChange={(e) => setНаДень(e.target.value)}
                className="h-7 w-36 text-xs" />
              {наДень && (
                <Button size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => setНаДень('')}>
                  К последним данным
                </Button>
              )}
              <ExportButton title="Производители"
                subtitle={`окно ${d.days} дней по ${d.asOf.slice(0, 10)}`}
                getEl={() => экран.current} />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Select value={регионОтбора} onValueChange={setРегионОтбора}>
              <SelectTrigger className="h-7 w-52 text-xs">
                <SelectValue placeholder="Регион" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Вся сеть</SelectItem>
                {d.regions.map((р) => (
                  <SelectItem key={р} value={р}>{р}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
              placeholder="Марка или модель…" className="h-7 w-52 text-xs" />
            {(регионОтбора !== 'all' || поиск) && (
              <Button size="sm" variant="ghost" className="h-7 text-xs"
                onClick={() => { setРегионОтбора('all'); setПоиск('') }}>
                Сбросить
              </Button>
            )}
            <PanelViewTabs value={вид} onChange={setВид} label={null} tabs={[
              { k: 'list', label: 'Марки' },
              { k: 'pivot', label: 'Сводная' },
            ]} />
          </div>

          <p className="text-xs text-muted-foreground">{d.note}</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-3">
          {вид === 'pivot' ? (
            qВсе.isLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              /* Сводная идёт от марки вниз: марка → модель → регион, по
                 станциям, а не по агрегату — иначе «вниз к деталям» упирается
                 в одну строку на вендора. */
              <ReportPivot
                fields={['vendor', 'model', 'region', 'state', 'stations',
                         'visits', 'visitsFailed', 'energyKwh', 'revenue']}
                columns={['Марка', 'Модель', 'Регион', 'Как работает', 'Станций',
                          'Приездов', 'Ни с чем', 'кВт·ч', 'Выручка, руб']}
                rows={(qВсе.data?.stations ?? []).map((s) => ({
                  vendor: s.vendor,
                  model: s.model ?? '— модель не указана',
                  region: s.region ?? '— регион не указан',
                  state: s.silentDays === null ? 'ни разу не заряжала'
                    : s.silentDays <= 2 ? 'заряжает'
                      : s.silentDays <= 7 ? 'молчит до недели' : 'молчит больше недели',
                  stations: 1,
                  visits: s.visits,
                  visitsFailed: s.visitsFailed,
                  energyKwh: s.energyKwh,
                  revenue: s.revenue,
                }))} />
            )
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm"
              {...exportRows('Производители',
                ['Марка', 'Станций', 'Живых за 2 суток', 'Живых %', 'Молчат > недели',
                 'Приездов', 'Ни с чем %', 'Попыток на приезд', 'Плохих станций',
                 'кВтч на станцию в сутки', 'Моделей'],
                таблица.rows.map((r) => [
                  r.vendor, r.stations, r.charging2d, r.livePct, r.silentWeek,
                  r.visits, r.failedVisitsPct, r.attemptsPerVisit, r.badStations,
                  r.kwhPerStationDay, r.modelsCount,
                ]))}>
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="w-6 p-1.5" />
                  <SortTh sortKey="vendor" sort={таблица.sort} onSort={таблица.toggle}>Марка</SortTh>
                  <SortTh sortKey="stations" sort={таблица.sort} onSort={таблица.toggle} align="right">Станций</SortTh>
                  <SortTh sortKey="live" sort={таблица.sort} onSort={таблица.toggle} align="right">Живых</SortTh>
                  <SortTh sortKey="silent" sort={таблица.sort} onSort={таблица.toggle} align="right">Молчат</SortTh>
                  <SortTh sortKey="visits" sort={таблица.sort} onSort={таблица.toggle} align="right">Приездов</SortTh>
                  <SortTh sortKey="failed" sort={таблица.sort} onSort={таблица.toggle} align="right">Ни с чем</SortTh>
                  <SortTh sortKey="attempts" sort={таблица.sort} onSort={таблица.toggle} align="right">Попыток / приезд</SortTh>
                  <SortTh sortKey="bad" sort={таблица.sort} onSort={таблица.toggle} align="right">Плохих станций</SortTh>
                  <SortTh sortKey="output" sort={таблица.sort} onSort={таблица.toggle} align="right">кВтч / станцию в сутки</SortTh>
                </tr>
              </thead>
              <tbody>
                {таблица.rows.map((r) => {
                  const открыт = открыта === r.vendor
                  return (
                    <Fragment key={r.vendor}>
                      <tr
                        onClick={() => setОткрыта(открыт ? null : r.vendor)}
                        className={cn('cursor-pointer border-b border-border/40 hover:bg-accent/30',
                          r.failedVisitsPct >= d.threshold && 'bg-red-500/5')}>
                        <td className="p-1.5">
                          {открыт ? <ChevronDown className="size-3.5 opacity-60" />
                            : <ChevronRight className="size-3.5 opacity-60" />}
                        </td>
                        <td className="p-1.5 font-medium">
                          {r.vendor}
                          {r.modelsCount > 0 && (
                            <span className="ml-1.5 text-xs text-muted-foreground">
                              {r.modelsCount} {r.modelsCount === 1 ? 'модель' : 'моделей'}
                            </span>
                          )}
                        </td>
                        <td className="p-1.5 text-right tabular-nums">{nf.format(r.stations)}</td>
                        {/* Живость марки: станций, реально отпускавших энергию.
                            Именно здесь видно железо, которое числится, но стоит. */}
                        <td className={cn('p-1.5 text-right tabular-nums',
                          r.livePct < 50 && 'text-red-600 dark:text-red-400')}>
                          {nf.format(r.charging2d)}
                          <span className="ml-1 text-xs text-muted-foreground">{r.livePct} %</span>
                        </td>
                        <td className="p-1.5 text-right tabular-nums text-muted-foreground">
                          {nf.format(r.silentWeek)}
                        </td>
                        <td className="p-1.5 text-right tabular-nums">{nf.format(r.visits)}</td>
                        <td className={cn('p-1.5 text-right font-medium tabular-nums',
                          r.failedVisitsPct >= d.threshold && 'text-red-600 dark:text-red-400')}>
                          {r.visits ? `${r.failedVisitsPct} %` : '—'}
                        </td>
                        <td className={cn('p-1.5 text-right tabular-nums',
                          r.attemptsPerVisit >= 2 && 'text-amber-600 dark:text-amber-400')}>
                          {r.visits ? r.attemptsPerVisit : '—'}
                        </td>
                        <td className="p-1.5 text-right tabular-nums">{nf.format(r.badStations)}</td>
                        <td className="p-1.5 text-right tabular-nums">{r.kwhPerStationDay}</td>
                      </tr>
                      {открыт && (
                        <tr>
                          <td colSpan={10} className="bg-muted/20 p-2">
                            {r.models.length > 0 && (
                              <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs">
                                <PlugZap className="size-3.5 text-muted-foreground" />
                                <span className="text-muted-foreground">модели:</span>
                                {r.models.map((m) => (
                                  <span key={m} className="rounded bg-background px-1.5 py-0.5">
                                    {m}
                                  </span>
                                ))}
                                {r.avgPowerKwt != null && (
                                  <span className="ml-2 text-muted-foreground">
                                    средняя мощность {r.avgPowerKwt} кВт
                                  </span>
                                )}
                              </div>
                            )}
                            <VendorStations vendor={r.vendor} days={окно} region={регион}
                              asOf={наДень || undefined} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
