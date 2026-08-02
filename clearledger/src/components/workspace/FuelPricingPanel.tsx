/**
 * «Изменения цен» — решение о цене как предмет разбора (fuel, ГИГ).
 *
 * Табы: Журнал (события смены цены) · Волны (решения сети) · Календарь (станция × день).
 * Данные — /api/fuel/pricing/{changes,calendar}.
 *
 * Семантика цвета здесь НЕ «хорошо/плохо»: рост и снижение цены — два типа события,
 * а не оценка, поэтому направление кодируется знаком и стрелкой, а цвет взят
 * приглушённой парой (янтарь/лазурь). Зелёный и красный оставлены реакции объёма —
 * там смысл однозначен: литры выросли или упали.
 */

import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, ArrowUp, ArrowDown, ChevronsUpDown, TrendingUp, TrendingDown } from 'lucide-react'
import { Kpi } from './analytics/Kpi'
import { ExportButton } from './analytics/ExportButton'
import { PanelViewTabs } from './PanelViewTabs'
import { ViewParamsBar } from './ViewParamsBar'
import { useTabParams } from '@/hooks/useTabParams'
import { useScopeSubtitle } from '@/hooks/useScopeReset'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import {
  getFuelPriceChanges, getFuelPriceCalendar, type FuelPriceWave,
} from '@/services/fuelSalesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const dmy = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
const dm = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })

/** Направление события: цвет-пара без оценочного смысла. */
const dirCls = (step: number) => (step > 0
  ? 'text-amber-600 dark:text-amber-400'
  : 'text-sky-600 dark:text-sky-400')
