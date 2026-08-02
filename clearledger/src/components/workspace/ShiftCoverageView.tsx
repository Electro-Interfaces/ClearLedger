/**
 * «Пробелы» — полнота сменных отчётов по презумпции непрерывной работы.
 *
 * Правило (решение МАГа 30.07.2026): АЗС работает непрерывно, значит **за каждый
 * день у станции ждём хотя бы один сменный отчёт**. Сутки без отчёта — дефект
 * данных, пока не доказано обратное; остановки бывают, но обязаны быть видны и
 * объяснены, а не растворяться в средних.
 *
 * Экран отвечает на три вопроса в таком порядке:
 *   1. Сколько всего потеряно — покрытие сети в процентах и в сутках;
 *   2. У кого именно — станции по возрастанию покрытия, худшие сверху;
 *   3. Когда — календарь суток и крупнейшие интервалы пропусков.
 *
 * Три состояния, а не два: смена может быть, но без сумм («без данных») — источник
 * не отдал детализацию. Считать такие сутки закрытыми значило бы прятать пробел,
 * считать пустыми — врать, что станция не работала.
 *
 * Сутки до подключения станции к контуру в знаменатель не идут: у АЗС №288 это 208
 * суток периода, и без этого правила её покрытие читалось бы как 0,5 % при
 * единственном рабочем дне.
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getFuelShiftCoverage, type CoverageState } from '@/services/fuelNetworkService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const dmy = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
const dm = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
const days = (n: number) => {
  const t = n % 100 > 4 && n % 100 < 21 ? 5 : n % 10
  return `${nf0.format(n)} ${t === 1 ? 'день' : t > 1 && t < 5 ? 'дня' : 'дней'}`
}

/** Статусная палитра: состояние суток, а не величина — поэтому три фиксированных цвета. */
const CELL: Record<CoverageState, string> = {
  ok: 'bg-emerald-500/60',
  nodata: 'bg-amber-500/80',
  miss: 'bg-rose-600/80',
}
const CELL_LABEL: Record<CoverageState, string> = {
  ok: 'смена закрыта с суммами',
  nodata: 'смена есть, детализации нет',
  miss: 'сменного отчёта нет',
}

function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'danger' | 'warn' | 'ok'
}) {
  return (
    <div className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn('mt-1 truncate text-lg font-semibold tabular-nums',
        tone === 'danger' && 'text-rose-500 dark:text-rose-400',
        tone === 'warn' && 'text-amber-600 dark:text-amber-400',
        tone === 'ok' && 'text-emerald-600 dark:text-emerald-400')}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}

