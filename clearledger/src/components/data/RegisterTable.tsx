import { useState, useMemo, memo, useCallback } from 'react'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'
import { StatusBadge } from './StatusBadge'
import { useIsMobile } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import { useUpdateEntry, useAuditorVerify } from '@/hooks/useEntries'
import { getDocumentTypeById } from '@/config/categories'
import { formatDate } from '@/lib/formatDate'
import { ArrowUpDown, ShieldCheck } from 'lucide-react'
import type { DataEntry } from '@/types'
import type { MetadataField } from '@/config/profiles'

// ---- Типы ----

type SortField = 'docNumber' | 'docDate' | 'counterparty' | 'amount' | 'title' | 'status'
type SortDirection = 'asc' | 'desc'

interface RegisterTableProps {
  entries: DataEntry[]
  onRowClick: (id: string) => void
  selectedIds?: Set<string>
  onSelectionChange?: (ids: Set<string>) => void
}

// ---- Форматирование чисел ----

const numberFormatter = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | undefined): string {
  if (!value) return ''
  const num = parseFloat(value)
  if (isNaN(num)) return value
  return numberFormatter.format(num)
}

// ---- Статус аудитора ----

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
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent side="top" className="text-xs">{tooltipText}</TooltipContent>
      </Tooltip>
    )
  }

  return badge
}

// ---- Основной компонент ----

