/**
 * «Остатки» раздела «Магазин» — собственный журнал движений Edge Agent.
 * Старый срез ЦБ используется только как переходный fallback до первого снимка агента.
 *
 * Остаток — снимок на момент выгрузки (не за период): фильтр периода не применяется.
 * Отрицательные остатки — норма для розничных АЗС (учёт по средней) → флаг.
 */
import { useEffect, useMemo, useState } from 'react'
import { rowDrill } from './rowDrill'
import { SkuDetailModal } from './SkuDetailModal'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { PivotView } from './PivotView'
import {
  getStoreStock, getStorePivot, getStorePivotCatalog, type StoreStockItem,
} from '@/services/storeService'
import { getDemoStoreStock } from '@/services/storeDemoService'
import { fmtMoney } from '@/services/analyticsService'
import { ChzBadge } from '@/components/common/ChzBadge'
import { SnapshotBadge } from '@/components/common/SnapshotBadge'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

type MarkedFilter = 'all' | 'marked' | 'plain'

export function StoreStockPanel({ companyId, dateFrom, dateTo, stations, demo = false }: {
  companyId: string; dateFrom?: string; dateTo?: string; stations?: string[]; demo?: boolean
}) {
  // Строка = товар: раскрывается его карточка (та же, что в «Ассортименте»).
  const [openSku, setOpenSku] = useState<string | null>(null)
  const [warehouse, setWarehouse] = useState<string | undefined>(undefined)
  const [q, setQ] = useState('')
  const [marked, setMarked] = useState<MarkedFilter>('all')
  const [onlyNegative, setOnlyNegative] = useState(false)
  // Список и сводная — две подачи одного отбора, как в «Топливе»: там разрез
  // собирают мышью, и здесь он собирается тем же конструктором, а не своим.
  const [подача, задатьПодачу] = useState<'list' | 'pivot'>('list')
  const [выгружается, задатьВыгрузку] = useState(false)
  const stationKey = stations?.join(',') ?? ''

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-stock', demo ? 'demo' : 'live', companyId, warehouse ?? '', stationKey],
    queryFn: () => demo
      ? getDemoStoreStock({ warehouse, stations })
      : getStoreStock({ warehouse, stations }),
  })

  useEffect(() => { setWarehouse(undefined) }, [stationKey])

  const items = useMemo(() => {
    if (!data) return [] as StoreStockItem[]
    const ql = q.toLowerCase().trim()
    const rows = data.items.filter((i) => {
      if (marked === 'marked' && !i.marked) return false
      if (marked === 'plain' && i.marked) return false
      if (onlyNegative && !i.negative) return false
      if (ql && !(i.name.toLowerCase().includes(ql) || (i.barcode ?? '').includes(q) || (i.article ?? '').includes(q))) return false
      return true
    })
    // Список отсортирован по розничной стоимости убыв., поэтому в режиме «только в минусе»
    // сверху оказывались нули, а сами глубокие минусы — в хвосте. Разворачиваем.
    return onlyNegative ? [...rows].sort((a, b) => (a.retail_value ?? 0) - (b.retail_value ?? 0)) : rows
  }, [data, q, marked, onlyNegative])
  const показ = useVisible(items)

  const выгрузить = async () => {
    задатьВыгрузку(true)
    try {
      const { exportStockBook } = await import('@/services/stockExport')
      await exportStockBook({
        items,
        scopeLabel: warehouse ? `место ${warehouse}` : 'вся сеть',
        snapshotAt: data?.snapshot_at ?? null,
        summary: data?.summary,
      })
    } catch (e) {
      toast.error('Не удалось собрать книгу', { description: (e as Error).message })
    } finally {
      задатьВыгрузку(false)
    }
  }

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка остатков…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки остатков. <button type="button" className="underline" onClick={() => refetch()}>Повторить</button></div>
  if (!data) return null

  // KPI по отфильтрованному набору (что на экране)
  const kpiRetailPos = items.reduce((s, i) => s + (i.qty > 0 ? (i.retail_value ?? 0) : 0), 0)
  const kpiPos = items.filter((i) => i.qty > 0).length
  const kpiNeg = items.filter((i) => i.negative).length
  // Сомнительная себестоимость (партия выше цены или разошлась с закупкой) в сводку не
  // идёт: иначе «потенц. маржа» считается по цифрам, которым сама панель не верит.
  const onShelf = items.filter((i) => i.qty > 0)
  const costed = onShelf.filter((i) => i.cost_amount != null && !i.cost_doubt)
  const doubt = onShelf.filter((i) => i.cost_amount != null && i.cost_doubt)
  const noCost = onShelf.length - costed.length - doubt.length
  const kpiCost = costed.reduce((s, i) => s + (i.cost_amount ?? 0), 0)
  const kpiRetailCosted = costed.reduce((s, i) => s + (i.retail_value ?? 0), 0)
  const kpiMarginPct = kpiRetailCosted ? ((kpiRetailCosted - kpiCost) / kpiRetailCosted) * 100 : null
  const curWh = data.warehouses.find((w) => w.code === data.warehouse)
  const scopeStationIds = (stations ?? []).map(Number).filter(Number.isFinite)
  // В сводном разрезе один и тот же товар встречается несколько раз — по разу
  // на каждую полку, поэтому колонка «где лежит» появляется только здесь.
  const всяСеть = !curWh

  const KPIS: { label: string; value: string; hint?: string; danger?: boolean }[] = [
    { label: 'Позиций (SKU)', value: nf(items.length) },
    { label: 'На полке (>0)', value: nf(kpiPos), hint: 'положительный остаток' },
    { label: 'В минусе', value: nf(kpiNeg), danger: kpiNeg > 0, hint: 'расход без прихода в контуре' },
    { label: 'Розн. стоимость', value: fmtMoney(kpiRetailPos), hint: `${nf(kpiPos)} позиций на полке × цена` },
    {
      label: 'Себест. остатка', value: fmtMoney(kpiCost),
      hint: `${nf(costed.length)} SKU из ${nf(onShelf.length)}${doubt.length ? ` · ${nf(doubt.length)} спорных не в счёт` : ''}${noCost ? ` · ${nf(noCost)} без партий` : ''}`,
    },
    {
      label: 'Потенц. маржа', value: kpiMarginPct == null ? '—' : `${nf(kpiMarginPct, 1)}%`,
      hint: `от розницы ${fmtMoney(kpiRetailCosted)} тех же ${nf(costed.length)} SKU`,
    },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">Остатки</h3>
            <SnapshotBadge at={data.snapshot_at} />
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data.source === 'edge_agent'
              ? 'Собственный остаток агента АЗС: стартовый перенос + документы и продажи станции.'
              : 'Нет собственного снимка агента: рабочий остаток станции ещё не получен.'}
            {' '}Не за период — текущее состояние.
            {curWh
              ? <> Место: <span className="text-foreground">{curWh.name}</span> (АЗС {curWh.station_id}).</>
              : <> Показана <span className="text-foreground">вся сеть</span>: у каждой строки видно, чья это полка.</>}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Книга для сверки: сводка, лист проблемных и позиции с пустой
              колонкой ФАКТ. Выгружается ТЕКУЩИЙ отбор — то, что человек видит,
              иначе файл спорит с экраном. */}
          <button type="button" disabled={demo || выгружается || !items.length}
            onClick={выгрузить}
            title={demo ? 'Демонстрационные данные — выгрузка отключена' : 'Книга Excel: сводка, лист «Требуют решения» и остатки с колонкой ФАКТ — для сверки и подготовки пересчёта'}
            className="rounded-md border border-border/50 px-2.5 py-1.5 text-xs font-medium hover:bg-accent/40 disabled:opacity-50">
            {выгружается ? 'Собираю…' : 'Выгрузить в Excel'}
          </button>
          <div className="inline-flex rounded-md bg-muted p-[3px]">
            {(['list', 'pivot'] as const).map((v) => (
              <button key={v} type="button" disabled={demo && v === 'pivot'} onClick={() => задатьПодачу(v)}
                title={demo && v === 'pivot' ? 'Сводная доступна в рабочем контуре' : undefined}
                className={`rounded-[5px] px-2.5 py-1 text-xs font-medium transition-colors ${
                  подача === v ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'} disabled:cursor-not-allowed disabled:opacity-40`}>
                {v === 'list' ? 'Список' : 'Сводная'}
              </button>
            ))}
          </div>
          <select
            value={warehouse ?? data.warehouse ?? ''}
            onChange={(e) => setWarehouse(e.target.value || undefined)}
            className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background"
          >
            {/* Вся сеть — первый пункт: вопрос «где вообще лежит этот товар»
                задают чаще, чем «что на конкретной полке», и он не должен
                требовать перебора станций. */}
            <option value="all">{scopeStationIds.length ? 'Выбранные станции — все места' : 'Вся сеть — все станции и места'}</option>
            {data.warehouses.map((w) => (
              <option key={w.code} value={w.code}>{w.name ?? w.code} — на полке {w.positive} из {w.sku}</option>
            ))}
          </select>
          <select
            value={marked} onChange={(e) => setMarked(e.target.value as MarkedFilter)}
            className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background"
          >
            <option value="all">Все товары</option>
            <option value="marked">Маркированные</option>
            <option value="plain">Обычные</option>
          </select>
          <label className="text-xs flex items-center gap-1.5 text-muted-foreground">
            <input type="checkbox" checked={onlyNegative} onChange={(e) => setOnlyNegative(e.target.checked)} />
            только «в минусе»
          </label>
          <input
            value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара / ШК…"
            className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-52"
          />
        </div>
      </div>

      {(data.stations?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-2">
          {data.stations!.map((st) => (
            <button key={st.station_id} type="button"
              onClick={() => setWarehouse(`${st.station_id}:${data.warehouses.find((w) => w.station_id === st.station_id)?.place_code ?? ''}`)}
              className="rounded-lg border border-border/50 bg-card/40 px-3 py-2 text-left transition-colors hover:border-primary/50">
              <div className="text-xs font-medium">АЗС {st.station_id}</div>
              <div className="text-[11px] text-muted-foreground">
                {nf(st.positive)} на полке из {nf(st.sku)} · {st.places} мест{st.negative > 0
                  ? <> · <span className="text-amber-300/90">{nf(st.negative)} в минусе</span></> : ''}
              </div>
              <div className="text-[11px] tabular-nums text-muted-foreground">
                {fmtMoney(st.retail_value)} · снимок {st.snapshot_at
                  ? new Date(st.snapshot_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
                  : '—'}
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.danger ? 'text-red-400/90' : ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{k.hint}</div>}
          </div>
        ))}
      </div>

      <p className="text-[11px] text-muted-foreground/70 -mt-1">
        Остаток — в базовой единице регистра (молоко в мл, соусы в г), она указана рядом с числом.
        {data.source === 'edge_agent'
          ? 'Себестоимость — средняя по собственным приёмкам агента; неполное покрытие стартового остатка помечено «?». '
          : 'Себестоимость — переходная оценка из партий ЦБ; сомнительные значения помечены «?». '}
        <span className="text-muted-foreground">Минус по остатку</span> — расход прошёл, а
        приход в этом контуре не оформлен: так ведут себя расходники общепита (стаканы, соусы,
        упаковка) и товар, чьи накладные заводятся вне контура. Это не долг по приёмке.
      </p>

      {подача === 'pivot' ? (
        <PivotView
          source="store_stock"
          storageKey="store-stock-pivot"
          defaultDims={['station', 'place']}
          fetchCatalog={getStorePivotCatalog}
          fetchLeaves={(dims) => getStorePivot({
            source: 'store_stock', dims,
            stations: curWh?.station_id ? [curWh.station_id] : (scopeStationIds.length ? scopeStationIds : undefined),
          })}
          queryKey={[warehouse ?? '', marked, onlyNegative, stationKey]}
          dateFrom={dateFrom ?? ''}
          dateTo={dateTo ?? ''}
          scopeLabel={curWh ? `АЗС ${curWh.station_id}` : (scopeStationIds.length ? 'выбранные станции' : 'вся сеть')}
          hint="Остаток — срез на момент снимка станции, а не за период: датами он не фильтруется."
        />
      ) : (
      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left">Товар</th>
              {всяСеть && <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Где лежит</th>}
              <th className="px-3 py-2 font-medium text-center">ЧЗ</th>
              <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Штрихкод</th>
              <th className="px-3 py-2 font-medium text-right">Остаток</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Розн. цена</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Себест/ед</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Маржа %</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Розн. стоимость</th>
              <th className="px-3 py-2 font-medium text-left">НДС</th>
            </tr>
          </thead>
          <tbody>
            {показ.visible.map((i) => (
              <tr key={`${i.station_id ?? ''}:${i.place_code ?? ''}:${i.guid}`}
                  {...rowDrill(() => setOpenSku(i.guid), `${i.name} — карточка товара`,
                    'border-t border-border/30')}>
                <td className="px-3 py-1.5">
                  {i.name}
                  {i.weighed && <span className="ml-1 text-[10px] text-muted-foreground/60" title="весовой — остаток в базовых единицах">вес.</span>}
                </td>
                {всяСеть && (
                  <td className="px-3 py-1.5 whitespace-nowrap text-muted-foreground">
                    {i.station_id ? `АЗС ${i.station_id}` : '—'}
                    {i.place_name && <span className="ml-1 text-[11px] text-muted-foreground/70">{i.place_name.replace(/^АЗС\s*№?\d+,\s*/, '')}</span>}
                  </td>
                )}
                <td className="px-3 py-1.5 text-center">{i.marked && <ChzBadge />}</td>
                <td className="px-3 py-1.5 text-muted-foreground tabular-nums">{i.barcode ?? '—'}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${i.negative ? 'text-red-400/80 font-medium' : ''}`}>
                  {nf(i.qty, 3)}
                  {i.unit && <span className="ml-1 text-[10px] text-muted-foreground/60">{i.unit}</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{i.retail_price != null ? fmtMoney(i.retail_price) : '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {i.cost_unit != null ? nf(i.cost_unit, 2) : '—'}
                  {i.cost_doubt && (
                    <span className="ml-1 text-amber-400/80" title={`себестоимость партии ${i.cost_doubt} — в сводную маржу не входит`}>?</span>
                  )}
                </td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${i.cost_doubt ? 'text-muted-foreground/50' : i.margin_pct == null ? '' : i.margin_pct < 0 ? 'text-red-400/80' : 'text-emerald-300/70'}`}
                  title={i.cost_doubt ? `цифра ненадёжна: ${i.cost_doubt}` : undefined}>
                  {i.margin_pct != null ? `${nf(i.margin_pct, 1)}%` : '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{i.retail_value != null ? fmtMoney(i.retail_value) : '—'}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{i.vat ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="позиций" />
        {items.length === 0 && (
          <div className="px-3 py-6 text-sm text-muted-foreground text-center">
            Нет позиций. Проверьте стартовый остаток и время последнего снимка агента.
          </div>
        )}
      </div>
      )}
      {openSku && (
        <SkuDetailModal guid={openSku} dateFrom={dateFrom ?? ''} dateTo={dateTo ?? ''} stations={stations} demo={demo}
          onClose={() => setOpenSku(null)} />
      )}
    </div>
  )
}
