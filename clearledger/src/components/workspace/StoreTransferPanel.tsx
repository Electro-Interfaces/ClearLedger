/**
 * «Перемещения» раздела «Магазин» — реестр ПеремещениеТоваров ЦБ ЭЛСИ.АЗК
 * относительно складов 208 (откуда→куда) + направления (внутреннее склад↔зал,
 * приход на 208, расход с 208). Данные: /api/store/transfers.
 * Сумма = розн. стоимость перемещённого (Количество × Цена). Клик по док → строки.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreTransfers, type StoreTransferDoc } from '@/services/storeService'
import { SnapshotBadge } from '@/components/common/SnapshotBadge'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

export function StoreTransferPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom?: string; dateTo?: string }) {
  const [direction, setDirection] = useState<string | null>(null)
  const [openDoc, setOpenDoc] = useState<StoreTransferDoc | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-transfers', companyId, dateFrom, dateTo],
    queryFn: () => getStoreTransfers({ dateFrom, dateTo }),
  })

  const docs = useMemo(
    () => (data?.docs ?? []).filter((d) => !direction || d.direction === direction),
    [data, direction],
  )

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка перемещений…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки перемещений</div>
  if (!data) return null

  const tot = docs.reduce((s, d) => s + d.total_amount, 0)
  const maxDir = Math.max(1, ...data.by_direction.map((r) => Math.abs(r.amount)))
  const s = data.summary

  const KPIS: { label: string; value: string; hint?: string }[] = [
    { label: 'Перемещений', value: nf(docs.length), hint: `${s.period_from ?? ''} – ${s.period_to ?? ''}` },
    { label: 'Розн. стоимость', value: money(tot), hint: 'кол-во × цена' },
    { label: 'Приход на 208', value: money(s.inbound_amount), hint: 'с других складов' },
    { label: 'Расход с 208', value: money(s.outbound_amount), hint: 'на другие склады' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold inline-flex items-center gap-2">Перемещения <SnapshotBadge at={data.snapshot_at} /></h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            ПеремещениеТоваров из ЦБ относительно складов 208. Большинство — внутренние (склад ↔ торговый
            зал, пополнение полки). Клик по документу — строки. {direction && <>Фильтр: <b>{direction}</b> <button className="underline ml-1" onClick={() => setDirection(null)}>сбросить</button></>}
          </p>
        </div>
      </div>

      <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-4">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className="text-lg font-semibold tabular-nums mt-0.5">{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{k.hint}</div>}
          </div>
        ))}
      </div>

      {/* Направления (клик = фильтр) */}
      <div className="rounded-lg border border-border/50 bg-card/40 p-3">
        <div className="text-sm font-medium mb-2">Направления перемещений</div>
        <div className="space-y-1.5">
          {data.by_direction.map((r) => (
            <button
              key={r.direction} onClick={() => setDirection(direction === r.direction ? null : r.direction)}
              className={`w-full flex items-center gap-2 text-xs group ${direction === r.direction ? 'font-semibold' : ''}`}
            >
              <span className="w-48 text-left truncate shrink-0">{r.direction}</span>
              <span className="flex-1 h-3 bg-muted/30 rounded overflow-hidden">
                <span className="block h-full bg-blue-400/40 group-hover:bg-blue-400/60 transition-colors" style={{ width: `${(Math.abs(r.amount) / maxDir) * 100}%` }} />
              </span>
              <span className="w-28 text-right tabular-nums shrink-0">{fmtMoney(r.amount)}</span>
              <span className="w-10 text-right tabular-nums text-muted-foreground shrink-0">{r.count}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        {/* Реестр */}
        <div className="overflow-x-auto rounded-lg border border-border/50 h-fit">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Дата</th>
                <th className="px-3 py-2 font-medium text-left">Номер</th>
                <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Откуда → Куда</th>
                <th className="px-3 py-2 font-medium text-right">Позиций</th>
                <th className="px-3 py-2 font-medium text-right">Стоимость</th>
              </tr>
            </thead>
            <tbody>
              {docs.slice(0, 300).map((d) => (
                <tr
                  key={d.ref}
                  onClick={() => d.positions && setOpenDoc(d)}
                  className={`border-t border-border/30 ${d.positions ? 'hover:bg-accent/20 cursor-pointer' : 'opacity-60'}`}
                >
                  <td className="px-3 py-1.5 whitespace-nowrap">{d.date ?? '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums">{d.number ?? '—'}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    <span className="text-muted-foreground">{d.from_code}</span>
                    <span className="mx-1 opacity-50">→</span>
                    <span className="text-muted-foreground">{d.to_code ?? '—'}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{d.positions || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money(d.total_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {docs.length > 300 && (
            <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">Показано 300 из {nf(docs.length)}.</div>
          )}
          {docs.length === 0 && (
            <div className="px-3 py-6 text-sm text-muted-foreground text-center">
              Нет перемещений. Наполните: <code>py -3.13 scripts/pull_cb_transfer_dev.py</code>
            </div>
          )}
        </div>

        {/* Топ перемещаемых товаров */}
        <div className="rounded-lg border border-border/50 bg-card/40 p-3 h-fit">
          <div className="text-sm font-medium mb-2">Топ перемещаемых товаров</div>
          <div className="space-y-1.5">
            {data.top_sku.length === 0 && <div className="text-xs text-muted-foreground">Нет данных</div>}
            {data.top_sku.map((t) => (
              <div key={t.name} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate" title={t.name}>{t.name}</span>
                <span className="tabular-nums text-blue-300/80 shrink-0">{fmtMoney(t.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Модалка строк документа */}
      {openDoc && (
        <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={() => setOpenDoc(null)}>
          <div className="bg-card border border-border rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
              <div>
                <div className="text-sm font-semibold">Перемещение {openDoc.number} · {openDoc.date}</div>
                <div className="text-xs text-muted-foreground">
                  {openDoc.from_name} → {openDoc.to_name} · {openDoc.direction} · {openDoc.positions} позиций · {fmtMoney(openDoc.total_amount)}
                  {openDoc.comment && <> · {openDoc.comment}</>}
                </div>
              </div>
              <button onClick={() => setOpenDoc(null)} className="text-muted-foreground hover:text-foreground text-lg leading-none px-2">×</button>
            </div>
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/30 text-muted-foreground sticky top-0">
                  <tr>
                    <th className="px-3 py-2 font-medium text-left">Товар</th>
                    <th className="px-3 py-2 font-medium text-right">Кол-во</th>
                    <th className="px-3 py-2 font-medium text-right">Цена</th>
                    <th className="px-3 py-2 font-medium text-right">Стоимость</th>
                  </tr>
                </thead>
                <tbody>
                  {openDoc.lines.map((ln, idx) => (
                    <tr key={`${ln.ref}-${idx}`} className="border-t border-border/30">
                      <td className="px-3 py-1.5">{ln.name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{nf(ln.qty, 3)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{fmtMoney(ln.price)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(ln.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
