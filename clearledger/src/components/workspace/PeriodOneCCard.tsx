/**
 * Что лежит в боевой 1С за период — взгляд из центра в реальную бухгалтерию.
 *
 * Отвечает на вопрос, которого раньше не было чем закрыть: как там на самом деле
 * идёт учёт. Сколько документов проведено, сколько висит непроведёнными и до
 * какой даты бухгалтерия закрыла период у себя.
 *
 * Читаем и только читаем: документы в 1С кладёт бухгалтер расширением, разбирая
 * нашу очередь. Здесь мы смотрим, а не правим.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Building2, Lock, RefreshCw, TriangleAlert } from 'lucide-react'

import { get } from '@/services/apiClient'
import { fmtMoney } from '@/services/analyticsService'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface ВидДокумента {
  Вид: string
  Всего: number
  Проведено: number
  Сумма: number
}

interface СрезБП {
  Прочитано: string
  Организация: string
  ДатаЗапрета: string | null
  Ошибка: string
  Итого: { Документов: number; Проведено: number; НеПроведено: number; Сумма: number }
  ПоВидам: ВидДокумента[]
  Документы: {
    Вид: string; Номер: string; Дата: string
    Сумма: number; Проведён: boolean; Комментарий: string
  }[]
}

const дата = (iso: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('ru-RU')
}

export function PeriodOneCCard({ dateFrom, dateTo, companyId, ourClosingDate }: {
  dateFrom: string
  dateTo: string
  companyId: string
  /** Наша граница закрытого периода: если строже бухгалтерской — это осознанно. */
  ourClosingDate?: string | null
}) {
  const [открыт, setОткрыт] = useState(false)

  const срез = useQuery({
    queryKey: ['onec-snapshot', companyId, dateFrom, dateTo],
    queryFn: () => get<СрезБП>('/api/accounting/adjustments/onec-snapshot', {
      date_from: dateFrom, date_to: dateTo,
    }),
    enabled: открыт,
    // Читать боевую базу дорого: одно COM-соединение на всех, и лицензий мало.
    // Кеш держим долго, обновление — по кнопке.
    staleTime: 10 * 60 * 1000,
    retry: false,
  })

  const д = срез.data

  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="flex flex-wrap items-center gap-2 px-4 py-3">
        <Building2 className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Что в бухгалтерии</h3>
        <span className="text-xs text-muted-foreground">
          боевая 1С — читаем, не правим
        </span>
        <div className="ml-auto flex items-center gap-2">
          {открыт && (
            <Button variant="ghost" size="sm" onClick={() => срез.refetch()}
              disabled={срез.isFetching}>
              <RefreshCw className={cn('h-3.5 w-3.5', срез.isFetching && 'animate-spin')} />
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setОткрыт((v) => !v)}>
            {открыт ? 'Свернуть' : 'Посмотреть в 1С'}
          </Button>
        </div>
      </header>

      {!открыт && (
        <p className="px-4 pb-3 text-xs text-muted-foreground">
          Запрос идёт в боевую базу по одному COM-соединению, поэтому открывается по
          кнопке, а не сам: лицензий столько же, сколько людей за работой.
        </p>
      )}

      {открыт && срез.isLoading && (
        <p className="px-4 pb-4 text-sm text-muted-foreground">Читаем боевую базу…</p>
      )}

      {открыт && (срез.isError || д?.Ошибка) && (
        <div className="mx-4 mb-4 flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/5 p-3 text-xs">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div>
            <div className="font-medium text-amber-200">Боевая база не прочитана</div>
            <p className="mt-0.5 text-muted-foreground">
              {д?.Ошибка || (срез.error as Error)?.message}
            </p>
          </div>
        </div>
      )}

      {открыт && д && !д.Ошибка && (
        <div className="space-y-3 px-4 pb-4">
          <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-4">
            <Показатель метка="Документов" значение={String(д.Итого.Документов)} />
            <Показатель метка="Проведено" значение={String(д.Итого.Проведено)} />
            <Показатель
              метка="Не проведено"
              значение={String(д.Итого.НеПроведено)}
              тревога={д.Итого.НеПроведено > 0}
              подсказка="ждут бухгалтера: проводит человек, не мы"
            />
            <Показатель
              метка="Сумма проведённого"
              значение={д.Итого.Сумма ? fmtMoney(д.Итого.Сумма) : '—'}
            />
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5" />
              Период закрыт в 1С по <b className="text-foreground">{дата(д.ДатаЗапрета)}</b>
            </span>
            {ourClosingDate && ourClosingDate !== (д.ДатаЗапрета ?? '') && (
              <span>
                у нас на станции — <b className="text-foreground">{дата(ourClosingDate)}</b>
                {ourClosingDate > (д.ДатаЗапрета ?? '')
                  ? ' (строже, чем бухгалтерия)'
                  : ' (мягче, чем бухгалтерия)'}
              </span>
            )}
            {д.Организация && <span>· {д.Организация}</span>}
            <span className="ml-auto">прочитано {new Date(д.Прочитано).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span>
          </div>

          {д.ПоВидам.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border/50">
              <table className="w-full text-xs">
                <thead className="bg-muted/30 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Вид документа</th>
                    <th className="px-3 py-2 text-right font-medium">Всего</th>
                    <th className="px-3 py-2 text-right font-medium">Проведено</th>
                    <th className="px-3 py-2 text-right font-medium">Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {д.ПоВидам.map((в) => {
                    const висят = в.Всего - в.Проведено
                    return (
                      <tr key={в.Вид} className="border-t border-border/30">
                        <td className="px-3 py-1.5">{в.Вид}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{в.Всего}</td>
                        <td className={cn('px-3 py-1.5 text-right tabular-nums',
                          висят > 0 && 'text-amber-300')}>
                          {в.Проведено}
                          {висят > 0 && <span className="text-muted-foreground"> (−{висят})</span>}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums">
                          {в.Сумма ? fmtMoney(в.Сумма) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {д.Итого.НеПроведено > 0 && (
            <p className="text-xs text-muted-foreground">
              Непроведённые документы период закрыть не дадут. Проводит их бухгалтер
              в 1С — мы только показываем, что они там есть.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function Показатель({ метка, значение, тревога, подсказка }: {
  метка: string; значение: string; тревога?: boolean; подсказка?: string
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3" title={подсказка}>
      <div className="text-[11px] text-muted-foreground">{метка}</div>
      <div className={cn('mt-0.5 text-lg font-semibold tabular-nums',
        тревога && 'text-amber-300')}>
        {значение}
      </div>
    </div>
  )
}
