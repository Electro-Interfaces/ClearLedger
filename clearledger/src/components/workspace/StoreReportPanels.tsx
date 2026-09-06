/**
 * Отчётные панели раздела «Магазин»: Приёмка / Поставщики / Общепит / Категории.
 * Данные: /api/store/{receipts|suppliers|catering|categories} (GoodsDashboardService).
 * Имена поставщиков — из кеша CbRef, блюда/товары — CbNomenclature.
 */
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  getStoreReport, getStoreBarcodes,
  type StoreReceiptsData, type StoreSuppliersData,
  type StoreCategoriesData,
  type StoreRecipesData,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { useResetOnScopeChange } from '@/hooks/useScopeReset'
import { SupplierCardModal } from './SupplierCardModal'
import { NomenclatureCardModal } from './NomenclatureCardModal'
import { DocsModal } from './DocsModal'
import { rowDrill } from './rowDrill'
import { ShowMore, useVisible } from '@/components/common/ShowMore'

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

function Table({ head, rows, onRowClick, rowLabel }: {
  head: { label: string; num?: boolean }[]; rows: ReactNode[][]
  /** Расшифровка строки задаётся здесь, а не копией таблицы в каждой панели: одна
   *  правка открывает Приёмку, Поставщиков, Категории и Штрихкоды сразу. */
  onRowClick?: (i: number) => void; rowLabel?: (i: number) => string
}) {
  const показ = useVisible(rows)
  return (
    <div className="overflow-x-auto rounded-lg border border-border/50">
      <table className="w-full text-xs">
        <thead className="bg-muted/30 text-muted-foreground">
          <tr>{head.map((h, i) => <th key={i} className={`px-3 py-2 font-medium whitespace-nowrap ${h.num ? 'text-right' : 'text-left'}`}>{h.label}</th>)}</tr>
        </thead>
        <tbody>
          {показ.visible.map((r, ri) => (
            <tr key={ri}
              {...(onRowClick
                ? rowDrill(() => onRowClick(ri), rowLabel?.(ri), 'border-t border-border/30')
                : { className: 'border-t border-border/30 hover:bg-accent/20' })}>
              {r.map((cell, ci) => <td key={ci} className={`px-3 py-1.5 ${head[ci]?.num ? 'text-right tabular-nums' : ''}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 300 && <ShowMore {...показ} onMore={показ.more} onAll={показ.all} />}
      {rows.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет данных за выбранный период.</div>}
    </div>
  )
}

const wrap = (q: { isLoading: boolean; error: unknown }, render: () => ReactNode): ReactNode => {
  if (q.isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  if (q.error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки</div>
  return render()
}

export function StoreReceiptsPanel(p: PanelProps) {
  const q = useReport<StoreReceiptsData>('receipts-report', p)
  const [open, setOpen] = useState<number | null>(null)
  const [sku, setSku] = useState<string | null>(null)
  return wrap(q, () => {
    const d = q.data!
    const doc = open != null ? d.docs[open] : null
    return (
      <Shell title="Приёмка (поступления)"
        sub={`${d.period.from} – ${d.period.to} · ${d.summary.count} документов · закупки нетто ${fmtMoney(d.summary.amount_net)} · НДС ${fmtMoney(d.summary.vat)} · клик по строке — состав накладной`}>
        <Table
          head={[{ label: 'Дата' }, { label: 'Смена' }, { label: 'Номер' }, { label: 'Поставщик' }, { label: 'Завёл' }, { label: 'Позиций', num: true }, { label: 'Сумма (нетто)', num: true }, { label: 'НДС', num: true }]}
          rows={d.docs.map((r) => [r.date, r.shift_number ?? '—', r.number, r.supplier, r.author ?? '—', nf(r.positions), fmtMoney(r.amount_net), fmtMoney(r.vat)])}
          onRowClick={(i) => setOpen(i)}
          rowLabel={(i) => `накладная ${d.docs[i].number} от ${d.docs[i].supplier}`}
        />
        {doc && (
          <DocsModal
            title={`Накладная ${doc.number ?? '—'}`}
            subtitle={`${doc.date} · ${doc.supplier} · ${nf(doc.positions)} позиций · нетто ${fmtMoney(doc.amount_net)}`}
            docs={[{ number: doc.number, lines: doc.lines ?? [], meta: doc.supplier }]}
            onOpenSku={setSku} onClose={() => setOpen(null)}
          />
        )}
        {sku && <NomenclatureCardModal guid={sku} companyId={p.companyId} dateFrom={p.dateFrom} dateTo={p.dateTo} stations={p.stations} onClose={() => setSku(null)} />}
      </Shell>
    )
  })
}

export function StoreSuppliersPanel(p: PanelProps) {
  const q = useReport<StoreSuppliersData>('suppliers', p)
  const [open, setOpen] = useState<string | null>(null)
  const [sku, setSku] = useState<string | null>(null)
  return wrap(q, () => {
    const d = q.data!
    return (
      <Shell title="Поставщики"
        sub={`${d.period.from} – ${d.period.to} · ${d.summary.count} поставщиков · закупки нетто ${fmtMoney(d.summary.amount_net)} · клик по строке — карточка поставщика`}>
        <Table
          head={[{ label: 'Поставщик' }, { label: 'Закупки (нетто)', num: true }, { label: 'Документов', num: true }, { label: 'SKU', num: true }]}
          rows={d.suppliers.map((r) => [r.name, fmtMoney(r.amount_net), nf(r.docs), nf(r.sku_count)])}
          onRowClick={(i) => setOpen(d.suppliers[i].name)}
          rowLabel={(i) => `карточка поставщика ${d.suppliers[i].name}`}
        />
        {open && (
          <SupplierCardModal
            name={open} companyId={p.companyId}
            dateFrom={p.dateFrom} dateTo={p.dateTo} stations={p.stations}
            onOpenSku={setSku} onClose={() => setOpen(null)}
          />
        )}
        {sku && <NomenclatureCardModal guid={sku} companyId={p.companyId} dateFrom={p.dateFrom} dateTo={p.dateTo} stations={p.stations} onClose={() => setSku(null)} />}
      </Shell>
    )
  })
}

export function StoreCategoriesPanel(p: PanelProps) {
  const q = useReport<StoreCategoriesData>('categories', p)
  // «Сопутка» и «Общепит» — это вид учёта, и на них экран заканчивался: две
  // строки на весь каталог. Работают же с товарными группами, и вопрос
  // товароведа там: какая группа кормит, а какая лежит. Классы оставлены
  // отдельной подачей — по ним считают выручку в бухгалтерии.
  const [разрез, задатьРазрез] = useState<'groups' | 'classes'>('groups')
  const [поиск, задатьПоиск] = useState('')
  return wrap(q, () => {
    const d = q.data!
    const строкаПоиска = поиск.trim().toLowerCase()
    const группы = (d.groups ?? []).filter((г) =>
      !строкаПоиска || (г.path || '').toLowerCase().includes(строкаПоиска))
    return (
      <Shell title="Товарные группы"
        sub={`${d.period.from} – ${d.period.to} · групп ${d.summary.groups ?? (d.groups ?? []).length}`
          + ` · классов ${d.summary.count} · выручка ${fmtMoney(d.summary.revenue)}`}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {([['groups', 'По товарным группам'], ['classes', 'По классам учёта']] as const).map(([k, label]) => (
            <button key={k} type="button" onClick={() => задатьРазрез(k)}
              className={`text-xs px-2.5 py-1.5 rounded-md border ${разрез === k
                ? 'border-primary/60 bg-primary/10 text-foreground'
                : 'border-border/50 text-muted-foreground hover:text-foreground'}`}>
              {label}
            </button>
          ))}
          {разрез === 'groups' && (
            <input value={поиск} onChange={(e) => задатьПоиск(e.target.value)}
              placeholder="найти группу…"
              className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-56" />
          )}
        </div>
        {разрез === 'groups' ? (
          <Table
            head={[{ label: 'Группа' }, { label: 'Класс' }, { label: 'Выручка', num: true },
                   { label: 'Доля', num: true }, { label: 'Маржа %', num: true },
                   { label: 'Позиций', num: true }, { label: 'Продано', num: true }]}
            rows={группы.map((г) => [
              г.path || <span className="text-muted-foreground">— без группы —</span>,
              г.sku_class || '—',
              fmtMoney(г.revenue), `${г.share}%`,
              г.margin_pct != null ? `${г.margin_pct}%` : '—',
              nf(г.sku_count), nf(г.qty),
            ])}
          />
        ) : (
          <Table
            head={[{ label: 'Класс учёта' }, { label: 'Выручка', num: true }, { label: 'Доля', num: true }, { label: 'Маржа %', num: true }, { label: 'SKU', num: true }, { label: 'Продано', num: true }]}
            rows={d.categories.map((r) => [
              r.category, fmtMoney(r.revenue), `${r.share}%`,
              r.margin_pct != null ? `${r.margin_pct}%` : '—', nf(r.sku_count), nf(r.qty),
            ])}
          />
        )}
      </Shell>
    )
  })
}

export function StoreBarcodesPanel(p: PanelProps) {
  // Справочник-снимок: период/станции к штрихкодам неприменимы — в ключ не входят.
  const q = useQuery({ queryKey: ['store-report', 'barcodes', p.companyId], queryFn: getStoreBarcodes })
  const [search, setSearch] = useState('')
  // Смена контура обнуляет поиск по номенклатуре (CLAUDE.md, правило 5).
  useResetOnScopeChange(() => setSearch(''))
  const [openGuid, setOpenGuid] = useState<string | null>(null)
  // Находки, а не просто список. Штрихкод сам по себе — цифра; работа начинается
  // там, где он ведёт себя не так: код на двух карточках, карточка с пятью
  // кодами, товар вообще без кода (его не пробить на кассе), внутренний номер
  // станции вместо кода с упаковки.
  const [срез, задатьСрез] = useState<'all' | 'dup' | 'multi' | 'internal' | 'nocash' | 'nobarcode'>('all')
  return (
    <>
      {wrap(q, () => {
        const d = q.data!
        const поиск = search.trim().toLowerCase()
        const подходит = (b: string, n: string) =>
          !поиск || b.includes(поиск) || n.toLowerCase().includes(поиск)
        const items = d.items.filter((i) => {
          if (!подходит(i.barcode, i.owner_name)) return false
          switch (срез) {
            case 'dup': return (i.dup_items ?? 1) > 1
            case 'multi': return (i.item_barcodes ?? 1) > 1
            case 'internal': return i.type === 'внутренний' || i.type === 'иной'
            case 'nocash': return !i.ns_code
            default: return true
          }
        })
        const безКода = (d.items_without_barcode ?? []).filter((i) => подходит('', i.name))
        // Группы объясняем словами, а не цветом.
        //
        // Семь строк подряд с одинаковым именем читаются как семь разных
        // товаров. Полоса фона сказала бы «это как-то связано», но не сказала
        // бы КАК: имя товара стоит в первой строке группы со счётчиком кодов,
        // остальные помечены стрелкой «тот же товар». Тогда видно и границу
        // группы, и её смысл, и работает это на монохромной печати.
        const первыйВГруппе = new Set<number>()
        const размерГруппы = new Map<string, number>()
        items.forEach((i, n) => {
          const ключ = i.owner_guid ?? i.owner_name
          размерГруппы.set(ключ, (размерГруппы.get(ключ) ?? 0) + 1)
          const пред = n > 0 ? (items[n - 1].owner_guid ?? items[n - 1].owner_name) : null
          if (ключ !== пред) первыйВГруппе.add(n)
        })
        return (
          <Shell title="Штрихкоды / EAN"
            sub={`${d.total} кодов в работе на ${d.items_with_barcode ?? 0} карточках · `
              + Object.entries(d.by_type).map(([t, n]) => `${t}: ${n}`).join(' · ')
              + (d.archive_total ? ` · в старом справочнике 1С осталось ${d.archive_total} кодов без товара — они здесь не показаны` : '')
              + ' · клик по товару — карточка'}>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="поиск по штрихкоду или товару…"
                className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-64" />
              {/* Срез — это вопрос, а не украшение. Каждый отвечает на свой:
                  «нет ли кода на двух карточках», «где карточка обросла кодами»,
                  «что станция завела сама», «что лежит и не продаётся»,
                  «чего нельзя пробить на кассе вовсе». */}
              {([
                ['all', `Все · ${d.total}`, 'весь рабочий справочник'],
                ['dup', `Дубли · ${d.duplicates ?? 0}`, 'один код на нескольких карточках: касса возьмёт первую попавшуюся. Ноль здесь — не то же самое, что ноль в «Коллизиях ШК»: там очередь отклонённых заявок на занятый код, а в самом справочнике активный код всегда у одной карточки'],
                ['multi', `Много кодов · ${d.multi_barcode_items ?? 0}`, 'карточки, у которых кодов больше одного: вкусы, старая и новая упаковка'],
                ['internal', `Внутренние · ${d.internal_codes ?? 0}`, 'короткие номера станции вместо кода с упаковки — общепит и весовое'],
                ['nocash', `Без кода кассы · ${d.without_ns_code ?? 0}`, 'кода нефтесервера нет — по такому штрихкоду товар не пробьётся'],
                ['nobarcode', `Без кода · ${(d.items_without_barcode ?? []).length}`, 'карточки без штрихкода вовсе — такой товар не пробить на кассе'],
              ] as const).map(([k, label, hint]) => (
                <button key={k} type="button" title={hint} onClick={() => задатьСрез(k)}
                  className={`text-xs px-2.5 py-1.5 rounded-md border ${срез === k
                    ? 'border-primary/60 bg-primary/10 text-foreground'
                    : 'border-border/50 text-muted-foreground hover:text-foreground'}`}>
                  {label}
                </button>
              ))}
            </div>
            {/* «Основной» убран: в рабочем справочнике у карточки кодов бывает
                несколько (вкусы, старая и новая упаковка), и все равноправны —
                колонка всегда стояла пустой. На её месте то, что отвечает на
                живой вопрос: чей это код и продавали ли по нему. */}
            {/* В срезе «без кода» строка — это карточка, а не код: колонке
                штрихкода нечего показать, и прочерк в ней прятал бы суть. */}
            {срез === 'nobarcode' ? (
              <Table
                head={[{ label: 'Товар' }, { label: 'Артикул' }, { label: 'Класс' }, { label: 'Остаток' }]}
                rows={безКода.map((i) => [
                  i.guid
                    ? <button type="button" onClick={() => setOpenGuid(i.guid)} className="text-left hover:text-primary hover:underline">{i.name}</button>
                    : i.name,
                  i.sku ?? '—',
                  i.sku_class || '—',
                  i.stock_qty ? nf(i.stock_qty) : '—',
                ])}
                onRowClick={(ri) => { const g = безКода[ri]?.guid; if (g) setOpenGuid(g) }}
                rowLabel={(ri) => `Карточка: ${безКода[ri]?.name ?? ''}`}
              />
            ) : (
            <Table
              head={[{ label: 'Штрихкод' }, { label: 'Товар' }, { label: 'Артикул' },
                     { label: 'Тип' }, { label: 'АЗС' }, { label: 'Кодов у карточки' },
                     { label: 'Код кассы' }, { label: 'Остаток', num: true }]}
              rows={items.map((i, ri) => [
                <span className="font-mono">{i.barcode}</span>,
                первыйВГруппе.has(ri)
                  ? (
                    <span>
                      {i.owner_name}
                      {(i.item_barcodes ?? 1) > 1 && (
                        <span className="ml-1.5 text-muted-foreground/70"
                          title="у этой карточки несколько штрихкодов: вкусы, старая и новая упаковка или внутренний номер станции рядом с кодом производителя">
                          · {i.item_barcodes} кодов
                        </span>
                      )}
                    </span>
                  )
                  : <span className="text-muted-foreground/60" title="тот же товар, другой штрихкод">↳ тот же товар</span>,
                i.sku ?? '—',
                (i.dup_items ?? 1) > 1
                  ? <span className="text-amber-400/90" title="этот код есть ещё на другой карточке">{i.type} · дубль</span>
                  : i.type ?? '—',
                i.station_id ?? '—',
                (i.item_barcodes ?? 1) > 1
                  ? <span title="у карточки несколько штрихкодов">{i.item_barcodes}</span>
                  : '1',
                i.ns_code
                  ? i.ns_code
                  : <span className="text-amber-400/90" title="кода нефтесервера нет — по этому штрихкоду товар не пробьётся">нет</span>,
                i.stock_qty ? nf(i.stock_qty) : '—',
              ])}
              onRowClick={(ri) => { const g = items[ri]?.owner_guid; if (g) setOpenGuid(g) }}
              rowLabel={(ri) => `Карточка: ${items[ri]?.owner_name ?? ''}`}

            />
            )}
          </Shell>
        )
      })}
      {openGuid && <NomenclatureCardModal guid={openGuid} companyId={p.companyId} dateFrom={p.dateFrom} dateTo={p.dateTo} stations={p.stations} onClose={() => setOpenGuid(null)} />}
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
      {openGuid && <NomenclatureCardModal guid={openGuid} companyId={p.companyId} dateFrom={p.dateFrom} dateTo={p.dateTo} stations={p.stations} onClose={() => setOpenGuid(null)} />}
    </>
  )
}
