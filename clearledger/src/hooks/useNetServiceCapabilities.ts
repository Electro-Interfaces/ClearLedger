/**
 * Доступность линий Сервисного центра — для подключаемости раздела (скрытие
 * группы/подпунктов, когда источники линий не настроены). Серверный ответ
 * /netservice/capabilities (hubex = токен настроен И есть точки с hubexAssetId).
 */
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getCapabilities, type NetCapabilities } from '@/services/netServiceService'

const EMPTY: NetCapabilities = { hubex: false, line1: false, line2: false, assetsLinked: 0 }

export function useNetServiceCapabilities(): NetCapabilities {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['netservice-capabilities', companyId],
    queryFn: () => getCapabilities(companyId),
    enabled: !!companyId,
    staleTime: 300_000,
  })
  return q.data ?? EMPTY
}

/** Доступна ли хоть одна линия (раздел вообще показывать?). */
export function useNetServiceEnabled(): boolean {
  const c = useNetServiceCapabilities()
  return c.hubex || c.line1 || c.line2
}