/** Реакция объёма: здесь зелёный/красный уместны — литры выросли или упали. */
const respCls = (v: number) => (v > 0 ? 'text-emerald-600 dark:text-emerald-400'
  : v < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')

const signed = (v: number, nf: Intl.NumberFormat) => `${v > 0 ? '+' : ''}${nf.format(v)}`
/** Склонение дней: «1 день · 2 дня · 5 дней». */
const days = (n: number) => {
  const t = n % 100 > 4 && n % 100 < 21 ? 5 : n % 10
  return `${nf0.format(n)} ${t === 1 ? 'день' : t > 1 && t < 5 ? 'дня' : 'дней'}`
}

function exportRows(name: string, columns: string[], rows: (string | number | null)[][]) {
  return { 'data-export-name': name, 'data-export-rows': JSON.stringify({ columns, rows }) }
}
function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет данных за период' }: { text?: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

interface TabProps { companyId: string; dateFrom: string; dateTo: string }

/** Общий запрос трёх табов: журнал строится один раз и переиспользуется. */
function useChanges({ companyId, dateFrom, dateTo }: TabProps) {
  const fk = useFuelKindFilter()
  return useQuery({
    queryKey: ['fuel-price-changes', companyId, dateFrom, dateTo, fk.key],
    queryFn: () => getFuelPriceChanges({ companyId, dateFrom, dateTo, fuelCodes: fk.fuelCodes }),
  })
}

/* ────────────────────────── Таб: Журнал ────────────────────────── */

type SortKey = 'day' | 'station' | 'fuel_name' | 'step' | 'held_days' | 'response_pct'

function JournalTab(p: TabProps) {
  const { data, isLoading } = useChanges(p)
  const [f, patch] = useTabParams('fuel_pricing/log', { fuel: 'all', dir: 'all' })
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'day', dir: 'desc' })

  const fuels = useMemo(
    () => Array.from(new Set((data?.events ?? []).map((e) => e.fuel_name))).sort((a, b) => a.localeCompare(b, 'ru')),
    [data],
  )
  const rows = useMemo(() => {
    const src = (data?.events ?? []).filter((e) => (
      (f.fuel === 'all' || e.fuel_name === f.fuel)
      && (f.dir === 'all' || (f.dir === 'up' ? e.step > 0 : e.step < 0))
    ))
    const mul = sort.dir === 'asc' ? 1 : -1
    return [...src].sort((a, b) => {
      const va = a[sort.key], vb = b[sort.key]
      if (typeof va === 'string' || typeof vb === 'string') return mul * String(va).localeCompare(String(vb), 'ru')
      return mul * ((va ?? 0) - (vb ?? 0))
    })
  }, [data, f.fuel, f.dir, sort])

  const t = data?.totals
  const toggle = (k: SortKey) => setSort((s) => (s.key === k ? { key: k, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: 'desc' }))
  const Th = ({ k, label, left }: { k: SortKey; label: string; left?: boolean }) => {
    const on = sort.key === k
    const Ico = on ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    return (
      <th aria-sort={on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
        className={`p-2 font-medium ${left ? 'text-left' : 'text-right'}`}>
        <button onClick={() => toggle(k)} title="Сортировать"
          className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${left ? '' : 'flex-row-reverse'} ${on ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{label}</span>
          <Ico className={`h-3 w-3 shrink-0 ${on ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </th>
    )
  }

  return (
    <div className="space-y-4">
      <ViewParamsBar>
        <Field label="Топливо">
          <Select value={f.fuel} onValueChange={(v) => patch({ fuel: v })}>
            <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все виды</SelectItem>
              {fuels.map((x) => <SelectItem key={x} value={x} className="text-xs">{x}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Направление">
          <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
            {[{ v: 'all', l: 'Все' }, { v: 'up', l: 'Рост' }, { v: 'down', l: 'Снижение' }].map((o) => (
              <button key={o.v} type="button" onClick={() => patch({ dir: o.v })}
                className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${f.dir === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                {o.l}
              </button>
            ))}
          </div>
        </Field>
      </ViewParamsBar>

      {isLoading ? <Loading /> : !t || t.events === 0 ? <Empty text="За период цену не меняли" /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-2">
            <Kpi label="Изменений" value={nf0.format(t.events)}
              sub={`${nf0.format(t.waves)} решений сети${t.jumps ? ` · ${nf0.format(t.jumps)} догоняющих` : ''}`} />
            <Kpi label="Повышений" value={nf0.format(t.ups)} sub={t.ups ? `типичный шаг ${signed(t.step_up_avg, nf2)} ₽/л` : undefined}
              cls="text-amber-600 dark:text-amber-400" />
            <Kpi label="Снижений" value={nf0.format(t.downs)} sub={t.downs ? `типичный шаг ${signed(t.step_down_avg, nf2)} ₽/л` : undefined}
              cls="text-sky-600 dark:text-sky-400" />
            <Kpi label="Цена держится" value={days(Math.round(t.held_median))} sub="медиана между сменами" />
            <Kpi label="Реакция объёма"
              value={t.response_median == null ? '—' : `${signed(t.response_median, nf1)}%`}
              sub={t.response_median == null ? 'окна ещё не закрылись' : `медиана по ${nf0.format(t.responded)} событиям`}
              cls={t.response_median == null ? undefined : respCls(t.response_median)} />
          </div>

          <div className="text-xs text-muted-foreground">
            Событие — смена цены стеллы относительно прошлого торгового дня; сутки с объёмом ниже
            десятой доли обычного (техпролив, простой ТРК) в расчёт не идут. «Реакция» — медианный
            суточный объём за {data!.window_days} дней после против {data!.window_days} дней до;
            «—» значит окно ещё не закрылось, а не отсутствие реакции.
          </div>

          <Card><CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-xs" {...exportRows('Изменения цен',
              ['Дата', 'Станция', 'Топливо', 'Было ₽/л', 'Стало ₽/л', 'Шаг ₽/л', 'Шаг %', 'Держалась, дней', 'Литров/сут до', 'Литров/сут после', 'Реакция %'],
              rows.map((e) => [dmy(e.day), e.station, e.fuel_name, e.was, e.became, e.step, e.step_pct,
                e.held_days, e.liters_before, e.liters_after, e.window_full ? e.response_pct : null]))}>
              <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                <Th k="day" label="Дата" left />
                <Th k="station" label="Станция" left />
                <Th k="fuel_name" label="Топливо" left />
                <th className="p-2 font-medium text-right whitespace-nowrap">Было → стало</th>
                <Th k="step" label="Шаг ₽/л" />
                <Th k="held_days" label="Держалась" />
                <th className="p-2 font-medium text-right whitespace-nowrap">Л/сут до → после</th>
                <Th k="response_pct" label="Реакция" />
              </tr></thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={`${e.day}|${e.station_code}|${e.fuel_code}`} className="border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 whitespace-nowrap font-medium">{dmy(e.day)}</td>
                    <td className="p-2 truncate max-w-[220px]">{e.station}</td>
                    <td className="p-2 text-muted-foreground whitespace-nowrap">{e.fuel_name}</td>
                    <td className="p-2 text-right tabular-nums font-mono whitespace-nowrap">
                      <span className="text-muted-foreground">{nf2.format(e.was)}</span>
                      <span className="mx-1 text-muted-foreground/50">→</span>
                      <span className="font-medium text-foreground">{nf2.format(e.became)}</span>
                    </td>
                    <td className={`p-2 text-right tabular-nums font-mono whitespace-nowrap ${dirCls(e.step)}`}>
                      {e.step > 0 ? <TrendingUp className="inline h-3 w-3 mr-0.5 align-[-1px]" /> : <TrendingDown className="inline h-3 w-3 mr-0.5 align-[-1px]" />}
                      {signed(e.step, nf2)}
                      <span className="ml-1 text-[10px] opacity-70">{signed(e.step_pct, nf1)}%</span>
                      {e.jump && (
                        <span className="ml-1.5 rounded border border-current/40 px-1 text-[9px] uppercase tracking-wide opacity-80"
                          title="Догоняющий скачок: между продажами станция стояла и пропустила промежуточные ступени. В типичный шаг и волны не входит.">
                          догон
                        </span>
                      )}
                    </td>
                    <td className="p-2 text-right tabular-nums font-mono text-muted-foreground">{e.held_days || '—'}</td>
                    <td className="p-2 text-right tabular-nums font-mono text-muted-foreground whitespace-nowrap">
                      {e.liters_before == null ? '—' : nf0.format(e.liters_before)}
                      <span className="mx-1 opacity-50">→</span>
                      {e.liters_after == null ? '—' : nf0.format(e.liters_after)}
                    </td>
                    <td className={`p-2 text-right tabular-nums font-mono ${e.response_pct != null && e.window_full ? respCls(e.response_pct) : 'text-muted-foreground/40'}`}>
                      {e.response_pct == null ? '—' : e.window_full ? `${signed(e.response_pct, nf1)}%` : <span title={`Окно ${data!.window_days} дней ещё не закрылось`}>~{signed(e.response_pct, nf1)}%</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        </>
      )}
    </div>
  )
}

/* ────────────────────────── Таб: Волны ────────────────────────── */

/** Одно ценовое решение сети: доехало до N станций за M дней. */
function WaveRow({ w, stationsTotal }: { w: FuelPriceWave; stationsTotal: number }) {
  const covered = stationsTotal > 0 ? (w.stations / stationsTotal) * 100 : 0
  const spread = Math.abs(w.step_max - w.step_min) > 0.005
  return (
    <tr className="border-b border-border/30 hover:bg-muted/30">
      <td className="p-2 whitespace-nowrap font-medium">
        {dm(w.from)}{w.from !== w.to && <><span className="mx-1 text-muted-foreground/50">–</span>{dm(w.to)}</>}
        <div className="text-[10px] text-muted-foreground">{days(w.days)}</div>
      </td>
      <td className="p-2 whitespace-nowrap">{w.fuel_name}</td>
      <td className={`p-2 text-right tabular-nums font-mono whitespace-nowrap ${dirCls(w.step_avg)}`}>
        {signed(w.step_avg, nf2)}
        {spread && <div className="text-[10px] opacity-70">{signed(w.step_min, nf2)}…{signed(w.step_max, nf2)}</div>}
      </td>
      <td className="p-2 text-right tabular-nums font-mono whitespace-nowrap">
        {nf0.format(w.stations)}<span className="text-muted-foreground/60"> из {nf0.format(stationsTotal)}</span>
        <div className="mt-1 h-1 w-full min-w-[60px] rounded-full bg-muted overflow-hidden">
          <div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.min(100, covered)}%` }} />
        </div>
      </td>
      <td className="p-2 text-muted-foreground truncate max-w-[220px]">{w.first.join(', ')}</td>
      <td className="p-2 text-muted-foreground truncate max-w-[220px]">{w.days > 1 ? w.last.join(', ') : '—'}</td>
    </tr>
  )
}

function WavesTab(p: TabProps) {
  const { data, isLoading } = useChanges(p)
  const waves = data?.waves ?? []
  // Знаменатель охвата — станции, которые вообще торговали этим топливом в периоде.
  const stationsByFuel = useMemo(() => {
    const m = new Map<number, Set<number>>()
    ;(data?.events ?? []).forEach((e) => {
      if (!m.has(e.fuel_code)) m.set(e.fuel_code, new Set())
      m.get(e.fuel_code)!.add(e.station_code)
    })
    return m
  }, [data])

  return (
    <div className="space-y-4">
      <div className="text-xs text-muted-foreground">
        Решение о цене доезжает до станций не одномоментно. Волна — события одного вида топлива в одну
        сторону, идущие подряд (разрыв до трёх суток). Столбец «Дошло последними» показывает, кого
        пересмотрели с опозданием: пока станция стоит по старой цене, сеть торгует по двум ценникам.
      </div>
      {isLoading ? <Loading /> : waves.length === 0 ? <Empty text="За период решений по цене не было" /> : (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs" {...exportRows('Волны изменения цен',
            ['Период', 'Топливо', 'Шаг ₽/л средний', 'Шаг мин', 'Шаг макс', 'Станций', 'Дней', 'Пошли первыми', 'Дошло последними'],
            waves.map((w) => [`${dmy(w.from)}–${dmy(w.to)}`, w.fuel_name, w.step_avg, w.step_min, w.step_max,
              w.stations, w.days, w.first.join(', '), w.days > 1 ? w.last.join(', ') : '']))}>
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Когда</th>
              <th className="p-2 text-left font-medium">Топливо</th>
              <th className="p-2 text-right font-medium whitespace-nowrap">Шаг ₽/л</th>
              <th className="p-2 text-right font-medium">Охват сети</th>
              <th className="p-2 text-left font-medium whitespace-nowrap">Пошли первыми</th>
              <th className="p-2 text-left font-medium whitespace-nowrap">Дошло последними</th>
            </tr></thead>
            <tbody>
              {waves.map((w) => (
                <WaveRow key={`${w.fuel_code}|${w.from}|${w.to}`} w={w}
                  stationsTotal={stationsByFuel.get(w.fuel_code)?.size ?? w.stations} />
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}
    </div>
  )
}

/* ──────────────────────── Таб: Календарь ──────────────────────── */

function CalendarTab(p: TabProps) {
  const { data: changes } = useChanges(p)
  const fuels = useMemo(() => {
    const m = new Map<number, string>()
    ;(changes?.events ?? []).forEach((e) => m.set(e.fuel_code, e.fuel_name))
    return Array.from(m, ([code, name]) => ({ code, name })).sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [changes])
  const [c, patch] = useTabParams('fuel_pricing/cal', { fuel: '' })
  const fuelCode = Number(c.fuel) || fuels[0]?.code || 0

  const { data, isLoading } = useQuery({
    queryKey: ['fuel-price-calendar', p.companyId, p.dateFrom, p.dateTo, fuelCode],
    queryFn: () => getFuelPriceCalendar({ companyId: p.companyId, dateFrom: p.dateFrom, dateTo: p.dateTo, fuelCode }),
    enabled: fuelCode > 0,
  })

  // Шкала — по процентилям (границы приходят с бэка): за полугодие цена растёт на треть,
  // и при шкале «мин…макс» весь последний месяц становится одного оттенка.
  const lo = data?.scale_low ?? data?.price_min ?? 0
  const hi = data?.scale_high ?? data?.price_max ?? 0
  /** Уровень цены → насыщенность одной hue: шкала читается как «дороже — плотнее». */
  const shade = (price: number) => (hi > lo
    ? 0.1 + Math.min(1, Math.max(0, (price - lo) / (hi - lo))) * 0.75
    : 0.4)
  const byDay = useMemo(() => (data?.rows ?? []).map((r) => ({
    ...r, map: new Map(r.cells.map((cell) => [cell.day, cell])),
  })), [data])

  return (
    <div className="space-y-4">
      <ViewParamsBar>
        <Field label="Топливо">
          <Select value={String(fuelCode)} onValueChange={(v) => patch({ fuel: v })}>
            <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {fuels.map((x) => <SelectItem key={x.code} value={String(x.code)} className="text-xs">{x.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        {data && lo > 0 && (
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>{nf2.format(lo)} ₽/л</span>
            <span className="h-3 w-24 rounded-sm" style={{ background: 'linear-gradient(90deg, hsl(var(--primary)/0.1), hsl(var(--primary)/0.85))' }} />
            <span>{nf2.format(hi)} ₽/л</span>
            <span className="ml-2 inline-flex items-center gap-1">
              <span className="inline-block h-3 w-3 rounded-sm ring-1 ring-foreground/70" /> день смены цены
            </span>
          </div>
        )}
      </ViewParamsBar>

      {fuels.length === 0 ? <Empty text="За период цену не меняли — календарь пуст" />
        : isLoading ? <Loading />
        : !data || data.rows.length === 0 ? <Empty />
        : (
          <Card><CardContent className="p-0 overflow-x-auto">
            <table className="text-xs border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className="sticky left-0 z-10 bg-background p-2 text-left font-medium text-muted-foreground border-b">АЗС</th>
                  {data.days.map((d, i) => (
                    <th key={d} className="border-b p-0 pb-1 align-bottom">
                      {/* Подпись каждого 7-го дня: 300+ подписей в ряд не читаются. */}
                      {i % 7 === 0 && <div className="text-[9px] text-muted-foreground/70 -rotate-90 origin-center w-[14px] h-8 whitespace-nowrap">{dm(d)}</div>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {byDay.map((r) => (
                  <tr key={r.station_code}>
                    <td className="sticky left-0 z-10 bg-background p-2 whitespace-nowrap border-b border-border/30">
                      <span className="font-medium">{r.station}</span>
                    </td>
                    {data.days.map((d) => {
                      const cell = r.map.get(d)
                      if (!cell) {
                        return <td key={d} className="border-b border-border/30 p-0"><div className="h-5 w-[14px] bg-muted/20" title={`${dmy(d)} · нет продаж`} /></td>
                      }
                      return (
                        <td key={d} className="border-b border-border/30 p-0">
                          <div
                            className={`h-5 w-[14px] ${cell.changed ? 'ring-1 ring-inset ring-foreground/70' : ''}`}
                            style={{ background: `hsl(var(--primary) / ${shade(cell.price)})` }}
                            title={`${dmy(d)} · ${r.station} · ${nf2.format(cell.price)} ₽/л · ${nf0.format(cell.liters)} л`
                              + (cell.changed ? ' · цена изменена' : '') + (cell.varies ? ' · в течение дня цена менялась' : '')}
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        )}
      {data && data.rows.length > 0 && (
        <div className="text-xs text-muted-foreground">
          Строка — станция (сверху те, что продают больше), столбец — сутки. Плотность цвета — уровень цены
          в пределах {data.fuel_name}; обводка — день, когда цену сменили. Вертикальная полоса обводок
          означает одно решение сети, лесенка — что оно доезжало по станциям несколько дней.
        </div>
      )}
    </div>
  )
}

/* ─────────────────────── Контейнер табов ─────────────────────── */

const PRICING_TABS: { k: string; label: string }[] = [
  { k: 'log', label: 'Журнал' },
  { k: 'waves', label: 'Волны' },
  { k: 'cal', label: 'Календарь' },
]

/** Пункт «Изменения цен» — контейнер с внутренними табами. */
export function FuelPricingPanel({ companyId, dateFrom, dateTo }: TabProps) {
  const [t, patch] = useTabParams('fuel_pricing', { sub: 'log' })
  const p: TabProps = { companyId, dateFrom, dateTo }
  const ref = useRef<HTMLDivElement>(null)
  const curLabel = PRICING_TABS.find((x) => x.k === t.sub)?.label ?? 'Журнал'
  const scopeSub = useScopeSubtitle({ scopeApplied: false })  // API не принимает сужение по станциям
  return (
    <div>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <PanelViewTabs tabs={PRICING_TABS} value={t.sub} onChange={(k) => patch({ sub: k })} ariaLabel="Виды пункта «Изменения цен»" />
        <ExportButton title={`Изменения цен · ${curLabel}`} subtitle={scopeSub} getEl={() => ref.current} />
      </div>
      <div ref={ref} className="p-4" key={t.sub}>
        {t.sub === 'log' && <JournalTab {...p} />}
        {t.sub === 'waves' && <WavesTab {...p} />}
        {t.sub === 'cal' && <CalendarTab {...p} />}
      </div>
    </div>
  )
}
