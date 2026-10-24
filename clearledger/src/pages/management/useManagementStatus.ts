import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { getManagementStatus, managementAvailable } from '@/services/managementService'

export function useManagementStatus() {
  const { companyId } = useCompany()
  const { user } = useAuth()
  return useQuery({
    queryKey: ['management-status', companyId, user?.id],
    queryFn: getManagementStatus,
    enabled: managementAvailable() && !!companyId && !!user?.id,
    staleTime: 30_000, gcTime: 0, retry: false, placeholderData: undefined,
  })
}
