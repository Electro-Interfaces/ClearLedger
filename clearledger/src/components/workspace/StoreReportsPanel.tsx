/**
 * «Магазин» → Отчёты сети.
 *
 * Каталог повторяет тот, что уже работает в рабочем месте станции: те же
 * разделы, те же названия, тот же CSV. Иначе товаровед на АЗС и менеджер в
 * офисе обсуждали бы «списания» по двум разным спискам.
 *
 * Отличия центра, которых у станции нет и быть не может:
 *   — разрез по АЗС: сеть, показанная одной цифрой, прячет провал точки;
 *   — экраны сети рядом с отчётами: каталог — единственный вход, и уводить
 *     человека искать «Перемещения» в меню незачем.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronRight, Download, FileSpreadsheet, ExternalLink } from 'lucide-react'
import {
  getStoreNetworkReports, getStoreNetworkReport, storeNetworkReportCsvUrl, getStoreStations,
  type StoreStation,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { useCompany } from '@/contexts/CompanyContext'
import { ShowMore, useVisible } from '@/components/common/ShowMore'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/**
 * Экраны сети по разделам каталога.
 *
 * Отчёт отвечает на вопрос «сколько», экран — «что с этим делать»: в приёмке
 * правят расхождение, в инвентаризации утверждают пересчёт. Держим их рядом,
 * как в каталоге станции, где ссылки ведут на рабочие экраны агента.
 */
const ЭКРАНЫ: Record<string, { label: string; hint: string; to: string }[]> = {
  torg: [
    { label: 'Продажи', hint: 'выручка и маржа по товарам', to: '/shop?mode=store&sub=sales' },
    { label: 'Чеки', hint: 'продажа на уровне покупки', to: '/shop?mode=store&sub=cheques' },
    { label: 'Ассортимент', hint: 'ABC×XYZ, оборачиваемость', to: '/shop?mode=store&sub=assortment' },
    { label: 'Цены и маржа', hint: 'прибыльность и наценка', to: '/shop?mode=store&sub=pricing' },
  ],
  priem: [
    { label: 'Приёмка', hint: 'журнал поставок и расхождений', to: '/shop?mode=store_stock&sub=receipts' },
    { label: 'Поставщики', hint: 'справочник контрагентов', to: '/shop?mode=store_catalog&sub=suppliers' },
  ],
  sklad: [
    { label: 'Остатки', hint: 'по станциям и местам хранения', to: '/shop?mode=store_stock&sub=stock' },
    { label: 'Перемещения', hint: 'склад ↔ зал и между АЗС', to: '/shop?mode=store_stock&sub=transfers' },
    { label: 'Инвентаризация', hint: 'пересчёты и их итоги', to: '/shop?mode=store_stock&sub=inventory' },
    { label: 'Списания', hint: 'причины и суммы', to: '/shop?mode=store_stock&sub=writeoffs' },
    { label: 'Возвраты', hint: 'покупателю и поставщику', to: '/shop?mode=store_stock&sub=returns' },
  ],
  mark: [
    { label: 'МРЦ табака', hint: 'предельные цены', to: '/shop?mode=store_marking&sub=mrc' },
    { label: 'Коды на остатке', hint: '«Честный знак» по станциям', to: '/shop?mode=store_marking&sub=mark_codes' },
    { label: 'Вывод из оборота', hint: 'продажи и списания марок', to: '/shop?mode=store_marking&sub=withdrawal' },
  ],
  close: [
    { label: 'Смены', hint: 'закрытые смены станций', to: '/shop?mode=store_network&sub=shifts' },
  ],
  skvoz: [
    { label: 'Сверка с 1С', hint: 'расхождения переходного контура', to: '/shop?mode=store_network&sub=parity' },
    { label: 'Состояние станций', hint: 'связь, очередь, свежесть данных', to: '/shop?mode=store_network&sub=station_health' },
    { label: 'Хранение сырья', hint: 'пакеты и их разбор', to: '/shop?mode=store_network&sub=storage' },
  ],
}

/** Значение ячейки: даты и деньги читаются иначе, чем количества. */
function ячейка(поле: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (поле.endsWith('date') || поле === 'doc_date' || поле === 'snapshot_at' || поле === 'shift_date') {
    return new Date(String(v)).toLocaleDateString('ru-RU',
      { day: '2-digit', month: '2-digit', year: '2-digit' })
  }
  if (typeof v === 'number') {
    const деньги = ['amount', 'revenue', 'vat', 'price', 'diff_amount', 'mrc', 'over',
      'shortage', 'surplus', 'cost_amount', 'avg_price']
    return деньги.includes(поле) ? fmtMoney(v) : nf(v, 3)
  }
  return String(v)
}

