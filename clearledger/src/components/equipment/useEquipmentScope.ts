/**
 * Контур рабочей области для раздела «Оборудование».
 *
 * Панель фильтров стоит над разделом целиком, значит её обещание («Приморский
 * край · ЭЗС 648») обязаны выполнять все экраны группы — парк, склады, движения.
 * До 26.08.2026 её читал только парк, а остальные молча показывали всю сеть.
 */
import { useMemo } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import { useFilters } from '@/contexts/FilterContext'
import type { EquipmentScope } from '@/services/equipmentService'

export function useEquipmentScope(): EquipmentScope {
  const { regionIds, stationCodes, locationIds } = useFilters()
  return useMemo(
    () => ({ regionIds, stationCodes: stationCodes.map(String), locationIds }),
    [regionIds, stationCodes, locationIds],
  )
}

/**
 * Все запросы раздела живут под ключом ['equipment', …], и любая запись сбрасывает
 * раздел целиком: документ меняет парк, журнал, остатки складов и разбор сразу, а
 * перечень «что задето» по каждой кнопке однажды уже разошёлся с ключами панелей.
 */
export const invalidateEquipment = (qc: QueryClient) => qc.invalidateQueries({ queryKey: ['equipment'] })

/** Весь отбор, а не страница: листает ручку до конца (для выгрузки и «отметить все»). */
export async function allPages<T>(load: (page: number) => Promise<{ items: T[]; total: number }>): Promise<T[]> {
  const out: T[] = []
  for (let page = 1; ; page++) {
    const r = await load(page)
    out.push(...r.items)
    if (!r.items.length || out.length >= r.total) return out
  }
}

/** Ключ контура для queryKey: смена контура обязана перезапрашивать данные. */
export function scopeKeyOf(s: EquipmentScope): string {
  return [s.regionIds, s.stationCodes, s.locationIds].map((x) => (x ?? []).join(',')).join('|')
}
