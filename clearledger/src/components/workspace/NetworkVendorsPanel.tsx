import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, ChevronRight, Factory, FileText, Gauge, Loader2, PlugZap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PanelViewTabs } from './PanelViewTabs'
import { ReportPivot } from './ReportPivot'
import { OpsSnapshotStatus } from './OpsSnapshotNotice'
import { ExportButton } from './analytics/ExportButton'
import { exportRows } from './analytics/exportRows'
import { daysAgoISO } from './analytics/periodPresets'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable,
  TILE_ROW, Tile, ToolPanel, ToolStrip, plural, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { cn } from '@/lib/utils'
import { matchesSearch } from '@/lib/textUtils'
import { StationLink } from '@/components/common/StationLink'
import { getNetworkVendors, type NetworkVendors, type VendorRow, type VendorStationRow } from '@/services/opsService'

const С = { марка: 0, станций: 1, заряжали: 2, живыхПроц: 3, безЗарядок: 4,
  приездов: 5, неудачных: 6, отказПроц: 7, попыток: 8, плохих: 9, отдача: 10,
  моделей: 11, модели: 12, энергия: 13, выручка: 14, действующих: 15, ниРазу: 16, мощность: 17 }
const ШАПКА = ['Марка', 'Станций', 'Заряжали за 2 суток', 'Заряжали, %', 'Без зарядок > 7 дн',
  'Приездов', 'Приездов без зарядки', 'Без зарядки, %', 'Попыток / приезд', 'Станций с отказами',
  'кВт·ч / станцию в сутки', 'Моделей', 'Модели', 'Энергия, кВт·ч', 'Выручка, ₽',
  'Действующих станций', 'Ни разу не заряжали', 'Средняя мощность, кВт']
const СКРЫТЫ = [С.живыхПроц, С.неудачных, С.моделей, С.модели, С.энергия, С.выручка, С.действующих, С.ниРазу, С.мощность]
const ШИРИНЫ = { [С.марка]: 220, [С.станций]: 90, [С.заряжали]: 130, [С.безЗарядок]: 130,
  [С.приездов]: 115, [С.отказПроц]: 115, [С.попыток]: 120, [С.плохих]: 125, [С.отдача]: 145 }
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:ops-vendors'
const ПОКАЗАТЬ = { all: 'Все марки', bad: 'Есть станции с отказами', silent: 'Без зарядок больше недели', low: 'Заряжает меньше половины' }
type Отбор = keyof typeof ПОКАЗАТЬ
type Разбор = 'stations' | 'bad' | 'silent' | 'models'
const РАСШИФРОВКИ: { key: Разбор; title: string; hint: string }[] = [
  { key: 'stations', title: 'Все станции марки', hint: 'модель, регион, приезды, энергия и давность зарядок' },
  { key: 'bad', title: 'Станции с отказами', hint: 'не менее 10 приездов, доля без зарядки от порога отчёта' },
  { key: 'silent', title: 'Без зарядок больше недели', hint: 'включая станции без зарядок в загруженной истории' },
  { key: 'models', title: 'Модели марки', hint: 'станции, приезды и энергия по каждой модели' },
]
const дата = (s: string) => new Date(s).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })
const sum = (rows: VendorRow[], key: keyof VendorRow) => rows.reduce((n, r) => n + (Number(r[key]) || 0), 0)
const доля = (n: number, all: number): Cell => all ? Math.round(n / all * 1000) / 10 : ''
const нетЗарядок = (r: VendorStationRow) => r.silentDays === null || r.silentDays > 7
const сОтказами = (r: VendorStationRow, threshold: number) => r.visits >= 10 && r.failedVisitsPct >= threshold
const количество = (n: number) => qty(n) + ' ' + plural(n, 'станция', 'станции', 'станций')

