/**
 * «Продажи» — операционный инструмент менеджера: анализ продаж сопутки/общепита
 * по любому срезу. НЕ дублирует «Аналитику» (Обзор/Ассортимент/Цены-маржа) —
 * здесь гибкая группировка + фильтры + НДС-разрез (сверка с учётной политикой).
 *
 * Группировки: по товарам · категориям · видам номенклатуры · Честному Знаку ·
 * ставке НДС · дням · оплатам. Фильтры: Сопутка/Общепит/Вместе · Все/Маркир./Обычные · поиск.
 * Данные: /api/store/sales (GoodsDashboardService.sales_analysis).
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { Kpi } from './analytics/Kpi'
import { seriesColor } from './analytics/palette'
import { ExportButton } from './analytics/ExportButton'
import { useScopeSubtitle } from '@/hooks/useScopeReset'
import { rowDrill } from './rowDrill'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { SkuDetailModal } from './SkuDetailModal'
import { ShiftDetailModal } from './ShiftDetailModal'
import {
  getStoreSales, getStoreVisits, type SalesGroupBy, type SalesCategory, type SalesMarked,
} from '@/services/storeService'
import { fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

const GROUP_TABS: { key: SalesGroupBy; label: string }[] = [
  { key: 'sku', label: 'По товарам' },
  { key: 'category', label: 'Категории' },
  { key: 'kind', label: 'Виды' },
  { key: 'marking', label: 'Честный Знак' },
  { key: 'vat', label: 'Ставка НДС' },
  { key: 'day', label: 'По дням' },
  { key: 'shift', label: 'По сменам' },
  { key: 'payment', label: 'Оплаты' },
]
const CAT_TABS: { key: SalesCategory; label: string }[] = [
  { key: 'all', label: 'Вместе' }, { key: 'soputka', label: 'Сопутка' }, { key: 'obshepit', label: 'Общепит' },
]
const MARK_TABS: { key: SalesMarked; label: string }[] = [
  { key: 'all', label: 'Все' }, { key: 'marked', label: 'Маркир.' }, { key: 'plain', label: 'Обычные' },
]

function Seg<T extends string>({ tabs, value, onChange, disabled = false }: {
  tabs: { key: T; label: string }[]; value: T; onChange: (v: T) => void; disabled?: boolean
}) {
  return (
    <div className="inline-flex rounded-md border border-border/50 overflow-hidden">
      {tabs.map((t) => (
        <button key={t.key} type="button" disabled={disabled} onClick={() => onChange(t.key)}
          className={`px-2.5 py-1 text-xs transition-colors ${value === t.key ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/40'}`}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function StoreSalesPanel({ companyId, dateFrom, dateTo, stations }: { companyId: string; dateFrom: string; dateTo: string; stations?: string[] }) {
  const [groupBy, setGroupBy] = useState<SalesGroupBy>('sku')
  const [category, setCategory] = useState<SalesCategory>('all')
  const [marked, setMarked] = useState<SalesMarked>('all')
  const [q, setQ] = useState('')
  // Что раскрыто по клику: товар (GUID номенклатуры) или смена (ключ смены).
  // Ключ приходит в `g.key` от сервера и годится обеим ручкам как есть.
  const [openSku, setOpenSku] = useState<string | null>(null)
  const [openShift, setOpenShift] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const scopeSub = useScopeSubtitle()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-sales', companyId, dateFrom, dateTo, groupBy, category, marked, q, stations],
    queryFn: () => getStoreSales(dateFrom, dateTo, { groupBy, category, marked, q, stations }),
  })
  const { data: поток } = useQuery({
    queryKey: ['store-visits', companyId, dateFrom, dateTo, stations],
    queryFn: () => getStoreVisits(dateFrom, dateTo, stations),
  })

  const isPayment = groupBy === 'payment'
  const showSkuCol = groupBy !== 'sku' && !isPayment
  const показ = useVisible(data?.groups ?? [])

  return (
    <div ref={ref} className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Продажи</h3>
          <p className="text-xs text-muted-foreground">
            Крутите продажи сопутки/общепита по любой группировке. НДС-разрез — для сверки с учётной политикой.
          </p>
        </div>
        <ExportButton title="Продажи магазина" subtitle={scopeSub} getEl={() => ref.current} />
      </div>

      {/* группировки */}
      <Seg tabs={GROUP_TABS} value={groupBy} onChange={setGroupBy} />

      {/* фильтры (оплаты — по чекам, товарные фильтры к ним не применяются) */}
      <div className={`flex flex-wrap items-center gap-3 ${isPayment ? 'opacity-50' : ''}`} aria-disabled={isPayment}>
        <Seg tabs={CAT_TABS} value={category} onChange={setCategory} disabled={isPayment} />
        <Seg tabs={MARK_TABS} value={marked} onChange={setMarked} disabled={isPayment} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара…"
          disabled={isPayment} aria-label="Поиск товара"
          className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-48 disabled:cursor-not-allowed" />
      </div>
      {/* Бэкенд вернул фильтры, которые к этому разрезу неприменимы — цифры по всей точке. */}
      {!!data?.filters_ignored?.length && (
        <div className="text-[11px] text-amber-300/80">
          В разрезе «{GROUP_TABS.find((t) => t.key === groupBy)?.label}» не применены товарные фильтры
          ({data.filters_ignored.join(', ')}) — цифры по всем продажам периода.
        </div>
      )}

      {isLoading && <div className="text-sm text-muted-foreground">Загрузка…</div>}
      {error && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-red-400/30 bg-red-400/5 px-3 py-2 text-sm text-red-300/90">
          Продажи не загрузились. Проверьте связь с сервером.
          <button type="button" onClick={() => refetch()} className="underline underline-offset-2">Повторить</button>
        </div>
      )}
      {data && (
        <>
          <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Выручка" value={fmtMoney(data.summary.revenue)} sub="с НДС" />
            <Kpi label="Без НДС" value={fmtMoney(data.summary.revenue_net)} />
            <Kpi label="НДС" value={fmtMoney(data.summary.vat)} />
            <Kpi label="Продано ед." value={nf(data.summary.qty)} />
            <Kpi label="SKU" value={nf(data.summary.sku_count)} />
            <Kpi label="Групп" value={nf(data.summary.groups_count)} />
          </div>

          {поток && поток.visits > 0 && (
            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi label="Посещений" value={nf(поток.visits)}
                sub={`${nf(поток.fuel_ops)} заправок · ${nf(поток.shop_cheques)} чеков магазина`} />
              <Kpi label="Конверсия магазина" value={`${поток.conversion.toFixed(1)}%`}
                sub={поток.conversion > 0
                  ? `покупает каждый ${Math.round(100 / поток.conversion)}-й`
                  : 'магазин не продаёт'} />
              <Kpi label="На посетителя" value={fmtMoney(поток.per_visit)}
                sub={`средний чек ${fmtMoney(поток.avg_cheque)}`} />
              <Kpi label="Уехали без покупки" value={nf(поток.fuel_only)}
                sub="потенциал сопутки" />
            </div>
          )}

          {groupBy === 'day' && (
            <div className="rounded-lg border border-border/50 bg-card/40 p-4">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={data.groups.map((g) => ({ date: g.label, revenue: g.revenue }))} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.12} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => fmtMoneyShort(v)} width={52} />
                  <Tooltip {...rechartsTooltipTheme} formatter={(value) => fmtMoney(Number(value))}
                    contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="revenue" fill={seriesColor(0, 2)} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{GROUP_TABS.find((t) => t.key === groupBy)?.label}</th>
                  <th className="px-3 py-2 text-right font-medium">Выручка</th>
                  <th className="px-3 py-2 text-left font-medium w-44">Доля</th>
                  <th className="px-3 py-2 text-right font-medium">Без НДС</th>
                  <th className="px-3 py-2 text-right font-medium">НДС</th>
                  {!isPayment && <th className="px-3 py-2 text-right font-medium">Продано</th>}
                  {showSkuCol && <th className="px-3 py-2 text-right font-medium">SKU</th>}
                </tr>
              </thead>
              <tbody>
                {показ.visible.map((g, i) => (
                  <tr key={g.key}
                      {...rowDrill(
                        groupBy === 'sku' ? () => setOpenSku(g.key)
                        : groupBy === 'shift' ? () => setOpenShift(g.key)
                        : null,
                        `${g.label} — раскрыть`,
                        'border-t border-border/30',
                      )}>
                    <td className="px-3 py-1.5">{g.label}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(g.revenue)}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <div className="h-1.5 rounded-full bg-muted/40 flex-1 overflow-hidden">
                          <div className="h-full rounded-full" style={{ width: `${Math.min(g.share, 100)}%`, background: seriesColor(Math.min(i, 5), 6) }} />
                        </div>
                        <span className="tabular-nums text-muted-foreground w-10 text-right">{g.share}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(g.revenue_net)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(g.vat)}</td>
                    {!isPayment && <td className="px-3 py-1.5 text-right tabular-nums">{nf(g.qty)}</td>}
                    {showSkuCol && <td className="px-3 py-1.5 text-right tabular-nums">{nf(g.sku_count)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
            <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="групп" />
            {data.groups.length === 0 && (
              <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет продаж по выбранному периоду и фильтрам.</div>
            )}
          </div>
        </>
      )}
      {/* Расшифровка строки: товар и смена — единственные группировки, за которыми стоит
          сущность; у остальных строка агрегатная и по клику не раскрывается. */}
      {openSku && (
        <SkuDetailModal guid={openSku} dateFrom={dateFrom} dateTo={dateTo} stations={stations}
          onClose={() => setOpenSku(null)} />
      )}
      {openShift && (
        <ShiftDetailModal shiftKey={openShift} companyId={companyId}
          onClose={() => setOpenShift(null)} />
      )}
    </div>
  )
}
