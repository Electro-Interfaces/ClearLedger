/**
 * «Надёжность» — вторая половина рабочего дня инженера.
 *
 * «Состояние сети» отвечает, работает ли станция вообще. Здесь — про станции,
 * которые в сети и даже показывают сессии, а клиент уезжает ни с чем.
 *
 * Считаем ПРИЕЗДАМИ, а не попытками. CPO пишет каждое втыкание разъёма отдельной
 * строкой: человек, у которого схватилось с третьего раза, даёт три сессии — две
 * с ошибкой и одну рабочую. По сессиям это «27 % брака», по приездам — 9,8 %
 * тех, кто уехал ни с чем. Первое описывает железо, второе — клиента, и для
 * разговора об эксплуатации верно второе.
 *
 * Рядом — попытки на приезд: визит удался, но с четвёртого раза (у худших
 * станций так и есть) — это станция «работает» с испорченным впечатлением.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { OpsSnapshotNotice } from './OpsSnapshotNotice'
import { AlertTriangle, BatteryWarning, Loader2, Users, Zap } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
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
  getNetworkReliability, type NetworkReliability, type ReliabilityRow,
} from '@/services/opsService'

const nf = new Intl.NumberFormat('ru-RU')
const ОКНА = [30, 90, 180] as const

/** Плитка показателя; с `onClick` — ещё и фильтр списка снизу. */
function Плитка({ icon: Icon, label, value, hint, tone, onClick, active }: {
  icon: typeof Zap; label: string; value: string; hint?: string; tone?: string
  onClick?: () => void; active?: boolean
}) {
  const внутри = (
    <>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" />{label}
      </div>
      <div className={cn('mt-0.5 text-lg font-semibold tabular-nums', tone)}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </>
  )
  const вид = cn('rounded-lg border bg-card px-3 py-2 text-left',
    active ? 'border-primary ring-1 ring-primary/40' : 'border-border/60')
  if (!onClick) return <div data-kpi className={вид}>{внутри}</div>
  return (
    <button type="button" data-kpi onClick={onClick} aria-pressed={!!active}
      className={cn(вид, 'transition-colors hover:border-primary/60')}>
      {внутри}
    </button>
  )
}

