/**
 * «Ассортимент» (Аналитика) — инструмент менеджера: матрица ABC (вклад в выручку) ×
 * XYZ (стабильность спроса), оборачиваемость и запасы на реальном остатке, GMROI,
 * дефицит / неликвиды / затоварка и action-list по SKU. Клик по товару → модалка.
 * Данные: /api/store/assortment (GoodsDashboardService.assortment_analysis).
 */
import { Fragment, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreAssortment, type AssortmentSku, type PriceCategory, type StockStatus } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { SkuDetailModal } from './SkuDetailModal'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

const SEGMENTS: { key: PriceCategory; label: string }[] = [
  { key: 'all', label: 'Всё вместе' }, { key: 'soputka', label: 'Сопутка' }, { key: 'obshepit', label: 'Общепит' },
]
const ABC = ['A', 'B', 'C'] as const
const XYZ = ['X', 'Y', 'Z'] as const

// тон ячейки: A×X (ядро) → зелёный, C×Z (вывод) → красный
function cellTone(abc: string, xyz: string): string {
  const score = ABC.indexOf(abc as 'A') + XYZ.indexOf(xyz as 'X')
  if (score <= 1) return 'bg-emerald-400/15 hover:bg-emerald-400/25'
  if (score === 2) return 'bg-amber-400/12 hover:bg-amber-400/22'
  return 'bg-red-400/12 hover:bg-red-400/22'
}

const STATUS_META: Record<StockStatus, { label: string; cls: string } | null> = {
  ok: null,
  dead: { label: 'неликвид', cls: 'border-red-400/40 text-red-300/80' },
  out_of_stock: { label: 'дефицит', cls: 'border-amber-400/40 text-amber-300/90' },
  overstock: { label: 'затоварка', cls: 'border-sky-400/40 text-sky-300/90' },
}

type SortKey = 'revenue' | 'qty' | 'stock_qty' | 'stock_cost' | 'days_of_supply' | 'gmroi'
type StatusFilter = 'all' | StockStatus

