/**
 * Смена-детализация (модалка): смена как полный составной документ. Строки
 * продаж по SKU, касса (оплаты), возвраты + ВСЕ документы того же дня —
 * приходы, инвентаризации, списания, перемещения, переоценки — с раскрытием
 * строк по клику. Данные: /api/store/shift?key=… (shift_detail).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShoppingCart, Wallet, PackagePlus, ClipboardList, Trash2, ArrowLeftRight, Tag, ChevronRight,
} from 'lucide-react'
import { getStoreShiftDetail, type ShiftDocLine } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number | null | undefined) => (n == null ? '—' : fmtMoney(n))

/** Строки документа — рендер по наличию полей (приход/инвент/списание/переоценка). */
function DocLines({ lines }: { lines: ShiftDocLine[] }) {
  if (!lines?.length) return <div className="px-3 py-1.5 text-[11px] text-muted-foreground">Нет строк</div>
  const isReval = lines.some((l) => l.old != null || l.new != null)
  const isInv = lines.some((l) => l.fact != null || l.uchet != null)
  return (
    <table className="w-full text-[11px]">
      <tbody>
        {lines.map((l, i) => (
          <tr key={i} className="border-t border-border/20">
            <td className="px-3 py-1">{l.name ?? '—'}</td>
            {isReval ? (
              <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                {money(l.old)} → {money(l.new)}
                {l.pct != null && <span className={`ml-1 ${(l.pct ?? 0) < 0 ? 'text-emerald-300/80' : 'text-amber-300/80'}`}>{l.pct > 0 ? '+' : ''}{nf(l.pct, 1)}%</span>}
              </td>
            ) : isInv ? (
              <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                факт {nf(l.fact ?? 0, 2)} / учёт {nf(l.uchet ?? 0, 2)}
                <span className={`ml-1 ${(l.dev ?? 0) < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>({(l.dev ?? 0) >= 0 ? '+' : ''}{nf(l.dev ?? 0, 2)})</span>
                {l.amount != null && <span className="ml-1 text-muted-foreground">{money(l.amount)}</span>}
              </td>
            ) : (
              <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                {l.qty != null ? nf(l.qty, 3) : '—'}{l.price != null ? ` × ${money(l.price)}` : ''}{l.amount != null ? ` = ${money(l.amount)}` : ''}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Группа документов одного типа: заголовок + раскрываемые документы. */
function DocGroup<T extends { number: string | null; lines: ShiftDocLine[] }>({
  icon: Icon, title, cls, docs, meta,
}: {
  icon: typeof PackagePlus; title: string; cls?: string
  docs: T[]; meta: (d: T) => string
}) {
  const [open, setOpen] = useState<number | null>(null)
  if (!docs.length) return null
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 overflow-hidden">
      <div className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium ${cls ?? ''}`}>
        <Icon className="h-4 w-4" /> {title} <span className="text-[11px] text-muted-foreground font-normal">· {docs.length}</span>
      </div>
      <div>
        {docs.map((d, i) => (
          <div key={i} className="border-t border-border/30">
            <button onClick={() => setOpen(open === i ? null : i)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/20 text-left">
              <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${open === i ? 'rotate-90' : ''}`} />
              <span className="tabular-nums text-muted-foreground shrink-0">{d.number ?? '—'}</span>
              <span className="flex-1 truncate">{meta(d)}</span>
            </button>
            {open === i && <div className="bg-background/40"><DocLines lines={d.lines} /></div>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function ShiftDetailModal({ shiftKey, companyId, onClose }: { shiftKey: string; companyId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['store-shift-detail', companyId, shiftKey],
    queryFn: () => getStoreShiftDetail(shiftKey),
  })
  const sh = data?.shift

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg shadow-xl max-w-4xl w-full max-h-[88vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
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
          <div className="overflow-auto p-4 space-y-3">
            {/* Касса */}
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="flex items-center gap-1.5 text-sm font-medium mb-2"><Wallet className="h-4 w-4 text-emerald-300/80" /> Касса</div>
              {data.payments && data.payments.length > 0 ? (
                <div className="flex flex-wrap gap-x-6 gap-y-1">
                  {data.payments.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="text-muted-foreground">{p.form}</span><span className="tabular-nums font-medium">{fmtMoney(p.amount)}</span>
                    </div>
                  ))}
                </div>
              ) : <div className="text-xs text-muted-foreground">Нет разбивки оплат</div>}
            </div>

            {/* Документы смены (раскрываемые) */}
            <DocGroup icon={PackagePlus} title="Приходы" cls="text-primary" docs={data.receipts ?? []}
              meta={(d) => `${d.supplier} · ${d.positions} поз · ${fmtMoney(d.amount_net)}`} />
            <DocGroup icon={ClipboardList} title="Инвентаризации" cls="text-blue-300/80" docs={data.inventory ?? []}
              meta={(d) => `${d.dev_positions} отклонений · ${fmtMoney(d.net)}`} />
            <DocGroup icon={Trash2} title="Списания" cls="text-red-400/80" docs={data.writeoffs ?? []}
              meta={(d) => `${d.reason ?? '—'} · ${d.positions} поз · ${fmtMoney(d.amount)}`} />
            <DocGroup icon={ArrowLeftRight} title="Перемещения" docs={data.transfers ?? []}
              meta={(d) => `→ ${d.to ?? '—'} · ${d.positions} поз · ${fmtMoney(d.amount)}`} />
            <DocGroup icon={Tag} title="Переоценки" cls="text-amber-300/80" docs={data.revaluations ?? []}
              meta={(d) => `${d.positions} позиций`} />

            {/* Строки продаж */}
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="flex items-center gap-1.5 text-sm font-medium mb-2"><ShoppingCart className="h-4 w-4 text-primary" /> Продажи по товарам <span className="text-[11px] text-muted-foreground font-normal">· {data.sales?.length ?? 0}</span></div>
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
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
