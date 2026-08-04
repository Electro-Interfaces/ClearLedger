/**
 * «Период» — реестр месяцев и полнота данных в каждом.
 *
 * Главный вопрос бухгалтера к этому экрану — не «сколько выручки», а «какой месяц
 * ещё открыт и чего в нём не хватает». Поэтому центр экрана — не сводка, а две
 * вещи: список периодов со статусом закрытия и карта полноты за выбранный месяц,
 * где видно, какая станция за какой день не прислала сменный отчёт.
 *
 * Дыра в данных — это не «мало выручки», а несделанная работа: пока за 12 июля по
 * АЗС 205 нет смены, период закрывать нельзя, и никакая сводка этого не покажет —
 * она сложит то, что есть, и цифра будет выглядеть правдоподобно.
 *
 * Полнота считается на клиенте из тех же журналов, которые открывают разделы
 * потоков: своего источника правды у экрана нет намеренно. Расхождение сводки с
 * журналом означало бы, что одна из двух цифр врёт, а какая — выяснять уже некому.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, CalendarCheck, ChefHat, CheckCircle2, Fuel, Loader2, Lock, ShoppingCart, Unlock,
} from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { get } from '@/services/apiClient'
import { getLoadedShifts, getFuelReadiness } from '@/services/fuel/fuelMappingService'
import { getReconciliationSummary } from '@/services/accountingDocService'
import { getStoreShifts } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const H3 = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
const fmtN = (v: number) => (v ?? 0).toLocaleString('ru-RU')
const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

interface PeriodRow {
  id: string | null
  year: number
  month: number
  status: 'open' | 'closed'
  closedAt: string | null
  closureSource: 'manual' | 'from_bp' | 'derived'
  docsCount: number
  minDate: string | null
  maxDate: string | null
}
interface PeriodsSummary { items: PeriodRow[]; totalDocs: number }

const pad = (n: number) => String(n).padStart(2, '0')
const monthRange = (year: number, month: number) => ({
  from: `${year}-${pad(month)}-01`,
  to: `${year}-${pad(month)}-${new Date(year, month, 0).getDate()}`,
})
const dayOf = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : '')

/** Ячейка карты: смена есть и закрыта · есть, но открыта · данных нет. */
type Cell = 'closed' | 'open' | 'none'

