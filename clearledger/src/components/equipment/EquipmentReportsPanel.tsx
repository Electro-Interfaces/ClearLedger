/**
 * «Отчёты» складского учёта оборудования: остатки на дату, оборотно-сальдовая,
 * оборотная ведомость, что числится за контрагентом, единицы в ремонте.
 *
 * Всё считается сервером из журнала движений, поэтому отвечает и на вопросы
 * задним числом («что лежало у хранителя на 30 сентября»). Единицы без истории
 * движений показываются по текущему состоянию и помечены — их на любую дату
 * видно там, где они числятся сегодня.
 *
 * Раздел ведёт складские предметы: станция, введённая в эксплуатацию, со
 * складского учёта выбыла и в остатки не входит — она показана одним числом.
 *
 * «Оборотно-сальдовая» — та же ведомость, что строит 1С:Бухгалтерия по счёту с
 * субконто «Склады» и «Номенклатура»: сальдо и обороты в количестве и сумме по
 * счетам 07, 08.03, 01.01, 10.xx. По ней сверяются с бухгалтерией; сверенный
 * период закрывается — документы той датой больше не проводятся и не отменяются.
 *
 * ТАБЛИЦА С ИНСТРУМЕНТАМИ (report-kit, 17.10.2026) — как «Мониторинг → На
 * сегодня» (Екатерина): сверху только плитки, они же отборы и выбор таблицы
 * отчёта; фильтры свёрнуты в строку; меню столбца, Σ, сводная, карточка строки
 * с расшифровками окном поверх, инструменты в правой рельсе. Дата и период
 * отчёта — общий «Период» рабочего стола, а не свои поля: «на дату» — его конец.
 */
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, Boxes, Building2, ChevronDown, FileWarning, History, Layers, Loader2, Lock, Package, PackageX, Users, Warehouse, Wrench,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { daysAgoISO, isoLocal } from '@/components/workspace/analytics/periodPresets'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable, TILE_ROW, Tile, ToolPanel, ToolStrip, plural, qty, useReportKit,
  type Cell,
} from '@/components/report-kit'
import { useFilters } from '@/contexts/FilterContext'
import { loadLocations } from '@/services/locationService'
import {
  getEquipmentSettings, getHoldersReport, getOsvReport, getRepairsReport, getStockReport, getTurnoverReport, listMovements, setClosedPeriod,
  type EquipmentMovement, type HolderGroup, type OsvCells, type ReportUnitRow, type StockReport, type TurnoverFigures,
} from '@/services/equipmentService'
import { ApiError } from '@/services/apiClient'
import { formatDate } from '@/lib/formatDate'
import { cn } from '@/lib/utils'
import { eqName } from './equipmentDocPrint'

