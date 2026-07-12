/**
 * Карточка номенклатуры (товаровед) — полный паспорт SKU: идентификация,
 * классификация, штрихкоды, цена/остаток по складам, продажи, поставщики,
 * движение (инвент./списания/перемещения), рецептура ТТК, МРЦ. Открывается
 * кликом по строке в «Номенклатуре». Данные: /api/store/sku-card/{guid}.
 */
import { useQuery } from '@tanstack/react-query'
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip } from 'recharts'
import {
  Barcode, Package, Wallet, ShoppingCart, PackagePlus, ArrowLeftRight,
  ClipboardList, Trash2, ChefHat, ShieldAlert, TrendingUp,
} from 'lucide-react'
import { getStoreSkuCard, type SkuMovementRow } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number | null | undefined) => (n == null ? '—' : fmtMoney(n))
const pct = (n: number | null | undefined) => (n == null ? '—' : `${nf(n, 1)}%`)

const MOVE_META: Record<SkuMovementRow['kind'], { label: string; icon: typeof ArrowLeftRight; cls: string }> = {
  inventory: { label: 'Инвентаризация', icon: ClipboardList, cls: 'text-blue-300/80' },
  writeoff: { label: 'Списание', icon: Trash2, cls: 'text-red-400/80' },
  transfer: { label: 'Перемещение', icon: ArrowLeftRight, cls: 'text-muted-foreground' },
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      <div className="text-sm mt-0.5 break-words">{children}</div>
    </div>
  )
}

function Section({ icon: Icon, title, right, children }: {
  icon: typeof Package; title: string; right?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3.5">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5 text-sm font-medium"><Icon className="h-4 w-4 text-primary" /> {title}</div>
        {right}
      </div>
      {children}
    </div>
  )
}

