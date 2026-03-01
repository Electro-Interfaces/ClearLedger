/**
 * Таблица результатов обогащения — dark-safe цвета через HSL и semantic Badge.
 */

import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { CheckCheck } from 'lucide-react'
import type { EntryEnrichmentResult } from '@/types'

interface Props {
  results: EntryEnrichmentResult[]
  onApply: (entryId: string, enrichment: Record<string, string>) => void
  isPending?: boolean
}

export function EnrichmentResultsTable({ results, onApply, isPending }: Props) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return results
    const q = search.toLowerCase()
    return results.filter((r) =>
      r.entryTitle.toLowerCase().includes(q) ||
      r.counterpartyMatch?.name.toLowerCase().includes(q),
    )
  }, [results, search])

  const pendingApply = useMemo(
    () => filtered.filter((r) => !r.enrichmentApplied && Object.keys(r.fullEnrichment).length > 0),
    [filtered],
  )

  if (results.length === 0) {
    return (
      <div className="text-center text-muted-foreground py-12">
        Запустите нормализацию для получения результатов
      </div>
    )
  }

  const handleApplyAll = () => {
    for (const r of pendingApply) {
      onApply(r.entryId, r.fullEnrichment)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Input
          placeholder="Поиск по названию или контрагенту..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        {pendingApply.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleApplyAll}
            disabled={isPending}
            className="shrink-0 gap-1.5"
          >
            <CheckCheck className="size-3.5" />
            Принять все ({pendingApply.length})
          </Button>
        )}
      </div>

      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left p-3 font-medium">Название</th>
              <th className="text-left p-3 font-medium w-[180px]">Контрагент</th>
              <th className="text-left p-3 font-medium w-[140px]">Договор</th>
              <th className="text-left p-3 font-medium w-[90px]">Комплект</th>
              <th className="text-left p-3 font-medium w-[120px]">Действия</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => {
              const hasData = Object.keys(r.fullEnrichment).length > 0
              return (
                <tr key={r.entryId} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="p-3 font-medium text-foreground">{r.entryTitle}</td>
                  <td className="p-3">
                    {r.counterpartyMatch ? (
                      <div>
                        <span className="text-sm text-foreground">{r.counterpartyMatch.name}</span>
                        <span className="ml-1.5 text-xs text-muted-foreground">
                          {Math.round(r.counterpartyMatch.confidence * 100)}%
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="p-3">
                    {r.contractMatch ? (
                      <span className="text-sm text-foreground">{r.contractMatch.number}</span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="p-3 text-center">
                    {r.bundleSuggestionCount > 0 ? (
                      <Badge variant="secondary" className="text-xs">{r.bundleSuggestionCount}</Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="p-3">
                    {r.enrichmentApplied ? (
                      <Badge variant="outline" className="text-xs border-green-500 text-green-400">Применено</Badge>
                    ) : hasData ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={isPending}
                        onClick={() => onApply(r.entryId, r.fullEnrichment)}
                      >
                        Принять
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Показано {filtered.length} из {results.length}
        {pendingApply.length > 0 && ` · ${pendingApply.length} ожидают применения`}
      </p>
    </div>
  )
}
