/**
 * Анализ приёмки: ошибки слива бензовозов по каждой ТТН.
 *
 * Недолив бензовоза — одна из причин расхождения книги с фактом в резервуаре.
 * Считается по МАССЕ (кг), а не по объёму: станция часто вписывает объём
 * накладной в факт один-в-один, и недолив прячется в массе.
 *
 * Причины разведены по классам и НЕ складываются в одну цифру — у каждой свой
 * смысл: «недолив» — претензия поставщику, «без замера» — приняли вслепую (не
 * доказанная недостача), «сорванный замер» — данные ненадёжны.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Download, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  getReceiptAnalysis, type ReceiptAnalysisResponse, type ReceiptClass,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf3 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

/** Цвет класса причины — семантический, приглушённый. */
const CLASS_TONE: Record<ReceiptClass, string> = {
  shortfall: 'border-red-400/50 text-red-300/80',
  not_measured: 'border-amber-400/50 text-amber-300/80',
  broken_measure: 'border-amber-400/50 text-amber-300/80',
  surplus: 'border-sky-400/50 text-sky-300/80',
  ok: 'border-zinc-600 text-zinc-400',
}

interface Props {
  companyId: string
  dateFrom: string
  dateTo: string
  stationCodes: number[]
  fuelCodes: number[]
}

