/**
 * Выбор из списка с поиском.
 *
 * Обычный `<Select>` годится, пока вариантов десяток. На пилоте объектов
 * пространства семьсот — их выпадающий список превращается в бесконечную
 * прокрутку, где нужную АЗС ищут глазами. Поэтому везде, где список длиннее
 * пары десятков, стоит этот пикер: набрал «208» — увидел строку.
 *
 * Механика взята у пикера номенклатуры 1С (`fuel/NomenclaturePicker`), чтобы
 * поиск в пространстве работал одинаково: те же Popover + Command, тот же
 * порядок, та же клавиатура.
 */
import { useState } from 'react'
import { PartyChip } from '@/components/chat/PartyBadge'
import { Check, ChevronsUpDown, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command'
import { cn } from '@/lib/utils'

export interface PickItem {
  id: string
  name: string
  /** Вторая строка: адрес объекта, должность человека — то, что различает тёзок. */
  hint?: string | null
  /** Кто это пространству: у внешнего рядом с именем стоит знак. */
  party?: 'internal' | 'partner' | 'vendor' | null
}

export function SearchPicker({
  items, value, onChange, placeholder, emptyLabel, searchPlaceholder,
  className, disabled, loading, allowClear = true, width = 'w-[280px]',
}: {
  items: PickItem[]
  value: string
  onChange: (id: string) => void
  /** Что показать, когда ничего не выбрано («Без объекта», «Не назначен»). */
  placeholder: string
  /** Подпись строки «сбросить выбор» в самом списке. */
  emptyLabel?: string
  searchPlaceholder?: string
  className?: string
  disabled?: boolean
  loading?: boolean
  allowClear?: boolean
  width?: string
}) {
  const [open, setOpen] = useState(false)
  const picked = items.find((i) => i.id === value)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" role="combobox" aria-expanded={open}
          disabled={disabled}
          className={cn('h-8 w-full justify-between px-2.5 text-xs font-normal', className)}>
          <span className={cn('truncate', picked ? '' : 'text-muted-foreground')}>
            {picked ? picked.name : placeholder}
          </span>
          <ChevronsUpDown className="h-3 w-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className={cn('p-0', width)} align="start">
        {/* Ищем и по названию, и по подсказке: АЗС находят по адресу не реже,
            чем по номеру. */}
        <Command filter={(v, search) =>
          v.toLowerCase().includes(search.toLowerCase()) ? 1 : 0}>
          <CommandInput className="text-xs"
            placeholder={searchPlaceholder ?? 'Поиск…'} />
          <CommandList>
            {loading ? (
              <div className="py-6 text-center text-xs text-muted-foreground">Загрузка…</div>
            ) : (
              <>
                <CommandEmpty className="py-6 text-center text-xs text-muted-foreground">
                  Ничего не нашлось
                </CommandEmpty>
                <CommandGroup>
                  {allowClear && (
                    <CommandItem value="__clear__" className="text-xs text-muted-foreground"
                      onSelect={() => { onChange(''); setOpen(false) }}>
                      <X className="mr-2 h-3 w-3" />
                      {emptyLabel ?? placeholder}
                    </CommandItem>
                  )}
                  {items.map((i) => (
                    <CommandItem key={i.id} value={`${i.name} ${i.hint ?? ''}`}
                      className="text-xs"
                      onSelect={() => { onChange(i.id); setOpen(false) }}>
                      <Check className={cn('mr-2 h-3 w-3',
                        i.id === value ? 'opacity-100' : 'opacity-0')} />
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5 truncate">
                          <PartyChip party={i.party} />
                          {i.name}
                        </span>
                        {i.hint && (
                          <span className="block truncate text-[11px] text-muted-foreground">
                            {i.hint}
                          </span>
                        )}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

export default SearchPicker
