import { useMemo, useState } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Checkbox } from '@/components/ui/checkbox'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/data/StatusBadge'
import { SourceBadge } from '@/components/data/SourceBadge'
import { useIsMobile } from '@/hooks/use-mobile'
import { Check, Pencil, X, ArrowUpDown } from 'lucide-react'
import { formatDate } from '@/lib/formatDate'
import type { DataEntry } from '@/types'

type SortField = 'title' | 'createdAt' | 'source' | 'status'
type SortDirection = 'asc' | 'desc'

interface InboxTableProps {
  entries: DataEntry[]
  selectedIds: Set<string>
  onSelectionChange: (ids: Set<string>) => void
  onRowClick: (id: string) => void
  onVerify: (id: string) => void
  onReject: (id: string) => void
}

export function InboxTable({
  entries,
  selectedIds,
  onSelectionChange,
  onRowClick,
  onVerify,
  onReject,
}: InboxTableProps) {
  const isMobile = useIsMobile()
  const [sortField, setSortField] = useState<SortField>('createdAt')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

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
    if (selectedIds.size === entries.length) {
      onSelectionChange(new Set())
    } else {
      onSelectionChange(new Set(entries.map((e) => e.id)))
    }
  }

  function toggleOne(id: string) {
    const next = new Set(selectedIds)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    onSelectionChange(next)
  }

  const allSelected = entries.length > 0 && selectedIds.size === entries.length
  const someSelected = selectedIds.size > 0 && selectedIds.size < entries.length

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
        Нет записей для обработки
      </div>
    )
  }

  if (isMobile) {
    return (
      <div className="space-y-2">
        {sortedEntries.map((entry) => (
          <div
            key={entry.id}
            className="p-3 rounded-lg border bg-card"
          >
            <button
              type="button"
              onClick={() => onRowClick(entry.id)}
              className="w-full text-left"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-medium leading-tight line-clamp-2">{entry.title}</span>
                <StatusBadge status={entry.status} />
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <SourceBadge source={entry.source} />
                <span className="text-xs text-muted-foreground ml-auto">{formatDate(entry.createdAt)}</span>
              </div>
            </button>
            <div className="flex items-center gap-1 mt-2 pt-2 border-t">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onVerify(entry.id)}
                className="flex-1 text-green-500 hover:text-green-400 hover:bg-green-500/10 h-9"
              >
                <Check className="size-4" />
                Принять
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onRowClick(entry.id)}
                className="flex-1 h-9"
              >
                <Pencil className="size-4" />
                Открыть
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onReject(entry.id)}
                className="flex-1 text-red-500 hover:text-red-400 hover:bg-red-500/10 h-9"
              >
                <X className="size-4" />
                Отклонить
              </Button>
            </div>
          </div>
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
          <TableHead className="text-right">Действия</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sortedEntries.map((entry) => (
          <TableRow
            key={entry.id}
            data-state={selectedIds.has(entry.id) ? 'selected' : undefined}
            className="cursor-pointer"
          >
            <TableCell>
              <Checkbox
                checked={selectedIds.has(entry.id)}
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
            <TableCell>
              <div className="flex items-center justify-end gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Верифицировать"
                  onClick={(e) => { e.stopPropagation(); onVerify(entry.id) }}
                  className="text-green-500 hover:text-green-400 hover:bg-green-500/10"
                >
                  <Check className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Открыть"
                  onClick={(e) => { e.stopPropagation(); onRowClick(entry.id) }}
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Отклонить"
                  onClick={(e) => { e.stopPropagation(); onReject(entry.id) }}
                  className="text-red-500 hover:text-red-400 hover:bg-red-500/10"
                >
                  <X className="size-4" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
