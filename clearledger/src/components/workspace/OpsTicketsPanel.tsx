import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, ChevronRight, Clock, ExternalLink, LifeBuoy, Loader2, Timer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StationLink } from '@/components/common/StationLink'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useStationCard } from '@/contexts/StationCardContext'
import { cn } from '@/lib/utils'
import { matchesSearch } from '@/lib/textUtils'
import { getOpsTickets, type OpsTickets, type TicketRow } from '@/services/opsService'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable,
  TILE_ROW, Tile, ToolPanel, ToolStrip, plural, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { PanelViewTabs } from './PanelViewTabs'
import { ReportPivot } from './ReportPivot'
import { ExportButton } from './analytics/ExportButton'
import { exportRows } from './analytics/exportRows'
import { todayISO } from './analytics/periodPresets'

const С = { номер: 0, тема: 1, статус: 2, станция: 3, марка: 4, регион: 5, создана: 6,
  возраст: 7, срок: 8, закрыта: 9, вид: 10, источник: 11, стадия: 12, важность: 13,
  исполнитель: 14, город: 15, владелец: 16, открыта: 17, окно: 18, часы: 19, номерСтанции: 20 }
const ШАПКА = ['Номер', 'Тема', 'Состояние', 'Станция', 'Марка', 'Регион', 'Создана',
  'Дней с создания', 'Срок', 'Закрыта', 'Вид работ', 'Источник', 'Стадия маршрута', 'Важность',
  'Исполнитель', 'Город', 'Владелец', 'Открыта', 'Включение в срез', 'Время закрытия, ч', '№ станции']
const СКРЫТЫ = [С.вид, С.источник, С.стадия, С.важность, С.исполнитель, С.город,
  С.владелец, С.открыта, С.окно, С.часы, С.номерСтанции]
const СОСТАВ = { order: [], hidden: СКРЫТЫ }
const ШИРИНЫ = { 0: 140, 1: 320, 2: 140, 3: 220, 4: 110, 5: 180, 6: 120, 7: 110, 8: 135, 9: 120 }
const ГРУППЫ = { status: 'Состояние', kind: 'Вид работ', source: 'Источник', stage: 'Стадия маршрута',
  brand: 'Марка станции', region: 'Регион', priority: 'Важность', owner: 'Владелец', city: 'Город',
  station: 'Станция', age: 'Возраст', sla: 'Срок', month: 'Месяц создания', window: 'Включение в срез' }
type Группа = keyof typeof ГРУППЫ
const ПОЛЯ = ['status', 'brand', 'region', 'kind', 'source', 'stage', 'priority'] as const
const ПОКАЗАТЬ = { all: 'Все заявки среза', open: 'Открытые сейчас', breached: 'Срок сорван за окно', stale: 'Открыты больше месяца', closed: 'Закрытые для среднего за окно' }
type Режим = keyof typeof ПОКАЗАТЬ
type Настройки = { days: number; view: string; group: Группа; mode: Режим; search: string; cuts: Partial<Record<Группа, string>> }
const ГРУПП_ХВОСТ = ['Заявок', 'Открыто', 'Срок сорван за окно', 'Открыты > 30 дн', 'В окне', 'Среднее закрытие, ч', 'Все отметки срыва']
const ГРУПП_СКРЫТЫ = [7]
const ГРУПП_ШИРИНЫ = { 0: 260, 1: 100, 2: 100, 3: 145, 4: 140, 5: 100, 6: 150 }
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:ops-tickets'
const СТАТУСЫ: Record<string, string> = { new: 'Новая', open: 'Открыта', in_progress: 'В работе',
  waiting_customer: 'Ждём заказчика', waiting_partner: 'Ждём подрядчика', escalated: 'Эскалация',
  handed_over: 'Передана', accepted: 'Принята', resolved: 'Решена', closed: 'Закрыта', cancelled: 'Отменена',
  ezs_survey: 'Обследование', ezs_hold: 'Удержание', ezs_rejected: 'Отказ' }
