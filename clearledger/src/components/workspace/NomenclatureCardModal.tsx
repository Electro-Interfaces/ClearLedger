/**
 * Карточка номенклатуры (товаровед) — полный паспорт SKU: идентификация,
 * классификация, штрихкоды, цена/остаток по складам, продажи, поставщики,
 * движение (инвент./списания/перемещения), рецептура ТТК, МРЦ. Открывается
 * кликом по строке в «Номенклатуре». Данные: /api/store/sku-card/{guid}.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip } from 'recharts'
import {
  Barcode, Package, Wallet, ShoppingCart, PackagePlus, ArrowLeftRight,
  ClipboardList, Trash2, ChefHat, ShieldAlert, TrendingUp,
} from 'lucide-react'
import { getStoreSkuCard, type SkuMovementRow } from '@/services/storeService'
import { ItemPassportSection } from './ItemPassportSection'
import { fmtMoney } from '@/services/analyticsService'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'
import { ModalCard } from '@/components/ui/modal-card'
import { NsiEditSection } from './NsiEditSection'

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

export function NomenclatureCardModal({ guid, companyId, dateFrom, dateTo, stations, onClose }: {
  guid: string; companyId: string; dateFrom: string; dateTo: string; stations?: string[]; onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['store-sku-card', companyId, guid, dateFrom, dateTo, stations?.join(',') ?? ''],
    queryFn: () => getStoreSkuCard(guid, dateFrom, dateTo, stations),
  })

  const m = data?.metrics

  // Вкладки — по вопросам, которые задают карточке, а не по происхождению
  // полей: «что это за товар», «сколько стоит и где лежит», «что с ним
  // происходило». Свиток из семи блоков заставлял прокручивать мимо трёх
  // чужих ответов ради одного нужного.
  //
  // Вкладка без содержимого не показывается: у обычной воды нет рецептуры, и
  // пустой раздел в карточке читается как поломка данных.
  const ВКЛАДКИ = useMemo(() => {
    if (!data) return []
    const список: { key: string; label: string; count?: number }[] = [
      { key: 'card', label: 'Карточка' },
      { key: 'network', label: 'Сеть и станции' },
      { key: 'price', label: 'Цена и остаток', count: data.stock.length || undefined },
      { key: 'moves', label: 'Движение', count: (data.purchases.length + data.movement.length) || undefined },
    ]
    if (data.recipe.length) список.push({ key: 'recipe', label: 'Рецептура', count: data.recipe.length })
    if (data.marked) список.push({ key: 'mark', label: 'Маркировка' })
    return список
  }, [data])
  const [вкладка, выбрать] = useState('card')
  const активна = ВКЛАДКИ.some((t) => t.key === вкладка) ? вкладка : 'card'

  return (
    <ModalCard
      className="max-w-4xl max-h-[90vh]"
      // Полоса цифр и вкладки закреплены — прокручивается только содержимое вкладки
      bodyClassName="flex flex-col overflow-hidden"
      onClose={onClose}
      title={data?.name ?? 'Карточка товара'}
      subtitle={data ? (
        <span className="flex items-center gap-1.5 flex-wrap text-[11px]">
          {data.kind && <span className="px-1.5 py-0.5 rounded border border-border/50">{data.kind}</span>}
          <span className="px-1.5 py-0.5 rounded border border-border/50">{data.unit ?? (data.weighed ? 'весовой' : 'штучный')}</span>
          <span className="px-1.5 py-0.5 rounded border border-border/50">НДС {data.vat ?? '—'}</span>
          {data.marked && <span className="px-1.5 py-0.5 rounded border border-zinc-600 text-zinc-400" title="Маркированный товар (Честный знак)">ЧЗ</span>}
          {data.category && <span className="px-1.5 py-0.5 rounded border border-border/50">{data.category}</span>}
        </span>
      ) : undefined}
    >
        {/* Главные цифры видны на любой вкладке: сколько лежит, почём, сколько
            заработали. Ради них карточку и открывают, и прятать их за
            переключением разделов — значит менять один свиток на другой. */}
        {data && m && (
          <div className="flex flex-wrap gap-x-6 gap-y-1.5 border-b border-border/50 px-5 py-2 text-xs">
            <span className="text-muted-foreground">На остатке{' '}
              <span className="font-semibold tabular-nums text-foreground">
                {nf(data.stock.reduce((a, x) => a + x.qty, 0), 3)}
              </span>
              {data.stock.length > 1 && (
                <span className="text-muted-foreground/70"> в {data.stock.length} местах</span>
              )}
            </span>
            <span className="text-muted-foreground">Цена{' '}
              <span className="font-semibold tabular-nums text-foreground">
                {money(data.stock.find((x) => x.retail_price != null)?.retail_price ?? null)}
              </span>
            </span>
            <span className="text-muted-foreground">Продано{' '}
              <span className="font-semibold tabular-nums text-foreground">{nf(m.qty, 3)}</span>
              <span className="text-muted-foreground/70"> на {money(m.revenue)}</span>
            </span>
            <span className="text-muted-foreground">Маржа{' '}
              <span className={`font-semibold tabular-nums ${(m.margin_pct ?? 0) < 0 ? 'text-red-400/90' : 'text-foreground'}`}>
                {pct(m.margin_pct)}
              </span>
            </span>
            {data.mrc?.over && (
              <span className="text-red-400/90">цена выше МРЦ {money(data.mrc.mrc)} — нарушение</span>
            )}
          </div>
        )}

        {isLoading || !data ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка карточки…</div>
        ) : (
          <>
          <div className="flex flex-wrap gap-1 border-b border-border/50 px-4 pt-2">
            {ВКЛАДКИ.map((t) => (
              <button key={t.key} type="button" onClick={() => выбрать(t.key)}
                aria-current={активна === t.key ? 'page' : undefined}
                className={`relative -mb-px rounded-t-md px-3 py-1.5 text-xs transition-colors ${
                  активна === t.key
                    ? 'border-x border-t border-border/60 bg-card font-semibold text-primary'
                    : 'font-medium text-muted-foreground hover:text-foreground'}`}>
                {t.label}
                {t.count != null && (
                  <span className="ml-1.5 rounded-full bg-muted/60 px-1.5 text-[10px] tabular-nums text-muted-foreground">
                    {t.count}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-4 space-y-3.5">
            {активна === 'card' && <NsiEditSection guid={guid} companyId={companyId} />}

            {/* Сеть и станции: ярусы кодов, условия каждой АЗС, чья рецептура */}
            {активна === 'network' && <ItemPassportSection guid={guid} />}

            {/* Паспорт + Штрихкоды */}
            {активна === 'card' && (
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
            )}

            {/* Цена и остаток */}
            {активна === 'price' && (
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
            )}

            {/* Продажи за период */}
            {(активна === 'price' || активна === 'moves') && (
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
                      <Tooltip {...rechartsTooltipTheme} formatter={(v: any) => fmtMoney(Number(v))} labelFormatter={(l: any) => `${l}`} contentStyle={{ fontSize: 11 }} />
                      <Bar dataKey="revenue" fill="currentColor" className="text-primary/60" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Section>
            )}

            {/* Рецептура ТТК (для блюд общепита) */}
            {активна === 'recipe' && data.recipe.length > 0 && (
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
            {активна === 'moves' && (
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
            )}

            {/* История цен (переоценки) */}
            {(активна === 'price' || активна === 'moves') && data.price_history.length > 0 && (
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

            {активна === 'mark' && (
              <Section icon={ShieldAlert} title="Маркировка «Честный знак»">
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Требует DataMatrix">{data.marked ? 'да' : 'нет'}</Field>
                  <Field label="GTIN">{data.barcodes.find((b) => b.barcode.length === 14)?.barcode ?? '—'}</Field>
                  <Field label="МРЦ">{data.mrc ? money(data.mrc.mrc) : '—'}</Field>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                  Коды этого товара, которыми мы владеем, живут в разделе «Маркировка → Коды на
                  остатке»: карточка отвечает за правила, а поэкземплярный учёт — за факты.
                  {data.mrc?.over && (
                    <span className="text-red-400/90"> Розничная цена выше МРЦ — это нарушение
                      статьи 13 ФЗ-15, продавать так нельзя.</span>
                  )}
                </p>
              </Section>
            )}
          </div>
          </>
        )}
    </ModalCard>
  )
}
