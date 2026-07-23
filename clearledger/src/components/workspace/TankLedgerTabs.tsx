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

const ARI_TOL = 0.5   // арифметика книги — это счёт, любое отклонение = ошибка отчёта
const CONT_TOL = 0.5  // стык смен — тоже счёт, не измерение

/** Есть ли в смене «жёсткое» замечание — сломанный счёт (не погрешность замера). */
function hasHardIssue(r: TankLedgerRow): boolean {
  return Math.abs(r.arithmetic_gap) > ARI_TOL
    || (r.continuity_gap != null && Math.abs(r.continuity_gap) > CONT_TOL)
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
    'Приход, л': r1(r.receipts),
    'Отпуск, л': r1(r.sales),
    'Книга кон., л': r1(r.book_end),
    'Счёт (арифметика), л': r1(r.arithmetic_gap),
    'Факт (замер), л': r1(r.fact_end),
    'Книга − факт, л': r1(r.fact_gap),
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

  const query = useQuery({
    queryKey: ['tank-ledger', companyId, dateFrom, dateTo, stationCodes.join(','), fuelCodes.join(',')],
    queryFn: () => getTankLedger({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }),
    placeholderData: keepPreviousData,
  })

  const data = query.data
  const tol = data?.tolerances.fact_liters ?? 50

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
    const contBad = (r: TankLedgerRow) => r.continuity_gap != null && Math.abs(r.continuity_gap) > CONT_TOL
    const ariBad = (r: TankLedgerRow) => Math.abs(r.arithmetic_gap) > ARI_TOL
    const factBad = (r: TankLedgerRow) => r.fact_gap != null && Math.abs(r.fact_gap) > tol
    return (r: TankLedgerRow): boolean => {
      switch (fIssue) {
        case 'issues': return hasHardIssue(r)
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
          hint={`${nf3.format(Math.abs(t.fact_gap_pct))}% от отпуска`}
          tone={gapTone(t.fact_gap, tol)}
        />
      </div>

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
              <table className="w-full min-w-[1120px] text-xs">
                <thead className="bg-muted/40 text-muted-foreground">
                  <tr>
                    <Th>Смена</Th><Th>Дата</Th>
                    <Th right>Книга нач.</Th><Th right>Книга кон.</Th><Th>Стык</Th>
                    <Th right>Приход</Th><Th right>Отпуск</Th>
                    <Th right>Факт</Th><Th right>Книга − факт</Th>
                    <Th right>Плотн.</Th><Th right>Темп.</Th><Th right>Вода</Th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <GroupBlock key={g.key} group={g} tol={tol} />
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
            Красным — сломанная арифметика отчёта или расхождение книги с фактом
            (недостача); жёлтым — излишек и разрыв стыка. Замер уровнемера имеет
            погрешность, поэтому расхождение книги с фактом до {nf0.format(tol)} л не подсвечивается.
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
                  <Th right>Было на входе</Th><Th right>Смен</Th><Th>Замечания</Th>
                </tr>
              </thead>
              <tbody>
                {data.tanks.map((tank) => (
                  <tr key={`${tank.station_code}:${tank.tank_number}`} className="border-t">
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
            «Было на входе» — с каким расхождением резервуар вошёл в период. Если оно
            близко к текущему, значит за период ничего не изменилось: вопрос старый и
            решается инвентаризацией, а не поиском утечки.
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
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[900px] text-xs">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <Th>Тип</Th><Th>АЗС</Th><Th>Резервуар</Th><Th>Смена</Th><Th>Дата</Th>
                  <Th right>Расхождение</Th><Th>Что не сходится</Th>
                </tr>
              </thead>
              <tbody>
                {data.issues.map((issue, i) => (
                  <tr key={i} className="border-t">
                    <Td>
                      <Badge variant="outline" className={
                        issue.type === 'arithmetic' ? 'border-red-400/50 text-red-300/80'
                          : issue.type === 'fuel_change' ? 'border-blue-400/50 text-blue-300/80'
                            : 'border-amber-400/50 text-amber-300/80'}>
                        {issue.type === 'arithmetic' ? 'арифметика'
                          : issue.type === 'fuel_change' ? 'смена топлива' : 'стык смен'}
                      </Badge>
                    </Td>
                    <Td>{issue.station_name}</Td>
                    <Td>№{issue.tank_number} · {issue.fuel_name}</Td>
                    <Td>№{issue.shift_number}</Td>
                    <Td>{issue.date ? new Date(issue.date).toLocaleDateString('ru-RU') : '—'}</Td>
                    <Td right className="font-medium">{nf1.format(issue.gap_liters)} л</Td>
                    <Td className="text-muted-foreground">{issue.detail}</Td>
                  </tr>
                ))}
                {data.issues.length === 0 && (
                  <tr><td colSpan={7} className="p-6 text-center text-muted-foreground">
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
    </div>
  )
}

/** Блок одного резервуара в журнале: заголовок-итог + смены подряд. */
function GroupBlock({ group, tol }: { group: Group; tol: number }) {
  const { tank, head, rows } = group
  return (
    <>
      {/* Разделитель-заголовок группы: какой резервуар и его итог за период. */}
      <tr className="border-t-2 border-border bg-muted/30">
        <td colSpan={12} className="px-2.5 py-2">
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
        const ariBad = Math.abs(r.arithmetic_gap) > ARI_TOL
        const contBad = r.continuity_gap != null && Math.abs(r.continuity_gap) > CONT_TOL
        return (
          <tr
            key={`${r.shift_number}:${r.opened_at}`}
            className={cn(
              'border-t',
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
              {r.fuel_changed ? (
                <span className="text-blue-600 dark:text-blue-400">смена топлива</span>
              ) : r.continuity_gap == null ? (
                <span className="text-muted-foreground">начало периода</span>
              ) : contBad ? (
                <span className="font-medium text-amber-600 dark:text-amber-400">
                  разрыв {nf1.format(r.continuity_gap)} л
                </span>
              ) : (
                <span className="text-muted-foreground">✓ сходится</span>
              )}
            </Td>
            <Td right className={r.receipts > 0 ? 'text-blue-600 dark:text-blue-400' : ''}>
              {r.receipts > 0 ? L1(r.receipts) : '—'}
            </Td>
            <Td right>{L1(r.sales)}</Td>
            <Td right>{L1(r.fact_end)}</Td>
            <Td right className={cn('font-medium', gapTone(r.fact_gap, tol))}>
              {gapLabel(r.fact_gap)}
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

function Td({ children, right, className }: {
  children: React.ReactNode; right?: boolean; className?: string
}) {
  return <td className={cn('p-2.5', right ? 'text-right tabular-nums' : '', className)}>{children}</td>
}
