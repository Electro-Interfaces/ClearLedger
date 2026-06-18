/**
 * «Договоры» точки — popover со списком договоров (адресные + общекомпанейские)
 * и их контрагентами (ось договор↔точки, Фаза 2). Данные грузятся лениво.
 */
import { useState } from 'react'
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { FileSignature, Loader2, Building } from 'lucide-react'
import { useLocationContracts } from '@/hooks/useReferences'

export function LocationContractsPopover({ locationId }: { locationId: string }) {
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useLocationContracts(open ? locationId : null)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 font-normal text-muted-foreground">
          <FileSignature className="size-3.5" /> Договоры
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Загрузка…
          </div>
        )}
        {data && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Договоры точки</span>
              <span className="text-xs text-muted-foreground">{data.contracts.length}</span>
            </div>
            {data.contracts.length === 0 && (
              <p className="text-xs text-muted-foreground">Нет связанных договоров.</p>
            )}
            <div className="space-y-1.5 max-h-72 overflow-y-auto">
              {data.contracts.map((c) => (
                <div key={c.id}
                  className="flex items-start justify-between gap-2 text-sm border-b border-border/40 pb-1.5 last:border-0">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{c.number}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {c.counterpartyName || c.counterpartyId}
                      {c.kind && <span> · {c.kind}</span>}
                    </div>
                  </div>
                  {c.companyWide ? (
                    <Badge variant="secondary" className="gap-1 shrink-0 text-[10px]">
                      <Building className="size-2.5" /> вся компания
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="shrink-0 text-[10px]">адресный</Badge>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
