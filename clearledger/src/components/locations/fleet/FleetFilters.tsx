/**
 * Панель отбора парка: быстрые пилюли «требуют внимания» + поиск +
 * мультиселект-фильтры + чипы активных + «Очистить».
 */
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Search, X, Layers, Activity, CircleDot, MapPin, Building2, Radio,
  CircleSlash, Wrench, AlertTriangle, Unlink, Link as LinkIcon, Cog, WifiOff, PowerOff,
} from 'lucide-react'
import { MultiSelectFilter } from './MultiSelectFilter'
import {
  EMPTY_LOCATION_FILTERS, activeFilterCount, activeAttentionKey,
  ATTENTION_META, type AttentionKey,
  type LocationFilters, type FilterOptions, type FleetStats,
} from './locationFleetService'
import type { LocationStatus } from '@/types/location'

const ATTENTION_ICON: Record<AttentionKey, typeof Wrench> = {
  // Иконки для отдельных категорий CPO «Нет связи»/«Отключены» (см. ATTENTION_META).
  // ATTENTION_KEYS ниже не трогаем — состав фильтр-чипов остаётся прежним.
  noLink: WifiOff, disabled: PowerOff,
  notWorking: CircleSlash, onRepair: Wrench, linkConflict: AlertTriangle, noBinding: Unlink,
}
const ATTENTION_KEYS: AttentionKey[] = ['notWorking', 'onRepair', 'linkConflict', 'noBinding']

