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

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
const monthLabel = (ym: string) => {
  const [y, m] = ym.split('-')
  return `${MONTHS[Number(m) - 1]} ${y.slice(2)}`
}

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

  /** Сколько расхождения набежало в каждом месяце и где оно скакнуло. */
  const byMonth = useMemo(() => {
    const acc = new Map<string, { delta: number; shifts: number; measured: number; jump: TankLedgerRow | null }>()
    for (const r of rows) {
      if (!r.opened_at) continue
      const ym = r.opened_at.slice(0, 7)
      const e = acc.get(ym) ?? { delta: 0, shifts: 0, measured: 0, jump: null }
      e.shifts += 1
      if (r.fact_gap_delta != null) {
        e.delta += r.fact_gap_delta
        e.measured += 1
        if (!e.jump || Math.abs(r.fact_gap_delta) > Math.abs(e.jump.fact_gap_delta ?? 0)) e.jump = r
      }
      acc.set(ym, e)
    }
    return [...acc.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [rows])

  /** Первая смена периода, где расхождение уже перешло допуск — точка появления. */
  const firstBad = useMemo(() => rows.find(
    (r) => r.fact_gap != null && Math.abs(r.fact_gap) > tol) ?? null, [rows, tol])
  const noFact = useMemo(() => rows.filter((r) => r.fact_end == null).length, [rows])

  /** Раскладка «набежавшего за период» по обстоятельствам смен. */
  const parts = useMemo(() => {
    if (!tank) return []
    let defects = 0, onReceipts = 0, clean = 0
    for (const r of rows) {
      const d = r.fact_gap_delta
      if (d == null) continue
      const broken = Math.abs(r.arithmetic_gap) > 0.5
        || (r.continuity_kind != null && DEFECT_KINDS.has(r.continuity_kind))
        || r.fuel_changed
      if (broken) defects += d
      else if (r.receipts > 1) onReceipts += d
      else clean += d
    }
    return [
      { key: 'opening', label: 'Было на входе', value: tank.fact_gap_opening ?? 0, defect: false,
        hint: 'расхождение пришло из прошлого периода — вопрос не этого разбора' },
      { key: 'defects', label: 'Дефекты учёта', value: defects, defect: true,
        hint: 'смены со сломанной арифметикой, разрывом стыка или ручной правкой: правится в отчётах, а не списанием' },
      { key: 'receipts', label: 'В сменах со сливом', value: onReceipts, defect: false,
        hint: 'набежало в смены с приёмкой — проверить недолив по ТТН и синхронность замера со сливом' },
      { key: 'clean', label: 'В рабочих сменах', value: clean, defect: false,
        hint: 'чистые смены: погрешность замера, температурное дыхание, естественная убыль, пролив' },
    ]
  }, [tank, rows])

  const chart = useMemo(() => rows
    .filter((r) => r.fact_end != null)
    .map((r) => ({
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
      subtitle={tank
        ? `${tank.shifts} смен · смены ${tank.first_shift}–${tank.last_shift} · период ${dateFrom} — ${dateTo}`
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
                    <th className="px-3 py-1.5 text-right font-medium">Набежало</th>
                    <th className="px-3 py-1.5 text-left font-medium">Наибольший прыжок в месяце</th>
                  </tr>
                </thead>
                <tbody>
                  {byMonth.map(([ym, m]) => (
                    <tr key={ym} className="border-t border-border/50">
                      <td className="px-3 py-1.5 font-medium">{monthLabel(ym)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {m.shifts}{m.measured < m.shifts && (
                          <span className="ml-1 text-[10px]">({m.shifts - m.measured} без замера)</span>
                        )}
                      </td>
                      <td className={cn('px-3 py-1.5 text-right font-medium tabular-nums', gapTone(m.delta, tol))}>
                        {gapWord(m.delta)}
                      </td>
                      <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                        {m.jump && Math.abs(m.jump.fact_gap_delta ?? 0) > tol ? (
                          <button type="button" onClick={() => onPickShift?.(m.jump as TankLedgerRow)}
                            className="text-left underline-offset-2 hover:text-foreground hover:underline">
                            смена №{m.jump.shift_number} · {gapWord(m.jump.fact_gap_delta)}
                            {m.jump.receipts > 1 && ' · при сливе'}
                            {m.jump.continuity_kind && ` · ${m.jump.continuity_kind === 'delivery' ? 'слив между сменами'
                              : m.jump.continuity_kind === 'manual' ? 'ручная правка'
                              : m.jump.continuity_kind === 'book_reset' ? 'сброс книги'
                              : m.jump.continuity_kind === 'renumber' ? 'перенумерация'
                              : m.jump.continuity_kind === 'pulled_to_fact' ? 'списано на станции'
                              : m.jump.continuity_kind}`}
                          </button>
                        ) : '—'}
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
                    <XAxis dataKey="shift" tick={{ fontSize: 10 }} stroke="currentColor" className="text-muted-foreground" />
                    <YAxis tick={{ fontSize: 10 }} width={52} stroke="currentColor" className="text-muted-foreground" />
                    <RTooltip
                      contentStyle={{ fontSize: 11, borderRadius: 8, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                      formatter={(v, n) => [`${nf0.format(Number(v ?? 0))} л`, n]}
                      labelFormatter={(l) => `смена ${l}`}
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
