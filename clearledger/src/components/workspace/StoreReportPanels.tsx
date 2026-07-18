/**
 * Отчётные панели раздела «Магазин»: Приёмка / Поставщики / Общепит / Категории.
 * Данные: /api/store/{receipts|suppliers|catering|categories} (GoodsDashboardService).
 * Имена поставщиков — из кеша CbRef, блюда/товары — CbNomenclature.
 */
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  getStoreReport,
  type StoreReceiptsData, type StoreSuppliersData,
  type StoreCategoriesData,
  type StoreBarcodesData, type StoreRecipesData,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { useResetOnScopeChange } from '@/hooks/useScopeReset'
import { NomenclatureCardModal } from './NomenclatureCardModal'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

interface PanelProps { companyId: string; dateFrom: string; dateTo: string; stations?: string[] }

function useReport<T>(report: string, p: PanelProps) {
  return useQuery({
    queryKey: ['store-report', report, p.companyId, p.dateFrom, p.dateTo, p.stations],
    queryFn: () => getStoreReport<T>(report, p.dateFrom, p.dateTo, p.stations),
  })
}

function Shell({ title, sub, children }: { title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold">{title}</h3>
        {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
      </div>
      {children}
    </div>
  )
}

function Table({ head, rows }: { head: { label: string; num?: boolean }[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border/50">
      <table className="w-full text-xs">
        <thead className="bg-muted/30 text-muted-foreground">
          <tr>{head.map((h, i) => <th key={i} className={`px-3 py-2 font-medium whitespace-nowrap ${h.num ? 'text-right' : 'text-left'}`}>{h.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-t border-border/30 hover:bg-accent/20">
              {r.map((cell, ci) => <td key={ci} className={`px-3 py-1.5 ${head[ci]?.num ? 'text-right tabular-nums' : ''}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет данных за период (поставьте апрель).</div>}
    </div>
  )
}

const wrap = (q: { isLoading: boolean; error: unknown }, render: () => ReactNode): ReactNode => {
  if (q.isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  if (q.error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки</div>
  return render()
}

export function StoreReceiptsPanel(p: PanelProps) {
  const q = useReport<StoreReceiptsData>('receipts', p)
  return wrap(q, () => {
    const d = q.data!
    return (
      <Shell title="Приёмка (поступления)"
        sub={`${d.period.from} – ${d.period.to} · ${d.summary.count} документов · закупки нетто ${fmtMoney(d.summary.amount_net)} · НДС ${fmtMoney(d.summary.vat)}`}>
        <Table
          head={[{ label: 'Дата' }, { label: 'Номер' }, { label: 'Поставщик' }, { label: 'Позиций', num: true }, { label: 'Сумма (нетто)', num: true }, { label: 'НДС', num: true }]}
          rows={d.docs.map((r) => [r.date, r.number, r.supplier, nf(r.positions), fmtMoney(r.amount_net), fmtMoney(r.vat)])}
        />
      </Shell>
    )
  })
}

export function StoreSuppliersPanel(p: PanelProps) {
  const q = useReport<StoreSuppliersData>('suppliers', p)
  return wrap(q, () => {
    const d = q.data!
    return (
      <Shell title="Поставщики"
        sub={`${d.period.from} – ${d.period.to} · ${d.summary.count} поставщиков · закупки нетто ${fmtMoney(d.summary.amount_net)}`}>
        <Table
          head={[{ label: 'Поставщик' }, { label: 'Закупки (нетто)', num: true }, { label: 'Документов', num: true }, { label: 'SKU', num: true }]}
          rows={d.suppliers.map((r) => [r.name, fmtMoney(r.amount_net), nf(r.docs), nf(r.sku_count)])}
        />
      </Shell>
    )
  })
}

export function StoreCategoriesPanel(p: PanelProps) {
  const q = useReport<StoreCategoriesData>('categories', p)
  return wrap(q, () => {
    const d = q.data!
    return (
      <Shell title="Категории"
        sub={`${d.period.from} – ${d.period.to} · ${d.summary.count} категории · выручка ${fmtMoney(d.summary.revenue)}`}>
        <Table
          head={[{ label: 'Категория' }, { label: 'Выручка', num: true }, { label: 'Доля', num: true }, { label: 'Маржа %', num: true }, { label: 'SKU', num: true }, { label: 'Продано', num: true }]}
          rows={d.categories.map((r) => [
            r.category, fmtMoney(r.revenue), `${r.share}%`,
            r.margin_pct != null ? `${r.margin_pct}%` : '—', nf(r.sku_count), nf(r.qty),
          ])}
        />
      </Shell>
    )
  })
}

export function StoreBarcodesPanel(p: PanelProps) {
  const q = useReport<StoreBarcodesData>('barcodes', p)
  const [search, setSearch] = useState('')
  // Смена контура обнуляет поиск по номенклатуре (CLAUDE.md, правило 5).
  useResetOnScopeChange(() => setSearch(''))
  const [openGuid, setOpenGuid] = useState<string | null>(null)
  return (
    <>
      {wrap(q, () => {
        const d = q.data!
        const items = search
          ? d.items.filter((i) => i.barcode.includes(search) || i.owner_name.toLowerCase().includes(search.toLowerCase()))
          : d.items
        return (
          <Shell title="Штрихкоды / EAN"
            sub={`${d.total} штрихкодов · ${Object.entries(d.by_type).map(([t, n]) => `${t}: ${n}`).join(' · ')} · клик по товару — карточка`}>
            <div className="mb-3">
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="поиск по штрихкоду или товару…"
                className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-64" />
            </div>
            <Table
              head={[{ label: 'Штрихкод' }, { label: 'Товар' }, { label: 'Тип' }, { label: 'Основной' }]}
              rows={items.slice(0, 300).map((i) => [
                <span className="font-mono">{i.barcode}</span>,
                i.owner_guid
                  ? <button onClick={() => setOpenGuid(i.owner_guid)} className="text-left hover:text-primary hover:underline">{i.owner_name}</button>
                  : i.owner_name,
                i.type ?? '—', i.main ? 'да' : '',
              ])}
            />
            {items.length > 300 && (
              <div className="px-1 pt-2 text-[11px] text-muted-foreground">Показано 300 из {items.length}. Уточните поиск.</div>
            )}
          </Shell>
        )
      })}
      {openGuid && <NomenclatureCardModal guid={openGuid} companyId={p.companyId} dateFrom={p.dateFrom} dateTo={p.dateTo} onClose={() => setOpenGuid(null)} />}
    </>
  )
}

export function StoreRecipesPanel(p: PanelProps) {
  const q = useReport<StoreRecipesData>('recipes', p)
  const [openGuid, setOpenGuid] = useState<string | null>(null)
  return (
    <>
      {wrap(q, () => {
        const d = q.data!
        return (
          <Shell title="Рецептуры (ТТК)"
            sub={`${d.period.from} – ${d.period.to} · ${d.summary.count} блюд с рецептурой (разворот ТТК из продаж общепита) · клик по блюду — карточка`}>
            {d.recipes.length === 0
              ? <div className="text-sm text-muted-foreground">Нет блюд с рецептурой за период (поставьте апрель).</div>
              : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {d.recipes.map((r) => (
                    <div key={r.guid} className="rounded-lg border border-border/50 bg-card/40 p-3">
                      <button onClick={() => setOpenGuid(r.guid)} className="text-sm font-medium mb-1.5 text-left hover:text-primary hover:underline">
                        {r.name} <span className="text-[10px] text-muted-foreground font-normal">· {r.ing_count} ингр.</span>
                      </button>
                      <ul className="text-xs text-muted-foreground space-y-0.5">
                        {r.ingredients.map((ing, i) => (
                          <li key={i} className="flex justify-between gap-2"><span className="truncate">{ing.name}</span><span className="tabular-nums shrink-0">{ing.qty}</span></li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
          </Shell>
        )
      })}
      {openGuid && <NomenclatureCardModal guid={openGuid} companyId={p.companyId} dateFrom={p.dateFrom} dateTo={p.dateTo} onClose={() => setOpenGuid(null)} />}
    </>
  )
}