export function AccountingPeriodPanel() {
  const { companyId } = useCompany()
  const { setCoreMode } = useWorkspace()
  const [selected, setSelected] = useState<{ year: number; month: number } | null>(null)
  const [stream, setStream] = useState<'fuel' | 'store'>('fuel')

  const periods = useQuery({
    queryKey: ['periods-summary', companyId],
    queryFn: () => get<PeriodsSummary>('/api/periods/summary', { company_id: companyId }),
  })

  // По умолчанию — самый свежий период: с него человек и начинает, закрытые месяцы
  // смотрят реже и по поводу.
  const items = periods.data?.items ?? []
  const active = selected ?? (items[0] ? { year: items[0].year, month: items[0].month } : null)
  const range = active ? monthRange(active.year, active.month) : null

  const fuelShifts = useQuery({
    queryKey: ['fuel-shifts-period', companyId, range?.from, range?.to],
    queryFn: () => getLoadedShifts({ dateFrom: range!.from, dateTo: range!.to, limit: 20000 }),
    enabled: !!range,
  })
  const storeShifts = useQuery({
    queryKey: ['store-shifts', companyId, range?.from, range?.to],
    queryFn: () => getStoreShifts(range!.from, range!.to),
    enabled: !!range,
  })
  const readiness = useQuery({
    queryKey: ['fuel-readiness', companyId, range?.from, range?.to],
    queryFn: () => getFuelReadiness(range!.from, range!.to),
    enabled: !!range,
  })
  const recon = useQuery({
    queryKey: ['reconciliation-summary', companyId],
    queryFn: () => getReconciliationSummary(companyId),
  })

  // Карта полноты: станция → день → состояние. Дни берём все, что есть в месяце,
  // но не дальше сегодняшнего: пустые клетки будущего — не пробел, а просто «ещё
  // не наступило», и красить их значило бы пугать зря.
  const map = useMemo(() => {
    if (!active || !range) return { days: [] as string[], stations: [] as string[], cells: new Map<string, Cell>() }
    const today = new Date().toISOString().slice(0, 10)
    const last = range.to < today ? range.to : today
    const days: string[] = []
    for (let d = 1; d <= Number(last.slice(8, 10)); d++) days.push(`${range.from.slice(0, 8)}${pad(d)}`)

    const cells = new Map<string, Cell>()
    const stations = new Set<string>()
    if (stream === 'fuel') {
      for (const s of fuelShifts.data ?? []) {
        const day = dayOf(s.opened_at)
        if (!day) continue
        const st = String(s.station_code)
        stations.add(st)
        const key = `${st}|${day}`
        // Закрытая смена сильнее открытой: за день бывает несколько смен, и одна
        // незакрытая не отменяет того, что день отработан.
        if (cells.get(key) !== 'closed') cells.set(key, s.closed_at ? 'closed' : 'open')
      }
    } else {
      for (const s of storeShifts.data?.shifts ?? []) {
        const day = dayOf(s.date)
        if (!day) continue
        stations.add(String(s.station))
        cells.set(`${String(s.station)}|${day}`, s.close ? 'closed' : 'open')
      }
    }
    return { days, stations: [...stations].sort((a, b) => Number(a) - Number(b)), cells }
  }, [active, range, stream, fuelShifts.data, storeShifts.data])

  // Пробелы: день без единой смены по станции, которая в этом месяце работала.
  // Станция, не работавшая весь месяц, в список не попадает — это не пробел
  // данных, а закрытая точка, и разбираться с ней надо не здесь.
  const gaps = useMemo(() => {
    const out: { station: string; days: string[] }[] = []
    for (const st of map.stations) {
      const missing = map.days.filter((d) => !map.cells.has(`${st}|${d}`))
      if (missing.length) out.push({ station: st, days: missing })
    }
    return out.sort((a, b) => b.days.length - a.days.length)
  }, [map])

  const openShifts = useMemo(
    () => [...map.cells.entries()].filter(([, v]) => v === 'open').length, [map])

  const rs = recon.data
  const storeRows = storeShifts.data?.shifts ?? []
  const obshepit = storeRows.reduce((s, r) => s + (r.obshepit ?? 0), 0)
  const soputka = storeRows.reduce((s, r) => s + (r.soputka ?? 0), 0)

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Периоды</h2>
        <span className="text-xs text-muted-foreground">
          какой месяц закрыт, что в открытом собрано и чего не хватает
        </span>
      </div>

      {/* ── Реестр месяцев ── */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2">
            <CalendarCheck className="h-4 w-4 text-primary" />
            <h3 className={H3}>Месяцы</h3>
          </div>
          {periods.isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Загружаем реестр периодов…
            </div>
          ) : items.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              Периодов пока нет: они появляются вместе с документами из 1С.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-[11px] text-muted-foreground">
                    <th className="py-1.5 text-left font-medium">Месяц</th>
                    <th className="py-1.5 text-left font-medium">Состояние</th>
                    <th className="py-1.5 text-right font-medium">Документов 1С</th>
                    <th className="py-1.5 text-left font-medium">Данные с</th>
                    <th className="py-1.5 text-left font-medium">по</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((p) => {
                    const on = active?.year === p.year && active?.month === p.month
                    return (
                      <tr key={`${p.year}-${p.month}`}
                        onClick={() => setSelected({ year: p.year, month: p.month })}
                        className={cn('cursor-pointer border-b border-border/30 transition-colors hover:bg-accent/40',
                          on && 'bg-primary/10')}>
                        <td className="py-1.5 font-medium">{MONTHS[p.month - 1]} {p.year}</td>
                        <td className="py-1.5">
                          <span className={cn('inline-flex items-center gap-1.5 text-xs',
                            p.status === 'closed'
                              ? 'text-muted-foreground'
                              : 'text-amber-600 dark:text-amber-400')}>
                            {p.status === 'closed'
                              ? <><Lock className="h-3 w-3" />закрыт</>
                              : <><Unlock className="h-3 w-3" />открыт</>}
                          </span>
                        </td>
                        <td className="py-1.5 text-right tabular-nums">{fmtN(p.docsCount)}</td>
                        <td className="py-1.5 tabular-nums text-muted-foreground">{p.minDate ?? '—'}</td>
                        <td className="py-1.5 tabular-nums text-muted-foreground">{p.maxDate ?? '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {active && (
        <>
          {/* ── Что в периоде собрано ── */}
          <div className="grid gap-3 lg:grid-cols-3">
            <StreamRow icon={Fuel} title="Нефтепродукты"
              rows={[
                ['Смен', fmtN(readiness.data?.shifts.total ?? 0)],
                ['С правками', fmtN(readiness.data?.shifts.corrected ?? 0)],
                ['ТТН принято', `${fmtN(readiness.data?.receipts.confirmed ?? 0)} из ${fmtN(readiness.data?.receipts.total ?? 0)}`],
              ]}
              alert={(readiness.data?.receipts.pending ?? 0) > 0
                ? `${fmtN(readiness.data!.receipts.pending)} ТТН ждут подтверждения`
                : undefined}
              go={() => setCoreMode('accounting', 'recon1c')} />
            <StreamRow icon={ShoppingCart} title="Магазин"
              rows={[
                ['Смен', fmtN(storeShifts.data?.summary.count ?? 0)],
                ['Выручка сопутки', fmtMoney(soputka)],
                ['Возвраты', fmtMoney(storeShifts.data?.summary.returns ?? 0)],
              ]}
              alert={(storeShifts.data?.summary.count ?? 0) === 0 ? 'смен за месяц нет' : undefined}
              go={() => setCoreMode('acc_store', 'export')} />
            <StreamRow icon={ChefHat} title="Общепит"
              rows={[
                ['Смен с кухней', fmtN(storeRows.filter((r) => (r.obshepit ?? 0) > 0).length)],
                ['Выручка блюд', fmtMoney(obshepit)],
                ['Доля товарной', soputka + obshepit > 0
                  ? `${Math.round((obshepit / (soputka + obshepit)) * 100)}%` : '—'],
              ]}
              go={() => setCoreMode('acc_food', 'food_release')} />
          </div>

          {/* ── Карта полноты ── */}
          <Card>
            <CardContent className="pt-4">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <CalendarCheck className="h-4 w-4 text-primary" />
                <h3 className={H3}>Полнота данных по дням</h3>
                <div className="ml-auto flex gap-1 rounded-lg bg-card p-1">
                  {([['fuel', 'Топливо'], ['store', 'Магазин']] as const).map(([k, label]) => (
                    <button key={k} onClick={() => setStream(k)}
                      className={cn('rounded px-3 py-1 text-xs transition-colors',
                        stream === k ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-accent/40')}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {fuelShifts.isLoading || storeShifts.isLoading ? (
                <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Считаем полноту…
                </div>
              ) : map.stations.length === 0 ? (
                <p className="py-4 text-sm text-muted-foreground">
                  За этот месяц смен нет — считать полноту не по чему.
                </p>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="text-[11px]">
                      <thead>
                        <tr>
                          <th className="sticky left-0 bg-card pr-3 text-left font-medium text-muted-foreground">АЗС</th>
                          {map.days.map((d) => (
                            <th key={d} className="w-5 pb-1 text-center font-normal text-muted-foreground/70">
                              {Number(d.slice(8, 10))}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {map.stations.map((st) => (
                          <tr key={st}>
                            <td className="sticky left-0 bg-card pr-3 font-medium tabular-nums">{st}</td>
                            {map.days.map((d) => {
                              const v = map.cells.get(`${st}|${d}`) ?? 'none'
                              return (
                                <td key={d} className="p-[1px]">
                                  <div title={`АЗС ${st}, ${d}: ${CELL_TITLE[v]}`}
                                    className={cn('h-4 w-4 rounded-[3px]', CELL_STYLE[v])} />
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-muted-foreground">
                    <Legend cell="closed" text="смена закрыта" />
                    <Legend cell="open" text="смена не закрыта" />
                    <Legend cell="none" text="данных нет" />
                    {openShifts > 0 && (
                      <span className="text-amber-600 dark:text-amber-400">
                        Незакрытых смен: {fmtN(openShifts)}
                      </span>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* ── Пробелы и готовность ── */}
          <Card>
            <CardContent className="pt-4">
              <div className="mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-primary" />
                <h3 className={H3}>Что мешает закрыть месяц</h3>
              </div>
              <ul className="space-y-1.5 text-sm">
                {gaps.length === 0 ? (
                  <li className="flex items-start gap-2">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    <span className="text-muted-foreground">
                      Пропусков по дням нет: каждая работавшая станция закрыта каждый день месяца.
                    </span>
                  </li>
                ) : gaps.slice(0, 8).map((g) => (
                  <li key={g.station} className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                    <span>
                      <span className="font-medium">АЗС {g.station}</span> — нет данных за{' '}
                      {g.days.length > 4
                        ? `${g.days.length} дн.: ${g.days.slice(0, 3).map((d) => d.slice(8, 10)).join(', ')}…`
                        : g.days.map((d) => d.slice(8, 10)).join(', ')}
                    </span>
                  </li>
                ))}
                {gaps.length > 8 && (
                  <li className="pl-6 text-xs text-muted-foreground">
                    …и ещё {gaps.length - 8} станций с пропусками
                  </li>
                )}
                <li className="flex items-start gap-2">
                  {rs && rs.totalAccDocs > 0
                    ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />}
                  <span className={cn(rs && rs.totalAccDocs > 0 && 'text-muted-foreground')}>
                    {rs && rs.totalAccDocs > 0
                      ? `Сопоставлено с 1С: ${fmtN(rs.matched)} из ${fmtN(rs.totalEntries)}, расхождений ${fmtN(rs.discrepancy)}`
                      : 'Документы из 1С не загружены — сверить период не с чем'}
                  </span>
                </li>
              </ul>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

// Состояние дня различается не только цветом: заливка, обводка и штриховка
// читаются и в монохроме, и при дальтонизме.
const CELL_STYLE: Record<Cell, string> = {
  closed: 'bg-emerald-500/70',
  open: 'border-2 border-amber-500/80 bg-amber-500/15',
  none: 'border border-dashed border-border bg-transparent',
}
const CELL_TITLE: Record<Cell, string> = {
  closed: 'смена закрыта',
  open: 'смена открыта, не закрыта',
  none: 'данных нет',
}

function Legend({ cell, text }: { cell: Cell; text: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn('h-3 w-3 rounded-[3px]', CELL_STYLE[cell])} />
      {text}
    </span>
  )
}

function StreamRow({ icon: Icon, title, rows, alert, go }: {
  icon: typeof Fuel
  title: string
  rows: [string, string][]
  alert?: string
  go: () => void
}) {
  return (
    <button onClick={go}
      className="rounded-lg border border-border bg-card/40 p-3 text-left transition-colors hover:bg-accent/30">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">{title}</span>
      </div>
      <dl className="mt-2 space-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-sm font-medium tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {alert && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{alert}
        </p>
      )}
    </button>
  )
}
