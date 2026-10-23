import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ViewParamsBar } from '../ViewParamsBar'
import { TzToggle, type Tz } from './TzToggle'
import { ConnectorFilter } from './ConnectorFilter'
import { CHART_SERIES } from './palette'
import { getHourlyOccupancy, occupancySeriesLabel, type OccupancyGroup, type OccupancyScope, type HourlyOccupancyResponse } from '@/services/chargeOccupancyService'
import { occupancyInterval } from '@/lib/occupancyInterval'

const HOURS = Array.from({ length: 24 }, (_, hour) => hour)
const hourLabel = (hour: number) => `${String(hour).padStart(2, '0')}:00`
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const detailNumber = new Intl.NumberFormat('ru-RU', { maximumSignificantDigits: 21 })
type Metric = 'occupancy_pct' | 'starts'

function HourTooltip({ active, label, data }: { active?: boolean; label?: unknown; data: HourlyOccupancyResponse }) {
  if (!active) return null
  const hour = Number(label)
  return <div role="region" aria-label="Станции в подсказке" tabIndex={0} onWheel={e => e.stopPropagation()} onPointerMove={e => e.stopPropagation()} onMouseMove={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()} className="max-h-72 max-w-[min(30rem,85vw)] overflow-auto overscroll-contain rounded-md border bg-popover p-3 text-xs text-popover-foreground shadow-md">
    <p className="mb-2 font-medium">{hourLabel(hour)}–{hourLabel(hour + 1)}</p>
    {data.series.map((s, i) => {
      const p = s.points.find(p => p.hour === hour)!
      return <div key={s.id} className="mb-2 last:mb-0">
        <div className="flex items-start gap-2"><span className="mt-1 size-2 shrink-0 rounded-full" style={{ background: CHART_SERIES[i % CHART_SERIES.length] }} />{occupancySeriesLabel(s)}</div>
        <p className="pl-4 tabular-nums">Занятость: {p.occupancy_complete === false ? 'неизвестна' : `${nf.format(p.occupancy_pct)}% · ${nf.format(p.occupied_minutes)}`} из {nf.format(p.available_minutes)} мин</p>
        <p className="pl-4 tabular-nums">Начатые сессии: {p.starts_complete === false ? 'неизвестно' : `${nf.format(p.starts)} шт.`}</p>
      </div>
    })}
  </div>
}

