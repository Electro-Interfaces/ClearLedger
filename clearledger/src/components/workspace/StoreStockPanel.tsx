/**
 * «Остатки» раздела «Магазин» — ДОСТОВЕРНЫЙ остаток из регистров ЦБ ЭЛСИ.АЗК
 * (снимок ТоварыНаАЗК + себестоимость из ПартииТоваровНаСкладах), НЕ оценка
 * «закупка − продажи». Источник: /api/store/stock (GoodsDashboardService.stock_onhand).
 *
 * Остаток — снимок на момент выгрузки (не за период): фильтр периода не применяется.
 * Отрицательные остатки — норма для розничных АЗС (учёт по средней) → флаг.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreStock, type StoreStockItem } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { ChzBadge } from '@/components/common/ChzBadge'
import { SnapshotBadge } from '@/components/common/SnapshotBadge'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

type MarkedFilter = 'all' | 'marked' | 'plain'

export function StoreStockPanel({ companyId }: { companyId: string; dateFrom?: string; dateTo?: string }) {
  const [warehouse, setWarehouse] = useState<string | undefined>(undefined)
  const [q, setQ] = useState('')
  const [marked, setMarked] = useState<MarkedFilter>('all')
  const [onlyNegative, setOnlyNegative] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-stock', companyId, warehouse ?? ''],
    queryFn: () => getStoreStock({ warehouse }),
  })

  const items = useMemo(() => {
    if (!data) return [] as StoreStockItem[]
    const ql = q.toLowerCase().trim()
    return data.items.filter((i) => {
      if (marked === 'marked' && !i.marked) return false
      if (marked === 'plain' && i.marked) return false
      if (onlyNegative && !i.negative) return false
      if (ql && !(i.name.toLowerCase().includes(ql) || (i.barcode ?? '').includes(q) || (i.article ?? '').includes(q))) return false
      return true
    })
  }, [data, q, marked, onlyNegative])

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка остатков…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки остатков</div>
  if (!data) return null

  // KPI по отфильтрованному набору (что на экране)
  const kpiRetailPos = items.reduce((s, i) => s + (i.qty > 0 ? (i.retail_value ?? 0) : 0), 0)
  const kpiPos = items.filter((i) => i.qty > 0).length
  const kpiNeg = items.filter((i) => i.negative).length
  const costed = items.filter((i) => i.qty > 0 && i.cost_amount != null)
  const kpiCost = costed.reduce((s, i) => s + (i.cost_amount ?? 0), 0)
  const kpiRetailCosted = costed.reduce((s, i) => s + (i.retail_value ?? 0), 0)
  const kpiMarginPct = kpiRetailCosted ? ((kpiRetailCosted - kpiCost) / kpiRetailCosted) * 100 : null
  const curWh = data.warehouses.find((w) => w.code === data.warehouse)

  const KPIS: { label: string; value: string; hint?: string; danger?: boolean }[] = [
    { label: 'Позиций (SKU)', value: nf(items.length) },
    { label: 'На полке (>0)', value: nf(kpiPos), hint: 'положительный остаток' },
    { label: 'В минусе', value: nf(kpiNeg), danger: kpiNeg > 0, hint: 'продажи опередили приёмку' },
    { label: 'Розн. стоимость', value: fmtMoney(kpiRetailPos), hint: 'товар на полке × цена' },
    { label: 'Себест. остатка', value: fmtMoney(kpiCost), hint: `${nf(costed.length)} SKU с себест.` },
    { label: 'Потенц. маржа', value: kpiMarginPct == null ? '—' : `${nf(kpiMarginPct, 1)}%`, hint: 'на полке (закуп.)' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">Остатки — достоверный (регистры ЦБ)</h3>
            <SnapshotBadge at={data.snapshot_at} />
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Снимок остатка из 1С (ТоварыНаАЗК + партии). Не за период — текущий остаток базы.
            {curWh && <> Склад: <span className="text-foreground">{curWh.name}</span>.</>}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={warehouse ?? data.warehouse ?? ''}
            onChange={(e) => setWarehouse(e.target.value || undefined)}
            className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background"
          >
            {data.warehouses.map((w) => (
              <option key={w.code} value={w.code}>{w.name ?? w.code} ({w.sku})</option>
            ))}
          </select>
          <select
            value={marked} onChange={(e) => setMarked(e.target.value as MarkedFilter)}
            className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background"
          >
            <option value="all">Все товары</option>
            <option value="marked">Маркированные</option>
            <option value="plain">Обычные</option>
          </select>
          <label className="text-xs flex items-center gap-1.5 text-muted-foreground">
            <input type="checkbox" checked={onlyNegative} onChange={(e) => setOnlyNegative(e.target.checked)} />
            только «в минусе»
          </label>
          <input
            value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара / ШК…"
            className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-52"
          />
        </div>
      </div>

      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.danger ? 'text-red-400/90' : ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{k.hint}</div>}
          </div>
        ))}
      </div>

      <p className="text-[11px] text-muted-foreground/70 -mt-1">
        ⚠ Весовые считаются в базовых единицах (мл/г/л). Себестоимость — удельная из партий
        (Стоимость/Количество, те же единицы, что и остаток). Маржа ориентировочна: у части SKU
        цена/партия устаревшие → возможны выбросы (напр. &gt;80% или отрицательная). Отрицательные
        остатки — норма для розницы по средней (флаг красным).
      </p>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left">Товар</th>
              <th className="px-3 py-2 font-medium text-center">ЧЗ</th>
              <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Штрихкод</th>
              <th className="px-3 py-2 font-medium text-right">Остаток</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Розн. цена</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Себест/ед</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Маржа %</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Розн. стоимость</th>
              <th className="px-3 py-2 font-medium text-left">НДС</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 400).map((i) => (
              <tr key={i.guid} className="border-t border-border/30 hover:bg-accent/20">
                <td className="px-3 py-1.5">
                  {i.name}
                  {i.weighed && <span className="ml-1 text-[10px] text-muted-foreground/60" title="весовой — остаток в базовых единицах">вес.</span>}
                </td>
                <td className="px-3 py-1.5 text-center">{i.marked && <ChzBadge />}</td>
                <td className="px-3 py-1.5 text-muted-foreground tabular-nums">{i.barcode ?? '—'}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${i.negative ? 'text-red-400/80 font-medium' : ''}`}>{nf(i.qty, 3)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{i.retail_price != null ? fmtMoney(i.retail_price) : '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{i.cost_unit != null ? nf(i.cost_unit, 2) : '—'}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${i.margin_pct == null ? '' : i.margin_pct < 0 ? 'text-red-400/80' : 'text-emerald-300/70'}`}>{i.margin_pct != null ? `${nf(i.margin_pct, 1)}%` : '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{i.retail_value != null ? fmtMoney(i.retail_value) : '—'}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{i.vat ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length > 400 && (
          <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">
            Показано 400 из {nf(items.length)}. Уточните поиск.
          </div>
        )}
        {items.length === 0 && (
          <div className="px-3 py-6 text-sm text-muted-foreground text-center">
            Нет позиций. Если пусто целиком — наполните остаток: <code>py -3.13 scripts/pull_cb_stock_dev.py</code>
          </div>
        )}
      </div>
    </div>
  )
}