export function FleetFilters({
  filters, onChange, options, stats, filteredCount, totalCount, onAttention,
}: {
  filters: LocationFilters
  onChange: (next: LocationFilters) => void
  options: FilterOptions
  stats: FleetStats
  filteredCount: number
  totalCount: number
  /** Клик по пилюле «требуют внимания» — срез (replace). */
  onAttention: (key: AttentionKey) => void
}) {
  const set = (patch: Partial<LocationFilters>) => onChange({ ...filters, ...patch })
  const activeCount = activeFilterCount(filters)
  const activeKey = activeAttentionKey(filters)

  // Карта value→label для подписи чипов.
  const labelOf = (opts: { value: string; label: string }[], v: string) =>
    opts.find((o) => o.value === v)?.label ?? v

  // Чипы активных фильтров (массивы + привязка).
  const chips: { id: string; label: string; remove: () => void }[] = []
  filters.types.forEach((v) => chips.push({ id: `t-${v}`, label: labelOf(options.types, v), remove: () => set({ types: filters.types.filter((x) => x !== v) }) }))
  filters.lifeStatuses.forEach((v) => chips.push({ id: `l-${v}`, label: labelOf(options.lifeStatuses, v), remove: () => set({ lifeStatuses: filters.lifeStatuses.filter((x) => x !== v) }) }))
  filters.opStatuses.forEach((v) => chips.push({ id: `o-${v}`, label: labelOf(options.opStatuses, v), remove: () => set({ opStatuses: filters.opStatuses.filter((x) => x !== v) }) }))
  filters.regions.forEach((v) => chips.push({ id: `r-${v}`, label: v, remove: () => set({ regions: filters.regions.filter((x) => x !== v) }) }))
  filters.owners.forEach((v) => chips.push({ id: `w-${v}`, label: v, remove: () => set({ owners: filters.owners.filter((x) => x !== v) }) }))
  filters.linkStatuses.forEach((v) => chips.push({ id: `h-${v}`, label: labelOf(options.linkStatuses, v), remove: () => set({ linkStatuses: filters.linkStatuses.filter((x) => x !== v) }) }))
  if (filters.sourceBinding !== 'any') {
    chips.push({
      id: 'sb', label: filters.sourceBinding === 'bound' ? 'С привязкой' : 'Без привязки',
      remove: () => set({ sourceBinding: 'any' }),
    })
  }
  if (filters.serviceKind !== 'any') {
    chips.push({
      id: 'sk', label: filters.serviceKind === 'service' ? 'Служебные' : 'Рабочие',
      remove: () => set({ serviceKind: 'any' }),
    })
  }

  return (
    <div className="space-y-3">
      {/* Пилюли «требуют внимания» — переключатели: повторное нажатие снимает срез
          (просил Якушевич 27.08.2026). Включённая залита плотнее и обведена, иначе
          по виду не отличить нажатую от ненажатой. */}
      <div className="flex flex-wrap gap-2">
        {ATTENTION_KEYS.map((k) => {
          const Icon = ATTENTION_ICON[k]
          const count = stats.attention[k]
          if (count === 0) return null
          const on = activeKey === k
          return (
            <button
              key={k}
              onClick={() => (on ? onChange(EMPTY_LOCATION_FILTERS) : onAttention(k))}
              aria-pressed={on}
              title={on ? 'Нажмите ещё раз, чтобы снять отбор' : undefined}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                on
                  ? 'border-amber-500 bg-amber-500/30 text-amber-900 ring-1 ring-amber-500/40 hover:bg-amber-500/40 dark:text-amber-200'
                  : 'border-amber-400/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-400'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {ATTENTION_META[k].label}
              <Badge variant="secondary" className="h-4 min-w-4 justify-center bg-amber-500/20 px-1 text-[10px] tabular-nums text-amber-700 dark:text-amber-300">
                {count}
              </Badge>
              {on && <X className="h-3 w-3 opacity-70" />}
            </button>
          )
        })}
      </div>

      {/* Поиск + мультиселекты */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={filters.q} onChange={(e) => set({ q: e.target.value })}
            placeholder="Поиск: номер, серийник, название, город, владелец…" className="h-9 pl-8" />
        </div>
        {options.types.length > 1 && (
          <MultiSelectFilter label="Тип" icon={Layers} options={options.types}
            selected={filters.types} onChange={(v) => set({ types: v })} />
        )}
        {options.lifeStatuses.length > 1 && (
          <MultiSelectFilter label="Статус" icon={CircleDot} options={options.lifeStatuses}
            selected={filters.lifeStatuses} onChange={(v) => set({ lifeStatuses: v as LocationStatus[] })} width="w-[180px]" />
        )}
        {options.opStatuses.length > 1 && (
          <MultiSelectFilter label="Работа" icon={Activity} options={options.opStatuses}
            selected={filters.opStatuses} onChange={(v) => set({ opStatuses: v })} width="w-[190px]" />
        )}
        {options.regions.length > 0 && (
          <MultiSelectFilter label="Регион" icon={MapPin} options={options.regions}
            selected={filters.regions} onChange={(v) => set({ regions: v })} width="w-[240px]" />
        )}
        {options.owners.length > 1 && (
          <MultiSelectFilter label="Владелец" icon={Building2} options={options.owners}
            selected={filters.owners} onChange={(v) => set({ owners: v })} width="w-[240px]" />
        )}
        {options.linkStatuses.length > 0 && (
          <MultiSelectFilter label="Связка HubEx" icon={Radio} options={options.linkStatuses}
            selected={filters.linkStatuses} onChange={(v) => set({ linkStatuses: v })} width="w-[200px]" />
        )}
        <Select value={filters.sourceBinding} onValueChange={(v) => set({ sourceBinding: v as LocationFilters['sourceBinding'] })}>
          <SelectTrigger className="h-9 w-[170px]">
            <LinkIcon className="h-3.5 w-3.5 text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Привязка: любая</SelectItem>
            <SelectItem value="bound">С привязкой</SelectItem>
            <SelectItem value="unbound">Без привязки</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filters.serviceKind} onValueChange={(v) => set({ serviceKind: v as LocationFilters['serviceKind'] })}>
          <SelectTrigger className="h-9 w-[180px]">
            <Cog className="h-3.5 w-3.5 text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Назначение: любое</SelectItem>
            <SelectItem value="regular">Рабочие</SelectItem>
            <SelectItem value="service">Служебные</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Чипы активных */}
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {chips.map((c) => (
            <Badge key={c.id} variant="secondary" className="gap-1 pr-1 font-normal">
              {c.label}
              <button onClick={c.remove} className="rounded-sm hover:bg-muted-foreground/20" aria-label={`Убрать ${c.label}`}>
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* «Очистить» стоит здесь, а не в ряду селекторов. В ряду она была последней,
          а сами селекторы условные — на узком срезе их пропадает до четырёх из шести,
          и кнопка уезжала через пол-экрана («перескакивает», Якушевич 27.08.2026).
          Строка «Найдено» одна и не переносится, поэтому место постоянное — и кнопка
          оказалась рядом с числом, которое возвращает к полному. */}
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>Найдено: {filteredCount}{filteredCount !== totalCount && ` из ${totalCount}`}</span>
        {activeCount > 0 && (
          <Button variant="ghost" size="sm" className="h-7 shrink-0 px-2 text-xs"
            onClick={() => onChange(EMPTY_LOCATION_FILTERS)}>
            <X className="mr-1 h-3.5 w-3.5" /> Очистить
          </Button>
        )}
      </div>
    </div>
  )
}
