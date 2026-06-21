/**
 * Мультиселект-фильтр (Popover + Command + поиск по опциям).
 * Триггер — кнопка с подписью и бейджем-счётчиком выбранных.
 */
import { useState, type ComponentType } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import {
  Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem,
} from '@/components/ui/command'
import { cn } from '@/lib/utils'

export interface FilterOption { value: string; label: string }

export function MultiSelectFilter({
  label, options, selected, onChange, icon: Icon, width = 'w-[220px]',
}: {
  label: string
  options: FilterOption[]
  selected: string[]
  onChange: (next: string[]) => void
  icon?: ComponentType<{ className?: string }>
  width?: string
}) {
  const [open, setOpen] = useState(false)
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-9 gap-1.5">
          {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
          {label}
          {selected.length > 0 && (
            <Badge variant="secondary" className="ml-0.5 h-5 px-1.5 text-[10px] tabular-nums">{selected.length}</Badge>
          )}
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className={cn('p-0', width)} align="start">
        <Command>
          <CommandInput placeholder={`Поиск: ${label.toLowerCase()}…`} />
          <CommandList>
            <CommandEmpty>Ничего не найдено</CommandEmpty>
            <CommandGroup>
              {options.map((o) => {
                const on = selected.includes(o.value)
                return (
                  <CommandItem key={o.value} value={o.label} onSelect={() => toggle(o.value)}>
                    <Check className={cn('mr-2 h-4 w-4 shrink-0', on ? 'opacity-100' : 'opacity-0')} />
                    <span className="flex-1 truncate">{o.label}</span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
          {selected.length > 0 && (
            <div className="border-t border-border/50 p-1">
              <Button variant="ghost" size="sm" className="h-8 w-full text-xs" onClick={() => onChange([])}>
                Сбросить ({selected.length})
              </Button>
            </div>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  )
}
