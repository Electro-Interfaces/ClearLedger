import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getStoreAccessPolicy } from '@/services/businessAccessService'

export function useStoreAccessPolicy() {
  const { companyId } = useCompany()
  const query = useQuery({
    queryKey: ['store-access-policy', companyId],
    queryFn: getStoreAccessPolicy,
    staleTime: 60_000,
  })
  return query.data
}

export function useCentralCommercialWrite() {
  return useStoreAccessPolicy()?.capabilities.central_commercial_write === true
}
