import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, ChevronDown, ChevronRight, ClipboardX, Loader2, PlugZap, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StationLink } from '@/components/common/StationLink'
import { BulkTicketDialog } from '@/components/locations/BulkTicketDialog'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useMonitorScope } from './useMonitorScope'
import { useStationCard } from '@/contexts/StationCardContext'
import { LOCATION_STATUS_META, type LocationStatus } from '@/types/location'
import { cn } from '@/lib/utils'
import { matchesSearch } from '@/lib/textUtils'
import { getNetworkState, type NetworkState, type NetworkStationRow } from '@/services/opsService'
import { getNetworkOpenWork, type OpenWorkRow } from '@/services/spaceObjectsService'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable,
  Tile, ToolPanel, ToolStrip, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { PanelViewTabs } from './PanelViewTabs'
import { ReportPivot } from './ReportPivot'
import { OpsSnapshotStatus } from './OpsSnapshotNotice'
import { IntakeHealthBar } from './IntakeHealthBar'
import { ExportButton } from './analytics/ExportButton'
import { exportRows } from './analytics/exportRows'
import { daysAgoISO } from './analytics/periodPresets'

const С = { номер: 0, станция: 1, регион: 2, статус: 3, тишина: 4, сессии: 5, потери: 6,
  работа: 7, последняя: 8, город: 9, заявок: 10, заявка: 11, расхождение: 12, внимание: 13,
  выручка: 14, сессии90: 15, разъёмов: 16, паспорт: 17, статусСырой: 18 }
const ШАПКА = ['№', 'Станция', 'Регион', 'Состояние', 'Без зарядок, дн', 'Сессий за 7 дней',
  'Недобираем, ₽/мес', 'В работе', 'Последняя зарядка', 'Город', 'Открытых заявок', 'Последняя заявка',
  'Расхождение статуса', 'Требует внимания', 'Обычная выручка, ₽/мес', 'Сессий за 90 дней', 'Разъёмов', 'Паспортный статус', 'Статус из выгрузки']
const СКРЫТЫ = [С.город, С.заявок, С.заявка, С.расхождение, С.внимание, С.выручка, С.сессии90, С.разъёмов, С.паспорт, С.статусСырой]
const СОСТАВ = { order: [], hidden: СКРЫТЫ }
const ШИРИНЫ = { 0: 70, 1: 240, 2: 180, 3: 190, 4: 110, 5: 110, 6: 140, 7: 150, 8: 130 }
const РЕГ_ШАПКА = ['Регион', 'Станций', 'Числятся рабочими', 'Нет связи', 'Без зарядок > 7 дн', 'Требуют внимания', 'Недобираем, ₽/мес']
const РЕГ_СКРЫТЫ: number[] = []
const РЕГ_ШИРИНЫ = { 0: 280, 1: 90, 2: 140, 3: 100, 4: 140, 5: 130, 6: 150 }
const ПОКАЗАТЬ = { all: 'Вся сеть', attention: 'Требуют внимания', fresh: 'Заряжали за 2 суток', silent: 'Без зарядок больше недели',
  loss: 'Есть недобор выручки', mismatch: 'Расхождение статуса', unassigned: 'Требуют внимания без заявки' }
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:ops-state'
type Настройки = { search: string; region: string; status: string; filter: keyof typeof ПОКАЗАТЬ; view: string }
type Работа = Map<string, OpenWorkRow> | null
const дата = (s: string) => new Date(s).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })
const сумма = (rows: NetworkStationRow[], key: keyof NetworkStationRow) => rows.reduce((n, r) => n + (Number(r[key]) || 0), 0)
const молчит = (r: NetworkStationRow) => r.silentDays === null || r.silentDays > 7
const деньги = (n: number) => qty(Math.round(n / 1000)) + ' тыс ₽'
const ходРаботы = (r: NetworkStationRow, work: Работа) => work === null ? 'неизвестно' : work.get(r.locationId)?.open
  ? (work.get(r.locationId)?.lastNumber || 'в работе') + (work.get(r.locationId)?.breached ? ' · срок сорван' : '') : r.attention ? 'не взята' : 'нет открытых заявок'

