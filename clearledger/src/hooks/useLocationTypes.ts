/**
 * Каталог типов точек активной компании. React Query: ключ = companyId,
 * рефетч при переключении компании (+ сброс qc.clear()). Возвращает встроенные
 * + кастомные типы, отсортированные с бэка по sort_order.
 */
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { loadLocationTypes } from '@/services/locationTypeService'
import { BUILTIN_LOCATION_TYPES } from '@/config/locationTypes'
import type { LocationTypeDef } from '@/types/locationType'

export function useLocationTypes(): LocationTypeDef[] {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['location-types', companyId],
    queryFn: () => loadLocationTypes(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  // Пока каталог грузится — встроенный набор (чтобы группировка/форма работали).
  return q.data ?? BUILTIN_LOCATION_TYPES
}
