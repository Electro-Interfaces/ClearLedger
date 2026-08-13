/**
 * Просмотрщик документа бухгалтерии — окном поверх того места, откуда открыли.
 *
 * Реестр отвечает «какие документы есть», карточка контрагента — «что у нас с ним»,
 * и оба заканчиваются строкой таблицы. Дальше человеку нужен САМ документ: из чего
 * сложилась сумма и какими проводками он лёг в учёт. Без этого следующий шаг —
 * открыть 1С и искать документ там, то есть выйти из пространства.
 *
 * Компонент общий: его открывают и офисные панели («Реализация», «Бухгалтерия»), и
 * ядровой экран «Контрагенты». Поэтому он живёт отдельным файлом, а не внутри панели.
 */
import { useQuery } from '@tanstack/react-query'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { getDocumentCard } from '@/services/booksService'

const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const qty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })

/** Подписи реквизитов из 1С: ключи приезжают как есть, показывать их сырыми нельзя. */
const META_LABELS: Record<string, string> = {
  'ВидОперации': 'Вид операции',
  'Договор': 'Договор',
  'Комментарий': 'Комментарий',
  'НомерВходящего': 'Входящий номер',
  'Проведен': 'Проведён',
  'Содержание': 'Содержание',
  'time': 'Время проведения',
  'purpose': 'Назначение платежа',
  'proved': 'Проведён',
}

export function DocumentWindow({ companyId, docId, onClose }: {
  companyId: string; docId: string; onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['books', 'document', companyId, docId],
    queryFn: () => getDocumentCard(companyId, docId),
  })
  const d = q.data
  const linesTotal = (d?.lines ?? []).reduce((s, l) => s + l.amount, 0)
  // Строки должны сходиться с шапкой: расхождение значит, что документ приехал
  // неполным, и цифра в реестре не подтверждается его же содержимым.
  const linesMismatch = !!d && d.lines.length > 0 && Math.abs(linesTotal - d.amount) > 1

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">
            {d?.label ?? 'Документ'}
            {d && <span className="ml-2 font-normal text-muted-foreground">
              № {d.number} от {d.date}
            </span>}
          </DialogTitle>
        </DialogHeader>
        {q.isError && <QueryError onRetry={() => q.refetch()} />}
        {!d ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
            <Card>
              <CardContent className="p-4 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                <Row label="Контрагент"
                  value={d.counterparty?.name ?? d.counterpartyName}
                  hint={d.counterpartyInn ? `ИНН ${d.counterpartyInn}` : undefined} />
                <Row label="Договор" value={d.contract
                  ? `${d.contract.type}${d.contract.number ? ` № ${d.contract.number}` : ''}`
                  : undefined} />
                <Row label="Сумма" value={`${money.format(d.amount)} ₽`}
                  hint={d.vat ? `в т. ч. НДС ${money.format(d.vat)} ₽` : undefined} />
                <Row label="Состояние"
                  value={`${d.status}${d.periodStatus === 'closed' ? ' · период закрыт' : ''}`} />
                {d.externalNumber && (
                  <Row label="Входящий документ"
                    value={`№ ${d.externalNumber}${d.externalDate ? ` от ${d.externalDate}` : ''}`} />
                )}
                {Object.entries(d.meta).map(([k, v]) => (
                  <Row key={k} label={META_LABELS[k] ?? k} value={String(v)} />
                ))}
              </CardContent>
            </Card>

            {d.lines.length > 0 && (
              <Card>
                <CardContent className="p-0 overflow-x-auto">
                  <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">
                    Строки — {d.lines.length}
                    {linesMismatch && (
                      <span className="ml-2 text-amber-600 dark:text-amber-400">
                        сумма строк {money.format(linesTotal)} ₽ не сходится с шапкой
                      </span>
                    )}
                  </div>
                  <table className="w-full text-sm">
                    <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                      <tr className="border-b">
                        <th className="text-left font-normal px-3 py-2">Позиция</th>
                        <th className="text-left font-normal px-3 py-2 w-[120px]">Код</th>
                        <th className="text-right font-normal px-3 py-2 w-[90px]">Кол-во</th>
                        <th className="text-right font-normal px-3 py-2 w-[110px]">Цена</th>
                        <th className="text-right font-normal px-3 py-2 w-[120px]">Сумма</th>
                        <th className="text-right font-normal px-3 py-2 w-[110px]">НДС</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.lines.map((l, i) => (
                        <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                          <td className="px-3 py-1.5 max-w-[360px] truncate" title={l.name}>
                            {l.name}
                            {l.kind === 'service' && (
                              <span className="ml-1.5 text-[10px] text-muted-foreground">услуга</span>
                            )}
                          </td>
                          <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                            {l.code ?? '—'}
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{qty.format(l.qty)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{money.format(l.price)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{money.format(l.amount)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                            {l.vat ? money.format(l.vat) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardContent className="p-0 overflow-x-auto">
                <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">
                  {d.entries.length
                    ? `Проводки — ${d.entries.length}`
                    : 'Проводок нет: документ не отражён в регистре или не сведён с ним'}
                </div>
                {d.entries.length > 0 && (
                  <table className="w-full text-sm">
                    <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                      <tr className="border-b">
                        <th className="text-left font-normal px-3 py-2 w-[110px]">Дата</th>
                        <th className="text-left font-normal px-3 py-2 w-[90px]">Дт</th>
                        <th className="text-left font-normal px-3 py-2 w-[90px]">Кт</th>
                        <th className="text-right font-normal px-3 py-2 w-[140px]">Сумма</th>
                        <th className="text-left font-normal px-3 py-2">Содержание</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.entries.map((e, i) => (
                        <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                          <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{e.date}</td>
                          <td className="px-3 py-1.5 tabular-nums">{e.accountDt ?? '—'}</td>
                          <td className="px-3 py-1.5 tabular-nums">{e.accountKt ?? '—'}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            {money.format(e.amount)}
                          </td>
                          <td className="px-3 py-1.5 text-muted-foreground max-w-[320px] truncate"
                            title={e.content ?? ''}>{e.content}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Row({ label, value, hint }: { label: string; value?: string; hint?: string }) {
  return (
    <div className="flex gap-2">
      <span className="w-40 shrink-0 text-muted-foreground">{label}</span>
      <span className={cn('min-w-0 break-words', !value && 'text-muted-foreground')}>
        {value || '—'}
        {hint && <span className="ml-2 text-xs text-muted-foreground">{hint}</span>}
      </span>
    </div>
  )
}