const REPORTS = [
  { k: 'stock', label: 'Остатки на дату' },
  { k: 'osv', label: 'Оборотно-сальдовая' },
  { k: 'turnover', label: 'Оборотная ведомость' },
  { k: 'holders', label: 'За контрагентом' },
  { k: 'repairs', label: 'В ремонте' },
] as const

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const day = (iso: string | null | undefined) => (iso ? formatDate(iso) : '')
const sum = <T,>(rows: T[], f: (r: T) => number) => rows.reduce((n, r) => n + f(r), 0)
const round2 = (n: number) => Math.round(n * 100) / 100
const byOp = (ops: TurnoverFigures['incomeByOp']) => ops.map((o) => `${o.label} ${nf.format(o.qty)}`).join(', ')
/** Склад — запись справочника мест; «склад не указан» и прочие места без записи движений не имеют. */
const isLocation = (id: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(id)
const AMBER = 'text-amber-600 dark:text-amber-400'
const FILTERS_OPEN = 'report-kit.v1:filters-open:equipment-reports'

/**
 * Дата и период отчётов — общий «Период» рабочего стола (как «На сегодня»).
 * Конец по вчера или позже — это «сейчас»: документы раздела вводят днём, и
 * остаток «на вчера» не показал бы сегодняшнюю приёмку.
 */
type Range = { date: string; from: string }
function useRange(): Range {
  const { period } = useFilters()
  const date = period.to >= daysAgoISO(1) ? isoLocal(new Date()) : period.to
  return { date, from: period.from <= date ? period.from : date }
}

// ─── расшифровки строки ─────────────────────────────────────────────────────

/** Отчёт-расшифровка в карточке строки: готовые строки или движения из журнала. */
type Drill = { label: string; hint?: string } & (
  | { head: string[]; rows: Cell[][] }
  | { unitId: string }
  | { locationId: string; dateFrom: string; dateTo: string }
)

const MOVE_HEAD = ['Дата', 'Операция', 'Единица', 'Откуда', 'Куда', 'Состояние после', 'Документ', 'Контрагент', 'Основание']
const moveCells = (m: EquipmentMovement): Cell[] => [
  day(m.occurredOn), m.opLabel, [m.unit?.serialNumber, eqName(m.unit?.vendor, m.unit?.model)].filter(Boolean).join(' · '),
  m.fromLocation?.name ?? '', m.toLocation?.name ?? '', m.toStateLabel ?? '',
  m.documentNumber ?? m.supplyNumber ?? '', m.counterparty ?? '', m.basis ?? '',
]

function DrillWindow({ companyId, drill, subtitle, onClose }: {
  companyId: string; drill: Drill | null; subtitle: string; onClose: () => void
}) {
  const unitId = drill && 'unitId' in drill ? drill.unitId : undefined
  const place = drill && 'locationId' in drill ? drill : undefined
  const q = useQuery({
    queryKey: ['eq-drill-moves', companyId, unitId ?? '', place?.locationId ?? '', place?.dateFrom ?? '', place?.dateTo ?? ''],
    queryFn: () => listMovements({
      companyId, unitId, locationId: place?.locationId, dateFrom: place?.dateFrom, dateTo: place?.dateTo, pageSize: 1000,
    }),
    enabled: !!unitId || !!place,
  })
  const local = drill && 'rows' in drill ? drill : undefined
  const items = q.data?.items ?? []
  return (
    <RelatedReport open={!!drill} title={drill?.label ?? ''} subtitle={subtitle}
      head={local?.head ?? MOVE_HEAD} rows={local?.rows ?? items.map(moveCells)}
      loading={!local && q.isLoading} error={!local && q.isError}
      note={!local && q.data && q.data.total > items.length ? `Показаны первые ${nf.format(items.length)} из ${nf.format(q.data.total)}` : undefined}
      onClose={onClose} />
  )
}

// ─── таблица отчёта на наборе report-kit ────────────────────────────────────

/** Таблица отчёта. Набор — один на экран, поэтому у отчёта таблица одна, а плитки выбирают, какая. */
type Sheet = {
  /** Ключ настроек столбцов (`report-kit.v1:cols:<id>`): смена смысла столбцов — новый id. */
  id: string
  title: string
  head: string[]
  rows: Cell[][]
  total?: Cell[]
  hide?: number[]
  groupBy?: Record<number, string>
  /** Не идут в сводную: у каждой строки своё значение (серийный, номер). */
  noPivot?: number[]
  render?: (row: number, col: number) => ReactNode | undefined
  rowClass?: (row: number) => string | undefined
  rowTitle: (row: number) => string
  drills?: (row: number) => Drill[]
  empty: string
}

/** Поле фильтра своей ширины, как на «На сегодня». */
function Поле({ label, w, children }: { label: string; w: string; children: ReactNode }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', w)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}

function Pick({ label, all, value, onChange, opts, w = 'w-60' }: {
  label: string; all: string; value: string; onChange: (v: string) => void; opts: { id: string; name: string }[]; w?: string
}) {
  return (
    <Поле label={label} w={w}>
      <Select value={value || 'all'} onValueChange={(v) => onChange(v === 'all' ? '' : v)}>
        <SelectTrigger className="h-9 w-full text-sm"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{all}</SelectItem>
          {opts.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
        </SelectContent>
      </Select>
    </Поле>
  )
}

function KitSheet({ companyId, sheet, lines, fields, chosen, onReset, help, compare, searchHint, formulaExample, root }: {
  companyId: string; sheet: Sheet; lines: string[]; fields?: ReactNode; chosen: number; onReset: () => void
  help: ReactNode; compare: ReactNode; searchHint: string; formulaExample: string; root: () => HTMLElement | null
}) {
  const [view, setView] = useState('list')
  const [first, setFirst] = useState<number | null>(null)
  const [card, setCard] = useState<{ order: number[]; pos: number } | null>(null)
  const [order, setOrder] = useState<number[]>([])
  const [drill, setDrill] = useState<Drill | null>(null)
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(FILTERS_OPEN) === '1' } catch { return false }
  })
  const toggle = () => {
    setOpen(!open)
    try { localStorage.setItem(FILTERS_OPEN, open ? '0' : '1') } catch { /* хранилище недоступно */ }
  }
  const kit = useReportKit({
    id: sheet.id, title: sheet.title, head: sheet.head, rows: sheet.rows, total: sheet.total, hide: sheet.hide,
    ready: true, pivot: view === 'pivot', help,
  })
  const head = kit.sheet.head
  const shown = useMemo(() => {
    const cols = kit.table.cols
    const all = cols.order.length === head.length ? cols.order : head.map((_, i) => i)
    return all.filter((i) => !cols.hidden.includes(i))
  }, [kit.table.cols, head])
  const active = chosen + Object.keys(kit.filters).length
  const cut = kit.kept.length !== sheet.rows.length
  // Сводная — от всех столбцов таблицы, включая свои столбцы-формулы; первым —
  // уровень, выбранный значком в шапке.
  const pivotCols = head.map((_, c) => c).filter((c) => !(sheet.noPivot ?? []).includes(c))
  const pivotFields = [...new Set([...(first !== null && pivotCols.includes(first) ? [first] : []), ...pivotCols])].map((c) => `c${c}`)
  const row = card ? card.order[card.pos] : null
  const drills = row !== null && sheet.drills ? sheet.drills(row) : []
  const title = row !== null ? sheet.rowTitle(row) : ''
  return (
    <>
      <Card className="py-0">
        <CardContent className="space-y-3 p-3">
          {open && (
            <div className="flex flex-wrap items-end gap-3">
              {fields}
              <Поле label="Строк на странице" w="w-32"><PageSizeField bare /></Поле>
            </div>
          )}
          <div className={cn('flex flex-wrap items-center justify-between gap-2', open && 'border-t border-border/60 pt-3')}>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <button type="button" onClick={toggle} aria-expanded={open}
                className="-ml-1 inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm font-semibold text-primary hover:bg-accent">
                <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
                {open ? 'Свернуть фильтры' : 'Фильтры'}
                {!open && active > 0 && (
                  <span className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground">{active}</span>
                )}
              </button>
              <PanelViewTabs value={view} onChange={setView} label={null} tabs={[
                { k: 'list', label: 'Список' },
                { k: 'pivot', label: 'Сводная' },
              ]} />
              <span className="text-xs text-muted-foreground">строк: {nf.format(kit.kept.length)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ExportButton title={`Оборудование · ${sheet.title}`} subtitle={lines[0]} getEl={root} />
              <Button size="sm" variant="outline" className="h-7 text-xs" disabled={!active}
                onClick={() => { onReset(); kit.setFilters({}) }}>
                Сброс
              </Button>
            </div>
          </div>

          {/* Телефон и планшет: рельсы нет, те же кнопки — полосой над таблицей. */}
          <ToolStrip />

          {view === 'pivot' ? (
            <div className="space-y-2">
              {cut && (
                <div className="rounded-md bg-primary/5 px-3 py-1.5 text-xs text-muted-foreground">
                  Сводная собрана по {nf.format(kit.kept.length)} из {nf.format(sheet.rows.length)} строк: фильтр по{' '}
                  {Object.keys(kit.filters).map((k) => `«${head[Number(k)]}»`).join(', ')}.{' '}
                  <button type="button" className="font-semibold text-primary hover:underline" onClick={() => kit.setFilters({})}>Снять</button>
                </div>
              )}
              <ReportPivot key={pivotFields[0]} fields={pivotFields}
                columns={pivotFields.map((f) => head[Number(f.slice(1))])}
                rows={kit.kept.map((i) => Object.fromEntries(pivotCols.map((c) => [`c${c}`, kit.sheet.rows[i][c]])))} />
            </div>
          ) : (
            <SheetTable
              {...kit.table}
              caption={sheet.title}
              lines={lines}
              groupBy={sheet.groupBy}
              onGroup={(c) => { setFirst(c); setView('pivot') }}
              onRow={(o, pos) => setCard({ order: o, pos })}
              onView={setOrder}
              render={sheet.render}
              rowClass={sheet.rowClass}
              rowTitle={sheet.rowTitle}
              empty={sheet.empty}
              // Excel получает то, что на экране: видимые столбцы в порядке человека,
              // строки в порядке таблицы с фильтрами.
              tableAttrs={exportRows(sheet.title, shown.map((c) => head[c]),
                order.map((i) => shown.map((c) => kit.sheet.rows[i]?.[c] ?? '')))}
            />
          )}
        </CardContent>
      </Card>

      <ToolPanel>
        <ReportTools {...kit.tools} searchHint={searchHint} formulaExample={formulaExample} compare={compare} />
      </ToolPanel>

      <RowCard
        report={sheet.title}
        head={head}
        row={row !== null ? kit.sheet.rows[row] ?? null : null}
        title={title}
        at={card?.pos ?? 0}
        of={card?.order.length ?? 0}
        onStep={(dir) => setCard((k) => (k ? { ...k, pos: Math.min(Math.max(k.pos + dir, 0), k.order.length - 1) } : k))}
        onClose={() => { setCard(null); setDrill(null) }}
        extra={drills.length ? (
          <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
            {drills.map((d) => <RelatedLink key={d.label} label={d.label} hint={d.hint} onClick={() => setDrill(d)} />)}
          </div>
        ) : undefined}
      />
      <DrillWindow companyId={companyId} drill={card ? drill : null} subtitle={title} onClose={() => setDrill(null)} />
    </>
  )
}

/** Загрузка и ошибка отчёта: ошибка — это ошибка, а не пустой список. */
function Pending({ q }: { q: { isError: boolean; error: unknown } }) {
  return q.isError
    ? <p role="alert" className="text-sm text-destructive">Отчёт не загрузился{q.error instanceof Error ? `: ${q.error.message}` : ''}</p>
    : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}

type ViewProps = { companyId: string; range: Range; warehouses: { id: string; name: string }[]; root: () => HTMLElement | null }
const nameOf = (opts: { id: string; name: string }[], id: string) => opts.find((o) => o.id === id)?.name ?? id

// ─── единицы ────────────────────────────────────────────────────────────────

const UNIT_HEAD = ['Серийный №', 'Инв. №', 'Оборудование', 'Состояние', 'Где', 'С даты', 'Документ', 'Контрагент', 'Договор', 'История движений']
const unitCells = (u: ReportUnitRow): Cell[] => [
  u.serialNumber ?? '', u.inventoryNumber ?? '', eqName(u.vendor, u.model), u.stateLabel, u.place, day(u.since),
  u.docNumber ?? u.basis ?? '', u.counterpartyName ?? '', u.contractLabel ?? '', u.noHistory ? 'нет' : 'есть',
]
const unitTitle = (u: { serialNumber: string | null; vendor: string | null; model: string | null }) =>
  [u.serialNumber, eqName(u.vendor, u.model)].filter(Boolean).join(' · ') || 'Единица без номера'
const unitHistory = (id: string): Drill => ({ label: 'История движений единицы', hint: 'все документы по ней — от прихода до сегодня', unitId: id })
const isGone = (u: ReportUnitRow) => u.placeKind === 'vendor' || u.placeKind === 'written_off'
const SPARE_HEAD = ['Склад', 'Номенклатура', 'Артикул', 'Остаток', 'Ед.']
const spareCells = (s: StockReport['spares'][number]): Cell[] => [s.location, s.name, s.article ?? '', s.qty, s.unitLabel]

// ─── остатки на дату ────────────────────────────────────────────────────────

/** Состояния единиц на учёте — постоянным набором столбцов: настройки вида опираются на номер столбца. */
const STATE_COLS = [
  ['in_stock_new', 'На складе (новая)'], ['in_stock_used', 'На складе (б/у)'], ['reserved', 'Резерв'],
  ['in_installation', 'В монтаже'], ['in_repair', 'В ремонте'],
] as const
const PLACE_HEAD = ['Где', 'Раздел', ...STATE_COLS.map(([, l]) => l), 'Всего', 'Без истории движений']
const SECTION = { stock: 'на складе', out: 'вне склада', gone: 'выбыло' } as const
type StockTable = 'places' | 'units' | 'repair' | 'nohist' | 'gone' | 'spares'
const STOCK_UNITS: Record<Exclude<StockTable, 'places' | 'spares'>, { title: string; keep: (u: ReportUnitRow) => boolean }> = {
  units: { title: 'Единицы на учёте', keep: (u) => !isGone(u) },
  repair: { title: 'Единицы в ремонте', keep: (u) => u.placeKind === 'repair' },
  nohist: { title: 'Единицы без истории движений', keep: (u) => !isGone(u) && u.noHistory },
  gone: { title: 'Списано и возвращено производителю', keep: isGone },
}

function stockSheet(d: StockReport, table: StockTable, from: string): Sheet {
  if (table === 'places') {
    const groups = d.groups.filter((g) => g.section !== 'gone')
    const byState = (k: string) => sum(groups, (g) => g.byState[k] ?? 0)
    return {
      id: 'eq-stock-places.v1', title: 'Остатки по местам', head: PLACE_HEAD,
      rows: groups.map((g) => [g.name, SECTION[g.section], ...STATE_COLS.map(([k]) => g.byState[k] ?? 0), g.total, g.noHistory]),
      total: ['Итого', `${qty(groups.length)} мест`, ...STATE_COLS.map(([k]) => byState(k)), d.total, d.noHistory],
      // Резерв и монтаж бывают редко: пустые столбцы скрыты, включаются в «Столбцах».
      hide: STATE_COLS.flatMap(([k], i) => (byState(k) ? [] : [i + 2])),
      groupBy: { 1: 'Раздел' }, noPivot: [0],
      rowTitle: (i) => groups[i]?.name ?? '',
      empty: 'На эту дату единиц по отбору нет',
      drills: (i) => {
        const g = groups[i]
        if (!g) return []
        const spares = d.spares.filter((s) => s.locationId === g.key)
        return [
          { label: 'Единицы на месте', hint: 'откуда числа строки: каждая единица с документом', head: UNIT_HEAD,
            rows: d.units.filter((u) => u.placeKey === g.key).map(unitCells) },
          ...(spares.length ? [{ label: 'ЗИП на складе', hint: 'остаток запчастей на дату', head: SPARE_HEAD, rows: spares.map(spareCells) }] : []),
          ...(isLocation(g.key) ? [{ label: 'Движения склада за период', hint: `с ${day(from)} по ${day(d.date)}`,
            locationId: g.key, dateFrom: from, dateTo: d.date }] : []),
        ]
      },
    }
  }
  if (table === 'spares') {
    return {
      id: 'eq-stock-spares.v1', title: 'ЗИП на складах', head: SPARE_HEAD, rows: d.spares.map(spareCells),
      groupBy: { 0: 'Склад', 1: 'Номенклатура' }, rowTitle: (i) => d.spares[i]?.name ?? '', empty: 'Остатков ЗИП на эту дату нет',
    }
  }
  const { title, keep } = STOCK_UNITS[table]
  const units = d.units.filter(keep)
  return {
    id: 'eq-stock-units.v1', title, head: UNIT_HEAD, rows: units.map(unitCells),
    total: ['Итого', '', `${qty(units.length)} ед.`, '', '', '', '', '', '', ''],
    hide: [8], groupBy: { 2: 'Оборудование', 3: 'Состояние', 4: 'Где', 7: 'Контрагент' }, noPivot: [0, 1],
    rowTitle: (i) => (units[i] ? unitTitle(units[i]) : ''),
    empty: 'Таких единиц на эту дату нет',
    drills: (i) => (units[i] ? [unitHistory(units[i].id)] : []),
  }
}

function StockView({ companyId, range, warehouses, root }: ViewProps) {
  const [table, setTable] = useState<StockTable>('places')
  const [locationId, setLocationId] = useState('')
  const [counterpartyId, setCounterpartyId] = useState('')
  const q = useQuery({
    queryKey: ['eq-report-stock', companyId, range.date, locationId, counterpartyId],
    queryFn: () => getStockReport({ companyId, date: range.date, locationId: locationId || undefined, counterpartyId: counterpartyId || undefined }),
    placeholderData: keepPreviousData,
  })
  const d = q.data
  const sheet = useMemo(() => (d ? stockSheet(d, table, range.from) : null), [d, table, range.from])
  if (!d || !sheet) return <Pending q={q} />
  const section = (s: string) => sum(d.groups.filter((g) => g.section === s), (g) => g.total)
  const repair = d.units.filter((u) => u.placeKind === 'repair').length
  const gone = section('gone')
  const pick = (t: StockTable) => setTable(table === t ? 'places' : t)
  const state = (k: string) => sum(d.groups, (g) => (g.section === 'gone' ? 0 : g.byState[k] ?? 0))
  const spareStores = new Set(d.spares.map((s) => s.locationId)).size
  return (
    <>
      <div className={TILE_ROW}>
        <Tile icon={Warehouse} label="Мест хранения" value={nf.format(d.groups.filter((g) => g.section !== 'gone').length)}
          hint={`на складах ${nf.format(section('stock'))} · вне складов ${nf.format(section('out'))}`}
          active={table === 'places'} onClick={() => setTable('places')} />
        <Tile icon={Boxes} label="Единиц на учёте" value={nf.format(d.total)}
          hint={`новых ${nf.format(state('in_stock_new'))} · б/у ${nf.format(state('in_stock_used'))}`}
          active={table === 'units'} onClick={() => pick('units')} />
        <Tile icon={Wrench} label="В ремонте" value={nf.format(repair)} hint="у подрядчика на дату"
          tone={repair ? AMBER : undefined} active={table === 'repair'} onClick={() => pick('repair')} />
        <Tile icon={History} label="Без истории движений" value={nf.format(d.noHistory)} hint="место известно только на сегодня"
          tone={d.noHistory ? AMBER : undefined} active={table === 'nohist'} onClick={() => pick('nohist')} />
        <Tile icon={PackageX} label="Выбыло" value={nf.format(gone + d.inOperation)}
          hint={`в эксплуатацию ${nf.format(d.inOperation)} · списано и возвращено ${nf.format(gone)}`}
          active={table === 'gone'} onClick={() => pick('gone')} />
        {/* ЗИП — плиткой, только когда он есть: «0 на 0 складах» читается как поломка. */}
        {(d.spares.length > 0 || table === 'spares') && (
          <Tile icon={Package} label="ЗИП, позиций" value={nf.format(d.spares.length)}
            hint={`на ${nf.format(spareStores)} ${plural(spareStores, 'складе', 'складах', 'складах')}`}
            active={table === 'spares'} onClick={() => pick('spares')} />
        )}
      </div>
      <KitSheet key={table} companyId={companyId} sheet={sheet} root={root}
        lines={[
          `на ${day(range.date)}`,
          ...(locationId ? [`склад: ${nameOf(warehouses, locationId)}`] : []),
          ...(counterpartyId ? [`контрагент: ${nameOf(d.counterparties, counterpartyId)}`] : []),
          ...(table === 'spares' && d.spareCorrectionsUnknown ? ['есть корректировки ЗИП без величины — остаток может отличаться от карточки склада'] : []),
        ]}
        fields={<>
          <Pick label="Склад" all="Все склады" value={locationId} onChange={setLocationId} opts={warehouses} />
          <Pick label="Контрагент" all="Все контрагенты" value={counterpartyId} onChange={setCounterpartyId} opts={d.counterparties} />
        </>}
        chosen={(locationId ? 1 : 0) + (counterpartyId ? 1 : 0)}
        onReset={() => { setLocationId(''); setCounterpartyId(''); setTable('places') }}
        help={HELP_STOCK}
        compare={<StockCompare companyId={companyId} date={range.date} locationId={locationId} counterpartyId={counterpartyId} now={d} />}
        searchHint="Склад, серийный номер, модель или контрагент"
        formulaExample="Например, доля б/у: [На складе (б/у)] / [Всего]" />
    </>
  )
}

const shiftDay = (iso: string, days: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString().slice(0, 10)
}

/** «Сравнить» для остатков: те же остатки на более раннюю дату — что изменилось и где. */
function StockCompare({ companyId, date, locationId, counterpartyId, now }: {
  companyId: string; date: string; locationId: string; counterpartyId: string; now: StockReport
}) {
  const [days, setDays] = useState<number | null>(null)
  const then = days ? shiftDay(date, days) : ''
  const q = useQuery({
    queryKey: ['eq-report-stock', companyId, then, locationId, counterpartyId],
    queryFn: () => getStockReport({ companyId, date: then, locationId: locationId || undefined, counterpartyId: counterpartyId || undefined }),
    enabled: !!then,
  })
  const was = q.data
  const figures = (r: StockReport): [string, number][] => {
    const s = (k: string) => sum(r.groups.filter((g) => g.section === k), (g) => g.total)
    return [['Единиц на учёте', r.total], ['На складах', s('stock')], ['Вне складов: монтаж, ремонт', s('out')],
      ['Списано и возвращено', s('gone')], ['Передано в эксплуатацию', r.inOperation], ['Позиций ЗИП', r.spares.length]]
  }
  const places = useMemo(() => {
    if (!was) return []
    const before = new Map(was.groups.map((g) => [g.key, g]))
    const after = new Map(now.groups.map((g) => [g.key, g]))
    return [...new Set([...before.keys(), ...after.keys()])]
      .map((k) => ({ name: after.get(k)?.name ?? before.get(k)?.name ?? k, was: before.get(k)?.total ?? 0, now: after.get(k)?.total ?? 0 }))
      .filter((p) => p.was !== p.now)
      .sort((a, b) => Math.abs(b.now - b.was) - Math.abs(a.now - a.was))
  }, [was, now])
  const delta = (n: number) => (n > 0 ? `+${nf.format(n)}` : n < 0 ? `−${nf.format(-n)}` : '0')
  const prev = was ? figures(was) : []
  return (
    <>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Те же остатки на более раннюю дату: сколько единиц прибавилось или ушло и на каких местах. Склад и контрагент отбора действуют на обе даты.
      </p>
      <div className="flex flex-wrap gap-2">
        {([[1, 'С прошлым днём'], [7, 'С неделей назад'], [30, 'С месяцем назад']] as const).map(([n, label]) => (
          <Button key={n} size="sm" variant={days === n ? 'default' : 'outline'} onClick={() => setDays(n)}>{label}</Button>
        ))}
      </div>
      {q.isFetching && <div className="flex justify-center py-4"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>}
      {q.isError && <p role="alert" className="text-sm font-medium text-red-700 dark:text-red-400">Остатки на {day(then)} собрать не удалось.</p>}
      {was && !q.isFetching && (
        <>
          <p className="text-xs text-di-on-surface-variant">Сейчас — {day(date)}, было — {day(then)}</p>
          <ul className="flex flex-col divide-y divide-di-outline-variant/50">
            {figures(now).map(([label, cur], i) => (
              <li key={label} className="py-2 first:pt-0">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-di-on-surface-variant">{label}</span>
                  <span className="whitespace-nowrap text-sm font-bold tabular-nums text-foreground">{delta(cur - prev[i][1])}</span>
                </div>
                <div className="mt-0.5 flex items-baseline justify-between gap-3 text-xs text-muted-foreground">
                  <span>сейчас <span className="font-semibold text-foreground">{nf.format(cur)}</span></span>
                  <span>было {nf.format(prev[i][1])}</span>
                </div>
              </li>
            ))}
          </ul>
          <div>
            <h3 className="mb-1.5 text-sm font-semibold text-foreground">Изменились места: {nf.format(places.length)}</h3>
            {!places.length ? <p className="text-xs text-muted-foreground">Нет.</p> : (
              <ul className="flex flex-col divide-y divide-di-outline-variant/50">
                {places.slice(0, 12).map((p) => (
                  <li key={p.name} className="flex items-baseline justify-between gap-3 py-1.5 text-xs">
                    <span className="min-w-0 truncate">{p.name}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">{nf.format(p.was)} → {nf.format(p.now)}</span>
                  </li>
                ))}
                {places.length > 12 && <li className="py-1.5 text-xs text-muted-foreground">и ещё {nf.format(places.length - 12)}</li>}
              </ul>
            )}
          </div>
        </>
      )}
    </>
  )
}

// ─── оборотно-сальдовая ─────────────────────────────────────────────────────

const OSV_KEYS: (keyof OsvCells)[] = ['oq', 'os', 'dq', 'ds', 'cq', 'cs', 'zq', 'zs']
const OSV_HEAD = ['Счёт', 'Наименование счёта', 'Склад / место', 'Номенклатура', 'Ед.',
  'Нач. кол-во', 'Нач. сумма, ₽', 'Приход, кол-во', 'Приход, сумма, ₽', 'Расход, кол-во', 'Расход, сумма, ₽', 'Кон. кол-во', 'Кон. сумма, ₽']
/** Складские счета — без 01.01: работающие станции со склада выбыли и нужны только для сверки основных средств. */
const STOCK_ACCOUNTS = 'stock'

function OsvView({ companyId, range, warehouses, root }: ViewProps) {
  const [account, setAccount] = useState(STOCK_ACCOUNTS)
  const [locationId, setLocationId] = useState('')
  const q = useQuery({
    queryKey: ['eq-report-osv', companyId, range.from, range.date, locationId],
    queryFn: () => getOsvReport({ companyId, dateFrom: range.from, dateTo: range.date, locationId: locationId || undefined }),
    placeholderData: keepPreviousData,
  })
  const d = q.data
  const sheet = useMemo((): Sheet | null => {
    if (!d) return null
    const label = new Map(d.accounts.map((a) => [a.account, a.label]))
    const list = d.rows.filter((r) => (account === STOCK_ACCOUNTS ? r.account !== '01.01' : !account || r.account === account))
    return {
      id: 'eq-osv.v1', title: 'Оборотно-сальдовая ведомость', head: OSV_HEAD,
      // Ноль — пустая клетка, как в ведомости 1С.
      rows: list.map((r) => [r.account, label.get(r.account) ?? '', r.placeName, r.itemName, r.unitLabel, ...OSV_KEYS.map((k) => r[k] || '')]),
      total: ['Итого', '', '', `${qty(list.length)} строк`, '', ...OSV_KEYS.map((k) => (k.endsWith('s') ? round2(sum(list, (r) => r[k])) : ''))],
      // Название счёта уже начинается с кода («07 — …»): по умолчанию скрыто, есть в карточке строки.
      hide: [1], groupBy: { 0: 'Счёт', 2: 'Склад / место', 3: 'Номенклатура' }, noPivot: [1],
      render: (i, c) => (c === 3 && list[i]?.item.startsWith('text:')
        ? <span className={AMBER} title="Без номенклатуры — модель из карточки">{list[i].itemName}</span> : undefined),
      rowTitle: (i) => (list[i] ? `${list[i].account} · ${list[i].placeName} · ${list[i].itemName}` : ''),
      empty: 'За период по отбору ни остатков, ни оборотов нет',
      drills: (i) => (list[i] && isLocation(list[i].place) ? [{ label: 'Движения места за период', hint: 'откуда приход и расход строки',
        locationId: list[i].place, dateFrom: range.from, dateTo: range.date }] : []),
    }
  }, [d, account, range.from, range.date])
  if (!d || !sheet) return <Pending q={q} />
  const stock = d.accounts.filter((a) => a.account !== '01.01')
  const noCost = account === STOCK_ACCOUNTS ? d.noCostStock : d.noCost
  return (
    <>
      <div className={TILE_ROW}>
        <Tile icon={Layers} label="Складские счета" value={nf.format(sum(stock, (a) => a.zq))}
          hint={`на конец, без 01.01 · ${money.format(sum(stock, (a) => a.zs))} ₽`}
          active={account === STOCK_ACCOUNTS} onClick={() => setAccount(STOCK_ACCOUNTS)} />
        {d.accounts.map((a) => (
          <Tile key={a.account} icon={Layers} label={a.label} value={nf.format(a.zq)}
            hint={a.zs ? `на конец ${money.format(a.zs)} ₽` : `приход ${nf.format(a.dq)} · расход ${nf.format(a.cq)}`}
            active={account === a.account} onClick={() => setAccount(account === a.account ? STOCK_ACCOUNTS : a.account)} />
        ))}
        <Tile icon={FileWarning} label="Без стоимости" value={nf.format(noCost)} hint="идут количеством без суммы"
          tone={noCost ? AMBER : undefined} />
      </div>
      <KitSheet key="osv" companyId={companyId} sheet={sheet} root={root}
        lines={[
          `${day(range.from)} — ${day(range.date)}`, 'суммы без НДС',
          account === STOCK_ACCOUNTS ? 'складские счета' : account ? `счёт ${account}` : 'все счета',
          ...(locationId ? [`склад: ${nameOf(warehouses, locationId)}`] : []),
        ]}
        fields={<>
          <Pick label="Счёт" all="Все счета" value={account} onChange={setAccount} w="w-72"
            opts={[{ id: STOCK_ACCOUNTS, name: 'Складские счета (без 01.01)' }, ...d.accounts.map((a) => ({ id: a.account, name: a.label }))]} />
          <Pick label="Склад" all="Все места" value={locationId} onChange={setLocationId} opts={warehouses} />
        </>}
        chosen={(account !== STOCK_ACCOUNTS ? 1 : 0) + (locationId ? 1 : 0)}
        onReset={() => { setAccount(STOCK_ACCOUNTS); setLocationId('') }}
        help={HELP_OSV}
        compare={COMPARE_PERIOD}
        searchHint="Счёт, склад или номенклатура"
        formulaExample="Например, средняя цена: [Кон. сумма, ₽] / [Кон. кол-во]" />
      <ClosedPeriod companyId={companyId} />
    </>
  )
}

/** Закрытый период — как дата запрета изменений в 1С: закрывает администратор пространства. */
function ClosedPeriod({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['equipment', 'settings', companyId], queryFn: () => getEquipmentSettings(companyId) })
  const [value, setValue] = useState<string | null>(null)
  const current = q.data?.closedUntil ?? ''
  const shown = value ?? current
  const mut = useMutation({
    mutationFn: (v: string | null) => setClosedPeriod(companyId, v),
    onSuccess: (r) => {
      toast.success(r.closedUntil ? `Период закрыт по ${formatDate(r.closedUntil)}` : 'Закрытый период снят')
      setValue(null); void qc.invalidateQueries({ queryKey: ['equipment', 'settings', companyId] })
    },
    onError: (e) => toast.error('Период не изменён', { description: e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e) }),
  })
  return <Card><CardContent className="flex flex-wrap items-center gap-3 p-3 text-sm">
    <Lock className="h-4 w-4 text-muted-foreground" />
    <span className="min-w-0 flex-1">
      <span className="font-medium">Закрытый период</span>
      <span className="block text-xs text-muted-foreground">{current
        ? `Сверен с бухгалтерией по ${formatDate(current)} включительно: документы этими датами не проводятся и не отменяются.`
        : 'Не закрыт. После сверки с 1С закройте период — так прошлые остатки не изменятся задним числом.'}</span>
    </span>
    <Input type="date" aria-label="Закрыть период по дату" value={shown} onChange={(e) => setValue(e.target.value)} className="h-9 w-40" />
    <Button size="sm" variant="outline" disabled={mut.isPending || !shown || shown === current} onClick={() => mut.mutate(shown)}>Закрыть по дату</Button>
    {current && <Button size="sm" variant="ghost" disabled={mut.isPending} onClick={() => mut.mutate(null)}>Снять</Button>}
  </CardContent></Card>
}

