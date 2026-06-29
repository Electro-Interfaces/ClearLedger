/**
 * Резолвер канонического наименования топлива из единого справочника
 * (fuel_mappings, согласован с 1С). fuel_code → каноническое имя; при отсутствии
 * — фолбэк на исходное (STS) имя. Используется для единого отображения в
 * журналах/деталях/бейджах.
 */
import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { isApiEnabled } from '@/services/apiClient'
import { getFuelTypes } from '@/services/fuel/fuelMappingService'

export function useFuelName(): (code?: number | null, fallback?: string | null) => string {
  const { data } = useQuery({
    queryKey: ['fuel-types-map'],
    queryFn: getFuelTypes,
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const map = useMemo(() => {
    const m = new Map<number, string>()
    for (const f of data ?? []) if (f.fuel_name) m.set(f.service_code, f.fuel_name)
    return m
  }, [data])
  return useCallback(
    (code?: number | null, fallback?: string | null) =>
      (code != null ? map.get(code) : undefined) || fallback || '',
    [map],
  )
}
