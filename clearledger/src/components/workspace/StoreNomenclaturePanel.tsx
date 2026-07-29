/**
 * «Номенклатура» — полный справочник товаров (мастер-НСИ из ЦБ, 7456 карточек),
 * обогащённый продажами и штрихкодами. Фильтры: вид · маркировка · весовой ·
 * с продажами/без · поиск. Данные: /api/store/nomenclature.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreNomenclature, type SalesMarked } from '@/services/storeService'
import { Kpi } from './analytics/Kpi'
import { fmtMoney } from '@/services/analyticsService'
import { NomenclatureCardModal } from './NomenclatureCardModal'
import { ChzBadge } from '@/components/common/ChzBadge'

const nf = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n)

function Seg<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-md border border-border/50 overflow-hidden">
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onChange(t.key)}
          className={`px-2.5 py-1 text-xs transition-colors ${value === t.key ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/40'}`}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

const MARK_TABS: { key: SalesMarked; label: string }[] = [
  { key: 'all', label: 'Все' }, { key: 'marked', label: 'Маркир.' }, { key: 'plain', label: 'Обычные' },
]
const SALES_TABS: { key: 'all' | 'yes' | 'no'; label: string }[] = [
  { key: 'all', label: 'Все' }, { key: 'yes', label: 'С продажами' }, { key: 'no', label: 'Без продаж' },
]
const WEIGH_TABS: { key: 'all' | 'weighed'; label: string }[] = [
  { key: 'all', label: 'Любые' }, { key: 'weighed', label: 'Весовые' },
]

export function StoreNomenclaturePanel({ companyId, dateFrom, dateTo, stations }: { companyId: string; dateFrom: string; dateTo: string; stations?: string[] }) {
  const [kind, setKind] = useState('all')
  const [marked, setMarked] = useState<SalesMarked>('all')
  const [weighed, setWeighed] = useState<'all' | 'weighed'>('all')
  const [hasSales, setHasSales] = useState<'all' | 'yes' | 'no'>('all')
  const [q, setQ] = useState('')
  const [openGuid, setOpenGuid] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-nom', companyId, dateFrom, dateTo, kind, marked, weighed, hasSales, q, stations],
    queryFn: () => getStoreNomenclature(dateFrom, dateTo, { kind, marked, weighed, hasSales, q, stations }),
  })

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold">Номенклатура</h3>
        <p className="text-xs text-muted-foreground">Мастер-НСИ из ЦБ ЭЛСИ.АЗК. Клик по строке — полная карточка товара: паспорт, штрихкоды, цена/остаток, продажи, поставки, движение, ТТК, МРЦ.</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select value={kind} onChange={(e) => setKind(e.target.value)}
          className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background">
          <option value="all">Все виды</option>
          {data?.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <Seg tabs={MARK_TABS} value={marked} onChange={setMarked} />
        <Seg tabs={WEIGH_TABS} value={weighed} onChange={setWeighed} />
        <Seg tabs={SALES_TABS} value={hasSales} onChange={setHasSales} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск по товару/артикулу…"
          className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-52" />
      </div>

      {isLoading && <div className="text-sm text-muted-foreground">Загрузка…</div>}
      {error && <div className="text-sm text-red-400/90">Ошибка загрузки</div>}
      {data && (
        <>
          <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
            <Kpi label="Позиций" value={nf(data.summary.total)} />
            <Kpi label="Маркированных" value={nf(data.summary.marked)} />
            <Kpi label="Весовых" value={nf(data.summary.weighed)} />
            <Kpi label="С продажами" value={nf(data.summary.with_sales)} />
            <Kpi label="Со штрихкодом" value={nf(data.summary.with_barcode)} />
          </div>

          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Товар</th>
                  <th className="px-3 py-2 text-left font-medium">Артикул</th>
                  <th className="px-3 py-2 text-left font-medium">Вид</th>
                  <th className="px-3 py-2 text-left font-medium">НДС</th>
                  <th className="px-3 py-2 text-center font-medium">ШК</th>
                  <th className="px-3 py-2 text-center font-medium">ЧЗ</th>
                  <th className="px-3 py-2 text-right font-medium">Остаток</th>
                  <th className="px-3 py-2 text-right font-medium">Цена</th>
                  <th className="px-3 py-2 text-right font-medium">Выручка</th>
                </tr>
              </thead>
              <tbody>
                {data.items.slice(0, 400).map((i) => (
                  <tr key={i.guid} onClick={() => setOpenGuid(i.guid)}
                    className="border-t border-border/30 hover:bg-accent/20 cursor-pointer">
                    <td className="px-3 py-1.5">{i.name}</td>
                    <td className="px-3 py-1.5">{i.article ?? '—'}</td>
                    <td className="px-3 py-1.5">{i.kind}</td>
                    <td className="px-3 py-1.5">{i.vat ?? '—'}</td>
                    <td className="px-3 py-1.5 text-center">{i.has_barcode ? '✓' : ''}</td>
                    <td className="px-3 py-1.5 text-center">{i.marked && <ChzBadge />}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${i.stock_qty <= 0 ? 'text-muted-foreground/50' : ''}`}>{i.stock_qty ? nf(i.stock_qty) : '—'}{i.unit && i.stock_qty ? <span className="text-muted-foreground/60 ml-0.5 text-[10px]">{i.unit}</span> : ''}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{i.retail_price != null ? fmtMoney(i.retail_price) : '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{i.revenue ? fmtMoney(i.revenue) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.items.length > 400 && (
              <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/30">
                Показано 400 из {data.items.length}. Уточните фильтр/поиск.
              </div>
            )}
            {data.items.length === 0 && (
              <div className="px-3 py-6 text-sm text-muted-foreground text-center">Ничего не найдено по фильтру.</div>
            )}
          </div>
        </>
      )}

      {openGuid && (
        <NomenclatureCardModal guid={openGuid} companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} onClose={() => setOpenGuid(null)} />
      )}
    </div>
  )
}