// ─── оборотная ведомость ────────────────────────────────────────────────────

const TURN_COLS = ['Начальный остаток', 'Приход', 'Расход', 'Конечный остаток']
const TURN_HEAD = ['Склад', ...TURN_COLS, 'Без истории движений', 'Приход по операциям', 'Расход по операциям']
const TURN_SPARE_HEAD = ['Склад', 'Номенклатура', 'Артикул', 'Ед.', ...TURN_COLS, 'Приход по операциям', 'Расход по операциям']
const figures = (t: TurnoverFigures): Cell[] => [t.opening, t.income, t.outcome, t.closing]
type TurnTable = 'all' | 'moved' | 'nohist' | 'spares'

function TurnoverView({ companyId, range, warehouses, root }: ViewProps) {
  const [table, setTable] = useState<TurnTable>('all')
  const [locationId, setLocationId] = useState('')
  const q = useQuery({
    queryKey: ['eq-report-turnover', companyId, range.from, range.date, locationId],
    queryFn: () => getTurnoverReport({ companyId, dateFrom: range.from, dateTo: range.date, locationId: locationId || undefined }),
    placeholderData: keepPreviousData,
  })
  const d = q.data
  const sheet = useMemo((): Sheet | null => {
    if (!d) return null
    if (table === 'spares') {
      return {
        id: 'eq-turnover-spares.v1', title: 'ЗИП по складам', head: TURN_SPARE_HEAD,
        rows: d.spares.map((s) => [s.location, s.name, s.article ?? '', s.unitLabel, ...figures(s), byOp(s.incomeByOp), byOp(s.outcomeByOp)]),
        groupBy: { 0: 'Склад', 1: 'Номенклатура' },
        rowTitle: (i) => (d.spares[i] ? `${d.spares[i].name} · ${d.spares[i].location}` : ''),
        empty: 'Движений и остатков ЗИП за период нет',
      }
    }
    const list = d.warehouses.filter((w) => table === 'all' || (table === 'moved' ? w.income + w.outcome > 0 : w.noHistory > 0))
    return {
      id: 'eq-turnover.v1', title: 'Оборудование по складам, шт.', head: TURN_HEAD,
      rows: list.map((w) => [w.location, ...figures(w), w.noHistory, byOp(w.incomeByOp), byOp(w.outcomeByOp)]),
      total: [`${qty(list.length)} складов`, sum(list, (w) => w.opening), sum(list, (w) => w.income), sum(list, (w) => w.outcome),
        sum(list, (w) => w.closing), sum(list, (w) => w.noHistory), '', ''],
      noPivot: [0],
      rowTitle: (i) => list[i]?.location ?? '',
      empty: 'Складов по отбору нет',
      drills: (i) => (list[i] && isLocation(list[i].locationId) ? [{ label: 'Движения склада за период', hint: 'откуда «Приход» и «Расход»',
        locationId: list[i].locationId, dateFrom: range.from, dateTo: range.date }] : []),
    }
  }, [d, table, range.from, range.date])
  if (!d || !sheet) return <Pending q={q} />
  const w = d.warehouses
  const moved = w.filter((x) => x.income + x.outcome > 0).length
  const noHistory = sum(w, (x) => x.noHistory)
  const pick = (t: TurnTable) => setTable(table === t ? 'all' : t)
  return (
    <>
      <div className={TILE_ROW}>
        <Tile icon={Warehouse} label="Складов" value={nf.format(w.length)}
          hint={`на начало ${nf.format(sum(w, (x) => x.opening))} · на конец ${nf.format(sum(w, (x) => x.closing))}`}
          active={table === 'all'} onClick={() => setTable('all')} />
        <Tile icon={Boxes} label="С движением за период" value={nf.format(moved)}
          hint={`приход ${nf.format(sum(w, (x) => x.income))} · расход ${nf.format(sum(w, (x) => x.outcome))}`}
          active={table === 'moved'} onClick={() => pick('moved')} />
        <Tile icon={History} label="Без истории движений" value={nf.format(noHistory)} hint="единиц: дают только остаток"
          tone={noHistory ? AMBER : undefined} active={table === 'nohist'} onClick={() => pick('nohist')} />
        {(d.spares.length > 0 || table === 'spares') && (
          <Tile icon={Package} label="ЗИП, позиций" value={nf.format(d.spares.length)} hint="с остатком или движением"
            active={table === 'spares'} onClick={() => pick('spares')} />
        )}
      </div>
      <KitSheet key={table === 'spares' ? 'spares' : 'eq'} companyId={companyId} sheet={sheet} root={root}
        lines={[
          `${day(range.from)} — ${day(range.date)}`,
          ...(table === 'moved' ? ['с движением'] : table === 'nohist' ? ['есть единицы без истории'] : []),
          ...(locationId ? [`склад: ${nameOf(warehouses, locationId)}`] : []),
          ...(table === 'spares' && d.spareCorrectionsUnknown ? ['есть корректировки ЗИП без величины — в расчёт не вошли'] : []),
        ]}
        fields={<Pick label="Склад" all="Все склады" value={locationId} onChange={setLocationId} opts={warehouses} />}
        chosen={(locationId ? 1 : 0) + (table === 'moved' || table === 'nohist' ? 1 : 0)}
        onReset={() => { setLocationId(''); setTable('all') }}
        help={HELP_TURNOVER}
        compare={COMPARE_PERIOD}
        searchHint="Склад, номенклатура или операция"
        formulaExample="Например, оборот: [Приход] + [Расход]" />
    </>
  )
}

