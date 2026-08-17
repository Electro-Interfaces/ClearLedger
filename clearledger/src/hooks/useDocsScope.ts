import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { loadLocations, locationRegion } from '@/services/locationService'

export function useDocsScope() {
  const { companyId } = useCompany()
  const filters = useFilters()
  const locationsQ = useQuery({
    queryKey: ['locations', companyId],
    queryFn: () => loadLocations(companyId),
    enabled: !!companyId && filters.regionIds.length > 0,
    staleTime: 60_000,
  })
  const objectIds = useMemo(() => {
    const ids = new Set(filters.locationIds)
    if (filters.regionIds.length > 0 && locationsQ.data) {
      const regions = new Set(filters.regionIds)
      for (const location of locationsQ.data) {
        if (regions.has(locationRegion(location))) ids.add(location.id)
      }
    }
    return [...ids]
  }, [filters.locationIds, filters.regionIds, locationsQ.data])
  const resolving = filters.regionIds.length > 0 && locationsQ.isLoading
  const failed = filters.regionIds.length > 0 && locationsQ.isError
  const objectFilter = filters.locationIds.length > 0 || filters.regionIds.length > 0
    ? (objectIds.length > 0 ? objectIds.join(',') : '__none__')
    : undefined

  return {
    period: filters.period,
    objectIds,
    objectFilter,
    regionIds: filters.regionIds,
    locationIds: filters.locationIds,
    sourceSpecific: filters.stationCode !== 'all' || filters.stationCodes.length > 0
      || filters.fuelCodes.length > 0,
    resolving,
    failed,
    ready: !resolving && !failed,
    retry: locationsQ.refetch,
  }
}
