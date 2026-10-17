import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, BatteryWarning, ChevronDown, ChevronRight, Loader2, Users, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StationLink } from '@/components/common/StationLink'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { cn } from '@/lib/utils'
import { matchesSearch } from '@/lib/textUtils'
import { getNetworkReliability, type NetworkReliability, type ReliabilityRow } from '@/services/opsService'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable,
  TILE_ROW, Tile, ToolPanel, ToolStrip, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { PanelViewTabs } from './PanelViewTabs'
import { ReportPivot } from './ReportPivot'
import { OpsSnapshotStatus } from './OpsSnapshotNotice'
import { ExportButton } from './analytics/ExportButton'
import { exportRows } from './analytics/exportRows'
import { daysAgoISO } from './analytics/periodPresets'

const С = { номер: 0, станция: 1, регион: 2, марка: 3, модель: 4, приездов: 5,
  безЗарядки: 6, отказПроц: 7, попыток: 8, пустыхПроц: 9, кВтч: 10, ушло: 11,
  сессий: 12, ошибок: 13, ошибокПроц: 14, пустых: 15, энергия: 16, выручка: 17,
  клиентов: 18, задетых: 19, последняя: 20 }
const ШАПКА = ['№', 'Станция', 'Регион', 'Марка', 'Модель', 'Приездов', 'Приездов без зарядки',
  'Без зарядки, %', 'Попыток / приезд', 'Без энергии, %', 'кВт·ч / попытку', 'Ушло клиентов',
  'Попыток всего', 'Ошибок', 'Ошибок, %', 'Попыток без энергии', 'Энергия, кВт·ч',
  'Выручка, ₽', 'Клиентов', 'Столкнулись с отказом', 'Последняя сессия']
const СКРЫТЫ = [С.модель, С.пустыхПроц, С.сессий, С.ошибок, С.ошибокПроц, С.пустых,
  С.энергия, С.выручка, С.клиентов, С.задетых, С.последняя]
const СОСТАВ_СТОЛБЦОВ = { order: [], hidden: СКРЫТЫ }
const ШИРИНЫ = { [С.номер]: 70, [С.станция]: 230, [С.регион]: 190, [С.марка]: 110,
  [С.приездов]: 110, [С.безЗарядки]: 130, [С.отказПроц]: 115, [С.попыток]: 120, [С.кВтч]: 120, [С.ушло]: 115 }
const РЕГ_ШАПКА = ['Регион', 'Станций', 'Приездов', 'Приездов без зарядки', 'Без зарядки, %', 'Станций с частыми отказами']
const РЕГ_СКРЫТЫ: number[] = []
const РЕГ_ШИРИНЫ = { 0: 280, 1: 100, 2: 120, 3: 150, 4: 130, 5: 160 }
const ПОКАЗАТЬ = { all: 'Все станции списка', failed: 'Есть приезды без зарядки', bad: 'Частые отказы', attempts: 'От двух попыток на приезд', clients: 'Столкнулись с отказом', lost: 'Ушли клиенты' }
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:ops-reliability'
type Отбор = keyof typeof ПОКАЗАТЬ
type Настройки = { days: number; search: string; region: string; brand: string; filter: Отбор; view: string }
const дата = (s: string) => new Date(s).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })
const сумма = (rows: ReliabilityRow[], key: keyof ReliabilityRow) => rows.reduce((n, r) => n + (Number(r[key]) || 0), 0)
const доля = (n: number, all: number, digits = 1): Cell => all ? Math.round(n / all * 10 ** digits) / 10 ** digits : ''
const процент = (n: number, all: number): Cell => доля(n * 100, all)