// ─── за контрагентом ────────────────────────────────────────────────────────

const HOLDER_HEAD = ['Контрагент', 'В справочнике', 'Складов', 'Единиц на складах', 'В ремонте, возвращено, хранитель в карточке', 'Всего']
const HOLDER_WH_HEAD = ['Контрагент', 'Склад', 'Вид владения', 'Договор', 'Действует до', 'Статус договора', 'Ответственный', 'Единиц']
const HOLDER_UNIT_HEAD = ['Контрагент', 'В справочнике', 'Серийный №', 'Инв. №', 'Оборудование', 'Состояние', 'Где', 'С даты', 'Документ',
  'Договор документа', 'История движений']
type HolderWh = HolderGroup['warehouses'][number] & { holder: HolderGroup }
const linked = (h: HolderGroup) => (h.linked ? 'да' : 'не привязан')
const whCells = (w: HolderWh): Cell[] => [w.holder.name, w.name, w.ownershipLabel, w.contract.number ? `№ ${w.contract.number} от ${day(w.contract.date)}` : '',
  day(w.contract.validUntil), w.contract.statusLabel, w.responsible ?? '', w.units.length]
const holderUnits = (h: HolderGroup) => [...h.warehouses.flatMap((w) => w.units), ...h.units]
const holderUnitCells = (h: HolderGroup, u: ReportUnitRow): Cell[] => [h.name, linked(h), ...unitCells(u).slice(0, 7), u.contractLabel ?? '',
  u.noHistory ? 'нет' : 'есть']