export function NomenclatureCardModal({ guid, companyId, dateFrom, dateTo, onClose }: {
  guid: string; companyId: string; dateFrom: string; dateTo: string; onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['store-sku-card', companyId, guid, dateFrom, dateTo],
    queryFn: () => getStoreSkuCard(guid, dateFrom, dateTo),
  })

  const m = data?.metrics

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* шапка */}
        <div className="flex items-start justify-between px-5 py-3.5 border-b border-border/50">
          <div className="min-w-0">
            <div className="text-base font-semibold flex items-center gap-2 flex-wrap">
              {data?.marked && <span title="маркированный (Честный знак)">🔖</span>}
              {data?.name ?? 'Карточка товара'}
            </div>
            {data && (
              <div className="flex items-center gap-1.5 mt-1 flex-wrap text-[11px]">
                {data.kind && <span className="px-1.5 py-0.5 rounded border border-border/50 text-muted-foreground">{data.kind}</span>}
                <span className="px-1.5 py-0.5 rounded border border-border/50 text-muted-foreground">{data.unit ?? (data.weighed ? 'весовой' : 'штучный')}</span>
                <span className="px-1.5 py-0.5 rounded border border-border/50 text-muted-foreground">НДС {data.vat ?? '—'}</span>
                {data.marked && <span className="px-1.5 py-0.5 rounded border border-emerald-400/40 text-emerald-300/80">ЧЗ</span>}
                {data.category && <span className="px-1.5 py-0.5 rounded border border-border/50 text-muted-foreground">{data.category}</span>}
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-lg leading-none px-2 shrink-0">×</button>
        </div>

        {isLoading || !data ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка карточки…</div>
        ) : (
          <div className="overflow-auto p-4 space-y-3.5">
            {/* Паспорт + Штрихкоды */}
            <div className="grid gap-3.5 md:grid-cols-2">
              <Section icon={Package} title="Паспорт">
                <div className="grid grid-cols-2 gap-3">
                  {data.full_name && data.full_name !== data.name && (
                    <div className="col-span-2"><Field label="Полное наименование">{data.full_name}</Field></div>
                  )}
                  <Field label="Артикул">{data.article ?? '—'}</Field>
                  <Field label="Вид номенклатуры">{data.kind ?? '—'}</Field>
                  <Field label="Группа">{data.group ?? '—'}</Field>
                  <Field label="Ставка НДС">{data.vat ?? '—'}</Field>
                  <Field label="Маркировка ЧЗ">{data.marked ? 'да' : 'нет'}</Field>
                  <Field label="Базовая единица">{data.unit ?? '—'}{data.weighed ? ' · весовой' : ''}</Field>
                  {data.main_supplier && <Field label="Основной поставщик">{data.main_supplier}</Field>}
                  <div className="col-span-2">
                    <Field label="GUID (1С)"><span className="font-mono text-[11px] text-muted-foreground">{data.guid}</span></Field>
                  </div>
                </div>
              </Section>

              <Section icon={Barcode} title="Штрихкоды" right={<span className="text-[11px] text-muted-foreground">{data.barcodes.length}</span>}>
                {data.barcodes.length === 0 ? (
                  <div className="text-xs text-muted-foreground">Штрихкоды не заведены</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5 max-h-40 overflow-auto">
                    {data.barcodes.map((b) => (
                      <span key={b.barcode} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] tabular-nums ${b.main ? 'border-primary/50 text-primary' : 'border-border/50 text-muted-foreground'}`}
                        title={`${b.type ?? 'тип не указан'}${b.main ? ' · основной' : ''}`}>
                        {b.barcode}
                        {b.type && <span className="text-[9px] opacity-60">{b.type}</span>}
                      </span>
                    ))}
                  </div>
                )}
              </Section>
            </div>

            {/* Цена и остаток */}
            <Section icon={Wallet} title="Цена и остаток по складам"
              right={data.mrc && (
                <span className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border ${data.mrc.over ? 'border-red-400/50 text-red-400/90' : 'border-emerald-400/40 text-emerald-300/80'}`}>
                  <ShieldAlert className="h-3 w-3" /> МРЦ {money(data.mrc.mrc)}{data.mrc.over ? ' · нарушение' : ''}
                </span>
              )}>
              {data.stock.length === 0 ? (
                <div className="text-xs text-muted-foreground">Нет на остатке</div>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground"><tr>
                    <th className="px-2 py-1 text-left font-medium">Склад</th>
                    <th className="px-2 py-1 text-right font-medium">Остаток</th>
                    <th className="px-2 py-1 text-right font-medium">Розн. цена</th>
                    <th className="px-2 py-1 text-right font-medium">Себест. ед</th>
                    <th className="px-2 py-1 text-right font-medium">Стоимость (розн.)</th>
                  </tr></thead>
                  <tbody>
                    {data.stock.map((s, i) => (
                      <tr key={i} className="border-t border-border/30">
                        <td className="px-2 py-1">{s.warehouse}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{nf(s.qty, 3)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{money(s.retail_price)}</td>
                        <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">{s.cost_unit != null ? money(s.cost_unit) : '—'}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{s.retail_price != null ? money(s.qty * s.retail_price) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>

            {/* Продажи за период */}
            <Section icon={TrendingUp} title={`Продажи · ${dateFrom} – ${dateTo}`}>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-3">
                {[
                  { l: 'Выручка', v: money(m!.revenue) },
                  { l: 'Продано', v: nf(m!.qty, 3) },
                  { l: 'Ср. цена', v: money(m!.avg_price) },
                  { l: 'Себест. ед', v: money(m!.avg_cost) },
                  { l: 'Маржа', v: money(m!.margin), cls: (m!.margin ?? 0) < 0 ? 'text-red-400/80' : 'text-emerald-300/80' },
                  { l: 'Маржа %', v: pct(m!.margin_pct) },
                ].map((k) => (
                  <div key={k.l} className="rounded-md border border-border/40 bg-background/40 p-2">
                    <div className="text-[10px] text-muted-foreground">{k.l}</div>
                    <div className={`text-sm font-semibold tabular-nums ${k.cls ?? ''}`}>{k.v}</div>
                  </div>
                ))}
              </div>
              {data.daily.length > 1 && (
                <div className="h-24">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.daily}>
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d: string) => d.slice(8)} />
                      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                      <Tooltip formatter={(v: any) => fmtMoney(Number(v))} labelFormatter={(l: any) => `${l}`} contentStyle={{ fontSize: 11 }} />
                      <Bar dataKey="revenue" fill="currentColor" className="text-primary/60" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Section>

            {/* Рецептура ТТК (для блюд общепита) */}
            {data.recipe.length > 0 && (
              <Section icon={ChefHat} title="Рецептура (ТТК)" right={<span className="text-[11px] text-muted-foreground">{data.recipe.length} ингр.</span>}>
                <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1">
                  {data.recipe.map((r, i) => (
                    <div key={i} className="flex items-center justify-between text-xs">
                      <span>{r.name}</span><span className="tabular-nums text-muted-foreground">{nf(r.qty, 3)}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Поставщики / Движение */}
            <div className="grid gap-3.5 md:grid-cols-2">
              <Section icon={PackagePlus} title="Поставки" right={<span className="text-[11px] text-muted-foreground">{data.purchases.length}</span>}>
                {data.purchases.length === 0 ? <div className="text-xs text-muted-foreground">Нет закупок за период</div> : (
                  <div className="max-h-44 overflow-auto"><table className="w-full text-xs">
                    <tbody>
                      {data.purchases.slice().reverse().map((p, i) => (
                        <tr key={i} className="border-b border-border/20 last:border-0">
                          <td className="py-1 pr-2 whitespace-nowrap text-muted-foreground">{p.date}</td>
                          <td className="py-1 pr-2 truncate max-w-[140px]" title={p.supplier}>{p.supplier}</td>
                          <td className="py-1 text-right tabular-nums whitespace-nowrap">{nf(p.qty, 2)} × {money(p.price_net)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table></div>
                )}
              </Section>

              <Section icon={ArrowLeftRight} title="Движение" right={<span className="text-[11px] text-muted-foreground">{data.movement.length}</span>}>
                {data.movement.length === 0 ? <div className="text-xs text-muted-foreground">Нет движения</div> : (
                  <div className="max-h-44 overflow-auto"><table className="w-full text-xs">
                    <tbody>
                      {data.movement.map((mv, i) => {
                        const meta = MOVE_META[mv.kind]
                        return (
                          <tr key={i} className="border-b border-border/20 last:border-0">
                            <td className="py-1 pr-2 whitespace-nowrap text-muted-foreground">{mv.date}</td>
                            <td className={`py-1 pr-2 whitespace-nowrap ${meta.cls}`}><meta.icon className="h-3 w-3 inline mr-0.5" />{meta.label}</td>
                            <td className="py-1 text-right tabular-nums whitespace-nowrap">{mv.qty != null ? nf(mv.qty, 2) : '—'}{mv.amount != null ? ` · ${money(mv.amount)}` : ''}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table></div>
                )}
              </Section>
            </div>

            {/* История цен (переоценки) */}
            {data.price_history.length > 0 && (
              <Section icon={ShoppingCart} title="История цен (переоценки)" right={<span className="text-[11px] text-muted-foreground">{data.price_history.length}</span>}>
                <div className="max-h-40 overflow-auto"><table className="w-full text-xs">
                  <tbody>
                    {data.price_history.slice().reverse().map((h, i) => (
                      <tr key={i} className="border-b border-border/20 last:border-0">
                        <td className="py-1 pr-2 whitespace-nowrap text-muted-foreground">{h.date ?? '—'}</td>
                        <td className="py-1 text-right tabular-nums">{money(h.old)} → {money(h.new)}</td>
                        <td className={`py-1 pl-2 text-right tabular-nums ${(h.delta ?? 0) < 0 ? 'text-emerald-300/80' : 'text-amber-300/80'}`}>{h.pct != null ? `${h.pct > 0 ? '+' : ''}${nf(h.pct, 1)}%` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              </Section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
