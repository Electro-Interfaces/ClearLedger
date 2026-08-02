/**
 * Разбор резервуара — «откуда взялось расхождение и в какой смене оно возникло».
 *
 * Панель немодальная: расхождения смотрят подряд по нескольким резервуарам, и
 * закрывать окно ради того, чтобы увидеть следующую строку, незачем.
 *
 * Данные грузятся СВОИМ запросом по (АЗС, резервуар), а не берутся из журнала:
 * журнал режется на 5 000 строках, и у станции с двумя сотнями смен строк в нём
 * не оказывается — карточка показывала пустые условия замера и раскладку «всё
 * сходится» при расхождении в тысячи литров.
 *
 * Порядок разбора сверху вниз:
 *   1. итог — сколько числится, сколько намерено, что к разбору;
 *   2. когда возникло — по месяцам и первая смена с расхождением: без этого
 *      «6 632 л излишек» не привязан ни к чему;
 *   3. из чего сложилось — дефекты учёта, сливы, рабочие смены;
 *   4. динамика, условия замера, накладные, смены-виновники.
 */
import { formatBucket } from '@/lib/formatDate'
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts'
import { AlertTriangle, Droplets, Loader2, Thermometer } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { DetailPane } from './DetailPane'
import { cn } from '@/lib/utils'
import {
  getTankLedger, getVarianceDiagnostics, type TankLedgerRow, type TankLedgerTank,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const L = (v: number | null | undefined) => (v == null ? '—' : `${nf0.format(v)} л`)
const gapWord = (v: number | null | undefined) =>
  v == null ? '—'
    : Math.abs(v) < 0.5 ? 'сходится'
    : `${nf0.format(Math.abs(v))} л ${v > 0 ? 'недостача' : 'излишек'}`
const gapTone = (v: number | null | undefined, tol = 50) =>
  v == null || Math.abs(v) <= tol ? 'text-muted-foreground'
    : v > 0 ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'


/** Причины разрыва, которые считаем дефектом учёта, а не движением топлива. */
const DEFECT_KINDS = new Set(['book_reset', 'manual', 'pulled_to_fact', 'renumber', 'unexplained'])

/** Резервуар, по которому открыт разбор: кода АЗС и номера достаточно. */
export type TankRef = {
  station_code: number
  tank_number: number
  station_name?: string
  fuel_name?: string
}

export function TankCardDialog({ target, tol, companyId, dateFrom, dateTo, onClose, onPickShift }: {
  target: TankRef | null
  tol: number
  companyId: string
  dateFrom: string
  dateTo: string
  onClose: () => void
  /** Клик по смене — открыть её разбор (журнал строки). */
  onPickShift?: (row: TankLedgerRow) => void
}) {
  const open = !!target
  const q = useQuery({
    queryKey: ['tank-ledger-one', companyId, dateFrom, dateTo, target?.station_code, target?.tank_number],
    queryFn: () => getTankLedger({
      companyId, dateFrom, dateTo,
      stationCodes: target ? [target.station_code] : [],
      tankNumber: target?.tank_number,
    }),
    enabled: open,
    staleTime: 60_000,
  })
  const diag = useQuery({
    queryKey: ['variance-diag', companyId, dateFrom, dateTo, target?.station_code],
    queryFn: () => getVarianceDiagnostics({
      companyId, dateFrom, dateTo, stationCodes: target ? [target.station_code] : [],
    }),
    enabled: open,
    staleTime: 60_000,
  })

  const tank: TankLedgerTank | null = useMemo(() => (q.data?.tanks ?? []).find(
    (t) => t.station_code === target?.station_code && t.tank_number === target?.tank_number) ?? null,
    [q.data, target])
  const rows = useMemo(() => (q.data?.rows ?? []).filter(
    (r) => r.station_code === target?.station_code && r.tank_number === target?.tank_number),
    [q.data, target])
  const nature = useMemo(() => (diag.data?.tanks ?? []).find(
    (t) => t.station_code === target?.station_code && t.tank_number === target?.tank_number),
    [diag.data, target])

  /** Сколько расхождения набежало в каждом месяце и где оно скакнуло.
   *  Смены с разрывом цепочки (перенумерация, обнуление книги, смена топлива) в
   *  прирост НЕ входят: там замер и книга из разных историй резервуара. */
  const byMonth = useMemo(() => {
    const acc = new Map<string, {
      delta: number; shifts: number; measured: number
      /** Состояние на конец месяца — последнее измеренное расхождение. Именно оно
       *  переходит в следующий месяц; складывать состояния нельзя. */
      state: number | null
      jump: TankLedgerRow | null; chain: TankLedgerRow | null
    }>()
    for (const r of rows) {
      if (!r.opened_at) continue
      const ym = r.opened_at.slice(0, 7)
      const e = acc.get(ym) ?? { delta: 0, shifts: 0, measured: 0, state: null, jump: null, chain: null }
      e.shifts += 1
      if (r.chain_break) e.chain = r
      if (r.fact_gap != null) e.state = r.fact_gap
      if (r.fact_gap_delta != null) {
        e.delta += r.fact_gap_delta
        e.measured += 1
        if (!e.jump || Math.abs(r.fact_gap_delta) > Math.abs(e.jump.fact_gap_delta ?? 0)) e.jump = r
      }
      acc.set(ym, e)
    }
    return [...acc.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [rows])

  /** Разрывы цепочки: где история резервуара начиналась заново. */
  const chainRows = useMemo(() => rows.filter((r) => r.chain_break), [rows])
  const chainJumpSum = chainRows.reduce((s, r) => s + (r.chain_jump ?? 0), 0)
  /** Месяц последнего перезапуска учёта: месяцы раньше него к итогу не относятся. */
  const resetMonth = chainRows.length
    ? chainRows[chainRows.length - 1].opened_at?.slice(0, 7) ?? null
    : null

  /** Дата смены — «смена №4» после перенумерации сама по себе ничего не говорит. */
  const shiftDate = (r: TankLedgerRow) =>
    r.opened_at ? new Date(r.opened_at).toLocaleDateString('ru-RU') : '—'

  /** Первая смена периода, где расхождение уже перешло допуск — точка появления. */
  const firstBad = useMemo(() => rows.find(
    (r) => r.fact_gap != null && Math.abs(r.fact_gap) > tol) ?? null, [rows, tol])
  const noFact = useMemo(() => rows.filter((r) => r.fact_end == null).length, [rows])

  /** Раскладка расхождения. Считается от ТОЧКИ ОТСЧЁТА: это начало периода, а если
   *  учёт по резервуару начинался заново — первая смена после последнего разрыва.
   *  Складывать приросты через разрыв нельзя: до и после него книга описывает разные
   *  истории, и сумма не сходится с итогом (у АЗС 8 рез.6 расходилась на 12 тыс. л). */
  const parts = useMemo(() => {
    if (!tank) return []
    const lastResetIdx = rows.reduce((acc, r, i) => (r.chain_break ? i : acc), -1)
    const tail = lastResetIdx >= 0 ? rows.slice(lastResetIdx) : rows
    // База: расхождение на первой смене нового отсчёта (после разрыва) либо то, с
    // которым резервуар вошёл в период.
    const base = lastResetIdx >= 0
      ? (tail.find((r) => r.fact_gap != null)?.fact_gap ?? 0)
      : (tank.fact_gap_opening ?? 0)

    let defects = 0, onReceipts = 0, clean = 0
    // Прирост базовой смены уже сидит в `base` — считаем со следующей.
    for (const r of tail.slice(1)) {
      const d = r.fact_gap_delta
      if (d == null) continue
      const broken = Math.abs(r.arithmetic_gap) > 0.5
        || (r.continuity_kind != null && DEFECT_KINDS.has(r.continuity_kind))
      if (broken) defects += d
      else if (r.receipts > 1) onReceipts += d
      else clean += d
    }
    return [
      {
        key: 'base',
        label: lastResetIdx >= 0 ? 'На старте нового учёта' : 'Было на входе',
        value: base,
        defect: false,
        hint: lastResetIdx >= 0
          ? `с этим расхождением резервуар пошёл после перезапуска учёта ${shiftDate(rows[lastResetIdx])} — прошлая история к нему не складывается`
          : 'расхождение пришло из прошлого периода — вопрос не этого разбора',
      },
      { key: 'defects', label: 'Дефекты учёта', value: defects, defect: true,
        hint: 'смены со сломанной арифметикой, разрывом стыка или ручной правкой: правится в отчётах, а не списанием' },
      { key: 'receipts', label: 'В сменах со сливом', value: onReceipts, defect: false,
        hint: 'набежало в смены с приёмкой — проверить недолив по ТТН и синхронность замера со сливом' },
      { key: 'clean', label: 'В рабочих сменах', value: clean, defect: false,
        hint: 'чистые смены: погрешность замера, температурное дыхание, естественная убыль, пролив' },
    ]
  }, [tank, rows])

  // Ось — ДАТА, а не номер смены: после перенумерации номера идут 7331, 4, 5…,
  // и график читался как прыжок назад во времени.
  const chart = useMemo(() => rows
    .filter((r) => r.fact_end != null)
    .map((r) => ({
      x: r.opened_at ? r.opened_at.slice(0, 10) : String(r.shift_number),
      shift: r.shift_number,
      Книга: Math.round(r.book_end),
      Замер: Math.round(r.fact_end as number),
    })), [rows])

  const worstShifts = useMemo(() => rows
    .filter((r) => r.fact_gap_delta != null && Math.abs(r.fact_gap_delta) > tol)
    .sort((a, b) => Math.abs(b.fact_gap_delta as number) - Math.abs(a.fact_gap_delta as number))
    .slice(0, 8), [rows, tol])

  const physics = useMemo(() => {
    const pick = (f: (r: TankLedgerRow) => number | null) =>
      rows.map(f).filter((v): v is number => v != null)
    const temps = pick((r) => r.temp_end)
    const water = pick((r) => r.water_volume)
    const dens = pick((r) => r.density_end)
    return {
      tempMin: temps.length ? Math.min(...temps) : null,
      tempMax: temps.length ? Math.max(...temps) : null,
      waterMax: water.length ? Math.max(...water) : null,
      waterLast: water.length ? water[water.length - 1] : null,
      densMin: dens.length ? Math.min(...dens) : null,
      densMax: dens.length ? Math.max(...dens) : null,
    }
  }, [rows])

  const receiptsDocs = useMemo(() => rows.flatMap(
    (r) => (r.receipts_docs ?? []).map((d) => ({ ...d, shift: r.shift_number }))), [rows])

  const sumParts = parts.reduce((s, p) => s + p.value, 0)
  const residual = (tank?.fact_gap ?? 0) - sumParts

  return (
    <DetailPane
      open={open}
      title={target
        ? `${tank?.station_name ?? target.station_name ?? `АЗС ${target.station_code}`} · резервуар №${target.tank_number}${tank?.fuel_name ? ` · ${tank.fuel_name}` : ''}`
        : ''}
      // «смены 7326–32» после перенумерации читается как ошибка: номер упал. Пишем
      // диапазон только когда нумерация непрерывна, иначе говорим об этом прямо.
      subtitle={tank
        ? `${tank.shifts} смен · ${chainRows.length > 0
            ? 'нумерация смен прерывалась'
            : `смены ${tank.first_shift}–${tank.last_shift}`} · период ${dateFrom} — ${dateTo}`
        : `период ${dateFrom} — ${dateTo}`}
      badges={nature && (
        <>
          <Badge variant="outline" className="border-primary/40 text-primary">{nature.nature_title}</Badge>
          {Math.abs(nature.trend_per_shift ?? 0) > 0.5 && (
            <span className="text-[11px] text-muted-foreground">
              тренд {nf1.format(nature.trend_per_shift)} л/смену
            </span>
          )}
          {nature.temperature_share >= 0.5 && (
            <Badge variant="outline" className="border-sky-500/40 text-sky-400">объём «дышит» температурой</Badge>
          )}
        </>
      )}
      onClose={onClose}
    >
      {q.isLoading ? (
        <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Собираю историю резервуара…
        </div>
      ) : !tank ? (
        <div className="py-10 text-sm text-muted-foreground">
          За период по этому резервуару нет сменных записей.
        </div>
      ) : (
        <>
          {/* Итог */}
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-4">
            {[
              ['Книга на конец', L(tank.book_end), 'по документам', null],
              ['Замер', L(tank.fact_end), 'уровнемер', null],
              ['Книга − факт', gapWord(tank.fact_gap), 'всё накопленное', tank.fact_gap],
              ['К разбору', gapWord(tank.fact_gap_open), tank.inventory_date
                ? `после ведомости от ${tank.inventory_date}` : 'ведомостей не было', tank.fact_gap_open],
            ].map(([label, value, hint, tone]) => (
              <div key={label as string} className="bg-card px-3 py-2.5">
                <div className="text-[11px] text-muted-foreground">{label}</div>
                <div className={cn('mt-0.5 text-sm font-semibold tabular-nums',
                  tone != null && gapTone(tone as number, tol))}>{value}</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
              </div>
            ))}
          </div>

          {/* КОГДА возникло — без этого итоговая цифра ни к чему не привязана. */}
          <section>
            <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
              Когда возникло
            </h3>
            <p className="mb-2 text-[11px] text-muted-foreground">
              Каждая смена сверяется сама: книга и замер на начало, книга и замер на
              конец. Расхождение — это <b>состояние</b> резервуара («Стало»), оно переходит
              в следующую смену и по сменам НЕ складывается: два месяца по 200 л дают
              не 400, а те же 200. Складывается только <b>изменение</b> — насколько
              состояние выросло или сократилось. Смены без замера в изменение не входят:
              их прирост измерить нечем.
              {resetMonth && ' Месяцы до перезапуска учёта бледные: они относятся к прошлой истории резервуара и к сегодняшнему состоянию не относятся.'}
            </p>
            {firstBad ? (
              <p className="mb-2 text-xs">
                Расхождение впервые вышло за допуск {nf0.format(tol)} л в{' '}
                <button type="button" onClick={() => onPickShift?.(firstBad)}
                  className="font-medium text-primary underline-offset-2 hover:underline">
                  смене №{firstBad.shift_number}
                </button>{' '}
                {firstBad.opened_at && `(${new Date(firstBad.opened_at).toLocaleDateString('ru-RU')})`} —{' '}
                <span className={gapTone(firstBad.fact_gap, tol)}>{gapWord(firstBad.fact_gap)}</span>.
                {' '}Раньше в периоде оно держалось в допуске.
              </p>
            ) : (
              <p className="mb-2 text-xs text-muted-foreground">
                В периоде расхождение ни в одной смене не выходило за допуск {nf0.format(tol)} л.
              </p>
            )}
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-xs">
                <thead className="bg-muted/40 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium">Месяц</th>
                    <th className="px-3 py-1.5 text-right font-medium">Смен</th>
                    <th className="px-3 py-1.5 text-right font-medium"
                        title="Насколько расхождение выросло или сократилось за месяц. Это не сумма расхождений по сменам.">
                      Изменение
                    </th>
                    <th className="px-3 py-1.5 text-right font-medium"
                        title="Состояние резервуара на конец месяца: столько числится сверх факта или недостаёт. Именно оно переходит в следующий месяц — состояния не складываются.">
                      Стало
                    </th>
                    <th className="px-3 py-1.5 text-left font-medium">Наибольший прыжок в месяце</th>
                  </tr>
                </thead>
                <tbody>
                  {byMonth.map(([ym, m]) => (
                    // Месяцы до последнего перезапуска учёта к текущему итогу не
                    // относятся: тогда книга описывала другую историю резервуара.
                    // Гасим их, иначе они читаются как слагаемые сегодняшней цифры.
                    <tr key={ym} className={cn('border-t border-border/50',
                      resetMonth && ym < resetMonth && 'opacity-45')}>
                      <td className="px-3 py-1.5 font-medium">{formatBucket(ym)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {m.shifts}{m.measured < m.shifts && (
                          <span className="ml-1 text-[10px]">({m.shifts - m.measured} без замера)</span>
                        )}
                      </td>
                      <td className={cn('px-3 py-1.5 text-right tabular-nums', gapTone(m.delta, tol))}>
                        {Math.abs(m.delta) < 0.5 ? 'без изменений'
                          : `${m.delta > 0 ? '+' : '−'}${nf0.format(Math.abs(m.delta))} л`}
                      </td>
                      {/* Состояние на конец месяца. Рядом с изменением видно, что
                          расхождение не накапливается сложением: два месяца по
                          «+200 л» не дают 400 — во второй строке стоит то же 200. */}
                      <td className={cn('px-3 py-1.5 text-right font-medium tabular-nums', gapTone(m.state, tol))}>
                        {gapWord(m.state)}
                      </td>
                      <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                        {m.chain && (
                          // Разрыв цепочки в этом месяце — главное объяснение: пока он
                          // не назван, «смена №4 · 11 853 л недостача» выглядит бредом.
                          <button type="button" onClick={() => onPickShift?.(m.chain as TankLedgerRow)}
                            className="mb-0.5 block text-left text-amber-500 underline-offset-2 hover:underline">
                            учёт начат заново: смена №{m.chain.shift_number} от {shiftDate(m.chain)}
                            {m.chain.continuity_kind === 'renumber' ? ' — станцию переустановили, нумерация смен пошла с начала'
                              : m.chain.continuity_kind === 'book_reset' ? ' — книгу обнулили на станции'
                              : m.chain.fuel_changed ? ' — в резервуаре сменилось топливо' : ''}
                          </button>
                        )}
                        {m.jump && Math.abs(m.jump.fact_gap_delta ?? 0) > tol ? (
                          <button type="button" onClick={() => onPickShift?.(m.jump as TankLedgerRow)}
                            className="text-left underline-offset-2 hover:text-foreground hover:underline">
                            смена №{m.jump.shift_number} от {shiftDate(m.jump)} · {gapWord(m.jump.fact_gap_delta)}
                            {m.jump.receipts > 1 && ' · при сливе'}
                            {m.jump.continuity_kind && ` · ${m.jump.continuity_kind === 'delivery' ? 'слив между сменами'
                              : m.jump.continuity_kind === 'manual' ? 'ручная правка'
                              : m.jump.continuity_kind === 'pulled_to_fact' ? 'списано на станции'
                              : m.jump.continuity_kind === 'unexplained' ? 'без объяснения'
                              : m.jump.continuity_kind}`}
                          </button>
                        ) : !m.chain && '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Раскладка */}
          <section>
            <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
              Из чего сложилось расхождение
            </h3>
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-xs">
                <tbody>
                  {parts.map((p) => (
                    <tr key={p.key} className="border-b border-border/60 last:border-b-0">
                      <td className="px-3 py-2 font-medium">
                        {p.label}
                        {p.defect && Math.abs(p.value) > tol && (
                          <AlertTriangle className="ml-1.5 inline h-3 w-3 text-amber-500" />
                        )}
                      </td>
                      <td className={cn('w-36 px-3 py-2 text-right font-medium tabular-nums',
                        gapTone(p.value, tol))}>{gapWord(p.value)}</td>
                      <td className="px-3 py-2 text-[11px] text-muted-foreground">{p.hint}</td>
                    </tr>
                  ))}
                  {chainRows.length > 0 && (
                    // Склейка на разрыве — не топливо и не часть суммы. Показывается
                    // справкой: сколько «прыгнуло» на стыке двух разных историй.
                    <tr className="border-b border-border/60 bg-amber-500/5">
                      <td className="px-3 py-2 font-medium">
                        Учёт начинался заново
                        <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                          {chainRows.length === 1 ? '1 раз' : `${chainRows.length} раза`}
                        </span>
                      </td>
                      <td className="w-36 px-3 py-2 text-right font-medium tabular-nums text-amber-500">
                        скачок {nf0.format(Math.abs(chainJumpSum))} л
                      </td>
                      <td className="px-3 py-2 text-[11px] text-muted-foreground">
                        {chainRows.map((r) => `смена №${r.shift_number} от ${shiftDate(r)}`).join(', ')}
                        {chainRows[0]?.continuity_kind === 'renumber' && ' — станцию переустановили, нумерация смен пошла с начала'}
                        {chainRows[0]?.continuity_kind === 'book_reset' && ' — книгу обнулили на станции'}.
                        {' '}В сумму не входит: замер до разрыва и книга после — разные истории
                        резервуара, списывать эту величину нечего.
                      </td>
                    </tr>
                  )}
                  {tank.inventory_adjustment != null && (
                    <tr className="border-b border-border/60 bg-muted/20">
                      <td className="px-3 py-2 font-medium">Оформлено ведомостями</td>
                      <td className="w-36 px-3 py-2 text-right font-medium tabular-nums text-muted-foreground">
                        {nf0.format(Math.abs(tank.inventory_adjustment))} л{' '}
                        {tank.inventory_adjustment > 0 ? 'оприходовано' : 'списано'}
                      </td>
                      <td className="px-3 py-2 text-[11px] text-muted-foreground">
                        ведомость от {tank.inventory_date} — закрыто документом
                      </td>
                    </tr>
                  )}
                  <tr className="bg-muted/40">
                    <td className="px-3 py-2 font-semibold">Итого «книга − факт»</td>
                    <td className={cn('w-36 px-3 py-2 text-right font-semibold tabular-nums',
                      gapTone(tank.fact_gap, tol))}>{gapWord(tank.fact_gap)}</td>
                    <td className="px-3 py-2 text-[11px] text-muted-foreground">
                      {Math.abs(residual) <= Math.max(tol, Math.abs(tank.fact_gap ?? 0) * 0.02)
                        ? 'раскладка сходится с итогом'
                        : chainRows.length > 0
                          ? `не разложилось ${nf0.format(Math.abs(residual))} л: учёт начинался заново — приросты до и после разрыва между собой не складываются`
                          : noFact > 0
                            ? `не разложилось ${nf0.format(Math.abs(residual))} л: ${noFact} смен без замера — в них прирост посчитать нечем`
                            : `не разложилось ${nf0.format(Math.abs(residual))} л — цепочка смен в периоде неполная`}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          {/* Динамика */}
          {chart.length > 2 && (
            <section>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                Книга и замер по сменам
              </h3>
              <div className="h-44 rounded-lg border p-2">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
                    <XAxis dataKey="x" tick={{ fontSize: 10 }} stroke="currentColor" className="text-muted-foreground"
                           tickFormatter={(v: string) => (v.length === 10
                             ? new Date(v).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) : v)}
                           minTickGap={24} />
                    <YAxis tick={{ fontSize: 10 }} width={52} stroke="currentColor" className="text-muted-foreground" />
                    <RTooltip
                      contentStyle={{ fontSize: 11, borderRadius: 8, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                      formatter={(v, n) => [`${nf0.format(Number(v ?? 0))} л`, n]}
                      labelFormatter={(l, p) => {
                        const shift = (p?.[0]?.payload as { shift?: number } | undefined)?.shift
                        const date = String(l).length === 10 ? new Date(String(l)).toLocaleDateString('ru-RU') : String(l)
                        return shift ? `${date} · смена №${shift}` : date
                      }}
                    />
                    <Line type="monotone" dataKey="Книга" stroke="hsl(var(--primary))" dot={false} strokeWidth={1.5} />
                    <Line type="monotone" dataKey="Замер" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Линии расходятся — расхождение накапливается; идут с постоянным зазором —
                оно старое и держится; разрыв в одной точке — событие смены.
              </p>
            </section>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <section>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">Условия замера</h3>
              <div className="space-y-1.5 rounded-lg border px-3 py-2.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Thermometer className="h-3.5 w-3.5" />температура
                  </span>
                  <span className="tabular-nums">
                    {physics.tempMin != null
                      ? `${nf1.format(physics.tempMin)} … ${nf1.format(physics.tempMax as number)} °C` : '—'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Droplets className="h-3.5 w-3.5" />подтоварная вода
                  </span>
                  <span className={cn('tabular-nums', (physics.waterMax ?? 0) > 20 && 'text-amber-500')}>
                    {physics.waterLast != null
                      ? `${nf1.format(physics.waterLast)} л (макс. ${nf1.format(physics.waterMax as number)})` : '—'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">плотность</span>
                  <span className="tabular-nums">
                    {physics.densMin != null ? `${physics.densMin} … ${physics.densMax}` : '—'}
                  </span>
                </div>
                <p className="pt-1 text-[11px] text-muted-foreground">
                  Вода занимает объём и попадает в замер как топливо. Разброс температуры
                  в 10 °C — около 1% объёма, на 20 м³ это примерно 200 л.
                </p>
              </div>
            </section>

            <section>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                Накладные периода {receiptsDocs.length > 0 && `· ${receiptsDocs.length}`}
              </h3>
              <div className="max-h-40 overflow-y-auto rounded-lg border text-xs">
                {receiptsDocs.length === 0 ? (
                  <div className="px-3 py-2.5 text-muted-foreground">
                    Приходов с привязанной накладной нет
                    {tank.receipts > 0 && ` — при этом принято ${L(tank.receipts)}: приход без ТТН нечем подтвердить`}
                  </div>
                ) : receiptsDocs.map((d, i) => (
                  <div key={`${d.ttn}-${i}`} className="flex items-center justify-between border-b border-border/50 px-3 py-1.5 last:border-b-0">
                    <span className="font-mono">ТТН {d.ttn}</span>
                    <span className="text-muted-foreground">смена {d.shift}</span>
                    <span className="tabular-nums">{L(d.volume)}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          {/* Смены-виновники: строка открывает разбор смены. */}
          {worstShifts.length > 0 && (
            <section>
              <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                Смены с наибольшим изменением расхождения
              </h3>
              <div className="overflow-hidden rounded-lg border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-medium">Смена</th>
                      <th className="px-3 py-1.5 text-left font-medium">Дата</th>
                      <th className="px-3 py-1.5 text-right font-medium">Отпуск</th>
                      <th className="px-3 py-1.5 text-right font-medium">Приход</th>
                      <th className="px-3 py-1.5 text-right font-medium">Δ расхождения</th>
                      <th className="px-3 py-1.5 text-left font-medium">Обстоятельство</th>
                    </tr>
                  </thead>
                  <tbody>
                    {worstShifts.map((r) => (
                      <tr
                        key={`${r.shift_number}:${r.opened_at}`}
                        tabIndex={onPickShift ? 0 : undefined}
                        onClick={() => onPickShift?.(r)}
                        onKeyDown={(e) => {
                          if (onPickShift && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onPickShift(r) }
                        }}
                        className={cn('border-t border-border/50',
                          onPickShift && 'cursor-pointer hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring')}
                      >
                        <td className="px-3 py-1.5 tabular-nums">№{r.shift_number}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">
                          {r.opened_at ? new Date(r.opened_at).toLocaleDateString('ru-RU') : '—'}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{L(r.sales)}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{r.receipts > 0 ? L(r.receipts) : '—'}</td>
                        <td className={cn('px-3 py-1.5 text-right font-medium tabular-nums',
                          gapTone(r.fact_gap_delta, tol))}>{gapWord(r.fact_gap_delta)}</td>
                        <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                          {Math.abs(r.arithmetic_gap) > 0.5 ? 'арифметика отчёта не сходится'
                            : r.continuity_reason ? r.continuity_reason
                            : r.receipts > 1 ? 'смена с приёмкой'
                            : 'рабочая смена'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </DetailPane>
  )
}