type HolderTable = 'holders' | 'unlinked' | 'warehouses' | 'nocontract' | 'units'

function HoldersView({ companyId, range, root }: ViewProps) {
  const [table, setTable] = useState<HolderTable>('holders')
  const q = useQuery({
    queryKey: ['eq-report-holders', companyId, range.date],
    queryFn: () => getHoldersReport(companyId, range.date),
    placeholderData: keepPreviousData,
  })
  const holders = q.data?.holders
  const sheet = useMemo((): Sheet | null => {
    if (!holders) return null
    const whs = holders.flatMap((h) => h.warehouses.map((w): HolderWh => ({ ...w, holder: h })))
    const whDrills = (w: HolderWh): Drill[] => [
      { label: 'Единицы на складе', hint: 'что лежит у контрагента на дату', head: UNIT_HEAD, rows: w.units.map(unitCells) },
      { label: 'Движения склада за период', hint: `с ${day(range.from)} по ${day(range.date)}`, locationId: w.id, dateFrom: range.from, dateTo: range.date },
    ]
    if (table === 'warehouses' || table === 'nocontract') {
      const list = whs.filter((w) => table === 'warehouses' || w.contract.status !== 'active')
      return {
        id: 'eq-holders-wh.v1', title: 'Склады контрагентов', head: HOLDER_WH_HEAD, rows: list.map(whCells),
        total: ['Итого', `${qty(list.length)} складов`, '', '', '', '', '', sum(list, (w) => w.units.length)],
        groupBy: { 0: 'Контрагент', 2: 'Вид владения', 5: 'Статус договора' }, noPivot: [1],
        rowClass: (i) => (list[i] && list[i].contract.status !== 'active' ? AMBER : undefined),
        rowTitle: (i) => (list[i] ? `${list[i].name} · ${list[i].holder.name}` : ''),
        empty: table === 'nocontract' ? 'У всех складов контрагентов договор действует' : 'Складов у контрагентов нет',
        drills: (i) => (list[i] ? whDrills(list[i]) : []),
      }
    }
    if (table === 'units') {
      const list = holders.flatMap((h) => holderUnits(h).map((u) => ({ h, u })))
      return {
        id: 'eq-holders-units.v1', title: 'Единицы за контрагентами', head: HOLDER_UNIT_HEAD, rows: list.map(({ h, u }) => holderUnitCells(h, u)),
        total: ['Итого', '', '', '', `${qty(list.length)} ед.`, '', '', '', '', '', ''],
        groupBy: { 0: 'Контрагент', 4: 'Оборудование', 5: 'Состояние', 6: 'Где' }, noPivot: [2, 3],
        rowTitle: (i) => (list[i] ? unitTitle(list[i].u) : ''),
        empty: 'Единиц нет',
        drills: (i) => (list[i] ? [unitHistory(list[i].u.id)] : []),
      }
    }
    const list = holders.filter((h) => table === 'holders' || !h.linked)
    return {
      id: 'eq-holders.v1', title: 'Контрагенты', head: HOLDER_HEAD,
      rows: list.map((h) => [h.name, linked(h), h.warehouses.length, h.total - h.units.length, h.units.length, h.total]),
      total: [`${qty(list.length)} контрагентов`, '', sum(list, (h) => h.warehouses.length), sum(list, (h) => h.total - h.units.length),
        sum(list, (h) => h.units.length), sum(list, (h) => h.total)],
      groupBy: { 1: 'В справочнике' }, noPivot: [0],
      rowClass: (i) => (list[i] && !list[i].linked ? AMBER : undefined),
      rowTitle: (i) => list[i]?.name ?? '',
      empty: table === 'unlinked' ? 'Все держатели привязаны к справочнику' : 'На эту дату за контрагентами ничего не числится',
      drills: (i) => {
        const h = list[i]
        if (!h) return []
        return [
          ...(h.warehouses.length ? [{ label: 'Склады контрагента', hint: 'договоры хранения и ответственные', head: HOLDER_WH_HEAD,
            rows: h.warehouses.map((w) => whCells({ ...w, holder: h })) }] : []),
          { label: 'Единицы за контрагентом', hint: 'на складах и в ремонте, по документам', head: HOLDER_UNIT_HEAD,
            rows: holderUnits(h).map((u) => holderUnitCells(h, u)) },
        ]
      },
    }
  }, [holders, table, range.from, range.date])
  if (!holders || !sheet) return <Pending q={q} />
  const whs = holders.flatMap((h) => h.warehouses)
  const unlinked = holders.filter((h) => !h.linked).length
  const noContract = whs.filter((w) => w.contract.status !== 'active').length
  const pick = (t: HolderTable) => setTable(table === t ? 'holders' : t)
  return (
    <>
      <div className={TILE_ROW}>
        <Tile icon={Users} label="Контрагентов" value={nf.format(holders.length)} hint={`за ними ${nf.format(sum(holders, (h) => h.total))} ед.`}
          active={table === 'holders'} onClick={() => setTable('holders')} />
        <Tile icon={AlertTriangle} label="Не в справочнике" value={nf.format(unlinked)} hint="держатель записан текстом"
          tone={unlinked ? AMBER : undefined} active={table === 'unlinked'} onClick={() => pick('unlinked')} />
        <Tile icon={Building2} label="Складов у контрагентов" value={nf.format(whs.length)}
          hint={`единиц на них ${nf.format(sum(whs, (w) => w.units.length))}`}
          active={table === 'warehouses'} onClick={() => pick('warehouses')} />
        <Tile icon={FileWarning} label="Договор не действует" value={nf.format(noContract)} hint="истёк, закрыт или не заведён"
          tone={noContract ? AMBER : undefined} active={table === 'nocontract'} onClick={() => pick('nocontract')} />
        <Tile icon={Boxes} label="Единиц за контрагентами" value={nf.format(sum(holders, (h) => holderUnits(h).length))} hint="списком, с документом"
          active={table === 'units'} onClick={() => pick('units')} />
      </div>
      <KitSheet key={table} companyId={companyId} sheet={sheet} root={root}
        lines={[`на ${day(range.date)}`]}
        chosen={table === 'unlinked' || table === 'nocontract' ? 1 : 0}
        onReset={() => setTable('holders')}
        help={HELP_HOLDERS}
        compare={COMPARE_STOCK}
        searchHint="Контрагент, склад, договор или серийный номер"
        formulaExample="Например, доля на складах: [Единиц на складах] / [Всего]" />
    </>
  )
}

