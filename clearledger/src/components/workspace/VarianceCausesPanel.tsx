/**
 * Причины расхождения книга↔факт по резервуарам.
 *
 * Причина одной смены по массе ненадёжна (книга и факт считаются по разной
 * плотности), поэтому она читается по поведению расхождения во времени:
 *  • дрейф   — расхождение монотонно растёт: реальная убыль/прибыль (испарение,
 *    утечка, недоучёт ТРК) — надо искать причину;
 *  • скачок  — прыгнуло в одну смену и осталось: разовое событие (часто слив);
 *  • шум     — большой разброс без тренда: замер нестабилен;
 *  • стабильное — держится ровно: старая разница, лечится инвентаризацией.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Download, Loader2, TrendingDown, TrendingUp, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { TankCardDialog, type TankRef } from './TankCardDialog'
import { TankShiftDialog } from './TankShiftDialog'
import { ContinuityKindsStrip } from './TankLedgerTabs'
import {
  getTankLedger, getVarianceDiagnostics,
  type TankLedgerRow, type VarianceDiagnosticsResponse, type VarianceNature,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const NATURE_TONE: Record<VarianceNature, string> = {
  drift: 'border-red-400/50 text-red-300/80',
  jump: 'border-amber-400/50 text-amber-300/80',
  noise: 'border-zinc-500/50 text-zinc-300/80',
  stable: 'border-zinc-600 text-zinc-400',
  short: 'border-zinc-600 text-zinc-500',
}

/** Расхождение со словом: знак сам по себе неоднозначен. */
function gap(v: number): string {
  if (Math.abs(v) < 0.5) return '—'
  return `${nf0.format(Math.abs(v))} л ${v > 0 ? 'недостача' : 'излишек'}`
}

interface Props {
  companyId: string
  dateFrom: string
  dateTo: string
  stationCodes: number[]
  fuelCodes: number[]
}

