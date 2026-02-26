import { useState, useMemo } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Checkbox } from '@/components/ui/checkbox'
import { StatusBadge } from './StatusBadge'
import { SourceBadge } from './SourceBadge'
import { useIsMobile } from '@/hooks/use-mobile'
import { formatDate } from '@/lib/formatDate'
import type { DataEntry } from '@/types'
import { ArrowUpDown } from 'lucide-react'

type SortField = 'title' | 'createdAt' | 'source' | 'status'
type SortDirection = 'asc' | 'desc'

interface DataTableProps {
  entries: DataEntry[]
  onRowClick: (id: string) => void
  selectedIds?: Set<string>
  onSelectionChange?: (ids: Set<string>) => void
}

export function DataTable({ entries, onRowClick, selectedIds, onSelectionChange }: DataTableProps) {
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

  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

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

  function SortableHead({ field, children }: { field: SortField; children: React.ReactNode }) {
    return (
      <TableHead>
        <button
          type="button"
          className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
          onClick={() => handleSort(field)}
        >
          {children}
          <ArrowUpDown className="size-3.5 text-muted-foreground" />
        </button>
      </TableHead>
    )
  }

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
              <span className="text-sm font-medium leading-tight line-clamp-2">{entry.title}</span>
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
          <SortableHead field="title">Название</SortableHead>
          <SortableHead field="createdAt">Дата</SortableHead>
          <SortableHead field="source">Источник</SortableHead>
          <SortableHead field="status">Статус</SortableHead>
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
              <button
                type="button"
                className="text-left text-sm font-medium text-foreground hover:underline"
                onClick={() => onRowClick(entry.id)}
              >
                {entry.title}
              </button>
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {formatDate(entry.createdAt)}
            </TableCell>
            <TableCell>
              <SourceBadge source={entry.source} />
            </TableCell>
            <TableCell>
              <StatusBadge status={entry.status} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