export function ReceiptAnalysisPanel({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }: Props) {
  const [fClass, setFClass] = useState<'all' | ReceiptClass>('all')

  const query = useQuery({
    queryKey: ['receipt-analysis', companyId, dateFrom, dateTo, stationCodes.join(','), fuelCodes.join(',')],
    queryFn: () => getReceiptAnalysis({ companyId, dateFrom, dateTo, stationCodes, fuelCodes }),
    placeholderData: keepPreviousData,
  })

  const data = query.data
  const rows = useMemo(() => {
    if (!data) return []
    return fClass === 'all' ? data.rows : data.rows.filter((r) => r.klass === fClass)
  }, [data, fClass])

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Загрузка приёмки…
      </div>
    )
  }
  if (query.error || !data) {
    return <div className="p-8 text-sm text-muted-foreground">Не удалось загрузить анализ приёмки</div>
  }
  if (data.totals.ttn === 0) {
    return <div className="p-8 text-sm text-muted-foreground">За период нет приёмок топлива (ТТН)</div>
  }

  const t = data.totals

  return (
    <div className="space-y-4">
      {/* Итог приёмки и главные категории причин */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Cell label="Принято ТТН" value={nf0.format(t.ttn)} hint={`${nf1.format(t.doc_tonn)} т по документам`} />
        <Cell label="Недолив (претензия)" value={`${nf0.format(t.shortfall_ttn)} ТТН`}
              hint={`${nf0.format(Math.abs(t.shortfall_kg))} кг недобор`} tone="text-red-600 dark:text-red-400" />
        <Cell label="Без замера" value={`${nf0.format(t.not_measured_ttn)} ТТН`}
              hint={`${nf1.format(t.not_measured_kg / 1000)} т приняты вслепую`} tone={t.not_measured_ttn ? 'text-amber-600 dark:text-amber-400' : undefined} />
        <Cell label="Перелив" value={`${nf0.format(t.surplus_ttn)} ТТН`} tone="text-sky-600 dark:text-sky-400" />
        <Cell label="Плотность расходится" value={`${nf0.format(t.density_mismatch)} ТТН`}
              hint="принята другая партия" />
      </div>

      {/* Плитки классов — кликабельны как фильтр */}
      <div className="flex flex-wrap gap-2">
        <ClassChip active={fClass === 'all'} onClick={() => setFClass('all')}
                   label="Все ТТН" count={t.ttn} />
        {data.classes.map((c) => (
          <ClassChip
            key={c.klass}
            active={fClass === c.klass}
            onClick={() => setFClass(fClass === c.klass ? 'all' : c.klass)}
            label={c.title}
            count={c.count}
            klass={c.klass}
            hint={c.klass !== 'ok' ? `${c.diff_kg >= 0 ? '+' : ''}${nf0.format(c.diff_kg)} кг` : undefined}
          />
        ))}
        <span className="ml-auto flex items-center gap-3">
          <span className="text-[11px] text-muted-foreground">
            строк: {nf0.format(rows.length)}{fClass !== 'all' ? ` из ${nf0.format(t.ttn)}` : ''}
          </span>
          <Button variant="outline" size="sm" className="h-8" onClick={() => exportXlsx(data)}>
            <Download className="mr-1.5 h-3.5 w-3.5" />Экспорт в Excel
          </Button>
        </span>
      </div>

      {/* Лента ТТН */}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[1180px] text-xs">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr>
              <Th>ТТН</Th><Th>Дата</Th><Th>АЗС</Th><Th>Рез.</Th><Th>Топливo</Th>
              <Th right>Документ, кг</Th><Th right>Факт, кг</Th><Th right>Отклонение</Th>
              <Th right>Плотн. док</Th><Th right>Плотн. факт</Th><Th right>Темп.</Th>
              <Th>Причина</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.ttn}:${r.station_code}:${r.tank}:${i}`} className={cn(
                'border-t',
                r.klass === 'shortfall' && 'bg-red-500/5',
                (r.klass === 'not_measured' || r.klass === 'broken_measure') && 'bg-amber-500/5',
              )}>
                <Td>{r.ttn}</Td>
                <Td>{r.date ? new Date(r.date).toLocaleDateString('ru-RU') : '—'}</Td>
                <Td>{r.station_name}</Td>
                <Td>{r.tank != null ? `№${r.tank}` : '—'}</Td>
                <Td>{r.fuel_name}</Td>
                <Td right>{nf1.format(r.doc_mass_kg)}</Td>
                <Td right>{nf1.format(r.fact_mass_kg)}</Td>
                <Td right className={cn('font-medium',
                  r.diff_mass_kg < -0.05 ? 'text-red-600 dark:text-red-400'
                    : r.diff_mass_kg > 0.05 ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground')}>
                  {r.diff_mass_kg >= 0 ? '+' : ''}{nf0.format(r.diff_mass_kg)} кг
                  {r.diff_pct != null && (
                    <span className="ml-1 text-[10px] text-muted-foreground">{nf1.format(r.diff_pct)}%</span>
                  )}
                </Td>
                <Td right className="text-muted-foreground">{r.density_doc != null ? nf3.format(r.density_doc) : '—'}</Td>
                <Td right className={r.density_mismatch ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
                  {r.density_fact != null ? nf3.format(r.density_fact) : '—'}
                </Td>
                <Td right className="text-muted-foreground">{r.temp_fact != null ? `${nf1.format(r.temp_fact)}°` : '—'}</Td>
                <Td>
                  <Badge variant="outline" className={CLASS_TONE[r.klass]}>{r.klass_title}</Badge>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Отклонение считается по массе (кг): при сливе станция часто переписывает
        объём из накладной, а реальный недобор виден только в массе. Допуск приёмки —
        {' '}{nf1.format(data.tolerance.pct * 100)}% массы (не меньше {nf0.format(data.tolerance.min_kg)} кг).
        «Без замера» и «сорванный замер» — это не доказанная недостача, а
        ненадёжные данные приёмки: их нельзя предъявлять поставщику как недолив.
      </p>
    </div>
  )
}

async function exportXlsx(data: ReceiptAnalysisResponse) {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()
  const rows = data.rows.map((r) => ({
    'ТТН': r.ttn,
    'Дата': r.date ? new Date(r.date).toLocaleDateString('ru-RU') : '',
    'АЗС': r.station_name,
    'Резервуар': r.tank,
    'Топливо': r.fuel_name,
    'Поставщик': r.supplier,
    'Документ, кг': r.doc_mass_kg,
    'Факт, кг': r.fact_mass_kg,
    'Отклонение, кг': r.diff_mass_kg,
    'Отклонение, %': r.diff_pct ?? '',
    'Документ, л': r.doc_volume_l,
    'Факт, л': r.fact_volume_l,
    'Плотность док.': r.density_doc ?? '',
    'Плотность факт.': r.density_fact ?? '',
    'Плотность расходится': r.density_mismatch ? 'да' : '',
    'Темп. док., °C': r.temp_doc ?? '',
    'Темп. факт., °C': r.temp_fact ?? '',
    'Причина': r.klass_title,
  }))
  const ws = XLSX.utils.json_to_sheet(rows)
  ws['!cols'] = [{ wch: 8 }, { wch: 11 }, { wch: 12 }, { wch: 9 }, { wch: 8 }, { wch: 12 }, ...Array(12).fill({ wch: 13 })]
  XLSX.utils.book_append_sheet(wb, ws, 'Ошибки слива')
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.by_station.map((s) => ({
    'АЗС': s.station_name, 'ТТН': s.ttn, 'Документ, кг': s.doc_kg, 'Отклонение, кг': s.diff_kg,
    'Недоливов': s.shortfall, 'Переливов': s.surplus, 'Без замера': s.not_measured, 'Сорван замер': s.broken_measure,
  }))), 'По АЗС')
  XLSX.writeFile(wb, `oshibki_sliva_${data.period.from}_${data.period.to}.xlsx`)
}

function ClassChip({ active, onClick, label, count, klass, hint }: {
  active: boolean; onClick: () => void; label: string; count: number
  klass?: ReceiptClass; hint?: string
}) {
  return (
    <button
      type="button" onClick={onClick}
      className={cn(
        'rounded-md border px-2.5 py-1.5 text-xs transition-colors',
        active ? 'bg-primary text-primary-foreground' : 'hover:bg-muted/50',
      )}
    >
      <span className={cn(!active && klass && CLASS_TONE[klass].split(' ')[1])}>{label}</span>
      <span className="ml-1.5 font-semibold">{nf0.format(count)}</span>
      {hint && <span className={cn('ml-1', active ? 'opacity-80' : 'text-muted-foreground')}>{hint}</span>}
    </button>
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
