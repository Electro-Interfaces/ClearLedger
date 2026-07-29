/**
 * Книга резервуара: движение СМЕНА ЗА СМЕНОЙ и сверка книги с фактическим замером.
 *
 * Главный экран — журнал по сменам единой лентой: начало смены → конец → начало
 * следующей, подряд, сгруппированный по резервуару. Именно здесь виден стык
 * смен, ради которого всё и затевалось. Сводка по резервуарам за период и список
 * замечаний — вспомогательные экраны.
 *
 * Знак расхождения везде один: плюс — недостача (в резервуаре меньше, чем по
 * документам), минус — излишек. Подписи дублируют знак словом, потому что
 * «−444 л» без слова читается как «мало топлива», а это ровно наоборот.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Download, Loader2, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { TankShiftDialog } from './TankShiftDialog'
import { TankCardDialog, type TankRef } from './TankCardDialog'
import {
  getTankLedger, type TankLedgerResponse, type TankLedgerRow, type TankLedgerTank,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf3 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

const L = (v: number | null | undefined) => (v == null ? '—' : `${nf0.format(v)} л`)
const L1 = (v: number | null | undefined) => (v == null ? '—' : `${nf1.format(v)} л`)

/** Расхождение со словом: знак сам по себе читается неоднозначно. */
function gapLabel(v: number | null | undefined): string {
  if (v == null) return '—'
  if (Math.abs(v) < 0.05) return 'сходится'
  return `${nf0.format(Math.abs(v))} л ${v > 0 ? 'недостача' : 'излишек'}`
}

function gapTone(v: number | null | undefined, tolerance: number): string {
  if (v == null) return 'text-muted-foreground'
  if (Math.abs(v) <= tolerance) return 'text-muted-foreground'
  return v > 0 ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'
}

/** Допуски приходят с сервера (`tolerances`) — это его правила счёта, а не наши.
 *  Здесь только страховка на случай старого ответа: пока они были захардкожены,
 *  фронт мог подсвечивать одно, а сервер считать замечания по другому порогу. */
const TOL_FALLBACK = { ari: 0.5, cont: 0.5, fact: 50 }
type Tols = { ari: number; cont: number; fact: number }

/** Причины разрыва стыка. Разрыв — не один дефект: слив между сменами это работа
 *  приёмки, сброс счётчика — эксплуатации, а списание на станции — бухгалтерии.
 *  Раньше всё выглядело одинаково «разрыв N л», и разбирать было нечего. */
const BREAK_KINDS: Record<string, { label: string; tone: string; hard: boolean }> = {
  delivery:      { label: 'слив между сменами', tone: 'text-blue-600 dark:text-blue-400',    hard: false },
  renumber:      { label: 'перенумерация',      tone: 'text-muted-foreground',               hard: false },
  gap:           { label: 'пауза между сменами', tone: 'text-muted-foreground',              hard: false },
  reversal:      { label: 'возврат',             tone: 'text-blue-600 dark:text-blue-400',   hard: false },
  fuel_change:   { label: 'смена топлива',       tone: 'text-blue-600 dark:text-blue-400',   hard: false },
  book_reset:    { label: 'сброс книги',         tone: 'text-red-600 dark:text-red-400',     hard: true },
  pulled_to_fact:{ label: 'списано на станции',  tone: 'text-amber-600 dark:text-amber-400', hard: true },
  manual:        { label: 'ручная правка',       tone: 'text-amber-600 dark:text-amber-400', hard: true },
  unexplained:   { label: 'требует разбора',     tone: 'text-amber-600 dark:text-amber-400', hard: true },
}

/** Есть ли в смене «жёсткое» замечание — сломанный счёт (не погрешность замера). */
function hasHardIssue(r: TankLedgerRow, tols: Tols): boolean {
  return Math.abs(r.arithmetic_gap) > tols.ari
    || (r.continuity_gap != null && Math.abs(r.continuity_gap) > tols.cont)
    || r.fuel_changed
}

const r1 = (v: number | null | undefined) => (v == null ? '' : Math.round(v * 10) / 10)
const r3 = (v: number | null | undefined) => (v == null ? '' : Math.round(v * 1000) / 1000)

/** Выгрузка книги резервуаров в xlsx: журнал по сменам + итог + замечания.
 *  Цифры — числами (не текстом), чтобы бухгалтер мог считать в самом Excel. */