export function ShiftCoverageView({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-shift-coverage', companyId, dateFrom, dateTo],
    queryFn: () => getFuelShiftCoverage({ companyId, dateFrom, dateTo }),
  })

  // Ось календаря — все сутки периода, а не только те, где что-то было: пропуск
  // обязан занимать столько же места, сколько рабочий день.
  const axis = useMemo(() => {
    const out: string[] = []
    const from = new Date(`${dateFrom}T00:00:00`)
    const to = new Date(`${dateTo}T00:00:00`)
    for (const d = new Date(from); d <= to; d.setDate(d.getDate() + 1)) {
      out.push(d.toISOString().slice(0, 10))
    }
    return out
  }, [dateFrom, dateTo])

  if (isLoading || !data) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const t = data.totals
  if (t.expected_days === 0) return <div className="p-8 text-center text-sm text-muted-foreground">За период нет ни одной станции с историей смен</div>

  return (
    <div className="space-y-4">
      <Card className="gap-0 py-0"><CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-5">
        <Stat label="Покрытие сети" value={t.coverage_pct != null ? `${nf1.format(t.coverage_pct)} %` : '—'}
          sub={`${nf0.format(t.ok_days)} из ${nf0.format(t.expected_days)} рабочих суток`}
          tone={t.coverage_pct == null ? undefined : t.coverage_pct >= 99 ? 'ok' : t.coverage_pct >= 95 ? 'warn' : 'danger'} />
        <Stat label="Нет отчёта" value={days(t.miss_days)} sub="сутки без сменного отчёта"
          tone={t.miss_days ? 'danger' : 'ok'} />
        <Stat label="Без детализации" value={days(t.nodata_days)} sub="смена есть, сумм нет"
          tone={t.nodata_days ? 'warn' : 'ok'} />
        <Stat label="Станций без пробелов" value={`${nf0.format(t.stations_full)} из ${nf0.format(t.stations)}`}
          tone={t.stations_full === t.stations ? 'ok' : undefined} />
        <Stat label="Худший провал"
          value={t.worst_gap ? days(t.worst_gap.days) : '—'}
          sub={t.worst_gap ? `${dmy(t.worst_gap.from)} – ${dmy(t.worst_gap.to)}` : 'пропусков нет'}
          tone={t.worst_gap ? 'danger' : 'ok'} />
      </CardContent></Card>

      <div className="flex flex-wrap items-center gap-4 text-[11px] text-muted-foreground">
        {(['ok', 'nodata', 'miss'] as CoverageState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span className={cn('inline-block h-3 w-3 rounded-sm', CELL[s])} />{CELL_LABEL[s]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm bg-muted/40" />не подключена к контуру
        </span>
      </div>

      <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs"
          data-export-name="Полнота сменных отчётов"
          data-export-rows={JSON.stringify({
            columns: ['АЗС', 'Первая смена', 'Ожидалось суток', 'Закрыто', 'Без детализации', 'Нет отчёта', 'Покрытие, %', 'Крупнейший провал'],
            rows: data.stations.map((s) => [
              s.station, s.first_day, s.expected_days, s.ok_days, s.nodata_days, s.miss_days,
              s.coverage_pct, s.gaps[0] ? `${s.gaps[0].from}…${s.gaps[0].to} (${s.gaps[0].days})` : '',
            ]),
          })}>
          <thead>
            <tr className="border-b bg-muted/35 text-muted-foreground">
              <th className="sticky left-0 z-10 bg-muted/35 p-2 text-left font-medium">АЗС</th>
              <th className="p-2 text-right font-medium whitespace-nowrap">Покрытие</th>
              <th className="p-2 text-right font-medium whitespace-nowrap">Нет отчёта</th>
              <th className="p-2 text-left font-medium">Календарь суток</th>
              <th className="p-2 text-left font-medium whitespace-nowrap">Крупнейшие провалы</th>
            </tr>
          </thead>
          <tbody>
            {data.stations.map((s) => {
              const byDay = new Map(s.cells.map((c) => [c.day, c]))
              return (
                <tr key={s.station_code} className="border-b border-border/40 align-middle hover:bg-muted/20">
                  <td className="sticky left-0 z-10 bg-background p-2 whitespace-nowrap">
                    <span className="font-medium">{s.station}</span>
                    {s.not_connected_days > 0 && (
                      <div className="text-[10px] text-muted-foreground">
                        подключена {dmy(s.first_day)}
                      </div>
                    )}
                  </td>
                  <td className={cn('p-2 text-right tabular-nums font-medium whitespace-nowrap',
                    s.coverage_pct == null ? '' : s.coverage_pct >= 99 ? 'text-emerald-600 dark:text-emerald-400'
                      : s.coverage_pct >= 95 ? 'text-amber-600 dark:text-amber-400' : 'text-rose-500 dark:text-rose-400')}>
                    {s.coverage_pct != null ? `${nf1.format(s.coverage_pct)} %` : '—'}
                    <div className="text-[10px] font-normal text-muted-foreground">из {nf0.format(s.expected_days)} сут.</div>
                  </td>
                  <td className="p-2 text-right tabular-nums whitespace-nowrap">
                    {s.miss_days ? <span className="text-rose-500 dark:text-rose-400">{nf0.format(s.miss_days)}</span> : '—'}
                    {s.nodata_days ? <div className="text-[10px] text-amber-600 dark:text-amber-400">+{nf0.format(s.nodata_days)} без сумм</div> : null}
                  </td>
                  <td className="p-2">
                    <div className="flex gap-[1px]">
                      {axis.map((d) => {
                        const c = byDay.get(d)
                        return (
                          <span key={d}
                            className={cn('h-4 w-[3px] shrink-0 rounded-[1px]', c ? CELL[c.state] : 'bg-muted/40')}
                            title={c
                              ? `${dmy(d)} · ${CELL_LABEL[c.state]}${c.shifts ? ` · смен ${c.shifts}` : ''}`
                              : `${dmy(d)} · станция ещё не подключена к контуру`} />
                        )
                      })}
                    </div>
                  </td>
                  <td className="p-2 text-[11px] text-muted-foreground">
                    {s.gaps.length === 0 ? 'без пропусков' : (
                      <div className="space-y-0.5">
                        {s.gaps.slice(0, 3).map((g) => (
                          <div key={`${g.from}-${g.to}`} className="whitespace-nowrap">
                            <span className="text-foreground">{days(g.days)}</span>
                            {' · '}{dm(g.from)}{g.days > 1 && <>–{dm(g.to)}</>}
                          </div>
                        ))}
                        {s.gaps.length > 3 && <div>ещё {s.gaps.length - 3}</div>}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </CardContent></Card>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs leading-relaxed text-muted-foreground">
        Знаменатель покрытия — рабочие сутки станции: от её первой смены в данных до
        конца периода (но не дальше вчерашних суток — сегодняшняя смена ещё не закрыта).
        Сутки до подключения станции к контуру в расчёт не идут и на календаре показаны
        серым. «Без детализации» добирается переигровкой канала «Топливо: сменный отчёт»
        задним числом; «нет отчёта» — это либо остановка точки, либо неполученные данные,
        и такие интервалы стоит проверять по журналу связи станции.
      </div>
    </div>
  )
}