export function StoreAssortmentPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [category, setCategory] = useState<PriceCategory>('all')
  const [cell, setCell] = useState<string | null>(null)
  const [statusF, setStatusF] = useState<StatusFilter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('revenue')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [q, setQ] = useState('')
  const [openGuid, setOpenGuid] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-assortment', companyId, dateFrom, dateTo, category],
    queryFn: () => getStoreAssortment(dateFrom, dateTo, category),
  })

  const skus = useMemo(() => {
    const ql = q.toLowerCase().trim()
    const rows = (data?.skus ?? []).filter((s) =>
      (!cell || s.abc_xyz === cell) &&
      (statusF === 'all' || s.status === statusF) &&
      (!ql || s.name.toLowerCase().includes(ql)))
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity, bv = b[sortKey] ?? -Infinity
      return av === bv ? 0 : (av > bv ? dir : -dir)
    })
  }, [data, cell, statusF, q, sortKey, sortDir])

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка ассортимента…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки</div>
  if (!data) return null

  const s = data.summary
  const maxCell = Math.max(1, ...Object.values(data.matrix).map((m) => m.revenue))
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
    { label: 'Товаров (SKU)', value: nf(s.sku_count) },
    { label: 'Запас (себест.)', value: fmtMoney(s.stock_cost), hint: `в рознице ${fmtMoney(s.stock_retail)}` },
    { label: 'GMROI', value: s.gmroi == null ? '—' : nf(s.gmroi, 2), hint: 'маржа / запас' },
    { label: 'Неликвиды', value: nf(s.dead_count), hint: fmtMoney(s.dead_cost), cls: s.dead_count > 0 ? 'text-red-400/90' : '' },
    { label: 'Дефицит', value: nf(s.oos_count), hint: 'нет остатка, есть спрос', cls: s.oos_count > 0 ? 'text-amber-300/90' : '' },
    { label: 'Затоварка', value: nf(s.overstock_count), hint: fmtMoney(s.overstock_cost), cls: 'text-sky-300/90' },
  ]

  const STATUS_CHIPS: { key: StatusFilter; label: string }[] = [
    { key: 'all', label: 'Все' }, { key: 'dead', label: 'Неликвиды' },
    { key: 'out_of_stock', label: 'Дефицит' }, { key: 'overstock', label: 'Затоварка' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Ассортимент — ABC × XYZ</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data.period.from} – {data.period.to}. ABC (вклад в выручку) × XYZ (стабильность спроса), оборачиваемость
            на реальном остатке, GMROI. Клик по ячейке матрицы или товару. Неликвиды — только в «Всё вместе».
          </p>
        </div>
        <div className="inline-flex rounded-md border border-border/50 overflow-hidden text-xs">
          {SEGMENTS.map((seg) => (
            <button key={seg.key} onClick={() => { setCategory(seg.key); setCell(null); setStatusF('all') }}
              className={`px-3 py-1.5 transition-colors ${category === seg.key ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:bg-accent/30'}`}>
              {seg.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{k.hint}</div>}
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_1fr]">
        {/* Матрица ABC × XYZ */}
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-sm font-medium mb-2">Матрица ABC × XYZ</div>
          <div className="grid grid-cols-[auto_repeat(3,1fr)] gap-1 text-xs">
            <div />
            {XYZ.map((x) => <div key={x} className="text-center text-[10px] text-muted-foreground pb-0.5">{x}<span className="opacity-50">{x === 'X' ? ' стаб.' : x === 'Y' ? ' перем.' : ' спорад.'}</span></div>)}
            {ABC.map((a) => (
              <Fragment key={a}>
                <div className="flex items-center text-[10px] text-muted-foreground pr-1">{a}</div>
                {XYZ.map((x) => {
                  const key = `${a}${x}`
                  const m = data.matrix[key] ?? { count: 0, revenue: 0 }
                  const active = cell === key
                  return (
                    <button key={key} onClick={() => setCell(active ? null : key)}
                      className={`rounded-md p-2 text-left transition-colors ${cellTone(a, x)} ${active ? 'ring-2 ring-primary' : ''}`}>
                      <div className="flex items-baseline justify-between">
                        <span className="text-sm font-semibold tabular-nums">{m.count}</span>
                        <span className="text-[9px] text-muted-foreground uppercase">{key}</span>
                      </div>
                      <div className="text-[9px] text-muted-foreground tabular-nums" style={{ opacity: 0.5 + 0.5 * (m.revenue / maxCell) }}>{fmtMoney(m.revenue)}</div>
                    </button>
                  )
                })}
              </Fragment>
            ))}
          </div>
          <div className="text-[10px] text-muted-foreground/70 mt-2 leading-snug">
            <span className="text-emerald-300/80">AX</span> — ядро (держать) · <span className="text-red-300/80">CZ</span> — кандидаты на вывод.
            X стабильный / Z сporадический спрос (CV недельных продаж).
          </div>
        </div>

        {/* ABC-сводка */}
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-sm font-medium mb-2">ABC по вкладу в выручку</div>
          <div className="space-y-2">
            {ABC.map((a) => {
              const x = data.abc[a]
              const tone = a === 'A' ? 'bg-emerald-400/50' : a === 'B' ? 'bg-amber-400/50' : 'bg-muted-foreground/40'
              return (
                <div key={a} className="flex items-center gap-2 text-xs">
                  <span className="w-4 font-semibold">{a}</span>
                  <span className="flex-1 h-4 bg-muted/30 rounded overflow-hidden"><span className={`block h-full ${tone}`} style={{ width: `${x.share}%` }} /></span>
                  <span className="w-14 text-right tabular-nums text-muted-foreground shrink-0">{x.count} SKU</span>
                  <span className="w-12 text-right tabular-nums shrink-0">{x.share}%</span>
                  <span className="w-24 text-right tabular-nums shrink-0">{fmtMoney(x.revenue)}</span>
                </div>
              )
            })}
          </div>
          <div className="text-[10px] text-muted-foreground/70 mt-2">A ≈ 80% выручки, B ≈ 15%, C ≈ 5%. Класс A — фокус наличия и цен.</div>
        </div>
      </div>

      {/* Фильтры + реестр */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5">
          {STATUS_CHIPS.map((c) => (
            <button key={c.key} onClick={() => setStatusF(c.key)}
              className={`px-2.5 py-1 rounded-md text-xs border transition-colors ${statusF === c.key ? 'border-primary bg-primary/10 text-primary' : 'border-border/50 text-muted-foreground hover:bg-accent/30'}`}>
              {c.label}
            </button>
          ))}
          {cell && <span className="text-xs text-muted-foreground ml-1">ячейка {cell} · <button className="underline" onClick={() => setCell(null)}>сброс</button></span>}
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара…"
          className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-52" />
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left">Товар</th>
              <th className="px-3 py-2 font-medium text-center">ABC-XYZ</th>
              {th('qty', 'Продано')}
              {th('revenue', 'Выручка')}
              {th('stock_qty', 'Остаток')}
              {th('days_of_supply', 'Дни запаса')}
              {th('gmroi', 'GMROI')}
              <th className="px-3 py-2 font-medium text-left">Действие</th>
            </tr>
          </thead>
          <tbody>
            {skus.slice(0, 400).map((d: AssortmentSku) => {
              const stM = STATUS_META[d.status]
              return (
                <tr key={d.guid} onClick={() => setOpenGuid(d.guid)} className="border-t border-border/30 hover:bg-accent/20 cursor-pointer">
                  <td className="px-3 py-1.5">{d.marked && <span title="маркированный">🔖 </span>}{d.name}</td>
                  <td className="px-3 py-1.5 text-center"><span className="font-mono text-[11px] text-muted-foreground">{d.abc_xyz}</span></td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{nf(d.qty)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(d.revenue)}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${d.stock_qty < 0 ? 'text-red-400/70' : ''}`}>{nf(d.stock_qty, 3)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{d.days_of_supply != null ? nf(d.days_of_supply, 1) : '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{d.gmroi != null ? nf(d.gmroi, 2) : '—'}</td>
                  <td className="px-3 py-1.5">
                    {stM && <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] uppercase tracking-wide mr-1.5 ${stM.cls}`}>{stM.label}</span>}
                    <span className="text-muted-foreground">{d.action}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {skus.length > 400 && <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">Показано 400 из {nf(skus.length)}. Уточните фильтр.</div>}
        {skus.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет товаров по фильтру.</div>}
      </div>

      {openGuid && <SkuDetailModal guid={openGuid} dateFrom={dateFrom} dateTo={dateTo} onClose={() => setOpenGuid(null)} />}
    </div>
  )
}