async function exportLedgerXlsx(data: TankLedgerResponse, dateFrom: string, dateTo: string) {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()

  // Лист 1 — журнал по сменам, полный (без учёта экранного фильтра).
  const journal = data.rows.map((r) => ({
    'АЗС': r.station_name,
    'Резервуар': r.tank_number,
    'Топливо': r.fuel_name,
    'Смена': r.shift_number,
    'Открыта': r.opened_at ? new Date(r.opened_at).toLocaleString('ru-RU') : '',
    'Закрыта': r.closed_at ? new Date(r.closed_at).toLocaleString('ru-RU') : '',
    'Книга нач., л': r1(r.book_start),
    'Конец пред. смены, л': r.continuity_gap == null ? '' : r1(r.book_start - r.continuity_gap),
    'Стык, л': r.continuity_gap == null ? '' : r1(r.continuity_gap),
    'Причина разрыва': r.continuity_kind ? (BREAK_KINDS[r.continuity_kind]?.label ?? r.continuity_kind) : '',
    'Пояснение разрыва': r.continuity_reason ?? '',
    'Приход, л': r1(r.receipts),
    'Отпуск, л': r1(r.sales),
    'Книга кон., л': r1(r.book_end),
    'Счёт (арифметика), л': r1(r.arithmetic_gap),
    'Факт нач., л': r.fact_start == null ? '' : r1(r.fact_start),
    'Факт кон., л': r1(r.fact_end),
    'Расхождение на начало, л': r1(r.fact_gap_start),
    'Расхождение на конец, л': r1(r.fact_gap),
    'Δ за смену, л': r1(r.fact_gap_delta),
    'Расхождение': r.fact_gap == null ? '' : Math.abs(r.fact_gap) < 0.05 ? 'сходится' : r.fact_gap > 0 ? 'недостача' : 'излишек',
    'Масса нач., кг': r3(r.mass_start),
    'Масса кон., кг': r3(r.mass_end),
    'Приход, кг': r3(r.mass_received),
    'Отпуск, кг': r3(r.mass_sales),
    'Факт, кг': r3(r.fact_mass),
    'Плотн. нач.': r3(r.density_beg),
    'Плотн. кон.': r3(r.density_end),
    'Темп. нач., °C': r1(r.temp_beg),
    'Темп. кон., °C': r1(r.temp_end),
    'Уровень, мм': r1(r.level_end),
    'Вода, л': r1(r.water_volume),
    'Смена топлива': r.fuel_changed ? 'да' : '',
  }))
  const wsJournal = XLSX.utils.json_to_sheet(journal)
  wsJournal['!cols'] = [
    { wch: 12 }, { wch: 10 }, { wch: 8 }, { wch: 8 }, { wch: 17 }, { wch: 17 },
    ...Array(21).fill({ wch: 13 }),
  ]
  XLSX.utils.book_append_sheet(wb, wsJournal, 'Журнал по сменам')

  // Лист 2 — итог по резервуарам за период.
  const tanks = data.tanks.map((t) => ({
    'АЗС': t.station_name,
    'Резервуар': t.tank_number,
    'Топливо': t.fuel_name,
    'Смен': t.shifts,
    'Книга нач., л': r1(t.book_start),
    'Приход, л': r1(t.receipts),
    'Отпуск, л': r1(t.sales),
    'Книга кон., л': r1(t.book_end),
    'Факт, л': r1(t.fact_end),
    'Книга − факт, л': r1(t.fact_gap),
    '% от отпуска': t.fact_gap_pct ?? '',
    'Расхождение': t.fact_gap == null ? '' : Math.abs(t.fact_gap) < 0.05 ? 'сходится' : t.fact_gap > 0 ? 'недостача' : 'излишек',
    'Было на входе, л': r1(t.fact_gap_opening),
    'Приход, кг': r1(t.mass_receipts),
    'Отпуск, кг': r1(t.mass_sales),
    'Арифметика (замечаний)': t.arithmetic_breaks,
    'Стык (замечаний)': t.continuity_breaks,
    'Расхождение замера (замечаний)': t.fact_breaks,
  }))
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tanks), 'Итог по резервуарам')

  // Лист 3 — замечания.
  const issues = data.issues.map((i) => ({
    'Тип': i.type === 'arithmetic' ? 'арифметика отчёта' : i.type === 'fuel_change' ? 'смена топлива' : 'стык смен',
    'АЗС': i.station_name,
    'Резервуар': i.tank_number,
    'Топливо': i.fuel_name,
    'Смена': i.shift_number,
    'Дата': i.date ? new Date(i.date).toLocaleDateString('ru-RU') : '',
    'Расхождение, л': r1(i.gap_liters),
    'Что не сходится': i.detail,
  }))
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(issues), 'Замечания')

  XLSX.writeFile(wb, `zhurnal_smen_${dateFrom}_${dateTo}.xlsx`)
}

/** Какой разрез книги показываем. Вкладками управляет родитель (панель баланса),
 *  чтобы всё жило в одном ряду вкладок, а не пряталось на второй уровень. */
export type TankLedgerView = 'journal' | 'tanks' | 'issues'

interface Props {
  companyId: string
  dateFrom: string
  dateTo: string
  stationCodes: number[]
  fuelCodes: number[]
  view: TankLedgerView
}

type Group = { key: string; tank: TankLedgerTank | undefined; head: TankLedgerRow; rows: TankLedgerRow[] }

type IssueFilter = 'all' | 'issues' | 'continuity' | 'arithmetic' | 'fact' | 'fuel_change'

