/**
 * «Цены и маржа» (Аналитика) — инструмент менеджера: сегмент (Всё / Сопутка /
 * Общепит), анализ по группам (категория / вид номенклатуры — какая группа сколько
 * маржи приносит) и реестр SKU. Клик по товару → модалка: метрики + история цен
 * (переоценки) + динамика продаж + закупки + остаток.
 * Данные: /api/store/pricing, /api/store/sku/{guid} (GoodsDashboardService).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip, CartesianGrid } from 'recharts'
import {
  getStorePricing, getStoreSkuDetail,
  type PricingSku, type PricingGroup, type PriceCategory, type SkuDetailData,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const pctStr = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${nf(v, d)}%`)
const marginCls = (v: number | null | undefined) => (v == null ? '' : v < 0 ? 'text-red-400/80' : v < 10 ? 'text-amber-300/90' : 'text-emerald-300/80')

const SEGMENTS: { key: PriceCategory; label: string }[] = [
  { key: 'all', label: 'Всё вместе' },
  { key: 'soputka', label: 'Сопутка' },
  { key: 'obshepit', label: 'Общепит' },
]

type SortKey = 'qty' | 'revenue' | 'cost_net' | 'margin' | 'margin_pct' | 'markup_pct'

export function StorePricingPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [category, setCategory] = useState<PriceCategory>('all')
  const [groupBy, setGroupBy] = useState<'category' | 'kind'>('category')
  const [sortKey, setSortKey] = useState<SortKey>('revenue')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [q, setQ] = useState('')
  const [openGuid, setOpenGuid] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-pricing', companyId, dateFrom, dateTo, category],
    queryFn: () => getStorePricing(dateFrom, dateTo, category),
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
    <th onClick={() => toggleSort(k)} className="px-3 py-2 font-medium text-right whitespace-nowrap cursor-pointer select-none hover:text-foreground">
      {label}{sortKey === k && <span className="ml-0.5 opacity-60">{sortDir === 'asc' ? '▲' : '▼'}</span>}
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
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Цены и маржа</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data.period.from} – {data.period.to}. Сегмент, разбивка по группам и реестр SKU.
            Клик по товару — история цен, продажи, закупки. Себестоимость: сопутка — закупка, общепит — по ТТК.
          </p>
        </div>
        {/* Переключатель сегмента */}
        <div className="inline-flex rounded-md border border-border/50 overflow-hidden text-xs">
          {SEGMENTS.map((seg) => (
            <button key={seg.key} onClick={() => setCategory(seg.key)}
              className={`px-3 py-1.5 transition-colors ${category === seg.key ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:bg-accent/30'}`}>
              {seg.label}
            </button>
          ))}
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
            {skus.slice(0, 400).map((d: PricingSku) => (
              <tr key={d.guid} onClick={() => setOpenGuid(d.guid)} className="border-t border-border/30 hover:bg-accent/20 cursor-pointer">
                <td className="px-3 py-1.5">{d.marked && <span title="маркированный">🔖 </span>}{d.name}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{d.category ?? '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{nf(d.qty)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(d.revenue)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{d.cost_net != null ? fmtMoney(d.cost_net) : '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{d.margin != null ? fmtMoney(d.margin) : '—'}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${marginCls(d.margin_pct)}`}>{pctStr(d.margin_pct)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{pctStr(d.markup_pct)}</td>
                <td className="px-3 py-1.5 text-center">{d.abc}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {skus.length > 400 && <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">Показано 400 из {nf(skus.length)}. Уточните поиск.</div>}
        {skus.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет товаров за период (поставьте апрель).</div>}
      </div>

      {openGuid && <SkuDetailModal guid={openGuid} dateFrom={dateFrom} dateTo={dateTo} onClose={() => setOpenGuid(null)} />}
    </div>
  )
}

function SkuDetailModal({ guid, dateFrom, dateTo, onClose }: { guid: string; dateFrom: string; dateTo: string; onClose: () => void }) {
  const { data: d, isLoading } = useQuery({
    queryKey: ['store-sku', guid, dateFrom, dateTo],
    queryFn: () => getStoreSkuDetail(guid, dateFrom, dateTo),
  })

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg shadow-xl max-w-4xl w-full max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-5 py-3.5 border-b border-border/50">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-semibold truncate">{d?.name ?? 'Товар'}</h3>
              {d?.marked && <span className="inline-flex items-center rounded-full border border-emerald-400/40 text-emerald-300/80 px-2 py-0.5 text-[10px]">🔖 маркир.</span>}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {[d?.category, d?.kind, d?.article ? `арт. ${d.article}` : null, d?.vat ? `НДС ${d.vat}` : null].filter(Boolean).join(' · ') || ' '}
            </p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none px-2 shrink-0">×</button>
        </div>

        <div className="overflow-auto p-5 space-y-4">
          {isLoading || !d ? <div className="text-sm text-muted-foreground py-8 text-center">Загрузка детализации…</div> : (
            <SkuDetailBody d={d} />
          )}
        </div>
      </div>
    </div>
  )
}

function SkuDetailBody({ d }: { d: SkuDetailData }) {
  const m = d.metrics
  const METRICS: { label: string; value: string; cls?: string }[] = [
    { label: 'Продано', value: nf(m.qty) },
    { label: 'Выручка', value: fmtMoney(m.revenue) },
    { label: 'Средняя цена', value: m.avg_price != null ? fmtMoney(m.avg_price) : '—' },
    { label: 'Себест. ед.', value: m.avg_cost != null ? fmtMoney(m.avg_cost) : '—' },
    { label: 'Маржа', value: m.margin != null ? fmtMoney(m.margin) : '—', cls: 'text-emerald-300/90' },
    { label: 'Маржа %', value: pctStr(m.margin_pct), cls: marginCls(m.margin_pct) },
    { label: 'Наценка %', value: pctStr(m.markup_pct) },
    { label: 'Закуплено', value: nf(m.purch_qty) },
  ]
  return (
    <>
      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-4">
        {METRICS.map((x) => (
          <div key={x.label} className="rounded-lg border border-border/50 bg-card/40 p-2.5">
            <div className="text-[10px] text-muted-foreground">{x.label}</div>
            <div className={`text-sm font-semibold tabular-nums mt-0.5 ${x.cls ?? ''}`}>{x.value}</div>
          </div>
        ))}
      </div>

      {/* Динамика продаж */}
      <div>
        <div className="text-xs font-medium mb-1.5">Динамика продаж (выручка/день) · {d.daily.length} дн.</div>
        <div className="rounded-md border border-border/40 bg-card/30 p-2">
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={d.daily} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border/40" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(v) => String(v).slice(8, 10)} tick={{ fontSize: 9 }} interval="preserveStartEnd" />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(v: any, _n: any, p: any) => [`${fmtMoney(v)} · ${nf(p?.payload?.qty ?? 0)}`, 'Выручка']}
                labelFormatter={(l) => `Дата: ${l}`} />
              <Bar dataKey="revenue" fill="currentColor" className="text-primary" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* История цен (переоценки) */}
        <div>
          <div className="text-xs font-medium mb-1.5">История цен (переоценки) · {d.price_history.length}</div>
          {d.price_history.length === 0 ? (
            <div className="text-xs text-muted-foreground rounded-md border border-border/40 px-3 py-3">Переоценок за период не было.</div>
          ) : (
            <div className="rounded-md border border-border/40 overflow-hidden max-h-52 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/20 text-muted-foreground sticky top-0"><tr>
                  <th className="px-2.5 py-1.5 text-left font-medium">Дата</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Была</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Стала</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Δ%</th>
                </tr></thead>
                <tbody>
                  {d.price_history.map((h, i) => (
                    <tr key={i} className="border-t border-border/20">
                      <td className="px-2.5 py-1">{h.date}</td>
                      <td className="px-2.5 py-1 text-right tabular-nums text-muted-foreground">{nf(h.old, 2)}</td>
                      <td className="px-2.5 py-1 text-right tabular-nums">{nf(h.new, 2)}</td>
                      <td className={`px-2.5 py-1 text-right tabular-nums ${(h.pct ?? 0) < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>{h.pct != null ? `${h.pct > 0 ? '+' : ''}${nf(h.pct, 1)}%` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Закупки + остаток */}
        <div className="space-y-3">
          <div>
            <div className="text-xs font-medium mb-1.5">Закупки · {d.purchases.length}</div>
            {d.purchases.length === 0 ? (
              <div className="text-xs text-muted-foreground rounded-md border border-border/40 px-3 py-3">
                Прямых закупок нет{d.category === 'Общепит' ? ' — себестоимость по ТТК (ингредиенты)' : ''}.
              </div>
            ) : (
              <div className="rounded-md border border-border/40 overflow-hidden max-h-40 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted/20 text-muted-foreground sticky top-0"><tr>
                    <th className="px-2.5 py-1.5 text-left font-medium">Дата</th>
                    <th className="px-2.5 py-1.5 text-left font-medium">Поставщик</th>
                    <th className="px-2.5 py-1.5 text-right font-medium">Кол-во</th>
                    <th className="px-2.5 py-1.5 text-right font-medium">Цена нетто</th>
                  </tr></thead>
                  <tbody>
                    {d.purchases.map((p, i) => (
                      <tr key={i} className="border-t border-border/20">
                        <td className="px-2.5 py-1">{p.date}</td>
                        <td className="px-2.5 py-1 truncate max-w-[140px]" title={p.supplier}>{p.supplier}</td>
                        <td className="px-2.5 py-1 text-right tabular-nums">{nf(p.qty, 3)}</td>
                        <td className="px-2.5 py-1 text-right tabular-nums">{p.price_net != null ? fmtMoney(p.price_net) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {d.stock.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1.5">Остаток</div>
              <div className="space-y-1">
                {d.stock.map((st, i) => (
                  <div key={i} className="flex items-center justify-between gap-2 text-xs rounded-md border border-border/40 px-2.5 py-1">
                    <span className="truncate">{st.warehouse}</span>
                    <span className={`tabular-nums shrink-0 ${st.qty < 0 ? 'text-red-400/80' : ''}`}>{nf(st.qty, 3)} шт{st.retail_price != null ? ` · ${fmtMoney(st.retail_price)}` : ''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
