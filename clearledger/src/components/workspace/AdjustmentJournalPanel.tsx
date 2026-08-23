/**
 * Журнал корректировок за период — то, что спросят при разборе с бухгалтерией.
 *
 * Отменённые правки входят намеренно: журнал отвечает на вопрос «что делали», а
 * не «что осталось». Отменённая правка объясняет, почему цифра сначала
 * изменилась, а потом вернулась.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import {
  getЖурналПравок, type ЗаписьЖурнала,
} from '@/services/adjustmentService'
import { fmtMoney } from '@/services/analyticsService'
import { Button } from '@/components/ui/button'

const ИМЕНА_ВИДОВ: Record<string, string> = {
  retail_sale_sidegoods: 'Отчёт о розничных продажах',
  purchase: 'Поступление',
  production_release: 'Выпуск',
  inventory: 'Инвентаризация',
  gain: 'Оприходование',
  writeoff: 'Списание',
  transfer: 'Перемещение',
  return_purchase: 'Возврат поставщику',
  recipe: 'Техкарта',
}

const дата = (iso: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

/** Что именно изменила правка: поле, было, стало. Читается без пересборки пакета. */
function изменения(з: ЗаписьЖурнала): { товар: string; поле: string; было: unknown; стало: unknown }[] {
  const out: { товар: string; поле: string; было: unknown; стало: unknown }[] = []
  for (const строка of з.patch?.Строки ?? []) {
    const номер = String(строка.НомерСтроки ?? '')
    const было = з.prev_values?.Строки?.[номер] ?? {}
    const товар = String(было.Наименование ?? `строка ${номер}`)
    for (const [поле, стало] of Object.entries(строка)) {
      if (поле === 'НомерСтроки') continue
      out.push({ товар, поле, было: было[поле], стало })
    }
  }
  for (const [поле, стало] of Object.entries(з.patch?.Шапка ?? {})) {
    out.push({ товар: 'шапка', поле, было: з.prev_values?.Шапка?.[поле], стало })
  }
  return out
}

const показать = (v: unknown) =>
  v === null || v === undefined || v === '' ? '—' : String(v)

export function AdjustmentJournalPanel({ dateFrom, dateTo, companyId }: {
  dateFrom: string; dateTo: string; companyId: string
}) {
  const [автор, setАвтор] = useState('')
  const журнал = useQuery({
    queryKey: ['adjustments', 'journal', companyId, dateFrom, dateTo],
    queryFn: () => getЖурналПравок(dateFrom, dateTo),
  })

  const записи = useMemo(() => {
    const все = журнал.data?.Записи ?? []
    return автор ? все.filter((з) => з.author === автор) : все
  }, [журнал.data, автор])

  const выгрузить = () => {
    const шапка = ['Когда', 'АЗС', 'Дата смены', 'Документ', 'Товар', 'Поле',
      'Было', 'Стало', 'Влияние, ₽', 'Причина', 'Кто', 'Состояние']
    const строки = записи.flatMap((з) => изменения(з).map((и) => [
      дата(з.created_at), з.station_id ?? '', з.business_date ?? '',
      ИМЕНА_ВИДОВ[з.doc_kind] ?? з.doc_kind, и.товар, и.поле,
      показать(и.было), показать(и.стало),
      String(з.amount_delta ?? 0).replace('.', ','), з.reason, з.author,
      з.status === 'cancelled' ? 'отменена' : 'действует',
    ]))
    const csv = [шапка, ...строки]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(';'))
      .join('\r\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `Корректировки_${dateFrom}_${dateTo}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const влияние = журнал.data?.ВлияниеНаСумму ?? 0

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-base font-semibold">Журнал корректировок</h3>
          <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
            Все правки документов за период — что меняли, кто и почему. Отменённые тоже здесь:
            журнал отвечает, что делали, а не что осталось.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={выгрузить} disabled={записи.length === 0}>
          <Download className="mr-1.5 h-3.5 w-3.5" />
          Выгрузить в Excel
        </Button>
      </div>

      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-4">
        <Показатель метка="Правок за период" значение={String(журнал.data?.Всего ?? 0)} />
        <Показатель метка="Действуют" значение={String(журнал.data?.Действующих ?? 0)} />
        <Показатель
          метка="Влияние на суммы"
          значение={влияние === 0 ? '—' : `${влияние > 0 ? '+' : ''}${fmtMoney(влияние)}`}
          подсказка="на столько правки изменили суммы документов против факта станции"
        />
        <Показатель метка="Правили" значение={String(журнал.data?.Авторы.length ?? 0)} />
      </div>

      {(журнал.data?.Авторы.length ?? 0) > 1 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Автор:</span>
          <button
            onClick={() => setАвтор('')}
            className={`rounded-md border px-2 py-1 transition-colors ${
              автор === '' ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
          >
            все
          </button>
          {журнал.data?.Авторы.map((a) => (
            <button
              key={a}
              onClick={() => setАвтор(a === автор ? '' : a)}
              className={`rounded-md border px-2 py-1 transition-colors ${
                автор === a ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
            >
              {a}
            </button>
          ))}
        </div>
      )}

      {журнал.isLoading && <Пусто текст="Загружаем журнал…" />}
      {журнал.isError && <Пусто текст="Журнал не загрузился" />}
      {журнал.data && записи.length === 0 && (
        <Пусто текст="За этот период документы не правили." />
      )}

      {записи.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Когда</th>
                <th className="px-3 py-2 text-left font-medium">Смена</th>
                <th className="px-3 py-2 text-left font-medium">Документ</th>
                <th className="px-3 py-2 text-left font-medium">Что изменено</th>
                <th className="px-3 py-2 text-right font-medium">Влияние</th>
                <th className="px-3 py-2 text-left font-medium">Причина</th>
                <th className="px-3 py-2 text-left font-medium">Кто</th>
              </tr>
            </thead>
            <tbody>
              {записи.map((з) => {
                const отменена = з.status === 'cancelled'
                return (
                  <tr key={з.id} className={`border-t border-border/30 align-top ${отменена ? 'opacity-55' : ''}`}>
                    <td className="whitespace-nowrap px-3 py-2">
                      {дата(з.created_at)}
                      {отменена && (
                        <div className="text-[10px] text-muted-foreground">
                          отменена {дата(з.cancelled_at)}
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                      {з.business_date ?? '—'}
                      {з.station_id ? <div className="text-[10px]">АЗС{з.station_id}</div> : null}
                    </td>
                    <td className="px-3 py-2">{ИМЕНА_ВИДОВ[з.doc_kind] ?? з.doc_kind}</td>
                    <td className="px-3 py-2">
                      <div className={`space-y-0.5 ${отменена ? 'line-through' : ''}`}>
                        {изменения(з).map((и, i) => (
                          <div key={i}>
                            <span className="text-muted-foreground">{и.товар} · {и.поле}: </span>
                            <s className="text-muted-foreground/60">{показать(и.было)}</s>
                            {' → '}
                            <span className="font-medium">{показать(и.стало)}</span>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                      {з.amount_delta
                        ? `${з.amount_delta > 0 ? '+' : ''}${fmtMoney(з.amount_delta)}`
                        : '—'}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{з.reason}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{з.author}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Показатель({ метка, значение, подсказка }: {
  метка: string; значение: string; подсказка?: string
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3" title={подсказка}>
      <div className="text-[11px] text-muted-foreground">{метка}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{значение}</div>
    </div>
  )
}

function Пусто({ текст }: { текст: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
      {текст}
    </div>
  )
}