export function TankLedgerTabs({ companyId, dateFrom, dateTo, stationCodes, fuelCodes, view }: Props) {
  const [fStation, setFStation] = useState('all')  // код АЗС
  const [fTank, setFTank] = useState('all')        // номер резервуара
  const [fFuel, setFFuel] = useState('all')        // код топлива
  const [fIssue, setFIssue] = useState<IssueFilter>('all')
  const [fShift, setFShift] = useState('')         // поиск по номеру смены
  const [picked, setPicked] = useState<TankLedgerRow | null>(null)  // строка в разборе
  // Резервуар в разборе: храним только ссылку (АЗС + номер) — карточка сама грузит.
  const [pickedTank, setPickedTank] = useState<TankRef | null>(null)
  const [sort, setSort] = useState<Sort | null>(null)               // null = хронология

  const query = useQuery({
    queryKey: ['tank-ledger', companyId, dateFrom, dateTo, stationCodes.join(','), fuelCodes.join(',')],
    queryFn: () => getTankLedger({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }),
    placeholderData: keepPreviousData,
  })

  const data = query.data
  const tols: Tols = {
    ari: data?.tolerances?.arithmetic_liters ?? TOL_FALLBACK.ari,
    cont: data?.tolerances?.continuity_liters ?? TOL_FALLBACK.cont,
    fact: data?.tolerances?.fact_liters ?? TOL_FALLBACK.fact,
  }
  const tol = tols.fact

  // Сводка по резервуарам — для заголовков групп журнала и второго экрана.
  const tankByKey = useMemo(() => {
    const m = new Map<string, TankLedgerTank>()
    for (const t of data?.tanks ?? []) m.set(`${t.station_code}:${t.tank_number}`, t)
    return m
  }, [data])

  // Значения для выпадающих фильтров — из самих данных.
  const filterOptions = useMemo(() => {
    const stations = new Map<number, string>()
    const fuels = new Map<number, string>()
    const tanksForStation = new Set<number>()
    for (const r of data?.rows ?? []) {
      stations.set(r.station_code, r.station_name)
      if (r.fuel_code != null) fuels.set(r.fuel_code, r.fuel_name)
      if (fStation === 'all' || String(r.station_code) === fStation) tanksForStation.add(r.tank_number)
    }
    return {
      stations: [...stations].sort((a, b) => a[0] - b[0]),
      fuels: [...fuels].sort((a, b) => a[0] - b[0]),
      tanks: [...tanksForStation].sort((a, b) => a - b),
    }
  }, [data, fStation])

  // Проходит ли строка через выбранное «замечание».
  const passIssue = useMemo(() => {
    const contBad = (r: TankLedgerRow) => r.continuity_gap != null && Math.abs(r.continuity_gap) > tols.cont
    const ariBad = (r: TankLedgerRow) => Math.abs(r.arithmetic_gap) > tols.ari
    const factBad = (r: TankLedgerRow) => r.fact_gap != null && Math.abs(r.fact_gap) > tols.fact
    return (r: TankLedgerRow): boolean => {
      switch (fIssue) {
        case 'issues': return hasHardIssue(r, tols)
        case 'continuity': return contBad(r)
        case 'arithmetic': return ariBad(r)
        case 'fact': return factBad(r)
        case 'fuel_change': return r.fuel_changed
        default: return true
      }
    }
  }, [fIssue, tol])

  // Строки уже приходят в порядке АЗС → резервуар → дата. Фильтруем по всем
  // критериям и группируем в ленты по физическому резервуару.
  const groups: Group[] = useMemo(() => {
    if (!data) return []
    const shiftQuery = fShift.trim()
    const rows = data.rows.filter((r) => {
      if (fStation !== 'all' && String(r.station_code) !== fStation) return false
      if (fTank !== 'all' && String(r.tank_number) !== fTank) return false
      if (fFuel !== 'all' && String(r.fuel_code) !== fFuel) return false
      if (shiftQuery && !String(r.shift_number).includes(shiftQuery)) return false
      if (!passIssue(r)) return false
      return true
    })
    const out: Group[] = []
    let cur: Group | null = null
    for (const r of rows) {
      const key = `${r.station_code}:${r.tank_number}`
      if (!cur || cur.key !== key) {
        cur = { key, tank: tankByKey.get(key), head: r, rows: [] }
        out.push(cur)
      }
      cur.rows.push(r)
    }
    return out
  }, [data, tankByKey, fStation, fTank, fFuel, fShift, passIssue])

  const shownRows = groups.reduce((n, g) => n + g.rows.length, 0)
  const filtered = fStation !== 'all' || fTank !== 'all' || fFuel !== 'all' || fIssue !== 'all' || fShift.trim() !== ''
  const resetFilters = () => {
    setFStation('all'); setFTank('all'); setFFuel('all'); setFIssue('all'); setFShift('')
  }

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Загрузка книги резервуаров…
      </div>
    )
  }
  if (query.error || !data) {
    return <div className="p-8 text-sm text-muted-foreground">Не удалось загрузить книгу резервуаров</div>
  }
  if (data.tanks.length === 0) {
    return <div className="p-8 text-sm text-muted-foreground">За период нет данных по резервуарам</div>
  }

  const t = data.totals

  return (
    <div className="space-y-4">
      {/* Итог книга↔факт — на всех разрезах книги. Это НЕ «Излишек» из шапки
          панели: там разрыв прихода-расхода по документам, здесь книга против
          фактического замера — разные величины, обе нужны. */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Cell label="Книга на начало" value={L(t.book_start)} />
        <Cell label="Поступило" value={L(t.receipts)} hint={`${nf0.format(t.mass_receipts / 1000)} т`} />
        <Cell label="Отпущено" value={L(t.sales)} hint={`${nf0.format(t.mass_sales / 1000)} т`} />
        <Cell label="Книга на конец" value={L(t.book_end)} />
        <Cell label="Факт (замер)" value={L(t.fact_end)} hint="уровнемер на конец смены" />
        <Cell
          label="Книга − факт"
          value={gapLabel(t.fact_gap)}
          hint={t.inventory_adjustment
            ? `оформлено ведомостями ${nf0.format(Math.abs(t.inventory_adjustment))} л`
            : `${nf3.format(Math.abs(t.fact_gap_pct))}% от отпуска`}
          tone={gapTone(t.fact_gap, tol)}
        />
      </div>

      {/* Непокрытое ведомостями — то, что реально идёт в следующую инвентаризацию.
          Показываем отдельной строкой только когда ведомости уже есть: иначе это
          дубль карточки «Книга − факт» и лишний шум. */}
      {t.tanks_with_inventory > 0 && (
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 rounded-lg border border-border/70 bg-card/60 px-3 py-2 text-xs">
          <span className="text-muted-foreground">
            Инвентаризация проведена по {t.tanks_with_inventory} из {t.tanks} резервуаров
          </span>
          <span>
            <span className="text-muted-foreground">оформлено: </span>
            <span className="font-medium tabular-nums">{nf0.format(Math.abs(t.inventory_adjustment))} л</span>
          </span>
          <span>
            <span className="text-muted-foreground">к разбору после ведомостей: </span>
            <span className={cn('font-medium tabular-nums', gapTone(t.fact_gap_open, tol))}>
              {gapLabel(t.fact_gap_open)}
            </span>
          </span>
        </div>
      )}

      {/* ── ЖУРНАЛ смена-за-сменой единой лентой ──────────────────────── */}
      {view === 'journal' && (
        <div className="mt-3">
          <p className="mb-2 text-[11px] text-muted-foreground">
            Начало смены → конец → начало следующей, подряд по каждому резервуару.
            Столбец «Стык» сверяет начало смены с концом предыдущей.
          </p>

          {/* Фильтры журнала: сужают уже загруженную ленту, без перезапроса. */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Select value={fStation} onValueChange={(v) => { setFStation(v); setFTank('all') }}>
              <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue placeholder="АЗС" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все АЗС</SelectItem>
                {filterOptions.stations.map(([code, name]) => (
                  <SelectItem key={code} value={String(code)}>{name}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={fTank} onValueChange={setFTank}>
              <SelectTrigger className="h-8 w-[130px] text-xs"><SelectValue placeholder="Резервуар" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все резервуары</SelectItem>
                {filterOptions.tanks.map((n) => (
                  <SelectItem key={n} value={String(n)}>Резервуар №{n}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={fFuel} onValueChange={setFFuel}>
              <SelectTrigger className="h-8 w-[120px] text-xs"><SelectValue placeholder="Топливо" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Всё топливо</SelectItem>
                {filterOptions.fuels.map(([code, name]) => (
                  <SelectItem key={code} value={String(code)}>{name}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={fIssue} onValueChange={(v) => setFIssue(v as IssueFilter)}>
              <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все смены</SelectItem>
                <SelectItem value="issues">Только с замечаниями</SelectItem>
                <SelectItem value="continuity">Разрыв стыка смен</SelectItem>
                <SelectItem value="arithmetic">Ошибка счёта (арифметика)</SelectItem>
                <SelectItem value="fact">Расхождение с замером</SelectItem>
                <SelectItem value="fuel_change">Смена вида топлива</SelectItem>
              </SelectContent>
            </Select>

            <Input
              value={fShift}
              onChange={(e) => setFShift(e.target.value)}
              placeholder="№ смены"
              className="h-8 w-[110px] text-xs"
              inputMode="numeric"
            />

            {filtered && (
              <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={resetFilters}>
                <X className="mr-1 h-3.5 w-3.5" />Сбросить
              </Button>
            )}

            <span className="ml-auto flex items-center gap-3">
              <span className="text-[11px] text-muted-foreground">
                строк: {nf0.format(shownRows)}{filtered && data.rows_total ? ` из ${nf0.format(data.rows_total)}` : ''}
              </span>
              <Button
                variant="outline" size="sm" className="h-8"
                onClick={() => exportLedgerXlsx(data, dateFrom, dateTo)}
              >
                <Download className="mr-1.5 h-3.5 w-3.5" />Экспорт в Excel
              </Button>
            </span>
          </div>

          {groups.length === 0 ? (
            <div className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
              {filtered ? 'Под фильтр не попала ни одна смена' : 'За период нет смен по резервуарам'}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border">
              {/* Порядок строк — состояние, влияющее на чтение ленты: показываем
                  его явно и даём вернуть хронологию одним кликом. */}
              {sort && (
                <div className="flex flex-wrap items-center gap-2 border-b bg-amber-500/5 px-3 py-1.5 text-[11px]">
                  <span className="font-medium text-amber-600 dark:text-amber-400">
                    Порядок изменён: {SORT_LABEL[sort.key]} {sort.dir === 'desc' ? '↓' : '↑'}
                  </span>
                  <span className="text-muted-foreground">
                    сортировка внутри резервуара · «Стык» и «Δ за смену» посчитаны относительно
                    предыдущей смены по времени, а не строки выше
                  </span>
                  <button onClick={() => setSort(null)}
                          className="ml-auto rounded border px-1.5 py-0.5 hover:bg-muted">
                    вернуть хронологию
                  </button>
                </div>
              )}
              <table className="w-full min-w-[1400px] text-xs">
                <thead className="bg-muted/40 text-muted-foreground">
                  <tr>
                    <ThSort sortKey="shift" sort={sort} onSort={setSort}>Смена</ThSort>
                    <Th>Дата</Th>
                    <ThSort right sortKey="book_start" sort={sort} onSort={setSort}>Книга нач.</ThSort>
                    <ThSort right sortKey="book_end" sort={sort} onSort={setSort}>Книга кон.</ThSort>
                    <ThSort sortKey="continuity" sort={sort} onSort={setSort}>Стык</ThSort>
                    <ThSort right sortKey="receipts" sort={sort} onSort={setSort}>Приход</ThSort>
                    <ThSort right sortKey="sales" sort={sort} onSort={setSort}>Отпуск</ThSort>
                    <ThSort right sortKey="fact_start" sort={sort} onSort={setSort}>Факт нач.</ThSort>
                    <ThSort right sortKey="fact_end" sort={sort} onSort={setSort}>Факт кон.</ThSort>
                    <ThSort right sortKey="gap_start" sort={sort} onSort={setSort}>Расхожд. нач.</ThSort>
                    <ThSort right sortKey="gap_end" sort={sort} onSort={setSort}>Расхожд. кон.</ThSort>
                    <ThSort right sortKey="gap_delta" sort={sort} onSort={setSort}>Δ за смену</ThSort>
                    <ThSort right sortKey="density" sort={sort} onSort={setSort}>Плотн.</ThSort>
                    <ThSort right sortKey="temp" sort={sort} onSort={setSort}>Темп.</ThSort>
                    <ThSort right sortKey="water" sort={sort} onSort={setSort}>Вода</ThSort>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <GroupBlock key={g.key} group={g} tol={tol} tols={tols} onPick={setPicked} sort={sort} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {data.rows_truncated && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Показаны первые {nf0.format(data.rows.length)} из {nf0.format(data.rows_total)} строк —
              сузьте период или АЗС в фильтре сверху.
            </p>
          )}
          <p className="mt-2 text-[11px] text-muted-foreground">
            Расхождение книги с фактом — это состояние резервуара, а не итог смены:
            в «Расхожд. кон.» сидит и всё, что накопилось раньше. Что произошло
            именно в эту смену, показывает <b>Δ за смену</b> = расхождение на конец
            минус на начало. Растущая недостача сменами подряд — это убыль или утечка,
            а разовый скачок — событие (слив, правка, сбой замера).
            Красным — сломанная арифметика отчёта или недостача; жёлтым — излишек и
            разрыв стыка. Замер уровнемера имеет погрешность, поэтому расхождение
            до {nf0.format(tol)} л не подсвечивается.
            В столбце «Стык» указана причина разрыва: <span className="text-blue-600 dark:text-blue-400">слив
            между сменами</span> (накладная закрыта в промежутке — объём не попал в приход) и перенумерация
            смен объяснены и разбора не требуют; <span className="text-amber-600 dark:text-amber-400">списано
            на станции</span>, <span className="text-amber-600 dark:text-amber-400">ручная правка</span> и
            <span className="text-red-600 dark:text-red-400"> сброс книги</span> — правки мимо учёта.
            Наведите курсор на причину, чтобы увидеть подробность (номер ТТН, объём, номера смен).
          </p>
        </div>
      )}

      {/* ── Итог по резервуарам за период ────────────────────────────── */}
      {view === 'tanks' && (
        <div className="mt-3">
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[1100px] text-xs">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <Th>АЗС</Th><Th>Резервуар</Th><Th>Топливо</Th>
                  <Th right>Книга нач.</Th><Th right>Приход</Th><Th right>Отпуск</Th>
                  <Th right>Книга кон.</Th><Th right>Факт</Th><Th right>Книга − факт</Th>
                  <Th right>Оформлено</Th><Th right>К разбору</Th>
                  <Th right>Было на входе</Th><Th right>Смен</Th><Th>Замечания</Th>
                </tr>
              </thead>
              <tbody>
                {data.tanks.map((tank) => (
                  <tr
                    key={`${tank.station_code}:${tank.tank_number}`}
                    tabIndex={0}
                    aria-haspopup="dialog"
                    onClick={() => setPickedTank(tank)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPickedTank(tank) }
                    }}
                    className="cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <Td>{tank.station_name}</Td>
                    <Td>№{tank.tank_number}</Td>
                    <Td>{tank.fuel_name}</Td>
                    <Td right>{L(tank.book_start)}</Td>
                    <Td right>{L(tank.receipts)}</Td>
                    <Td right>{L(tank.sales)}</Td>
                    <Td right>{L(tank.book_end)}</Td>
                    <Td right>{L(tank.fact_end)}</Td>
                    <Td right className={cn('font-medium', gapTone(tank.fact_gap, tol))}>
                      {gapLabel(tank.fact_gap)}
                      {tank.fact_gap_pct != null && (
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          {nf3.format(Math.abs(tank.fact_gap_pct))}%
                        </span>
                      )}
                    </Td>
                    {/* Оформлено ведомостью — и что осталось к разбору. Иначе уже
                        списанная недостача выглядит непогашенной и её списывают дважды. */}
                    <Td right className="text-muted-foreground">
                      {tank.inventory_adjustment != null ? (
                        <span title={tank.inventory_date ? `ведомость от ${tank.inventory_date}` : undefined}>
                          {nf0.format(Math.abs(tank.inventory_adjustment))} л
                          <span className="ml-1 text-[10px]">
                            {tank.inventory_adjustment > 0 ? 'оприходовано' : 'списано'}
                          </span>
                        </span>
                      ) : '—'}
                    </Td>
                    <Td right className={cn('font-medium', gapTone(tank.fact_gap_open, tol))}>
                      {gapLabel(tank.fact_gap_open)}
                    </Td>
                    <Td right className="text-muted-foreground">{gapLabel(tank.fact_gap_opening)}</Td>
                    <Td right>{tank.shifts}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {tank.arithmetic_breaks > 0 && (
                          <Badge variant="outline" className="border-red-400/50 text-red-300/80">
                            арифметика {tank.arithmetic_breaks}
                          </Badge>
                        )}
                        {tank.continuity_breaks > 0 && (
                          <Badge variant="outline" className="border-amber-400/50 text-amber-300/80">
                            стык {tank.continuity_breaks}
                          </Badge>
                        )}
                        {tank.fact_breaks > 0 && (
                          <Badge variant="outline" className="border-zinc-600 text-zinc-400">
                            замер {tank.fact_breaks}
                          </Badge>
                        )}
                        {tank.arithmetic_breaks + tank.continuity_breaks + tank.fact_breaks === 0 && (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            «Книга − факт» — всё накопленное расхождение: книга в источнике к замеру не
            приводится, и уже списанное продолжает в нём сидеть. «Оформлено» — что закрыто
            проведёнными ведомостями, «К разбору» — что набежало после последней из них;
            именно эта цифра идёт в следующую инвентаризацию. «Было на входе» — с каким
            расхождением резервуар вошёл в период: если оно близко к текущему, вопрос
            старый и решается ведомостью, а не поиском утечки.
          </p>
        </div>
      )}

      {/* ── Замечания по типам ───────────────────────────────────────── */}
      {view === 'issues' && (
        <div className="mt-3">
          <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-3">
            <Cell label="Арифметика отчёта" value={nf0.format(t.arithmetic_breaks)}
                  hint="начало + приход − отпуск ≠ конец" tone={t.arithmetic_breaks ? 'text-red-600 dark:text-red-400' : undefined} />
            <Cell label="Стык смен" value={nf0.format(t.continuity_breaks)}
                  hint="начало ≠ конец предыдущей смены" tone={t.continuity_breaks ? 'text-amber-600 dark:text-amber-400' : undefined} />
            <Cell label="Расхождение с замером" value={nf0.format(t.fact_breaks)}
                  hint={`свыше ${nf0.format(tol)} л за смену`} />
          </div>

          {/* Разрывы по причинам. «760 разрывов» одной цифрой не говорят, что делать:
              перенумерация станции и молчаливое списание — разные адресаты и разные
              решения, а топлива касается только часть из них. */}
          {t.continuity_kinds && Object.keys(t.continuity_kinds).length > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5 rounded-lg border border-border/70 bg-card/60 px-3 py-2">
              <span className="mr-1 text-[11px] uppercase tracking-wider text-muted-foreground">
                Стык смен — по причинам
              </span>
              {Object.entries(t.continuity_kinds)
                .sort((a, b) => b[1].count - a[1].count)
                .map(([kind, agg]) => {
                  const meta = BREAK_KINDS[kind]
                  return (
                    <span key={kind}
                      title={`${nf0.format(agg.count)} разрывов на ${nf0.format(Math.abs(agg.liters))} л суммарно`}
                      className={cn('rounded-md border px-2 py-0.5 text-[11px]',
                        meta?.hard ? 'border-amber-500/40 text-amber-500' : 'border-border text-muted-foreground')}>
                      {meta?.label ?? kind}{' '}
                      <span className="tabular-nums">{nf0.format(agg.count)}</span>
                      <span className="ml-1 opacity-70">· {nf0.format(Math.abs(agg.liters))} л</span>
                    </span>
                  )
                })}
              <span className="ml-auto text-[11px] text-muted-foreground">
                подсвечено янтарным — требует решения; остальное объяснено событиями станции
              </span>
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[1000px] text-xs">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <Th>Тип</Th><Th>Причина</Th><Th>АЗС</Th><Th>Резервуар</Th><Th>Смена</Th><Th>Дата</Th>
                  <Th right>Расхождение</Th><Th>Что не сходится</Th>
                </tr>
              </thead>
              <tbody>
                {data.issues.map((issue, i) => (
                  // Замечание — это всегда конкретный резервуар: строка ведёт в его
                  // разбор, а не оставляет менеджера искать его в журнале руками.
                  <tr
                    key={i}
                    tabIndex={0}
                    aria-haspopup="dialog"
                    onClick={() => setPickedTank({
                      station_code: issue.station_code, tank_number: issue.tank_number,
                      station_name: issue.station_name, fuel_name: issue.fuel_name,
                    })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setPickedTank({
                          station_code: issue.station_code, tank_number: issue.tank_number,
                          station_name: issue.station_name, fuel_name: issue.fuel_name,
                        })
                      }
                    }}
                    className="cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <Td>
                      <Badge variant="outline" className={
                        issue.type === 'arithmetic' ? 'border-red-400/50 text-red-300/80'
                          : issue.type === 'fuel_change' ? 'border-blue-400/50 text-blue-300/80'
                            : 'border-amber-400/50 text-amber-300/80'}>
                        {issue.type === 'arithmetic' ? 'арифметика'
                          : issue.type === 'fuel_change' ? 'смена топлива' : 'стык смен'}
                      </Badge>
                    </Td>
                    {/* Причина — то, что превращает «разрыв 22 642 л» из бреда в
                        событие: перенумерацию станции не ищут как утечку. */}
                    <Td>
                      {issue.kind ? (
                        <span className={cn('whitespace-nowrap', BREAK_KINDS[issue.kind]?.tone ?? 'text-muted-foreground')}>
                          {BREAK_KINDS[issue.kind]?.label ?? issue.kind}
                        </span>
                      ) : <span className="text-muted-foreground">—</span>}
                    </Td>
                    <Td>{issue.station_name}</Td>
                    <Td>№{issue.tank_number} · {issue.fuel_name}</Td>
                    <Td>№{issue.shift_number}</Td>
                    <Td>{issue.date ? new Date(issue.date).toLocaleDateString('ru-RU') : '—'}</Td>
                    <Td right className="font-medium">{nf1.format(issue.gap_liters)} л</Td>
                    <Td className="text-muted-foreground">
                      {issue.detail}
                      {issue.reason && (
                        <span className="mt-0.5 block text-[11px] text-foreground/70">{issue.reason}</span>
                      )}
                    </Td>
                  </tr>
                ))}
                {data.issues.length === 0 && (
                  <tr><td colSpan={8} className="p-6 text-center text-muted-foreground">
                    Замечаний нет: книга сходится и стыкуется между сменами
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          {data.issues_total > data.issues.length && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Показаны {data.issues.length} из {data.issues_total} — сузьте период или АЗС.
            </p>
          )}
        </div>
      )}

      {/* Разбор строки журнала: три контроля раздельно + накладные, масса, физика. */}
      <TankShiftDialog row={picked} tol={tol} onClose={() => setPicked(null)} />
      {/* Разбор резервуара: свою историю карточка грузит сама — журнал режется на
          5 000 строках, и у станции с сотнями смен её строк в нём не оказывается. */}
      <TankCardDialog
        target={pickedTank}
        tol={tol}
        companyId={companyId}
        dateFrom={dateFrom}
        dateTo={dateTo}
        onClose={() => setPickedTank(null)}
        onPickShift={(r) => setPicked(r)}
      />
    </div>
  )
}

/** Блок одного резервуара в журнале: заголовок-итог + смены подряд. */
function GroupBlock({ group, tol, tols, onPick, sort }: {
  group: Group; tol: number; tols: Tols
  onPick: (r: TankLedgerRow) => void; sort: Sort | null
}) {
  const { tank, head, rows: srcRows } = group
  const rows = useMemo(() => sortRows(srcRows, sort), [srcRows, sort])
  return (
    <>
      {/* Разделитель-заголовок группы: какой резервуар и его итог за период. */}
      <tr className="border-t-2 border-border bg-muted/30">
        <td colSpan={15} className="px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-semibold">
              {head.station_name} · резервуар №{head.tank_number} · {head.fuel_name}
            </span>
            {tank && (
              <>
                <span className="text-[11px] text-muted-foreground">{tank.shifts} смен</span>
                <span className={cn('text-[11px] font-medium', gapTone(tank.fact_gap, tol))}>
                  за период: книга − факт {gapLabel(tank.fact_gap)}
                </span>
                {(tank.arithmetic_breaks > 0 || tank.continuity_breaks > 0) && (
                  <span className="text-[11px] text-muted-foreground">
                    {tank.arithmetic_breaks > 0 && <span className="text-red-500">арифметика {tank.arithmetic_breaks}</span>}
                    {tank.arithmetic_breaks > 0 && tank.continuity_breaks > 0 && ' · '}
                    {tank.continuity_breaks > 0 && <span className="text-amber-500">стык {tank.continuity_breaks}</span>}
                  </span>
                )}
              </>
            )}
          </div>
        </td>
      </tr>
      {rows.map((r) => {
        const ariBad = Math.abs(r.arithmetic_gap) > tols.ari
        const contBad = r.continuity_gap != null && Math.abs(r.continuity_gap) > tols.cont
        return (
          <tr
            key={`${r.shift_number}:${r.opened_at}`}
            onClick={() => onPick(r)}
            title="Открыть разбор смены по резервуару"
            className={cn(
              'cursor-pointer border-t hover:bg-muted/50',
              ariBad && 'bg-red-500/5',
              !ariBad && (contBad || r.fuel_changed) && 'bg-amber-500/5',
            )}
          >
            <Td>№{r.shift_number}</Td>
            <Td>{r.opened_at ? new Date(r.opened_at).toLocaleDateString('ru-RU') : '—'}</Td>
            <Td right>{L1(r.book_start)}</Td>
            <Td right className={ariBad ? 'font-medium text-red-600 dark:text-red-400' : ''}>
              {L1(r.book_end)}
              {ariBad && (
                <span className="ml-1 text-[10px]">(счёт {nf1.format(r.arithmetic_gap)})</span>
              )}
            </Td>
            {/* Стык: начало ЭТОЙ смены против конца предыдущей. Первая смена
                периода — сравнивать не с чем. */}
            <Td>
              {r.continuity_gap == null ? (
                <span className="text-muted-foreground">начало периода</span>
              ) : contBad || r.fuel_changed ? (
                (() => {
                  const k = BREAK_KINDS[r.continuity_kind ?? (r.fuel_changed ? 'fuel_change' : 'unexplained')]
                    ?? BREAK_KINDS.unexplained
                  return (
                    <span className={k.hard ? `font-medium ${k.tone}` : k.tone} title={r.continuity_reason ?? undefined}>
                      {k.label}
                      {contBad && <span className="ml-1 text-[10px] opacity-80">{nf1.format(r.continuity_gap)} л</span>}
                    </span>
                  )
                })()
              ) : (
                <span className="text-muted-foreground">✓ сходится</span>
              )}
            </Td>
            <Td right className={r.receipts > 0 ? 'text-blue-600 dark:text-blue-400' : ''}>
              {r.receipts > 0 ? L1(r.receipts) : '—'}
            </Td>
            <Td right>{L1(r.sales)}</Td>
            <Td right className="text-muted-foreground">{r.fact_start != null ? L1(r.fact_start) : '—'}</Td>
            <Td right>{r.fact_end != null ? L1(r.fact_end) : '—'}</Td>
            {/* Расхождение на входе и на выходе — это СОСТОЯНИЕ (в нём сидит
                накопленное ранее), а Δ — то, что произошло именно в эту смену.
                Без разделения одна цифра «книга − факт» читается как результат
                смены, хотя может годами тянуться с прошлого. */}
            <Td right className={cn(gapTone(r.fact_gap_start, tol), 'text-[11px]')}>
              {gapLabel(r.fact_gap_start)}
            </Td>
            <Td right className={cn('font-medium', gapTone(r.fact_gap, tol))}>
              {gapLabel(r.fact_gap)}
            </Td>
            <Td right className={cn('font-medium', gapTone(r.fact_gap_delta, tol))}>
              {r.fact_gap_delta == null ? '—'
                : Math.abs(r.fact_gap_delta) < 0.05 ? 'без изменений'
                : `${r.fact_gap_delta > 0 ? '+' : '−'}${nf0.format(Math.abs(r.fact_gap_delta))} л`}
            </Td>
            <Td right className="text-muted-foreground">
              {r.density_end != null ? nf3.format(r.density_end) : '—'}
            </Td>
            <Td right className="text-muted-foreground">
              {r.temp_end != null ? `${nf1.format(r.temp_end)}°` : '—'}
            </Td>
            <Td right className={r.water_volume ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
              {r.water_volume ? L1(r.water_volume) : '—'}
            </Td>
          </tr>
        )
      })}
    </>
  )
}

function Cell({ label, value, hint, tone }: {
  label: string; value: string; hint?: string; tone?: string
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('mt-0.5 text-sm font-semibold', tone)}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={cn('p-2.5 font-medium', right ? 'text-right' : 'text-left')}>{children}</th>
}

/* ── Сортировка журнала ──────────────────────────────────────────────────
   Сортируем ВНУТРИ резервуара, а не сквозь всю таблицу: журнал — это лента
   движения по конкретной ёмкости, где строки связаны цепочкой. Сквозная
   сортировка смешала бы резервуары и разорвала эту связь.
   «Стык» и «Δ за смену» посчитаны на сервере относительно предыдущей смены
   ПО ВРЕМЕНИ — при другом порядке они остаются верными, но соседняя строка
   в таблице уже не та, с которой шло сравнение. Об этом предупреждаем. */
type SortKey = 'shift' | 'book_start' | 'book_end' | 'continuity' | 'receipts' | 'sales'
  | 'fact_start' | 'fact_end' | 'gap_start' | 'gap_end' | 'gap_delta'
  | 'density' | 'temp' | 'water'

const SORT_VALUE: Record<SortKey, (r: TankLedgerRow) => number | null> = {
  shift: (r) => r.opened_at ? Date.parse(r.opened_at) : r.shift_number,
  book_start: (r) => r.book_start,
  book_end: (r) => r.book_end,
  // По стыку и расхождениям сортируем по МОДУЛЮ: ищут «где сильнее разошлось»,
  // а не «где самое отрицательное» — иначе крупный излишек уходит в конец списка.
  continuity: (r) => r.continuity_gap == null ? null : Math.abs(r.continuity_gap),
  receipts: (r) => r.receipts,
  sales: (r) => r.sales,
  fact_start: (r) => r.fact_start,
  fact_end: (r) => r.fact_end,
  gap_start: (r) => r.fact_gap_start == null ? null : Math.abs(r.fact_gap_start),
  gap_end: (r) => r.fact_gap == null ? null : Math.abs(r.fact_gap),
  gap_delta: (r) => r.fact_gap_delta == null ? null : Math.abs(r.fact_gap_delta),
  density: (r) => r.density_end,
  temp: (r) => r.temp_end,
  water: (r) => r.water_volume,
}

type Sort = { key: SortKey; dir: 'asc' | 'desc' }

const SORT_LABEL: Record<SortKey, string> = {
  shift: 'смена', book_start: 'книга на начало', book_end: 'книга на конец',
  continuity: 'стык (по модулю)', receipts: 'приход', sales: 'отпуск',
  fact_start: 'факт на начало', fact_end: 'факт на конец',
  gap_start: 'расхождение на начало (по модулю)', gap_end: 'расхождение на конец (по модулю)',
  gap_delta: 'Δ за смену (по модулю)', density: 'плотность', temp: 'температура', water: 'вода',
}

function sortRows(rows: TankLedgerRow[], sort: Sort | null): TankLedgerRow[] {
  if (!sort) return rows
  const get = SORT_VALUE[sort.key]
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = get(a), vb = get(b)
    // Пустые значения всегда внизу — при любом направлении. Иначе колонка
    // с пропусками (нет замера) выглядит как «самые проблемные сверху».
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    return (va - vb) * sign
  })
}

/** Кликабельный заголовок: 1-й клик — по убыванию (сверху самое крупное),
 *  2-й — по возрастанию, 3-й — возврат к хронологии. */
function ThSort({ children, right, sortKey, sort, onSort }: {
  children: React.ReactNode; right?: boolean; sortKey: SortKey
  sort: Sort | null; onSort: (s: Sort | null) => void
}) {
  const active = sort?.key === sortKey
  const next = (): Sort | null =>
    !active ? { key: sortKey, dir: 'desc' }
      : sort!.dir === 'desc' ? { key: sortKey, dir: 'asc' }
        : null
  return (
    <th
      onClick={() => onSort(next())}
      title={active ? (sort!.dir === 'desc' ? 'по убыванию · клик — по возрастанию'
        : 'по возрастанию · клик — вернуть хронологию') : 'Сортировать внутри резервуара'}
      className={cn('cursor-pointer select-none p-2.5 font-medium hover:text-foreground',
        right ? 'text-right' : 'text-left', active && 'text-foreground')}
    >
      <span className={cn('inline-flex items-center gap-1', right && 'flex-row-reverse')}>
        {children}
        <span className={cn('text-[9px]', active ? 'opacity-100' : 'opacity-25')}>
          {active ? (sort!.dir === 'desc' ? '▼' : '▲') : '▽'}
        </span>
      </span>
    </th>
  )
}

function Td({ children, right, className }: {
  children: React.ReactNode; right?: boolean; className?: string
}) {
  return <td className={cn('p-2.5', right ? 'text-right tabular-nums' : '', className)}>{children}</td>
}