function строка(r: VendorRow): Cell[] {
  return [r.vendor, r.stations, r.charging2d, r.active ? r.livePct : '', r.silentWeek,
    r.visits, r.visitsFailed, r.visits ? r.failedVisitsPct : '', r.visits ? r.attemptsPerVisit : '',
    r.badStations, r.active ? r.kwhPerStationDay : '', r.modelsCount, r.models.join('; '),
    r.energyKwh, r.revenue, r.active, r.neverCharged, r.avgPowerKwt ?? '']
}
function итоги(rows: VendorRow[], days: number): Cell[] {
  const active = sum(rows, 'active'), visits = sum(rows, 'visits'), energy = sum(rows, 'energyKwh')
  return ['Итого', sum(rows, 'stations'), sum(rows, 'charging2d'), доля(sum(rows, 'charging2d'), active),
    sum(rows, 'silentWeek'), visits, sum(rows, 'visitsFailed'), доля(sum(rows, 'visitsFailed'), visits), '',
    sum(rows, 'badStations'), active && days ? Math.round(energy / active / days * 10) / 10 : '',
    '', '', energy, sum(rows, 'revenue'), active, sum(rows, 'neverCharged'), '']
}
function Поле({ id, label, children, className }: { id: string; label: string; children: ReactNode; className: string }) {
  return <div className={cn('flex min-w-0 flex-col gap-1', className)}>
    <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>{children}
  </div>
}

