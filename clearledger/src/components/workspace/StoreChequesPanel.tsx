/**
 * «Магазин» → Торговля → Чеки.
 *
 * Отчёт о розничных продажах закрывает смену сводом — этого хватает
 * бухгалтерии, но не разбору. Спорная продажа, возврат, проверка
 * маркированного товара и жалоба покупателя разбираются по конкретному чеку:
 * когда, что, за сколько и по какому фискальному номеру.
 *
 * Топлива здесь нет: оно ведёт свой контур. Смешанный чек (заправка плюс кофе)
 * помечен — иначе его сумма читалась бы как весь чек, а это не так.
 */
import { Fragment, useDeferredValue, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Search, X, Receipt, RotateCcw } from 'lucide-react'
import {
  getStoreCheques, getStorePivot, getStorePivotCatalog, type StoreCheque,
} from '@/services/storeService'
import { PivotView } from './PivotView'
import { fmtMoney } from '@/services/analyticsService'
import { rowDrill } from './rowDrill'

const PAGE_SIZE = 500

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

function время(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Kpi({ label, value, hint, cls }: {
  label: string; value: string; hint?: string; cls?: string
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${cls ?? ''}`}>{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export function StoreChequesPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const [запрос, задатьЗапрос] = useState('')
  const отложенныйЗапрос = useDeferredValue(запрос)
  const [возвраты, задатьВозвраты] = useState(false)
  const [открыт, открыть] = useState<string | null>(null)
  const [страница, задатьСтраницу] = useState({ scope: '', offset: 0 })
  // Список и сводная — две подачи одного отбора: «сколько за смену наличными»
  // и «какой чек спорный» это разные вопросы к одним данным.
  const [подача, задатьПодачу] = useState<'list' | 'pivot'>('list')

  const scopeKey = [companyId, dateFrom, dateTo, отложенныйЗапрос,
    возвраты ? 'returns' : 'all', stations?.join(',') || ''].join('|')
  const смещение = страница.scope === scopeKey ? страница.offset : 0

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-cheques', companyId, dateFrom, dateTo, отложенныйЗапрос, возвраты, stations, смещение],
    queryFn: () => getStoreCheques({
      dateFrom, dateTo, stations, q: отложенныйЗапрос, onlyReturns: возвраты,
      limit: PAGE_SIZE, offset: смещение,
    }),
  })

  const чеки = data?.cheques ?? []
  const свод = data?.summary

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Чеки</h3>
        <p className="text-xs text-muted-foreground">
          Продажи на уровне покупки, а не смены: время, позиции, сумма, фискальный номер.
          Свод смены закрывает бухгалтерию, а спорную продажу и возврат разбирают по чеку.
          Топлива здесь нет — оно ведёт свой контур; смешанный чек помечен.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md bg-muted p-[3px]">
          {(['list', 'pivot'] as const).map((v) => (
            <button key={v} type="button" onClick={() => задатьПодачу(v)}
              className={`rounded-[5px] px-2.5 py-1 text-xs font-medium transition-colors ${
                подача === v ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
              {v === 'list' ? 'Список' : 'Сводная'}
            </button>
          ))}
        </div>
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input value={запрос} onChange={(e) => задатьЗапрос(e.target.value)}
            placeholder="Товар, номер чека или фискальный номер"
            aria-label="Поиск по чекам"
            className="h-8 w-full rounded-md border border-border/60 bg-background/60 pl-8 pr-8 text-xs outline-none placeholder:text-muted-foreground/70 focus:border-primary/60" />
          {запрос && (
            <button type="button" onClick={() => задатьЗапрос('')} aria-label="Очистить поиск"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <button type="button" onClick={() => задатьВозвраты(!возвраты)} aria-pressed={возвраты}
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${возвраты
            ? 'border-amber-400/60 bg-amber-400/10 text-amber-200'
            : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
          <RotateCcw className="h-3 w-3" />только возвраты
        </button>
      </div>

      {свод && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Kpi label="Чеков" value={nf(свод.sales)} hint="без возвратов" />
          <Kpi label="Выручка" value={fmtMoney(свод.amount)} />
          <Kpi label="Средний чек" value={свод.avg != null ? fmtMoney(свод.avg) : '—'}
               hint="возвраты в среднее не идут" />
          <Kpi label="Возвраты" value={nf(свод.returns)}
               hint={свод.returns_amount ? fmtMoney(свод.returns_amount) : undefined}
               cls={свод.returns > 0 ? 'text-amber-300/90' : ''} />
          <Kpi label="Со заправкой" value={nf(свод.with_fuel)}
               hint="в чеке было и топливо" />
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-muted-foreground">Загрузка чеков…</div>
      ) : error ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-red-400/30 bg-red-400/5 px-3 py-2 text-sm text-red-300/90">
          Не удалось получить чеки. Проверьте связь с сервером.
          <button type="button" onClick={() => refetch()} className="underline underline-offset-2">Повторить</button>
        </div>
      ) : чеки.length === 0 ? (
        <div className="flex items-start gap-3 rounded-lg border border-dashed border-border/50 p-5">
          <Receipt className="mt-0.5 h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm">Чеков за период нет</div>
            <div className="text-xs text-muted-foreground">
              Чеки поднимает агент станции отдельным пакетом при закрытии смены. Если станция
              работает на версии без чекового пакета, здесь будет пусто, а свод смены —
              на месте: он собирается из той же ленты.
            </div>
          </div>
        </div>
      ) : подача === 'pivot' ? (
        <PivotView
          source="store_cheques"
          storageKey="store-cheques-pivot"
          defaultDims={['station', 'day']}
          fetchCatalog={getStorePivotCatalog}
          fetchLeaves={(dims) => getStorePivot({
            source: 'store_cheques', dims, dateFrom, dateTo,
            stations: stations?.map(Number).filter(Number.isFinite),
          })}
          queryKey={[dateFrom, dateTo, stations?.join(',') ?? '']}
          dateFrom={dateFrom}
          dateTo={dateTo}
          hint="Средний чек считается делением суммы на число чеков в узле — подытоги сходятся с карточками выше."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border/50">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Время</th>
                <th className="px-3 py-2 text-left font-medium">АЗС</th>
                <th className="px-3 py-2 text-right font-medium">Смена</th>
                <th className="px-3 py-2 text-right font-medium">Чек</th>
                <th className="px-3 py-2 text-right font-medium">ФД</th>
                <th className="px-3 py-2 text-right font-medium">Позиций</th>
                <th className="px-3 py-2 text-right font-medium">Сумма</th>
                <th className="px-3 py-2 text-left font-medium">Особенности</th>
              </tr>
            </thead>
            <tbody>
              {чеки.map((c: StoreCheque) => (
                // Ключ на фрагменте, а не на строках внутри: React сверяет
                // список по корню элемента, и без него раскрытый состав чека
                // при перерисовке уезжает на соседнюю строку.
                <Fragment key={c.id}>
                  <tr
                      aria-expanded={открыт === c.id}
                      {...rowDrill(
                        () => открыть(открыт === c.id ? null : c.id),
                        `Чек ${c.number} — ${открыт === c.id ? 'свернуть' : 'раскрыть'} состав`,
                        'border-t border-border/30',
                      )}>
                    <td className="whitespace-nowrap px-3 py-1.5">{время(c.at)}</td>
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.station_id}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.shift_number}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{c.number}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {c.fiscal_number ?? '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{c.positions}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums font-medium ${
                      c.is_return ? 'text-amber-300/90' : ''}`}>
                      {fmtMoney(c.total)}
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground">
                      {[c.is_return ? 'возврат' : null,
                        c.had_fuel ? 'с заправкой' : null,
                        c.pay_name].filter(Boolean).join(' · ') || '—'}
                    </td>
                  </tr>
                  {открыт === c.id && (
                    <tr className="bg-background/40">
                      <td colSpan={8} className="px-3 py-2">
                        <table className="w-full text-[11px]">
                          <thead className="text-muted-foreground">
                            <tr>
                              <th className="px-2 py-1 text-left font-medium">Товар</th>
                              <th className="px-2 py-1 text-right font-medium">Кол-во</th>
                              <th className="px-2 py-1 text-right font-medium">Цена</th>
                              <th className="px-2 py-1 text-right font-medium">Сумма</th>
                              <th className="px-2 py-1 text-right font-medium">Код кассы</th>
                            </tr>
                          </thead>
                          <tbody>
                            {c.lines.map((l, i) => (
                              <tr key={i} className="border-t border-border/20">
                                <td className="px-2 py-1">{l.name}</td>
                                <td className="px-2 py-1 text-right tabular-nums">{nf(l.qty, 3)}</td>
                                <td className="px-2 py-1 text-right tabular-nums">{fmtMoney(l.price)}</td>
                                <td className="px-2 py-1 text-right tabular-nums">{fmtMoney(l.amount)}</td>
                                <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                                  {l.ns_code ?? '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {подача === 'list' && data && data.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/30 pt-2 text-[11px]">
          <span className="text-muted-foreground" aria-live="polite">
            Показаны {nf(data.offset + 1)}–{nf(data.offset + чеки.length)} из {nf(data.total)} чеков.
            KPI выше рассчитаны по всему отбору.
          </span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={смещение === 0}
              onClick={() => задатьСтраницу({ scope: scopeKey, offset: Math.max(0, смещение - PAGE_SIZE) })}
              className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40">
              <ChevronLeft className="h-3.5 w-3.5" />предыдущие
            </button>
            <button type="button" disabled={!data.truncated}
              onClick={() => задатьСтраницу({ scope: scopeKey, offset: смещение + PAGE_SIZE })}
              className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40">
              следующие<ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
