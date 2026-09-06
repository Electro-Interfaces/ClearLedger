/**
 * «Номенклатура» — полный справочник товаров (мастер-НСИ из ЦБ, 7456 карточек),
 * обогащённый продажами и штрихкодами. Фильтры: вид · маркировка · весовой ·
 * с продажами/без · поиск. Данные: /api/store/nomenclature.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
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
  const [станцияПрименения, задатьСтанциюПрименения] = useState('all')

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-nom', companyId, dateFrom, dateTo, kind, marked, weighed, hasSales, q, stations],
    queryFn: () => getStoreNomenclature(dateFrom, dateTo, { kind, marked, weighed, hasSales, q, stations }),
  })

  // Список показывается порциями: обрезать его молча нельзя — товаровед
  // приходит смотреть весь справочник, а не первые строки по чужой сортировке.
  // Какие АЗС вообще встречаются в справочнике — из них и собирается
  // переключатель. Зашивать номера нельзя: станция появляется без нашего
  // участия, и на третьей АЗС список должен вырасти сам.
  const станцииСписком = useMemo(() => {
    const набор = new Set<string>()
    for (const i of data?.items ?? []) {
      for (const с of (i.stations_list ?? '').split(',')) {
        const код = с.trim()
        if (код) набор.add(код)
      }
    }
    return [...набор].sort((a, b) => Number(a) - Number(b))
  }, [data?.items])

  const строки = useMemo(() => {
    const все = data?.items ?? []
    if (станцияПрименения === 'all') return все
    return все.filter((i) => (i.stations_list ?? '')
      .split(',').map((с) => с.trim()).includes(станцияПрименения))
  }, [data?.items, станцияПрименения])

  const показ = useVisible(строки)

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold">Номенклатура</h3>
        <p className="text-xs text-muted-foreground">Сетевой справочник: карточка заводится один раз на сеть, условия станций описаны правилами к ней. Клик по строке — полная карточка: паспорт, штрихкоды и ярусы, условия каждой АЗС, продажи, поставки, движение, ТТК, МРЦ.</p>
        {/* В каком разрезе читаются цифры.
            Остаток, цена и выручка считаются по выбранной области учёта, а
            выбирается она наверху, в шапке рабочего стола. Пока экран об этом
            молчал, сетевые итоги и цифры одной АЗС выглядели одинаково — и
            «почему остаток не тот» становилось вопросом к данным, а не к
            фильтру. */}
        <p className="mt-1 text-xs">
          <span className="text-muted-foreground">Разрез: </span>
          <span className="font-medium">
            {stations && stations.length ? `АЗС ${stations.join(', ')}` : 'вся сеть'}
          </span>
          <span className="text-muted-foreground">
            {' '}— остаток, цена и выручка показаны по нему. Меняется в шапке, «Область учёта».
          </span>
        </p>
      </div>

      {/* Поиск стоит ПЕРВЫМ и во всю ширину: справочник на полторы тысячи
          позиций смотрят не листая, а ища. Раньше поле пряталось последним в
          ряду фильтров и выглядело таким же второстепенным, как «весовые». */}
      <div className="flex flex-wrap items-center gap-3">
        <input value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="найти: название, артикул или штрихкод — можно сканером"
          className="text-xs px-2.5 py-2 rounded-md border border-border/50 bg-background w-full sm:w-96" />
        {q && (
          <button type="button" onClick={() => setQ('')}
            className="text-xs text-muted-foreground hover:text-foreground underline">сбросить</button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {/* Быстрый разрез «где применяется». Он про КАРТОЧКУ (на каких АЗС у неё
            есть цена), а не про цифры: остаток и выручка считаются по области
            учёта из шапки — об этом сказано строкой выше. Смешивать их в одном
            переключателе нельзя, иначе человек решит, что сузил всё сразу. */}
        {станцииСписком.length > 1 && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Применяется на:</span>
            <Seg
              tabs={[{ key: 'all', label: 'любой' },
                     ...станцииСписком.map((s) => ({ key: s, label: `АЗС ${s}` }))]}
              value={станцияПрименения}
              onChange={(v) => задатьСтанциюПрименения(v as string)}
            />
          </div>
        )}
        <select value={kind} onChange={(e) => setKind(e.target.value)}
          className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background">
          <option value="all">Все виды</option>
          {data?.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <Seg tabs={MARK_TABS} value={marked} onChange={setMarked} />
        <Seg tabs={WEIGH_TABS} value={weighed} onChange={setWeighed} />
        <Seg tabs={SALES_TABS} value={hasSales} onChange={setHasSales} />
      </div>

      {isLoading && <div className="text-sm text-muted-foreground">Загрузка…</div>}
      {error && <div className="text-sm text-red-400/90">Ошибка загрузки</div>}
      {data && (
        <>
          <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
            <Kpi label={строки.length === data.summary.total ? 'Позиций' : 'Найдено'}
                 value={nf(строки.length)} />
            <Kpi label="Маркированных" value={nf(data.summary.marked)} />
            <Kpi label="Применяется на АЗС" value={nf(data.summary.on_stations ?? 0)} />
            <Kpi label="С продажами" value={nf(data.summary.with_sales)} />
            <Kpi label="Со штрихкодом" value={nf(data.summary.with_barcode)} />
          </div>

          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Товар</th>
                  <th className="px-3 py-2 text-left font-medium">Артикул</th>
                  <th className="px-3 py-2 text-left font-medium">Класс</th>
                  <th className="px-3 py-2 text-center font-medium" title="АЗС, где у позиции есть действующая цена — то есть где она применяется">На АЗС</th>
                  <th className="px-3 py-2 text-left font-medium">НДС</th>
                  <th className="px-3 py-2 text-center font-medium">ШК</th>
                  <th className="px-3 py-2 text-center font-medium">ЧЗ</th>
                  <th className="px-3 py-2 text-right font-medium">Остаток</th>
                  <th className="px-3 py-2 text-right font-medium">Цена</th>
                  <th className="px-3 py-2 text-right font-medium">Выручка</th>
                </tr>
              </thead>
              <tbody>
                {показ.visible.map((i) => (
                  <tr key={i.guid} onClick={() => setOpenGuid(i.guid)}
                    className="border-t border-border/30 hover:bg-accent/20 cursor-pointer">
                    <td className="px-3 py-1.5">{i.name}</td>
                    <td className="px-3 py-1.5">{i.article ?? '—'}</td>
                    <td className="px-3 py-1.5">{i.kind}</td>
                    {/* Номера станций, а не просто их количество. «2» у сети из
                        двух АЗС и «1» рядом читаются одинаково, а вопрос у
                        товароведа другой: где позиция есть, а где её нет. */}
                    <td className="px-3 py-1.5 text-center tabular-nums"
                        title={i.stations_list
                          ? `Позиция применяется на АЗС: ${i.stations_list}`
                          : 'Ни одна станция не применяет эту позицию — кандидат в архив'}>
                      {i.stations_list
                        ? <span className="text-[11px]">{i.stations_list}</span>
                        : <span className="text-muted-foreground/60">—</span>}
                    </td>
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
            <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="позиций" />
            {data.items.length === 0 && (
              <div className="px-3 py-6 text-sm text-muted-foreground text-center">Ничего не найдено по фильтру.</div>
            )}
          </div>
        </>
      )}

      {openGuid && (
        <NomenclatureCardModal guid={openGuid} companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} stations={stations} onClose={() => setOpenGuid(null)} />
      )}
    </div>
  )
}