// ─── в ремонте ──────────────────────────────────────────────────────────────

const REPAIR_HEAD = ['Серийный №', 'Инв. №', 'Оборудование', 'Кому передана', 'Документ', 'Передана', 'Плановый возврат',
  'Дней в ремонте', 'Просрочка, дней', 'Вид ремонта', 'Заявка']

function RepairsView({ companyId, root }: ViewProps) {
  const [overdueOnly, setOverdueOnly] = useState(false)
  const q = useQuery({ queryKey: ['eq-report-repairs', companyId], queryFn: () => getRepairsReport(companyId) })
  const d = q.data
  const sheet = useMemo((): Sheet | null => {
    if (!d) return null
    const list = d.items.filter((r) => !overdueOnly || r.overdueDays > 0)
    return {
      id: 'eq-repairs.v1', title: 'В ремонте', head: REPAIR_HEAD,
      rows: list.map((r) => [r.serialNumber ?? '', r.inventoryNumber ?? '', eqName(r.vendor, r.model), r.holder ?? '', r.docNumber ?? '',
        day(r.sentOn), day(r.plannedReturn), r.days ?? '', r.overdueDays || '', r.repairKind ?? '', r.ticketRef ?? '']),
      total: ['Итого', '', `${qty(list.length)} ед.`, '', '', '', '', '', '', '', ''],
      groupBy: { 2: 'Оборудование', 3: 'Кому передана', 9: 'Вид ремонта' }, noPivot: [0, 1, 4, 10],
      rowClass: (i) => (list[i] && list[i].overdueDays > 0 ? AMBER : undefined),
      rowTitle: (i) => (list[i] ? unitTitle(list[i]) : ''),
      empty: overdueOnly ? 'Дольше планового срока ничего не задержано' : 'В ремонте ничего нет',
      drills: (i) => (list[i] ? [unitHistory(list[i].id)] : []),
    }
  }, [d, overdueOnly])
  if (!d || !sheet) return <Pending q={q} />
  const holders = new Set(d.items.map((r) => r.holder ?? '')).size
  return (
    <>
      <div className={TILE_ROW}>
        <Tile icon={Wrench} label="В ремонте" value={nf.format(d.items.length)}
          hint={`у ${nf.format(holders)} ${plural(holders, 'подрядчика', 'подрядчиков', 'подрядчиков')}`}
          active={!overdueOnly} onClick={() => setOverdueOnly(false)} />
        <Tile icon={AlertTriangle} label="Дольше планового срока" value={nf.format(d.overdue)} hint="плановый возврат прошёл"
          tone={d.overdue ? 'text-red-600 dark:text-red-400' : undefined}
          active={overdueOnly} onClick={() => setOverdueOnly(!overdueOnly)} />
      </div>
      <KitSheet key="repairs" companyId={companyId} sheet={sheet} root={root}
        lines={[`на ${day(d.date)}`, ...(overdueOnly ? ['дольше планового срока'] : [])]}
        chosen={overdueOnly ? 1 : 0}
        onReset={() => setOverdueOnly(false)}
        help={HELP_REPAIRS}
        compare={COMPARE_STOCK}
        searchHint="Серийный номер, подрядчик, документ или заявка"
        formulaExample="Например, просрочка в неделях: [Просрочка, дней] / 7" />
    </>
  )
}

