/**
 * «Инвентаризация» раздела «Магазин» — реестр инвентаризаций ЦБ ЭЛСИ.АЗК +
 * отклонения факт↔учёт (недостачи/излишки, shrinkage). Данные: /api/store/inventory
 * (GoodsDashboardService.inventory) — снимок Document.ИнвентаризацияТоваровНаСкладе.
 *
 * Клик по документу → модалка со строками-отклонениями (drill-down).
 * Свежие полные пересчёты часто без отклонений (факт=учёт) — это норма (контроль).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreInventory, type StoreInventoryDoc } from '@/services/storeService'
import { SnapshotBadge } from '@/components/common/SnapshotBadge'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

export function StoreInventoryPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom?: string; dateTo?: string }) {
  const [warehouse, setWarehouse] = useState<string | undefined>(undefined)
  const [onlyDev, setOnlyDev] = useState(false)
  const [openDoc, setOpenDoc] = useState<StoreInventoryDoc | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-inventory', companyId, warehouse ?? '', onlyDev, dateFrom, dateTo],
    queryFn: () => getStoreInventory({ warehouse, onlyDev, dateFrom, dateTo }),
  })

  const docs = useMemo(() => data?.docs ?? [], [data])

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка инвентаризаций…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки инвентаризаций</div>
  if (!data) return null

  const s = data.summary
  const KPIS: { label: string; value: string; hint?: string; cls?: string }[] = [
    { label: 'Инвентаризаций', value: nf(s.docs_count), hint: `${s.period_from ?? ''} – ${s.period_to ?? ''}` },
    { label: 'С отклонениями', value: nf(s.docs_with_dev), hint: 'факт ≠ учёт' },
    { label: 'Недостачи', value: money(s.shortage_amount), cls: 'text-red-400/90', hint: 'списание при пересчёте' },
    { label: 'Излишки', value: money(s.surplus_amount), cls: 'text-emerald-300/90', hint: 'оприходование' },
    { label: 'Итог (shrinkage)', value: money(s.net_amount), cls: s.net_amount < 0 ? 'text-red-400/90' : 'text-emerald-300/90' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">Инвентаризация — недостачи и излишки</h3>
            <SnapshotBadge at={data.snapshot_at} />
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Реестр инвентаризаций из ЦБ + отклонения факт↔учёт. Клик по документу — строки-отклонения.
            Полные пересчёты без отклонений (факт=учёт) — контрольные, это норма.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={warehouse ?? ''} onChange={(e) => setWarehouse(e.target.value || undefined)}
            className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background"
          >
            <option value="">Все склады магазина</option>
            {data.warehouses.map((w) => (
              <option key={w.code} value={w.code}>{w.name ?? w.code} ({w.count})</option>
            ))}
          </select>
          <label className="text-xs flex items-center gap-1.5 text-muted-foreground">
            <input type="checkbox" checked={onlyDev} onChange={(e) => setOnlyDev(e.target.checked)} />
            только с отклонениями
          </label>
        </div>
      </div>

      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{k.hint}</div>}
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        {/* Реестр документов */}
        <div className="overflow-x-auto rounded-lg border border-border/50 h-fit">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Дата</th>
                <th className="px-3 py-2 font-medium text-left">Номер</th>
                <th className="px-3 py-2 font-medium text-left">Склад</th>
                <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Откл. поз.</th>
                <th className="px-3 py-2 font-medium text-right">Недостача</th>
                <th className="px-3 py-2 font-medium text-right">Излишки</th>
                <th className="px-3 py-2 font-medium text-right">Итог</th>
              </tr>
            </thead>
            <tbody>
              {docs.slice(0, 300).map((d) => (
                <tr
                  key={d.ref}
                  onClick={() => d.dev_positions && setOpenDoc(d)}
                  className={`border-t border-border/30 ${d.dev_positions ? 'hover:bg-accent/20 cursor-pointer' : 'opacity-60'}`}
                >
                  <td className="px-3 py-1.5 whitespace-nowrap">{d.date ?? '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums">{d.number ?? '—'}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{d.warehouse_code}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{d.dev_positions || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-red-400/80">{money(d.shortage_amount)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-emerald-300/80">{money(d.surplus_amount)}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${d.net_amount < 0 ? 'text-red-400/80' : d.net_amount > 0 ? 'text-emerald-300/80' : ''}`}>{money(d.net_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {docs.length > 300 && (
            <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">Показано 300 из {nf(docs.length)}.</div>
          )}
          {docs.length === 0 && (
            <div className="px-3 py-6 text-sm text-muted-foreground text-center">
              Нет инвентаризаций. Наполните: <code>py -3.13 scripts/pull_cb_inventory_dev.py</code>
            </div>
          )}
        </div>

        {/* Топ недостач по товарам */}
        <div className="rounded-lg border border-border/50 bg-card/40 p-3 h-fit">
          <div className="text-sm font-medium mb-2">Топ недостач по товарам</div>
          <div className="space-y-1.5">
            {data.top_shortage.length === 0 && <div className="text-xs text-muted-foreground">Нет данных</div>}
            {data.top_shortage.map((t) => (
              <div key={t.name} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate" title={t.name}>{t.name}</span>
                <span className="tabular-nums text-red-400/80 shrink-0">{fmtMoney(t.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Модалка строк-отклонений документа */}
      {openDoc && (
        <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={() => setOpenDoc(null)}>
          <div className="bg-card border border-border rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
              <div>
                <div className="text-sm font-semibold">Инвентаризация {openDoc.number} · {openDoc.date}</div>
                <div className="text-xs text-muted-foreground">
                  {openDoc.warehouse_name} · {openDoc.dev_positions} позиций с отклонением ·
                  недостача <span className="text-red-400/80">{fmtMoney(openDoc.shortage_amount)}</span> ·
                  излишки <span className="text-emerald-300/80">{fmtMoney(openDoc.surplus_amount)}</span>
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
                    <th className="px-3 py-2 font-medium text-right">Факт</th>
                    <th className="px-3 py-2 font-medium text-right">Учёт</th>
                    <th className="px-3 py-2 font-medium text-right">Откл.</th>
                    <th className="px-3 py-2 font-medium text-right">Сумма откл.</th>
                  </tr>
                </thead>
                <tbody>
                  {openDoc.lines.map((ln, idx) => (
                    <tr key={`${ln.ref}-${idx}`} className="border-t border-border/30">
                      <td className="px-3 py-1.5">{ln.name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{nf(ln.fact, 3)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{nf(ln.uchet, 3)}</td>
                      <td className={`px-3 py-1.5 text-right tabular-nums ${ln.dev < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>{nf(ln.dev, 3)}</td>
                      <td className={`px-3 py-1.5 text-right tabular-nums ${ln.amount_dev < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>{fmtMoney(ln.amount_dev)}</td>
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
