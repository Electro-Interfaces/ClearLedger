import { useState, useMemo } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Checkbox } from '@/components/ui/checkbox'
import { StatusBadge } from './StatusBadge'
import { SourceBadge } from './SourceBadge'
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

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function DataTable({ entries, onRowClick, selectedIds, onSelectionChange }: DataTableProps) {
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
