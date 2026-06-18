/**
 * «Договоры» по элементу разреза (обратная навигация граней, Фаза 3): показывает
 * договоры, ограниченные данной номенклатурой/каналом. Данные грузятся лениво.
 */
import { useState } from 'react'
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { FileSignature, Loader2 } from 'lucide-react'
import { useDimensionContracts } from '@/hooks/useReferences'

export function DimensionContractsPopover({
  dimType,
  dimRef,
  title = 'Договоры',
}: {
  dimType: string
  dimRef: string
  title?: string
}) {
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useDimensionContracts(dimType, open ? dimRef : null)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 font-normal text-muted-foreground">
          <FileSignature className="size-3.5" /> {title}
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
              <span className="text-sm font-medium">Ограниченные договоры</span>
              <span className="text-xs text-muted-foreground">{data.length}</span>
            </div>
            {data.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Нет договоров, ограниченных этим элементом разреза.
              </p>
            )}
            <div className="space-y-1.5 max-h-72 overflow-y-auto">
              {data.map((c) => (
                <div key={c.id}
                  className="flex items-start justify-between gap-2 text-sm border-b border-border/40 pb-1.5 last:border-0">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{c.number}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {c.date || '—'}{c.kind && <span> · {c.kind}</span>}
                    </div>
                  </div>
                  {c.scopeType === 'company' && (
                    <Badge variant="secondary" className="shrink-0 text-[10px]">вся компания</Badge>
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
