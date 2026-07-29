/**
 * Чип «Вид топлива» в общем фильтре рабочей области (профиль fuel).
 *
 * Топливо на АЗС — не один товар: у АИ-92, АИ-95, ДТ и газа разная маржа, разный
 * спрос, разные клиенты и разные резервуары. «Выручка сети» без указания вида —
 * среднее по больнице, поэтому вид стоит рядом с периодом и областью учёта, а не
 * внутри отдельных экранов: измерение, которое меняет ответ ВЕЗДЕ, обязано жить
 * в общем фильтре и применяться сразу ко всем разрезам.
 *
 * Справочник берётся из фактических операций периода (`/fuel/transactions/filters`),
 * а не из отдельной таблицы: в списке ровно то, чем сеть торговала, без мёртвых
 * позиций из истории.
 */
import { useMemo, useState } from 'react'
import { Fuel } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useFilters } from '@/contexts/FilterContext'
import { useFuelKinds } from '@/hooks/useFuelKinds'
import { cn } from '@/lib/utils'

export function FuelKindControl() {
  const { fuelCodes, setFuelCodes, toggleFuelCode } = useFilters()
  const kinds = useFuelKinds()
  const [open, setOpen] = useState(false)
  const selected = new Set(fuelCodes)

  const label = useMemo(() => {
    if (fuelCodes.length === 0) return 'Все виды'
    const names = kinds.filter((k) => selected.has(String(k.code))).map((k) => k.name)
    if (names.length === 0) return `${fuelCodes.length} выбрано`
    return names.length <= 2 ? names.join(', ') : `${names[0]} и ещё ${names.length - 1}`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fuelCodes, kinds])

  // Нет справочника (нет операций за период или API выключен) — чип не рисуем:
  // пустой список видов выглядел бы поломкой фильтра.
  if (kinds.length === 0) return null
  const active = fuelCodes.length > 0

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Вид топлива: ${label}. Открыть выбор`}
          className={cn(
            'group flex h-11 shrink-0 items-center gap-2.5 rounded-lg border px-3.5 text-left transition-colors',
            active
              ? 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/15'
              : 'border-border bg-background/50 text-foreground hover:bg-muted/70',
          )}
        >
          <Fuel className="size-[18px] shrink-0 opacity-80" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-[11px] uppercase tracking-wide leading-tight text-muted-foreground">
              Вид топлива
            </span>
            <span className="block max-w-56 truncate text-sm font-semibold leading-tight">{label}</span>
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Нефтепродукты
          </span>
          {active && (
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
              onClick={() => setFuelCodes([])}>
              Все виды
            </Button>
          )}
        </div>
        <div className="flex flex-col gap-0.5">
          {kinds.map((k) => {
            const on = selected.has(String(k.code))
            return (
              <button key={k.code} type="button"
                onClick={() => toggleFuelCode(String(k.code))}
                className={cn(
                  'flex items-center justify-between rounded-md px-2.5 py-1.5 text-sm transition-colors',
                  on ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-muted/60',
                )}>
                <span className="truncate">{k.name}</span>
                <span className="ml-2 shrink-0 text-[11px] text-muted-foreground">{k.code}</span>
              </button>
            )
          })}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Выбор применяется ко всем экранам «Топлива»: обзору, разрезам, ценам,
          клиентам и товародвижению.
        </p>
      </PopoverContent>
    </Popover>
  )
}
