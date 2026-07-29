/**
 * Активные ограничения фильтра рабочей области — как удаляемые чипы (§6.2,
 * правило 3 «активные ограничения всегда видны и удаляются поштучно»).
 *
 * Заменяет неудаляемые SummaryControl-сводки: каждое ограничение можно снять
 * отдельным «×», плюс «Сбросить всё». Лейблы резолвятся из реальных источников
 * (точки — из справочника, типы данных — по профилю компании), а не показывают
 * сырые id. Период здесь не выводится — он редактируется своим контролом и «убрать»
 * его нельзя (только изменить).
 *
 * Возвращает null, когда активных ограничений нет.
 */
import { X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useFilters } from '@/contexts/FilterContext'
import { useLocations } from '@/hooks/useLocations'
import { useFuelKinds } from '@/hooks/useFuelKinds'

interface Chip {
  key: string
  label: string
  onRemove: () => void
}

export function ActiveFilterChips({ className }: { className?: string }) {
  const f = useFilters()
  const locations = useLocations()
  const kinds = useFuelKinds()

  const chips: Chip[] = []
  if (f.stationCode !== 'all') {
    chips.push({ key: `sts:${f.stationCode}`, label: `Источник STS: ${f.stationCode}`, onRemove: () => f.setStationCode('all') })
  }
  for (const id of f.locationIds) {
    const name = locations.find((l) => l.id === id)?.name ?? id
    chips.push({ key: `loc:${id}`, label: name, onRemove: () => f.toggleLocation(id) })
  }
  for (const r of f.regionIds) {
    chips.push({ key: `reg:${r}`, label: r, onRemove: () => f.toggleRegion(r) })
  }
  for (const c of f.stationCodes) {
    chips.push({ key: `st:${c}`, label: `ЭЗС ${c}`, onRemove: () => f.toggleStationCode(c) })
  }
  // Вид нефтепродукта — такое же ограничение, как область: без чипа человек видит
  // урезанные цифры и не понимает, почему выручка вдвое меньше вчерашней.
  for (const c of f.fuelCodes) {
    const name = kinds.find((k) => String(k.code) === c)?.name ?? `Код ${c}`
    chips.push({ key: `fuel:${c}`, label: `Топливо: ${name}`, onRemove: () => f.toggleFuelCode(c) })
  }
  if (chips.length === 0) return null

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className ?? ''}`}>
      {chips.map((c) => (
        <Badge
          key={c.key}
          variant="outline"
          className="gap-1 pl-2 pr-1 py-0.5 font-normal border-zinc-600 text-zinc-300"
        >
          <span className="truncate max-w-[180px]">{c.label}</span>
          <button
            type="button"
            onClick={c.onRemove}
            aria-label={`Убрать ограничение: ${c.label}`}
            className="rounded-sm p-0.5 -mr-0.5 hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <X className="h-3 w-3" />
          </button>
        </Badge>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          onClick={f.clearAll}
          className="px-1.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Сбросить всё
        </button>
      )}
    </div>
  )
}
