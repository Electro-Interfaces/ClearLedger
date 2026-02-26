import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export interface InboxFilters {
  search: string
  source: string
  status: string
}

interface InboxToolbarProps {
  filters: InboxFilters
  onFiltersChange: (filters: InboxFilters) => void
}

export function InboxToolbar({ filters, onFiltersChange }: InboxToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Input
        placeholder="Поиск по названию..."
        value={filters.search}
        onChange={(e) => onFiltersChange({ ...filters, search: e.target.value })}
        className="max-w-xs"
      />

      <Select
        value={filters.source}
        onValueChange={(v) => onFiltersChange({ ...filters, source: v })}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Источник" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все источники</SelectItem>
          <SelectItem value="upload">Загрузка</SelectItem>
          <SelectItem value="photo">Фото</SelectItem>
          <SelectItem value="manual">Ручной</SelectItem>
          <SelectItem value="api">API</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.status}
        onValueChange={(v) => onFiltersChange({ ...filters, status: v })}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Статус" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все статусы</SelectItem>
          <SelectItem value="new">Новый</SelectItem>
          <SelectItem value="recognized">Распознан</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}
