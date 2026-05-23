import { useState, useEffect } from 'react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Search, X, Layers } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { DOC_PURPOSE_CONFIG } from '@/config/statuses'
import type { DocPurpose } from '@/types'

export interface InboxFilters {
  search: string
  source: string
  status: string
  categoryId: string
  docPurpose: string
  dateFrom: string
  dateTo: string
}

export const defaultInboxFilters: InboxFilters = {
  search: '',
  source: 'all',
  status: 'all',
  categoryId: 'all',
  docPurpose: 'all',
  dateFrom: '',
  dateTo: '',
}

export type GroupBy = 'none' | 'source' | 'category' | 'date'

const sourceOptions: { value: string; label: string }[] = [
  { value: 'all', label: 'Все источники' },
  { value: 'upload', label: 'Загрузка' },
  { value: 'photo', label: 'Фото' },
  { value: 'manual', label: 'Ручной' },
  { value: 'api', label: 'API' },
  { value: 'email', label: 'Email' },
  { value: 'oneC', label: '1С' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'paste', label: 'Вставка' },
]

interface InboxToolbarProps {
  filters: InboxFilters
  onFiltersChange: (filters: InboxFilters) => void
  groupBy: GroupBy
  onGroupByChange: (groupBy: GroupBy) => void
}

export function InboxToolbar({ filters, onFiltersChange, groupBy, onGroupByChange }: InboxToolbarProps) {
  const { effectiveCategories } = useCompany()
  const [localSearch, setLocalSearch] = useState(filters.search)

  // Debounce поиска — 300мс
  useEffect(() => {
    const timer = setTimeout(() => {
      if (localSearch !== filters.search) {
        onFiltersChange({ ...filters, search: localSearch })
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [localSearch])

  // Синхронизация при внешнем сбросе
  useEffect(() => {
    if (filters.search !== localSearch) {
      setLocalSearch(filters.search)
    }
  }, [filters.search])

  const activeCount = [
    filters.source !== 'all',
    filters.status !== 'all',
    filters.categoryId !== 'all',
    filters.docPurpose !== 'all',
    filters.dateFrom !== '',
    filters.dateTo !== '',
    filters.search !== '',
  ].filter(Boolean).length

  const handleClear = () => {
    setLocalSearch('')
    onFiltersChange(defaultInboxFilters)
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Поиск с иконкой и debounce */}
      <div className="relative max-w-xs flex-1 min-w-[200px]">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по названию..."
          value={localSearch}
          onChange={(e) => setLocalSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Источник — все 9 */}
      <Select
        value={filters.source}
        onValueChange={(v) => onFiltersChange({ ...filters, source: v })}
      >
        <SelectTrigger className="w-[150px]">
          <SelectValue placeholder="Источник" />
        </SelectTrigger>
        <SelectContent>
          {sourceOptions.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Статус */}
      <Select
        value={filters.status}
        onValueChange={(v) => onFiltersChange({ ...filters, status: v })}
      >
        <SelectTrigger className="w-[150px]">
          <SelectValue placeholder="Статус" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все статусы</SelectItem>
          <SelectItem value="new">Новый</SelectItem>
          <SelectItem value="recognized">Распознан</SelectItem>
        </SelectContent>
      </Select>

      {/* Категория */}
      <Select
        value={filters.categoryId}
        onValueChange={(v) => onFiltersChange({ ...filters, categoryId: v })}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Категория" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все категории</SelectItem>
          {effectiveCategories.map((cat) => (
            <SelectItem key={cat.id} value={cat.id}>
              {cat.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Назначение */}
      <Select
        value={filters.docPurpose}
        onValueChange={(v) => onFiltersChange({ ...filters, docPurpose: v })}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Назначение" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все назначения</SelectItem>
          {(Object.entries(DOC_PURPOSE_CONFIG) as [DocPurpose, { label: string }][]).map(([key, cfg]) => (
            <SelectItem key={key} value={key}>
              {cfg.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Дата от */}
      <Input
        type="date"
        value={filters.dateFrom}
        onChange={(e) => onFiltersChange({ ...filters, dateFrom: e.target.value })}
        className="w-[150px]"
        placeholder="Дата от"
      />

      {/* Дата до */}
      <Input
        type="date"
        value={filters.dateTo}
        onChange={(e) => onFiltersChange({ ...filters, dateTo: e.target.value })}
        className="w-[150px]"
        placeholder="Дата до"
      />

      {/* Группировка */}
      <Select
        value={groupBy}
        onValueChange={(v) => onGroupByChange(v as GroupBy)}
      >
        <SelectTrigger className="w-[170px]">
          <Layers className="size-4 mr-1" />
          <SelectValue placeholder="Группировка" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">Без группировки</SelectItem>
          <SelectItem value="source">По источнику</SelectItem>
          <SelectItem value="category">По категории</SelectItem>
          <SelectItem value="date">По дате</SelectItem>
        </SelectContent>
      </Select>

      {/* Очистить */}
      {activeCount > 0 && (
        <Button variant="ghost" size="sm" onClick={handleClear} className="gap-1.5">
          <X className="size-4" />
          Очистить
          <Badge variant="secondary" className="ml-1 px-1.5 py-0 text-xs">
            {activeCount}
          </Badge>
        </Button>
      )}
    </div>
  )
}
