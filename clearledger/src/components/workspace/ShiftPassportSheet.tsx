/**
 * Паспорт смены — карточка состояния, а не журнал ошибок.
 *
 * Отчёт о розничных продажах закрывает смену сводом, но сам по себе ничего не
 * объясняет: рядом лежат выпуск блюд, техкарты, чеки и кассовая смена, а
 * приёмки и пересчёты в неё не входят вовсе — они её условие. Менеджеру нужно
 * одно место, где видно и то и другое, и главное — что сделать, чтобы смена
 * ушла в бухгалтерию.
 */
import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, LoaderCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { getStoreShiftPassport, type StoreShiftPassport } from '@/services/storeDocumentsService'

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
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n) + ' ₽'

const время = (value: string | null) =>
  value
    ? new Date(value).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
      })
    : '—'

export function ShiftPassportSheet({
  station, shift, onClose, onOpenDocuments,
}: {
  station: number | null
  shift: number | null
  onClose: () => void
  onOpenDocuments?: (station: number, shift: number) => void
}) {
  const [passport, setPassport] = useState<StoreShiftPassport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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

  const выверена = passport?.status === 'complete'

  return (
    <Sheet open={station != null && shift != null} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-2xl">
        <SheetHeader className="border-b pr-14">
          <SheetTitle className="flex items-center gap-2">
            Смена № {shift}
            {passport && (
              <Badge variant={выверена ? 'secondary' : 'destructive'}>
                {выверена ? 'выверена' : 'нужна выверка'}
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription>
            АЗС {station} · {время(passport?.started_at ?? null)} — {время(passport?.finished_at ?? null)}
          </SheetDescription>
        </SheetHeader>

        {loading && (
          <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Собираю паспорт…
          </div>
        )}
        {error && <div className="p-6 text-sm text-destructive">{error}</div>}

        {passport && (
          <div className="space-y-6 p-6">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Kpi label="Выручка" value={money(passport.revenue)} />
              <Kpi label="НДС" value={passport.vat == null ? '—' : money(passport.vat)} />
              <Kpi label="Чеков" value={String(passport.cheques)} />
              <Kpi label="Документов" value={String(passport.documents)} />
            </div>

            {passport.actions.length > 0 ? (
              <section>
                <h3 className="mb-2 text-sm font-medium">Что сделать</h3>
                <ul className="space-y-2">
                  {passport.actions.map((действие) => (
                    <li
                      key={действие.code}
                      className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm"
                    >
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
                        <div>
                          <div>{действие.text}</div>
                          {действие.hint && (
                            <div className="mt-1 text-xs text-muted-foreground">{действие.hint}</div>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : (
              <div className="flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm">
                <CheckCircle2 className="size-4 text-emerald-500" />
                Смена выверена, к бухгалтерии готова
              </div>
            )}

            <section>
              <h3 className="mb-2 text-sm font-medium">Из чего состоит</h3>
              <table className="w-full text-sm">
                <tbody>
                  {passport.composition.map((строка) => (
                    <tr key={строка.kind} className="border-b last:border-0">
                      <td className="py-1.5">{KIND_LABELS[строка.kind] ?? строка.kind}</td>
                      <td className="py-1.5 text-right tabular-nums text-muted-foreground">{строка.count}</td>
                      <td className="py-1.5 text-right tabular-nums">
                        {строка.amount ? money(строка.amount) : '—'}
                      </td>
                      <td className="py-1.5 pl-3 text-right">
                        {строка.attention > 0 && (
                          <Badge variant="outline" className="text-amber-500">
                            внимание: {строка.attention}
                          </Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {onOpenDocuments && station != null && shift != null && (
                <button
                  type="button"
                  onClick={() => onOpenDocuments(station, shift)}
                  className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  Открыть все документы смены <ArrowRight className="size-3" />
                </button>
              )}
            </section>

            {passport.cost_estimated.length > 0 && (
              <section>
                <h3 className="mb-1 text-sm font-medium">Себестоимость по оценке центра</h3>
                <p className="text-xs text-muted-foreground">
                  {passport.cost_estimated.length} ингредиентов посчитаны оценкой: своей закупки по ним
                  нет. Пока это так, смена в бухгалтерию не уйдёт без явного решения.
                </p>
              </section>
            )}

            {passport.influenced_by.length > 0 && (
              <section>
                <h3 className="mb-1 text-sm font-medium">Повлияло на смену</h3>
                <p className="mb-2 text-xs text-muted-foreground">
                  Эти документы в смену не входят, но меняют её остаток.
                </p>
                <table className="w-full text-sm">
                  <tbody>
                    {passport.influenced_by.map((док) => (
                      <tr key={док.record_id} className="border-b last:border-0">
                        <td className="py-1.5">{KIND_LABELS[док.kind] ?? док.kind}</td>
                        <td className="py-1.5 text-muted-foreground">{док.number ?? '—'}</td>
                        <td className="py-1.5 text-muted-foreground">{док.counterparty ?? '—'}</td>
                        <td className="py-1.5 text-right tabular-nums">{money(док.amount)}</td>
                        <td className="py-1.5 pl-2 text-right text-xs text-muted-foreground">
                          {док.operational_status ?? ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-base font-medium tabular-nums">{value}</div>
    </div>
  )
}
