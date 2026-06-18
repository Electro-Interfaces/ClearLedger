/**
 * «Где работаем» для контрагента — popover с агрегатом по его договорам
 * (ось договор↔точки, Фаза 2). Данные грузятся лениво при открытии.
 */
import { useState } from 'react'
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { MapPin, Loader2, Building } from 'lucide-react'
import { useCounterpartyLocations } from '@/hooks/useReferences'

export function CounterpartyLocationsPopover({ counterpartyId }: { counterpartyId: string }) {
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useCounterpartyLocations(open ? counterpartyId : null)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 font-normal text-muted-foreground">
          <MapPin className="size-3.5" /> Где работаем
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72" align="end">
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Загрузка…
          </div>
        )}
        {data && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Где работаем</span>
              <span className="text-xs text-muted-foreground">договоров: {data.contractsCount}</span>
            </div>

            {data.scope === 'company' && (
              <Badge variant="secondary" className="gap-1">
                <Building className="size-3" /> Вся компания
              </Badge>
            )}
            {data.scope === 'locations' && (
              <div className="flex flex-wrap gap-1">
                {data.locations.map((l) => (
                  <Badge key={l.id} variant="outline" className="text-xs">{l.name}</Badge>
                ))}
              </div>
            )}
            {data.scope === 'none' && (
              <p className="text-xs text-muted-foreground">
                {data.contractsCount === 0
                  ? 'Нет договоров.'
                  : 'Ни у одного договора не задан охват.'}
              </p>
            )}

            {data.unassignedCount > 0 && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Не распределённых договоров: {data.unassignedCount}
              </p>
            )}
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