export function RegisterTable({ entries, onRowClick, selectedIds, onSelectionChange }: RegisterTableProps) {
  const isMobile = useIsMobile()
  const { company } = useCompany()
  const updateEntry = useUpdateEntry()
  const auditorVerify = useAuditorVerify()
  const [sortField, setSortField] = useState<SortField>('docDate')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  const selected = selectedIds ?? new Set<string>()

  // Определяем динамические метаполя из профиля
  const dynamicFields = useMemo(() => {
    // Собираем все уникальные metaFields из docType записей
    const fieldsMap = new Map<string, MetadataField>()
    const fixedKeys = new Set(['docNumber', 'docDate', 'counterparty', 'amount'])

    for (const entry of entries) {
      if (!entry.docTypeId) continue
      const docType = getDocumentTypeById(company.profileId, entry.docTypeId)
      if (!docType) continue
      for (const field of docType.metadataFields) {
        if (!fixedKeys.has(field.key) && !field.key.startsWith('_') && !fieldsMap.has(field.key)) {
          fieldsMap.set(field.key, field)
        }
      }
    }

    return [...fieldsMap.values()].slice(0, 5) // макс 5 доп. колонок
  }, [entries, company.profileId])

  // Сортировка
  const sortedEntries = useMemo(() => {
    const sorted = [...entries]
    sorted.sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case 'docNumber':
          cmp = (a.metadata.docNumber ?? '').localeCompare(b.metadata.docNumber ?? '', 'ru')
          break
        case 'docDate':
          cmp = (a.metadata.docDate ?? a.createdAt).localeCompare(b.metadata.docDate ?? b.createdAt)
          break
        case 'counterparty':
          cmp = (a.metadata.counterparty ?? '').localeCompare(b.metadata.counterparty ?? '', 'ru')
          break
        case 'amount': {
          const aNum = parseFloat(a.metadata.amount ?? '0') || 0
          const bNum = parseFloat(b.metadata.amount ?? '0') || 0
          cmp = aNum - bNum
          break
        }
        case 'title':
          cmp = a.title.localeCompare(b.title, 'ru')
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

  // Агрегации для footer
  const totals = useMemo(() => {
    const sums: Record<string, number> = { amount: 0 }
    for (const field of dynamicFields) {
      if (field.type === 'number') sums[field.key] = 0
    }
    for (const entry of entries) {
      const amt = parseFloat(entry.metadata.amount ?? '0')
      if (!isNaN(amt)) sums.amount += amt
      for (const field of dynamicFields) {
        if (field.type === 'number') {
          const val = parseFloat(entry.metadata[field.key] ?? '0')
          if (!isNaN(val)) sums[field.key] += val
        }
      }
    }
    return sums
  }, [entries, dynamicFields])

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

  // Мобильный — переключаем на list-вид (register слишком широкий)
  if (isMobile) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
        Реестровый вид доступен только на десктопе
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
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
            <SortableHead field="docNumber" current={sortField} direction={sortDirection} onSort={handleSort}>
              №
            </SortableHead>
            <SortableHead field="docDate" current={sortField} direction={sortDirection} onSort={handleSort}>
              Дата док.
            </SortableHead>
            <SortableHead field="counterparty" current={sortField} direction={sortDirection} onSort={handleSort}>
              Контрагент
            </SortableHead>
            <SortableHead field="amount" current={sortField} direction={sortDirection} onSort={handleSort}>
              Сумма
            </SortableHead>
            {dynamicFields.map((field) => (
              <TableHead key={field.key}>
                <span className="text-xs">{field.label}</span>
                {field.unit && <span className="text-[10px] text-muted-foreground ml-0.5">({field.unit})</span>}
              </TableHead>
            ))}
            <TableHead>Аудитор</TableHead>
            <SortableHead field="status" current={sortField} direction={sortDirection} onSort={handleSort}>
              Статус
            </SortableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedEntries.map((entry) => (
            <RegisterRow
              key={entry.id}
              entry={entry}
              dynamicFields={dynamicFields}
              isSelected={selected.has(entry.id)}
              onToggle={() => toggleOne(entry.id)}
              onRowClick={onRowClick}
              onMetaChange={(key, value) => {
                updateEntry.mutate({
                  id: entry.id,
                  updates: { metadata: { ...entry.metadata, [key]: value } },
                })
              }}
              onAuditorVerify={() => auditorVerify.mutate(entry.id)}
            />
          ))}
        </TableBody>
        <TableFooter>
          <TableRow className="bg-muted/50 font-semibold">
            <TableCell colSpan={4} className="text-right text-sm">
              Итого:
            </TableCell>
            <TableCell className="text-right text-sm tabular-nums">
              {formatAmount(String(totals.amount))} ₽
            </TableCell>
            {dynamicFields.map((field) => (
              <TableCell key={field.key} className="text-right text-sm tabular-nums">
                {field.type === 'number' && totals[field.key]
                  ? `${formatAmount(String(totals[field.key]))}${field.unit ? ` ${field.unit}` : ''}`
                  : ''}
              </TableCell>
            ))}
            <TableCell />
            <TableCell />
            <TableCell />
          </TableRow>
        </TableFooter>
      </Table>
    </div>
  )
}

// ---- RegisterRow (мемоизированный) ----