function строка(r: NetworkStationRow, work: Работа): Cell[] {
  const w = work?.get(r.locationId)
  return [r.number ?? r.code ?? '', r.name, r.region ?? '', r.statusLabel, r.silentDays ?? 'ни разу', r.sessions7d,
    r.loss, ходРаботы(r, work), r.lastSessionAt ? дата(r.lastSessionAt) : '', r.city ?? '', work ? w?.open ?? 0 : '',
    w?.lastNumber ?? '', r.mismatch ? 'да' : 'нет', r.attention ? 'да' : 'нет', r.revenuePerMonth,
    r.sessions90d, r.connectors ?? '', LOCATION_STATUS_META[r.lifeStatus as LocationStatus]?.label ?? r.lifeStatus, r.statusRaw ?? '']
}
function итоги(rows: NetworkStationRow[], work: Работа): Cell[] {
  return ['Итого', rows.length + ' станций', '', '', '', сумма(rows, 'sessions7d'), сумма(rows, 'loss'), '', '', '',
    work ? rows.reduce((n, r) => n + (work.get(r.locationId)?.open ?? 0), 0) : '', '', '', '',
    сумма(rows, 'revenuePerMonth'), сумма(rows, 'sessions90d'), сумма(rows, 'connectors'), '', '']
}
function поРегионам(rows: NetworkStationRow[]) {
  const groups = new Map<string, NetworkStationRow[]>()
  rows.forEach((r) => {
    const name = r.region || 'Регион не указан', group = groups.get(name)
    if (group) group.push(r); else groups.set(name, [r])
  })
  return [...groups].map(([name, stations]) => ({ name, stations, cells: регионСтрока(stations, name) }))
    .sort((a, b) => Number(b.cells[6]) - Number(a.cells[6]))
}
function регионСтрока(rows: NetworkStationRow[], name = 'Итого'): Cell[] {
  return [name, rows.length, rows.filter((r) => r.status === 'working').length, rows.filter((r) => r.status === 'no_link').length,
    rows.filter(молчит).length, rows.filter((r) => r.attention).length, сумма(rows, 'loss')]
}
function Поле({ id, label, children, className }: { id: string; label: string; children: ReactNode; className: string }) {
  return <div className={cn('flex min-w-0 flex-col gap-1', className)}>
    <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>{children}
  </div>
}

export function NetworkStatePanel() {
  const scope = useMonitorScope()
  const { companyId } = useCompany()
  const { regionIds, period } = useFilters()
  const [settings, setSettings] = useState<Настройки>({ search: '', region: 'all', status: 'all', filter: 'attention', view: 'list' })
  const region = regionIds.length ? regionIds.join('|') : undefined
  const asOf = period.to >= daysAgoISO(1) ? '' : period.to
  const q = useQuery({ queryKey: ['ops-network-state-report', companyId, region ?? '', asOf, scope],
    queryFn: () => getNetworkState(companyId, { ...scope, region, asOf: asOf || undefined }), enabled: !!companyId, staleTime: 60_000 })
  const work = useQuery({ queryKey: ['network-open-work', companyId, asOf], queryFn: () => getNetworkOpenWork(companyId),
    enabled: !!companyId && !asOf, staleTime: 60_000, retry: false })
  const поЗаявкам = useMemo(() => !asOf && work.data && !work.isError
    ? new Map(work.data.objects.map((r) => [r.ecoObjectId, r])) : null, [asOf, work.data, work.isError])
  if (q.isLoading) return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  if (q.isError || !q.data) return <div role="alert" className="flex flex-col items-center gap-3 p-8 text-sm text-muted-foreground">
    <p>Не удалось получить состояние сети.</p><Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching}>Повторить загрузку</Button>
  </div>
  return <StateReport key={settings.view === 'regions' ? 'regions' : 'stations'} data={q.data} settings={settings}
    change={(patch) => setSettings((s) => ({ ...s, ...patch }))} companyId={companyId} region={region} work={поЗаявкам}
    workNote={asOf ? 'история заявок на этот день недоступна' : work.isError ? 'связь с Поддержкой недоступна' : 'загружаем сведения о заявках'}
    retryWork={() => void work.refetch()} historical={!!asOf} />
}

