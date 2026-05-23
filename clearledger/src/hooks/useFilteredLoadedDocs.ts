/**
 * Хук — отфильтрованные загруженные документы с учётом глобальных
 * фильтров шапки (Компания/Точки/Типы документов).
 *
 * Все потребители GetAllLoadedDocs() должны идти через этот хук —
 * иначе глобальный фильтр работает только на части UI.
 */

import { useMemo } from 'react'
import { getAllLoadedDocs, type LoadedDocument } from '@/services/channelSyncService'
import { getLocations } from '@/services/locationService'
import { useFilters } from '@/contexts/FilterContext'

interface UseFilteredLoadedDocsResult {
  docs: LoadedDocument[]
  /** Сколько было до фильтра — для UI «Показано X из Y» */
  totalBeforeFilter: number
  /** Активен ли хоть один глобальный фильтр */
  hasActiveFilters: boolean
}

export function useFilteredLoadedDocs(): UseFilteredLoadedDocsResult {
  const { locationIds, docTypeIds } = useFilters()

  // Маппинг locationId → код станции (через справочник)
  const stationCodes = useMemo<Set<number> | null>(() => {
    if (locationIds.length === 0) return null
    const idToLoc = new Map(getLocations().map((l) => [l.id, l]))
    const codes = new Set<number>()
    for (const id of locationIds) {
      const code = Number(idToLoc.get(id)?.code)
      if (Number.isFinite(code) && code > 0) codes.add(code)
    }
    return codes.size > 0 ? codes : null
  }, [locationIds])

  const docTypeSet = useMemo<Set<string> | null>(() => {
    return docTypeIds.length > 0 ? new Set(docTypeIds) : null
  }, [docTypeIds])

  return useMemo(() => {
    const all = getAllLoadedDocs()
    const totalBeforeFilter = all.length

    if (!stationCodes && !docTypeSet) {
      return { docs: all, totalBeforeFilter, hasActiveFilters: false }
    }

    const docs = all.filter((d) => {
      if (stationCodes && !stationCodes.has(d.stationId)) return false
      if (docTypeSet && !docTypeSet.has(d.docType)) return false
      return true
    })

    return { docs, totalBeforeFilter, hasActiveFilters: true }
  }, [stationCodes, docTypeSet])
}
