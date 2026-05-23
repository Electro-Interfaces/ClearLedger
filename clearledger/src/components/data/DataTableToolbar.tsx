import { Search, Download } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import type { FilterState } from '@/types'

interface DataTableToolbarProps {
  filters: FilterState
  onFiltersChange: (filters: FilterState) => void
}

export function DataTableToolbar({ filters, onFiltersChange }: DataTableToolbarProps) {
  function updateFilter<K extends keyof FilterState>(key: K, value: FilterState[K]) {
    onFiltersChange({ ...filters, [key]: value })
  }

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по названию..."
          value={filters.search}
          onChange={(e) => updateFilter('search', e.target.value)}
          className="pl-9"
        />
      </div>

      <Select
        value={filters.status}
        onValueChange={(value) => updateFilter('status', value as FilterState['status'])}
      >
        <SelectTrigger className="w-[150px]">
          <SelectValue placeholder="Статус" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все</SelectItem>
          <SelectItem value="new">Новый</SelectItem>
          <SelectItem value="recognized">Распознан</SelectItem>
          <SelectItem value="verified">Проверен</SelectItem>
          <SelectItem value="transferred">Передан</SelectItem>
          <SelectItem value="error">Ошибка</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.source}
        onValueChange={(value) => updateFilter('source', value)}
      >
        <SelectTrigger className="w-[150px]">
          <SelectValue placeholder="Источник" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все</SelectItem>
          <SelectItem value="upload">Загрузка</SelectItem>
          <SelectItem value="photo">Фото</SelectItem>
          <SelectItem value="manual">Ручной</SelectItem>
          <SelectItem value="api">API</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.docPurpose ?? 'all'}
        onValueChange={(value) => updateFilter('docPurpose', value as FilterState['docPurpose'])}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Назначение" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все назначения</SelectItem>
          <SelectItem value="accounting">Бухгалтерский</SelectItem>
          <SelectItem value="reference">Справочный</SelectItem>
          <SelectItem value="context">Контекстный</SelectItem>
          <SelectItem value="archive">Архивный</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.syncStatus ?? 'all'}
        onValueChange={(value) => updateFilter('syncStatus', value as FilterState['syncStatus'])}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Синхр." />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Все статусы 1С</SelectItem>
          <SelectItem value="not_applicable">Не требуется</SelectItem>
          <SelectItem value="pending">Ожидает</SelectItem>
          <SelectItem value="exported">Выгружен</SelectItem>
          <SelectItem value="confirmed">Подтверждён</SelectItem>
          <SelectItem value="rejected_1c">Отклонён 1С</SelectItem>
        </SelectContent>
      </Select>

      <Button variant="outline" size="default">
        <Download />
        Экспорт
      </Button>
    </div>
  )
}