const RegisterRow = memo(function RegisterRow({
  entry,
  dynamicFields,
  isSelected,
  onToggle,
  onRowClick,
  onMetaChange,
  onAuditorVerify,
}: {
  entry: DataEntry
  dynamicFields: MetadataField[]
  isSelected: boolean
  onToggle: () => void
  onRowClick: (id: string) => void
  onMetaChange: (key: string, value: string) => void
  onAuditorVerify: () => void
}) {
  return (
    <TableRow
      data-state={isSelected ? 'selected' : undefined}
      className="cursor-pointer"
    >
      <TableCell>
        <Checkbox
          checked={isSelected}
          onCheckedChange={onToggle}
          aria-label={`Выделить ${entry.title}`}
          onClick={(e) => e.stopPropagation()}
        />
      </TableCell>
      <TableCell>
        <InlineMetaInput
          value={entry.metadata.docNumber ?? ''}
          placeholder="—"
          onSave={(v) => onMetaChange('docNumber', v)}
        />
      </TableCell>
      <TableCell>
        <InlineMetaInput
          value={entry.metadata.docDate ?? ''}
          placeholder="—"
          onSave={(v) => onMetaChange('docDate', v)}
          isDate
        />
      </TableCell>
      <TableCell>
        <button
          type="button"
          className="text-left text-sm font-medium text-foreground hover:underline max-w-[200px] truncate block"
          onClick={() => onRowClick(entry.id)}
          title={entry.metadata.counterparty || entry.title}
        >
          {entry.metadata.counterparty || entry.title}
        </button>
      </TableCell>
      <TableCell className="text-right tabular-nums">
        <InlineMetaInput
          value={entry.metadata.amount ?? ''}
          placeholder="0.00"
          onSave={(v) => onMetaChange('amount', v)}
          isNumber
          className="text-right"
        />
      </TableCell>
      {dynamicFields.map((field) => (
        <TableCell key={field.key}>
          <InlineMetaInput
            value={entry.metadata[field.key] ?? ''}
            placeholder="—"
            onSave={(v) => onMetaChange(field.key, v)}
            isNumber={field.type === 'number'}
            className={field.type === 'number' ? 'text-right' : ''}
          />
        </TableCell>
      ))}
      <TableCell>
        <AuditorBadge entry={entry} />
      </TableCell>
      <TableCell>
        <StatusBadge status={entry.status} />
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="icon-sm"
          title="Проверить аудитором"
          onClick={(e) => { e.stopPropagation(); onAuditorVerify() }}
          className="text-violet-500 hover:text-violet-400 hover:bg-violet-500/10"
        >
          <ShieldCheck className="size-4" />
        </Button>
      </TableCell>
    </TableRow>
  )
})

// ---- InlineMetaInput — кликабельный Input для inline-редактирования ----

function InlineMetaInput({
  value,
  placeholder,
  onSave,
  isNumber,
  isDate,
  className,
}: {
  value: string
  placeholder: string
  onSave: (value: string) => void
  isNumber?: boolean
  isDate?: boolean
  className?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  if (!editing) {
    return (
      <button
        type="button"
        className={`text-xs min-w-[40px] text-left hover:bg-muted/50 rounded px-1 py-0.5 transition-colors ${
          value ? 'text-foreground' : 'text-muted-foreground'
        } ${className ?? ''}`}
        onClick={(e) => {
          e.stopPropagation()
          setDraft(value)
          setEditing(true)
        }}
      >
        {isNumber && value ? formatAmount(value) : isDate && value ? formatDate(value) : value || placeholder}
      </button>
    )
  }

  return (
    <Input
      autoFocus
      type={isDate ? 'date' : isNumber ? 'number' : 'text'}
      step={isNumber ? '0.01' : undefined}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        setEditing(false)
        if (draft !== value) onSave(draft)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          setEditing(false)
          if (draft !== value) onSave(draft)
        }
        if (e.key === 'Escape') {
          setEditing(false)
          setDraft(value)
        }
      }}
      onClick={(e) => e.stopPropagation()}
      className={`h-7 text-xs px-1 py-0 w-full min-w-[60px] ${className ?? ''}`}
    />
  )
}

// ---- SortableHead ----

const SortableHead = memo(function SortableHead({
  field,
  current,
  direction,
  onSort,
  children,
}: {
  field: SortField
  current: SortField
  direction: SortDirection
  onSort: (field: SortField) => void
  children: React.ReactNode
}) {
  const isActive = field === current

  return (
    <TableHead>
      <button
        type="button"
        className={`inline-flex items-center gap-1 hover:text-foreground transition-colors ${
          isActive ? 'text-foreground' : ''
        }`}
        onClick={() => onSort(field)}
      >
        {children}
        <ArrowUpDown className={`size-3.5 ${isActive ? 'text-foreground' : 'text-muted-foreground'}`} />
        {isActive && (
          <span className="text-[10px] text-muted-foreground">{direction === 'asc' ? '↑' : '↓'}</span>
        )}
      </button>
    </TableHead>
  )
})
