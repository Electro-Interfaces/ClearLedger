/**
 * Side-by-side сравнение документа 1С и DataEntry.
 * Подсветка различий в суммах, датах, номенклатуре.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Unlink } from 'lucide-react'
import type { AccountingDoc, DataEntry } from '@/types'
import { DOC_TYPE_LABELS } from '@/config/statuses'

interface Props {
  doc: AccountingDoc
  entry?: DataEntry
  onUnmatch?: () => void
}

function FieldRow({ label, left, right }: { label: string; left: string; right: string }) {
  const isDiff = left !== right && left && right
  return (
    <div className="grid grid-cols-[120px_1fr_1fr] gap-2 py-1.5 border-b last:border-0">
      <span className="text-xs text-muted-foreground font-medium">{label}</span>
      <span className="text-sm font-mono">{left || '—'}</span>
      <span className={`text-sm font-mono ${isDiff ? 'text-red-600 font-semibold' : ''}`}>
        {right || '—'}
      </span>
    </div>
  )
}

export function MatchView({ doc, entry, onUnmatch }: Props) {
  const meta = entry?.metadata || {}

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Сравнение документов</CardTitle>
          {onUnmatch && (doc.matchStatus === 'matched' || doc.matchStatus === 'discrepancy') && (
            <Button variant="outline" size="sm" onClick={onUnmatch}>
              <Unlink className="size-3.5 mr-1.5" />
              Разорвать
            </Button>
          )}
        </div>
        {doc.matchDetails && typeof doc.matchDetails.score === 'number' && (
          <div className="flex gap-2 mt-1">
            <Badge variant="outline">Score: {doc.matchDetails.score}</Badge>
            {doc.matchDetails.amountDiff != null && Math.abs(doc.matchDetails.amountDiff) > 0.01 && (
              <Badge variant="destructive">
                Разница суммы: {doc.matchDetails.amountDiff > 0 ? '+' : ''}{doc.matchDetails.amountDiff.toFixed(2)}
              </Badge>
            )}
            {doc.matchDetails.dateDiff != null && doc.matchDetails.dateDiff > 0 && (
              <Badge variant="secondary">
                Разница дат: {doc.matchDetails.dateDiff} дн.
              </Badge>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-[120px_1fr_1fr] gap-2 pb-2 border-b mb-2">
          <span />
          <span className="text-xs font-semibold text-muted-foreground">Документ 1С</span>
          <span className="text-xs font-semibold text-muted-foreground">ClearLedger</span>
        </div>

        <FieldRow
          label="Тип"
          left={DOC_TYPE_LABELS[doc.docType] || doc.docType}
          right={entry?.title || '—'}
        />
        <FieldRow
          label="Номер"
          left={doc.number}
          right={meta.docNumber || '—'}
        />
        <FieldRow
          label="Дата"
          left={doc.date}
          right={meta.docDate || '—'}
        />
        <FieldRow
          label="Контрагент"
          left={doc.counterpartyName}
          right={meta.counterparty || '—'}
        />
        <FieldRow
          label="ИНН"
          left={doc.counterpartyInn || ''}
          right={meta.inn || '—'}
        />
        <FieldRow
          label="Сумма"
          left={doc.amount.toLocaleString('ru-RU', { minimumFractionDigits: 2 })}
          right={meta.amount || '—'}
        />
        <FieldRow
          label="НДС"
          left={doc.vatAmount != null ? doc.vatAmount.toLocaleString('ru-RU', { minimumFractionDigits: 2 }) : '—'}
          right={meta.vatAmount || '—'}
        />

        {doc.lines.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold text-muted-foreground mb-2">
              Строки документа 1С ({doc.lines.length})
            </p>
            <div className="rounded border overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-muted/50">
                    <th className="text-left p-1.5">Номенклатура</th>
                    <th className="text-right p-1.5 w-16">Кол-во</th>
                    <th className="text-right p-1.5 w-20">Цена</th>
                    <th className="text-right p-1.5 w-24">Сумма</th>
                    <th className="text-right p-1.5 w-14">НДС%</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.lines.map((line, i) => (
                    <tr key={i} className="border-t">
                      <td className="p-1.5">{line.nomenclatureName}</td>
                      <td className="text-right p-1.5 font-mono">{line.quantity}</td>
                      <td className="text-right p-1.5 font-mono">{line.price.toFixed(2)}</td>
                      <td className="text-right p-1.5 font-mono">{line.amount.toFixed(2)}</td>
                      <td className="text-right p-1.5">{line.vatRate}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