// ─── помощь и сравнение ─────────────────────────────────────────────────────
// Элементы — константами модуля: помощь уходит в хранилище рельсы, и новый
// элемент на каждом рендере зациклил бы его (README набора).

const П = 'text-sm leading-relaxed text-di-on-surface-variant'
const TOOLS_HELP = (
  <p className={П}>
    <b>Таблица.</b> Наведите на заголовок: стрелка сортирует, Σ считает сумму, ▾ открывает меню — закрепить, скрыть, полоски и фильтр по
    значениям. Значок у столбца с повторами открывает сводную с этим уровнем. Щелчок по строке — её карточка с расшифровками окном поверх.
    Справа — калькулятор, свои столбцы-формулы, поиск, столбцы, сравнение и отложенные цифры.
  </p>
)
const help = (text: ReactNode) => <div className="space-y-3"><p className={П}>{text}</p>{TOOLS_HELP}</div>

const HELP_STOCK = help(<>
  Остатки на конец периода из строки «Период» (период по сегодня — на сейчас). Плитки выбирают таблицу: места хранения, единицы на учёте,
  в ремонте, без истории движений, выбывшие и ЗИП. Станции в эксплуатации со складского учёта выбыли и показаны одним числом. Единица без истории
  движений видна там, где числится сегодня, — где она была на прошлую дату, учёт не знает.
</>)
const HELP_OSV = help(<>
  Ведомость как в 1С:Бухгалтерии: сальдо и обороты в количестве и сумме по счетам с разрезом «склад — номенклатура», за период из строки
  «Период». По умолчанию — складские счета; 01.01 (работающие станции) — плиткой или в фильтре «Счёт». Ноль — пустая клетка. Номенклатура
  жёлтым — единица без номенклатуры, модель взята из карточки. Ниже — закрытый период: после сверки с 1С прошлые остатки не меняются.
</>)
const HELP_TURNOVER = help(<>
  Остаток на начало, приход, расход и остаток на конец по складам за период из строки «Период», отдельно оборудование в штуках и ЗИП.
  Монтаж и ввод — одно выбытие со склада, демонтаж — возврат на него. Единицы без истории движений дают только остаток.
</>)
const HELP_HOLDERS = help(<>
  Что числится за каждым контрагентом на конец периода: на его складах (аренда, ответственное хранение) и вне складов — в ремонте, возвращено,
  хранитель в карточке. Жёлтым — держатель, записанный текстом, и склад с недействующим договором.
</>)
const HELP_REPAIRS = help(<>
  Единицы, переданные в ремонт, на сегодня: кому, по какому документу, с какого дня и до какого планового срока. Жёлтым — дольше срока.
</>)