function StateReport({ data: d, settings: s, change, companyId, region, work, workNote, retryWork, historical }: {
  data: NetworkState; settings: Настройки; change: (patch: Partial<Настройки>) => void; companyId: string; region?: string;
  work: Работа; workNote: string; retryWork: () => void; historical: boolean
}) {
  const экран = useRef<HTMLDivElement>(null)
  const станция = useStationCard()
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [разбор, setРазбор] = useState<'region' | 'status' | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [открыты, setОткрыты] = useState<Set<string>>(new Set())
  const [отмечены, setОтмечены] = useState<Set<string>>(new Set())
  const [пачка, setПачка] = useState<{ id: string; name: string; number: string | null }[] | null>(null)
  const раскрыть = useCallback((name: string) => setОткрыты((was) => {
    const next = new Set(was); if (next.has(name)) next.delete(name); else next.add(name); return next
  }), [])
  const регионы = useMemo(() => [...new Set(d.stations.flatMap((r) => r.region ? [r.region] : []))].sort((a, b) => a.localeCompare(b, 'ru')), [d.stations])
  const выбранРегион = регионы.includes(s.region) ? s.region : 'all'
  const строки = useMemo(() => d.stations.filter((r) => {
    if (s.filter === 'attention' && !r.attention) return false
    if (s.filter === 'fresh' && (r.silentDays === null || r.silentDays > 2)) return false
    if (s.filter === 'silent' && !молчит(r)) return false
    if (s.filter === 'loss' && !r.loss) return false
    if (s.filter === 'mismatch' && !r.mismatch) return false
    if (s.filter === 'unassigned' && (!work || !r.attention || work.get(r.locationId)?.open)) return false
    if (s.status !== 'all' && r.status !== s.status) return false
    if (выбранРегион !== 'all' && r.region !== выбранРегион) return false
    return !s.search.trim() || matchesSearch(s.search, [r.number, r.code, r.name, r.city, r.region, r.statusLabel, r.statusRaw])
  }), [d.stations, s.filter, s.status, s.search, выбранРегион, work])
  const группы = useMemo(() => поРегионам(строки), [строки])
  const регионыВид = s.view === 'regions'
  const ячейки = useMemo(() => регионыВид ? группы.map((g) => g.cells) : строки.map((r) => строка(r, work)), [регионыВид, группы, строки, work])
  const total = useMemo(() => регионыВид ? регионСтрока(строки) : итоги(строки, work), [регионыВид, строки, work])
  const status = useMemo(() => <OpsSnapshotStatus dataThrough={d.dataThrough} dataLagHours={d.dataLagHours} snapshotNote={d.snapshotNote} />,
    [d.dataThrough, d.dataLagHours, d.snapshotNote])
  const help = useMemo(() => <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">{ПОМОЩЬ}<p>{d.note}</p><IntakeHealthBar compact /></div>, [d.note])
  const набор = useReportKit({ id: регионыВид ? 'ops-state-regions.v1' : 'ops-state.v1', title: 'Состояние сети',
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
    const r = строки[i], w = work?.get(r.locationId)
    if (c === С.станция) return <span className="whitespace-normal break-words"><span className="font-medium">{r.name}</span>
      {r.city && <span className="ml-1.5 text-xs text-muted-foreground">{r.city}</span>}</span>
    if (c === С.статус) return <span title={r.statusRaw ?? undefined} className="whitespace-normal">{r.statusLabel}
      {r.mismatch && <span className="block text-xs text-muted-foreground">числится рабочей, зарядок нет</span>}</span>
    if (c === С.тишина && r.silentDays === null) return <span className="text-xs text-muted-foreground">ни разу</span>
    if (c === С.работа) return w?.lastId ? <a href={'/support/customer/tickets/' + w.lastId} className="text-primary hover:underline">{ходРаботы(r, work)}{w.open > 1 ? ' +' + (w.open - 1) : ''}</a>
      : <span className={cn(r.attention && work && 'text-destructive')}>{ходРаботы(r, work)}</span>
    return undefined
  }, [регионыВид, группы, открыты, раскрыть, строки, work])
  const фильтры = [s.filter !== 'all' && ПОКАЗАТЬ[s.filter], выбранРегион !== 'all' && выбранРегион,
    s.status !== 'all' && d.statusLabels[s.status], s.search.trim() && 'поиск «' + s.search.trim() + '»'].filter(Boolean) as string[]
  const отборов = фильтры.length + Object.keys(набор.filters).length
  const сброс = () => { change({ search: '', region: 'all', status: 'all', filter: 'all' }); набор.setFilters({}); setОтмечены(new Set()) }
  const выбрать = (filter: Настройки['filter']) => { change({ filter: s.filter === filter ? 'all' : filter }); набор.setFilters({}); setОтмечены(new Set()) }
  const выбранная = карточка ? строки[карточка.order[карточка.pos]] : null
  const расшифровка = выбранная && разбор ? d.stations.filter((r) => разбор === 'status' ? r.status === выбранная.status : r.region === выбранная.region) : []
  const подпись = 'срез на ' + дата(d.asOf) + ' · МСК'
  const проблемные = d.stations.filter((r) => r.attention)
  const вРаботе = work ? проблемные.filter((r) => work.get(r.locationId)?.open).length : 0
  const отмеченные = !регионыВид ? оставлены.filter((r) => отмечены.has(r.locationId)) : []
  const открытьЗаявки = (rows: NetworkStationRow[]) => setПачка(rows.map((r) => ({ id: r.locationId, name: r.name, number: r.number ?? r.code })))
  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-3 2xl:grid-cols-6">
      <Tile icon={Activity} label="Станций в сети" value={qty(d.totals.stations)} hint={'действующих ' + qty(d.totals.active)} active={s.filter === 'all'} onClick={() => выбрать('all')} />
      <Tile icon={PlugZap} label="Заряжали за 2 суток" value={qty(d.totals.charging2d)} hint={'за неделю ' + qty(d.totals.chargingWeek)} active={s.filter === 'fresh'} onClick={() => выбрать('fresh')} />
      <Tile icon={WifiOff} label="Без зарядок больше недели" value={qty(d.totals.silentWeek)} hint={'ни разу не заряжали ' + qty(d.totals.neverCharged)} active={s.filter === 'silent'} onClick={() => выбрать('silent')} />
      <Tile icon={AlertTriangle} label="Требуют внимания" value={qty(d.totals.attention)} hint={'расхождений статуса ' + qty(d.totals.mismatch)} active={s.filter === 'attention'} onClick={() => выбрать('attention')} />
      <Tile icon={AlertTriangle} label="Недобираем в месяц" value={деньги(d.totals.lossPerMonth)} hint="по выручке замолчавших станций" active={s.filter === 'loss'} onClick={() => выбрать('loss')} />
      <Tile icon={ClipboardX} label="Не взяты в работу" value={work ? qty(проблемные.length - вРаботе) : '—'} hint={work ? 'в работе ' + qty(вРаботе) : workNote}
        active={s.filter === 'unassigned'} onClick={work ? () => выбрать('unassigned') : undefined} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      {фильтрыОткрыты && <div className="flex flex-wrap items-end gap-3">
        <Поле id="state-show" label="Показать" className="w-64"><Select value={s.filter} onValueChange={(v) => change({ filter: v as Настройки['filter'] })}>
          <SelectTrigger id="state-show" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(ПОКАЗАТЬ).map(([key, text]) => <SelectItem key={key} value={key} disabled={key === 'unassigned' && !work}>{text}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="state-status" label="Состояние" className="w-52"><Select value={s.status} onValueChange={(status) => change({ status })}>
          <SelectTrigger id="state-status" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Любое состояние</SelectItem>{Object.entries(d.statusLabels).map(([key, text]) => <SelectItem key={key} value={key}>{text}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="state-region" label="Регион" className="w-52"><Select value={выбранРегион} onValueChange={(region) => change({ region })}>
          <SelectTrigger id="state-region" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Все регионы контура</SelectItem>{регионы.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="state-search" label="Найти станцию" className="w-56"><Input id="state-search" value={s.search}
          onChange={(e) => change({ search: e.target.value })} placeholder="Номер, название, город…" className="h-9" /></Поле>
        <Поле id="state-page" label="Строк на странице" className="w-32"><PageSizeField bare id="state-page" /></Поле>
      </div>}
      <div className={cn('flex flex-wrap items-center justify-between gap-2', фильтрыОткрыты && 'border-t border-border/60 pt-3')}>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" aria-expanded={фильтрыОткрыты} onClick={() => {
            const next = !фильтрыОткрыты; setФильтрыОткрыты(next)
            try { localStorage.setItem(КЛЮЧ_ФИЛЬТРОВ, next ? '1' : '0') } catch { /* хранилище недоступно */ }
          }} className="inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm font-semibold text-primary hover:bg-accent">
            <ChevronDown className={cn('size-4 transition-transform', фильтрыОткрыты && 'rotate-180')} />{фильтрыОткрыты ? 'Свернуть фильтры' : 'Фильтры'}
            {!фильтрыОткрыты && отборов > 0 && <span className="rounded-full bg-primary px-1.5 text-xs leading-5 text-primary-foreground">{отборов}</span>}
          </button>
          <PanelViewTabs label={null} value={s.view} onChange={(view) => change({ view })} tabs={[{ k: 'list', label: 'Список' }, { k: 'regions', label: 'По регионам' }, { k: 'pivot', label: 'Сводная' }]} />
          <span className="text-xs text-muted-foreground">{регионыВид ? 'регионов' : 'станций'}: {qty(набор.kept.length)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {отмеченные.length > 0 && <Button size="sm" onClick={() => открытьЗаявки(отмеченные)}>Завести заявки ({отмеченные.length})</Button>}
          <ExportButton title="Состояние сети" subtitle={подпись} getEl={() => экран.current} />
          <Button size="sm" variant="outline" onClick={сброс} disabled={!отборов}>Сбросить фильтры</Button>
        </div>
      </div>
      {s.filter === 'unassigned' && !work && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm"><p>{workNote}. Отбор без заявки сейчас неизвестен.</p>
        {!historical && <Button variant="outline" onClick={retryWork}>Повторить запрос заявок</Button>}</div>}
      <ToolStrip />
      {s.view === 'pivot' ? <ReportPivot fields={['region', 'status', 'city', 'silence', 'work', 'stations', 'loss', 'sessions7d']}
        columns={['Регион', 'Состояние', 'Город', 'Давность', 'В работе', 'Станций', 'Недобираем, ₽/мес', 'Сессий за 7 дней']}
        rows={оставлены.map((r) => ({ region: r.region || 'Регион не указан', status: r.statusLabel, city: r.city || 'Город не указан',
          silence: r.silentDays === null ? 'Ни разу не заряжала' : r.silentDays <= 2 ? 'Заряжала за 2 суток' : r.silentDays <= 7 ? 'Без зарядок до недели' : 'Без зарядок больше недели',
          work: !work ? 'Неизвестно' : work.get(r.locationId)?.open ? 'Есть открытая заявка' : r.attention ? 'Не взята в работу' : 'Нет открытой заявки',
          stations: 1, loss: r.loss, sessions7d: r.sessions7d }))} />
        : <SheetTable {...набор.table} caption={регионыВид ? 'Состояние сети по регионам' : 'Станции сети'} lines={[подпись, ...фильтры]}
          defaultWidths={регионыВид ? РЕГ_ШИРИНЫ : ШИРИНЫ} render={ячейка} onView={setПорядок}
          rowTitle={(i) => регионыВид ? группы[i]?.name ?? '' : строки[i]?.name ?? ''}
          onRow={(order, pos) => регионыВид ? раскрыть(группы[order[pos]].name) : setКарточка({ order, pos })}
          mark={!регионыВид ? { has: (i) => отмечены.has(строки[i].locationId), label: (i) => строки[i].name,
            set: (ids, on) => setОтмечены((was) => { const next = new Set(was); ids.forEach((i) => { if (on) next.add(строки[i].locationId); else next.delete(строки[i].locationId) }); return next }) } : undefined}
          expand={регионыВид ? (i) => открыты.has(группы[i]?.name) ? <StateSubset key={группы[i].name} rows={группы[i].stations} work={work} caption={'Станции · ' + группы[i].name} lines={[подпись]} /> : null : undefined}
          derive={(t) => { const rows = регионыВид ? набор.kept.flatMap((i) => группы[i].stations) : оставлены
            const values = регионыВид ? регионСтрока(rows) : итоги(rows, work)
            const fixed = t.map((v, i) => i < values.length ? values[i] : v)
            return набор.table.derive ? набор.table.derive(fixed) : fixed }}
          empty={s.filter === 'unassigned' && !work ? 'Статус заявок неизвестен.' : 'По этому отбору станции не найдены. Измените поиск или сбросьте фильтры.'}
          tableAttrs={exportRows(регионыВид ? 'Регионы' : 'Станции', видимые.map((c) => набор.sheet.head[c]), порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />}
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Номер, станция, регион или число" formulaExample="Например, Выручка на разъём"
      compare={<StateCompare companyId={companyId} region={region} now={d} />} /></ToolPanel>
    <RowCard report="Состояние сети" head={набор.sheet.head} title={выбранная?.name}
      row={карточка && !станция.открыта && !пачка ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
      at={карточка?.pos ?? 0} of={карточка?.order.length ?? 0}
      onStep={(dir) => { setРазбор(null); setКарточка((v) => v ? { ...v, pos: Math.max(0, Math.min(v.pos + dir, v.order.length - 1)) } : v) }}
      onClose={() => { setКарточка(null); setРазбор(null) }} extra={выбранная && <div className="flex flex-col gap-3">
        <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
          <RelatedLink label="Станции региона" hint={выбранная.region || 'Регион не указан'} onClick={() => setРазбор('region')} />
          <RelatedLink label="С таким же состоянием" hint={выбранная.statusLabel} onClick={() => setРазбор('status')} />
        </div>
        <div className="text-sm"><StationLink station={выбранная.locationId}>Открыть карточку станции</StationLink></div>
        <div className="flex flex-col gap-2 border-t pt-3"><p className="text-xs font-semibold text-muted-foreground">Действия</p>
          <Button variant="outline" onClick={() => открытьЗаявки([выбранная])}>Завести заявку</Button></div>
      </div>} />
    <RelatedReport open={!!разбор && !!выбранная && !станция.открыта} title={разбор === 'status' ? 'С таким же состоянием' : 'Станции региона'}
      subtitle={подпись} head={ШАПКА} rows={расшифровка.map((r) => строка(r, work))} onClose={() => setРазбор(null)} note="Все станции того же среза; локальные отборы основной таблицы не применяются.">
      <StateSubset rows={расшифровка} work={work} caption={разбор === 'status' ? выбранная?.statusLabel || '' : выбранная?.region || 'Регион не указан'} lines={[подпись]} />
    </RelatedReport>
    <BulkTicketDialog open={!!пачка} stations={пачка ?? []} onClose={() => { setПачка(null); setОтмечены(new Set()); if (!historical) retryWork() }} />
  </div>
}

function StateSubset({ rows, work, caption, lines }: { rows: NetworkStationRow[]; work: Работа; caption: string; lines: string[] }) {
  const [order, setOrder] = useState<number[]>([])
  const cells = useMemo(() => rows.map((r) => строка(r, work)), [rows, work])
  return <SheetTable head={ШАПКА} rows={cells} caption={caption} lines={lines} cols={СОСТАВ} defaultWidths={ШИРИНЫ} onView={setOrder}
    render={(i, c) => c === С.станция ? <StationLink station={rows[i].locationId}>{rows[i].name}</StationLink> : c === С.тишина && rows[i].silentDays === null ? 'ни разу' : undefined}
    tableAttrs={exportRows(caption, ШАПКА.filter((_, i) => !СКРЫТЫ.includes(i)), order.map((i) => cells[i].filter((_, c) => !СКРЫТЫ.includes(c))))} />
}

function StateCompare({ companyId, region, now }: { companyId: string; region?: string; now: NetworkState }) {
  const scope = useMonitorScope()
  const [offset, setOffset] = useState<number | null>(null)
  const date = new Date(now.asOf.slice(0, 10) + 'T12:00:00Z'); date.setUTCDate(date.getUTCDate() - (offset ?? 0))
  const past = offset ? date.toISOString().slice(0, 10) : ''
  const q = useQuery({ queryKey: ['ops-state-compare', companyId, region ?? '', past, scope],
    queryFn: () => getNetworkState(companyId, { ...scope, region, asOf: past }), enabled: !!past && !!companyId, staleTime: 60_000 })
  return <div className="flex flex-col gap-3">
    <p className="text-xs text-muted-foreground">Весь выбранный контур без локальных отборов. Состав парка и паспортные статусы текущие в обоих срезах; история заявок не сравнивается.</p>
    <div className="flex flex-wrap gap-2">{[[1, 'День назад'], [7, 'Неделю назад'], [30, 'Месяц назад']].map(([n, label]) =>
      <Button key={String(n)} size="sm" variant={offset === n ? 'default' : 'outline'} onClick={() => setOffset(Number(n))}>{label}</Button>)}</div>
    {!past ? <p className="text-sm text-muted-foreground">Выберите срез для сравнения.</p> : q.isFetching ? <Loader2 className="size-5 animate-spin" />
      : q.isError ? <div role="alert" className="flex flex-col gap-2 text-sm"><p>Не удалось загрузить прошлый срез.</p><Button variant="outline" onClick={() => void q.refetch()}>Повторить</Button></div>
        : q.data && <><p className="text-xs text-muted-foreground">{дата(now.asOf)} / {дата(q.data.asOf)}</p>
          <dl className="divide-y divide-border/60">{[['Заряжали за 2 суток', now.totals.charging2d, q.data.totals.charging2d],
            ['Без зарядок больше недели', now.totals.silentWeek, q.data.totals.silentWeek], ['Требуют внимания', now.totals.attention, q.data.totals.attention],
            ['Недобор, ₽/мес', now.totals.lossPerMonth, q.data.totals.lossPerMonth]].map(([label, current, previous]) =>
            <div key={label} className="flex flex-col gap-1 py-2 text-sm"><dt>{label}</dt><dd className="text-muted-foreground">в срезе {qty(Number(current))} · было {qty(Number(previous))}
              <span className="ml-2 font-semibold text-foreground">{Number(current) - Number(previous) > 0 ? '+' : ''}{qty(Math.round((Number(current) - Number(previous)) * 100) / 100)}</span></dd></div>)}</dl>
        </>}
  </div>
}

const ПОМОЩЬ = <>
  <p>Состояние сети показывает свой парк, партнёрские станции не включены. Плитки показывают весь выбранный контур и отбирают список.
    По умолчанию открыты требующие внимания: есть расхождение статуса или оценка недобора выручки. Повторное нажатие плитки снимает отбор.</p>
  <p>«Заряжали за 2 суток» и «Без зарядок больше недели» считаются от даты данных, не от текущего часа. «Ни разу» означает отсутствие зарядок в загруженной истории, это не ноль дней.
    Отдельный отбор «Расхождение статуса» показывает числящиеся рабочими станции без зарядок больше недели.</p>
  <p>Недобор — оценка по обычной месячной выручке станций, которые зарабатывали и замолчали с учётом обычного интервала зарядок. Это не начисленный долг и не фактический убыток.</p>
  <p>Конец общего «Периода» задаёт день среза. Сегодня и вчера показывают последние загруженные данные; начало периода не меняет этот отчёт.
    Состав парка и паспортные статусы текущие, история состава не восстановлена. На историческую дату сведения о заявках не восстановлены и показываются как неизвестные.</p>
  <p>«По регионам» группирует станции текущего отбора. Строка региона раскрывает конкретные станции прямо в таблице. В «Сводной» можно добавить состояние, город, давность и работу по заявкам.
    Фильтры столбцов списка действуют на сводную; настройки региональной таблицы отдельные.</p>
  <p>Щелчок по строке или Enter открывает показатели и связанные отчёты. Расшифровка открывается поверх, после закрытия остаётся та же строка.
    Отметки станций позволяют завести несколько заявок; в карточке есть действие для одной станции. Ссылка в «В работе» ведёт в последнюю открытую заявку.</p>
  <p>«Не взяты в работу» считает только требующие внимания станции без открытой заявки. При недоступности Поддержки неизвестное не считается нулём.
    Сравнение прошлых срезов доступно в «Сравнить». Excel выгружает видимые столбцы и все строки отбора в текущем порядке.</p>
</>