const дата = (iso: string | null | undefined) => iso ? new Date(iso).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' }) : ''
const мск = (iso: string | null) => iso ? new Date(iso).toLocaleString('ru-RU', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' }) + ' МСК' : 'время неизвестно'
const статус = (r: TicketRow) => r.statusLabel && r.statusLabel !== r.status ? r.statusLabel : СТАТУСЫ[r.status] || r.statusLabel || r.status
const срывЗаОкно = (r: TicketRow) => r.inWindow && r.slaBreached
const дляСреднего = (r: TicketRow) => r.inWindow && !!r.closedAt && r.status !== 'cancelled'
const часы = (r: TicketRow) => r.closedAt ? (new Date(r.closedAt).getTime() - new Date(r.createdAt).getTime()) / 3_600_000 : null
const среднее = (rows: TicketRow[]): Cell => {
  const values = rows.filter(дляСреднего).map(часы).filter((n): n is number => n !== null && Number.isFinite(n))
  return values.length ? Math.round(values.reduce((n, v) => n + v, 0) / values.length * 10) / 10 : ''
}
function срок(hours: number | null) {
  if (hours === null) return '—'
  if (hours < 24) return qty(Math.round(hours)) + ' ч'
  const days = hours / 24
  return days < 30 ? qty(days < 10 ? Math.round(days * 10) / 10 : Math.round(days)) + ' дн' : qty(Math.round(days / 30)) + ' мес'
}
function значение(r: TicketRow, group: Группа): string {
  if (group === 'status') return статус(r)
  if (group === 'priority') return r.priorityLabel || r.priority || 'Не указана'
  if (group === 'source') return ({ hubex: 'HubEx', web: 'Веб' } as Record<string, string>)[r.source] || r.source || 'Не указан'
  if (group === 'station') return r.station ? [r.stationNumber && '№' + r.stationNumber, r.station].filter(Boolean).join(' · ') : 'Не сопоставлена'
  if (group === 'age') return !r.isOpen ? 'Завершена' : r.ageDays === null ? 'Возраст неизвестен'
    : r.ageDays > 90 ? 'Открыта > 90 дней' : r.ageDays > 30 ? 'Открыта > 30 дней' : r.ageDays > 7 ? 'Открыта > 7 дней' : 'Открыта до недели'
  if (group === 'sla') return r.slaBreached ? r.inWindow ? 'Срок сорван за окно' : 'Отметка срыва вне окна' : 'Без отметки срыва'
  if (group === 'month') return r.createdAt ? new Date(r.createdAt).toLocaleDateString('ru-RU', { month: 'long', year: 'numeric', timeZone: 'Europe/Moscow' }) : 'Месяц неизвестен'
  if (group === 'window') return r.inWindow ? 'Создана за окно' : 'Открыта с прошлого'
  return r[group] || 'Не указано'
}
function строка(r: TicketRow): Cell[] {
  return [r.number, r.title, статус(r), r.station || 'Не сопоставлена', r.brand, r.region,
    дата(r.createdAt), r.ageDays ?? '', значение(r, 'sla'), дата(r.closedAt), r.kind, значение(r, 'source'),
    r.stage || '', значение(r, 'priority'), r.assignee || '', r.city || '', r.owner, r.isOpen ? 'да' : 'нет',
    значение(r, 'window'), часы(r) === null ? '' : Math.round(часы(r)! * 10) / 10, r.stationNumber || '']
}
function итоги(rows: TicketRow[]): Cell[] {
  const cells: Cell[] = ШАПКА.map(() => '')
  cells[0] = 'Итого'; cells[1] = qty(rows.length) + ' заявок'; cells[С.часы] = среднее(rows)
  return cells
}
function группаСтрока(rows: TicketRow[], name = 'Итого'): Cell[] {
  return [name, rows.length, rows.filter((r) => r.isOpen).length, rows.filter(срывЗаОкно).length,
    rows.filter((r) => r.isOpen && r.ageDays !== null && r.ageDays > 30).length,
    rows.filter((r) => r.inWindow).length, среднее(rows), rows.filter((r) => r.slaBreached).length]
}
function поГруппам(rows: TicketRow[], field: Группа) {
  const groups = new Map<string, { key: string; label: string; rows: TicketRow[] }>()
  rows.forEach((r) => {
    const label = значение(r, field), key = field === 'station' ? r.locationId || 'unmapped' : label
    const group = groups.get(key)
    if (group) group.rows.push(r); else groups.set(key, { key, label, rows: [r] })
  })
  return [...groups.values()].map((g) => ({ ...g, cells: группаСтрока(g.rows, g.label) }))
    .sort((a, b) => b.rows.length - a.rows.length || a.label.localeCompare(b.label, 'ru'))
}
function Поле({ id, label, children, className }: { id: string; label: string; children: ReactNode; className: string }) {
  return <div className={cn('flex min-w-0 flex-col gap-1', className)}>
    <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>{children}
  </div>
}

export function OpsTicketsPanel() {
  const { companyId } = useCompany()
  const { regionIds, period } = useFilters()
  const [settings, setSettings] = useState<Настройки>({ days: 90, view: 'list', group: 'status', mode: 'open', search: '', cuts: {} })
  const region = regionIds.length ? regionIds.join('|') : undefined
  const asOf = period.to >= todayISO() ? '' : period.to
  const q = useQuery({ queryKey: ['ops-tickets-report', companyId, settings.days, region ?? '', asOf],
    queryFn: () => getOpsTickets(companyId, { days: settings.days, region, asOf: asOf || undefined, limit: 5000 }),
    enabled: !!companyId, staleTime: 60_000, retry: false })
  if (q.isLoading) return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  if (q.isError || !q.data) return <div role="alert" className="flex flex-col items-center gap-3 p-8 text-sm text-muted-foreground">
    <p>Не удалось получить заявки: Поддержка недоступна или не связана с пространством.</p>
    <Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching}>Повторить загрузку</Button>
  </div>
  return <TicketsReport key={settings.view === 'groups' ? 'groups' : 'tickets'} data={q.data} settings={settings}
    change={(patch) => setSettings((s) => ({ ...s, ...patch }))} companyId={companyId} region={region} />
}

