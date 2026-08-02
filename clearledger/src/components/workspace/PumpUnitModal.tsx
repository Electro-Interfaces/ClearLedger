/**
 * Расшифровка строки «Загрузки ТРК»: из чего сложились её цифры.
 *
 * Сущность строки — единица оборудования (АЗС × ТРК × пистолет × вид топлива), то
 * есть физический объект, а не агрегат разных вещей: поэтому расшифровка открывается
 * окном, а не меняет фильтр (канон разбора строки в продукте — см. «Магазин»).
 *
 * Четыре ответа на «откуда цифры», в порядке вопросов, с которыми открывают:
 *   1. Динамика по суткам — реализации столбиками и цена линией: видно, работал ли
 *      рукав ровно или рывками и что было с ценой в эти дни;
 *   2. Простои — КОГДА именно не работал: «56 дней без работы» это либо сломанный
 *      рукав в мае, либо конец периода, и это разные разговоры с сервисом;
 *   3. Часы — профиль суток: когда через рукав идёт поток;
 *   4. Источник — таблица, грейн, объём и границы выборки: чтобы цифре можно было
 *      доверять, надо видеть, из чего она посчитана.
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts'
import { Loader2, Gauge, AlertTriangle, Clock, Database } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fmtMoneyShort, fmtLiters } from '@/services/analyticsService'
import { getFuelUnitDetail, type UnitDetailResponse } from '@/services/fuelNetworkService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const dmy = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
const dm = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
const dt = (iso: string | null) => (iso ? new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—')
/** Склонение суток: «1 день · 2 дня · 5 дней». */
const days = (n: number) => {
  const t = n % 100 > 4 && n % 100 < 21 ? 5 : n % 10
  return `${nf0.format(n)} ${t === 1 ? 'день' : t > 1 && t < 5 ? 'дня' : 'дней'}`
}

export interface PumpUnitRef {
  stationCode: number
  station: string
  pos: number | null
  nozzle: number | null
  fuelCode?: number | null
  fuelName?: string | null
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-sm font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium tabular-nums">{value}</span>
    </>
  )
}

/** Динамика: реализации столбиками, факт-цена линией на своей оси. */
function DailyChart({ d }: { d: UnitDetailResponse }) {
  const data = useMemo(() => d.daily.map((x) => ({ ...x, label: dm(x.date) })), [d.daily])
  if (data.length === 0) return <Empty text="За период ни одной реализации" />
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
            interval="preserveStartEnd" minTickGap={24} />
          <YAxis yAxisId="l" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} width={34} />
          <YAxis yAxisId="r" orientation="right" domain={['auto', 'auto']}
            tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} width={44}
            tickFormatter={(v) => nf0.format(Number(v))} />
          <RTooltip
            contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
            formatter={(v, n) => [
              n === 'price' ? `${nf2.format(Number(v))} ₽/л` : nf0.format(Number(v)),
              n === 'price' ? 'Цена' : 'Реализаций',
            ]} />
          <Bar yAxisId="l" dataKey="fills" fill="hsl(var(--chart-1) / 0.75)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
          <Line yAxisId="r" dataKey="price" stroke="hsl(var(--warning))" strokeWidth={1.6} dot={false}
            connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-1 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-blue-500/75" />реализаций в сутки</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-amber-500" />цена ₽/л (выручка ÷ литры)</span>
      </div>
    </div>
  )
}

