/**
 * Пикер номенклатуры 1С (combobox с поиском). Выбор привязывает GUID + имя из
 * синхронизированного каталога 1С — наименование становится согласованным с
 * бухгалтерией. Записи без external_ref (заведены вручную) недоступны для выбора.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronsUpDown, Check } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command'
import { cn } from '@/lib/utils'
import { getNomenclature } from '@/services/referenceService'

export function NomenclaturePicker({ companyId, valueRef, valueName, placeholder = 'Выбрать номенклатуру 1С…', onPick }: {
  companyId: string
  valueRef?: string | null
  valueName?: string | null
  placeholder?: string
  onPick: (ref: string, name: string) => void
}) {
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['ref-nomenclature', companyId],
    enabled: open && !!companyId,
    queryFn: () => getNomenclature(companyId),
  })
  const options = data ?? []
  const label = valueName || valueRef || placeholder

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" role="combobox" aria-expanded={open}
          className="h-7 text-xs w-full justify-between font-normal">
          <span className={cn('truncate', valueRef ? '' : 'text-muted-foreground')}>{label}</span>
          <ChevronsUpDown className="h-3 w-3 opacity-50 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command filter={(value, search) => value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0}>
          <CommandInput placeholder="Поиск по названию/коду…" className="text-xs" />
          <CommandList>
            {isLoading ? (
              <div className="py-6 text-center text-xs text-muted-foreground">Загрузка каталога 1С…</div>
            ) : (
              <>
                <CommandEmpty className="py-6 text-center text-xs text-muted-foreground">
                  Ничего не найдено. Синхронизируйте номенклатуру 1С.
                </CommandEmpty>
                <CommandGroup>
                  {options.map((o, i) => (
                    <CommandItem
                      key={(o.externalRef ?? 'noref') + i}
                      value={`${o.name} ${o.code ?? ''}`}
                      disabled={!o.externalRef}
                      onSelect={() => { if (o.externalRef) { onPick(o.externalRef, o.name); setOpen(false) } }}
                      className="text-xs"
                    >
                      <Check className={cn('mr-2 h-3 w-3', valueRef === o.externalRef ? 'opacity-100' : 'opacity-0')} />
                      <span className="truncate">{o.name}</span>
                      {o.code && <span className="ml-auto text-[10px] text-muted-foreground font-mono">{o.code}</span>}
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