function TicketsReport({ data: d, settings: s, change, companyId, region }: {
  data: OpsTickets; settings: Настройки; change: (patch: Partial<Настройки>) => void; companyId: string; region?: string
}) {
  const экран = useRef<HTMLDivElement>(null)
  const станция = useStationCard()
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [разбор, setРазбор] = useState<'station' | 'status' | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [открыты, setОткрыты] = useState<Set<string>>(new Set())
  const раскрыть = useCallback((key: string) => setОткрыты((was) => {
    const next = new Set(was); if (next.has(key)) next.delete(key); else next.add(key); return next
  }), [])
  const варианты = useMemo(() => Object.fromEntries(ПОЛЯ.map((key) => [key,
    [...new Set(d.rows.map((r) => значение(r, key)))].sort((a, b) => a.localeCompare(b, 'ru'))])), [d.rows])
  const строки = useMemo(() => d.rows.filter((r) => {
    if (s.mode === 'open' && !r.isOpen) return false
    if (s.mode === 'breached' && !срывЗаОкно(r)) return false
    if (s.mode === 'stale' && (!r.isOpen || r.ageDays === null || r.ageDays <= 30)) return false
    if (s.mode === 'closed' && !дляСреднего(r)) return false
    if (Object.entries(s.cuts).some(([key, value]) => значение(r, key as Группа) !== value)) return false
    return !s.search.trim() || matchesSearch(s.search, [r.number, r.title, r.station, r.stationNumber, r.brand, r.region,
      r.city, r.assignee, r.kind, r.stage, значение(r, 'status'), значение(r, 'source')])
  }).sort((a, b) => b.createdAt.localeCompare(a.createdAt) || a.number.localeCompare(b.number, 'ru', { numeric: true })),
  [d.rows, s.mode, s.cuts, s.search])
  const группы = useMemo(() => поГруппам(строки, s.group), [строки, s.group])
  const групповой = s.view === 'groups'
  const head = useMemo(() => групповой ? [ГРУППЫ[s.group], ...ГРУПП_ХВОСТ] : ШАПКА, [групповой, s.group])
  const ячейки = useMemo(() => групповой ? группы.map((g) => g.cells) : строки.map(строка), [групповой, группы, строки])
  const total = useMemo(() => групповой ? группаСтрока(строки) : итоги(строки), [групповой, строки])
  const status = useMemo(() => <span title={[мск(d.dataThrough), d.snapshotNote].filter(Boolean).join(' · ')}
    className="text-xs leading-4 text-muted-foreground">Поддержка прочитана: {мск(d.dataThrough)}</span>, [d.dataThrough, d.snapshotNote])
  const help = useMemo(() => <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
    {ПОМОЩЬ}<p>{d.snapshotNote}</p><p>{d.note}</p>
    <p>Затронуто станций: {qty(d.totals.objects)}; с открытой работой: {qty(d.totals.openObjects)}.</p>
    {d.gaps.length > 0 && <div className="flex flex-col gap-2 border-t pt-3"><p className="font-medium text-foreground">Ограничения данных</p>
      <ul className="list-disc pl-5">{d.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></div>}
  </div>, [d.snapshotNote, d.note, d.gaps, d.totals.objects, d.totals.openObjects])
  const набор = useReportKit({ id: групповой ? 'ops-tickets-groups.v1' : 'ops-tickets.v1', title: 'Заявки', head,
    rows: ячейки, total, hide: групповой ? ГРУПП_СКРЫТЫ : СКРЫТЫ, ready: true, pivot: s.view === 'pivot', help, status })
  const оставлены = useMemo(() => набор.kept.map((i) => строки[i]), [набор.kept, строки])
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i)).filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.table.head])
  const ячейка = useCallback((i: number, c: number) => {
    if (групповой) {
      const g = группы[i], key = s.group + ':' + g?.key
      if (c === 0 && g) return <span className="flex items-center gap-1.5">
        <button type="button" aria-label={(открыты.has(key) ? 'Свернуть заявки ' : 'Раскрыть заявки ') + g.label}
          aria-expanded={открыты.has(key)} onClick={(e) => { e.stopPropagation(); раскрыть(key) }}
          className="grid size-8 shrink-0 place-items-center rounded-md text-primary hover:bg-accent">
          {открыты.has(key) ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button><span className="whitespace-normal font-medium">{g.label}</span></span>
      return undefined
    }
    const r = строки[i]
    if (c === С.номер) return <a href={'/support/customer/tickets/' + r.id} target="_blank" rel="noreferrer"
      title="Открыть заявку в Поддержке в новой вкладке" className="text-primary hover:underline">{r.number}</a>
    if (c === С.тема) return <span className="whitespace-normal break-words">{r.title}</span>
    if (c === С.станция) return r.locationId && r.station ? <StationLink station={r.locationId}>{[r.stationNumber && '№' + r.stationNumber, r.station].filter(Boolean).join(' · ')}</StationLink>
      : <span className="text-muted-foreground">не сопоставлена</span>
    if (c === С.срок) return <span className={cn('whitespace-normal', срывЗаОкно(r) && 'font-medium text-destructive')}>{значение(r, 'sla')}</span>
    return undefined
  }, [групповой, группы, s.group, открыты, раскрыть, строки])
  const фильтры = [s.mode !== 'all' && ПОКАЗАТЬ[s.mode], ...Object.entries(s.cuts).map(([key, value]) => ГРУППЫ[key as Группа] + ': ' + value),
    s.search.trim() && 'поиск «' + s.search.trim() + '»'].filter(Boolean) as string[]
  const отборов = фильтры.length + Object.keys(набор.filters).length
  const сброс = () => { change({ mode: 'all', search: '', cuts: {} }); набор.setFilters({}) }
  const выбрать = (mode: Режим) => { change({ mode: s.mode === mode ? 'all' : mode }); набор.setFilters({}) }
  const выбранная = карточка ? строки[карточка.order[карточка.pos]] : null
  const расшифровка = выбранная && разбор ? d.rows.filter((r) => разбор === 'station' ? r.locationId === выбранная.locationId : значение(r, 'status') === значение(выбранная, 'status')) : []
  const подпись = d.days + ' дней по ' + дата(d.asOf) + ' · открытые — текущие'
  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className={cn(TILE_ROW, 'xl:grid-cols-5')}>
      <Tile icon={LifeBuoy} label="Заявок в срезе" value={qty(d.totals.total)} hint={'за окно ' + qty(d.totals.inWindow) + ' · с прошлого ' + qty(d.totals.openBeforeWindow)} active={s.mode === 'all'} onClick={() => выбрать('all')} />
      <Tile icon={Clock} label="Открыто сейчас" value={qty(d.totals.open)} hint={'срочных ' + qty(d.totals.urgentOpen) + ' · станций ' + qty(d.totals.openObjects)} active={s.mode === 'open'} onClick={() => выбрать('open')} />
      <Tile icon={AlertTriangle} label="Срок сорван за окно" value={qty(d.totals.breached)} hint="по заявкам, созданным за окно" active={s.mode === 'breached'} onClick={() => выбрать('breached')} />
      <Tile icon={Timer} label="Открыты больше месяца" value={qty(d.totals.staleOpen)} hint="созданы более 30 дней назад" active={s.mode === 'stale'} onClick={() => выбрать('stale')} />
      <Tile icon={Timer} label="Закрывают в среднем" value={срок(d.totals.avgHours)} hint="закрытые за окно · без отменённых" active={s.mode === 'closed'} onClick={() => выбрать('closed')} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      {фильтрыОткрыты && <div className="flex flex-wrap items-end gap-3">
        <Поле id="tickets-window" label="Окно истории" className="w-36"><Select value={String(s.days)} onValueChange={(v) => change({ days: Number(v) })}>
          <SelectTrigger id="tickets-window" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{[30, 90, 365].map((n) => <SelectItem key={n} value={String(n)}>{n} дней</SelectItem>)}</SelectContent>
        </Select></Поле>
        <Поле id="tickets-show" label="Показать" className="w-60"><Select value={s.mode} onValueChange={(mode) => change({ mode: mode as Режим })}>
          <SelectTrigger id="tickets-show" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(ПОКАЗАТЬ).map(([key, label]) => <SelectItem key={key} value={key}>{label}</SelectItem>)}</SelectContent>
        </Select></Поле>
        {ПОЛЯ.map((key) => <Поле key={key} id={'tickets-' + key} label={ГРУППЫ[key]} className={key === 'region' ? 'w-52' : 'w-44'}>
          <Select value={s.cuts[key] || 'all'} onValueChange={(v) => { const cuts = { ...s.cuts }; if (v === 'all') delete cuts[key]; else cuts[key] = v; change({ cuts }) }}>
            <SelectTrigger id={'tickets-' + key} className="h-9 w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">Все значения</SelectItem>{(варианты[key] || []).map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent>
          </Select>
        </Поле>)}
        <Поле id="tickets-search" label="Найти заявку" className="w-64"><Input id="tickets-search" value={s.search} onChange={(e) => change({ search: e.target.value })} placeholder="Номер, тема, станция…" className="h-9" /></Поле>
        <Поле id="tickets-page" label="Строк на странице" className="w-32"><PageSizeField bare id="tickets-page" /></Поле>
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
          <PanelViewTabs label={null} value={s.view} onChange={(view) => change({ view })} tabs={[{ k: 'list', label: 'Список' }, { k: 'groups', label: 'По группам' }, { k: 'pivot', label: 'Сводная' }]} />
          <span className="text-xs text-muted-foreground">{групповой ? 'групп' : 'заявок'}: {qty(набор.kept.length)}</span>
          {d.gaps.length > 0 && <span title={d.gaps.join('\n')} className="text-xs text-muted-foreground">Данные: {qty(d.gaps.length)} {plural(d.gaps.length, 'замечание', 'замечания', 'замечаний')} в «Инфо»</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a href="/support/" target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-primary hover:bg-accent">Поддержка <ExternalLink className="size-3.5" /></a>
          <ExportButton title="Заявки" subtitle={подпись} getEl={() => экран.current} />
          <Button size="sm" variant="outline" onClick={сброс} disabled={!отборов}>Сбросить фильтры</Button>
        </div>
      </div>
      {групповой && <div className="flex flex-wrap items-center gap-3"><Поле id="tickets-group" label="Группировать по" className="w-56">
        <Select value={s.group} onValueChange={(group) => change({ group: group as Группа })}><SelectTrigger id="tickets-group" className="h-9 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(ГРУППЫ).map(([key, label]) => <SelectItem key={key} value={key}>{label}</SelectItem>)}</SelectContent></Select>
      </Поле><span className="text-xs text-muted-foreground">{['brand', 'region', 'owner', 'city', 'station'].includes(s.group) ? 'По реестру объектов пространства' : 'По данным Поддержки'} · текущий отбор</span></div>}
      <ToolStrip />
      {s.view === 'pivot' ? <ReportPivot fields={[...Object.keys(ГРУППЫ), 'tickets', 'open', 'closed', 'breached', 'allBreaches']}
        columns={[...Object.values(ГРУППЫ), 'Заявок', 'Открыто', 'Завершено', 'Срыв за окно', 'Все отметки срыва']}
        rows={оставлены.map((r) => ({ ...Object.fromEntries(Object.keys(ГРУППЫ).map((key) => [key, значение(r, key as Группа)])),
          tickets: 1, open: r.isOpen ? 1 : 0, closed: r.isOpen ? 0 : 1, breached: срывЗаОкно(r) ? 1 : 0, allBreaches: r.slaBreached ? 1 : 0 }))} />
        : <SheetTable {...набор.table} caption={групповой ? 'Заявки · ' + ГРУППЫ[s.group] : 'Заявки по сети'} lines={[подпись, ...фильтры]}
          defaultWidths={групповой ? ГРУПП_ШИРИНЫ : ШИРИНЫ} render={ячейка} onView={setПорядок}
          rowTitle={(i) => групповой ? группы[i]?.label || '' : строки[i]?.number || ''}
          onRow={(order, pos) => групповой ? раскрыть(s.group + ':' + группы[order[pos]].key) : setКарточка({ order, pos })}
          expand={групповой ? (i) => открыты.has(s.group + ':' + группы[i]?.key) ? <TicketSubset key={s.group + ':' + группы[i].key} rows={группы[i].rows} caption={'Заявки · ' + группы[i].label} lines={[подпись]} /> : null : undefined}
          derive={(t) => { const kept = групповой ? набор.kept.flatMap((i) => группы[i].rows) : оставлены
            const values = групповой ? группаСтрока(kept) : итоги(kept), fixed = t.map((v, i) => i < values.length ? values[i] : v)
            return набор.table.derive ? набор.table.derive(fixed) : fixed }}
          empty="По этому отбору заявки не найдены. Измените поиск или сбросьте фильтры."
          tableAttrs={exportRows(групповой ? ГРУППЫ[s.group] : 'Заявки', видимые.map((c) => набор.sheet.head[c]), порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />}
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Номер, тема, станция или число" formulaExample="Например, Доля открытых"
      compare={<TicketsCompare companyId={companyId} region={region} now={d} />} /></ToolPanel>
    <RowCard report="Заявки" head={набор.sheet.head} title={выбранная ? выбранная.number + ' · ' + выбранная.title : undefined}
      row={карточка && !станция.открыта ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
      at={карточка?.pos ?? 0} of={карточка?.order.length ?? 0}
      onStep={(dir) => { setРазбор(null); setКарточка((v) => v ? { ...v, pos: Math.max(0, Math.min(v.pos + dir, v.order.length - 1)) } : v) }}
      onClose={() => { setКарточка(null); setРазбор(null) }} extra={выбранная && <div className="flex flex-col gap-3">
        <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
          {выбранная.locationId && выбранная.station && <RelatedLink label="Заявки этой станции" hint={выбранная.station} onClick={() => setРазбор('station')} />}
          <RelatedLink label="С таким же состоянием" hint={статус(выбранная)} onClick={() => setРазбор('status')} />
        </div>
        {выбранная.locationId && выбранная.station && <div className="text-sm"><StationLink station={выбранная.locationId}>Открыть карточку станции</StationLink></div>}
        <div className="flex flex-col gap-2 border-t pt-3"><p className="text-xs font-semibold text-muted-foreground">Действия</p>
          <a href={'/support/customer/tickets/' + выбранная.id} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Открыть заявку в Поддержке <ExternalLink className="size-4" /></a></div>
      </div>} />
    <RelatedReport open={!!разбор && !!выбранная && !станция.открыта} title={разбор === 'station' ? 'Заявки этой станции' : 'С таким же состоянием'}
      subtitle={подпись} head={ШАПКА} rows={расшифровка.map(строка)} onClose={() => setРазбор(null)} note="Все заявки того же среза; локальные отборы основной таблицы не применяются.">
      <TicketSubset rows={расшифровка} caption={разбор === 'station' ? выбранная?.station || '' : выбранная ? статус(выбранная) : ''} lines={[подпись]} />
    </RelatedReport>
  </div>
}

function TicketSubset({ rows, caption, lines }: { rows: TicketRow[]; caption: string; lines: string[] }) {
  const [order, setOrder] = useState<number[]>([])
  const cells = useMemo(() => rows.map(строка), [rows])
  return <SheetTable head={ШАПКА} rows={cells} caption={caption} lines={lines} cols={СОСТАВ} defaultWidths={ШИРИНЫ} onView={setOrder}
    render={(i, c) => c === С.номер ? <a href={'/support/customer/tickets/' + rows[i].id} target="_blank" rel="noreferrer" className="text-primary hover:underline">{rows[i].number}</a>
      : c === С.станция && rows[i].locationId && rows[i].station ? <StationLink station={rows[i].locationId}>{значение(rows[i], 'station')}</StationLink> : undefined}
    tableAttrs={exportRows(caption, ШАПКА.filter((_, i) => !СКРЫТЫ.includes(i)), order.map((i) => cells[i].filter((_, c) => !СКРЫТЫ.includes(c))))} />
}

function TicketsCompare({ companyId, region, now }: { companyId: string; region?: string; now: OpsTickets }) {
  const [offset, setOffset] = useState<number | null>(null)
  const date = new Date(now.asOf.slice(0, 10) + 'T12:00:00Z'); date.setUTCDate(date.getUTCDate() - (offset ?? 0))
  const past = offset ? date.toISOString().slice(0, 10) : ''
  const q = useQuery({ queryKey: ['ops-tickets-compare', companyId, region ?? '', now.days, past],
    queryFn: () => getOpsTickets(companyId, { region, days: now.days, asOf: past, limit: 5000 }), enabled: !!past && !!companyId, staleTime: 60_000, retry: false })
  return <div className="flex flex-col gap-3"><p className="text-xs text-muted-foreground">Сравнивается история за одинаковые окна по всему контуру, без локальных отборов.
    Статусы заявок текущие в обоих окнах, история статусов не восстановлена. Это не число открытых заявок в прошлом.</p>
    <div className="flex flex-wrap gap-2">{[[7, 'Неделю назад'], [now.days, 'Предыдущее окно']].map(([n, label]) =>
      <Button key={String(n)} size="sm" variant={offset === n ? 'default' : 'outline'} onClick={() => setOffset(Number(n))}>{label}</Button>)}</div>
    {!past ? <p className="text-sm text-muted-foreground">Выберите окно для сравнения.</p> : q.isFetching ? <Loader2 className="size-5 animate-spin" />
      : q.isError ? <div role="alert" className="flex flex-col gap-2 text-sm"><p>Не удалось загрузить прошлое окно.</p><Button variant="outline" onClick={() => void q.refetch()}>Повторить</Button></div>
        : q.data && <><p className="text-xs text-muted-foreground">{now.days} дней по {дата(now.asOf)} / {дата(q.data.asOf)}</p>
          <dl className="divide-y divide-border/60">{[['Создано за окно', now.totals.inWindow, q.data.totals.inWindow],
            ['Срок сорван за окно', now.totals.breached, q.data.totals.breached], ['Среднее закрытие, ч', now.totals.avgHours, q.data.totals.avgHours]].map(([label, current, previous]) =>
            <div key={label} className="flex flex-col gap-1 py-2 text-sm"><dt>{label}</dt><dd className="text-muted-foreground">в окне {current === null ? '—' : qty(Number(current))} · было {previous === null ? '—' : qty(Number(previous))}</dd></div>)}</dl>
        </>}
  </div>
}

const ПОМОЩЬ = <>
  <p>В срезе объединены заявки, созданные за окно, и все открытые, включая заведённые раньше. Смена окна не прячет старую открытую работу.
    «Открыто сейчас» определяется признаком Поддержки, а не наличием даты закрытия.</p>
  <p>«Срок сорван за окно» отбирает только заявки, созданные за выбранное окно, с отметкой срыва. Все отметки срыва, включая старые,
    доступны в столбце «Срок» и отдельной мере сводной. «Открыты больше месяца» — открытые заявки старше 30 дней.</p>
  <p>Среднее закрытие считается по заявкам, созданным за окно и имеющим дату закрытия, без отменённых. Плитка открывает именно этот состав.
    В группах средние вычисляются из времени заявок, не складываются и не усредняются без весов.</p>
  <p>Конец общего «Периода» задаёт конец окна истории. Само окно 30, 90 или 365 дней выбирается в фильтрах; начало общего периода его не меняет.
    Статусы заявок и состав парка текущие, история их состояний на дату не восстановлена.</p>
  <p>Время в общей строке показывает чтение Поддержки. Оно не подтверждает свежесть внешней выгрузки. Ограничения полей и связей с реестром приведены ниже.</p>
  <p>«По группам» содержит все значения выбранного разреза без ограничения восемью строками. Строка раскрывает конкретные заявки.
    Состояние, вид работ, стадия и источник приходят из Поддержки; марка, регион, город, владелец и станция — из реестра объектов пространства.</p>
  <p>Щелчок по строке или Enter открывает показатели и связанные отчёты. Расшифровки открываются поверх с возвратом в ту же карточку.
    Номер открывает заявку в Поддержке в новой вкладке, станция — карточку оборудования поверх отчёта.</p>
  <p>Доступны все загруженные заявки с постраничным просмотром, сортировкой, поиском, фильтрами столбцов и экспортом.
    Сводная использует тот же отбор списка. Настройки и формулы у списка и групп раздельные. Excel получает все строки отбора и видимые столбцы в текущем порядке.</p>
</>
