/**
 * «Маржа и наценка» (Аналитика) — инструмент менеджера: сегмент (Всё / Сопутка /
 * Общепит), анализ по группам (категория / вид номенклатуры — какая группа сколько
 * маржи приносит) и реестр SKU. Клик по товару → модалка: метрики + история цен
 * (переоценки) + динамика продаж + закупки + остаток.
 * Данные: /api/store/pricing, /api/store/sku/{guid} (GoodsDashboardService).
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { getStorePricing, type PricingSku, type PricingGroup, type PriceCategory } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { SkuDetailModal } from './SkuDetailModal'
import { ExportButton } from './analytics/ExportButton'
import { ChzBadge } from '@/components/common/ChzBadge'
import { rowDrill } from './rowDrill'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const pctStr = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${nf(v, d)}%`)
const marginCls = (v: number | null | undefined) => (v == null ? '' : v < 0 ? 'text-red-400/80' : v < 10 ? 'text-amber-300/90' : 'text-emerald-300/80')

const SEGMENTS: { key: PriceCategory; label: string }[] = [
  { key: 'all', label: 'Всё вместе' },
  { key: 'soputka', label: 'Сопутка' },
  { key: 'obshepit', label: 'Общепит' },
]

type SortKey = 'qty' | 'revenue' | 'cost_net' | 'margin' | 'margin_pct' | 'markup_pct'

export function StorePricingPanel({ companyId, dateFrom, dateTo, stations }: { companyId: string; dateFrom: string; dateTo: string; stations?: string[] }) {
  const [category, setCategory] = useState<PriceCategory>('all')
  const [groupBy, setGroupBy] = useState<'category' | 'kind'>('category')
  const [sortKey, setSortKey] = useState<SortKey>('revenue')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [q, setQ] = useState('')
  const [openGuid, setOpenGuid] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-pricing', companyId, dateFrom, dateTo, category, stations],
    queryFn: () => getStorePricing(dateFrom, dateTo, category, stations),
  })

  const skus = useMemo(() => {
    const ql = q.toLowerCase().trim()
    const rows = (data?.skus ?? []).filter((s) => !ql || s.name.toLowerCase().includes(ql) || (s.article ?? '').includes(q))
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity, bv = b[sortKey] ?? -Infinity
      return av === bv ? 0 : (av > bv ? dir : -dir)
    })
  }, [data, q, sortKey, sortDir])
  const показ = useVisible(skus)

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка цен и маржи…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки</div>
  if (!data) return null

  const s = data.summary
  const groups = groupBy === 'category' ? data.by_category : data.by_kind
  const maxRev = Math.max(1, ...groups.map((g) => g.revenue))
  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }
  const th = (k: SortKey, label: string) => (
    <th aria-sort={sortKey === k ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="p-0 font-medium text-right whitespace-nowrap">
      <button type="button" onClick={() => toggleSort(k)}
        className="w-full px-3 py-2 text-right select-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60">
        {label}{sortKey === k && <span className="ml-0.5 opacity-60" aria-hidden="true">{sortDir === 'asc' ? '▲' : '▼'}</span>}
      </button>
    </th>
  )

  const KPIS = [
    { label: 'Выручка', value: fmtMoney(s.revenue) },
    { label: 'Себестоимость', value: fmtMoney(s.cogs), hint: `${nf(s.sku_costed)} SKU с себест.` },
    { label: 'Валовая маржа', value: fmtMoney(s.margin), cls: 'text-emerald-300/90' },
    { label: 'Маржа %', value: pctStr(s.margin_pct), cls: marginCls(s.margin_pct) },
    { label: 'Наценка %', value: pctStr(s.markup_pct) },
    { label: 'Убыточных SKU', value: nf(s.loss_makers), cls: s.loss_makers > 0 ? 'text-red-400/90' : '' },
  ]

  return (
    <div ref={ref} className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Маржа и наценка</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data.period.from} – {data.period.to}. Сегмент, разбивка по группам и реестр SKU.
            Клик по товару — история цен, продажи, закупки. Себестоимость: сопутка — закупка, общепит — по ТТК.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Переключатель сегмента */}
          <div className="inline-flex rounded-md border border-border/50 overflow-hidden text-xs">
            {SEGMENTS.map((seg) => (
              <button key={seg.key} onClick={() => setCategory(seg.key)}
                className={`px-3 py-1.5 transition-colors ${category === seg.key ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:bg-accent/30'}`}>
                {seg.label}
              </button>
            ))}
          </div>
          <ExportButton title="Маржа и наценка" subtitle={`${data.period.from} — ${data.period.to} · ${SEGMENTS.find((x) => x.key === category)?.label}`} getEl={() => ref.current} />
        </div>
      </div>

      {/* KPI */}
      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{k.hint}</div>}
          </div>
        ))}
      </div>

      {/* Разбивка по группам — какая группа сколько маржи приносит */}
      <div className="rounded-lg border border-border/50 bg-card/40 p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium">Прибыльность по группам</div>
          <div className="inline-flex rounded-md border border-border/50 overflow-hidden text-[11px]">
            <button onClick={() => setGroupBy('category')} className={`px-2 py-1 ${groupBy === 'category' ? 'bg-accent/40 font-medium' : 'text-muted-foreground'}`}>Категория</button>
            <button onClick={() => setGroupBy('kind')} className={`px-2 py-1 ${groupBy === 'kind' ? 'bg-accent/40 font-medium' : 'text-muted-foreground'}`}>Вид</button>
          </div>
        </div>
        <div className="space-y-1.5">
          {groups.map((g: PricingGroup) => (
            <div key={g.group} className="flex items-center gap-2 text-xs">
              <span className="w-40 text-left truncate shrink-0" title={g.group}>{g.group}</span>
              <span className="flex-1 h-4 bg-muted/30 rounded overflow-hidden relative">
                <span className="block h-full bg-primary/40" style={{ width: `${(g.revenue / maxRev) * 100}%` }} />
              </span>
              <span className="w-24 text-right tabular-nums shrink-0">{fmtMoney(g.revenue)}</span>
              <span className="w-12 text-right tabular-nums text-muted-foreground shrink-0">{pctStr(g.share)}</span>
              <span className={`w-16 text-right tabular-nums shrink-0 ${marginCls(g.margin_pct)}`}>{g.margin_pct != null ? `${nf(g.margin_pct, 1)}%` : '—'}</span>
            </div>
          ))}
        </div>
        <div className="text-[10px] text-muted-foreground/60 mt-1.5 flex justify-end gap-3"><span>выручка</span><span>доля</span><span>маржа%</span></div>
      </div>

      {/* Реестр SKU */}
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium">Товары ({nf(skus.length)})</div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара…"
          className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-52" />
      </div>
      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left">Товар</th>
              <th className="px-3 py-2 font-medium text-center">ЧЗ</th>
              <th className="px-3 py-2 font-medium text-left">Категория</th>
              {th('qty', 'Продано')}
              {th('revenue', 'Выручка')}
              {th('cost_net', 'Себест.ед')}
              {th('margin', 'Маржа ₽')}
              {th('margin_pct', 'Маржа%')}
              {th('markup_pct', 'Наценка%')}
              <th className="px-3 py-2 font-medium text-center">ABC</th>
            </tr>
          </thead>
          <tbody>
            {показ.visible.map((d: PricingSku) => (
              <tr key={d.guid} {...rowDrill(
                () => setOpenGuid(d.guid), `${d.name} — открыть карточку`,
                'border-t border-border/30',
              )}>
                <td className="px-3 py-1.5">{d.name}</td>
                <td className="px-3 py-1.5 text-center">{d.marked && <ChzBadge />}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{d.category ?? '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{nf(d.qty)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(d.revenue)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {d.cost_net != null ? fmtMoney(d.cost_net) : '—'}
                  {d.margin != null && !d.cost_reliable && <span className="ml-1 text-amber-400/70" title="себестоимость ненадёжна (весовой/блочный товар или малый объём закупки) — маржа ориентировочна, не учтена в групповой">⚠</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{d.margin != null ? fmtMoney(d.margin) : '—'}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${d.cost_reliable ? marginCls(d.margin_pct) : 'text-muted-foreground/50'}`}>{pctStr(d.margin_pct)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{pctStr(d.markup_pct)}</td>
                <td className="px-3 py-1.5 text-center">{d.abc}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="позиций" />
        {skus.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет товаров по выбранному периоду и фильтрам.</div>}
      </div>

      {openGuid && <SkuDetailModal guid={openGuid} dateFrom={dateFrom} dateTo={dateTo} stations={stations} onClose={() => setOpenGuid(null)} />}
    </div>
  )
}
