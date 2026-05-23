import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { GroupMode, SortConfig, SortColumn, SortDirection } from './raw-panel-types'

const GROUP_OPTIONS: { value: GroupMode; label: string; description: string }[] = [
  { value: 'default', label: 'По умолчанию', description: 'Объект \u2192 Год \u2192 Месяц \u2192 Тип' },
  { value: 'object', label: 'По объектам', description: 'Объект \u2192 Документы' },
  { value: 'category', label: 'По категориям', description: 'Категория \u2192 Тип \u2192 Документы' },
  { value: 'date', label: 'По дате', description: 'Год \u2192 Месяц \u2192 Документы' },
  { value: 'status', label: 'По статусу', description: 'Статус \u2192 Документы' },
  { value: 'source', label: 'По источнику', description: 'Источник \u2192 Документы' },
  { value: 'flat', label: 'Плоский список', description: 'Без группировки' },
]

const SORT_COLUMNS: { value: SortColumn; label: string }[] = [
  { value: 'date', label: 'Дата' },
  { value: 'name', label: 'Название' },
  { value: 'status', label: 'Статус' },
]

const SORT_DIRS: { value: SortDirection; label: string }[] = [
  { value: 'desc', label: 'По убыванию' },
  { value: 'asc', label: 'По возрастанию' },
]

interface Props {
  groupMode: GroupMode
  onGroupModeChange: (mode: GroupMode) => void
  sortConfig: SortConfig
  onSortChange: (config: SortConfig) => void
}

export function RawPanelGroupTab({ groupMode, onGroupModeChange, sortConfig, onSortChange }: Props) {
  return (
    <div className="space-y-6">
      {/* Grouping */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-3 block">
          Группировать по
        </Label>
        <div className="space-y-1">
          {GROUP_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex items-start gap-3 p-2.5 rounded-lg cursor-pointer transition-colors ${
                groupMode === opt.value ? 'bg-primary/10' : 'hover:bg-accent/40'
              }`}
            >
              <input
                type="radio"
                name="groupMode"
                value={opt.value}
                checked={groupMode === opt.value}
                onChange={() => onGroupModeChange(opt.value)}
                className="mt-0.5 accent-primary"
              />
              <div>
                <div className="text-sm font-medium">{opt.label}</div>
                <div className="text-xs text-muted-foreground">{opt.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Sorting */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-2 block">
          Сортировка
        </Label>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Поле</Label>
            <Select
              value={sortConfig.column}
              onValueChange={(v) => onSortChange({ ...sortConfig, column: v as SortColumn })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {SORT_COLUMNS.map((c) => (
                  <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Направление</Label>
            <Select
              value={sortConfig.direction}
              onValueChange={(v) => onSortChange({ ...sortConfig, direction: v as SortDirection })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {SORT_DIRS.map((d) => (
                  <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>
  )
}
