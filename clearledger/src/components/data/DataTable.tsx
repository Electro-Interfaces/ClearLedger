import { useState, useMemo, memo, useCallback } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { StatusBadge } from './StatusBadge'
import { SourceBadge } from './SourceBadge'
import { useIsMobile } from '@/hooks/use-mobile'
import { formatDate } from '@/lib/formatDate'
import type { DataEntry } from '@/types'
import { ArrowUpDown, FolderTree, ShieldCheck } from 'lucide-react'

type SortField = 'title' | 'createdAt' | 'source' | 'status'
type SortDirection = 'asc' | 'desc'

const AUDITOR_STATUS_MAP: Record<string, { label: string; className: string }> = {
  approved: { label: 'OK', className: 'border-green-500 text-green-500' },
  needs_review: { label: 'Проверить', className: 'border-yellow-500 text-yellow-500' },
  rejected: { label: 'Отклонён', className: 'border-red-500 text-red-500' },
}

function AuditorBadge({ entry }: { entry: DataEntry }) {
  const vs = entry.metadata._verificationStatus
  if (!vs) return null
  const cfg = AUDITOR_STATUS_MAP[vs]
  if (!cfg) return null

  const confidence = entry.metadata._verificationConfidence
  const fails = entry.metadata._verificationFails
  const warnings = entry.metadata._verificationWarnings

  const tooltipText = [
    confidence && `Уверенность: ${confidence}%`,
    fails && fails !== '0' && `Ошибок: ${fails}`,
    warnings && warnings !== '0' && `Предупреждений: ${warnings}`,
  ].filter(Boolean).join(', ')

  const badge = (
    <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${cfg.className}`}>
      {cfg.label}
    </Badge>
  )

  if (tooltipText) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{badge}</TooltipTrigger>
          <TooltipContent side="top" className="text-xs">{tooltipText}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    )
  }

  return badge
}

interface DataTableProps {
  entries: DataEntry[]
  onRowClick: (id: string) => void
  selectedIds?: Set<string>
  onSelectionChange?: (ids: Set<string>) => void
  onAuditorVerify?: (id: string) => void
}

export function DataTable({ entries, onRowClick, selectedIds, onSelectionChange, onAuditorVerify }: DataTableProps) {
  const isMobile = useIsMobile()
  const [sortField, setSortField] = useState<SortField>('createdAt')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  const selected = selectedIds ?? new Set<string>()

  const sortedEntries = useMemo(() => {
    const sorted = [...entries]
    sorted.sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case 'title':
          cmp = a.title.localeCompare(b.title, 'ru')
          break
        case 'createdAt':
          cmp = a.createdAt.localeCompare(b.createdAt)
          break
        case 'source':
          cmp = a.source.localeCompare(b.source)
          break
        case 'status':
          cmp = a.status.localeCompare(b.status)
          break
      }
      return sortDirection === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [entries, sortField, sortDirection])

  const handleSort = useCallback((field: SortField) => {
    setSortField((prev) => {
      if (prev === field) {
        setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
        return prev
      }
      setSortDirection('asc')
      return field
    })
  }, [])

  function toggleAll() {
    if (!onSelectionChange) return
    if (selected.size === entries.length) {
      onSelectionChange(new Set())
    } else {
      onSelectionChange(new Set(entries.map((e) => e.id)))
    }
  }

  function toggleOne(id: string) {
    if (!onSelectionChange) return
    const next = new Set(selected)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    onSelectionChange(next)
  }

  const allSelected = entries.length > 0 && selected.size === entries.length
  const someSelected = selected.size > 0 && selected.size < entries.length

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Нет данных для отображения
      </div>
    )
  }

  // Мобильный card layout
  if (isMobile) {
    return (
      <div className="space-y-2">
        {sortedEntries.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => onRowClick(entry.id)}
            className="w-full text-left p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium leading-tight line-clamp-2 flex items-center gap-1">
                {entry.metadata._bundleRootId && (
                  <FolderTree className="size-3.5 shrink-0 text-teal-500" />
                )}
                {entry.title}
              </span>
              <StatusBadge status={entry.status} />
            </div>
            <div className="flex items-center gap-2 mt-2">
              <SourceBadge source={entry.source} />
              <span className="text-xs text-muted-foreground ml-auto">{formatDate(entry.createdAt)}</span>
            </div>
          </button>
        ))}
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10">
            <Checkbox
              checked={allSelected ? true : someSelected ? 'indeterminate' : false}
              onCheckedChange={toggleAll}
              aria-label="Выделить все"
            />
          </TableHead>
          <SortableHead field="title" onSort={handleSort}>Название</SortableHead>
          <SortableHead field="createdAt" onSort={handleSort}>Дата</SortableHead>
          <SortableHead field="source" onSort={handleSort}>Источник</SortableHead>
          <TableHead>Аудитор</TableHead>
          <SortableHead field="status" onSort={handleSort}>Статус</SortableHead>
          {onAuditorVerify && <TableHead className="w-10" />}
        </TableRow>
      </TableHeader>
      <TableBody>
        {sortedEntries.map((entry) => (
          <TableRow
            key={entry.id}
            data-state={selected.has(entry.id) ? 'selected' : undefined}
            className="cursor-pointer"
          >
            <TableCell>
              <Checkbox
                checked={selected.has(entry.id)}
                onCheckedChange={() => toggleOne(entry.id)}
                aria-label={`Выделить ${entry.title}`}
                onClick={(e) => e.stopPropagation()}
              />
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-1.5">
                {entry.metadata._bundleRootId && (
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <FolderTree className="size-3.5 shrink-0 text-teal-500" />
                      </TooltipTrigger>
                      <TooltipContent>Часть комплекта</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
                <button
                  type="button"
                  className="text-left text-sm font-medium text-foreground hover:underline"
                  onClick={() => onRowClick(entry.id)}
                >
                  {entry.title}
                </button>
              </div>
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {formatDate(entry.createdAt)}
            </TableCell>
            <TableCell>
              <SourceBadge source={entry.source} />
            </TableCell>
            <TableCell>
              <AuditorBadge entry={entry} />
            </TableCell>
            <TableCell>
              <StatusBadge status={entry.status} />
            </TableCell>
            {onAuditorVerify && (
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Проверить аудитором"
                  onClick={(e) => { e.stopPropagation(); onAuditorVerify(entry.id) }}
                  className="text-violet-500 hover:text-violet-400 hover:bg-violet-500/10"
                >
                  <ShieldCheck className="size-4" />
                </Button>
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// ---- SortableHead (извлечён из render, мемоизирован) ----

const SortableHead = memo(function SortableHead({
  field,
  onSort,
  children,
}: {
  field: SortField
  onSort: (field: SortField) => void
  children: React.ReactNode
}) {
  return (
    <TableHead>
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
        onClick={() => onSort(field)}
      >
        {children}
        <ArrowUpDown className="size-3.5 text-muted-foreground" />
      </button>
    </TableHead>
  )
})
