/**
 * Справочник видов нефтепродуктов, которыми сеть торговала в периоде фильтра.
 *
 * Берётся из фактических операций (`/fuel/transactions/filters`), а не из отдельной
 * таблицы: в списке ровно то, чем торговали, без мёртвых позиций из истории.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { getFuelTxFilters } from '@/services/fuel/fuelMappingService'
import { isApiEnabled } from '@/services/apiClient'

export interface FuelKind { code: number; name: string }

export function useFuelKinds(): FuelKind[] {
  const { period } = useFilters()
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['fuel-kinds', period.from, period.to],
    queryFn: () => getFuelTxFilters(period.from, period.to),
    enabled: isApiEnabled() && company.profileId === 'fuel',
    staleTime: 10 * 60_000,
    retry: false,
  })
  return useMemo(() => (q.data?.fuels ?? []) as FuelKind[], [q.data])
}
