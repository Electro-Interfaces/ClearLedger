/**
 * Карточка резервуара — «что привело к расхождению книги и факта».
 *
 * Разбор был размазан по трём экранам: журнал показывал смены, «По резервуарам»
 * итог, «Причины» природу — а решение принимают по одному резервуару и сразу.
 * Здесь всё вместе и в порядке разбора.
 *
 * Главное — РАСКЛАДКА расхождения. Она отвечает на вопрос, который решает судьбу
 * инвентаризации: сколько из недостачи вообще про топливо, а сколько про данные.
 *
 *   было на входе      — старое расхождение, оно пришло из прошлого периода;
 *   дефекты учёта      — набежало в сменах со сломанной арифметикой, разрывом
 *                        стыка или ручной правкой: это не топливо, это отчёты;
 *   при сливах         — набежало в сменах с приёмкой: смотреть недолив по ТТН;
 *   рабочие смены      — набежало в чистых сменах: погрешность замера, темпера-
 *                        турное дыхание, естественная убыль, пролив;
 *   оформлено          — уже закрыто ведомостями;
 *   к разбору          — остаток, который пойдёт в следующую инвентаризацию.
 *
 * Суммы раскладки по построению дают текущее расхождение — проверяется строкой
 * «сходится» под таблицей: если нет, данные периода неполные, и это тоже вывод.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts'
import { AlertTriangle, Droplets, Thermometer } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import {
  getVarianceDiagnostics, type TankLedgerRow, type TankLedgerTank,
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

type Part = { key: string; label: string; value: number; hint: string; defect: boolean }

export function TankCardDialog({ tank, rows, tol, companyId, dateFrom, dateTo, onClose }: {
  tank: TankLedgerTank | null
  rows: TankLedgerRow[]
  tol: number
  companyId: string
  dateFrom: string
  dateTo: string
  onClose: () => void
}) {
  const open = !!tank
  const diag = useQuery({
    queryKey: ['variance-diag', companyId, dateFrom, dateTo, tank?.station_code],
    queryFn: () => getVarianceDiagnostics({
      companyId, dateFrom, dateTo, stationCodes: tank ? [tank.station_code] : [],
    }),
    enabled: open,
    staleTime: 60_000,
  })
  const nature = useMemo(() => (diag.data?.tanks ?? []).find(
    (t) => t.station_code === tank?.station_code && t.tank_number === tank?.tank_number), [diag.data, tank])

  /** Раскладка «набежавшего за период» по обстоятельствам смен. */
  const parts = useMemo<Part[]>(() => {
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
    const opening = tank.fact_gap_opening ?? 0
    return [
      { key: 'opening', label: 'Было на входе', value: opening, defect: false,
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
      Расхождение: r.fact_gap,
    })), [rows])

  /** Крупнейшие изменения расхождения — с них начинают смотреть смены. */
  const worstShifts = useMemo(() => rows
    .filter((r) => r.fact_gap_delta != null && Math.abs(r.fact_gap_delta) > tol)
    .sort((a, b) => Math.abs(b.fact_gap_delta as number) - Math.abs(a.fact_gap_delta as number))
    .slice(0, 6), [rows, tol])

  /** Условия замера: крайние значения — по ним видно, могло ли «дышать» объёмом. */
  const physics = useMemo(() => {
    const temps = rows.map((r) => r.temp_end).filter((v): v is number => v != null)
    const water = rows.map((r) => r.water_volume).filter((v): v is number => v != null)
    const dens = rows.map((r) => r.density_end).filter((v): v is number => v != null)
    return {
      tempMin: temps.length ? Math.min(...temps) : null,
      tempMax: temps.length ? Math.max(...temps) : null,
      waterMax: water.length ? Math.max(...water) : null,
      waterLast: water.length ? water[water.length - 1] : null,
      densMin: dens.length ? Math.min(...dens) : null,
      densMax: dens.length ? Math.max(...dens) : null,
    }
  }, [rows])

  const receiptsDocs = useMemo(() => rows.flatMap((r) => (r.receipts_docs ?? []).map(
    (d) => ({ ...d, shift: r.shift_number }))), [rows])

  if (!tank) return null
  const sumParts = parts.reduce((s, p) => s + p.value, 0)
  const residual = (tank.fact_gap ?? 0) - sumParts

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {tank.station_name} · резервуар №{tank.tank_number} · {tank.fuel_name}
          </DialogTitle>
          <DialogDescription>
            {tank.shifts} смен · смены {tank.first_shift}–{tank.last_shift} · период {dateFrom} — {dateTo}
          </DialogDescription>
        </DialogHeader>

        {/* Итог: сколько числится, сколько намерено и что с этим делать. */}
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-4">
          {[
            ['Книга на конец', L(tank.book_end), 'по документам'],
            ['Замер', L(tank.fact_end), 'уровнемер'],
            ['Книга − факт', gapWord(tank.fact_gap), 'всё накопленное'],
            ['К разбору', gapWord(tank.fact_gap_open), tank.inventory_date
              ? `после ведомости от ${tank.inventory_date}` : 'ведомостей не было'],
          ].map(([label, value, hint], i) => (
            <div key={label} className="bg-card px-3 py-2.5">
              <div className="text-[11px] text-muted-foreground">{label}</div>
              <div className={cn('mt-0.5 text-sm font-semibold tabular-nums',
                i >= 2 && gapTone(i === 2 ? tank.fact_gap : tank.fact_gap_open, tol))}>{value}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
            </div>
          ))}
        </div>

        {/* Природа расхождения — вывод диагностики по всей истории резервуара. */}
        {nature && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border/70 bg-card/60 px-3 py-2 text-xs">
            <Badge variant="outline" className="border-primary/40 text-primary">{nature.nature_title}</Badge>
            {nature.trend_per_shift != null && Math.abs(nature.trend_per_shift) > 0.5 && (
              <span className="text-muted-foreground">
                тренд {nf1.format(nature.trend_per_shift)} л/смену · накоплено {L(nature.accumulated)}
              </span>
            )}
            {nature.jump_liters != null && Math.abs(nature.jump_liters) > tol && (
              <span className="text-muted-foreground">
                скачок {L(nature.jump_liters)} в смене {nature.jump_shift}
                {nature.jump_on_receipt && ' · при сливе'}
              </span>
            )}
            {nature.temperature_share >= 0.5 && (
              <Badge variant="outline" className="border-sky-500/40 text-sky-400">
                объём «дышит» температурой — масса в допуске
              </Badge>
            )}
          </div>
        )}

        {/* Раскладка: главный экран разбора. */}
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
                    <td className={cn('w-40 px-3 py-2 text-right font-medium tabular-nums',
                      gapTone(p.value, tol))}>{gapWord(p.value)}</td>
                    <td className="px-3 py-2 text-[11px] text-muted-foreground">{p.hint}</td>
                  </tr>
                ))}
                {tank.inventory_adjustment != null && (
                  <tr className="border-b border-border/60 bg-muted/20">
                    <td className="px-3 py-2 font-medium">Оформлено ведомостями</td>
                    <td className="w-40 px-3 py-2 text-right font-medium tabular-nums text-muted-foreground">
                      {nf0.format(Math.abs(tank.inventory_adjustment))} л{' '}
                      {tank.inventory_adjustment > 0 ? 'оприходовано' : 'списано'}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-muted-foreground">
                      ведомость от {tank.inventory_date} — это расхождение уже закрыто документом
                    </td>
                  </tr>
                )}
                <tr className="bg-muted/40">
                  <td className="px-3 py-2 font-semibold">Итого «книга − факт»</td>
                  <td className={cn('w-40 px-3 py-2 text-right font-semibold tabular-nums',
                    gapTone(tank.fact_gap, tol))}>{gapWord(tank.fact_gap)}</td>
                  <td className="px-3 py-2 text-[11px] text-muted-foreground">
                    {Math.abs(residual) <= Math.max(tol, Math.abs(tank.fact_gap ?? 0) * 0.02)
                      ? 'раскладка сходится с итогом'
                      : `не разложилось ${nf0.format(Math.abs(residual))} л — в периоде есть смены без замера`}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* Динамика: расходятся ли линии книги и замера или идут параллельно. */}
        {chart.length > 2 && (
          <section>
            <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
              Книга и замер по сменам
            </h3>
            <div className="h-48 rounded-lg border p-2">
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
              Линии расходятся — расхождение накапливается; идут параллельно с постоянным
              зазором — расхождение старое и держится, скачок в одной точке — событие смены.
            </p>
          </section>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          {/* Условия замера: могло ли «дышать» объёмом и есть ли вода. */}
          <section>
            <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">Условия замера</h3>
            <div className="space-y-1.5 rounded-lg border px-3 py-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <Thermometer className="h-3.5 w-3.5" />температура
                </span>
                <span className="tabular-nums">
                  {physics.tempMin != null ? `${nf1.format(physics.tempMin)} … ${nf1.format(physics.tempMax as number)} °C` : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <Droplets className="h-3.5 w-3.5" />подтоварная вода
                </span>
                <span className={cn('tabular-nums', (physics.waterMax ?? 0) > 20 && 'text-amber-500')}>
                  {physics.waterLast != null
                    ? `${nf1.format(physics.waterLast)} л (макс. ${nf1.format(physics.waterMax as number)})`
                    : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">плотность</span>
                <span className="tabular-nums">
                  {physics.densMin != null ? `${physics.densMin} … ${physics.densMax}` : '—'}
                </span>
              </div>
              <p className="pt-1 text-[11px] text-muted-foreground">
                Вода занимает объём и в замер попадает как топливо. Разброс температуры
                в 10 °C — это около 1% объёма, на 20 м³ примерно 200 л.
              </p>
            </div>
          </section>

          {/* Приёмка: чем подтверждён приход. */}
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

        {/* Смены, где расхождение прыгнуло сильнее всего. */}
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
                    <tr key={`${r.shift_number}:${r.opened_at}`} className="border-t border-border/50">
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
      </DialogContent>
    </Dialog>
  )
}