export function HourlyOccupancy({ companyId, dateFrom, dateTo, narrow, tz, onTzChange }: {
  companyId: string; dateFrom: string; dateTo: string
  narrow: OccupancyScope & { key: string }; tz: Tz; onTzChange: (tz: Tz) => void
}) {
  const [groupBy, setGroupBy] = useState<OccupancyGroup>('auto')
  const [metric, setMetric] = useState<Metric>('occupancy_pct')
  const [connectorTypes, setConnectorTypes] = useState<string[]>([])
  const [connectorIds, setConnectorIds] = useState<string[]>([])
  const [hourFrom, setHourFrom] = useState(0)
  const [hourTo, setHourTo] = useState(24)
  const { data, isPending, isFetching, error, refetch } = useQuery({
    queryKey: ['charge-hourly-occupancy', companyId, dateFrom, dateTo, narrow.key, tz, groupBy, connectorTypes, connectorIds],
    queryFn: () => getHourlyOccupancy({ companyId, dateFrom, dateTo, ...narrow, tz, groupBy, connectorTypes, connectorIds }),
    retry: false,
  })
  const types = useMemo(() => [...new Set([...(data?.connector_types ?? []), ...(data?.connectors.flatMap(c => c.connector_type ? [c.connector_type] : []) ?? [])])]
    .sort().map(type => ({ id: type, label: type })), [data?.connectors, data?.connector_types])
  const ports = useMemo(() => data?.connectors.map(c => ({ id: c.id, label: occupancySeriesLabel(c) })) ?? [], [data?.connectors])
  const rows = useMemo(() => {
    const result: Record<string, number | null>[] = HOURS.map(hour => ({ hour }))
    data?.series.forEach((s, i) => s.points.forEach(p => { result[p.hour][`s${i}`] = p[metric === 'starts' ? 'starts_complete' : 'occupancy_complete'] === false ? null : p[metric] }))
    return result
  }, [data, metric])
  const occupancy = metric === 'occupancy_pct'
  const title = occupancy ? 'Занятость по часам, %' : 'Начатые сессии по часам, шт.'
  const quality = data?.quality
  const hasQualityIssues = quality && (quality.missing_interval_sessions > 0 || quality.missing_connector_sessions > 0 || quality.unmapped_station_sessions > 0)
  const detailColumns = [data?.group_by === 'station' ? 'Станция' : 'Физический порт', 'Занятость, %', 'Занято, мин', 'В расчётном периоде, мин', 'Начатые сессии, шт.']
  const detailRows = data?.series.map(s => {
    const p = occupancyInterval(s.points, hourFrom, hourTo)
    return [occupancySeriesLabel(s), p.occupancy_pct, p.occupied_minutes, p.available_minutes, p.starts]
  }) ?? []
  const metadata = [
    ['Период', `${dateFrom} — ${dateTo} (включительно)`],
    ['Интервал детализации', `${hourLabel(hourFrom)}–${hourLabel(hourTo)}, каждый день; конец не включён`],
    ['Часовой пояс', tz === 'msk' ? 'Московское время' : 'Местное время каждой станции'],
    ['Разрез', data?.group_by === 'connector' ? 'Физические порты' : 'Станции'],
    ['Показатель графика', title],
    ['Станции: отбор', narrow.stations?.join(', ') || 'Все в текущем контуре'],
    ['Регионы: отбор', narrow.regions?.join(', ') || 'Все'],
    ['Дополнительный отбор', narrow.dim ? `${narrow.dim}: ${narrow.dimVal ?? ''}` : 'Нет'],
    ['Типы коннекторов', connectorTypes.join(', ') || 'Все'],
    ['Физические порты', connectorIds.length ? connectorIds.map(id => ports.find(p => p.id === id)?.label || id).join('; ') : 'Все'],
    ['Метод расчёта', 'Пересечение сессий с интервалом; пересекающиеся сессии объединены. Станция занята, если занят хотя бы один выбранный порт.'],
    ['Неполные данные', `Без корректного интервала: ${quality?.missing_interval_sessions ?? 0}; без порта: ${quality?.missing_connector_sessions ?? 0}; без станции: ${quality?.unmapped_station_sessions ?? 0}. Пустая числовая ячейка означает неизвестное значение.`],
  ]
  return <section className="min-w-0 space-y-4 p-4" aria-label="Почасовая занятость ЭЗС" data-export-state={error || isPending || isFetching ? 'unavailable' : 'ready'} data-export-meta={JSON.stringify(metadata)}>
    <ViewParamsBar label={null}>
      <Select value={metric} onValueChange={v => setMetric(v as Metric)}>
        <SelectTrigger className="min-h-11 w-[225px] max-w-full sm:min-h-9" aria-label="Показатель"><SelectValue /></SelectTrigger>
        <SelectContent className="[&_[role=option]]:min-h-11 sm:[&_[role=option]]:min-h-0"><SelectItem value="occupancy_pct">Занятость, %</SelectItem><SelectItem value="starts">Начатые сессии, шт.</SelectItem></SelectContent>
      </Select>
      <Select value={groupBy} onValueChange={v => setGroupBy(v as OccupancyGroup)}>
        <SelectTrigger className="min-h-11 w-[190px] max-w-full sm:min-h-9" aria-label="Разрез"><SelectValue /></SelectTrigger>
        <SelectContent className="[&_[role=option]]:min-h-11 sm:[&_[role=option]]:min-h-0"><SelectItem value="auto">Авто</SelectItem><SelectItem value="station">Станции</SelectItem><SelectItem value="connector">Коннекторы</SelectItem></SelectContent>
      </Select>
      <TzToggle value={tz} onChange={onTzChange} className="[&_button]:min-h-11 sm:[&_button]:min-h-0" />
      <ConnectorFilter label="Типы коннекторов" options={types} value={connectorTypes} onChange={setConnectorTypes} disabled={isPending} />
      <ConnectorFilter label="Физические порты" options={ports} value={connectorIds} onChange={setConnectorIds} disabled={isPending} />
      {connectorTypes.length + connectorIds.length > 0 ? <Button variant="ghost" size="sm" className="h-11 sm:h-9" onClick={() => { setConnectorTypes([]); setConnectorIds([]) }}>Сбросить отборы</Button> : null}
    </ViewParamsBar>
    <p className="text-xs text-muted-foreground">{tz === 'local' ? 'Местное время каждой станции.' : 'Московское время.'} {groupBy === 'auto' ? 'Авто: одна станция — отдельные порты, несколько — станции.' : 'Разрез не меняет выбранные отборы.'}</p>
    {error ? <div role="alert" className="space-y-2 rounded-md border border-destructive/40 p-4 text-sm">
      <p className="font-medium">Не удалось получить почасовые данные</p><p>{error.message}</p>
      <Button variant="outline" size="sm" className="h-11 sm:h-9" disabled={isFetching} onClick={() => void refetch()}>{isFetching ? 'Повторяем запрос…' : 'Повторить запрос'}</Button>
    </div> : isPending ? <div role="status" className="flex h-80 items-center justify-center rounded-md border bg-muted/30 text-sm text-muted-foreground">Загружаем почасовые данные…</div> : data ? <>
      {hasQualityIssues ? <div role="status" className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" aria-hidden="true" />
        <div><p className="font-medium">Есть ограничения качества данных</p><p>Без корректного интервала: {quality.missing_interval_sessions}; без физического порта: {quality.missing_connector_sessions}; без связи со станцией: {quality.unmapped_station_sessions}.</p>
          <p className="text-xs text-muted-foreground">Неполные интервалы не входят в занятость. Начатые сессии учитываются по времени старта.</p></div>
      </div> : null}
      {quality && quality.missing_connector_sessions > 0 && data.group_by === 'connector' ? <div className="flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm">
        <p className="max-w-3xl">Физическая детализация неполная: у части сессий нет номера порта. Неизвестная занятость не означает свободный порт.</p>
        <Button variant="outline" size="sm" className="h-11 sm:h-9" onClick={() => setGroupBy('station')}>Показать станции</Button>
      </div> : null}
      {data.series.length ? <>
        <div className="space-y-3" aria-busy={isFetching} data-export-chart>
          <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-medium">{title}</h3><span className="text-xs text-muted-foreground">{data.group_by === 'station' ? 'По станциям' : 'По физическим портам'}{isFetching ? ' · Обновляем…' : ''}</span></div>
          <div className="h-80 w-full min-w-0" data-chart aria-label={`${title}, 24 часа`}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
              <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 12, left: 0 }} accessibilityLayer>
                <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="hour" type="number" domain={[0, 23]} ticks={HOURS} interval="preserveStartEnd" minTickGap={18} tickFormatter={h => String(h).padStart(2, '0')} tick={{ fontSize: 11 }} />
                <YAxis domain={occupancy ? [0, 100] : [0, 'auto']} ticks={occupancy ? [0, 25, 50, 75, 100] : undefined} allowDecimals={false} width={48} tickFormatter={v => `${v}${occupancy ? '%' : ''}`} tick={{ fontSize: 11 }} />
                <Tooltip content={<HourTooltip data={data} />} wrapperStyle={{ pointerEvents: 'auto', zIndex: 20 }} filterNull={false} />
                {data.series.map((s, i) => <Line key={s.id} dataKey={`s${i}`} name={occupancySeriesLabel(s)} type="linear" stroke={CHART_SERIES[i % CHART_SERIES.length]} strokeDasharray={i >= CHART_SERIES.length ? `${4 + Math.floor(i / CHART_SERIES.length) * 2} 3` : undefined} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ul aria-label="Легенда графика" data-export-expand className="flex max-h-36 flex-wrap gap-x-5 gap-y-2 overflow-y-auto text-xs">
            {data.series.map((s, i) => <li key={s.id} className="flex min-w-0 items-start gap-2"><span aria-hidden="true" className="mt-1.5 w-5 shrink-0 border-t-2" style={{ borderColor: CHART_SERIES[i % CHART_SERIES.length], borderTopStyle: i >= CHART_SERIES.length ? 'dashed' : 'solid' }} /><span className="break-words">{occupancySeriesLabel(s)}</span></li>)}
          </ul>
        </div>
        <details className="rounded-md border p-3">
          <summary className="min-h-11 cursor-pointer text-sm font-medium sm:min-h-8">Детализация за интервал</summary>
          <div className="my-3 flex flex-wrap items-center gap-2 text-sm" data-export-ignore>
            <span>С</span><Select value={String(hourFrom)} onValueChange={v => { const h = Number(v); setHourFrom(h); if (h >= hourTo) setHourTo(h + 1) }}><SelectTrigger aria-label="Начало интервала" className="min-h-11 w-24 sm:min-h-9"><SelectValue /></SelectTrigger><SelectContent>{HOURS.map(h => <SelectItem key={h} value={String(h)}>{hourLabel(h)}</SelectItem>)}</SelectContent></Select>
            <span>До</span><Select value={String(hourTo)} onValueChange={v => { const h = Number(v); setHourTo(h); if (h <= hourFrom) setHourFrom(h - 1) }}><SelectTrigger aria-label="Конец интервала" className="min-h-11 w-24 sm:min-h-9"><SelectValue /></SelectTrigger><SelectContent>{HOURS.map(h => <SelectItem key={h + 1} value={String(h + 1)}>{hourLabel(h + 1)}</SelectItem>)}</SelectContent></Select>
          </div>
          <p className="my-2 text-xs text-muted-foreground">{hourLabel(hourFrom)}–{hourLabel(hourTo)} каждого выбранного дня. Конец интервала не включён. Учитываются части сессий, начавшихся раньше; «Неизвестно» означает, что не все сессии связаны с выбранными портами.</p>
          <div className="overflow-x-auto"><table className="w-full text-sm tabular-nums" data-export-name="Детализация интервала" data-export-rows={JSON.stringify({ columns: detailColumns, rows: detailRows })}><caption className="sr-only">Детализация за {hourLabel(hourFrom)}–{hourLabel(hourTo)}</caption>
            <thead><tr className="border-b text-xs text-muted-foreground">{detailColumns.map((column, i) => <th key={column} className={`p-2 font-medium ${i ? 'text-right' : 'text-left'}`}>{column}</th>)}</tr></thead>
            <tbody>{detailRows.map((row, n) => <tr key={data.series[n].id} className="border-b last:border-0"><th className="min-w-48 p-2 text-left font-normal">{row[0]}</th>{row.slice(1).map((v, i) => <td key={i} className="p-2 text-right">{v == null ? 'Неизвестно' : detailNumber.format(Number(v))}</td>)}</tr>)}</tbody>
          </table></div>
        </details>
        <div hidden aria-hidden="true">
          <table data-export-name="Данные графика" data-export-rows={JSON.stringify({ columns: [detailColumns[0], 'Час с', 'Час до', ...detailColumns.slice(1)], rows: data.series.flatMap(s => s.points.map(p => [occupancySeriesLabel(s), hourLabel(p.hour), hourLabel(p.hour + 1), p.occupancy_complete === false ? null : p.occupancy_pct, p.occupancy_complete === false ? null : p.occupied_minutes, p.available_minutes, p.starts_complete === false ? null : p.starts])) })} />
          <table data-export-name="Легенда" data-export-rows={JSON.stringify({ columns: ['Ряд', 'Станция / порт', 'Цвет', 'Линия'], rows: data.series.map((s, i) => [i + 1, occupancySeriesLabel(s), CHART_SERIES[i % CHART_SERIES.length], i >= CHART_SERIES.length ? 'Штриховая' : 'Сплошная']) })} />
        </div>
      </> : <p className="rounded-md border p-6 text-sm text-muted-foreground">Нет почасовых данных для выбранного периода и отборов.{connectorIds.length || connectorTypes.length ? ' Сбросьте отборы или измените общий контур.' : ' Измените период или общий контур.'}</p>}
      <p className="max-w-4xl text-xs text-muted-foreground">Занятость — доля времени в каждом часе суток за выбранные дни. Для станции учитывается время, когда занят хотя бы один выбранный порт. Типы и физические порты ограничивают оба показателя. Каталог портов — из паспорта и истории в текущем контуре.</p>
      {quality?.last_session_at ? <p className="text-xs text-muted-foreground">Последняя сессия в данных: {quality.last_session_at.replace('T', ' ')}</p> : null}
    </> : null}
  </section>
}
