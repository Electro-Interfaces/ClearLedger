/**
 * Таблица результатов валидации — левый цветной бордюр вместо фона строки (dark-safe).
 */

import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronRight, ArrowUpDown } from 'lucide-react'
import type { EntryValidationResult } from '@/types'

interface Props {
  results: EntryValidationResult[]
}

type SortKey = 'title' | 'errors' | 'completeness'

export function ValidationResultsTable({ results }: Props) {
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('errors')

  const filtered = useMemo(() => {
    let items = results
    if (search) {
      const q = search.toLowerCase()
      items = items.filter((r) => r.entryTitle.toLowerCase().includes(q))
    }
    return [...items].sort((a, b) => {
      if (sortKey === 'errors') return (b.errorCount + b.warningCount) - (a.errorCount + a.warningCount)
      if (sortKey === 'completeness') return a.completeness - b.completeness
      return a.entryTitle.localeCompare(b.entryTitle, 'ru')
    })
  }, [results, search, sortKey])

  const cycleSortKey = () => {
    setSortKey((prev) => {
      if (prev === 'errors') return 'completeness'
      if (prev === 'completeness') return 'title'
      return 'errors'
    })
  }

  const sortLabels: Record<SortKey, string> = {
    errors: 'по ошибкам',
    completeness: 'по полноте',
    title: 'по названию',
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Input
          placeholder="Поиск по названию..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <Button variant="outline" size="sm" onClick={cycleSortKey} className="shrink-0 gap-1.5">
          <ArrowUpDown className="size-3.5" />
          {sortLabels[sortKey]}
        </Button>
      </div>

      {filtered.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">
          {results.length === 0 ? 'Запустите нормализацию для получения результатов' : 'Ничего не найдено'}
        </div>
      ) : (
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="w-[30px]" />
                <th className="text-left p-3 font-medium">Название</th>
                <th className="text-left p-3 font-medium w-[120px]">Полнота</th>
                <th className="text-left p-3 font-medium w-[100px]">Ошибки</th>
                <th className="text-left p-3 font-medium w-[130px]">Предупреждения</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <IssueRow
                  key={r.entryId}
                  r={r}
                  isExpanded={expandedId === r.entryId}
                  onToggle={() => setExpandedId(expandedId === r.entryId ? null : r.entryId)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {results.length}</p>
    </div>
  )
}

/** Цвет левого бордюра — по severity */
function borderColor(r: EntryValidationResult): string {
  if (r.errorCount > 0) return 'hsl(0 84% 60%)'     // red
  if (r.warningCount > 0) return 'hsl(45 100% 55%)'  // yellow
  return 'hsl(120 100% 40%)'                          // green
}

/** Inline-bar цвет полноты */
function completenessColor(pct: number): string {
  if (pct >= 80) return 'hsl(120 100% 40%)'
  if (pct >= 50) return 'hsl(45 100% 55%)'
  return 'hsl(0 84% 60%)'
}

function IssueRow({
  r,
  isExpanded,
  onToggle,
}: {
  r: EntryValidationResult
  isExpanded: boolean
  onToggle: () => void
}) {
  const hasIssues = r.issues.length > 0
  return (
    <>
      <tr
        className={`border-b last:border-0 hover:bg-muted/30 ${hasIssues ? 'cursor-pointer' : ''}`}
        style={{ borderLeft: `3px solid ${borderColor(r)}` }}
        onClick={hasIssues ? onToggle : undefined}
      >
        <td className="pl-2 pr-0 py-3">
          {hasIssues && (
            isExpanded
              ? <ChevronDown className="size-4 text-muted-foreground" />
              : <ChevronRight className="size-4 text-muted-foreground" />
          )}
        </td>
        <td className="p-3">
          <Link
            to={`/data/${r.categoryId}/${r.entryId}`}
            className="font-medium text-primary hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {r.entryTitle}
          </Link>
        </td>
        <td className="p-3">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${r.completeness}%`, backgroundColor: completenessColor(r.completeness) }}
              />
            </div>
            <span className="text-xs text-muted-foreground w-8 text-right">{r.completeness}%</span>
          </div>
        </td>
        <td className="p-3">
          {r.errorCount > 0 ? (
            <Badge variant="destructive" className="text-xs">{r.errorCount}</Badge>
          ) : (
            <span className="text-xs text-muted-foreground">0</span>
          )}
        </td>
        <td className="p-3">
          {r.warningCount > 0 ? (
            <Badge variant="outline" className="text-xs border-yellow-500 text-yellow-400">{r.warningCount}</Badge>
          ) : (
            <span className="text-xs text-muted-foreground">0</span>
          )}
        </td>
      </tr>
      {isExpanded && r.issues.length > 0 && (
        <tr>
          <td />
          <td colSpan={4} className="px-3 pb-3">
            <div className="space-y-1.5 ml-1 border-l-2 border-muted pl-3 pt-1">
              {r.issues.map((issue, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <span
                    className="inline-block w-1.5 h-1.5 rounded-full shrink-0 mt-1.5"
                    style={{
                      backgroundColor: issue.severity === 'error'
                        ? 'hsl(0 84% 60%)'
                        : 'hsl(45 100% 55%)',
                    }}
                  />
                  <span className="text-foreground font-medium">{issue.label}:</span>
                  <span className="text-muted-foreground">{issue.message}</span>
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
