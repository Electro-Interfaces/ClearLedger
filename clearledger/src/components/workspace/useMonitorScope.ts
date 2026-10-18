import { useMemo } from 'react'
import { useFilters } from '@/contexts/FilterContext'

export function useMonitorScope() {
  const { locationIds, stationCodes } = useFilters()
  return useMemo(() => ({
    locationIds: locationIds.join('|') || undefined,
    stationCodes: stationCodes.map(String).join('|') || undefined,
  }), [locationIds, stationCodes])
}
