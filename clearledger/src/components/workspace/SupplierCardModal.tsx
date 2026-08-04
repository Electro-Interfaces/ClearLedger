/**
 * Карточка поставщика — история работы с ним, а не список накладных.
 *
 * Раньше клик по поставщику открывал его накладные, и на этом всё: что мы у
 * него берём, почём было в прошлый раз, когда он привозил в последний раз,
 * сколько возвращали — данные в 1С есть, но никто их не разворачивал. Для
 * товароведа это половина работы: разговор о цене начинается не со «стало
 * дорого», а с «в прошлый раз было столько».
 *
 * Период ограничивает документы, но НЕ историю цен: прошлая цена берётся из
 * прошлой поставки, даже если она была до начала выбранного периода.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Truck, X, TrendingUp, TrendingDown, Undo2 } from 'lucide-react'
import { getSupplierCard, type SupplierCard } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })

function Плитка({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border/50 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

const ВКЛАДКИ = ['items', 'docs', 'returns'] as const
type Вкладка = (typeof ВКЛАДКИ)[number]

export function SupplierCardModal({ name, companyId, dateFrom, dateTo, stations, onClose, onOpenSku }: {
  name: string; companyId: string; dateFrom: string; dateTo: string
  stations?: string[]; onClose: () => void; onOpenSku?: (ref: string) => void
}) {
  const [tab, setTab] = useState<Вкладка>('items')
  const { data, isLoading } = useQuery<SupplierCard>({
    queryKey: ['supplier-card', companyId, name, dateFrom, dateTo, stations?.join(',')],
    queryFn: () => getSupplierCard(name, dateFrom, dateTo, stations),
  })

  const подпись: Record<Вкладка, string> = {
    items: `Что возит${data ? ` (${data.items.length})` : ''}`,
    docs: `Поставки${data ? ` (${data.docs.length})` : ''}`,
    returns: `Возвраты${data ? ` (${data.returns.length})` : ''}`,
  }

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col rounded-lg border border-border bg-card shadow-xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between border-b border-border/50 px-5 py-3.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-base font-semibold">
              <Truck className="h-4 w-4 text-primary" />{name}
            </div>
            {data && (
              <div className="mt-0.5 text-xs text-muted-foreground">
                {data.totals.docs_all_time} поставок за всё время
                {data.totals.first && ` · с ${data.totals.first}`}
                {data.totals.avg_days != null && ` · обычно раз в ${data.totals.avg_days} дн.`}
              </div>
            )}
          </div>
          <button onClick={onClose} className="px-2 text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {isLoading || !data ? (
          <div className="p-6 text-sm text-muted-foreground">Собираем историю поставок…</div>
        ) : (
          <div className="overflow-auto p-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <Плитка label="Поставок за период" value={String(data.totals.docs)} />
              <Плитка label="Закупки (нетто)" value={fmtMoney(data.totals.amount_net)} />
              <Плитка label="Позиций возит" value={String(data.totals.positions)} />
              <Плитка label="Последняя поставка" value={data.totals.last ?? '—'}
                      hint={data.totals.returns > 0 ? `возвратов: ${data.totals.returns}` : undefined} />
            </div>

            <div className="mt-4 flex gap-2 text-xs">
              {ВКЛАДКИ.map((key) => (
                <button key={key} onClick={() => setTab(key)}
                        className={`rounded-md border px-2.5 py-1 ${tab === key
                          ? 'border-primary/50 text-primary' : 'border-border/50 text-muted-foreground'}`}>
                  {подпись[key]}
                </button>
              ))}
            </div>

            {tab === 'items' && (
              <table className="mt-3 w-full text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-border/50">
                    <th className="py-1.5 text-left">Товар</th>
                    <th className="py-1.5 text-right">Куплено</th>
                    <th className="py-1.5 text-right">Нетто</th>
                    <th className="py-1.5 text-right">Последняя цена</th>
                    <th className="py-1.5 text-right">Было</th>
                    <th className="py-1.5 text-left">Изменение</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((it) => (
                    <tr key={it.ref} className="border-b border-border/50">
                      <td className="py-1.5">
                        {onOpenSku ? (
                          <button className="text-left hover:text-primary" onClick={() => onOpenSku(it.ref)}>
                            {it.name}
                          </button>
                        ) : it.name}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">{nf.format(it.qty)}</td>
                      <td className="py-1.5 text-right tabular-nums">{fmtMoney(it.amount_net)}</td>
                      <td className="py-1.5 text-right tabular-nums">
                        {it.last_price != null ? fmtMoney(it.last_price) : '—'}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                        {it.prev_price != null ? fmtMoney(it.prev_price) : '—'}
                      </td>
                      <td className="py-1.5">
                        {it.price_delta_pct != null && (
                          <span className={`inline-flex items-center gap-1 text-xs ${
                            it.price_delta_pct > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                            {it.price_delta_pct > 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                            {it.price_delta_pct > 0 ? '+' : ''}{it.price_delta_pct}%
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {tab === 'docs' && (
              <table className="mt-3 w-full text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-border/50">
                    <th className="py-1.5 text-left">Дата</th>
                    <th className="py-1.5 text-left">Документ</th>
                    <th className="py-1.5 text-left">Станция</th>
                    <th className="py-1.5 text-right">Позиций</th>
                    <th className="py-1.5 text-right">Нетто</th>
                  </tr>
                </thead>
                <tbody>
                  {data.docs.map((d, i) => (
                    <tr key={`${d.number ?? 'б-н'}-${i}`} className="border-b border-border/50">
                      <td className="py-1.5">{d.date}</td>
                      <td className="py-1.5">
                        {d.number ?? '—'}
                        {d.incoming && <span className="text-muted-foreground"> · вх. {d.incoming}</span>}
                      </td>
                      <td className="py-1.5 text-muted-foreground">{d.station ?? '—'}</td>
                      <td className="py-1.5 text-right tabular-nums">{d.positions}</td>
                      <td className="py-1.5 text-right tabular-nums">{fmtMoney(d.amount_net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {tab === 'returns' && (
              data.returns.length === 0 ? (
                <div className="mt-3 text-sm text-muted-foreground">
                  Возвратов этому поставщику не было — по данным 1С.
                </div>
              ) : (
                <table className="mt-3 w-full text-sm">
                  <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr className="border-b border-border/50">
                      <th className="py-1.5 text-left">Дата</th>
                      <th className="py-1.5 text-left">Документ</th>
                      <th className="py-1.5 text-right">Позиций</th>
                      <th className="py-1.5 text-right">Сумма</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.returns.map((r, i) => (
                      <tr key={`${r.number ?? 'б-н'}-${i}`} className="border-b border-border/50">
                        <td className="py-1.5">
                          <Undo2 className="mr-1 inline h-3 w-3 text-muted-foreground" />{r.date}
                        </td>
                        <td className="py-1.5">{r.number ?? '—'}</td>
                        <td className="py-1.5 text-right tabular-nums">{r.positions}</td>
                        <td className="py-1.5 text-right tabular-nums">{fmtMoney(r.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}
          </div>
        )}
      </div>
    </div>
  )
}
