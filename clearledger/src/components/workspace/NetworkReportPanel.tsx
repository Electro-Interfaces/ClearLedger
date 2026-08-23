/**
 * Отчёт сети на экране — один компонент на все виды.
 *
 * Отчёты уже считались на сервере и уходили файлом из витрины «Отчёты»: чтобы
 * посмотреть оборотку по сети, человек скачивал xlsx и открывал Excel. Для
 * вопроса «что вообще происходит» это дорого: файл нужен, когда цифру несут
 * дальше, а не когда на неё смотрят.
 *
 * Второй панели каждому отчёту не требуется: ответ API самоописателен — несёт
 * заголовок, пояснение, имена колонок и поля строк. Шесть панелей-близнецов
 * разошлись бы между собой за месяц, эта — не может по устройству.
 *
 * Итоги показываем те, что отчёт сам про себя знает (недовоз, НДС к вычету,
 * необъяснённая разница): их набор у каждого свой, поэтому берём по наличию,
 * а не по общему списку.
 */
import { useQuery } from '@tanstack/react-query'
import { Download, Loader2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { fmtMoney } from '@/services/analyticsService'
import {
  getStoreNetworkReport, скачатьОтчётСети, type StoreReportData,
} from '@/services/storeService'

const nf = (n: number, d = 0) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Итоги, которые отчёты кладут рядом со строками. Показываем что есть. */
const ИТОГИ: { поле: keyof StoreReportData; метка: string; деньги?: boolean }[] = [
  { поле: 'total', метка: 'Строк' },
  { поле: 'amount', метка: 'Сумма', деньги: true },
  { поле: 'revenue', метка: 'Выручка', деньги: true },
  { поле: 'stock_amount', метка: 'Запас', деньги: true },
  { поле: 'cost_amount', метка: 'Себестоимость', деньги: true },
  { поле: 'shortfall', метка: 'Недовоз', деньги: true },
  { поле: 'surplus', метка: 'Перевоз', деньги: true },
  { поле: 'vat_deductible', метка: 'НДС к вычету', деньги: true },
  { поле: 'vat_unconfirmed', метка: 'НДС без документа', деньги: true },
  { поле: 'unexplained_total', метка: 'Не объяснено', деньги: true },
  { поле: 'violations', метка: 'Нарушений' },
]

// Числовую колонку узнаём по значению, а не по имени поля: имена задаёт
// сервер, и список «какие из них числа» разошёлся бы с ним при первом же
// новом отчёте.
const число = (v: unknown) => typeof v === 'number'

const ячейка = (v: unknown) => {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (typeof v === 'number') return nf(v, Number.isInteger(v) ? 0 : 2)
  if (Array.isArray(v)) return v.join(', ')
  return String(v)
}

export function NetworkReportPanel({ kind, dateFrom, dateTo, stations }: {
  kind: string
  dateFrom: string
  dateTo: string
  stations?: number[]
}) {
  const [скачивается, скачивать] = useState(false)
  const отчёт = useQuery({
    queryKey: ['network-report', kind, dateFrom, dateTo, stations],
    queryFn: () => getStoreNetworkReport(kind, { dateFrom, dateTo, stations }),
  })

  const д = отчёт.data
  const строки = д?.rows ?? []
  const показ = useVisible(строки)

  const скачать = async () => {
    скачивать(true)
    try {
      await скачатьОтчётСети(kind, { dateFrom, dateTo, stations, format: 'xlsx' })
    } finally {
      скачивать(false)
    }
  }

  if (отчёт.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Считаем по сети…</div>
  }
  if (отчёт.error) {
    return (
      <div className="p-6 text-sm text-red-400/90">
        Отчёт не собрался: {(отчёт.error as Error).message}
      </div>
    )
  }
  if (!д) return null

  const итоги = ИТОГИ.filter(({ поле }) => typeof д[поле] === 'number')

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">{д.title}</h3>
          {д.about && (
            <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              {д.about}
            </p>
          )}
        </div>
        <Button variant="outline" size="sm" className="ml-auto h-8 gap-1.5 text-xs"
          onClick={скачать} disabled={скачивается}>
          {скачивается
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Download className="h-3.5 w-3.5" />}
          Выгрузить в Excel
        </Button>
      </div>

      {итоги.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {итоги.map(({ поле, метка, деньги }) => (
            <div key={поле} className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">{метка}</div>
              <div className="mt-0.5 text-lg font-semibold tabular-nums">
                {деньги ? fmtMoney(д[поле] as number) : nf(д[поле] as number)}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              {д.columns.map((c, i) => (
                <th key={i} className="whitespace-nowrap px-3 py-2 text-left font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {показ.visible.map((строка, ri) => (
              <tr key={ri} className="border-t border-border/30 hover:bg-accent/20">
                {д.fields.map((f, ci) => (
                  <td key={ci}
                    className={`px-3 py-1.5 ${число(строка[f]) ? 'text-right tabular-nums' : ''}`}>
                    {ячейка(строка[f])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {строки.length > 300 && (
          <ShowMore {...показ} onMore={показ.more} onAll={показ.all} />
        )}
        {строки.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            За выбранный период и контур строк нет.
          </div>
        )}
      </div>
    </div>
  )
}