function строка(r: ReliabilityRow): Cell[] {
  return [r.number ?? r.code ?? '', r.name, r.region ?? '', r.brand ?? '', r.model ?? '',
    r.visits, r.visitsFailed, r.failedVisitsPct, r.attemptsPerVisit, r.emptyPct, r.kwhPerSession,
    r.clientsLost, r.sessions, r.failed, r.failedPct, r.empty, r.energyKwh, r.revenue,
    r.clients, r.clientsAffected, r.lastSessionAt ? дата(r.lastSessionAt) : '']
}
function итоги(rows: ReliabilityRow[]): Cell[] {
  const visits = сумма(rows, 'visits'), sessions = сумма(rows, 'sessions')
  return ['Итого', rows.length + ' станций', '', '', '', visits, сумма(rows, 'visitsFailed'),
    процент(сумма(rows, 'visitsFailed'), visits), доля(sessions, visits, 2), процент(сумма(rows, 'empty'), sessions),
    доля(сумма(rows, 'energyKwh'), sessions, 2), сумма(rows, 'clientsLost'), sessions, сумма(rows, 'failed'),
    процент(сумма(rows, 'failed'), sessions), сумма(rows, 'empty'), сумма(rows, 'energyKwh'), сумма(rows, 'revenue'),
    сумма(rows, 'clients'), сумма(rows, 'clientsAffected'), '']
}
function поРегионам(rows: ReliabilityRow[], threshold: number) {
  const groups = new Map<string, ReliabilityRow[]>()
  rows.forEach((r) => {
    const name = r.region || 'Регион не указан', group = groups.get(name)
    if (group) group.push(r); else groups.set(name, [r])
  })
  return [...groups].map(([name, stations]) => {
    const visits = сумма(stations, 'visits'), failed = сумма(stations, 'visitsFailed')
    return { name, stations, cells: [name, stations.length, visits, failed, процент(failed, visits),
      stations.filter((r) => r.failedVisitsPct >= threshold).length] as Cell[] }
  }).sort((a, b) => Number(b.cells[4]) - Number(a.cells[4]))
}
function Поле({ id, label, children, className }: { id: string; label: string; children: ReactNode; className: string }) {
  return <div className={cn('flex min-w-0 flex-col gap-1', className)}>
    <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>{children}
  </div>
}

export function NetworkReliabilityPanel() {
  const { companyId } = useCompany()
  const { regionIds, period } = useFilters()
  const [settings, setSettings] = useState<Настройки>({ days: 90, search: '', region: 'all', brand: 'all', filter: 'all', view: 'list' })
  const region = regionIds.length ? regionIds.join('|') : undefined
  const asOf = period.to >= daysAgoISO(1) ? '' : period.to
  const q = useQuery({
    queryKey: ['ops-reliability', companyId, settings.days, region ?? '', asOf],
    queryFn: () => getNetworkReliability(companyId, { days: settings.days, region, asOf: asOf || undefined }),
    enabled: !!companyId, staleTime: 60_000,
  })
  if (q.isLoading) return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  if (q.isError || !q.data) return <div role="alert" className="flex flex-col items-center gap-3 p-8 text-sm text-muted-foreground">
    <p>Не удалось посчитать надёжность станций.</p>
    <Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching}>Повторить загрузку</Button>
  </div>
  return <ReliabilityReport key={settings.view === 'regions' ? 'regions' : 'stations'} data={q.data}
    settings={settings} change={(patch) => setSettings((s) => ({ ...s, ...patch }))} companyId={companyId} region={region} />
}

