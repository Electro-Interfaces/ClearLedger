/**
 * Лист документа ОРП (смены) — большое модальное окно по утверждённой схеме.
 *
 * Отчёт о розничных продажах закрывает смену сводом, но сам по себе ничего не
 * объясняет: рядом лежат выпуск блюд, техкарты, чеки и кассовая смена, а приёмки
 * и пересчёты в неё не входят — они её условие. Одно место, где видно всё, а
 * главное — светофор достоверности: можно ли грузить смену в бухгалтерию.
 *
 * Схема-эталон: app/clearledger/docs/orp-shema-predstavleniya.html.
 * Товарная часть документов, проводки и сверка ящика — Этап 3 (расширение API).
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, LoaderCircle } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getStoreShiftPassport, type StoreShiftPassport } from '@/services/storeDocumentsService'
import { useCompany } from '@/contexts/CompanyContext'
import { NomenclatureCardModal } from './NomenclatureCardModal'

type SaleRow = StoreShiftPassport['sales'][number]
type PayRow = StoreShiftPassport['payments'][number]
type DishRow = StoreShiftPassport['dishes'][number]
type StockRow = StoreShiftPassport['stock'][number]

const STOCK_LABELS: Record<string, string> = {
  purchase: 'Поступление', inventory: 'Инвентаризация', writeoff: 'Списание',
  transfer: 'Перемещение', gain: 'Оприходование',
}

const KIND_LABELS: Record<string, string> = {
  retail_sale_sidegoods: 'Отчёт о розничных продажах',
  production_release: 'Выпуск продукции',
  recipe: 'Техкарты',
  fiscal_receipt: 'Чеки',
  store_shift: 'Кассовая смена',
  ingredients_writeoff: 'Списание ингредиентов',
  return_sale: 'Возвраты покупателей',
  purchase: 'Поступление',
  inventory: 'Инвентаризация',
  gain: 'Оприходование',
  writeoff: 'Списание',
  transfer: 'Перемещение',
  revaluation: 'Переоценка',
}

const money = (n: number) =>
  Number.isFinite(n) ? new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n) + ' ₽' : '—'

const время = (value: string | null) =>
  value
    ? new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '—'

type DocHint = { kind: string; number: string | null; document_at: string | null }

export function ShiftPassportSheet({
  station, shift, onClose, onOpenDocuments, onOpenDocument,
}: {
  station: number | null
  shift: number | null
  onClose: () => void
  onOpenDocuments?: (station: number, shift: number) => void
  /** Открыть карточку конкретного документа поверх листа смены. */
  onOpenDocument?: (recordId: string, hint?: DocHint) => void
}) {
  const { company } = useCompany()
  const [passport, setPassport] = useState<StoreShiftPassport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // GUID товара сопутки, раскрытого карточкой (единообразно с рецептурой блюда).
  const [sku, setSku] = useState<string | null>(null)

  useEffect(() => {
    if (station == null || shift == null) { setPassport(null); return }
    let живо = true
    setLoading(true); setError(''); setPassport(null)
    getStoreShiftPassport(station, shift)
      .then((данные) => { if (живо) setPassport(данные) })
      .catch((err) => { if (живо) setError(err instanceof Error ? err.message : 'Паспорт не открылся') })
      .finally(() => { if (живо) setLoading(false) })
    return () => { живо = false }
  }, [station, shift])

  // Светофор достоверности: можно ли грузить в бухгалтерию. Красный (не грузить —
  // расхождение) подключится на Этапе 3 с правилами сверки.
  const светофор = useMemo<{ color: 'g' | 'y' | 'r'; verdict: string; why: string } | null>(() => {
    if (!passport) return null
    // Цвет — из readiness бэка (тот же источник, что реестр), а не из локального
    // разбора: иначе смена зелёная в списке и жёлтая внутри (или наоборот).
    // Блокеры — первыми: это причины, по которым смена НЕ уедет, а всё
    // остальное лишь неточности, с которыми уедет.
    const проблемы: string[] = [
      ...(passport.blockers ?? []),
      ...passport.actions.map((a) => a.text),
    ]
    if (passport.cost_estimated.length > 0) {
      проблемы.push(`себестоимость ${passport.cost_estimated.length} ингредиентов посчитана оценкой центра`)
    }
    if (passport.readiness === 'g') {
      return { color: 'g', verdict: 'Готов к выгрузке', why: проблемы.join(' · ') || 'Все разрезы сведены, смена готова к бухгалтерии.' }
    }
    if (passport.readiness === 'r') {
      return {
        color: 'r',
        verdict: 'Не уедет в бухгалтерию — разобрать здесь',
        why: проблемы.join(' · ') || 'В смене расхождение, требующее разбора.',
      }
    }
    return { color: 'y', verdict: 'Можно грузить — есть неточности', why: проблемы.join(' · ') || 'Смена ещё не выверена полностью.' }
  }, [passport])

  // «Повлияло на смену» без пустых переоценок (0 ₽ — техническая правка цен, шум).
  const влияние = (passport?.influenced_by ?? []).filter((д) => Math.abs(д.amount) > 0.005)

  const bulb = светофор ? (светофор.color === 'g' ? 'bg-emerald-500' : светофор.color === 'y' ? 'bg-amber-500' : 'bg-red-500') : ''
  const sfBorder = светофор?.color === 'g' ? 'border-l-emerald-500 bg-emerald-500/5' : светофор?.color === 'y' ? 'border-l-amber-500 bg-amber-500/5' : 'border-l-red-500 bg-red-500/5'
  const sfText = светофор?.color === 'g' ? 'text-emerald-500' : светофор?.color === 'y' ? 'text-amber-500' : 'text-red-500'

  return (
    <>
    <Dialog open={station != null && shift != null} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex max-h-[92vh] max-w-5xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4 pr-14 text-left">
          <DialogTitle className="text-xl">Смена № {shift} · <span className="font-mono text-base text-muted-foreground">АЗС {station}</span></DialogTitle>
          <DialogDescription>
            {время(passport?.started_at ?? null)} — {время(passport?.finished_at ?? null)}
            {passport && <> · выручка {money(passport.revenue)} · {passport.documents} документов</>}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {loading && (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" /> Собираю лист смены…
            </div>
          )}
          {error && <div className="py-8 text-sm text-destructive">{error}</div>}

          {passport && светофор && (
            <>
              {/* Светофор достоверности */}
              <div className={`mb-5 flex items-center gap-4 rounded-lg border border-l-4 p-4 ${sfBorder}`}>
                <span className={`size-8 shrink-0 rounded-full ${bulb}`} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <div className={`font-semibold ${sfText}`}>
                    {светофор.color === 'g'
                      ? <><CheckCircle2 className="mr-1 inline size-4" />{светофор.verdict}</>
                      : <><AlertTriangle className="mr-1 inline size-4" />{светофор.verdict}</>}
                  </div>
                  <div className="mt-0.5 text-sm text-muted-foreground">{светофор.why}</div>
                </div>
              </div>

              {/* KPI-полоса. Выручка разложена по деньгам: наличными и картой —
                  первое, что сверяет бухгалтер (из свода оплат смены). */}
              {(() => {
                const оплаты = passport.payments ?? []
                const нал = оплаты.filter((p) => /налич/i.test(p.form)).reduce((s, p) => s + p.amount, 0)
                const карта = оплаты.filter((p) => /карт|банк|мпс|сбер/i.test(p.form)).reduce((s, p) => s + p.amount, 0)
                return (
                  <div className="mb-5 grid grid-cols-2 overflow-hidden rounded-lg border sm:grid-cols-3 lg:grid-cols-6">
                    <Kpi label="Выручка" value={money(passport.revenue)} />
                    <Kpi label="Наличными" value={money(нал)} />
                    <Kpi label="Банковская карта" value={money(карта)} />
                    <Kpi label="НДС" value={passport.vat == null ? '—' : money(passport.vat)} />
                    <Kpi label="Чеков" value={String(passport.cheques)} />
                    <Kpi label="Документов" value={String(passport.documents)} />
                  </div>
                )
              })()}

              {/* Секции: продажи разделены по классу — Сопутка и Общепит отдельно.
                  Рецептура блюд (ТТК) берётся из выпуска (dishes) по имени. */}
              {(() => {
                const продажи = passport.sales ?? []
                const оплаты = passport.payments ?? []
                const сопутка = продажи.filter((s) => s.cls !== 'Общепит')
                const общепит = продажи.filter((s) => s.cls === 'Общепит')
                // Рецептуру ищем по GUID блюда, а имя — только запасной путь: у
                // общепита 208 есть тёзки, различающиеся точкой в конце («Капучино
                // 400 мл» и «Капучино 400 мл.»), и составы у них РАЗНЫЕ — поиск по
                // имени подставил бы чужую карту. Агент связывает карту по dish_uuid.
                const рецептПоGuid = new Map(
                  (passport.dishes ?? []).filter((d) => d.guid).map((d) => [d.guid as string, d.recipe]))
                const рецептПоИмени = new Map((passport.dishes ?? []).map((d) => [d.name, d.recipe]))
                const рецептура = (s: SaleRow) =>
                  (s.guid ? рецептПоGuid.get(s.guid) : undefined) ?? рецептПоИмени.get(s.name) ?? []
                const естьОбщепит = общепит.length > 0
                const склад = passport.stock ?? []
                const естьСклад = склад.length > 0
                // Секции создаём в каждом табе заново, а не переиспользуем один
                // элемент: Radix монтирует его лишь в одном месте, и в «Все»
                // общепит пропадал, а «Все» и «Сопутка» выглядели одинаково.
                return (
                  <Tabs defaultValue="all">
                    <TabsList className="mb-4 flex-wrap">
                      <TabsTrigger value="all">Все<span className="ml-1.5 text-xs opacity-60">{продажи.length}</span></TabsTrigger>
                      <TabsTrigger value="sop">Сопутка<span className="ml-1.5 text-xs opacity-60">{сопутка.length}</span></TabsTrigger>
                      {естьОбщепит && <TabsTrigger value="food">Общепит<span className="ml-1.5 text-xs opacity-60">{общепит.length}</span></TabsTrigger>}
                      {естьСклад && <TabsTrigger value="stock">Склад<span className="ml-1.5 text-xs opacity-60">{склад.length}</span></TabsTrigger>}
                    </TabsList>
                    <TabsContent value="all" className="space-y-7">
                      <SalesSection sales={сопутка} payments={оплаты} onSelect={setSku} />
                      {естьОбщепит && <FoodSalesSection sales={общепит} recipe={рецептура} />}
                      {естьСклад && <StockSection docs={склад} onOpen={onOpenDocument} />}
                    </TabsContent>
                    <TabsContent value="sop">
                      <SalesSection sales={сопутка} payments={оплаты} onSelect={setSku} />
                    </TabsContent>
                    {естьОбщепит && (
                      <TabsContent value="food">
                        <FoodSalesSection sales={общепит} recipe={рецептура} />
                      </TabsContent>
                    )}
                    {естьСклад && (
                      <TabsContent value="stock">
                        <StockSection docs={склад} onOpen={onOpenDocument} />
                      </TabsContent>
                    )}
                  </Tabs>
                )
              })()}

              {/* Повлияло на смену — документы вне смены, меняющие остаток.
                  Пустые переоценки (0 ₽, техническая правка цен) — шум, не
                  показываем: они остаток деньгами не двигают. */}
              {влияние.length > 0 && (
                <section className="mt-6 border-t pt-5">
                  <h3 className="mb-1 text-sm font-medium">Повлияло на смену</h3>
                  <p className="mb-2 text-xs text-muted-foreground">Эти документы в смену не входят, но меняют её остаток.</p>
                  <table className="w-full text-sm">
                    <tbody>
                      {влияние.map((док) => {
                        const открыть = Boolean(onOpenDocument && док.record_id)
                        return (
                          <tr key={док.record_id}
                            className={`border-b last:border-0 ${открыть ? 'cursor-pointer hover:bg-muted/40' : ''}`}
                            onClick={() => { if (открыть) onOpenDocument!(док.record_id, { kind: док.kind, number: док.number, document_at: док.document_at }) }}>
                            <td className="py-1.5">
                              <span className={открыть ? 'text-primary hover:underline' : ''}>{KIND_LABELS[док.kind] ?? док.kind}</span>
                            </td>
                            <td className="py-1.5 text-muted-foreground">{док.number ?? '—'}</td>
                            <td className="py-1.5 text-muted-foreground">{док.counterparty ?? '—'}</td>
                            <td className="py-1.5 text-right tabular-nums">{money(док.amount)}</td>
                            <td className="py-1.5 pl-2 text-right text-xs text-muted-foreground">{док.operational_status ?? ''}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </section>
              )}

              {onOpenDocuments && station != null && shift != null && (
                <button type="button" onClick={() => onOpenDocuments(station, shift)}
                  className="mt-5 inline-flex items-center gap-1 text-xs text-primary hover:underline">
                  Открыть все документы смены в реестре <ArrowRight className="size-3" />
                </button>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
    {sku && (
      <NomenclatureCardModal guid={sku} companyId={company?.id ?? ''}
        dateFrom={(passport?.started_at ?? '').slice(0, 10)}
        dateTo={(passport?.finished_at ?? '').slice(0, 10)}
        onClose={() => setSku(null)} />
    )}
    </>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-r border-t p-3 first:border-l-0 [&:nth-child(-n+4)]:border-t-0">
      <div className="text-lg font-bold tabular-nums">{value}</div>
      <div className="mt-1 text-[11px] text-muted-foreground">{label}</div>
    </div>
  )
}

// ── Товарные секции листа (данные shift_detail) ───────────────────────────────

const num = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(n)

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h4 className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {children}<span className="h-px flex-1 bg-border" />
    </h4>
  )
}


// ── Товарные секции листа (данные паспорта из первичных пакетов) ──────────────

// Продажи: проданные позиции по SKU + свод по видам оплаты.
function SalesSection({ sales, payments, onSelect }: { sales: SaleRow[]; payments: PayRow[]; onSelect?: (guid: string) => void }) {
  return (
    <section>
      <SectionTitle>Проданные позиции · {sales.length}</SectionTitle>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="p-2 text-left font-medium">Товар</th>
              <th className="p-2 text-left font-medium">Класс</th>
              <th className="p-2 text-right font-medium">Кол-во</th>
              <th className="p-2 text-right font-medium">Цена</th>
              <th className="p-2 text-right font-medium">Сумма</th>
              <th className="p-2 text-right font-medium">НДС</th>
            </tr>
          </thead>
          <tbody>
            {sales.slice(0, 80).map((s, i) => (
              <tr key={i} className={`border-b last:border-0 ${s.guid && onSelect ? 'cursor-pointer hover:bg-muted/40' : ''}`}
                onClick={() => { if (s.guid && onSelect) onSelect(s.guid) }}>
                <td className="p-2">{s.name}</td>
                <td className="p-2 text-muted-foreground">{s.cls ?? '—'}</td>
                <td className="p-2 text-right tabular-nums">{num(s.qty)}</td>
                <td className="p-2 text-right tabular-nums">{num(s.price)}</td>
                <td className="p-2 text-right font-medium tabular-nums">{money(s.amount)}</td>
                <td className="p-2 text-right tabular-nums text-muted-foreground">{money(s.vat)}</td>
              </tr>
            ))}
            {sales.length > 80 && (
              <tr><td colSpan={6} className="p-2 text-xs text-muted-foreground">…ещё {sales.length - 80} позиций</td></tr>
            )}
            {sales.length === 0 && (
              <tr><td colSpan={6} className="p-2 text-xs text-muted-foreground">Проданных позиций нет.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {payments.length > 0 && (
        <div className="mt-3">
          <SectionTitle>Свод по оплате</SectionTitle>
          <div className="flex flex-wrap gap-2">
            {payments.map((pm, i) => (
              <div key={i} className="rounded-md border px-3 py-2 text-sm">
                <span className="text-muted-foreground">{pm.form}: </span>
                <span className="font-semibold tabular-nums">{money(pm.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

// Общепит: ПРОДАННЫЕ блюда (класс «Общепит») с ценой за порцию и раскрытием
// рецептуры (ТТК). Рецептура берётся из выпуска смены по GUID блюда (имя — запасной
// путь: у тёзок общепита составы разные).
function FoodSalesSection({ sales, recipe }: { sales: SaleRow[]; recipe: (s: SaleRow) => DishRow['recipe'] }) {
  return (
    <section>
      <SectionTitle>Общепит · проданных позиций {sales.length}</SectionTitle>
      <div className="space-y-1.5">
        {sales.map((s, i) => {
          const рец = recipe(s)
          return (
            <details key={i} className="rounded-md border bg-card">
              <summary className="flex cursor-pointer list-none items-center gap-3 p-2.5">
                <span className="text-sm font-medium">{s.name}</span>
                <span className="text-xs tabular-nums text-muted-foreground">× {num(s.qty)}</span>
                <span className="text-xs tabular-nums text-muted-foreground">{money(s.price)}/порц</span>
                {рец.length > 0 && <span className="text-[11px] text-muted-foreground">рецептура · {рец.length}</span>}
                <span className="ml-auto text-sm font-semibold tabular-nums">{money(s.amount)}</span>
              </summary>
              <div className="border-t p-2.5">
                <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Рецептура (ТТК)</div>
                {рец.length > 0 ? (
                  <table className="w-full text-xs">
                    <tbody>
                      {рец.map((r, j) => (
                        <tr key={j} className="border-b last:border-0">
                          <td className="py-1">{r.name}</td>
                          <td className="py-1 text-right tabular-nums">{num(r.qty)} {r.unit ?? ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="text-xs text-muted-foreground">Техкарта для этого блюда не найдена в выпуске смены.</div>
                )}
              </div>
            </details>
          )
        })}
      </div>
    </section>
  )
}


// Склад: поступления, инвентаризации, списания, перемещения — с товарами.
// Служебные (наше выравнивание остатка) помечены и открываются как документ.
function StockSection({ docs, onOpen }: { docs: StockRow[]; onOpen?: (recordId: string, hint?: DocHint) => void }) {
  return (
    <section>
      <SectionTitle>Склад и движение · документов {docs.length}</SectionTitle>
      <div className="space-y-1.5">
        {docs.map((d, i) => (
          <details key={i} className="rounded-md border bg-card">
            <summary className="flex cursor-pointer list-none items-center gap-3 p-2.5">
              <span className="rounded border bg-muted/40 px-2 py-0.5 text-[11px] font-medium">{STOCK_LABELS[d.kind] ?? d.kind}</span>
              {d.number && <span className="font-mono text-xs">{d.number}</span>}
              {d.service
                ? <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">служебное · выравнивание остатка</span>
                : d.meta && <span className="truncate text-xs text-muted-foreground">{d.meta}</span>}
              <span className="ml-auto text-sm font-semibold tabular-nums">{d.service ? <span className="text-muted-foreground">без стоимости</span> : money(d.amount)}</span>
              {onOpen && d.record_id && (
                <button type="button" title="Открыть документ"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); onOpen(d.record_id!, { kind: d.kind, number: d.number, document_at: null }) }}
                  className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] text-primary hover:bg-primary/10">
                  Открыть <ArrowRight className="size-3" />
                </button>
              )}
            </summary>
            <div className="border-t p-2.5">
              {d.lines.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="p-1 text-left font-medium">Товар</th>
                        {d.kind === 'inventory' ? (
                          <>
                            <th className="p-1 text-right font-medium">Учёт</th>
                            <th className="p-1 text-right font-medium">Откл.</th>
                            <th className="p-1 text-right font-medium">Сумма</th>
                          </>
                        ) : (
                          <>
                            <th className="p-1 text-right font-medium">Кол-во</th>
                            <th className="p-1 text-right font-medium">Цена</th>
                            <th className="p-1 text-right font-medium">Сумма</th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {d.lines.slice(0, 50).map((l, j) => (
                        <tr key={j} className="border-b last:border-0">
                          <td className="p-1">{l.name}</td>
                          {d.kind === 'inventory' ? (
                            <>
                              <td className="p-1 text-right tabular-nums">{l.uchet ?? '—'}</td>
                              <td className={`p-1 text-right tabular-nums ${(l.dev ?? 0) < 0 ? 'text-red-500' : 'text-emerald-500'}`}>{l.dev ?? '—'}</td>
                              <td className="p-1 text-right tabular-nums">{money(l.amount)}</td>
                            </>
                          ) : (
                            <>
                              <td className="p-1 text-right tabular-nums">{num(l.qty)}</td>
                              <td className="p-1 text-right tabular-nums">{num(l.price)}</td>
                              <td className="p-1 text-right tabular-nums">{money(l.amount)}</td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">Строки документа не приехали в пакете.</div>
              )}
            </div>
          </details>
        ))}
      </div>
    </section>
  )
}
