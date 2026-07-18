/**
 * Мостик «Применить ко всей области» — поднимает локальное сужение таба
 * в контур рабочей области (верхний фильтр).
 *
 * Зачем: локальные сужения живут только внутри своего таба. Если менеджер
 * отобрал станцию или регион и понял, что дальше работает именно с ними, —
 * одна кнопка переносит выбор в контур, и он применится ко всем разделам.
 * Так два уровня управления связаны, а не конкурируют (CLAUDE.md, правило 6).
 *
 * Кнопка сама прячется, когда поднимать нечего или контур уже равен выбору.
 */

import { ArrowUpToLine } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useFilters } from '@/contexts/FilterContext'

type ScopeKind = 'regions' | 'stations' | 'locations'

const KIND_LABEL: Record<ScopeKind, string> = {
  regions: 'регион',
  stations: 'станции',
  locations: 'точки',
}

export function ApplyToScope({ kind, values }: {
  kind: ScopeKind
  /** Что поднять в контур. Пусто — кнопка не показывается. */
  values: string[]
}) {
  const {
    regionIds, stationCodes, locationIds,
    setRegionIds, setStationCodes, setLocationIds,
  } = useFilters()

  const current = kind === 'regions' ? regionIds : kind === 'stations' ? stationCodes : locationIds
  const sameAsScope = values.length === current.length && values.every((v) => current.includes(v))
  if (values.length === 0 || sameAsScope) return null

  const apply = () => {
    if (kind === 'regions') setRegionIds(values)
    else if (kind === 'stations') setStationCodes(values)
    else setLocationIds(values)
  }

  return (
    <Button
      variant="outline"
      size="sm"
      className="h-7 gap-1.5 px-2 text-xs"
      onClick={apply}
      title={`Перенести выбранн${kind === 'regions' ? 'ый' : 'ые'} ${KIND_LABEL[kind]} в фильтр рабочей области — ограничение применится ко всем разделам`}
    >
      <ArrowUpToLine className="size-3.5" aria-hidden="true" />
      Применить ко всей области
    </Button>
  )
}