function ReliabilityReport({ data: d, settings: s, change, companyId, region }: {
  data: NetworkReliability; settings: Настройки; change: (patch: Partial<Настройки>) => void; companyId: string; region?: string
}) {
  const экран = useRef<HTMLDivElement>(null)
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [разбор, setРазбор] = useState<'region' | 'brand' | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [открыты, setОткрыты] = useState<Set<string>>(new Set())
  const раскрыть = useCallback((name: string) => setОткрыты((was) => {
    const next = new Set(was)
    if (next.has(name)) next.delete(name); else next.add(name)
    return next
  }), [])
  const [регионы, марки] = useMemo(() => [
    [...new Set(d.stations.flatMap((r) => r.region ? [r.region] : []))].sort((a, b) => a.localeCompare(b, 'ru')),
    [...new Set(d.stations.flatMap((r) => r.brand ? [r.brand] : []))].sort((a, b) => a.localeCompare(b, 'ru')),
  ], [d.stations])
  const выбранРегион = регионы.includes(s.region) ? s.region : 'all'
  const строки = useMemo(() => d.stations.filter((r) => {
    if (s.filter === 'failed' && !r.visitsFailed) return false
    if (s.filter === 'bad' && r.failedVisitsPct < d.threshold) return false
    if (s.filter === 'attempts' && r.attemptsPerVisit < 2) return false
    if (s.filter === 'clients' && !r.clientsAffected) return false
    if (s.filter === 'lost' && !r.clientsLost) return false
    if (выбранРегион !== 'all' && r.region !== выбранРегион) return false
    if (s.brand !== 'all' && r.brand !== s.brand) return false
    return !s.search.trim() || matchesSearch(s.search, [r.number, r.code, r.name, r.city, r.region, r.brand, r.model])
  }), [d.stations, d.threshold, s.filter, s.brand, s.search, выбранРегион])
  const группы = useMemo(() => поРегионам(строки, d.threshold), [строки, d.threshold])
  const регионыВид = s.view === 'regions'
  const ячейки = useMemo(() => регионыВид ? группы.map((g) => g.cells) : строки.map(строка), [регионыВид, группы, строки])
  const total = useMemo(() => регионыВид ? ['Итого', строки.length, сумма(строки, 'visits'), сумма(строки, 'visitsFailed'),
    процент(сумма(строки, 'visitsFailed'), сумма(строки, 'visits')), строки.filter((r) => r.failedVisitsPct >= d.threshold).length] as Cell[] : итоги(строки), [регионыВид, строки, d.threshold])
  const status = useMemo(() => <OpsSnapshotStatus dataThrough={d.dataThrough} dataLagHours={d.dataLagHours} snapshotNote={d.snapshotNote} />,
    [d.dataThrough, d.dataLagHours, d.snapshotNote])
  const help = useMemo(() => <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
    {ПОМОЩЬ}<p>{d.note}</p><p>Парк: {qty(d.totals.populationStations)} станций; с сессиями за окно: {qty(d.totals.stations)};
      в списке с {d.minSessions}+ приездами: {qty(d.totals.stationsCounted)}.</p>
  </div>, [d.note, d.totals.populationStations, d.totals.stations, d.totals.stationsCounted, d.minSessions])
  const набор = useReportKit({ id: регионыВид ? 'ops-reliability-regions.v1' : 'ops-reliability.v1', title: 'Надёжность',
    head: регионыВид ? РЕГ_ШАПКА : ШАПКА, rows: ячейки, total, hide: регионыВид ? РЕГ_СКРЫТЫ : СКРЫТЫ,
    ready: true, pivot: s.view === 'pivot', help, status })
  const оставлены = useMemo(() => набор.kept.map((i) => строки[i]), [набор.kept, строки])
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i)).filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.table.head])
  const ячейка = useCallback((i: number, c: number) => {
    if (регионыВид) {
      const g = группы[i]
      if (c === 0 && g) return <span className="flex items-center gap-1.5">
        <button type="button" aria-label={(открыты.has(g.name) ? 'Свернуть станции ' : 'Раскрыть станции ') + g.name}
          aria-expanded={открыты.has(g.name)} onClick={(e) => { e.stopPropagation(); раскрыть(g.name) }}
          className="grid size-8 shrink-0 place-items-center rounded-md text-primary hover:bg-accent">
          {открыты.has(g.name) ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button><span className="whitespace-normal font-medium">{g.name}</span></span>
      return undefined
    }
    const r = строки[i]
    if (c === С.станция) return <span className="whitespace-normal break-words font-medium">{r.name}</span>
    if (c === С.отказПроц) return <span className={cn(r.failedVisitsPct >= d.threshold && 'font-semibold text-destructive')}>{qty(r.failedVisitsPct)} %</span>
    return undefined
  }, [регионыВид, группы, открыты, раскрыть, строки, d.threshold])
  const фильтры = [s.filter !== 'all' && ПОКАЗАТЬ[s.filter], выбранРегион !== 'all' && выбранРегион,
    s.brand !== 'all' && s.brand, s.search.trim() && 'поиск «' + s.search.trim() + '»'].filter(Boolean) as string[]
  const отборов = фильтры.length + Object.keys(набор.filters).length
  const сброс = () => { change({ search: '', region: 'all', brand: 'all', filter: 'all' }); набор.setFilters({}) }
  const выбрать = (filter: Отбор) => { change({ filter: s.filter === filter ? 'all' : filter }); набор.setFilters({}) }
  const выбранная = карточка ? строки[карточка.order[карточка.pos]] : null
  const расшифровка = выбранная && разбор ? d.stations.filter((r) => разбор === 'brand' ? r.brand === выбранная.brand : r.region === выбранная.region) : []
  const подпись = d.days + ' дней по ' + дата(d.asOf) + ' · МСК · от ' + d.minSessions + ' приездов'
  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className={TILE_ROW}>
      <Tile icon={Zap} label="Приездов клиентов" value={qty(d.totals.visits)} hint={qty(d.totals.stations) + ' станций с сессиями'}
        active={s.filter === 'all'} onClick={() => выбрать('all')} />
      <Tile icon={AlertTriangle} label="Приездов без зарядки" value={qty(d.totals.failedVisitsPct) + ' %'} hint={qty(d.totals.visitsFailed) + ' приездов'}
        active={s.filter === 'failed'} onClick={() => выбрать('failed')} />
      <Tile icon={BatteryWarning} label="Попыток на приезд" value={qty(d.totals.attemptsPerVisit)} hint={qty(d.totals.sessions) + ' попыток всего'}
        active={s.filter === 'attempts'} onClick={() => выбрать('attempts')} />
      <Tile icon={AlertTriangle} label="Станций с частыми отказами" value={qty(d.totals.badStations)} hint={'без зарядки от ' + qty(d.threshold) + ' % приездов'}
        active={s.filter === 'bad'} onClick={() => выбрать('bad')} />
      <Tile icon={Users} label="Столкнулись с отказом" value={qty(d.totals.clientsAffected)} hint="сумма клиентов по станциям"
        active={s.filter === 'clients'} onClick={() => выбрать('clients')} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      {фильтрыОткрыты && <div className="flex flex-wrap items-end gap-3">
        <Поле id="reliability-window" label="Окно анализа" className="w-36"><Select value={String(s.days)} onValueChange={(v) => change({ days: Number(v) })}>
          <SelectTrigger id="reliability-window" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{[30, 90, 180].map((n) => <SelectItem key={n} value={String(n)}>{n} дней</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="reliability-show" label="Показать" className="w-60"><Select value={s.filter} onValueChange={(v) => change({ filter: v as Отбор })}>
          <SelectTrigger id="reliability-show" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(ПОКАЗАТЬ).map(([key, text]) => <SelectItem key={key} value={key}>{text}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="reliability-region" label="Регион" className="w-52"><Select value={выбранРегион} onValueChange={(v) => change({ region: v })}>
          <SelectTrigger id="reliability-region" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Все регионы контура</SelectItem>{регионы.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="reliability-brand" label="Марка" className="w-40"><Select value={s.brand} onValueChange={(v) => change({ brand: v })}>
          <SelectTrigger id="reliability-brand" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Все марки</SelectItem>{марки.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="reliability-search" label="Найти станцию" className="w-56"><Input id="reliability-search" value={s.search}
          onChange={(e) => change({ search: e.target.value })} placeholder="Номер, название, марка…" className="h-9" /></Поле>
        <Поле id="reliability-page" label="Строк на странице" className="w-32"><PageSizeField bare id="reliability-page" /></Поле>
      </div>}
      <div className={cn('flex flex-wrap items-center justify-between gap-2', фильтрыОткрыты && 'border-t border-border/60 pt-3')}>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" aria-expanded={фильтрыОткрыты} onClick={() => {
            const next = !фильтрыОткрыты; setФильтрыОткрыты(next)
            try { localStorage.setItem(КЛЮЧ_ФИЛЬТРОВ, next ? '1' : '0') } catch { /* хранилище недоступно */ }
          }} className="inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm font-semibold text-primary hover:bg-accent">
            <ChevronDown className={cn('size-4 transition-transform', фильтрыОткрыты && 'rotate-180')} />
            {фильтрыОткрыты ? 'Свернуть фильтры' : 'Фильтры'}
            {!фильтрыОткрыты && отборов > 0 && <span className="rounded-full bg-primary px-1.5 text-xs leading-5 text-primary-foreground">{отборов}</span>}
          </button>
          <PanelViewTabs label={null} value={s.view} onChange={(view) => change({ view })} tabs={[
            { k: 'list', label: 'Список' }, { k: 'regions', label: 'По регионам' }, { k: 'pivot', label: 'Сводная' },
          ]} />
          <span className="text-xs text-muted-foreground">{регионыВид ? 'регионов' : 'станций'}: {qty(набор.kept.length)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ExportButton title="Надёжность" subtitle={подпись} getEl={() => экран.current} />
          <Button size="sm" variant="outline" onClick={сброс} disabled={!отборов}>Сбросить фильтры</Button>
        </div>
      </div>
      <ToolStrip />
      {s.view === 'pivot' ? <ReportPivot fields={['region', 'brand', 'model', 'severity', 'stations', 'visits', 'visitsFailed', 'clientsLost']}
        columns={['Регион', 'Марка', 'Модель', 'Оценка', 'Станций', 'Приездов', 'Без зарядки', 'Ушло клиентов']}
        rows={оставлены.map((r) => ({ region: r.region || 'Регион не указан', brand: r.brand || 'Марка не указана',
          model: r.model || 'Модель не указана', severity: r.failedVisitsPct >= d.threshold ? 'Частые отказы' : r.failedVisitsPct >= d.threshold / 2 ? 'Требует внимания' : 'Ниже порога',
          stations: 1, visits: r.visits, visitsFailed: r.visitsFailed, clientsLost: r.clientsLost }))} />
        : <SheetTable {...набор.table} caption={регионыВид ? 'Надёжность по регионам' : 'Надёжность станций'} lines={[подпись, ...фильтры]}
          defaultWidths={регионыВид ? РЕГ_ШИРИНЫ : ШИРИНЫ} render={ячейка} onView={setПорядок}
          rowTitle={(i) => регионыВид ? группы[i]?.name ?? '' : строки[i]?.name ?? ''}
          onRow={(order, pos) => регионыВид ? раскрыть(группы[order[pos]].name) : setКарточка({ order, pos })}
          expand={регионыВид ? (i) => открыты.has(группы[i]?.name) ? <StationSubset key={группы[i].name} rows={группы[i].stations} caption={'Станции · ' + группы[i].name} lines={[подпись]} /> : null : undefined}
          derive={(t) => {
            const kept = регионыВид ? набор.kept.flatMap((i) => группы[i].stations) : оставлены
            const values = регионыВид ? ['Итого', kept.length, сумма(kept, 'visits'), сумма(kept, 'visitsFailed'),
              процент(сумма(kept, 'visitsFailed'), сумма(kept, 'visits')), kept.filter((r) => r.failedVisitsPct >= d.threshold).length] : итоги(kept)
            const fixed = t.map((v, i) => i < values.length ? values[i] : v)
            return набор.table.derive ? набор.table.derive(fixed) : fixed
          }}
          empty="По этому отбору станции не найдены. Измените поиск или сбросьте фильтры."
          tableAttrs={exportRows(регионыВид ? 'Регионы' : 'Станции', видимые.map((c) => набор.sheet.head[c]),
            порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />}
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Номер, станция, регион или число" formulaExample="Например, Доля успешных приездов"
      compare={<ReliabilityCompare companyId={companyId} region={region} now={d} />} /></ToolPanel>
    <RowCard report="Надёжность" head={набор.sheet.head} title={выбранная?.name}
      row={карточка ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
      at={карточка?.pos ?? 0} of={карточка?.order.length ?? 0}
      onStep={(dir) => { setРазбор(null); setКарточка((v) => v ? { ...v, pos: Math.max(0, Math.min(v.pos + dir, v.order.length - 1)) } : v) }}
      onClose={() => { setКарточка(null); setРазбор(null) }} extra={выбранная && <div className="flex flex-col gap-3">
        <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
          <RelatedLink label="Станции региона" hint={выбранная.region || 'Регион не указан'} onClick={() => setРазбор('region')} />
          {выбранная.brand && <RelatedLink label="Станции производителя" hint={выбранная.brand} onClick={() => setРазбор('brand')} />}
        </div>
        <div className="text-sm"><StationLink station={выбранная.locationId}>Открыть карточку станции</StationLink></div>
      </div>} />
    <RelatedReport open={!!разбор && !!выбранная} title={разбор === 'brand' ? 'Станции производителя' : 'Станции региона'}
      subtitle={подпись} head={ШАПКА} rows={расшифровка.map(строка)} onClose={() => setРазбор(null)}
      note="Полный состав списка с достаточным числом приездов за тот же срез; локальные отборы основной таблицы не применяются.">
      <StationSubset rows={расшифровка} caption={разбор === 'brand' ? выбранная?.brand || 'Марка не указана' : выбранная?.region || 'Регион не указан'} lines={[подпись]} />
    </RelatedReport>
  </div>
}

function StationSubset({ rows, caption, lines }: { rows: ReliabilityRow[]; caption: string; lines: string[] }) {
  const [order, setOrder] = useState<number[]>([])
  const cells = useMemo(() => rows.map(строка), [rows])
  return <SheetTable head={ШАПКА} rows={cells} caption={caption} lines={lines} cols={СОСТАВ_СТОЛБЦОВ}
    defaultWidths={ШИРИНЫ} onView={setOrder} render={(i, c) => c === С.станция ? <StationLink station={rows[i].locationId}>{rows[i].name}</StationLink> : undefined}
    tableAttrs={exportRows(caption, ШАПКА.filter((_, i) => !СКРЫТЫ.includes(i)),
      order.map((i) => cells[i].filter((_, c) => !СКРЫТЫ.includes(c))))} />
}

function ReliabilityCompare({ companyId, region, now }: { companyId: string; region?: string; now: NetworkReliability }) {
  const [offset, setOffset] = useState<number | null>(null)
  const date = new Date(now.asOf.slice(0, 10) + 'T12:00:00Z')
  date.setUTCDate(date.getUTCDate() - (offset ?? 0))
  const past = offset ? date.toISOString().slice(0, 10) : ''
  const q = useQuery({ queryKey: ['ops-reliability-compare', companyId, now.days, region ?? '', past],
    queryFn: () => getNetworkReliability(companyId, { days: now.days, region, asOf: past }), enabled: !!past && !!companyId, staleTime: 60_000 })
  return <div className="flex flex-col gap-3">
    <p className="text-xs text-muted-foreground">Весь выбранный контур. Плитки, локальный поиск, марка и фильтры столбцов не применяются. Состав парка текущий в обоих срезах.</p>
    {now.trend && <div className="flex flex-col gap-1 rounded-md border p-3 text-sm">
      <p className="font-medium">Последние 7 дней данных</p>
      <p>{qty(now.trend.current.failed)} из {qty(now.trend.current.visits)} приездов без зарядки · {qty(now.trend.current.failedPct)} %</p>
      <p className="text-muted-foreground">Предыдущие 7 дней: {qty(now.trend.previous.failed)} из {qty(now.trend.previous.visits)} · {qty(now.trend.previous.failedPct)} %</p>
      <p>Изменение: {now.trend.deltaPp > 0 ? '+' : ''}{qty(now.trend.deltaPp)} п.п.</p>
    </div>}
    <div className="flex flex-wrap gap-2">{[[1, 'День назад'], [7, 'Неделю назад'], [now.days, 'Предыдущее окно']].map(([n, label]) =>
      <Button key={String(n) + label} size="sm" variant={offset === n ? 'default' : 'outline'} onClick={() => setOffset(Number(n))}>{label}</Button>)}</div>
    {!past ? <p className="text-sm text-muted-foreground">Выберите срез для сравнения.</p> : q.isFetching ? <Loader2 className="size-5 animate-spin" />
      : q.isError ? <div role="alert" className="flex flex-col gap-2 text-sm"><p>Не удалось загрузить прошлый срез.</p><Button variant="outline" onClick={() => void q.refetch()}>Повторить</Button></div>
        : q.data && <>
          <p className="text-xs text-muted-foreground">{дата(now.asOf)} / {дата(q.data.asOf)} · окно {now.days} дней.</p>
          <dl className="divide-y divide-border/60">{[
            ['Приездов', now.totals.visits, q.data.totals.visits], ['Без зарядки, %', now.totals.failedVisitsPct, q.data.totals.failedVisitsPct],
            ['Попыток на приезд', now.totals.attemptsPerVisit, q.data.totals.attemptsPerVisit], ['Станций с частыми отказами', now.totals.badStations, q.data.totals.badStations],
          ].map(([label, current, previous]) => <div key={label} className="flex flex-col gap-1 py-2 text-sm"><dt>{label}</dt>
            <dd className="text-muted-foreground">в срезе {qty(Number(current))} · было {qty(Number(previous))}
              <span className="ml-2 font-semibold text-foreground">{Number(current) - Number(previous) > 0 ? '+' : ''}{qty(Math.round((Number(current) - Number(previous)) * 100) / 100)}{label === 'Без зарядки, %' ? ' п.п.' : ''}</span>
            </dd></div>)}</dl>
        </>}
  </div>
}

const ПОМОЩЬ = <>
  <p>Надёжность считается по приездам клиентов. Несколько попыток подряд входят в один приезд.
    Процент без зарядки показывает, какая доля приездов закончилась без энергии.</p>
  <p>Плитки относятся ко всему выбранному контуру, включая станции с малым числом приездов.
    В списке и региональных группах только станции с достаточным числом приездов. Поэтому итог списка может отличаться от плиток.
    Плитки отбирают станции: безуспешные приезды, частые отказы от порога отчёта, от двух попыток на приезд или ушедшие клиенты.
    Повторное нажатие снимает отбор. Счёт клиентов по разным станциям допускает повтор одного человека.</p>
  <p>Конец общего «Периода» задаёт дату среза. Сегодня и вчера показывают последние загруженные данные.
    Окно 30, 90 или 180 дней выбирается в фильтрах; начало общего периода его не меняет.
    Состав парка и паспортные статусы текущие, история состава не восстановлена.</p>
  <p>«По регионам» группирует отобранные станции. Строка региона или стрелка раскрывает их прямо в таблице.
    В списке щелчок по строке или Enter открывает её показатели и связанные отчёты. Расшифровка открывается поверх, после закрытия карточка остаётся.</p>
  <p>В «Сводной» доступны регион, марка, модель и оценка. Фильтры столбцов списка действуют на сводную.
    Настройки столбцов и формулы у регионов и станций раздельные. Проценты и средние в итогах считаются из общих числителей и знаменателей.</p>
  <p>Недельная динамика и прошлые срезы доступны в «Сравнить». Калькулятор, формулы, поиск, столбцы и отложенные цифры работают как на остальных отчётах.
    Excel выгружает видимые столбцы и все строки отбора в текущем порядке, включая раскрытые регионы.</p>
</>
