/**
 * Таб "Документы 1С" на странице справочников.
 * Таблица + импорт + кнопка сверки.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RefreshCw, GitCompare } from 'lucide-react'
import { AccountingDocsTable } from '@/components/reconciliation/AccountingDocsTable'
import { ImportAccountingDocs } from '@/components/reference/ImportAccountingDocs'
import {
  useAccountingDocs,
  useDeleteAccountingDoc,
  useRunReconciliation,
  useUnmatch,
} from '@/hooks/useAccountingDocs'

export function AccountingDocsTab() {
  const { data = [], isLoading } = useAccountingDocs()
  const deleteMut = useDeleteAccountingDoc()
  const unmatchMut = useUnmatch()
  const runReconciliation = useRunReconciliation()
  const navigate = useNavigate()
  const [showImport, setShowImport] = useState(data.length === 0)

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
        ))}
      </div>
    )
  }

  // Статистика по типам
  const typeCounts = data.reduce<Record<string, number>>((acc, d) => {
    acc[d.docType] = (acc[d.docType] || 0) + 1
    return acc
  }, {})

  // Период
  const dates = data.map((d) => d.date).filter(Boolean).sort()
  const dateRange = dates.length > 0
    ? `${dates[0]} — ${dates[dates.length - 1]}`
    : '—'

  return (
    <div className="space-y-6">
      {/* Статистика + кнопки */}
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{data.length} документов</Badge>
            <Badge variant="secondary">Период: {dateRange}</Badge>
          </div>
          {Object.keys(typeCounts).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(typeCounts).map(([type, count]) => (
                <Badge key={type} variant="outline" className="text-xs">
                  {type}: {count}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowImport(!showImport)}
          >
            {showImport ? 'Скрыть импорт' : 'Импорт XML'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => runReconciliation.mutate()}
            disabled={runReconciliation.isPending || data.length === 0}
          >
            <RefreshCw className={`size-3.5 mr-1.5 ${runReconciliation.isPending ? 'animate-spin' : ''}`} />
            Запустить сверку
          </Button>
          <Button
            size="sm"
            onClick={() => navigate('/reconciliation')}
          >
            <GitCompare className="size-3.5 mr-1.5" />
            Результаты сверки
          </Button>
        </div>
      </div>

      {/* Импорт */}
      {showImport && (
        <ImportAccountingDocs onImported={() => setShowImport(false)} />
      )}

      {/* Таблица */}
      <AccountingDocsTable
        docs={data}
        onDelete={(id) => deleteMut.mutate(id)}
        onUnmatch={(id) => unmatchMut.mutate(id)}
      />
    </div>
  )
}