export function VarianceCausesPanel({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }: Props) {
  const [fNature, setFNature] = useState<'all' | VarianceNature>('all')
  // Разбор открывается немодально: диагноз читают по одному резервуару, а список
  // причин под панелью должен оставаться на месте.
  const [picked, setPicked] = useState<TankRef | null>(null)
  const [pickedShift, setPickedShift] = useState<TankLedgerRow | null>(null)

  const query = useQuery({
    queryKey: ['variance-diagnostics', companyId, dateFrom, dateTo, stationCodes.join(','), fuelCodes.join(',')],
    queryFn: () => getVarianceDiagnostics({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }),
    placeholderData: keepPreviousData,
  })
  // Стыки смен — та же сводка, что на соседней вкладке «Замечания» (ключ совпадает —
  // берётся из кеша). Без неё вкладка «Причины» молчала про 760 разрывов, о которых
  // только что сказала плашка сверху, — две вкладки одного экрана расходились.
  const ledgerQuery = useQuery({
    queryKey: ['tank-ledger', companyId, dateFrom, dateTo, stationCodes.join(','), fuelCodes.join(',')],
    queryFn: () => getTankLedger({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }),
    placeholderData: keepPreviousData,
  })
  const continuityKinds = ledgerQuery.data?.totals.continuity_kinds

  const data = query.data
  const rows = useMemo(() => {
    if (!data) return []
    return fNature === 'all' ? data.tanks : data.tanks.filter((t) => t.nature === fNature)
  }, [data, fNature])

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Разбор причин расхождений…
      </div>
    )
  }
  if (query.error || !data) {
    return <div className="p-8 text-sm text-muted-foreground">Не удалось загрузить разбор причин</div>
  }
  if (data.totals.tanks === 0) {
    return <div className="p-8 text-sm text-muted-foreground">За период нет данных для диагностики</div>
  }

  const t = data.totals

  return (
    <div className="space-y-4">
      {/* Первая ось причин — разрывы стыка смен; их разбор строка за строкой
          лежит на вкладке «Замечания». Вторая ось — поведение расхождения с
          замером во времени — ниже плитками. */}
      {continuityKinds && (
        <ContinuityKindsStrip
          kinds={continuityKinds}
          note="разбор каждого разрыва — на вкладке «Замечания»: клик по причине там отбирает её строки"
        />
      )}

      {/* Причины — плитки, кликаются как фильтр */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <CauseTile
          active={fNature === 'drift'} onClick={() => setFNature(fNature === 'drift' ? 'all' : 'drift')}
          icon={<TrendingDown className="h-4 w-4" />}
          title="Систематическая убыль" value={t.drift}
          hint="растёт от смены к смене — реальный процесс" tone="text-red-600 dark:text-red-400" />
        <CauseTile
          active={fNature === 'jump'} onClick={() => setFNature(fNature === 'jump' ? 'all' : 'jump')}
          icon={<Zap className="h-4 w-4" />}
          title="Разовый скачок" value={t.jump}
          hint="прыгнуло в одну смену — событие/слив" tone="text-amber-600 dark:text-amber-400" />
        <CauseTile
          active={fNature === 'noise'} onClick={() => setFNature(fNature === 'noise' ? 'all' : 'noise')}
          icon={<TrendingUp className="h-4 w-4" />}
          title="Нестабильный замер" value={t.noise}
          hint="большой разброс без тренда" />
        <CauseTile
          active={fNature === 'stable'} onClick={() => setFNature(fNature === 'stable' ? 'all' : 'stable')}
          icon={<Badge variant="outline" className="h-4 border-0 p-0 text-[10px]">≈</Badge>}
          title="Стабильное смещение" value={t.stable}
          hint="держится ровно — старая разница" />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {t.temperature_driven > 0 && (
          <Badge variant="outline" className="border-sky-400/50 text-sky-300/80">
            тепловое расширение влияет на {nf0.format(t.temperature_driven)} рез.
          </Badge>
        )}
        {fNature !== 'all' && (
          <button className="text-xs text-muted-foreground underline" onClick={() => setFNature('all')}>
            показать все {nf0.format(t.tanks)}
          </button>
        )}
        <span className="ml-auto flex items-center gap-3">
          <span className="text-[11px] text-muted-foreground">резервуаров: {nf0.format(rows.length)}</span>
          <Button variant="outline" size="sm" className="h-8" onClick={() => exportXlsx(data)}>
            <Download className="mr-1.5 h-3.5 w-3.5" />Экспорт в Excel
          </Button>
        </span>
      </div>

      {/* Таблица резервуаров с диагнозом */}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[1080px] text-xs">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr>
              <Th>АЗС</Th><Th>Рез.</Th><Th>Топливо</Th><Th>Причина</Th>
              <Th right>Тренд, л/смену</Th><Th right>Накоплено за период</Th>
              <Th right>Скачок</Th><Th>В какой смене</Th>
              <Th right>Расхождение сейчас</Th><Th right>Смен</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              // Строка ведёт в разбор резервуара: «разовый скачок 11 923 л» без ответа
              // на вопрос «в какой смене и при чём» — приговор без дела.
              <tr
                key={`${r.station_code}:${r.tank_number}`}
                tabIndex={0}
                aria-haspopup="dialog"
                onClick={() => setPicked({
                  station_code: r.station_code, tank_number: r.tank_number,
                  station_name: r.station_name, fuel_name: r.fuel_name,
                })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setPicked({
                      station_code: r.station_code, tank_number: r.tank_number,
                      station_name: r.station_name, fuel_name: r.fuel_name,
                    })
                  }
                }}
                className={cn(
                  'cursor-pointer border-t transition-colors hover:bg-muted/40',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                  r.nature === 'drift' && 'bg-red-500/5',
                  r.nature === 'jump' && 'bg-amber-500/5',
                )}
              >
                <Td>{r.station_name}</Td>
                <Td>№{r.tank_number}</Td>
                <Td>{r.fuel_name}</Td>
                <Td>
                  <Badge variant="outline" className={NATURE_TONE[r.nature]}>{r.nature_title}</Badge>
                  {r.temperature_share >= 0.5 && (
                    <Badge variant="outline" className="ml-1 border-sky-400/50 text-sky-300/80">температура</Badge>
                  )}
                </Td>
                <Td right className={r.nature === 'drift'
                  ? (r.trend_per_shift > 0 ? 'font-medium text-red-600 dark:text-red-400' : 'font-medium text-sky-600 dark:text-sky-400')
                  : 'text-muted-foreground'}>
                  {Math.abs(r.trend_per_shift) >= 0.5 ? `${r.trend_per_shift > 0 ? '+' : ''}${nf1.format(r.trend_per_shift)}` : '—'}
                </Td>
                <Td right className={r.nature === 'drift' ? 'font-medium' : 'text-muted-foreground'}>
                  {Math.abs(r.accumulated) >= 1 ? gap(r.accumulated) : '—'}
                </Td>
                <Td right className={r.nature === 'jump' ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
                  {r.nature === 'jump' && Math.abs(r.jump_liters) >= 1
                    ? `${r.jump_liters > 0 ? '+' : ''}${nf0.format(r.jump_liters)} л` : '—'}
                </Td>
                <Td>
                  {r.nature === 'jump' && r.jump_shift != null ? (
                    <span>
                      №{r.jump_shift}
                      {r.jump_on_receipt && <span className="ml-1 text-sky-600 dark:text-sky-400">при сливе</span>}
                    </span>
                  ) : <span className="text-muted-foreground">—</span>}
                </Td>
                <Td right className={r.last_gap > 0 ? 'text-red-600 dark:text-red-400' : r.last_gap < 0 ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground'}>
                  {gap(r.last_gap)}
                </Td>
                <Td right>{r.shifts}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Причина определяется по тому, как расхождение книги с фактом ведёт себя от
        смены к смене (порог замера {nf0.format(data.tolerance.vol_liters)} л, минимум
        {' '}{data.tolerance.min_shifts} смен). «Тренд» — насколько расхождение меняется
        за смену: плюс — недостача растёт, минус — растёт излишек. Расхождение одной
        смены по массе не используется — книжная и фактическая масса считаются по
        разной плотности и дают ложные тонны. «Температура» — где объём гуляет, а
        масса держится: это тепловое расширение, а не потеря топлива.
        {' '}Строка открывает разбор резервуара: когда возникло, в какой смене и из чего сложилось.
      </p>

      <TankCardDialog
        target={picked}
        tol={data.tolerance.vol_liters}
        companyId={companyId}
        dateFrom={dateFrom}
        dateTo={dateTo}
        onClose={() => setPicked(null)}
        onPickShift={(r) => setPickedShift(r)}
      />
      <TankShiftDialog row={pickedShift} tol={data.tolerance.vol_liters}
                       onClose={() => setPickedShift(null)} />
    </div>
  )
}

