/**
 * Реестр SKU раздела «Магазин» — одна таблица под 4 экрана (mode):
 *   assortment  — ABC-анализ (класс + выручка + остаток);
 *   pricing     — цены и маржа (себест./маржа %/наценка, алерт отрицательной);
 *   nomenclature— карточки НСИ (артикул/НДС/маркировка/весовой);
 *   sales       — продажи по товарам (продано/выручка/ср.цена).
 * Данные: /api/store/skus (GoodsDashboardService.sku_analytics). Имена — из кеша НСИ ЦБ.
 */
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreSkus, type StoreSku } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

export type SkuMode = 'assortment' | 'pricing' | 'nomenclature' | 'sales' | 'stock' | 'marked'

const ABC_CLS: Record<'A' | 'B' | 'C', string> = {
  A: 'text-emerald-300/90', B: 'text-amber-300/90', C: 'text-muted-foreground',
}

interface Col {
  key: string
  label: string
  num?: boolean
  render: (s: StoreSku) => ReactNode
  cls?: (s: StoreSku) => string
}

const nameCell = (s: StoreSku): ReactNode => (
  <span>{s.marked && <span title="маркированный (Честный Знак)">🔖 </span>}{s.name}</span>
)

const COLS: Record<SkuMode, Col[]> = {
  assortment: [
    { key: 'abc', label: 'ABC', render: (s) => <span className={`font-semibold ${ABC_CLS[s.abc]}`}>{s.abc}</span> },
    { key: 'name', label: 'Товар', render: nameCell },
    { key: 'cat', label: 'Категория', render: (s) => s.category ?? '—' },
    { key: 'rev', label: 'Выручка', num: true, render: (s) => fmtMoney(s.revenue) },
    { key: 'qty', label: 'Продано', num: true, render: (s) => nf(s.qty) },
    { key: 'stock', label: 'Остаток~', num: true, render: (s) => nf(s.stock_est), cls: (s) => (s.stock_est < 0 ? 'text-red-400/70' : '') },
  ],
  pricing: [
    { key: 'name', label: 'Товар', render: nameCell },
    { key: 'price', label: 'Ср.цена', num: true, render: (s) => fmtMoney(s.avg_price) },
    { key: 'cost', label: 'Себест.', num: true, render: (s) => (s.cost_net != null ? fmtMoney(s.cost_net) : '—') },
    { key: 'margin', label: 'Маржа', num: true, render: (s) => (s.margin != null ? fmtMoney(s.margin) : '—') },
    { key: 'mpct', label: 'Маржа %', num: true, render: (s) => (s.margin_pct != null ? `${s.margin_pct}%` : '—'), cls: (s) => (s.margin_pct != null && s.margin_pct < 0 ? 'text-red-400/80 font-medium' : '') },
    { key: 'markup', label: 'Наценка %', num: true, render: (s) => (s.markup_pct != null ? `${s.markup_pct}%` : '—') },
  ],
  nomenclature: [
    { key: 'name', label: 'Товар', render: nameCell },
    { key: 'art', label: 'Артикул', render: (s) => s.article ?? '—' },
    { key: 'cat', label: 'Категория', render: (s) => s.category ?? '—' },
    { key: 'vat', label: 'НДС', render: (s) => s.vat ?? '—' },
    { key: 'mark', label: 'Маркировка', render: (s) => (s.marked ? 'маркир.' : '—') },
    { key: 'weigh', label: 'Весовой', render: (s) => (s.weighed ? 'да' : '—') },
  ],
  sales: [
    { key: 'name', label: 'Товар', render: nameCell },
    { key: 'cat', label: 'Категория', render: (s) => s.category ?? '—' },
    { key: 'qty', label: 'Продано', num: true, render: (s) => nf(s.qty) },
    { key: 'rev', label: 'Выручка', num: true, render: (s) => fmtMoney(s.revenue) },
    { key: 'price', label: 'Ср.цена', num: true, render: (s) => fmtMoney(s.avg_price) },
  ],
  stock: [
    { key: 'name', label: 'Товар', render: nameCell },
    { key: 'cat', label: 'Категория', render: (s) => s.category ?? '—' },
    { key: 'purch', label: 'Закуплено', num: true, render: (s) => nf(s.purch_qty) },
    { key: 'qty', label: 'Продано', num: true, render: (s) => nf(s.qty) },
    { key: 'stock', label: 'Остаток~', num: true, render: (s) => nf(s.stock_est), cls: (s) => (s.stock_est < 0 ? 'text-red-400/70' : '') },
    { key: 'cost', label: 'Себест. ед.', num: true, render: (s) => (s.cost_net != null ? fmtMoney(s.cost_net) : '—') },
  ],
  marked: [
    { key: 'name', label: 'Товар', render: nameCell },
    { key: 'art', label: 'Артикул', render: (s) => s.article ?? '—' },
    { key: 'vat', label: 'НДС', render: (s) => s.vat ?? '—' },
    { key: 'qty', label: 'Продано', num: true, render: (s) => nf(s.qty) },
    { key: 'rev', label: 'Выручка', num: true, render: (s) => fmtMoney(s.revenue) },
  ],
}