export function NetworkReliabilityPanel() {
  const { companyId } = useCompany()
  const { regionIds } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  const [окно, setОкно] = useState<number>(90)
  const [поиск, setПоиск] = useState('')
  const [регионОтбора, setРегионОтбора] = useState('all')
  const [маркаОтбора, setМаркаОтбора] = useState('all')
  const [вид, setВид] = useState('list')
  // Окно можно закончить не «сегодня», а выбранным днём: «как станции работали
  // в августе» — это тот же расчёт, сдвинутый назад.
  const [наДень, setНаДень] = useState('')
  // Разрез по показателю: нажатие на плитку показывает ровно те станции, про
  // которые это число. Иначе «61 станция хуже 20 %» остаётся числом, к которому
  // надо самому подбирать сортировку.
  const [разрез, setРазрез] = useState<'all' | 'bad' | 'attempts' | 'clients'>('all')

  const регион = регионОтбора !== 'all' ? регионОтбора : regionIds.length ? regionIds.join('|') : undefined
  const q = useQuery({
    queryKey: ['ops-reliability', companyId, окно, регион ?? '', наДень],
    queryFn: () => getNetworkReliability(companyId, {
      days: окно, region: регион, asOf: наДень || undefined }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  const сортировка = useMemo(() => ({
    name: (r: ReliabilityRow) => r.name,
    number: (r: ReliabilityRow) => r.number ?? r.code,
    region: (r: ReliabilityRow) => r.region,
    visits: (r: ReliabilityRow) => r.visits,
    failedVisits: (r: ReliabilityRow) => r.failedVisitsPct,
    attempts: (r: ReliabilityRow) => r.attemptsPerVisit,
    empty: (r: ReliabilityRow) => r.emptyPct,
    clients: (r: ReliabilityRow) => r.clientsLost,
    kwh: (r: ReliabilityRow) => r.kwhPerSession,
  }), [])

  // Значения отбора — из самой выборки: список марок в сети меняется, и свой
  // справочник разошёлся бы с ним на первой же поставке.
  const [регионыСписком, маркиСписком] = useMemo(() => {
    const рег = new Set<string>()
    const мар = new Set<string>()
    for (const r of q.data?.stations ?? []) {
      if (r.region) рег.add(r.region)
      if (r.brand) мар.add(r.brand)
    }
    const по = (a: string, b: string) => a.localeCompare(b, 'ru')
    return [[...рег].sort(по), [...мар].sort(по)]
  }, [q.data])

  const порог = q.data?.threshold ?? 20
  const строки = useMemo(() => {
    let все = q.data?.stations ?? []
    if (разрез === 'bad') все = все.filter((r) => r.failedVisitsPct >= порог)
    if (разрез === 'attempts') все = все.filter((r) => r.attemptsPerVisit >= 2)
    if (разрез === 'clients') все = все.filter((r) => r.clientsLost > 0)
    if (регионОтбора !== 'all') все = все.filter((r) => r.region === регионОтбора)
    if (маркаОтбора !== 'all') все = все.filter((r) => r.brand === маркаОтбора)
    const текст = поиск.trim().toLowerCase()
    if (!текст) return все
    return все.filter((r) => [r.name, r.number, r.code, r.city, r.region, r.brand, r.model]
      .some((v) => (v ?? '').toLowerCase().includes(текст)))
  }, [q.data, поиск, регионОтбора, маркаОтбора, разрез, порог])

  const таблица = useTableSort(строки, сортировка)

  const сортРегионов = useMemo(() => ({
    region: (g: NetworkReliability['regions'][number]) => g.region,
    stations: (g: NetworkReliability['regions'][number]) => g.stations,
    visits: (g: NetworkReliability['regions'][number]) => g.visits,
    failed: (g: NetworkReliability['regions'][number]) => g.failedVisitsPct,
    bad: (g: NetworkReliability['regions'][number]) => g.bad,
  }), [])
  const регионы = useTableSort(q.data?.regions ?? [], сортРегионов,
    { key: 'failed', dir: 'desc' })

  if (q.isLoading) {
    return <div className="flex justify-center py-12">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.error || !q.data) {
    return <div className="p-8 text-center text-sm text-muted-foreground">
      Не удалось посчитать надёжность
    </div>
  }

  const d = q.data
  const t = d.totals

  return (
    <div ref={экран} className="space-y-3 p-3">
      <OpsSnapshotNotice data={d} />
      <p className="text-xs text-muted-foreground">Парк: {d.totals.populationStations} · с сессиями за окно: {d.totals.stations} · в списке с {d.minSessions}+ визитами: {d.totals.stationsCounted}.</p>
      {d.trend && <p className="rounded-md border p-2 text-sm">Последние 7 дней данных: {d.trend.current.failed} из {d.trend.current.visits} приездов без зарядки ({d.trend.current.failedPct} %). Предыдущие 7: {d.trend.previous.failed} из {d.trend.previous.visits} ({d.trend.previous.failedPct} %). Изменение: {d.trend.deltaPp > 0 ? '+' : ''}{d.trend.deltaPp} п.п.</p>}
      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">Надёжность станций</div>
              <div className="text-xs text-muted-foreground">
                окно {d.days} дней по {d.asOf.slice(0, 10).split('-').reverse().join('.')}
                {' · '}станции с {d.minSessions}+ приездами
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {ОКНА.map((w) => (
                <Button key={w} size="sm" variant={окно === w ? 'default' : 'outline'}
                  className="h-7 px-2 text-xs" onClick={() => setОкно(w)}>
                  {w} дн
                </Button>
              ))}
              <label className="text-xs text-muted-foreground" htmlFor="rel-asof">
                на день
              </label>
              <Input id="rel-asof" type="date" value={наДень}
                max={d.dataThrough?.slice(0, 10)}
                onChange={(e) => setНаДень(e.target.value)}
                className="h-7 w-36 text-xs" />
              {наДень && (
                <Button size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => setНаДень('')}>
                  К последним данным
                </Button>
              )}
              <ExportButton title="Надёжность станций"
                subtitle={`окно ${d.days} дней по ${d.asOf.slice(0, 10)}`}
                getEl={() => экран.current} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {/* Плитки — фильтры списка: нажатие показывает те станции, про
                которые это число (20.09.2026). */}
            <Плитка icon={Zap} label="Приездов клиентов" value={nf.format(t.visits)}
              hint={`станций в счёте ${nf.format(t.stationsCounted)}`}
              active={разрез === 'all'} onClick={() => setРазрез('all')} />
            <Плитка icon={AlertTriangle} label="Уехали ни с чем"
              value={`${t.failedVisitsPct} %`}
              hint={`${nf.format(t.visitsFailed)} приездов`}
              tone="text-red-600 dark:text-red-400"
              active={разрез === 'bad'}
              onClick={() => setРазрез(разрез === 'bad' ? 'all' : 'bad')} />
            <Плитка icon={BatteryWarning} label="Попыток на приезд"
              value={String(t.attemptsPerVisit)}
              hint={`${nf.format(t.sessions)} попыток всего`}
              tone={t.attemptsPerVisit >= 2 ? 'text-amber-600 dark:text-amber-400' : undefined}
              active={разрез === 'attempts'}
              onClick={() => setРазрез(разрез === 'attempts' ? 'all' : 'attempts')} />
            <Плитка icon={AlertTriangle} label={`Станций хуже ${d.threshold} %`}
              value={nf.format(t.badStations)}
              tone="text-red-600 dark:text-red-400"
              active={разрез === 'bad'}
              onClick={() => setРазрез(разрез === 'bad' ? 'all' : 'bad')} />
            <Плитка icon={Users} label="Задето клиентов" value={nf.format(t.clientsAffected)}
              hint="столкнулись с отказом"
              active={разрез === 'clients'}
              onClick={() => setРазрез(разрез === 'clients' ? 'all' : 'clients')} />
          </div>

          <p className="text-xs text-muted-foreground">{d.note}</p>
        </CardContent>
      </Card>

      {d.regions.length > 1 && (
        <Card>
          <CardContent className="p-3">
            <div className="mb-2 text-sm font-semibold">Где отказывает чаще</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-export-name="Регионы">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <SortTh sortKey="region" sort={регионы.sort} onSort={регионы.toggle}>Регион</SortTh>
                    <SortTh sortKey="stations" sort={регионы.sort} onSort={регионы.toggle} align="right">Станций</SortTh>
                    <SortTh sortKey="visits" sort={регионы.sort} onSort={регионы.toggle} align="right">Приездов</SortTh>
                    <SortTh sortKey="failed" sort={регионы.sort} onSort={регионы.toggle} align="right">Ни с чем</SortTh>
                    <SortTh sortKey="bad" sort={регионы.sort} onSort={регионы.toggle} align="right">Станций за порогом</SortTh>
                  </tr>
                </thead>
                <tbody>
                  {регионы.rows.map((g) => (
                    <tr key={g.region} className="border-b border-border/40">
                      <td className="p-1.5">{g.region}</td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.stations)}</td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.visits)}</td>
                      <td className="p-1.5 text-right font-medium tabular-nums">
                        {g.failedVisitsPct} %
                      </td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.bad)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={регионОтбора} onValueChange={setРегионОтбора}>
              <SelectTrigger className="h-7 w-52 text-xs">
                <SelectValue placeholder="Регион" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все регионы</SelectItem>
                {регионыСписком.map((р) => (
                  <SelectItem key={р} value={р}>{р}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={маркаОтбора} onValueChange={setМаркаОтбора}>
              <SelectTrigger className="h-7 w-44 text-xs">
                <SelectValue placeholder="Марка" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все марки</SelectItem>
                {маркиСписком.map((м) => (
                  <SelectItem key={м} value={м}>{м}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
              placeholder="Номер, название, марка…" className="h-7 w-56 text-xs" />
            {(регионОтбора !== 'all' || маркаОтбора !== 'all' || поиск || разрез !== 'all') && (
              <Button size="sm" variant="ghost" className="h-7 text-xs"
                onClick={() => {
                  setРегионОтбора('all'); setМаркаОтбора('all')
                  setПоиск(''); setРазрез('all')
                }}>
                Сбросить
              </Button>
            )}
            <span className="text-xs text-muted-foreground">
              строк: {nf.format(таблица.rows.length)}
            </span>
          </div>

          <PanelViewTabs value={вид} onChange={setВид} label={null} tabs={[
            { k: 'list', label: 'Список' },
            { k: 'pivot', label: 'Сводная' },
          ]} />

          {вид === 'pivot' ? (
            /* Сводная отвечает на вопрос уровнем выше строки: отказы кучкуются
               по региону, по марке или всё-таки по отдельным станциям. */
            <ReportPivot
              fields={['region', 'brand', 'model', 'severity', 'stations',
                       'visits', 'visitsFailed', 'clientsLost']}
              columns={['Регион', 'Марка', 'Модель', 'Оценка', 'Станций',
                        'Приездов', 'Ни с чем', 'Ушло клиентов']}
              rows={таблица.rows.map((r) => ({
                region: r.region ?? '— регион не указан',
                brand: r.brand ?? '— марка не указана',
                model: r.model ?? '— модель не указана',
                severity: r.failedVisitsPct >= d.threshold ? `хуже ${d.threshold} %`
                  : r.failedVisitsPct >= d.threshold / 2 ? 'настораживает' : 'в норме',
                stations: 1,
                visits: r.visits,
                visitsFailed: r.visitsFailed,
                clientsLost: r.clientsLost,
              }))} />
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm"
              {...exportRows('Надёжность',
                ['Номер', 'Станция', 'Регион', 'Приездов', 'Уехали ни с чем',
                 'Ни с чем %', 'Попыток на приезд', 'Пустых %', 'кВтч на попытку',
                 'Клиентов ушло'],
                таблица.rows.map((r) => [
                  r.number ?? r.code, r.name, r.region, r.visits, r.visitsFailed,
                  r.failedVisitsPct, r.attemptsPerVisit, r.emptyPct,
                  r.kwhPerSession, r.clientsLost,
                ]))}>
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <SortTh sortKey="number" sort={таблица.sort} onSort={таблица.toggle}>№</SortTh>
                  <SortTh sortKey="name" sort={таблица.sort} onSort={таблица.toggle}>Станция</SortTh>
                  <SortTh sortKey="region" sort={таблица.sort} onSort={таблица.toggle}>Регион</SortTh>
                  <SortTh sortKey="visits" sort={таблица.sort} onSort={таблица.toggle} align="right">Приездов</SortTh>
                  <SortTh sortKey="failedVisits" sort={таблица.sort} onSort={таблица.toggle} align="right">Ни с чем</SortTh>
                  <SortTh sortKey="attempts" sort={таблица.sort} onSort={таблица.toggle} align="right">Попыток / приезд</SortTh>
                  <SortTh sortKey="empty" sort={таблица.sort} onSort={таблица.toggle} align="right">Пустых</SortTh>
                  <SortTh sortKey="kwh" sort={таблица.sort} onSort={таблица.toggle} align="right">кВтч / попытку</SortTh>
                  <SortTh sortKey="clients" sort={таблица.sort} onSort={таблица.toggle} align="right">Ушло клиентов</SortTh>
                </tr>
              </thead>
              <tbody>
                {таблица.rows.map((r) => (
                  <tr key={r.locationId}
                    className={cn('border-b border-border/40',
                      r.failedVisitsPct >= d.threshold && 'bg-red-500/5')}>
                    <td className="p-1.5 font-mono text-xs text-muted-foreground">
                      {r.number ?? r.code ?? '—'}
                    </td>
                    <td className="max-w-[240px] truncate p-1.5 font-medium" title={r.name}>
                      <StationLink station={r.locationId}>{r.name}</StationLink>
                      {r.city && <span className="ml-1.5 text-xs text-muted-foreground">{r.city}</span>}
                    </td>
                    <td className="p-1.5 text-muted-foreground">{r.region ?? '—'}</td>
                    <td className="p-1.5 text-right tabular-nums">{nf.format(r.visits)}</td>
                    <td className={cn('p-1.5 text-right font-medium tabular-nums',
                      r.failedVisitsPct >= d.threshold && 'text-red-600 dark:text-red-400')}>
                      {r.failedVisitsPct} %
                      <span className="ml-1 text-xs font-normal text-muted-foreground">
                        {nf.format(r.visitsFailed)}
                      </span>
                    </td>
                    {/* Четыре втыкания разъёма на приезд — станция «работает», но
                        человек запомнит именно это. */}
                    <td className={cn('p-1.5 text-right tabular-nums',
                      r.attemptsPerVisit >= 2 && 'text-amber-600 dark:text-amber-400')}>
                      {r.attemptsPerVisit}
                    </td>
                    <td className="p-1.5 text-right tabular-nums text-muted-foreground">
                      {r.emptyPct} %
                    </td>
                    {/* Ноль энергии на попытку — самый показательный признак: клиент
                        подъезжает, а станция не отдаёт ничего. */}
                    <td className={cn('p-1.5 text-right tabular-nums',
                      r.kwhPerSession < 1 && 'text-red-600 dark:text-red-400')}>
                      {r.kwhPerSession}
                    </td>
                    <td className="p-1.5 text-right tabular-nums">{nf.format(r.clientsLost)}</td>
                  </tr>
                ))}
                {!таблица.rows.length && (
                  <tr>
                    <td colSpan={9} className="p-6 text-center text-sm text-muted-foreground">
                      Станций с достаточным числом приездов не нашлось
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