export function NetworkVendorsPanel() {
  const { companyId } = useCompany()
  const { regionIds, period } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  const [окно, setОкно] = useState(90)
  const [поиск, setПоиск] = useState('')
  const [регионОтбора, setРегионОтбора] = useState('all')
  const [отбор, setОтбор] = useState<Отбор>('all')
  const [вид, setВид] = useState('list')
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [разбор, setРазбор] = useState<Разбор | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [открыты, setОткрыты] = useState<Set<string>>(new Set())
  const раскрыть = useCallback((vendor: string) => setОткрыты((was) => {
    const next = new Set(was)
    if (next.has(vendor)) next.delete(vendor); else next.add(vendor)
    return next
  }), [])
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })
  const наДень = period.to >= daysAgoISO(1) ? '' : period.to
  const локальныйРегион = regionIds.length && !regionIds.includes(регионОтбора) ? 'all' : регионОтбора
  const регион = локальныйРегион !== 'all' ? локальныйРегион : regionIds.length ? regionIds.join('|') : undefined
  const q = useQuery({
    queryKey: ['ops-vendors', companyId, окно, регион ?? '', наДень],
    queryFn: () => getNetworkVendors(companyId, { days: окно, region: регион, asOf: наДень || undefined }),
    enabled: !!companyId, staleTime: 60_000,
  })
  const qВсе = useQuery({
    queryKey: ['ops-vendor-stations-all', companyId, окно, регион ?? '', наДень],
    queryFn: () => getNetworkVendors(companyId, { vendor: '*', days: окно, region: регион, asOf: наДень || undefined }),
    enabled: !!companyId && вид === 'pivot', staleTime: 60_000,
  })
  const loaded = !!q.data && !q.isError
  const dataThrough = q.data?.dataThrough ?? null
  const dataLagHours = q.data?.dataLagHours ?? null
  const snapshotNote = q.data?.snapshotNote
  const status = useMemo(() => loaded ? <OpsSnapshotStatus dataThrough={dataThrough}
    dataLagHours={dataLagHours} snapshotNote={snapshotNote} /> : null,
  [loaded, dataThrough, dataLagHours, snapshotNote])
  const исходные = q.data?.vendors ?? []
  const строки = useMemo(() => (q.data?.vendors ?? []).filter((r) => {
    if (отбор === 'bad' && !r.badStations) return false
    if (отбор === 'silent' && !r.silentWeek) return false
    if (отбор === 'low' && (!r.active || r.livePct >= 50)) return false
    return !поиск.trim() || matchesSearch(поиск, [r.vendor, ...r.models])
  }), [q.data, отбор, поиск])
  const ячейки = useMemo(() => строки.map(строка), [строки])
  const итог = useMemo(() => итоги(строки, окно), [строки, окно])
  const набор = useReportKit({ id: 'ops-vendors.v1', title: 'Производители', head: ШАПКА,
    rows: ячейки, total: итог, hide: СКРЫТЫ, ready: !!q.data, pivot: вид === 'pivot', help: ПОМОЩЬ, status })
  const оставлены = useMemo(() => набор.kept.map((i) => строки[i]), [набор.kept, строки])
  const маркиСводной = useMemo(() => new Set(оставлены.map((r) => r.vendor)), [оставлены])
  const сводная = useMemo(() => (qВсе.data?.stations ?? []).filter((r) => маркиСводной.has(r.vendor)).map((r) => ({
    vendor: r.vendor, model: r.model || 'Модель не указана', region: r.region || 'Регион не указан',
    state: r.silentDays === null ? 'Нет зарядок в истории' : r.silentDays <= 2 ? 'Заряжала за 2 суток'
      : r.silentDays <= 7 ? 'Без зарядок до недели' : 'Без зарядок больше недели',
    stations: 1, visits: r.visits, visitsFailed: r.visitsFailed, energyKwh: r.energyKwh, revenue: r.revenue,
  })), [qВсе.data, маркиСводной])
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i)).filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.table.head])
  const ячейка = useCallback((i: number, c: number) => {
    const r = строки[i]
    if (!r) return undefined
    if (c === С.марка) return <span className="flex items-center gap-1.5">
      <button type="button" aria-expanded={открыты.has(r.vendor)} aria-label={(открыты.has(r.vendor) ? 'Свернуть станции ' : 'Раскрыть станции ') + r.vendor}
        onClick={(e) => { e.stopPropagation(); раскрыть(r.vendor) }} className="grid size-8 shrink-0 place-items-center rounded-md text-primary hover:bg-accent">
        {открыты.has(r.vendor) ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
      </button>
      <span className="min-w-0 flex-1 whitespace-normal break-words font-medium">{r.vendor}</span>
      <button type="button" aria-label={'Карточка марки ' + r.vendor} title={'Карточка марки ' + r.vendor}
        onClick={(e) => {
          e.stopPropagation()
          const order = порядок.includes(i) ? порядок : набор.kept
          setКарточка({ order, pos: order.indexOf(i) })
        }} className="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
        <FileText className="size-4" />
      </button>
    </span>
    if (c === С.заряжали) return <span>{qty(r.charging2d)}<span className="ml-1.5 text-xs text-muted-foreground">{r.active ? qty(r.livePct) + ' %' : '—'}</span></span>
    if (c === С.отказПроц && r.visits) return <span className={cn(r.failedVisitsPct >= (q.data?.threshold ?? 20) && 'font-semibold text-destructive')}>{qty(r.failedVisitsPct)} %</span>
    return undefined
  }, [строки, q.data?.threshold, открыты, раскрыть, порядок, набор.kept])
  const сброс = () => { setПоиск(''); setРегионОтбора('all'); setОтбор('all'); набор.setFilters({}) }
  const переключить = (v: Отбор) => { setОтбор(v); setПоиск(''); набор.setFilters({}) }
  const фильтры = [отбор !== 'all' && ПОКАЗАТЬ[отбор], локальныйРегион !== 'all' && локальныйРегион,
    поиск.trim() && 'поиск «' + поиск.trim() + '»'].filter(Boolean) as string[]
  const выбранная = карточка ? строки[карточка.order[карточка.pos]] : null
  if (q.isLoading) return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  if (q.isError || !q.data) return <div role="alert" className="flex flex-col items-center gap-3 p-8 text-sm text-muted-foreground">
    <p>Не удалось собрать разрез по производителям.</p>
    <Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching}>Повторить загрузку</Button>
  </div>
  const d = q.data
  const подпись = d.days + ' дней по ' + дата(d.asOf) + ' · МСК'
  const сПроблемами = исходные.filter((r) => r.badStations > 0)
  const безЗарядок = исходные.filter((r) => r.silentWeek > 0)
  const малоЗаряжает = исходные.filter((r) => r.active > 0 && r.livePct < 50)
  const отборов = фильтры.length + Object.keys(набор.filters).length
  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className={TILE_ROW}>
      <Tile icon={Factory} label="Марок в парке" value={qty(d.totals.vendors)} hint={количество(d.totals.stations)}
        active={отбор === 'all'} onClick={() => переключить('all')} />
      <Tile icon={AlertTriangle} label="Есть станции с отказами" value={qty(сПроблемами.length)}
        hint={'марок · ' + количество(d.totals.badStations) + ' с частыми отказами'}
        active={отбор === 'bad'} onClick={() => переключить(отбор === 'bad' ? 'all' : 'bad')} />
      <Tile icon={PlugZap} label="Без зарядок больше недели" value={qty(безЗарядок.length)}
        hint={'марок · ' + количество(sum(исходные, 'silentWeek'))}
        active={отбор === 'silent'} onClick={() => переключить(отбор === 'silent' ? 'all' : 'silent')} />
      <Tile icon={Gauge} label="Заряжает меньше половины" value={qty(малоЗаряжает.length)}
        hint="марок · доля от действующих станций" active={отбор === 'low'} onClick={() => переключить(отбор === 'low' ? 'all' : 'low')} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      {фильтрыОткрыты && <div className="flex flex-wrap items-end gap-3">
        <Поле id="vendors-window" label="Окно анализа" className="w-36"><Select value={String(окно)} onValueChange={(v) => setОкно(Number(v))}>
          <SelectTrigger id="vendors-window" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{[30, 90, 180].map((n) => <SelectItem key={n} value={String(n)}>{n} дней</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="vendors-show" label="Показать" className="w-64"><Select value={отбор} onValueChange={(v) => setОтбор(v as Отбор)}>
          <SelectTrigger id="vendors-show" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(ПОКАЗАТЬ).map(([key, text]) => <SelectItem key={key} value={key}>{text}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="vendors-region" label="Регион" className="w-52"><Select value={локальныйРегион} onValueChange={setРегионОтбора}>
          <SelectTrigger id="vendors-region" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Все регионы контура</SelectItem>
            {d.regions.filter((r) => !regionIds.length || regionIds.includes(r)).map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
          </SelectContent>
        </Select></Поле>
        <Поле id="vendors-search" label="Марка или модель" className="w-56"><Input id="vendors-search" value={поиск}
          onChange={(e) => setПоиск(e.target.value)} placeholder="Название марки или модели…" className="h-9" /></Поле>
        <Поле id="vendors-page" label="Строк на странице" className="w-32"><PageSizeField bare id="vendors-page" /></Поле>
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
          <PanelViewTabs label={null} value={вид} onChange={setВид} tabs={[{ k: 'list', label: 'Список' }, { k: 'pivot', label: 'Сводная' }]} />
          <span className="text-xs text-muted-foreground">марок: {qty(оставлены.length)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ExportButton title="Производители" subtitle={подпись} getEl={() => экран.current} />
          <Button size="sm" variant="outline" onClick={сброс} disabled={!отборов}>Сбросить фильтры</Button>
        </div>
      </div>
      <ToolStrip />
      {вид === 'pivot' ? qВсе.isLoading ? <div className="flex justify-center py-8"><Loader2 className="size-5 animate-spin" /></div>
        : qВсе.isError ? <div role="alert" className="flex items-center gap-3 p-4 text-sm">Не удалось загрузить станции для сводной.
          <Button variant="outline" onClick={() => void qВсе.refetch()}>Повторить</Button></div>
          : <div className="flex flex-col gap-2"><p className="text-xs text-muted-foreground">{подпись} · станции {оставлены.length} выбранных марок</p>
            <ReportPivot fields={['vendor', 'model', 'region', 'state', 'stations', 'visits', 'visitsFailed', 'energyKwh', 'revenue']}
              columns={['Марка', 'Модель', 'Регион', 'Как работает', 'Станций', 'Приездов', 'Без зарядки', 'кВт·ч', 'Выручка, ₽']} rows={сводная} /></div>
        : <SheetTable {...набор.table} caption="Производители" lines={[подпись, ...фильтры]} defaultWidths={ШИРИНЫ}
          render={ячейка} rowTitle={(i) => строки[i]?.vendor ?? ''} onView={setПорядок}
          onRow={(order, pos) => { const row = строки[order[pos]]; if (row) раскрыть(row.vendor) }}
          expand={(i) => открыты.has(строки[i]?.vendor) ? <VendorInlineStations key={строки[i].vendor}
            vendor={строки[i].vendor} days={окно} region={регион} asOf={наДень || undefined} threshold={d.threshold} /> : null}
          derive={(t) => {
            const weighted = итоги(оставлены, окно)
            const fixed = t.map((v, i) => i < weighted.length ? weighted[i] : v)
            return набор.table.derive ? набор.table.derive(fixed) : fixed
          }}
          empty="По этому отбору марки не найдены. Измените поиск или сбросьте фильтры."
          tableAttrs={exportRows('Производители', видимые.map((c) => набор.sheet.head[c]),
            порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />}
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Марка, модель или число" formulaExample="Например, Энергия на станцию"
      compare={<VendorCompare companyId={companyId} days={окно} region={регион} now={d} />} /></ToolPanel>
    <RowCard report="Производители" head={набор.sheet.head} title={выбранная?.vendor}
      row={карточка ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
      at={карточка?.pos ?? 0} of={карточка?.order.length ?? 0}
      onStep={(dir) => setКарточка((v) => v ? { ...v, pos: Math.max(0, Math.min(v.pos + dir, v.order.length - 1)) } : v)}
      onClose={() => { setКарточка(null); setРазбор(null) }}
      extra={выбранная && <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
        {РАСШИФРОВКИ.map((r) => <RelatedLink key={r.key} label={r.title} hint={r.hint} onClick={() => setРазбор(r.key)} />)}
      </div>} />
    <VendorDrill vendor={выбранная?.vendor ?? ''} kind={карточка ? разбор : null} days={окно} region={регион}
      asOf={наДень || undefined} threshold={d.threshold} onClose={() => setРазбор(null)} />
  </div>
}

function VendorInlineStations({ vendor, days, region, asOf, threshold }: {
  vendor: string; days: number; region?: string; asOf?: string; threshold: number
}) {
  const { companyId } = useCompany()
  const [order, setOrder] = useState<number[]>([])
  const q = useQuery({
    queryKey: ['ops-vendor-stations', companyId, vendor, days, region ?? '', asOf ?? ''],
    queryFn: () => getNetworkVendors(companyId, { vendor, days, region, asOf }),
    enabled: !!companyId, staleTime: 60_000,
  })
  const stations = q.data?.stations ?? []
  const rows = useMemo<Cell[][]>(() => stations.map((r) => {
    const state = r.silentDays === null ? 'Нет зарядок в истории' : r.silentDays <= 2 ? 'Заряжала за 2 суток'
      : 'Без зарядок ' + qty(r.silentDays) + ' дн'
    return [r.number ?? r.code ?? '', r.name, r.model ?? '',
      state + (сОтказами(r, threshold) ? ' · частые отказы' : ''), r.region ?? '', r.visits,
      r.visits ? r.failedVisitsPct : '', r.silentDays ?? '', r.energyKwh, r.revenue]
  }), [stations, threshold])
  if (q.isLoading) return <div role="status" className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
    <Loader2 className="size-4 animate-spin" />Загружаются станции {vendor}</div>
  if (q.isError) return <div role="alert" className="flex items-center gap-3 p-3 text-sm">Не удалось загрузить станции {vendor}.
    <Button variant="outline" onClick={() => void q.refetch()}>Повторить</Button></div>
  return <SheetTable head={СТАНЦИИ_ШАПКА} rows={rows} caption={'Станции · ' + vendor} onView={setOrder}
    tableAttrs={exportRows('Станции · ' + vendor, СТАНЦИИ_ШАПКА, order.map((i) => rows[i]))}
    lines={[days + ' дней' + (q.data ? ' по ' + дата(q.data.asOf) : ''), 'по названию — карточка станции']}
    defaultWidths={СТАНЦИИ_ШИРИНЫ}
    render={(i, c) => {
      const r = stations[i]
      if (c === 0) return <span className="block truncate font-mono text-xs">{r.number ?? r.code ?? '—'}</span>
      if (c === 1) return <span className="block whitespace-normal break-words"><StationLink station={r.locationId}>{r.name}</StationLink></span>
      if (c === 3) return <span className="block whitespace-normal text-xs">{rows[i][c]}</span>
      if (c === 6 && r.visits) return <span className={cn(сОтказами(r, threshold) && 'font-semibold text-destructive')}>{qty(r.failedVisitsPct)} %</span>
      return undefined
    }} empty="Станций этой марки в выборке нет" />
}

const СТАНЦИИ_ШАПКА = ['№', 'Станция', 'Модель', 'Как работает', 'Регион', 'Приездов', 'Без зарядки, %', 'Без зарядок, дн', 'Энергия, кВт·ч', 'Выручка, ₽']
const СТАНЦИИ_ШИРИНЫ = { 0: 84, 1: 230, 2: 160, 3: 250, 4: 180 }

function VendorDrill({ vendor, kind, days, region, asOf, threshold, onClose }: {
  vendor: string; kind: Разбор | null; days: number; region?: string; asOf?: string; threshold: number; onClose: () => void
}) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['ops-vendor-stations', companyId, vendor, days, region ?? '', asOf ?? ''],
    queryFn: () => getNetworkVendors(companyId, { vendor, days, region, asOf }),
    enabled: !!companyId && !!vendor && !!kind, staleTime: 60_000,
  })
  const stations = (q.data?.stations ?? []).filter((r) => kind === 'bad' ? сОтказами(r, threshold) : kind === 'silent' ? нетЗарядок(r) : true)
  let head = ['№', 'Станция', 'Регион', 'Модель', 'Приездов', 'Без зарядки, %', 'Без зарядок, дн', 'Энергия, кВт·ч', 'Выручка, ₽']
  let rows: Cell[][] = stations.map((r) => [r.number ?? r.code ?? '', r.name, r.region ?? '', r.model ?? '', r.visits,
    r.visits ? r.failedVisitsPct : '', r.silentDays ?? 'Нет зарядок в истории', r.energyKwh, r.revenue])
  if (kind === 'models') {
    head = ['Модель', 'Станций', 'Приездов', 'Без зарядки', 'Без зарядки, %', 'Энергия, кВт·ч', 'Выручка, ₽']
    const groups = new Map<string, VendorStationRow[]>()
    for (const r of stations) { const key = r.model || 'Модель не указана'; groups.set(key, [...(groups.get(key) ?? []), r]) }
    rows = [...groups].map(([name, rs]) => {
      const visits = rs.reduce((n, r) => n + r.visits, 0), failed = rs.reduce((n, r) => n + r.visitsFailed, 0)
      return [name, rs.length, visits, failed, доля(failed, visits), rs.reduce((n, r) => n + r.energyKwh, 0), rs.reduce((n, r) => n + r.revenue, 0)]
    })
  }
  const title = РАСШИФРОВКИ.find((r) => r.key === kind)?.title ?? ''
  return <RelatedReport open={!!kind && !!vendor} title={title} subtitle={vendor + ' · ' + days + ' дней' + (q.data ? ' по ' + дата(q.data.asOf) : '')}
    head={head} rows={rows} loading={q.isLoading} error={q.isError} onClose={onClose}>
    <SheetTable key={kind} head={head} rows={rows} caption={vendor} lines={[]}
      defaultWidths={kind === 'models' ? { 0: 240 } : { 0: 100, 1: 260, 2: 180, 3: 190 }} empty="Станций по этому отбору нет" />
  </RelatedReport>
}

function VendorCompare({ companyId, days, region, now }: { companyId: string; days: number; region?: string; now: NetworkVendors }) {
  const [offset, setOffset] = useState<number | null>(null)
  const d = new Date(now.asOf.slice(0, 10) + 'T12:00:00Z')
  d.setUTCDate(d.getUTCDate() - (offset ?? 0))
  const past = offset ? d.toISOString().slice(0, 10) : ''
  const q = useQuery({ queryKey: ['ops-vendors-compare', companyId, days, region ?? '', past],
    queryFn: () => getNetworkVendors(companyId, { days, region, asOf: past }), enabled: !!companyId && !!past, staleTime: 60_000 })
  return <div className="flex flex-col gap-3">
    <p className="text-xs text-muted-foreground">Весь список марок региона за одинаковое окно. Поиск, плитки и фильтры столбцов не применяются.</p>
    <div className="flex flex-wrap gap-2">{[[1, 'День назад'], [7, 'Неделю назад'], [days, 'Предыдущее окно']].map(([n, label]) =>
      <Button key={String(n) + label} size="sm" variant={offset === n ? 'default' : 'outline'} onClick={() => setOffset(Number(n))}>{label}</Button>)}</div>
    {!past ? <p className="text-sm text-muted-foreground">Выберите день сравнения.</p> : q.isFetching ? <Loader2 className="size-5 animate-spin" />
      : q.isError ? <p role="alert">Не удалось загрузить прошлый срез.</p> : q.data && <>
        <p className="text-xs text-muted-foreground">{дата(now.asOf)} / {дата(q.data.asOf)} · окно {days} дней. Состав парка текущий в обоих срезах.</p>
        <dl className="divide-y divide-border/60">{[
          ['Марок', now.totals.vendors, q.data.totals.vendors], ['Приездов', now.totals.visits, q.data.totals.visits],
          ['Приездов без зарядки', now.totals.visitsFailed, q.data.totals.visitsFailed],
          ['Станций с отказами', now.totals.badStations, q.data.totals.badStations],
        ].map(([label, current, previous]) => <div key={label} className="flex flex-col gap-1 py-2 text-sm">
          <dt>{label}</dt><dd className="text-muted-foreground">сейчас {qty(Number(current))} · было {qty(Number(previous))}
            <span className="ml-2 font-semibold text-foreground">{Number(current) - Number(previous) > 0 ? '+' : ''}{qty(Number(current) - Number(previous))}</span></dd>
        </div>)}</dl>
      </>}
  </div>
}
const ПОМОЩЬ = <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
  <p>«Производители» сравнивает марки нашего парка, без партнёрских станций. Плитки показывают число марок и отбирают список.
    В подписи плиток — число станций. Повторное нажатие снимает отбор.</p>
  <p>Конец общего «Периода» задаёт дату среза. По вчера или сегодня — последние загруженные данные.
    Начало периода не меняет окно: 30, 90 или 180 дней выбираются в фильтрах. Состав парка и паспортные статусы текущие;
    история состава не восстановлена.</p>
  <p>«Заряжали за 2 суток» — отпускали энергию за двое суток от среза; доля от действующих станций.
    «Без зарядок больше недели» включает станции без зарядок в истории. «Станций с отказами» — не менее 10 приездов,
    как минимум каждый пятый без зарядки. Несколько попыток подряд считаются одним приездом.</p>
  <p>Итоги процентов считаются из общих числителей и знаменателей, не суммой процентов марок.
    Отдача — энергия на действующую станцию в сутки. Попытки на приезд и средняя мощность в итог не складываются.</p>
  <p>Строка производителя — группа. Щелчок по строке, стрелке слева или Enter раскрывает конкретные станции прямо под маркой.
    Можно раскрыть несколько марок. В списке станций видны модель, регион, зарядки и отказы; по названию открывается карточка станции.
    Значок документа справа от марки открывает её отдельную карточку с отчётами. Ограничения в 60 станций нет.</p>
  <p>Сводная строится по станциям выбранных марок: марка, модель, регион и давность зарядок.
    Фильтры столбцов списка ограничивают марки и в сводной. Формулы по маркам в станционную сводную не переносятся.</p>
  <p>Рельса: калькулятор, формулы, поиск по видимым ячейкам, столбцы, сравнение и отложенные цифры.
    Excel получает видимые столбцы и строки с отбором в текущем порядке.</p>
</div>
