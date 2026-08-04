/**
 * Смена-детализация (модалка): смена как полный составной документ. Строки
 * продаж по SKU, касса (оплаты), возвраты + ВСЕ документы того же дня —
 * приходы, инвентаризации, списания, перемещения, переоценки — с раскрытием
 * строк по клику. Данные: /api/store/shift?key=… (shift_detail).
 *
 * Читают её в двух режимах: «что за деньги в этой смене» и «какие документы её
 * сопровождали». Поэтому деньги вынесены в шапку крупно, документы и касса
 * стоят слева одной колонкой, а длинный список продаж — справа, со своим
 * поиском: искать товар прокруткой в трёхстах строках нельзя.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShoppingCart, Wallet, PackagePlus, ClipboardList, Trash2, ArrowLeftRight, Tag,
  ChevronRight, Search, X,
} from 'lucide-react'
import { getStoreShiftDetail, type ShiftDocLine } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { ChzBadge } from '@/components/common/ChzBadge'
import { DocLines } from './DocsModal'   // строки документа рисует общий компонент

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Группа документов одного типа: заголовок + раскрываемые документы. */
function DocGroup<T extends { number: string | null; lines: ShiftDocLine[] }>({
  icon: Icon, title, cls, docs, meta, sum,
}: {
  icon: typeof PackagePlus; title: string; cls?: string
  docs: T[]; meta: (d: T) => string; sum?: string
}) {
  const [open, setOpen] = useState<number | null>(null)
  if (!docs.length) return null
  return (
    <div className="overflow-hidden rounded-lg border border-border/50 bg-card/40">
      <div className="flex items-center gap-1.5 border-b border-border/30 px-3 py-2 text-sm font-medium">
        <Icon className={`h-4 w-4 ${cls ?? 'text-muted-foreground'}`} />
        <span>{title}</span>
        <span className="rounded-full bg-muted/60 px-1.5 text-[10px] font-normal tabular-nums text-muted-foreground">
          {docs.length}
        </span>
        {sum && <span className="ml-auto text-xs font-normal tabular-nums text-muted-foreground">{sum}</span>}
      </div>
      <div>
        {docs.map((d, i) => (
          <div key={i} className="border-t border-border/20 first:border-t-0">
            <button onClick={() => setOpen(open === i ? null : i)}
              aria-expanded={open === i}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/20">
              <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${open === i ? 'rotate-90' : ''}`} />
              <span className="shrink-0 tabular-nums text-muted-foreground">{d.number ?? '—'}</span>
              <span className="flex-1 truncate">{meta(d)}</span>
            </button>
            {open === i && <div className="bg-background/40"><DocLines lines={d.lines} /></div>}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Крупная величина в шапке смены. */
function Метрика({ label, value, hint, cls }: {
  label: string; value: string; hint?: string; cls?: string
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 truncate text-xl font-semibold tabular-nums ${cls ?? ''}`}>{value}</div>
      {hint && <div className="truncate text-[10px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export function ShiftDetailModal({ shiftKey, companyId, onClose }: { shiftKey: string; companyId: string; onClose: () => void }) {
  const [поиск, задатьПоиск] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['store-shift-detail', companyId, shiftKey],
    queryFn: () => getStoreShiftDetail(shiftKey),
  })
  const sh = data?.shift

  // Esc закрывает: модалка перекрывает весь холст, и мышь до крестика в углу —
  // лишняя работа для того, кто пролистывает смены одну за другой.
  useEffect(() => {
    const наКлавишу = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', наКлавишу)
    return () => window.removeEventListener('keydown', наКлавишу)
  }, [onClose])

  const оплаты = data?.payments ?? []
  const кассаВсего = оплаты.reduce((a, p) => a + p.amount, 0)

  const продажи = useMemo(() => {
    const q = поиск.trim().toLowerCase()
    const строки = (data?.sales ?? []).filter(
      (l) => !q || `${l.name} ${l.category ?? ''}`.toLowerCase().includes(q))
    return [...строки].sort((a, b) => b.revenue - a.revenue)
  }, [data, поиск])
  const пикПродаж = Math.max(1, ...продажи.map((l) => l.revenue))

  const документов = (data?.receipts?.length ?? 0) + (data?.inventory?.length ?? 0)
    + (data?.writeoffs?.length ?? 0) + (data?.transfers?.length ?? 0)
    + (data?.revaluations?.length ?? 0)

  const доляСопутки = sh && sh.revenue > 0 ? Math.round((sh.soputka / sh.revenue) * 100) : null

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={`Смена ${sh?.number ?? ''}`}
        className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="border-b border-border/50 px-5 py-3">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-sm font-semibold">
                Смена {sh?.number ?? ''}
                {sh && <span className="ml-2 font-normal text-muted-foreground">{sh.date} · АЗС {sh.station}</span>}
              </div>
              {sh?.open && (
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  открыта {sh.open}{sh.close ? ` · закрыта ${sh.close}` : ''}
                </div>
              )}
            </div>
            <button onClick={onClose} aria-label="Закрыть"
              className="rounded-md p-1 text-muted-foreground hover:bg-accent/30 hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>

          {sh && (
            <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-5">
              <Метрика label="Выручка" value={fmtMoney(sh.revenue)}
                       hint={доляСопутки !== null ? `сопутка ${доляСопутки}% · общепит ${100 - доляСопутки}%` : undefined} />
              <Метрика label="Сопутка" value={fmtMoney(sh.soputka)} />
              <Метрика label="Общепит" value={fmtMoney(sh.obshepit)} />
              <Метрика label="Позиций" value={nf(sh.positions)}
                       hint={`${nf(документов)} документов дня`} />
              <Метрика label="Возвраты" value={sh.returns > 0 ? fmtMoney(sh.returns) : '—'}
                       cls={sh.returns > 0 ? 'text-amber-300/90' : 'text-muted-foreground'} />
            </div>
          )}
        </div>

        {isLoading || !data ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка смены…</div>
        ) : !data.found ? (
          <div className="p-6 text-sm text-muted-foreground">Смена не найдена.</div>
        ) : (
          <div className="grid gap-4 overflow-auto p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            {/* Слева — чем смена закрыта: касса и документы дня */}
            <div className="space-y-3">
              <div className="rounded-lg border border-border/50 bg-card/40 p-3">
                <div className="mb-2 flex items-center gap-1.5 text-sm font-medium">
                  <Wallet className="h-4 w-4 text-emerald-300/80" /> Касса
                  {кассаВсего > 0 && (
                    <span className="ml-auto text-xs font-normal tabular-nums text-muted-foreground">
                      {fmtMoney(кассаВсего)}
                    </span>
                  )}
                </div>
                {оплаты.length > 0 ? (
                  <div className="space-y-1.5">
                    {оплаты.map((p, i) => {
                      const доля = кассаВсего > 0 ? (p.amount / кассаВсего) * 100 : 0
                      return (
                        <div key={i}>
                          <div className="flex items-baseline justify-between gap-3 text-xs">
                            <span className="truncate text-muted-foreground">{p.form}</span>
                            <span className="shrink-0 tabular-nums">
                              {fmtMoney(p.amount)}
                              <span className="ml-1.5 text-[10px] text-muted-foreground">{Math.round(доля)}%</span>
                            </span>
                          </div>
                          <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                            <div className="h-full bg-emerald-400/60" style={{ width: `${доля}%` }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : <div className="text-xs text-muted-foreground">Нет разбивки оплат</div>}
              </div>

              {документов === 0 ? (
                <div className="rounded-lg border border-dashed border-border/50 p-4 text-xs text-muted-foreground">
                  В этот день на станции не было ни приёмок, ни инвентаризаций, ни списаний —
                  смена состоит только из продаж.
                </div>
              ) : (
                <>
                  <DocGroup icon={PackagePlus} title="Приходы" cls="text-primary" docs={data.receipts ?? []}
                    sum={fmtMoney((data.receipts ?? []).reduce((a, d) => a + d.amount_net, 0))}
                    meta={(d) => `${d.supplier} · ${d.positions} поз · ${fmtMoney(d.amount_net)}`} />
                  <DocGroup icon={ClipboardList} title="Инвентаризации" cls="text-blue-300/80" docs={data.inventory ?? []}
                    sum={fmtMoney((data.inventory ?? []).reduce((a, d) => a + d.net, 0))}
                    meta={(d) => `${d.dev_positions} отклонений · ${fmtMoney(d.net)}`} />
                  <DocGroup icon={Trash2} title="Списания" cls="text-red-400/80" docs={data.writeoffs ?? []}
                    sum={fmtMoney((data.writeoffs ?? []).reduce((a, d) => a + d.amount, 0))}
                    meta={(d) => `${d.reason ?? '—'} · ${d.positions} поз · ${fmtMoney(d.amount)}`} />
                  <DocGroup icon={ArrowLeftRight} title="Перемещения" docs={data.transfers ?? []}
                    sum={fmtMoney((data.transfers ?? []).reduce((a, d) => a + d.amount, 0))}
                    meta={(d) => `→ ${d.to ?? '—'} · ${d.positions} поз · ${fmtMoney(d.amount)}`} />
                  <DocGroup icon={Tag} title="Переоценки" cls="text-amber-300/80" docs={data.revaluations ?? []}
                    meta={(d) => `${d.positions} позиций`} />
                </>
              )}
            </div>

            {/* Справа — из чего сложилась выручка */}
            <div className="flex min-h-0 flex-col rounded-lg border border-border/50 bg-card/40">
              <div className="flex flex-wrap items-center gap-2 border-b border-border/30 px-3 py-2">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  <ShoppingCart className="h-4 w-4 text-primary" /> Продажи по товарам
                  <span className="rounded-full bg-muted/60 px-1.5 text-[10px] font-normal tabular-nums text-muted-foreground">
                    {продажи.length}
                  </span>
                </div>
                <div className="relative ml-auto min-w-[160px] flex-1">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <input value={поиск} onChange={(e) => задатьПоиск(e.target.value)}
                    placeholder="Товар или категория" aria-label="Поиск по товарам смены"
                    className="h-7 w-full rounded-md border border-border/60 bg-background/60 pl-8 pr-2 text-xs outline-none placeholder:text-muted-foreground/70 focus:border-primary/60" />
                </div>
              </div>

              <div className="max-h-[52vh] overflow-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 z-10 bg-card text-muted-foreground">
                    <tr className="border-b border-border/30">
                      <th className="px-3 py-1.5 text-left font-medium">Товар</th>
                      <th className="px-2 py-1.5 text-center font-medium">ЧЗ</th>
                      <th className="px-2 py-1.5 text-left font-medium">Категория</th>
                      <th className="px-2 py-1.5 text-right font-medium">Кол-во</th>
                      <th className="px-3 py-1.5 text-right font-medium">Выручка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {продажи.map((l) => (
                      <tr key={l.guid} className="border-t border-border/20 hover:bg-accent/10">
                        <td className="px-3 py-1">
                          <div className="truncate">{l.name}</div>
                          {/* Полоса доли: топ смены виден без чтения чисел */}
                          <div className="mt-0.5 h-0.5 overflow-hidden rounded-full bg-muted/60">
                            <div className="h-full bg-primary/50"
                                 style={{ width: `${Math.max(2, (l.revenue / пикПродаж) * 100)}%` }} />
                          </div>
                        </td>
                        <td className="px-2 py-1 text-center">{l.marked && <ChzBadge />}</td>
                        <td className="px-2 py-1 text-muted-foreground">{l.category ?? '—'}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{nf(l.qty, 3)}</td>
                        <td className="px-3 py-1 text-right font-medium tabular-nums">{fmtMoney(l.revenue)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {продажи.length === 0 && (
                  <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                    {(data.sales?.length ?? 0) === 0
                      ? 'В смене нет строк продаж.'
                      : 'Ни один товар не совпал с поиском.'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