const COMPARE_PERIOD = (
  <p className="text-xs leading-relaxed text-muted-foreground">
    Отчёт уже сравнивает начало и конец периода: начальный остаток, приход, расход и конечный остаток. Другой период выбирается в строке
    «Период» над экраном.
  </p>
)
const COMPARE_STOCK = (
  <p className="text-xs leading-relaxed text-muted-foreground">
    Сравнение остатков по датам — в отчёте «Остатки на дату», инструмент «Сравнить».
  </p>
)

// ─── экран ──────────────────────────────────────────────────────────────────

const VIEWS = { stock: StockView, osv: OsvView, turnover: TurnoverView, holders: HoldersView, repairs: RepairsView }

export function EquipmentReportsPanel({ companyId }: { companyId: string }) {
  const [report, setReport] = useState<keyof typeof VIEWS>('stock')
  const range = useRange()
  const root = useRef<HTMLDivElement>(null)
  const locs = useQuery({ queryKey: ['eq-locations', companyId], queryFn: () => loadLocations(companyId), staleTime: 60_000 })
  const warehouses = useMemo(() => (locs.data ?? []).filter((l) => l.type === 'warehouse')
    .map((l) => ({ id: l.id, name: l.name })).sort((a, b) => a.name.localeCompare(b.name, 'ru')), [locs.data])
  const View = VIEWS[report]
  return (
    <div className="space-y-3 p-3" ref={root}>
      <div data-export-ignore>
        <PanelViewTabs tabs={REPORTS} value={report} label="Отчёт" ariaLabel="Отчёты складского учёта"
          onChange={(k) => setReport(k as keyof typeof VIEWS)} />
      </div>
      <View key={report} companyId={companyId} range={range} warehouses={warehouses} root={() => root.current} />
    </div>
  )
}
