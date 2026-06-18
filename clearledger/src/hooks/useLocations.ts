/**
 * Точки обслуживания активной компании. React Query: ключ = companyId, поэтому
 * при переключении компании список перезапрашивается (и сбрасывается qc.clear()).
 * loadLocations попутно наполняет localStorage-зеркало, чтобы синхронные
 * getLocations()/getStsStationsFromLocations() в других местах тоже видели
 * данные активной компании.
 */
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { loadLocations } from '@/services/locationService'
import type { ServiceLocation } from '@/types/location'

export function useLocations(): ServiceLocation[] {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['locations', companyId],
    queryFn: () => loadLocations(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  return q.data ?? []
}
