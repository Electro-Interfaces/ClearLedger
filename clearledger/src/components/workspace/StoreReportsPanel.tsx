/**
 * «Магазин» → Отчёты.
 *
 * На станции такой раздел уже работает в рабочем месте агента: считает по
 * локальному учёту и отдаёт CSV. Здесь те же вопросы, заданные сети — не «что
 * на моей полке», а «что по всем АЗС и чем одна отличается от другой».
 *
 * Поэтому у каждого отчёта есть выбор станций и свод по ним: сеть, показанная
 * одной цифрой, прячет провал отдельной точки в средних. Выгрузка отдаёт тот
 * же CSV, что и станция, — файл открывается Excel двойным кликом, и офис со
 * станцией смотрят на один формат.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileSpreadsheet, Download, ChevronRight } from 'lucide-react'
import {
  getStoreNetworkReports, getStoreNetworkReport, storeNetworkReportCsvUrl, getStoreStations,
  type StoreStation,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { useCompany } from '@/contexts/CompanyContext'
import { ShowMore, useVisible } from '@/components/common/ShowMore'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Значение ячейки: даты и деньги читаются иначе, чем количества. */
function ячейка(поле: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (поле.endsWith('date') || поле === 'doc_date') {
    return new Date(String(v)).toLocaleDateString('ru-RU',
      { day: '2-digit', month: '2-digit', year: '2-digit' })
  }
  if (typeof v === 'number') {
    const деньги = ['amount', 'revenue', 'vat', 'price', 'diff_amount']
    return деньги.includes(поле) ? fmtMoney(v) : nf(v, 3)
  }
  return String(v)
}

export function StoreReportsPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { company } = useCompany()
  const [открыт, открыть] = useState<string | null>(null)
  const [станции, задатьСтанции] = useState<number[]>([])

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

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Отчёты</h3>
        <p className="text-xs text-muted-foreground">
          Те же отчёты, что считает рабочее место станции, но по сети: с разрезом по АЗС и
          выгрузкой в Excel. Период берётся из шапки; станции выбираются ниже — без выбора
          считается вся сеть.
        </p>
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

      <div className="grid gap-2.5 lg:grid-cols-2">
        {(витрина?.reports ?? []).map((r) => (
          <div key={r.key}
               className={`rounded-lg border p-3 transition-colors ${открыт === r.key
                 ? 'border-primary/50 bg-primary/5' : 'border-border/50 bg-card/40'}`}>
            <div className="flex items-start gap-2">
              <FileSpreadsheet className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <button type="button" onClick={() => открыть(открыт === r.key ? null : r.key)}
                  className="text-left text-sm font-medium hover:text-primary">
                  {r.title}
                  <ChevronRight className={`ml-1 inline h-3.5 w-3.5 transition-transform ${
                    открыт === r.key ? 'rotate-90' : ''}`} />
                </button>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{r.about}</p>
                <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px]">
                  <button type="button" onClick={() => открыть(r.key)}
                    className="text-primary hover:underline">открыть</button>
                  <a href={storeNetworkReportCsvUrl(r.key, { dateFrom, dateTo, stations: станции })}
                     className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
                    <Download className="h-3 w-3" />выгрузить в Excel
                  </a>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {открыт && (
        <div className="rounded-lg border border-border/50">
          <div className="flex flex-wrap items-center gap-3 border-b border-border/40 px-3 py-2">
            <span className="text-sm font-medium">{отчёт?.title ?? 'Отчёт'}</span>
            <span className="text-[11px] text-muted-foreground">
              {станции.length === 0 ? 'вся сеть' : `АЗС ${станции.join(', ')}`} ·
              {' '}{dateFrom} — {dateTo}
            </span>
            {отчёт && (
              <span className="ml-auto text-[11px] text-muted-foreground">
                {nf(отчёт.total)} строк
                {отчёт.shortfall !== undefined && (
                  <> · недовоз {fmtMoney(отчёт.shortfall)} · перевоз {fmtMoney(отчёт.surplus ?? 0)}</>
                )}
                {отчёт.vat_deductible !== undefined && (
                  <> · к вычету {fmtMoney(отчёт.vat_deductible)} ·
                    {' '}не подтверждено {fmtMoney(отчёт.vat_unconfirmed ?? 0)}</>
                )}
                {отчёт.unexplained_total !== undefined && (
                  <> · необъяснено {nf(отчёт.unexplained_total, 3)} ед.</>
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
                  <span className="tabular-nums text-foreground">{nf(s.docs)}</span> док ·
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
