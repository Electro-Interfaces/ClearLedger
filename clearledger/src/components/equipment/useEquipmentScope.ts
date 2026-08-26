/**
 * Контур рабочей области для раздела «Оборудование».
 *
 * Панель фильтров стоит над разделом целиком, значит её обещание («Приморский
 * край · ЭЗС 648») обязаны выполнять все экраны группы — парк, склады, движения.
 * До 26.08.2026 её читал только парк, а остальные молча показывали всю сеть.
 */
import { useMemo } from 'react'
import { useFilters } from '@/contexts/FilterContext'
import type { EquipmentScope } from '@/services/equipmentService'

export function useEquipmentScope(): EquipmentScope {
  const { regionIds, stationCodes, locationIds } = useFilters()
  return useMemo(
    () => ({ regionIds, stationCodes: stationCodes.map(String), locationIds }),
    [regionIds, stationCodes, locationIds],
  )
}

/** Ключ контура для queryKey: смена контура обязана перезапрашивать данные. */
export function scopeKeyOf(s: EquipmentScope): string {
  return [s.regionIds, s.stationCodes, s.locationIds].map((x) => (x ?? []).join(',')).join('|')
}
