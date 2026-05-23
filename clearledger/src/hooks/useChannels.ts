/**
 * React Query хуки для каналов поступления.
 */

import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as svc from '@/services/channelService'

const keys = {
  all: (companyId: string) => ['channels', companyId] as const,
  stats: (companyId: string) => ['channel-stats', companyId] as const,
}

export function useChannels() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.all(companyId),
    queryFn: () => svc.getChannels(companyId),
    refetchInterval: 30_000,
  })
}

export function useChannelStats() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.stats(companyId),
    queryFn: () => svc.getChannelStats(companyId),
    refetchInterval: 30_000,
  })
}