async function exportXlsx(data: VarianceDiagnosticsResponse) {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()
  const rows = data.tanks.map((r) => ({
    'АЗС': r.station_name,
    'Резервуар': r.tank_number,
    'Топливо': r.fuel_name,
    'Причина': r.nature_title,
    'Тренд, л/смену': r.trend_per_shift,
    'Накоплено за период, л': r.accumulated,
    'Скачок, л': r.nature === 'jump' ? r.jump_liters : '',
    'Смена скачка': r.nature === 'jump' ? (r.jump_shift ?? '') : '',
    'Скачок при сливе': r.jump_on_receipt ? 'да' : '',
    'Расхождение сейчас, л': r.last_gap,
    'Смен': r.shifts,
    'Среднее расхождение, л': r.mean_gap,
    'Разброс (σ), л': r.std_gap,
    'Доля температурных смен': r.temperature_share,
  }))
  const ws = XLSX.utils.json_to_sheet(rows)
  ws['!cols'] = [{ wch: 12 }, { wch: 9 }, { wch: 8 }, { wch: 26 }, ...Array(10).fill({ wch: 15 })]
  XLSX.utils.book_append_sheet(wb, ws, 'Причины расхождений')
  XLSX.writeFile(wb, `prichiny_rashozhdenij_${data.period.from}_${data.period.to}.xlsx`)
}

function CauseTile({ active, onClick, icon, title, value, hint, tone }: {
  active: boolean; onClick: () => void; icon: React.ReactNode
  title: string; value: number; hint: string; tone?: string
}) {
  return (
    <button
      type="button" onClick={onClick}
      className={cn(
        'rounded-lg border p-3 text-left transition-colors',
        active ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'bg-card hover:bg-muted/40',
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">{icon}{title}</div>
      <div className={cn('mt-1 text-lg font-semibold', tone)}>{nf0.format(value)} <span className="text-xs font-normal text-muted-foreground">рез.</span></div>
      <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>
    </button>
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
