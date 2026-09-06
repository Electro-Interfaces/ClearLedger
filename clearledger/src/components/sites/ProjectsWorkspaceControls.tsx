import { Settings2, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PROJECT_OBJECT_TYPES } from '@/services/sitesService'
import { PROJECT_COLUMNS, PROJECT_WORKSPACE_DEFAULTS, type ProjectWorkspacePreferences } from './projectWorkspacePreferences'

export function ProjectsWorkspaceControls({ value, onChange, kinds }: {
  value: ProjectWorkspacePreferences; onChange: (patch: Partial<ProjectWorkspacePreferences>) => void
  kinds: { key: string; label: string }[]
}) {
  return (
    <div className="flex flex-wrap items-end gap-2" aria-label="Рабочая область проектов">
      {([
        ['kind', 'Вид работ', kinds],
        ['placeKind', 'Тип объекта', PROJECT_OBJECT_TYPES.map((label) => ({ key: label.toLocaleLowerCase('ru'), label }))],
      ] as const).map(([key, label, options]) => (
        <div key={key} className="min-w-0 flex-1 sm:flex-none">
          <label htmlFor={`filter-${key}`} className="mb-1 block text-xs text-muted-foreground">{label}</label>
          <Select value={value[key] || '__all__'} onValueChange={(next) => onChange({ [key]: next === '__all__' ? '' : next })}>
            <SelectTrigger id={`filter-${key}`} className="h-11 w-full rounded-lg max-sm:text-xs sm:w-56"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">{key === 'kind' ? 'Все виды работ' : 'Все типы объектов'}</SelectItem>
              {options.map((option) => <SelectItem key={option.key} value={option.key}>{option.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      ))}
      {(value.kind || value.placeKind) && <Button variant="ghost" className="h-11" onClick={() => onChange({ kind: '', placeKind: '' })}>
        <RotateCcw className="size-4" /> Сбросить отбор
      </Button>}
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="outline" className="h-11 max-sm:w-full sm:ml-auto"><Settings2 className="size-4" />Рабочая область</Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-72 max-w-[calc(100vw-2rem)] space-y-3">
          <div><p className="text-sm font-medium">Столбцы реестра</p>
            <p className="mt-1 text-xs text-muted-foreground">Ваш выбор сохраняется в этом браузере для текущего пространства.</p></div>
          {PROJECT_COLUMNS.map(([key, label]) => (
            <label key={key} className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox checked={value.columns.includes(key)} onCheckedChange={(checked) => onChange({
                columns: checked ? [...value.columns, key] : value.columns.filter((column) => column !== key),
              })} />{label}
            </label>
          ))}
          <Button variant="ghost" size="sm" onClick={() => onChange({ columns: PROJECT_WORKSPACE_DEFAULTS.columns })}>Все столбцы</Button>
        </PopoverContent>
      </Popover>
    </div>
  )
}
