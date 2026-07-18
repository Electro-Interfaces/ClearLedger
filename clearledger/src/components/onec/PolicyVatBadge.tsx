/**
 * Бейдж активного НДС-профиля из учётной политики организации
 * (1С → Учётная политика, GET /api/policy).
 *
 * Ставка НДС критична для корректности проводок при выгрузке в 1С, поэтому её
 * активное значение показывается прямо на поверхностях выгрузки, а не заперто на
 * отдельной странице «Учётная политика» (стандарт управления сложностью §5,
 * правило 3 — «критичное для корректности всегда на виду»).
 *
 * Разные ставки у разных организаций — это сигнал неоднородности: бейдж
 * подсвечивается янтарным. Возвращает null, если политика не загружена
 * (напр. energy-профиль без 1С) — тогда бейдж просто не показывается.
 */
import { useQuery } from '@tanstack/react-query'
import { Landmark } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { get } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'

interface PolicyRow {
  organization_name: string | null
  organization_external_ref: string | null
  vat_rate: string | null
}

export function PolicyVatBadge({ className }: { className?: string }) {
  const { companyId } = useCompany()
  const { data } = useQuery({
    // Тот же ключ, что и на PolicyPage — переиспользуем кеш, без лишнего запроса.
    queryKey: ['onec-policies', companyId],
    queryFn: () => get<PolicyRow[]>('/api/policy', { company_id: companyId }),
    staleTime: 5 * 60_000,
  })

  const policies = (data ?? []).filter((p) => p.vat_rate)
  if (policies.length === 0) return null

  const rates = Array.from(new Set(policies.map((p) => p.vat_rate as string)))
  const mixed = rates.length > 1
  const label = mixed ? `${rates.length} профиля` : rates[0]
  const details = policies
    .map((p) => `${p.organization_name ?? p.organization_external_ref ?? '—'}: ${p.vat_rate}`)
    .join('\n')

  return (
    <Badge
      variant="outline"
      title={`НДС-профиль (учётная политика 1С)\n${details}`}
      className={`gap-1 font-normal ${
        mixed ? 'border-amber-400/50 text-amber-300/80' : 'border-zinc-600 text-zinc-400'
      } ${className ?? ''}`}
    >
      <Landmark className="h-3 w-3" />
      НДС-профиль: {label}
    </Badge>
  )
}