const TITLES: Record<SkuMode, string> = {
  assortment: 'Ассортимент — ABC-анализ',
  pricing: 'Цены и маржа',
  nomenclature: 'Номенклатура',
  sales: 'Продажи по товарам',
  stock: 'Остатки (приход − продажа)',
  marked: 'Маркированные товары (Честный Знак)',
}

export function StoreSkuPanel({ companyId, dateFrom, dateTo, mode }: {
  companyId: string; dateFrom: string; dateTo: string; mode: SkuMode
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-skus', companyId, dateFrom, dateTo],
    queryFn: () => getStoreSkus(dateFrom, dateTo),
  })
  const [q, setQ] = useState('')
  const [markedOnly, setMarkedOnly] = useState(false)

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка товаров…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки реестра SKU</div>
  if (!data) return null

  const cols = COLS[mode]
  let skus = data.skus
  if (q) {
    const ql = q.toLowerCase()
    skus = skus.filter((s) => s.name.toLowerCase().includes(ql) || (s.article ?? '').includes(q))
  }
  if (mode === 'nomenclature' && markedOnly) skus = skus.filter((s) => s.marked)
  if (mode === 'marked') skus = skus.filter((s) => s.marked)
  if (mode === 'stock') skus = [...skus].sort((a, b) => b.stock_est - a.stock_est)
  if (mode === 'pricing') skus = [...skus].sort((a, b) => (a.margin_pct ?? 9e9) - (b.margin_pct ?? 9e9))

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">{TITLES[mode]}</h3>
          <p className="text-xs text-muted-foreground">
            {data.period.from} – {data.period.to} · {data.summary.sku_count} SKU · {data.summary.marked_count} маркир.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {mode === 'nomenclature' && (
            <label className="text-xs flex items-center gap-1.5 text-muted-foreground">
              <input type="checkbox" checked={markedOnly} onChange={(e) => setMarkedOnly(e.target.checked)} />
              только маркированные
            </label>
          )}
          <input
            value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара…"
            className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-52"
          />
        </div>
      </div>

      {mode === 'assortment' && (
        <div className="grid grid-cols-3 gap-2.5">
          {(['A', 'B', 'C'] as const).map((c) => (
            <div key={c} className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className={`text-sm font-semibold ${ABC_CLS[c]}`}>Класс {c}</div>
              <div className="text-xs text-muted-foreground mt-1">{data.abc[c].count} SKU · {data.abc[c].share}% выручки</div>
              <div className="text-sm tabular-nums mt-0.5">{fmtMoney(data.abc[c].revenue)}</div>
            </div>
          ))}
        </div>
      )}
      {mode === 'pricing' && (
        <div className="text-xs text-muted-foreground">
          Маржа по {data.summary.sku_costed} из {data.summary.sku_count} SKU (у которых есть закупка в периоде):
          средняя <span className="text-foreground font-medium">{data.summary.margin_pct_costed ?? '—'}%</span> ·
          валовая {fmtMoney(data.summary.margin_costed)}. Остальные — себестоимость неизвестна (нет поступления).
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              {cols.map((c) => (
                <th key={c.key} className={`px-3 py-2 font-medium whitespace-nowrap ${c.num ? 'text-right' : 'text-left'}`}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {skus.slice(0, 300).map((s) => (
              <tr key={s.guid} className="border-t border-border/30 hover:bg-accent/20">
                {cols.map((c) => (
                  <td key={c.key} className={`px-3 py-1.5 ${c.num ? 'text-right tabular-nums' : ''} ${c.cls?.(s) ?? ''}`}>
                    {c.render(s)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {skus.length > 300 && (
          <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">
            Показано 300 из {skus.length}. Уточните поиск.
          </div>
        )}
        {skus.length === 0 && (
          <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет данных за период (поставьте апрель — локальная копия ЦБ до 29.04).</div>
        )}
      </div>
    </div>
  )
}
