/**
 * Модалка детализации товара — общая для «Цены и маржа» и «Ассортимент».
 * Метрики + история цен (переоценки) + динамика продаж + закупки + остаток.
 * Данные: /api/store/sku/{guid} (GoodsDashboardService.sku_detail).
 */
import { useQuery } from '@tanstack/react-query'
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip, CartesianGrid } from 'recharts'
import { getStoreSkuDetail, type SkuDetailData } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const pctStr = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${nf(v, d)}%`)
const marginCls = (v: number | null | undefined) => (v == null ? '' : v < 0 ? 'text-red-400/80' : v < 10 ? 'text-amber-300/90' : 'text-emerald-300/80')

export function SkuDetailModal({ guid, dateFrom, dateTo, onClose }: { guid: string; dateFrom: string; dateTo: string; onClose: () => void }) {
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
          {isLoading || !d ? <div className="text-sm text-muted-foreground py-8 text-center">Загрузка детализации…</div> : <SkuDetailBody d={d} />}
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
