/**
 * Бейдж активного метода оценки себестоимости (МПЗ) из учётной политики
 * организации (1С → Учётная политика, GET /api/policy, поле mpz_method).
 *
 * Метод (ФИФО / по средней) критичен для корректности сумм и FIFO-себестоимости
 * в нормализации и выгрузке — активное значение показывается на виду (§5,
 * правило 3), а не остаётся скрытым (прошлый P0 «две базы себестоимости»).
 * Разные методы у разных организаций → сигнал неоднородности (янтарный).
 * Возвращает null, если политика не загружена (напр. energy-профиль без 1С).
 */
import { useQuery } from '@tanstack/react-query'
import { Layers } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { get } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'

interface PolicyRow {
  organization_name: string | null
  organization_external_ref: string | null
  mpz_method: string | null
}

export function PolicyCostingBadge({ className }: { className?: string }) {
  const { companyId } = useCompany()
  const { data } = useQuery({
    // Тот же ключ, что PolicyPage/PolicyVatBadge — общий кеш, без лишнего запроса.
    queryKey: ['onec-policies', companyId],
    queryFn: () => get<PolicyRow[]>('/api/policy', { company_id: companyId }),
    staleTime: 5 * 60_000,
  })

  const policies = (data ?? []).filter((p) => p.mpz_method)
  if (policies.length === 0) return null

  const methods = Array.from(new Set(policies.map((p) => p.mpz_method as string)))
  const mixed = methods.length > 1
  const label = mixed ? `${methods.length} метода` : methods[0]
  const details = policies
    .map((p) => `${p.organization_name ?? p.organization_external_ref ?? '—'}: ${p.mpz_method}`)
    .join('\n')

  return (
    <Badge
      variant="outline"
      title={`Метод оценки себестоимости (МПЗ), учётная политика 1С\n${details}`}
      className={`gap-1 font-normal ${
        mixed ? 'border-amber-400/50 text-amber-300/80' : 'border-zinc-600 text-zinc-400'
      } ${className ?? ''}`}
    >
      <Layers className="h-3 w-3" />
      Себестоимость: {label}
    </Badge>
  )
}
