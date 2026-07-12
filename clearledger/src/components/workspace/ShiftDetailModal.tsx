/**
 * Смена-детализация (модалка): операции одной смены — строки продаж по SKU,
 * касса (оплаты), возвраты + документы приходов/инвентаризаций/списаний того же
 * дня. Открывается кликом по строке в «Смены».
 * Данные: /api/store/shift?key=… (GoodsDashboardService.shift_detail).
 */
import { useQuery } from '@tanstack/react-query'
import { ShoppingCart, Wallet, PackagePlus, ClipboardList, Trash2 } from 'lucide-react'
import { getStoreShiftDetail } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

export function ShiftDetailModal({ shiftKey, companyId, onClose }: { shiftKey: string; companyId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['store-shift-detail', companyId, shiftKey],
    queryFn: () => getStoreShiftDetail(shiftKey),
  })

  const sh = data?.shift

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg shadow-xl max-w-4xl w-full max-h-[86vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* шапка */}
        <div className="flex items-start justify-between px-4 py-3 border-b border-border/50">
          <div>
            <div className="text-sm font-semibold">
              Смена {sh?.number ?? ''} {sh && <span className="text-muted-foreground font-normal">· {sh.date} · АЗС {sh.station}</span>}
            </div>
            {sh && (
              <div className="text-xs text-muted-foreground mt-0.5">
                Выручка <span className="text-foreground font-medium">{fmtMoney(sh.revenue)}</span>
                {' '}(сопутка {fmtMoney(sh.soputka)} · общепит {fmtMoney(sh.obshepit)}) · {nf(sh.positions)} позиций
                {sh.returns > 0 && <> · возвраты <span className="text-amber-300/90">{fmtMoney(sh.returns)}</span></>}
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-lg leading-none px-2">×</button>
        </div>

        {isLoading || !data ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка смены…</div>
        ) : !data.found ? (
          <div className="p-6 text-sm text-muted-foreground">Смена не найдена.</div>
        ) : (
          <div className="overflow-auto p-4 space-y-4">
            {/* Касса + сводка документов */}
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-border/50 bg-card/40 p-3">
                <div className="flex items-center gap-1.5 text-sm font-medium mb-2"><Wallet className="h-4 w-4 text-emerald-300/80" /> Касса</div>
                {data.payments && data.payments.length > 0 ? (
                  <div className="space-y-1">
                    {data.payments.map((p, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">{p.form}</span>
                        <span className="tabular-nums">{fmtMoney(p.amount)}</span>
                      </div>
                    ))}
                  </div>
                ) : <div className="text-xs text-muted-foreground">Нет разбивки оплат</div>}
              </div>
              <div className="rounded-lg border border-border/50 bg-card/40 p-3">
                <div className="text-sm font-medium mb-2">Операции дня</div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div><div className="text-lg font-semibold tabular-nums">{nf(data.receipts?.length ?? 0)}</div><div className="text-[10px] text-muted-foreground">приходов</div></div>
                  <div><div className="text-lg font-semibold tabular-nums text-blue-300/80">{nf(data.inventory?.length ?? 0)}</div><div className="text-[10px] text-muted-foreground">инвент.</div></div>
                  <div><div className="text-lg font-semibold tabular-nums text-red-400/80">{nf(data.writeoffs?.length ?? 0)}</div><div className="text-[10px] text-muted-foreground">списаний</div></div>
                </div>
              </div>
            </div>

            {/* Приходы дня */}
            {data.receipts && data.receipts.length > 0 && (
              <Section icon={<PackagePlus className="h-4 w-4 text-primary" />} title={`Приходы (${data.receipts.length})`}>
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground"><tr>
                    <th className="px-2 py-1 text-left font-medium">Документ</th>
                    <th className="px-2 py-1 text-left font-medium">Поставщик</th>
                    <th className="px-2 py-1 text-right font-medium">Позиций</th>
                    <th className="px-2 py-1 text-right font-medium">Сумма (нетто)</th>
                  </tr></thead>
                  <tbody>
                    {data.receipts.map((r, i) => (
                      <tr key={i} className="border-t border-border/30">
                        <td className="px-2 py-1 tabular-nums text-muted-foreground">{r.number ?? '—'}</td>
                        <td className="px-2 py-1">{r.supplier}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{nf(r.positions)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{fmtMoney(r.amount_net)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {/* Инвентаризации / Списания */}
            {((data.inventory && data.inventory.length > 0) || (data.writeoffs && data.writeoffs.length > 0)) && (
              <div className="grid gap-3 md:grid-cols-2">
                {data.inventory && data.inventory.length > 0 && (
                  <Section icon={<ClipboardList className="h-4 w-4 text-blue-300/80" />} title={`Инвентаризации (${data.inventory.length})`}>
                    <div className="space-y-1">
                      {data.inventory.map((r, i) => (
                        <div key={i} className="flex items-center justify-between text-xs">
                          <span className="tabular-nums text-muted-foreground">{r.number ?? '—'} · {r.dev_positions} откл.</span>
                          <span className={`tabular-nums ${r.net < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>{fmtMoney(r.net)}</span>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}
                {data.writeoffs && data.writeoffs.length > 0 && (
                  <Section icon={<Trash2 className="h-4 w-4 text-red-400/80" />} title={`Списания (${data.writeoffs.length})`}>
                    <div className="space-y-1">
                      {data.writeoffs.map((r, i) => (
                        <div key={i} className="flex items-center justify-between text-xs gap-2">
                          <span className="text-muted-foreground truncate">{r.number ?? '—'} · {r.reason ?? '—'}</span>
                          <span className="tabular-nums text-red-400/80 shrink-0">{fmtMoney(r.amount)}</span>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}
              </div>
            )}

            {/* Строки продаж */}
            <Section icon={<ShoppingCart className="h-4 w-4 text-primary" />} title={`Продажи по товарам (${data.sales?.length ?? 0})`}>
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground sticky top-0 bg-card"><tr>
                    <th className="px-2 py-1 text-left font-medium">Товар</th>
                    <th className="px-2 py-1 text-left font-medium">Категория</th>
                    <th className="px-2 py-1 text-right font-medium">Кол-во</th>
                    <th className="px-2 py-1 text-right font-medium">Выручка</th>
                  </tr></thead>
                  <tbody>
                    {(data.sales ?? []).map((l) => (
                      <tr key={l.guid} className="border-t border-border/30">
                        <td className="px-2 py-1">{l.marked && <span title="маркированный">🔖 </span>}{l.name}</td>
                        <td className="px-2 py-1 text-muted-foreground">{l.category ?? '—'}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{nf(l.qty, 3)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{fmtMoney(l.revenue)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="flex items-center gap-1.5 text-sm font-medium mb-2">{icon} {title}</div>
      {children}
    </div>
  )
}
