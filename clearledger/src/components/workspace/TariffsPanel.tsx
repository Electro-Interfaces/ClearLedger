/**
 * Пункт «Тарифы» — ценообразование сети ЭЗС (розница/публичная цена).
 * Внутренние табы: Прайс-лист (сетка) · По тарифам · Средний тариф · Факт vs номинал · Динамика.
 * Данные — /api/tariffs/* (сетка, факт vs номинал) + analytics (разрезы, timeseries).
 * Договорные тарифы ЮЛ — в «Корпоратив».
 */
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Kpi } from './analytics/Kpi'
import { ExportButton } from './analytics/ExportButton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-react'
import { useTabParams } from '@/hooks/useTabParams'
import { getTariffGrid, getFactVsNominal, type FvnLine } from '@/services/tariffService'
import { getChargeSessions, getChargeTimeseries, type ChargeSessionLine } from '@/services/analyticsService'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const money = (v: number) => nf0.format(Math.round(v || 0)) + ' ₽'
const moneyK = (v: number) => (Math.abs(v) >= 10000 ? nf1.format(v / 1000) + ' тыс' : nf0.format(v)) + ' ₽'
const rub = (v: number) => nf2.format(v)
const gapCls = (v: number) => (v < -0.05 ? 'text-amber-400/90' : v > 0.05 ? 'text-emerald-400/90' : 'text-muted-foreground')

function Loading() { return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> }
function Empty({ text }: { text: string }) { return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div> }


interface TabProps { companyId: string; dateFrom: string; dateTo: string }

