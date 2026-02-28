import { useMemo, useState } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Checkbox } from '@/components/ui/checkbox'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/data/StatusBadge'
import { SourceBadge } from '@/components/data/SourceBadge'
import { useIsMobile } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import { DOC_PURPOSE_CONFIG } from '@/config/statuses'
import { Check, Pencil, X, ArrowUpDown, ShieldCheck } from 'lucide-react'
import { formatDate } from '@/lib/formatDate'
import type { DataEntry, DocPurpose } from '@/types'

type SortField = 'title' | 'createdAt' | 'source' | 'status' | 'categoryId'
type SortDirection = 'asc' | 'desc'

const AUDITOR_STATUS_MAP: Record<string, { label: string; className: string }> = {
  approved: { label: 'OK', className: 'border-green-500 text-green-500' },
  needs_review: { label: 'Проверить', className: 'border-yellow-500 text-yellow-500' },
  rejected: { label: 'Отклонён', className: 'border-red-500 text-red-500' },
}

function SortableHead({
  field,
  children,
  onSort,
}: {
  field: SortField
  children: React.ReactNode
  onSort: (field: SortField) => void
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
}

/** Бейдж результата аудитора */
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
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent side="top" className="text-xs">{tooltipText}</TooltipContent>
      </Tooltip>
    )
  }

  return badge
}

interface InboxTableProps {
  entries: DataEntry[]
  selectedIds: Set<string>
  onSelectionChange: (ids: Set<string>) => void
  onRowClick: (id: string) => void
  onVerify: (id: string) => void
  onReject: (id: string) => void
  onAuditorVerify?: (id: string) => void
  onCategoryChange?: (id: string, categoryId: string, subcategoryId: string) => void
  onDocPurposeChange?: (id: string, docPurpose: string) => void
}

export function InboxTable({
  entries,
  selectedIds,
  onSelectionChange,
  onRowClick,
  onVerify,
  onReject,
  onAuditorVerify,
  onCategoryChange,
  onDocPurposeChange,
}: InboxTableProps) {
  const isMobile = useIsMobile()
  const { effectiveCategories } = useCompany()
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
        case 'categoryId':
          cmp = a.categoryId.localeCompare(b.categoryId)
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

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Нет записей для обработки
      </div>
    )
  }

  function getFirstSubcategoryId(categoryId: string): string {
    const cat = effectiveCategories.find((c) => c.id === categoryId)
    return cat?.subcategories?.[0]?.id ?? ''
  }

  function getCategoryLabel(categoryId: string): string {
    const cat = effectiveCategories.find((c) => c.id === categoryId)
    return cat?.label ?? categoryId
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
                <div className="flex items-center gap-1">
                  <AuditorBadge entry={entry} />
                  <StatusBadge status={entry.status} />
                </div>
              </div>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <SourceBadge source={entry.source} />
                {entry.categoryId && (
                  <Badge variant="outline" className="text-xs">
                    {getCategoryLabel(entry.categoryId)}
                  </Badge>
                )}
                {entry.docPurpose && (
                  <Badge variant="secondary" className="text-xs">
                    {DOC_PURPOSE_CONFIG[entry.docPurpose]?.label ?? entry.docPurpose}
                  </Badge>
                )}
                <span className="text-xs text-muted-foreground ml-auto">{formatDate(entry.createdAt)}</span>
              </div>
            </button>
            <div className="flex items-center gap-1 mt-2 pt-2 border-t">
              {onAuditorVerify && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onAuditorVerify(entry.id)}
                  className="flex-1 text-violet-500 hover:text-violet-400 hover:bg-violet-500/10 h-9"
                >
                  <ShieldCheck className="size-4" />
                  Аудитор
                </Button>
              )}
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
          <SortableHead field="title" onSort={handleSort}>Название</SortableHead>
          <SortableHead field="createdAt" onSort={handleSort}>Дата</SortableHead>
          <SortableHead field="source" onSort={handleSort}>Источник</SortableHead>
          <SortableHead field="categoryId" onSort={handleSort}>Категория</SortableHead>
          <TableHead>Назначение</TableHead>
          <TableHead>Аудитор</TableHead>
          <SortableHead field="status" onSort={handleSort}>Статус</SortableHead>
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
            {/* Категория — inline Select */}
            <TableCell>
              <Select
                value={entry.categoryId || 'none'}
                onValueChange={(v) => {
                  if (onCategoryChange && v !== 'none') {
                    onCategoryChange(entry.id, v, getFirstSubcategoryId(v))
                  }
                }}
              >
                <SelectTrigger
                  className="h-7 text-xs w-[130px]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  {effectiveCategories.map((cat) => (
                    <SelectItem key={cat.id} value={cat.id} className="text-xs">
                      {cat.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </TableCell>
            {/* Назначение — inline Select */}
            <TableCell>
              <Select
                value={entry.docPurpose || 'accounting'}
                onValueChange={(v) => {
                  if (onDocPurposeChange) {
                    onDocPurposeChange(entry.id, v)
                  }
                }}
              >
                <SelectTrigger
                  className="h-7 text-xs w-[130px]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  {(Object.entries(DOC_PURPOSE_CONFIG) as [DocPurpose, { label: string }][]).map(([key, cfg]) => (
                    <SelectItem key={key} value={key} className="text-xs">
                      {cfg.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </TableCell>
            {/* Аудитор — бейдж результата */}
            <TableCell>
              <AuditorBadge entry={entry} />
            </TableCell>
            <TableCell>
              <StatusBadge status={entry.status} />
            </TableCell>
            <TableCell>
              <div className="flex items-center justify-end gap-1">
                {onAuditorVerify && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="Проверить аудитором"
                    onClick={(e) => { e.stopPropagation(); onAuditorVerify(entry.id) }}
                    className="text-violet-500 hover:text-violet-400 hover:bg-violet-500/10"
                  >
                    <ShieldCheck className="size-4" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Принять"
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