/** Профиль суток: 24 столбика. Пустые часы остаются в ряду — их отсутствие и есть факт. */
function HourChart({ d }: { d: UnitDetailResponse }) {
  const max = Math.max(...d.hourly.map((h) => h.fills), 1)
  return (
    <div>
      <div className="flex items-end gap-[3px]" style={{ height: 120 }}>
        {d.hourly.map((h) => (
          <div key={h.hour} className="flex-1" title={`${String(h.hour).padStart(2, '0')}:00 — ${nf0.format(h.fills)} реализаций · ${fmtLiters(h.liters)}`}>
            <div className="w-full rounded-t-sm bg-primary/70"
              style={{ height: `${Math.max(h.fills ? 3 : 0, (h.fills / max) * 118)}px` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
        {[0, 6, 12, 18, 23].map((h) => <span key={h}>{String(h).padStart(2, '0')}:00</span>)}
      </div>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="p-6 text-center text-sm text-muted-foreground">{text}</div>
}

export function PumpUnitModal({ unit, companyId, dateFrom, dateTo, onClose }: {
  unit: PumpUnitRef | null
  companyId: string; dateFrom: string; dateTo: string
  onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-unit', companyId, dateFrom, dateTo, unit?.stationCode, unit?.pos, unit?.nozzle, unit?.fuelCode],
    queryFn: () => getFuelUnitDetail({
      companyId, dateFrom, dateTo,
      stationCode: unit!.stationCode, pos: unit?.pos, nozzle: unit?.nozzle, fuelCode: unit?.fuelCode,
    }),
    enabled: !!unit,
  })

  const title = unit
    ? `${unit.station} · ТРК ${unit.pos ?? '—'}${unit.nozzle != null ? ` · пистолет ${unit.nozzle}` : ''}`
      + (unit.fuelName ? ` · ${unit.fuelName}` : '')
    : ''

  return (
    <Dialog open={!!unit} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-[860px]">
        <DialogHeader>
          <DialogTitle className="text-sm">{title}</DialogTitle>
        </DialogHeader>

        {isLoading || !data ? (
          <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <>
            <div className="grid grid-cols-2 divide-x divide-border rounded-lg border md:grid-cols-4">
              <Stat label="Реализаций/сут" value={nf2.format(data.totals.fills_per_day)}
                sub={`${nf0.format(data.totals.fills)} за ${days(data.totals.days)}`} />
              <Stat label="Объём" value={fmtLiters(data.totals.liters)}
                sub={`ср. заправка ${nf1.format(data.totals.avg_fill)} л`} />
              <Stat label="Выручка" value={`${fmtMoneyShort(data.totals.amount)} ₽`}
                sub={`чек ${nf0.format(data.totals.avg_check)} ₽`} />
              <Stat label="Работал" value={days(data.totals.active_days)}
                sub={data.totals.idle_days ? `простой ${days(data.totals.idle_days)}` : 'без простоев'} />
            </div>

            <Tabs defaultValue="daily" className="mt-1">
              <TabsList variant="line" className="h-9">
                <TabsTrigger value="daily"><Gauge className="mr-1.5 h-3.5 w-3.5" />Динамика</TabsTrigger>
                <TabsTrigger value="gaps">
                  <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />Простои
                  {data.gaps.length ? <span className="ml-1 text-muted-foreground">{data.gaps.length}</span> : null}
                </TabsTrigger>
                <TabsTrigger value="hours"><Clock className="mr-1.5 h-3.5 w-3.5" />Часы</TabsTrigger>
                <TabsTrigger value="source"><Database className="mr-1.5 h-3.5 w-3.5" />Источник</TabsTrigger>
              </TabsList>

              <TabsContent value="daily" className="mt-3">
                <DailyChart d={data} />
              </TabsContent>

              <TabsContent value="gaps" className="mt-3">
                {data.gaps.length === 0 ? <Empty text="Рукав работал каждые сутки периода" /> : (
                  <>
                    <div className="mb-2 text-xs text-muted-foreground">
                      Сутки без единой реализации, склеенные в интервалы — от длинных к коротким.
                      Длинный интервал это остановка рукава, россыпь одиночных — обычные выходные дни точки.
                    </div>
                    <div className="overflow-hidden rounded-lg border">
                      <table className="w-full text-xs">
                        <thead><tr className="border-b bg-muted/35 text-muted-foreground">
                          <th className="p-2 text-left font-medium">Период простоя</th>
                          <th className="p-2 text-right font-medium">Длительность</th>
                          <th className="p-2 text-left font-medium">Доля периода</th>
                        </tr></thead>
                        <tbody>
                          {data.gaps.map((g) => (
                            <tr key={`${g.from}-${g.to}`} className="border-b border-border/50">
                              <td className="p-2 whitespace-nowrap font-medium">
                                {dmy(g.from)}{g.days > 1 && <> <span className="text-muted-foreground/60">–</span> {dmy(g.to)}</>}
                              </td>
                              <td className="p-2 text-right tabular-nums">{days(g.days)}</td>
                              <td className="p-2">
                                <div className="h-1.5 w-full max-w-[220px] overflow-hidden rounded-full bg-muted">
                                  <div className="h-full rounded-full bg-amber-500/80"
                                    style={{ width: `${Math.min(100, (g.days / data.totals.days) * 100)}%` }} />
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </TabsContent>

              <TabsContent value="hours" className="mt-3">
                <HourChart d={data} />
                <div className="mt-2 text-xs text-muted-foreground">
                  Часы московские. Пустой столбик — час, в котором через этот рукав не отпускали:
                  у ночной трассовой станции профиль ровный, у городской — с двумя горбами.
                </div>
              </TabsContent>

              <TabsContent value="source" className="mt-3">
                <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs">
                  <Row label="Таблица" value={data.source.table} />
                  <Row label="Грейн строки" value={data.source.grain} />
                  <Row label="Канал загрузки" value={data.source.channel} />
                  <Row label="Ключ отбора" value={data.source.keys.join(' · ')} />
                  <Row label="Строк в выборке" value={nf0.format(data.source.rows)} />
                  <Row label="Первая реализация" value={dt(data.source.first_dt)} />
                  <Row label="Последняя реализация" value={dt(data.source.last_dt)} />
                  <Row label="Смен" value={nf0.format(data.source.shifts)} />
                  <Row label="Разных карт" value={nf0.format(data.source.cards)} />
                  <Row label="Видов оплаты" value={nf0.format(data.source.pay_types)} />
                  <Row label="Резервуаров" value={nf0.format(data.source.tanks)} />
                  <Row label="Средняя цена" value={data.totals.avg_price ? `${nf2.format(data.totals.avg_price)} ₽/л` : '—'} />
                </div>
                <div className="mt-3 rounded-md border border-border/60 bg-muted/20 p-2.5 text-[11px] leading-relaxed text-muted-foreground">
                  Цифры строки — агрегат этих строк тем же фильтром, что и в таблице: период рабочей
                  области, область учёта и вид топлива. Поэтому «реализаций в сутки» делится на все
                  сутки периода, включая простой: иначе остановка рукава пряталась бы в среднем.
                </div>
              </TabsContent>
            </Tabs>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