export function StoreReportsPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { company } = useCompany()
  const [открыт, открыть] = useState<string | null>(null)
  const [станции, задатьСтанции] = useState<number[]>([])
  // Свёрнутые разделы: развёрнут тот, где сейчас смотрят. Пятнадцать отчётов
  // одним свитком читаются как список названий, а не как каталог.
  const [раздел, выбратьРаздел] = useState<string | null>(null)

  const { data: витрина } = useQuery({
    queryKey: ['store-reports', company.id],
    queryFn: getStoreNetworkReports,
  })
  const { data: парк } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const всеСтанции = (парк?.stations ?? []) as StoreStation[]

  const { data: отчёт, isLoading } = useQuery({
    queryKey: ['store-report', company.id, открыт, dateFrom, dateTo, станции],
    queryFn: () => getStoreNetworkReport(открыт as string, {
      dateFrom, dateTo, stations: станции,
    }),
    enabled: !!открыт,
  })

  const показ = useVisible(отчёт?.rows ?? [])
  const переключить = (id: number) => задатьСтанции(
    станции.includes(id) ? станции.filter((x) => x !== id) : [...станции, id])

  const группы = витрина?.groups ?? []
  const отчёты = витрина?.reports ?? []
  const видимые = раздел ? группы.filter((g) => g.key === раздел) : группы

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Отчёты сети</h3>
        <p className="max-w-4xl text-xs leading-relaxed text-muted-foreground">
          Тот же каталог, что в рабочем месте станции, — те же разделы и названия, но по всем
          АЗС и с разрезом по каждой. Клик по названию открывает отчёт на экране, кнопка рядом
          отдаёт тот же CSV, что и станция. Период берётся из шапки; без выбора станций
          считается вся сеть.
        </p>
      </div>

      {/* Разделы каталога — как пункты меню: отчёт ищут там, где работают */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" onClick={() => выбратьРаздел(null)}
          className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${раздел === null
            ? 'border-primary/60 bg-primary/10 font-medium text-foreground'
            : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
          Все
        </button>
        {группы.map((g) => (
          <button key={g.key} type="button" onClick={() => выбратьРаздел(g.key)}
            className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${раздел === g.key
              ? 'border-primary/60 bg-primary/10 font-medium text-foreground'
              : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
            {g.label}
          </button>
        ))}
      </div>

      {всеСтанции.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">АЗС:</span>
          <button type="button" onClick={() => задатьСтанции([])}
            className={`rounded-md border px-2 py-1 text-xs ${станции.length === 0
              ? 'border-primary/60 bg-primary/10 text-foreground'
              : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
            вся сеть
          </button>
          {всеСтанции.map((s) => (
            <button key={s.station_id} type="button" onClick={() => переключить(s.station_id)}
              className={`rounded-md border px-2 py-1 text-xs tabular-nums ${
                станции.includes(s.station_id)
                  ? 'border-primary/60 bg-primary/10 text-foreground'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
              {s.station_id}
            </button>
          ))}
        </div>
      )}

      <div className="space-y-2.5">
        {видимые.map((g) => {
          const свои = отчёты.filter((r) => r.group === g.key)
          const экраны = ЭКРАНЫ[g.key] ?? []
          if (!свои.length && !экраны.length) return null
          const развёрнут = раздел !== null || свои.some((r) => r.key === открыт) || g.key === 'torg'
          return (
            <details key={g.key} open={развёрнут}
                     className="rounded-lg border border-border/50 bg-card/40 px-3.5">
              <summary className="flex cursor-pointer list-none items-center gap-2 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
                <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-60 transition-transform [details[open]_&]:rotate-90" />
                {g.label}
                <span className="text-xs font-normal text-muted-foreground">— {g.hint}</span>
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {свои.length} отчётов
                </span>
              </summary>

              <ul className="mb-3 space-y-2">
                {свои.map((r) => (
                  <li key={r.key} className="flex items-start gap-2 text-sm">
                    <FileSpreadsheet className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <button type="button" onClick={() => открыть(открыт === r.key ? null : r.key)}
                        className={`text-left font-medium hover:text-primary ${
                          открыт === r.key ? 'text-primary' : ''}`}>
                        {r.title}
                      </button>
                      <span className="text-xs text-muted-foreground"> — {r.about}</span>
                      <a href={storeNetworkReportCsvUrl(r.key, { dateFrom, dateTo, stations: станции })}
                         className="ml-2 inline-flex items-center gap-1 whitespace-nowrap text-[11px] text-muted-foreground hover:text-foreground">
                        <Download className="h-3 w-3" />Excel
                      </a>
                    </div>
                  </li>
                ))}
              </ul>

              {экраны.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1.5 border-t border-border/40 pt-2.5">
                  {экраны.map((э) => (
                    <Link key={э.to} to={э.to} title={э.hint}
                      className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary">
                      <ExternalLink className="h-3 w-3" />{э.label}
                    </Link>
                  ))}
                </div>
              )}
            </details>
          )
        })}
      </div>

      {открыт && (
        <div className="rounded-lg border border-border/50">
          <div className="flex flex-wrap items-center gap-3 border-b border-border/40 px-3 py-2">
            <span className="text-sm font-medium">{отчёт?.title ?? 'Отчёт'}</span>
            <span className="text-[11px] text-muted-foreground">
              {станции.length === 0 ? 'вся сеть' : `АЗС ${станции.join(', ')}`} ·
              {' '}{dateFrom} — {dateTo}
            </span>
            <button type="button" onClick={() => открыть(null)}
              className="text-[11px] text-muted-foreground hover:text-foreground">свернуть</button>
            {отчёт && (
              <span className="ml-auto text-[11px] text-muted-foreground">
                {nf(отчёт.total)} строк
                {отчёт.revenue !== undefined && <> · выручка {fmtMoney(отчёт.revenue)}</>}
                {отчёт.stock_amount !== undefined && (
                  <> · остаток {fmtMoney(отчёт.stock_amount)} ·
                    {' '}в себестоимости {fmtMoney(отчёт.cost_amount ?? 0)}</>
                )}
                {отчёт.shortfall !== undefined && (
                  <> · недостача {fmtMoney(отчёт.shortfall)} · излишек {fmtMoney(отчёт.surplus ?? 0)}</>
                )}
                {отчёт.vat_deductible !== undefined && (
                  <> · к вычету {fmtMoney(отчёт.vat_deductible)} ·
                    {' '}не подтверждено {fmtMoney(отчёт.vat_unconfirmed ?? 0)}</>
                )}
                {отчёт.unexplained_total !== undefined && (
                  <> · необъяснено {nf(отчёт.unexplained_total, 3)} ед.</>
                )}
                {отчёт.violations !== undefined && (
                  <> · <span className={отчёт.violations ? 'text-destructive' : ''}>
                    нарушений {отчёт.violations}</span></>
                )}
                {отчёт.by_class && (
                  <> · A {отчёт.by_class.A} · B {отчёт.by_class.B} · C {отчёт.by_class.C}</>
                )}
              </span>
            )}
          </div>

          {/* Свод по станциям: сеть одной цифрой прячет провал отдельной точки */}
          {отчёт?.by_station && отчёт.by_station.length > 0 && (
            <div className="flex flex-wrap gap-3 border-b border-border/30 px-3 py-2 text-[11px]">
              {отчёт.by_station.map((s) => (
                <span key={s.station_id} className="text-muted-foreground">
                  АЗС {s.station_id}:{' '}
                  <span className="tabular-nums text-foreground">{nf(s.docs)}</span> строк ·
                  {' '}<span className="tabular-nums">{fmtMoney(s.amount)}</span>
                </span>
              ))}
            </div>
          )}

          {isLoading ? (
            <div className="px-3 py-6 text-sm text-muted-foreground">Считаем отчёт…</div>
          ) : !отчёт || отчёт.rows.length === 0 ? (
            <div className="px-3 py-6 text-sm text-muted-foreground">
              За период и выбранные станции строк нет.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted/30 text-muted-foreground">
                    <tr>
                      {отчёт.columns.map((c) => (
                        <th key={c} className="whitespace-nowrap px-3 py-2 text-left font-medium">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {показ.visible.map((r, i) => (
                      <tr key={i} className="border-t border-border/30">
                        {отчёт.fields.map((f) => (
                          <td key={f} className={`px-3 py-1.5 ${
                            typeof (r as Record<string, unknown>)[f] === 'number' ? 'text-right tabular-nums' : ''}`}>
                            {ячейка(f, (r as Record<string, unknown>)[f])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="строк" />
            </>
          )}
        </div>
      )}
    </div>
  )
}