// ── Общая сортируемая таблица ──
interface Col<T> { key: string; label: string; left?: boolean; get: (r: T) => number | string; cell: (r: T) => ReactNode }
function SortTable<T>({ rows, cols, initial, rowKey }: { rows: T[]; cols: Col<T>[]; initial: string; rowKey: (r: T, i: number) => string }) {
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: initial, dir: 'desc' })
  const col = useMemo(() => cols.find((c) => c.key === sort.key) ?? cols[0], [cols, sort.key])
  const sorted = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = col.get(a), vb = col.get(b)
      if (typeof va === 'string' || typeof vb === 'string') return dir * String(va).localeCompare(String(vb), 'ru')
      return dir * (va - vb)
    })
  }, [rows, col, sort.dir])
  const toggle = (k: string) => setSort((s) => (s.key === k ? { key: k, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: 'desc' }))
  return (
    <Card><CardContent className="p-0 overflow-x-auto">
      <table className="w-full text-xs">
        <thead><tr className="border-b bg-muted/40 text-muted-foreground">
          {cols.map((c) => {
            const on = sort.key === c.key
            const Ico = on ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
            return (
              <th key={c.key} className={`p-2 font-medium ${c.left ? 'text-left' : 'text-right'}`}>
                <button onClick={() => toggle(c.key)} title="Сортировать"
                  className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${c.left ? '' : 'flex-row-reverse'} ${on ? 'text-foreground' : ''}`}>
                  <span className="whitespace-nowrap">{c.label}</span>
                  <Ico className={`h-3 w-3 shrink-0 ${on ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
                </button>
              </th>
            )
          })}
        </tr></thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={rowKey(r, i)} className="border-b border-border/30 hover:bg-muted/30">
              {cols.map((c, j) => (
                <td key={c.key} className={`p-2 ${c.left ? 'text-left font-medium truncate max-w-[260px]' : 'text-right tabular-nums'} ${j === 0 ? '' : 'text-muted-foreground'}`}>{c.cell(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </CardContent></Card>
  )
}

const CUT_OPTS = [
  { v: 'region', label: 'По регионам' },
  { v: 'station', label: 'По станциям' },
  { v: 'connector', label: 'По коннекторам' },
  { v: 'user_type', label: 'По типу клиента' },
]

// ── Таб: Прайс-лист (сетка регион|станция × коннектор) ──
function PriceGrid({ companyId, dateFrom, dateTo }: TabProps) {
  const [g, patch] = useTabParams('tf_grid', { by: 'region' })
  const { data, isLoading } = useQuery({
    queryKey: ['tariff-grid', companyId, dateFrom, dateTo, g.by],
    queryFn: () => getTariffGrid({ companyId, dateFrom, dateTo, by: g.by }),
  })
  const cell = (row: string, conn: string) => data?.cells.find((c) => c.row === row && c.connector === conn)
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Розничная тарифная сетка (преобладающий тариф ₽/кВтч; «~» — варьируется). Разрез:</span>
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5">
          {[{ v: 'region', l: 'По регионам' }, { v: 'station', l: 'По станциям' }].map((o) => (
            <button key={o.v} type="button" onClick={() => patch({ by: o.v })}
              className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${g.by === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{o.l}</button>
          ))}
        </div>
      </div>
      {isLoading ? <Loading /> : !data || data.cells.length === 0 ? <Empty text="Нет данных за период" /> : (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="text-left p-2 font-medium sticky left-0 bg-muted/40">{g.by === 'station' ? 'Станция' : 'Регион'}</th>
              {data.connectors.map((c) => <th key={c} className="text-right p-2 font-medium whitespace-nowrap">{c}</th>)}
            </tr></thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="text-left p-2 font-medium truncate max-w-[240px] sticky left-0 bg-background">{row}</td>
                  {data.connectors.map((conn) => {
                    const c = cell(row, conn)
                    return (
                      <td key={conn} className="text-right p-2 tabular-nums" title={c ? `${c.sessions} сес · факт ${rub(c.realized)} ₽/кВтч${c.varies ? ` · диапазон ${rub(c.tariff_min)}–${rub(c.tariff_max)}` : ''}` : ''}>
                        {c ? <span className={c.varies ? 'text-amber-300/90' : ''}>{rub(c.tariff)}{c.varies ? '~' : ''}</span> : <span className="text-muted-foreground/30">—</span>}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}
    </div>
  )
}

// ── Таб: По тарифам (разрез по значению тарифа) ──
function ByTariff({ companyId, dateFrom, dateTo }: TabProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['tariff-by', companyId, dateFrom, dateTo],
    queryFn: () => getChargeSessions({ companyId, dateFrom, dateTo, groupBy: 'tariff' }),
  })
  if (isLoading) return <Loading />
  if (!data || data.lines.length === 0) return <Empty text="Нет данных" />
  const cols: Col<ChargeSessionLine>[] = [
    { key: 'label', label: 'Тариф', left: true, get: (r) => r.label, cell: (r) => r.label },
    { key: 'sessions', label: 'Сессий', get: (r) => r.sessions, cell: (r) => nf0.format(r.sessions) },
    { key: 'energy_kwh', label: 'Энергия кВтч', get: (r) => r.energy_kwh, cell: (r) => nf0.format(r.energy_kwh) },
    { key: 'amount', label: 'Выручка', get: (r) => r.amount, cell: (r) => money(r.amount) },
    { key: 'share_pct', label: 'Доля', get: (r) => r.share_pct, cell: (r) => nf1.format(r.share_pct) + '%' },
    { key: 'avg_check', label: 'Ср. чек', get: (r) => r.avg_check, cell: (r) => money(r.avg_check) },
  ]
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">Какие ценовые точки дают бизнес: выручка/энергия/сессии по значению тарифа.</div>
      <SortTable rows={data.lines} cols={cols} initial="amount" rowKey={(r) => r.label} />
    </div>
  )
}

// ── Таб: Средний тариф (карта цен по разрезу) ──
function AvgTariff({ companyId, dateFrom, dateTo }: TabProps) {
  const [cut, patch] = useTabParams('tf_avg', { by: 'region' })
  const { data, isLoading } = useQuery({
    queryKey: ['tariff-avg', companyId, dateFrom, dateTo, cut.by],
    queryFn: () => getChargeSessions({ companyId, dateFrom, dateTo, groupBy: cut.by as never }),
  })
  const cols: Col<ChargeSessionLine>[] = [
    { key: 'label', label: 'Разрез', left: true, get: (r) => r.label, cell: (r) => r.label },
    { key: 'sessions', label: 'Сессий', get: (r) => r.sessions, cell: (r) => nf0.format(r.sessions) },
    { key: 'energy_kwh', label: 'Энергия кВтч', get: (r) => r.energy_kwh, cell: (r) => nf0.format(r.energy_kwh) },
    { key: 'amount', label: 'Выручка', get: (r) => r.amount, cell: (r) => money(r.amount) },
    { key: 'price_per_kwh', label: 'Ср. ₽/кВтч', get: (r) => r.price_per_kwh, cell: (r) => <span className="font-medium text-foreground">{rub(r.price_per_kwh)}</span> },
  ]
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Средневзвешенная цена ₽/кВтч — где дорого/дёшево. Разрез:</span>
        <Select value={cut.by} onValueChange={(v) => patch({ by: v })}>
          <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{CUT_OPTS.map((o) => <SelectItem key={o.v} value={o.v} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      {isLoading ? <Loading /> : !data || data.lines.length === 0 ? <Empty text="Нет данных" /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            <Kpi label="Ср. ₽/кВтч (сеть)" value={rub(data.totals.price_per_kwh)} />
            <Kpi label="Энергия" value={`${nf0.format(data.totals.energy_kwh)} кВтч`} />
            <Kpi label="Выручка" value={moneyK(data.totals.amount)} />
          </div>
          <SortTable rows={data.lines} cols={cols} initial="price_per_kwh" rowKey={(r) => r.label} />
        </>
      )}
    </div>
  )
}

// ── Таб: Факт vs номинал ──
function FactVsNominal({ companyId, dateFrom, dateTo }: TabProps) {
  const [cut, patch] = useTabParams('tf_fvn', { by: 'region' })
  const { data, isLoading } = useQuery({
    queryKey: ['tariff-fvn', companyId, dateFrom, dateTo, cut.by],
    queryFn: () => getFactVsNominal({ companyId, dateFrom, dateTo, groupBy: cut.by }),
  })
  const cols: Col<FvnLine>[] = [
    { key: 'label', label: 'Разрез', left: true, get: (r) => r.label, cell: (r) => r.label },
    { key: 'energy_kwh', label: 'Энергия кВтч', get: (r) => r.energy_kwh, cell: (r) => nf0.format(r.energy_kwh) },
    { key: 'nominal', label: 'Номинал ₽/кВтч', get: (r) => r.nominal, cell: (r) => rub(r.nominal) },
    { key: 'realized', label: 'Факт ₽/кВтч', get: (r) => r.realized, cell: (r) => <span className="font-medium text-foreground">{rub(r.realized)}</span> },
    { key: 'delta', label: 'Отклонение', get: (r) => r.delta, cell: (r) => <span className={gapCls(r.delta)}>{rub(r.delta)}</span> },
    { key: 'delta_pct', label: '%', get: (r) => r.delta_pct, cell: (r) => <span className={gapCls(r.delta)}>{nf1.format(r.delta_pct)}%</span> },
  ]
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Прайс (номинал `tariff`) vs реально полученная цена (выручка÷энергия). Отклонение &lt; 0 = скидки/промо. Разрез:</span>
        <Select value={cut.by} onValueChange={(v) => patch({ by: v })}>
          <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{CUT_OPTS.map((o) => <SelectItem key={o.v} value={o.v} className="text-xs">{o.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      {isLoading ? <Loading /> : !data || data.lines.length === 0 ? <Empty text="Нет данных" /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            <Kpi label="Номинал (сеть)" value={`${rub(data.totals.nominal)} ₽/кВтч`} />
            <Kpi label="Факт (сеть)" value={`${rub(data.totals.realized)} ₽/кВтч`} />
            <Kpi label="Отклонение" value={`${rub(data.totals.delta)} ₽/кВтч`} cls={gapCls(data.totals.delta)} />
          </div>
          <SortTable rows={data.lines} cols={cols} initial="energy_kwh" rowKey={(r) => r.label} />
        </>
      )}
    </div>
  )
}

// ── Таб: Динамика (ср.тариф по месяцам) ──
function TariffDynamics({ companyId, dateFrom, dateTo }: TabProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['tariff-dyn', companyId, dateFrom, dateTo],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'month', metric: 'price_per_kwh' }),
  })
  if (isLoading) return <Loading />
  const rows = (data?.data ?? []).map((r) => ({ bucket: String(r.bucket), value: Number(r['Вся сеть'] ?? r.value ?? 0) }))
  if (rows.length === 0) return <Empty text="Нет данных за период" />
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">Средневзвешенный тариф сети ₽/кВтч по месяцам (индексация/изменения цен).</div>
      <Card><CardContent className="p-3">
        <div data-chart>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={rows} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                tickFormatter={(b: string) => (b.length === 7 ? `${b.slice(5)}.${b.slice(2, 4)}` : b)} />
              <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                width={52} domain={['auto', 'auto']} tickFormatter={(v: number) => rub(v)} />
              <Tooltip cursor={{ stroke: 'hsl(var(--muted-foreground))', strokeDasharray: '3 3' }}
                labelFormatter={(b) => String(b)} formatter={(v) => [`${rub(Number(v))} ₽/кВтч`, 'Тариф']} />
              <Line type="monotone" dataKey="value" stroke="hsl(217, 91%, 60%)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent></Card>
    </div>
  )
}

const TARIFF_TABS: { k: string; label: string }[] = [
  { k: 'grid', label: 'Прайс-лист (сетка)' },
  { k: 'by', label: 'По тарифам' },
  { k: 'avg', label: 'Средний тариф' },
  { k: 'fvn', label: 'Факт vs номинал' },
  { k: 'dyn', label: 'Динамика' },
]

/** Контейнер пункта «Тарифы» с внутренними табами. */
export function TariffsPanel({ companyId, dateFrom, dateTo }: TabProps) {
  const [t, patch] = useTabParams('tariffs', { sub: 'grid' })
  const p: TabProps = { companyId, dateFrom, dateTo }
  const ref = useRef<HTMLDivElement>(null)
  const curLabel = TARIFF_TABS.find((x) => x.k === t.sub)?.label ?? 'Тарифы'
  return (
    <div>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4">
        <div className="flex items-stretch gap-0.5 overflow-x-auto">
          {TARIFF_TABS.map((x) => {
            const on = t.sub === x.k
            return (
              <button key={x.k} type="button" onClick={() => patch({ sub: x.k })}
                className={`whitespace-nowrap border-b-2 -mb-px px-3 py-2.5 text-[13px] transition-colors ${on ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}`}>
                {x.label}
              </button>
            )
          })}
        </div>
        <ExportButton title={`Тарифы ЭЗС · ${curLabel}`} subtitle={`Период: ${dateFrom} — ${dateTo}`} getEl={() => ref.current} />
      </div>
      <div ref={ref} className="p-4" key={t.sub}>
        {t.sub === 'grid' && <PriceGrid {...p} />}
        {t.sub === 'by' && <ByTariff {...p} />}
        {t.sub === 'avg' && <AvgTariff {...p} />}
        {t.sub === 'fvn' && <FactVsNominal {...p} />}
        {t.sub === 'dyn' && <TariffDynamics {...p} />}
      </div>
    </div>
  )
}
